"""Loc co phieu - CHI DOC snapshot da tinh san, KHONG tinh lai, KHONG goi mang.

Giai quyet van de: truoc day moi lan /loc phai quet lai toan san (goi
recommend() + router.ohlcv() cho tung ma), lam bot treo. Gio /loc chi doc
`data/market/snapshot.parquet` (xem analysis/snapshot.py:build_snapshot(),
chay dinh ky sau gio dong cua qua bot/scheduler.py) roi loc bang pandas
boolean mask - xong duoi 1 giay.

Neu snapshot chua co hoac cu hon phien giao dich gan nhat, screen_report()
tra ve ghi chu ro rang thay vi tu di tinh lai trong handler (xem
bot/handlers/screener.py va analysis/snapshot.py:is_stale()).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field, replace
from datetime import date, datetime

import pandas as pd

from ..config import get_settings
from ..logging_conf import get_logger
from . import snapshot
from .scoring import (
    ACTION_ACCUMULATE,
    ACTION_BUY,
    ACTION_REDUCE,
    ACTION_SELL,
    ACTION_WATCH,
)

log = get_logger(__name__)

_ACTION_RANK = {
    ACTION_SELL: 0,
    ACTION_REDUCE: 1,
    ACTION_WATCH: 2,
    ACTION_ACCUMULATE: 3,
    ACTION_BUY: 4,
}


@dataclass
class ScreenCriteria:
    """Dieu kien loc. Tat ca truong deu tuy chon (None = khong loc theo do)."""

    exchanges: list[str] | None = None
    min_action: str | None = None
    min_total_score: float | None = None
    price_vs_kumo: str | None = None  # "tren_may" / "trong_may" / "duoi_may"
    max_kumo_break_bars: int | None = None  # gia moi vuot may trong toi da N phien
    max_kumo_thickness: float | None = None  # may MONG duoi nguong nay (chuan hoa theo ATR)
    macd_cross: str | None = None  # "golden" / "death"
    max_macd_bars_since: int | None = None  # MACD moi giao cat trong toi da N phien
    rsi_zone: str | None = None  # "qua_mua" / "trung_tinh" / "qua_ban"
    divergence_type: str | None = None  # "bullish" / "bearish"
    min_volume_ratio: float | None = None
    max_volume_ratio: float | None = None
    max_pe: float | None = None  # P/E toi da - can data/fundamentals_store.py (co the thieu)
    min_roe: float | None = None  # ROE toi thieu (%) - can data/fundamentals_store.py
    alert_mode: bool = False  # "canh bao": duoi may (moi thung) HOAC phan ky am (OR)
    sort_ascending: bool = False


@dataclass
class ScreenResult:
    symbol: str
    exchange: str | None
    action: str
    total_score: float
    close: float
    component_scores: dict[str, float]
    reasons: list[str]


@dataclass
class ScreenReport:
    results: list[ScreenResult]
    total_universe: int
    as_of: datetime | None
    note: str | None = field(default=None)
    session: date | None = None  # ngay cua nen moi nhat trong snapshot
    total_matches: int = 0  # so ma khop TRUOC khi cat con screener.max_results dong


def preset_breakout() -> ScreenCriteria:
    """"Dot pha": gia MOI vuot len tren may Kumo, MACD MOI giao cat tang,
    khoi luong >= 1.5x TB20. "Moi" = trong vai phien gan day (ngan khong ai
    thoa dieu kien tu hang chuc phien truoc)."""
    settings = get_settings()
    return ScreenCriteria(
        price_vs_kumo="tren_may",
        max_kumo_break_bars=settings.get("screener.breakout.max_kumo_break_bars", 3),
        macd_cross="golden",
        max_macd_bars_since=settings.get("screener.breakout.max_macd_bars_since", 3),
        min_volume_ratio=settings.get("screener.breakout.min_volume_ratio", 1.5),
    )


def preset_accumulate() -> ScreenCriteria:
    """"Tich luy": gia trong may (may MONG), RSI trung tinh, khoi luong can."""
    settings = get_settings()
    return ScreenCriteria(
        price_vs_kumo="trong_may",
        max_kumo_thickness=settings.get("screener.accumulate.max_kumo_thickness", 1.0),
        rsi_zone="trung_tinh",
        max_volume_ratio=settings.get("screener.accumulate.max_volume_ratio", 0.8),
    )


def preset_warning() -> ScreenCriteria:
    """"Canh bao": gia MOI thung xuong duoi may Kumo HOAC co phan ky am (OR)."""
    settings = get_settings()
    return ScreenCriteria(
        alert_mode=True,
        max_kumo_break_bars=settings.get("screener.warning.max_kumo_break_bars", 3),
        sort_ascending=True,
    )


# Ba bo loc dung san: khoa noi bo (callback cua nut bam) -> ham tao tieu chi.
PRESETS = {
    "breakout": preset_breakout,
    "accumulate": preset_accumulate,
    "warning": preset_warning,
}
# Ten go tay cua tung bo loc, KHOP voi ten nut bam trong menu /loc
# (bot/keyboards.screener_menu): /loc dotpha | tichluy | canhbao.
PRESET_COMMANDS = {"dotpha": "breakout", "tichluy": "accumulate", "canhbao": "warning"}


def preset_from_text(text: str) -> ScreenCriteria | None:
    """`/loc dotpha` (hoac "Đột phá", "TICH LUY"...) -> tieu chi cua bo loc dung
    san tuong ung; None neu khong phai ten bo loc."""
    key = PRESET_COMMANDS.get(_normalize_token(text))
    return PRESETS[key]() if key else None


def _passes(row: pd.Series, criteria: ScreenCriteria) -> bool:
    if criteria.alert_mode:
        broke_down = row.get("price_vs_kumo") == "duoi_may" and (
            criteria.max_kumo_break_bars is None
            or (
                pd.notna(row.get("kumo_break_bars"))
                and row["kumo_break_bars"] <= criteria.max_kumo_break_bars
            )
        )
        bearish_div = row.get("divergence_type") == "bearish"
        return bool(broke_down or bearish_div)

    if criteria.exchanges and row.get("exchange") not in criteria.exchanges:
        return False
    if criteria.min_action:
        wanted_rank = _ACTION_RANK.get(criteria.min_action, 0)
        if _ACTION_RANK.get(row.get("action"), -1) < wanted_rank:
            return False
    if criteria.min_total_score is not None:
        if pd.isna(row.get("total_score")) or row["total_score"] < criteria.min_total_score:
            return False
    if criteria.price_vs_kumo and row.get("price_vs_kumo") != criteria.price_vs_kumo:
        return False
    if criteria.max_kumo_break_bars is not None:
        bb = row.get("kumo_break_bars")
        if pd.isna(bb) or bb > criteria.max_kumo_break_bars:
            return False
    if criteria.max_kumo_thickness is not None:
        kt = row.get("kumo_thickness")
        if pd.isna(kt) or kt > criteria.max_kumo_thickness:
            return False
    if criteria.macd_cross and row.get("macd_cross") != criteria.macd_cross:
        return False
    if criteria.max_macd_bars_since is not None:
        bs = row.get("macd_bars_since")
        if pd.isna(bs) or bs > criteria.max_macd_bars_since:
            return False
    if criteria.rsi_zone and row.get("rsi_zone") != criteria.rsi_zone:
        return False
    if criteria.divergence_type and row.get("divergence_type") != criteria.divergence_type:
        return False
    if criteria.min_volume_ratio is not None:
        vr = row.get("vol_ratio20")
        if pd.isna(vr) or vr < criteria.min_volume_ratio:
            return False
    if criteria.max_volume_ratio is not None:
        vr = row.get("vol_ratio20")
        if pd.isna(vr) or vr > criteria.max_volume_ratio:
            return False
    if criteria.max_pe is not None:
        pe = row.get("pe")
        if pd.isna(pe) or pe > criteria.max_pe:
            return False
    if criteria.min_roe is not None:
        roe = row.get("roe")
        if pd.isna(roe) or roe < criteria.min_roe:
            return False
    return True


def _row_reasons(row: pd.Series) -> list[str]:
    """"reasons" doc lai tu parquet co the la None hoac numpy array (khong
    phai list) - "x or []" se loi ("truth value cua array la ambiguous"),
    phai kiem tra "is None" tuong minh."""
    value = row.get("reasons")
    return [] if value is None else list(value)


def _to_results(frame: pd.DataFrame) -> list[ScreenResult]:
    return [
        ScreenResult(
            symbol=row["symbol"],
            exchange=row.get("exchange"),
            action=row["action"],
            total_score=float(row["total_score"]),
            close=float(row["close"]),
            component_scores={
                "macd": row.get("score_macd"),
                "rsi": row.get("score_rsi"),
                "ichimoku": row.get("score_ichimoku"),
            },
            reasons=_row_reasons(row),
        )
        for _, row in frame.iterrows()
    ]


def _freshness_note(as_of: datetime | None, n_symbols: int) -> str | None:
    """Ghi chu ve do moi cua snapshot dang doc: ban TAM (chi danh sach theo
    doi), dang cap nhat o nen (kem tien do) hoac da cu hon phien gan nhat.
    None neu du lieu day du, moi va khong co gi dang chay."""
    stamp = f"{as_of:%d/%m/%Y %H:%M}" if as_of else "không rõ"
    running = snapshot.progress_text()
    if snapshot.is_partial_snapshot():
        error = snapshot.get_build_status().last_error
        if running:
            tail = f"{running}."
        elif error:
            tail = f"Lần nạp toàn sàn gần nhất thất bại: {error}."
        else:
            tail = "Đang nạp toàn sàn ở nền."
        return (
            f"📌 Dữ liệu tạm thời: {n_symbols} mã (danh sách theo dõi). {tail} "
            "Gõ /trangthai để xem chi tiết."
        )
    if running:
        return f"⏳ {running}. Kết quả dưới đây từ bản tính lúc {stamp}."
    if snapshot.is_stale():
        expected = snapshot.last_expected_session()
        return (
            f"⚠️ Chưa có dữ liệu phiên {expected:%d/%m/%Y} (bản gần nhất tính lúc "
            f"{stamp}), kết quả có thể cũ. Gõ /trangthai để xem chi tiết."
        )
    return snapshot.intraday_note()


def _session_of(frame: pd.DataFrame) -> date | None:
    """Phien giao dich cua du lieu (ngay nen moi nhat), KHAC thoi diem ghi
    file: chay build_snapshot luc 8h sang van la du lieu phien hom truoc."""
    if "as_of" not in frame.columns or frame.empty:
        return None
    latest = pd.to_datetime(frame["as_of"]).max()
    return None if pd.isna(latest) else latest.date()


def screen_report(criteria: ScreenCriteria) -> ScreenReport:
    """Loc snapshot theo `criteria`. KHONG goi mang, KHONG tinh chi bao."""
    frame = snapshot.load_snapshot()
    if frame.empty:
        return ScreenReport(
            results=[], total_universe=0, as_of=None, note=snapshot.data_unavailable_message()
        )

    as_of = snapshot.snapshot_last_updated()
    freshness = _freshness_note(as_of, len(frame))
    notes = [freshness] if freshness else []

    # Dieu kien theo chi so co ban (pe/roe) can data/fundamentals_store.py da
    # duoc gop vao snapshot (xem analysis/snapshot.py:_merge_fundamentals()).
    # Neu chua chay scripts/backfill_fundamentals.py, cot khong ton tai - BO
    # QUA NHE NHANG dieu kien do (khong loai het ket qua) va bao ro cho nguoi dung.
    if criteria.max_pe is not None and "pe" not in frame.columns:
        criteria = replace(criteria, max_pe=None)
        notes.append("Chưa có dữ liệu P/E (chạy `python scripts/backfill_fundamentals.py`).")
    if criteria.min_roe is not None and "roe" not in frame.columns:
        criteria = replace(criteria, min_roe=None)
        notes.append("Chưa có dữ liệu ROE (chạy `python scripts/backfill_fundamentals.py`).")
    note = " ".join(notes) or None

    mask = frame.apply(lambda row: _passes(row, criteria), axis=1)
    matched = frame.loc[mask].copy()
    matched = matched.sort_values("total_score", ascending=criteria.sort_ascending)

    total_matches = len(matched)
    limit = get_settings().get("screener.max_results", 15)
    matched = matched.head(limit)

    results = _to_results(matched)
    return ScreenReport(
        results=results, total_universe=len(frame), as_of=as_of, note=note,
        session=_session_of(frame), total_matches=total_matches,
    )


def screen(criteria: ScreenCriteria) -> list[ScreenResult]:
    """Loc co phieu theo `criteria`. Xem screen_report() de lay them ghi chu."""
    return screen_report(criteria).results


@dataclass
class SignalReport:
    """Ket qua /tinhieu: tin hieu MUA/TICH LUY va BAN/GIAM TY TRONG cua phien
    gan nhat, doc thang tu snapshot - khong loc theo dieu kien nao them."""

    buy: list[ScreenResult]
    sell: list[ScreenResult]
    as_of: datetime | None
    note: str | None = field(default=None)
    session: date | None = None  # ngay cua nen moi nhat trong snapshot


def today_signals(limit: int | None = None) -> SignalReport:
    """Yeu cau con thieu cua de: liet ke tin hieu MUA/TICH LUY va BAN/GIAM
    TY TRONG cua phien gan nhat (xem /tinhieu, bot/handlers/signals.py).
    CHI DOC snapshot, cung nguyen tac voi screen_report() - khong tinh lai.
    """
    frame = snapshot.load_snapshot()
    if frame.empty:
        return SignalReport(buy=[], sell=[], as_of=None, note=snapshot.data_unavailable_message())

    as_of = snapshot.snapshot_last_updated()
    note = _freshness_note(as_of, len(frame))

    limit = limit or get_settings().get("screener.max_results", 15)

    buy_frame = frame[frame["action"].isin([ACTION_BUY, ACTION_ACCUMULATE])]
    buy_frame = buy_frame.sort_values("total_score", ascending=False).head(limit)

    sell_frame = frame[frame["action"].isin([ACTION_SELL, ACTION_REDUCE])]
    sell_frame = sell_frame.sort_values("total_score", ascending=True).head(limit)

    return SignalReport(
        buy=_to_results(buy_frame), sell=_to_results(sell_frame), as_of=as_of, note=note,
        session=_session_of(frame),
    )


# --------------------------------------------------------- loc tuy chinh (/loc <dieu kien>)
class CriteriaParseError(ValueError):
    """Tham so /loc sai cu phap hoac gia tri khong hop le - kem thong bao than thien."""


_ACTION_ALIASES = {
    "mua": ACTION_BUY,
    "tichluy": ACTION_ACCUMULATE,
    "theodoi": ACTION_WATCH,
    "giamtytrong": ACTION_REDUCE,
    "ban": ACTION_SELL,
}
_KUMO_ALIASES = {"tren": "tren_may", "trong": "trong_may", "duoi": "duoi_may"}
_MACD_ALIASES = {"tang": "golden", "giam": "death"}
_RSI_ALIASES = {"quamua": "qua_mua", "trungtinh": "trung_tinh", "quaban": "qua_ban"}
_DIV_ALIASES = {"duong": "bullish", "am": "bearish"}

USAGE_EXAMPLE = "/loc san=HOSE kn=MUA"
PRESET_USAGE = "/loc dotpha, /loc tichluy, /loc canhbao"


def _normalize_token(value: str) -> str:
    """Bo dau + thuong hoa de nguoi dung go co dau hay khong dau deu khop
    (vd 'quá bán' hoac 'quaban' deu ra 'quaban')."""
    decomposed = unicodedata.normalize("NFD", value)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    # "đ" khong tach thanh d + dau khi NFD (la mot chu cai rieng) - doi tay.
    stripped = stripped.replace("đ", "d").replace("Đ", "D")
    return stripped.lower().replace("_", "").replace(" ", "").replace("-", "")


def _parse_alias(key: str, value: str, table: dict[str, str]) -> str:
    norm = _normalize_token(value)
    result = table.get(norm)
    if result is None:
        raise CriteriaParseError(
            f"Giá trị {key}={value} không hợp lệ. Dùng một trong: "
            f"{', '.join(table)}. Ví dụ: {USAGE_EXAMPLE}"
        )
    return result


def _parse_float(key: str, value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise CriteriaParseError(
            f"Giá trị {key}={value} phải là số. Ví dụ: {USAGE_EXAMPLE}"
        ) from exc


def parse_criteria(text: str) -> ScreenCriteria:
    """Phan tich tham so dang 'san=HOSE kn=MUA rsi=quaban' thanh ScreenCriteria.

    Nem CriteriaParseError (thong bao than thien, kem vi du dung) neu tham
    so sai cu phap hoac gia tri khong hop le - KHONG bao gio crash handler.
    """
    criteria = ScreenCriteria()
    tokens = text.split()
    if not tokens:
        return criteria

    for token in tokens:
        if "=" not in token:
            raise CriteriaParseError(
                f"Tham số '{token}' thiếu dấu '='. Ví dụ đúng: {USAGE_EXAMPLE}. "
                f"Bộ lọc dựng sẵn thì gõ đúng tên: {PRESET_USAGE}"
            )
        key, _, value = token.partition("=")
        key, value = key.strip().lower(), value.strip()
        if not value:
            raise CriteriaParseError(f"Tham số '{key}' thiếu giá trị. Ví dụ: {USAGE_EXAMPLE}")

        if key == "san":
            criteria.exchanges = [v.strip().upper() for v in value.split(",") if v.strip()]
        elif key == "kn":
            criteria.min_action = _parse_alias(key, value, _ACTION_ALIASES)
        elif key == "rsi":
            criteria.rsi_zone = _parse_alias(key, value, _RSI_ALIASES)
        elif key == "may":
            criteria.price_vs_kumo = _parse_alias(key, value, _KUMO_ALIASES)
        elif key == "macd":
            criteria.macd_cross = _parse_alias(key, value, _MACD_ALIASES)
        elif key == "phanky":
            criteria.divergence_type = _parse_alias(key, value, _DIV_ALIASES)
        elif key == "diem":
            criteria.min_total_score = _parse_float(key, value)
        elif key == "kl":
            criteria.min_volume_ratio = _parse_float(key, value)
        elif key == "pe":
            criteria.max_pe = _parse_float(key, value)
        elif key == "roe":
            criteria.min_roe = _parse_float(key, value)
        else:
            raise CriteriaParseError(
                f"Tham số '{key}' không được hỗ trợ. Các tham số hợp lệ: "
                f"san, kn, rsi, may, macd, phanky, diem, kl, pe, roe. Ví dụ: {USAGE_EXAMPLE}"
            )
    return criteria
