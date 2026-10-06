import numpy as np
import pandas as pd
import pytest

from bot_phan_tich.backtest import metrics


def test_sortino_hand_computed():
    """r = [0.02, -0.01, 0.03, -0.02]; mean = 0.005
    downside = sqrt((0 + 0.0001 + 0 + 0.0004) / 4) = sqrt(0.000125) = 0.0111803
    Sortino = 0.005 / 0.0111803 * sqrt(252) = 7.0993"""
    returns = pd.Series([0.02, -0.01, 0.03, -0.02])
    assert metrics.sortino(returns) == pytest.approx(0.005 / np.sqrt(0.000125) * np.sqrt(252))
    assert metrics.sortino(returns) == pytest.approx(7.0993, abs=1e-4)


def test_sortino_ignores_upside_volatility():
    calm = pd.Series([0.01, -0.005] * 50)
    wild_upside = pd.Series([0.05, -0.005, -0.03, 0.025] * 25)
    assert metrics.sortino(calm) > metrics.sharpe(calm)
    assert metrics.sortino(pd.Series([0.01, 0.02])) == 0.0  # khong co ky giam
    assert np.isfinite(metrics.sortino(wild_upside))


def test_turnover_hand_computed():
    """Mua 100 tr + ban 110 tr trong 1 nam (252 phien), von binh quan 200 tr:
    (100 + 110) / 2 / 200 / 1 = 0.525 lan/nam."""
    trades = pd.DataFrame({"entry": [10_000.0], "exit": [11_000.0], "shares": [10_000]})
    equity = pd.Series(np.full(252, 200_000_000.0))
    assert metrics.turnover(trades, equity) == pytest.approx(0.525)
    assert metrics.turnover(pd.DataFrame(), equity) == 0.0


def test_summarise_reports_sortino_and_turnover():
    equity = pd.Series(np.linspace(100, 110, 50))
    trades = pd.DataFrame({"entry": [10.0], "exit": [11.0], "shares": [1], "return": [0.1],
                           "r_multiple": [1.0]})
    stats = metrics.summarise(equity, trades)
    assert {"Ti so Sortino", "Vong quay (lan/nam)"} <= set(stats)
    assert "Ti so Sortino: " in metrics.format_report(stats)
