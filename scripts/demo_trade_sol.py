"""
Demo end-to-end: trade SOL/USDT na conta Bybit Demo com TPs parciais.

Uso:
  python scripts/demo_trade_sol.py
  python scripts/demo_trade_sol.py --dry-run
  python scripts/demo_trade_sol.py --sl-pct 1.5 --tp-pct 0.5,1.0,1.5,2.0
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.settings import get_settings
from src.services.exchange_client import ExchangeClient
from src.services.position_manager import PositionManager
from src.services.runtime_config_store import RuntimeConfigStore
from src.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)

SYMBOL = "SOL/USDT"
DEFAULT_SL_PCT = 1.5
DEFAULT_TP_PCTS = (0.5, 1.0, 1.5, 2.0)
MONITOR_SECONDS = 120


def log_step(msg: str) -> None:
    print(f"  -> {msg}")


def log_ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def log_fail(msg: str) -> None:
    print(f"  [FALHA] {msg}")


async def run_demo(
    dry_run: bool,
    sl_pct: float,
    tp_pcts: tuple[float, float, float, float],
    monitor_seconds: int,
    size_cap: float | None,
) -> int:
    settings = get_settings()
    runtime_store = RuntimeConfigStore(settings.settings_path)
    runtime = runtime_store.reload()
    setup_logging(runtime.log_level, runtime.log_format)

    print("=" * 60)
    print("Demo Trade SOL/USDT — Bybit Demo (paper)")
    print("=" * 60)
    log_step(f"Modo: {settings.bybit_mode.upper()}")
    log_step(f"Risco/trade: {runtime.risk.risk_per_trade_pct}%")
    log_step(f"Max posição: {runtime.risk.max_position_pct}%")
    tp = runtime.imba.tp_close_pcts
    log_step(f"TPs: {tp[0]}/{tp[1]}/{tp[2]}/{tp[3]}%")
    log_step(f"Breakeven após TP: {runtime.breakeven.level}")
    log_step(f"DRY_RUN: {dry_run}")
    print()

    if settings.bybit_mode != "demo":
        log_fail(f"BYBIT_MODE={settings.bybit_mode} — este script exige demo")
        return 1

    exchange = ExchangeClient(settings, runtime_store)
    position_mgr = PositionManager(settings, exchange, runtime_store)

    try:
        print("--- Conectando ---")
        await exchange.connect()
        log_ok("Conectado")

        resolved = exchange.resolve_symbol(SYMBOL)
        log_step(f"Simbolo resolvido: {SYMBOL} -> {resolved}")

        print("\n--- Saldo ---")
        balance = await exchange.fetch_usdt_balance()
        log_ok(f"USDT livre: {balance:,.2f}")

        print("\n--- Preço atual ---")
        ticker = await exchange.fetch_ticker(SYMBOL)
        last_price = float(ticker.get("last") or ticker.get("close") or 0)
        if last_price <= 0:
            log_fail("Preço inválido")
            return 1
        log_ok(f"SOL último: {last_price}")

        entry_price = last_price
        stop_loss = exchange.price_to_precision(
            SYMBOL, entry_price * (1 - sl_pct / 100.0)
        )
        tp_prices = [
            exchange.price_to_precision(SYMBOL, entry_price * (1 + p / 100.0))
            for p in tp_pcts
        ]

        leverage = min(runtime.risk.min_leverage, runtime.risk.max_leverage)

        print("\n--- Sizing ---")
        sizing = await position_mgr.compute_size_for_trade(
            symbol=SYMBOL,
            entry_price=entry_price,
            stop_loss=stop_loss,
            leverage=leverage,
        )
        limits = exchange.get_market_limits(SYMBOL)
        trade_amount = sizing.amount
        if size_cap is not None:
            trade_amount = min(trade_amount, size_cap)
        trade_amount = max(trade_amount, limits["min_amount"])
        trade_amount = exchange.amount_to_precision(SYMBOL, trade_amount)

        log_step(f"Min amount: {limits['min_amount']}")
        log_step(f"Amount calculado (risk): {sizing.amount} SOL")
        log_step(f"Amount efetivo (trade): {trade_amount} SOL")
        log_step(f"Notional: ~{sizing.notional_usdt:,.2f} USDT")
        log_step(f"Margem (~{leverage}x): ~{sizing.margin_usdt:,.2f} USDT")
        log_step(f"Risco no SL: ~{sizing.risk_usdt:,.2f} USDT")

        print("\n--- Níveis ---")
        log_step(f"Entry (market): {entry_price}")
        log_step(f"SL (-{sl_pct}%): {stop_loss}")
        for i, (tp, pct) in enumerate(zip(tp_prices, tp_pcts), 1):
            log_step(f"TP{i} (+{pct}%): {tp}")

        if dry_run:
            print("\n" + "=" * 60)
            print("DRY_RUN — nenhuma ordem enviada")
            print("=" * 60)
            return 0

        print("\n--- Executando LONG ---")
        result = await position_mgr.execute_with_partial_tps(
            symbol=SYMBOL,
            side="buy",
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit_prices=tp_prices,
            leverage=leverage,
            amount=trade_amount,
        )

        entry_id = result.get("entry", {}).get("id")
        sl_id = result.get("sl_order_id")
        tp_orders = result.get("tp_orders", [])
        emergency = result.get("emergency_closed", False)

        if emergency:
            log_fail("Trade encerrado em emergência (proteções falharam)")
            return 1

        log_ok(f"Entry order: {entry_id}")
        log_ok(f"SL order: {sl_id}")
        for tp in tp_orders:
            log_ok(
                f"TP{tp['level']}: id={tp['order_id']} "
                f"amount={tp['amount']} @ {tp['price']}"
            )

        prot_errors = result.get("protection_errors", [])
        if prot_errors:
            log_step(f"Avisos proteção: {prot_errors}")

        print(f"\n--- Monitor breakeven ({monitor_seconds}s) ---")
        log_step("Aguardando TP2 ou timeout...")
        await asyncio.sleep(monitor_seconds)

        positions = await exchange.fetch_positions(SYMBOL)
        pos_size = await exchange.fetch_position_size(SYMBOL, "buy")
        open_orders = await exchange.fetch_open_orders(SYMBOL)

        print("\n--- Estado pós-execução ---")
        log_step(f"Posição aberta: {pos_size} SOL")
        log_step(f"Ordens abertas: {len(open_orders)}")

        active = position_mgr._active_trades.get(SYMBOL)
        breakeven = active.breakeven_applied if active else False
        log_step(f"Breakeven aplicado: {breakeven}")

        if positions:
            for p in positions:
                if float(p.get("contracts") or 0) > 0:
                    log_step(
                        f"  side={p.get('side')} contracts={p.get('contracts')} "
                        f"entry={p.get('entryPrice')} sl={p.get('stopLossPrice')}"
                    )

        print("\n" + "=" * 60)
        print("RESULTADO: TRADE DEMO EXECUTADO")
        print(f"  Entry ID: {entry_id}")
        print(f"  Size: {trade_amount} SOL")
        print(f"  SL: {stop_loss} | TPs: {tp_prices}")
        print(f"  Breakeven testado: {breakeven}")
        print("=" * 60)
        return 0

    except Exception as exc:
        log_fail(str(exc))
        logger.exception("Erro no demo trade")
        return 1
    finally:
        symbol_key = exchange.resolve_symbol(SYMBOL) if exchange.is_connected else SYMBOL
        position_mgr.stop_monitoring(symbol_key)
        position_mgr.stop_monitoring(SYMBOL)
        await exchange.disconnect()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Demo trade SOL/USDT Bybit")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Simula sem enviar ordens (default: executa)",
    )
    parser.add_argument(
        "--sl-pct",
        type=float,
        default=DEFAULT_SL_PCT,
        help=f"Stop loss %% abaixo da entrada (default {DEFAULT_SL_PCT})",
    )
    parser.add_argument(
        "--tp-pct",
        type=str,
        default=",".join(str(p) for p in DEFAULT_TP_PCTS),
        help="TPs %% acima da entrada separados por vírgula (default 0.5,1.0,1.5,2.0)",
    )
    parser.add_argument(
        "--size-cap",
        type=float,
        default=1.0,
        help="Teto de contratos SOL para o demo (default 1.0)",
    )
    parser.add_argument(
        "--monitor",
        type=int,
        default=MONITOR_SECONDS,
        help=f"Segundos para monitorar breakeven (default {MONITOR_SECONDS})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tp_parts = [float(x.strip()) for x in args.tp_pct.split(",")]
    if len(tp_parts) != 4:
        print("Erro: --tp-pct deve ter exatamente 4 valores")
        return 1

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    return asyncio.run(
        run_demo(
            dry_run=args.dry_run,
            sl_pct=args.sl_pct,
            tp_pcts=(tp_parts[0], tp_parts[1], tp_parts[2], tp_parts[3]),
            monitor_seconds=args.monitor,
            size_cap=args.size_cap,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
