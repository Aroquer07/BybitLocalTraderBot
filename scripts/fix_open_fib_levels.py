"""Recalcula SL/TP Fib + liquidação segura em posições abertas (journal)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.settings import get_settings
from src.models.schemas import TradeDirection
from src.services.exchange_client import ExchangeClient
from src.services.position_manager import normalize_tp_amounts_for_exchange, split_tp_amounts
from src.services.runtime_config_store import RuntimeConfigStore
from src.strategies.fib_execution_levels import compute_fib_scalp_levels
from src.strategies.trade_validation import apply_liquidation_safe_stop_loss
from src.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)
TRADES_PATH = ROOT / "data" / "trades.json"


def _load_open_trades(symbol: str | None) -> list[dict]:
    if not TRADES_PATH.exists():
        return []
    data = json.loads(TRADES_PATH.read_text(encoding="utf-8"))
    trades = data.get("trades") or []
    open_trades = [t for t in trades if t.get("status") == "open"]
    if symbol:
        sym = symbol.upper()
        open_trades = [t for t in open_trades if t.get("symbol", "").upper() == sym]
    return open_trades


def _save_trade_levels(trade_id: str, stop_loss: float, take_profits: list[float]) -> None:
    data = json.loads(TRADES_PATH.read_text(encoding="utf-8"))
    for trade in data.get("trades", []):
        if trade.get("id") == trade_id:
            trade["stop_loss"] = stop_loss
            trade["take_profits"] = take_profits
            break
    TRADES_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def fix_trade(
    client: ExchangeClient,
    runtime,
    trade: dict,
    *,
    apply: bool,
) -> dict:
    symbol = trade["symbol"]
    direction = (trade.get("direction") or "LONG").upper()
    side = "buy" if direction == "LONG" else "sell"
    entry = float(trade["entry_price"])
    leverage = int(trade.get("leverage") or 15)
    amount = float(trade.get("amount") or 0)
    tf = runtime.imba.fib_structure_timeframe or runtime.timeframes.execution

    ohlcv = await client.fetch_ohlcv(symbol, timeframe=tf, limit=runtime.ohlcv_limit)
    fib = compute_fib_scalp_levels(
        ohlcv,
        direction,
        entry,
        lookback=runtime.imba.fib_lookback,
        sl_buffer_pct=runtime.imba.fib_sl_buffer_pct,
        min_tp1_rr=runtime.imba.fib_min_tp1_rr,
        tp_close_pcts=runtime.imba.tp_close_tuple(),
        max_entry_ratio=runtime.imba.fib_max_entry_ratio,
        min_tps_above=runtime.imba.fib_min_tps_above,
    )
    if fib is None:
        return {"symbol": symbol, "status": "skipped", "reason": f"Fib inválido em {tf}"}

    liq = await client.resolve_liquidation_price(symbol, side, entry, leverage)
    dir_enum = TradeDirection.LONG if direction == "LONG" else TradeDirection.SHORT
    safe_sl, sl_err = apply_liquidation_safe_stop_loss(
        dir_enum,
        entry,
        fib.stop_loss,
        liq,
        runtime.risk.liquidation_sl_buffer_pct,
    )
    if sl_err or safe_sl is None:
        return {"symbol": symbol, "status": "failed", "reason": sl_err or "SL inseguro"}

    tps = [p for p in fib.take_profits if (p < entry if direction == "SHORT" else p > entry)]
    if len(tps) < 1:
        return {"symbol": symbol, "status": "skipped", "reason": "sem TP válido vs entrada"}

    # Preenche até 3 níveis repetindo o último se Fib só gerou 1–2 acima/abaixo da entrada
    while len(tps) < 3:
        tps.append(tps[-1])
    tps = tps[:3]
    close_pcts = runtime.imba.tp_close_tuple()
    pos_size = amount or await client.fetch_position_size(symbol, side)
    if pos_size <= 0:
        return {"symbol": symbol, "status": "skipped", "reason": "sem posição na exchange"}

    parts = split_tp_amounts(pos_size, *close_pcts)
    parts = normalize_tp_amounts_for_exchange(
        symbol,
        pos_size,
        parts,
        amount_to_precision=client.amount_to_precision,
        min_amount=float(client.get_market_limits(symbol).get("min_amount") or 0),
    )

    plan = {
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "liquidation": round(liq, 6),
        "old_sl": trade.get("stop_loss"),
        "new_sl": round(safe_sl, 6),
        "old_tps": trade.get("take_profits"),
        "new_tps": [round(p, 6) for p in tps],
        "tp_amounts": [parts.tp1, parts.tp2, parts.tp3],
        "fib": {
            "swing_low": fib.swing_low,
            "swing_high": fib.swing_high,
            "tp1_rr": fib.tp1_rr,
        },
    }

    if not apply:
        plan["status"] = "dry_run"
        return plan

    await client.cancel_stop_loss_orders(symbol, side)
    await client.cancel_take_profit_orders(symbol, side)
    await asyncio.sleep(0.3)

    close_side = "sell" if side == "buy" else "buy"
    sl_order = await client.create_partial_stop_loss(
        symbol, close_side, pos_size, safe_sl
    )
    tp_orders = []
    for price, qty in zip(tps, (parts.tp1, parts.tp2, parts.tp3)):
        if qty <= 0:
            continue
        tp_orders.append(
            await client.create_partial_take_profit(
                symbol, close_side, qty, price
            )
        )
        await asyncio.sleep(0.15)

    _save_trade_levels(trade["id"], safe_sl, tps)
    plan["status"] = "ok"
    plan["sl_order_id"] = sl_order.get("id")
    plan["tp_order_ids"] = [o.get("id") for o in tp_orders]
    return plan


async def main() -> int:
    parser = argparse.ArgumentParser(description="Corrige SL/TP Fib em posições abertas")
    parser.add_argument("--symbol", help="Só este símbolo (ex: DOGE/USDT)")
    parser.add_argument("--apply", action="store_true", help="Aplica na exchange (default: dry-run)")
    args = parser.parse_args()

    settings = get_settings()
    runtime = RuntimeConfigStore(settings.settings_path).reload()
    setup_logging(runtime.log_level, runtime.log_format)

    trades = _load_open_trades(args.symbol)
    if not trades:
        print("Nenhum trade aberto no journal.")
        return 0

    client = ExchangeClient(settings, RuntimeConfigStore(settings.settings_path))
    await client.connect()
    try:
        for trade in trades:
            print(f"\n--- {trade['symbol']} {trade.get('direction')} ---")
            result = await fix_trade(client, runtime, trade, apply=args.apply)
            for key in (
                "status",
                "reason",
                "old_sl",
                "new_sl",
                "liquidation",
                "old_tps",
                "new_tps",
                "fib",
            ):
                if key in result:
                    print(f"  {key}: {result[key]}")
    finally:
        await client.disconnect()

    if not args.apply:
        print("\nDry-run. Use --apply para enviar ordens à Bybit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
