"""Khung backtest theo su kien.

Cac nguyen tac chong tu lua, deu da duoc cai o day:
  1. Vao lenh o gia MO CUA phien ke tiep, khong phai gia dong cua phien co tin hieu.
  2. Tru day du phi hai chieu va thue thu nhap ca nhan khi ban.
  3. Gioi han khoi luong khop khong vuot qua max_participation lan khoi luong phien
     de phan anh truot gia.
  4. Chu ky thanh toan T+2 (costs.settlement_days): co phieu mua o phien T chi
     ban duoc tu phien T+2, dem theo PHIEN trong lich giao dich
     (risk/constraints.is_settled) - stop/target cham truoc do deu bi bo qua.
  5. Gap: neu gia mo cua da nam duoi stop (hoac tren target) thi khop o gia mo
     cua, khong phai o muc stop/target. Neu ca stop va target cung bi cham
     trong phien ma khong gap, gia dinh BI QUAN la stop cham truoc.
  6. Ket gia san: phien dong cua o gia san va low == gia san (bien do theo san
     cua tung ma, risk/constraints.floor_locked) coi nhu KHONG ban duoc - lenh
     ban (stop/target/het han) doi sang phien ke tiep, khop o gia mo cua phien
     dau tien khong con ket san.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..config import get_settings
from ..data import market_store
from ..logging_conf import get_logger
from ..risk import constraints
from ..risk.sizing import position_size, r_multiple

log = get_logger(__name__)


@dataclass
class Trade:
    symbol: str
    entry_time: pd.Timestamp
    entry_price: float
    shares: int
    stop_loss: float
    target: float
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    entry_session: int = 0  # chi so phien vao lenh trong lich giao dich (cho T+2)
    pending_exit: str | None = None  # ly do ban da kich hoat nhung bi ket san

    @property
    def closed(self) -> bool:
        return self.exit_price is not None

    def result(self, fee: float, tax: float) -> dict:
        gross_in = self.entry_price * self.shares
        gross_out = (self.exit_price or self.entry_price) * self.shares
        costs = (gross_in + gross_out) * fee / 2 + gross_out * tax
        net = gross_out - gross_in - costs
        return {
            "symbol": self.symbol,
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "entry": self.entry_price,
            "exit": self.exit_price,
            "shares": self.shares,
            "pnl": net,
            "return": net / gross_in if gross_in else 0.0,
            "r_multiple": r_multiple(
                self.entry_price, self.exit_price or self.entry_price, self.stop_loss
            ),
            "reason": self.exit_reason,
        }


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: pd.DataFrame
    initial_capital: float
    logs: list[str] = field(default_factory=list)


def run(
    price_frames: dict[str, pd.DataFrame],
    signals: pd.DataFrame,
    initial_capital: float = 100_000_000,
    max_participation: float = 0.10,
    max_hold_days: int = 20,
    exchanges: dict[str, str] | None = None,
) -> BacktestResult:
    """signals: DataFrame gom cot symbol, time, stop_loss, target (tin hieu mua).

    `exchanges`: ma -> san (HOSE/HNX/UPCOM) de lay bien do gia san. None = doc
    tu du lieu symbols trong kho (data/market_store.load_symbols); ma khong co
    trong do mac dinh HOSE (bien do hep nhat).
    """
    settings = get_settings()
    fee = settings.get("costs.fee_rate", 0.0025)
    tax = settings.get("costs.sell_tax_rate", 0.001)

    calendar = sorted({t for frame in price_frames.values() for t in frame["time"]})
    if not calendar:
        return BacktestResult(pd.Series(dtype=float), pd.DataFrame(), initial_capital)

    exchange_of = _resolve_exchanges(list(price_frames), exchanges)
    indexed = {}
    for sym, frame in price_frames.items():
        frame = frame.sort_values("time")
        frame = frame.assign(_floor_locked=constraints.floor_locked(frame, exchange_of[sym]))
        indexed[sym] = frame.set_index("time")
    by_time: dict[pd.Timestamp, list] = {}
    for _, row in signals.iterrows():
        by_time.setdefault(pd.Timestamp(row["time"]), []).append(row)

    cash = initial_capital
    open_trades: list[Trade] = []
    closed: list[dict] = []
    equity_points: list[tuple[pd.Timestamp, float]] = []

    def _close(trade: Trade, price: float, reason: str) -> None:
        nonlocal cash
        trade.exit_time = today
        trade.exit_price = price
        trade.exit_reason = reason
        cash += trade.shares * price * (1 - fee / 2 - tax)
        closed.append(trade.result(fee, tax))
        open_trades.remove(trade)

    for i, today in enumerate(calendar):
        # ---------- 1. cap nhat cac vi the dang mo ----------
        for trade in list(open_trades):
            frame = indexed.get(trade.symbol)
            if frame is None or today not in frame.index:
                continue
            if not constraints.is_settled(trade.entry_session, i):
                continue  # chua ve tai khoan (T+2): khong ban duoc du cham stop/target
            bar = frame.loc[today]
            locked = bool(bar["_floor_locked"])
            exit_price = exit_reason = None

            if trade.pending_exit is not None:
                # Lenh ban tu phien ket san truoc: ban o gia mo cua neu het ket.
                if not locked:
                    _close(trade, float(bar["open"]), f"{trade.pending_exit} (tre do ket san)")
                continue

            # Gap: mo cua da vuot qua stop/target thi lenh cho (stop/limit) khop
            # o gia mo cua - gia tot nhat CON co, khong phai muc da dat.
            bar_open = float(bar["open"])
            if bar_open <= trade.stop_loss:
                exit_price, exit_reason = bar_open, "Mo cua duoi diem dung lo (gap)"
            elif bar_open >= trade.target:
                exit_price, exit_reason = bar_open, "Mo cua tren muc tieu (gap)"
            elif float(bar["low"]) <= trade.stop_loss:
                exit_price, exit_reason = trade.stop_loss, "Cham diem dung lo"
            elif float(bar["high"]) >= trade.target:
                exit_price, exit_reason = trade.target, "Cham muc tieu"
            else:
                held = len(frame.loc[trade.entry_time:today])
                if held >= max_hold_days:
                    exit_price, exit_reason = float(bar["close"]), "Het rao chan doc"

            if exit_price is not None:
                if locked:
                    trade.pending_exit = exit_reason  # trang ben mua: doi sang phien sau
                else:
                    _close(trade, exit_price, exit_reason)

        # ---------- 2. mo vi the moi tu tin hieu phien TRUOC ----------
        if i > 0:
            for signal in by_time.get(calendar[i - 1], []):
                symbol = str(signal["symbol"]).upper()
                frame = indexed.get(symbol)
                if frame is None or today not in frame.index:
                    continue
                if any(t.symbol == symbol for t in open_trades):
                    continue

                bar = frame.loc[today]
                entry = float(bar["open"])
                sizing = position_size(cash, entry, float(signal["stop_loss"]))
                if sizing.shares <= 0:
                    continue

                max_shares = int(float(bar["volume"]) * max_participation // 100 * 100)
                shares = min(sizing.shares, max_shares)
                if shares <= 0:
                    continue

                cost = shares * entry * (1 + fee / 2)
                if cost > cash:
                    continue
                cash -= cost
                open_trades.append(
                    Trade(symbol, today, entry, shares, float(signal["stop_loss"]),
                          float(signal["target"]), entry_session=i)
                )

        # ---------- 3. dinh gia danh muc ----------
        holdings = 0.0
        for trade in open_trades:
            frame = indexed.get(trade.symbol)
            if frame is not None and today in frame.index:
                holdings += trade.shares * float(frame.loc[today, "close"])
            else:
                holdings += trade.shares * trade.entry_price
        equity_points.append((today, cash + holdings))

    equity = pd.Series(dict(equity_points)).sort_index()
    final_equity = equity.iloc[-1] if len(equity) else 0
    log.info("Backtest: %d lenh dong, von cuoi ky %.0f", len(closed), final_equity)
    return BacktestResult(equity, pd.DataFrame(closed), initial_capital)


def _resolve_exchanges(
    symbols: list[str], exchanges: dict[str, str] | None
) -> dict[str, str]:
    if exchanges is None:
        try:
            meta = market_store.load_symbols()
            exchanges = dict(
                zip(
                    meta["symbol"].astype(str).str.upper(),
                    meta["exchange"].astype(str).str.upper(),
                    strict=True,
                )
            )
        except Exception as exc:  # kho chua co / thieu cot: van chay, coi la HOSE
            log.debug("Khong doc duoc san cua ma (%s) - mac dinh HOSE", exc)
            exchanges = {}
    upper = {str(k).upper(): str(v).upper() for k, v in exchanges.items()}
    return {sym: upper.get(str(sym).upper(), "HOSE") for sym in symbols}
