"""Rang buoc danh muc va vi cau truc thi truong Viet Nam.

Cac rang buoc rat that nhung hay bi bo qua trong do an:
  - chu ky thanh toan T+2: co phieu mua hom nay chua ban duoc ngay
  - bien do gia: +-7% HOSE, +-10% HNX, +-15% UPCOM
  - tran ti trong mot ma va mot nganh
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from ..config import get_settings


@dataclass
class PortfolioState:
    capital: float
    positions: dict[str, float] = field(default_factory=dict)      # symbol -> gia tri
    entry_dates: dict[str, date] = field(default_factory=dict)
    sectors: dict[str, str] = field(default_factory=dict)          # symbol -> nganh

    def weight(self, symbol: str) -> float:
        return self.positions.get(symbol, 0.0) / self.capital if self.capital else 0.0

    def sector_weight(self, sector: str) -> float:
        if not self.capital:
            return 0.0
        total = sum(
            value for sym, value in self.positions.items() if self.sectors.get(sym) == sector
        )
        return total / self.capital


def can_open(
    state: PortfolioState, symbol: str, value: float, sector: str = "Khac"
) -> tuple[bool, str]:
    settings = get_settings()
    max_symbol = settings.get("risk.max_weight_per_symbol", 0.15)
    max_sector = settings.get("risk.max_weight_per_sector", 0.35)

    new_weight = (state.positions.get(symbol, 0.0) + value) / state.capital
    if new_weight > max_symbol:
        return False, f"Vuot tran ti trong ma ({new_weight:.0%} > {max_symbol:.0%})"

    new_sector = state.sector_weight(sector) + value / state.capital
    if new_sector > max_sector:
        return False, f"Vuot tran ti trong nganh {sector} ({new_sector:.0%} > {max_sector:.0%})"

    return True, ""


def settlement_days() -> int:
    """So phien thanh toan (T+N) doc tu config: costs.settlement_days."""
    return int(get_settings().get("costs.settlement_days", 2))


def is_settled(entry_session: int, today_session: int) -> bool:
    """T+N tinh theo PHIEN GIAO DICH (chi so trong lich giao dich), khong theo
    ngay trong tuan: mua o phien `entry_session` thi ban duoc tu phien
    entry_session + N. Dem theo ngay trong tuan se sai quanh nghi le (Tet nghi
    ca tuan -> "T+2" theo ngay lam viec roi vao ky nghi, phien mo lai dau tien
    chi la T+1 theo phien). Dung trong backtest/engine.py.
    """
    return today_session - entry_session >= settlement_days()


def is_sellable(state: PortfolioState, symbol: str, today: date) -> tuple[bool, str]:
    """Kiem tra chu ky thanh toan T+2 (cho bot, dem theo ngay lam viec - khong
    co lich nghi le; backtest dung is_settled() voi lich phien that)."""
    entry = state.entry_dates.get(symbol)
    if entry is None:
        return True, ""
    days = settlement_days()
    available = _add_business_days(entry, days)
    if today < available:
        return False, f"Chua ve tai khoan, ban duoc tu {available:%d/%m/%Y}"
    return True, ""


def price_band(exchange: str) -> float:
    return get_settings().get(f"price_band.{exchange.upper()}", 0.07)


def hits_ceiling(close: float, reference: float, exchange: str, tolerance: float = 0.001) -> bool:
    """Gia cham tran. Breakout ngay phien tran thuong khong khop duoc khoi luong mong muon."""
    band = price_band(exchange)
    return close >= reference * (1 + band) * (1 - tolerance)


def tick_size(price: float, exchange: str) -> float:
    """Buoc gia: HOSE 10/50/100 dong theo vung gia (<10k, <50k, >=50k);
    HNX va UPCOM 100 dong."""
    if exchange.upper() != "HOSE":
        return 100.0
    if price < 10_000:
        return 10.0
    if price < 50_000:
        return 50.0
    return 100.0


def floor_locked(frame: pd.DataFrame, exchange: str) -> pd.Series:
    """Phien "trang ben mua o gia san": dong cua o gia san VA low == gia san.

    Gia tham chieu = close phien truoc; gia san = tham chieu * (1 - bien do),
    so giao dich lam tron LEN theo buoc gia, nen chap nhan close lech tren gia
    san ly thuyet toi mot buoc gia. Du lieu gia trong kho da dieu chinh co tuc
    (khong nam tren luoi buoc gia) nen khong so sanh bang tuyet doi duoc.
    low == close (sai so float32) nghia la ca phien khong co giao dich nao
    duoi gia dong cua - ben ban xep hang o san ma khong co nguoi mua.

    Tra ve Series bool cung chi so voi `frame` (phien dau tien luon False vi
    khong co gia tham chieu).
    """
    close = frame["close"].astype(float)
    low = frame["low"].astype(float)
    reference = close.shift(1)
    floor = reference * (1 - price_band(exchange))
    tick = reference.map(lambda p: tick_size(p, exchange) if pd.notna(p) else 0.0)
    at_floor = close <= floor + tick
    no_trade_below_close = low >= close * (1 - 1e-6)
    return (at_floor & no_trade_below_close & reference.notna()).astype(bool)


def _add_business_days(start: date, days: int) -> date:
    current, added = start, 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current
