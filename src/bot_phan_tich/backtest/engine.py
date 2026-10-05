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

Dinh gia moi phien theo gia dong cua; ngay ma khong co phien (tam ngung giao
dich, thieu du lieu) dung gia dong cua GAN NHAT, khong phai gia vao lenh.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field

import numpy as np
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
    entry_row: int = 0  # hang vao lenh trong du lieu CUA MA (dem so phien nam giu)
    last_close: float = 0.0  # gia dong cua gan nhat, dung de dinh gia

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


@dataclass
class _Bars:
    """Gia mot ma o dang mang; row[i] = hang cua phien calendar[i] (-1 = khong co phien)."""

    row: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    floor_locked: np.ndarray


@dataclass
class PreparedPrices:
    """Gia da chuan bi san cho run(): lich giao dich chung + mang gia tung ma.

    Chuan bi mot lan, dung lai cho hang tram lan chay (walk-forward, do nhay
    chi phi) - tranh tinh lai floor_locked va lich moi lan.
    """

    calendar: list[pd.Timestamp]
    bars: dict[str, _Bars]


def prepare_prices(
    price_frames: dict[str, pd.DataFrame], exchanges: dict[str, str] | None = None
) -> PreparedPrices:
    """`exchanges`: ma -> san (HOSE/HNX/UPCOM) de lay bien do gia san. None = doc
    tu du lieu symbols trong kho (data/market_store.load_symbols); ma khong co
    trong do mac dinh HOSE (bien do hep nhat)."""
    frames = {sym: f.sort_values("time") for sym, f in price_frames.items() if not f.empty}
    if not frames:
        return PreparedPrices([], {})
    times = np.unique(np.concatenate([f["time"].to_numpy() for f in frames.values()]))
    calendar = list(pd.DatetimeIndex(times))
    exchange_of = _resolve_exchanges(list(frames), exchanges)

    bars = {}
    for sym, frame in frames.items():
        row = np.full(len(times), -1, dtype=np.int64)
        row[np.searchsorted(times, frame["time"].to_numpy())] = np.arange(len(frame))
        bars[str(sym).upper()] = _Bars(
            row=row,
            open=frame["open"].to_numpy(dtype=float),
            high=frame["high"].to_numpy(dtype=float),
            low=frame["low"].to_numpy(dtype=float),
            close=frame["close"].to_numpy(dtype=float),
            volume=frame["volume"].to_numpy(dtype=float),
            floor_locked=constraints.floor_locked(frame, exchange_of[sym]).to_numpy(),
        )
    return PreparedPrices(calendar, bars)


def run(
    price_frames: dict[str, pd.DataFrame] | PreparedPrices,
    signals: pd.DataFrame,
    initial_capital: float = 100_000_000,
    max_participation: float = 0.10,
    max_hold_days: int = 20,
    exchanges: dict[str, str] | None = None,
    fee_rate: float | None = None,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    close_at_end: bool = False,
) -> BacktestResult:
    """signals: DataFrame gom cot symbol, time, stop_loss, target (tin hieu mua).

    `price_frames`: dict ma -> OHLCV, hoac PreparedPrices (prepare_prices) da
    chuan bi san. `exchanges`: xem prepare_prices (bo qua neu da chuan bi).
    `fee_rate`: phi hai chieu, None = costs.fee_rate trong config.
    `start`/`end`: chi chay tren cac phien trong [start, end) - duong von va
    moi chi so chi phu thuoc khoang nay; gia truoc `start` van dung de xac
    dinh gia tham chieu/gia san. Tin hieu truoc `start` bi bo qua.
    `close_at_end`: dong moi vi the o gia dong cua phien cuoi (co tru phi,
    thue) va khong mo vi the moi trong `settlement_days` phien cuoi (de vi the
    nao cung ban duoc theo T+2) - dung cho tung lat walk-forward.
    """
    settings = get_settings()
    fee = settings.get("costs.fee_rate", 0.0025) if fee_rate is None else fee_rate
    tax = settings.get("costs.sell_tax_rate", 0.001)
    risk_per_trade = settings.get("risk.risk_per_trade", 0.01)
    max_weight = settings.get("risk.max_weight_per_symbol", 0.15)
    settle_days = constraints.settlement_days()

    prices = (
        price_frames if isinstance(price_frames, PreparedPrices)
        else prepare_prices(price_frames, exchanges)
    )
    calendar = prices.calendar
    first = 0 if start is None else bisect_left(calendar, pd.Timestamp(start))
    stop = len(calendar) if end is None else bisect_left(calendar, pd.Timestamp(end))
    if stop <= first:
        return BacktestResult(pd.Series(dtype=float), pd.DataFrame(), initial_capital)
    last_entry_session = stop - 1 - settle_days if close_at_end else stop - 1

    by_time: dict[pd.Timestamp, list[dict]] = {}
    for signal in signals.to_dict("records"):
        by_time.setdefault(pd.Timestamp(signal["time"]), []).append(signal)

    cash = initial_capital
    open_trades: list[Trade] = []
    closed: list[dict] = []
    equity_points: list[float] = []

    def _close(trade: Trade, price: float, reason: str) -> None:
        nonlocal cash
        trade.exit_time = today
        trade.exit_price = price
        trade.exit_reason = reason
        cash += trade.shares * price * (1 - fee / 2 - tax)
        closed.append(trade.result(fee, tax))
        open_trades.remove(trade)

    for i in range(first, stop):
        today = calendar[i]
        # ---------- 1. cap nhat cac vi the dang mo ----------
        for trade in list(open_trades):
            bars = prices.bars[trade.symbol]
            r = bars.row[i]
            if r < 0:
                continue
            if not constraints.is_settled(trade.entry_session, i, settle_days):
                continue  # chua ve tai khoan (T+2): khong ban duoc du cham stop/target
            locked = bool(bars.floor_locked[r])
            exit_price = exit_reason = None

            if trade.pending_exit is not None:
                # Lenh ban tu phien ket san truoc: ban o gia mo cua neu het ket.
                if not locked:
                    _close(trade, float(bars.open[r]), f"{trade.pending_exit} (tre do ket san)")
                continue

            # Gap: mo cua da vuot qua stop/target thi lenh cho (stop/limit) khop
            # o gia mo cua - gia tot nhat CON co, khong phai muc da dat.
            bar_open = float(bars.open[r])
            if bar_open <= trade.stop_loss:
                exit_price, exit_reason = bar_open, "Mo cua duoi diem dung lo (gap)"
            elif bar_open >= trade.target:
                exit_price, exit_reason = bar_open, "Mo cua tren muc tieu (gap)"
            elif bars.low[r] <= trade.stop_loss:
                exit_price, exit_reason = trade.stop_loss, "Cham diem dung lo"
            elif bars.high[r] >= trade.target:
                exit_price, exit_reason = trade.target, "Cham muc tieu"
            elif r - trade.entry_row + 1 >= max_hold_days:
                exit_price, exit_reason = float(bars.close[r]), "Het rao chan doc"

            if exit_price is not None:
                if locked:
                    trade.pending_exit = exit_reason  # trang ben mua: doi sang phien sau
                else:
                    _close(trade, exit_price, exit_reason)

        # ---------- 2. mo vi the moi tu tin hieu phien TRUOC ----------
        if first < i <= last_entry_session:
            for signal in by_time.get(calendar[i - 1], []):
                symbol = str(signal["symbol"]).upper()
                bars = prices.bars.get(symbol)
                if bars is None or bars.row[i] < 0:
                    continue
                if any(t.symbol == symbol for t in open_trades):
                    continue

                r = int(bars.row[i])
                entry = float(bars.open[r])
                stop_loss = float(signal["stop_loss"])
                sizing = position_size(cash, entry, stop_loss, risk_per_trade=risk_per_trade,
                                       max_weight=max_weight)
                if sizing.shares <= 0:
                    continue

                max_shares = int(bars.volume[r] * max_participation // 100 * 100)
                shares = min(sizing.shares, max_shares)
                if shares <= 0:
                    continue

                cost = shares * entry * (1 + fee / 2)
                if cost > cash:
                    continue
                cash -= cost
                open_trades.append(
                    Trade(symbol, today, entry, shares, stop_loss, float(signal["target"]),
                          entry_session=i, entry_row=r, last_close=entry)
                )

        # ---------- 3. dinh gia danh muc ----------
        for trade in open_trades:
            bars = prices.bars[trade.symbol]
            if bars.row[i] >= 0:
                trade.last_close = float(bars.close[bars.row[i]])
        if close_at_end and i == stop - 1:
            for trade in list(open_trades):
                _close(trade, trade.last_close, "Dong vi the cuoi giai doan")
        holdings = sum(trade.shares * trade.last_close for trade in open_trades)
        equity_points.append(cash + holdings)

    equity = pd.Series(equity_points, index=pd.DatetimeIndex(calendar[first:stop]), dtype=float)
    log.debug("Backtest: %d lenh dong, von cuoi ky %.0f", len(closed), equity.iloc[-1])
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
