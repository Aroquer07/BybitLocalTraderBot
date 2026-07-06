"""Cache TTL simples para OHLCV — evita re-fetch no mesmo ciclo."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any


class OhlcvCache:
    """Cache in-memory com TTL e limite de entradas (LRU)."""

    def __init__(self, *, ttl_seconds: float = 90.0, max_entries: int = 800) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._store: OrderedDict[tuple[str, str, int], tuple[float, list[Any]]] = (
            OrderedDict()
        )

    def get(self, key: tuple[str, str, int]) -> list[Any] | None:
        row = self._store.get(key)
        if row is None:
            return None
        ts, data = row
        if time.monotonic() - ts > self._ttl:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return data

    def set(self, key: tuple[str, str, int], data: list[Any]) -> None:
        self._store[key] = (time.monotonic(), data)
        self._store.move_to_end(key)
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()
