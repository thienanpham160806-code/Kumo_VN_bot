"""Lenh /loc (/screen): loc co phieu.

Hai lop, KHONG lan voi nhau:
  1. Ba bo loc dung san (mau hinh ky thuat): bam nut, hoac go dung ten nut
     `/loc dotpha` | `/loc tichluy` | `/loc canhbao`.
  2. Loc tuy chinh `khoa=gia_tri`, vd `/loc san=HOSE kn=MUA rsi=quaban`;
     `kn=` la MUC KHUYEN NGHI toi thieu cua lenh /kn (MUA > TICH LUY > THEO
     DOI > GIAM TY TRONG > BAN), khac bo loc dung san "Tich luy".
"""
from __future__ import annotations

import asyncio
from html import escape

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ...analysis.screener import (
    PRESETS,
    CriteriaParseError,
    ScreenCriteria,
    parse_criteria,
    preset_from_text,
    screen_report,
)
from ...analysis.snapshot import data_unavailable_message, load_snapshot
from ...logging_conf import get_logger
from ..formatters import error_card, screener_results_card
from ..keyboards import screener_menu

log = get_logger(__name__)
router = Router(name="screener")

_MENU_TEXT = (
    "🔍 <b>BỘ LỌC CỔ PHIẾU TOÀN SÀN</b>\n\n"
    "<b>1. Bộ lọc dựng sẵn</b>: bấm nút bên dưới hoặc gõ lệnh:\n"
    "• 🚀 <b>Đột phá</b>: <code>/loc dotpha</code>\n"
    "   Vượt mây Kumo + MACD cắt lên + khối lượng nổ (≥ 1.5x TB20)\n"
    "• 📦 <b>Tích luỹ</b>: <code>/loc tichluy</code>\n"
    "   Nén giá trong mây mỏng + RSI trung tính + khối lượng cạn\n"
    "• ⚠️ <b>Cảnh báo</b>: <code>/loc canhbao</code>\n"
    "   Giá vừa thủng mây Kumo hoặc xuất hiện phân kỳ âm\n\n"
    "<b>2. Lọc tuỳ chỉnh</b>: ghép các điều kiện <code>khoá=giá trị</code>:\n"
    "• <code>san=</code> sàn: HOSE, HNX, UPCOM\n"
    "• <code>kn=</code> khuyến nghị tối thiểu theo lệnh /kn: "
    "MUA &gt; TÍCH LUỸ &gt; THEO DÕI &gt; GIẢM TỶ TRỌNG &gt; BÁN "
    "(gõ mua, tichluy, theodoi, giamtytrong, ban)\n"
    "• <code>may=</code> tren/trong/duoi · <code>rsi=</code> quamua/trungtinh/quaban · "
    "<code>kl=</code> khối lượng so với TB20\n"
    "Ví dụ:\n"
    "• <code>/loc san=HOSE kn=MUA</code> (khuyến nghị MUA trên HOSE)\n"
    "• <code>/loc kn=tichluy</code> (khuyến nghị từ TÍCH LUỸ trở lên, tức TÍCH LUỸ "
    "hoặc MUA; khác bộ lọc 📦 Tích luỹ ở trên)\n"
    "• <code>/loc may=tren kl=1.2</code> (giá trên mây, khối lượng &gt; 1.2 lần TB20)"
)


async def _no_data_text() -> str | None:
    """Thong bao (da escape HTML) neu chua co snapshot - noi ro dang nap den
    dau hoac lan truoc loi gi. None neu da co du lieu."""
    if not (await asyncio.to_thread(load_snapshot)).empty:
        return None
    return escape(data_unavailable_message())


async def _screen_text(criteria: ScreenCriteria, label: str) -> str:
    try:
        report = await asyncio.to_thread(screen_report, criteria)
        return screener_results_card(
            report.results, note=report.note, session=report.session, as_of=report.as_of
        )
    except Exception as exc:
        log.exception("Lenh /loc (%s) that bai", label)
        return error_card(str(exc))


@router.message(Command("loc", "screen"))
async def cmd_screen(message: Message) -> None:
    args = (message.text or "").split(maxsplit=1)
    custom_args = args[1].strip() if len(args) > 1 else ""

    if not custom_args:
        await message.answer(_MENU_TEXT, reply_markup=screener_menu())
        return

    # Khong co dau "=": phai la ten mot bo loc dung san (giong nut bam).
    criteria = preset_from_text(custom_args) if "=" not in custom_args else None
    if criteria is None:
        try:
            criteria = parse_criteria(custom_args)
        except CriteriaParseError as exc:
            await message.answer(error_card(str(exc)))
            return

    no_data = await _no_data_text()
    if no_data:
        await message.answer(no_data)
        return
    await message.answer(await _screen_text(criteria, custom_args))


@router.callback_query(lambda c: bool(c.data) and c.data.startswith("screen:"))
async def on_screen_preset(callback: CallbackQuery) -> None:
    if callback.data is None or callback.message is None:
        await callback.answer()
        return

    preset_key = callback.data.split(":", 1)[1]
    factory = PRESETS.get(preset_key)
    if factory is None:
        await callback.answer("Bộ lọc không hợp lệ.")
        return

    # Gui thanh tin nhan thuong, khong dung show_alert: popup cua Telegram gioi
    # han 200 ky tu, khong du cho thong bao tien do/loi.
    no_data = await _no_data_text()
    if no_data:
        await callback.answer()
        await callback.message.answer(no_data)
        return

    await callback.answer("Đang lọc...")
    await callback.message.answer(await _screen_text(factory(), preset_key))
