"""Xac dinh khoi luong theo rui ro co dinh.

    So co phieu = (Von * r) / (k_sl * ATR14)

r = ti le von chap nhan mat cho moi lenh (mac dinh 1%).
Cach nay bao dam moi lenh deu rui ro nhu nhau ve gia tri tuyet doi, bat ke ma do
bien dong manh hay yeu - dieu ma cach chia deu von khong lam duoc.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import get_settings

LOT_SIZE = 100  # HOSE giao dich lo chan 100 co phieu


@dataclass
class PositionSize:
    shares: int
    value: float
    risk_amount: float
    weight: float
    note: str = ""


def position_size(
    capital: float,
    entry: float,
    stop_loss: float,
    risk_per_trade: float | None = None,
    regime_multiplier: float = 1.0,
    max_weight: float | None = None,
    lot_size: int = LOT_SIZE,
) -> PositionSize:
    if not risk_per_trade or not max_weight:  # chi doc config (parse YAML, cham) khi can
        settings = get_settings()
        risk_per_trade = risk_per_trade or settings.get("risk.risk_per_trade", 0.01)
        max_weight = max_weight or settings.get("risk.max_weight_per_symbol", 0.15)

    if entry <= 0 or stop_loss <= 0 or entry <= stop_loss:
        return PositionSize(0, 0.0, 0.0, 0.0, "Diem dung lo khong hop le")

    risk_budget = capital * risk_per_trade * regime_multiplier
    if risk_budget <= 0:
        return PositionSize(0, 0.0, 0.0, 0.0, "Che do thi truong khong cho phep mo vi the")

    risk_per_share = entry - stop_loss
    raw_shares = risk_budget / risk_per_share

    cap_by_weight = (capital * max_weight) / entry
    shares = int(min(raw_shares, cap_by_weight) // lot_size * lot_size)

    if shares <= 0:
        return PositionSize(0, 0.0, 0.0, 0.0, "Von khong du de mua toi thieu 1 lo")

    value = shares * entry
    note = "Bi chan boi tran ti trong" if raw_shares > cap_by_weight else ""
    return PositionSize(shares, value, shares * risk_per_share, value / capital, note)


def r_multiple(entry: float, exit_price: float, stop_loss: float) -> float | None:
    """Ket qua lenh tinh bang boi so rui ro ban dau."""
    risk = entry - stop_loss
    return None if risk <= 0 else (exit_price - entry) / risk
