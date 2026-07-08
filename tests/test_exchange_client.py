"""Testes para ExchangeClient (limites de mercado)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.config.settings import Settings
from src.services.exchange_client import (
    ABSOLUTE_MAX_LEVERAGE,
    ExchangeClient,
    _parse_max_leverage_from_error,
    _parse_risk_tier_max_leverage,
    clamp_leverage_hard,
)


class TestParseRiskTierMaxLeverage:
    def test_extracts_suggested_leverage(self) -> None:
        msg = (
            'bybit {"retCode":110090,"retMsg":"Please adjust your leverage to 40 '
            'or below to increase the limit."}'
        )
        assert _parse_risk_tier_max_leverage(msg) == 40

    def test_returns_none_when_missing(self) -> None:
        assert _parse_risk_tier_max_leverage("other error") is None


class TestParseMaxLeverageFromError:
    def test_extracts_market_max_leverage(self) -> None:
        msg = (
            'bybit {"retCode":110013,"retMsg":"cannot set leverage [5000] '
            'gt maxLeverage [2000] by risk limit"}'
        )
        assert _parse_max_leverage_from_error(msg) == 20


class TestClampLeverageHard:
    def test_hard_cap_at_15(self) -> None:
        assert clamp_leverage_hard(50) == ABSOLUTE_MAX_LEVERAGE
        assert clamp_leverage_hard(50, config_max=20) == 15
        assert clamp_leverage_hard(15, market_max=10) == 10
        assert clamp_leverage_hard(0) == 1


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
        "TRUMP/USDT:USDT": {
            "swap": True,
            "linear": True,
            "type": "swap",
            "base": "TRUMP",
            "limits": {"amount": {"min": 0.1, "max": 40000.0}, "leverage": {"max": 50.0}},
            "precision": {"amount": 0.1, "price": 0.001},
            "contractSize": 1.0,
            "info": {
                "lotSizeFilter": {
                    "maxOrderQty": "40000.0",
                    "maxMktOrderQty": "8000.0",
                    "minOrderQty": "0.1",
                    "qtyStep": "0.1",
                }
            },
        }
    }
    client._exchange = mock_exchange
    return client


class TestGetMarketLimits:
    def test_caps_max_amount_by_max_mkt_order_qty(
        self, exchange_client: ExchangeClient
    ) -> None:
        limits = exchange_client.get_market_limits("TRUMP/USDT")
        assert limits["max_amount"] == 8000.0
        assert limits["min_amount"] == 0.1

    def test_uses_max_amount_when_no_mkt_cap(
        self, exchange_client: ExchangeClient
    ) -> None:
        market = exchange_client._exchange.markets["TRUMP/USDT:USDT"]
        market["info"]["lotSizeFilter"].pop("maxMktOrderQty")
        limits = exchange_client.get_market_limits("TRUMP/USDT")
        assert limits["max_amount"] == 40000.0
