"""
Adaptive Kalman Trend Strength Oscillator (Zeiierman) — port Pine → Python.

Detecta força de tendência e reversões via cruzamento de zero / zonas OB-OS.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

KalmanModel = Literal["standard", "volume_adjusted", "parkinson_adjusted"]


@dataclass(frozen=True)
class KalmanConfig:
    process_noise_1: float = 0.01
    process_noise_2: float = 0.01
    measurement_noise: float = 500.0
    osc_smoothness: int = 10
    trend_lookback: int = 10
    strength_smoothness: int = 10
    model: KalmanModel = "standard"
    ob_threshold: float = 30.0
    os_threshold: float = -30.0


def _wma_last(values: list[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    segment = values[-period:]
    weights = np.arange(1, period + 1, dtype=float)
    weights /= weights.sum()
    return float(np.dot(segment, weights))


def compute_kalman_indicators(
    df: pd.DataFrame,
    config: KalmanConfig | None = None,
) -> dict[str, Any]:
    """
    Calcula filtro de Kalman adaptativo e oscilador de força de tendência.

    Retorna dict JSON-serializável para injetar em `compute_indicators`.
    """
    cfg = config or KalmanConfig()
    min_bars = max(cfg.trend_lookback + cfg.strength_smoothness, 30)
    if df.empty or len(df) < min_bars:
        return {}

    close = df["close"].astype(float).to_numpy()
    high = df["high"].astype(float).to_numpy()
    low = df["low"].astype(float).to_numpy()
    volume = df["volume"].astype(float).to_numpy()
    n = len(close)

    pn1, pn2 = cfg.process_noise_1, cfg.process_noise_2
    F = np.array([[1.0, 1.0], [0.0, 1.0]])
    P = np.eye(2)
    Q = np.array([[pn1, pn1 * pn2], [pn2 * pn1, pn2]])
    R = np.array([[cfg.measurement_noise]])
    H = np.array([[1.0, 0.0]])
    I2 = np.eye(2)
    X = np.array([close[0], close[0]], dtype=float)

    osc_buffer: list[float] = []
    strength_raw_series: list[float | None] = []
    trend_strength_series: list[float | None] = []
    filtered_series: list[float] = []

    for i in range(n):
        src = close[i]

        X = F @ X
        P = F @ P @ F.T + Q

        R_adj = R.copy()
        if cfg.model != "standard" and i > 2:
            if cfg.model == "volume_adjusted":
                v1 = max(volume[i - 1], 1e-12)
                v0 = max(volume[i], 1e-12)
                R_adj[0, 0] = R[0, 0] * v1 / min(v1, v0)
            elif cfg.model == "parkinson_adjusted":
                current_range = max(high[i] - low[i], 1e-12)
                previous_range = max(high[i - 1] - low[i - 1], 1e-12)
                parkinson_scaled = 1.0 + current_range / previous_range
                R_adj[0, 0] = R[0, 0] * parkinson_scaled

        S = H @ P @ H.T + R_adj
        K = P @ H.T @ np.linalg.inv(S)
        innovation = src - float((H @ X).item())
        X = X + (K.flatten() * innovation)
        P = (I2 - K @ H) @ P

        estimate = float(X[0])
        oscillator = float(X[1])
        filtered_series.append(estimate)

        osc_buffer.append(oscillator)
        if len(osc_buffer) > cfg.trend_lookback:
            osc_buffer.pop(0)

        if len(osc_buffer) >= cfg.trend_lookback:
            A = max(abs(x) for x in osc_buffer) or 1e-12
            strength_raw = oscillator / A * 100.0
        else:
            strength_raw = None

        strength_raw_series.append(strength_raw)
        valid_strengths = [v for v in strength_raw_series if v is not None]
        ts = _wma_last(valid_strengths, cfg.strength_smoothness)
        trend_strength_series.append(ts)

    valid_trend = [v for v in trend_strength_series if v is not None]
    trend_strength = valid_trend[-1] if valid_trend else None
    prev_trend = valid_trend[-2] if len(valid_trend) >= 2 else None
    osc_smoothed = _wma_last(valid_trend, cfg.osc_smoothness)

    if trend_strength is None or osc_smoothed is None:
        return {}

    reversal: str | None = None
    if prev_trend is not None:
        if prev_trend < 0 <= trend_strength:
            reversal = "bullish"
        elif prev_trend > 0 >= trend_strength:
            reversal = "bearish"
        elif prev_trend < cfg.os_threshold and trend_strength > prev_trend:
            reversal = "bullish"
        elif prev_trend > cfg.ob_threshold and trend_strength < prev_trend:
            reversal = "bearish"

    if osc_smoothed > 0:
        signal = "bullish"
    elif osc_smoothed < 0:
        signal = "bearish"
    else:
        signal = "neutral"

    if trend_strength >= cfg.ob_threshold:
        zone = "overbought"
    elif trend_strength <= cfg.os_threshold:
        zone = "oversold"
    else:
        zone = "neutral"

    last_close = float(close[-1])
    filtered = filtered_series[-1]
    price_vs_kalman = "above" if last_close > filtered else "below" if last_close < filtered else "at"

    return {
        "kalman_filtered_price": round(filtered, 6),
        "kalman_trend_strength": round(osc_smoothed, 2),
        "kalman_trend_strength_raw": round(trend_strength, 2),
        "kalman_signal": signal,
        "kalman_reversal": reversal,
        "kalman_zone": zone,
        "kalman_price_position": price_vs_kalman,
    }
