"""Regras operacionais do bot — carregadas de settings.json com hot-reload."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator


def _default_strategies():
    from src.config.strategy_config import StrategiesConfig

    return StrategiesConfig()


class ConfidenceConfig(BaseModel):
    """Limites de confiança da LLM."""

    telegram: float = Field(default=0.90, ge=0.0, le=1.0)
    scanner: float = Field(default=0.65, ge=0.0, le=1.0)


class TimeframesConfig(BaseModel):
    """Timeframes unificados — Telegram, scanner e IMBA."""

    analysis: list[str] = Field(
        default_factory=lambda: ["3m", "5m", "15m", "30m", "1h"],
        description="TFs para buscar OHLCV (todos os pipelines)",
    )
    primary: str = Field(default="15m", description="TF primário de confluência")
    trend: str = Field(default="30m", description="TF de filtro de tendência")
    execution: str = Field(default="5m", description="TF IMBA para entry/SL/TP")

    @field_validator("analysis", mode="before")
    @classmethod
    def normalize_analysis(cls, value: object) -> list[str]:
        if value is None:
            return ["3m", "5m", "15m"]
        if isinstance(value, str):
            return [v.strip().lower() for v in value.split(",") if v.strip()]
        if isinstance(value, list):
            return [str(v).strip().lower() for v in value if str(v).strip()]
        raise ValueError(f"analysis inválido: {value!r}")

    @field_validator("primary", "trend", "execution", mode="before")
    @classmethod
    def normalize_tf(cls, value: object) -> str:
        return str(value).strip().lower()

    @model_validator(mode="after")
    def ensure_primary_in_analysis(self) -> Self:
        if self.primary not in self.analysis:
            self.analysis = [self.primary, *self.analysis]
        if self.trend not in self.analysis:
            self.analysis.append(self.trend)
        if self.execution not in self.analysis:
            self.analysis.append(self.execution)
        return self


class RiskConfig(BaseModel):
    risk_per_trade_pct: float = Field(
        default=1.0,
        ge=0.1,
        le=5.0,
        description="% do saldo arriscado por trade (perda máxima no SL)",
    )
    max_position_pct: float = Field(default=5.0, ge=0.5, le=100.0)
    max_concurrent_trades: int = Field(default=3, ge=1, le=10)
    max_portfolio_risk_pct: float = Field(
        default=3.0,
        ge=0.5,
        le=20.0,
        description="Soma do risco % de todas posições abertas",
    )
    wins_cover_losses: int = Field(
        default=3,
        ge=2,
        le=10,
        description="R:R ponderado mínimo — 1 win deve cobrir N losses",
    )
    min_leverage: int = Field(default=10, ge=1, le=100)
    max_leverage: int = Field(default=30, ge=1, le=100)
    liquidation_sl_buffer_pct: float = Field(
        default=0.4,
        ge=0.1,
        le=2.0,
        description="Margem % entre SL e preço de liquidação",
    )


class SmcConfig(BaseModel):
    """Smart Money Concepts — SL/TP em liquidez e estrutura."""

    enabled: bool = True
    structure_timeframe: str = Field(
        default="15m",
        description="TF para swings, OB, FVG e liquidez",
    )
    sl_buffer_atr_mult: float = Field(default=0.2, ge=0.05, le=1.0)
    min_tp1_rr: float = Field(default=2.0, ge=1.0, le=10.0)
    min_tp2_rr: float = Field(default=3.0, ge=1.5, le=15.0)
    swing_lookback: int = Field(default=80, ge=30, le=200)

    @field_validator("structure_timeframe", mode="before")
    @classmethod
    def normalize_structure_tf(cls, value: object) -> str:
        return str(value).strip().lower()


class ImbaConfig(BaseModel):
    sensitivity: float = Field(default=2.0, ge=0.1)
    tp_percents: list[float] = Field(default_factory=lambda: [1.0, 2.0, 3.0])
    tp_close_pcts: list[float] = Field(default_factory=lambda: [50.0, 30.0, 20.0])
    close_on_reversal: bool = False
    use_fib_levels: bool = Field(
        default=True,
        description="TPs/SL por Fibonacci no TF de execução (scalp)",
    )
    fib_lookback: int = Field(default=60, ge=20, le=200)
    fib_sl_buffer_pct: float = Field(
        default=0.08,
        ge=0.0,
        le=0.5,
        description="Buffer % abaixo/acima da base fib para SL",
    )
    fib_min_tp1_rr: float = Field(
        default=0.0,
        ge=0.0,
        le=3.0,
        description="R:R mínimo TP1 fib (0 = desliga para scalp)",
    )
    fib_structure_timeframe: str = Field(
        default="5m",
        description="TF para ancorar swings da Fib (estrutura)",
    )
    fib_max_entry_ratio: float = Field(
        default=0.95,
        ge=0.2,
        le=0.95,
        description="Entrada máxima na retração fib (zona de compra/venda)",
    )
    min_htf_confirm: int = Field(
        default=1,
        ge=1,
        le=3,
        description="Mínimo de TFs 15m/30m/1h alinhados com o sinal 5m",
    )
    require_fresh_signal: bool = Field(
        default=False,
        description="Se false, aceita tendência alinhada no 5m (não só sinal no último candle)",
    )
    fib_min_tps_above: int = Field(
        default=1,
        ge=1,
        le=4,
        description="Mínimo de TPs válidos acima/abaixo da entrada",
    )
    fib_fallback_to_imba: bool = Field(
        default=False,
        description="Se Fib inválida, rejeita trade (não usa % fixos IMBA)",
    )

    @field_validator("tp_percents", "tp_close_pcts", mode="before")
    @classmethod
    def parse_float_list(cls, value: object) -> list[float]:
        if isinstance(value, list):
            items = [float(v) for v in value]
        elif isinstance(value, str):
            items = [float(v.strip()) for v in value.split(",") if v.strip()]
        else:
            raise ValueError(f"lista numérica inválida: {value!r}")
        if len(items) == 4 and abs(items[3]) < 0.01:
            items = items[:3]
        return items

    @model_validator(mode="after")
    def validate_tp_lists(self) -> Self:
        if len(self.tp_percents) != 3:
            raise ValueError("imba.tp_percents deve ter 3 valores")
        if len(self.tp_close_pcts) != 3:
            raise ValueError("imba.tp_close_pcts deve ter 3 valores")
        total = sum(self.tp_close_pcts)
        if abs(total - 100.0) > 0.01:
            raise ValueError(f"imba.tp_close_pcts deve somar 100%, recebido {total}")
        return self

    def tp_close_tuple(self) -> tuple[float, float, float]:
        p = self.tp_close_pcts
        return (p[0], p[1], p[2])

    def tp_percent_tuple(self) -> tuple[float, float, float]:
        p = self.tp_percents
        return (p[0], p[1], p[2])


class ScreenerConfig(BaseModel):
    """Descoberta automática de moedas — replica RSI Heatmap + Visual Screener (Bybit grátis)."""

    enabled: bool = True
    interval_seconds: int = Field(default=900, ge=120, description="Intervalo entre varreduras de mercado")
    min_turnover_24h_usd: float = Field(
        default=500_000.0,
        ge=0.0,
        description="Volume mínimo 24h (USD) para considerar o par",
    )
    max_candidates: int = Field(
        default=100,
        ge=5,
        le=100,
        description="Máximo de moedas descobertas pelo screener por ciclo",
    )
    max_scan_symbols: int = Field(
        default=100,
        ge=10,
        le=150,
        description="Limite total de símbolos por ciclo do scanner (screener + watchlist)",
    )
    max_prescan_symbols: int = Field(
        default=200,
        ge=20,
        le=500,
        description="Máximo de pares analisados por RSI (top volume)",
    )
    prescan_batch_size: int = Field(
        default=40,
        ge=5,
        le=100,
        description="Pares processados por lote no screener (asyncio)",
    )
    merge_static_watchlist: bool = Field(
        default=True,
        description="Une watchlist manual com candidatos do screener",
    )
    rsi_period: int = Field(default=14, ge=7, le=28)
    timeframes: list[str] = Field(
        default_factory=lambda: ["15m", "1h", "4h", "1d"],
        description="TFs para RSI estilo CoinGlass Heatmap",
    )
    ohlcv_concurrency: int = Field(
        default=12,
        ge=1,
        le=30,
        description="Requisições OHLCV simultâneas dentro de cada lote",
    )
    require_confluence: bool = Field(
        default=True,
        description="Exige RSI Heatmap + fluxo derivativos na MESMA direção",
    )
    mode: Literal["trend", "reversal"] = Field(
        default="trend",
        description="trend=só verifica direção da moeda | reversal=setup contrarian",
    )
    discovery_only: bool = Field(
        default=True,
        description="Só expande universo de scan — não filtra entrada (ALGO+Kalman decide)",
    )
    rsi_overbought_min: float = Field(
        default=70.0,
        ge=60.0,
        le=90.0,
        description="RSI >= valor = overbought no heatmap CoinGlass",
    )
    rsi_oversold_max: float = Field(
        default=30.0,
        ge=10.0,
        le=40.0,
        description="RSI <= valor = oversold no heatmap CoinGlass",
    )
    oi_change_min_pct: float = Field(
        default=2.0,
        ge=0.5,
        le=20.0,
        description="OI subindo >= X% = posições entrando",
    )
    account_ratio_period: str = Field(
        default="1h",
        description="Período do long/short ratio Bybit (shorts/long entering)",
    )
    account_ratio_delta_min: float = Field(
        default=0.02,
        ge=0.005,
        le=0.2,
        description="Variação mínima do sell/buy ratio entre leituras",
    )
    long_rsi_high_tf_max: float = Field(default=40.0, ge=10.0, le=50.0)
    long_rsi_mid_tf_min: float = Field(default=35.0, ge=10.0, le=55.0)
    short_rsi_high_tf_min: float = Field(default=60.0, ge=50.0, le=90.0)
    short_rsi_mid_tf_max: float = Field(default=65.0, ge=45.0, le=90.0)
    funding_squeeze_max: float = Field(
        default=-0.0001,
        description="Funding abaixo disso favorece LONG (short squeeze)",
    )
    funding_crowded_min: float = Field(
        default=0.0003,
        description="Funding acima disso favorece SHORT (longs pagando)",
    )

    @field_validator("timeframes", mode="before")
    @classmethod
    def normalize_screener_tfs(cls, value: object) -> list[str]:
        if value is None:
            return ["15m", "1h", "4h", "1d"]
        if isinstance(value, str):
            return [v.strip().lower() for v in value.split(",") if v.strip()]
        if isinstance(value, list):
            return [str(v).strip().lower() for v in value if str(v).strip()]
        raise ValueError(f"timeframes inválido: {value!r}")


class ScannerQualityConfig(BaseModel):
    """Filtros objetivos para reduzir entradas fracas no scanner autônomo."""

    min_imba_confidence: float = Field(default=0.55, ge=0.0, le=1.0)
    min_combined_confidence: float = Field(
        default=0.78,
        ge=0.0,
        le=1.0,
        description="Score mínimo dos indicadores combinados (Trend+Range+Sniper)",
    )
    min_confluence_score: int = Field(default=65, ge=0, le=100)
    min_confluence_spread: int = Field(
        default=12,
        ge=0,
        le=50,
        description="Lado da direção deve superar o oposto por pelo menos N pontos",
    )
    require_confluence_align: bool = True
    require_imba_tf_align: bool = True
    min_tp1_rr: float = Field(default=1.2, ge=1.0, le=5.0)
    min_sl_atr_multiple: float = Field(default=0.55, ge=0.1, le=5.0)
    max_sl_atr_multiple: float = Field(default=2.5, ge=0.5, le=20.0)
    min_volume_ratio: float = Field(default=0.45, ge=0.0, le=5.0)
    require_kalman_align: bool = True
    reject_kalman_reversal_against: bool = True
    pwin_reliability_bump_low: float = Field(default=0.07, ge=0.0, le=0.2)
    pwin_reliability_bump_medium: float = Field(default=0.03, ge=0.0, le=0.15)
    pwin_bad_historical_bump: float = Field(
        default=0.0,
        ge=0.0,
        le=0.2,
        description="Bump extra no threshold P(win) quando histórico bayesiano é ruim",
    )
    min_llm_confidence: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        description="Mínimo da LLM antes de aplicar níveis (além do kill switch P(win))",
    )
    require_market_pattern: bool = Field(
        default=True,
        description="Exige padrão clássico de price action alinhado à direção",
    )
    min_pattern_historical_winrate: float = Field(
        default=0.80,
        ge=0.5,
        le=1.0,
        description="Win rate histórico mínimo do padrão (literatura técnica)",
    )
    min_pattern_match_confidence: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        description="Confiança mínima da detecção do padrão (0-1)",
    )
    pattern_timeframes: list[str] = Field(
        default_factory=lambda: ["5m", "15m"],
        description="TFs onde buscar padrões de price action",
    )

    @field_validator("pattern_timeframes", mode="before")
    @classmethod
    def normalize_pattern_tfs(cls, value: object) -> list[str]:
        if value is None:
            return ["5m", "15m"]
        if isinstance(value, str):
            return [v.strip().lower() for v in value.split(",") if v.strip()]
        if isinstance(value, list):
            return [str(v).strip().lower() for v in value if str(v).strip()]
        raise ValueError(f"pattern_timeframes inválido: {value!r}")


class ScannerConfig(BaseModel):
    enabled: bool = True
    interval_seconds: int = Field(default=300, ge=60)
    watchlist_path: str = "data/watchlist.txt"
    scan_batch_size: int = Field(
        default=25,
        ge=5,
        le=50,
        description="Símbolos avaliados por lote no ciclo do scanner",
    )
    scan_concurrency: int = Field(
        default=10,
        ge=1,
        le=30,
        description="Avaliações simultâneas dentro de cada lote",
    )
    screener: ScreenerConfig = Field(default_factory=ScreenerConfig)
    quality: ScannerQualityConfig = Field(default_factory=ScannerQualityConfig)


class TelegramFiltersConfig(BaseModel):
    topic_ids: list[int] = Field(default_factory=list)
    topic_names: list[str] = Field(default_factory=list)
    allowed_trade_styles: list[str] = Field(default_factory=lambda: ["daytrade", "scalp"])
    reject_trade_styles: list[str] = Field(default_factory=lambda: ["swing", "spot"])

    @field_validator("topic_ids", mode="before")
    @classmethod
    def parse_topic_ids(cls, value: object) -> list[int]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [int(v) for v in value]
        if isinstance(value, str):
            return [int(v.strip()) for v in value.split(",") if v.strip()]
        return []

    @field_validator("topic_names", "allowed_trade_styles", "reject_trade_styles", mode="before")
    @classmethod
    def parse_str_list(cls, value: object) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return []


class BreakevenConfig(BaseModel):
    """Move SL para entrada após TP parcial (default: após TP1 = 50% fechado)."""

    after_tp: int = Field(
        default=1,
        ge=0,
        le=2,
        description="0=off | 1=após TP1 | 2=após TP2",
    )
    legacy_on_tp2: bool = False

    @property
    def level(self) -> int:
        return self.after_tp


class PnlReportConfig(BaseModel):
    enabled: bool = True
    interval_seconds: int = Field(default=3600, ge=60)
    period: Literal["day", "week", "month", "year"] = Field(
        default="week",
        description="Período do W/L fechado: day | week | month | year",
    )


class LearningConfig(BaseModel):
    """Aprendizado com journal + rejeições + calibração de P(win)."""

    enabled: bool = True
    rejections_path: str = "data/rejections.json"
    approvals_path: str = "data/approvals.json"
    log_approvals: bool = True
    min_pattern_samples: int = Field(default=3, ge=2, le=50)
    bad_pattern_winrate_pct: float = Field(
        default=40.0,
        ge=0.0,
        le=100.0,
        description="Bloqueia padrão com WR abaixo deste % (amostra mínima)",
    )
    pattern_probability_penalty: float = Field(
        default=0.15,
        ge=0.0,
        le=0.5,
        description="Reduz P(win) para padrões ruins",
    )
    good_pattern_boost: float = Field(
        default=0.05,
        ge=0.0,
        le=0.2,
        description="Aumento leve de P(win) para padrões fortes",
    )
    good_pattern_winrate_pct: float = Field(default=60.0, ge=50.0, le=100.0)
    include_in_pnl_report: bool = True
    log_rejections: bool = True
    use_pattern_family_blocking: bool = Field(
        default=True,
        description="Bloqueia família de padrão (sem chart) com histórico ruim",
    )
    pattern_family_min_samples: int = Field(default=2, ge=2, le=20)
    big_loss_block_pct: float = Field(
        default=-0.80,
        le=0.0,
        description="Loss % que conta como erro grave no journal",
    )
    block_family_on_big_loss: bool = Field(
        default=True,
        description="Bloqueia família após loss grave com amostra mínima",
    )
    max_avg_loss_pct: float = Field(
        default=-0.35,
        le=0.0,
        description="Bloqueia família se PnL médio ficar abaixo deste %",
    )
    severe_loss_penalty: float = Field(
        default=0.20,
        ge=0.0,
        le=0.5,
        description="Penalidade extra de P(win) quando família tem loss grave",
    )
    zero_winrate_block_samples: int = Field(
        default=2,
        ge=2,
        le=10,
        description="Bloqueia padrão exato com 0% WR após N trades",
    )


class DisplayConfig(BaseModel):
    """Exibição no dashboard (fusos e gráficos)."""

    utc_offset_hours: float = Field(
        default=-3.0,
        ge=-12.0,
        le=14.0,
        description="Offset UTC para horários no gráfico de análise (ex: -3 = Brasília)",
    )


class BotRuntimeConfig(BaseModel):
    """Configuração operacional hot-reload (data/settings.json)."""

    ohlcv_limit: int = Field(default=200, ge=50, le=1000)
    confidence: ConfidenceConfig = Field(default_factory=ConfidenceConfig)
    timeframes: TimeframesConfig = Field(default_factory=TimeframesConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    smc: SmcConfig = Field(default_factory=SmcConfig)
    imba: ImbaConfig = Field(default_factory=ImbaConfig)
    scanner: ScannerConfig = Field(default_factory=ScannerConfig)
    telegram: TelegramFiltersConfig = Field(default_factory=TelegramFiltersConfig)
    breakeven: BreakevenConfig = Field(default_factory=BreakevenConfig)
    pnl_report: PnlReportConfig = Field(default_factory=PnlReportConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    display: DisplayConfig = Field(default_factory=DisplayConfig)
    strategies: "StrategiesConfig" = Field(default_factory=_default_strategies)
    trade_journal_path: str = "data/trades.json"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "text"] = "text"

    def effective_max_concurrent_trades(self, bybit_mode: str) -> int:
        if bybit_mode in ("testnet", "demo"):
            return 10
        return self.risk.max_concurrent_trades


from src.config.strategy_config import StrategiesConfig  # noqa: E402

BotRuntimeConfig.model_rebuild()
