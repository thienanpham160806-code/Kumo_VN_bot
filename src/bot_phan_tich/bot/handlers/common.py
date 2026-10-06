"""Lenh chung: /start, /help, /market - va tien ich dung chung cho handlers khac."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from datetime import time as dt_time

import pandas as pd
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from ...config import get_universe_config, now_local
from ...data.router import get_router
from ...logging_conf import get_logger
from ..formatters import error_card, market_card
from ..keyboards import main_menu

log = get_logger(__name__)
router = Router(name="common")

HELP_TEXT = """<b>🤖 BOT PHÂN TÍCH KỸ THUẬT CHỨNG KHOÁN VIỆT NAM</b>
<i>Chiến lược: Hợp lưu ba hệ chỉ báo MACD, RSI thích ứng & Ichimoku Kinko Hyo.</i>

━━━━━━━━━━━━━━━━━━━━━
🎯 <b>1. NHU CẦU: PHÂN TÍCH 1 CỔ PHIẾU CỤ THỂ</b>
<i>(Gõ lệnh kèm mã cổ phiếu bạn đang quan tâm hoặc nắm giữ)</i>

• <code>/kn &lt;mã&gt;</code> — <b>Khuyến nghị & Kế hoạch giao dịch</b>
  ➔ Vùng mua an toàn, cắt lỗ (% rủi ro), mục tiêu (% kỳ vọng), tỷ lệ R:R và 3 chỉ báo.
  <i>Ví dụ: <code>/kn FPT</code> hoặc <code>/kn MBB</code></i>

• <code>/chart &lt;mã&gt;</code> — <b>Biểu đồ kỹ thuật nến Nhật</b>
  ➔ Biểu đồ nến trực quan tích hợp mây Ichimoku, MACD và RSI.
  <i>Ví dụ: <code>/chart SSI</code></i>

• <code>/info &lt;mã&gt;</code> — <b>Hồ sơ doanh nghiệp & Định giá</b>
  ➔ Chỉ số P/E, P/B, ROE, ngành nghề, vốn hoá và tin tức công bố thông tin.
  <i>Ví dụ: <code>/info VNM</code></i>

• <code>/fin &lt;mã&gt;</code> — <b>Báo cáo tài chính & Sức khỏe nợ vay</b>
  ➔ Tăng trưởng, sinh lời, cơ cấu vốn, dòng tiền qua các năm.
  ➔ Kèm PDF BCTC: gửi file với chú thích <code>/fin MÃ</code> (hoặc reply file
     bằng <code>/fin MÃ</code>) để đọc thêm ý kiến kiểm toán, rủi ro thuyết minh.
  <i>Ví dụ: <code>/fin HPG</code></i>

━━━━━━━━━━━━━━━━━━━━━
🔍 <b>2. NHU CẦU: TÌM CƠ HỘI ĐẦU TƯ TOÀN SÀN</b>
<i>(Quét toàn bộ thị trường, không cần nhập mã cụ thể)</i>

• <code>/loc</code> — <b>Bộ lọc cổ phiếu toàn sàn</b>
  ➔ 3 bộ lọc dựng sẵn (bấm nút hoặc gõ đúng tên):
     🚀 <b>Đột phá</b> <code>/loc dotpha</code>: vượt mây Kumo + MACD cắt lên + khối lượng nổ
     📦 <b>Tích luỹ</b> <code>/loc tichluy</code>: nén giá trong mây mỏng + RSI trung tính
        + khối lượng cạn
     ⚠️ <b>Cảnh báo</b> <code>/loc canhbao</code>: thủng mây hoặc phân kỳ âm
  ➔ Hoặc lọc tuỳ chỉnh <code>khoá=giá trị</code>; <code>kn=</code> là khuyến nghị
     tối thiểu của lệnh /kn (MUA &gt; TÍCH LUỸ &gt; THEO DÕI &gt; GIẢM TỶ TRỌNG &gt; BÁN):
     <code>/loc san=HOSE kn=MUA</code> (mã có khuyến nghị MUA trên HOSE)
     <code>/loc may=tren kl=1.2</code> (giá trên mây, khối lượng tăng)

• <code>/tinhieu</code> — <b>Tín hiệu MUA / BÁN phiên gần nhất</b>
  ➔ Danh sách cổ phiếu xuất hiện tín hiệu MUA/TÍCH LUỸ hoặc BÁN ở phiên gần nhất.

• <code>/market</code> — <b>Chỉ số VN-Index</b>
  ➔ Điểm mới nhất (cả trong phiên), mức tăng/giảm, biên độ, khối lượng.

• <code>/tintuc</code> — <b>Bản tin vĩ mô, nghị định & luật thị trường</b>
  ➔ Tổng hợp tin tức vĩ mô, văn bản pháp quy, nghị định, nghị quyết mới nhất.
  ➔ Tin tự động mỗi 1 giờ được BẬT SẴN.
     Tắt: <code>/tintuc off</code> — bật lại: <code>/tintuc on</code>.

━━━━━━━━━━━━━━━━━━━━━
⭐ <b>3. NHU CẦU: QUẢN LÝ DANH MỤC & CẢNH BÁO</b>
<i>(Lưu danh mục cá nhân để bot theo dõi hộ bạn mỗi ngày)</i>

• <code>/sub &lt;mã&gt;</code> — Thêm mã vào danh mục theo dõi (VD: <code>/sub FPT</code>)
• <code>/watchlist</code> — Xem lại danh mục theo dõi kèm khuyến nghị hôm nay
• <code>/unsub &lt;mã&gt;</code> — Bỏ theo dõi một mã (VD: <code>/unsub FPT</code>)
• <code>/canhbao</code> — Bật/Tắt thông báo tự động cuối phiên (15:05 mỗi ngày)

━━━━━━━━━━━━━━━━━━━━━
🛠 <code>/trangthai</code> — Tình trạng dữ liệu của bot
  ➔ Kho giá, snapshot, tiến độ nạp, lỗi gần nhất, RAM đang dùng.

━━━━━━━━━━━━━━━━━━━━━
💡 <i>Mẹo: Bạn có thể chạm nhanh vào các lệnh có khung màu xám (code) ở trên để copy vào ô chat!</i>
<i>(Hỗ trợ cả lệnh cũ: /khuyennghi, /bieudo, /tracuu, /bctc, /theodoi, /danhsach...)</i>

<i>Sản phẩm học thuật. Không phải khuyến nghị đầu tư.</i>"""


def parse_symbol(message: Message) -> str | None:
    """Lay tham so dau tien sau ten lenh (ma co phieu), vien hoa. None neu thieu.
    Doc ca caption: gui file kem chu thich "/fin CTG" thi lenh nam o caption,
    `text` rong (ban cu bo sot -> tra loi "Cu phap: ...")."""
    parts = (message.text or message.caption or "").split()
    return parts[1].upper() if len(parts) > 1 else None


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu())


def _benchmark_bars(benchmark: str) -> pd.DataFrame:
    """Nen ngay cua chi so, UU TIEN gap-chart cua Vietcap (co nen dang chay
    trong phien). Router (kho/cache 12 gio) chi la du phong - no giu nen hom
    qua suot phien, nen /market luc 13h tung hien diem phien hom truoc."""
    from ...data.vietcap import fetch_daily_bars

    try:
        bars = fetch_daily_bars(benchmark, count_back=30)
        if len(bars) >= 2:
            return bars
    except Exception as exc:  # noqa: BLE001 - con nguon du phong ben duoi
        log.warning("/market: gap-chart loi (%s), dung router", exc)
    end = date.today()
    return get_router().ohlcv(benchmark, end - timedelta(days=30), end)


@router.message(Command("market"))
async def cmd_market(message: Message) -> None:
    try:
        benchmark = get_universe_config().get("benchmark", "VNINDEX")
        frame = await asyncio.to_thread(_benchmark_bars, benchmark)
        if frame.empty:
            await message.answer(error_card(f"Không có dữ liệu cho {benchmark}"))
            return
        frame = frame.sort_values("time")
        last = frame.iloc[-1]
        prev = frame.iloc[-2] if len(frame) > 1 else last
        change_pts = (float(last["close"]) - float(prev["close"])) if prev["close"] else 0.0
        change_pct = (change_pts / float(prev["close"])) if prev["close"] else 0.0
        now = now_local()
        session = pd.Timestamp(last["time"]).date()
        # Truoc 15h cua chinh ngay do: nen chua dong, "diem" la diem hien tai.
        live_at = now if session == now.date() and now.time() < dt_time(15, 0) else None
        await message.answer(
            market_card(
                benchmark,
                float(last["close"]),
                change_pct,
                session,
                change_pts=change_pts,
                high=float(last.get("high", 0)),
                low=float(last.get("low", 0)),
                volume=float(last.get("volume", 0)),
                live_at=live_at,
            )
        )
    except Exception as exc:
        log.exception("Lenh /market that bai")
        await message.answer(error_card(str(exc)))
