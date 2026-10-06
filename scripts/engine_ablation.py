"""Do anh huong cua tung sua doi engine (T+2, gap, ket san...) tren du lieu that:
chay CUNG MOT bo tin hieu qua engine o nhieu phien ban git khac nhau.

Moi phien ban duoc lay bang git worktree, roi chay trong tien trinh rieng voi
PYTHONPATH tro vao src/ cua worktree do. Tin hieu, gia va khoang thoi gian co
dinh (sinh bang code hien tai: tham so mac dinh, vu tru theo thoi diem), nen
moi khac biet giua cac dong deu do engine.

Cach chay (tu thu muc goc repo):
    git worktree add ../abl-main main
    git worktree add ../abl-t2 <commit T+2>
    ...
    python scripts/engine_ablation.py main=../abl-main t2=../abl-t2 ... head=.
Ket qua: outputs/backtest/engine_ablation.csv (va in ra man hinh).
"""
from __future__ import annotations

import json
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_WORKER = r'''
import json, pickle, sys
sys.path.insert(0, sys.argv[1])
import pandas as pd
from bot_phan_tich.backtest import engine, metrics
frames, signals, start, end, exchanges = pickle.load(open(sys.argv[2], "rb"))
kwargs = {"initial_capital": 100_000_000, "max_hold_days": 20}
params = engine.run.__code__.co_varnames[: engine.run.__code__.co_argcount]
if "exchanges" in params:
    kwargs["exchanges"] = exchanges
if "start" in params:
    kwargs.update(start=start, end=end, close_at_end=True)
else:
    signals = signals[(signals["time"] >= start) & (signals["time"] < end)]
result = engine.run(frames, signals, **kwargs)
equity = result.equity[(result.equity.index >= start) & (result.equity.index < end)]
trades = result.trades
stats = metrics.summarise(equity, trades)
returns = equity.pct_change().dropna()
print(json.dumps({
    "Loi nhuan tich luy": stats["Ti suat sinh loi tich luy"],
    "CAGR": stats["CAGR"],
    "Sharpe": stats["Ti so Sharpe"],
    "Sut giam toi da": stats["Sut giam toi da"],
    "So lenh": int(len(trades)),
    "Ti le thang": stats["Ti le thang"],
    "Loi nhuan TB/lenh": float(trades["return"].mean()) if len(trades) else None,
    "Ban ngay lam viec ke tiep": int(sum(
        1 for _, t in trades.iterrows()
        if len(pd.bdate_range(t["entry_time"], t["exit_time"])) == 2
    )) if len(trades) else 0,
}))
'''


def _dump(path: Path) -> None:
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "scripts"))
    import pandas as pd
    import run_backtest as rb

    from bot_phan_tich.data import market_store

    frames = rb._load_frames(None)
    universe_fn = rb._universe_fn(None)
    start = rb._default_start(frames)
    signals = rb._point_in_time(rb.SignalCache(frames)(rb._default_params()), universe_fn)
    end = max(f["time"].max() for f in frames.values()) + pd.Timedelta(days=1)
    traded = set(signals["symbol"])
    frames = {s: f for s, f in frames.items() if s in traded}
    meta = market_store.load_symbols()
    exchanges = dict(zip(meta["symbol"].astype(str), meta["exchange"].astype(str), strict=True))
    pickle.dump((frames, signals, start, end, exchanges), open(path, "wb"))
    print(f"{len(signals)} tin hieu, {len(frames)} ma, {start.date()} -> {end.date()}")


def main() -> None:
    import pandas as pd

    versions = dict(arg.split("=", 1) for arg in sys.argv[1:])
    if not versions:
        print(__doc__)
        return
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "input.pkl"
        _dump(data)
        worker = Path(tmp) / "worker.py"
        worker.write_text(_WORKER, encoding="utf-8")
        rows = []
        for label, src in versions.items():
            src_dir = str((Path(src) / "src").resolve())
            out = subprocess.run([sys.executable, str(worker), src_dir, str(data)],
                                 capture_output=True, text=True, check=True, cwd=ROOT)
            rows.append({"Phien ban": label, **json.loads(out.stdout.strip().splitlines()[-1])})
            print(rows[-1], flush=True)
    table = pd.DataFrame(rows)
    out_path = ROOT / "outputs" / "backtest" / "engine_ablation.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
