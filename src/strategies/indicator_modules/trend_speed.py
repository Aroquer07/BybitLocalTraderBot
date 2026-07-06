"""Trend Speed Analyzer (Zeiierman) — port Python para mercados em tendência."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pandas_ta as ta

from src.strategies.indicator_modules.base import Direction, ModuleResult
from src.strategies.indicators import ohlcv_to_dataframe

DEFAULT_MAX_LENGTH = 50
DEFAULT_ACCEL_MULT = 5.0
DEFAULT_COLLECTION = 100
TOUCH_ATR_MULT = 0.35


def _wma(series: pd.Series, length: int) -> pd.Series:
    weights = np.arange(1, length + 1, dtype=float)
    return series.rolling(length).apply(
        lambda x: np.dot(x, weights) / weights.sum(),
        raw=True,
    )


def _compute_dyn_ema(close: pd.Series, max_length: int, accel_mult: float) -> pd.Series:
    counts_diff = close
    max_abs = counts_diff.abs().rolling(200, min_periods=1).max().replace(0, 1.0)
    counts_norm = (counts_diff + max_abs) / (2 * max_abs)
    dyn_length = 5 + counts_norm * (max_length - 5)

    prev_diff = counts_diff.shift(1).fillna(counts_diff.iloc[0])
    delta = (counts_diff - prev_diff).abs()
    max_delta = delta.rolling(200, min_periods=1).max().replace(0, 1.0)
    accel_factor = delta / max_delta

    out = np.empty(len(close))
    out[:] = np.nan
    dyn_ema = float(close.iloc[0])
    for i in range(len(close)):
        dl = float(dyn_length.iloc[i])
        af = float(accel_factor.iloc[i])
        alpha_base = 2 / (dl + 1)
        alpha = min(1.0, alpha_base * (1 + af * accel_mult))
        c = float(close.iloc[i])
        dyn_ema = c if i == 0 else alpha * c + (1 - alpha) * dyn_ema
        out[i] = dyn_ema
    return pd.Series(out, index=close.index)


def evaluate_trend_speed(
    ohlcv: list[list[float]],
    *,
    max_length: int = DEFAULT_MAX_LENGTH,
    accel_mult: float = DEFAULT_ACCEL_MULT,
    collection: int = DEFAULT_COLLECTION,
    touch_atr_mult: float = TOUCH_ATR_MULT,
    screener_bias: Direction | None = None,
    allow_without_pullback: bool = False,
) -> ModuleResult:
    """
    LONG: linha verde, preço acima, pullback na linha, histograma verde.
    SHORT: linha vermelha, preço abaixo, pullback na linha, histograma vermelho.
    """
    if len(ohlcv) < max(60, collection // 2):
        return ModuleResult("trend_speed", None, 0.0, False, "OHLCV insuficiente")

    df = ohlcv_to_dataframe(ohlcv)
    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_ = df["open"]

    dyn_ema = _compute_dyn_ema(close, max_length, accel_mult)
    wma2 = _wma(close, 2)
    bullish_line = wma2.iloc[-1] > dyn_ema.iloc[-1]

    c_rma = ta.rma(close, length=10)
    o_rma = ta.rma(open_, length=10)
    if c_rma is None or o_rma is None:
        return ModuleResult("trend_speed", None, 0.0, False, "RMA indisponível")

    speed = (c_rma - o_rma).cumsum()
    trendspeed = ta.hma(speed, length=5)
    if trendspeed is None:
        return ModuleResult("trend_speed", None, 0.0, False, "HMA speed indisponível")

    ts_last = float(trendspeed.iloc[-1])
    trend_last = float(dyn_ema.iloc[-1])
    close_last = float(close.iloc[-1])
    low_last = float(low.iloc[-1])
    high_last = float(high.iloc[-1])

    atr = ta.atr(high, low, close, length=14)
    atr_last = float(atr.iloc[-1]) if atr is not None and not pd.isna(atr.iloc[-1]) else abs(close_last - trend_last)
    touch_tol = atr_last * touch_atr_mult

    hist_bull = ts_last > 0
    hist_bear = ts_last < 0

    direction: Direction | None = None
    reason = ""

    if bullish_line and close_last > trend_last and hist_bull:
        touched = low_last <= trend_last + touch_tol and close_last >= trend_last - touch_tol
        if touched:
            direction = "LONG"
            reason = (
                f"Pullback na linha verde | speed={ts_last:.4g} | "
                f"close={close_last:.4g} trend={trend_last:.4g}"
            )

    if not direction and not bullish_line and close_last < trend_last and hist_bear:
        touched = high_last >= trend_last - touch_tol and close_last <= trend_last + touch_tol
        if touched:
            direction = "SHORT"
            reason = (
                f"Pullback na linha vermelha | speed={ts_last:.4g} | "
                f"close={close_last:.4g} trend={trend_last:.4g}"
            )

    if direction is None and allow_without_pullback:
        if screener_bias == "LONG" and bullish_line and close_last > trend_last and hist_bull:
            direction = "LONG"
            reason = (
                f"Tendência LONG alinhada (screener) | speed={ts_last:.4g} | "
                f"close={close_last:.4g} trend={trend_last:.4g}"
            )
        elif screener_bias == "SHORT" and not bullish_line and close_last < trend_last and hist_bear:
            direction = "SHORT"
            reason = (
                f"Tendência SHORT alinhada (screener) | speed={ts_last:.4g} | "
                f"close={close_last:.4g} trend={trend_last:.4g}"
            )
        elif screener_bias is None:
            if bullish_line and close_last > trend_last and hist_bull:
                direction = "LONG"
                reason = (
                    f"Tendência LONG alinhada | speed={ts_last:.4g} | "
                    f"close={close_last:.4g} trend={trend_last:.4g}"
                )
            elif not bullish_line and close_last < trend_last and hist_bear:
                direction = "SHORT"
                reason = (
                    f"Tendência SHORT alinhada | speed={ts_last:.4g} | "
                    f"close={close_last:.4g} trend={trend_last:.4g}"
                )

    if direction is None:
        bias = "bull" if bullish_line else "bear"
        return ModuleResult(
            "trend_speed",
            None,
            0.0,
            False,
            f"Sem pullback {bias} | hist={'+' if hist_bull else '-'}",
            regime="trend",
        )

    min_sp = speed.tail(collection).min()
    max_sp = speed.tail(collection).max()
    norm = (float(speed.iloc[-1]) - min_sp) / (max_sp - min_sp) if max_sp != min_sp else 0.5
    confidence = min(1.0, 0.55 + abs(norm - 0.5) + (0.15 if abs(ts_last) > atr_last * 0.1 else 0))
    if "screener)" in reason:
        confidence = 0.72
    elif "alinhada" in reason:
        confidence = max(confidence, 0.66)

    risk = atr_last * 1.5
    if direction == "LONG":
        sl = close_last - risk
        tps = tuple(close_last + risk * i for i in range(1, 4))
    else:
        sl = close_last + risk
        tps = tuple(close_last - risk * i for i in range(1, 4))

    return ModuleResult(
        "trend_speed",
        direction,
        round(confidence, 3),
        True,
        reason,
        regime="trend",
        entry_price=close_last,
        stop_loss=sl,
        take_profits=tps,
    )
