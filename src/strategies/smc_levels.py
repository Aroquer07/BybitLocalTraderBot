"""
Smart Money Concepts (SMC) — SL/TP ancorados em estrutura de mercado.

SL: abaixo/acima de liquidez (swing) ou invalidação do order block.
TPs: pools de liquidez, FVG e extensões estruturais (BSL/SSL).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from src.models.schemas import TradeDirection
from src.strategies.indicators import ohlcv_to_dataframe

Side = Literal["LONG", "SHORT"]


@dataclass(frozen=True)
class OrderBlock:
    high: float
    low: float
    direction: Literal["bullish", "bearish"]
    bar_index: int


@dataclass(frozen=True)
class FairValueGap:
    top: float
    bottom: float
    direction: Literal["bullish", "bearish"]
    bar_index: int


@dataclass(frozen=True)
class SMCLevels:
    entry: float
    stop_loss: float
    take_profits: tuple[float, float, float, float]
    tp_labels: tuple[str, str, str, str]
    sl_reason: str
    swing_high: float
    swing_low: float
    tp1_rr: float
    weighted_rr: float


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        rng = float(df["high"].max() - df["low"].min()) if len(df) else 0.0
        return max(rng * 0.02, 1e-8)
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    val = float(tr.tail(period).mean())
    return max(val, 1e-8)


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


def _find_order_blocks(df: pd.DataFrame, lookback: int = 40) -> list[OrderBlock]:
    blocks: list[OrderBlock] = []
    tail = df.tail(lookback)
    offset = len(df) - len(tail)
    for i in range(2, len(tail) - 1):
        o = float(tail["open"].iloc[i])
        c = float(tail["close"].iloc[i])
        h = float(tail["high"].iloc[i])
        l = float(tail["low"].iloc[i])
        nxt_close = float(tail["close"].iloc[i + 1])
        prev_high = float(tail["high"].iloc[i - 1])
        prev_low = float(tail["low"].iloc[i - 1])

        if c < o and nxt_close > prev_high:
            blocks.append(
                OrderBlock(h, l, "bullish", offset + i)
            )
        if c > o and nxt_close < prev_low:
            blocks.append(
                OrderBlock(h, l, "bearish", offset + i)
            )
    return blocks


def _find_fvgs(df: pd.DataFrame, lookback: int = 60) -> list[FairValueGap]:
    fvgs: list[FairValueGap] = []
    tail = df.tail(lookback)
    offset = len(df) - len(tail)
    for i in range(2, len(tail)):
        h0 = float(tail["high"].iloc[i - 2])
        l0 = float(tail["low"].iloc[i - 2])
        h2 = float(tail["high"].iloc[i])
        l2 = float(tail["low"].iloc[i])
        if l2 > h0:
            fvgs.append(FairValueGap(l2, h0, "bullish", offset + i))
        if h2 < l0:
            fvgs.append(FairValueGap(l0, l2, "bearish", offset + i))
    return fvgs


def _liquidity_targets(
    direction: TradeDirection,
    entry: float,
    swing_highs: list[tuple[int, float]],
    swing_lows: list[tuple[int, float]],
    fvgs: list[FairValueGap],
) -> list[tuple[float, str]]:
    targets: list[tuple[float, str]] = []
    if direction == TradeDirection.LONG:
        for _, price in swing_highs:
            if price > entry * 1.0005:
                targets.append((price, "BSL"))
        for fvg in fvgs:
            if fvg.direction == "bullish" and fvg.top > entry:
                targets.append((fvg.top, "FVG"))
    else:
        for _, price in swing_lows:
            if price < entry * 0.9995:
                targets.append((price, "SSL"))
        for fvg in fvgs:
            if fvg.direction == "bearish" and fvg.bottom < entry:
                targets.append((fvg.bottom, "FVG"))

    if direction == TradeDirection.LONG:
        targets.sort(key=lambda x: x[0])
    else:
        targets.sort(key=lambda x: x[0], reverse=True)

    deduped: list[tuple[float, str]] = []
    seen: set[float] = set()
    for price, label in targets:
        key = round(price, 8)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((price, label))
    return deduped


def _compute_stop(
    direction: TradeDirection,
    entry: float,
    swing_lows: list[tuple[int, float]],
    swing_highs: list[tuple[int, float]],
    blocks: list[OrderBlock],
    atr_val: float,
    buffer_mult: float,
) -> tuple[float, str]:
    buffer = atr_val * buffer_mult
    if direction == TradeDirection.LONG:
        candidates: list[tuple[float, str]] = []
        lows_below = [p for _, p in swing_lows if p < entry]
        if lows_below:
            liq = min(lows_below)
            candidates.append((liq - buffer, "SSL abaixo da entrada"))
        bullish_obs = [b for b in blocks if b.direction == "bullish"]
        if bullish_obs:
            ob = bullish_obs[-1]
            candidates.append((ob.low - buffer, "invalidação OB bullish"))
        if not candidates:
            candidates.append((entry - atr_val * 1.5, "ATR fallback"))
        sl, reason = min(candidates, key=lambda x: x[0])
        if sl >= entry:
            sl = entry - max(buffer, atr_val * 0.5)
        return sl, reason

    candidates = []
    highs_above = [p for _, p in swing_highs if p > entry]
    if highs_above:
        liq = max(highs_above)
        candidates.append((liq + buffer, "BSL acima da entrada"))
    bearish_obs = [b for b in blocks if b.direction == "bearish"]
    if bearish_obs:
        ob = bearish_obs[-1]
        candidates.append((ob.high + buffer, "invalidação OB bearish"))
    if not candidates:
        candidates.append((entry + atr_val * 1.5, "ATR fallback"))
    sl, reason = max(candidates, key=lambda x: x[0])
    if sl <= entry:
        sl = entry + max(buffer, atr_val * 0.5)
    return sl, reason


def _rr(entry: float, sl: float, tp: float) -> float:
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0
    return abs(tp - entry) / risk


def _build_tps(
    direction: TradeDirection,
    entry: float,
    sl: float,
    liquidity: list[tuple[float, str]],
    *,
    min_tp1_rr: float,
    min_tp2_rr: float,
) -> tuple[tuple[float, float, float, float], tuple[str, str, str, str], float, float]:
    risk = abs(entry - sl)
    close_weights = (0.40, 0.30, 0.20, 0.10)

    if direction == TradeDirection.LONG:
        min_tp1 = entry + risk * min_tp1_rr
        min_tp2 = entry + risk * min_tp2_rr
        valid = [(p, l) for p, l in liquidity if p >= min_tp1]
        tps: list[float] = []
        labels: list[str] = []
        for price, label in valid:
            if len(tps) == 0 or price > tps[-1] * 1.001:
                tps.append(price)
                labels.append(label)
            if len(tps) >= 4:
                break
        while len(tps) < 4:
            mult = min_tp2_rr + len(tps) * 1.5
            tps.append(entry + risk * mult)
            labels.append(f"{mult:.1f}R")
    else:
        min_tp1 = entry - risk * min_tp1_rr
        min_tp2 = entry - risk * min_tp2_rr
        valid = [(p, l) for p, l in liquidity if p <= min_tp1]
        tps = []
        labels = []
        for price, label in valid:
            if len(tps) == 0 or price < tps[-1] * 0.999:
                tps.append(price)
                labels.append(label)
            if len(tps) >= 4:
                break
        while len(tps) < 4:
            mult = min_tp2_rr + len(tps) * 1.5
            tps.append(entry - risk * mult)
            labels.append(f"{mult:.1f}R")

    rr1 = _rr(entry, sl, tps[0])
    weighted = sum(
        close_weights[i] * _rr(entry, sl, tps[i]) for i in range(4)
    )
    return (tps[0], tps[1], tps[2], tps[3]), tuple(labels), rr1, weighted


def compute_smc_levels(
    ohlcv: list[list[float]],
    direction: TradeDirection,
    entry: float,
    *,
    min_tp1_rr: float = 2.0,
    min_tp2_rr: float = 3.0,
    sl_buffer_atr_mult: float = 0.2,
    swing_lookback: int = 80,
) -> SMCLevels | None:
    """Calcula SL/TPs SMC a partir de OHLCV estrutural."""
    df = ohlcv_to_dataframe(ohlcv)
    if df.empty or len(df) < 20 or entry <= 0:
        return None

    work = df.iloc[:-1] if len(df) > 1 else df
    if len(work) < 20:
        return None

    atr_val = _atr(work)
    swing_highs, swing_lows = _swing_points(work.tail(swing_lookback))
    blocks = _find_order_blocks(work, lookback=min(40, len(work) - 3))
    fvgs = _find_fvgs(work, lookback=min(60, len(work) - 2))

    sl, sl_reason = _compute_stop(
        direction,
        entry,
        swing_lows,
        swing_highs,
        blocks,
        atr_val,
        sl_buffer_atr_mult,
    )

    liquidity = _liquidity_targets(direction, entry, swing_highs, swing_lows, fvgs)
    tps, labels, tp1_rr, weighted = _build_tps(
        direction,
        entry,
        sl,
        liquidity,
        min_tp1_rr=min_tp1_rr,
        min_tp2_rr=min_tp2_rr,
    )

    if tp1_rr < min_tp1_rr:
        return None

    sh = max((p for _, p in swing_highs), default=entry)
    slw = min((p for _, p in swing_lows), default=entry)

    return SMCLevels(
        entry=entry,
        stop_loss=sl,
        take_profits=tps,
        tp_labels=labels,
        sl_reason=sl_reason,
        swing_high=sh,
        swing_low=slw,
        tp1_rr=round(tp1_rr, 4),
        weighted_rr=round(weighted, 4),
    )


def smc_levels_from_dataframe(
    df: pd.DataFrame,
    direction: TradeDirection,
    entry: float,
    **kwargs,
) -> SMCLevels | None:
    if df.empty:
        return None
    rows = []
    for _, row in df.iterrows():
        ts = int(row["timestamp"].value // 1_000_000)
        rows.append([ts, row["open"], row["high"], row["low"], row["close"], row["volume"]])
    return compute_smc_levels(rows, direction, entry, **kwargs)
