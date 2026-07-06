"""Motor de análise técnica multi-timeframe — orquestra indicadores e Fibonacci."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from src.config.runtime_config import BotRuntimeConfig
from src.config.settings import Settings
from src.services.runtime_config_store import RuntimeConfigStore
from src.models.schemas import ConfluenceResult, MarketState, TimeframeSnapshot
from src.strategies.confluence import compute_confluence
from src.strategies.indicators import (
    compute_indicators,
    compute_ohlcv_summary,
    ohlcv_to_dataframe,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

RETRACEMENT_RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786)
EXTENSION_RATIOS = (1.272, 1.618, 2.0, 2.618)
def compute_fibonacci_levels(
    df: pd.DataFrame,
    lookback: int = 80,
    reference_entry: float | None = None,
    reference_sl: float | None = None,
    trend: str | None = None,
) -> dict[str, Any]:
    """
    Calcula retrações e extensões Fibonacci a partir de swing high/low recentes.
    """
    if df.empty:
        return {}

    window = df.tail(lookback)
    swing_high = float(window["high"].max())
    swing_low = float(window["low"].min())
    range_size = swing_high - swing_low

    if range_size <= 0:
        return {
            "swing_high": round(swing_high, 6),
            "swing_low": round(swing_low, 6),
            "range": 0.0,
            "impulse": "neutral",
            "retracements": {},
            "extensions": {},
            "risk_reward_extensions": {},
        }

    idx_high = window["high"].idxmax()
    idx_low = window["low"].idxmin()

    if trend in ("bullish", "bearish"):
        impulse = trend
    elif idx_low < idx_high:
        impulse = "bullish"
    else:
        impulse = "bearish"

    retracements: dict[str, float] = {}
    extensions: dict[str, float] = {}

    for ratio in RETRACEMENT_RATIOS:
        key = str(ratio)
        if impulse == "bullish":
            retracements[key] = round(swing_high - ratio * range_size, 6)
        else:
            retracements[key] = round(swing_low + ratio * range_size, 6)

    for ratio in EXTENSION_RATIOS:
        key = str(ratio)
        if impulse == "bullish":
            extensions[key] = round(swing_low + ratio * range_size, 6)
        else:
            extensions[key] = round(swing_high - (ratio - 1.0) * range_size, 6)

    entry = reference_entry if reference_entry is not None else float(df["close"].iloc[-1])
    if reference_sl is not None:
        sl = reference_sl
    elif impulse == "bullish":
        sl = swing_low
    else:
        sl = swing_high

    risk = abs(entry - sl)
    risk_reward_extensions: dict[str, float] = {}
    if risk > 0:
        for key, tp_price in extensions.items():
            reward = abs(tp_price - entry)
            risk_reward_extensions[key] = round(reward / risk, 4)

    return {
        "swing_high": round(swing_high, 6),
        "swing_low": round(swing_low, 6),
        "range": round(range_size, 6),
        "impulse": impulse,
        "lookback_candles": len(window),
        "reference_entry": round(entry, 6),
        "reference_sl": round(sl, 6),
        "retracements": retracements,
        "extensions": extensions,
        "risk_reward_extensions": risk_reward_extensions,
    }


class TechnicalAnalysisEngine:
    """
    Encapsula cálculo multi-TF de indicadores e confluência.

    Responsabilidade exclusiva do Python — a LLM recebe apenas o JSON resultante.
    """

    def __init__(
        self,
        settings: Settings,
        runtime_store: RuntimeConfigStore | None = None,
    ) -> None:
        self._settings = settings
        self._runtime = runtime_store

    def _runtime_cfg(self) -> BotRuntimeConfig:
        if self._runtime is not None:
            return self._runtime.reload()
        return BotRuntimeConfig()

    @property
    def timeframes(self) -> list[str]:
        return self._runtime_cfg().timeframes.analysis

    def build_timeframe_snapshot(
        self,
        ohlcv: list[list[float]],
        lookback: int | None = None,
    ) -> TimeframeSnapshot:
        """Constrói snapshot técnico para um único timeframe."""
        df = ohlcv_to_dataframe(ohlcv)
        if df.empty:
            raise ValueError("OHLCV vazio")

        indicators = compute_indicators(df)
        ohlcv_summary = compute_ohlcv_summary(df)

        last_price = float(df["close"].iloc[-1])
        trend = indicators.get("trend")
        trend_str = str(trend) if trend is not None else None

        atr = indicators.get("atr_14")
        if trend_str == "bullish" and atr is not None:
            ref_sl = last_price - float(atr) * 1.5
        elif trend_str == "bearish" and atr is not None:
            ref_sl = last_price + float(atr) * 1.5
        else:
            ref_sl = None

        lb = lookback or min(80, len(df))
        fibonacci = compute_fibonacci_levels(
            df,
            lookback=lb,
            reference_entry=last_price,
            reference_sl=ref_sl,
            trend=trend_str,
        )

        from src.strategies.market_patterns import detect_market_patterns

        patterns = detect_market_patterns(df, indicators)
        if patterns:
            indicators["market_patterns"] = [p.to_dict() for p in patterns]

        return TimeframeSnapshot(
            indicators=indicators,
            fibonacci=fibonacci,
            ohlcv_summary=ohlcv_summary,
        )

    def build_market_state(
        self,
        symbol: str,
        ohlcv_by_timeframe: dict[str, list[list[float]]],
        orderbook: dict[str, Any] | None = None,
        confluence: ConfluenceResult | None = None,
    ) -> MarketState:
        """
        Constrói MarketState multi-timeframe a partir de OHLCV por TF.

        Args:
            symbol: Par CCXT (ex: BTC/USDT).
            ohlcv_by_timeframe: Dict {timeframe: ohlcv_candles}.
            orderbook: Snapshot opcional do orderbook.
            confluence: Pré-score opcional (calculado internamente se None).
        """
        timeframes: dict[str, TimeframeSnapshot] = {}

        for tf, ohlcv in ohlcv_by_timeframe.items():
            try:
                timeframes[tf] = self.build_timeframe_snapshot(ohlcv)
            except ValueError:
                logger.warning("OHLCV vazio para %s @ %s — TF ignorado", symbol, tf)

        if not timeframes:
            raise ValueError(f"Nenhum OHLCV válido para {symbol}")

        primary_tf = (
            self._runtime_cfg().timeframes.primary
            if self._runtime_cfg().timeframes.primary in timeframes
            else next(iter(timeframes))
        )
        primary = timeframes[primary_tf]
        last_price = primary.ohlcv_summary.get("last_close") or 0.0
        if not last_price:
            last_price = float(
                primary.indicators.get("ema_14") or primary.indicators.get("sma_14") or 0
            )

        orderbook_snapshot = self._summarize_orderbook(orderbook) if orderbook else {}

        state = MarketState(
            symbol=symbol,
            timeframe=primary_tf,
            last_price=float(last_price),
            timestamp=datetime.now(timezone.utc),
            timeframes=timeframes,
            orderbook_snapshot=orderbook_snapshot,
        )

        cfg = self._runtime_cfg()
        state.confluence = confluence or compute_confluence(
            state,
            primary_tf=cfg.timeframes.primary,
            trend_tf=cfg.timeframes.trend,
        )
        return state

    def build_market_state_single(
        self,
        symbol: str,
        ohlcv: list[list[float]],
        orderbook: dict[str, Any] | None = None,
        timeframe: str | None = None,
    ) -> MarketState:
        """Atalho para um único timeframe (compatibilidade)."""
        tf = timeframe or self._runtime_cfg().timeframes.primary
        return self.build_market_state(
            symbol=symbol,
            ohlcv_by_timeframe={tf: ohlcv},
            orderbook=orderbook,
        )

    @staticmethod
    def _summarize_orderbook(orderbook: dict[str, Any]) -> dict[str, Any]:
        """Resume orderbook sem enviar dados brutos massivos."""
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])

        bid_volume = sum(b[1] for b in bids[:10]) if bids else 0.0
        ask_volume = sum(a[1] for a in asks[:10]) if asks else 0.0
        total = bid_volume + ask_volume

        return {
            "best_bid": bids[0][0] if bids else None,
            "best_ask": asks[0][0] if asks else None,
            "spread": round(asks[0][0] - bids[0][0], 6) if bids and asks else None,
            "bid_volume_top10": round(bid_volume, 4),
            "ask_volume_top10": round(ask_volume, 4),
            "bid_ask_ratio": round(bid_volume / ask_volume, 4) if ask_volume > 0 else None,
            "imbalance": round((bid_volume - ask_volume) / total, 4) if total > 0 else 0.0,
        }
