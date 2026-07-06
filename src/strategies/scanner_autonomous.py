"""Decisão do scanner autônomo — sem LLM, baseada em regras Python."""

from __future__ import annotations

from src.config.runtime_config import BotRuntimeConfig
from src.models.schemas import (
    ImbaAnalysis,
    MarketState,
    TradeDecision,
    TradeDirection,
    TradeSource,
    TradeStyle,
)


def suggest_leverage(
    imba_score: float,
    confluence_score: int,
    runtime: BotRuntimeConfig,
) -> int:
    """Alavancagem proporcional à força do setup (sem LLM)."""
    risk = runtime.risk
    strength = imba_score * 0.6 + (confluence_score / 100.0) * 0.4
    if strength >= 0.80:
        lev = risk.max_leverage
    elif strength >= 0.65:
        lev = int((risk.min_leverage + risk.max_leverage) / 2)
    else:
        lev = risk.min_leverage
    return max(risk.min_leverage, min(lev, risk.max_leverage))


def build_sniper_scanner_decision(
    *,
    symbol: str,
    signal: "CombinedSignal",
    runtime: BotRuntimeConfig,
    confluence_score: int = 70,
) -> TradeDecision:
    """Decisão do scanner Sniper + Breakout (níveis ATR do indicador)."""
    from src.strategies.indicator_modules.base import CombinedSignal

    direction = (
        TradeDirection.LONG if signal.direction == "LONG" else TradeDirection.SHORT
    )
    modules = ", ".join(signal.modules)
    bias = f"{direction.value} SNIPER | {modules} | {signal.summary}"

    lev = suggest_leverage(signal.confidence, confluence_score, runtime)
    if signal.confidence < 0.88:
        lev = min(lev, 20)

    return TradeDecision(
        approved=True,
        confidence=signal.confidence,
        confidence_threshold=runtime.confidence.scanner,
        direction=direction,
        symbol=symbol,
        entry_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        leverage=lev,
        bias=bias,
        ai_analysis="Sniper Entry + Breakout Probability (≥60%)",
        trade_style=TradeStyle.DAYTRADE,
        trade_style_label="DAYTRADE",
        source=TradeSource.SCANNER,
        tp_sl_quality=f"Níveis Sniper ATR TF {runtime.timeframes.execution}",
    )


def build_combined_scanner_decision(
    *,
    symbol: str,
    signal: "CombinedSignal",
    runtime: BotRuntimeConfig,
    confluence_score: int = 70,
) -> TradeDecision:
    """Decisão do scanner com indicadores combinados + SMC."""
    from src.strategies.indicator_modules.base import CombinedSignal

    direction = (
        TradeDirection.LONG if signal.direction == "LONG" else TradeDirection.SHORT
    )
    smc_note = "SMC" if runtime.strategies.scanner.smc and runtime.smc.enabled else "ATR"
    modules = ", ".join(signal.modules)
    bias = f"{direction.value} {signal.regime.upper()} | {modules} | {signal.summary}"

    lev = suggest_leverage(signal.confidence, confluence_score, runtime)
    if signal.confidence < 0.88:
        lev = min(lev, 20)

    return TradeDecision(
        approved=True,
        confidence=signal.confidence,
        confidence_threshold=runtime.confidence.scanner,
        direction=direction,
        symbol=symbol,
        entry_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        leverage=lev,
        bias=bias,
        ai_analysis=f"Combined [{modules}] + {smc_note}",
        trade_style=TradeStyle.DAYTRADE,
        trade_style_label="DAYTRADE",
        source=TradeSource.SCANNER,
        tp_sl_quality=f"Níveis {smc_note} TF {runtime.timeframes.execution}",
    )


def synthetic_imba_analysis(symbol: str, signal: "CombinedSignal") -> ImbaAnalysis:
    """Compatibilidade P(win) sem pipeline IMBA."""
    from src.strategies.indicator_modules.base import CombinedSignal

    direction = (
        TradeDirection.LONG if signal.direction == "LONG" else TradeDirection.SHORT
    )
    return ImbaAnalysis(
        symbol=symbol,
        aligned_direction=direction,
        fresh_signal_direction=direction,
        confidence_score=signal.confidence,
        summary=signal.summary,
    )


def build_autonomous_scanner_decision(
    *,
    symbol: str,
    direction: TradeDirection,
    analysis: ImbaAnalysis,
    market_state: MarketState,
    imba_signal,
    runtime: BotRuntimeConfig,
) -> TradeDecision:
    """
    Monta decisão com níveis IMBA/SMC — P(win) e learning fazem o gate final.
    """
    conf = market_state.confluence
    if direction == TradeDirection.LONG:
        conf_score = conf.long_score if conf else 0
    else:
        conf_score = conf.short_score if conf else 0

    leverage = suggest_leverage(analysis.confidence_score, conf_score, runtime)
    smc_note = "SMC" if runtime.strategies.scanner.smc and runtime.smc.enabled else "IMBA"
    bias = (
        f"{direction.value} {smc_note} | score IMBA {analysis.confidence_score:.0%} "
        f"| conf {conf_score} | {analysis.summary}"
    )

    return TradeDecision(
        approved=True,
        confidence=analysis.confidence_score,
        confidence_threshold=runtime.confidence.scanner,
        direction=direction,
        symbol=symbol,
        entry_price=imba_signal.entry_price,
        stop_loss=imba_signal.stop_loss,
        leverage=leverage,
        bias=bias,
        ai_analysis="Scanner autônomo — regras Python + P(win)",
        trade_style=TradeStyle.DAYTRADE,
        trade_style_label="DAYTRADE",
        source=TradeSource.SCANNER,
        tp_sl_quality=f"Níveis {smc_note} TF {runtime.timeframes.execution}",
    )
