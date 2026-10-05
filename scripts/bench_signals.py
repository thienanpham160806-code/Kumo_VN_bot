"""Do toc do sinh tin hieu MUA lich su: ban cu O(n^2) (goi recommend() o tung
phien) so voi ban vectorized (analysis/score_history.py), tren 1 ma va tren
N ma that tu kho gia - dong thoi kiem tra hai ban cho tin hieu TRUNG KHOP.

Ket qua ghi vao docs/benchmark.md (ghi de).

Cach chay:
    python scripts/bench_signals.py                 # 1 ma (FPT) + 100 ma
    python scripts/bench_signals.py --symbols 20    # nhanh hon: 20 ma
    python scripts/bench_signals.py --no-write      # chi in, khong ghi docs/

LUU Y: ban cu mat ~15-20 giay moi ma 3 nam -> 100 ma mat khoang nua gio.
"""
from __future__ import annotations

import argparse
import platform
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from bot_phan_tich.backtest.signals import (  # noqa: E402
    generate_buy_signals,
    generate_buy_signals_reference,
)
from bot_phan_tich.data import market_store  # noqa: E402
from bot_phan_tich.logging_conf import setup_logging  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_OUT = _ROOT / "docs" / "benchmark.md"


def _same(new: pd.DataFrame, old: pd.DataFrame) -> bool:
    if new["time"].tolist() != old["time"].tolist():
        return False
    if new.empty:
        return True
    return bool(
        np.allclose(new["stop_loss"], old["stop_loss"], rtol=1e-12)
        and np.allclose(new["target"], old["target"], rtol=1e-12)
    )


def _time(fn, *args) -> tuple[float, pd.DataFrame]:
    started = time.perf_counter()
    result = fn(*args)
    return time.perf_counter() - started, result


def _most_liquid(frames: dict[str, pd.DataFrame], count: int, min_bars: int) -> list[str]:
    """N ma co gia tri giao dich TB lon nhat trong so ma du `min_bars` phien."""
    value = {
        sym: float((f["close"].astype(float) * f["volume"].astype(float)).mean())
        for sym, f in frames.items()
        if len(f) >= min_bars
    }
    return sorted(value, key=value.get, reverse=True)[:count]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--single", default="FPT", help="Ma dung cho phep do 1 ma")
    parser.add_argument("--symbols", type=int, default=100, help="So ma cho phep do nhieu ma")
    parser.add_argument("--no-write", action="store_true", help="Khong ghi docs/benchmark.md")
    args = parser.parse_args()
    setup_logging()

    frames = market_store.frames_by_symbol()
    if not frames:
        print("Kho gia rong - chay `python scripts/backfill_data.py` truoc.")
        return
    single = frames[args.single]
    many = _most_liquid(frames, args.symbols, min_bars=len(single))

    # ---- 1 ma: ban moi do 5 lan lay trung vi (nhanh, nhieu nhieu do), ban cu 1 lan
    new_runs = []
    for _ in range(5):
        elapsed, new_single = _time(generate_buy_signals, single, args.single)
        new_runs.append(elapsed)
    new_single_s = float(np.median(new_runs))
    old_single_s, old_single = _time(generate_buy_signals_reference, single, args.single)
    single_match = _same(new_single, old_single)
    print(f"1 ma ({args.single}, {len(single)} phien): cu {old_single_s:.2f}s, "
          f"moi {new_single_s * 1000:.1f}ms, khop={single_match}")

    # ---- N ma
    new_total = old_total = 0.0
    n_signals = 0
    mismatched: list[str] = []
    for k, sym in enumerate(many, 1):
        elapsed_new, new = _time(generate_buy_signals, frames[sym], sym)
        elapsed_old, old = _time(generate_buy_signals_reference, frames[sym], sym)
        new_total += elapsed_new
        old_total += elapsed_old
        n_signals += len(new)
        if not _same(new, old):
            mismatched.append(sym)
        print(f"[{k}/{len(many)}] {sym}: cu {elapsed_old:.1f}s, moi {elapsed_new * 1000:.0f}ms, "
              f"{len(new)} tin hieu, khop={sym not in mismatched}", flush=True)

    bars = int(np.mean([len(frames[s]) for s in many]))
    rows = [
        ("1 ma", args.single, len(single), old_single_s, new_single_s, len(new_single),
         "100%" if single_match else "KHONG KHOP"),
        (f"{len(many)} ma", "thanh khoan nhat", bars, old_total, new_total, n_signals,
         f"{len(many) - len(mismatched)}/{len(many)} ma khop 100%"),
    ]
    table = [
        "| Phep do | Ma | Phien/ma | Ban cu O(n^2) | Ban vectorized | Tang toc | Tin hieu | Khop |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for label, syms, n_bars, old_s, new_s, sigs, match in rows:
        table.append(
            f"| {label} | {syms} | {n_bars} | {old_s:,.1f} s | {new_s:,.2f} s | "
            f"{old_s / new_s:,.0f}x | {sigs} | {match} |"
        )
    print("\n".join(table))
    if mismatched:
        print("Ma KHONG khop:", ", ".join(mismatched))

    if args.no_write:
        return
    _OUT.write_text(
        "\n".join(
            [
                "# Benchmark: sinh tin hieu MUA lich su",
                "",
                "Sinh bang `python scripts/bench_signals.py` (khong sua tay).",
                "",
                f"- Ngay chay: {date.today():%Y-%m-%d}",
                f"- May: {platform.processor() or platform.machine()}, "
                f"{platform.system()} {platform.release()}",
                f"- Python {platform.python_version()}, pandas {pd.__version__}, "
                f"numpy {np.__version__}; chay don luong",
                "- Du lieu: kho gia that `data/market/ohlcv.parquet`; "
                f"{len(many)} ma co gia tri giao dich trung binh lon nhat",
                "",
                *table,
                "",
                "**Ban cu** (`generate_buy_signals_reference`): goi `recommend()` tren "
                "`frame.iloc[:i+1]` o moi phien i -> moi phien tinh lai moi chi bao "
                "tren toan bo lich su, O(n^2).",
                "",
                "**Ban vectorized** (`generate_buy_signals` -> `analysis/score_history.py`): "
                "tinh chi bao mot lan cho ca chuoi, suy ra trang thai tung phien, O(n) "
                "(phan ky: O(n log n) - vai phep tim nhi phan moi phien).",
                "",
                "**Khop**: cung danh sach phien co tin hieu; stop_loss/target lech "
                "tuong doi <= 1e-12 (do doc tinh bang cong thuc dong thay vi "
                "`np.polyfit`, sai so ~1e-13 diem).",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Da ghi {_OUT}")


if __name__ == "__main__":
    main()
