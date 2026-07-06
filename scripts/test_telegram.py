"""Testa conexão Telegram e localiza grupos/canais por nome."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telethon import TelegramClient, utils
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.types import Channel, Chat, User

from src.config.settings import get_settings
from src.services.runtime_config_store import RuntimeConfigStore
from src.utils.logger import get_logger, setup_logging
from src.utils.telegram_topics import (
    fetch_all_forum_topics,
    resolve_topic_names,
)

logger = get_logger(__name__)

TARGET_TITLE = "Grupo VIP do Mack"
SIMILAR_KEYWORDS = ("mack", "vip")
DEFAULT_TARGET_TOPIC_NAMES = (
    "Call membros",
    "calls top traders",
    "Sinais vip do mack",
)


def safe_print(text: str) -> None:
    """Imprime texto com fallback para caracteres não suportados no console."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
            sys.stdout.encoding or "utf-8", errors="replace"
        ))


def session_path(session_name: str) -> Path:
    """Retorna o caminho esperado do arquivo de sessão Telethon."""
    return Path(f"{session_name}.session")


def chat_type_label(entity: object) -> str:
    """Descreve o tipo de entidade do Telegram."""
    if isinstance(entity, Channel):
        if entity.megagroup:
            return "supergrupo"
        return "canal"
    if isinstance(entity, Chat):
        return "grupo"
    if isinstance(entity, User):
        return "usuário"
    return type(entity).__name__


async def get_member_count(client: TelegramClient, entity: object) -> int | None:
    """Obtém contagem de membros quando disponível."""
    try:
        if isinstance(entity, Channel):
            full = await client(GetFullChannelRequest(entity))
            return full.full_chat.participants_count
        if isinstance(entity, Chat):
            full = await client(GetFullChatRequest(entity.id))
            return full.full_chat.participants_count
    except Exception:
        logger.debug("Não foi possível obter contagem de membros", exc_info=True)
    return None


def message_preview(text: str | None, max_len: int = 120) -> str:
    """Formata preview de mensagem para exibição."""
    if not text:
        return "(sem texto)"
    compact = " ".join(text.split())
    if len(compact) <= max_len:
        return compact
    return f"{compact[: max_len - 3]}..."


async def iter_dialogs(client: TelegramClient) -> list[tuple[object, str]]:
    """Lista diálogos com título legível."""
    dialogs: list[tuple[object, str]] = []
    async for dialog in client.iter_dialogs():
        title = (dialog.title or dialog.name or "").strip()
        if title:
            dialogs.append((dialog.entity, title))
    return dialogs


def find_by_title(
    dialogs: list[tuple[object, str]],
    query: str,
) -> list[tuple[object, str]]:
    """Filtra diálogos cujo título contém a query (case insensitive)."""
    needle = query.casefold()
    return [(entity, title) for entity, title in dialogs if needle in title.casefold()]


def find_similar(dialogs: list[tuple[object, str]]) -> list[tuple[object, str]]:
    """Lista diálogos com nomes parecidos (Mack ou VIP)."""
    results: list[tuple[object, str]] = []
    for entity, title in dialogs:
        lowered = title.casefold()
        if any(keyword in lowered for keyword in SIMILAR_KEYWORDS):
            results.append((entity, title))
    return results


def target_topic_names(settings_names: list[str]) -> list[str]:
    """Retorna nomes de tópicos alvo (configurados ou padrão)."""
    return settings_names or list(DEFAULT_TARGET_TOPIC_NAMES)


async def print_forum_topics(
    client: TelegramClient,
    entity: object,
    target_names: list[str],
) -> None:
    """Lista tópicos do fórum e destaca os alvos configurados."""
    try:
        forum_topics = await fetch_all_forum_topics(client, entity)
    except Exception as exc:
        print(f"\n--- Tópicos do fórum ---")
        print(f"Não foi possível listar tópicos: {exc}")
        return

    if not forum_topics:
        print("\n--- Tópicos do fórum ---")
        print("(nenhum tópico encontrado ou grupo sem fórum habilitado)")
        return

    mappings, resolved_ids = resolve_topic_names(target_names, forum_topics)

    print(f"\n--- Tópicos do fórum ({len(forum_topics)} encontrados) ---")
    for topic in forum_topics:
        marker = ">>> ALVO <<<" if topic.id in resolved_ids else ""
        print(f"  - id={topic.id} | {topic.title} {marker}".rstrip())

    print("\n--- Tópicos alvo ---")
    for name in target_names:
        topic_id = mappings.get(name)
        if topic_id is not None:
            matched_title = next(
                (t.title for t in forum_topics if t.id == topic_id),
                "?",
            )
            print(f'  [OK] "{name}" -> id={topic_id} (título: "{matched_title}")')
        else:
            print(f'  [X]  "{name}" -> NÃO ENCONTRADO')

    if resolved_ids:
        ids_csv = ",".join(str(topic_id) for topic_id in sorted(resolved_ids))
        names_csv = ",".join(target_names)
        print("\n--- Sugestão para .env ---")
        print(f"TELEGRAM_TOPIC_NAMES={names_csv}")
        print(f"TELEGRAM_TOPIC_IDS={ids_csv}")
    else:
        print("\n--- Sugestão para .env ---")
        print(f"TELEGRAM_TOPIC_NAMES={','.join(target_names)}")
        print("TELEGRAM_TOPIC_IDS=")
        print("(nenhum ID resolvido — verifique os nomes dos tópicos acima)")


async def print_chat_details(
    client: TelegramClient,
    entity: object,
    title: str,
    configured_channel_id: int,
    target_names: list[str],
) -> None:
    """Exibe detalhes do chat encontrado."""
    chat_id = utils.get_peer_id(entity)
    chat_type = chat_type_label(entity)
    members = await get_member_count(client, entity)

    print(f"\n=== Grupo encontrado ===")
    print(f"Título: {title}")
    print(f"Chat ID: {chat_id}")
    print(f"Tipo: {chat_type}")
    if members is not None:
        print(f"Membros: {members}")

    if configured_channel_id:
        if chat_id == configured_channel_id:
            print(f"TELEGRAM_CHANNEL_ID: OK (bate com {configured_channel_id})")
        else:
            print(
                f"TELEGRAM_CHANNEL_ID: DIVERGENTE "
                f"(.env={configured_channel_id}, encontrado={chat_id})"
            )
            print(f"Atualize o .env com: TELEGRAM_CHANNEL_ID={chat_id}")

    await print_forum_topics(client, entity, target_names)

    print("\n--- Últimas 5 mensagens ---")
    count = 0
    async for message in client.iter_messages(entity, limit=5):
        count += 1
        sender = await message.get_sender()
        sender_name = getattr(sender, "first_name", None) or getattr(sender, "title", "?")
        date_str = message.date.strftime("%Y-%m-%d %H:%M:%S") if message.date else "?"
        safe_print(f"{count}. [{date_str}] {sender_name}: {message_preview(message.message)}")

    if count == 0:
        print("(nenhuma mensagem visível)")


async def main() -> int:
    settings = get_settings()
    runtime = RuntimeConfigStore(settings.settings_path).reload()
    setup_logging(runtime.log_level, runtime.log_format)

    target_names = target_topic_names(runtime.telegram.topic_names)
    session_file = session_path(settings.telegram_session_name)
    print(f"Sessão configurada: {settings.telegram_session_name}")
    print(f"Arquivo de sessão: {session_file} ({'existe' if session_file.exists() else 'não encontrado'})")
    print(f"TELEGRAM_CHANNEL_ID no .env: {settings.telegram_channel_id}")
    print(f"TELEGRAM_TOPIC_NAMES (settings.json): {runtime.telegram.topic_names or '(padrão)'}")
    print(f"TELEGRAM_TOPIC_IDS (settings.json): {runtime.telegram.topic_ids or '(vazio)'}")

    client = TelegramClient(
        settings.telegram_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash.get_secret_value(),
    )

    await client.connect()

    if not await client.is_user_authorized():
        print("\nSessão Telegram NÃO autorizada.")
        print("Execute a autenticação interativa primeiro:")
        print("  python scripts/auth_telegram.py")
        print("\nSerá necessário informar telefone e código de verificação do Telegram.")
        await client.disconnect()
        return 1

    me = await client.get_me()
    print(f"\nAutenticado como: {me.first_name} (id={me.id})")

    try:
        dialogs = await iter_dialogs(client)
        print(f"\nTotal de diálogos: {len(dialogs)}")

        matches = find_by_title(dialogs, TARGET_TITLE)
        if matches:
            for entity, title in matches:
                await print_chat_details(
                    client,
                    entity,
                    title,
                    settings.telegram_channel_id,
                    target_names,
                )
        else:
            print(f'\nNenhum chat encontrado com título contendo "{TARGET_TITLE}".')
            similar = find_similar(dialogs)
            if similar:
                print("\nChats parecidos (contêm Mack ou VIP):")
                for entity, title in similar:
                    chat_id = utils.get_peer_id(entity)
                    chat_type = chat_type_label(entity)
                    print(f"  - {title} | id={chat_id} | tipo={chat_type}")
            else:
                print("\nNenhum chat parecido com Mack ou VIP encontrado.")
    finally:
        await client.disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
