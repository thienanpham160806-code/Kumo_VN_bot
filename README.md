# bot-phan-tich

Telegram Bot phân tích kỹ thuật chứng khoán Việt Nam — hợp lưu ba hệ chỉ báo
**MACD, RSI (ngưỡng thích ứng), Ichimoku Kinko Hyo** — trên **toàn sàn**
HOSE/HNX/UPCOM (không chỉ vài mã theo dõi mẫu).

Kiến trúc cốt lõi: giá toàn sàn nằm trong một kho parquet duy nhất
(`data/market_store.py`); khuyến nghị của từng mã được tính sẵn thành
"snapshot" (`analysis/snapshot.py`) sau phiên sáng và sau giờ đóng cửa, nên
`/loc` và `/tinhieu` chỉ đọc bảng có sẵn và trả lời dưới 1 giây. Việc nặng
chạy trong thread riêng (`asyncio.to_thread`), bot vẫn trả lời lệnh khác trong
lúc nạp dữ liệu — xem [docs/kien-truc.md](docs/kien-truc.md).

---

## 0. Bắt đầu nhanh

### 0.1. Cài đặt

```bash
pip install -r requirements.txt
cp .env.example .env    # Windows: copy .env.example .env — rồi điền TELEGRAM_BOT_TOKEN
```

Chi tiết (virtualenv, khoá DNSE tuỳ chọn): mục 1 và 2.

### 0.2. Hai lệnh nạp dữ liệu

| Lệnh | Làm gì | Mất bao lâu |
|---|---|---|
| `python scripts/backfill_data.py` | Tải giá toàn sàn (HOSE/HNX/UPCOM, khoảng 1.500 mã) về máy, lưu vào **một file duy nhất** `data/market/ohlcv.parquet`. | Lần đầu 2–3 phút (500 phiên/mã). Các lần sau khoảng 1–2 phút: vẫn gọi mỗi mã một lượt nhưng chỉ tải 10 phiên gần nhất rồi gộp vào kho cũ. |
| `python scripts/build_snapshot.py` | Chạy chiến lược (MACD + RSI thích ứng + Ichimoku) cho từng mã đủ thanh khoản trong kho, ghi ra bảng kết quả `data/market/snapshot.parquet`. **Đây chính là bảng mà `/loc` và `/tinhieu` đọc** — hai lệnh này không tự tính gì. | 5–20 giây (khoảng 200 mã, tuỳ máy). |

**Thứ tự bắt buộc: `backfill_data.py` trước, `build_snapshot.py` sau.**
`build_snapshot.py` chỉ đọc kho do `backfill_data.py` tạo ra. Chạy ngược lại
(hoặc chưa backfill) thì kho trống, snapshot rỗng, và `/loc` báo "đang chuẩn
bị dữ liệu" — đúng lỗi gặp trước đây.

Khi bot đang chạy, nó tự làm lại hai bước này vào thứ 2–6: **11:35** (sau
phiên sáng, kết quả ghi "tạm tính") và **15:05** (sau giờ đóng cửa, bản chính
thức). Khởi động trên máy chưa có dữ liệu thì bot cũng tự nạp ở nền (xem tiến
độ bằng `/trangthai`). Chạy tay hai lệnh trên chủ yếu để có dữ liệu ngay,
trước khi demo.

**Sự cố thường gặp**

| Hiện tượng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `/loc`, `/tinhieu` báo "đang chuẩn bị dữ liệu" | Chưa có snapshot: chưa chạy hai lệnh, chạy sai thứ tự, hoặc bot đang tự nạp ở nền | Chạy `backfill_data.py` rồi `build_snapshot.py`. Nếu bot đang tự nạp: gõ `/trangthai` xem tiến độ, chờ vài phút |
| `backfill_data.py` báo nhiều mã thất bại (dòng cuối `Xong: X/Y ma`, X thấp hơn Y nhiều) | Vietcap tạm giới hạn tần suất hoặc chặn IP — endpoint bảng giá không chính thức | Đợi vài phút rồi chạy lại. Vài chục mã lỗi là bình thường (mã ngừng giao dịch, mới niêm yết) |
| `build_snapshot.py` báo "vũ trụ thanh khoản rỗng" | Kho trống (chưa backfill, hoặc backfill tải hỏng hết), hoặc mỗi mã có ít hơn 250 phiên nên không qua điều kiện `universe.min_listed_days` (do đặt `MARKET_COUNT_BACK` < 250) | Chạy `backfill_data.py` trước và xem dòng `Xong:` có đủ mã không. Nếu đã đặt `MARKET_COUNT_BACK`, để ≥ 400 rồi chạy `backfill_data.py --full` |
| Máy treo / rất chậm khi build | Bản cũ mở nhiều tiến trình, mỗi tiến trình giữ một bản sao kho giá. Bản hiện tại chạy tuần tự, RAM đỉnh khoảng 250 MB | Kiểm tra `snapshot.max_workers: 1` trong `config/settings.yaml`. Máy yếu: đặt `UNIVERSE_MAX_SYMBOLS=200` trong `.env` để chỉ tính 200 mã thanh khoản nhất |
| Không có dữ liệu hôm nay | Snapshot chính thức chỉ có **sau 15:05**; bản tạm tính phiên sáng có sau 11:35 | Demo trước 11:35 thì dữ liệu là của **phiên hôm trước** — kết quả `/loc`, `/tinhieu` ghi rõ "Dữ liệu phiên dd/mm", cứ nói thẳng với thầy. Từ 11:35 đến 15:05 là bản tạm tính (có ghi chú). `/market` luôn lấy điểm VN-Index mới nhất, kể cả trong phiên |

### 0.3. Chạy bot

```bash
python scripts/run_bot.py
```

Tạm dừng service trên Render trước khi chạy trên máy (xem mục 7.1).

---

## 1. Cài đặt

Yêu cầu Python 3.10+.

```bash
git clone https://github.com/thienanpham160806-code/bot-phan-tich.git
cd bot-phan-tich

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # Windows: copy .env.example .env
```

---

## 2. Cấu hình `.env`

Mở `.env` và điền:

| Biến | Lấy ở đâu |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Chat với [@BotFather](https://t.me/BotFather) trên Telegram, lệnh `/newbot` |
| `DNSE_API_KEY`, `DNSE_API_SECRET` | EntradeX → mục LightSpeed API (xem hướng dẫn bên dưới) — **tuỳ chọn** |
| `VNSTOCK_ACCEPT_TOS` | Đặt `1` sau khi chạy `register_user()` của vnstock một lần |

> **Không bao giờ** commit file `.env`. File này đã nằm trong `.gitignore`
> (chỉ `.env.example` — bản mẫu rỗng — mới được commit).

Chưa có `DNSE_API_KEY`/`DNSE_API_SECRET` cũng không sao — `data/router.py`
tự động dùng nguồn dự phòng (Vietcap/VCI qua `vnstock`, không cần API key)
nên bot vẫn chạy được đầy đủ phần dữ liệu cuối phiên. Xem bảng nguồn dữ liệu
ở mục 6.

### Cách lấy API key DNSE (nếu muốn dùng nguồn chính)

1. Mở tài khoản chứng khoán online tại <https://www.dnse.com.vn> (eKYC bằng
   CCCD gắn chip), không cần nạp tiền để dùng phần dữ liệu thị trường.
2. Đăng nhập **EntradeX** (<https://banggia.dnse.com.vn> hoặc app EntradeX)
   → mục **LightSpeed API** trong cài đặt tài khoản → tạo khoá.
3. **API secret chỉ hiện đúng một lần** — copy ngay vào `.env`, lỡ mất phải
   tạo khoá mới. Không thấy mục LightSpeed API thì liên hệ DNSE (hotline
   024 7108 9234 / hello@dnse.com.vn), cung cấp số tài khoản 064C + họ tên.
4. `pip install openapi-sdk` (theo docs của DNSE) **không cài được** — tên
   gói đó chỉ là ví dụ trong docs, không phải tên thật trên PyPI. Tên gói
   PyPI thật là `dnse-sdk-openapi` (đã có sẵn trong `requirements.txt`,
   không cần cài riêng — xem `data/dnse.py`).

Cấu hình Vietcap (nguồn dự phòng, **không cần API key**): qua thư viện
`vnstock` — `pip install -U vnstock` (đã có trong `requirements.txt`), chạy
`register_user()` một lần, đặt `VNSTOCK_ACCEPT_TOS=1` trong `.env`.

> Lỡ commit lộ `DNSE_API_KEY`/`DNSE_API_SECRET` lên Git: vào EntradeX **tạo
> khoá mới ngay** (khoá cũ coi như đã lộ) rồi mới dọn lịch sử commit — đổi
> khoá trước, dọn git sau.

---

## 3. Nạp dữ liệu và chạy bot

Hai lệnh nạp dữ liệu, thứ tự và sự cố thường gặp: xem **mục 0.2**. Tuỳ chọn
của `backfill_data.py`: `--full` (tải lại từ đầu), `--watchlist-only` (chỉ 12
mã trong `config/universe.yaml`, để phát triển cho nhanh). Số phiên tải lần
đầu: `market_store.count_back_bootstrap` trong `config/settings.yaml` hoặc
biến `MARKET_COUNT_BACK`.

Tuỳ chọn thêm (không bắt buộc để bot chạy được):

```bash
# Chỉ số cơ bản (P/E, P/B, ROE) cho vũ trụ thanh khoản — bổ sung điều kiện
# lọc pe=/roe= trong /loc. Cache 7 ngày, tự bỏ qua nếu chạy lại quá sớm.
python scripts/backfill_fundamentals.py

# Backtest chiến lược 3 và 6 tháng gần nhất, so với mua-và-giữ VN-Index.
# Xuất outputs/backtest_3m.csv, backtest_6m.csv, outputs/equity_curve.png.
python scripts/run_backtest.py

# Phân tích IC của điểm MACD/RSI/Ichimoku/tổng (mục 5b) -> outputs/ic/.
python scripts/ic_analysis.py
```

Kiểm thử: `pytest -q`. Chất lượng mã: `ruff check src tests scripts`.

Trên Windows có thể dùng script tác vụ cho gọn (`.\tasks.ps1 <task>` — xem
`tasks.ps1` để biết danh sách đầy đủ).

---

## 4. Bộ lệnh bot

Lệnh chia theo 3 nhóm:

### 🎯 Nhóm 1: Phân tích 1 cổ phiếu cụ thể
| Lệnh ngắn | Bí danh | Chức năng |
|---|---|---|
| `/kn MA` | `/khuyennghi`, `/rec` | Khuyến nghị MUA/TÍCH LUỸ/THEO DÕI/GIẢM TỶ TRỌNG/BÁN, kế hoạch giá (vùng vào, cắt lỗ, mục tiêu), R:R, tỷ trọng giải ngân gợi ý |
| `/chart MA` | `/bieudo` | Biểu đồ nến kỹ thuật tích hợp mây Ichimoku, MACD, RSI |
| `/info MA` | `/tracuu` | Hồ sơ niêm yết, P/E, P/B, ROE, vốn hoá và tin công bố thông tin gần đây |
| `/fin MA` | `/bctc` | Nhận xét BCTC nhiều năm: tăng trưởng, sinh lời, cơ cấu vốn, dòng tiền (ngân hàng có thêm thu nhập lãi thuần, dự phòng, cho vay/huy động). Có PDF BCTC thì khai thác thêm ý kiến kiểm toán và rủi ro thuyết minh: gửi file kèm chú thích `/fin MA`, hoặc trả lời (reply) file bằng `/fin MA`. PDF bản scan không có chữ thì không đọc được |

### 🔍 Nhóm 2: Tìm cơ hội đầu tư & Thông tin toàn sàn
| Lệnh ngắn | Bí danh | Chức năng |
|---|---|---|
| `/loc [đk]` | `/screen` | Bộ lọc cổ phiếu toàn sàn — 3 bộ lọc dựng sẵn (Đột phá, Tích luỹ, Cảnh báo), hoặc gõ điều kiện tuỳ biến (VD: `/loc san=HOSE kn=MUA kl=1.2`) |
| `/tinhieu` | `/signals` | Các mã có khuyến nghị MUA/TÍCH LUỸ hoặc BÁN/GIẢM TỶ TRỌNG ở phiên gần nhất (ghi rõ dữ liệu phiên nào) |
| `/market` | | VN-Index: điểm mới nhất (trong phiên là điểm hiện tại, lấy trực tiếp từ Vietcap), mức tăng/giảm, biên độ, khối lượng |
| `/tintuc` | `/news` | Tổng hợp tin tức vĩ mô, văn bản pháp quy, nghị định, nghị quyết mới nhất. Tin tự động mỗi 1 giờ được **bật sẵn** cho ai nhắn bot; `/tintuc off` để tắt, `/tintuc on` để bật lại |

### ⭐ Nhóm 3: Quản lý danh mục & Cảnh báo cá nhân
| Lệnh ngắn | Bí danh | Chức năng |
|---|---|---|
| `/sub MA` | `/theodoi` | Thêm mã vào danh mục theo dõi cá nhân |
| `/watchlist` | `/danhsach` | Xem danh sách cổ phiếu theo dõi kèm khuyến nghị hiện tại |
| `/unsub MA` | `/bosach` | Bỏ theo dõi một mã |
| `/canhbao` | `/alerts` | Bật/tắt cảnh báo tự động cuối phiên (15:05 mỗi ngày giao dịch) |
| `/trangthai` | `/status` | Tình trạng dữ liệu: kho giá, snapshot (mới/cũ/tạm thời), tiến độ nạp nền, lỗi gần nhất, RAM đang dùng |
| `/help` | `/start` | Menu hướng dẫn chi tiết và bàn phím tương tác nhanh |

`/loc` hỗ trợ các khoá lọc tuỳ chỉnh: `san` (sàn), `kn` (khuyến nghị tối
thiểu), `rsi` (vùng RSI), `may` (vị trí so với mây Kumo), `macd` (chiều giao
cắt), `phanky` (phân kỳ), `diem` (điểm tối thiểu), `kl` (tỷ lệ khối lượng tối
thiểu), `pe`/`roe` (chỉ khả dụng sau khi chạy `backfill_fundamentals.py`).
Công thức chi tiết ba bộ lọc dựng sẵn: [docs/cong-thuc.md](docs/cong-thuc.md).

---

## 5. Kiến trúc

Sơ đồ đầy đủ và nguyên tắc thiết kế: [docs/kien-truc.md](docs/kien-truc.md).
Công thức/ngưỡng của từng chỉ báo: [docs/cong-thuc.md](docs/cong-thuc.md).

```
Vietcap/DNSE --> data/market_store.py (kho giá TOÀN SÀN, 1 file parquet)
                        |  scripts/backfill_data.py (tải/cập nhật)
                        v
              analysis/snapshot.py (build_snapshot: recommend() 1 lần/mã,
                        |            tuần tự, ghi snapshot.parquet)
                        |  scripts/build_snapshot.py, hoặc tự động qua
                        |  bot/scheduler.py: 11:35 (tạm tính) và 15:05
                        v
              analysis/screener.py, /tinhieu  --  CHỈ ĐỌC snapshot.parquet
                        |
                        v
                   bot/ (aiogram, polling)
```

Nguyên tắc hợp lưu quan trọng nhất: **Ichimoku có quyền phủ quyết khuyến
nghị MUA** khi giá nằm dưới mây Kumo, bất kể điểm tổng của MACD/RSI cao bao
nhiêu — xem `analysis/scoring.py`.

Các hàm nặng (tra cứu, khuyến nghị, vẽ biểu đồ, text mining BCTC, quét
watchlist) chạy qua `await asyncio.to_thread(...)` trong handler, nên `/help`
vẫn trả lời ngay khi đang có lệnh nặng khác (xem `tests/test_nonblocking.py`).

---

## 5b. Kiểm định định lượng

### Phân tích Information Coefficient (IC)

`python scripts/ic_analysis.py` (module `backtest/ic.py`). Mỗi phiên t, trên
**mặt cắt** các mã trong vũ trụ thanh khoản *tại thời điểm đó* (chọn theo dữ
liệu đến hết tháng trước), tính tương quan hạng Spearman giữa điểm của từng
hệ chỉ báo (chỉ dùng dữ liệu đến t) và lợi suất từ **giá mở cửa t+1** đến giá
mở cửa t+1+h. IC đo xem điểm số có **xếp hạng đúng** mã nào sẽ tăng hơn mã nào
hay không. Kết quả đầy đủ: `outputs/ic/` (`ic_summary.csv`, `ic_daily.csv`,
`ic_monthly.csv`, `ic_decay.png`).

Mẫu: 02/01/2024 – 22/09/2026, 675 phiên, trung vị 280 mã/phiên.

| Chỉ báo | h | IC TB | Độ lệch chuẩn | ICIR | t-stat | t-stat Newey-West | Tháng IC > 0 |
|---|---:|---:|---:|---:|---:|---:|---:|
| MACD | 5 | 0,0025 | 0,117 | 0,02 | 0,55 | 0,32 | 58% |
| MACD | 10 | 0,0152 | 0,111 | 0,14 | 3,54 | 1,72 | 61% |
| MACD | 20 | 0,0163 | 0,104 | 0,16 | 4,00 | 1,44 | 66% |
| RSI | 5 | −0,0155 | 0,130 | −0,12 | −3,09 | −1,88 | 33% |
| RSI | 10 | 0,0050 | 0,124 | 0,04 | 1,04 | 0,52 | 61% |
| RSI | 20 | 0,0212 | 0,119 | 0,18 | 4,56 | 1,72 | 69% |
| Ichimoku | 5 | 0,0082 | 0,131 | 0,06 | 1,62 | 0,91 | 64% |
| Ichimoku | 10 | 0,0160 | 0,124 | 0,13 | 3,34 | 1,42 | 64% |
| Ichimoku | 20 | 0,0218 | 0,117 | 0,19 | 4,79 | 1,50 | 66% |
| Điểm tổng | 5 | −0,0010 | 0,133 | −0,01 | −0,19 | −0,11 | 58% |
| Điểm tổng | 10 | 0,0135 | 0,125 | 0,11 | 2,78 | 1,25 | 61% |
| Điểm tổng | 20 | 0,0227 | 0,113 | 0,20 | 5,15 | 1,72 | 72% |

![IC decay](outputs/ic/ic_decay.png)

**Diễn giải — kết quả gần như bằng 0, và cần nói thẳng như vậy:**

- **IC rất nhỏ.** Mọi |IC| ≤ 0,023. Không có hệ nào, kể cả điểm tổng, có ý
  nghĩa thống kê ở mức 5% sau khi hiệu chỉnh: t-stat Newey-West cao nhất là
  1,72 (< 1,96).
- **t-stat thường bị thổi phồng.** Với h = 10–20, lợi suất của hai phiên liền
  nhau dùng chung 9–19 phiên, nên chuỗi IC tự tương quan mạnh. t-stat thường
  (3,5–5,2, trông "rất có ý nghĩa") cao gấp 2–3 lần t-stat Newey-West (độ trễ =
  h). Nếu chỉ báo cáo t-stat thường sẽ tự lừa mình.
- **Đảo chiều ngắn hạn là tín hiệu rõ nhất, và nó ngược chiều chiến lược.** Ở
  h = 1 phiên IC **âm có ý nghĩa**: RSI −0,038 (t Newey-West −7,7, chỉ 6% số
  tháng có IC > 0), điểm tổng −0,020 (t −4,1). Mã có điểm cao hôm nay có xu
  hướng giảm lại trong 1–2 phiên kế tiếp; từ h ≈ 10 phiên IC mới chuyển sang
  dương, và vẫn yếu. Chiến lược mua ngay giá mở cửa sau ngày điểm cao, với dừng lỗ
  1,5 ATR, đi đúng vào nhịp điều chỉnh này. Đó là một lời giải thích hợp lý
  cho kết quả backtest yếu ở mục dưới.
- **Giới hạn:** chỉ ~2,7 năm dữ liệu (kho giữ ~750 phiên mỗi mã), giá đã điều
  chỉnh cổ tức, vũ trụ lấy sàn theo danh sách hiện tại. IC đo khả năng *xếp
  hạng* giữa các mã; chiến lược thật là *định thời điểm* có stop/target, nên
  hai thước đo bổ sung cho nhau chứ không thay thế nhau.

---

## 6. Nguồn dữ liệu

| Loại dữ liệu | Nguồn chính | Nguồn dự phòng | Cần API key? |
|---|---|---|---|
| Giá lịch sử/cuối phiên (OHLCV) | Kho toàn sàn nạp từ Vietcap (`data/vietcap.py`, endpoint công khai bảng giá); mã ngoài kho: DNSE OpenAPI (`data/dnse.py`) | Vietcap/VCI qua `vnstock` | DNSE: có; Vietcap: không |
| Danh sách mã toàn sàn | DNSE (`/market/instruments`) | Vietcap (`/price/symbols/getAll`) | Không (Vietcap) |
| Báo cáo tài chính, chỉ số cơ bản | Vietcap/VCI qua `vnstock` | — | Không |
| Ngành (industry map) | Vietcap/VCI qua `vnstock` | — | Không |
| Tin tức công bố thông tin | Vietcap/VCI qua `vnstock` | — | Không |
| Realtime (khớp lệnh trực tiếp) | **Chưa cài** — `data/realtime.py` mới có giao diện + stub, mặc định tắt (`realtime.enabled: false`) | — | — |

`data/router.py` là nơi DUY NHẤT biết thứ tự ưu tiên nguồn — phần còn lại
của hệ thống chỉ gọi `get_router().ohlcv(...)` và không quan tâm dữ liệu đến
từ đâu. Khi nguồn lỗi/timeout/hết hạn mức, router tự chuyển sang nguồn dự
phòng theo thứ tự khai báo ở `config/settings.yaml: data.price_sources` /
`data.fundamental_sources`.

### Xử lý sự cố dữ liệu

| Tình huống | Hệ thống làm gì / bạn nên làm gì |
|---|---|
| DNSE lỗi / không kết nối được / chưa có API key | `data/router.py` chuyển sang Vietcap. Không kết nối được (vd Render ở Singapore bị DNSE chặn) thì bỏ qua DNSE 15 phút, không chờ lại |
| Bị giới hạn tần suất (429, hoặc vnstock/vnai tự gọi `sys.exit()` khi chạm hạn mức) | Lùi theo cấp số nhân tối đa 5 lần thử; nếu vẫn lỗi, đợi vài phút rồi chạy lại — bản Guest của vnstock giới hạn khoảng 20 lượt/phút |
| `backfill_data.py`/`backfill_fundamentals.py` báo hàng loạt mã lỗi hoặc trả về rỗng dù không có exception | Endpoint công khai của Vietcap **không chính thức**, có thể tạm thời giới hạn/chặn theo IP hoặc tần suất truy cập bất thường — thử lại sau vài phút; nếu chạy trên máy chủ/cloud ở nước ngoài, khả năng cao bị chặn nhiều hơn chạy từ máy cá nhân tại Việt Nam (xem mục 7) |
| Tất cả nguồn đều lỗi | Trả dữ liệu cũ trong cache (nếu có, ghi cảnh báo vào log); không có cache thì báo lỗi cho người dùng. Bot không sập |
| Dữ liệu bẩn (BOM, CRLF, trùng lặp) | `data/cleaner.py` chuẩn hoá trước khi ghi cache |
| Mã không tồn tại / chưa đủ lịch sử | Handler bắt lỗi cụ thể, trả tin nhắn dễ hiểu qua `bot/formatters.py:error_card()` |
| Bot vừa khởi động trên máy trắng dữ liệu (lần đầu, hoặc Render gói Free vừa restart) | Bot tự dựng dữ liệu **tạm** cho danh sách theo dõi (`config/universe.yaml`, ~12 mã) trong vài giây — `/loc`, `/tinhieu` có kết quả ngay kèm ghi chú "Dữ liệu tạm thời" — rồi nạp toàn sàn ở nền (vài phút) |
| `/loc`, `/tinhieu` báo đang nạp hoặc báo lỗi | Thông báo nói rõ tiến độ (vd "450/1500 mã, khoảng 2 phút nữa") hoặc lỗi của lần nạp gần nhất. Gõ `/trangthai` để xem chi tiết |

---

## 7. Vận hành và triển khai

Bot dùng **long polling** (`dispatcher.start_polling()`) — không cần mở port, webhook hay tên miền SSL.

### 7.1. Chạy trên máy cá nhân (để thử / phát triển)

Bản chạy chính thức đặt trên Render (mục 7.3). Khi cần chạy thử trên máy:

```bash
python scripts/run_bot.py
```

Không cần đặt `PYTHONPATH` hay `pip install -e .` — script tự thêm `src/`
vào đường dẫn. Log hiện trên cửa sổ và ghi vào **`logs/bot.log`**; đóng cửa
sổ (hoặc `Ctrl+C`) là bot dừng.

> ⚠️ **Tạm dừng service trên Render trước khi chạy trên máy.** Hai tiến
> trình dùng chung một `TELEGRAM_BOT_TOKEN` sẽ tranh nhau nhận tin nhắn và
> Telegram báo lỗi xung đột (`Conflict: terminated by other getUpdates`).

**Cách kiểm tra bot còn sống:** gõ `/trangthai` trên Telegram (trả lời được
là bot đang chạy).

### 7.2. Chạy trên VPS Linux bằng Docker

Repo có sẵn `Dockerfile` và `docker-compose.yml`:

```bash
# 1. Clone code về VPS Linux (Ubuntu / Debian / CentOS)
git clone https://github.com/thienanpham160806-code/bot-phan-tich.git
cd bot-phan-tich

# 2. Cấu hình biến môi trường
cp .env.example .env
nano .env  # Điền TELEGRAM_BOT_TOKEN

# 3. Chạy nền bằng Docker
docker compose up -d --build

# Xem log hoạt động:
docker compose logs -f
```

### 7.3. Triển khai trên Render.com — giới hạn thực tế và lựa chọn

**Giới hạn của gói Free (đã gặp thực tế khi deploy):**

- **512 MB RAM, CPU chia sẻ.** Riêng việc nạp thư viện của bot (aiogram,
  pandas, vnstock) đã chiếm khoảng 250–300 MB, chỉ còn khoảng 200 MB cho
  dữ liệu. Toàn sàn vẫn chạy được nhưng sát giới hạn; vượt là container bị
  tắt và khởi động lại.
- **Không có ổ đĩa lưu bền.** Mọi thứ trong `data/` (kho giá, snapshot,
  danh sách theo dõi, cài đặt cảnh báo của người dùng) **mất sạch mỗi lần
  container khởi động lại** (deploy mới, lỗi, hoặc Render tự khởi động lại).
  Mỗi lần như vậy bot phải nạp lại kho giá từ đầu: vài giây đầu chỉ có dữ
  liệu tạm cho danh sách theo dõi, vài phút sau mới có đủ vũ trụ.
- **Tự ngủ sau ~15 phút không có request HTTP.** Bot chỉ polling Telegram
  ra ngoài, không ai gọi HTTP vào, nên nếu không có dịch vụ ping thì cả
  tiến trình bị dừng (kể cả lịch quét 15:05).
- **Không có Background Worker** (loại phù hợp đúng bản chất bot polling,
  không bị quét port). Gói Free báo *"service type is not available for
  this plan"*, nên phải chạy dưới dạng Web Service kèm health-check HTTP
  giả trong `bot/main.py`.

**Ba lựa chọn:**

| | Lựa chọn | Dữ liệu | Chi phí | Hợp khi |
|---|---|---|---|---|
| **(a)** | **Chạy trên máy cá nhân** (mục 7.1) | Đầy đủ toàn sàn, giữ được qua các lần tắt/mở | Miễn phí | **Demo, chấm bài** — nhanh nhất, ổn định nhất |
| (b) | Render gói trả phí + **Persistent Disk** | Đầy đủ, không mất khi restart | Trả phí hàng tháng | Cần chạy 24/7 lâu dài |
| (c) | Render Free + vũ trụ rút gọn 300 mã + UptimeRobot | Rút gọn, nạp lại mỗi lần restart | Miễn phí | Muốn bot online 24/7 mà không trả phí, chấp nhận hạn chế |

**Khuyến nghị: dùng (a) khi demo và chấm bài.** Chạy `python scripts/run_bot.py`
trên máy cá nhân sau khi đã chạy `scripts/backfill_data.py` và
`scripts/build_snapshot.py` — có ngay dữ liệu toàn sàn, `/loc` trả lời tức
thì. (c) chỉ là phương án dự phòng "cho bot luôn online", không nên dùng để
trình diễn trước hội đồng vì có thể đúng lúc đó container vừa restart và
đang nạp lại dữ liệu.

**Cách làm (b):** nâng service lên gói trả phí → đổi `render.yaml` sang
`type: worker` (không cần health-check/UptimeRobot) → thêm Persistent Disk
gắn vào `/app/data` (thư mục `DATA_DIR` mặc định trong Docker image) →
deploy lại. Bỏ các biến giới hạn quy mô ở (c) để chạy toàn sàn.

**Cách làm (c):**

1. Render → **New +** → **Blueprint** → chọn repo này, nhánh `main` —
   `render.yaml` đã đặt sẵn `UNIVERSE_MAX_SYMBOLS=300`, `MARKET_COUNT_BACK=400`,
   `SNAPSHOT_MAX_WORKERS=1`. **Nếu service được tạo thủ công** (New + →
   Web Service, không qua Blueprint) thì `render.yaml` **không tự áp dụng**:
   phải tự thêm ba biến này trong tab **Environment** của service.
2. Điền `TELEGRAM_BOT_TOKEN` → Deploy.
3. UptimeRobot (miễn phí) → **Add New Monitor** → HTTP(s) →
   `https://<ten-service>.onrender.com/healthz` → Interval **5 phút**.
4. Kiểm tra trên Telegram: `/trangthai` (kho giá, snapshot, tiến độ nạp,
   lỗi gần nhất, RAM) và `/trangthai chandoan` (RAM/CPU thật của container,
   có gọi được Vietcap/DNSE không — gói Free không có Shell nên đây là cách
   chẩn đoán duy nhất). Trên máy cá nhân chạy `python scripts/diagnose.py`.

### 7.4. Lịch chạy tự động

Chạy bằng `APScheduler`, giờ Việt Nam (`bot.timezone`):

1. **Sau phiên sáng — `bot.midday_cron`, mặc định 11:35 thứ 2–6:** tải nến
   đang chạy của hôm nay cho cả kho rồi tính lại snapshot. `/loc`, `/tinhieu`
   có giá phiên sáng, kèm ghi chú "tạm tính" (nến chưa đóng, khối lượng mới
   được nửa phiên). Không gửi cảnh báo. Đặt `midday_cron: ""` để tắt.
2. **Cuối phiên — `bot.scan_cron`, mặc định 15:05 thứ 2–6:** tải lại nến
   đóng cửa (ghi đè nến tạm tính), tính snapshot chính thức, rồi so trạng thái
   các mã người dùng theo dõi (`/sub`) với lần quét trước. Chỉ gửi cảnh báo
   khi có thay đổi: đổi khuyến nghị, MACD giao cắt, giá đổi vị trí so với mây
   Kumo, RSI vào/ra vùng quá mua/quá bán, khối lượng > 2 lần TB20, hoặc giá
   biến động > 4% (tối đa 3 cảnh báo/mã/ngày). Chạy bù trong vòng 1 giờ nếu bot
   khởi động trễ.
3. **Tin tức — `bot.news_cron`, mặc định mỗi giờ 08:00–22:00:** quét RSS
   CafeF và VnExpress, phân loại theo từ khoá (Chính sách – Pháp luật / Vĩ mô
   & TTCK), gửi tin đăng trong 2 giờ gần nhất cho người đang bật bản tin.
   Nguồn "CafeF Vĩ mô" lẫn tin xã hội nên chỉ giữ tin khớp từ khoá.

> ⚠️ **Render gói Free xoá CSDL mỗi lần khởi động lại** (danh sách `/sub`,
> lựa chọn `/tintuc off`...). Bản tin tin tức vẫn tự phục hồi: chat nào nhắn
> bot bất kỳ lệnh nào đều được bật sẵn bản tin (middleware `AutoSubscribeNews`
> trong `bot/main.py`), nên sau khi restart chỉ cần nhắn bot một lần. Muốn
> nhận tin ngay cả khi chưa kịp nhắn lại: đặt biến **`AUTO_SUBSCRIBE_CHAT_IDS`**
> (các chat id, cách nhau dấu phẩy) trong tab Environment.

---

## 8. Giấy phép thư viện

Dự án dùng cho mục đích học tập. Lưu ý điều khoản của một số thư viện:

- `vnstock` — giấy phép tuỳ chỉnh, miễn phí cho mục đích cá nhân, dùng thương mại cần xin phép tác giả.
- DNSE LightSpeed API — có ràng buộc về việc phân phối lại dữ liệu, đọc kỹ điều khoản dịch vụ trước khi public repo.

---

## 9. Miễn trừ trách nhiệm

Đây là sản phẩm học thuật. Mọi tín hiệu do bot sinh ra **không phải** khuyến nghị đầu tư.
