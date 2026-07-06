"""Testes para níveis Fibonacci de scalp."""

import pandas as pd
import pytest

from src.strategies.fib_execution_levels import (
    FIB_TP_PRIMARY,
    _build_take_profits,
    compute_fib_scalp_levels,
)


def _make_bullish_ohlcv(
    low: float = 453.0,
    high: float = 489.0,
    bars: int = 100,
) -> list[list[float]]:
    """OHLCV sintético: swing low no início, swing high no fim (impulso bullish)."""
    ohlcv: list[list[float]] = []
    ts = 1_700_000_000_000
    for i in range(bars):
        if i < 10:
            o, h, l, c = low + 1, low + 3, low, low + 2
        elif i > bars - 15:
            o, h, l, c = high - 2, high, high - 4, high - 1
        else:
            mid = low + (high - low) * (i / bars)
            o, h, l, c = mid, mid + 2, mid - 2, mid + 0.5
        ohlcv.append([ts + i * 300_000, o, h, l, c, 1000.0])
    return ohlcv


def test_fib_long_levels_match_ratios():
    entry = 462.0
    ohlcv = _make_bullish_ohlcv()
    fib = compute_fib_scalp_levels(ohlcv, "LONG", entry, lookback=80)
    assert fib is not None
    assert fib.swing_low < entry < fib.take_profits[0]
    range_size = fib.swing_high - fib.swing_low
    for ratio, tp in zip(FIB_TP_PRIMARY, fib.take_profits):
        expected = fib.swing_low + ratio * range_size
        assert abs(tp - expected) < 0.01
    assert len(fib.take_profits) == 3
    assert fib.stop_loss < fib.swing_low


def test_fib_rejects_entry_above_structure_top():
    """Entry acima do topo estrutural é rejeitada."""
    ohlcv = _make_bullish_ohlcv(high=489.0)
    fib = compute_fib_scalp_levels(ohlcv, "LONG", 495.0, lookback=80)
    assert fib is None


def test_fib_tp1_rr_sanity():
    fib = compute_fib_scalp_levels(_make_bullish_ohlcv(), "LONG", 462.0, min_tp1_rr=0.35)
    assert fib is not None
    assert fib.tp1_rr >= 0.35


def _make_bearish_ohlcv(
    low: float = 0.065806,
    high: float = 0.079162,
    bars: int = 100,
) -> list[list[float]]:
    """OHLCV sintético bearish: topo no início, fundo no fim (impulso baixista)."""
    ohlcv: list[list[float]] = []
    ts = 1_700_000_000_000
    for i in range(bars):
        if i == 0:
            o, h, l, c = high - 0.001, high, high - 0.002, high - 0.001
        elif i < 8:
            o, h, l, c = high - 0.002, high - 0.001, high - 0.004, high - 0.002
        elif i >= bars - 5:
            o, h, l, c = low + 0.001, low + 0.003, low, low + 0.002
        elif i == bars - 1:
            o, h, l, c = low + 0.001, low + 0.002, low, low + 0.001
        else:
            progress = i / bars
            mid = high - (high - low) * progress
            o, h, l, c = mid, mid + 0.0005, mid - 0.0005, mid - 0.0002
        ohlcv.append([ts + i * 300_000, o, h, l, c, 1000.0])
    return ohlcv


def test_fib_short_levels_match_ratios():
    entry = 0.07573
    ohlcv = _make_bearish_ohlcv()
    fib = compute_fib_scalp_levels(ohlcv, "SHORT", entry, lookback=80)
    assert fib is not None
    assert fib.take_profits[0] < entry < fib.stop_loss
    range_size = fib.swing_high - fib.swing_low
    for ratio, tp in zip(FIB_TP_PRIMARY, fib.take_profits):
        expected = fib.swing_high - ratio * range_size
        assert abs(tp - expected) < 0.0001
    assert fib.stop_loss > fib.swing_high


def test_fib_short_doge_like_tp_values():
    """TPs SHORT em 38.2/50/61.8% medidos do topo do impulso (caso DOGE)."""
    low, high = 0.065806, 0.079162
    range_size = high - low
    tps = _build_take_profits("SHORT", low, high, range_size, 0.07573)
    assert tps == pytest.approx((0.07406, 0.07249, 0.07091), abs=0.001)


def test_fib_long_near_top_uses_extensions():
    """LONG perto do topo usa 1.0 / extensões em vez de SMC distante."""
    low, high = 0.05742, 0.05913
    range_size = high - low
    entry = 0.05903
    tps = _build_take_profits("LONG", low, high, range_size, entry)
    assert tps is not None
    assert all(tp > entry for tp in tps)
    assert tps[0] == pytest.approx(high, abs=0.0001)


def test_structure_short_uses_recent_fractal_top():
    """SHORT: SL ancorado no último topo fractal (índice mais recente), não no maior."""
    from src.strategies.fib_execution_levels import _anchor_swing_high_short

    highs = [(10, 0.1452), (50, 0.1445), (90, 0.14264)]
    df = pd.DataFrame({"high": [0.14] * 100, "low": [0.13] * 100})
    idx, price = _anchor_swing_high_short(highs, 0.14228, df)
    assert idx == 90
    assert price == pytest.approx(0.14264)


def test_structure_short_ape_like_targets():
    """SHORT: SL no topo fractal recente; TPs na perna topo máx → fundo."""
    tp_low, tp_high, entry = 0.14144, 0.14762, 0.14228
    from src.strategies.fib_execution_levels import _build_take_profits

    tps = _build_take_profits("SHORT", tp_low, tp_high, tp_high - tp_low, entry)
    assert tps is not None
    assert tps[0] == pytest.approx(0.14144, abs=0.001)
    assert all(tp < entry for tp in tps)
    assert tps[0] > tps[1] > tps[2]


def test_fib_short_tp_order_decreasing():
    fib = compute_fib_scalp_levels(_make_bearish_ohlcv(), "SHORT", 0.07573, lookback=80)
    assert fib is not None
    tps = fib.take_profits
    assert tps[0] > tps[1] > tps[2]
    assert all(tp < fib.entry for tp in tps)
