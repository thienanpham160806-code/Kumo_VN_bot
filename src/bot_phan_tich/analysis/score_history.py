"""Diem hop luu cho TUNG PHIEN cua ca chuoi gia - ban vectorized cua
analysis/scoring.recommend() dung cho backtest va phan tich IC.

Van de: backtest can biet "neu chay recommend() vao cuoi phien t thi ra gi"
cho moi t. Cach ngay tho goi recommend(frame.iloc[:t+1]) o tung phien - moi
lan tinh lai MOI chi bao tren toan bo lich su -> O(n^2) (~11 giay cho 1 ma x 3
nam).

Cach o day: tinh chi bao MOT LAN cho ca chuoi, roi suy ra trang thai tai
tung phien. Dung duoc vi moi chi bao deu NHAN QUA (causal): EMA adjust=False,
lam muot Wilder, rolling max/min/mean/quantile - gia tri tai t chi phu thuoc
du lieu <= t, va pandas tinh chung theo cung mot trinh tu nen ket qua tai t
GIONG HET khi tinh tren frame.iloc[:t+1]. Phan con lai cua recommend() la cac
phep "lay gia tri hop le cuoi cung" (-> ffill), "so phien tu lan giao cat
cuoi" (-> chi so lan doi dau gan nhat), "do doc k diem hop le cuoi" (-> cua
so truot tren chuoi da bo NaN) va phan ky (dinh/day cuc bo trong cua so 60
phien cuoi - xem _divergence_history).

Cham diem dung LAI score_macd/score_rsi/score_ichimoku cua scoring.py (khong
viet lai cong thuc) - mot nguon su that duy nhat cho logic MUA/BAN.
tests/test_score_history.py kiem chung khop 100% voi recommend() phien-theo-phien.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from ..config import get_settings
from ..indicators.common import atr
from ..indicators.ichimoku import ICHIMOKU_PRESETS, ichimoku
from ..indicators.macd import macd
from ..indicators.rsi import LOWER_BOUNDS, UPPER_BOUNDS, adaptive_bands, rsi
from .scoring import score_ichimoku, score_macd, score_rsi

SCORE_COLUMNS = [
    "time", "close", "macd", "rsi", "ichimoku", "total", "vetoed", "bearish_divergence",
    "stop_loss", "target",
]

_KUMO_SHIFT = 26
_DIVERGENCE_LOOKBACK = 60
_SWING_ORDER = 5


def score_history(
    frame: pd.DataFrame,
    ichimoku_preset: str | None = None,
    weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Diem tung he chi bao + diem tong + stop/target cho MOI phien cua `frame`.

    Dong t cua ket qua == nhung gi recommend(frame.iloc[:t+1]) tra ve (diem
    thanh phan, total_score, vetoed_by_kumo, stop_loss, target). Chi dung du
    lieu <= t (khong nhin truoc).

    `ichimoku_preset`: ten trong ICHIMOKU_PRESETS, None = theo config.
    """
    settings = get_settings()
    weights = weights or {
        "macd": settings.get("scoring.weights.macd", 0.30),
        "rsi": settings.get("scoring.weights.rsi", 0.25),
        "ichimoku": settings.get("scoring.weights.ichimoku", 0.45),
    }
    preset = ichimoku_preset or settings.get("indicators.ichimoku_preset", "goc_nhat_6ngay")
    tenkan, kijun, senkou_b = ICHIMOKU_PRESETS.get(preset, ICHIMOKU_PRESETS["goc_nhat_6ngay"])
    penalty = settings.get("scoring.divergence_penalty", 25.0)
    k_sl = settings.get("signals.stop_loss_atr", 1.5)
    k_tp = settings.get("signals.take_profit_atr", 3.0)

    frame = frame.reset_index(drop=True)
    n = len(frame)
    close = frame["close"]
    close_np = close.to_numpy(dtype=float)

    # ---- MACD (macd_state) ----
    lines = macd(frame)
    macd_dir, macd_bars = _cross_history(lines["macd"], lines["signal"])
    macd_slope = _slope_history(lines["hist"], 3)
    macd_last = lines["macd"].ffill().to_numpy(dtype=float)

    # ---- RSI (rsi_state) ----
    rsi_values = rsi(close)
    bands = adaptive_bands(rsi_values)
    rsi_last = rsi_values.ffill().to_numpy(dtype=float)
    upper_last = bands["upper"].ffill().fillna(UPPER_BOUNDS[1]).to_numpy(dtype=float)
    lower_last = bands["lower"].ffill().fillna(LOWER_BOUNDS[0]).to_numpy(dtype=float)
    rsi_slope = _slope_history(rsi_values, 5)

    # ---- Ichimoku (ichimoku_state) ----
    ichi = ichimoku(frame, tenkan=tenkan, kijun=kijun, senkou_b=senkou_b, shift=_KUMO_SHIFT)
    span_a = ichi["senkou_a"].ffill().to_numpy(dtype=float)
    span_b = ichi["senkou_b"].ffill().to_numpy(dtype=float)
    tk_dir, tk_bars = _cross_history(ichi["tenkan"], ichi["kijun"])
    twist = _twist_history(ichi["senkou_a_base"], ichi["senkou_b_base"], _KUMO_SHIFT)
    atr_last = atr(frame).ffill().to_numpy(dtype=float)
    kijun_last = ichi["kijun"].ffill().to_numpy(dtype=float)

    bearish = _divergence_history(close, lines["hist"]) == "bearish"

    macd_scores = np.zeros(n)
    rsi_scores = np.zeros(n)
    ichi_scores = np.zeros(n)
    vetoed = np.zeros(n, dtype=bool)
    for t in range(n):
        macd_scores[t] = score_macd(
            {
                "cross": macd_dir[t],
                "bars_since_cross": _int_or_none(macd_bars[t]),
                "hist_slope": _float_or_none(macd_slope[t]),
                "above_zero": None if np.isnan(macd_last[t]) else bool(macd_last[t] > 0),
            }
        )
        rsi_scores[t] = score_rsi(_rsi_state(rsi_last[t], upper_last[t], lower_last[t],
                                             rsi_slope[t]))
        position = _price_vs_kumo(close_np[t], span_a[t], span_b[t])
        vetoed[t] = position == "duoi_may"
        ichi_scores[t] = score_ichimoku(
            _ichimoku_state(t, position, tk_dir, tk_bars, twist, close_np, span_a, span_b,
                            atr_last)
        )

    total = (
        weights["macd"] * macd_scores
        + weights["rsi"] * rsi_scores
        + weights["ichimoku"] * ichi_scores
    )
    total = np.clip(np.where(bearish, total - penalty, total), -100.0, 100.0)

    atr_or_zero = np.nan_to_num(atr_last, nan=0.0)
    atr_stop = close_np - k_sl * atr_or_zero
    stop_loss = np.where(np.isnan(kijun_last), atr_stop, np.fmax(atr_stop, kijun_last))
    stop_loss = np.minimum(stop_loss, close_np * 0.999)
    target = close_np + k_tp * atr_or_zero

    return pd.DataFrame(
        {
            "time": frame["time"].to_numpy(),
            "close": close_np,
            "macd": macd_scores,
            "rsi": rsi_scores,
            "ichimoku": ichi_scores,
            "total": total,
            "vetoed": vetoed,
            "bearish_divergence": bearish,
            "stop_loss": stop_loss,
            "target": target,
        },
        columns=SCORE_COLUMNS,
    )


# ------------------------------------------------------------ trang thai tung phien
def _int_or_none(value: float) -> int | None:
    return None if np.isnan(value) else int(value)


def _float_or_none(value: float) -> float | None:
    return None if np.isnan(value) else float(value)


def _rsi_state(value: float, upper: float, lower: float, slope: float) -> dict:
    if np.isnan(value):
        return {"value": None, "zone": None, "upper": None, "lower": None, "slope": None}
    if value > upper:
        zone = "qua_mua"
    elif value < lower:
        zone = "qua_ban"
    else:
        zone = "trung_tinh"
    return {"value": float(value), "zone": zone, "upper": upper, "lower": lower,
            "slope": _float_or_none(slope)}


def _price_vs_kumo(close: float, span_a: float, span_b: float) -> str | None:
    if np.isnan(span_a) or np.isnan(span_b):
        return None
    if close > max(span_a, span_b):
        return "tren_may"
    if close < min(span_a, span_b):
        return "duoi_may"
    return "trong_may"


_TK_STRENGTH = {"tren_may": "manh", "trong_may": "trung_tinh", "duoi_may": "yeu"}


def _ichimoku_state(t, position, tk_dir, tk_bars, twist, close, span_a, span_b, atr_last):
    if position is None:
        return {"price_vs_kumo": None, "tk_cross": (None, None, None)}
    cross = tk_dir[t]
    chikou_free = bool(close[t] > close[t - _KUMO_SHIFT]) if t >= _KUMO_SHIFT else None
    thickness = None
    if not np.isnan(atr_last[t]) and atr_last[t]:
        thickness = abs(span_a[t] - span_b[t]) / atr_last[t]
    return {
        "price_vs_kumo": position,
        "tk_cross": (cross, _int_or_none(tk_bars[t]),
                     _TK_STRENGTH[position] if cross is not None else None),
        "kumo_twist": bool(twist[t]),
        "chikou_free": chikou_free,
        "kumo_thickness": thickness,
    }


# ------------------------------------------------------- cac phep "theo tung phien"
def _compress(series: pd.Series) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(gia tri hop le, vi tri goc cua chung, so gia tri hop le tinh den moi phien)."""
    values = series.to_numpy(dtype=float)
    valid = ~np.isnan(values)
    return values[valid], np.flatnonzero(valid), np.cumsum(valid)


def _cross_history(fast: pd.Series, slow: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """detect_cross(fast[:t+1], slow[:t+1]) cho moi t.

    Tra ve (huong: mang object "golden"/"death"/None, so phien tu lan cat: float, NaN = None).
    detect_cross() tim lan doi dau CUOI CUNG cua chuoi hieu (da bo NaN); tai t
    do chinh la lan doi dau gan nhat co chi so (trong chuoi da bo NaN) <= so
    gia tri hop le tinh den t tru 1.
    """
    values, _, count = _compress(fast - slow)
    n = len(count)
    direction = np.full(n, None, dtype=object)
    bars = np.full(n, np.nan)
    sign = np.sign(values)
    changes = np.flatnonzero(sign[1:] != sign[:-1]) + 1  # chi so (da nen) ngay SAU khi doi dau
    if len(changes) == 0:
        return direction, bars
    last_idx = count - 1
    which = np.searchsorted(changes, last_idx, side="right") - 1
    has = which >= 0
    k = changes[np.clip(which, 0, None)]
    direction[has] = np.where(sign[k[has]] > 0, "golden", "death")
    bars[has] = (last_idx - k)[has]
    return direction, bars


def _slope_history(series: pd.Series, bars: int) -> np.ndarray:
    """slope(series[:t+1], bars) - do doc hoi quy bac 1 cua `bars` gia tri hop le
    cuoi cung - cho moi t. NaN = khong du du lieu (slope() tra None)."""
    values, _, count = _compress(series)
    out = np.full(len(count), np.nan)
    if len(values) < bars:
        return out
    x = np.arange(bars, dtype=float) - (bars - 1) / 2.0
    compressed = np.full(len(values), np.nan)
    compressed[bars - 1:] = sliding_window_view(values, bars) @ x / float(x @ x)
    has = count >= bars
    out[has] = compressed[count[has] - 1]
    return out


def _twist_history(span_a_base: pd.Series, span_b_base: pd.Series, shift: int) -> np.ndarray:
    """kumo_twist cua ichimoku_state(frame[:t+1]) cho moi t: Senkou A/B (truoc
    khi dich) co doi dau trong `shift` phien cuoi khong.

    Mot lan doi dau giua hai gia tri hop le lien tiep (vi tri goc p_truoc <
    p_sau) nam tron trong cua so [t-shift+1, t] khi p_sau <= t va p_truoc >=
    t-shift+1. Lan doi dau gan nhat co p_truoc lon nhat nen chi can xet no.
    """
    values, positions, count = _compress(span_a_base - span_b_base)
    n = len(count)
    sign = np.sign(values)
    changes = np.flatnonzero(sign[1:] != sign[:-1]) + 1
    if len(changes) == 0:
        return np.zeros(n, dtype=bool)
    after = positions[changes]
    before = positions[changes - 1]
    t = np.arange(n)
    which = np.searchsorted(after, t, side="right") - 1
    has = which >= 0
    return has & (before[np.clip(which, 0, None)] >= t - shift + 1)


def _swing_flags(values: np.ndarray, order: int) -> tuple[np.ndarray, np.ndarray]:
    """find_swings() tren toan chuoi: dinh/day cuc bo tai vi tri p chi phu thuoc
    values[p-order : p+order+1], khong phu thuoc cua so chua no."""
    n = len(values)
    highs = np.zeros(n, dtype=bool)
    lows = np.zeros(n, dtype=bool)
    width = 2 * order + 1
    if n < width:
        return highs, lows
    windows = sliding_window_view(values, width)
    clean = ~np.isnan(windows).any(axis=1)
    safe = np.where(np.isnan(windows), 0.0, windows)
    center = windows[:, order]
    is_high = clean & (center == safe.max(axis=1)) & (safe.argmax(axis=1) == order)
    is_low = clean & ~is_high & (center == safe.min(axis=1)) & (safe.argmin(axis=1) == order)
    highs[order:n - order] = is_high
    lows[order:n - order] = is_low
    return highs, lows


def _divergence_history(
    close: pd.Series,
    oscillator: pd.Series,
    lookback: int = _DIVERGENCE_LOOKBACK,
    order: int = _SWING_ORDER,
) -> np.ndarray:
    """detect_divergence(frame[:t+1], oscillator[:t+1])["type"] cho moi t.

    Trong cua so [s, t] (s = t-lookback+1), find_swings chi xet vi tri
    [s+order, t-order]; dinh/day o day trung voi co dinh/day toan chuoi (xem
    _swing_flags). Moi phien chi con vai phep searchsorted tren mang da tinh san.
    """
    price = close.to_numpy(dtype=float)
    osc = oscillator.to_numpy(dtype=float)
    price_high, price_low = _swing_flags(price, order)
    osc_high, osc_low = _swing_flags(osc, order)
    swings = {
        "price_low": np.flatnonzero(price_low),
        "price_high": np.flatnonzero(price_high),
        "osc_low": np.flatnonzero(osc_low),
        "osc_high": np.flatnonzero(osc_high),
    }
    tolerance = order * 2
    n = len(price)
    result = np.full(n, None, dtype=object)

    def nearest(candidates: np.ndarray, position: int, lo: int, hi: int) -> int | None:
        left = np.searchsorted(candidates, max(lo, position - tolerance), side="left")
        right = np.searchsorted(candidates, min(hi, position + tolerance), side="right")
        if right <= left:
            return None
        window = candidates[left:right]
        return int(window[np.argmin(np.abs(window - position))])  # hoa -> vi tri som hon

    def check(price_pos, osc_pos, t_lo, t_hi, bullish: bool) -> bool:
        a = np.searchsorted(price_pos, t_lo, side="left")
        b = np.searchsorted(price_pos, t_hi, side="right")
        if b - a < 2:
            return False
        p1, p2 = int(price_pos[b - 2]), int(price_pos[b - 1])
        o1 = nearest(osc_pos, p1, t_lo, t_hi)
        o2 = nearest(osc_pos, p2, t_lo, t_hi)
        if o1 is None or o2 is None:
            return False
        if bullish:
            return price[p2] < price[p1] and osc[o2] > osc[o1]
        return price[p2] > price[p1] and osc[o2] < osc[o1]

    for t in range(n):
        start = max(0, t - lookback + 1)
        lo, hi = start + order, t - order
        if hi < lo:
            continue
        if check(swings["price_low"], swings["osc_low"], lo, hi, bullish=True):
            result[t] = "bullish"
        elif check(swings["price_high"], swings["osc_high"], lo, hi, bullish=False):
            result[t] = "bearish"
    return result
