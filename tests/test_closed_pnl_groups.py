"""Testes do agrupador de closed-PnL."""

from __future__ import annotations

from src.services.closed_pnl_groups import (
    aggregate_position_groups,
    group_closed_pnl_records,
)


class TestGroupClosedPnl:
    def test_groups_partial_fills_into_one_trade(self) -> None:
        records = [
            {
                "symbol": "BTCUSDT",
                "side": "Sell",
                "avgEntryPrice": "100",
                "closedPnl": "50",
                "openFee": "1",
                "closeFee": "1",
                "leverage": "20",
                "closedSize": "1",
                "updatedTime": "1000",
            },
            {
                "symbol": "BTCUSDT",
                "side": "Sell",
                "avgEntryPrice": "100",
                "closedPnl": "-80",
                "openFee": "1",
                "closeFee": "1",
                "leverage": "20",
                "closedSize": "1",
                "updatedTime": "2000",
            },
            {
                "symbol": "ETHUSDT",
                "side": "Buy",
                "avgEntryPrice": "2000",
                "closedPnl": "10",
                "openFee": "0.5",
                "closeFee": "0.5",
                "leverage": "15",
                "closedSize": "2",
                "updatedTime": "3000",
            },
        ]
        groups = group_closed_pnl_records(records)
        assert len(groups) == 2
        btc = next(g for g in groups if g["symbol"] == "BTCUSDT")
        assert btc["fill_count"] == 2
        assert btc["total_pnl"] == -30.0

    def test_aggregate_position_stats(self) -> None:
        groups = [
            {"total_pnl": 100.0, "total_fees": 2.0, "fill_count": 1},
            {"total_pnl": -50.0, "total_fees": 1.0, "fill_count": 2},
            {"total_pnl": 25.0, "total_fees": 0.5, "fill_count": 1},
        ]
        stats = aggregate_position_groups(groups)
        assert stats["position_trades"] == 3
        assert stats["wins"] == 2
        assert stats["losses"] == 1
        assert stats["winrate_pct"] == 66.67
        assert stats["profit_factor"] == 2.5
