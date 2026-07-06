"""Testes de notificação de trade aberto."""

from __future__ import annotations

from pydantic import SecretStr

from src.config.settings import Settings
from src.models.schemas import TakeProfitLevel, TradeDecision, TradeDirection, TradeSource
from src.services.trade_notifier import TradeNotifier
from src.utils.formatters import format_trade_opened_message


def _settings(**kwargs) -> Settings:
    return Settings(
        telegram_api_id=1,
        telegram_api_hash="x",
        telegram_channel_id=1,
        **kwargs,
    )


class TestTradeNotifierConfig:
    def test_enabled_with_token_and_chat_id(self) -> None:
        notifier = TradeNotifier(
            _settings(
                telegram_bot_token=SecretStr("123:ABC"),
                telegram_notify_chat_id=999888777,
            )
        )
        assert notifier.enabled

    def test_disabled_without_chat_id(self) -> None:
        s = _settings(telegram_bot_token=SecretStr("123:ABC"))
        s = s.model_copy(update={"telegram_notify_chat_id": None})
        notifier = TradeNotifier(s)
        assert not notifier.enabled
        assert "NOTIFY_CHAT_ID" in (notifier.missing_config_hint or "")


class TestFormatTradeOpened:
    def test_includes_leverage_and_levels(self) -> None:
        decision = TradeDecision(
            approved=True,
            confidence=0.84,
            confidence_threshold=0.65,
            direction=TradeDirection.LONG,
            symbol="BTC/USDT",
            entry_price=100.0,
            stop_loss=98.0,
            leverage=20,
            source=TradeSource.SCANNER,
            take_profits=[
                TakeProfitLevel(price=101.0, percentage=1.0, risk_reward=0.5),
                TakeProfitLevel(price=102.0, percentage=2.0, risk_reward=1.0),
                TakeProfitLevel(price=103.0, percentage=3.0, risk_reward=1.5),
                TakeProfitLevel(price=104.0, percentage=4.0, risk_reward=2.0),
            ],
            bias="Multi-TF alinhado",
        )
        text = format_trade_opened_message(
            decision, leverage=20, amount=1.5, bybit_mode="demo"
        )
        assert "TRADE ABERTO" in text
        assert "20x" in text
        assert "BTCUSDT" in text
        assert "TP1" in text
