"""Phan tich Information Coefficient (IC) cua diem MACD, RSI, Ichimoku va diem
tong (analysis/score_history.py) so voi loi suat tuong lai.

Moi phien t, tren MAT CAT cac ma trong vu tru tai t (chon theo thoi diem:
liquid_universe(as_of = ngay cuoi thang truoc), chi du lieu <= as_of):
  - diem so tai t (chi dung du lieu den t),
  - loi suat tuong lai h phien: open[t+1+h] / open[t+1] - 1 (mua o gia mo
    cua phien ke tiep - som nhat co the sau khi biet diem cuoi phien t),
  - IC = tuong quan hang Spearman giua hai cot tren.
Xuat (outputs/ic/): ic_summary.csv (IC trung binh, do lech chuan, ICIR,
t-stat thuong va Newey-West, ti le thang IC > 0), ic_daily.csv, ic_monthly.csv,
ic_decay.png (IC trung binh theo do dai horizon, kem khoang tin cay 95% NW).

Cach chay:
    python scripts/ic_analysis.py
    python scripts/ic_analysis.py --watchlist-only     # nhanh, vai ma (khong co y nghia thong ke)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from bot_phan_tich.analysis.score_history import score_history  # noqa: E402
from bot_phan_tich.backtest import ic  # noqa: E402
from bot_phan_tich.config import get_universe_config  # noqa: E402
from bot_phan_tich.data import market_store  # noqa: E402
from bot_phan_tich.data.universe import liquid_universe  # noqa: E402
from bot_phan_tich.logging_conf import get_logger, setup_logging  # noqa: E402

log = get_logger("ic_analysis")

_OUT_DIR = Path("outputs") / "ic"
_MIN_BARS = 60
_FACTORS = {"macd": "MACD", "rsi": "RSI", "ichimoku": "Ichimoku", "total": "Diem tong"}
_REPORT_HORIZONS = [5, 10, 20]
_DECAY_HORIZONS = [1, 2, 5, 10, 20]

# Bang mau tham chieu (dataviz skill, references/palette.md), slot 1-4 theo thu tu.
_SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
_SURFACE, _TEXT, _TEXT_2, _GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"


def _broad_start(frames: dict[str, pd.DataFrame]) -> pd.Timestamp:
    """Giong run_backtest._default_start: tu khi >= 1/2 so ma co du lieu, + 60 phien."""
    counts = pd.concat([f["time"] for f in frames.values()]).value_counts().sort_index()
    sessions = counts.index[counts.index >= counts.index[counts >= counts.max() * 0.5][0]]
    return sessions[min(_MIN_BARS, len(sessions) - 1)]


def build_panel(frames: dict[str, pd.DataFrame], horizons: list[int]) -> pd.DataFrame:
    """Bang dai (time, symbol, diem tung he, loi suat tuong lai) cho moi ma."""
    parts = []
    for k, (sym, frame) in enumerate(frames.items(), 1):
        frame = frame.reset_index(drop=True)
        scores = score_history(frame)[["time", *_FACTORS]]
        scores.loc[: _MIN_BARS - 1, list(_FACTORS)] = np.nan  # chua du du lieu khoi dong
        parts.append(
            pd.concat([scores, ic.forward_open_returns(frame, horizons)], axis=1)
            .assign(symbol=sym)
        )
        if k % 200 == 0:
            log.info("Da cham diem %d/%d ma", k, len(frames))
    return pd.concat(parts, ignore_index=True)


def restrict_to_universe(panel: pd.DataFrame, watchlist: list[str] | None) -> pd.DataFrame:
    """Giu (phien, ma) khi ma thuoc vu tru cua THANG do, chon voi du lieu den
    het thang truoc."""
    if watchlist:
        return panel[panel["symbol"].isin(watchlist)]
    ohlcv = market_store.load_ohlcv(columns=["symbol", "time", "close", "volume"])
    months = panel["time"].dt.to_period("M")
    keep = []
    for month in sorted(months.unique()):
        as_of = (month.start_time - pd.Timedelta(days=1)).date()
        members = set(liquid_universe(as_of, ohlcv=ohlcv, min_days=_MIN_BARS))
        rows = panel[(months == month) & panel["symbol"].isin(members)]
        keep.append(rows)
        log.info("Thang %s: %d ma trong vu tru", month, len(members))
    return pd.concat(keep, ignore_index=True)


def plot_decay(summary: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.6), facecolor=_SURFACE)
    ax.set_facecolor(_SURFACE)
    dodge = np.linspace(0.93, 1.07, len(_FACTORS))  # lech nhe tren truc log de khong de nhau
    ends = []
    for color, label, shift in zip(_SERIES_COLORS, _FACTORS.values(), dodge, strict=True):
        rows = summary[summary["Chi bao"] == label].sort_values("Horizon (phien)")
        x = rows["Horizon (phien)"].to_numpy() * shift
        y = rows["IC trung binh"].to_numpy()
        # khoang tin cay 95% theo sai so chuan Newey-West: SE = |mean / t_NW|
        se = np.abs(y / rows["t-stat Newey-West"].to_numpy())
        ax.errorbar(x, y, yerr=1.96 * se, fmt="none", ecolor=color, elinewidth=1.2, alpha=0.55)
        ax.plot(x, y, color=color, linewidth=2, marker="o", markersize=6, label=label,
                markeredgecolor=_SURFACE, markeredgewidth=1.5)
        ends.append([y[-1], x[-1], label])
    # nhan cuoi duong: day cach nhau toi thieu de khong chong chu
    ends.sort()
    gap = 0.0045
    for k in range(1, len(ends)):
        ends[k][0] = max(ends[k][0], ends[k - 1][0] + gap)
    label_x = max(x_end for _, x_end, _ in ends) * 1.06
    for y_label, _, label in ends:
        ax.annotate(label, (label_x, y_label), va="center", fontsize=9, color=_TEXT_2)
    ax.axhline(0, color=_TEXT_2, linewidth=1)
    ax.set_xscale("log")
    ax.set_xticks(_DECAY_HORIZONS, [str(h) for h in _DECAY_HORIZONS])
    ax.minorticks_off()
    ax.set_xlim(0.85, 40)
    ax.set_xlabel("Horizon (so phien, tinh tu gia mo cua t+1)", color=_TEXT_2)
    ax.set_ylabel("IC Spearman trung binh", color=_TEXT_2)
    ax.set_title("IC decay theo horizon (thanh doc = khoang tin cay 95% Newey-West)",
                 color=_TEXT, fontsize=11, loc="left")
    ax.grid(axis="y", color=_GRID, linewidth=0.8)
    ax.tick_params(colors=_TEXT_2)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(_GRID)
    ax.legend(frameon=False, loc="upper left", ncol=4, fontsize=9, labelcolor=_TEXT_2)
    fig.tight_layout()
    fig.savefig(path, dpi=130, facecolor=_SURFACE)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchlist-only", action="store_true")
    args = parser.parse_args()
    setup_logging()
    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    watchlist = (
        [s.upper() for s in get_universe_config()["watchlist"]] if args.watchlist_only else None
    )
    frames = {s: f for s, f in market_store.frames_by_symbol(watchlist).items()
              if len(f) >= _MIN_BARS}
    if not frames:
        print("Kho gia rong - chay scripts/backfill_data.py truoc.")
        return

    started = time.time()
    horizons = sorted(set(_REPORT_HORIZONS + _DECAY_HORIZONS))
    panel = build_panel(frames, horizons)
    start = _broad_start(frames)
    panel = panel[panel["time"] >= start]
    panel = restrict_to_universe(panel, watchlist)
    log.info("Bang du lieu: %d dong (phien x ma), tu %s, %.0fs", len(panel), start.date(),
             time.time() - started)

    daily_frames, rows = [], []
    for factor, label in _FACTORS.items():
        for h in horizons:
            daily = ic.daily_rank_ic(panel, factor, f"fwd_{h}")
            daily_frames.append(daily.rename(f"{factor}_fwd_{h}"))
            summary = ic.summarise_ic(daily, horizon=h)
            if summary:
                rows.append({"Chi bao": label, "Horizon (phien)": h, **summary})
    summary = pd.DataFrame(rows)
    if summary.empty:
        print(f"Khong phien nao co >= {ic.MIN_CROSS_SECTION} ma trong vu tru - khong tinh "
              "duoc IC mat cat (danh sach theo doi qua it ma?).")
        return
    daily_all = pd.concat(daily_frames, axis=1).sort_index()
    names = panel.groupby("time")["symbol"].nunique().rename("so_ma")

    summary.to_csv(_OUT_DIR / "ic_summary.csv", index=False, encoding="utf-8-sig")
    daily_all.join(names).to_csv(_OUT_DIR / "ic_daily.csv", encoding="utf-8-sig")
    daily_all.groupby(daily_all.index.to_period("M")).mean().to_csv(
        _OUT_DIR / "ic_monthly.csv", encoding="utf-8-sig")
    plot_decay(summary, _OUT_DIR / "ic_decay.png")

    report = summary[summary["Horizon (phien)"].isin(_REPORT_HORIZONS)]
    pd.set_option("display.width", 200)
    print(f"\nKhoang: {daily_all.index.min().date()} -> {daily_all.index.max().date()}, "
          f"{len(daily_all)} phien, so ma/phien: trung vi {int(names.median())} "
          f"(min {names.min()}, max {names.max()})")
    print(report.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print(f"\nDa xuat {_OUT_DIR}/ic_summary.csv, ic_daily.csv, ic_monthly.csv, ic_decay.png")


if __name__ == "__main__":
    main()
