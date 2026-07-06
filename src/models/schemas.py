"""Schemas Pydantic para validação estrita de inputs/outputs do pipeline."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TradeDirection(str, Enum):
    """Direção do trade."""

    LONG = "LONG"
    SHORT = "SHORT"


class TradeStyle(str, Enum):
    """Estilo operacional do trade."""

    DAYTRADE = "daytrade"
    SCALP = "scalp"
    SWING = "swing"
    SPOT = "spot"


class OrderSide(str, Enum):
    """Lado da ordem na exchange."""

    BUY = "buy"
    SELL = "sell"


class SignalStrength(str, Enum):
    """Força do sinal técnico."""

    FORTE = "FORTE"
    FRACO = "FRACO"


class TradeSource(str, Enum):
    """Origem da decisão de trade."""

    TELEGRAM = "telegram"
    SCANNER = "scanner"


class TradeStatus(str, Enum):
    """Status de um trade registrado."""

    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class TelegramSignal(BaseModel):
    """Sinal bruto extraído do Telegram."""

    message_id: int = Field(..., description="ID da mensagem no Telegram")
    channel_id: int = Field(..., description="ID do canal de origem")
    topic_id: int | None = Field(default=None, description="ID do tópico (forum)")
    raw_text: str = Field(..., min_length=1, description="Texto original da mensagem")
    symbol: str | None = Field(
        default=None,
        description="Par extraído (ex: BTC/USDT)",
    )
    direction: TradeDirection | None = Field(
        default=None,
        description="Direção inferida do sinal",
    )
    entry_price: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profits: list[float] = Field(default_factory=list)
    leverage: int | None = Field(default=None, ge=1, le=100)
    trade_style: TradeStyle | None = Field(
        default=None,
        description="Estilo inferido do sinal (daytrade, scalp, swing, spot)",
    )
    received_at: datetime = Field(default_factory=_utc_now)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str | None) -> str | None:
        """Normaliza símbolo para formato CCXT."""
        if value is None:
            return None
        normalized = value.upper().replace("#", "").strip()
        if "/" not in normalized and normalized.endswith("USDT"):
            base = normalized[:-4]
            return f"{base}/USDT"
        return normalized


class TakeProfitLevel(BaseModel):
    """Nível de take profit com métricas de risco/retorno."""

    price: float = Field(..., gt=0)
    percentage: float = Field(..., description="% de ganho em relação à entrada")
    risk_reward: float = Field(..., ge=0, description="Relação risco/retorno")


class TimeframeSnapshot(BaseModel):
    """Snapshot técnico de um timeframe individual."""

    indicators: dict[str, Any] = Field(
        default_factory=dict,
        description="Indicadores técnicos calculados via pandas-ta",
    )
    fibonacci: dict[str, Any] = Field(
        default_factory=dict,
        description="Níveis Fibonacci, swing points e R:R pré-calculados",
    )
    ohlcv_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Resumo estatístico dos candles (sem DataFrame bruto)",
    )


class ConfluenceResult(BaseModel):
    """Pré-score de confluência calculado em Python."""

    long_score: int = Field(ge=0, le=100)
    short_score: int = Field(ge=0, le=100)
    long_checks: dict[str, bool] = Field(default_factory=dict)
    short_checks: dict[str, bool] = Field(default_factory=dict)
    recommendation: str = Field(
        default="NEUTRAL",
        description="LONG | SHORT | NEUTRAL — pré-recomendação Python",
    )


class ImbaTimeframeResult(BaseModel):
    """Resultado IMBA ALGO em um timeframe."""

    timeframe: str
    trend: str = Field(description="LONG | SHORT | NEUTRAL")
    signal_on_last_bar: bool = False
    signal_side: TradeDirection | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profits: list[float] = Field(default_factory=list)


class ImbaAnalysis(BaseModel):
    """Análise multi-TF do indicador [IMBA] ALGO."""

    symbol: str
    timeframes: dict[str, ImbaTimeframeResult] = Field(default_factory=dict)
    aligned_direction: TradeDirection | None = None
    fresh_signal_direction: TradeDirection | None = None
    confidence_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Score Python 0-1 baseado em alinhamento multi-TF",
    )
    summary: str = ""


class StoredTrade(BaseModel):
    """Trade persistido para histórico win/loss."""

    id: str
    symbol: str
    direction: TradeDirection
    source: TradeSource
    status: TradeStatus = TradeStatus.OPEN
    entry_price: float
    stop_loss: float
    take_profits: list[float] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    leverage: int = 15
    amount: float | None = None
    probability_features: dict[str, Any] | None = Field(
        default=None,
        description="Features usadas na estimativa P(win) na abertura",
    )
    entry_order_id: str | None = None
    sl_order_id: str | None = None
    opened_at: datetime = Field(default_factory=_utc_now)
    closed_at: datetime | None = None
    exit_price: float | None = None
    pnl_pct: float | None = None
    close_reason: str | None = None
    telegram_message_id: int | None = None
    notes: str = ""


class MarketState(BaseModel):
    """Estado de mercado multi-timeframe com confluência (Python, não LLM)."""

    symbol: str = Field(..., min_length=1)
    timeframe: str = Field(
        ...,
        min_length=1,
        description="Timeframe primário de confirmação (15m)",
    )
    last_price: float = Field(..., gt=0)
    timestamp: datetime = Field(default_factory=_utc_now)
    timeframes: dict[str, TimeframeSnapshot] = Field(
        default_factory=dict,
        description="Snapshots por TF: 5m (entrada), 15m (confirmação), 30m (tendência)",
    )
    confluence: ConfluenceResult | None = Field(
        default=None,
        description="Pré-score de confluência long/short",
    )
    orderbook_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="Snapshot resumido do orderbook",
    )
    imba_analysis: ImbaAnalysis | None = Field(
        default=None,
        description="Análise [IMBA] ALGO multi-TF (3m/5m/15m)",
    )

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        """Garante formato CCXT para o símbolo."""
        return value.upper().strip()

    @property
    def primary_snapshot(self) -> TimeframeSnapshot | None:
        """Retorna snapshot do timeframe primário (15m)."""
        return self.timeframes.get(self.timeframe) or self.timeframes.get("15m")


class TradeDecision(BaseModel):
    """Decisão estratégica retornada pela LLM (Juiz Estratégico)."""

    approved: bool = Field(..., description="Se o trade foi aprovado")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="P(win) objetiva (0-1) após motor Python; substitui chute da LLM",
    )
    llm_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence original retornada pela LLM (auditoria)",
    )
    probability_breakdown: dict[str, Any] | None = Field(
        default=None,
        description="Breakdown técnico/mercado/setup/histórico da P(win)",
    )
    trade_style: TradeStyle | None = Field(
        default=None,
        description="Estilo operacional (scalp ou daytrade)",
    )
    trade_style_label: str | None = Field(
        default=None,
        description="Label SCALP ou DAYTRADE para output formatado",
    )
    direction: TradeDirection | None = None
    symbol: str | None = None
    entry_zone_min: float | None = Field(default=None, gt=0)
    entry_zone_max: float | None = Field(default=None, gt=0)
    entry_price: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    stop_loss_pct: float | None = Field(default=None, ge=0)
    leverage: int | None = Field(default=None, ge=1, le=100)
    take_profits: list[TakeProfitLevel] = Field(default_factory=list)
    bias: str = Field(default="", description="Viés técnico conciso")
    ai_analysis: str = Field(default="", description="Análise concisa da IA (legado)")
    volume_cvd_note: str = Field(default="", description="Nota sobre volume/CVD")
    entry_condition: str = Field(default="", description="Condição de ativação")
    tp_sl_quality: str = Field(default="", description="Avaliação TP/SL vs S/R")
    signal_strength: SignalStrength | None = None
    formatted_output: str = Field(
        default="",
        description="Output formatado conforme layout obrigatório",
    )
    raw_llm_response: str = Field(default="", description="Resposta bruta da LLM")
    source: TradeSource = Field(
        default=TradeSource.TELEGRAM,
        description="Origem: telegram ou scanner autônomo",
    )
    confidence_threshold: float = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        description="Limite mínimo de confiança (Regra de 90% ou settings)",
    )
    execution_timeframe: str | None = Field(
        default=None,
        description="TF usado para entry/SL/TP (ex.: 5m)",
    )

    @model_validator(mode="after")
    def validate_approval_consistency(self) -> "TradeDecision":
        """Trades aprovados devem ter campos obrigatórios preenchidos."""
        if (
            self.approved
            and self.probability_breakdown is not None
            and self.confidence < self.confidence_threshold
        ):
            raise ValueError(
                f"Trade aprovado requer confidence >= {self.confidence_threshold:.0%}"
            )
        if self.approved:
            required = [self.symbol, self.direction, self.entry_price, self.stop_loss]
            if any(v is None for v in required):
                raise ValueError(
                    "Trade aprovado requer symbol, direction, entry_price e stop_loss"
                )
        return self

    @property
    def passes_kill_switch(self) -> bool:
        """Verifica se a decisão passa no limiar de confiança configurado."""
        return self.approved and self.confidence >= self.confidence_threshold
