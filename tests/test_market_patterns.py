"""Testes de detecção de padrões clássicos de price action."""

from __future__ import annotations

import pandas as pd

from src.models.schemas import TradeDirection
from src.strategies.market_patterns import (
    best_pattern_for_direction,
    detect_market_patterns,
)


def _df(rows: list[tuple[float, float, float, float, float]]) -> pd.DataFrame:
    data = []
    for i, (o, h, l, c, v) in enumerate(rows):
        data.append([i * 60_000, o, h, l, c, v])
    return pd.DataFrame(
        data,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )


class TestDetectMarketPatterns:
    def test_bullish_engulfing(self) -> None:
        base = [(100, 101, 99, 100, 1000.0)] * 10
        base.append((100.5, 101, 99.5, 99.8, 900.0))  # bearish
        base.append((99.5, 102, 99, 101.5, 1500.0))  # bullish engulf
        patterns = detect_market_patterns(_df(base))
        names = {p.name for p in patterns}
        assert "bullish_engulfing" in names

    def test_hammer_at_low(self) -> None:
        rows = [(100, 101, 99, 100, 1000.0)] * 9
        rows.append((99.9, 100.0, 95, 100.0, 1200.0))  # martelo no fundo
        patterns = detect_market_patterns(_df(rows))
        assert any(p.name == "hammer" for p in patterns)

    def test_best_pattern_filters_by_winrate(self) -> None:
        from src.strategies.market_patterns import PatternMatch

        patterns = [
            PatternMatch("weak", "LONG", 0.70, 0.90, "weak"),
            PatternMatch("bullish_engulfing", "LONG", 0.82, 0.75, "strong"),
        ]
        best = best_pattern_for_direction(
            patterns,
            TradeDirection.LONG,
            min_historical_winrate=0.80,
            min_confidence=0.65,
        )
        assert best is not None
        assert best.name == "bullish_engulfing"
