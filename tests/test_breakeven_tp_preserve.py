"""Testes: breakeven não deve apagar TPs restantes."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.services.exchange_client import ExchangeClient


async def _run_restore_missing_tps() -> None:
    client = ExchangeClient.__new__(ExchangeClient)
    client.amount_to_precision = lambda _s, a: a
    client.price_to_precision = lambda _s, p: p

    tp_snapshots = [
        {"price": 0.05964, "amount": 95471.0, "level": 2},
        {"price": 0.0603, "amount": 63647.0, "level": 3},
    ]

    async def fake_collect(symbol: str, entry_side: str):
        if not hasattr(fake_collect, "call"):
            fake_collect.call = 0
        fake_collect.call += 1
        if fake_collect.call == 1:
            return list(tp_snapshots)
        return []

    client._collect_open_tp_snapshots = AsyncMock(side_effect=fake_collect)
    client.fetch_open_stop_loss_price = AsyncMock(return_value=None)
    client.cancel_stop_loss_orders = AsyncMock(return_value=1)
    client.create_partial_stop_loss = AsyncMock(return_value={"id": "sl-new"})
    client.create_partial_take_profit = AsyncMock(
        side_effect=[{"id": "tp2-new"}, {"id": "tp3-new"}]
    )
    client.fetch_position_size = AsyncMock(return_value=159119.0)

    result = await client.move_stop_loss_to_entry(
        "WLFI/USDT",
        "buy",
        0.05903,
        amount=159119.0,
        tp_fallback=tp_snapshots,
    )

    assert result.get("id") == "sl-new"
    restored = result.get("restored_tps") or []
    assert len(restored) == 2
    assert restored[0]["price"] == pytest.approx(0.05964)
    assert client.create_partial_take_profit.await_count == 2


async def _run_skips_when_tps_still_open() -> None:
    client = ExchangeClient.__new__(ExchangeClient)
    client.amount_to_precision = lambda _s, a: a
    client.price_to_precision = lambda _s, p: p

    tp_snapshots = [{"price": 0.05964, "amount": 95471.0}]

    async def fake_collect(symbol: str, entry_side: str):
        return list(tp_snapshots)

    client._collect_open_tp_snapshots = AsyncMock(side_effect=fake_collect)
    client.fetch_open_stop_loss_price = AsyncMock(return_value=None)
    client.cancel_stop_loss_orders = AsyncMock(return_value=1)
    client.create_partial_stop_loss = AsyncMock(return_value={"id": "sl-new"})
    client.create_partial_take_profit = AsyncMock()
    client.fetch_position_size = AsyncMock(return_value=159119.0)

    result = await client.move_stop_loss_to_entry(
        "WLFI/USDT",
        "buy",
        0.05903,
        amount=159119.0,
    )

    assert result.get("restored_tps") == []
    client.create_partial_take_profit.assert_not_called()


def test_move_stop_loss_to_entry_restores_missing_tps() -> None:
    asyncio.run(_run_restore_missing_tps())


def test_move_stop_loss_skips_restore_when_tps_still_open() -> None:
    asyncio.run(_run_skips_when_tps_still_open())


async def _run_skips_when_sl_already_at_entry() -> None:
    client = ExchangeClient.__new__(ExchangeClient)
    client.amount_to_precision = lambda _s, a: a
    client.price_to_precision = lambda _s, p: p
    client.fetch_open_stop_loss_price = AsyncMock(return_value=0.05903)
    client.is_stop_at_entry = ExchangeClient.is_stop_at_entry
    client._collect_open_tp_snapshots = AsyncMock(
        return_value=[{"price": 0.05964, "amount": 95471.0}]
    )
    client.cancel_stop_loss_orders = AsyncMock()
    client.create_partial_stop_loss = AsyncMock()
    client.create_partial_take_profit = AsyncMock()

    result = await client.move_stop_loss_to_entry(
        "WLFI/USDT",
        "buy",
        0.05903,
        amount=159119.0,
    )

    assert result.get("skipped") is True
    assert result.get("restored_tps") == []
    client.cancel_stop_loss_orders.assert_not_called()
    client.create_partial_stop_loss.assert_not_called()
    client.create_partial_take_profit.assert_not_called()


def test_move_stop_loss_skips_when_sl_already_at_entry() -> None:
    asyncio.run(_run_skips_when_sl_already_at_entry())
