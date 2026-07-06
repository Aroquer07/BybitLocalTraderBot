"""Estratégia Sniper Entry + confirmação Breakout Probability."""

from __future__ import annotations

from src.config.strategy_config import IndicatorModulesConfig
from src.strategies.indicator_modules.base import CombinedSignal, ModuleResult
from src.strategies.indicator_modules.breakout_probability import (
    breakout_confirms_direction,
    evaluate_breakout_probability,
)
from src.strategies.indicator_modules.sniper_entry import (
    SNIPER_TP_RR_MULTIPLIERS,
    evaluate_sniper_entry,
)
from src.strategies.trade_validation import REQUIRED_TP_COUNT


def evaluate_sniper_setup(
    ohlcv: list[list[float]],
    *,
    ohlcv_htf: list[list[float]] | None = None,
    config: IndicatorModulesConfig,
) -> tuple[CombinedSignal | None, list[ModuleResult], str]:
    """
    Sniper define entrada + SL/TP (ATR do indicador).
    Breakout Probability confirma viés do próximo candle (≥ min %).
    """
    results: list[ModuleResult] = []

    sniper = evaluate_sniper_entry(
        ohlcv,
        ohlcv_htf,
        min_score_pct=config.min_sniper_score_pct,
        entry_mode="cross",
    )
    results.append(sniper)
    if not sniper.triggered or sniper.direction is None:
        return None, results, sniper.reason

    outlook = evaluate_breakout_probability(
        ohlcv,
        min_probability_pct=config.min_breakout_probability_pct,
    )
    results.append(
        ModuleResult(
            "breakout_probability",
            "LONG" if outlook.bias == "BULLISH" else "SHORT",
            outlook.probability_pct / 100.0,
            outlook.probability_pct >= config.min_breakout_probability_pct,
            outlook.reason,
        )
    )

    ok, reject = breakout_confirms_direction(
        outlook,
        sniper.direction,
        min_probability_pct=config.min_breakout_probability_pct,
    )
    if not ok:
        return None, results, reject

    entry = sniper.entry_price
    sl = sniper.stop_loss
    tps_raw = sniper.take_profits
    if entry is None or sl is None or not tps_raw:
        return None, results, "Sniper sem níveis SL/TP"

    tps_list = list(tps_raw)
    while len(tps_list) < REQUIRED_TP_COUNT:
        risk = abs(entry - sl)
        mult = SNIPER_TP_RR_MULTIPLIERS[len(tps_list)]
        tps_list.append(
            entry + risk * mult if sniper.direction == "LONG" else entry - risk * mult
        )
    tps = tuple(tps_list[:REQUIRED_TP_COUNT])  # type: ignore[assignment]

    summary = (
        f"SNIPER {sniper.direction} | {sniper.reason} | "
        f"{outlook.reason}"
    )

    return (
        CombinedSignal(
            direction=sniper.direction,
            entry_price=entry,
            stop_loss=sl,
            take_profits=tps,  # type: ignore[arg-type]
            confidence=round(
                min(1.0, (sniper.confidence + outlook.probability_pct / 100) / 2),
                3,
            ),
            regime="trend",
            modules=("sniper", "breakout_probability"),
            summary=summary,
        ),
        results,
        "",
    )
