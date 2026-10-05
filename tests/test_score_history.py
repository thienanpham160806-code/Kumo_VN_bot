"""analysis/score_history.py phai cho DUNG ket qua cua recommend() chay tren
frame.iloc[:t+1] tai MOI phien t - va khong duoc nhin truoc tuong lai."""
import numpy as np
import pandas as pd
import pytest

from bot_phan_tich.analysis import scoring
from bot_phan_tich.analysis.score_history import score_history
from bot_phan_tich.config import get_settings


def _frame(n: int, seed: int, drift: float = 0.0005, vol: float = 0.02) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 50_000 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    # vai doan di ngang (gia khong doi) de thu cac truong hop hoa / dau bang 0
    close[100:106] = close[99]
    return pd.DataFrame(
        {
            "time": pd.bdate_range("2022-01-03", periods=n),
            "open": close * (1 + rng.normal(0, 0.005, n)),
            "high": close * (1 + rng.uniform(0, 0.02, n)),
            "low": close * (1 - rng.uniform(0, 0.02, n)),
            "close": close,
            "volume": rng.integers(100_000, 1_000_000, n).astype(float),
        }
    )


class _PresetSettings:
    def __init__(self, preset: str):
        self._inner = get_settings()
        self._preset = preset

    def get(self, key, default=None):
        if key == "indicators.ichimoku_preset":
            return self._preset
        return self._inner.get(key, default)


def _assert_matches_recommend(frame: pd.DataFrame, history: pd.DataFrame, start: int = 1):
    for t in range(start, len(frame)):
        rec = scoring.recommend(frame.iloc[: t + 1], "X")
        row = history.iloc[t]
        assert row["macd"] == pytest.approx(rec.component_scores["macd"], abs=1e-9), t
        assert row["rsi"] == pytest.approx(rec.component_scores["rsi"], abs=1e-9), t
        assert row["ichimoku"] == pytest.approx(rec.component_scores["ichimoku"], abs=1e-9), t
        assert row["total"] == pytest.approx(rec.total_score, abs=1e-9), t
        assert row["stop_loss"] == pytest.approx(rec.stop_loss, rel=1e-12), t
        assert row["target"] == pytest.approx(rec.target, rel=1e-12), t
        assert bool(row["vetoed"]) == rec.vetoed_by_kumo, t
        assert bool(row["bearish_divergence"]) == (rec.divergence.get("type") == "bearish"), t


@pytest.mark.parametrize("seed,drift", [(1, 0.0), (2, 0.002), (3, -0.002)])
def test_every_bar_matches_recommend_on_prefix(seed, drift):
    frame = _frame(260, seed, drift)
    _assert_matches_recommend(frame, score_history(frame))


def test_matches_recommend_with_5_day_ichimoku_preset(monkeypatch):
    monkeypatch.setattr(scoring, "get_settings", lambda: _PresetSettings("hieu_chinh_5ngay"))
    frame = _frame(200, seed=4)
    _assert_matches_recommend(frame, score_history(frame, ichimoku_preset="hieu_chinh_5ngay"))


def test_float32_input_like_market_store_matches():
    """Kho gia luu float32 - ket qua van phai khop (chi bao tinh tren cung dau vao)."""
    frame = _frame(200, seed=5)
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = frame[col].astype("float32")
    _assert_matches_recommend(frame, score_history(frame), start=60)


def test_no_look_ahead_future_bars_do_not_change_past_scores():
    """Thay toan bo du lieu SAU phien t bang du lieu khac hoan toan: diem tai
    moi phien <= t phai giu nguyen tung bit."""
    frame = _frame(300, seed=6)
    cut = 180
    other = _frame(300, seed=99)
    altered = pd.concat([frame.iloc[: cut + 1], other.iloc[cut + 1:]], ignore_index=True)
    altered["time"] = frame["time"]

    original = score_history(frame).iloc[: cut + 1]
    changed = score_history(altered).iloc[: cut + 1]
    pd.testing.assert_frame_equal(original, changed)
    assert not score_history(frame).iloc[cut + 1:].equals(score_history(altered).iloc[cut + 1:])
