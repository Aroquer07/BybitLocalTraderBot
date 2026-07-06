"""Envia relatório PnL atual para o Telegram (teste manual)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.settings import get_settings
from src.controllers.execution_controller import ExecutionController
from src.controllers.report_controller import ReportController
from src.services.exchange_client import ExchangeClient
from src.services.runtime_config_store import RuntimeConfigStore
from src.services.trade_notifier import TradeNotifier
from src.utils.logger import setup_logging


async def main() -> int:
    settings = get_settings()
    runtime_store = RuntimeConfigStore(settings.settings_path)
    runtime = runtime_store.reload()
    setup_logging(runtime.log_level, runtime.log_format)

    exchange = ExchangeClient(settings, runtime_store)
    notifier = TradeNotifier(settings)
    if not notifier.enabled:
        print("Telegram notifier desabilitado — verifique .env")
        return 1

    execution = ExecutionController(settings, exchange, runtime_store, notifier)
    report = ReportController(
        settings, exchange, execution, notifier, runtime_store
    )

    try:
        await exchange.connect()
        await report.send_report()
        print("Relatório enviado com sucesso.")
        return 0
    finally:
        await exchange.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
