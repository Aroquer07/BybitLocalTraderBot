"""Smoke tests para arsenal de indicadores."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategies.indicators import compute_indicators, ohlcv_to_dataframe

BASE_KEYS = {
    "rsi_6",
    "rsi_12",
    "rsi_24",
    "macd",
    "macd_signal",
    "macd_histogram",
    "sma_7",
    "sma_14",
    "sma_28",
    "ema_7",
    "ema_14",
    "ema_28",
    "volume_ma_5",
    "volume_ma_10",
    "bb_lower",
    "bb_middle",
    "bb_upper",
    "atr_14",
}

PRO_KEYS = {
    "stochrsi_k",
    "obv",
    "adx_14",
    "supertrend_direction",
    "vwap",
    "ichimoku_tenkan",
    "ichimoku_kijun",
    "divergences",
}


def _synthetic_ohlcv(n: int = 120) -> list[list[float]]:
    rng = np.random.default_rng(42)
    base = 100.0
    rows: list[list[float]] = []
    ts = 1_700_000_000_000
    for i in range(n):
        o = base + rng.normal(0, 0.5)
        h = o + abs(rng.normal(0, 0.3))
        l = o - abs(rng.normal(0, 0.3))
        c = o + rng.normal(0, 0.2)
        v = abs(rng.normal(1000, 200))
        rows.append([ts + i * 300_000, o, h, l, c, v])
        base = c
    return rows


class TestIndicators:
    def test_ohlcv_to_dataframe(self) -> None:
        df = ohlcv_to_dataframe(_synthetic_ohlcv(10))
        assert len(df) == 10
        assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]

    def test_base_indicator_keys_present(self) -> None:
        df = ohlcv_to_dataframe(_synthetic_ohlcv(120))
        result = compute_indicators(df)
        missing_base = BASE_KEYS - set(result.keys())
        assert not missing_base, f"Chaves base ausentes: {missing_base}"

    def test_pro_indicator_keys_present(self) -> None:
        df = ohlcv_to_dataframe(_synthetic_ohlcv(120))
        result = compute_indicators(df)
        missing_pro = PRO_KEYS - set(result.keys())
        assert not missing_pro, f"Chaves PRO ausentes: {missing_pro}"

    def test_divergences_structure(self) -> None:
        df = ohlcv_to_dataframe(_synthetic_ohlcv(120))
        result = compute_indicators(df)
        div = result.get("divergences", {})
        assert "rsi_divergence" in div
        assert "macd_divergence" in div

    def test_empty_df_returns_empty(self) -> None:
        assert compute_indicators(pd.DataFrame()) == {}
