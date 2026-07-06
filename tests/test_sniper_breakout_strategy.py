"""Testes Sniper + Breakout Probability."""

from __future__ import annotations

import numpy as np

from src.config.strategy_config import IndicatorModulesConfig
from src.strategies.indicator_modules.breakout_probability import (
    BreakoutOutlook,
    breakout_confirms_direction,
    evaluate_breakout_probability,
)
from src.strategies.indicator_modules.sniper_strategy import evaluate_sniper_setup


def _synthetic_ohlcv(n: int = 120, trend: float = 0.001) -> list[list[float]]:
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


def test_breakout_probability_returns_outlook():
    outlook = evaluate_breakout_probability(_synthetic_ohlcv())
    assert outlook.bias in ("BULLISH", "BEARISH")
    assert 0 <= outlook.probability_pct <= 100
    assert outlook.prev_candle in ("green", "red")


def test_breakout_confirms_direction_long():
    outlook = BreakoutOutlook(
        bias="BULLISH",
        probability_pct=72.0,
        prob_high_pct=72.0,
        prob_low_pct=28.0,
        prev_candle="green",
        reason="test",
    )
    ok, msg = breakout_confirms_direction(outlook, "LONG", min_probability_pct=60.0)
    assert ok
    assert msg


def test_breakout_rejects_low_probability():
    outlook = BreakoutOutlook(
        bias="BULLISH",
        probability_pct=55.0,
        prob_high_pct=55.0,
        prob_low_pct=45.0,
        prev_candle="green",
        reason="test",
    )
    ok, msg = breakout_confirms_direction(outlook, "LONG", min_probability_pct=60.0)
    assert not ok
    assert "60" in msg


def test_breakout_rejects_wrong_bias():
    outlook = BreakoutOutlook(
        bias="BEARISH",
        probability_pct=70.0,
        prob_high_pct=30.0,
        prob_low_pct=70.0,
        prev_candle="red",
        reason="test",
    )
    ok, _ = breakout_confirms_direction(outlook, "LONG", min_probability_pct=60.0)
    assert not ok


def test_sniper_setup_returns_none_without_trigger():
    config = IndicatorModulesConfig(
        min_breakout_probability_pct=60.0,
        min_sniper_score_pct=50.0,
    )
    signal, mods, reject = evaluate_sniper_setup(_synthetic_ohlcv(trend=0.0001), config=config)
    assert signal is None or signal.direction in ("LONG", "SHORT")
    assert any(m.name == "sniper" for m in mods)
    if signal is None:
        assert reject
