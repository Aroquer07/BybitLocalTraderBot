"""Testes unitários para cálculo de sizing e split de TPs."""

from __future__ import annotations

import pytest

from src.services.position_manager import (
    calculate_position_size,
    split_tp_amounts,
)


class TestCalculatePositionSize:
    def test_basic_sizing(self) -> None:
        # balance=46000, risk 1% = 460 USDT, SL distance 1.5 on entry 150
        result = calculate_position_size(
            balance_usdt=46000.0,
            entry_price=150.0,
            stop_loss=148.5,
            risk_per_trade_pct=1.0,
            max_position_pct=5.0,
            leverage=10,
            min_amount=0.1,
        )
        # risk / sl_distance = 460 / 1.5 ≈ 306.67 SOL
        assert result.amount > 0
        assert result.risk_usdt == pytest.approx(460.0)
        assert result.sl_distance == pytest.approx(1.5)

    def test_capped_by_max_position(self) -> None:
        result = calculate_position_size(
            balance_usdt=1000.0,
            entry_price=100.0,
            stop_loss=99.0,
            risk_per_trade_pct=5.0,
            max_position_pct=1.0,
            leverage=5,
            min_amount=0.001,
        )
        max_notional = 1000.0 * 0.01 * 5
        max_amount = max_notional / 100.0
        assert result.amount <= max_amount + 0.001

    def test_invalid_sl_raises(self) -> None:
        with pytest.raises(ValueError, match="Stop loss"):
            calculate_position_size(
                balance_usdt=1000.0,
                entry_price=100.0,
                stop_loss=100.0,
                risk_per_trade_pct=1.0,
                max_position_pct=5.0,
                leverage=5,
                min_amount=0.001,
            )


class TestSplitTpAmounts:
    def test_default_split(self) -> None:
        parts = split_tp_amounts(10.0, 50.0, 30.0, 20.0)
        assert parts.tp1 == pytest.approx(5.0)
        assert parts.tp2 == pytest.approx(3.0)
        assert parts.tp3 == pytest.approx(2.0)
        assert parts.total == pytest.approx(10.0)

    def test_invalid_total_raises(self) -> None:
        with pytest.raises(ValueError, match="100%"):
            split_tp_amounts(10.0, 50.0, 30.0, 10.0)

    def test_breakeven_threshold_after_tp1(self) -> None:
        from src.services.position_manager import ActiveTradeState, PositionManager

        state = ActiveTradeState(
            symbol="BTC/USDT",
            side="buy",
            entry_price=100.0,
            original_amount=1000.0,
            stop_loss=98.0,
            tp_close_pcts=(50.0, 30.0, 20.0),
            breakeven_trigger_tp=1,
        )
        mgr = PositionManager.__new__(PositionManager)
        threshold = mgr._tp_fill_threshold(state, 1)
        assert threshold == pytest.approx(510.0)
