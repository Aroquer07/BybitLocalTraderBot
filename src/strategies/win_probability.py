"""
Estimativa objetiva de P(win) — técnico, microestrutura, setup e histórico.

Não é previsão garantida: combina features Python calibráveis com win rate
bayesiano do journal para trades com perfil similar.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field

from src.config.runtime_config import LearningConfig, ScannerQualityConfig
from src.models.schemas import (
    ImbaAnalysis,
    MarketState,
    StoredTrade,
    TradeDecision,
    TradeDirection,
    TradeSource,
    TradeStatus,
)

# Pesos do blend final (redistribuídos se histórico escasso)
_WEIGHT_TECHNICAL = 0.35
_WEIGHT_MARKET = 0.25
_WEIGHT_SETUP = 0.20
_WEIGHT_HISTORICAL = 0.20

_BAYES_ALPHA0 = 2.0
_BAYES_BETA0 = 2.0


class ProbabilityFeatures(BaseModel):
    """Features persistidas no journal para calibração futura."""

    imba_score: float = Field(ge=0.0, le=1.0)
    confluence_score: int = Field(ge=0, le=100)
    volume_ratio: float = Field(ge=0.0)
    spread_pct: float = Field(ge=0.0)
    ob_imbalance: float = Field(description="-1 a 1; + = mais bids")
    atr_pct: float = Field(ge=0.0, description="ATR14 / preço * 100")
    tp1_rr: float = Field(ge=0.0)
    sl_atr_multiple: float = Field(ge=0.0)
    direction: TradeDirection
    source: TradeSource
    symbol: str
    leverage: int | None = Field(default=None, ge=1, le=125)
    kalman_trend_strength: float | None = None
    kalman_signal: str | None = None
    kalman_reversal: str | None = None
    pattern_name: str | None = None
    pattern_winrate: float | None = Field(default=None, ge=0.0, le=1.0)
    pattern_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    llm_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    predicted_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    entry_strategy: str | None = None


class WinProbabilityResult(BaseModel):
    """Resultado da estimativa com breakdown transparente."""

    probability: float = Field(ge=0.0, le=1.0)
    technical: float = Field(ge=0.0, le=1.0)
    market: float = Field(ge=0.0, le=1.0)
    setup: float = Field(ge=0.0, le=1.0)
    historical: float = Field(ge=0.0, le=1.0)
    historical_n: int = Field(ge=0)
    reliability: str = Field(description="low | medium | high")
    breakdown: str = Field(description="Resumo curto para UI")
    features: ProbabilityFeatures


def probability_timeframes(runtime) -> list[str]:
    """TFs mínimos para confluência + IMBA no scanner."""
    from src.strategies.imba_analyzer import imba_analysis_timeframes

    tfs = set(imba_analysis_timeframes(runtime))
    tfs.add(runtime.timeframes.primary)
    tfs.add(runtime.timeframes.trend)
    tfs.add(runtime.timeframes.execution)
    return list(tfs)


def _score_kalman_alignment(
    direction: TradeDirection,
    kalman_signal: str | None,
    kalman_reversal: str | None,
) -> float:
    """Penaliza quando Kalman contradiz a direção do trade."""
    score = 0.75
    if kalman_signal:
        ks = kalman_signal.lower()
        if direction == TradeDirection.LONG:
            if ks == "bullish":
                score = 1.0
            elif ks == "bearish":
                score = 0.35
        elif ks == "bullish":
            score = 0.35
        else:
            score = 1.0
    if kalman_reversal:
        kr = kalman_reversal.lower()
        if direction == TradeDirection.LONG and kr == "bearish":
            score = min(score, 0.4)
        if direction == TradeDirection.SHORT and kr == "bullish":
            score = min(score, 0.4)
    return score


def _score_market_pattern(winrate: float | None, confidence: float | None) -> float:
    if winrate is None or confidence is None:
        return 0.5
    return min(0.95, winrate * confidence + 0.08)


def _score_spread(spread_pct: float) -> float:
    if spread_pct <= 0:
        return 0.7
    if spread_pct <= 0.03:
        return 1.0
    if spread_pct <= 0.08:
        return 0.85
    if spread_pct <= 0.15:
        return 0.65
    if spread_pct <= 0.30:
        return 0.45
    return 0.25


def _score_volume(volume_ratio: float) -> float:
    if volume_ratio <= 0:
        return 0.4
    if volume_ratio < 0.7:
        return 0.45
    if volume_ratio < 1.0:
        return 0.55 + (volume_ratio - 0.7) * 0.5
    if volume_ratio <= 2.0:
        return 0.7 + (volume_ratio - 1.0) * 0.25
    if volume_ratio <= 3.5:
        return 0.95 - (volume_ratio - 2.0) * 0.1
    return 0.75


def _score_volatility(atr_pct: float) -> float:
    if atr_pct <= 0:
        return 0.5
    if atr_pct < 0.15:
        return 0.55
    if atr_pct <= 0.8:
        return 0.65 + min(atr_pct, 0.5) * 0.5
    if atr_pct <= 1.5:
        return 0.85
    if atr_pct <= 3.0:
        return 0.7 - (atr_pct - 1.5) * 0.08
    return 0.45


def _score_sl_atr(multiple: float) -> float:
    if multiple <= 0:
        return 0.3
    if multiple < 0.4:
        return 0.35
    if multiple <= 2.5:
        return 0.55 + min(multiple, 2.0) * 0.15
    if multiple <= 4.0:
        return 0.85 - (multiple - 2.5) * 0.12
    return 0.5


def _score_tp_rr(rr: float) -> float:
    if rr <= 0:
        return 0.35
    return min(0.35 + rr * 0.22, 0.95)


def _orderbook_alignment(direction: TradeDirection, imbalance: float) -> float:
    if direction == TradeDirection.LONG:
        return 0.5 + imbalance * 0.5
    return 0.5 - imbalance * 0.5


def _imba_bucket(score: float) -> str:
    step = 0.1
    bucket = math.floor(score / step) * step
    return f"{bucket:.1f}"


def _confluence_bucket(score: int) -> str:
    if score < 40:
        return "low"
    if score < 60:
        return "mid"
    if score < 80:
        return "high"
    return "very_high"


def _historical_win_rate(
    closed: list[StoredTrade],
    features: ProbabilityFeatures,
) -> tuple[float, int]:
    """Win rate bayesiano para trades com perfil parecido."""
    imba_b = _imba_bucket(features.imba_score)
    conf_b = _confluence_bucket(features.confluence_score)

    matched = [
        t
        for t in closed
        if t.source == features.source
        and t.direction == features.direction
        and t.probability_features
        and _imba_bucket(float(t.probability_features.get("imba_score", 0))) == imba_b
        and _confluence_bucket(int(t.probability_features.get("confluence_score", 0)))
        == conf_b
    ]
    if features.entry_strategy is not None:
        matched = [
            t
            for t in matched
            if (t.probability_features or {}).get("entry_strategy")
            == features.entry_strategy
        ]

    wins = sum(1 for t in matched if (t.pnl_pct or 0) > 0)
    loss_weight = sum(
        min(2.5, max(1.0, abs(t.pnl_pct or 0)))
        for t in matched
        if (t.pnl_pct or 0) <= 0
    )
    alpha = _BAYES_ALPHA0 + wins
    beta = _BAYES_BETA0 + loss_weight
    return alpha / (alpha + beta), len(matched)


def _blend_weights(historical_n: int) -> tuple[float, float, float, float]:
    w_hist = _WEIGHT_HISTORICAL
    if historical_n < 5:
        w_hist = 0.05
    elif historical_n < 15:
        w_hist = 0.12
    elif historical_n >= 30:
        w_hist = 0.30

    rest = 1.0 - w_hist
    scale = rest / (_WEIGHT_TECHNICAL + _WEIGHT_MARKET + _WEIGHT_SETUP)
    return (
        _WEIGHT_TECHNICAL * scale,
        _WEIGHT_MARKET * scale,
        _WEIGHT_SETUP * scale,
        w_hist,
    )


def _reliability_label(n: int) -> str:
    if n >= 20:
        return "high"
    if n >= 8:
        return "medium"
    return "low"


def extract_probability_features(
    decision: TradeDecision,
    imba_analysis: ImbaAnalysis,
    market_state: MarketState,
    *,
    source: TradeSource,
    entry_strategy: str | None = None,
) -> ProbabilityFeatures:
    direction = decision.direction or TradeDirection.LONG
    entry = decision.entry_price or market_state.last_price
    sl = decision.stop_loss or entry

    conf = market_state.confluence
    if direction == TradeDirection.LONG:
        confluence_score = conf.long_score if conf else 0
    else:
        confluence_score = conf.short_score if conf else 0

    exec_tf = market_state.timeframes.get("5m") or market_state.primary_snapshot
    primary = market_state.primary_snapshot
    exec_snap = market_state.timeframes.get("5m") or primary

    volume_ratio = 1.0
    if exec_snap and exec_snap.ohlcv_summary:
        volume_ratio = float(exec_snap.ohlcv_summary.get("volume_ratio") or 1.0)

    atr_pct = 0.5
    if primary and primary.indicators.get("atr_14") and entry > 0:
        atr_pct = float(primary.indicators["atr_14"]) / entry * 100.0

    ob = market_state.orderbook_snapshot or {}
    best_bid = ob.get("best_bid")
    best_ask = ob.get("best_ask")
    spread_pct = 0.05
    if best_bid and best_ask and entry > 0:
        spread_pct = (float(best_ask) - float(best_bid)) / entry * 100.0
    elif ob.get("spread") and entry > 0:
        spread_pct = float(ob["spread"]) / entry * 100.0

    imbalance = float(ob.get("imbalance") or 0.0)

    tp1_rr = 0.0
    if decision.take_profits:
        tp1_rr = float(decision.take_profits[0].risk_reward or 0.0)
    elif entry and sl:
        risk = abs(entry - sl)
        if risk > 0 and decision.take_profits:
            tp1_rr = abs(decision.take_profits[0].price - entry) / risk

    sl_dist = abs(entry - sl)
    sl_atr = sl_dist / (entry * atr_pct / 100.0) if atr_pct > 0 else 1.0

    kalman_strength = None
    kalman_signal = None
    kalman_reversal = None
    if primary and primary.indicators:
        kalman_strength = primary.indicators.get("kalman_trend_strength")
        kalman_signal = primary.indicators.get("kalman_signal")
        kalman_reversal = primary.indicators.get("kalman_reversal")

    from src.strategies.market_patterns import (
        best_pattern_for_direction,
        collect_patterns_from_state,
    )

    patterns = collect_patterns_from_state(market_state.timeframes, ["5m", "15m"])
    best_pat = best_pattern_for_direction(patterns, direction)
    pattern_name = best_pat.name if best_pat else None
    pattern_winrate = best_pat.historical_winrate if best_pat else None
    pattern_confidence = best_pat.confidence if best_pat else None

    return ProbabilityFeatures(
        imba_score=imba_analysis.confidence_score,
        confluence_score=confluence_score,
        volume_ratio=round(volume_ratio, 4),
        spread_pct=round(spread_pct, 6),
        ob_imbalance=round(imbalance, 4),
        atr_pct=round(atr_pct, 4),
        tp1_rr=round(tp1_rr, 4),
        sl_atr_multiple=round(sl_atr, 4),
        direction=direction,
        source=source,
        symbol=decision.symbol or market_state.symbol,
        leverage=decision.leverage,
        kalman_trend_strength=kalman_strength,
        kalman_signal=kalman_signal,
        kalman_reversal=kalman_reversal,
        pattern_name=pattern_name,
        pattern_winrate=pattern_winrate,
        pattern_confidence=pattern_confidence,
        llm_confidence=decision.llm_confidence or decision.confidence,
        entry_strategy=entry_strategy,
    )


def compute_win_probability(
    features: ProbabilityFeatures,
    closed_trades: list[StoredTrade] | None = None,
    learning_config: LearningConfig | None = None,
) -> WinProbabilityResult:
    closed = [
        t
        for t in (closed_trades or [])
        if t.status == TradeStatus.CLOSED and t.probability_features
    ]

    technical = (
        features.imba_score * 0.40
        + (features.confluence_score / 100.0) * 0.35
        + _score_kalman_alignment(
            features.direction,
            features.kalman_signal,
            features.kalman_reversal,
        )
        * 0.25
    )

    market = (
        _score_spread(features.spread_pct) * 0.30
        + _score_volume(features.volume_ratio) * 0.35
        + _orderbook_alignment(features.direction, features.ob_imbalance) * 0.20
        + _score_volatility(features.atr_pct) * 0.15
    )

    setup = (
        _score_tp_rr(features.tp1_rr) * 0.40
        + _score_sl_atr(features.sl_atr_multiple) * 0.30
        + _score_market_pattern(features.pattern_winrate, features.pattern_confidence)
        * 0.30
    )

    historical, historical_n = _historical_win_rate(closed, features)

    wt, wm, ws, wh = _blend_weights(historical_n)
    raw = technical * wt + market * wm + setup * ws + historical * wh

    if historical_n >= 3 and historical < 0.50:
        raw *= 0.65
    elif historical_n >= 5 and historical < 0.60:
        raw *= 0.80

    from src.services.trade_learning import pattern_probability_adjustment

    feat_dict = features.model_dump(mode="json")
    mult, adj_note = pattern_probability_adjustment(
        feat_dict,
        closed,
        learning_config,
    )
    if mult != 1.0:
        raw *= mult

    probability = max(0.05, min(0.95, round(raw, 4)))

    reliability = _reliability_label(historical_n)
    breakdown = (
        f"tec {technical:.0%}·merc {market:.0%}·setup {setup:.0%}·"
        f"hist {historical:.0%} (n={historical_n})"
    )
    if features.pattern_name:
        breakdown += f"·{features.pattern_name} {features.pattern_winrate:.0%}"
    if adj_note:
        breakdown += f"·{adj_note}"

    return WinProbabilityResult(
        probability=probability,
        technical=round(technical, 4),
        market=round(market, 4),
        setup=round(setup, 4),
        historical=round(historical, 4),
        historical_n=historical_n,
        reliability=reliability,
        breakdown=breakdown,
        features=features,
    )


def _patch_formatted_probability(formatted: str, probability: float, breakdown: str) -> str:
    prob_int = int(round(probability * 100))
    line = f"📌 Probabilidade: {prob_int}%"
    if not formatted:
        return line
    lines = formatted.split("\n")
    patched = False
    for i, row in enumerate(lines):
        if row.startswith("📌 Probabilidade:"):
            lines[i] = line
            patched = True
            break
    if not patched:
        # Insere após viés se existir
        for i, row in enumerate(lines):
            if row.startswith("📈 Viés:"):
                lines.insert(i + 1, line)
                patched = True
                break
    if not patched:
        lines.append(line)
    return "\n".join(lines)


def apply_win_probability(
    decision: TradeDecision,
    result: WinProbabilityResult,
    *,
    confidence_threshold: float,
) -> TradeDecision:
    """Substitui confidence LLM pela P(win) objetiva; pode rejeitar no kill switch."""
    llm_confidence = decision.confidence
    probability = result.probability
    approved = decision.approved

    if approved and probability < confidence_threshold:
        approved = False

    from src.utils.formatters import build_formatted_output_from_decision

    base_formatted = decision.formatted_output
    if not base_formatted or not base_formatted.strip().startswith("🚨"):
        base_formatted = build_formatted_output_from_decision(decision)

    formatted = _patch_formatted_probability(
        base_formatted,
        probability,
        result.breakdown,
    )

    note_suffix = f" | P(win)={probability:.0%} [{result.reliability}] llm={llm_confidence:.0%}"
    bias = decision.bias
    if bias and "P(win)=" not in bias:
        bias = f"{bias}{note_suffix}"
    elif not bias:
        bias = f"Score objetivo{note_suffix}"

    return decision.model_copy(
        update={
            "approved": approved,
            "confidence": probability,
            "llm_confidence": llm_confidence,
            "probability_breakdown": result.model_dump(mode="json"),
            "formatted_output": formatted,
            "bias": bias,
        }
    )


def enrich_decision_with_win_probability(
    decision: TradeDecision,
    imba_analysis: ImbaAnalysis,
    market_state: MarketState,
    *,
    source: TradeSource,
    confidence_threshold: float,
    closed_trades: list[StoredTrade] | None = None,
    learning_config: LearningConfig | None = None,
    quality_config: ScannerQualityConfig | None = None,
    entry_strategy: str | None = None,
) -> TradeDecision:
    if not decision.approved or decision.direction is None:
        return decision

    features = extract_probability_features(
        decision,
        imba_analysis,
        market_state,
        source=source,
        entry_strategy=entry_strategy,
    )
    result = compute_win_probability(
        features,
        closed_trades,
        learning_config=learning_config,
    )
    enriched_features = result.features.model_copy(
        update={
            "llm_confidence": decision.llm_confidence if decision.llm_confidence is not None else decision.confidence,
            "predicted_probability": result.probability,
        }
    )
    result = result.model_copy(update={"features": enriched_features})
    effective_threshold = confidence_threshold
    if quality_config is not None:
        from src.strategies.scanner_filters import effective_pwin_threshold

        effective_threshold = effective_pwin_threshold(
            result, confidence_threshold, quality_config
        )
    out = apply_win_probability(
        decision,
        result,
        confidence_threshold=effective_threshold,
    )
    breakdown = dict(out.probability_breakdown or {})
    breakdown["effective_threshold"] = effective_threshold
    return out.model_copy(
        update={
            "confidence_threshold": effective_threshold,
            "probability_breakdown": breakdown,
        }
    )
