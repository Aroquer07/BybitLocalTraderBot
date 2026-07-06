"""Testes do cache OHLCV."""

from __future__ import annotations

import time

from src.services.ohlcv_cache import OhlcvCache


def test_cache_hit_within_ttl() -> None:
    cache = OhlcvCache(ttl_seconds=60.0)
    key = ("BTC/USDT:USDT", "5m", 200)
    data = [[1, 2, 3, 4, 5, 6]]
    cache.set(key, data)
    assert cache.get(key) == data


def test_cache_miss_after_ttl() -> None:
    cache = OhlcvCache(ttl_seconds=0.01)
    key = ("ETH/USDT:USDT", "15m", 100)
    cache.set(key, [[1]])
    time.sleep(0.02)
    assert cache.get(key) is None
