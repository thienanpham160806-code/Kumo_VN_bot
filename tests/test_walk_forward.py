import numpy as np
import pandas as pd
import pytest

from bot_phan_tich.backtest import metrics
from bot_phan_tich.backtest.walk_forward import (
    DEFAULT_GRID,
    SignalCache,
    StrategyParams,
    walk_forward,
)

_A = StrategyParams(50, "goc_nhat_6ngay", 10)
_B = StrategyParams(70, "goc_nhat_6ngay", 10)


def _uptrend(start="2023-01-02", end="2024-01-01", seed=0) -> pd.DataFrame:
    """Gia tang deu ~0,3%/phien: lenh mua nao cung co lai."""
    days = pd.bdate_range(start, end, inclusive="left")
    rng = np.random.default_rng(seed)
    close = 20_000 * np.exp(np.cumsum(0.003 + rng.normal(0, 0.002, len(days))))
    return pd.DataFrame(
        {"time": days, "open": close * 0.999, "high": close * 1.004, "low": close * 0.996,
         "close": close, "volume": 5_000_000.0}
    )


def _signals_every(frame, every, start, end) -> pd.DataFrame:
    times = frame["time"][(frame["time"] >= start) & (frame["time"] < end)].iloc[::every]
    closes = frame.set_index("time").loc[times, "close"]
    return pd.DataFrame({"symbol": "AAA", "time": times.to_numpy(),
                         "stop_loss": (closes * 0.9).to_numpy(),
                         "target": (closes * 1.03).to_numpy()})


def test_parameters_are_chosen_on_train_window_only():
    """A chi co tin hieu trong cua so train, B chi co trong cua so test. Chon
    dung (chi nhin train) -> A; neu nhin truoc cua so test se chon B."""
    frame = _uptrend()
    train_end = pd.Timestamp("2023-10-02")
    signals = {
        _A: _signals_every(frame, 7, pd.Timestamp("2023-01-02"), train_end),
        _B: _signals_every(frame, 7, train_end, pd.Timestamp("2024-01-01")),
    }
    result = walk_forward(
        {"AAA": frame}, signals.__getitem__, grid=(_B, _A), train_months=9, test_months=3,
        start=pd.Timestamp("2023-01-02"), exchanges={"AAA": "HOSE"},
    )
    assert len(result.slices) == 1
    chosen = result.slices.iloc[0]
    assert chosen["buy_threshold"] == _A.buy_threshold
    assert chosen["Sharpe train"] > 0
    assert result.trades.empty  # A khong co tin hieu nao trong cua so test
    trials = result.trials.set_index("buy_threshold")["train_sharpe"]
    assert trials[_A.buy_threshold] > trials[_B.buy_threshold] == 0.0


def test_slice_metrics_cover_only_their_own_window_and_equity_is_stitched():
    frame = _uptrend("2022-01-03", "2024-01-01")
    signals = _signals_every(frame, 5, pd.Timestamp("2022-01-03"), pd.Timestamp("2024-01-01"))
    result = walk_forward(
        {"AAA": frame}, lambda params: signals, grid=(_A,), train_months=6, test_months=3,
        exchanges={"AAA": "HOSE"},
    )
    assert len(result.slices) == 6  # test: 2022-07 .. 2023-12, moi lat 3 thang

    for _, row in result.slices.iterrows():
        in_slice = result.equity[(result.equity.index >= pd.Timestamp(row["test_start"]))
                                 & (result.equity.index < pd.Timestamp(row["test_end"]))]
        assert row["So phien"] == len(in_slice)
        # CAGR cua lat tinh tren dung so phien cua lat (khong phai ca 2 nam)
        assert row["CAGR"] == pytest.approx(metrics.cagr(in_slice))
        assert row["Ti suat sinh loi tich luy"] == pytest.approx(
            in_slice.iloc[-1] / in_slice.iloc[0] - 1
        )
        assert row["Ti suat sinh loi tich luy"] > 0  # lat 3 thang cua xu huong tang

    # duong von ghep lien mach: khong trung ngay, lat sau bat dau tu von cuoi lat truoc
    assert result.equity.index.is_monotonic_increasing and result.equity.index.is_unique
    assert result.equity.index.min() == pd.Timestamp("2022-07-04")  # 03/07 la Chu nhat
    assert result.equity.iloc[0] == pytest.approx(100_000_000)
    assert result.equity.iloc[-1] > 100_000_000


def test_n_trials_is_grid_size_and_every_combo_is_tried_on_every_slice():
    frame = _uptrend("2022-01-03", "2023-07-03")
    signals = _signals_every(frame, 5, pd.Timestamp("2022-01-03"), pd.Timestamp("2024-01-01"))
    grid = DEFAULT_GRID[:4]
    result = walk_forward({"AAA": frame}, lambda params: signals, grid=grid, train_months=6,
                          test_months=3, exchanges={"AAA": "HOSE"})
    assert result.n_trials == 4
    assert len(result.trials) == 4 * len(result.slices)


def test_default_grid_has_12_distinct_combinations():
    assert len(DEFAULT_GRID) == 12
    assert len(set(DEFAULT_GRID)) == 12


def test_signal_cache_matches_generate_buy_signals():
    from bot_phan_tich.backtest.signals import generate_buy_signals

    rng = np.random.default_rng(3)
    n = 300
    close = 30_000 * np.exp(np.cumsum(rng.normal(0.001, 0.02, n)))
    frame = pd.DataFrame({"time": pd.bdate_range("2022-01-03", periods=n), "open": close,
                          "high": close * 1.02, "low": close * 0.98, "close": close,
                          "volume": 1e6})
    cache = SignalCache({"AAA": frame})
    for params in (_A, StrategyParams(60, "hieu_chinh_5ngay", 20)):
        expected = generate_buy_signals(frame, "AAA", buy_threshold=params.buy_threshold,
                                        ichimoku_preset=params.ichimoku_preset)
        pd.testing.assert_frame_equal(cache(params).reset_index(drop=True),
                                      expected.reset_index(drop=True))


def test_sharpe_report_uses_grid_size_as_n_trials():
    from bot_phan_tich.backtest import metrics

    frame = _uptrend("2022-01-03", "2023-07-03")
    dense = _signals_every(frame, 3, pd.Timestamp("2022-01-03"), pd.Timestamp("2024-01-01"))
    sparse = _signals_every(frame, 15, pd.Timestamp("2022-01-03"), pd.Timestamp("2024-01-01"))
    grid = (_A, _B, StrategyParams(60, "goc_nhat_6ngay", 20))
    lookup = {_A: dense, _B: sparse, grid[2]: dense.iloc[::2]}
    result = walk_forward({"AAA": frame}, lookup.__getitem__, grid=grid, train_months=6,
                          test_months=3, exchanges={"AAA": "HOSE"})
    report = result.sharpe_report()

    assert report["n_trials"] == 3
    per_day = result.trials["train_sharpe"] / np.sqrt(252)
    expected_var = per_day.groupby(result.trials["train_start"]).var(ddof=1).mean()
    assert report["sr_variance"] == pytest.approx(expected_var)
    assert report["dsr"] == pytest.approx(metrics.deflated_sharpe(
        report["sr"], 3, report["n_obs"], expected_var, report["skew"], report["kurtosis"]))
    assert 0.0 <= report["dsr"] <= report["psr"] <= 1.0


def test_universe_is_chosen_point_in_time_per_window():
    """universe_fn duoc goi voi as_of TRUOC moi cua so; ma ngoai vu tru luc do
    khong duoc giao dich du co tin hieu."""
    aaa = _uptrend("2022-01-03", "2023-07-03", seed=1)
    bbb = _uptrend("2022-01-03", "2023-07-03", seed=2)
    start, stop = pd.Timestamp("2022-01-03"), pd.Timestamp("2024-01-01")
    signals = pd.concat([_signals_every(aaa, 5, start, stop),
                         _signals_every(bbb, 5, start, stop).assign(symbol="BBB")])
    calls = []

    def universe_fn(as_of):
        calls.append(as_of)
        return frozenset({"AAA"}) if as_of < pd.Timestamp("2022-12-31") else frozenset({"BBB"})

    result = walk_forward({"AAA": aaa, "BBB": bbb}, lambda p: signals, grid=(_A,),
                          train_months=6, test_months=3,
                          exchanges={"AAA": "HOSE", "BBB": "HOSE"}, universe_fn=universe_fn)

    for _, row in result.slices.iterrows():
        assert pd.Timestamp(row["test_start"]) - pd.Timedelta(days=1) in calls
    trades = result.trades.assign(entry_time=pd.to_datetime(result.trades["entry_time"]))
    early = trades[trades["entry_time"] < pd.Timestamp("2023-01-01")]
    late = trades[trades["entry_time"] >= pd.Timestamp("2023-01-03")]
    assert set(early["symbol"]) == {"AAA"}
    assert set(late["symbol"]) == {"BBB"}
    assert all(as_of < pd.Timestamp(row) for as_of, row in zip(
        calls[1::2], result.slices["test_start"], strict=True))
