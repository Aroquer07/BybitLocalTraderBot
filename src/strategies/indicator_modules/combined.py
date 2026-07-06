"""Orquestra Trend Speed + Range Detector + Sniper com regime de mercado."""

from __future__ import annotations

from src.config.strategy_config import IndicatorModulesConfig
from src.strategies.indicator_modules.base import CombinedSignal, Direction, ModuleResult
from src.strategies.indicator_modules.range_detector import evaluate_range_detector
from src.strategies.indicator_modules.sniper_entry import evaluate_sniper_entry
from src.strategies.indicator_modules.trend_speed import evaluate_trend_speed


def _pick_regime(
    trend: ModuleResult,
    range_: ModuleResult,
    config: IndicatorModulesConfig,
) -> str:
    """Escolhe regime: range ativo tem prioridade se ambos detectam."""
    if config.range_detector and range_.triggered:
        return "range"
    if config.trend_speed and trend.triggered:
        return "trend"
    if config.range_detector and range_.regime == "range" and not trend.triggered:
        return "range"
    return "trend"


def evaluate_combined_setup(
    ohlcv: list[list[float]],
    *,
    ohlcv_htf: list[list[float]] | None = None,
    config: IndicatorModulesConfig,
    screener_bias: Direction | None = None,
) -> tuple[CombinedSignal | None, list[ModuleResult]]:
    """
    Combina módulos habilitados:
    - Regime range → Range Detector
    - Regime trend → Trend Speed Analyzer
    - Sniper confirma todas as condições (se habilitado)
    - screener_bias filtra direção (só escolha de moeda)
    """
    results: list[ModuleResult] = []

    trend = (
        evaluate_trend_speed(
            ohlcv,
            screener_bias=screener_bias,
            allow_without_pullback=config.allow_trend_without_pullback,
        )
        if config.trend_speed
        else ModuleResult("trend_speed", None, 0.0, False, "desabilitado")
    )
    range_ = (
        evaluate_range_detector(ohlcv)
        if config.range_detector
        else ModuleResult("range_detector", None, 0.0, False, "desabilitado")
    )
    sniper = (
        evaluate_sniper_entry(ohlcv, ohlcv_htf, min_score_pct=config.min_sniper_score_pct)
        if config.sniper
        else ModuleResult("sniper", None, 0.0, False, "desabilitado")
    )
    results.extend([trend, range_, sniper])

    regime = _pick_regime(trend, range_, config)
    primary = range_ if regime == "range" else trend

    if not primary.triggered or primary.direction is None:
        return None, results

    if config.sniper and config.sniper_required:
        if not sniper.triggered or sniper.direction is None:
            return None, results
        if sniper.direction != primary.direction:
            return None, results
    elif config.sniper and sniper.triggered and sniper.direction and sniper.direction != primary.direction:
        return None, results

    if config.require_all:
        regime_modules = (range_, sniper) if regime == "range" else (trend, sniper)
        active = [
            r
            for r in regime_modules
            if r.name in _enabled_names(config) and r.triggered
        ]
        dirs = {r.direction for r in active if r.direction}
        if len(dirs) > 1:
            return None, results

    direction = primary.direction
    if screener_bias and direction != screener_bias:
        return None, results

    entry = primary.entry_price or sniper.entry_price
    sl = primary.stop_loss or sniper.stop_loss
    tps_raw = primary.take_profits or sniper.take_profits
    if entry is None or sl is None or not tps_raw:
        return None, results

    tps_list = list(tps_raw)
    while len(tps_list) < 4:
        risk = abs(entry - sl)
        last_mult = len(tps_list) + 1
        tps_list.append(
            entry + risk * last_mult if direction == "LONG" else entry - risk * last_mult
        )
    tps = tuple(tps_list[:4])

    modules = tuple(r.name for r in results if r.triggered)
    confidences = [r.confidence for r in results if r.triggered and r.confidence > 0]
    if config.sniper and sniper.triggered and sniper.confidence > 0:
        confidences.append(sniper.confidence)
    confidence = sum(confidences) / len(confidences) if confidences else primary.confidence

    summary = (
        f"{regime.upper()} | {direction} | "
        + " + ".join(f"{m}" for m in modules)
        + f" | {primary.reason}"
    )

    return CombinedSignal(
        direction=direction,
        entry_price=entry,
        stop_loss=sl,
        take_profits=tps,  # type: ignore[arg-type]
        confidence=round(min(1.0, confidence), 3),
        regime=regime,  # type: ignore[arg-type]
        modules=modules,
        summary=summary,
    ), results


def _enabled_names(config: IndicatorModulesConfig) -> set[str]:
    names: set[str] = set()
    if config.trend_speed:
        names.add("trend_speed")
    if config.range_detector:
        names.add("range_detector")
    if config.sniper:
        names.add("sniper")
    return names
