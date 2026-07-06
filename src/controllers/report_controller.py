"""Relatório periódico de win/loss e PnL aberto via Telegram."""

from __future__ import annotations

import asyncio

from src.config.settings import Settings
from src.services.runtime_config_store import RuntimeConfigStore
from src.controllers.execution_controller import ExecutionController
from src.services.exchange_client import ExchangeClient
from src.services.pnl_reporter import build_pnl_report_message, period_range_ms
from src.services.trade_notifier import TradeNotifier
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ReportController:
    """Envia relatório de PnL a cada intervalo configurado."""

    def __init__(
        self,
        settings: Settings,
        exchange: ExchangeClient,
        execution: ExecutionController,
        notifier: TradeNotifier,
        runtime_store: RuntimeConfigStore,
    ) -> None:
        self._settings = settings
        self._exchange = exchange
        self._execution = execution
        self._notifier = notifier
        self._runtime = runtime_store
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        runtime = self._runtime.reload()
        if not runtime.pnl_report.enabled:
            logger.info("Relatório PnL desabilitado (pnl_report.enabled=false)")
            return
        if not self._notifier.enabled:
            logger.warning(
                "Relatório PnL não iniciado | %s",
                self._notifier.missing_config_hint,
            )
            return
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="pnl-report")
        logger.info(
            "Relatório PnL iniciado | interval=%ds | period=%s",
            runtime.pnl_report.interval_seconds,
            runtime.pnl_report.period,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self._running:
            runtime = self._runtime.reload()
            await asyncio.sleep(runtime.pnl_report.interval_seconds)
            try:
                await self.send_report()
            except Exception:
                logger.exception("Erro no ciclo do relatório PnL")

    async def send_report(self) -> None:
        """Gera e envia relatório atual (útil para testes manuais)."""
        if not self._notifier.enabled:
            return

        await self._execution.sync_closed_positions()
        runtime = self._runtime.reload()
        period = runtime.pnl_report.period
        start_ms, end_ms = period_range_ms(period)

        try:
            stats = await self._exchange.fetch_closed_pnl_stats(start_ms, end_ms)
            rows = await self._exchange.fetch_open_position_report_rows()
        except Exception:
            logger.exception("Falha ao buscar PnL na Bybit — relatório abortado")
            return

        text = build_pnl_report_message(
            stats=stats,
            open_positions=rows,
            bybit_mode=self._settings.bybit_mode,
            period=period,
        )

        await self._notifier.send_message(text)
        pos = stats.get("position_groups") or {}
        logger.info(
            "Relatório PnL enviado | period=%s | fills=%d | positions=%d | "
            "pos_wr=%.1f%% | open=%d | realized=$%.2f",
            period,
            stats.get("closed_trades", 0),
            pos.get("position_trades", 0),
            float(pos.get("winrate_pct", 0)),
            len(rows),
            stats.get("total_pnl_usd", 0),
        )
