"""Diagnóstico rápido — por que combined não dispara."""
import asyncio
import json
from pathlib import Path

from src.config.runtime_config import BotRuntimeConfig
from src.config.settings import get_settings
from src.services.exchange_client import ExchangeClient
from src.services.runtime_config_store import RuntimeConfigStore
from src.strategies.indicator_modules.combined import evaluate_combined_setup


async def main() -> None:
    settings = get_settings()
    runtime = RuntimeConfigStore(settings.settings_path)
    cfg = BotRuntimeConfig.model_validate(
        json.loads(Path("data/settings.json").read_text(encoding="utf-8"))
    )
    pipeline = cfg.strategies.scanner
    ex = ExchangeClient(settings, runtime)
    await ex.connect()

    symbols = [
        "HMSTR/USDT:USDT",
        "MIRA/USDT:USDT",
        "TLM/USDT:USDT",
        "BTC/USDT:USDT",
        "WIF/USDT:USDT",
        "ETH/USDT:USDT",
    ]
    tf = cfg.timeframes.execution
    print(f"config: sniper_req={pipeline.indicators.sniper_required} pullback={pipeline.indicators.allow_trend_without_pullback}")
    for sym in symbols:
        try:
            ohlcv = await ex.fetch_ohlcv(sym, tf, limit=200)
            htf = await ex.fetch_ohlcv(sym, "5m", limit=200) if tf != "5m" else None
            bias = "LONG" if "HMSTR" in sym or "MIRA" in sym or "TLM" in sym else None
            sig, mods = evaluate_combined_setup(
                ohlcv, ohlcv_htf=htf, config=pipeline.indicators, screener_bias=bias
            )
            status = "PASS" if sig else "FAIL"
            print(f"\n{sym} -> {status}")
            for m in mods:
                d = m.direction or "-"
                print(f"  {m.name}: triggered={m.triggered} dir={d} | {m.reason[:70]}")
            if sig:
                print(f"  SIGNAL: {sig.direction} conf={sig.confidence} modules={sig.modules}")
        except Exception as exc:
            print(f"{sym} ERR {exc}")

    # test relaxed sniper
    relaxed = pipeline.indicators.model_copy(
        update={"min_sniper_score_pct": 85.0, "require_all": False}
    )
    print("\n--- relaxed sniper=85 require_all=false ---")
    sym = "HMSTR/USDT:USDT"
    ohlcv = await ex.fetch_ohlcv(sym, tf, limit=200)
    htf = await ex.fetch_ohlcv(sym, "5m", limit=200) if tf != "5m" else None
    sig, mods = evaluate_combined_setup(ohlcv, ohlcv_htf=htf, config=relaxed)
    print(sym, "PASS" if sig else "FAIL", sig.summary if sig else "")
    for m in mods:
        print(f"  {m.name}: {m.triggered} {m.reason[:60]}")

    await ex.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
