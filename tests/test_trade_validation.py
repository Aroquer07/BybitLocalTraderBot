"""Testes de validação de níveis e alavancagem da IA."""

from __future__ import annotations

import pytest

from src.config.runtime_config import BotRuntimeConfig
from src.models.schemas import TakeProfitLevel, TradeDecision, TradeDirection
from src.strategies.trade_validation import (
    apply_execution_levels,
    merge_execution_levels,
    shift_execution_levels,
    validate_execution_decision,
)


def _runtime() -> BotRuntimeConfig:
    return BotRuntimeConfig()


def _long_decision(**kwargs) -> TradeDecision:
    base = dict(
        approved=True,
        confidence=0.92,
        confidence_threshold=0.65,
        direction=TradeDirection.LONG,
        symbol="BTC/USDT",
        entry_price=100.0,
        stop_loss=98.0,
        leverage=20,
        take_profits=[
            TakeProfitLevel(price=106.0, percentage=6.0, risk_reward=3.0),
            TakeProfitLevel(price=109.0, percentage=9.0, risk_reward=4.5),
            TakeProfitLevel(price=112.0, percentage=12.0, risk_reward=6.0),
        ],
    )
    base.update(kwargs)
    return TradeDecision(**base)


class TestApplyExecutionLevels:
    def test_overwrites_llm_tps_with_execution_tf(self) -> None:
        llm = _long_decision(
            take_profits=[
                TakeProfitLevel(price=200.0, percentage=100.0, risk_reward=50.0),
                TakeProfitLevel(price=210.0, percentage=110.0, risk_reward=55.0),
                TakeProfitLevel(price=220.0, percentage=120.0, risk_reward=60.0),
            ]
        )
        applied = apply_execution_levels(
            llm,
            symbol="BTC/USDT",
            direction=TradeDirection.LONG,
            entry_price=100.0,
            stop_loss=98.0,
            take_profit_prices=[101.0, 102.0, 103.0],
            execution_timeframe="5m",
        )
        assert applied.entry_price == 100.0
        assert applied.take_profits[0].price == 101.0
        assert applied.execution_timeframe == "5m"


class TestValidateExecutionDecision:
    def test_approved_with_leverage_passes(self) -> None:
        d = validate_execution_decision(_long_decision(), _runtime())
        assert d.approved
        assert d.leverage == 20

    def test_rejects_without_leverage(self) -> None:
        d = validate_execution_decision(_long_decision(leverage=None), _runtime())
        assert not d.approved
        assert "alavancagem" in d.bias.lower()

    def test_caps_leverage_to_max(self) -> None:
        d = validate_execution_decision(_long_decision(leverage=50), _runtime())
        assert d.leverage == 30

    def test_rejects_sniper_like_levels_below_tp1_rr_floor(self) -> None:
        d = validate_execution_decision(
            _long_decision(
                take_profits=[
                    TakeProfitLevel(price=99.5, percentage=0.0, risk_reward=0.25),
                    TakeProfitLevel(price=102.0, percentage=2.0, risk_reward=1.0),
                    TakeProfitLevel(price=103.0, percentage=3.0, risk_reward=1.5),
                ]
            ),
            _runtime(),
            require_weighted_expectancy=False,
            sniper_levels=True,
        )
        assert not d.approved
        assert "TP1" in (d.bias or "")

    def test_sniper_atr_levels_pass_without_weighted_rr_gate(self) -> None:
        """Sniper 1.2R/2R/3R → ponderado ~1.8; não deve exigir wins_cover_losses=3."""
        d = validate_execution_decision(
            _long_decision(
                take_profits=[
                    TakeProfitLevel(price=102.5, percentage=2.5, risk_reward=1.25),
                    TakeProfitLevel(price=104.0, percentage=4.0, risk_reward=2.0),
                    TakeProfitLevel(price=106.0, percentage=6.0, risk_reward=3.0),
                ]
            ),
            _runtime(),
            require_weighted_expectancy=False,
            sniper_levels=True,
        )
        assert d.approved


class TestLiquidationSafeLevels:
    def test_apply_clamps_short_sl(self) -> None:
        from src.strategies.trade_validation import apply_liquidation_safe_stop_loss

        safe, err = apply_liquidation_safe_stop_loss(
            TradeDirection.SHORT,
            0.07573,
            0.07941,
            0.07767,
            0.4,
        )
        assert err is None
        assert safe is not None
        assert safe < 0.07767
        assert safe > 0.07573

    def test_rejects_unsafe_short_when_clamp_invalid(self) -> None:
        from src.strategies.trade_validation import apply_liquidation_safe_stop_loss

        safe, err = apply_liquidation_safe_stop_loss(
            TradeDirection.SHORT,
            0.07760,
            0.07941,
            0.07767,
            0.4,
        )
        assert safe is None
        assert err is not None


class TestMergeExecutionLevels:
    def test_fills_missing_from_reference(self) -> None:
        llm = TradeDecision(
            approved=False,
            confidence=0.7,
            confidence_threshold=0.65,
            leverage=18,
        )
        merged = merge_execution_levels(
            llm,
            symbol="ETH/USDT",
            direction=TradeDirection.LONG,
            entry_price=200.0,
            stop_loss=196.0,
            take_profit_prices=[202.0, 204.0, 206.0],
        )
        assert merged.symbol == "ETH/USDT"
        assert merged.entry_price == 200.0
        assert len(merged.take_profits) == 3

    def test_does_not_overwrite_ai_levels(self) -> None:
        llm = _long_decision(leverage=22)
        merged = merge_execution_levels(
            llm,
            entry_price=50.0,
            stop_loss=40.0,
            take_profit_prices=[60.0, 70.0, 80.0],
        )
        assert merged.entry_price == 100.0
        assert merged.take_profits[0].price == 106.0


class TestShiftExecutionLevels:
    def test_shifts_all_levels_by_fill_delta(self) -> None:
        sl, tps = shift_execution_levels(
            100.0,
            100.5,
            98.0,
            [101.0, 102.0, 103.0],
        )
        assert sl == pytest.approx(98.5)
        assert tps == pytest.approx([101.5, 102.5, 103.5])
