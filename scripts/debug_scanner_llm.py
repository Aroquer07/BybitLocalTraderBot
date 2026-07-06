"""Diagnóstico LLM do scanner — reproduz avaliação e mostra resposta bruta."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.settings import get_settings
from src.services.exchange_client import ExchangeClient
from src.services.llm_client import LLMClient, SYSTEM_PROMPT
from src.services.runtime_config_store import RuntimeConfigStore
from src.strategies.imba_analyzer import (
    analyze_multi_timeframe,
    config_from_runtime,
    imba_analysis_timeframes,
    pick_execution_levels,
)
from src.strategies.technical_analysis import TechnicalAnalysisEngine
from src.utils.logger import setup_logging


async def diagnose(symbol: str, *, force: bool = False) -> int:
    settings = get_settings()
    runtime_store = RuntimeConfigStore(settings.settings_path)
    runtime = runtime_store.reload()
    setup_logging(runtime.log_level, runtime.log_format)

    exchange = ExchangeClient(settings, runtime_store)
    llm = LLMClient(settings, runtime_store)
    ta = TechnicalAnalysisEngine(settings, runtime_store)

    print("=" * 70)
    print(f"DIAGNÓSTICO LLM SCANNER | {symbol}")
    print("=" * 70)

    await exchange.connect()
    await llm.warmup()

    resolved = exchange.resolve_symbol(symbol)
    print(f"Symbol resolvido: {resolved}")

    timeframes = runtime.timeframes.analysis
    limit = max(runtime.ohlcv_limit, 50)
    ohlcv_by_tf = {}
    for tf in timeframes:
        try:
            ohlcv_by_tf[tf] = await exchange.fetch_ohlcv(resolved, timeframe=tf, limit=limit)
        except Exception as exc:
            print(f"  OHLCV {tf}: FALHOU — {exc}")

    orderbook = {}
    try:
        orderbook = await exchange.fetch_order_book(resolved)
    except Exception as exc:
        print(f"  Orderbook: FALHOU — {exc}")

    imba_tfs = imba_analysis_timeframes(runtime)
    imba_ohlcv = {tf: ohlcv_by_tf[tf] for tf in imba_tfs if tf in ohlcv_by_tf}
    config = config_from_runtime(runtime)
    analysis = analyze_multi_timeframe(resolved, imba_ohlcv, config, settings=runtime)

    print(f"IMBA: {analysis.summary}")
    print(f"  fresh_signal={analysis.fresh_signal_direction} score={analysis.confidence_score:.0%}")

    if analysis.fresh_signal_direction is None and not force:
        print("Sem sinal IMBA fresco — scanner nem chamaria LLM. Use --force para testar LLM mesmo assim.")
        await exchange.disconnect()
        return 1

    if analysis.fresh_signal_direction is None and force:
        print("(modo --force: chamando LLM sem sinal fresco)")

    imba_signal = pick_execution_levels(
        analysis, config, imba_ohlcv, execution_timeframe=runtime.timeframes.execution
    )
    if imba_signal is None:
        print("pick_execution_levels retornou None.")
        await exchange.disconnect()
        return 1

    market_state = ta.build_market_state(
        symbol=resolved,
        ohlcv_by_timeframe=ohlcv_by_tf,
        orderbook=orderbook or None,
    )
    market_state = market_state.model_copy(update={"imba_analysis": analysis})

    conf = market_state.confluence
    if conf:
        print(
            f"Confluência: {conf.recommendation} L={conf.long_score} S={conf.short_score}"
        )

    payload = llm._build_scanner_payload(market_state, imba_signal)
    print(f"\nPayload scanner: {len(payload):,} chars ({len(payload.encode('utf-8')):,} bytes)")
    print(f"System prompt: {len(SYSTEM_PROMPT):,} chars")

    decision = await llm.evaluate_scanner_opportunity(market_state, imba_signal)

    print("\n" + "=" * 70)
    print("DECISÃO PARSEADA")
    print("=" * 70)
    print(f"  approved:     {decision.approved}")
    print(f"  confidence:   {decision.confidence:.2%}")
    print(f"  threshold:    {decision.confidence_threshold:.2%}")
    print(f"  direction:    {decision.direction}")
    print(f"  leverage:     {decision.leverage}")
    print(f"  bias:         {decision.bias!r}")
    print(f"  tp_sl_quality:{decision.tp_sl_quality!r}")
    print(f"  TPs count:    {len(decision.take_profits)}")

    raw = decision.raw_llm_response or ""
    print(f"\nResposta bruta ({len(raw)} chars):")
    print("-" * 70)
    if raw:
        try:
            parsed = json.loads(raw)
            print(json.dumps(parsed, ensure_ascii=False, indent=2))
        except json.JSONDecodeError:
            print(raw[:4000])
    else:
        print("(vazia)")

    await exchange.disconnect()
    return 0


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    force = "--force" in sys.argv
    sym = args[0] if args else "HEI/USDT"
    raise SystemExit(asyncio.run(diagnose(sym, force=force)))


if __name__ == "__main__":
    main()
