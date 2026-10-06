"""Vi cau truc thi truong Viet Nam trong backtest/engine.py.

Moi test dung mot ma duy nhat voi vai phien dung tay, tin hieu MUA o phien 0
-> vao lenh o gia mo cua phien 1 (T). Cac phien sau duoc dat sao cho dung mot
quy tac (T+2, gap, gia san) quyet dinh ket qua.
"""
import pandas as pd
import pytest

from bot_phan_tich.backtest.engine import run
from bot_phan_tich.data import market_store

_VOLUME = 10_000_000.0  # du lon de max_participation khong chan khoi luong


def _symbols(exchange: str):
    return lambda: pd.DataFrame({"symbol": ["AAA"], "exchange": [exchange]})


@pytest.fixture(autouse=True)
def _hose_listing(monkeypatch):
    """Khong phu thuoc data/market/symbols.parquet tren may: AAA mac dinh la HOSE."""
    monkeypatch.setattr(market_store, "load_symbols", _symbols("HOSE"))


def _frame(bars: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """bars: danh sach (open, high, low, close), moi phan tu la mot phien."""
    return pd.DataFrame(
        {
            "time": pd.bdate_range("2024-01-01", periods=len(bars)),
            "open": [b[0] for b in bars],
            "high": [b[1] for b in bars],
            "low": [b[2] for b in bars],
            "close": [b[3] for b in bars],
            "volume": [_VOLUME] * len(bars),
        }
    )


def _signal(frame: pd.DataFrame, stop: float, target: float) -> pd.DataFrame:
    return pd.DataFrame(
        {"symbol": ["AAA"], "time": [frame["time"].iloc[0]], "stop_loss": [stop],
         "target": [target]}
    )


def _run(frame, signals, **kwargs):
    kwargs.setdefault("max_hold_days", 100)
    return run({"AAA": frame}, signals, initial_capital=100_000_000, **kwargs)


# ------------------------------------------------------------------ 1. T+2
def test_cannot_sell_on_t_plus_1_even_if_stop_is_hit():
    """Mua o phien 1 (T). Phien 2 (T+1) thung stop nhung chua ve tai khoan ->
    KHONG duoc ban. Phien 3 (T+2) gia hoi phuc tren stop -> lenh van mo."""
    frame = _frame(
        [
            (100, 101, 99, 100),   # 0: phien co tin hieu
            (100, 101, 99, 100),   # 1: T   - vao lenh gia mo cua 100
            (99, 99, 90, 92),      # 2: T+1 - low 90 < stop 95, nhung chua ban duoc
            (98, 99, 96, 98),      # 3: T+2 - ban duoc, nhung khong con cham stop
            (98, 99, 97, 98),      # 4
        ]
    )
    result = _run(frame, _signal(frame, stop=95, target=130))
    assert result.trades.empty, "Lenh bi dong o T+1 - vi pham chu ky thanh toan T+2"


def test_can_sell_from_t_plus_2():
    frame = _frame(
        [
            (100, 101, 99, 100),
            (100, 101, 99, 100),   # T
            (99, 100, 97, 99),     # T+1
            (98, 99, 94, 95),      # T+2 - cham stop 95, duoc ban
            (95, 96, 94, 95),
        ]
    )
    result = _run(frame, _signal(frame, stop=95, target=130))
    assert len(result.trades) == 1
    assert result.trades["exit_time"].iloc[0] == frame["time"].iloc[3]


def test_settlement_days_follow_trading_sessions_not_weekdays():
    """Nghi le giua tuan (khong co phien) khong duoc tinh vao T+2: chi dem
    phien giao dich co trong lich, khong dem ngay trong tuan."""
    frame = _frame(
        [
            (100, 101, 99, 100),
            (100, 101, 99, 100),   # T (thu Ba)
            (99, 99, 90, 92),      # T+1 phien (sau 2 ngay nghi le)
            (98, 99, 96, 98),      # T+2
        ]
    )
    # Bo thu Tu, thu Nam (nghi le): T la thu Ba, phien ke tiep la thu Sau.
    frame["time"] = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-05", "2024-01-08"])
    result = _run(frame, _signal(frame, stop=95, target=130))
    assert result.trades.empty


@pytest.mark.parametrize("settlement", [1, 3])
def test_settlement_days_read_from_config(monkeypatch, settlement):
    from bot_phan_tich.risk import constraints

    monkeypatch.setattr(constraints, "settlement_days", lambda: settlement)
    frame = _frame(
        [
            (100, 101, 99, 100),
            (100, 101, 99, 100),   # T
            (99, 99, 94, 95),      # T+1 cham stop
            (95, 96, 94, 95),      # T+2 cham stop
            (95, 96, 94, 95),      # T+3 cham stop
        ]
    )
    result = _run(frame, _signal(frame, stop=95, target=130))
    assert result.trades["exit_time"].iloc[0] == frame["time"].iloc[1 + settlement]


# ------------------------------------------------------------- 2. gap qua stop/target
def test_gap_down_below_stop_fills_at_open_not_at_stop():
    """Mo cua 88 da thung stop 95 -> lenh dung lo khop o 88, khong phai 95."""
    frame = _frame(
        [
            (100, 101, 99, 100),
            (100, 101, 99, 100),   # T
            (100, 101, 99, 100),   # T+1
            (88, 90, 86, 89),      # T+2: gap xuong duoi stop
            (89, 90, 88, 89),
        ]
    )
    result = _run(frame, _signal(frame, stop=95, target=130))
    trade = result.trades.iloc[0]
    assert trade["exit"] == pytest.approx(88)
    assert trade["exit_time"] == frame["time"].iloc[3]


def test_gap_up_above_target_fills_at_open_not_at_target():
    """Mo cua 125 da vuot target 110 -> chot loi o 125 (gia thi truong luc mo cua)."""
    frame = _frame(
        [
            (100, 101, 99, 100),
            (100, 101, 99, 100),
            (100, 101, 99, 100),
            (125, 128, 122, 126),  # T+2: gap len tren target
            (126, 127, 125, 126),
        ]
    )
    result = _run(frame, _signal(frame, stop=95, target=110))
    trade = result.trades.iloc[0]
    assert trade["exit"] == pytest.approx(125)


def test_intraday_touch_without_gap_still_fills_at_level():
    frame = _frame(
        [
            (100, 101, 99, 100),
            (100, 101, 99, 100),
            (100, 101, 99, 100),
            (99, 100, 93, 96),     # mo cua tren stop, trong phien cham stop
            (96, 97, 95, 96),
        ]
    )
    result = _run(frame, _signal(frame, stop=95, target=130))
    assert result.trades.iloc[0]["exit"] == pytest.approx(95)


# ------------------------------------------------------------ 3. ket gia san
# Gia tham chieu 20.000 -> san HOSE = 18.600 (-7%), san HNX = 18.000 (-10%).
_LOCKED_AT_FLOOR = (18_600, 18_600, 18_600, 18_600)


def _floor_frame(*after_t2):
    return _frame(
        [
            (20_000, 20_100, 19_900, 20_000),
            (20_000, 20_100, 19_900, 20_000),   # T
            (20_000, 20_100, 19_900, 20_000),   # T+1
            *after_t2,
        ]
    )


def test_stop_on_floor_locked_session_is_deferred_to_next_session():
    """T+2 dong cua o gia san va low == san -> khong ai mua, khong ban duoc.
    Lenh ban doi sang phien sau, khop o gia mo cua phien do."""
    frame = _floor_frame(_LOCKED_AT_FLOOR, (17_400, 17_800, 17_300, 17_500), (17_500,) * 4)
    result = _run(frame, _signal(frame, stop=19_000, target=30_000))
    trade = result.trades.iloc[0]
    assert trade["exit_time"] == frame["time"].iloc[4]
    assert trade["exit"] == pytest.approx(17_400)


def test_consecutive_floor_locks_keep_deferring():
    # san phien 4: 18.600 * 0.93 = 17.298 -> lam tron len buoc gia 50 = 17.300
    frame = _floor_frame(
        _LOCKED_AT_FLOOR, (17_300,) * 4, (16_500, 16_900, 16_400, 16_800), (16_800,) * 4
    )
    result = _run(frame, _signal(frame, stop=19_000, target=30_000))
    trade = result.trades.iloc[0]
    assert trade["exit_time"] == frame["time"].iloc[5]
    assert trade["exit"] == pytest.approx(16_500)


def test_floor_uses_exchange_band_from_symbols_data(monkeypatch):
    """-7% la gia san cua HOSE nhung KHONG phai cua HNX (bien do 10%): ma HNX
    van ban duoc ngay trong phien do."""
    monkeypatch.setattr(market_store, "load_symbols", _symbols("HNX"))
    frame = _floor_frame(_LOCKED_AT_FLOOR, (17_400, 17_800, 17_300, 17_500))
    result = _run(frame, _signal(frame, stop=19_000, target=30_000))
    trade = result.trades.iloc[0]
    assert trade["exit_time"] == frame["time"].iloc[3]
    assert trade["exit"] == pytest.approx(18_600)


def test_explicit_exchange_mapping_overrides_symbols_data():
    frame = _floor_frame(_LOCKED_AT_FLOOR, (17_400, 17_800, 17_300, 17_500))
    result = _run(frame, _signal(frame, stop=19_000, target=30_000), exchanges={"AAA": "HNX"})
    assert result.trades.iloc[0]["exit_time"] == frame["time"].iloc[3]


def test_close_at_floor_but_low_below_close_is_not_locked():
    """low < close nghia la da co giao dich duoi gia dong cua -> khong phai
    trang thai trang ben mua o gia san."""
    frame = _floor_frame((18_900, 19_000, 18_600, 18_700), (18_700,) * 4)
    result = _run(frame, _signal(frame, stop=19_000, target=30_000))
    assert result.trades.iloc[0]["exit_time"] == frame["time"].iloc[3]


# --------------------------------------------- dinh gia, cua so, dong vi the cuoi ky
def test_missing_bar_is_valued_at_last_close_not_entry_price():
    """BBB khong co phien ngay 3 (tam ngung giao dich): danh muc phai dinh gia
    BBB theo gia dong cua gan nhat (120), khong phai gia vao lenh (100)."""
    days = pd.bdate_range("2024-01-01", periods=5)
    aaa = pd.DataFrame({"time": days, "open": 50.0, "high": 51.0, "low": 49.0, "close": 50.0,
                        "volume": _VOLUME})
    bbb = pd.DataFrame(
        {
            "time": days[[0, 1, 2, 4]],
            "open": [100.0, 100.0, 118.0, 121.0],
            "high": [101.0, 121.0, 122.0, 122.0],
            "low": [99.0, 99.0, 117.0, 120.0],
            "close": [100.0, 120.0, 120.0, 121.0],
            "volume": _VOLUME,
        }
    )
    signals = pd.DataFrame({"symbol": ["BBB"], "time": [days[0]], "stop_loss": [90.0],
                            "target": [200.0]})
    result = run({"AAA": aaa, "BBB": bbb}, signals, initial_capital=100_000_000,
                 max_hold_days=100)
    assert result.equity[days[3]] == pytest.approx(result.equity[days[2]])


def test_window_limits_equity_and_signals_to_start_end():
    frame = _frame([(100, 101, 99, 100)] * 30)
    start, end = frame["time"].iloc[10], frame["time"].iloc[20]
    signals = pd.DataFrame(
        {"symbol": ["AAA", "AAA"], "time": [frame["time"].iloc[5], frame["time"].iloc[12]],
         "stop_loss": [95.0, 95.0], "target": [130.0, 130.0]}
    )
    result = _run(frame, signals, start=start, end=end, max_hold_days=3)
    assert result.equity.index.min() == start
    assert result.equity.index.max() == frame["time"].iloc[19]
    assert result.equity.iloc[0] == pytest.approx(100_000_000)
    assert result.trades["entry_time"].tolist() == [frame["time"].iloc[13]]


def test_close_at_end_liquidates_and_skips_unsellable_late_entries():
    frame = _frame([(100, 101, 99, 100)] * 12)
    signals = pd.DataFrame(
        {"symbol": ["AAA", "AAA"], "time": [frame["time"].iloc[2], frame["time"].iloc[9]],
         "stop_loss": [95.0, 95.0], "target": [130.0, 130.0]}
    )
    result = _run(frame, signals, close_at_end=True)
    # tin hieu phien 9 -> vao phien 10, chua kip T+2 truoc phien cuoi (11): bo qua
    assert len(result.trades) == 1
    assert result.trades["reason"].iloc[0] == "Dong vi the cuoi giai doan"
    assert result.trades["exit_time"].iloc[0] == frame["time"].iloc[11]
    fee, tax = 0.0025, 0.001
    shares = result.trades["shares"].iloc[0]
    expected = 100_000_000 - shares * 100 * (fee / 2) - shares * 100 * (fee / 2 + tax)
    assert result.equity.iloc[-1] == pytest.approx(expected)


def test_fee_rate_override():
    frame = _frame([(100, 101, 99, 100)] * 3 + [(100, 131, 99, 120)] * 2)
    signals = _signal(frame, stop=95, target=130)
    cheap = _run(frame, signals, fee_rate=0.0015).trades["pnl"].iloc[0]
    costly = _run(frame, signals, fee_rate=0.0035).trades["pnl"].iloc[0]
    shares = _run(frame, signals).trades["shares"].iloc[0]
    assert cheap - costly == pytest.approx(shares * (100 + 130) * 0.002 / 2)
