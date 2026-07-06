"""Testes de processamento asyncio em lotes."""

from __future__ import annotations

import asyncio

from src.utils.async_batch import map_batched


def test_map_batched_respects_batch_size() -> None:
    calls: list[int] = []

    async def worker(n: int) -> int:
        calls.append(n)
        return n

    async def _run() -> list[int]:
        return await map_batched(
            list(range(10)),
            worker,
            batch_size=4,
            concurrency=2,
        )

    result = asyncio.run(_run())
    assert result == list(range(10))
    assert len(calls) == 10


def test_map_batched_skips_none() -> None:
    async def worker(n: int) -> int | None:
        return n if n % 2 == 0 else None

    async def _run() -> list[int]:
        return await map_batched(list(range(6)), worker, batch_size=3, concurrency=3)

    assert asyncio.run(_run()) == [0, 2, 4]
