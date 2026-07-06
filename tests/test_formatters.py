"""Testes para formatadores de output de trade."""

from __future__ import annotations

from src.models.schemas import TakeProfitLevel, TradeDecision, TradeDirection, TradeSource, TradeStyle
from src.utils.formatters import (
    build_formatted_trade_output,
    format_rr_br,
    format_trade_opened_message,
)


class TestFormatRrBr:
    def test_comma_decimal(self) -> None:
        assert format_rr_br(2.1) == "1:2,1"
        assert format_rr_br(1.5) == "1:1,5"


class TestBuildFormattedTradeOutput:
    def test_scalp_layout(self) -> None:
        output = build_formatted_trade_output(
            direction=TradeDirection.LONG,
            symbol="BTC/USDT",
            entry_zone_min=95000.0,
            entry_zone_max=95200.0,
            stop_loss=94500.0,
            take_profits=[
                (96000.0, 50.0, 2.0),
                (96800.0, 30.0, 3.6),
                (97500.0, 20.0, 5.0),
            ],
            bias="Tendência bullish com suporte em fib 0.618",
            entry_condition="Reteste da zona com confirmação",
            confidence=0.92,
            trade_style=TradeStyle.SCALP,
        )

        assert "🚨 SCALP TÉCNICO - BTCUSDT 🚨" in output
        assert "📊 Direção: LONG 🟢" in output
        assert "📌 Probabilidade: 92%" in output
        assert "R:R 1:2,0" in output
        assert "🎯 TP3:" in output


class TestFormatTradeOpenedMessage:
    def test_scanner_layout_with_header(self) -> None:
        decision = TradeDecision(
            approved=True,
            confidence=0.84,
            confidence_threshold=0.72,
            direction=TradeDirection.SHORT,
            symbol="DASH/USDT",
            entry_price=35.4024,
            stop_loss=35.9234,
            leverage=20,
            trade_style=TradeStyle.SCALP,
            trade_style_label="SCALP",
            source=TradeSource.SCANNER,
            execution_timeframe="5m",
            bias="Tendência curta em todos os timeframes",
            take_profits=[
                TakeProfitLevel(price=35.4024, percentage=0.0, risk_reward=1.0),
                TakeProfitLevel(price=35.0448, percentage=1.0, risk_reward=2.0),
                TakeProfitLevel(price=34.6872, percentage=2.0, risk_reward=3.0),
                TakeProfitLevel(price=34.3296, percentage=3.0, risk_reward=4.0),
            ],
        )
        text = format_trade_opened_message(
            decision,
            leverage=20,
            amount=989.94,
            bybit_mode="demo",
        )
        assert text.startswith("✅ TRADE ABERTO | DEMO | scanner | 20x | qty=989.94")
        assert "🚨 SCALP TÉCNICO - DASHUSDT 🚨" in text
        assert "📊 Direção: SHORT 🔴" in text
        assert "📈 Viés: Tendência curta em todos os timeframes" in text
        assert "📌 Probabilidade: 84%" in text
        assert "✅ Condição: Sinal SHORT confirmado em 5m" in text
        assert "🎯 TP4:" in text
