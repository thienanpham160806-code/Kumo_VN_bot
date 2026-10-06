# Ghi chú phỏng vấn — nâng cấp backtest (nhánh `quant-upgrade`)

Tài liệu ôn tập cho buổi phỏng vấn quant developer / quant engineer. Mỗi mục
ghi: lỗi cũ là gì, vì sao làm sai kết quả, sửa thế nào, con số trước/sau, và
vài câu interviewer hay hỏi kèm gợi ý trả lời. Mọi con số đều lấy từ lần chạy
thật; nguồn ghi ngay bên cạnh để mở ra đối chiếu khi bị hỏi.

---

## Tóm tắt 30 giây (nói khi được hỏi "kể về dự án của bạn")

> Tôi xây một bot Telegram phân tích kỹ thuật cổ phiếu Việt Nam, hợp lưu MACD,
> RSI và Ichimoku trên ~1.500 mã. Sau đó tôi đưa phần backtest lên chuẩn định
> lượng: khớp lệnh giá mở cửa phiên sau, T+2, gap qua stop, kẹt giá sàn, vũ trụ
> chọn theo thời điểm, walk-forward, Deflated Sharpe, phân tích IC. Kết quả:
> **chiến lược không có lợi thế**. Walk-forward out-of-sample lỗ 33% trong
> khi VN-Index tăng 44%, DSR = 0,002, và cả 12/12 bộ tham số đều lỗ. Điều tôi
> tự hào nhất là hạ tầng đủ chặt để tự bác bỏ được chiến lược của chính mình
> thay vì tự lừa mình bằng một backtest đẹp.

Câu chốt nên nhớ: *"Backtest cũ báo −33,7%. Sau khi sửa lỗi phương pháp nó
còn tệ hơn, −42,6%, và tôi báo cáo đúng như vậy."*

### Bảng số liệu nhanh

| Chỉ tiêu | Giá trị | Nguồn |
|---|---|---|
| Walk-forward OOS (11/2024–09/2026) | −33,4%, CAGR −19,9%, Sharpe −1,39, MDD −44,3% | `outputs/backtest/report.md` |
| VN-Index cùng kỳ | +44,1%, CAGR +22,1%, Sharpe 1,09 | như trên |
| Tham số mặc định, cả kỳ (11/2023–09/2026) | −42,6%, CAGR −17,8%, Sharpe −1,21 | như trên |
| PSR / DSR của walk-forward | 0,023 / 0,002 | như trên |
| Số tổ hợp tham số lỗ trên cả kỳ | 12/12 (CAGR −12% đến −27%) | `grid_full_period.csv` |
| Vòng quay | 25–30 lần vốn/năm, giữ lệnh trung vị 4 phiên | `report.md`, `trades_full_period.csv` |
| IC điểm tổng, h = 20 phiên | +0,023, t Newey-West 1,72 (không có ý nghĩa) | `outputs/ic/ic_summary.csv` |
| IC điểm tổng, h = 1 phiên | −0,020, t Newey-West −4,1 (đảo chiều ngắn hạn) | như trên |
| Engine gốc → đã sửa (cùng tín hiệu) | −33,7% → −42,6% | `outputs/backtest/engine_ablation.csv` |
| Tốc độ sinh tín hiệu | nhanh hơn ~125–150 lần (100 mã: 1.734,6 s → 13,8 s), khớp 100% | `docs/benchmark.md` |
| Số test | 209 → 274 | `pytest -q` |

---

## 1. T+2: không được bán ngay phiên sau khi mua

**Lỗi cũ.** `backtest/engine.py` mua ở phiên T và cho bán ngay ở T+1 nếu chạm
stop/target. Config đã có `costs.settlement_days: 2`, `risk/constraints.py` đã
có hàm kiểm tra T+2, nhưng engine không gọi.

**Vì sao sai.** Ở Việt Nam, cổ phiếu mua phiên T phải đến T+2 mới về tài khoản.
Giống như mua vé xe khách mà 2 ngày sau mới nhận vé: bạn không thể bán lại vé
vào ngày mai dù giá vé đang hời. Backtest cho bán sớm là đang "mượn" một quyền
mà nhà đầu tư thật không có.

**Sửa.** Engine ghi lại chỉ số phiên lúc mua và chỉ xét thoát lệnh khi
`constraints.is_settled(entry_session, today_session)` đúng. Điểm quan trọng:
đếm theo **phiên giao dịch** trong lịch, không đếm theo ngày trong tuần. Dịp
Tết nghỉ cả tuần, nếu đếm theo ngày làm việc thì "T+2" rơi vào kỳ nghỉ và phiên
mở cửa đầu tiên thực chất mới là T+1.

**Trước → sau** (cùng một bộ tín hiệu, `engine_ablation.csv`):
- Engine gốc: **717/2.323 lệnh (31%)** bán ngay ngày làm việc kế tiếp.
- Lợi nhuận cả kỳ: −33,7% → **−23,2%**. Sửa T+2 làm kết quả *tốt lên*.

**Câu hỏi có thể gặp.**
- *"Sửa ràng buộc mà kết quả lại tốt lên, có phải bug không?"* — Không. Phân
  tích IC cho thấy đảo chiều ngắn hạn rất mạnh (IC 1 phiên âm, t ≈ −4 đến −8).
  Bị buộc giữ qua T+1 nghĩa là không bị "rũ" ra ở đáy nhịp điều chỉnh. Một ràng
  buộc thật vẫn có thể giúp kết quả; quan trọng là mô hình đúng thực tế, không
  phải mô hình cho đẹp.
- *"Cổ phiếu về tài khoản lúc nào trong phiên T+2?"* — Tôi cho bán ngay từ giá
  mở cửa phiên T+2. Nếu quy định hiện hành chỉ cho bán từ một thời điểm trong
  phiên T+2 (cần kiểm tra lại với công ty chứng khoán), mô hình hơi lạc quan với
  lệnh dừng lỗ đầu phiên. Có thể chặt hơn bằng cách chỉ cho khớp ở giá đóng cửa
  T+2.
- *"Sao không dùng luôn hàm `is_sellable` có sẵn?"* — Hàm đó đếm ngày trong
  tuần, đủ cho bot nhưng sai quanh ngày lễ. Tôi thêm `is_settled` đếm theo
  phiên; cả hai đọc cùng một `settlement_days`.

---

## 2. Gap qua stop/target: khớp ở giá mở cửa

**Lỗi cũ.** Nếu giá mở cửa đã thấp hơn stop, engine vẫn ghi khớp **đúng bằng
giá stop**. Tương tự khi mở cửa đã vượt target.

**Vì sao sai.** Bạn hẹn bán khi giá xuống 95.000đ, nhưng sáng mở cửa giá đã là
88.000đ: không ai mua của bạn ở 95.000đ nữa. Giá 95.000đ không hề giao dịch
trong phiên đó, backtest "khớp" ở một mức giá không tồn tại.

**Sửa.** Mở cửa ≤ stop thì khớp ở giá mở cửa; mở cửa ≥ target cũng khớp ở giá mở
cửa (lệnh giới hạn bán khớp ở giá tốt hơn). Nếu trong phiên chạm cả stop lẫn
target mà không gap, giả định bi quan là stop chạm trước.

**Trước → sau.** −23,2% → **−35,9%**. Trong backtest cả kỳ có 345 lệnh gap qua
stop (trung bình −6,7%/lệnh, tệ hơn lệnh dừng lỗ thường −5,0%) và 167 lệnh gap
qua target (+10,7%/lệnh). Gap có cả hai chiều, nhưng chiều xấu nhiều gấp đôi.

**Câu hỏi có thể gặp.**
- *"Sàn Việt Nam có lệnh stop chuẩn không?"* — HOSE không có lệnh dừng chuẩn;
  các công ty chứng khoán cung cấp lệnh điều kiện, khi kích hoạt thì đẩy lệnh
  vào sàn. Tôi mô hình đúng hành vi đó: khi kích hoạt, khớp ở giá thị trường
  tốt nhất còn có (giá mở cửa nếu gap).
- *"Chạm cả stop và target trong cùng một nến thì sao?"* — Không biết thứ tự
  nếu chỉ có dữ liệu ngày, nên chọn kịch bản bi quan (stop trước). Muốn chính
  xác cần dữ liệu trong phiên.
- *"Còn trượt giá khi khớp ở giá mở cửa?"* — Chưa mô hình riêng; đã giới hạn
  khối lượng ≤ 10% khối lượng phiên. Bước tiếp theo là cộng thêm một khoản
  trượt giá theo spread và ATR.

---

## 3. Giá sàn: phiên trắng bên mua thì không bán được

**Lỗi cũ.** Engine không biết biên độ giá. Phiên giá đóng ở giá sàn, cả thị
trường muốn bán mà không ai mua, nhưng backtest vẫn cho khớp lệnh dừng lỗ.

**Vì sao sai.** Giống như chợ vỡ: ai cũng muốn bán, không ai mua. Bạn xếp hàng
bán ở giá sàn nhưng hàng nghìn người đứng trước bạn. Bán được trong backtest
là không có thật.

**Sửa.** `risk/constraints.floor_locked()` đánh dấu phiên "kẹt sàn": close ở giá
sàn (giá tham chiếu = close phiên trước, nhân 0,93 với HOSE, 0,90 với HNX, 0,85
với UPCOM; sàn của từng mã lấy từ `symbols.parquet`) **và** low == close. Lệnh
bán dời sang phiên kế tiếp, khớp ở giá mở cửa phiên đầu tiên không còn kẹt.
Chi tiết kỹ thuật đáng kể: giá trong kho đã **điều chỉnh cổ tức** nên không nằm
trên lưới bước giá. So sánh bằng tuyệt đối sẽ trượt, nên tôi chấp nhận sai số
một bước giá (giá sàn thật được làm tròn lên theo bước giá).

**Trước → sau.** Bộ phát hiện đánh dấu 2,5% số phiên (ví dụ HPG ngày 3 và 8–9/4/
2025, đợt bán tháo vì thuế quan). Lợi nhuận −35,9% → **−42,6%**. Có 63 lệnh bị
dời; trung bình chúng lỗ −10,6%/lệnh, so với −5,0% của lệnh dừng lỗ thường.

**Câu hỏi có thể gặp.**
- *"Quy tắc có quá bảo thủ không?"* — Có. Nếu sáng còn cao rồi chiều mới về
  sàn, lệnh dừng lỗ có thể đã khớp trước đó. Quy tắc này chặn cả phiên, nên là
  cận dưới. Muốn chính xác cần dữ liệu trong phiên hoặc sổ lệnh.
- *"Còn chiều mua, giá trần thì sao?"* — Chưa mô hình. Mua ở giá mở cửa của
  phiên kẹt trần (trắng bên bán) cũng không khớp được. Đây là bước tiếp theo
  hợp lý, đối xứng với giá sàn.
- *"Vì sao không dùng `close == floor` chính xác?"* — Vì giá đã điều chỉnh: chỉ
  ~41% giá đóng cửa trong kho nằm trên lưới bước giá. Dùng sai số một bước giá
  cộng điều kiện `low == close` là đủ chặt.

---

## (Bổ sung) Định giá phiên thiếu dữ liệu và engine nhanh hơn

**Lỗi cũ.** Ngày một mã đang nắm giữ không có phiên (tạm ngừng giao dịch, thiếu
dữ liệu), engine định giá nó bằng **giá vào lệnh** thay vì giá đóng cửa gần
nhất. Đường vốn nhảy lên xuống vô cớ ở những ngày đó.

**Sửa và con số.** Dùng giá đóng cửa gần nhất. Trong test, một vị thế đã lãi
20% bị định giá lại về giá vốn vào ngày thiếu dữ liệu: vốn 101,99 triệu bị ghi
thành 99,99 triệu. Cùng commit, engine chuyển sang tra mảng numpy theo chỉ số
phiên thay cho `DataFrame.loc`. Trên 150 mã thanh khoản và 2.352 tín hiệu, thời
gian chạy giảm **2,73 s → 0,24 s** với danh sách lệnh và đường vốn giống hệt.
Đây là điều kiện để walk-forward chạy hàng trăm lần.

---

## 4. Sinh tín hiệu: từ O(n²) sang vectorized

**Lỗi cũ.** `generate_buy_signals` gọi `recommend()` trên `frame.iloc[:i+1]` ở
**mỗi** phiên i, nghĩa là mỗi phiên tính lại mọi chỉ báo trên toàn bộ lịch sử.

**Vì sao chậm.** Giống như muốn biết số dư tài khoản mỗi ngày mà lần nào cũng
cộng lại toàn bộ sao kê từ đầu năm, thay vì lấy số dư hôm qua cộng giao dịch
hôm nay. 750 phiên nghĩa là khoảng 750²/2 phép tính lặp.

**Sửa.** `analysis/score_history.py` tính chỉ báo **một lần** cho cả chuỗi rồi
suy ra trạng thái từng phiên. Điều này đúng vì mọi chỉ báo đều **nhân quả**:
EMA (`adjust=False`), làm mượt Wilder, rolling max/min/mean/quantile, nên giá
trị tại t chỉ phụ thuộc dữ liệu ≤ t. Các phép "giá trị hợp lệ cuối cùng" thành
forward-fill; "số phiên từ lần cắt cuối" thành chỉ số lần đổi dấu gần nhất.
Phần khó nhất là phân kỳ: đỉnh/đáy cục bộ tại vị trí p chỉ phụ thuộc
[p−5, p+5], nên tính cờ đỉnh/đáy cho cả chuỗi một lần, rồi mỗi phiên chỉ cần
vài phép tìm nhị phân để lấy các đỉnh/đáy trong cửa sổ 60 phiên. Chấm điểm vẫn
gọi lại đúng `score_macd/score_rsi/score_ichimoku`, nên logic MUA/BÁN chỉ có
một nguồn.

**Trước → sau** (`docs/benchmark.md`, máy đang rảnh):
- 1 mã (FPT, 752 phiên): 9,0 s → 0,06 s (149×).
- 100 mã thanh khoản nhất: 9,0 s00 → 0,06 s00 (~126×).
- Thời gian tuyệt đối dao động theo nhiệt độ/xung nhịp laptop (bản cũ 7,6–41,4 s
  mỗi mã trong cùng một lần chạy), tỷ số thì ổn định: lần đo trước ra 138× và
  139×. Nên nói "nhanh hơn khoảng 125–150 lần".
- Khớp **100/100 mã, 1.629 tín hiệu trùng khớp tuyệt đối**. Điểm từng phiên lệch
  tối đa ~1e-13 so với `recommend()`.

**Câu hỏi có thể gặp.**
- *"Làm sao chứng minh không nhìn trước tương lai?"* — Có test thay **toàn bộ**
  dữ liệu sau phiên t bằng dữ liệu ngẫu nhiên khác: điểm tại mọi phiên ≤ t giữ
  nguyên đến từng bit. Thêm test so từng phiên với `recommend(frame[:t+1])`.
  Lưu ý Ichimoku: Chikou dùng `shift(-26)` (nhìn trước) nhưng không đi vào
  điểm số; Senkou dùng `shift(+26)` là hợp lệ.
- *"Phân kỳ dùng cửa sổ trung tâm ±5 phiên, có nhìn trước không?"* — Không. Đỉnh
  tại p chỉ được công nhận khi đã có dữ liệu đến p+5 ≤ t, tức xác nhận trễ 5
  phiên, giống hệt bản gốc.
- *"Sao lệch 1e-13 mà không bằng nhau tuyệt đối?"* — Độ dốc tính bằng công thức
  đóng thay vì `np.polyfit`. Sai số dấu phẩy động không đổi được quyết định
  MUA nào (test kiểm chứng danh sách tín hiệu giống hệt).
- *"Vẫn còn vòng lặp Python theo phiên?"* — Có, một vòng O(n) gọi lại các hàm
  chấm điểm có sẵn, cộng phần phân kỳ O(n log n). Tôi chọn giữ một nguồn logic
  thay vì viết lại công thức bằng numpy để nhanh thêm vài lần.

---

## 5. Walk-forward thật

**Lỗi cũ.** Hàm walk-forward không tối ưu gì trong cửa sổ train (chỉ bỏ qua nó),
không được gọi ở đâu, và tính chỉ số mỗi lát trên đường vốn trải **cả lịch**.

**Vì sao sai.** Walk-forward giống ôn thi bằng đề các năm trước rồi thi đề năm
nay: phải chọn cách học dựa trên đề cũ, rồi giữ nguyên cách đó khi thi. Bản cũ
không "học" gì cả. Còn tính chỉ số trên cả lịch giống chấm điểm bài thi 15 phút
nhưng chia cho thời gian của cả năm học.

**Sửa.** Mỗi lát: chạy 12 tổ hợp (ngưỡng MUA 50/60/70 × Ichimoku 9-26-52 hoặc
7-22-44 × giữ tối đa 10/20 phiên) trên 12 tháng train, chọn Sharpe cao nhất, áp
nguyên lên 3 tháng test kế tiếp. Vốn đầu lát = vốn cuối lát trước. Các đoạn test
ghép thành **một** đường vốn out-of-sample. Chỉ số mỗi lát chỉ tính trên đúng
các phiên của lát. Đã nối vào `scripts/run_backtest.py`.

**Trước → sau.**
- Lỗi chỉ số theo lát (dữ liệu giả tăng đều 2 năm): lát 3 tháng của bản cũ bị
  tính trên 520 phiên, nên CAGR báo **0,7%** thay vì khoảng **5,3%**.
- Trên dữ liệu thật, walk-forward OOS 8 lát: **−33,4%** (VN-Index +44,1%).
  Trong 7/8 lát, tổ hợp tốt nhất trên train vẫn có Sharpe train âm. Tham số
  được chọn nhảy qua lại giữa các lát. Cả hai đều là dấu hiệu không có lợi thế
  ổn định.

**Câu hỏi có thể gặp.**
- *"Sharpe train tốt nhất còn âm mà vẫn giao dịch?"* — Đúng, thuật toán chỉ
  argmax. Thêm lựa chọn "đứng ngoài khi Sharpe train < 0" là hợp lý, nhưng
  thêm nó **sau khi** đã thấy kết quả OOS là data snooping. Nếu làm, phải coi
  đó là thử nghiệm thứ 13 và tính vào DSR.
- *"Cửa sổ cuốn hay neo (anchored)?"* — Cuốn 12 tháng, để thích nghi với chế độ
  thị trường. Neo dùng nhiều dữ liệu hơn nhưng phản ứng chậm. Với chỉ ~3 năm dữ
  liệu, cả hai đều ít lát; đây là giới hạn của mẫu.
- *"Đóng vị thế cuối mỗi lát có làm méo kết quả?"* — Có tốn thêm phí. Đổi lại
  mỗi lát độc lập và đúng tham số của lát. Để mọi vị thế bán được theo T+2,
  engine không mở lệnh mới trong 2 phiên cuối lát.

---

## 6. Probabilistic & Deflated Sharpe Ratio

**Lỗi cũ.** Hàm `deflated_sharpe` lấy Sharpe năm trừ một đại lượng z-score chia
√T: hai thứ khác đơn vị. Nó bỏ qua skew/kurtosis và độ phân tán Sharpe giữa các
lần thử, và trả về một số kiểu Sharpe chứ không phải xác suất. Trên chính ví dụ
số trong bài báo gốc, hàm cũ trả **2,43**; đáp án đúng là **0,9004**.

**Vì sao quan trọng.** Tung 12 đồng xu, đồng nào ra ngửa nhiều nhất cũng không
phải đồng xu "giỏi" hơn. Thử càng nhiều cấu hình, cấu hình đẹp nhất càng có
khả năng đẹp nhờ may mắn.

**Sửa.** Cài đúng Bailey & López de Prado (2014):
- PSR(SR\*) = Φ( (SR − SR\*)·√(T−1) / √(1 − γ₃·SR + (γ₄−1)/4·SR²) ), với SR theo
  ngày (không annualize), γ₃ = skew, γ₄ = kurtosis (không trừ 3).
- DSR = PSR(SR₀), với SR₀ = √V[SR] · ((1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(N·e))),
  γ = hằng số Euler-Mascheroni.
- N = 12 tổ hợp ở mục 5; V[SR] = phương sai Sharpe ngày giữa 12 tổ hợp.
- Test tái tạo ví dụ của bài báo (SR₀ = 0,1132; DSR = 0,9004) và một PSR tính
  tay (0,840741).

**Kết quả.** Walk-forward PSR 0,023, DSR **0,002**. Tổ hợp tốt nhất in-sample
(Sharpe −0,78): DSR 0,013. Cả hai cùng nói: không có bằng chứng Sharpe thật > 0.

**Câu hỏi có thể gặp.**
- *"12 tổ hợp tương quan cao, N hiệu dụng có nhỏ hơn 12 không?"* — Có. Các tổ
  hợp chỉ khác ngưỡng/preset nên tương quan mạnh. N hiệu dụng nhỏ hơn (có thể
  ước lượng bằng phân cụm ma trận tương quan lợi suất). Dùng N = 12 là hơi khắt
  khe, nhưng ở đây PSR đã gần 0 nên không đổi kết luận.
- *"Vì sao skew âm làm PSR giảm?"* — Chiến lược kiểu "nhặt tiền lẻ trước xe lu"
  có Sharpe đẹp nhưng đuôi trái dày. Mẫu số 1 − γ₃·SR + (γ₄−1)/4·SR² tăng khi
  γ₃·SR < 0 (skew âm, Sharpe dương) hoặc kurtosis lớn, nên cùng một Sharpe sẽ
  kém đáng tin hơn.
- *"Vì sao dùng T−1 và Sharpe theo ngày?"* — Công thức là sai số chuẩn của ước
  lượng Sharpe trên T quan sát; annualize trước sẽ sai đơn vị (đúng lỗi của bản
  cũ).

---

## 7. Vũ trụ cổ phiếu theo thời điểm (chống survivorship bias)

**Lỗi cũ.** `run_backtest.py` gọi `liquid_universe()` với ngày **hôm nay** rồi
dùng danh sách đó cho cả quá khứ. Ngoài ra, `liquid_universe(as_of)` vẫn giữ
những mã đã ngừng giao dịch từ lâu, chỉ vì 20 phiên cuối cùng của chúng (từ năm
2024) thanh khoản tốt.

**Vì sao sai.** Giống chọn ra "những học sinh giỏi nhất khoá" dựa trên điểm thi
tốt nghiệp, rồi kết luận lớp này học giỏi ngay từ lớp 1. Mã thanh khoản hôm nay
thường là mã đã sống sót và tăng trưởng; mã "chết" giữa chừng bị loại khỏi danh
sách một cách vô hình.

**Sửa.** Walk-forward nhận `universe_fn(as_of)`, gọi với as_of = ngày **trước**
khi cửa sổ train/test bắt đầu, chỉ dùng dữ liệu đến đó. Backtest cả kỳ lọc theo
vũ trụ của tháng (dữ liệu đến hết tháng trước). Mã có phiên cuối cũ hơn 14 ngày
so với phiên mới nhất ≤ as_of bị coi là đã ngừng giao dịch. Mốc đo là phiên mới
nhất trong dữ liệu chứ không phải ngày lịch, để bot không hỏng khi kho chậm cập
nhật.

**Trước → sau.** Vũ trụ thanh khoản hôm nay có 222 mã. Vũ trụ đúng tại cuối 2023
có 264 mã. Trong 222 mã hôm nay, **47 mã khi đó chưa đủ thanh khoản** (bản cũ vẫn
cho giao dịch từ ngày đầu). Ngược lại, **89 mã đủ thanh khoản khi đó** bị bản cũ
loại bỏ (phần lớn là mã sau này yếu đi).

**Câu hỏi có thể gặp.**
- *"Còn survivorship bias nào sót lại?"* — Có hai. (1) Mã đã huỷ niêm yết từ
  trước khi dựng kho thì không có trong kho. (2) Sàn của mã lấy theo danh sách
  hiện tại, nên mã chuyển từ UPCOM lên HOSE bị xếp theo sàn mới. Sửa triệt để
  cần dữ liệu lịch sử niêm yết.
- *"Sao chỉ yêu cầu 60 phiên lịch sử thay vì 250?"* — Kho chỉ giữ ~750 phiên
  gần nhất của mỗi mã nên không biết ngày niêm yết thật. Yêu cầu 250 phiên sẽ
  làm vũ trụ rỗng trong năm đầu. 60 phiên là mức khởi động chỉ báo.

---

## 8. Phân tích Information Coefficient

**Làm gì.** Mỗi phiên, trên mặt cắt ~280 mã trong vũ trụ thời điểm, tính tương
quan hạng Spearman giữa điểm (MACD, RSI, Ichimoku, tổng) và lợi suất từ giá mở
cửa t+1 đến t+1+h. Báo cáo IC trung bình, độ lệch chuẩn, ICIR, t-stat thường và
t-stat Newey-West, tỷ lệ tháng có IC > 0. Đầu ra ở `outputs/ic/`.

**Ví dụ đời thường.** IC giống chấm một dự báo thời tiết theo kiểu "xếp hạng":
không cần đoán đúng lượng mưa, chỉ cần ngày dự báo mưa nhiều thì đúng là mưa
nhiều hơn ngày dự báo mưa ít.

**Kết quả** (02/01/2024–22/09/2026, 675 phiên):
- Mọi |IC| ≤ 0,023 ở h = 5–20. Không hệ nào có ý nghĩa sau hiệu chỉnh Newey-West
  (t cao nhất 1,72).
- t-stat thường ở h = 10–20 là 3,5–5,2, trông rất "có ý nghĩa", nhưng bị thổi
  phồng 2–3 lần do các cửa sổ lợi suất chồng lấn.
- Đảo chiều ngắn hạn: IC 1 phiên của RSI là −0,038 (t NW −7,7, chỉ 6% số tháng
  dương); của điểm tổng là −0,020 (t NW −4,1). Mã điểm cao có xu hướng giảm lại
  ngay sau đó, đúng lúc chiến lược mua vào.

**Câu hỏi có thể gặp.**
- *"Vì sao Newey-West với độ trễ h?"* — Lợi suất h phiên của hai ngày liền nhau
  chung h−1 phiên, nên chuỗi IC ngày tự tương quan đến bậc khoảng h−1. Sai số
  chuẩn thường giả định độc lập nên quá nhỏ. Newey-West (trọng số Bartlett) cộng
  các tự hiệp phương sai vào.
- *"IC 0,02 có đáng tiền không?"* — Theo "fundamental law", IR ≈ IC·√(số cược
  độc lập), nên IC nhỏ trên nhiều mã về lý thuyết vẫn có giá trị. Nhưng ở đây
  IC không có ý nghĩa thống kê, các mã tương quan nên số cược độc lập nhỏ hơn
  nhiều, và vòng quay cao ăn hết phần lợi thế mỏng.
- *"Spearman hay Pearson?"* — Spearman (theo hạng) bền với giá trị ngoại lai và
  không cần quan hệ tuyến tính, phù hợp vì điểm số là thang thứ bậc [−100, 100].
- *"IC âm ngắn hạn có khai thác được không?"* — Có thể là giả thuyết cho chiến
  lược ngược chiều ngắn hạn. Nhưng nó đến từ chính dữ liệu này, nên phải kiểm
  định trên dữ liệu mới, tính chi phí (vòng quay rất cao ở h = 1), và Việt Nam
  gần như không bán khống được.

---

## 9. Backtest đầy đủ so với VN-Index

**Làm gì.** Toàn bộ kho (1.511 mã), từ 14/11/2023 đến 24/09/2026. Chạy tham số mặc
định cả kỳ, 12 tổ hợp cả kỳ, walk-forward OOS, so với VN-Index mua và giữ cùng kỳ.
Báo cáo CAGR, Sharpe, Sortino, MDD, vòng quay, số lệnh, PSR/DSR, và độ nhạy phí
0,15% / 0,25% / 0,35%. Bảng gốc: `outputs/backtest/report.md`.

**Kết quả chính.**

| | Lợi nhuận | CAGR | Sharpe | MDD | DSR |
|---|---:|---:|---:|---:|---:|
| Walk-forward OOS | −33,4% | −19,9% | −1,39 | −44,3% | 0,002 |
| VN-Index cùng kỳ | +44,1% | +22,1% | 1,09 | −18,1% | – |
| Tham số mặc định, cả kỳ | −42,6% | −17,8% | −1,21 | −47,7% | 0,001 |
| VN-Index cả kỳ | +60,0% | +18,1% | 1,01 | −18,1% | – |

Độ nhạy phí (mặc định, cả kỳ): CAGR −14,9% / −17,8% / −19,4% ở phí 0,15% /
0,25% / 0,35%. Phí làm tệ thêm nhưng không phải nguyên nhân gốc: trước phí mỗi
lệnh đã lỗ trung bình −0,31%.

**Vì sao chiến lược thua.** Thắng 36% số lệnh. Lệnh thắng trung bình +8,5%
(target 3 ATR), lệnh dừng lỗ trung bình −5,0% (1,5 ATR hoặc Kijun). Kỳ vọng xấp
xỉ 0,36·8,5 − 0,64·5,0 ≈ −0,15% trước gap và phí, rồi gap, giá sàn, phí và
thuế kéo xuống −0,66%/lệnh. Vòng quay 25–30 lần vốn/năm khuếch đại chi phí.
Kết hợp với IC ≈ 0 và đảo chiều ngắn hạn: không có lợi thế để bù chi phí.

**Câu hỏi có thể gặp.**
- *"Chiến lược lỗ, sao vẫn đưa lên CV?"* — Vì sản phẩm thật là hạ tầng kiểm định
  và cách làm việc: tôi phát hiện backtest cũ lạc quan sai, sửa từng lỗi có
  test chứng minh, và báo cáo kết quả xấu đúng như nó là. Ở quỹ, một nhà nghiên
  cứu dám nói "không có alpha" quý hơn một backtest đẹp do overfit.
- *"Nếu làm tiếp, bạn làm gì?"* — (1) Đăng ký trước giả thuyết mới (ví dụ đảo
  chiều ngắn hạn) rồi kiểm định trên dữ liệu chưa dùng. (2) Mô hình giá trần cho
  chiều mua và trượt giá. (3) Thêm lịch sử (5–10 năm) để có nhiều chu kỳ. (4)
  Giảm vòng quay bằng bộ lọc tín hiệu hoặc thời gian giữ tối thiểu.
- *"Sao không so với VN-Index có cổ tức hoặc ETF?"* — VN-Index là chỉ số giá
  nên benchmark hơi thấp hơn thực tế (không có cổ tức). Dù vậy chiến lược vẫn
  thua ~40 điểm %, nên kết luận không đổi.
- *"Kỳ vọng tính bằng R của bạn bị méo?"* — Có. `recommend()` có thể đặt stop
  tại Kijun, sát giá chỉ 0,1%, nên rủi ro mỗi cổ phiếu gần 0 và bội số R của lệnh
  gap phát nổ (trung bình −945R). Vì vậy tôi không báo cáo chỉ số R ra ngoài.
  Đây cũng là một phát hiện về thiết kế stop.

---

## 10. vnstock thành phụ thuộc tuỳ chọn

**Lỗi cũ.** `requirements.txt` bắt buộc `vnstock`, gói đang bị PyPI cách ly từ
25/09/2026, nên `pip install -r requirements.txt` hỏng trên máy mới. Code thật ra
đã import vnstock bên trong hàm, nhưng một gói hỏng làm hỏng cả bước cài đặt.

**Ví dụ đời thường.** Một nhà cung cấp rau đóng cửa không nên làm cả nhà hàng
đóng cửa; chỉ món cần rau đó tạm hết.

**Sửa.** Bỏ khỏi `requirements.txt`; khai báo trong `pyproject.toml` dạng extra
`pip install ".[vnstock]"`. Mọi chỗ import vnstock bắt cả `ImportError` lẫn lỗi
hoặc `SystemExit` khi vnai khởi tạo, và đổi thành `ProviderError` để router
chuyển nguồn. Header cho endpoint công khai có bản dự phòng. Dockerfile thử cài
vnstock nhưng không làm hỏng build.

**Trước → sau.** Trước: cài đặt thất bại trên máy mới. Sau: dựng venv Python 3.11
sạch, chỉ `requirements.txt`, không có vnstock: cài được, ruff sạch, 274 test pass.

**Câu hỏi có thể gặp.**
- *"Sao không ghim (pin) phiên bản cũ?"* — Bị cách ly là cả gói không tải được,
  ghim phiên bản không giúp gì. Đây cũng là vấn đề an ninh chuỗi cung ứng:
  phụ thuộc bên thứ ba nên tách khỏi đường chạy chính.

---

## 11. CI với GitHub Actions

**Sửa.** `.github/workflows/ci.yml` chạy `ruff` và `pytest` mỗi lần push/PR, trên
Python 3.11 (giống Docker/Render) và 3.12. CI cố ý **không** cài vnstock, nên mỗi
lần chạy cũng là phép thử "máy mới có cài và chạy được không".

**Câu hỏi có thể gặp.**
- *"Test có phụ thuộc mạng hoặc dữ liệu local không?"* — Không. Test dùng dữ liệu
  giả có seed cố định và kho tạm (`tmp_path`). Test hiệu năng đặt ngưỡng rộng
  (750 phiên < 2 giây; bản cũ 18 giây) để không chập chờn trên máy CI chậm.

---

## 12–13. README tiếng Anh và tài liệu này

README có đoạn mở đầu tiếng Anh (~150 từ): kiến trúc, phương pháp backtest
(next-open fill, T+2, giá sàn, phí, walk-forward, PSR/DSR) và bảng kết quả thật
từ mục 8–9. Phần tiếng Việt giữ nguyên bên dưới, thêm mục 5b (IC và backtest).

---

## Câu hỏi tổng quát hay gặp

- **"Làm sao bạn biết test của mình kiểm tra đúng thứ cần kiểm tra?"** — Với
  mỗi lỗi, tôi viết test trước, chạy trên code cũ để thấy nó **fail** vì đúng lý
  do (ví dụ lệnh bị đóng ở T+1, khớp 95 thay vì 88), rồi mới sửa code để nó pass.
  Với tính năng mới (DSR, IC), test so với giá trị tính tay hoặc ví dụ trong bài
  báo gốc.
- **"Lỗi nào nguy hiểm nhất trong backtest?"** — Look-ahead và survivorship, vì
  chúng làm kết quả *đẹp lên* mà không để lại dấu vết rõ ràng. Lỗi làm kết quả
  xấu đi thường bị phát hiện; lỗi làm đẹp thì không ai đi tìm.
- **"Nếu kết quả backtest tốt, bạn sẽ nghi ngờ điều gì đầu tiên?"** — Nhìn
  trước (tín hiệu dùng giá đóng cửa nhưng khớp cùng phiên), survivorship, chi
  phí và thanh khoản không thực tế, và số lần đã thử (dùng DSR).
- **"Vì sao Sharpe out-of-sample không bằng in-sample?"** — Thiên lệch chọn lọc:
  tổ hợp tốt nhất in-sample (CAGR −12,3%) được chọn *vì* may mắn trên chính mẫu
  đó. Out-of-sample không còn lợi thế chọn lọc. DSR định lượng phần may mắn này.
