"""Exporta últimas N mensagens dos tópicos alvo para análise de parsing."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telethon import TelegramClient, utils
from telethon.tl.types import Message

from src.config.settings import get_settings
from src.services.runtime_config_store import RuntimeConfigStore
from src.utils.telegram_topics import fetch_all_forum_topics, resolve_topic_names

TARGET_TITLE = "Grupo VIP do Mack"
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 100
OUT = ROOT / "data" / "telegram_samples.json"


def _topic_id(message: Message) -> int | None:
    reply_to = getattr(message, "reply_to", None)
    if reply_to is not None:
        top = getattr(reply_to, "reply_to_top_id", None)
        if top is not None:
            return int(top)
        forum = getattr(reply_to, "forum_topic", None)
        if forum is not None:
            return int(forum)
    return getattr(message, "topic_id", None)


async def main() -> int:
    settings = get_settings()
    runtime = RuntimeConfigStore(settings.settings_path).reload()
    target_names = runtime.telegram.topic_names or [
        "Call membros",
        "calls top traders",
        "Sinais vip do mack",
    ]

    client = TelegramClient(
        settings.telegram_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash.get_secret_value(),
    )
    await client.connect()
    if not await client.is_user_authorized():
        print("Sessão não autorizada")
        return 1

    entity = None
    async for dialog in client.iter_dialogs():
        title = (dialog.title or "").strip()
        if TARGET_TITLE.casefold() in title.casefold():
            entity = dialog.entity
            break
    if entity is None:
        print("Grupo não encontrado")
        return 1

    forum_topics = await fetch_all_forum_topics(client, entity)
    mappings, resolved_ids = resolve_topic_names(target_names, forum_topics)
    topic_titles = {t.id: t.title for t in forum_topics}

    samples: list[dict] = []
    async for message in client.iter_messages(entity, limit=LIMIT):
        if not message.message:
            continue
        tid = _topic_id(message)
        samples.append(
            {
                "id": message.id,
                "date": message.date.isoformat() if message.date else None,
                "topic_id": tid,
                "topic_title": topic_titles.get(tid or -1, "?"),
                "text": message.message,
            }
        )

    payload = {
        "channel_id": utils.get_peer_id(entity),
        "target_topics": {name: mappings.get(name) for name in target_names},
        "resolved_ids": sorted(resolved_ids),
        "count": len(samples),
        "messages": samples,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Salvo {len(samples)} mensagens em {OUT}")
    await client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
