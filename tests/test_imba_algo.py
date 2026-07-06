"""Testes da estratégia [IMBA] ALGO."""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategies.imba_algo import (
    ImbaAlgoConfig,
    ImbaChannelLevels,
    ImbaTrendState,
    compute_channel_levels,
    compute_stop_loss,
    compute_take_profits,
    evaluate_bar,
    evaluate_dataframe,
    signal_to_exchange_side,
)


def _make_df(closes: list[float], spread: float = 1.0) -> pd.DataFrame:
    rows = []
    for i, close in enumerate(closes):
        rows.append({
            "timestamp": pd.Timestamp(f"2024-01-{i+1:02d}", tz="UTC"),
            "open": close - spread * 0.2,
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": 1000.0,
        })
    return pd.DataFrame(rows)


class TestImbaChannel:
    def test_fib_levels(self) -> None:
        high = pd.Series([110.0, 120.0, 130.0])
        low = pd.Series([90.0, 80.0, 70.0])
        levels = compute_channel_levels(high, low)
        assert levels.high_line == 130.0
        assert levels.low_line == 70.0
        assert levels.trend_line == pytest.approx(100.0)
        assert levels.fib_236 == pytest.approx(130.0 - 60.0 * 0.236)
        assert levels.fib_786 == pytest.approx(130.0 - 60.0 * 0.786)


class TestImbaSignals:
    def test_long_signal_on_breakout(self) -> None:
        config = ImbaAlgoConfig(sensitivity=1.0)
        state = ImbaTrendState()
        levels = ImbaChannelLevels(
            high_line=100.0,
            low_line=80.0,
            fib_236=95.28,
            fib_786=82.84,
            trend_line=90.0,
        )
        state, signal = evaluate_bar(96.0, levels, state, config)
        assert signal is not None
        assert signal.side == "LONG"
        assert state.is_long_trend is True
        assert signal.stop_loss == pytest.approx(levels.fib_786)

    def test_short_signal_on_breakdown(self) -> None:
        config = ImbaAlgoConfig(sensitivity=1.0)
        state = ImbaTrendState(is_long_trend=True)
        levels = ImbaChannelLevels(
            high_line=100.0,
            low_line=80.0,
            fib_236=95.28,
            fib_786=82.84,
            trend_line=90.0,
        )
        state, signal = evaluate_bar(82.0, levels, state, config)
        assert signal is not None
        assert signal.side == "SHORT"
        assert state.is_short_trend is True
        assert signal.stop_loss == pytest.approx(levels.fib_236)

    def test_no_signal_without_breakout(self) -> None:
        config = ImbaAlgoConfig(sensitivity=1.0)
        state = ImbaTrendState()
        levels = ImbaChannelLevels(
            high_line=100.0,
            low_line=80.0,
            fib_236=95.28,
            fib_786=82.84,
            trend_line=90.0,
        )
        _, signal = evaluate_bar(91.0, levels, state, config)
        assert signal is None

    def test_take_profits_long(self) -> None:
        config = ImbaAlgoConfig(tp_percents=(1.0, 2.0, 3.0))
        tps = compute_take_profits("LONG", 100.0, config)
        assert tps == pytest.approx((101.0, 102.0, 103.0))

    def test_take_profits_short(self) -> None:
        config = ImbaAlgoConfig(tp_percents=(1.0, 2.0, 3.0))
        tps = compute_take_profits("SHORT", 100.0, config)
        assert tps == pytest.approx((99.0, 98.0, 97.0))

    def test_exchange_side_mapping(self) -> None:
        assert signal_to_exchange_side("LONG") == "buy"
        assert signal_to_exchange_side("SHORT") == "sell"


class TestImbaDataframeReplay:
    def test_replay_builds_state(self) -> None:
        closes = [100.0] * 15 + [105.0, 110.0, 115.0]
        df = _make_df(closes, spread=2.0)
        config = ImbaAlgoConfig(sensitivity=1.0)
        state, signal = evaluate_dataframe(df, config)
        assert isinstance(state, ImbaTrendState)

    def test_fixed_stop_sl(self) -> None:
        config = ImbaAlgoConfig(fixed_stop=True, sl_percent=2.0)
        levels = compute_channel_levels(pd.Series([100.0]), pd.Series([80.0]))
        sl = compute_stop_loss("LONG", 100.0, levels, config)
        assert sl == pytest.approx(98.0)
