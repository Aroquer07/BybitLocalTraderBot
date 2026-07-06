"""Testes do pipeline modular de estratégias."""

from src.config.runtime_config import BotRuntimeConfig, ScannerQualityConfig
from src.config.strategy_config import (
    ScannerPipelineConfig,
    effective_scanner_quality,
)


def test_autonomous_mode_disables_llm():
    pipeline = ScannerPipelineConfig(mode="autonomous", llm=True)
    assert pipeline.llm is False


def test_llm_assisted_mode_enables_llm():
    pipeline = ScannerPipelineConfig(mode="llm_assisted", llm=False)
    assert pipeline.llm is True


def test_effective_scanner_quality_relaxes_pattern_and_kalman():
    quality = ScannerQualityConfig(
        require_market_pattern=True,
        require_kalman_align=True,
        reject_kalman_reversal_against=True,
    )
    pipeline = ScannerPipelineConfig(
        market_patterns=False,
        kalman_hard_block=False,
    )
    effective = effective_scanner_quality(quality, pipeline)
    assert effective.require_market_pattern is False
    assert effective.require_kalman_align is False
    assert effective.reject_kalman_reversal_against is False


def test_runtime_loads_strategies_from_defaults():
    runtime = BotRuntimeConfig()
    assert runtime.strategies.scanner.entry_strategy == "combined"
    assert runtime.strategies.scanner.mode == "autonomous"
    assert runtime.strategies.scanner.llm is False
    assert runtime.strategies.scanner.indicators.trend_speed is True
    assert runtime.strategies.telegram.llm is True
