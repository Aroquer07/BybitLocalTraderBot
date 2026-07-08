"""Filtros objetivos do scanner — reduz entradas fracas antes da LLM e do P(win)."""

from __future__ import annotations

from dataclasses import dataclass

from src.config.runtime_config import ScannerQualityConfig
from src.models.schemas import (
    ConfluenceResult,
    ImbaAnalysis,
    MarketState,
    TradeDirection,
)
from src.strategies.imba_algo import ImbaSignal
from src.strategies.market_patterns import (
    best_pattern_for_direction,
    collect_patterns_from_state,
)
from src.strategies.win_probability import WinProbabilityResult

# Blacklist estática — pares ilíquidos / alto slippage histórico
SYMBOL_BLACKLIST: frozenset[str] = frozenset({
    "BTWUSDT",
    "XANUSDT",
    "AVAUSDT",
    "SOONUSDT",
})


def normalize_symbol_key(symbol: str) -> str:
    """Normaliza símbolo para comparação com blacklist (ex: AVA/USDT → AVAUSDT)."""
    s = symbol.upper().strip()
    if ":" in s:
        s = s.split(":")[0]
    return s.replace("/", "")


def is_symbol_blacklisted(symbol: str) -> tuple[bool, str]:
    """Retorna (bloqueado, motivo) se o par está na blacklist estática."""
    key = normalize_symbol_key(symbol)
    if key in SYMBOL_BLACKLIST:
        return True, f"Par na blacklist ilíquida: {key}"
    return False, ""


@dataclass(frozen=True)
class ScannerFilterVerdict:
    passed: bool
    reason: str = ""


def _direction_side_score(
    conf: ConfluenceResult | None,
    direction: TradeDirection,
) -> tuple[int, int]:
    if conf is None:
        return 0, 0
    if direction == TradeDirection.LONG:
        return conf.long_score, conf.short_score
    return conf.short_score, conf.long_score


def _kalman_conflicts(
    direction: TradeDirection,
    *,
    kalman_signal: str | None,
    kalman_reversal: str | None,
    reject_reversal: bool,
) -> str | None:
    if kalman_signal:
        ks = kalman_signal.lower()
        if direction == TradeDirection.LONG and ks == "bearish":
            return "Kalman bearish contra LONG"
        if direction == TradeDirection.SHORT and ks == "bullish":
            return "Kalman bullish contra SHORT"
    if reject_reversal and kalman_reversal:
        kr = kalman_reversal.lower()
        if direction == TradeDirection.LONG and kr == "bearish":
            return "Kalman reversal bearish contra LONG"
        if direction == TradeDirection.SHORT and kr == "bullish":
            return "Kalman reversal bullish contra SHORT"
    return None


def evaluate_scanner_setup(
    *,
    direction: TradeDirection,
    analysis: ImbaAnalysis,
    imba_signal: ImbaSignal,
    market_state: MarketState,
    filters: ScannerQualityConfig,
) -> ScannerFilterVerdict:
    """Checagens Python baratas — evita gastar LLM em setups já inválidos."""
    blocked, reason = is_symbol_blacklisted(market_state.symbol)
    if blocked:
        return ScannerFilterVerdict(False, reason)

    if analysis.confidence_score < filters.min_imba_confidence:
        return ScannerFilterVerdict(
            False,
            f"Setup score {analysis.confidence_score:.0%} < {filters.min_imba_confidence:.0%}",
        )

    if filters.require_imba_tf_align:
        fresh = analysis.fresh_signal_direction
        aligned = analysis.aligned_direction
        if fresh and aligned and fresh != aligned:
            return ScannerFilterVerdict(
                False,
                f"IMBA diverge: sinal={fresh.value} tendência={aligned.value}",
            )

    conf = market_state.confluence
    if filters.require_confluence_align and conf:
        rec = conf.recommendation
        if rec == "NEUTRAL":
            return ScannerFilterVerdict(False, "Confluência NEUTRAL")
        if rec != direction.value:
            return ScannerFilterVerdict(
                False,
                f"Confluência {rec} ≠ direção {direction.value}",
            )

    side_score, opp_score = _direction_side_score(conf, direction)
    if side_score < filters.min_confluence_score:
        return ScannerFilterVerdict(
            False,
            f"Confluência {direction.value}={side_score} < {filters.min_confluence_score}",
        )
    if side_score < opp_score + filters.min_confluence_spread:
        return ScannerFilterVerdict(
            False,
            f"Confluência fraca: {side_score} vs oposto {opp_score}",
        )

    entry = imba_signal.entry_price
    sl = imba_signal.stop_loss
    risk = abs(entry - sl)
    if risk <= 0:
        return ScannerFilterVerdict(False, "SL inválido no IMBA")

    tp1 = imba_signal.take_profits[0]
    reward = abs(tp1 - entry)
    tp1_rr = reward / risk
    if tp1_rr + 1e-9 < filters.min_tp1_rr:
        return ScannerFilterVerdict(
            False,
            f"TP1 R:R {tp1_rr:.2f} < {filters.min_tp1_rr}",
        )

    exec_tf = market_state.timeframes.get("5m") or market_state.primary_snapshot
    primary = market_state.primary_snapshot
    atr_pct = 0.5
    if primary and primary.indicators.get("atr_14") and entry > 0:
        atr_pct = float(primary.indicators["atr_14"]) / entry * 100.0
    sl_atr = risk / (entry * atr_pct / 100.0) if atr_pct > 0 else 99.0
    if sl_atr < filters.min_sl_atr_multiple:
        return ScannerFilterVerdict(
            False,
            f"SL muito apertado ({sl_atr:.2f}× ATR < {filters.min_sl_atr_multiple})",
        )
    if sl_atr > filters.max_sl_atr_multiple:
        return ScannerFilterVerdict(
            False,
            f"SL muito largo ({sl_atr:.2f}× ATR > {filters.max_sl_atr_multiple})",
        )

    volume_ratio = 1.0
    if exec_tf and exec_tf.ohlcv_summary:
        volume_ratio = float(exec_tf.ohlcv_summary.get("volume_ratio") or 1.0)
    if volume_ratio < filters.min_volume_ratio:
        return ScannerFilterVerdict(
            False,
            f"Volume baixo ({volume_ratio:.2f} < {filters.min_volume_ratio})",
        )

    kalman_signal = None
    kalman_reversal = None
    if primary and primary.indicators:
        kalman_signal = primary.indicators.get("kalman_signal")
        kalman_reversal = primary.indicators.get("kalman_reversal")
    if filters.require_kalman_align:
        conflict = _kalman_conflicts(
            direction,
            kalman_signal=str(kalman_signal) if kalman_signal else None,
            kalman_reversal=str(kalman_reversal) if kalman_reversal else None,
            reject_reversal=filters.reject_kalman_reversal_against,
        )
        if conflict:
            return ScannerFilterVerdict(False, conflict)

    if filters.require_market_pattern:
        patterns = collect_patterns_from_state(
            market_state.timeframes,
            filters.pattern_timeframes,
        )
        best = best_pattern_for_direction(
            patterns,
            direction,
            min_historical_winrate=filters.min_pattern_historical_winrate,
            min_confidence=filters.min_pattern_match_confidence,
        )
        if best is None:
            names = ", ".join(sorted({p.name for p in patterns})) or "nenhum"
            return ScannerFilterVerdict(
                False,
                (
                    f"Sem padrão ≥{filters.min_pattern_historical_winrate:.0%} "
                    f"alinhado ({names})"
                ),
            )

    return ScannerFilterVerdict(True)


def effective_pwin_threshold(
    result: WinProbabilityResult,
    base_threshold: float,
    filters: ScannerQualityConfig,
) -> float:
    """Exige P(win) maior quando histórico do padrão é escasso ou ruim."""
    bump = 0.0
    if result.reliability == "low":
        bump = filters.pwin_reliability_bump_low
    elif result.reliability == "medium":
        bump = filters.pwin_reliability_bump_medium
    if result.historical_n >= 3 and result.historical < 0.50:
        bump += filters.pwin_bad_historical_bump
    return min(0.95, base_threshold + bump)
