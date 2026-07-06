"""Testes unitários para cálculo de níveis Fibonacci."""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategies.technical_analysis import compute_fibonacci_levels


def _make_df(
    lows: list[float],
    highs: list[float],
    closes: list[float] | None = None,
) -> pd.DataFrame:
    n = len(lows)
    if closes is None:
        closes = [(l + h) / 2 for l, h in zip(lows, highs)]
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC"),
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [100.0] * n,
        }
    )


class TestComputeFibonacciLevels:
    def test_bullish_impulse_known_levels(self) -> None:
        """Swing low=100, high=200 → retrações e extensões conhecidas."""
        lows = [100.0] * 5 + [150.0] * 5
        highs = [120.0] * 5 + [200.0] * 5
        df = _make_df(lows, highs)

        result = compute_fibonacci_levels(
            df,
            lookback=10,
            reference_entry=180.0,
            reference_sl=100.0,
            trend="bullish",
        )

        assert result["swing_low"] == pytest.approx(100.0)
        assert result["swing_high"] == pytest.approx(200.0)
        assert result["range"] == pytest.approx(100.0)
        assert result["impulse"] == "bullish"

        assert result["retracements"]["0.618"] == pytest.approx(138.2)
        assert result["retracements"]["0.5"] == pytest.approx(150.0)
        assert result["extensions"]["1.618"] == pytest.approx(261.8)
        assert result["extensions"]["2.0"] == pytest.approx(300.0)

    def test_bearish_impulse_known_levels(self) -> None:
        """Swing high=200, low=100 em impulso bearish."""
        highs = [200.0] * 5 + [150.0] * 5
        lows = [180.0] * 5 + [100.0] * 5
        df = _make_df(lows, highs)

        result = compute_fibonacci_levels(
            df,
            lookback=10,
            reference_entry=120.0,
            reference_sl=200.0,
            trend="bearish",
        )

        assert result["impulse"] == "bearish"
        assert result["retracements"]["0.618"] == pytest.approx(161.8)
        assert result["extensions"]["1.618"] == pytest.approx(138.2)
        assert result["extensions"]["2.0"] == pytest.approx(100.0)

    def test_risk_reward_extensions(self) -> None:
        lows = [100.0] * 5 + [150.0] * 5
        highs = [120.0] * 5 + [200.0] * 5
        df = _make_df(lows, highs)

        result = compute_fibonacci_levels(
            df,
            lookback=10,
            reference_entry=150.0,
            reference_sl=100.0,
            trend="bullish",
        )

        # TP 1.618 = 261.8, reward=111.8, risk=50 → RR≈2.236
        assert result["risk_reward_extensions"]["1.618"] == pytest.approx(2.236, rel=0.01)

    def test_empty_df_returns_empty(self) -> None:
        df = pd.DataFrame()
        assert compute_fibonacci_levels(df) == {}

    def test_zero_range_returns_neutral(self) -> None:
        df = _make_df([100.0] * 5, [100.0] * 5)
        result = compute_fibonacci_levels(df, lookback=5)
        assert result["impulse"] == "neutral"
        assert result["range"] == 0.0
