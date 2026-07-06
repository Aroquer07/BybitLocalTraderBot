"""Utilitários para resolução e matching de tópicos de fórum do Telegram."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from telethon import TelegramClient
from telethon.tl.functions.messages import GetForumTopicsRequest
from telethon.tl.types import ForumTopic

_FUZZY_MATCH_THRESHOLD = 0.75
_MIN_WORD_OVERLAP_RATIO = 0.8


def normalize_topic_name(name: str) -> str:
    """Normaliza nome de tópico para comparação (trim, casefold, espaços)."""
    return re.sub(r"\s+", " ", name.strip().casefold())


def score_topic_match(query: str, title: str) -> float:
    """Pontua similaridade entre nome configurado e título do tópico (0.0 a 1.0)."""
    normalized_query = normalize_topic_name(query)
    normalized_title = normalize_topic_name(title)
    if not normalized_query or not normalized_title:
        return 0.0
    if normalized_query == normalized_title:
        return 1.0
    if normalized_query in normalized_title:
        return 0.95
    if normalized_title in normalized_query:
        return 0.85

    query_words = set(normalized_query.split())
    title_words = set(normalized_title.split())
    if query_words:
        word_overlap = len(query_words & title_words) / len(query_words)
        if word_overlap >= _MIN_WORD_OVERLAP_RATIO:
            return 0.8 + word_overlap * 0.15

    return SequenceMatcher(None, normalized_query, normalized_title).ratio()


def topic_names_match(query: str, title: str) -> bool:
    """
    Verifica se query corresponde ao título do tópico.

    Case-insensitive, trim, match parcial ou fuzzy para pequenas diferenças.
    """
    return score_topic_match(query, title) >= _FUZZY_MATCH_THRESHOLD


async def fetch_all_forum_topics(client: TelegramClient, peer: object) -> list[ForumTopic]:
    """Busca todos os tópicos de fórum de um chat com paginação."""
    topics: list[ForumTopic] = []
    offset_topic = 0
    offset_id = 0
    offset_date = None

    while True:
        result = await client(
            GetForumTopicsRequest(
                peer=peer,
                offset_date=offset_date,
                offset_id=offset_id,
                offset_topic=offset_topic,
                limit=100,
            )
        )
        batch = [topic for topic in result.topics if isinstance(topic, ForumTopic)]
        topics.extend(batch)
        if len(batch) < 100:
            break
        last = batch[-1]
        offset_topic = last.id
        offset_id = last.top_message
        offset_date = last.date

    return topics


def resolve_topic_names(
    configured_names: list[str],
    forum_topics: list[ForumTopic],
) -> tuple[dict[str, int | None], set[int]]:
    """Mapeia nomes configurados para IDs de tópicos do fórum."""
    mappings: dict[str, int | None] = {}
    resolved_ids: set[int] = set()

    for name in configured_names:
        best_score = 0.0
        matched_topic: ForumTopic | None = None
        for topic in forum_topics:
            score = score_topic_match(name, topic.title)
            if score > best_score:
                best_score = score
                matched_topic = topic

        if matched_topic is not None and best_score >= _FUZZY_MATCH_THRESHOLD:
            mappings[name] = matched_topic.id
            resolved_ids.add(matched_topic.id)
        else:
            mappings[name] = None

    return mappings, resolved_ids
