import numpy as np
import pandas as pd
import pytest
from scipy import stats

from bot_phan_tich.backtest import ic


def _panel(n_days=30, n_names=40, seed=0, signal=0.0):
    rng = np.random.default_rng(seed)
    rows = []
    for day in pd.bdate_range("2024-01-01", periods=n_days):
        score = rng.normal(size=n_names)
        ret = signal * score + rng.normal(size=n_names)
        rows += [{"time": day, "score": s, "fwd_5": r} for s, r in zip(score, ret, strict=True)]
    return pd.DataFrame(rows)


def test_rank_ic_matches_scipy_spearman_each_day():
    panel = _panel()
    panel.loc[panel.index[::7], "score"] = 1.0  # them gia tri trung nhau (hoa)
    daily = ic.daily_rank_ic(panel, "score", "fwd_5")
    for day, group in panel.groupby("time"):
        expected = stats.spearmanr(group["score"], group["fwd_5"]).statistic
        assert daily[day] == pytest.approx(expected, abs=1e-12)


def test_perfectly_predictive_factor_has_ic_one():
    panel = _panel()
    panel["fwd_5"] = panel["score"] * 0.01
    daily = ic.daily_rank_ic(panel, "score", "fwd_5")
    assert len(daily) == 30
    assert np.allclose(daily, 1.0)


def test_days_with_too_few_names_are_dropped():
    panel = _panel(n_names=10)
    assert ic.daily_rank_ic(panel, "score", "fwd_5", min_names=20).empty


def test_forward_returns_start_at_next_open():
    frame = pd.DataFrame({"open": [10.0, 11.0, 12.0, 15.0, 13.0]})
    fwd = ic.forward_open_returns(frame, [1, 2])
    # phien 0: mua mo cua phien 1 (11), ban mo cua phien 2 (12) / phien 3 (15)
    assert fwd["fwd_1"].iloc[0] == pytest.approx(12 / 11 - 1)
    assert fwd["fwd_2"].iloc[0] == pytest.approx(15 / 11 - 1)
    assert fwd["fwd_2"].iloc[2:].isna().all()


def test_newey_west_without_lags_is_plain_tstat():
    series = pd.Series(np.random.default_rng(1).normal(0.02, 0.1, 300))
    plain = series.mean() / (series.std(ddof=0) / np.sqrt(len(series)))
    assert ic.newey_west_tstat(series, lags=0) == pytest.approx(plain)


def test_newey_west_hand_computed():
    """x = [1, 2, 3, 4], mean 2.5, sai lech [-1.5, -0.5, 0.5, 1.5].
    g0 = (2.25 + 0.25 + 0.25 + 2.25)/4 = 1.25
    g1 = ((-0.5)(-1.5) + (0.5)(-0.5) + (1.5)(0.5))/4 = 1.25/4 = 0.3125
    L = 1 -> trong so 1 - 1/2 = 0.5; long_run = 1.25 + 2*0.5*0.3125 = 1.5625
    t = 2.5 / sqrt(1.5625/4) = 2.5 / 0.625 = 4.0"""
    assert ic.newey_west_tstat(pd.Series([1.0, 2.0, 3.0, 4.0]), lags=1) == pytest.approx(4.0)


def test_overlapping_ic_tstat_is_deflated_by_newey_west():
    """IC tu tuong quan duong (giong cua so chong lan) -> NW t-stat < t thuong."""
    rng = np.random.default_rng(2)
    noise = rng.normal(size=520)
    ic_series = pd.Series(0.01 + 0.05 * np.convolve(noise, np.ones(20) / 20, "same"),
                          index=pd.bdate_range("2024-01-01", periods=520))
    summary = ic.summarise_ic(ic_series, horizon=20)
    assert summary["t-stat Newey-West"] < summary["t-stat"]
    assert summary["ICIR"] == pytest.approx(ic_series.mean() / ic_series.std(ddof=1))
    assert 0.0 <= summary["Ti le thang IC>0"] <= 1.0


def test_predictive_factor_has_significant_positive_ic():
    daily = ic.daily_rank_ic(_panel(n_days=120, signal=0.3, seed=3), "score", "fwd_5")
    summary = ic.summarise_ic(daily, horizon=5)
    assert summary["IC trung binh"] > 0.15
    assert summary["t-stat Newey-West"] > 3
