# Ket qua backtest

Sinh bang `python scripts/run_backtest.py` ngay 2026-10-05 (khong sua tay).

- Du lieu: 1511 ma trong kho, kiem dinh tu 2023-11-14 den 2026-09-24; vu tru chon theo thoi diem (trung vi 288 ma/lat walk-forward).
- Phi hai chieu 0.25% + thue ban 0.1%; von ban dau 100,000,000 dong.
- Walk-forward: train 12 thang / test 3 thang, luoi 12 to hop; DSR dung n_trials = 12.

## Tong hop

| Chien luoc | Tu | Den | So phien | Loi nhuan tich luy | CAGR | Sharpe | Sortino | Sut giam toi da | Vong quay (lan/nam) | So lenh | Ti le thang | PSR | DSR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Walk-forward OOS (8 lat) | 2024-11-14 | 2026-09-24 | 461 | -33.4% | -19.9% | -1.39 | -1.66 | -44.3% | 30.13 | 1435 | 36% | 0.023 | 0.002 |
| VN-Index mua va giu (cung ky OOS) | 2024-11-14 | 2026-09-24 | 461 | +44.1% | +22.1% | 1.09 | 1.50 | -18.1% | - | - | - | 0.923 | - |
| Tham so mac dinh (MUA>=60, goc_nhat_6ngay, giu<=20), ca ky | 2023-11-14 | 2026-09-24 | 711 | -42.6% | -17.8% | -1.21 | -1.45 | -47.7% | 25.62 | 2121 | 36% | 0.016 | 0.001 |
| Tot nhat in-sample (MUA>=60, hieu_chinh_5ngay, giu<=20), ca ky | 2023-11-14 | 2026-09-24 | 711 | -31.0% | -12.3% | -0.78 | -0.94 | -38.9% | 27.66 | 2348 | 36% | 0.088 | 0.013 |
| VN-Index mua va giu (ca ky) | 2023-11-14 | 2026-09-24 | 711 | +60.0% | +18.1% | 1.01 | 1.37 | -18.1% | - | - | - | 0.949 | - |

## Do nhay chi phi

| Phi hai chieu | Chien luoc | CAGR | Sharpe | Sut giam toi da | Vong quay (lan/nam) | So lenh |
|---|---|---|---|---|---|---|
| 0.15% | Tham so mac dinh, ca ky | -14.9% | -0.98 | -42.7% | 25.75 | 2149 |
| 0.25% | Tham so mac dinh, ca ky | -17.8% | -1.21 | -47.7% | 25.62 | 2121 |
| 0.35% | Tham so mac dinh, ca ky | -19.4% | -1.34 | -49.7% | 25.42 | 2100 |
| 0.15% | Walk-forward OOS | -18.2% | -1.25 | -42.9% | 30.56 | 1443 |
| 0.25% | Walk-forward OOS | -19.9% | -1.39 | -44.3% | 30.13 | 1435 |
| 0.35% | Walk-forward OOS | -18.0% | -1.24 | -40.4% | 28.53 | 1299 |

## Walk-forward tung lat

| test_start | test_end | So ma vu tru | buy_threshold | ichimoku_preset | max_hold_days | Sharpe train | Loi nhuan | Sharpe test | So lenh |
|---|---|---|---|---|---|---|---|---|---|
| 2024-11-14 | 2025-02-14 | 256 | 50 | goc_nhat_6ngay | 20 | -0.33 | +3.2% | 1.06 | 272 |
| 2025-02-14 | 2025-05-14 | 289 | 60 | hieu_chinh_5ngay | 20 | -1.25 | -8.5% | -1.97 | 204 |
| 2025-05-14 | 2025-08-14 | 288 | 70 | goc_nhat_6ngay | 20 | -1.38 | +15.4% | 4.01 | 189 |
| 2025-08-14 | 2025-11-14 | 347 | 70 | goc_nhat_6ngay | 20 | 0.58 | -22.3% | -5.76 | 157 |
| 2025-11-14 | 2026-02-14 | 288 | 50 | hieu_chinh_5ngay | 20 | -0.09 | -10.0% | -2.94 | 223 |
| 2026-02-14 | 2026-05-14 | 294 | 50 | hieu_chinh_5ngay | 20 | -1.16 | -15.4% | -4.78 | 203 |
| 2026-05-14 | 2026-08-14 | 260 | 60 | hieu_chinh_5ngay | 20 | -1.19 | -2.9% | -0.89 | 137 |
| 2026-08-14 | 2026-09-25 | 240 | 60 | hieu_chinh_5ngay | 20 | -2.68 | +6.2% | 5.66 | 50 |
