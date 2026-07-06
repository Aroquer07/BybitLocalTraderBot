"""Testes do motor de probabilidade P(win)."""

from __future__ import annotations

from datetime import datetime, timezone

from src.models.schemas import (
    ConfluenceResult,
    ImbaAnalysis,
    MarketState,
    StoredTrade,
    TakeProfitLevel,
    TimeframeSnapshot,
    TradeDecision,
    TradeDirection,
    TradeSource,
    TradeStatus,
)
from src.strategies.win_probability import (
    ProbabilityFeatures,
    apply_win_probability,
    compute_win_probability,
    enrich_decision_with_win_probability,
    extract_probability_features,
)


def _market_state(symbol: str = "BTC/USDT") -> MarketState:
    return MarketState(
        symbol=symbol,
        timeframe="15m",
        last_price=100.0,
        confluence=ConfluenceResult(
            long_score=72,
            short_score=28,
            long_checks={},
            short_checks={},
            recommendation="LONG",
        ),
        orderbook_snapshot={
            "best_bid": 99.95,
            "best_ask": 100.05,
            "spread": 0.1,
            "imbalance": 0.15,
        },
        timeframes={
            "15m": TimeframeSnapshot(
                indicators={"atr_14": 1.2},
                ohlcv_summary={"volume_ratio": 1.4},
            ),
            "5m": TimeframeSnapshot(
                indicators={},
                ohlcv_summary={"volume_ratio": 1.6},
            ),
        },
    )


def _decision(confidence: float = 0.88) -> TradeDecision:
    return TradeDecision(
        approved=True,
        confidence=confidence,
        direction=TradeDirection.LONG,
        symbol="BTC/USDT",
        entry_price=100.0,
        stop_loss=98.0,
        leverage=20,
        confidence_threshold=0.75,
        take_profits=[
            TakeProfitLevel(price=102.0, percentage=50, risk_reward=1.0),
        ],
        formatted_output="📈 Viés: teste\n📌 Probabilidade: 88%",
    )


class TestWinProbability:
    def test_compute_returns_varied_score(self) -> None:
        features = ProbabilityFeatures(
            imba_score=0.85,
            confluence_score=72,
            volume_ratio=1.5,
            spread_pct=0.04,
            ob_imbalance=0.2,
            atr_pct=0.9,
            tp1_rr=1.2,
            sl_atr_multiple=1.8,
            direction=TradeDirection.LONG,
            source=TradeSource.SCANNER,
            symbol="BTC/USDT",
        )
        result = compute_win_probability(features, closed_trades=[])
        assert 0.45 <= result.probability <= 0.85
        assert result.historical_n == 0
        assert "tec" in result.breakdown

    def test_weak_setup_lowers_probability(self) -> None:
        strong = ProbabilityFeatures(
            imba_score=0.9,
            confluence_score=80,
            volume_ratio=1.5,
            spread_pct=0.03,
            ob_imbalance=0.3,
            atr_pct=0.8,
            tp1_rr=2.0,
            sl_atr_multiple=1.5,
            direction=TradeDirection.LONG,
            source=TradeSource.SCANNER,
            symbol="BTC/USDT",
        )
        weak = strong.model_copy(update={
            "confluence_score": 35,
            "spread_pct": 0.35,
            "volume_ratio": 0.5,
            "tp1_rr": 0.3,
        })
        assert compute_win_probability(strong, []).probability > compute_win_probability(
            weak, []
        ).probability

    def test_historical_calibration(self) -> None:
        features = ProbabilityFeatures(
            imba_score=0.8,
            confluence_score=60,
            volume_ratio=1.2,
            spread_pct=0.05,
            ob_imbalance=0.0,
            atr_pct=1.0,
            tp1_rr=1.0,
            sl_atr_multiple=1.5,
            direction=TradeDirection.LONG,
            source=TradeSource.SCANNER,
            symbol="ETH/USDT",
        )
        closed = [
            StoredTrade(
                id="1",
                symbol="ETH/USDT",
                direction=TradeDirection.LONG,
                source=TradeSource.SCANNER,
                status=TradeStatus.CLOSED,
                entry_price=100,
                stop_loss=98,
                confidence=0.7,
                pnl_pct=2.0,
                probability_features=features.model_dump(),
            ),
            StoredTrade(
                id="2",
                symbol="ETH/USDT",
                direction=TradeDirection.LONG,
                source=TradeSource.SCANNER,
                status=TradeStatus.CLOSED,
                entry_price=100,
                stop_loss=98,
                confidence=0.7,
                pnl_pct=-1.0,
                probability_features=features.model_dump(),
            ),
        ]
        result = compute_win_probability(features, closed)
        assert result.historical_n == 2
        assert 0.4 < result.historical < 0.7

    def test_apply_rejects_below_threshold(self) -> None:
        decision = _decision()
        imba = ImbaAnalysis(symbol="BTC/USDT", confidence_score=0.85)
        features = extract_probability_features(
            decision,
            imba,
            _market_state(),
            source=TradeSource.SCANNER,
        )
        result = compute_win_probability(features, [])
        updated = apply_win_probability(
            decision,
            result,
            confidence_threshold=0.99,
        )
        assert updated.approved is False
        assert updated.llm_confidence == 0.88
        assert "📌 Probabilidade:" in updated.formatted_output
        assert "tec" in (updated.probability_breakdown or {}).get("breakdown", "")

    def test_enrich_preserves_llm_confidence(self) -> None:
        decision = _decision(confidence=0.88).model_copy(update={"llm_confidence": 0.88})
        imba = ImbaAnalysis(symbol="BTC/USDT", confidence_score=0.85)
        enriched = enrich_decision_with_win_probability(
            decision,
            imba,
            _market_state(),
            source=TradeSource.SCANNER,
            confidence_threshold=0.65,
        )
        assert enriched.llm_confidence == 0.88
        assert enriched.probability_breakdown is not None
