"""Cliente Telethon para escuta assíncrona de sinais no Telegram."""

from __future__ import annotations

import asyncio
import re
import sqlite3
from collections.abc import Awaitable, Callable
from typing import Any

from telethon import TelegramClient as TelethonClient
from telethon import events
from src.config.settings import Settings
from src.services.runtime_config_store import RuntimeConfigStore
from src.models.schemas import TelegramSignal, TradeStyle
from src.utils.logger import get_logger
from src.utils.telegram_topics import fetch_all_forum_topics, resolve_topic_names
from src.utils.telegram_parse import (
    extract_direction,
    extract_entry_price,
    extract_stop_loss,
    extract_symbol,
    extract_take_profits,
    is_trade_signal,
    parse_signal_fields,
)
from src.utils.trade_filters import infer_trade_style

logger = get_logger(__name__)

SignalHandler = Callable[[TelegramSignal], Awaitable[None]]


class TelegramClient:
    """Wrapper assíncrono do Telethon com filtro por tópicos e parsing de sinais."""

    def __init__(
        self,
        settings: Settings,
        runtime_store: RuntimeConfigStore | None = None,
    ) -> None:
        self._settings = settings
        self._runtime = runtime_store
        self._client: TelethonClient | None = None
        self._handler: SignalHandler | None = None
        self._running = False
        self._resolved_topic_ids: set[int] = set()

    @property
    def is_connected(self) -> bool:
        """Indica se o cliente está conectado."""
        return self._client is not None and self._client.is_connected()

    async def connect(self, max_retries: int = 6, retry_delay: float = 2.0) -> None:
        """Inicializa e conecta o cliente Telethon (retry se sessão SQLite bloqueada)."""
        if self._client is not None and self._client.is_connected():
            return

        self._client = TelethonClient(
            self._settings.telegram_session_name,
            self._settings.telegram_api_id,
            self._settings.telegram_api_hash.get_secret_value(),
        )

        last_err: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                await self._client.connect()
                last_err = None
                break
            except sqlite3.OperationalError as exc:
                last_err = exc
                if "locked" not in str(exc).lower():
                    raise
                if attempt >= max_retries:
                    break
                logger.warning(
                    "Sessão Telegram bloqueada (outra instância?) | tentativa %d/%d | aguardando %.0fs",
                    attempt,
                    max_retries,
                    retry_delay,
                )
                await asyncio.sleep(retry_delay)

        if last_err is not None:
            raise RuntimeError(
                "Sessão Telegram bloqueada. Feche outras janelas do BybitBot "
                "(start.bat/stop.bat) e tente de novo."
            ) from last_err

        if not await self._client.is_user_authorized():
            logger.error(
                "Sessão Telegram não autorizada. Execute autenticação manual primeiro."
            )
            raise RuntimeError("Telegram session not authorized")

        await self._resolve_topic_filters()
        logger.info("Telegram conectado | canal=%s", self._settings.telegram_channel_id)

    async def disconnect(self) -> None:
        """Desconecta o cliente de forma segura."""
        self._running = False
        if self._client is not None:
            try:
                await self._client.disconnect()
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                logger.warning("Sessão Telegram bloqueada ao desconectar — ignorando")
            self._client = None
        logger.info("Telegram desconectado")

    def on_signal(self, handler: SignalHandler) -> None:
        """Registra callback assíncrono para novos sinais."""
        self._handler = handler

    async def start_listening(self) -> None:
        """
        Inicia escuta contínua de mensagens.

        Erros internos no handler NÃO derrubam o listener.
        """
        if self._client is None:
            await self.connect()

        assert self._client is not None
        self._running = True
        channel_id = self._settings.telegram_channel_id

        @self._client.on(events.NewMessage(chats=channel_id))
        async def _on_new_message(event: events.NewMessage.Event) -> None:
            if not self._running:
                return

            try:
                signal = self._parse_message(event)
                if signal is None:
                    return

                topic_ids = self._get_effective_topic_ids()
                if topic_ids and signal.topic_id not in topic_ids:
                    logger.debug(
                        "Mensagem ignorada | topic_id=%s não está em %s",
                        signal.topic_id,
                        topic_ids,
                    )
                    return

                if self._handler is not None:
                    asyncio.create_task(self._safe_dispatch(signal))

            except Exception:
                logger.exception("Erro ao processar mensagem Telegram (listener ativo)")

        topic_ids = self._get_effective_topic_ids()
        logger.info(
            "Escuta ativa | canal=%s | topics=%s",
            channel_id,
            topic_ids or "todos",
        )
        await self._client.run_until_disconnected()

    def _get_effective_topic_ids(self) -> set[int]:
        """Retorna IDs efetivos: explícitos (settings.json) + resolvidos por nome."""
        explicit = set()
        if self._runtime is not None:
            explicit = set(self._runtime.reload().telegram.topic_ids)
        return explicit | self._resolved_topic_ids

    async def _resolve_topic_filters(self) -> None:
        """Resolve nomes de tópicos em IDs e cacheia para filtragem."""
        self._resolved_topic_ids = set()
        explicit_ids = set()
        configured_names: list[str] = []
        if self._runtime is not None:
            runtime = self._runtime.reload()
            explicit_ids = set(runtime.telegram.topic_ids)
            configured_names = list(runtime.telegram.topic_names)

        if not configured_names:
            if explicit_ids:
                logger.info("Filtro de tópicos por ID | ids=%s", sorted(explicit_ids))
            return

        if self._client is None:
            return

        try:
            entity = await self._client.get_entity(self._settings.telegram_channel_id)
            forum_topics = await fetch_all_forum_topics(self._client, entity)
            mappings, resolved_ids = resolve_topic_names(configured_names, forum_topics)
            self._resolved_topic_ids = resolved_ids

            for name, topic_id in mappings.items():
                if topic_id is not None:
                    logger.info("Tópico resolvido | nome=%r -> id=%s", name, topic_id)
                else:
                    logger.warning("Tópico não encontrado | nome=%r", name)

            effective_ids = explicit_ids | resolved_ids
            if effective_ids:
                logger.info(
                    "Filtro de tópicos ativo | ids=%s | nomes=%s",
                    sorted(effective_ids),
                    configured_names,
                )
            else:
                logger.warning(
                    "Nenhum tópico resolvido | nomes=%s | ids explícitos=%s",
                    configured_names,
                    sorted(explicit_ids) or "nenhum",
                )
        except Exception:
            logger.exception(
                "Falha ao resolver tópicos por nome; usando apenas IDs explícitos"
            )

    async def _safe_dispatch(self, signal: TelegramSignal) -> None:
        """Despacha sinal ao handler isolando exceções."""
        if self._handler is None:
            return
        try:
            await self._handler(signal)
        except Exception:
            logger.exception(
                "Erro no handler de sinal | msg_id=%s (listener continua)",
                signal.message_id,
            )

    def _parse_message(self, event: events.NewMessage.Event) -> TelegramSignal | None:
        """Extrai TelegramSignal de uma mensagem com estrutura de trade."""
        message = event.message
        if message is None or not message.message:
            return None

        text = message.message.strip()
        if not is_trade_signal(text):
            return None

        fields = parse_signal_fields(text)
        topic_id = self._extract_topic_id(message)
        primary_tf = "15m"
        if self._runtime is not None:
            primary_tf = self._runtime.reload().timeframes.primary
        trade_style = infer_trade_style(text, primary_tf)

        logger.info(
            "Sinal parseado | msg_id=%s | %s %s | entry=%s | sl=%s | tps=%d",
            message.id,
            fields["direction"].value if fields["direction"] else "?",
            fields["symbol"],
            fields["entry_price"],
            fields["stop_loss"],
            len(fields["take_profits"]),
        )

        return TelegramSignal(
            message_id=message.id,
            channel_id=event.chat_id or self._settings.telegram_channel_id,
            topic_id=topic_id,
            raw_text=text,
            symbol=fields["symbol"],
            direction=fields["direction"],
            entry_price=fields["entry_price"],
            stop_loss=fields["stop_loss"],
            take_profits=fields["take_profits"],
            leverage=fields["leverage"],
            trade_style=trade_style,
        )

    @staticmethod
    def _extract_topic_id(message: Any) -> int | None:
        """Extrai topic_id de mensagens de forum."""
        reply_to = getattr(message, "reply_to", None)
        if reply_to is not None:
            topic_id = getattr(reply_to, "reply_to_top_id", None)
            if topic_id is not None:
                return int(topic_id)
            forum_topic = getattr(reply_to, "forum_topic", None)
            if forum_topic is not None:
                return int(forum_topic)
        return getattr(message, "topic_id", None)

    # --- API legada (scripts/testes) ---
    _PRICE_PATTERN = re.compile(r"__entry__")
    _SL_PATTERN = re.compile(r"__sl__")

    def _extract_symbol(self, text: str):
        return extract_symbol(text)

    def _extract_direction(self, text: str):
        return extract_direction(text)

    def _extract_take_profits(self, text: str) -> list[float]:
        return extract_take_profits(text, extract_symbol(text))

    def _extract_price(self, pattern: re.Pattern[str], text: str) -> float | None:
        symbol = extract_symbol(text)
        if pattern is self._SL_PATTERN:
            return extract_stop_loss(text, symbol)
        return extract_entry_price(text, symbol)
