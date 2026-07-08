"""Testes do guard de slippage."""

from __future__ import annotations

from src.services.slippage_guard import (
    SLIPPAGE_ALERT_THRESHOLD_PCT,
    compute_slippage_pct,
    detect_slippage,
    format_slippage_alert,
    scan_execution_rows,
)


class TestSlippageGuard:
    def test_compute_slippage_pct(self) -> None:
        assert compute_slippage_pct(100.0, 101.5) == 1.5

    def test_detect_below_threshold(self) -> None:
        assert (
            detect_slippage(
                symbol="BTCUSDT",
                order_price=100.0,
                exec_price=100.5,
                context="entry",
            )
            is None
        )

    def test_detect_above_threshold(self) -> None:
        event = detect_slippage(
            symbol="SOONUSDT",
            order_price=0.194,
            exec_price=0.172,
            context="entry",
            threshold_pct=SLIPPAGE_ALERT_THRESHOLD_PCT,
        )
        assert event is not None
        assert event.slippage_pct > 10.0
        assert "[SLIPPAGE URGENTE]" in format_slippage_alert(event)

    def test_scan_execution_rows(self) -> None:
        rows = [
            {
                "symbol": "XANUSDT",
                "orderPrice": "0.011487",
                "execPrice": "0.012745",
                "orderType": "Market",
                "stopOrderType": "Stop",
                "side": "Sell",
                "execTime": "1",
            }
        ]
        events = scan_execution_rows(rows)
        assert len(events) == 1
        assert events[0].context == "stop"
