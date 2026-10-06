# Cong thuc va nguong

> Moi trong so/nguong duoi day la GIA TRI KHOI DIEM de bat dau kiem thu,
> khong phai gia tri toi uu. Phai hieu chinh lai tren du lieu that va bao cao
> ket qua tren tap chua tung dung de hieu chinh (xem `backtest/walk_forward.py`).
> Tat ca nam trong `config/settings.yaml`, khong hard-code trong ma nguon.

## 1. MACD — `indicators/macd.py`

```
EMA_n(t) = alpha*P(t) + (1-alpha)*EMA_n(t-1),   alpha = 2/(n+1)
MACD     = EMA_12 - EMA_26
Signal   = EMA_9(MACD)
Hist     = MACD - Signal
```

Trang thai suy ra (`macd_state`): `cross` (giao cat "golden"/"death" giua
MACD va Signal), `bars_since_cross`, `hist_slope` (do doc histogram 3 phien
gan nhat), `above_zero`.

Quy uoc: giao cat **tren** duong 0 manh hon giao cat **duoi** duong 0;
histogram thu hep dan du chua giao cat la dau hieu dong luc suy yeu som.

## 2. RSI thich ung — `indicators/rsi.py`

```
RSI 14 phien, lam muot Wilder: ewm(alpha=1/14, adjust=False)
```

**Khong dung nguong cung 30/70.** Nguong thich ung theo phan vi lich su cua
chinh ma do:

```
upper(t) = phan_vi_90(RSI, 252 phien gan nhat), kep trong [65, 85]
lower(t) = phan_vi_10(RSI, 252 phien gan nhat), kep trong [15, 35]
```

Ly do: trong xu huong tang manh, RSI co the nam tren 70 nhieu tuan lien -
ban theo nguong cung la ban mat hang tot. Nguong thich ung tu dieu chinh theo
"vung binh thuong" cua rieng ma do.

## 3. Ichimoku Kinko Hyo — `indicators/ichimoku.py`

Ca nam thanh phan, khong cat bot:

```
Tenkan-sen (Chuyen) = (max(High,9)  + min(Low,9))  / 2
Kijun-sen  (Co so)  = (max(High,26) + min(Low,26)) / 2
Senkou A   (Dan A)  = (Tenkan + Kijun) / 2,  dich toi truoc 26 phien
Senkou B   (Dan B)  = (max(High,52) + min(Low,52)) / 2,  dich toi truoc 26 phien
Chikou     (Tre)    = Close,  dich lui 26 phien
Kumo (may)          = vung giua Senkou A va Senkou B
```

Tham so 9-26-52 la bo goc tu thi truong Nhat thap nien 1960 (tuan lam viec 6
ngay). `ICHIMOKU_PRESETS` cung cap ca bo hieu chinh cho tuan 5 ngay
`(7, 22, 44)`, chon qua `config/settings.yaml: indicators.ichimoku_preset`.

Trang thai suy ra (`ichimoku_state`): `price_vs_kumo` (tren/trong/duoi may),
`tk_cross` (giao cat Tenkan/Kijun, do manh phu thuoc vi tri so voi may),
`kumo_twist` (may phia truoc co doi mau khong), `chikou_free` (gia hien tai
co cao hon gia 26 phien truoc), `kumo_thickness` (do day may chuan hoa theo ATR14).

## 4. Phan ky gia/chi bao — `indicators/divergence.py`

```
find_swings(series, order)      tim dinh/day cuc bo bang cua so truot
detect_divergence(frame, osc)   so sanh hai day (hoac hai dinh) gan nhat
```

Quy uoc: phan ky **duong** = gia tao day thap hon, chi bao tao day cao hon.
Phan ky **am** = gia tao dinh cao hon, chi bao tao dinh thap hon.

## 5. Cham diem hop luu — `analysis/scoring.py`

Ba he cham DOC LAP, moi he trong `[-100, 100]`, gop co trong so:

```
Diem tong = w_macd*S_macd + w_rsi*S_rsi + w_ichi*S_ichi
mac dinh:  w_macd = 0.30,  w_rsi = 0.25,  w_ichi = 0.45
```

Ichimoku nang nhat vi la he thong xu huong hoan chinh; MACD/RSI la chi bao
dong luc don le.

**Quy tac hop luu bat buoc (khong cong don mu quang):**

| Quy tac | Hieu ung |
|---|---|
| Gia duoi may Kumo | Ichimoku PHU QUYET - khong bao gio ra MUA, bat ke diem tong cao bao nhieu |
| Co phan ky am (gia/MACD) | Tru thang `scoring.divergence_penalty` (mac dinh 25) diem vao diem tong |
| Khoi luong phien < 50% TB20 | Ha do tin cay xuong mot bac (khong doi diem so) |

**Anh xa diem sang khuyen nghi** (`config/settings.yaml: scoring.thresholds`):

| Diem tong | Khuyen nghi |
|---|---|
| >= 60 | MUA |
| [20, 60) | TICH LUY |
| [-20, 20) | THEO DOI |
| [-60, -20) | GIAM TY TRONG |
| <= -60 | BAN |

**Vung gia kem theo mot khuyen nghi:**

```
Cat lo  : max(gia - 1.5*ATR14, Kijun-sen)     - lay muc GAN gia hien tai hon
Muc tieu: gia + 3*ATR14, va muc khang cu Ichimoku gan nhat (Senkou A/B phia tren)
Ty le loi/rui ro = (muc tieu - gia) / (gia - cat lo)
```

He so ATR (`signals.stop_loss_atr = 1.5`, `signals.take_profit_atr = 3.0`)
dung chung voi `risk/stops.py`.

## 6. Quan tri rui ro — `risk/`

```
So co phieu = (Von * risk_per_trade) / (gia - cat lo)      risk_per_trade = 1%
Chot 1 phan tai +2R, phan con lai dung Chandelier: max(High ke tu khi vao) - 3*ATR22
```

Chi phi mo phong (`backtest/engine.py`): phi hai chieu 0.25% + thue ban 0.1%.
Thanh toan T+2. Bien do gia: HOSE +-7%, HNX +-10%, UPCOM +-15%
(`risk/constraints.py`).

## 7. Sinh tin hieu cho backtest — `backtest/signals.py`

Backtest chay tren khuyen nghi cua `analysis/scoring.py`, khong phai mot he
tin hieu rieng: `generate_buy_signals()` quet lai `recommend()` tren tung
phien qua khu (chi dung du lieu toi thoi diem do, khong nhin truoc tuong
lai), lay cac phien co khuyen nghi MUA lam tin hieu vao lenh cho
`backtest/engine.py:run()`.

## 8. Ba bo loc dung san cua `/loc` — `analysis/screener.py`

`/loc` CHI DOC `data/market/snapshot.parquet` (xem `analysis/snapshot.py`,
tinh san sau gio dong cua) - khong tinh lai, khong goi mang. Ca ba bo loc
duoi day deu doi hoi tin hieu **MOI** (vua xay ra trong vai phien gan day),
khong chi dung "dang o trang thai do" - mot ma da giao cat MACD tu 20 phien
truoc (du van dang tren may, khoi luong cao) se **KHONG** lot vao "dot pha",
vi `macd_bars_since` (so phien ke tu lan giao cat gan nhat) cua no vuot
nguong `max_macd_bars_since`.

Goi bo loc bang nut bam trong `/loc`, hoac go dung ten nut: `/loc dotpha`,
`/loc tichluy`, `/loc canhbao` (co dau/khong dau deu duoc). Day la cac MAU
HINH ky thuat, KHAC voi khoa `kn=` cua loc tuy chinh: `kn=` la muc khuyen
nghi toi thieu cua lenh /kn (bang diem o muc tren), vd `kn=tichluy` = khuyen
nghi TICH LUY hoac MUA, khong lien quan bo loc "Tich luy" ben duoi.

### 8.1. "Dot pha" (`preset_breakout()`)

Tat ca dieu kien deu phai dung (AND):

```
price_vs_kumo == "tren_may"                                 (gia dang TREN may)
kumo_break_bars <= screener.breakout.max_kumo_break_bars     (vuot may TRONG toi da N phien, mac dinh 3)
macd_cross == "golden"                                       (giao cat MACD gan nhat la TANG)
macd_bars_since <= screener.breakout.max_macd_bars_since      (giao cat do TRONG toi da N phien, mac dinh 3)
vol_ratio20 >= screener.breakout.min_volume_ratio             (khoi luong >= 1.5x TB20, mac dinh)
```

Thieu du lieu (`kumo_break_bars`/`macd_bars_since` la NaN, vi du gia dang
NAM TRONG may nen khong co "lan vuot may gan nhat") -> loai ma do khoi ket
qua (khong the xac nhan la "moi").

### 8.2. "Tich luy" (`preset_accumulate()`)

```
price_vs_kumo == "trong_may"                                  (gia dang TRONG may - chua ro xu huong)
kumo_thickness <= screener.accumulate.max_kumo_thickness       (may MONG, chuan hoa theo ATR14, mac dinh 1.0)
rsi_zone == "trung_tinh"                                       (RSI o vung giua, khong qua mua/qua ban)
vol_ratio20 <= screener.accumulate.max_volume_ratio            (khoi luong CAN, <= 0.8x TB20 mac dinh - dau hieu tich luy am tham)
```

### 8.3. "Canh bao" (`preset_warning()`)

Khac hai bo tren: dung logic **HOAC** (OR), vi day la canh bao rui ro - chi
can MOT trong hai dieu kien la du dang chu y:

```
(price_vs_kumo == "duoi_may" VA kumo_break_bars <= screener.warning.max_kumo_break_bars)
HOAC
divergence_type == "bearish"
```

Ket qua sap xep TANG DAN theo `total_score` (te nhat/am nhieu nhat truoc).

### 8.4. Loc tuy chinh (`/loc <dieu_kien>`)

Cu phap `key=value`, cach nhau boi khoang trang, khong phan biet co dau hay
khong dau (vd `rsi=quá_bán` va `rsi=quaban` tuong duong). Vi du:
`/loc san=HOSE kn=MUA rsi=quaban`.

| Khoa | Y nghia | Gia tri hop le |
|---|---|---|
| `san` | San giao dich | `HOSE`, `HNX`, `UPCOM` (cach nhau boi dau phay) |
| `kn` | Hang khuyen nghi TOI THIEU | `mua`, `tichluy`, `theodoi`, `giamtytrong`, `ban` |
| `rsi` | Vung RSI | `quamua`, `trungtinh`, `quaban` |
| `may` | Vi tri gia so voi may Kumo | `tren`, `trong`, `duoi` |
| `macd` | Chieu giao cat MACD | `tang` (golden), `giam` (death) |
| `phanky` | Loai phan ky | `duong` (bullish), `am` (bearish) |
| `diem` | Diem tong TOI THIEU | so thuc, vd `diem=30` |
| `kl` | Ty le khoi luong/TB20 TOI THIEU | so thuc, vd `kl=1.5` |
| `pe` | P/E TOI DA | so thuc, vd `pe=15` |
| `roe` | ROE (%) TOI THIEU | so thuc, vd `roe=15` |

`pe`/`roe` can `data/market/fundamentals.parquet` da duoc gop vao snapshot
(chay `python scripts/backfill_fundamentals.py` truoc) - neu chua co, dieu
kien do duoc **BO QUA NHE NHANG** (khong loai het ket qua), kem ghi chu ro
trong phan hoi cua bot.

## 9. Tin hieu phien gan nhat — `/tinhieu` (`analysis/screener.py:today_signals()`)

Cung nguyen tac voi `/loc`: CHI DOC snapshot, khong tinh lai. Chia lam hai
nhom, moi nhom toi da `screener.max_results` ma (mac dinh 15):

```
MUA / TICH LUY:        action IN {MUA, TICH LUY},        sap xep GIAM DAN theo total_score
BAN / GIAM TY TRONG:    action IN {BAN, GIAM TY TRONG},    sap xep TANG DAN theo total_score (te nhat truoc)
```
