"""Estratégia [IMBA] ALGO — sinais por virada de tendência no canal Fibonacci.

Portado de indicators/ALGO (TradingView). Diferente do Pine original, não fecha
posição em reversão de tendência — saída apenas por SL ou TPs na exchange.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from src.strategies.indicators import ohlcv_to_dataframe

Side = Literal["LONG", "SHORT"]


@dataclass(frozen=True)
class ImbaAlgoConfig:
    """Parâmetros alinhados ao preset MANUAL do Pine Script."""

    sensitivity: float = 2.0
    tp_percents: tuple[float, float, float] = (1.0, 2.0, 3.0)
    tp_close_pcts: tuple[float, float, float] = (50.0, 30.0, 20.0)
    fixed_stop: bool = False
    sl_percent: float = 0.0

    @property
    def lookback(self) -> int:
        return max(2, int(self.sensitivity * 10))


@dataclass
class ImbaTrendState:
    is_long_trend: bool = False
    is_short_trend: bool = False


@dataclass(frozen=True)
class ImbaChannelLevels:
    high_line: float
    low_line: float
    fib_236: float
    fib_786: float
    trend_line: float


@dataclass(frozen=True)
class ImbaSignal:
    side: Side
    entry_price: float
    stop_loss: float
    take_profits: tuple[float, float, float]
    levels: ImbaChannelLevels | None = None


def compute_channel_levels(high: pd.Series, low: pd.Series) -> ImbaChannelLevels:
    """Calcula canal Fibonacci a partir de uma janela high/low."""
    high_line = float(high.max())
    low_line = float(low.min())
    channel_range = high_line - low_line
    return ImbaChannelLevels(
        high_line=high_line,
        low_line=low_line,
        fib_236=high_line - channel_range * 0.236,
        fib_786=high_line - channel_range * 0.786,
        trend_line=high_line - channel_range * 0.5,
    )


def _sl_multiplier(config: ImbaAlgoConfig) -> float:
    return config.sl_percent / 100.0


def compute_stop_loss(
    side: Side,
    entry_price: float,
    levels: ImbaChannelLevels,
    config: ImbaAlgoConfig,
) -> float:
    """SL automático em fib oposto ou % fixa da entrada."""
    mult = _sl_multiplier(config)
    if side == "LONG":
        if config.fixed_stop:
            return entry_price * (1.0 - mult)
        return levels.fib_786 * (1.0 - mult)
    if config.fixed_stop:
        return entry_price * (1.0 + mult)
    return levels.fib_236 * (1.0 + mult)


def compute_take_profits(
    side: Side,
    entry_price: float,
    config: ImbaAlgoConfig,
) -> tuple[float, float, float]:
    """TPs como % fixo da entrada (3 níveis)."""
    tps: list[float] = []
    for pct in config.tp_percents:
        ratio = pct / 100.0
        if side == "LONG":
            tps.append(entry_price * (1.0 + ratio))
        else:
            tps.append(entry_price * (1.0 - ratio))
    return (tps[0], tps[1], tps[2])


def evaluate_bar(
    close: float,
    levels: ImbaChannelLevels,
    state: ImbaTrendState,
    config: ImbaAlgoConfig,
) -> tuple[ImbaTrendState, ImbaSignal | None]:
    """
    Avalia um candle fechado e retorna novo estado + sinal (se houver virada).

    LONG: close >= trend_line e close >= fib_236 e não estava em alta.
    SHORT: close <= trend_line e close <= fib_786 e não estava em baixa.
    """
    can_long = (
        close >= levels.trend_line
        and close >= levels.fib_236
        and not state.is_long_trend
    )
    can_short = (
        close <= levels.trend_line
        and close <= levels.fib_786
        and not state.is_short_trend
    )

    signal: ImbaSignal | None = None

    if can_long:
        state.is_long_trend = True
        state.is_short_trend = False
        signal = ImbaSignal(
            side="LONG",
            entry_price=close,
            stop_loss=compute_stop_loss("LONG", close, levels, config),
            take_profits=compute_take_profits("LONG", close, config),
            levels=levels,
        )
    elif can_short:
        state.is_short_trend = True
        state.is_long_trend = False
        signal = ImbaSignal(
            side="SHORT",
            entry_price=close,
            stop_loss=compute_stop_loss("SHORT", close, levels, config),
            take_profits=compute_take_profits("SHORT", close, config),
            levels=levels,
        )

    return state, signal


def evaluate_dataframe(
    df: pd.DataFrame,
    config: ImbaAlgoConfig | None = None,
    initial_state: ImbaTrendState | None = None,
) -> tuple[ImbaTrendState, ImbaSignal | None]:
    """
    Replay bar-a-bar para obter estado atual e sinal no último candle fechado.

    Usa apenas candles já fechados (exclui o candle em formação se presente).
    """
    if config is None:
        config = ImbaAlgoConfig()
    if df.empty or len(df) < config.lookback:
        return initial_state or ImbaTrendState(), None

    state = initial_state or ImbaTrendState()
    lookback = config.lookback
    last_signal: ImbaSignal | None = None

    for i in range(lookback - 1, len(df)):
        window_high = df["high"].iloc[i - lookback + 1 : i + 1]
        window_low = df["low"].iloc[i - lookback + 1 : i + 1]
        levels = compute_channel_levels(window_high, window_low)
        close = float(df["close"].iloc[i])
        state, bar_signal = evaluate_bar(close, levels, state, config)
        if bar_signal is not None:
            last_signal = bar_signal

    return state, last_signal


def evaluate_ohlcv(
    ohlcv: list[list[float]],
    config: ImbaAlgoConfig | None = None,
    *,
    exclude_forming_candle: bool = True,
    initial_state: ImbaTrendState | None = None,
) -> tuple[ImbaTrendState, ImbaSignal | None]:
    """Wrapper para lista OHLCV CCXT."""
    df = ohlcv_to_dataframe(ohlcv)
    if exclude_forming_candle and len(df) > 1:
        df = df.iloc[:-1]
    return evaluate_dataframe(df, config, initial_state)


def signal_to_exchange_side(side: Side) -> str:
    """Converte LONG/SHORT para side CCXT (buy/sell)."""
    return "buy" if side == "LONG" else "sell"
