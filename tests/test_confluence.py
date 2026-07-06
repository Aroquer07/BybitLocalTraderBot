"""Testes unitários para scoring de confluência."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.models.schemas import ConfluenceResult, MarketState, TimeframeSnapshot
from src.strategies.confluence import compute_confluence, score_long, score_short


def _bullish_indicators(last_price: float = 110.0) -> dict:
    return {
        "ema_7": 105.0,
        "ema_14": 103.0,
        "ema_28": 100.0,
        "sma_7": 104.0,
        "sma_14": 102.0,
        "sma_28": 99.0,
        "vwap": 100.0,
        "macd_cross": "bullish",
        "macd_momentum": "increasing",
        "macd_histogram": 0.5,
        "rsi_12": 58.0,
        "rsi_zone": "neutral",
        "bb_position": "above_upper",
        "bb_squeeze": False,
        "ichimoku_above_cloud": True,
        "ichimoku_tk_cross": "bullish",
        "supertrend_direction": "bullish",
        "adx_14": 30.0,
        "trend": "bullish",
        "kalman_trend_strength": 42.0,
        "kalman_signal": "bullish",
        "kalman_reversal": "bullish",
        "_last_price": last_price,
        "_volume_ratio": 1.5,
    }


def _bearish_indicators(last_price: float = 90.0) -> dict:
    return {
        "ema_7": 95.0,
        "ema_14": 97.0,
        "ema_28": 100.0,
        "sma_7": 96.0,
        "sma_14": 98.0,
        "sma_28": 101.0,
        "vwap": 100.0,
        "macd_cross": "bearish",
        "macd_momentum": "decreasing",
        "macd_histogram": -0.5,
        "rsi_12": 42.0,
        "rsi_zone": "neutral",
        "bb_position": "below_lower",
        "bb_squeeze": False,
        "ichimoku_below_cloud": True,
        "ichimoku_tk_cross": "bearish",
        "supertrend_direction": "bearish",
        "adx_14": 28.0,
        "trend": "bearish",
        "kalman_trend_strength": -38.0,
        "kalman_signal": "bearish",
        "kalman_reversal": "bearish",
        "_last_price": last_price,
        "_volume_ratio": 1.3,
    }


def _make_market_state(
    primary: dict,
    trend: dict | None = None,
) -> MarketState:
    trend_ind = trend or primary
    snapshot = TimeframeSnapshot(
        indicators=primary,
        fibonacci={"impulse": "bullish"},
        ohlcv_summary={"volume_ratio": primary.get("_volume_ratio", 1.0)},
    )
    trend_snapshot = TimeframeSnapshot(
        indicators=trend_ind,
        fibonacci={},
        ohlcv_summary={},
    )
    return MarketState(
        symbol="BTC/USDT",
        timeframe="15m",
        last_price=primary.get("_last_price", 100.0),
        timestamp=datetime.now(timezone.utc),
        timeframes={
            "5m": snapshot,
            "15m": snapshot,
            "30m": trend_snapshot,
        },
    )


class TestConfluence:
    def test_bullish_long_score_high(self) -> None:
        state = _make_market_state(_bullish_indicators())
        result = score_long(state)
        assert result.score >= 70
        assert result.checks.above_ema_ma is True
        assert result.checks.macd_bullish is True

    def test_bearish_short_score_high(self) -> None:
        state = _make_market_state(_bearish_indicators())
        result = score_short(state)
        assert result.score >= 70
        assert result.checks.above_ema_ma is True
        assert result.checks.macd_bullish is True

    def test_isolated_indicator_low_score(self) -> None:
        """Um único check verdadeiro não deve gerar score alto."""
        ind = {
            "ema_7": 50.0,
            "ema_14": 60.0,
            "sma_7": 55.0,
            "sma_14": 65.0,
            "vwap": 100.0,
            "macd_cross": "bullish",
            "rsi_12": 40.0,
            "trend": "neutral",
            "_last_price": 45.0,
            "_volume_ratio": 0.8,
        }
        state = _make_market_state(ind)
        result = score_long(state)
        assert result.score <= 30

    def test_compute_confluence_recommendation_long(self) -> None:
        state = _make_market_state(_bullish_indicators())
        conf = compute_confluence(state)
        assert isinstance(conf, ConfluenceResult)
        assert conf.long_score > conf.short_score
        assert conf.recommendation == "LONG"

    def test_compute_confluence_recommendation_short(self) -> None:
        state = _make_market_state(_bearish_indicators())
        conf = compute_confluence(state)
        assert conf.short_score > conf.long_score
        assert conf.recommendation == "SHORT"

    def test_neutral_when_scores_close(self) -> None:
        neutral = {
            "ema_7": 100.0,
            "ema_14": 100.0,
            "sma_7": 100.0,
            "sma_14": 100.0,
            "vwap": 100.0,
            "rsi_12": 50.0,
            "trend": "neutral",
            "_last_price": 100.0,
            "_volume_ratio": 1.0,
        }
        state = _make_market_state(neutral)
        conf = compute_confluence(state)
        assert conf.recommendation == "NEUTRAL"
