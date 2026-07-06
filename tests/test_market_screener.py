"""Testes do screener — confluência RSI Heatmap + Visual Screener."""

from __future__ import annotations

import pandas as pd

from src.config.runtime_config import ScreenerConfig
from src.strategies.market_screener import (
    classify_rsi_bias,
    compute_rsi_last,
    detect_derivative_flow,
    evaluate_screener_setup,
    rsi_map_from_ohlcv,
)


def _synthetic_ohlcv(closes: list[float]) -> list[list[float]]:
    rows: list[list[float]] = []
    for i, close in enumerate(closes):
        rows.append([i * 60_000, close, close + 1, close - 1, close, 100.0])
    return rows


class TestComputeRsi:
    def test_rsi_range(self) -> None:
        closes = pd.Series([float(50 + (i % 5)) for i in range(40)])
        rsi = compute_rsi_last(closes, period=14)
        assert rsi is not None
        assert 0 <= rsi <= 100


class TestClassifyRsiBias:
    def test_overbought_with_rollover(self) -> None:
        bias, detail = classify_rsi_bias(
            {"15m": 68.0, "1h": 72.0, "4h": 74.0},
            ScreenerConfig(),
        )
        assert bias == "overbought"
        assert "overbought" in detail.lower()

    def test_oversold_with_recovery(self) -> None:
        bias, _ = classify_rsi_bias(
            {"15m": 32.0, "1h": 28.0, "4h": 26.0},
            ScreenerConfig(),
        )
        assert bias == "oversold"

    def test_neutral_mid_range(self) -> None:
        bias, _ = classify_rsi_bias(
            {"15m": 50.0, "1h": 50.0, "4h": 50.0},
            ScreenerConfig(),
        )
        assert bias is None


class TestDetectDerivativeFlow:
    def test_shorts_entering_oi_and_weak_price(self) -> None:
        flow, detail = detect_derivative_flow(
            funding_rate=0.0001,
            oi_change_pct=5.0,
            price_change_24h_pct=-2.0,
            sell_ratio_delta=None,
            buy_ratio_delta=None,
            config=ScreenerConfig(),
        )
        assert flow == "shorts_entering"
        assert "OI" in detail

    def test_shorts_entering_sell_ratio_rising(self) -> None:
        flow, detail = detect_derivative_flow(
            funding_rate=0.0,
            oi_change_pct=None,
            price_change_24h_pct=0.0,
            sell_ratio_delta=0.03,
            buy_ratio_delta=None,
            config=ScreenerConfig(),
        )
        assert flow == "shorts_entering"
        assert "shorts entering" in detail.lower()

    def test_longs_entering_funding_squeeze(self) -> None:
        flow, _ = detect_derivative_flow(
            funding_rate=-0.0005,
            oi_change_pct=None,
            price_change_24h_pct=1.0,
            sell_ratio_delta=None,
            buy_ratio_delta=None,
            config=ScreenerConfig(),
        )
        assert flow == "longs_entering"


class TestConfluence:
    def test_ltc_style_short_overbought_plus_shorts_entering(self) -> None:
        """Exemplo do usuário: LTC overbought + shorts entering = SHORT."""
        cfg = ScreenerConfig()
        hit = evaluate_screener_setup(
            "LTC/USDT",
            {"15m": 68.0, "1h": 72.0, "4h": 74.0, "1d": 71.0},
            funding_rate=0.0004,
            turnover_24h=2_000_000,
            price_change_24h_pct=-0.5,
            oi_change_pct=4.0,
            sell_ratio=0.55,
            sell_ratio_delta=0.03,
            buy_ratio_delta=None,
            config=cfg,
        )
        assert hit is not None
        assert hit.direction == "SHORT"
        assert hit.rsi_bias == "overbought"
        assert hit.derivative_flow == "shorts_entering"
        assert "CONFLUÊNCIA" in hit.reason

    def test_long_oversold_plus_longs_entering(self) -> None:
        cfg = ScreenerConfig()
        hit = evaluate_screener_setup(
            "SOL/USDT",
            {"15m": 32.0, "1h": 28.0, "4h": 26.0},
            funding_rate=-0.0004,
            turnover_24h=1_000_000,
            price_change_24h_pct=3.0,
            oi_change_pct=5.0,
            sell_ratio_delta=None,
            buy_ratio_delta=0.04,
            config=cfg,
        )
        assert hit is not None
        assert hit.direction == "LONG"
        assert hit.rsi_bias == "oversold"
        assert hit.derivative_flow == "longs_entering"

    def test_overbought_without_derivatives_rejected(self) -> None:
        cfg = ScreenerConfig(require_confluence=True)
        hit = evaluate_screener_setup(
            "BTC/USDT",
            {"15m": 68.0, "1h": 72.0, "4h": 74.0},
            funding_rate=0.00005,
            turnover_24h=5_000_000,
            price_change_24h_pct=2.0,
            oi_change_pct=None,
            sell_ratio_delta=None,
            buy_ratio_delta=None,
            config=cfg,
        )
        assert hit is None

    def test_shorts_entering_without_overbought_rejected(self) -> None:
        cfg = ScreenerConfig(require_confluence=True)
        hit = evaluate_screener_setup(
            "ETH/USDT",
            {"15m": 50.0, "1h": 52.0, "4h": 48.0},
            funding_rate=0.0005,
            turnover_24h=5_000_000,
            price_change_24h_pct=-1.0,
            oi_change_pct=5.0,
            sell_ratio_delta=0.05,
            buy_ratio_delta=None,
            config=cfg,
        )
        assert hit is None


class TestRsiMapFromOhlcv:
    def test_builds_map_per_tf(self) -> None:
        uptrend = [float(100 + i) for i in range(40)]
        ohlcv = {"15m": _synthetic_ohlcv(uptrend)}
        result = rsi_map_from_ohlcv(ohlcv, period=14)
        assert "15m" in result
        assert result["15m"] > 50
