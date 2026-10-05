"""Backtest chien luoc (MACD + RSI thich ung + Ichimoku) tren 3 va 6 thang gan
nhat, so sanh voi mua-va-giu VN-Index - yeu cau con thieu cua de (xem PHAN 5).

Nguon gia: kho toan san local (data/market_store.py), khong goi mang - phai
chay `python scripts/backfill_data.py` truoc it nhat mot lan. Tin hieu MUA
duoc sinh tren TOAN BO lich su co san trong kho (backtest/signals.py) de cac
chi bao (dac biet Ichimoku, can toi 52+26 phien) co du du lieu khoi dong,
sau do CHI tin hieu roi vao khung 3/6 thang moi duoc dua vao backtest/engine.py
- ket qua phan anh dung "neu bat dau giao dich N thang truoc thi ra sao",
khong bi meo vi thieu du lieu khoi dong chi bao.

Xuat: outputs/backtest_3m.csv, outputs/backtest_6m.csv (danh sach lenh da
dong), outputs/equity_curve.png (duong von hai khung, so voi VN-Index).

Walk-forward (backtest/walk_forward.py): toi uu luoi tham so tren 12 thang
train, ap len 3 thang test ke tiep, lan cua so; xuat
outputs/backtest/walk_forward_slices.csv (tham so chon + chi so tung lat),
walk_forward_trials.csv (Sharpe train moi bo tham so) va
walk_forward_equity.csv (duong von out-of-sample ghep).

Cach chay:
    python scripts/run_backtest.py                    # toan bo vu tru thanh khoan
    python scripts/run_backtest.py --watchlist-only    # nhanh, vai ma trong universe.yaml
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from functools import cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from bot_phan_tich.backtest import metrics  # noqa: E402
from bot_phan_tich.backtest.engine import prepare_prices  # noqa: E402
from bot_phan_tich.backtest.engine import run as run_engine  # noqa: E402
from bot_phan_tich.backtest.walk_forward import (  # noqa: E402
    DEFAULT_GRID,
    SignalCache,
    StrategyParams,
    walk_forward,
)
from bot_phan_tich.config import get_settings, get_universe_config  # noqa: E402
from bot_phan_tich.data import market_store  # noqa: E402
from bot_phan_tich.data.router import get_router  # noqa: E402
from bot_phan_tich.data.universe import liquid_universe  # noqa: E402
from bot_phan_tich.logging_conf import get_logger, setup_logging  # noqa: E402

log = get_logger("run_backtest")

_OUTPUTS_DIR = Path("outputs")
_MIN_BARS = 60
_INITIAL_CAPITAL = 100_000_000.0
_WINDOWS = [("3m", 90), ("6m", 180)]
_WF_DIR = _OUTPUTS_DIR / "backtest"


def _default_params() -> StrategyParams:
    settings = get_settings()
    return StrategyParams(
        buy_threshold=settings.get("scoring.thresholds.buy", 60),
        ichimoku_preset=settings.get("indicators.ichimoku_preset", "goc_nhat_6ngay"),
        max_hold_days=20,
    )


def _universe_fn(watchlist: list[str] | None):
    """as_of -> tap ma du thanh khoan TAI as_of (chi du lieu <= as_of)."""
    if watchlist:
        return lambda as_of: frozenset(watchlist)
    ohlcv = market_store.load_ohlcv(columns=["symbol", "time", "close", "volume"])

    @cache
    def universe_at(as_of: pd.Timestamp) -> frozenset[str]:
        return frozenset(liquid_universe(as_of.date(), ohlcv=ohlcv, min_days=_MIN_BARS))

    return universe_at


def _default_start(frames: dict[str, pd.DataFrame]) -> pd.Timestamp:
    """Ngay dau tien ma it nhat mot nua so ma da co du lieu, cong _MIN_BARS
    phien khoi dong chi bao. Lich cua kho bat dau tu 2016 chi vi mot vai ma
    co lich su dai - kiem dinh tu do la kiem dinh tren vai ma le."""
    counts = pd.concat([f["time"] for f in frames.values()]).value_counts().sort_index()
    broad = counts.index[counts >= counts.max() * 0.5]
    sessions = counts.index[counts.index >= broad[0]]
    return sessions[min(_MIN_BARS, len(sessions) - 1)]


def _run_walk_forward(prices, cache: SignalCache, universe_fn, start: pd.Timestamp,
                      train_months: int, test_months: int) -> None:
    log.info("Walk-forward tu %s: luoi %d bo tham so, train %d thang / test %d thang",
             start.date(), len(DEFAULT_GRID), train_months, test_months)
    started = time.time()
    result = walk_forward(prices, cache, train_months=train_months, test_months=test_months,
                          start=start, initial_capital=_INITIAL_CAPITAL,
                          universe_fn=universe_fn)
    log.info("Walk-forward xong trong %.0fs", time.time() - started)
    if result.slices.empty:
        print("Walk-forward: lich su qua ngan cho mot lat train + test.")
        return

    _WF_DIR.mkdir(parents=True, exist_ok=True)
    result.slices.to_csv(_WF_DIR / "walk_forward_slices.csv", index=False, encoding="utf-8-sig")
    result.trials.to_csv(_WF_DIR / "walk_forward_trials.csv", index=False, encoding="utf-8-sig")
    result.equity.rename("equity").to_csv(_WF_DIR / "walk_forward_equity.csv",
                                          encoding="utf-8-sig")

    cols = ["test_start", "test_end", "So ma vu tru", "buy_threshold", "ichimoku_preset",
            "max_hold_days", "Sharpe train", "Ti suat sinh loi tich luy", "Ti so Sharpe", "So lenh"]
    print("\n=== Walk-forward: tham so chon tren train, ket qua tren test ===")
    print(result.slices[cols].to_string(index=False))
    print(f"\n=== Out-of-sample ghep ({len(result.slices)} lat, "
          f"{result.n_trials} bo tham so da thu) ===")
    print(metrics.format_report(metrics.summarise(result.equity, result.trades)))
    report = result.sharpe_report()
    print(f"PSR (P[Sharpe that > 0]): {report['psr']:.3f}")
    print(f"DSR (n_trials={report['n_trials']}, V[SR ngay]={report['sr_variance']:.2e}): "
          f"{report['dsr']:.3f}")


def _load_frames(symbols: list[str] | None) -> dict[str, pd.DataFrame]:
    """Gia moi ma (None = ca kho) du _MIN_BARS phien. KHONG loc theo thanh khoan
    hom nay - ma nao giao dich duoc o thoi diem nao do universe_fn quyet dinh."""
    frames = market_store.frames_by_symbol(symbols)
    return {sym: frame for sym, frame in frames.items() if len(frame) >= _MIN_BARS}


def _benchmark_return(benchmark: str, start: date, end: date) -> float | None:
    """Loi nhuan mua-va-giu VN-Index tu dau den cuoi khung - qua router (co
    the phai goi mang neu VNINDEX chua co trong kho toan san CP)."""
    frame = get_router().ohlcv(benchmark, start, end)
    if len(frame) < 2:
        return None
    first, last = float(frame["close"].iloc[0]), float(frame["close"].iloc[-1])
    return (last / first - 1) if first else None


def _win_rate(trades: pd.DataFrame) -> float | None:
    if trades.empty:
        return None
    return float((trades["pnl"] > 0).mean())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--watchlist-only", action="store_true",
        help="Chi dung vai ma trong config/universe.yaml (phat trien, chay nhanh)",
    )
    parser.add_argument("--train-months", type=int, default=12)
    parser.add_argument("--test-months", type=int, default=3)
    parser.add_argument("--start", default=None,
                        help="Ngay bat dau walk-forward (mac dinh: tu dong, xem _default_start)")
    args = parser.parse_args()

    setup_logging()
    _OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    universe_config = get_universe_config()
    benchmark = universe_config.get("benchmark", "VNINDEX")
    watchlist = (
        [s.upper() for s in universe_config["watchlist"]] if args.watchlist_only else None
    )
    frames = _load_frames(watchlist)
    if not frames:
        print("Khong co ma nao du du lieu trong kho - chay scripts/backfill_data.py truoc.")
        return
    log.info("%d ma du du lieu (>= %d phien)", len(frames), _MIN_BARS)
    universe_fn = _universe_fn(watchlist)

    log.info("Sinh tin hieu MUA tren toan bo lich su co san...")
    started = time.time()
    cache = SignalCache(frames)
    signals = cache(_default_params())
    elapsed_signals = time.time() - started
    log.info(
        "Sinh xong %d tin hieu tu %d ma trong %.1fs", len(signals), len(frames), elapsed_signals
    )

    prices = prepare_prices(frames)
    start = pd.Timestamp(args.start) if args.start else _default_start(frames)
    _run_walk_forward(prices, cache, universe_fn, start, args.train_months, args.test_months)

    today = date.today()
    rows = []
    equity_curves: dict[str, pd.Series] = {}

    for label, days in _WINDOWS:
        window_start = pd.Timestamp(today - timedelta(days=days))
        universe = universe_fn(window_start - pd.Timedelta(days=1))
        window_signals = signals[signals["symbol"].isin(universe)]

        result = run_engine(prices, window_signals, initial_capital=_INITIAL_CAPITAL,
                            max_hold_days=_default_params().max_hold_days, start=window_start)
        final_equity = float(result.equity.iloc[-1]) if len(result.equity) else _INITIAL_CAPITAL
        strategy_return = final_equity / _INITIAL_CAPITAL - 1

        bench_return = _benchmark_return(benchmark, window_start.date(), today)

        csv_path = _OUTPUTS_DIR / f"backtest_{label}.csv"
        result.trades.to_csv(csv_path, index=False, encoding="utf-8-sig")

        rows.append(
            {
                "khung": label,
                "so_lenh": len(result.trades),
                "ty_le_thang": _win_rate(result.trades),
                "loi_nhuan_chien_luoc": strategy_return,
                f"loi_nhuan_{benchmark}": bench_return,
            }
        )
        equity_curves[label] = result.equity
        bench_str = f"{bench_return:+.1%}" if bench_return is not None else "n/a"
        log.info(
            "Khung %s: %d lenh, chien luoc %+.1f%%, %s %s -> %s",
            label, len(result.trades), strategy_return * 100, benchmark, bench_str, csv_path,
        )

    table = pd.DataFrame(rows)
    print("\n=== So sanh chien luoc vs mua-va-giu (buy & hold) ===")
    print(table.to_string(index=False))

    fig, ax = plt.subplots(figsize=(10, 5))
    for label, equity in equity_curves.items():
        if len(equity):
            normalized = equity.values / _INITIAL_CAPITAL * 100
            ax.plot(equity.index, normalized, label=f"Chien luoc ({label})")
    ax.axhline(100, color="gray", linestyle="--", linewidth=1, label="Von ban dau")
    ax.set_ylabel("Von (chuan hoa, 100 = von ban dau)")
    ax.set_title("Duong von chien luoc - backtest 3 va 6 thang gan nhat")
    ax.legend()
    fig.autofmt_xdate()
    chart_path = _OUTPUTS_DIR / "equity_curve.png"
    fig.savefig(chart_path, dpi=120, bbox_inches="tight")
    plt.close(fig)

    csv_paths = ", ".join(str(_OUTPUTS_DIR / f"backtest_{label}.csv") for label, _ in _WINDOWS)
    print(f"\nDa xuat: {csv_paths}")
    print(f"Da xuat: {chart_path}")


if __name__ == "__main__":
    main()
