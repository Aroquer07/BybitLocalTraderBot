"""Testes SMC — SL em liquidez, TPs estruturais."""

from __future__ import annotations

import pandas as pd

from src.models.schemas import TradeDirection
from src.strategies.smc_levels import compute_smc_levels, smc_levels_from_dataframe


def _trending_up_ohlcv(n: int = 100, base: float = 100.0) -> list[list[float]]:
    rows: list[list[float]] = []
    price = base
    for i in range(n):
        o = price
        c = price + 0.3
        h = c + 0.5
        l = o - 0.4
        rows.append([i * 60_000, o, h, l, c, 1000.0 + i * 10])
        price = c
    return rows


class TestSmcLevels:
    def test_long_produces_sl_below_entry(self) -> None:
        ohlcv = _trending_up_ohlcv()
        entry = ohlcv[-2][4]
        smc = compute_smc_levels(ohlcv, TradeDirection.LONG, entry)
        assert smc is not None
        assert smc.stop_loss < entry
        assert all(tp > entry for tp in smc.take_profits)
        assert smc.tp1_rr >= 2.0

    def test_short_produces_sl_above_entry(self) -> None:
        rows = _trending_up_ohlcv()
        down: list[list[float]] = []
        price = rows[-1][4]
        for i, row in enumerate(rows[-40:]):
            o = price
            c = price - 0.35
            h = o + 0.3
            l = c - 0.5
            down.append([row[0] + i * 60_000, o, h, l, c, 1200.0])
            price = c
        entry = down[-1][4]
        smc = compute_smc_levels(down, TradeDirection.SHORT, entry)
        assert smc is not None
        assert smc.stop_loss > entry
        assert all(tp < entry for tp in smc.take_profits)

    def test_from_dataframe(self) -> None:
        ohlcv = _trending_up_ohlcv(60)
        df = pd.DataFrame(
            ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        smc = smc_levels_from_dataframe(df, TradeDirection.LONG, float(df["close"].iloc[-2]))
        assert smc is not None
        assert smc.weighted_rr >= 2.0
