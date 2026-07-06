"""Testes: TP final (TP3) deve cobrir posição restante após parciais."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.services.exchange_client import ExchangeClient


async def _run_ensure_creates_tp_when_missing() -> None:
    client = ExchangeClient.__new__(ExchangeClient)
    client.amount_to_precision = lambda _s, a: a
    client.price_to_precision = lambda _s, p: p
    client.fetch_position_size = AsyncMock(return_value=42.0)
    client._collect_open_tp_snapshots = AsyncMock(return_value=[])
    client.create_partial_take_profit = AsyncMock(return_value={"id": "tp3-new"})

    result = await client.ensure_take_profit_for_remaining(
        "SOL/USDT",
        "buy",
        150.5,
    )

    assert result is not None
    assert result["status"] == "created"
    assert result["amount"] == pytest.approx(42.0)
    client.create_partial_take_profit.assert_awaited_once_with(
        "SOL/USDT",
        "sell",
        42.0,
        150.5,
    )


async def _run_ensure_skips_when_tp_covers_remaining() -> None:
    client = ExchangeClient.__new__(ExchangeClient)
    client.amount_to_precision = lambda _s, a: a
    client.price_to_precision = lambda _s, p: p
    client.fetch_position_size = AsyncMock(return_value=40.0)
    client._collect_open_tp_snapshots = AsyncMock(
        return_value=[{"order_id": "tp3", "price": 150.5, "amount": 40.0}]
    )
    client.create_partial_take_profit = AsyncMock()
    client.cancel_order = AsyncMock()

    result = await client.ensure_take_profit_for_remaining(
        "SOL/USDT",
        "buy",
        150.5,
    )

    assert result is not None
    assert result["status"] == "ok"
    client.create_partial_take_profit.assert_not_called()
    client.cancel_order.assert_not_called()


async def _run_ensure_recreates_undersized_tp() -> None:
    client = ExchangeClient.__new__(ExchangeClient)
    client.amount_to_precision = lambda _s, a: a
    client.price_to_precision = lambda _s, p: p
    client.fetch_position_size = AsyncMock(return_value=40.0)
    client._collect_open_tp_snapshots = AsyncMock(
        return_value=[{"order_id": "tp3-old", "price": 150.5, "amount": 10.0}]
    )
    client.cancel_order = AsyncMock()
    client.create_partial_take_profit = AsyncMock(return_value={"id": "tp3-new"})

    result = await client.ensure_take_profit_for_remaining(
        "SOL/USDT",
        "buy",
        150.5,
    )

    assert result is not None
    assert result["status"] == "created"
    client.cancel_order.assert_awaited_once_with("tp3-old", "SOL/USDT")
    client.create_partial_take_profit.assert_awaited_once_with(
        "SOL/USDT",
        "sell",
        40.0,
        150.5,
    )


def test_ensure_take_profit_creates_when_missing() -> None:
    asyncio.run(_run_ensure_creates_tp_when_missing())


def test_ensure_take_profit_skips_when_ok() -> None:
    asyncio.run(_run_ensure_skips_when_tp_covers_remaining())


def test_ensure_take_profit_recreates_undersized() -> None:
    asyncio.run(_run_ensure_recreates_undersized_tp())
