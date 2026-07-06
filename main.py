"""Entrypoint do Agente de Trading Autônomo e Híbrido."""

from __future__ import annotations

import asyncio
import atexit
import os
import signal
import sys
from pathlib import Path

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

from src.config.settings import get_settings
from src.controllers.brain_controller import BrainController
from src.controllers.execution_controller import ExecutionController
from src.controllers.report_controller import ReportController
from src.controllers.scanner_controller import ScannerController
from src.controllers.signal_controller import SignalController
from src.models.schemas import TelegramSignal, TradeDecision, TradeSource
from src.services.exchange_client import ExchangeClient
from src.services.llm_client import LLMClient
from src.services.runtime_config_store import RuntimeConfigStore
from src.services.telegram_client import TelegramClient
from src.services.trade_notifier import TradeNotifier
from src.services.watchlist_loader import load_watchlist_file
from src.strategies.technical_analysis import TechnicalAnalysisEngine
from src.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent
_PID_FILE = _PROJECT_ROOT / ".run" / "bot.pid"


def _write_pid_file() -> None:
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()), encoding="utf-8")


def _remove_pid_file() -> None:
    try:
        _PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


atexit.register(_remove_pid_file)


class TradingAgent:
    """Orquestrador — Telegram + Scanner IMBA + LLM + execução."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._runtime = RuntimeConfigStore(self._settings.settings_path)
        self._shutdown_event = asyncio.Event()

        self._telegram = TelegramClient(self._settings, self._runtime)
        self._exchange = ExchangeClient(self._settings, self._runtime)
        self._llm = LLMClient(self._settings, self._runtime)
        self._ta = TechnicalAnalysisEngine(self._settings, self._runtime)
        self._trade_notifier = TradeNotifier(self._settings)

        self._execution_ctrl = ExecutionController(
            self._settings,
            self._exchange,
            self._runtime,
            trade_notifier=self._trade_notifier,
        )
        self._signal_ctrl = SignalController(
            self._settings,
            self._telegram,
            self._runtime,
        )
        self._brain_ctrl = BrainController(
            self._settings,
            self._exchange,
            self._llm,
            self._ta,
            self._runtime,
        )
        self._scanner_ctrl = ScannerController(
            self._settings,
            self._exchange,
            self._llm,
            self._execution_ctrl,
            self._runtime,
            self._ta,
        )
        self._report_ctrl = ReportController(
            self._settings,
            self._exchange,
            self._execution_ctrl,
            self._trade_notifier,
            self._runtime,
        )

    def _wire_pipeline(self) -> None:
        self._signal_ctrl.on_signal(self._brain_ctrl.process_signal)
        self._brain_ctrl.on_decision(self._on_trade_decision)

    async def _on_trade_decision(
        self,
        signal: TelegramSignal,
        decision: TradeDecision,
    ) -> None:
        decision = decision.model_copy(update={"source": TradeSource.TELEGRAM})
        await self._execution_ctrl.handle_decision(signal, decision)

    async def start(self) -> None:
        runtime = self._runtime.reload()
        setup_logging(runtime.log_level, runtime.log_format)
        logger.info(
            "BybitBot iniciando | mode=%s | settings=%s",
            self._settings.bybit_mode,
            self._settings.settings_path,
        )

        self._wire_pipeline()

        try:
            await self._exchange.connect()
        except Exception:
            logger.exception(
                "Bybit indisponível no startup — escuta continuará"
            )

        try:
            ollama_ok = await self._llm.warmup()
        except Exception:
            ollama_ok = False
            logger.exception("Ollama indisponível no startup")

        stats = self._execution_ctrl.journal.get_stats()
        watchlist = load_watchlist_file(runtime.scanner.watchlist_path)
        notify_hint = self._trade_notifier.missing_config_hint
        if notify_hint:
            logger.warning("Notificações Telegram desligadas | %s", notify_hint)
        else:
            logger.info(
                "Notificações Telegram ativas | chat_id=%s",
                self._settings.telegram_notify_chat_id,
            )
        logger.info(
            "Pipeline pronto | telegram_kill=%.0f%% | scanner_min=%.0f%% | "
            "max_pos=%d | breakeven_tp=%d | watchlist=%d (%s) | screener=%s | journal=%s",
            runtime.confidence.telegram * 100,
            runtime.confidence.scanner * 100,
            runtime.effective_max_concurrent_trades(self._settings.bybit_mode),
            runtime.breakeven.level,
            len(watchlist),
            runtime.scanner.watchlist_path,
            "on" if runtime.scanner.screener.enabled else "off",
            stats,
        )

        await self._execution_ctrl.resume_breakeven_for_open_trades()

        await self._scanner_ctrl.start()
        await self._report_ctrl.start()
        await self._signal_ctrl.start()

    async def stop(self) -> None:
        logger.info("Encerrando BybitBot...")
        await self._scanner_ctrl.stop()
        await self._report_ctrl.stop()
        await self._signal_ctrl.stop()
        await self._exchange.disconnect()
        self._shutdown_event.set()
        _remove_pid_file()
        logger.info("BybitBot encerrado | stats=%s", self._execution_ctrl.journal.get_stats())


async def main() -> None:
    _write_pid_file()
    agent = TradingAgent()
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        logger.info("Sinal de shutdown recebido")
        asyncio.create_task(agent.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    try:
        await agent.start()
    except KeyboardInterrupt:
        await agent.stop()
    except Exception:
        logger.exception("Erro fatal no agente")
        await agent.stop()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
