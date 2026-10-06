"""Kiem dinh walk-forward: toi uu tham so tren cua so TRAIN, ap NGUYEN tham so
do len cua so TEST ke tiep, lan cua so, roi ghep cac doan von out-of-sample.

    |---- train 12 thang ----|-- test 3 thang --|
              |---- train 12 thang ----|-- test 3 thang --|
                        |---- train 12 thang ----|-- test 3 thang --|

Moi lat:
  1. Chay MOI bo tham so trong luoi (DEFAULT_GRID) tren cua so train, chon bo
     co Sharpe cao nhat (hoa -> bo dung truoc trong luoi). Chi dung du lieu
     train - cua so test chua tung duoc nhin thay.
  2. Ap bo tham so do len cua so test, von dau lat = von cuoi lat truoc.
  3. Chi so cua lat tinh tren DUNG duong von cua lat (engine.run(start, end)),
     khong phai tren ca lich.
  4. Vu tru co phieu chon THEO THOI DIEM: universe_fn(as_of) voi as_of = ngay
     truoc khi cua so (train hoac test) bat dau - chi dung du lieu den do, ma
     chua du thanh khoan luc do khong duoc giao dich du hom nay thanh khoan.
Duong von out-of-sample ghep tu cac doan test - day la con so duy nhat duoc
bao cao nhu ket qua chien luoc. `trials` giu Sharpe train cua moi (lat, bo
tham so) va n_trials = so bo tham so da thu, dung cho Deflated Sharpe
(metrics.deflated_sharpe).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from itertools import product

import numpy as np
import pandas as pd

from ..analysis.score_history import score_history
from ..logging_conf import get_logger
from . import metrics
from .engine import PreparedPrices, prepare_prices, run
from .signals import _MIN_BARS, SIGNAL_COLUMNS, signals_from_scores

log = get_logger(__name__)

_MIN_TEST_SESSIONS = 10


@dataclass(frozen=True)
class StrategyParams:
    buy_threshold: float
    ichimoku_preset: str
    max_hold_days: int

    def label(self) -> str:
        return f"MUA>={self.buy_threshold:g}, {self.ichimoku_preset}, giu<={self.max_hold_days}"


DEFAULT_GRID: tuple[StrategyParams, ...] = tuple(
    StrategyParams(threshold, preset, hold)
    for threshold, preset, hold in product(
        (50, 60, 70), ("goc_nhat_6ngay", "hieu_chinh_5ngay"), (10, 20)
    )
)


class SignalCache:
    """Tin hieu MUA lich su cho tung bo tham so.

    score_history() (phan ton thoi gian) chi phu thuoc preset Ichimoku nen
    duoc tinh mot lan cho moi (ma, preset); nguong MUA ap len sau.
    """

    def __init__(self, price_frames: dict[str, pd.DataFrame], min_gap: int = 5):
        self._frames = {s: f for s, f in price_frames.items() if len(f) >= _MIN_BARS}
        self._min_gap = min_gap
        self._scores: dict[str, dict[str, pd.DataFrame]] = {}
        self._signals: dict[tuple[str, float], pd.DataFrame] = {}

    def scores(self, preset: str) -> dict[str, pd.DataFrame]:
        if preset not in self._scores:
            self._scores[preset] = {
                sym: score_history(frame, ichimoku_preset=preset)
                for sym, frame in self._frames.items()
            }
        return self._scores[preset]

    def __call__(self, params: StrategyParams) -> pd.DataFrame:
        key = (params.ichimoku_preset, float(params.buy_threshold))
        if key not in self._signals:
            parts = [
                signals_from_scores(table, sym, params.buy_threshold, self._min_gap)
                for sym, table in self.scores(params.ichimoku_preset).items()
            ]
            parts = [p for p in parts if not p.empty]
            self._signals[key] = (
                pd.concat(parts, ignore_index=True) if parts
                else pd.DataFrame(columns=SIGNAL_COLUMNS)
            )
        return self._signals[key]


@dataclass
class WalkForwardResult:
    equity: pd.Series          # duong von out-of-sample ghep tu cac lat test
    trades: pd.DataFrame       # lenh out-of-sample
    slices: pd.DataFrame       # moi lat: khoang train/test, tham so chon, chi so test
    trials: pd.DataFrame       # moi (lat, bo tham so): Sharpe train
    grid: tuple[StrategyParams, ...]

    @property
    def n_trials(self) -> int:
        """So bo tham so da thu - n_trials cho Deflated Sharpe."""
        return len(self.grid)

    def trial_sharpe_variance(self) -> float:
        """Phuong sai Sharpe THEO NGAY giua cac bo tham so tren cung cua so
        train, trung binh qua cac lat - V[SR_n] cho Deflated Sharpe."""
        if self.trials.empty or self.n_trials < 2:
            return 0.0
        per_day = self.trials["train_sharpe"] / np.sqrt(metrics.TRADING_DAYS)
        return float(per_day.groupby(self.trials["train_start"]).var(ddof=1).mean())

    def sharpe_report(self) -> dict:
        """PSR(0) va DSR cua duong von out-of-sample, n_trials = so bo tham so."""
        moments = metrics.sharpe_moments(self.equity.pct_change().dropna())
        args = (moments["sr"], moments["n_obs"], moments["skew"], moments["kurtosis"])
        return {
            **moments,
            "psr": metrics.probabilistic_sharpe(*args),
            "dsr": metrics.deflated_sharpe(
                moments["sr"], self.n_trials, moments["n_obs"], self.trial_sharpe_variance(),
                moments["skew"], moments["kurtosis"],
            ),
            "n_trials": self.n_trials,
            "sr_variance": self.trial_sharpe_variance(),
        }


def _window(
    signals: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    universe: frozenset[str] | None = None,
) -> pd.DataFrame:
    times = pd.to_datetime(signals["time"])
    mask = (times >= start) & (times < end)
    if universe is not None:
        mask &= signals["symbol"].astype(str).str.upper().isin(universe)
    return signals[mask]


def _sharpe(equity: pd.Series) -> float:
    return metrics.sharpe(equity.pct_change().dropna()) if len(equity) > 1 else 0.0


def walk_forward(
    price_frames: dict[str, pd.DataFrame] | PreparedPrices,
    signals_for: Callable[[StrategyParams], pd.DataFrame],
    grid: tuple[StrategyParams, ...] = DEFAULT_GRID,
    train_months: int = 12,
    test_months: int = 3,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    initial_capital: float = 100_000_000,
    fee_rate: float | None = None,
    exchanges: dict[str, str] | None = None,
    universe_fn: Callable[[pd.Timestamp], frozenset[str]] | None = None,
) -> WalkForwardResult:
    """Walk-forward cuon: train `train_months`, test `test_months`, buoc = test.

    `signals_for(params)` tra ve tin hieu MUA tren TOAN BO lich su cho bo tham
    so do (vd SignalCache) - tin hieu tai t chi dung du lieu <= t nen cat theo
    cua so la hop le. `start`/`end`: gioi han khoang kiem dinh (mac dinh: toan
    bo lich giao dich). `universe_fn(as_of)`: tap ma duoc phep giao dich, tinh
    chi bang du lieu <= as_of; None = moi ma co tin hieu.
    """
    prices = (
        price_frames if isinstance(price_frames, PreparedPrices)
        else prepare_prices(price_frames, exchanges)
    )
    calendar = pd.DatetimeIndex(prices.calendar)
    empty = WalkForwardResult(pd.Series(dtype=float), pd.DataFrame(), pd.DataFrame(),
                              pd.DataFrame(), grid)
    if calendar.empty or not grid:
        return empty
    start = pd.Timestamp(start) if start is not None else calendar[0]
    end = pd.Timestamp(end) if end is not None else calendar[-1] + pd.Timedelta(days=1)

    capital = initial_capital
    pieces: list[pd.Series] = []
    trade_frames: list[pd.DataFrame] = []
    slice_rows: list[dict] = []
    trial_rows: list[dict] = []

    train_start = start
    while True:
        train_end = train_start + pd.DateOffset(months=train_months)
        test_end = min(train_end + pd.DateOffset(months=test_months), end)
        test_sessions = int(((calendar >= train_end) & (calendar < test_end)).sum())
        if train_end >= end or test_sessions < _MIN_TEST_SESSIONS:
            break

        train_universe = _universe_before(universe_fn, train_start)
        test_universe = _universe_before(universe_fn, train_end)

        # ---- 1. chon tham so CHI tren cua so train ----
        best, best_sharpe = None, float("-inf")
        for params in grid:
            result = run(
                prices, _window(signals_for(params), train_start, train_end, train_universe),
                initial_capital=initial_capital, max_hold_days=params.max_hold_days,
                fee_rate=fee_rate, start=train_start, end=train_end, close_at_end=True,
            )
            sharpe = _sharpe(result.equity)
            trial_rows.append(
                {"train_start": train_start, "train_end": train_end, **asdict(params),
                 "train_sharpe": sharpe, "train_trades": len(result.trades),
                 "train_return": metrics.total_return(result.equity)}
            )
            if sharpe > best_sharpe:
                best, best_sharpe = params, sharpe

        # ---- 2. ap nguyen tham so len cua so test ----
        result = run(
            prices, _window(signals_for(best), train_end, test_end, test_universe),
            initial_capital=capital, max_hold_days=best.max_hold_days, fee_rate=fee_rate,
            start=train_end, end=test_end, close_at_end=True,
        )
        if not result.equity.empty:
            pieces.append(result.equity)
            capital = float(result.equity.iloc[-1])
        trade_frames.append(result.trades)

        stats = metrics.summarise(result.equity, result.trades)
        slice_rows.append(
            {"train_start": train_start.date(), "test_start": train_end.date(),
             "test_end": test_end.date(), "So phien": len(result.equity),
             "So ma vu tru": len(test_universe) if test_universe is not None else None,
             **asdict(best),
             "Sharpe train": best_sharpe, **stats}
        )
        log.info(
            "Lat test %s -> %s: chon [%s] (Sharpe train %.2f), %d lenh, loi nhuan %+.1f%%",
            train_end.date(), test_end.date(), best.label(), best_sharpe, len(result.trades),
            stats["Ti suat sinh loi tich luy"] * 100,
        )
        train_start = train_start + pd.DateOffset(months=test_months)

    if not slice_rows:
        return empty
    equity = pd.concat(pieces) if pieces else pd.Series(dtype=float)
    trades = [t for t in trade_frames if not t.empty]
    return WalkForwardResult(
        equity=equity,
        trades=pd.concat(trades, ignore_index=True) if trades else pd.DataFrame(),
        slices=pd.DataFrame(slice_rows),
        trials=pd.DataFrame(trial_rows),
        grid=grid,
    )


def _universe_before(
    universe_fn: Callable[[pd.Timestamp], frozenset[str]] | None, window_start: pd.Timestamp
) -> frozenset[str] | None:
    """Vu tru cho cua so bat dau tai `window_start`: as_of = ngay truoc do, de
    du lieu cua chinh phien dau cua so cung chua duoc dung."""
    if universe_fn is None:
        return None
    return frozenset(s.upper() for s in universe_fn(window_start - pd.Timedelta(days=1)))


def compare_benchmarks(
    result_equity: pd.Series, index_frame: pd.DataFrame
) -> pd.DataFrame:
    """So chien luoc voi mua-nam giu VN-Index tren cung khoang thoi gian."""
    if result_equity.empty or index_frame.empty:
        return pd.DataFrame()

    index = index_frame.set_index("time")["close"]
    index = index.reindex(result_equity.index).ffill().dropna()
    if index.empty:
        return pd.DataFrame()

    buy_hold = index / index.iloc[0] * result_equity.iloc[0]
    return pd.DataFrame(
        {
            "Chien luoc": metrics.summarise(result_equity, pd.DataFrame()),
            "Mua va nam giu VN-Index": metrics.summarise(buy_hold, pd.DataFrame()),
        }
    )
