"""Notificações de trade via Telegram Bot API (bot -> você)."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request

from src.config.settings import Settings
from src.models.schemas import TradeDecision
from src.utils.formatters import format_trade_opened_message
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TradeNotifier:
    """Envia resumo de operação aberta para o seu chat via Bot API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return bool(
            self._settings.telegram_bot_token
            and self._settings.telegram_notify_chat_id is not None
        )

    @property
    def missing_config_hint(self) -> str | None:
        if not self._settings.telegram_bot_token:
            return "TELEGRAM_BOT_TOKEN ausente"
        if self._settings.telegram_notify_chat_id is None:
            return "TELEGRAM_NOTIFY_CHAT_ID ausente — use @userinfobot para obter seu id"
        return None

    async def notify_trade_opened(
        self,
        decision: TradeDecision,
        *,
        leverage: int,
        amount: float,
    ) -> None:
        if not self.enabled:
            hint = self.missing_config_hint
            if hint:
                logger.debug("Notificação desligada | %s", hint)
            return

        text = format_trade_opened_message(
            decision,
            leverage=leverage,
            amount=amount,
            bybit_mode=self._settings.bybit_mode,
        )
        await self.send_message(text)

    async def send_message(self, text: str) -> None:
        if not self.enabled:
            return
        chat_id = self._settings.telegram_notify_chat_id
        assert chat_id is not None
        await asyncio.to_thread(self._send_bot_api, chat_id, text)

    def _send_bot_api(self, chat_id: int, text: str) -> None:
        token = self._settings.telegram_bot_token
        if token is None:
            return
        url = f"https://api.telegram.org/bot{token.get_secret_value()}/sendMessage"
        payload = json.dumps(
            {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                if resp.status != 200:
                    logger.warning("Bot API notify status=%s | %s", resp.status, body)
                    return
                logger.info("Notificação enviada | chat_id=%s", chat_id)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            logger.error(
                "Bot API notify falhou | chat=%s | %s | %s",
                chat_id,
                exc,
                detail,
            )
        except Exception:
            logger.exception("Bot API notify erro | chat=%s", chat_id)
