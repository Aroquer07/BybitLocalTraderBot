"""
Regras de confluência — pré-score Python (0-100) antes do juiz LLM.

REGRA FUNDAMENTAL: indicador isolado NÃO gera trade.
Múltiplos fatores devem convergir; a LLM ainda exige >= 90% para aprovar.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from src.models.schemas import ConfluenceResult, MarketState

DEFAULT_PRIMARY_TF = "15m"
DEFAULT_TREND_TF = "30m"
ENTRY_TF = "5m"

ADX_TREND_THRESHOLD = 25.0
SCORE_GAP_FOR_RECOMMENDATION = 15


class ConfluenceChecks(BaseModel):
    """Checklist booleano de confluência."""

    above_ema_ma: bool = False
    above_vwap: bool = False
    macd_bullish: bool = False
    rsi_favorable: bool = False
    bb_breakout: bool = False
    ichimoku_bullish: bool = False
    supertrend_adx: bool = False
    kalman_favorable: bool = False


class ConfluenceScore(BaseModel):
    """Score de confluência com checklist."""

    score: int = Field(ge=0, le=100)
    checks: ConfluenceChecks


def _get_tf_indicators(market_state: MarketState, tf: str) -> dict[str, Any]:
    snapshot = market_state.timeframes.get(tf)
    if snapshot is None:
        return {}
    return snapshot.indicators


def _eval_long_checks(ind: dict[str, Any], trend_ind: dict[str, Any]) -> ConfluenceChecks:
    close_above_emas = all(
        ind.get(k) is not None
        for k in ("ema_7", "ema_14", "sma_7", "sma_14")
    )
    above_ema_ma = False
    if close_above_emas:
        last = ind.get("_last_price") or ind.get("last_price")
        if last is None:
            last = ind.get("ema_7")
        ema_7 = ind.get("ema_7", 0)
        ema_14 = ind.get("ema_14", 0)
        sma_7 = ind.get("sma_7", 0)
        sma_14 = ind.get("sma_14", 0)
        if last and last > ema_7 and last > ema_14 and last > sma_7 and last > sma_14:
            above_ema_ma = True

    vwap = ind.get("vwap")
    last_price = ind.get("_last_price")
    above_vwap = bool(vwap and last_price and last_price > vwap)

    macd_bullish = (
        ind.get("macd_cross") == "bullish"
        or ind.get("macd_momentum") == "increasing"
        or (
            ind.get("macd_histogram") is not None
            and ind.get("macd_histogram", 0) > 0
            and ind.get("macd_momentum") == "increasing"
        )
    )

    rsi_12 = ind.get("rsi_12")
    rsi_zone = ind.get("rsi_zone")
    rsi_favorable = bool(
        rsi_12 is not None
        and (rsi_12 > 50 or (rsi_zone == "oversold" and ind.get("macd_momentum") == "increasing"))
    )

    volume_ratio = ind.get("_volume_ratio", 1.0)
    bb_breakout = bool(
        ind.get("bb_position") == "above_upper"
        and volume_ratio > 1.0
    ) or bool(
        ind.get("bb_squeeze")
        and ind.get("bb_position") == "above_upper"
    )

    ichimoku_bullish = bool(
        ind.get("ichimoku_above_cloud")
        and ind.get("ichimoku_tk_cross") == "bullish"
    )

    adx = ind.get("adx_14") or 0
    supertrend_adx = bool(
        ind.get("supertrend_direction") == "bullish"
        and adx >= ADX_TREND_THRESHOLD
    )

    if trend_ind.get("trend") == "bearish":
        above_ema_ma = False
        supertrend_adx = supertrend_adx and trend_ind.get("supertrend_direction") != "bearish"

    kalman_strength = ind.get("kalman_trend_strength")
    kalman_favorable = bool(
        (kalman_strength is not None and kalman_strength > 0)
        or ind.get("kalman_reversal") == "bullish"
        or ind.get("kalman_signal") == "bullish"
    )

    return ConfluenceChecks(
        above_ema_ma=above_ema_ma,
        above_vwap=above_vwap,
        macd_bullish=macd_bullish,
        rsi_favorable=rsi_favorable,
        bb_breakout=bb_breakout,
        ichimoku_bullish=ichimoku_bullish,
        supertrend_adx=supertrend_adx,
        kalman_favorable=kalman_favorable,
    )


def _eval_short_checks(ind: dict[str, Any], trend_ind: dict[str, Any]) -> ConfluenceChecks:
    close_below_emas = all(
        ind.get(k) is not None
        for k in ("ema_7", "ema_14", "sma_7", "sma_14")
    )
    below_ema_ma = False
    if close_below_emas:
        last = ind.get("_last_price")
        ema_7 = ind.get("ema_7", 0)
        ema_14 = ind.get("ema_14", 0)
        sma_7 = ind.get("sma_7", 0)
        sma_14 = ind.get("sma_14", 0)
        if last and last < ema_7 and last < ema_14 and last < sma_7 and last < sma_14:
            below_ema_ma = True

    vwap = ind.get("vwap")
    last_price = ind.get("_last_price")
    below_vwap = bool(vwap and last_price and last_price < vwap)

    macd_bearish = (
        ind.get("macd_cross") == "bearish"
        or ind.get("macd_momentum") == "decreasing"
        or (
            ind.get("macd_histogram") is not None
            and ind.get("macd_histogram", 0) < 0
            and ind.get("macd_momentum") == "decreasing"
        )
    )

    rsi_12 = ind.get("rsi_12")
    rsi_zone = ind.get("rsi_zone")
    rsi_favorable = bool(
        rsi_12 is not None
        and (rsi_12 < 50 or (rsi_zone == "overbought" and ind.get("macd_momentum") == "decreasing"))
    )

    volume_ratio = ind.get("_volume_ratio", 1.0)
    bb_breakout = bool(
        ind.get("bb_position") == "below_lower"
        and volume_ratio > 1.0
    ) or bool(
        ind.get("bb_squeeze")
        and ind.get("bb_position") == "below_lower"
    )

    ichimoku_bearish = bool(
        ind.get("ichimoku_below_cloud")
        and ind.get("ichimoku_tk_cross") == "bearish"
    )

    adx = ind.get("adx_14") or 0
    supertrend_adx = bool(
        ind.get("supertrend_direction") == "bearish"
        and adx >= ADX_TREND_THRESHOLD
    )

    if trend_ind.get("trend") == "bullish":
        below_ema_ma = False
        supertrend_adx = supertrend_adx and trend_ind.get("supertrend_direction") != "bullish"

    kalman_strength = ind.get("kalman_trend_strength")
    kalman_favorable = bool(
        (kalman_strength is not None and kalman_strength < 0)
        or ind.get("kalman_reversal") == "bearish"
        or ind.get("kalman_signal") == "bearish"
    )

    return ConfluenceChecks(
        above_ema_ma=below_ema_ma,
        above_vwap=below_vwap,
        macd_bullish=macd_bearish,
        rsi_favorable=rsi_favorable,
        bb_breakout=bb_breakout,
        ichimoku_bullish=ichimoku_bearish,
        supertrend_adx=supertrend_adx,
        kalman_favorable=kalman_favorable,
    )


def _checks_to_score(checks: ConfluenceChecks) -> int:
    """Cada check vale peso igual; mínimo 2 checks para score > 30."""
    fields = list(ConfluenceChecks.model_fields.keys())
    true_count = sum(1 for f in fields if getattr(checks, f))
    if true_count <= 1:
        return min(true_count * 10, 15)
    return min(100, round(true_count / len(fields) * 100))


def _enrich_indicators(
    market_state: MarketState,
    tf: str,
) -> dict[str, Any]:
    ind = dict(_get_tf_indicators(market_state, tf))
    snapshot = market_state.timeframes.get(tf)
    if snapshot:
        ind["_last_price"] = market_state.last_price
        ind["_volume_ratio"] = snapshot.ohlcv_summary.get("volume_ratio", 1.0)
    return ind


def score_long(
    market_state: MarketState,
    *,
    primary_tf: str = DEFAULT_PRIMARY_TF,
    trend_tf: str = DEFAULT_TREND_TF,
) -> ConfluenceScore:
    """Pontua setup LONG com base no TF primário filtrado por TF de tendência."""
    primary = _enrich_indicators(market_state, primary_tf)
    trend = _enrich_indicators(market_state, trend_tf)
    checks = _eval_long_checks(primary, trend)
    return ConfluenceScore(score=_checks_to_score(checks), checks=checks)


def score_short(
    market_state: MarketState,
    *,
    primary_tf: str = DEFAULT_PRIMARY_TF,
    trend_tf: str = DEFAULT_TREND_TF,
) -> ConfluenceScore:
    """Pontua setup SHORT — espelho do LONG."""
    primary = _enrich_indicators(market_state, primary_tf)
    trend = _enrich_indicators(market_state, trend_tf)
    checks = _eval_short_checks(primary, trend)
    return ConfluenceScore(score=_checks_to_score(checks), checks=checks)


def compute_confluence(
    market_state: MarketState,
    *,
    primary_tf: str = DEFAULT_PRIMARY_TF,
    trend_tf: str = DEFAULT_TREND_TF,
) -> ConfluenceResult:
    """Calcula confluência long/short e recomendação preliminar."""
    long_result = score_long(market_state, primary_tf=primary_tf, trend_tf=trend_tf)
    short_result = score_short(market_state, primary_tf=primary_tf, trend_tf=trend_tf)

    long_score = long_result.score
    short_score = short_result.score

    if long_score >= short_score + SCORE_GAP_FOR_RECOMMENDATION and long_score >= 40:
        recommendation: Literal["LONG", "SHORT", "NEUTRAL"] = "LONG"
    elif short_score >= long_score + SCORE_GAP_FOR_RECOMMENDATION and short_score >= 40:
        recommendation = "SHORT"
    else:
        recommendation = "NEUTRAL"

    return ConfluenceResult(
        long_score=long_score,
        short_score=short_score,
        long_checks={k: v for k, v in long_result.checks.model_dump().items()},
        short_checks={k: v for k, v in short_result.checks.model_dump().items()},
        recommendation=recommendation,
    )
