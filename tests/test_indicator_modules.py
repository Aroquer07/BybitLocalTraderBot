"""Testes dos indicadores combináveis."""

from __future__ import annotations

import numpy as np

from src.config.strategy_config import IndicatorModulesConfig
from src.strategies.indicator_modules.combined import evaluate_combined_setup
from src.strategies.indicator_modules.range_detector import evaluate_range_detector
from src.strategies.indicator_modules.sniper_entry import (
    SNIPER_TP_RR_MULTIPLIERS,
    evaluate_sniper_entry,
)
from src.strategies.indicator_modules.trend_speed import evaluate_trend_speed
from src.strategies.market_screener import classify_trend_bias, evaluate_screener_trend
from src.config.runtime_config import ScreenerConfig


def _synthetic_ohlcv(n: int = 120, trend: float = 0.001) -> list[list[float]]:
    """Gera OHLCV sintético com tendência leve."""
    base = 100.0
    out: list[list[float]] = []
    ts = 1_700_000_000_000
    for i in range(n):
        c = base * (1 + trend * i) + np.sin(i / 5) * 0.3
        o = c - 0.1
        h = c + 0.2
        l = c - 0.2
        v = 1000 + i * 10
        out.append([ts + i * 300_000, o, h, l, c, v])
    return out


def test_trend_speed_returns_module_result():
    result = evaluate_trend_speed(_synthetic_ohlcv())
    assert result.name == "trend_speed"
    assert isinstance(result.triggered, bool)


def test_range_detector_returns_module_result():
    result = evaluate_range_detector(_synthetic_ohlcv(trend=0.0001))
    assert result.name == "range_detector"
    assert result.regime == "range"


def test_sniper_entry_returns_module_result():
    result = evaluate_sniper_entry(_synthetic_ohlcv())
    assert result.name == "sniper"


def test_sniper_tp1_rr_at_least_1_2():
    ohlcv = _synthetic_ohlcv(trend=0.003)
    result = evaluate_sniper_entry(ohlcv, entry_mode="cross", min_score_pct=0.0)
    if not result.triggered or result.entry_price is None or result.stop_loss is None:
        return
    risk = abs(result.entry_price - result.stop_loss)
    assert risk > 0
    tp1_rr = abs(result.take_profits[0] - result.entry_price) / risk
    assert tp1_rr >= SNIPER_TP_RR_MULTIPLIERS[0] - 1e-9
    assert len(result.take_profits) == 3


def test_combined_setup_respects_screener_bias():
    ohlcv = _synthetic_ohlcv()
    config = IndicatorModulesConfig(
        trend_speed=True,
        range_detector=False,
        sniper=False,
        require_all=False,
    )
    signal, _ = evaluate_combined_setup(ohlcv, config=config, screener_bias="SHORT")
    assert signal is None or signal.direction == "SHORT"


def test_trend_speed_screener_aligned_has_levels():
    ohlcv = _synthetic_ohlcv(trend=0.002)
    result = evaluate_trend_speed(
        ohlcv,
        screener_bias="LONG",
        allow_without_pullback=True,
    )
    if result.triggered and result.direction == "LONG":
        assert result.stop_loss is not None
        assert result.entry_price is not None
        assert len(result.take_profits) == 3


def test_combined_passes_with_screener_trend_without_sniper():
    ohlcv = _synthetic_ohlcv(trend=0.003)
    config = IndicatorModulesConfig(
        trend_speed=True,
        range_detector=False,
        sniper=False,
        sniper_required=False,
        allow_trend_without_pullback=True,
    )
    signal, mods = evaluate_combined_setup(
        ohlcv,
        config=config,
        screener_bias="LONG",
    )
    trend = next(m for m in mods if m.name == "trend_speed")
    if trend.triggered:
        assert signal is not None
        assert signal.stop_loss is not None
        assert signal.direction == "LONG"


def test_classify_trend_bias_long():
    cfg = ScreenerConfig()
    bias, detail = classify_trend_bias({"4h": 62, "1h": 58, "15m": 55}, cfg)
    assert bias == "LONG"
    assert "trend UP" in detail


def test_evaluate_screener_trend_mode():
    cfg = ScreenerConfig(mode="trend", require_confluence=False)
    hit = evaluate_screener_trend(
        "BTC/USDT",
        {"4h": 62, "1h": 58, "15m": 55},
        funding_rate=0.0001,
        turnover_24h=1_000_000,
        price_change_24h_pct=2.5,
        config=cfg,
    )
    assert hit is not None
    assert hit.direction == "LONG"
    assert hit.reason.startswith("TREND")
