import numpy as np
import pandas as pd
import pytest

from bot_phan_tich.backtest import metrics
from bot_phan_tich.backtest.engine import run
from bot_phan_tich.backtest.signals import SIGNAL_COLUMNS, generate_buy_signals


def _uptrend_frame(n=200, seed=5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 50 * np.exp(np.cumsum(rng.normal(0.003, 0.012, n)))
    return pd.DataFrame(
        {
            "time": pd.date_range("2023-01-02", periods=n, freq="B"),
            "open": close * (1 + rng.normal(0, 0.002, n)),
            "high": close * (1 + rng.uniform(0.001, 0.01, n)),
            "low": close * (1 - rng.uniform(0.001, 0.01, n)),
            "close": close,
            "volume": rng.integers(100_000, 500_000, n).astype(float),
        }
    )


def test_generate_buy_signals_returns_expected_columns():
    frame = _uptrend_frame()
    signals = generate_buy_signals(frame, "FPT")
    assert list(signals.columns) == SIGNAL_COLUMNS
    if not signals.empty:
        assert (signals["symbol"] == "FPT").all()
        assert (signals["stop_loss"] < signals["target"]).all()


def test_generate_buy_signals_only_uses_data_up_to_each_bar():
    """Khong nhin truoc tuong lai: tin hieu tai phien i phai giong nhau du
    frame co bi cat ngan sau phien i bao nhieu di nua."""
    frame = _uptrend_frame(n=220)
    full_signals = generate_buy_signals(frame, "FPT")

    cutoff = 150
    truncated = frame.iloc[:cutoff].reset_index(drop=True)
    truncated_signals = generate_buy_signals(truncated, "FPT")

    early_full = full_signals[full_signals["time"] < frame["time"].iloc[cutoff]]
    pd.testing.assert_frame_equal(
        early_full.reset_index(drop=True), truncated_signals.reset_index(drop=True)
    )


def test_signals_feed_into_backtest_engine_and_produce_valid_report():
    frame = _uptrend_frame(n=260)
    signals = generate_buy_signals(frame, "FPT")
    if signals.empty:
        return  # du lieu ngau nhien co the khong sinh tin hieu nao, bo qua an toan

    result = run({"FPT": frame}, signals, initial_capital=100_000_000)
    stats = metrics.summarise(result.equity, result.trades)

    assert not result.equity.empty
    assert "CAGR" in stats
    assert "Sut giam toi da" in stats


# ---------------------------------------------- ban vectorized == ban O(n^2) cu
def _volatile_frame(n: int, seed: int) -> pd.DataFrame:
    """Gia dao dong manh, co ca xu huong tang/giam xen ke - de sinh nhieu tin
    hieu MUA (bai test khong duoc "dung" vi khong co tin hieu nao)."""
    rng = np.random.default_rng(seed)
    regime = np.repeat(rng.choice([-0.004, 0.0, 0.006], size=n // 40 + 1), 40)[:n]
    close = 30_000 * np.exp(np.cumsum(rng.normal(regime, 0.02, n)))
    return pd.DataFrame(
        {
            "time": pd.bdate_range("2021-01-04", periods=n),
            "open": close * (1 + rng.normal(0, 0.005, n)),
            "high": close * (1 + rng.uniform(0.001, 0.025, n)),
            "low": close * (1 - rng.uniform(0.001, 0.025, n)),
            "close": close,
            "volume": rng.integers(100_000, 2_000_000, n).astype(float),
        }
    )


@pytest.mark.parametrize("seed", [11, 12, 13])
@pytest.mark.parametrize("min_gap", [1, 5])
def test_vectorized_signals_match_reference_100_percent(seed, min_gap):
    from bot_phan_tich.backtest.signals import generate_buy_signals_reference

    frame = _volatile_frame(320, seed)
    new = generate_buy_signals(frame, "AAA", min_gap=min_gap)
    old = generate_buy_signals_reference(frame, "AAA", min_gap=min_gap)

    assert len(old) > 0, "du lieu gia phai sinh duoc tin hieu de phep so sanh co y nghia"
    assert new["time"].tolist() == old["time"].tolist()
    assert (new["symbol"] == old["symbol"]).all()
    np.testing.assert_allclose(new["stop_loss"], old["stop_loss"], rtol=1e-12)
    np.testing.assert_allclose(new["target"], old["target"], rtol=1e-12)


def test_vectorized_signals_are_fast_on_three_years():
    """3 nam (~750 phien) mot ma: ban cu mat ~11 giay; ban moi phai < 2 giay
    (nguong rong de khong chap chon tren may CI cham)."""
    import time

    frame = _volatile_frame(750, seed=21)
    started = time.perf_counter()
    generate_buy_signals(frame, "AAA")
    assert time.perf_counter() - started < 2.0
