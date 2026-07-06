"""Quais indicadores renderizar no chart — espelha a estratégia ativa."""

from __future__ import annotations

from dataclasses import dataclass

from src.config.strategy_config import IndicatorModulesConfig, ScannerPipelineConfig


@dataclass(frozen=True)
class ChartRenderConfig:
    """Indicadores visíveis no replay (conforme Pine em indicators/)."""

    entry_strategy: str
    trend_speed: bool = False
    range_detector: bool = False
    sniper: bool = False
    breakout_probability: bool = False
    kalman: bool = False
    imba: bool = False

    @property
    def active_names(self) -> tuple[str, ...]:
        names: list[str] = []
        if self.trend_speed:
            names.append("trend_speed")
        if self.range_detector:
            names.append("range_detector")
        if self.sniper:
            names.append("sniper")
        if self.breakout_probability:
            names.append("breakout_probability")
        if self.kalman:
            names.append("kalman")
        if self.imba:
            names.append("imba")
        return tuple(names)


def resolve_chart_render_for_entry(
    entry_strategy: str,
    indicators: IndicatorModulesConfig | None = None,
    *,
    imba: bool = False,
) -> ChartRenderConfig:
    """Resolve overlays a partir da estratégia + toggles do momento do registro."""
    pipeline = ScannerPipelineConfig(
        entry_strategy=entry_strategy,  # type: ignore[arg-type]
        indicators=indicators or IndicatorModulesConfig(),
        imba=imba,
    )
    return resolve_chart_render_config(pipeline)


def resolve_chart_render_config(
    pipeline: ScannerPipelineConfig | None,
) -> ChartRenderConfig:
    """
    Monta overlays só dos indicadores usados pela estratégia ativa.
    sniper → Sniper Entry + Breakout Probability
    combined → módulos ligados em indicators.*
    imba → IMBA ALGO
    """
    if pipeline is None:
        return ChartRenderConfig(entry_strategy="combined")

    ind: IndicatorModulesConfig = pipeline.indicators
    strategy = pipeline.entry_strategy

    if strategy == "sniper":
        return ChartRenderConfig(
            entry_strategy=strategy,
            sniper=True,
            breakout_probability=True,
        )

    if strategy == "imba":
        return ChartRenderConfig(
            entry_strategy=strategy,
            imba=pipeline.imba,
        )

    # combined (default)
    return ChartRenderConfig(
        entry_strategy=strategy,
        trend_speed=ind.trend_speed,
        range_detector=ind.range_detector,
        sniper=ind.sniper,
    )
