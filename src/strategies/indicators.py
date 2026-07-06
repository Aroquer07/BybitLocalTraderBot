"""Camada de indicadores técnicos — pandas-ta vetorizado, JSON compacto para LLM."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pandas_ta as ta

from src.utils.logger import get_logger

logger = get_logger(__name__)

RSI_PERIODS = (6, 12, 24)
SMA_PERIODS = (7, 14, 28)
EMA_PERIODS = (7, 14, 28)
VOL_MA_PERIODS = (5, 10)
ADX_TREND_THRESHOLD = 25.0


def ohlcv_to_dataframe(ohlcv: list[list[float]]) -> pd.DataFrame:
    """Converte lista OHLCV CCXT em DataFrame tipado."""
    df = pd.DataFrame(
        ohlcv,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna()


def compute_ohlcv_summary(df: pd.DataFrame) -> dict[str, Any]:
    """Resumo estatístico dos candles para contexto da LLM."""
    if df.empty:
        return {}
    candles_per_day = 96
    return {
        "candle_count": len(df),
        "last_close": round(float(df["close"].iloc[-1]), 6),
        "high_24": round(
            float(df["high"].tail(candles_per_day).max())
            if len(df) >= candles_per_day
            else float(df["high"].max()),
            6,
        ),
        "low_24": round(
            float(df["low"].tail(candles_per_day).min())
            if len(df) >= candles_per_day
            else float(df["low"].min()),
            6,
        ),
        "avg_volume": round(float(df["volume"].mean()), 4),
        "last_volume": round(float(df["volume"].iloc[-1]), 4),
        "volume_ratio": round(
            float(df["volume"].iloc[-1] / df["volume"].mean()), 4
        )
        if df["volume"].mean() > 0
        else 1.0,
        "price_change_pct": round(
            float((df["close"].iloc[-1] - df["close"].iloc[0]) / df["close"].iloc[0] * 100),
            4,
        ),
    }


def _safe_float(val: Any) -> float | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return round(float(val), 6)
    except (TypeError, ValueError):
        return None


def _find_swing_points(
    series: pd.Series,
    window: int = 5,
    count: int = 2,
) -> list[tuple[int, float]]:
    """Retorna os últimos `count` swing lows/highs (índice, valor)."""
    points: list[tuple[int, float]] = []
    if len(series) < window * 2 + 1:
        return points

    for i in range(len(series) - window - 1, window - 1, -1):
        segment = series.iloc[i - window : i + window + 1]
        center = series.iloc[i]
        if center == segment.min():
            points.append((i, float(center)))
            if len(points) >= count:
                break
    return points


def _find_swing_highs(series: pd.Series, window: int = 5, count: int = 2) -> list[tuple[int, float]]:
    points: list[tuple[int, float]] = []
    if len(series) < window * 2 + 1:
        return points

    for i in range(len(series) - window - 1, window - 1, -1):
        segment = series.iloc[i - window : i + window + 1]
        center = series.iloc[i]
        if center == segment.max():
            points.append((i, float(center)))
            if len(points) >= count:
                break
    return points


def _detect_divergences(df: pd.DataFrame) -> dict[str, str | None]:
    """
    Detecção básica de divergência: compara últimos 2 swings de preço vs indicador.
    """
    result: dict[str, str | None] = {
        "rsi_divergence": None,
        "macd_divergence": None,
    }
    if len(df) < 30:
        return result

    close = df["close"]
    rsi_col = next((c for c in df.columns if c.startswith("RSI_")), None)
    macd_col = next((c for c in df.columns if c.startswith("MACDh_")), None)

    price_lows = _find_swing_points(close, count=2)
    price_highs = _find_swing_highs(close, count=2)

    if rsi_col and len(price_lows) == 2:
        rsi_vals = [df[rsi_col].iloc[idx] for idx, _ in price_lows]
        if all(pd.notna(v) for v in rsi_vals):
            p1, p2 = price_lows[1][1], price_lows[0][1]
            r1, r2 = float(rsi_vals[1]), float(rsi_vals[0])
            if p2 < p1 and r2 > r1:
                result["rsi_divergence"] = "bullish"
            elif p2 > p1 and r2 < r1:
                result["rsi_divergence"] = "bearish"

    if rsi_col and len(price_highs) == 2:
        rsi_vals = [df[rsi_col].iloc[idx] for idx, _ in price_highs]
        if all(pd.notna(v) for v in rsi_vals):
            p1, p2 = price_highs[1][1], price_highs[0][1]
            r1, r2 = float(rsi_vals[1]), float(rsi_vals[0])
            if p2 > p1 and r2 < r1:
                result["rsi_divergence"] = "bearish"
            elif p2 < p1 and r2 > r1:
                result["rsi_divergence"] = "bullish"

    if macd_col and len(price_lows) == 2:
        macd_vals = [df[macd_col].iloc[idx] for idx, _ in price_lows]
        if all(pd.notna(v) for v in macd_vals):
            p1, p2 = price_lows[1][1], price_lows[0][1]
            m1, m2 = float(macd_vals[1]), float(macd_vals[0])
            if p2 < p1 and m2 > m1:
                result["macd_divergence"] = "bullish"
            elif p2 > p1 and m2 < m1:
                result["macd_divergence"] = "bearish"

    if macd_col and len(price_highs) == 2:
        macd_vals = [df[macd_col].iloc[idx] for idx, _ in price_highs]
        if all(pd.notna(v) for v in macd_vals):
            p1, p2 = price_highs[1][1], price_highs[0][1]
            m1, m2 = float(macd_vals[1]), float(macd_vals[0])
            if p2 > p1 and m2 < m1:
                result["macd_divergence"] = "bearish"
            elif p2 < p1 and m2 > m1:
                result["macd_divergence"] = "bullish"

    return result


def _compute_session_vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP intraday com reset na sessão UTC (meia-noite)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    session = df["timestamp"].dt.date
    cum_vol = df.groupby(session)["volume"].cumsum()
    cum_tpv = (typical * df["volume"]).groupby(session).cumsum()
    return cum_tpv / cum_vol.replace(0, pd.NA)


def compute_indicators(df: pd.DataFrame) -> dict[str, Any]:
    """
    Calcula arsenal completo de indicadores (base + PRO) para um timeframe.

    Retorna dict JSON-serializável — sem DataFrames.
    """
    indicators: dict[str, Any] = {}
    if df.empty or len(df) < 30:
        return indicators

    work = df.copy()

    try:
        for length in RSI_PERIODS:
            work.ta.rsi(length=length, append=True)

        work.ta.macd(fast=12, slow=26, signal=9, append=True)

        for length in SMA_PERIODS:
            work.ta.sma(length=length, append=True)

        for length in EMA_PERIODS:
            work.ta.ema(length=length, append=True)

        for length in VOL_MA_PERIODS:
            work[f"VOL_MA_{length}"] = work["volume"].rolling(length).mean()

        work.ta.bbands(length=20, std=2, append=True)
        work.ta.ichimoku(tenkan=9, kijun=26, senkou=52, append=True)
        work.ta.psar(append=True)
        work.ta.stochrsi(append=True)
        work.ta.obv(append=True)
        work.ta.atr(length=14, append=True)
        work.ta.adx(length=14, append=True)
        work.ta.supertrend(length=7, multiplier=3.0, append=True)

        vwap_series = _compute_session_vwap(work)
        work["VWAP_SESSION"] = vwap_series

        last = work.iloc[-1]
        prev = work.iloc[-2] if len(work) > 1 else last
        close = float(last["close"])

        for length in RSI_PERIODS:
            col = f"RSI_{length}"
            if col in work.columns:
                indicators[f"rsi_{length}"] = _safe_float(last[col])

        macd_map = {
            "MACD_12_26_9": "macd",
            "MACDs_12_26_9": "macd_signal",
            "MACDh_12_26_9": "macd_histogram",
        }
        for src, dest in macd_map.items():
            if src in work.columns:
                indicators[dest] = _safe_float(last[src])

        for length in SMA_PERIODS:
            col = f"SMA_{length}"
            if col in work.columns:
                indicators[f"sma_{length}"] = _safe_float(last[col])

        for length in EMA_PERIODS:
            col = f"EMA_{length}"
            if col in work.columns:
                indicators[f"ema_{length}"] = _safe_float(last[col])

        for length in VOL_MA_PERIODS:
            col = f"VOL_MA_{length}"
            if col in work.columns:
                indicators[f"volume_ma_{length}"] = _safe_float(last[col])

        bb_cols = {c.split("_")[0]: c for c in work.columns if c.startswith("BBL_") or c.startswith("BBM_") or c.startswith("BBU_") or c.startswith("BBB_") or c.startswith("BBP_")}
        bb_map = {
            "BBL": "bb_lower",
            "BBM": "bb_middle",
            "BBU": "bb_upper",
            "BBB": "bb_bandwidth",
            "BBP": "bb_percent",
        }
        for prefix, dest in bb_map.items():
            col = bb_cols.get(prefix)
            if col:
                indicators[dest] = _safe_float(last[col])

        ichimoku_map = {
            "ISA_9": "ichimoku_span_a",
            "ISB_26": "ichimoku_span_b",
            "ITS_9": "ichimoku_tenkan",
            "IKS_26": "ichimoku_kijun",
            "ICS_26": "ichimoku_chikou",
        }
        for src, dest in ichimoku_map.items():
            if src in work.columns:
                indicators[dest] = _safe_float(last[src])

        psar_long = next((c for c in work.columns if c.startswith("PSARl_")), None)
        psar_short = next((c for c in work.columns if c.startswith("PSARs_")), None)
        if psar_long and pd.notna(last[psar_long]):
            indicators["psar"] = _safe_float(last[psar_long])
            indicators["psar_direction"] = "bullish"
        elif psar_short and pd.notna(last[psar_short]):
            indicators["psar"] = _safe_float(last[psar_short])
            indicators["psar_direction"] = "bearish"

        stoch_k = next((c for c in work.columns if c.startswith("STOCHRSIk_")), None)
        stoch_d = next((c for c in work.columns if c.startswith("STOCHRSId_")), None)
        if stoch_k:
            indicators["stochrsi_k"] = _safe_float(last[stoch_k])
        if stoch_d:
            indicators["stochrsi_d"] = _safe_float(last[stoch_d])

        if "OBV" in work.columns:
            indicators["obv"] = _safe_float(last["OBV"])
            if len(work) > 2:
                obv_prev = work["OBV"].iloc[-2]
                if pd.notna(obv_prev) and pd.notna(last["OBV"]):
                    indicators["obv_trend"] = (
                        "rising" if last["OBV"] > obv_prev else "falling"
                    )

        atr_col = next((c for c in work.columns if c.startswith("ATR")), None)
        if atr_col:
            indicators["atr_14"] = _safe_float(last[atr_col])

        adx_col = next((c for c in work.columns if c.startswith("ADX_")), None)
        dmp_col = next((c for c in work.columns if c.startswith("DMP_")), None)
        dmn_col = next((c for c in work.columns if c.startswith("DMN_")), None)
        if adx_col:
            indicators["adx_14"] = _safe_float(last[adx_col])
        if dmp_col:
            indicators["dmp_14"] = _safe_float(last[dmp_col])
        if dmn_col:
            indicators["dmn_14"] = _safe_float(last[dmn_col])

        st_dir_col = next((c for c in work.columns if c.startswith("SUPERTd_")), None)
        st_val_col = next((c for c in work.columns if c.startswith("SUPERT_") and "d_" not in c and "l_" not in c and "s_" not in c), None)
        if st_dir_col:
            st_dir = last[st_dir_col]
            indicators["supertrend_direction"] = (
                "bullish" if st_dir == 1 or st_dir == 1.0 else "bearish"
            )
        if st_val_col:
            indicators["supertrend"] = _safe_float(last[st_val_col])

        if "VWAP_SESSION" in work.columns:
            indicators["vwap"] = _safe_float(last["VWAP_SESSION"])

        macd_hist = indicators.get("macd_histogram")
        macd_hist_prev = (
            _safe_float(prev["MACDh_12_26_9"])
            if "MACDh_12_26_9" in work.columns
            else None
        )
        macd_line = indicators.get("macd")
        macd_signal = indicators.get("macd_signal")
        macd_prev_line = _safe_float(prev.get("MACD_12_26_9"))
        macd_prev_signal = _safe_float(prev.get("MACDs_12_26_9"))

        if macd_hist is not None and macd_hist_prev is not None:
            indicators["macd_momentum"] = (
                "increasing" if macd_hist > macd_hist_prev else "decreasing"
            )
        if (
            macd_line is not None
            and macd_signal is not None
            and macd_prev_line is not None
            and macd_prev_signal is not None
        ):
            crossed_up = macd_prev_line <= macd_prev_signal and macd_line > macd_signal
            crossed_down = macd_prev_line >= macd_prev_signal and macd_line < macd_signal
            if crossed_up:
                indicators["macd_cross"] = "bullish"
            elif crossed_down:
                indicators["macd_cross"] = "bearish"

        rsi_12 = indicators.get("rsi_12")
        if rsi_12 is not None:
            if rsi_12 > 70:
                indicators["rsi_zone"] = "overbought"
            elif rsi_12 < 30:
                indicators["rsi_zone"] = "oversold"
            else:
                indicators["rsi_zone"] = "neutral"

        ema_7 = indicators.get("ema_7")
        ema_14 = indicators.get("ema_14")
        ema_28 = indicators.get("ema_28")
        if ema_7 is not None and ema_14 is not None and ema_28 is not None:
            if close > ema_7 > ema_14 > ema_28:
                indicators["trend"] = "bullish"
            elif close < ema_7 < ema_14 < ema_28:
                indicators["trend"] = "bearish"
            else:
                indicators["trend"] = "neutral"

        bb_upper = indicators.get("bb_upper")
        bb_lower = indicators.get("bb_lower")
        bb_bandwidth = indicators.get("bb_bandwidth")
        if bb_bandwidth is not None and "BBB" in str(bb_cols.get("BBB", "")):
            bbb_col = bb_cols["BBB"]
            indicators["bb_squeeze"] = bb_bandwidth < work[bbb_col].tail(20).mean() * 0.8
            if close > bb_upper:
                indicators["bb_position"] = "above_upper"
            elif close < bb_lower:
                indicators["bb_position"] = "below_lower"
            else:
                indicators["bb_position"] = "inside"

        span_a = indicators.get("ichimoku_span_a")
        span_b = indicators.get("ichimoku_span_b")
        tenkan = indicators.get("ichimoku_tenkan")
        kijun = indicators.get("ichimoku_kijun")
        if span_a is not None and span_b is not None:
            cloud_top = max(span_a, span_b)
            cloud_bottom = min(span_a, span_b)
            indicators["ichimoku_above_cloud"] = close > cloud_top
            indicators["ichimoku_below_cloud"] = close < cloud_bottom
        if tenkan is not None and kijun is not None:
            indicators["ichimoku_tk_cross"] = (
                "bullish" if tenkan > kijun else "bearish" if tenkan < kijun else "neutral"
            )

        indicators["divergences"] = _detect_divergences(work)

        from src.strategies.kalman import compute_kalman_indicators

        kalman = compute_kalman_indicators(work)
        if kalman:
            indicators.update(kalman)

    except Exception:
        logger.exception("Erro parcial no cálculo de indicadores — retornando parcial")

    return indicators
