"""Validação de níveis e alavancagem definidos pela IA."""

from __future__ import annotations

from src.config.runtime_config import BotRuntimeConfig
from src.models.schemas import TakeProfitLevel, TradeDecision, TradeDirection
from src.strategies.liquidation_safety import (
    clamp_stop_loss_to_liquidation,
    validate_stop_loss_vs_liquidation,
)

REQUIRED_TP_COUNT = 3
MIN_TP1_RR_FLOOR = 1.0


def effective_min_tp1_rr(runtime: BotRuntimeConfig, *, sniper: bool = False) -> float:
    """R:R mínimo no TP1 — piso 1.0; SMC só quando não é Sniper ATR."""
    configured = max(MIN_TP1_RR_FLOOR, runtime.scanner.quality.min_tp1_rr)
    if sniper:
        return configured
    pipeline = runtime.strategies.scanner
    if runtime.smc.enabled and pipeline.smc:
        configured = max(configured, runtime.smc.min_tp1_rr)
    return configured


def shift_execution_levels(
    planned_entry: float,
    actual_entry: float,
    stop_loss: float,
    take_profit_prices: list[float],
) -> tuple[float, list[float]]:
    """Desloca SL/TPs pelo delta entre preço planejado (IMBA) e fill real."""
    if planned_entry <= 0 or actual_entry <= 0:
        return stop_loss, list(take_profit_prices)
    delta = actual_entry - planned_entry
    if abs(delta) < 1e-12:
        return stop_loss, list(take_profit_prices)
    return stop_loss + delta, [price + delta for price in take_profit_prices]


def levels_from_prices(
    prices: list[float],
    entry_price: float,
    stop_loss: float,
) -> list[TakeProfitLevel]:
    """Converte preços de referência em TakeProfitLevel com R:R."""
    risk = abs(entry_price - stop_loss)
    out: list[TakeProfitLevel] = []
    for price in prices[:REQUIRED_TP_COUNT]:
        reward = abs(price - entry_price)
        pct = (reward / entry_price * 100.0) if entry_price else 0.0
        rr = (reward / risk) if risk > 0 else 0.0
        out.append(
            TakeProfitLevel(price=price, percentage=round(pct, 4), risk_reward=round(rr, 4))
        )
    return out


def apply_execution_levels(
    decision: TradeDecision,
    *,
    symbol: str,
    direction: TradeDirection,
    entry_price: float,
    stop_loss: float,
    take_profit_prices: list[float],
    execution_timeframe: str,
) -> TradeDecision:
    """Sobrescreve entry/SL/TPs com níveis do TF de execução (ex.: IMBA 5m)."""
    tps = levels_from_prices(take_profit_prices, entry_price, stop_loss)
    return decision.model_copy(
        update={
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profits": tps,
            "execution_timeframe": execution_timeframe,
        }
    )


def merge_execution_levels(
    decision: TradeDecision,
    *,
    symbol: str | None = None,
    direction: TradeDirection | None = None,
    entry_price: float | None = None,
    stop_loss: float | None = None,
    take_profit_prices: list[float] | None = None,
) -> TradeDecision:
    """Preenche apenas campos que a IA não definiu, usando referência IMBA/Telegram."""
    updates: dict = {}

    if symbol and not decision.symbol:
        updates["symbol"] = symbol
    if direction and not decision.direction:
        updates["direction"] = direction
    if entry_price is not None and decision.entry_price is None:
        updates["entry_price"] = entry_price
    if stop_loss is not None and decision.stop_loss is None:
        updates["stop_loss"] = stop_loss

    entry = updates.get("entry_price", decision.entry_price)
    sl = updates.get("stop_loss", decision.stop_loss)

    if len(decision.take_profits) < REQUIRED_TP_COUNT and take_profit_prices and entry and sl:
        updates["take_profits"] = levels_from_prices(take_profit_prices, entry, sl)

    if not updates:
        return decision
    return decision.model_copy(update=updates)


def validate_execution_decision(
    decision: TradeDecision,
    runtime: BotRuntimeConfig,
    *,
    require_weighted_expectancy: bool = True,
    sniper_levels: bool = False,
) -> TradeDecision:
    """Valida alavancagem e TPs escolhidos pela IA; rejeita se incoerentes."""
    if not decision.approved:
        return decision

    errors: list[str] = []

    if decision.leverage is None:
        errors.append("IA não definiu alavancagem")
    else:
        capped = min(
            max(int(decision.leverage), runtime.risk.min_leverage),
            runtime.risk.max_leverage,
        )
        if capped != decision.leverage:
            decision = decision.model_copy(update={"leverage": capped})

    if decision.entry_price is None or decision.stop_loss is None or decision.direction is None:
        errors.append("Níveis de execução incompletos")
        return _reject(decision, errors)

    if len(decision.take_profits) < REQUIRED_TP_COUNT:
        errors.append(
            f"IA deve validar {REQUIRED_TP_COUNT} TPs (recebidos {len(decision.take_profits)})"
        )
    else:
        geom_err = _validate_geometry(
            decision.direction,
            decision.entry_price,
            decision.stop_loss,
            [tp.price for tp in decision.take_profits[:REQUIRED_TP_COUNT]],
            min_tp1_rr=effective_min_tp1_rr(runtime, sniper=sniper_levels),
        )
        if geom_err:
            errors.append(geom_err)

    if errors:
        return _reject(decision, errors)

    if require_weighted_expectancy:
        exp_err = _validate_weighted_expectancy(decision, runtime)
        if exp_err:
            return _reject(decision, [exp_err])

    return decision


def _validate_weighted_expectancy(
    decision: TradeDecision,
    runtime: BotRuntimeConfig,
) -> str | None:
    """Garante que 1 win cobre N losses no mesmo risco %."""
    if (
        decision.entry_price is None
        or decision.stop_loss is None
        or len(decision.take_profits) < REQUIRED_TP_COUNT
    ):
        return None
    entry = decision.entry_price
    sl = decision.stop_loss
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    weights = tuple(p / 100.0 for p in runtime.imba.tp_close_tuple())
    rrs = [
        abs(tp.price - entry) / risk for tp in decision.take_profits[:REQUIRED_TP_COUNT]
    ]
    expectancy = sum(w * r for w, r in zip(weights, rrs))
    target = float(runtime.risk.wins_cover_losses)
    if expectancy < target:
        return (
            f"R:R ponderado {expectancy:.2f} < {target:.0f} "
            f"(1 win deve cobrir {int(target)} losses)"
        )
    return None


def validate_liquidation_safe_levels(
    direction: TradeDirection,
    entry: float,
    stop_loss: float,
    liquidation_price: float,
    buffer_pct: float,
) -> str | None:
    """Gate obrigatório: SL deve disparar antes da liquidação."""
    return validate_stop_loss_vs_liquidation(
        direction, entry, stop_loss, liquidation_price, buffer_pct
    )


def apply_liquidation_safe_stop_loss(
    direction: TradeDirection,
    entry: float,
    stop_loss: float,
    liquidation_price: float,
    buffer_pct: float,
) -> tuple[float | None, str | None]:
    """
    Ajusta SL para zona segura vs liquidação.

    Retorna (sl, erro). sl=None se não for possível colocar SL seguro.
    """
    adjusted, clamped, reject = clamp_stop_loss_to_liquidation(
        direction, entry, stop_loss, liquidation_price, buffer_pct
    )
    if reject:
        return None, reject
    if clamped:
        return adjusted, None
    err = validate_stop_loss_vs_liquidation(
        direction, entry, adjusted, liquidation_price, buffer_pct
    )
    return (None, err) if err else (adjusted, None)


def _validate_geometry(
    direction: TradeDirection,
    entry: float,
    stop_loss: float,
    tp_prices: list[float],
    *,
    min_tp1_rr: float = MIN_TP1_RR_FLOOR,
) -> str | None:
    risk = abs(entry - stop_loss)
    if risk <= 0:
        return "Distância entrada-SL inválida"

    if direction == TradeDirection.LONG:
        if stop_loss >= entry:
            return "SL deve ficar abaixo da entrada (LONG)"
        for i, tp in enumerate(tp_prices):
            if tp <= entry:
                return f"TP{i + 1} deve ficar acima da entrada (LONG)"
        for i in range(len(tp_prices) - 1):
            if tp_prices[i] >= tp_prices[i + 1]:
                return "TPs LONG devem ser estritamente crescentes"
        reward_tp1 = tp_prices[0] - entry
    else:
        if stop_loss <= entry:
            return "SL deve ficar acima da entrada (SHORT)"
        for i, tp in enumerate(tp_prices):
            if tp >= entry:
                return f"TP{i + 1} deve ficar abaixo da entrada (SHORT)"
        for i in range(len(tp_prices) - 1):
            if tp_prices[i] <= tp_prices[i + 1]:
                return "TPs SHORT devem ser estritamente decrescentes"
        reward_tp1 = entry - tp_prices[0]

    if reward_tp1 / risk + 1e-9 < min_tp1_rr:
        return f"TP1 com R:R {reward_tp1 / risk:.2f} < {min_tp1_rr} — níveis insuficientes"
    return None


def _reject(decision: TradeDecision, errors: list[str]) -> TradeDecision:
    reason = "; ".join(errors)
    llm_conf = decision.llm_confidence if decision.llm_confidence is not None else decision.confidence
    return decision.model_copy(
        update={
            "approved": False,
            "confidence": min(decision.confidence, 0.5),
            "llm_confidence": llm_conf,
            "bias": reason,
            "ai_analysis": reason,
        }
    )
