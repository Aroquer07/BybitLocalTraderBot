"""Pipeline modular — combine estratégias independentemente."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


class IndicatorModulesConfig(BaseModel):
    """Indicadores do vídeo — ligue/desligue cada um."""

    trend_speed: bool = Field(default=True, description="Trend Speed Analyzer (ZMA)")
    range_detector: bool = Field(default=True, description="Range Detector (LuxAlgo)")
    sniper: bool = Field(default=True, description="Sniper Entry Exit (painel)")
    require_all: bool = Field(
        default=True,
        description="Todos os módulos ativos devem concordar na direção",
    )
    min_sniper_score_pct: float = Field(
        default=85.0,
        ge=50.0,
        le=100.0,
        description="Score mínimo bull/bear no Sniper (modo panel)",
    )
    min_breakout_probability_pct: float = Field(
        default=60.0,
        ge=50.0,
        le=100.0,
        description="Breakout Probability mínima para confirmar próximo candle",
    )
    sniper_required: bool = Field(
        default=False,
        description="Se false, Sniper só reforça confiança — não bloqueia entrada",
    )
    allow_trend_without_pullback: bool = Field(
        default=True,
        description="Com bias do screener, aceita tendência alinhada sem pullback exato",
    )


class ScannerPipelineConfig(BaseModel):
    """
    Módulos do scanner autônomo — ligue/desligue cada camada.

    entry_strategy `combined`: Trend Speed + Range + Sniper + SMC.
    entry_strategy `sniper`: Sniper Entry (SL/TP ATR) + Breakout Probability.
    entry_strategy `imba`: pipeline IMBA legado.
  """

    entry_strategy: Literal["imba", "combined", "sniper"] = "combined"
    mode: Literal["autonomous", "llm_assisted"] = "autonomous"
    imba: bool = Field(default=False, description="Sinal direcional [IMBA] ALGO")
    indicators: IndicatorModulesConfig = Field(default_factory=IndicatorModulesConfig)
    smc: bool = Field(default=True, description="SL/TP em estrutura SMC")
    screener: bool = Field(
        default=True,
        description="RSI Heatmap + derivativos — só descobre moedas (não define entrada)",
    )
    quality_filters: bool = Field(
        default=True,
        description="Filtros Python (confluência, volume, R:R)",
    )
    market_patterns: bool = Field(
        default=False,
        description="Exige padrão clássico de price action",
    )
    kalman_hard_block: bool = Field(
        default=False,
        description="Rejeita se Kalman contradiz (senão só penaliza P(win))",
    )
    llm: bool = Field(default=False, description="Consulta LLM local")
    pwin: bool = Field(default=True, description="Kill switch P(win) objetiva")
    learning: bool = Field(default=True, description="Bloqueio por padrões ruins")

    @model_validator(mode="after")
    def sync_mode_defaults(self) -> Self:
        if self.mode == "autonomous" and self.llm:
            object.__setattr__(self, "llm", False)
        if self.mode == "llm_assisted" and not self.llm:
            object.__setattr__(self, "llm", True)
        return self


class TelegramPipelineConfig(BaseModel):
    """Módulos do pipeline Telegram — LLM continua central."""

    llm: bool = True
    imba: bool = True
    smc: bool = True
    pwin: bool = True
    learning: bool = True


class StrategiesConfig(BaseModel):
    scanner: ScannerPipelineConfig = Field(default_factory=ScannerPipelineConfig)
    telegram: TelegramPipelineConfig = Field(default_factory=TelegramPipelineConfig)


def effective_scanner_quality(quality, pipeline: ScannerPipelineConfig):
    """Aplica toggles do pipeline sobre os filtros de qualidade."""
    updates: dict = {}
    if not pipeline.market_patterns:
        updates["require_market_pattern"] = False
    if not pipeline.kalman_hard_block:
        updates["require_kalman_align"] = False
        updates["reject_kalman_reversal_against"] = False
    if updates:
        return quality.model_copy(update=updates)
    return quality
