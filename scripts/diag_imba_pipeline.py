#!/usr/bin/env python3
"""Funil IMBA — onde cada moeda morre (ALGO → HTF → Fib → Kalman → filtros)."""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config.settings import get_settings
from src.controllers.scanner_controller import ScannerController
from src.models.schemas import TradeDirection
from src.services.exchange_client import ExchangeClient
from src.services.runtime_config_store import load_runtime_config
from src.strategies.execution_levels import resolve_execution_levels
from src.strategies.imba_analyzer import (
    analyze_multi_timeframe,
    config_from_runtime,
    imba_analysis_timeframes,
    resolve_entry_direction,
)
from src.strategies.kalman_entry import kalman_allows_entry
from src.strategies.scanner_filters import evaluate_scanner_setup
from src.config.strategy_config import effective_scanner_quality
from src.strategies.technical_analysis import TechnicalAnalysisEngine


async def evaluate_symbol(symbol: str, runtime, exchange, ta) -> str:
    """Retorna estágio onde o símbolo parou."""
    pipeline = runtime.strategies.scanner
    imba_tfs = imba_analysis_timeframes(runtime)
    try:
        tfs = list(set(runtime.timeframes.analysis + imba_tfs))
        ohlcv_by_tf = {}
        for tf in tfs:
            candles = await exchange.fetch_ohlcv(symbol, timeframe=tf, limit=200)
            if candles:
                ohlcv_by_tf[tf] = candles
        if not ohlcv_by_tf:
            return "ohlcv"
    except Exception:
        return "ohlcv_erro"

    config = config_from_runtime(runtime)
    imba_ohlcv = {tf: ohlcv_by_tf[tf] for tf in imba_tfs if tf in ohlcv_by_tf}
    analysis = analyze_multi_timeframe(symbol, imba_ohlcv, config, settings=runtime)

    exec_tf = runtime.timeframes.execution
    direction = resolve_entry_direction(
        analysis,
        exec_tf=exec_tf,
        require_fresh=runtime.imba.require_fresh_signal,
    )
    if direction is None:
        return "sem_sinal_algo"

    if not ScannerController._imba_higher_tf_confirms(
        analysis,
        direction,
        min_matches=runtime.imba.min_htf_confirm,
    ):
        return "htf_desalinhado"

    analysis = analysis.model_copy(update={"fresh_signal_direction": direction})

    quality = effective_scanner_quality(runtime.scanner.quality, pipeline)
    if analysis.confidence_score < quality.min_imba_confidence:
        return "imba_conf_baixa"

    imba_signal, _, smc_reject = resolve_execution_levels(
        analysis, config, imba_ohlcv, runtime
    )
    if imba_signal is None:
        return "fib_invalido" if smc_reject else "sem_niveis"

    direction = (
        TradeDirection.LONG if imba_signal.side == "LONG" else TradeDirection.SHORT
    )

    try:
        market_state = ta.build_market_state(symbol, ohlcv_by_tf)
        market_state = market_state.model_copy(update={"imba_analysis": analysis})
    except Exception:
        return "market_state"

    exec_tf = runtime.timeframes.execution
    exec_snap = market_state.timeframes.get(exec_tf)
    kalman_ind = exec_snap.indicators if exec_snap else {}
    kalman_verdict = kalman_allows_entry(
        direction,
        kalman_ind,
        require_reversal=pipeline.kalman_hard_block,
    )
    if not kalman_verdict.passed:
        return "kalman"

    if pipeline.quality_filters:
        fv = evaluate_scanner_setup(
            direction=direction,
            analysis=analysis,
            imba_signal=imba_signal,
            market_state=market_state,
            filters=quality,
        )
        if not fv.passed:
            reason = (fv.reason or "filtro")[:40]
            return f"filtro:{reason}"

    return "PASSOU"


async def main(symbols: list[str] | None = None) -> None:
    settings = get_settings()
    runtime = load_runtime_config("data/settings.json")
    exchange = ExchangeClient(settings)
    ta = TechnicalAnalysisEngine(settings)
    await exchange.connect()

    if not symbols:
        from src.services.watchlist_loader import normalize_watchlist_symbols, parse_watchlist_text

        wl_path = Path(runtime.scanner.watchlist_path)
        static = parse_watchlist_text(wl_path.read_text(encoding="utf-8")) if wl_path.is_file() else []
        screener_samples = [
            "OGN/USDT",
            "VANRY/USDT",
            "HMSTR/USDT",
            "MIRA/USDT",
            "EPIC/USDT",
            "TLM/USDT",
            "LAB/USDT",
            "NOT/USDT",
        ]
        symbols = normalize_watchlist_symbols(static[:15] + screener_samples)

    print(f"\n=== Funil IMBA ({len(symbols)} moedas) ===")
    print(
        f"config: htf>={runtime.imba.min_htf_confirm} | "
        f"kalman_hard={runtime.strategies.scanner.kalman_hard_block} | "
        f"fib_zone={runtime.imba.fib_max_entry_ratio} | "
        f"portfolio_risk={runtime.risk.max_portfolio_risk_pct}%"
    )

    counts: Counter[str] = Counter()
    passed: list[str] = []

    for sym in symbols:
        stage = await evaluate_symbol(sym, runtime, exchange, ta)
        counts[stage] += 1
        if stage == "PASSOU":
            passed.append(sym)

    print("\n--- Bloqueios por estagio ---")
    for stage, n in counts.most_common():
        pct = 100 * n / len(symbols)
        print(f"  {n:3d} ({pct:4.0f}%) {stage}")

    if passed:
        print(f"\nOK Passaram ({len(passed)}): {', '.join(passed)}")
    else:
        print("\nNenhuma moeda passou no funil completo")

    await exchange.disconnect()


if __name__ == "__main__":
    syms = sys.argv[1:] if len(sys.argv) > 1 else None
    asyncio.run(main(syms))
