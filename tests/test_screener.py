import pandas as pd
import pytest

from bot_phan_tich.analysis import screener as screener_mod
from bot_phan_tich.analysis import snapshot as snapshot_mod
from bot_phan_tich.analysis.scoring import ACTION_BUY, ACTION_SELL, ACTION_WATCH
from bot_phan_tich.config import Paths


@pytest.fixture
def isolated_snapshot(tmp_path, monkeypatch):
    paths = Paths(data_dir=tmp_path, cache_db=tmp_path / "cache.sqlite3", model_dir=tmp_path)
    monkeypatch.setattr(snapshot_mod, "get_paths", lambda: paths)
    return paths


def _row(symbol: str, **overrides) -> dict:
    base = {
        "symbol": symbol, "exchange": "HOSE", "close": 50.0, "change_pct": 0.01,
        "volume": 1_000_000.0, "vol_ratio20": 1.0, "action": ACTION_WATCH, "total_score": 0.0,
        "score_macd": 0.0, "score_rsi": 0.0, "score_ichimoku": 0.0,
        "price_vs_kumo": "trong_may", "kumo_break_bars": None, "kumo_thickness": 0.5,
        "macd_cross": None, "macd_bars_since": None, "macd_above_zero": True,
        "rsi": 50.0, "rsi_zone": "trung_tinh", "rsi_upper": 70.0, "rsi_lower": 30.0,
        "divergence_type": None, "tk_cross": None, "stop_loss": 45.0, "target": 55.0,
        "reasons": [], "as_of": pd.Timestamp("2026-09-18"),
    }
    base.update(overrides)
    return base


def _write_snapshot(rows: list[dict]) -> None:
    frame = pd.DataFrame(rows)
    frame.to_parquet(snapshot_mod.snapshot_path(), index=False)


# ------------------------------------------------------------------- preset: dot pha
def test_breakout_excludes_old_macd_cross(isolated_snapshot):
    """Trong tam yeu cau cua nguoi dung: ma giao cat MACD tu 20 phien truoc
    (du van tren may, khoi luong cao) KHONG duoc lot vao "dot pha"."""
    rows = [
        _row(
            "FRESH", price_vs_kumo="tren_may", kumo_break_bars=1,
            macd_cross="golden", macd_bars_since=1, vol_ratio20=2.0,
            action=ACTION_BUY, total_score=70.0,
        ),
        _row(
            "OLDCROSS", price_vs_kumo="tren_may", kumo_break_bars=1,
            macd_cross="golden", macd_bars_since=20, vol_ratio20=2.0,
            action=ACTION_BUY, total_score=75.0,
        ),
    ]
    _write_snapshot(rows)

    report = screener_mod.screen_report(screener_mod.preset_breakout())
    symbols = {r.symbol for r in report.results}
    assert symbols == {"FRESH"}


def test_breakout_requires_kumo_break_recent_and_min_volume(isolated_snapshot):
    rows = [
        _row(
            "OK", price_vs_kumo="tren_may", kumo_break_bars=2,
            macd_cross="golden", macd_bars_since=2, vol_ratio20=1.6,
        ),
        _row(
            "OLD_BREAK", price_vs_kumo="tren_may", kumo_break_bars=10,
            macd_cross="golden", macd_bars_since=2, vol_ratio20=1.6,
        ),
        _row(
            "LOW_VOLUME", price_vs_kumo="tren_may", kumo_break_bars=2,
            macd_cross="golden", macd_bars_since=2, vol_ratio20=1.2,
        ),
        _row(
            "BELOW_KUMO", price_vs_kumo="duoi_may", kumo_break_bars=2,
            macd_cross="golden", macd_bars_since=2, vol_ratio20=1.6,
        ),
    ]
    _write_snapshot(rows)

    report = screener_mod.screen_report(screener_mod.preset_breakout())
    symbols = {r.symbol for r in report.results}
    assert symbols == {"OK"}


# ------------------------------------------------------------------- preset: tich luy
def test_accumulate_requires_thin_kumo_neutral_rsi_and_dried_volume(isolated_snapshot):
    common = {
        "price_vs_kumo": "trong_may", "kumo_thickness": 0.3,
        "rsi_zone": "trung_tinh", "vol_ratio20": 0.5,
    }
    rows = [
        _row("OK", **common),
        _row("THICK_KUMO", **{**common, "kumo_thickness": 5.0}),
        _row("OVERBOUGHT", **{**common, "rsi_zone": "qua_mua"}),
        _row("HIGH_VOLUME", **{**common, "vol_ratio20": 1.5}),
        _row("ABOVE_KUMO", **{**common, "price_vs_kumo": "tren_may"}),
    ]
    _write_snapshot(rows)

    report = screener_mod.screen_report(screener_mod.preset_accumulate())
    symbols = {r.symbol for r in report.results}
    assert symbols == {"OK"}


# ------------------------------------------------------------------- preset: canh bao
def test_warning_matches_recent_kumo_breakdown_or_bearish_divergence(isolated_snapshot):
    rows = [
        _row(
            "FRESH_BREAKDOWN", price_vs_kumo="duoi_may", kumo_break_bars=1,
            action=ACTION_SELL, total_score=-70.0,
        ),
        _row(
            "OLD_BREAKDOWN", price_vs_kumo="duoi_may", kumo_break_bars=30,
            action=ACTION_SELL, total_score=-70.0,
        ),
        _row(
            "BEARISH_DIV", price_vs_kumo="trong_may",
            divergence_type="bearish", total_score=-10.0,
        ),
        _row("NEITHER", price_vs_kumo="tren_may", divergence_type=None, total_score=50.0),
    ]
    _write_snapshot(rows)

    report = screener_mod.screen_report(screener_mod.preset_warning())
    symbols = {r.symbol for r in report.results}
    assert symbols == {"FRESH_BREAKDOWN", "BEARISH_DIV"}
    # canh bao sap xep TANG DAN theo diem (te nhat truoc)
    assert [r.total_score for r in report.results] == sorted(r.total_score for r in report.results)


# ---------------------------------------------------------------------- tong quat
def test_screen_report_missing_snapshot_gives_clear_note(isolated_snapshot):
    report = screener_mod.screen_report(screener_mod.ScreenCriteria())
    assert report.results == []
    assert report.note is not None
    assert "build_snapshot" in report.note


def test_screen_report_sorted_by_total_score_descending_by_default(isolated_snapshot):
    rows = [
        _row("LOW", total_score=10.0),
        _row("HIGH", total_score=80.0),
        _row("MID", total_score=40.0),
    ]
    _write_snapshot(rows)
    report = screener_mod.screen_report(screener_mod.ScreenCriteria())
    assert [r.symbol for r in report.results] == ["HIGH", "MID", "LOW"]


def test_screen_report_respects_max_results(isolated_snapshot, monkeypatch):
    rows = [_row(f"S{i}", total_score=float(i)) for i in range(20)]
    _write_snapshot(rows)

    class FakeSettings:
        def get(self, key, default=None):
            return 5 if key == "screener.max_results" else default

    monkeypatch.setattr(screener_mod, "get_settings", lambda: FakeSettings())
    report = screener_mod.screen_report(screener_mod.ScreenCriteria())
    assert len(report.results) == 5


def test_screen_helper_returns_only_results_list(isolated_snapshot):
    _write_snapshot([_row("A", total_score=1.0)])
    results = screener_mod.screen(screener_mod.ScreenCriteria())
    assert [r.symbol for r in results] == ["A"]


# ------------------------------------------------------- loc theo chi so co ban
def test_filters_by_max_pe_when_column_present(isolated_snapshot):
    rows = [
        _row("CHEAP", pe=10.0, roe=20.0),
        _row("EXPENSIVE", pe=30.0, roe=20.0),
        _row("NO_PE", pe=None, roe=20.0),
    ]
    _write_snapshot(rows)

    report = screener_mod.screen_report(screener_mod.ScreenCriteria(max_pe=15.0))
    symbols = {r.symbol for r in report.results}
    assert symbols == {"CHEAP"}
    assert report.note is None


def test_filters_by_min_roe_when_column_present(isolated_snapshot):
    rows = [
        _row("HIGH_ROE", pe=10.0, roe=25.0),
        _row("LOW_ROE", pe=10.0, roe=5.0),
    ]
    _write_snapshot(rows)

    report = screener_mod.screen_report(screener_mod.ScreenCriteria(min_roe=15.0))
    symbols = {r.symbol for r in report.results}
    assert symbols == {"HIGH_ROE"}


def test_today_signals_groups_buy_and_sell_correctly(isolated_snapshot):
    rows = [
        _row("BUY1", action=ACTION_BUY, total_score=80.0),
        _row("ACC1", action=screener_mod.ACTION_ACCUMULATE, total_score=30.0),
        _row("WATCH1", action=ACTION_WATCH, total_score=0.0),
        _row("REDUCE1", action=screener_mod.ACTION_REDUCE, total_score=-40.0),
        _row("SELL1", action=ACTION_SELL, total_score=-80.0),
    ]
    _write_snapshot(rows)

    report = screener_mod.today_signals()
    assert {r.symbol for r in report.buy} == {"BUY1", "ACC1"}
    assert {r.symbol for r in report.sell} == {"REDUCE1", "SELL1"}
    # mua sap xep diem cao truoc, ban sap xep te nhat (diem am nhieu nhat) truoc
    assert [r.symbol for r in report.buy] == ["BUY1", "ACC1"]
    assert [r.symbol for r in report.sell] == ["SELL1", "REDUCE1"]
    assert report.as_of is not None


def test_today_signals_missing_snapshot_gives_clear_note(isolated_snapshot):
    report = screener_mod.today_signals()
    assert report.buy == []
    assert report.sell == []
    assert report.note is not None
    assert "build_snapshot" in report.note


def test_pe_filter_gracefully_skipped_when_fundamentals_missing(isolated_snapshot):
    """Chua chay backfill_fundamentals.py -> khong co cot pe/roe trong snapshot.
    Dieu kien pe/roe phai duoc BO QUA (khong loai het ket qua), kem ghi chu ro."""
    rows = [_row("A", total_score=1.0), _row("B", total_score=2.0)]
    _write_snapshot(rows)  # _row() khong co pe/roe -> cot khong ton tai

    report = screener_mod.screen_report(screener_mod.ScreenCriteria(max_pe=15.0))
    symbols = {r.symbol for r in report.results}
    assert symbols == {"A", "B"}
    assert report.note is not None
    assert "P/E" in report.note


# --------------------------------------------------------------- parse_criteria
def test_parse_criteria_basic_tokens():
    criteria = screener_mod.parse_criteria("san=HOSE kn=MUA rsi=quaban")
    assert criteria.exchanges == ["HOSE"]
    assert criteria.min_action == ACTION_BUY
    assert criteria.rsi_zone == "qua_ban"


def test_parse_criteria_pe_and_roe_tokens():
    criteria = screener_mod.parse_criteria("pe=15 roe=20")
    assert criteria.max_pe == 15.0
    assert criteria.min_roe == 20.0


def test_parse_criteria_accepts_diacritics():
    criteria = screener_mod.parse_criteria("rsi=quá_bán may=trên macd=tăng")
    assert criteria.rsi_zone == "qua_ban"
    assert criteria.price_vs_kumo == "tren_may"
    assert criteria.macd_cross == "golden"


def test_parse_criteria_empty_string_returns_default_criteria():
    criteria = screener_mod.parse_criteria("")
    assert criteria == screener_mod.ScreenCriteria()


def test_parse_criteria_rejects_missing_equals_sign():
    with pytest.raises(screener_mod.CriteriaParseError, match="thiếu dấu"):
        screener_mod.parse_criteria("HOSE")


def test_parse_criteria_rejects_unknown_key():
    with pytest.raises(screener_mod.CriteriaParseError, match="không được hỗ trợ"):
        screener_mod.parse_criteria("khong_ton_tai=1")


def test_parse_criteria_rejects_invalid_alias_value():
    with pytest.raises(screener_mod.CriteriaParseError, match="không hợp lệ"):
        screener_mod.parse_criteria("kn=khong_ro")


def test_parse_criteria_rejects_non_numeric_score():
    with pytest.raises(screener_mod.CriteriaParseError, match="phải là số"):
        screener_mod.parse_criteria("diem=abc")


def test_cards_show_trading_session_not_file_time():
    """Chay build_snapshot luc 8h sang 25/09 tren du lieu phien 24/09: the
    phai ghi "phien 24/09", khong phai ngay ghi file."""
    from datetime import date, datetime

    import pandas as pd

    from bot_phan_tich.analysis.screener import SignalReport, _session_of
    from bot_phan_tich.bot.formatters import screener_results_card, signals_card

    frame = pd.DataFrame({"as_of": pd.to_datetime(["2026-09-23", "2026-09-24"])})
    assert _session_of(frame) == date(2026, 9, 24)
    assert _session_of(pd.DataFrame({"symbol": ["A"]})) is None

    written = datetime(2026, 9, 25, 8, 0)
    loc = screener_results_card([], session=date(2026, 9, 24), as_of=written)
    assert "Dữ liệu phiên 24/09/2026 (tính lúc 08:00 25/09)" in loc

    report = SignalReport(buy=[], sell=[], as_of=written, session=date(2026, 9, 24))
    card = signals_card(report)
    assert "Tín hiệu kỹ thuật phiên 24/09/2026" in card
    assert "25/09/2026</b>" not in card


def test_report_and_card_show_true_match_count_when_list_is_capped(
    isolated_snapshot, monkeypatch
):
    """Cap so dong hien thi (screener.max_results) khong duoc lam sai so ma khop:
    20 ma khop, hien 5 -> tieu de phai noi 20 ma khop, hien thi 5."""
    from bot_phan_tich.bot.formatters import screener_results_card

    rows = [_row(f"S{i}", total_score=float(i)) for i in range(20)]
    rows += [_row(f"X{i}", exchange="HNX") for i in range(7)]  # vu tru 27 ma
    _write_snapshot(rows)

    class FakeSettings:
        def get(self, key, default=None):
            return 5 if key == "screener.max_results" else default

    monkeypatch.setattr(screener_mod, "get_settings", lambda: FakeSettings())
    report = screener_mod.screen_report(screener_mod.ScreenCriteria(exchanges=["HOSE"]))
    assert len(report.results) == 5
    assert report.total_matches == 20
    assert report.total_universe == 27

    card = screener_results_card(report.results, total_matches=report.total_matches,
                                 universe=report.total_universe)
    assert "20 mã phù hợp" in card
    assert "27 mã thanh khoản" in card
    assert "hiển thị 5" in card
