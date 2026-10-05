"""PSR / DSR theo Bailey & Lopez de Prado (2014), doi chieu gia tri tinh tay."""
import math

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from bot_phan_tich.backtest import metrics

# Vi du so trong bai bao goc (Bailey & Lopez de Prado 2014, "The Deflated
# Sharpe Ratio", muc "A numerical example"): 100 lan thu, phuong sai Sharpe
# (nam) giua cac lan thu = 0.5, Sharpe nam tot nhat = 2.5, 5 nam du lieu ngay
# (T = 1250), skew = -3, kurtosis = 10. Bai bao ra SR0 ~ 0.1132 (theo ngay)
# va DSR ~ 0.9004.
_DAILY_SR = 2.5 / math.sqrt(250)
_DAILY_VAR = 0.5 / 250


def test_expected_max_sharpe_matches_paper_example():
    assert metrics.expected_max_sharpe(100, _DAILY_VAR) == pytest.approx(0.1132, abs=1e-4)


def test_deflated_sharpe_matches_paper_example():
    dsr = metrics.deflated_sharpe(
        observed=_DAILY_SR, n_trials=100, n_obs=1250, sr_variance=_DAILY_VAR,
        skew=-3.0, kurtosis=10.0,
    )
    assert dsr == pytest.approx(0.9004, abs=1e-4)


def test_psr_hand_computed():
    """SR = 0.1, T = 101, phan phoi chuan (skew 0, kurtosis 3):
    z = 0.1 * sqrt(100) / sqrt(1 + (3 - 1)/4 * 0.01) = 1 / sqrt(1.005) = 0.997509
    PSR = Phi(0.997509) = 0.840741"""
    assert metrics.probabilistic_sharpe(0.1, 101) == pytest.approx(0.840741, abs=1e-6)


def test_psr_penalises_negative_skew_and_fat_tails():
    normal = metrics.probabilistic_sharpe(0.1, 252)
    crash_prone = metrics.probabilistic_sharpe(0.1, 252, skew=-2.0, kurtosis=12.0)
    assert crash_prone < normal


def test_psr_against_its_own_sharpe_is_one_half():
    assert metrics.probabilistic_sharpe(0.07, 500, -0.5, 6.0, sr_benchmark=0.07) == 0.5


def test_dsr_is_a_probability_and_falls_with_more_trials():
    values = [
        metrics.deflated_sharpe(0.08, n, 750, sr_variance=0.002, skew=-0.4, kurtosis=5.0)
        for n in (1, 2, 12, 100, 1000)
    ]
    assert all(0.0 <= v <= 1.0 for v in values)
    assert values == sorted(values, reverse=True)
    # 1 lan thu = khong co thien lech chon loc -> DSR = PSR(0)
    assert values[0] == pytest.approx(metrics.probabilistic_sharpe(0.08, 750, -0.4, 5.0))


def test_sharpe_moments_use_raw_kurtosis():
    rng = np.random.default_rng(0)
    returns = pd.Series(rng.standard_t(df=5, size=2000) * 0.01 + 0.0005)
    moments = metrics.sharpe_moments(returns)
    assert moments["n_obs"] == 2000
    assert moments["sr"] == pytest.approx(returns.mean() / returns.std(ddof=1))
    assert moments["skew"] == pytest.approx(stats.skew(returns))
    assert moments["kurtosis"] == pytest.approx(stats.kurtosis(returns) + 3.0)
    assert moments["kurtosis"] > 3.0  # Student-t duoi day hon phan phoi chuan
