"""Dinh dang tin nhan Telegram va tien ich trinh bay dung chung.

Quy tac bat buoc cho moi tin nhan (muc 11 cua ke hoach refactor):
  - parse_mode=HTML, escape() moi noi dung do NGUOI DUNG nhap (ten ma...).
  - The khuyen nghi co bo cuc CO DINH: dong 1 ma+khuyen nghi, khoi 2 vung
    gia, khoi 3 diem ba he, khoi 4 ba ly do.
  - Tin nhan nao co tin hieu deu kem dong mien tru trach nhiem (DISCLAIMER).
  - Lenh chay qua 2 giay: gui truoc "Dang xu ly..." roi sua lai khi xong
    (xem run_with_notice()).
"""
from __future__ import annotations

import asyncio
import urllib.parse
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any

from aiogram.types import Message

from ..sysinfo import format_mb

DISCLAIMER = "<i>Sản phẩm học thuật. Không phải khuyến nghị đầu tư.</i>"
PROCESSING_NOTICE = "Đang xử lý..."
PROCESSING_THRESHOLD_SECONDS = 2.0


def money(value: float | None) -> str:
    return "không có dữ liệu" if value is None else f"{value:,.0f}"


def money_billion(value: float | None) -> str:
    """Hien so tien lon (VND) dang 'X,XXX tỷ đồng' - de doc hon so nguyen day du."""
    return "không có dữ liệu" if value is None else f"{value / 1e9:,.0f} tỷ đồng"


def price(value: float | None) -> str:
    """Gia co phieu (thang nghin dong/CP, vd 65.18) - can 2 chu so thap phan,
    khac voi money() (lam tron so nguyen, dung cho khoi luong/so CP...)."""
    return "không có dữ liệu" if value is None else f"{value:,.2f}"


def percent(value: float | None) -> str:
    return "không có dữ liệu" if value is None else f"{value:+.2%}"


# --------------------------------------------------------------------- /market
def market_card(
    symbol: str,
    close: float,
    change_pct: float,
    as_of,
    change_pts: float | None = None,
    high: float | None = None,
    low: float | None = None,
    volume: float | None = None,
    live_at: datetime | None = None,
) -> str:
    """The trang thai thi truong cho chi so tham chieu (VNINDEX). `live_at`:
    phien dang dien ra - diem la diem hien tai luc do, chua phai dong cua."""
    icon = "🟢" if change_pct > 0 else ("🔴" if change_pct < 0 else "🟡")
    huong = "tăng" if change_pct > 0 else ("giảm" if change_pct < 0 else "đứng giá")

    pts_str = f"{change_pts:+.2f} điểm / " if change_pts is not None else ""
    lines = [
        f"📊 <b>CHỈ SỐ THỊ TRƯỜNG: {escape(symbol)}</b>",
        (
            f"📅 <b>Phiên giao dịch:</b> <b>{as_of:%d/%m/%Y}</b>"
            + (f" (đang diễn ra, cập nhật {live_at:%H:%M})" if live_at else "")
        ),
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        "📈 <b>ĐIỂM SỐ & BIẾN ĐỘNG</b>",
        (
            f"• <b>{'Điểm hiện tại' if live_at else 'Điểm đóng cửa'}:</b> <b>{price(close)}</b> "
            f"({icon} {huong} {pts_str}{percent(change_pct)})"
        ),
    ]

    if high is not None and low is not None and high > 0 and low > 0:
        lines.append(f"• <b>Biên độ trong phiên:</b> {price(low)} – {price(high)}")

    if volume is not None and volume > 0:
        lines.append(f"• <b>Khối lượng giao dịch:</b> <b>{money(volume)}</b> CP")

    lines.extend(
        [
            "",
            DISCLAIMER,
        ]
    )
    return "\n".join(lines)


# ------------------------------------------------------------------ /khuyennghi
_ACTION_META = {
    "MUA": {
        "icon": "🟢",
        "title": "MUA MỚI",
        "desc": "Tín hiệu tăng giá được cả 3 hệ chỉ báo đồng thuận xác nhận.",
        "allocation": "Giải ngân 30% – 50% tiền mặt (chia làm 2 lần giải ngân, không all-in)",
    },
    "TÍCH LUỸ": {
        "icon": "🟡",
        "title": "TÍCH LUỸ / MUA THĂM DÒ",
        "desc": "Cổ phiếu đang nén nền giá hoặc hồi phục tích luỹ trong vùng an toàn.",
        "allocation": "Giải ngân 15% – 25% tiền mặt (mua gom từng phần khi giá đỏ quanh hỗ trợ)",
    },
    "THEO DÕI": {
        "icon": "⚪",
        "title": "THEO DÕI",
        "desc": "Chưa có tín hiệu vào lệnh an toàn, cơ hội và rủi ro đang ở mức cân bằng.",
        "allocation": "0% (Ưu tiên giữ tiền mặt, kiên nhẫn chờ tín hiệu bứt phá rõ ràng)",
    },
    "GIẢM TỶ TRỌNG": {
        "icon": "🟠",
        "title": "GIẢM TỶ TRỌNG",
        "desc": "Động lượng suy yếu hoặc chạm cản kỹ thuật. Rủi ro điều chỉnh ngắn hạn gia tăng.",
        "allocation": "Hạ margin, chốt lời 30% – 50% vị thế hiện tại để bảo toàn thành quả",
    },
    "BÁN": {
        "icon": "🔴",
        "title": "BÁN / THOÁT VỊ THẾ",
        "desc": "Xu hướng giảm đã xác nhận hoặc giá vi phạm ngưỡng kỹ thuật.",
        "allocation": "Bán toàn bộ vị thế hoặc cắt lỗ dứt khoát để bảo vệ vốn tối đa",
    },
}

_ACTION_EMOJI = {
    "MUA": "🟢",
    "TÍCH LUỸ": "🟡",
    "THEO DÕI": "⚪",
    "GIẢM TỶ TRỌNG": "🟠",
    "BÁN": "🔴",
}


def recommendation_card(rec) -> str:
    """The khuyen nghi chi tiet, de hieu va truc quan danh cho nha dau tu F0."""
    meta = _ACTION_META.get(
        rec.action,
        {
            "icon": "📌",
            "title": rec.action,
            "desc": "Tín hiệu kỹ thuật hiện tại của cổ phiếu.",
            "allocation": "Tuân thủ kỷ luật quản trị rủi ro danh mục.",
        },
    )

    lines = [
        f"{meta['icon']} <b>{escape(rec.symbol)}</b> — <b>KHUYẾN NGHỊ: {meta['title']}</b>",
        f"<i>{meta['desc']}</i>",
        f"💡 <b>Tỷ trọng gợi ý:</b> {meta['allocation']}",
    ]

    if rec.vetoed_by_kumo:
        lines.append(
            "⚠️ <b>LƯU Ý ĐẶC BIỆT:</b> Điểm động lượng kỹ thuật đủ MUA, nhưng hệ thống đã "
            "<b>PHỦ QUYẾT (Kumo Veto)</b> và hạ xuống <b>TÍCH LUỸ</b> do giá nằm dưới mây Kumo. "
            "Rủi ro kẹp hàng trong xu hướng giảm trung hạn rất lớn!"
        )
    if rec.confidence != "cao":
        do_tin_cay = "trung bình" if rec.confidence == "trung_binh" else "thấp"
        lines.append(
            f"⚠️ <i>Độ tin cậy: {do_tin_cay} (khối lượng thấp, thiếu xác nhận dòng tiền)</i>"
        )

    lines.extend(
        [
            "",
            "🎯 <b>KẾ HOẠCH GIAO DỊCH (TRADING PLAN)</b>",
            f"• <b>Giá hiện tại:</b> <b>{price(rec.close)}</b>",
            f"• <b>Vùng mua an toàn:</b> {price(rec.entry_low)} – {price(rec.entry_high)} "
            "<i>(Khuyến nghị: Không mua đuổi khi giá vượt vùng này)</i>",
        ]
    )

    if rec.close and rec.stop_loss:
        sl_pct = (rec.stop_loss / rec.close - 1) * 100
        sl_text = (
            f"• <b>Cắt lỗ (Stop Loss):</b> <b>{price(rec.stop_loss)}</b> "
            f"➔ <i>Rủi ro: {sl_pct:+.1f}% (Nếu thủng mức này, bán dứt khoát bảo toàn vốn)</i>"
        )
    else:
        sl_text = f"• <b>Cắt lỗ:</b> <b>{price(rec.stop_loss)}</b>"
    lines.append(sl_text)

    if rec.close and rec.target:
        tp_pct = (rec.target / rec.close - 1) * 100
        res_text = (
            f" [Kháng cự Kumo: {price(rec.target_resistance)}]"
            if rec.target_resistance is not None
            else ""
        )
        tp_text = (
            f"• <b>Mục tiêu (Take Profit):</b> <b>{price(rec.target)}</b> "
            f"➔ <i>Kỳ vọng lợi nhuận: {tp_pct:+.1f}%{res_text}</i>"
        )
    else:
        tp_text = f"• <b>Mục tiêu:</b> <b>{price(rec.target)}</b>"
    lines.append(tp_text)

    if rec.risk_reward is not None:
        rr = rec.risk_reward
        if rr >= 2.0:
            rr_eval = "Rất hấp dẫn (lãi kỳ vọng từ 2 lần rủi ro trở lên)"
        elif rr >= 1.5:
            rr_eval = "Tốt, đạt chuẩn quản trị rủi ro"
        else:
            rr_eval = "Lợi nhuận chưa vượt trội rủi ro, cần cân nhắc kỹ"
        lines.append(
            f"• <b>Tỷ lệ Lợi nhuận / Rủi ro (R:R):</b> <b>{rr:.1f} : 1</b> — <i>{rr_eval}</i>"
        )
    else:
        lines.append("• <b>Tỷ lệ Lợi nhuận / Rủi ro:</b> không có dữ liệu")

    if rec.total_score >= 60:
        mood = "Tích cực mạnh (Xu hướng tăng đồng thuận)"
    elif rec.total_score >= 20:
        mood = "Tích cực (Xu hướng tăng đang hình thành)"
    elif rec.total_score >= -20:
        mood = "Trung tính (Giằng co, chưa rõ xu hướng)"
    elif rec.total_score >= -60:
        mood = "Tiêu cực (Áp lực bán chiếm ưu thế)"
    else:
        mood = "Tiêu cực mạnh (Xu hướng giảm chiếm trọn thị trường)"

    lines.extend(
        [
            "",
            f"📊 <b>PHÂN TÍCH 3 HỆ CHỈ BÁO (Điểm tổng: {rec.total_score:+.0f} / 100)</b>",
            f"<i>Trạng thái kỹ thuật: {mood}</i>",
        ]
    )

    # Indicator 1: MACD
    macd_score = rec.component_scores.get("macd", 0.0)
    lines.append(f"1️⃣ <b>MACD ({macd_score:+.0f} đ) — Động lượng ngắn hạn:</b>")
    if rec.reasons and len(rec.reasons) > 0:
        lines.append(f"   • {escape(rec.reasons[0])}")

    # Indicator 2: RSI
    rsi_score = rec.component_scores.get("rsi", 0.0)
    rsi_zone = rec.rsi_state.get("zone")
    rsi_meaning = ""
    if rsi_zone == "qua_mua":
        rsi_meaning = (
            " ➔ <i>Lực mua quá đà (quá mua), cẩn trọng rung lắc, không mua đuổi!</i>"
        )
    elif rsi_zone == "qua_ban":
        rsi_meaning = (
            " ➔ <i>Áp lực bán tháo cực đại (quá bán), có thể có nhịp hồi kỹ thuật.</i>"
        )
    elif rsi_zone == "trung_tinh":
        rsi_meaning = " ➔ <i>Vùng cân bằng an toàn, cung cầu ổn định.</i>"

    lines.append(f"2️⃣ <b>RSI ({rsi_score:+.0f} đ) — Áp lực Mua/Bán:</b>")
    if rec.reasons and len(rec.reasons) > 1:
        lines.append(f"   • {escape(rec.reasons[1])}{rsi_meaning}")

    # Indicator 3: Ichimoku
    ichi_score = rec.component_scores.get("ichimoku", 0.0)
    pos = rec.ichimoku_state.get("price_vs_kumo")
    if pos == "tren_may":
        ichi_meaning = (
            " ➔ <i>Cổ phiếu duy trì Uptrend an toàn, mây Kumo là bệ đỡ hỗ trợ phía dưới.</i>"
        )
    elif pos == "trong_may":
        ichi_meaning = " ➔ <i>Cổ phiếu đi ngang giằng co (Sideway), biến động khó lường.</i>"
    elif pos == "duoi_may":
        ichi_meaning = (
            " ➔ <i>Cổ phiếu trong Downtrend rủi ro cao, mây Kumo là rào cản kháng cự phía trên.</i>"
        )
    else:
        ichi_meaning = ""

    lines.append(f"3️⃣ <b>Ichimoku ({ichi_score:+.0f} đ) — Xu hướng trung hạn & Hỗ trợ/Kháng cự:</b>")
    if rec.reasons and len(rec.reasons) > 2:
        lines.append(f"   • {escape(rec.reasons[2])}{ichi_meaning}")

    # F0 Golden rules
    lines.extend(
        [
            "",
            "💡 <b>LỜI KHUYÊN CHO NHÀ ĐẦU TƯ F0:</b>",
            "• <b>Kỷ luật cắt lỗ:</b> Luôn tuân thủ mức cắt lỗ, không gồng lỗ khi gãy hỗ trợ.",
            "• <b>Không mua đuổi:</b> Nếu giá đã vượt vùng an toàn, hãy kiên nhẫn chờ nhịp chỉnh.",
            "• <b>Chia nhỏ lệnh:</b> Mua 2-3 đợt (thăm dò trước, gia tăng khi đúng xu hướng).",
            "",
            DISCLAIMER,
        ]
    )
    return "\n".join(lines)


# --------------------------------------------------------------------- /tracuu
def _format_ratio_line(
    label: str,
    metric,
    unit: str = "",
    is_percent: bool = False,
    is_int: bool = False,
    is_debt: bool = False,
) -> str:
    if metric.value is None:
        return f"• <b>{label}:</b> <i>không có dữ liệu</i>"

    if is_int:
        val_str = f"{metric.value:,.0f}{unit}"
    elif is_percent:
        val_str = f"{metric.value:.2f}%"
    else:
        val_str = f"{metric.value:.2f}{unit}"

    note = ""
    if metric.industry_median is not None:
        if is_int:
            med_str = f"{metric.industry_median:,.0f}{unit}"
        elif is_percent:
            med_str = f"{metric.industry_median:.2f}%"
        else:
            med_str = f"{metric.industry_median:.2f}{unit}"
        note = f" <i>(Ngành: {med_str})</i>"

    warning = " ⚠️" if is_debt and metric.value > 150 else ""
    return f"• <b>{label}:</b> <b>{val_str}</b>{warning}{note}"


_DESCRIPTION_MAX_CHARS = 400


def _format_description(raw: str) -> str:
    """Mo ta hoat dong tu vnstock thuong co nhieu gach dau dong ngan cach
    boi ky tu xuong dong that (\\n) - giu NGUYEN xuong dong do (Telegram
    HTML van hien dung newline that, khac voi HTML trinh duyet), chi cat bot
    khi qua dai thay vi don het thanh mot dong lien tuc.
    """
    raw_lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]

    kept: list[str] = []
    used = 0
    for ln in raw_lines:
        if used + len(ln) > _DESCRIPTION_MAX_CHARS:
            remaining = _DESCRIPTION_MAX_CHARS - used
            if remaining > 20:  # con du cho de cat co nghia, khong thi bo han dong nay
                kept.append(ln[:remaining].rstrip() + "…")
            else:
                kept.append("…")
            break
        kept.append(ln)
        used += len(ln)

    return f"<i>{escape(chr(10).join(kept))}</i>"


def lookup_card(profile) -> str:
    symbol = escape(profile.symbol)
    full_name = escape(profile.full_name or "Chưa rõ tên đầy đủ")
    exchange = escape(profile.exchange or "—")
    industry = escape(profile.industry or "Chưa phân loại")
    listed = escape(profile.listed_date or "—")
    period = escape(profile.latest_report_period or "—")

    lines = [
        f"🏢 <b>{symbol} — {full_name}</b>",
        f"🏛️ <b>Sàn:</b> {exchange}  |  🏷️ <b>Ngành:</b> {industry}",
        f"📅 <b>Niêm yết:</b> {listed}  |  📑 <b>BCTC gần nhất:</b> {period}",
    ]

    if profile.description:
        lines.append("")
        lines.append("📝 <b>Lĩnh vực hoạt động chính:</b>")
        lines.append(_format_description(profile.description))

    lines.extend(
        [
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            "💰 <b>THỊ GIÁ & QUY MÔ VỐN</b>",
        ]
    )

    if profile.price is not None:
        p_str = (
            f"<b>{profile.price:,.0f} đ</b>"
            if profile.price >= 1000
            else f"<b>{profile.price:,.2f}</b>"
        )
        if profile.change_pct is not None:
            icon = "🟢" if profile.change_pct > 0 else ("🔴" if profile.change_pct < 0 else "🟡")
            lines.append(f"• <b>Giá khớp lệnh:</b> {p_str} ({icon} {profile.change_pct:+.2%})")
        else:
            lines.append(f"• <b>Giá khớp lệnh:</b> {p_str}")
    else:
        lines.append("• <b>Giá khớp lệnh:</b> <i>không có dữ liệu</i>")

    if profile.volume is not None:
        lines.append(f"• <b>Khối lượng phiên:</b> <b>{money(profile.volume)}</b> CP")

    if profile.market_cap is not None:
        lines.append(f"• <b>Vốn hoá thị trường:</b> <b>{money_billion(profile.market_cap)}</b>")

    cap_str = money_billion(profile.charter_capital)
    shares_str = money(profile.shares_outstanding)
    lines.append(f"• <b>Vốn điều lệ:</b> {cap_str}  |  <b>Lưu hành:</b> {shares_str} CP")

    lines.extend(
        [
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            "📊 <b>CHỈ SỐ ĐỊNH GIÁ & TÀI CHÍNH</b>",
            "",
            "🏷️ <b>Định giá cổ phiếu:</b>",
            _format_ratio_line("P/E", profile.pe, unit=" lần"),
            _format_ratio_line("P/B", profile.pb, unit=" lần"),
            _format_ratio_line("EPS", profile.eps, unit=" đ", is_int=True),
            "",
            "📈 <b>Hiệu quả sinh lời & Nợ vay:</b>",
            _format_ratio_line("ROE", profile.roe, is_percent=True),
            _format_ratio_line("ROA", profile.roa, is_percent=True),
            _format_ratio_line("Biên LN ròng", profile.net_margin, is_percent=True),
            _format_ratio_line(
                "Nợ / Vốn CSH (D/E)", profile.debt_to_equity, is_percent=True, is_debt=True
            ),
            _format_ratio_line("Tỷ suất cổ tức", profile.dividend_yield, is_percent=True),
        ]
    )

    lines.extend(
        [
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            "📰 <b>CÔNG BỐ THÔNG TIN & TIN TỨC GẦN ĐÂY</b>",
        ]
    )

    if profile.news:
        for item in profile.news:
            if hasattr(item, "title"):
                title = escape(item.title)
                date_str = escape(item.published_at or "")
                read_url = item.url
                cafef_url = item.cafef_url or f"https://s.cafef.vn/tin-doanh-nghiep/{profile.symbol.upper()}/Event.chn"
                date_prefix = f"• <b>{date_str}</b> — " if date_str else "• "
                if read_url:
                    lines.append(
                        f"{date_prefix}<a href=\"{read_url}\">{title}</a> "
                        f"<i>[<a href=\"{cafef_url}\">CafeF ↗</a>]</i>"
                    )
                else:
                    search_q = urllib.parse.quote_plus(f"{profile.symbol} {item.title}")
                    search_url = f"https://www.google.com/search?q={search_q}"
                    links = (
                        f"<i>[<a href=\"{search_url}\">🔍 Tìm</a> | "
                        f"<a href=\"{cafef_url}\">CafeF ↗</a>]</i>"
                    )
                    lines.append(f"{date_prefix}{title} {links}")
            else:
                raw_text = str(item)
                if " — " in raw_text:
                    dt, tit = raw_text.split(" — ", 1)
                    search_tit = tit.strip()
                    if not search_tit.upper().startswith(profile.symbol.upper()):
                        search_tit = f"{profile.symbol} {search_tit}"
                    q = urllib.parse.quote_plus(search_tit)
                    search_url = f"https://www.google.com/search?q={q}"
                    cafef_url = f"https://s.cafef.vn/tin-doanh-nghiep/{profile.symbol.upper()}/Event.chn"
                    links = (
                        f"<i>[<a href=\"{search_url}\">🔍 Tìm</a> | "
                        f"<a href=\"{cafef_url}\">CafeF ↗</a>]</i>"
                    )
                    lines.append(f"• <b>{escape(dt)}</b> — {escape(tit)} {links}")
                else:
                    lines.append(f"• {escape(raw_text)}")

        lines.append("")
        lines.append("🌐 <b>Báo chí & Cổng thông tin chính thống:</b>")
        lines.append(
            f"   ↳ <a href=\"https://s.cafef.vn/tin-doanh-nghiep/{profile.symbol}/Event.chn\">"
            f"Chuyên trang CafeF</a>  |  "
            f"<a href=\"https://finance.vietstock.vn/{profile.symbol}/tin-tuc-su-kien.htm\">"
            f"Cổng tin Vietstock</a>"
        )
    elif profile.recent_events:
        lines.extend(f"• {escape(e)}" for e in profile.recent_events)
    else:
        lines.append("<i>Chưa có dữ liệu sự kiện / tin tức trong 6 tháng gần nhất.</i>")

    if profile.data_notes:
        lines.append("")
        lines.append("<i>Lưu ý dữ liệu còn thiếu:</i>")
        lines.extend(f"  - {escape(note)}" for note in profile.data_notes)

    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


# ----------------------------------------------------------------------- /loc
def _session_line(session, as_of) -> str | None:
    """Dong "du lieu phien nao" - de nguoi dung (va hoi dong) thay ngay ket
    qua la cua phien hom nay hay phien truoc."""
    if session is None:
        return None
    line = f"📅 Dữ liệu phiên {session:%d/%m/%Y}"
    if as_of is not None:
        line += f" (tính lúc {as_of:%H:%M %d/%m})"
    return line


def screener_results_card(
    results, note: str | None = None, limit: int = 15, session=None, as_of=None,
    total_matches: int | None = None, universe: int | None = None,
) -> str:
    """`total_matches`: so ma khop that (truoc khi cat con screener.max_results
    dong); `universe`: so ma trong snapshot (vu tru thanh khoan) da duoc quet."""
    session_line = _session_line(session, as_of)
    if not results:
        lines = [
            "🔍 <b>Không tìm thấy mã nào khớp điều kiện lọc hiện tại.</b>",
            "",
            "💡 <b>Lý do thường gặp:</b>",
            "• Thị trường chung đang đi ngang/điều chỉnh, ít cổ phiếu bùng nổ đồng thời.",
            "• Tiêu chí lọc quá khắt khe (ví dụ: vừa yêu cầu MUA vừa đòi hỏi RSI Quá bán).",
            "",
            "👉 <b>Gợi ý cho bạn:</b>",
            "• Thử bộ lọc 📦 <b>Tích luỹ</b> (<code>/loc tichluy</code>) để tìm các cổ phiếu "
            "đang nén nền giá chờ tăng.",
            "• Xem tín hiệu tổng quát toàn thị trường bằng lệnh <code>/tinhieu</code>.",
            "• Thử lệnh lọc: <code>/loc san=HOSE kn=MUA</code> hoặc <code>/loc may=tren</code>",
        ]
        if session_line:
            lines += ["", f"<i>{session_line}</i>"]
        if note:
            lines.append("")
            lines.append(f"<i>{escape(note)}</i>")
        lines.append("")
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    shown = min(len(results), limit)
    matched = max(total_matches or 0, len(results))
    scope = f" trong {universe} mã thanh khoản" if universe else ""
    header = f"{matched} mã phù hợp{scope}"
    if matched > shown:
        header += f", hiển thị {shown} mã đầu theo điểm"
    lines = [f"🔍 <b>Kết quả lọc cổ phiếu</b> ({header})", ""]
    for r in results[:limit]:
        emoji = _ACTION_EMOJI.get(r.action, "📌")
        lines.append(
            f"{emoji} <b>{escape(r.symbol)}</b> — <b>{escape(r.action)}</b>  "
            f"| Điểm: <b>{r.total_score:+.0f}</b>  | Giá: <b>{price(r.close)}</b>"
        )
    if matched > shown:
        lines.append(f"<i>... và {matched - shown} mã khác</i>")
    if session_line:
        lines += ["", f"<i>{session_line}</i>"]
    if note:
        lines.append("")
        lines.append(f"<i>{escape(note)}</i>")
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


# ------------------------------------------------------------------- /tinhieu
def signals_card(report, limit: int = 15) -> str:
    """The /tinhieu: tin hieu MUA/TICH LUY va BAN/GIAM TY TRONG cua phien gan
    nhat, kem ro phien nao (as_of) de nguoi dung biet du lieu cu hay moi."""
    if report.as_of is None:
        header = "<b>Chưa có dữ liệu tín hiệu.</b>"
        return header if not report.note else f"{header}\n\n<i>{escape(report.note)}</i>"

    session = getattr(report, "session", None) or report.as_of.date()
    lines = [
        f"📊 <b>Tín hiệu kỹ thuật phiên {session:%d/%m/%Y}</b>",
        f"<i>Tính lúc {report.as_of:%H:%M %d/%m/%Y}</i>",
        "",
    ]

    lines.append(f"<b>📈 TÍN HIỆU TÍCH CỰC (MUA / TÍCH LUỸ)</b> ({len(report.buy)} mã)")
    if not report.buy:
        lines.append("  <i>Không có mã nào thoả mãn</i>")
    for r in report.buy[:limit]:
        emoji = _ACTION_EMOJI.get(r.action, "🟢")
        lines.append(
            f"  {emoji} <b>{escape(r.symbol)}</b> — {escape(r.action)}  "
            f"| Điểm: <b>{r.total_score:+.0f}</b>  | Giá: <b>{price(r.close)}</b>"
        )

    lines.append("")
    lines.append(f"<b>📉 TÍN HIỆU THẬN TRỌNG (BÁN / GIẢM TỶ TRỌNG)</b> ({len(report.sell)} mã)")
    if not report.sell:
        lines.append("  <i>Không có mã nào thoả mãn</i>")
    for r in report.sell[:limit]:
        emoji = _ACTION_EMOJI.get(r.action, "🔴")
        lines.append(
            f"  {emoji} <b>{escape(r.symbol)}</b> — {escape(r.action)}  "
            f"| Điểm: <b>{r.total_score:+.0f}</b>  | Giá: <b>{price(r.close)}</b>"
        )

    if report.note:
        lines.append("")
        lines.append(f"<i>{escape(report.note)}</i>")
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


# ------------------------------------------------------------------- /danhsach
def watchlist_card(symbols: list[str], recommendations: dict) -> str:
    if not symbols:
        return "Danh sách theo dõi đang trống. Thêm bằng <code>/theodoi FPT</code>."

    lines = [f"<b>Đang theo dõi {len(symbols)} mã</b>", ""]
    for symbol in symbols:
        rec = recommendations.get(symbol)
        if rec is None:
            lines.append(f"<b>{escape(symbol)}</b>: không có dữ liệu")
        else:
            lines.append(
                f"<b>{escape(symbol)}</b>: {escape(rec.action)} "
                f"(điểm {rec.total_score:+.0f}, giá {price(rec.close)})"
            )
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def alerts_toggle_card(enabled: bool) -> str:
    trang_thai = "BẬT" if enabled else "TẮT"
    return f"Đã {trang_thai} cảnh báo tự động cuối phiên cho các mã bạn theo dõi."


def error_card(message: str) -> str:
    return f"Không xử lý được yêu cầu.\n\n<i>{escape(message)}</i>"


# ----------------------------------------------------------------- /trangthai
def _stamp(value: datetime | None) -> str:
    return "chưa có" if value is None else f"{value:%d/%m/%Y %H:%M}"


def status_card(status) -> str:
    """The /trangthai - `status` la diagnostics.py:SystemStatus."""
    lines = ["<b>🛠 TÌNH TRẠNG DỮ LIỆU CỦA BOT</b>", ""]

    lines.append("<b>Kho giá</b>")
    if status.store_rows:
        size = f", {status.store_size_mb:,.1f} MB" if status.store_size_mb is not None else ""
        lines.append(f"  {status.store_symbols:,} mã, {status.store_rows:,} dòng{size}")
        lines.append(f"  Cập nhật: {_stamp(status.store_updated)}")
    else:
        lines.append("  Trống — chưa nạp")

    lines.append("<b>Snapshot khuyến nghị</b>")
    if status.snapshot_symbols:
        if status.snapshot_partial:
            freshness = "TẠM THỜI — chỉ danh sách theo dõi, đang chờ nạp toàn sàn"
        elif status.snapshot_stale:
            freshness = "cũ hơn phiên gần nhất"
        else:
            freshness = "mới"
        built_at = _stamp(status.snapshot_updated)
        lines.append(f"  {status.snapshot_symbols:,} mã, dựng lúc {built_at}")
        lines.append(f"  Tình trạng: {freshness}")
    else:
        lines.append("  Chưa có")

    lines.append("<b>Chỉ số cơ bản (P/E, P/B, ROE)</b>")
    if status.fundamentals_symbols:
        lines.append(
            f"  {status.fundamentals_symbols:,} mã, cập nhật {_stamp(status.fundamentals_updated)}"
        )
    else:
        lines.append("  Chưa có (chạy scripts/backfill_fundamentals.py)")

    build = status.build
    lines.append("<b>Tiến trình nền</b>")
    if build.running:
        lines.append(f"  ⏳ {escape(status.progress or 'Đang chạy')}")
        lines.append(f"  Bắt đầu: {_stamp(build.started_at)}")
    elif build.finished_at is None:
        lines.append("  Chưa chạy lần nào kể từ khi bot khởi động")
    elif build.last_error:
        lines.append(f"  ❌ Thất bại lúc {_stamp(build.finished_at)}")
    else:
        result = f" ({escape(build.last_result)})" if build.last_result else ""
        lines.append(f"  ✅ Xong lúc {_stamp(build.finished_at)}{result}")
    if build.last_error:
        lines.append(f"  Lỗi gần nhất: <i>{escape(build.last_error)}</i>")

    lines.append("<b>RAM tiến trình</b>")
    lines.append(
        f"  Đang dùng {format_mb(status.ram_mb)} (đỉnh {format_mb(status.ram_peak_mb)})"
    )
    lines.append("")
    lines.append(
        "<i>Kiểm tra RAM/CPU thật của máy chủ và kết nối nguồn dữ liệu: "
        "<code>/trangthai chandoan</code></i>"
    )
    return "\n".join(lines)


def macro_news_card(items: list[dict], title_suffix: str = "1 Giờ Qua") -> str:
    """Dinh dang ban tin tong hop vi mo, phap luat va thi truong."""
    if not items:
        return (
            f"📰 <b>ĐIỂM TIN THỊ TRƯỜNG & VĂN BẢN PHÁP LUẬT ({title_suffix})</b>\n\n"
            "<i>Không có tin tức vĩ mô hoặc văn bản mới nào được phát hành "
            "trong khoảng thời gian này.</i>\n\n"
            "💡 Gõ <code>/tintuc</code> để xem các tin tức gần nhất, "
            "hoặc <code>/tintuc on</code> để bật thông báo tự động mỗi 1 giờ."
        )

    lines: list[str] = [
        f"📰 <b>TỔNG HỢP TIN THỊ TRƯỜNG & VĂN BẢN PHÁP LUẬT — {title_suffix.upper()}</b>",
        "─────────────────────────",
    ]

    # Phan nhom tin
    policy_items = [it for it in items if it.get("category") == "CHÍNH SÁCH - PHÁP LUẬT"]
    macro_items = [it for it in items if it.get("category") == "VĨ MÔ & THỊ TRƯỜNG"]
    corp_items = [it for it in items if it.get("category") not in (
        "CHÍNH SÁCH - PHÁP LUẬT", "VĨ MÔ & THỊ TRƯỜNG"
    )]

    def _render_group(group_title: str, group_items: list[dict]) -> None:
        if not group_items:
            return
        lines.append("")
        lines.append(f"<b>{group_title}</b>")
        for it in group_items:
            # Dinh dang thoi gian
            time_str = ""
            pub_raw = it.get("published_at", "")
            if pub_raw:
                try:
                    # ISO format: 2026-09-22T17:10:00+00:00
                    dt = datetime.fromisoformat(pub_raw)
                    # Chuyen sang gio VN (+7)
                    dt_vn = dt.astimezone(timezone(timedelta(hours=7)))
                    time_str = dt_vn.strftime("%H:%M")
                except Exception:
                    time_str = pub_raw[:16]

            time_badge = f"<b>[{time_str}]</b> " if time_str else ""
            title = escape(it.get("title", ""))
            link = escape(it.get("link", ""), quote=True)
            source = escape(it.get("source", "Báo chí"))
            summary = escape(it.get("summary", ""))

            lines.append(f"• {time_badge}<a href=\"{link}\">{title}</a> <i>[{source}]</i>")
            if summary:
                lines.append(f"   ↳ <i>{summary}</i>")

    _render_group("🏛️ VĂN BẢN QUY PHẠM, NGHỊ ĐỊNH & CHÍNH SÁCH", policy_items)
    _render_group("📊 KINH TẾ VĨ MÔ & THỊ TRƯỜNG CHỨNG KHOÁN", macro_items)
    _render_group("🏢 DOANH NGHIỆP & NGÀNH NGHỀ", corp_items)

    lines.append("")
    lines.append("─────────────────────────")
    lines.append(
        "💡 <i>Để nhận bản tin tự động mỗi 1 giờ: gõ <code>/tintuc on</code> "
        "(hoặc <code>/tintuc off</code> để tắt).</i>"
    )
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)



# ------------------------------------------------------------- xu ly lau > 2s
async def run_with_notice(
    message: Message,
    work: Callable[[], Awaitable[str]],
    threshold: float = PROCESSING_THRESHOLD_SECONDS,
    reply_markup: Any = None,
) -> None:
    """Chay `work()` (coroutine tra ve chuoi HTML de gui cho nguoi dung).

    Neu xong truoc `threshold` giay thi gui thang ket qua. Neu lau hon, gui
    truoc PROCESSING_NOTICE roi SUA lai chinh tin nhan do bang ket qua khi
    xong - dung cho cac lenh co the mat vai giay (quet, tai BCTC...).
    """
    task = asyncio.ensure_future(work())
    try:
        result = await asyncio.wait_for(asyncio.shield(task), timeout=threshold)
    except asyncio.TimeoutError:
        notice = await message.answer(PROCESSING_NOTICE)
        result = await task
        await notice.edit_text(result, reply_markup=reply_markup)
        return
    await message.answer(result, reply_markup=reply_markup)
