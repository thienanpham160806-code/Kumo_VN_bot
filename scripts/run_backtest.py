"""Backtest day du chien luoc (MACD + RSI thich ung + Ichimoku) tren toan bo
lich su co san trong kho, so voi mua-va-giu VN-Index.

Nguon gia: kho toan san local (data/market_store.py), khong goi mang - phai
chay `python scripts/backfill_data.py` truoc it nhat mot lan. VN-Index lay qua
router (co the goi mang) va luu lai outputs/backtest/vnindex.csv.

Phuong phap (xem backtest/engine.py, walk_forward.py):
  - tin hieu cuoi phien t, vao lenh gia mo cua t+1; T+2; gap qua stop/target
    khop o gia mo cua; ket san thi doi lenh ban; phi + thue khi ban;
  - vu tru co phieu chon theo thoi diem (liquid_universe(as_of), chi du lieu
    <= as_of), khong dung danh sach thanh khoan hom nay;
  - walk-forward: toi uu 12 to hop tham so tren 12 thang train, ap len 3
    thang test, ghep duong von out-of-sample - day la ket qua chinh;
  - PSR/DSR (Bailey & Lopez de Prado 2014), n_trials = 12;
  - do nhay chi phi: phi hai chieu 0,15% / 0,25% / 0,35%.

Xuat (outputs/backtest/): report.md (bang ket qua dang Markdown - README lay
so tu day), summary.csv, cost_sensitivity.csv, grid_full_period.csv,
walk_forward_slices.csv, walk_forward_trials.csv, walk_forward_equity.csv,
trades_*.csv, equity_vs_vnindex.png, vnindex.csv. Them backtest_3m.csv,
backtest_6m.csv va equity_curve.png cho khung 3/6 thang gan nhat (yeu cau cua
de, xem PHAN 5).

Cach chay:
    python scripts/run_backtest.py                    # toan bo kho
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
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from bot_phan_tich.backtest import metrics  # noqa: E402
from bot_phan_tich.backtest.engine import BacktestResult, prepare_prices  # noqa: E402
from bot_phan_tich.backtest.engine import run as run_engine  # noqa: E402
from bot_phan_tich.backtest.walk_forward import (  # noqa: E402
    DEFAULT_GRID,
    SignalCache,
    StrategyParams,
    WalkForwardResult,
    walk_forward,
)
from bot_phan_tich.config import get_settings, get_universe_config  # noqa: E402
from bot_phan_tich.data import market_store  # noqa: E402
from bot_phan_tich.data.router import get_router  # noqa: E402
from bot_phan_tich.data.universe import liquid_universe  # noqa: E402
from bot_phan_tich.logging_conf import get_logger, setup_logging  # noqa: E402

log = get_logger("run_backtest")

_OUTPUTS_DIR = Path("outputs")
_OUT = _OUTPUTS_DIR / "backtest"
_MIN_BARS = 60
_INITIAL_CAPITAL = 100_000_000.0
_WINDOWS = [("3m", 90), ("6m", 180)]
_FEES = (0.0015, 0.0025, 0.0035)

# Bang mau tham chieu (dataviz skill): slot 1, 2; VN-Index (doi chung) mau trung tinh.
_COLOR_WF, _COLOR_FULL, _COLOR_INDEX = "#2a78d6", "#eb6834", "#8a8984"
_SURFACE, _TEXT, _TEXT_2, _GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"


# ------------------------------------------------------------------ chuan bi
def _default_params() -> StrategyParams:
    settings = get_settings()
    return StrategyParams(
        buy_threshold=settings.get("scoring.thresholds.buy", 60),
        ichimoku_preset=settings.get("indicators.ichimoku_preset", "goc_nhat_6ngay"),
        max_hold_days=20,
    )


def _load_frames(symbols: list[str] | None) -> dict[str, pd.DataFrame]:
    """Gia moi ma (None = ca kho) du _MIN_BARS phien. KHONG loc theo thanh khoan
    hom nay - ma nao giao dich duoc o thoi diem nao do universe_fn quyet dinh."""
    frames = market_store.frames_by_symbol(symbols)
    return {sym: frame for sym, frame in frames.items() if len(frame) >= _MIN_BARS}


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


def _point_in_time(signals: pd.DataFrame, universe_fn) -> pd.DataFrame:
    """Giu tin hieu khi ma thuoc vu tru cua THANG chua tin hieu (as_of = ngay
    cuoi thang truoc) - dung cho backtest mot mach tren ca ky."""
    if signals.empty:
        return signals
    months = pd.to_datetime(signals["time"]).dt.to_period("M")
    keep = pd.Series(False, index=signals.index)
    for month in months.unique():
        members = universe_fn(month.start_time - pd.Timedelta(days=1))
        keep |= (months == month) & signals["symbol"].isin(members)
    return signals[keep]


def _vnindex(benchmark: str, start: pd.Timestamp) -> pd.Series:
    frame = get_router().ohlcv(benchmark, (start - pd.Timedelta(days=10)).date(), date.today())
    closes = frame.assign(time=pd.to_datetime(frame["time"]).dt.normalize())
    series = closes.groupby("time")["close"].last().astype(float)
    _OUT.mkdir(parents=True, exist_ok=True)
    series.rename("close").to_csv(_OUT / "vnindex.csv", encoding="utf-8-sig")
    return series


# --------------------------------------------------------------- chi so / bang
def _row(label: str, equity: pd.Series, trades: pd.DataFrame, n_trials: int = 1,
         sr_variance: float = 0.0) -> dict:
    stats = metrics.summarise(equity, trades)
    moments = metrics.sharpe_moments(equity.pct_change().dropna())
    psr = metrics.probabilistic_sharpe(moments["sr"], moments["n_obs"], moments["skew"],
                                       moments["kurtosis"])
    dsr = (
        metrics.deflated_sharpe(moments["sr"], n_trials, moments["n_obs"], sr_variance,
                                moments["skew"], moments["kurtosis"])
        if n_trials > 1 else float("nan")
    )
    return {
        "Chien luoc": label,
        "Tu": equity.index.min().date(),
        "Den": equity.index.max().date(),
        "So phien": len(equity),
        "Loi nhuan tich luy": stats["Ti suat sinh loi tich luy"],
        "CAGR": stats["CAGR"],
        "Sharpe": stats["Ti so Sharpe"],
        "Sortino": stats["Ti so Sortino"],
        "Sut giam toi da": stats["Sut giam toi da"],
        "Vong quay (lan/nam)": stats["Vong quay (lan/nam)"] if len(trades) else float("nan"),
        "So lenh": len(trades) if "entry" in trades.columns else float("nan"),
        "Ti le thang": stats["Ti le thang"] if len(trades) else float("nan"),
        "PSR": psr,
        "DSR": dsr,
    }


def _benchmark_equity(index: pd.Series, like: pd.Series) -> pd.Series:
    aligned = index.reindex(like.index).ffill().dropna()
    return aligned / aligned.iloc[0] * _INITIAL_CAPITAL


def _markdown(frame: pd.DataFrame) -> str:
    percent = {"Loi nhuan tich luy", "CAGR", "Sut giam toi da", "Ti le thang", "Phi hai chieu"}
    ratio = {"Sharpe", "Sortino", "Vong quay (lan/nam)"}
    probability = {"PSR", "DSR"}

    def fmt(column, value):
        if isinstance(value, float) and np.isnan(value):
            return "-"
        if column == "Phi hai chieu":
            return f"{value:.2%}"
        if column == "Ti le thang":
            return f"{value:.0%}"
        if column in percent:
            return f"{value:+.1%}"
        if column in ratio:
            return f"{value:.2f}"
        if column in probability:
            return f"{value:.3f}"
        if column in {"So lenh", "So phien"}:
            return f"{int(value)}"
        return str(value)

    lines = ["| " + " | ".join(frame.columns) + " |",
             "|" + "|".join("---" for _ in frame.columns) + "|"]
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(fmt(c, row[c]) for c in frame.columns) + " |")
    return "\n".join(lines)


# ----------------------------------------------------------------- cac phan chay
def _full_period(prices, signals, start, params, fee_rate=None) -> BacktestResult:
    return run_engine(prices, signals, initial_capital=_INITIAL_CAPITAL,
                      max_hold_days=params.max_hold_days, fee_rate=fee_rate, start=start,
                      close_at_end=True)


def _walk_forward(prices, cache_, universe_fn, start, args, fee_rate=None) -> WalkForwardResult:
    started = time.time()
    result = walk_forward(prices, cache_, train_months=args.train_months,
                          test_months=args.test_months, start=start,
                          initial_capital=_INITIAL_CAPITAL, fee_rate=fee_rate,
                          universe_fn=universe_fn)
    log.info("Walk-forward (phi %s) xong trong %.0fs", fee_rate, time.time() - started)
    return result


def _plot(full: BacktestResult, wf: WalkForwardResult, index: pd.Series, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 5), facecolor=_SURFACE)
    ax.set_facecolor(_SURFACE)
    bench = _benchmark_equity(index, full.equity)
    lines = [
        (bench, _COLOR_INDEX, "VN-Index mua va giu"),
        (full.equity, _COLOR_FULL, "Tham so mac dinh, ca ky"),
    ]
    if not wf.equity.empty:
        lines.append((wf.equity, _COLOR_WF, "Walk-forward out-of-sample"))
        ax.axvline(wf.equity.index[0], color=_GRID, linewidth=1, linestyle="--")
    for series, color, label in lines:
        values = series / series.iloc[0] * 100
        ax.plot(values.index, values.to_numpy(), color=color, linewidth=2, label=label)
        ax.annotate(label, (values.index[-1], values.iloc[-1]), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=9, color=_TEXT_2)
    ax.axhline(100, color=_TEXT_2, linewidth=1)
    ax.set_ylabel("Gia tri (100 = dau ky cua tung duong)", color=_TEXT_2)
    ax.set_title("Duong von sau phi, thue - so voi VN-Index", color=_TEXT, fontsize=11,
                 loc="left")
    ax.grid(axis="y", color=_GRID, linewidth=0.8)
    ax.tick_params(colors=_TEXT_2)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(_GRID)
    ax.legend(frameon=False, loc="upper left", fontsize=9, labelcolor=_TEXT_2)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=130, facecolor=_SURFACE)
    plt.close(fig)


def _recent_windows(prices, signals, universe_fn, index: pd.Series, params) -> None:
    """Khung 3 va 6 thang gan nhat (yeu cau cua de) - chi de doi chieu, it y
    nghia thong ke."""
    today = date.today()
    rows, curves = [], {}
    for label, days in _WINDOWS:
        window_start = pd.Timestamp(today - timedelta(days=days))
        members = universe_fn(window_start - pd.Timedelta(days=1))
        result = run_engine(prices, signals[signals["symbol"].isin(members)],
                            initial_capital=_INITIAL_CAPITAL, max_hold_days=params.max_hold_days,
                            start=window_start)
        result.trades.to_csv(_OUTPUTS_DIR / f"backtest_{label}.csv", index=False,
                             encoding="utf-8-sig")
        bench = index[index.index >= window_start]
        rows.append({
            "khung": label,
            "so_lenh": len(result.trades),
            "ty_le_thang": float((result.trades["pnl"] > 0).mean()) if len(result.trades)
            else None,
            "loi_nhuan_chien_luoc": float(result.equity.iloc[-1] / _INITIAL_CAPITAL - 1),
            "loi_nhuan_VNINDEX": float(bench.iloc[-1] / bench.iloc[0] - 1) if len(bench) > 1
            else None,
        })
        curves[label] = result.equity
    print("\n=== Khung 3 / 6 thang gan nhat (yeu cau cua de) ===")
    print(pd.DataFrame(rows).to_string(index=False))

    fig, ax = plt.subplots(figsize=(10, 5))
    for label, equity in curves.items():
        ax.plot(equity.index, equity.values / _INITIAL_CAPITAL * 100, label=f"Chien luoc ({label})")
    ax.axhline(100, color="gray", linestyle="--", linewidth=1, label="Von ban dau")
    ax.set_ylabel("Von (chuan hoa, 100 = von ban dau)")
    ax.set_title("Duong von chien luoc - backtest 3 va 6 thang gan nhat")
    ax.legend()
    fig.autofmt_xdate()
    fig.savefig(_OUTPUTS_DIR / "equity_curve.png", dpi=120, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--watchlist-only", action="store_true",
        help="Chi dung vai ma trong config/universe.yaml (phat trien, chay nhanh)",
    )
    parser.add_argument("--train-months", type=int, default=12)
    parser.add_argument("--test-months", type=int, default=3)
    parser.add_argument("--start", default=None,
                        help="Ngay bat dau (mac dinh: tu dong, xem _default_start)")
    parser.add_argument("--skip-costs", action="store_true",
                        help="Bo qua bang do nhay chi phi (chay them 2 lan walk-forward)")
    args = parser.parse_args()

    setup_logging()
    _OUT.mkdir(parents=True, exist_ok=True)
    started = time.time()

    universe_config = get_universe_config()
    watchlist = (
        [s.upper() for s in universe_config["watchlist"]] if args.watchlist_only else None
    )
    frames = _load_frames(watchlist)
    if not frames:
        print("Khong co ma nao du du lieu trong kho - chay scripts/backfill_data.py truoc.")
        return
    universe_fn = _universe_fn(watchlist)
    start = pd.Timestamp(args.start) if args.start else _default_start(frames)
    log.info("%d ma du du lieu (>= %d phien); kiem dinh tu %s", len(frames), _MIN_BARS,
             start.date())

    cache_ = SignalCache(frames)
    params = _default_params()
    signals = _point_in_time(cache_(params), universe_fn)
    prices = prepare_prices(frames)
    index = _vnindex(universe_config.get("benchmark", "VNINDEX"), start)
    log.info("Chuan bi xong (tin hieu %d) trong %.0fs", len(signals), time.time() - started)

    # ---- 1. ca ky, tham so mac dinh + 12 to hop (cho phuong sai Sharpe cua DSR)
    grid_rows, grid_results = [], {}
    for combo in DEFAULT_GRID:
        result = _full_period(prices, _point_in_time(cache_(combo), universe_fn), start, combo)
        grid_results[combo] = result
        grid_rows.append({**combo.__dict__, **_row(combo.label(), result.equity, result.trades)})
    grid = pd.DataFrame(grid_rows)
    grid.to_csv(_OUT / "grid_full_period.csv", index=False, encoding="utf-8-sig")
    per_day_sr = grid["Sharpe"] / np.sqrt(metrics.TRADING_DAYS)
    full_variance = float(per_day_sr.var(ddof=1))
    n_trials = len(DEFAULT_GRID)

    full = (grid_results[params] if params in grid_results
            else _full_period(prices, signals, start, params))
    best_combo = DEFAULT_GRID[int(grid["Sharpe"].to_numpy().argmax())]
    best = grid_results[best_combo]

    # ---- 2. walk-forward out-of-sample
    wf = _walk_forward(prices, cache_, universe_fn, start, args)
    if wf.slices.empty:
        print("Walk-forward: lich su qua ngan cho mot lat train + test.")
        return
    wf.slices.to_csv(_OUT / "walk_forward_slices.csv", index=False, encoding="utf-8-sig")
    wf.trials.to_csv(_OUT / "walk_forward_trials.csv", index=False, encoding="utf-8-sig")
    wf.equity.rename("equity").to_csv(_OUT / "walk_forward_equity.csv", encoding="utf-8-sig")
    full.trades.to_csv(_OUT / "trades_full_period.csv", index=False, encoding="utf-8-sig")
    wf.trades.to_csv(_OUT / "trades_walk_forward.csv", index=False, encoding="utf-8-sig")

    summary = pd.DataFrame([
        _row(f"Walk-forward OOS ({len(wf.slices)} lat)", wf.equity, wf.trades, n_trials,
             wf.trial_sharpe_variance()),
        _row("VN-Index mua va giu (cung ky OOS)", _benchmark_equity(index, wf.equity),
             pd.DataFrame()),
        _row(f"Tham so mac dinh ({params.label()}), ca ky", full.equity, full.trades,
             n_trials, full_variance),
        _row(f"Tot nhat in-sample ({best_combo.label()}), ca ky", best.equity, best.trades,
             n_trials, full_variance),
        _row("VN-Index mua va giu (ca ky)", _benchmark_equity(index, full.equity),
             pd.DataFrame()),
    ])
    summary.to_csv(_OUT / "summary.csv", index=False, encoding="utf-8-sig")

    # ---- 3. do nhay chi phi
    cost_rows = []
    if not args.skip_costs:
        for fee in _FEES:
            default_fee = abs(fee - get_settings().get("costs.fee_rate", 0.0025)) < 1e-12
            run_full = full if default_fee else _full_period(prices, signals, start, params, fee)
            run_wf = wf if default_fee else _walk_forward(prices, cache_, universe_fn, start,
                                                          args, fee)
            for label, equity, trades in (
                ("Walk-forward OOS", run_wf.equity, run_wf.trades),
                ("Tham so mac dinh, ca ky", run_full.equity, run_full.trades),
            ):
                row = _row(label, equity, trades)
                cost_rows.append({"Phi hai chieu": fee, **{k: row[k] for k in (
                    "Chien luoc", "CAGR", "Sharpe", "Sut giam toi da", "Vong quay (lan/nam)",
                    "So lenh")}})
    costs = pd.DataFrame(cost_rows)
    if not costs.empty:
        costs = costs.sort_values(["Chien luoc", "Phi hai chieu"])
        costs.to_csv(_OUT / "cost_sensitivity.csv", index=False, encoding="utf-8-sig")

    # ---- 4. bao cao
    _plot(full, wf, index, _OUT / "equity_vs_vnindex.png")
    slice_cols = ["test_start", "test_end", "So ma vu tru", "buy_threshold", "ichimoku_preset",
                  "max_hold_days", "Sharpe train", "Ti suat sinh loi tich luy", "Ti so Sharpe",
                  "So lenh"]
    slices = wf.slices[slice_cols].rename(columns={"Ti suat sinh loi tich luy": "Loi nhuan",
                                                   "Ti so Sharpe": "Sharpe test"})
    slices["Loi nhuan"] = slices["Loi nhuan"].map(lambda v: f"{v:+.1%}")
    slices["Sharpe train"] = slices["Sharpe train"].map(lambda v: f"{v:.2f}")
    slices["Sharpe test"] = slices["Sharpe test"].map(lambda v: f"{v:.2f}")
    report = [
        "# Ket qua backtest",
        "",
        f"Sinh bang `python scripts/run_backtest.py` ngay {date.today():%Y-%m-%d} "
        "(khong sua tay).",
        "",
        f"- Du lieu: {len(frames)} ma trong kho, kiem dinh tu {start.date()} den "
        f"{full.equity.index.max().date()}; vu tru chon theo thoi diem "
        f"(trung vi {int(wf.slices['So ma vu tru'].median())} ma/lat walk-forward).",
        f"- Phi hai chieu {get_settings().get('costs.fee_rate'):.2%} + thue ban "
        f"{get_settings().get('costs.sell_tax_rate'):.1%}; von ban dau "
        f"{_INITIAL_CAPITAL:,.0f} dong.",
        f"- Walk-forward: train {args.train_months} thang / test {args.test_months} thang, "
        f"luoi {n_trials} to hop; DSR dung n_trials = {n_trials}.",
        "",
        "## Tong hop",
        "",
        _markdown(summary),
        "",
        "## Do nhay chi phi",
        "",
        _markdown(costs) if not costs.empty else "(bo qua)",
        "",
        "## Walk-forward tung lat",
        "",
        "| " + " | ".join(slices.columns) + " |",
        "|" + "|".join("---" for _ in slices.columns) + "|",
        *("| " + " | ".join(str(v) for v in row) + " |" for row in slices.to_numpy()),
        "",
    ]
    (_OUT / "report.md").write_text("\n".join(report), encoding="utf-8")

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print("\n=== Tong hop ===")
    print(summary.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    if not costs.empty:
        print("\n=== Do nhay chi phi ===")
        print(costs.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print("\n=== Walk-forward tung lat ===")
    print(slices.to_string(index=False))

    _recent_windows(prices, signals, universe_fn, index, params)
    print(f"\nDa xuat {_OUT}/ (report.md, summary.csv, ...) trong {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
