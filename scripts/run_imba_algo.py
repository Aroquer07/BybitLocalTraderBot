"""
Runner standalone da estratégia [IMBA] ALGO.

Poll OHLCV no fechamento do candle, gera sinal de virada verde/vermelho e executa
na Bybit. Não fecha posição em reversão — só SL/TPs na exchange.

Uso:
  python scripts/run_imba_algo.py --symbol SOL/USDT --timeframe 15m --dry-run
  python scripts/run_imba_algo.py --symbol BTC/USDT --sensitivity 2 --once
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.settings import get_settings
from src.services.exchange_client import ExchangeClient
from src.services.position_manager import PositionManager
from src.services.runtime_config_store import RuntimeConfigStore
from src.strategies.imba_algo import (
    ImbaAlgoConfig,
    ImbaTrendState,
    evaluate_ohlcv,
    signal_to_exchange_side,
)
from src.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)

DEFAULT_SYMBOL = "SOL/USDT"
DEFAULT_TIMEFRAME = "15m"
STATE_FILE = ROOT / "data" / "imba_algo_state.json"


def log_step(msg: str) -> None:
    print(f"  -> {msg}")


def log_ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def log_fail(msg: str) -> None:
    print(f"  [FALHA] {msg}")


def load_persisted_state(symbol: str) -> ImbaTrendState | None:
    if not STATE_FILE.exists():
        return None
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        entry = raw.get(symbol)
        if not entry:
            return None
        return ImbaTrendState(
            is_long_trend=bool(entry.get("is_long_trend", False)),
            is_short_trend=bool(entry.get("is_short_trend", False)),
        )
    except (json.JSONDecodeError, OSError):
        return None


def save_persisted_state(symbol: str, state: ImbaTrendState) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {}
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    data[symbol] = {
        "is_long_trend": state.is_long_trend,
        "is_short_trend": state.is_short_trend,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def timeframe_to_seconds(timeframe: str) -> int:
    unit = timeframe[-1]
    value = int(timeframe[:-1])
    multipliers = {"m": 60, "h": 3600, "d": 86400}
    if unit not in multipliers:
        raise ValueError(f"Timeframe não suportado: {timeframe}")
    return value * multipliers[unit]


async def has_open_position(
    exchange: ExchangeClient,
    symbol: str,
) -> tuple[bool, float, str | None]:
    """Retorna (tem_posição, tamanho, side buy/sell)."""
    for side in ("buy", "sell"):
        size = await exchange.fetch_position_size(symbol, side)
        if size > 0:
            return True, size, side
    return False, 0.0, None


async def run_cycle(
    exchange: ExchangeClient,
    position_mgr: PositionManager,
    symbol: str,
    timeframe: str,
    config: ImbaAlgoConfig,
    *,
    dry_run: bool,
    leverage: int,
    last_candle_ts: int | None,
) -> int | None:
    """Um ciclo de avaliação. Retorna timestamp do último candle processado."""
    ohlcv = await exchange.fetch_ohlcv(
        symbol,
        timeframe,
        limit=max(config.lookback + 5, 50),
    )
    if len(ohlcv) < config.lookback + 1:
        log_fail(f"OHLCV insuficiente ({len(ohlcv)} candles)")
        return last_candle_ts

    closed_candle = ohlcv[-2]
    closed_ts = int(closed_candle[0])

    if last_candle_ts is not None and closed_ts <= last_candle_ts:
        return last_candle_ts

    persisted = load_persisted_state(symbol)
    state, signal = evaluate_ohlcv(
        ohlcv,
        config,
        exclude_forming_candle=True,
        initial_state=persisted,
    )
    save_persisted_state(symbol, state)

    close_price = float(closed_candle[4])
    ts_str = datetime.fromtimestamp(closed_ts / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )
    trend = "LONG" if state.is_long_trend else "SHORT" if state.is_short_trend else "NEUTRO"
    log_step(f"Candle fechado {ts_str} | close={close_price} | tendência={trend}")

    if signal is None:
        log_step("Sem sinal de virada neste candle")
        return closed_ts

    has_pos, pos_size, pos_side = await has_open_position(exchange, symbol)
    if has_pos:
        log_step(
            f"Sinal {signal.side} ignorado — posição aberta "
            f"({pos_side} {pos_size}) — reversão NÃO fecha trade"
        )
        return closed_ts

    sl = exchange.price_to_precision(symbol, signal.stop_loss)
    tps = [
        exchange.price_to_precision(symbol, p) for p in signal.take_profits
    ]
    exchange_side = signal_to_exchange_side(signal.side)

    print()
    log_ok(f"SINAL {signal.side} @ {signal.entry_price}")
    log_step(f"SL: {sl}")
    for i, tp in enumerate(tps, 1):
        log_step(f"TP{i}: {tp}")
    log_step(
        f"Split TPs: {config.tp_close_pcts[0]}/"
        f"{config.tp_close_pcts[1]}/"
        f"{config.tp_close_pcts[2]}/"
        f"{config.tp_close_pcts[3]}%"
    )

    if dry_run:
        log_step("DRY_RUN — ordem não enviada")
        return closed_ts

    result = await position_mgr.execute_with_partial_tps(
        symbol=symbol,
        side=exchange_side,
        entry_price=signal.entry_price,
        stop_loss=sl,
        take_profit_prices=tps,
        leverage=leverage,
        tp_close_pcts=config.tp_close_pcts,
        monitor_breakeven=False,
        breakeven_after_tp=0,
    )

    if result.get("emergency_closed"):
        log_fail("Trade encerrado em emergência")
        return closed_ts

    log_ok(f"Entry: {result.get('entry', {}).get('id')}")
    log_ok(f"SL: {result.get('sl_order_id')}")
    for tp in result.get("tp_orders", []):
        log_ok(f"TP{tp['level']}: {tp['order_id']} @ {tp['price']}")

    return closed_ts


async def run_imba(
    symbol: str,
    timeframe: str,
    config: ImbaAlgoConfig,
    *,
    dry_run: bool,
    once: bool,
    poll_interval: float,
) -> int:
    settings = get_settings()
    runtime_store = RuntimeConfigStore(settings.settings_path)
    runtime = runtime_store.reload()
    setup_logging(runtime.log_level, runtime.log_format)

    print("=" * 60)
    print("[IMBA] ALGO — runner standalone")
    print("=" * 60)
    log_step(f"Modo Bybit: {settings.bybit_mode}")
    log_step(f"Símbolo: {symbol} | TF: {timeframe}")
    log_step(f"Sensitivity: {config.sensitivity} (lookback {config.lookback})")
    log_step(f"Risco/trade: {runtime.risk.risk_per_trade_pct}%")
    log_step(f"TPs: {config.tp_percents}% | Split: {config.tp_close_pcts}")
    log_step(f"Reversão fecha trade: NÃO")
    log_step(f"DRY_RUN: {dry_run}")
    print()

    exchange = ExchangeClient(settings, runtime_store)
    position_mgr = PositionManager(settings, exchange, runtime_store)
    leverage = min(runtime.risk.min_leverage, runtime.risk.max_leverage)
    last_candle_ts: int | None = None

    try:
        await exchange.connect()
        log_ok("Conectado à Bybit")

        resolved = exchange.resolve_symbol(symbol)
        if resolved != symbol:
            log_step(f"Símbolo resolvido: {symbol} -> {resolved}")
            symbol = resolved

        balance = await exchange.fetch_usdt_balance()
        log_ok(f"Saldo USDT: {balance:,.2f}")

        if once:
            last_candle_ts = await run_cycle(
                exchange,
                position_mgr,
                symbol,
                timeframe,
                config,
                dry_run=dry_run,
                leverage=leverage,
                last_candle_ts=None,
            )
            return 0

        tf_seconds = timeframe_to_seconds(timeframe)
        log_step(f"Aguardando fechamento de candles ({poll_interval}s poll)...")

        while True:
            try:
                last_candle_ts = await run_cycle(
                    exchange,
                    position_mgr,
                    symbol,
                    timeframe,
                    config,
                    dry_run=dry_run,
                    leverage=leverage,
                    last_candle_ts=last_candle_ts,
                )
            except Exception:
                logger.exception("Erro no ciclo IMBA ALGO")
            await asyncio.sleep(min(poll_interval, tf_seconds / 4))

    except KeyboardInterrupt:
        print("\nEncerrado pelo usuário")
        return 0
    except Exception as exc:
        log_fail(str(exc))
        logger.exception("Erro fatal no runner IMBA")
        return 1
    finally:
        position_mgr.stop_monitoring(symbol)
        await exchange.disconnect()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Runner [IMBA] ALGO")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    parser.add_argument("--sensitivity", type=float, default=2.0)
    parser.add_argument(
        "--tp-pct",
        type=str,
        default="1,2,3,4",
        help="TPs %% separados por vírgula",
    )
    parser.add_argument(
        "--tp-split",
        type=str,
        default="50,30,20,0",
        help="%% da posição por TP (soma pode ser < 100)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Avalia um candle fechado e sai",
    )
    parser.add_argument(
        "--poll",
        type=float,
        default=30.0,
        help="Intervalo de poll em segundos (modo contínuo)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tp_parts = [float(x.strip()) for x in args.tp_pct.split(",")]
    split_parts = [float(x.strip()) for x in args.tp_split.split(",")]
    if len(tp_parts) != 4 or len(split_parts) != 4:
        print("Erro: --tp-pct e --tp-split precisam de 4 valores")
        return 1

    config = ImbaAlgoConfig(
        sensitivity=args.sensitivity,
        tp_percents=(tp_parts[0], tp_parts[1], tp_parts[2], tp_parts[3]),
        tp_close_pcts=(
            split_parts[0],
            split_parts[1],
            split_parts[2],
            split_parts[3],
        ),
    )

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    return asyncio.run(
        run_imba(
            symbol=args.symbol,
            timeframe=args.timeframe,
            config=config,
            dry_run=args.dry_run,
            once=args.once,
            poll_interval=args.poll,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
