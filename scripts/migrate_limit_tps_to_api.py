"""Migra TPs limit reduce-only abertos para trading-stop Bybit (posição parcial)."""

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
from src.services.runtime_config_store import RuntimeConfigStore
from src.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)
TRADES_PATH = ROOT / "data" / "trades.json"


def _load_open_trades() -> list[dict]:
    if not TRADES_PATH.exists():
        return []
    data = json.loads(TRADES_PATH.read_text(encoding="utf-8"))
    trades = data.get("trades") or data
    if not isinstance(trades, list):
        return []
    return [t for t in trades if t.get("status") == "open"]


async def main() -> int:
    settings = get_settings()
    runtime = RuntimeConfigStore(settings.settings_path).reload()
    setup_logging(runtime.log_level, runtime.log_format)

    open_trades = _load_open_trades()
    if not open_trades:
        print("Nenhum trade aberto no journal.")
        return 0

    symbols: dict[str, str] = {}
    for trade in open_trades:
        sym = trade.get("symbol")
        direction = (trade.get("direction") or "LONG").upper()
        if sym:
            symbols[sym] = "buy" if direction == "LONG" else "sell"

    print(f"Migrando TPs limit -> trading-stop | {len(symbols)} simbolo(s)")
    for sym, side in symbols.items():
        print(f"  - {sym} ({side})")

    client = ExchangeClient(settings, RuntimeConfigStore(settings.settings_path))
    await client.connect()

    results: list[dict] = []
    try:
        for symbol, entry_side in symbols.items():
            print(f"\n--- {symbol} ---")
            result = await client.migrate_limit_tps_to_trading_stop(symbol, entry_side)
            results.append(result)
            status = result.get("status")
            migrated = result.get("migrated") or []
            errors = result.get("errors") or []
            if status == "skipped":
                print(f"  Pulado: {result.get('reason')}")
            else:
                print(f"  Status: {status} | migrados: {len(migrated)}")
                for m in migrated:
                    print(f"    TP @ {m['price']} qty={m['amount']} id={m.get('order_id')}")
                for err in errors:
                    print(f"  ERRO: {err}")
    finally:
        await client.disconnect()

    ok = sum(1 for r in results if r.get("migrated"))
    skip = sum(1 for r in results if r.get("status") == "skipped")
    fail = len(results) - ok - skip
    print(f"\nResumo: {ok} com migração, {skip} pulados, {fail} falhas/parciais")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
