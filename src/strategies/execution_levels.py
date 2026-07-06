"""Resolve níveis de execução: Fibonacci (scalp) ou SMC + IMBA (sinal/direção)."""

from __future__ import annotations

from src.config.runtime_config import BotRuntimeConfig
from src.models.schemas import ImbaAnalysis, TradeDirection
from src.strategies.fib_execution_levels import compute_fib_scalp_levels
from src.strategies.imba_algo import ImbaAlgoConfig, ImbaSignal
from src.strategies.imba_analyzer import pick_execution_levels
from src.strategies.smc_levels import SMCLevels, compute_smc_levels
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _weighted_rr_meets_target(
  smc: SMCLevels,
  *,
  wins_cover_losses: int,
  tp_close_pcts: tuple[float, float, float],
) -> bool:
    weights = tuple(p / 100.0 for p in tp_close_pcts)
    risk = abs(smc.entry - smc.stop_loss) if smc.stop_loss != smc.entry else 0
    rrs = [
        abs(tp - smc.entry) / risk if risk > 0 else 0
        for tp in smc.take_profits[:3]
    ]
    expectancy = sum(w * r for w, r in zip(weights, rrs))
    return expectancy >= float(wins_cover_losses)


def _apply_fib_levels(
    signal: ImbaSignal,
    symbol: str,
    ohlcv_by_tf: dict[str, list[list[float]]],
    runtime: BotRuntimeConfig,
) -> tuple[ImbaSignal | None, str]:
    exec_tf = runtime.timeframes.execution
    structure_tf = runtime.imba.fib_structure_timeframe
    ohlcv = ohlcv_by_tf.get(structure_tf) or ohlcv_by_tf.get(exec_tf)
    if not ohlcv:
        return None, "OHLCV estrutura fib ausente"

    fib = None
    used_tf = exec_tf
    # Prioriza TF de execução (5m) — igual ao gráfico do usuário
    for tf in (exec_tf, structure_tf):
        tf_ohlcv = ohlcv_by_tf.get(tf)
        if not tf_ohlcv:
            continue
        fib = compute_fib_scalp_levels(
            tf_ohlcv,
            signal.side,
            signal.entry_price,
            lookback=runtime.imba.fib_lookback,
            sl_buffer_pct=runtime.imba.fib_sl_buffer_pct,
            min_tp1_rr=runtime.imba.fib_min_tp1_rr,
            tp_close_pcts=runtime.imba.tp_close_tuple(),
            max_entry_ratio=runtime.imba.fib_max_entry_ratio,
            min_tps_above=runtime.imba.fib_min_tps_above,
        )
        if fib is not None:
            used_tf = tf
            break

    if fib is None:
        reason = f"Fib inválido em {structure_tf}/{exec_tf}"
        logger.info("Fib rejeitou | %s | %s", symbol, reason)
        return None, reason

    out = ImbaSignal(
        side=signal.side,
        entry_price=signal.entry_price,
        stop_loss=fib.stop_loss,
        take_profits=fib.take_profits,
        levels=signal.levels,
    )
    logger.info(
        "Fib níveis | %s %s @%s | base=%.6g top=%.6g | SL=%.6g | TPs=%s | RR1=%.2f",
        signal.side,
        symbol,
        used_tf,
        fib.swing_low,
        fib.swing_high,
        fib.stop_loss,
        "/".join(f"{p:.6g}" for p in fib.take_profits),
        fib.tp1_rr,
    )
    return out, ""


def resolve_signal_execution_levels(
    signal: ImbaSignal,
    symbol: str,
    ohlcv_by_tf: dict[str, list[list[float]]] | None,
    runtime: BotRuntimeConfig,
) -> tuple[ImbaSignal | None, SMCLevels | None, str]:
    """Fibonacci (padrão scalp) ou SMC sobre o sinal IMBA."""
    pipeline = runtime.strategies.scanner
    smc_cfg = runtime.smc
    use_smc = smc_cfg.enabled and pipeline.smc

    if runtime.imba.use_fib_levels and ohlcv_by_tf:
        fib_signal, reject = _apply_fib_levels(signal, symbol, ohlcv_by_tf, runtime)
        if fib_signal is not None:
            return fib_signal, None, ""
        # Fib obrigatório no scalp — não cair em SMC (TPs distantes do gráfico)
        return None, None, reject or "Fib inválido — trade rejeitado"
    if not use_smc or not ohlcv_by_tf:
        return signal, None, ""

    direction = (
        TradeDirection.LONG if signal.side == "LONG" else TradeDirection.SHORT
    )
    structure_tf = smc_cfg.structure_timeframe
    ohlcv = ohlcv_by_tf.get(structure_tf) or ohlcv_by_tf.get(
        runtime.timeframes.execution
    )
    if not ohlcv:
        return signal, None, ""

    smc = compute_smc_levels(
        ohlcv,
        direction,
        signal.entry_price,
        min_tp1_rr=smc_cfg.min_tp1_rr,
        min_tp2_rr=smc_cfg.min_tp2_rr,
        sl_buffer_atr_mult=smc_cfg.sl_buffer_atr_mult,
        swing_lookback=smc_cfg.swing_lookback,
    )
    if smc is None:
        reason = (
            f"SMC sem setup válido em {structure_tf} "
            f"(TP1 < {smc_cfg.min_tp1_rr}R)"
        )
        logger.info("SMC rejeitou | %s | %s", symbol, reason)
        return None, None, reason

    if not _weighted_rr_meets_target(
        smc,
        wins_cover_losses=runtime.risk.wins_cover_losses,
        tp_close_pcts=runtime.imba.tp_close_tuple(),
    ):
        reason = (
            f"SMC R:R ponderado {smc.weighted_rr:.2f} < "
            f"{runtime.risk.wins_cover_losses} losses cobertos"
        )
        logger.info("SMC R:R insuficiente | %s | %s", symbol, reason)
        return None, None, reason

    out = ImbaSignal(
        side=signal.side,
        entry_price=signal.entry_price,
        stop_loss=smc.stop_loss,
        take_profits=smc.take_profits[:3],
        levels=signal.levels,
    )
    logger.info(
        "SMC níveis | %s %s | SL=%s (%s) | TPs=%s | RR1=%.2f pond=%.2f",
        signal.side,
        symbol,
        f"{smc.stop_loss:.6g}",
        smc.sl_reason,
        "/".join(f"{p:.6g}" for p in smc.take_profits),
        smc.tp1_rr,
        smc.weighted_rr,
    )
    return out, smc, ""


def resolve_execution_levels(
    analysis: ImbaAnalysis,
    config: ImbaAlgoConfig,
    ohlcv_by_tf: dict[str, list[list[float]]] | None,
    runtime: BotRuntimeConfig,
) -> tuple[ImbaSignal | None, SMCLevels | None, str]:
    """Direção IMBA; entry 5m; SL/TP via Fib ou SMC."""
    imba = pick_execution_levels(
        analysis,
        config,
        ohlcv_by_tf,
        execution_timeframe=runtime.timeframes.execution,
    )
    if imba is None:
        return None, None, ""

    return resolve_signal_execution_levels(imba, analysis.symbol, ohlcv_by_tf, runtime)
