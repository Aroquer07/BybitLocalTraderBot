"""Testes do filtro Kalman."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.strategies.indicators import compute_indicators, ohlcv_to_dataframe
from src.strategies.kalman import compute_kalman_indicators


def _synthetic_ohlcv(n: int = 120, trend: float = 0.1) -> pd.DataFrame:
    rows = []
    price = 100.0
    for i in range(n):
        price += trend + np.sin(i / 5) * 0.2
        rows.append([
            i * 60_000,
            price - 0.3,
            price + 0.5,
            price - 0.5,
            price,
            1000.0 + i * 10,
        ])
    return ohlcv_to_dataframe(rows)


class TestKalman:
    def test_returns_strength_and_signal(self) -> None:
        df = _synthetic_ohlcv()
        result = compute_kalman_indicators(df)
        assert "kalman_trend_strength" in result
        assert result["kalman_signal"] in ("bullish", "bearish", "neutral")
        assert result["kalman_zone"] in ("overbought", "oversold", "neutral")

    def test_integrated_in_compute_indicators(self) -> None:
        df = _synthetic_ohlcv()
        indicators = compute_indicators(df)
        assert "kalman_trend_strength" in indicators
        assert "kalman_filtered_price" in indicators

    def test_insufficient_data_returns_empty(self) -> None:
        df = _synthetic_ohlcv(n=10)
        assert compute_kalman_indicators(df) == {}
