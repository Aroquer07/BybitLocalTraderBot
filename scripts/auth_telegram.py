"""Autenticação interativa da sessão Telethon (rodar uma vez)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telethon import TelegramClient
from src.config.settings import get_settings
from src.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    setup_logging()

    client = TelegramClient(
        settings.telegram_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash.get_secret_value(),
    )

    await client.start()
    me = await client.get_me()
    logger.info("Autenticado como %s (id=%s)", me.username or me.first_name, me.id)
    await client.disconnect()
    logger.info("Sessão salva em '%s.session'", settings.telegram_session_name)


if __name__ == "__main__":
    asyncio.run(main())
