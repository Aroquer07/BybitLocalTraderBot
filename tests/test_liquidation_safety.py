"""Testes de SL vs preço de liquidação."""

from __future__ import annotations

import pytest

from src.models.schemas import TradeDirection
from src.strategies.liquidation_safety import (
    clamp_stop_loss_to_liquidation,
    estimate_liquidation_price,
    safe_stop_loss_bounds,
    validate_stop_loss_vs_liquidation,
)
from src.strategies.trade_validation import apply_liquidation_safe_stop_loss


class TestEstimateLiquidation:
    def test_short_liquidation_above_entry(self) -> None:
        entry = 0.07573
        liq = estimate_liquidation_price(entry, 30, "SHORT")
        assert liq > entry
        assert liq == pytest.approx(entry * (1 + 1 / 30 - 0.005), rel=1e-4)

    def test_long_liquidation_below_entry(self) -> None:
        entry = 100.0
        liq = estimate_liquidation_price(entry, 20, "LONG")
        assert liq < entry


class TestStopLossVsLiquidation:
    def test_short_sl_above_liquidation_rejected(self) -> None:
        entry = 0.07573
        liq = 0.07767
        sl = 0.07941
        err = validate_stop_loss_vs_liquidation(
            TradeDirection.SHORT, entry, sl, liq, buffer_pct=0.4
        )
        assert err is not None
        assert "liquidação" in err.lower() or "limite seguro" in err.lower()

    def test_short_sl_clamped_below_liquidation(self) -> None:
        entry = 0.07573
        liq = 0.07767
        sl = 0.07941
        _, max_sl = safe_stop_loss_bounds(TradeDirection.SHORT, liq, 0.4)
        assert max_sl is not None
        adjusted, clamped, reject = clamp_stop_loss_to_liquidation(
            TradeDirection.SHORT, entry, sl, liq, 0.4
        )
        assert reject is None
        assert clamped
        assert adjusted < liq
        assert adjusted > entry
        assert adjusted == pytest.approx(max_sl, rel=1e-6)

    def test_long_sl_below_liquidation_rejected(self) -> None:
        entry = 100.0
        liq = 95.0
        sl = 94.0
        err = validate_stop_loss_vs_liquidation(
            TradeDirection.LONG, entry, sl, liq, buffer_pct=0.4
        )
        assert err is not None

    def test_long_sl_above_liquidation_ok(self) -> None:
        entry = 100.0
        liq = 95.0
        sl = 96.0
        err = validate_stop_loss_vs_liquidation(
            TradeDirection.LONG, entry, sl, liq, buffer_pct=0.4
        )
        assert err is None

    def test_apply_rejects_when_fib_sl_unsafe_and_cannot_clamp(self) -> None:
        entry = 0.07760
        liq = 0.07767
        sl = 0.07941
        safe, err = apply_liquidation_safe_stop_loss(
            TradeDirection.SHORT, entry, sl, liq, 0.4
        )
        assert safe is None
        assert err is not None

    def test_apply_clamps_doge_like_short(self) -> None:
        entry = 0.07573
        liq = 0.07767
        sl = 0.07941
        safe, err = apply_liquidation_safe_stop_loss(
            TradeDirection.SHORT, entry, sl, liq, 0.4
        )
        assert err is None
        assert safe is not None
        assert safe < liq
        assert safe > entry
