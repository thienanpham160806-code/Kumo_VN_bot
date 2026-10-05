import pandas as pd
import pytest

from bot_phan_tich.config import Paths
from bot_phan_tich.data import market_store, universe


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    paths = Paths(data_dir=tmp_path, cache_db=tmp_path / "cache.sqlite3", model_dir=tmp_path)
    monkeypatch.setattr(market_store, "get_paths", lambda: paths)
    market_store._cache.clear()
    return paths


def _daily_rows(symbol: str, n: int, price: float, volume: float) -> list[list]:
    dates = pd.bdate_range("2023-01-02", periods=n)
    return [
        [symbol, d.strftime("%Y-%m-%d"), price, price * 1.01, price * 0.99, price, volume]
        for d in dates
    ]


def test_liquid_universe_empty_store_returns_empty_list(isolated_store):
    assert universe.liquid_universe() == []


def test_liquid_universe_filters_by_price_volume_and_history(isolated_store):
    rows = []
    rows += _daily_rows("AAA", 260, price=20_000, volume=200_000)   # dat het dieu kien
    rows += _daily_rows("BBB", 260, price=1_000, volume=200_000)    # gia qua thap
    rows += _daily_rows("CCC", 260, price=20_000, volume=5_000)     # khoi luong qua thap
    rows += _daily_rows("DDD", 50, price=20_000, volume=200_000)    # chua du so phien
    frame = pd.DataFrame(rows, columns=market_store.OHLCV_COLUMNS)
    market_store.save_ohlcv(frame, merge=False)
    market_store.save_symbols(
        pd.DataFrame(
            {"symbol": ["AAA", "BBB", "CCC", "DDD"], "exchange": ["HOSE"] * 4}
        )
    )

    result = universe.liquid_universe()
    assert result == ["AAA"]


def _seed_liquid(volumes: dict[str, float]) -> None:
    rows = []
    for symbol, volume in volumes.items():
        rows += _daily_rows(symbol, 260, price=20_000, volume=volume)
    market_store.save_ohlcv(pd.DataFrame(rows, columns=market_store.OHLCV_COLUMNS), merge=False)
    market_store.save_symbols(
        pd.DataFrame({"symbol": list(volumes), "exchange": ["HOSE"] * len(volumes)})
    )


def test_liquid_universe_max_symbols_keeps_most_liquid(isolated_store, monkeypatch):
    _seed_liquid({"LOW": 150_000, "HIGH": 900_000, "MID": 400_000})
    monkeypatch.setenv("UNIVERSE_MAX_SYMBOLS", "2")

    result = universe.liquid_universe()

    assert result == ["HIGH", "MID"]  # sap xep giam dan theo khoi luong TB 20 phien


def test_liquid_universe_max_symbols_zero_means_unlimited(isolated_store, monkeypatch):
    _seed_liquid({"AAA": 150_000, "BBB": 900_000, "CCC": 400_000})
    monkeypatch.setenv("UNIVERSE_MAX_SYMBOLS", "0")

    assert set(universe.liquid_universe()) == {"AAA", "BBB", "CCC"}


def test_liquid_universe_use_watchlist_bypasses_store(isolated_store, monkeypatch):
    monkeypatch.setattr(
        universe, "get_universe_config", lambda: {"watchlist": ["fpt", "vnm"]}
    )
    assert universe.liquid_universe(use_watchlist=True) == ["FPT", "VNM"]


# ------------------------------------------------ vu tru theo thoi diem (backtest)
def _rows_between(symbol, start, end, price, volume) -> list[list]:
    dates = pd.bdate_range(start, end)
    return [
        [symbol, d.strftime("%Y-%m-%d"), price, price * 1.01, price * 0.99, price, volume]
        for d in dates
    ]


def _seed(rows, symbols):
    market_store.save_ohlcv(pd.DataFrame(rows, columns=market_store.OHLCV_COLUMNS), merge=False)
    market_store.save_symbols(
        pd.DataFrame({"symbol": symbols, "exchange": ["HOSE"] * len(symbols)})
    )


def test_symbol_that_stopped_trading_is_not_in_later_universe(isolated_store):
    """STALE thanh khoan tot den 07/2024 roi ngung giao dich (huy niem yet).
    Vu tru thang 01/2026 khong duoc chua no chi vi 20 phien cuoi (nam 2024) dep."""
    rows = _rows_between("ALIVE", "2023-01-02", "2026-01-30", 20_000, 300_000)
    rows += _rows_between("STALE", "2023-01-02", "2024-07-31", 20_000, 900_000)
    _seed(rows, ["ALIVE", "STALE"])

    assert universe.liquid_universe(as_of=pd.Timestamp("2024-06-03").date()) == ["ALIVE", "STALE"]
    assert universe.liquid_universe(as_of=pd.Timestamp("2026-01-15").date()) == ["ALIVE"]


def test_universe_as_of_uses_only_data_up_to_that_date(isolated_store):
    """RISER khong thanh khoan nam 2023, rat thanh khoan tu 2025: vu tru tai
    2024-01 khong co RISER du hom nay no dat moi dieu kien."""
    rows = _rows_between("BASE", "2022-01-03", "2026-01-30", 20_000, 300_000)
    rows += _rows_between("RISER", "2022-01-03", "2024-12-31", 20_000, 5_000)
    rows += _rows_between("RISER", "2025-01-01", "2026-01-30", 20_000, 2_000_000)
    _seed(rows, ["BASE", "RISER"])

    assert universe.liquid_universe(as_of=pd.Timestamp("2024-01-02").date()) == ["BASE"]
    assert set(universe.liquid_universe(as_of=pd.Timestamp("2026-01-30").date())) == {
        "BASE", "RISER"}


def test_min_days_override_and_preloaded_frame(isolated_store):
    """Backtest truyen san du lieu (khong doc lai kho) va ha nguong so phien
    toi thieu xuong muc khoi dong chi bao (kho khong biet ngay niem yet that)."""
    rows = _rows_between("NEW", "2023-01-02", "2023-06-30", 20_000, 300_000)  # ~130 phien
    frame = pd.DataFrame(rows, columns=market_store.OHLCV_COLUMNS)
    frame["time"] = pd.to_datetime(frame["time"])
    market_store.save_symbols(pd.DataFrame({"symbol": ["NEW"], "exchange": ["HOSE"]}))

    as_of = pd.Timestamp("2023-06-30").date()
    assert universe.liquid_universe(as_of=as_of, ohlcv=frame) == []
    assert universe.liquid_universe(as_of=as_of, ohlcv=frame, min_days=60) == ["NEW"]
