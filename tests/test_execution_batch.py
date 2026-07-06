"""Testes de slots e execução em batch."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.runtime_config import BotRuntimeConfig
from src.config.settings import Settings
from src.controllers.execution_controller import ExecutionController
from src.models.schemas import TradeDecision, TradeDirection, TradeSource
from src.services.runtime_config_store import RuntimeConfigStore


def _approved_decision(symbol: str, confidence: float) -> TradeDecision:
    return TradeDecision(
        approved=True,
        symbol=symbol,
        direction=TradeDirection.LONG,
        entry_price=100.0,
        stop_loss=98.0,
        leverage=20,
        confidence=confidence,
        confidence_threshold=0.65,
        source=TradeSource.SCANNER,
        take_profits=[],
    )


@pytest.fixture
def execution_ctrl(tmp_path) -> ExecutionController:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        BotRuntimeConfig().model_dump_json(indent=2),
        encoding="utf-8",
    )
    settings = Settings(
        bybit_api_key="k",
        bybit_api_secret="s",
        bybit_mode="demo",
        settings_path=str(settings_path),
    )
    runtime = RuntimeConfigStore(str(settings_path))
    exchange = MagicMock()
    exchange.count_open_positions = AsyncMock(return_value=7)
    return ExecutionController(settings, exchange, runtime)


def test_available_trade_slots_demo(execution_ctrl: ExecutionController) -> None:
    slots = asyncio.run(execution_ctrl.available_trade_slots())
    assert slots == 3


def test_execute_batch_stops_at_limit(execution_ctrl: ExecutionController) -> None:
    execution_ctrl.execute_imba_decision = AsyncMock(return_value={"entry": {"id": "1"}})
    execution_ctrl.can_open_new_trade = AsyncMock(
        side_effect=[
            (True, ""),
            (True, ""),
            (True, ""),
            (False, "Limite"),
        ]
    )
    decisions = [
        _approved_decision("BTC/USDT", 0.9),
        _approved_decision("ETH/USDT", 0.8),
        _approved_decision("SOL/USDT", 0.7),
        _approved_decision("XRP/USDT", 0.66),
    ]
    results = asyncio.run(execution_ctrl.execute_decisions_batch(decisions))
    assert len(results) == 3
    assert execution_ctrl.execute_imba_decision.await_count == 3
