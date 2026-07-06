#!/usr/bin/env python3
"""Diagnóstico ALGO+Kalman+Fib em par real (Bybit)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config.settings import get_settings
from src.services.exchange_client import ExchangeClient
from src.services.runtime_config_store import load_runtime_config
from src.strategies.fib_execution_levels import compute_fib_scalp_levels
from src.strategies.imba_analyzer import analyze_multi_timeframe, config_from_runtime, imba_analysis_timeframes
from src.strategies.kalman_entry import kalman_allows_entry
from src.strategies.technical_analysis import TechnicalAnalysisEngine
from src.models.schemas import TradeDirection


async def main(symbol: str = "ZEC/USDT:USDT") -> None:
    settings = get_settings()
    runtime = load_runtime_config("data/settings.json")
    exchange = ExchangeClient(settings)
    await exchange.connect()

    tfs = imba_analysis_timeframes(runtime)
    ohlcv_by_tf: dict[str, list] = {}
    for tf in tfs:
        ohlcv_by_tf[tf] = await exchange.fetch_ohlcv(symbol, timeframe=tf, limit=200)

    config = config_from_runtime(runtime)
    analysis = analyze_multi_timeframe(symbol, ohlcv_by_tf, config, settings=runtime)
    print(f"\n=== IMBA {symbol} ===")
    print(f"Fresh signal: {analysis.fresh_signal_direction}")
    print(f"Confidence: {analysis.confidence_score:.2%}")
    for tf, snap in analysis.timeframes.items():
        print(f"  {tf}: trend={snap.trend} signal={snap.signal_on_last_bar}")

    ta = TechnicalAnalysisEngine(settings)
    try:
        market = ta.build_market_state(symbol, ohlcv_by_tf)
        exec_tf = runtime.timeframes.execution
        exec_snap = market.timeframes.get(exec_tf)
        ind = exec_snap.indicators if exec_snap else {}
        print(f"\n=== Kalman @ {exec_tf} ===")
        print(f"  signal={ind.get('kalman_signal')} reversal={ind.get('kalman_reversal')}")

        if analysis.fresh_signal_direction:
            kv = kalman_allows_entry(
                analysis.fresh_signal_direction,
                ind,
                require_reversal=True,
            )
            print(f"  verdict: {kv.passed} — {kv.reason}")

        exec_ohlcv = ohlcv_by_tf.get(exec_tf, [])
        struct_ohlcv = ohlcv_by_tf.get(runtime.imba.fib_structure_timeframe) or exec_ohlcv
        entry = float(exec_ohlcv[-1][4]) if exec_ohlcv else 0.0
        direction = analysis.fresh_signal_direction or TradeDirection.LONG
        side = "LONG" if direction == TradeDirection.LONG else "SHORT"
        fib = compute_fib_scalp_levels(
            struct_ohlcv,
            side,
            entry,
            lookback=runtime.imba.fib_lookback,
            sl_buffer_pct=runtime.imba.fib_sl_buffer_pct,
            min_tp1_rr=runtime.imba.fib_min_tp1_rr,
            tp_close_pcts=runtime.imba.tp_close_tuple(),
        )
        print(f"\n=== Fib @ {runtime.imba.fib_structure_timeframe} entry={entry:.4f} ({side}) ===")
        if fib:
            print(f"  swing_low={fib.swing_low:.4f} swing_high={fib.swing_high:.4f}")
            print(f"  SL={fib.stop_loss:.4f}")
            for i, (r, tp) in enumerate(zip((0.382, 0.5, 0.618, 0.786), fib.take_profits), 1):
                print(f"  TP{i} ({r}) = {tp:.4f}")
            print(f"  RR1={fib.tp1_rr:.2f} weighted={fib.weighted_rr:.2f}")
        else:
            print("  Fib inválido para setup atual")
    finally:
        await exchange.disconnect()


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "ZEC/USDT:USDT"
    asyncio.run(main(sym))
