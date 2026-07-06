"""Testes do relatório periódico de PnL."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.models.schemas import StoredTrade, TradeDirection, TradeSource, TradeStatus
from src.services.pnl_reporter import (
    aggregate_closed_pnl_records,
    build_pnl_report_message,
    period_range_ms,
    position_row_from_exchange,
    realized_pnl_usd,
    unrealized_pnl_pct,
    unrealized_pnl_usd,
)


def _trade(direction: TradeDirection, entry: float, amount: float = 10.0) -> StoredTrade:
    return StoredTrade(
        id="x",
        symbol="BTC/USDT",
        direction=direction,
        source=TradeSource.SCANNER,
        status=TradeStatus.OPEN,
        entry_price=entry,
        stop_loss=entry * 0.99,
        confidence=0.8,
        leverage=15,
        amount=amount,
    )


class TestAggregateClosedPnl:
    def test_wins_losses_and_total(self) -> None:
        stats = aggregate_closed_pnl_records(
            [
                {"closedPnl": "100.5", "symbol": "A", "side": "Buy", "avgEntryPrice": "1"},
                {"closedPnl": "-60.1334", "symbol": "A", "side": "Buy", "avgEntryPrice": "1"},
                {"closedPnl": "175.8572", "symbol": "B", "side": "Sell", "avgEntryPrice": "2"},
            ]
        )
        assert stats["closed_trades"] == 3
        assert stats["wins"] == 2
        assert stats["losses"] == 1
        assert stats["total_pnl_usd"] == 216.22
        assert stats["winrate_pct"] == 66.67
        assert stats["position_groups"]["position_trades"] == 2


class TestPeriodRange:
    def test_week_range(self) -> None:
        start, end = period_range_ms("week")
        assert end > start
        assert end - start == 7 * 86_400_000


class TestPositionRowFromExchange:
    def test_uses_exchange_unrealized_pnl(self) -> None:
        row = position_row_from_exchange(
            {
                "symbol": "XRP/USDT:USDT",
                "side": "long",
                "contracts": 29019.9,
                "entryPrice": 1.1127,
                "markPrice": 1.1203,
                "unrealizedPnl": 217.6492,
                "notional": 32534.0,
                "leverage": 15.0,
            }
        )
        assert row is not None
        assert row["symbol"] == "XRP/USDT"
        assert row["direction"] == "LONG"
        assert row["pnl_usd"] == 217.65
        assert row["pnl_pct"] > 8.0


class TestUnrealizedPnl:
    def test_long_profit(self) -> None:
        pnl = unrealized_pnl_pct(_trade(TradeDirection.LONG, 100.0), 101.0)
        assert pnl == 1.0

    def test_short_profit(self) -> None:
        pnl = unrealized_pnl_pct(_trade(TradeDirection.SHORT, 100.0), 99.0)
        assert pnl == 1.0

    def test_long_profit_usd(self) -> None:
        trade = _trade(TradeDirection.LONG, 100.0, amount=5.0)
        assert unrealized_pnl_usd(trade, 101.0) == 5.0

    def test_realized_usd_from_exit(self) -> None:
        trade = StoredTrade(
            id="c",
            symbol="SOL/USDT",
            direction=TradeDirection.LONG,
            source=TradeSource.SCANNER,
            status=TradeStatus.CLOSED,
            entry_price=100.0,
            stop_loss=99.0,
            confidence=0.8,
            amount=2.0,
            exit_price=102.0,
            pnl_pct=2.0,
        )
        assert realized_pnl_usd(trade) == 4.0


class TestBuildPnlReport:
    def test_groups_and_sorts_positions(self) -> None:
        stats = {
            "closed_trades": 3,
            "wins": 2,
            "losses": 1,
            "winrate_pct": 66.67,
            "total_pnl_usd": 216.22,
            "position_groups": {
                "position_trades": 2,
                "wins": 2,
                "losses": 0,
                "winrate_pct": 100.0,
                "total_fills": 3,
                "avg_win_usd": 108.11,
                "avg_loss_usd": 0.0,
                "profit_factor": None,
            },
        }
        open_positions = [
            {
                "symbol": "ETH/USDT",
                "direction": "SHORT",
                "leverage": 20,
                "pnl_pct": 1.0,
                "pnl_usd": 50.0,
            },
            {
                "symbol": "BTC/USDT",
                "direction": "LONG",
                "leverage": 15,
                "pnl_pct": 2.0,
                "pnl_usd": 100.0,
            },
            {
                "symbol": "XRP/USDT",
                "direction": "LONG",
                "leverage": 10,
                "pnl_pct": -0.5,
                "pnl_usd": -25.0,
            },
        ]
        text = build_pnl_report_message(
            stats=stats,
            open_positions=open_positions,
            bybit_mode="demo",
            period="week",
            generated_at=datetime(2026, 7, 3, 13, 0, tzinfo=ZoneInfo("America/Sao_Paulo")),
        )
        assert "Período: última semana" in text
        assert "PnL realizado: +$216.22" in text
        assert "POSIÇÕES (agrupadas)" in text
        assert "Trades lógicos: 2" in text
        assert "✅ No lucro" in text
        assert "❌ No prejuízo" in text
        assert "📈 BTCUSDT" in text
        assert "📉 ETHUSDT" in text
        assert text.index("BTCUSDT") < text.index("ETHUSDT")
        assert "entry" not in text.lower()
        assert "PnL flutuante total:" in text
