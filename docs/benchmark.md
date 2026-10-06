# Benchmark: sinh tin hieu MUA lich su

Bang so lieu sinh bang `python scripts/bench_signals.py` (khong sua tay); muc
"Ghi chu" cuoi file viet tay.

- Ngay chay: 2026-10-06
- May: Intel64 Family 6 Model 186 Stepping 3, GenuineIntel, Windows 11
- Python 3.12.4, pandas 2.3.2, numpy 2.2.6; chay don luong
- Du lieu: kho gia that `data/market/ohlcv.parquet`; 100 ma co gia tri giao dich trung binh lon nhat

| Phep do | Ma | Phien/ma | Ban cu O(n^2) | Ban vectorized | Tang toc | Tin hieu | Khop |
|---|---|---:|---:|---:|---:|---:|---|
| 1 ma | FPT | 752 | 9.0 s | 0.06 s | 149x | 18 | 100% |
| 100 ma | thanh khoan nhat | 752 | 1,734.6 s | 13.82 s | 126x | 1629 | 100/100 ma khop 100% |

**Ban cu** (`generate_buy_signals_reference`): goi `recommend()` tren `frame.iloc[:i+1]` o moi phien i -> moi phien tinh lai moi chi bao tren toan bo lich su, O(n^2).

**Ban vectorized** (`generate_buy_signals` -> `analysis/score_history.py`): tinh chi bao mot lan cho ca chuoi, suy ra trang thai tung phien, O(n) (phan ky: O(n log n) - vai phep tim nhi phan moi phien).

**Khop**: cung danh sach phien co tin hieu; stop_loss/target lech tuong doi <= 1e-12 (do doc tinh bang cong thuc dong thay vi `np.polyfit`, sai so ~1e-13 diem).

## Ghi chu (viet tay)

- Thoi gian tuyet doi dao dong theo trang thai may (laptop, dieu chinh xung
  nhip/nhiet do): trong cung lan chay nay, ban cu mat tu 7,6 s den 41,4 s cho
  mot ma 752 phien, ban moi dao dong cung ti le. **Ti so** moi on dinh: lan
  chay truoc do (may dang ban chay kiem thu song song) ra 138x (1 ma) va 139x
  (100 ma), lan nay 149x va 126x. Nen trich dan "~125-150 lan" thay vi mot con
  so tuyet doi.
- Do do phuc tap: ban cu tang theo n^2 voi so phien, nen voi lich su dai hon
  (vd 10 nam, ~2.500 phien) khoang cach se lon hon nhieu.
