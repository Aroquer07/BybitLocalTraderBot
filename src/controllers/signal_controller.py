"""Controller de sinais — orquestra escuta do Telegram e despacho ao Brain."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from src.config.settings import Settings
from src.services.runtime_config_store import RuntimeConfigStore
from src.models.schemas import TelegramSignal
from src.services.telegram_client import TelegramClient
from src.utils.logger import get_logger

logger = get_logger(__name__)

SignalCallback = Callable[[TelegramSignal], Awaitable[None]]


class SignalController:
    """
    Orquestra a escuta contínua do Telegram.

    Responsável apenas por receber sinais e encaminhar ao próximo estágio.
    Falhas downstream NÃO interrompem a escuta.
    """

    def __init__(
        self,
        settings: Settings,
        telegram_client: TelegramClient,
        runtime_store: RuntimeConfigStore,
    ) -> None:
        self._settings = settings
        self._telegram = telegram_client
        self._runtime = runtime_store
        self._on_signal_callback: SignalCallback | None = None

    def on_signal(self, callback: SignalCallback) -> None:
        """Registra callback para novos sinais validados."""
        self._on_signal_callback = callback

    async def start(self) -> None:
        """Inicia pipeline de escuta do Telegram."""
        self._telegram.on_signal(self._handle_signal)
        await self._telegram.connect()

        runtime = self._runtime.reload()
        logger.info(
            "SignalController ativo | canal=%s | topics=%s",
            self._settings.telegram_channel_id,
            runtime.telegram.topic_ids or "todos",
        )
        await self._telegram.start_listening()

    async def stop(self) -> None:
        """Para escuta e desconecta."""
        await self._telegram.disconnect()
        logger.info("SignalController encerrado")

    async def _handle_signal(self, signal: TelegramSignal) -> None:
        """Handler interno — loga e despacha ao Brain."""
        logger.info(
            "Sinal recebido | msg_id=%s | symbol=%s | direction=%s | estilo=%s",
            signal.message_id,
            signal.symbol,
            signal.direction,
            signal.trade_style.value if signal.trade_style else "?",
        )

        if self._on_signal_callback is not None:
            try:
                await self._on_signal_callback(signal)
            except Exception:
                logger.exception(
                    "Erro no callback de sinal | msg_id=%s (escuta continua)",
                    signal.message_id,
                )
