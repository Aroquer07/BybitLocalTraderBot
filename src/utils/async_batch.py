"""Utilitários asyncio — processamento em lotes com concorrência limitada."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


async def map_batched(
    items: Sequence[T],
    worker: Callable[[T], Awaitable[R | None]],
    *,
    batch_size: int,
    concurrency: int | None = None,
    on_batch_done: Callable[[int, int, int], None] | None = None,
) -> list[R]:
    """
    Executa `worker` em lotes sequenciais; dentro de cada lote, até `concurrency` em paralelo.

    Args:
        items: itens a processar
        worker: coroutine por item (retorne None para ignorar)
        batch_size: tamanho de cada lote
        concurrency: semáforo global (default = batch_size)
        on_batch_done: callback(batch_start, batch_end, total_results)
    """
    if not items:
        return []

    limit = concurrency or batch_size
    sem = asyncio.Semaphore(max(1, limit))
    results: list[R] = []

    async def _run(item: T) -> R | None:
        async with sem:
            return await worker(item)

    total = len(items)
    for start in range(0, total, batch_size):
        chunk = items[start : start + batch_size]
        batch_out = await asyncio.gather(*[_run(item) for item in chunk])
        for value in batch_out:
            if value is not None:
                results.append(value)
        if on_batch_done is not None:
            on_batch_done(start, min(start + len(chunk), total), len(results))

    return results
