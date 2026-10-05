"""Vi cau truc thi truong Viet Nam trong backtest/engine.py.

Moi test dung mot ma duy nhat voi vai phien dung tay, tin hieu MUA o phien 0
-> vao lenh o gia mo cua phien 1 (T). Cac phien sau duoc dat sao cho dung mot
quy tac (T+2, gap, gia san) quyet dinh ket qua.
"""
import pandas as pd
import pytest

from bot_phan_tich.backtest.engine import run

_VOLUME = 10_000_000.0  # du lon de max_participation khong chan khoi luong


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
