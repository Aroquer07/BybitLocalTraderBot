"""Dados visuais do Sniper Entry/Exit para replay no dashboard (espelho do Pine)."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pandas_ta as ta

from src.strategies.indicator_modules.sniper_entry import (
    SNIPER_TP_RR_MULTIPLIERS,
    _score_bull,
    _vwap,
)
from src.strategies.indicators import ohlcv_to_dataframe

DEFAULT_ATR_MULT = 1.5
TP_COUNT = 3


def _bias_label(bull_pct: float, bear_pct: float) -> str:
    diff = bull_pct - bear_pct
    if diff >= 40:
        return "STRONG BULL"
    if -diff >= 40:
        return "STRONG BEAR"
    return "MILD BULL" if bull_pct > bear_pct else "MILD BEAR"


def build_sniper_panel(df: pd.DataFrame, *, rsi_htf: float | None = None) -> dict[str, Any]:
    """Painel estilo TradingView (último candle)."""
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
        return {}

    vwap_s = _vwap(df)
    macd_col = macd_df.columns[0]
    sig_col = macd_df.columns[2]
    adx_col = adx_df.columns[0]

    c = float(close.iloc[-1])
    o = float(open_.iloc[-1])
    e9 = float(ema9.iloc[-1])
    e21 = float(ema21.iloc[-1])
    rsi_v = float(rsi.iloc[-1])
    m = float(macd_df[macd_col].iloc[-1])
    s = float(macd_df[sig_col].iloc[-1])
    adx_v = float(adx_df[adx_col].iloc[-1])
    atr_v = float(atr.iloc[-1])
    vol = float(volume.iloc[-1])
    vol_a = float(vol_avg.iloc[-1]) if not pd.isna(vol_avg.iloc[-1]) else vol
    vwap_v = float(vwap_s.iloc[-1])
    rsi5 = rsi_htf if rsi_htf is not None else rsi_v

    bull_pct, bear_pct = _score_bull(c, o, vwap_v, rsi_v, m, s, e9, e21, adx_v, vol, vol_a, rsi5)
    bias = _bias_label(bull_pct, bear_pct)

    above_vwap = c > vwap_v
    macd_bull = m > s
    ema_bull = e9 > e21
    vol_high = vol > vol_a
    adx_strong = adx_v > 25

    rows = [
        {"label": "Price/VWAP", "value": "ABOVE" if above_vwap else "BELOW", "tone": "bull" if above_vwap else "bear"},
        {"label": "RSI (14)", "value": f"{rsi_v:.1f}", "tone": "bull" if rsi_v > 50 else "bear"},
        {"label": "MACD Trend", "value": "BULL" if macd_bull else "BEAR", "tone": "bull" if macd_bull else "bear"},
        {"label": "ADX Power", "value": f"{adx_v:.1f}", "tone": "bull" if adx_strong else "neutral"},
        {"label": "EMA Cross", "value": "BULL" if ema_bull else "BEAR", "tone": "bull" if ema_bull else "bear"},
        {"label": "ATR 14", "value": f"{atr_v:.4f}", "tone": "neutral"},
        {"label": "Vol Status", "value": "HIGH" if vol_high else "LOW", "tone": "bull" if vol_high else "neutral"},
        {"label": "5m RSI", "value": f"{rsi5:.1f}", "tone": "bull" if rsi5 > 50 else "bear"},
        {"label": "MACD Main", "value": f"{m:.4f}", "tone": "neutral"},
        {"label": "MACD Sig", "value": f"{s:.4f}", "tone": "neutral"},
        {"label": "Trend Str", "value": "STRONG" if adx_strong else "WEAK", "tone": "bull" if adx_strong else "bear"},
        {"label": "Sniper Mode", "value": "KHANSAAB V.02", "tone": "info"},
    ]

    return {
        "bull_pct": round(bull_pct, 1),
        "bear_pct": round(bear_pct, 1),
        "bias": bias,
        "rows": rows,
    }


def build_sniper_markers_and_setup(
    df: pd.DataFrame,
    timestamps: list[int],
    *,
    atr_mult: float = DEFAULT_ATR_MULT,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Marcadores BUY/SELL históricos + último setup de trade (entry/SL/TP1-5)."""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    ema9 = ta.ema(close, length=9)
    ema21 = ta.ema(close, length=21)
    atr = ta.atr(high, low, close, length=14)

    if ema9 is None or ema21 is None or atr is None:
        return [], None

    markers: list[dict[str, Any]] = []
    last_signal = 0
    trade_setup: dict[str, Any] | None = None

    for i in range(1, len(df)):
        e9_prev = float(ema9.iloc[i - 1])
        e21_prev = float(ema21.iloc[i - 1])
        e9 = float(ema9.iloc[i])
        e21 = float(ema21.iloc[i])
        if any(pd.isna(x) for x in (e9_prev, e21_prev, e9, e21)):
            continue

        cross_up = e9_prev <= e21_prev and e9 > e21
        cross_dn = e9_prev >= e21_prev and e9 < e21
        trigger_buy = cross_up and last_signal <= 0
        trigger_sell = cross_dn and last_signal >= 0

        if trigger_buy:
            last_signal = 1
            markers.append(
                {
                    "t": int(timestamps[i]),
                    "shape": "buy",
                    "price": float(low.iloc[i]),
                    "text": "BUY",
                }
            )
        elif trigger_sell:
            last_signal = -1
            markers.append(
                {
                    "t": int(timestamps[i]),
                    "shape": "sell",
                    "price": float(high.iloc[i]),
                    "text": "SELL",
                }
            )

        if trigger_buy or trigger_sell:
            atr_v = float(atr.iloc[i])
            if pd.isna(atr_v):
                continue
            entry = float(close.iloc[i])
            risk = atr_v * atr_mult
            direction = "LONG" if trigger_buy else "SHORT"
            if direction == "LONG":
                sl = entry - risk
                tps = [entry + risk * m for m in SNIPER_TP_RR_MULTIPLIERS]
            else:
                sl = entry + risk
                tps = [entry - risk * m for m in SNIPER_TP_RR_MULTIPLIERS]

            trade_setup = {
                "direction": direction,
                "signal_t": int(timestamps[i]),
                "entry": round(entry, 8),
                "stop_loss": round(sl, 8),
                "take_profits": [round(tp, 8) for tp in tps],
                "tp_hits": [False] * TP_COUNT,
            }

    if trade_setup and last_signal != 0:
        entry = trade_setup["entry"]
        tps = trade_setup["take_profits"]
        hits = [False] * TP_COUNT
        start_idx = next(
            (i for i, t in enumerate(timestamps) if t == trade_setup["signal_t"]),
            len(df) - 1,
        )
        for j in range(start_idx + 1, len(df)):
            h = float(high.iloc[j])
            l = float(low.iloc[j])
            if last_signal == 1:
                for k, tp in enumerate(tps):
                    if h >= tp:
                        hits[k] = True
            else:
                for k, tp in enumerate(tps):
                    if l <= tp:
                        hits[k] = True
        trade_setup["tp_hits"] = hits

    return markers, trade_setup


def build_ema_ribbon_values(
    df: pd.DataFrame,
    timestamps: list[int],
) -> list[dict[str, Any]]:
    """EMA9/21 por candle para ribbon segmentado no chart."""
    close = df["close"]
    ema9 = ta.ema(close, length=9)
    ema21 = ta.ema(close, length=21)
    if ema9 is None or ema21 is None:
        return []

    out: list[dict[str, Any]] = []
    for i, t in enumerate(timestamps):
        if i >= len(ema9) or pd.isna(ema9.iloc[i]) or pd.isna(ema21.iloc[i]):
            continue
        e9 = float(ema9.iloc[i])
        e21 = float(ema21.iloc[i])
        out.append(
            {
                "t": int(t),
                "ema9": round(e9, 8),
                "ema21": round(e21, 8),
                "bull": e9 > e21,
            }
        )
    return out
