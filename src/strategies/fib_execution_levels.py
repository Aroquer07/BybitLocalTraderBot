"""Níveis de scalp por Fibonacci — SL na base/topo, TPs no grid 38.2/50/61.8% (lado lucrativo)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from src.strategies.indicators import ohlcv_to_dataframe

Side = Literal["LONG", "SHORT"]

# Níveis padrão do gráfico (0→1); extensões quando entrada está no extremo do range
FIB_TP_PRIMARY = (0.382, 0.5, 0.618)
FIB_GRID_RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786, 1.0)
FIB_EXTENSION_RATIOS = (1.272, 1.618, 2.0)


@dataclass(frozen=True)
class FibScalpLevels:
    """Níveis calibrados no impulso recente (base 0 → topo 1)."""

    side: Side
    entry: float
    stop_loss: float
    take_profits: tuple[float, float, float]
    swing_low: float
    swing_high: float
    range_size: float
    impulse: str
    tp1_rr: float
    weighted_rr: float
    sl_reason: str = "fibo_base"


def _weighted_rr(
    entry: float,
    sl: float,
    tps: tuple[float, float, float],
    tp_close_pcts: tuple[float, float, float],
) -> tuple[float, float]:
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0, 0.0
    weights = tuple(p / 100.0 for p in tp_close_pcts)
    rrs = [abs(tp - entry) / risk for tp in tps]
    tp1_rr = rrs[0]
    weighted = sum(w * r for w, r in zip(weights, rrs))
    return tp1_rr, weighted


def _swing_points(
    df: pd.DataFrame,
    *,
    left: int = 2,
    right: int = 2,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    for i in range(left, len(df) - right):
        h = float(df["high"].iloc[i])
        l = float(df["low"].iloc[i])
        window_h = df["high"].iloc[i - left : i + right + 1]
        window_l = df["low"].iloc[i - left : i + right + 1]
        if h >= float(window_h.max()):
            highs.append((i, h))
        if l <= float(window_l.min()):
            lows.append((i, l))
    return highs, lows


def _find_bullish_leg(window) -> tuple[float, float, float] | None:
    if window.empty:
        return None
    low_idx = window["low"].idxmin()
    swing_low = float(window.loc[low_idx, "low"])
    after = window.loc[low_idx:]
    if after.empty:
        return None
    swing_high = float(after["high"].max())
    if swing_high <= swing_low:
        return None
    return swing_low, swing_high, swing_high - swing_low


def _find_bearish_leg(window) -> tuple[float, float, float] | None:
    if window.empty:
        return None
    high_idx = window["high"].idxmax()
    swing_high = float(window.loc[high_idx, "high"])
    after = window.loc[high_idx:]
    if after.empty:
        return None
    swing_low = float(after["low"].min())
    if swing_high <= swing_low:
        return None
    return swing_low, swing_high, swing_high - swing_low


def _find_bullish_impulse(window) -> tuple[float, float, float] | None:
    if window.empty:
        return None
    high_idx = window["high"].idxmax()
    pos = window.index.get_loc(high_idx)
    if isinstance(pos, slice):
        pos = pos.stop - 1 if pos.stop else 0
    segment = window.iloc[: pos + 1]
    if segment.empty:
        return None
    low_idx = segment["low"].idxmin()
    swing_low = float(segment.loc[low_idx, "low"])
    swing_high = float(window.loc[high_idx, "high"])
    if swing_high <= swing_low:
        return None
    return swing_low, swing_high, swing_high - swing_low


def _find_bearish_impulse(window) -> tuple[float, float, float] | None:
    if window.empty:
        return None
    low_idx = window["low"].idxmin()
    pos = window.index.get_loc(low_idx)
    if isinstance(pos, slice):
        pos = pos.stop - 1 if pos.stop else 0
    segment = window.iloc[: pos + 1]
    if segment.empty:
        return None
    high_idx = segment["high"].idxmax()
    swing_high = float(segment.loc[high_idx, "high"])
    swing_low = float(window.loc[low_idx, "low"])
    if swing_high <= swing_low:
        return None
    return swing_low, swing_high, swing_high - swing_low


def _fractal_legs(window, side: Side) -> list[tuple[float, float, float, str]]:
    """Pernas fractal low→high (LONG) ou high→low (SHORT), como fib manual no gráfico."""
    if window.empty:
        return []
    df = window.reset_index(drop=True)
    highs, lows = _swing_points(df)
    legs: list[tuple[float, float, float, str]] = []
    seen: set[tuple[float, float]] = set()

    if side == "LONG":
        for low_i, low_p in lows:
            highs_after = [h for i, h in highs if i > low_i]
            if not highs_after:
                continue
            high_p = max(highs_after)
            key = (round(low_p, 8), round(high_p, 8))
            if key in seen or high_p <= low_p:
                continue
            seen.add(key)
            legs.append((low_p, high_p, high_p - low_p, "fractal"))
    else:
        for high_i, high_p in highs:
            lows_after = [l for i, l in lows if i > high_i]
            if not lows_after:
                continue
            low_p = min(lows_after)
            key = (round(low_p, 8), round(high_p, 8))
            if key in seen or high_p <= low_p:
                continue
            seen.add(key)
            legs.append((low_p, high_p, high_p - low_p, "fractal"))

    return legs


def _enumerate_candidate_legs(window, side: Side) -> list[tuple[float, float, float, str]]:
    """Combina fractais + impulso global — prioriza perna com TPs realistas."""
    candidates: list[tuple[float, float, float, str]] = []
    seen: set[tuple[float, float]] = set()

    def _add(leg: tuple[float, float, float] | None, name: str) -> None:
        if leg is None:
            return
        sl, sh, rs = leg
        key = (round(sl, 8), round(sh, 8))
        if key in seen or rs <= 0:
            return
        seen.add(key)
        candidates.append((sl, sh, rs, name))

    for leg in _fractal_legs(window, side):
        key = (round(leg[0], 8), round(leg[1], 8))
        if key not in seen:
            seen.add(key)
            candidates.append(leg)

    if side == "LONG":
        _add(_find_bearish_leg(window), "bear_leg")
        _add(_find_bullish_impulse(window), "impulse")
        _add(_find_bullish_leg(window), "leg")
    else:
        _add(_find_bullish_leg(window), "bull_leg")
        _add(_find_bearish_impulse(window), "impulse")
        _add(_find_bearish_leg(window), "leg")

    return candidates


def _grid_levels(
    side: Side,
    swing_low: float,
    swing_high: float,
    range_size: float,
) -> list[float]:
    if side == "LONG":
        levels = [swing_low + r * range_size for r in FIB_GRID_RATIOS]
        levels.extend(swing_low + r * range_size for r in FIB_EXTENSION_RATIOS)
        return levels
    levels = [swing_high - r * range_size for r in FIB_GRID_RATIOS]
    levels.extend(swing_high - r * range_size for r in FIB_EXTENSION_RATIOS)
    return levels


def _build_take_profits(
    side: Side,
    swing_low: float,
    swing_high: float,
    range_size: float,
    entry_price: float,
) -> tuple[float, float, float] | None:
    """
    Seleciona 3 TPs no lado lucrativo do grid fib (como desenho manual).
    LONG: níveis acima da entrada; SHORT: níveis abaixo da entrada.
  Preferência: 0.382 → 0.5 → 0.618 quando disponíveis; senão 0.786/1.0/extensões.
    """
    grid = _grid_levels(side, swing_low, swing_high, range_size)
    primary = _levels_for_ratios(side, swing_low, swing_high, range_size, FIB_TP_PRIMARY)

    if side == "LONG":
        profit = sorted(p for p in grid if p > entry_price)
        primary_valid = [p for p in primary if p > entry_price]
    else:
        profit = sorted((p for p in grid if p < entry_price), reverse=True)
        primary_valid = [p for p in primary if p < entry_price]

    if len(primary_valid) >= 3:
        return tuple(primary_valid[:3])

    picked: list[float] = []
    for p in primary_valid:
        if p not in picked:
            picked.append(p)
    for p in profit:
        if p not in picked:
            picked.append(p)
        if len(picked) >= 3:
            break

    if len(picked) < 3:
        return None

    if side == "LONG":
        return tuple(sorted(picked[:3]))
    return tuple(sorted(picked[:3], reverse=True))


def _levels_for_ratios(
    side: Side,
    swing_low: float,
    swing_high: float,
    range_size: float,
    ratios: tuple[float, ...],
) -> tuple[float, ...]:
    if side == "LONG":
        return tuple(swing_low + r * range_size for r in ratios)
    return tuple(swing_high - r * range_size for r in ratios)


def _atr(window) -> float:
    if len(window) < 3:
        return max(float(window["high"].max() - window["low"].min()) * 0.02, 1e-8)
    high, low, close = window["high"], window["low"], window["close"]
    tr = (high - low).combine((high - close.shift()).abs(), max).combine(
        (low - close.shift()).abs(), max
    )
    val = float(tr.tail(14).mean())
    return max(val, 1e-8)


def _anchor_swing_high_short(
    highs: list[tuple[int, float]],
    entry_price: float,
    df: pd.DataFrame,
) -> tuple[int, float]:
    """SHORT: último topo fractal acima da entrada (invalidação do pullback)."""
    above = [(i, h) for i, h in highs if h > entry_price * 1.00001]
    if above:
        return max(above, key=lambda x: x[0])
    window_high = float(df["high"].max())
    if window_high > entry_price:
        idx = int(df["high"].idxmax())
        if isinstance(idx, slice):
            idx = idx.stop - 1 if idx.stop else len(df) - 1
        return idx, window_high
    if highs:
        return max(highs, key=lambda x: x[1])
    return len(df) - 1, window_high


def _anchor_swing_low_short(
    lows: list[tuple[int, float]],
    high_idx: int,
    entry_price: float,
    df: pd.DataFrame,
) -> float:
    """SHORT: último fundo / suporte abaixo da entrada (alvo de TP)."""
    below = [(i, l) for i, l in lows if l < entry_price]
    if below:
        return min(l for _, l in below)
    segment = df.iloc[high_idx:]
    if not segment.empty:
        seg_low = float(segment["low"].min())
        if seg_low < entry_price:
            return seg_low
    window_low = float(df["low"].min())
    return window_low


def _anchor_swing_low_long(
    lows: list[tuple[int, float]],
    entry_price: float,
    df: pd.DataFrame,
) -> tuple[int, float]:
    """LONG: último fundo fractal abaixo da entrada (invalidação do pullback)."""
    below = [(i, l) for i, l in lows if l < entry_price * 0.99999]
    if below:
        return max(below, key=lambda x: x[0])
    window_low = float(df["low"].min())
    if window_low < entry_price:
        idx = int(df["low"].idxmin())
        if isinstance(idx, slice):
            idx = idx.stop - 1 if idx.stop else 0
        return idx, window_low
    if lows:
        return min(lows, key=lambda x: x[1])
    return 0, window_low


def _anchor_swing_high_long(
    highs: list[tuple[int, float]],
    low_idx: int,
    entry_price: float,
    df: pd.DataFrame,
) -> float:
    """LONG: último topo / resistência acima da entrada (alvo de TP)."""
    above = [(i, h) for i, h in highs if h > entry_price]
    if above:
        return max(h for _, h in above)
    segment = df.iloc[low_idx:]
    if not segment.empty:
        seg_high = float(segment["high"].max())
        if seg_high > entry_price:
            return seg_high
    window_high = float(df["high"].max())
    return window_high


def _expand_leg_if_micro(
    window,
    side: Side,
    swing_low: float,
    swing_high: float,
) -> tuple[float, float, str]:
    """Se a perna fractal for micro (consolidação), usa impulso maior do lookback."""
    range_size = swing_high - swing_low
    atr_val = _atr(window)
    if range_size >= atr_val * 0.8:
        return swing_low, swing_high, "structure"

    if side == "SHORT":
        leg = _find_bearish_leg(window) or _find_bearish_impulse(window)
    else:
        leg = _find_bullish_leg(window) or _find_bullish_impulse(window)
    if leg is None:
        return swing_low, swing_high, "structure"
    return leg[0], leg[1], "impulse"


def _tp_leg_high_short(
    highs: list[tuple[int, float]],
    entry_price: float,
    sl_swing_high: float,
) -> float:
    """Topo da perna fib (maior high acima da entrada) — só para TPs."""
    above = [h for _, h in highs if h > entry_price]
    return max(above) if above else sl_swing_high


def _tp_leg_low_long(
    lows: list[tuple[int, float]],
    entry_price: float,
    sl_swing_low: float,
) -> float:
    """Fundo da perna fib (menor low abaixo da entrada) — só para TPs."""
    below = [l for _, l in lows if l < entry_price]
    return min(below) if below else sl_swing_low


def _resolve_swing_leg(
    window,
    side: Side,
    entry_price: float,
    *,
    max_entry_ratio: float,
    min_tps_above: int,
) -> tuple[float, float, float, float, str] | None:
    """
    Modelo do gráfico:
    SHORT — SL no último topo fractal; TPs em fib (topo máx → fundo).
    LONG  — SL no último fundo fractal; TPs em fib (fundo mín → topo).
    Retorna: swing_low, swing_high_tp, sl_anchor, range_size, impulse.
    """
    if window.empty:
        return None

    df = window.reset_index(drop=True)
    highs, lows = _swing_points(df)

    if side == "SHORT":
        _, sl_anchor = _anchor_swing_high_short(highs, entry_price, df)
        swing_high = _tp_leg_high_short(highs, entry_price, sl_anchor)
        swing_low = _anchor_swing_low_short(lows, 0, entry_price, df)
    else:
        _, sl_anchor = _anchor_swing_low_long(lows, entry_price, df)
        swing_low = _tp_leg_low_long(lows, entry_price, sl_anchor)
        swing_high = _anchor_swing_high_long(highs, 0, entry_price, df)

    swing_low, swing_high, impulse = _expand_leg_if_micro(
        window, side, swing_low, swing_high
    )
    range_size = swing_high - swing_low
    if range_size <= 0:
        return None

    if side == "LONG":
        if not (swing_low < entry_price <= swing_high * 1.01):
            return None
        entry_ratio = (entry_price - swing_low) / range_size
    else:
        if not (swing_low * 0.99 <= entry_price < swing_high * 1.01):
            return None
        entry_ratio = (swing_high - entry_price) / range_size

    if entry_ratio > max_entry_ratio:
        return None

    tps = _build_take_profits(
        side, swing_low, swing_high, range_size, entry_price
    )
    if tps is None:
        return None

    if side == "LONG":
        active = sum(1 for tp in tps if tp > entry_price)
    else:
        active = sum(1 for tp in tps if tp < entry_price)
    if active < min_tps_above:
        return None

    return swing_low, swing_high, sl_anchor, range_size, impulse


def compute_fib_scalp_levels(
    ohlcv: list[list[float]],
    side: Side,
    entry_price: float,
    *,
    lookback: int = 80,
    sl_buffer_pct: float = 0.08,
    min_tp1_rr: float = 0.0,
    tp_close_pcts: tuple[float, float, float] = (50.0, 30.0, 20.0),
    max_entry_ratio: float = 0.95,
    min_tps_above: int = 1,
) -> FibScalpLevels | None:
    """
    LONG: SL no último fundo, TPs em fib até o último topo (lado lucrativo).
    SHORT: SL no último topo, TPs em fib até o último fundo (lado lucrativo).
    """
    df = ohlcv_to_dataframe(ohlcv)
    if len(df) < max(lookback, 20):
        return None

    window = df.iloc[:-1] if len(df) > 1 else df
    window = window.tail(lookback)

    buffer = sl_buffer_pct / 100.0
    leg = _resolve_swing_leg(
        window,
        side,
        entry_price,
        max_entry_ratio=max_entry_ratio,
        min_tps_above=min_tps_above,
    )
    if leg is None:
        return None

    swing_low, swing_high, sl_anchor, range_size, impulse = leg
    if side == "LONG" and entry_price > swing_high * 1.001:
        return None
    if side == "SHORT" and entry_price < swing_low * 0.999:
        return None

    tps = _build_take_profits(
        side, swing_low, swing_high, range_size, entry_price
    )
    if tps is None:
        return None

    if side == "LONG":
        sl = sl_anchor * (1.0 - buffer)
        if not (sl < entry_price):
            return None
        active = [tp for tp in tps if tp > entry_price]
    else:
        sl = sl_anchor * (1.0 + buffer)
        if not (entry_price < sl):
            return None
        active = [tp for tp in tps if tp < entry_price]

    if len(active) < min_tps_above:
        return None

    tp1_rr, weighted_rr = _weighted_rr(entry_price, sl, tps, tp_close_pcts)
    if active:
        risk = abs(entry_price - sl)
        tp1_rr = abs(active[0] - entry_price) / risk if risk > 0 else 0.0
    if min_tp1_rr > 0 and tp1_rr < min_tp1_rr:
        return None

    return FibScalpLevels(
        side=side,
        entry=entry_price,
        stop_loss=sl,
        take_profits=tps,
        swing_low=swing_low,
        swing_high=swing_high,
        range_size=range_size,
        impulse=impulse,
        tp1_rr=round(tp1_rr, 3),
        weighted_rr=round(weighted_rr, 3),
        sl_reason="structure_base" if side == "LONG" else "structure_top",
    )
