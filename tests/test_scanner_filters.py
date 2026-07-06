"""Testes dos filtros objetivos do scanner."""

from __future__ import annotations

import pytest

from src.config.runtime_config import ScannerQualityConfig
from src.models.schemas import (
    ConfluenceResult,
    ImbaAnalysis,
    MarketState,
    TimeframeSnapshot,
    TradeDirection,
    TradeSource,
)
from src.strategies.imba_algo import ImbaSignal
from src.strategies.scanner_filters import (
    effective_pwin_threshold,
    evaluate_scanner_setup,
)
from src.strategies.win_probability import ProbabilityFeatures, WinProbabilityResult


def _filters() -> ScannerQualityConfig:
    return ScannerQualityConfig()


def _analysis(**kwargs) -> ImbaAnalysis:
    base = dict(
        symbol="BTC/USDT",
        confidence_score=0.62,
        aligned_direction=TradeDirection.LONG,
        fresh_signal_direction=TradeDirection.LONG,
    )
    base.update(kwargs)
    return ImbaAnalysis(**base)


def _market(**kwargs) -> MarketState:
    conf = kwargs.pop("confluence", None) or ConfluenceResult(
        long_score=72,
        short_score=28,
        long_checks={},
        short_checks={},
        recommendation="LONG",
    )
    indicators = kwargs.pop(
        "indicators",
        {
            "atr_14": 1.2,
            "kalman_signal": "bullish",
            "market_patterns": [
                {
                    "name": "bullish_engulfing",
                    "direction": "LONG",
                    "historical_winrate": 0.82,
                    "confidence": 0.78,
                    "description": "test",
                }
            ],
        },
    )
    return MarketState(
        symbol="BTC/USDT",
        timeframe="15m",
        last_price=100.0,
        confluence=conf,
        timeframes={
            "15m": TimeframeSnapshot(indicators=indicators),
            "5m": TimeframeSnapshot(
                ohlcv_summary={"volume_ratio": 1.2},
            ),
        },
        **kwargs,
    )


def _signal(
    entry: float = 100.0,
    sl: float = 98.0,
    tp1: float = 102.5,
) -> ImbaSignal:
    return ImbaSignal(
        side="LONG",
        entry_price=entry,
        stop_loss=sl,
        take_profits=(tp1, 103.0, 104.0),
    )


class TestEvaluateScannerSetup:
    def test_passes_strong_setup(self) -> None:
        verdict = evaluate_scanner_setup(
            direction=TradeDirection.LONG,
            analysis=_analysis(),
            imba_signal=_signal(),
            market_state=_market(),
            filters=_filters(),
        )
        assert verdict.passed

    def test_rejects_low_imba_score(self) -> None:
        verdict = evaluate_scanner_setup(
            direction=TradeDirection.LONG,
            analysis=_analysis(confidence_score=0.48),
            imba_signal=_signal(),
            market_state=_market(),
            filters=_filters(),
        )
        assert not verdict.passed
        assert "Setup score" in verdict.reason

    def test_rejects_confluence_mismatch(self) -> None:
        conf = ConfluenceResult(
            long_score=40,
            short_score=70,
            long_checks={},
            short_checks={},
            recommendation="SHORT",
        )
        verdict = evaluate_scanner_setup(
            direction=TradeDirection.LONG,
            analysis=_analysis(),
            imba_signal=_signal(),
            market_state=_market(confluence=conf),
            filters=_filters(),
        )
        assert not verdict.passed
        assert "Confluência SHORT" in verdict.reason

    def test_rejects_low_tp1_rr(self) -> None:
        verdict = evaluate_scanner_setup(
            direction=TradeDirection.LONG,
            analysis=_analysis(),
            imba_signal=_signal(tp1=101.0),
            market_state=_market(),
            filters=_filters(),
        )
        assert not verdict.passed
        assert "TP1 R:R" in verdict.reason

    def test_rejects_kalman_against_direction(self) -> None:
        verdict = evaluate_scanner_setup(
            direction=TradeDirection.LONG,
            analysis=_analysis(),
            imba_signal=_signal(),
            market_state=_market(indicators={"atr_14": 1.2, "kalman_signal": "bearish"}),
            filters=_filters(),
        )
        assert not verdict.passed
        assert "Kalman" in verdict.reason

    def test_rejects_without_chart_pattern(self) -> None:
        verdict = evaluate_scanner_setup(
            direction=TradeDirection.LONG,
            analysis=_analysis(),
            imba_signal=_signal(),
            market_state=_market(indicators={"atr_14": 1.2, "kalman_signal": "bullish"}),
            filters=_filters(),
        )
        assert not verdict.passed
        assert "padrão" in verdict.reason.lower()


class TestEffectivePwinThreshold:
    def test_bumps_low_reliability(self) -> None:
        feat = ProbabilityFeatures(
            imba_score=0.7,
            confluence_score=70,
            volume_ratio=1.0,
            spread_pct=0.05,
            ob_imbalance=0.1,
            atr_pct=1.0,
            tp1_rr=1.2,
            sl_atr_multiple=1.0,
            direction=TradeDirection.LONG,
            source=TradeSource.SCANNER,
            symbol="BTC/USDT",
        )
        result = WinProbabilityResult(
            probability=0.74,
            technical=0.7,
            market=0.7,
            setup=0.7,
            historical=0.5,
            historical_n=2,
            reliability="low",
            breakdown="test",
            features=feat,
        )
        thr = effective_pwin_threshold(result, 0.72, _filters())
        assert thr == pytest.approx(0.79)

    def test_no_bump_high_reliability(self) -> None:
        feat = ProbabilityFeatures(
            imba_score=0.8,
            confluence_score=75,
            volume_ratio=1.2,
            spread_pct=0.04,
            ob_imbalance=0.15,
            atr_pct=0.9,
            tp1_rr=1.5,
            sl_atr_multiple=1.0,
            direction=TradeDirection.LONG,
            source=TradeSource.SCANNER,
            symbol="BTC/USDT",
        )
        result = WinProbabilityResult(
            probability=0.80,
            technical=0.8,
            market=0.8,
            setup=0.8,
            historical=0.7,
            historical_n=20,
            reliability="high",
            breakdown="test",
            features=feat,
        )
        thr = effective_pwin_threshold(result, 0.72, _filters())
        assert thr == 0.72

    def test_bumps_bad_historical_bucket(self) -> None:
        feat = ProbabilityFeatures(
            imba_score=0.8,
            confluence_score=75,
            volume_ratio=1.2,
            spread_pct=0.04,
            ob_imbalance=0.15,
            atr_pct=0.9,
            tp1_rr=1.5,
            sl_atr_multiple=1.0,
            direction=TradeDirection.LONG,
            source=TradeSource.SCANNER,
            symbol="BTC/USDT",
        )
        result = WinProbabilityResult(
            probability=0.80,
            technical=0.8,
            market=0.8,
            setup=0.8,
            historical=0.40,
            historical_n=4,
            reliability="low",
            breakdown="test",
            features=feat,
        )
        thr = effective_pwin_threshold(result, 0.82, _filters())
        assert thr == pytest.approx(0.89)
