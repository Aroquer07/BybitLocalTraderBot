"""Restaura TPs faltantes após breakeven ter apagado."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config.settings import get_settings
from src.services.exchange_client import ExchangeClient
from src.services.position_manager import normalize_tp_amounts_for_exchange, split_tp_amounts
from src.services.runtime_config_store import RuntimeConfigStore


async def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "WLFI/USDT"
    settings = get_settings()
    runtime = RuntimeConfigStore(settings.settings_path).reload()
    client = ExchangeClient(settings, RuntimeConfigStore(settings.settings_path))
    await client.connect()
    try:
        side = "buy"
        size = await client.fetch_position_size(symbol, side)
        if size <= 0:
            print(f"Sem posição aberta em {symbol}")
            return

        trades = json.loads((ROOT / "data/trades.json").read_text(encoding="utf-8"))
        trade = next(
            (t for t in trades["trades"] if t.get("status") == "open" and t["symbol"] == symbol),
            None,
        )
        if not trade:
            print("Trade não encontrado no journal")
            return

        tps = trade.get("take_profits") or []
        if len(tps) < 3:
            print("TPs insuficientes no journal")
            return

        close_pcts = runtime.imba.tp_close_tuple()
        parts = split_tp_amounts(float(trade["amount"]), *close_pcts)
        parts = normalize_tp_amounts_for_exchange(
            symbol,
            float(trade["amount"]),
            parts,
            amount_to_precision=client.amount_to_precision,
            min_amount=float(client.get_market_limits(symbol).get("min_amount") or 0),
        )

        snapshots = await client._collect_open_tp_snapshots(symbol, side)
        print(f"TPs atuais na exchange: {snapshots}")

        pending = [
            {"price": tps[1], "amount": parts.tp2, "level": 2},
            {"price": tps[2], "amount": parts.tp3, "level": 3},
        ]
        restored = await client._restore_take_profit_snapshots(symbol, side, pending)
        print(f"Restaurados: {restored}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
