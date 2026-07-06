"""Range Detector (LuxAlgo) — port Python para mercados laterais."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.strategies.indicator_modules.base import Direction, ModuleResult
from src.strategies.indicators import ohlcv_to_dataframe

DEFAULT_LENGTH = 20
DEFAULT_MULT = 1.0
DEFAULT_ATR_LEN = 500
MIN_TOUCHES = 2
RETEST_ATR_MULT = 0.4


@dataclass
class RangeState:
    top: float
    bottom: float
    mid: float
    os: int  # 0=inside, 1=broke up, -1=broke down
    bar_start: int
    bar_end: int
    active: bool


def _detect_range_state(
    df: pd.DataFrame,
    *,
    length: int,
    mult: float,
    atr_len: int,
) -> RangeState | None:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    n = len(df)
    if n < length + 5:
        return None

    tr = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(atr_len, min_periods=14).mean() * mult
    ma = close.rolling(length).mean()

    state: RangeState | None = None
    prev_count = -1

    for i in range(length, n):
        atr_i = float(atr.iloc[i]) if not pd.isna(atr.iloc[i]) else 0.0
        ma_i = float(ma.iloc[i]) if not pd.isna(ma.iloc[i]) else float(close.iloc[i])
        count = sum(
            1
            for j in range(length)
            if abs(float(close.iloc[i - j]) - ma_i) > atr_i
        )

        if count == 0 and prev_count != 0:
            top = ma_i + atr_i
            bottom = ma_i - atr_i
            if state is not None and (i - length) <= state.bar_end:
                top = max(top, state.top)
                bottom = min(bottom, state.bottom)
            state = RangeState(
                top=top,
                bottom=bottom,
                mid=(top + bottom) / 2,
                os=0,
                bar_start=i - length,
                bar_end=i,
                active=True,
            )
        elif count == 0 and state is not None:
            state = RangeState(
                top=state.top,
                bottom=state.bottom,
                mid=state.mid,
                os=state.os,
                bar_start=state.bar_start,
                bar_end=i,
                active=True,
            )

        if state is not None:
            c = float(close.iloc[i])
            if c > state.top:
                state = RangeState(
                    state.top, state.bottom, state.mid, 1, state.bar_start, i, True
                )
            elif c < state.bottom:
                state = RangeState(
                    state.top, state.bottom, state.mid, -1, state.bar_start, i, True
                )

        prev_count = count

    return state


def _count_touches(df: pd.DataFrame, level: float, *, kind: str, lookback: int) -> int:
    """Conta toques em suporte (low) ou resistência (high)."""
    tail = df.tail(lookback)
    tol = level * 0.002
    touches = 0
    for _, row in tail.iterrows():
        if kind == "support" and abs(float(row["low"]) - level) <= tol:
            touches += 1
        elif kind == "resistance" and abs(float(row["high"]) - level) <= tol:
            touches += 1
    return touches


def evaluate_range_detector(
    ohlcv: list[list[float]],
    *,
    length: int = DEFAULT_LENGTH,
    mult: float = DEFAULT_MULT,
    atr_len: int = DEFAULT_ATR_LEN,
    min_touches: int = MIN_TOUCHES,
    retest_atr_mult: float = RETEST_ATR_MULT,
) -> ModuleResult:
    """
    Rompimento com fechamento + reteste do nível rompido.
    SL abaixo/acima da zona.
    """
    if len(ohlcv) < length + 30:
        return ModuleResult("range_detector", None, 0.0, False, "OHLCV insuficiente")

    df = ohlcv_to_dataframe(ohlcv)
    state = _detect_range_state(df, length=length, mult=mult, atr_len=atr_len)
    if state is None or not state.active:
        return ModuleResult("range_detector", None, 0.0, False, "Sem range ativo", regime="range")

    lookback = min(80, len(df))
    sup_touches = _count_touches(df, state.bottom, kind="support", lookback=lookback)
    res_touches = _count_touches(df, state.top, kind="resistance", lookback=lookback)
    if sup_touches < min_touches or res_touches < min_touches:
        return ModuleResult(
            "range_detector",
            None,
            0.0,
            False,
            f"Zona fraca ({sup_touches}S/{res_touches}R toques)",
            regime="range",
        )

    close_last = float(df["close"].iloc[-1])
    low_last = float(df["low"].iloc[-1])
    high_last = float(df["high"].iloc[-1])

    tr = (df["high"] - df["low"]).tail(14).mean()
    atr_last = float(tr) if not pd.isna(tr) else (state.top - state.bottom) * 0.1
    retest_tol = atr_last * retest_atr_mult

    direction: Direction | None = None
    entry = close_last
    sl: float | None = None
    reason = ""

    if state.os == 1:
        retest = low_last <= state.top + retest_tol and close_last >= state.top - retest_tol
        if retest and close_last > state.top:
            direction = "LONG"
            sl = state.bottom - atr_last * 0.2
            reason = f"Rompimento UP + reteste {state.top:.4g} | zona {state.bottom:.4g}-{state.top:.4g}"

    elif state.os == -1:
        retest = high_last >= state.bottom - retest_tol and close_last <= state.bottom + retest_tol
        if retest and close_last < state.bottom:
            direction = "SHORT"
            sl = state.top + atr_last * 0.2
            reason = f"Rompimento DN + reteste {state.bottom:.4g} | zona {state.bottom:.4g}-{state.top:.4g}"

    if direction is None:
        status = {1: "broke_up", -1: "broke_dn", 0: "inside"}.get(state.os, "?")
        return ModuleResult(
            "range_detector",
            None,
            0.0,
            False,
            f"Range {status} — aguardando reteste",
            regime="range",
        )

    risk = abs(entry - sl)
    tps = tuple(
        entry + risk * mult if direction == "LONG" else entry - risk * mult
        for mult in (1, 2, 3)
    )

    return ModuleResult(
        "range_detector",
        direction,
        0.72,
        True,
        reason,
        regime="range",
        entry_price=entry,
        stop_loss=sl,
        take_profits=tps,
    )
