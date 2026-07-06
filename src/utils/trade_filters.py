"""Filtros reutilizáveis de estilo de trade e tipo de mercado."""

from __future__ import annotations

import re

from src.config.runtime_config import BotRuntimeConfig, TelegramFiltersConfig
from src.config.settings import Settings
from src.models.schemas import TelegramSignal, TradeDirection, TradeStyle

_SWING_KEYWORDS = re.compile(
    r"\b(swing|hold|hodl|semanal|weekly|mensal|monthly|"
    r"médio\s*prazo|medio\s*prazo|longo\s*prazo|position\s*trade)\b",
    re.IGNORECASE,
)
_SPOT_KEYWORDS = re.compile(
    r"\b(spot|à\s*vista|a\s*vista|cash\s*market)\b",
    re.IGNORECASE,
)
_SCALP_KEYWORDS = re.compile(
    r"\b(scalp|scalping|scalper|rápido|rapido|turbo)\b",
    re.IGNORECASE,
)
_DAYTRADE_KEYWORDS = re.compile(
    r"\b(day\s*trade|daytrade|intraday|intra\s*day)\b",
    re.IGNORECASE,
)
_LONG_TIMEFRAME = re.compile(
    r"\b(4h|6h|8h|12h|1d|1w|daily|diário|diario)\b",
    re.IGNORECASE,
)
_LEVERAGE_PATTERN = re.compile(r"\d+\s*x", re.IGNORECASE)

_SCALP_TIMEFRAMES = frozenset({"1m", "3m", "5m"})
_DAYTRADE_TIMEFRAMES = frozenset({"15m", "30m", "1h"})
_SWING_TIMEFRAMES = frozenset({"4h", "6h", "8h", "12h", "1d", "1w"})


def infer_trade_style(text: str, timeframe: str | None = None) -> TradeStyle:
    """Infere estilo de trade a partir do texto do sinal e/ou timeframe."""
    if _SPOT_KEYWORDS.search(text):
        return TradeStyle.SPOT
    if _SWING_KEYWORDS.search(text) or _LONG_TIMEFRAME.search(text):
        return TradeStyle.SWING
    if _SCALP_KEYWORDS.search(text):
        return TradeStyle.SCALP
    if _DAYTRADE_KEYWORDS.search(text):
        return TradeStyle.DAYTRADE

    if timeframe:
        tf = timeframe.lower().strip()
        if tf in _SCALP_TIMEFRAMES:
            return TradeStyle.SCALP
        if tf in _DAYTRADE_TIMEFRAMES:
            return TradeStyle.DAYTRADE
        if tf in _SWING_TIMEFRAMES:
            return TradeStyle.SWING

    if _LEVERAGE_PATTERN.search(text):
        return TradeStyle.DAYTRADE

    return TradeStyle.DAYTRADE


def is_trade_style_allowed(
    style: TradeStyle,
    filters: TelegramFiltersConfig,
) -> tuple[bool, str]:
    """Verifica se o estilo está permitido e não está na lista de rejeição."""
    style_value = style.value
    rejected = {s.lower() for s in filters.reject_trade_styles}
    if style_value in rejected:
        return False, f"Estilo rejeitado: {style_value}"

    allowed = {s.lower() for s in filters.allowed_trade_styles}
    if allowed and style_value not in allowed:
        allowed_list = ", ".join(sorted(allowed))
        return False, f"Estilo não permitido: {style_value} (permitidos: {allowed_list})"

    return True, ""


def check_signal_allowed(
    signal: TelegramSignal,
    style: TradeStyle,
    settings: Settings,
    *,
    filters: TelegramFiltersConfig | None = None,
) -> tuple[bool, str]:
    """
    Valida sinal contra restrições de estilo, direção e mercado.

    Returns:
        (permitido, motivo_rejeição)
    """
    if signal.direction is not None and signal.direction not in (
        TradeDirection.LONG,
        TradeDirection.SHORT,
    ):
        return False, f"Direção inválida: {signal.direction}"

    if _SPOT_KEYWORDS.search(signal.raw_text):
        return False, "Sinal identificado como spot (à vista)"

    trade_filters = filters or TelegramFiltersConfig()
    style_ok, style_reason = is_trade_style_allowed(style, trade_filters)
    if not style_ok:
        return False, style_reason

    if settings.bybit_market_type == "linear_swap" and signal.symbol:
        sym = signal.symbol.upper()
        if sym.endswith("/USDT") and ":USDT" not in sym:
            if _SPOT_KEYWORDS.search(signal.raw_text):
                return False, "Símbolo spot não permitido — apenas futures linear"

    return True, ""
