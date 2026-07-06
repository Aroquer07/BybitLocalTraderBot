"""Sniper Entry/Exit (KhanSaab) — painel multi-condição com SL/TP por ATR."""

from __future__ import annotations

import pandas as pd
import pandas_ta as ta

from typing import Literal

from src.strategies.indicator_modules.base import Direction, ModuleResult
from src.strategies.indicators import ohlcv_to_dataframe

DEFAULT_ATR_MULT = 1.5
# R:R dos TPs Sniper — TP1 nunca abaixo de 1.2R.
SNIPER_TP_RR_MULTIPLIERS: tuple[float, ...] = (1.2, 2.0, 3.0)
EntryMode = Literal["panel", "cross"]
DEFAULT_MIN_SCORE_PCT = 85.0
DEFAULT_MIN_ADX = 20.0
DEFAULT_MIN_RSI_LONG = 60.0
DEFAULT_MAX_RSI_SHORT = 50.0


def _vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].replace(0, 1e-9)
    return (typical * vol).cumsum() / vol.cumsum()


def _score_bull(
    close: float,
    open_: float,
    vwap: float,
    rsi: float,
    macd: float,
    macd_sig: float,
    ema9: float,
    ema21: float,
    adx: float,
    volume: float,
    vol_avg: float,
    rsi_htf: float,
) -> tuple[float, float]:
    b = 0.0
    b += 1 if close > vwap else 0
    b += 1 if rsi > 50 else 0
    b += 1 if macd > macd_sig else 0
    b += 1 if ema9 > ema21 else 0
    b += 1 if adx > 25 and close > ema9 else 0
    b += 1 if volume > vol_avg and close > open_ else 0
    b += 1 if rsi_htf > 50 else 0
    r = 0.0
    r += 1 if close < vwap else 0
    r += 1 if rsi < 50 else 0
    r += 1 if macd < macd_sig else 0
    r += 1 if ema9 < ema21 else 0
    r += 1 if adx > 25 and close < ema9 else 0
    r += 1 if volume > vol_avg and close < open_ else 0
    r += 1 if rsi_htf < 50 else 0
    return (b / 7) * 100, (r / 7) * 100


def evaluate_sniper_entry(
    ohlcv: list[list[float]],
    ohlcv_htf: list[list[float]] | None = None,
    *,
    atr_mult: float = DEFAULT_ATR_MULT,
    min_score_pct: float = DEFAULT_MIN_SCORE_PCT,
    min_adx: float = DEFAULT_MIN_ADX,
    min_rsi_long: float = DEFAULT_MIN_RSI_LONG,
    max_rsi_short: float = DEFAULT_MAX_RSI_SHORT,
    require_ema_cross: bool = True,
    entry_mode: EntryMode = "panel",
) -> ModuleResult:
    """
    panel: score bull/bear alto + filtros do painel.
    cross: gatilho no cruzamento EMA9/21 (como TradingView) + SL/TP ATR 1R-3R.
    """
    if len(ohlcv) < 50:
        return ModuleResult("sniper", None, 0.0, False, "OHLCV insuficiente")

    df = ohlcv_to_dataframe(ohlcv)
    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_ = df["open"]
    volume = df["volume"]

    ema9 = ta.ema(close, length=9)
    ema21 = ta.ema(close, length=21)
    rsi = ta.rsi(close, length=14)
    macd_df = ta.macd(close, fast=12, slow=26, signal=9)
    adx_df = ta.adx(high, low, close, length=14)
    atr = ta.atr(high, low, close, length=14)
    vol_avg = volume.rolling(20).mean()

    if any(x is None for x in (ema9, ema21, rsi, macd_df, adx_df, atr)):
        return ModuleResult("sniper", None, 0.0, False, "Indicadores indisponíveis")

    vwap_s = _vwap(df)
    macd_col = macd_df.columns[0]
    sig_col = macd_df.columns[2]
    adx_col = adx_df.columns[0]

    if ohlcv_htf and len(ohlcv_htf) >= 20:
        df_htf = ohlcv_to_dataframe(ohlcv_htf)
        rsi_htf_s = ta.rsi(df_htf["close"], length=14)
        rsi_htf = float(rsi_htf_s.iloc[-1]) if rsi_htf_s is not None else float(rsi.iloc[-1])
    else:
        rsi_htf = float(rsi.iloc[-1])

    c = float(close.iloc[-1])
    o = float(open_.iloc[-1])
    e9 = float(ema9.iloc[-1])
    e21 = float(ema21.iloc[-1])
    e9_prev = float(ema9.iloc[-2])
    e21_prev = float(ema21.iloc[-2])
    rsi_v = float(rsi.iloc[-1])
    m = float(macd_df[macd_col].iloc[-1])
    s = float(macd_df[sig_col].iloc[-1])
    adx_v = float(adx_df[adx_col].iloc[-1])
    atr_v = float(atr.iloc[-1])
    vol = float(volume.iloc[-1])
    vol_a = float(vol_avg.iloc[-1]) if not pd.isna(vol_avg.iloc[-1]) else vol
    vwap_v = float(vwap_s.iloc[-1])

    bull_pct, bear_pct = _score_bull(c, o, vwap_v, rsi_v, m, s, e9, e21, adx_v, vol, vol_a, rsi_htf)

    cross_up = e9_prev <= e21_prev and e9 > e21
    cross_dn = e9_prev >= e21_prev and e9 < e21

    direction: Direction | None = None
    reason = ""

    if entry_mode == "cross":
        if cross_up and bull_pct >= bear_pct:
            direction = "LONG"
            reason = (
                f"EMA9×21 BUY | bull={bull_pct:.0f}% bear={bear_pct:.0f}% "
                f"| RSI={rsi_v:.1f} ADX={adx_v:.1f}"
            )
        elif cross_dn and bear_pct >= bull_pct:
            direction = "SHORT"
            reason = (
                f"EMA9×21 SELL | bear={bear_pct:.0f}% bull={bull_pct:.0f}% "
                f"| RSI={rsi_v:.1f} ADX={adx_v:.1f}"
            )
    else:
        if bull_pct >= min_score_pct and bear_pct < 100 - min_score_pct:
            checks = [
                c > vwap_v,
                rsi_v >= min_rsi_long,
                m > s,
                adx_v >= min_adx,
                e9 > e21,
            ]
            if all(checks) and (cross_up or not require_ema_cross):
                direction = "LONG"
                reason = f"Bull {bull_pct:.0f}% | RSI={rsi_v:.1f} ADX={adx_v:.1f} VWAP+ MACD+"

        if bear_pct >= min_score_pct and bull_pct < 100 - min_score_pct:
            checks = [
                c < vwap_v,
                rsi_v <= max_rsi_short,
                m < s,
                adx_v >= min_adx,
                e9 < e21,
            ]
            if all(checks) and (cross_dn or not require_ema_cross):
                direction = "SHORT"
                reason = f"Bear {bear_pct:.0f}% | RSI={rsi_v:.1f} ADX={adx_v:.1f} VWAP- MACD-"

    if direction is None:
        return ModuleResult(
            "sniper",
            None,
            max(bull_pct, bear_pct) / 100 * 0.5,
            False,
            f"Painel bull={bull_pct:.0f}% bear={bear_pct:.0f}% — condições incompletas",
        )

    risk = atr_v * atr_mult
    entry = c
    if direction == "LONG":
        sl = entry - risk
        tps = tuple(entry + risk * m for m in SNIPER_TP_RR_MULTIPLIERS)
    else:
        sl = entry + risk
        tps = tuple(entry - risk * m for m in SNIPER_TP_RR_MULTIPLIERS)

    confidence = min(1.0, max(bull_pct, bear_pct) / 100)

    return ModuleResult(
        "sniper",
        direction,
        round(confidence, 3),
        True,
        reason,
        entry_price=entry,
        stop_loss=sl,
        take_profits=tps,
    )
