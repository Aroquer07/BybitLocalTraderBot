"""Testes de blacklist, slippage block e entry limit chasing."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import Settings
from src.services.exchange_client import (
    ENTRY_CHASE_MAX_ATTEMPTS,
    ENTRY_CHASE_TTL_SEC,
    EntryOrderExpiredError,
    ExchangeClient,
)
from src.services.slippage_guard import (
    block_symbol_temporarily,
    format_slippage_alert,
    is_symbol_slippage_blocked,
)
from src.strategies.scanner_filters import (
    SYMBOL_BLACKLIST,
    is_symbol_blacklisted,
    normalize_symbol_key,
)


class TestSymbolBlacklist:
    def test_blacklisted_pairs(self) -> None:
        for sym in SYMBOL_BLACKLIST:
            blocked, reason = is_symbol_blacklisted(sym)
            assert blocked is True
            assert sym in reason

    def test_normalize_formats(self) -> None:
        assert normalize_symbol_key("AVA/USDT") == "AVAUSDT"
        assert normalize_symbol_key("SOON/USDT:USDT") == "SOONUSDT"

    def test_allowed_pair(self) -> None:
        blocked, _ = is_symbol_blacklisted("BTC/USDT")
        assert blocked is False


class TestSlippageBlock:
    def test_block_and_release(self) -> None:
        block_symbol_temporarily("XANUSDT", duration_sec=60)
        blocked, reason = is_symbol_slippage_blocked("XAN/USDT")
        assert blocked is True
        assert "XANUSDT" in reason

    def test_urgent_alert_format(self) -> None:
        from src.services.slippage_guard import SlippageEvent

        msg = format_slippage_alert(
            SlippageEvent(
                symbol="SOONUSDT",
                context="entry",
                order_price=0.194,
                exec_price=0.172,
                slippage_pct=11.34,
            )
        )
        assert "[SLIPPAGE URGENTE]" in msg


@pytest.fixture
def exchange_client() -> ExchangeClient:
    settings = Settings(
        telegram_api_id=1,
        telegram_api_hash="x",
        telegram_channel_id=1,
        bybit_api_key="k",
        bybit_api_secret="s",
        bybit_mode="demo",
    )
    client = ExchangeClient(settings)
    mock_exchange = MagicMock()
    mock_exchange.markets = {
        "BTC/USDT:USDT": {
            "swap": True,
            "linear": True,
            "type": "swap",
            "base": "BTC",
            "limits": {"amount": {"min": 0.001}, "leverage": {"max": 50.0}},
            "precision": {"amount": 0.001, "price": 0.01},
            "contractSize": 1.0,
            "info": {"lotSizeFilter": {"minOrderQty": "0.001", "qtyStep": "0.001"}},
        }
    }
    client._exchange = mock_exchange
    return client


class TestLimitEntryChase:
    def test_expires_on_ttl(self, exchange_client: ExchangeClient) -> None:
        exchange_client.set_leverage = AsyncMock(return_value=10)
        exchange_client._submit_limit_order = AsyncMock(
            return_value={"id": "ord-1", "status": "open", "filled": 0}
        )
        exchange_client.fetch_order = AsyncMock(
            return_value={"id": "ord-1", "status": "open", "filled": 0}
        )
        exchange_client.cancel_order = AsyncMock(return_value={})
        exchange_client._resolve_chase_limit_price = AsyncMock(return_value=100.0)

        async def _run() -> None:
            with patch("src.services.exchange_client.asyncio.sleep", new_callable=AsyncMock):
                with patch("src.services.exchange_client.time.monotonic") as mock_time:
                    mock_time.side_effect = [0.0, ENTRY_CHASE_TTL_SEC + 1]
                    with pytest.raises(EntryOrderExpiredError):
                        await exchange_client._create_limit_entry_with_chase(
                            "BTC/USDT",
                            "buy",
                            0.01,
                            10,
                            100.0,
                        )

        asyncio.run(_run())
        exchange_client.cancel_order.assert_called()

    def test_fills_and_returns(self, exchange_client: ExchangeClient) -> None:
        exchange_client.set_leverage = AsyncMock(return_value=10)
        exchange_client._submit_limit_order = AsyncMock(
            return_value={"id": "ord-1", "status": "open", "filled": 0}
        )
        exchange_client.fetch_order = AsyncMock(
            return_value={"id": "ord-1", "status": "closed", "filled": 0.01, "average": 100.5}
        )

        async def _run() -> None:
            with patch("src.services.exchange_client.asyncio.sleep", new_callable=AsyncMock):
                order, lev = await exchange_client._create_limit_entry_with_chase(
                    "BTC/USDT",
                    "buy",
                    0.01,
                    10,
                    100.0,
                )
            assert lev == 10
            assert order["average"] == 100.5

        asyncio.run(_run())
