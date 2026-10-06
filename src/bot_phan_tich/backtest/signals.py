"""Sinh tin hieu MUA lich su tu analysis/scoring.py de dua vao backtest/engine.py.

Giai quyet van de: backtest/engine.py:run() chi biet CHAY tren mot DataFrame
tin hieu (symbol, time, stop_loss, target) co san - no khong tu sinh tin
hieu. Tin hieu MUA tai phien i la ket qua cua recommend(frame.iloc[: i + 1]).

Ban hien tai (generate_buy_signals) KHONG goi recommend() o tung phien nua
ma dung analysis/score_history.py: tinh chi bao mot lan cho ca chuoi roi suy
ra trang thai tung phien - O(n) thay vi O(n^2). Ban cu duoc giu lai nguyen
van (generate_buy_signals_reference) lam chuan doi chieu: test va
scripts/bench_signals.py chung minh hai ban cho tin hieu trung khop 100%.

Chong nhin truoc tuong lai (look-ahead bias): trang thai tai phien i chi
dung du lieu den phien i - xem docstring analysis/score_history.py va
tests/test_backtest_signals.py (cat ngan chuoi sau phien i khong lam doi tin
hieu truoc do).
"""
from __future__ import annotations

import pandas as pd

from ..analysis.score_history import score_history
from ..analysis.scoring import ACTION_BUY, recommend
from ..config import get_settings
from ..logging_conf import get_logger

log = get_logger(__name__)

_MIN_BARS = 60
SIGNAL_COLUMNS = ["symbol", "time", "stop_loss", "target"]


def signals_from_scores(
    scores: pd.DataFrame,
    symbol: str,
    buy_threshold: float | None = None,
    min_gap: int = 5,
) -> pd.DataFrame:
    """Tu bang diem theo phien (score_history) -> tin hieu MUA.

    MUA khi diem tong >= nguong MUA va KHONG bi may Kumo phu quyet (giong
    _map_action + quy tac veto trong recommend()). Bo qua `_MIN_BARS` phien
    dau (chi bao chua du du lieu khoi dong). `min_gap`: so phien toi thieu
    giua hai tin hieu lien tiep cua CUNG mot ma.

    Tach rieng de walk-forward thu nhieu nguong MUA tren cung mot bang diem.
    """
    if buy_threshold is None:
        buy_threshold = get_settings().get("scoring.thresholds.buy", 60)
    if len(scores) <= _MIN_BARS:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)

    is_buy = (scores["total"] >= buy_threshold) & ~scores["vetoed"]
    is_buy.iloc[:_MIN_BARS] = False

    picked: list[int] = []
    last_hit = -min_gap
    for i in is_buy.to_numpy().nonzero()[0]:
        if i - last_hit >= min_gap:
            picked.append(int(i))
            last_hit = i

    rows = scores.iloc[picked]
    return pd.DataFrame(
        {
            "symbol": symbol,
            "time": rows["time"].to_numpy(),
            "stop_loss": rows["stop_loss"].to_numpy(),
            "target": rows["target"].to_numpy(),
        },
        columns=SIGNAL_COLUMNS,
    )


def generate_buy_signals(
    frame: pd.DataFrame,
    symbol: str,
    min_gap: int = 5,
    buy_threshold: float | None = None,
    ichimoku_preset: str | None = None,
) -> pd.DataFrame:
    """Moi phien trong qua khu ma recommend() se cho khuyen nghi MUA.

    Tra ve DataFrame dung dinh dang backtest/engine.py:run() can (cot
    SIGNAL_COLUMNS), rong neu khong co tin hieu nao hoac du lieu qua ngan.
    `buy_threshold`/`ichimoku_preset`: None = theo config (giong recommend()).
    """
    if len(frame) < _MIN_BARS:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)
    scores = score_history(frame, ichimoku_preset=ichimoku_preset)
    return signals_from_scores(scores, symbol, buy_threshold, min_gap)


def generate_buy_signals_reference(
    frame: pd.DataFrame, symbol: str, min_gap: int = 5
) -> pd.DataFrame:
    """Ban CU, O(n^2): goi recommend() tren frame.iloc[: i + 1] o tung phien.

    Khong dung trong he thong - chi giu lam chuan doi chieu cho
    generate_buy_signals() (tests/test_backtest_signals.py) va do toc do
    (scripts/bench_signals.py).
    """
    if len(frame) < _MIN_BARS:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)

    rows: list[dict] = []
    last_hit = -min_gap
    for i in range(_MIN_BARS, len(frame)):
        if i - last_hit < min_gap:
            continue
        window = frame.iloc[: i + 1]
        try:
            rec = recommend(window, symbol)
        except Exception as exc:
            log.debug("generate_buy_signals_reference(%s) loi tai phien %d: %s", symbol, i, exc)
            continue
        if rec.action == ACTION_BUY:
            rows.append(
                {
                    "symbol": symbol,
                    "time": frame["time"].iloc[i],
                    "stop_loss": rec.stop_loss,
                    "target": rec.target,
                }
            )
            last_hit = i

    return pd.DataFrame(rows, columns=SIGNAL_COLUMNS)


def generate_signals_for_universe(
    price_frames: dict[str, pd.DataFrame],
    min_gap: int = 5,
    buy_threshold: float | None = None,
    ichimoku_preset: str | None = None,
) -> pd.DataFrame:
    """Ap generate_buy_signals() cho nhieu ma, gop thanh mot DataFrame tin hieu
    duy nhat - dau vao truc tiep cho backtest/engine.py:run() va walk_forward.py.
    """
    frames = []
    for symbol, frame in price_frames.items():
        try:
            frames.append(
                generate_buy_signals(frame, symbol, min_gap, buy_threshold, ichimoku_preset)
            )
        except Exception as exc:
            log.warning("generate_signals_for_universe: bo qua %s do loi: %s", symbol, exc)
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)
    return pd.concat(frames, ignore_index=True)
