"""Screener automático — confluência RSI Heatmap + Visual Screener (derivativos)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from src.config.runtime_config import ScreenerConfig
from src.services.exchange_client import ExchangeClient
from src.strategies.indicators import ohlcv_to_dataframe
from src.utils.async_batch import map_batched
from src.utils.logger import get_logger

logger = get_logger(__name__)

SetupDirection = Literal["LONG", "SHORT"]
RsiBias = Literal["overbought", "oversold"]
DerivativeFlow = Literal["shorts_entering", "longs_entering"]


@dataclass
class ScreenerHit:
    """Moeda com confluência RSI + derivativos."""

    symbol: str
    direction: SetupDirection
    score: float
    rsi_by_tf: dict[str, float] = field(default_factory=dict)
    rsi_bias: str = ""
    derivative_flow: str = ""
    funding_rate: float | None = None
    turnover_24h: float | None = None
    price_change_24h_pct: float | None = None
    oi_change_pct: float | None = None
    sell_ratio: float | None = None
    reason: str = ""


def compute_rsi_last(closes: pd.Series, period: int = 14) -> float | None:
    """RSI Wilder no último candle — período padrão CoinGlass (14)."""
    if len(closes) < period + 1:
        return None
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    last_gain = avg_gain.iloc[-1]
    last_loss = avg_loss.iloc[-1]
    if pd.isna(last_gain) or pd.isna(last_loss):
        return None
    if last_loss == 0:
        return 100.0 if last_gain > 0 else 50.0
    if last_gain == 0:
        return 0.0
    rs = float(last_gain) / float(last_loss)
    return round(100 - (100 / (1 + rs)), 2)


def rsi_map_from_ohlcv(
    ohlcv_by_tf: dict[str, list[list[float]]],
    period: int,
) -> dict[str, float]:
    """Calcula RSI(period) por timeframe a partir de OHLCV."""
    result: dict[str, float] = {}
    for tf, candles in ohlcv_by_tf.items():
        if not candles or len(candles) < period + 2:
            continue
        df = ohlcv_to_dataframe(candles)
        rsi = compute_rsi_last(df["close"], period=period)
        if rsi is not None:
            result[tf] = rsi
    return result


def _rsi(tf_map: dict[str, float], tf: str) -> float | None:
    return tf_map.get(tf)


def _high_tf_rsi_values(
    rsi_by_tf: dict[str, float],
    *,
    prefer: tuple[str, ...] = ("4h", "1d", "1h", "30m"),
) -> list[float]:
    """RSI dos TFs maiores disponíveis (estilo heatmap)."""
    return [rsi_by_tf[tf] for tf in prefer if tf in rsi_by_tf]


def classify_rsi_bias(
    rsi_by_tf: dict[str, float],
    config: ScreenerConfig,
) -> tuple[RsiBias | None, str]:
    """
    RSI Heatmap — overbought / oversold em TF relevantes.

    SHORT: 4h ou 1h overbought + sinais de rollover no TF menor.
    LONG:  4h ou 1h oversold + recuperação no TF menor.
    """
    r15 = _rsi(rsi_by_tf, "15m")
    r1h = _rsi(rsi_by_tf, "1h")
    r4h = _rsi(rsi_by_tf, "4h")
    r1d = _rsi(rsi_by_tf, "1d")
    r30 = _rsi(rsi_by_tf, "30m")

    if r4h is None and r1h is None and r1d is None and r30 is None:
        return None, ""

    ob = config.rsi_overbought_min
    os_ = config.rsi_oversold_max

    overbought = any(
        r is not None and r >= ob for r in (r4h, r1h, r1d, r30, r15)
    )
    oversold = any(
        r is not None and r <= os_ for r in (r4h, r1h, r1d, r30, r15)
    )

    if overbought:
        rollover = (
            (r1h is not None and r4h is not None and r1h <= r4h)
            or (r15 is not None and r1h is not None and r15 <= r1h)
        )
        extreme = any(r is not None and r >= ob + 5 for r in (r4h, r1h, r1d))
        if rollover or extreme:
            detail = f"RSI overbought (>{ob:.0f}) 4h={r4h} 1h={r1h}"
            if r15 is not None:
                detail += f" 15m={r15}"
            if r1d is not None:
                detail += f" 1d={r1d}"
            return "overbought", detail

    if oversold:
        recovery = (
            (r1h is not None and r4h is not None and r1h >= r4h)
            or (r15 is not None and r1h is not None and r15 >= r1h)
        )
        extreme = any(r is not None and r <= os_ - 5 for r in (r4h, r1h, r1d))
        if recovery or extreme:
            detail = f"RSI oversold (<{os_:.0f}) 4h={r4h} 1h={r1h}"
            if r15 is not None:
                detail += f" 15m={r15}"
            if r1d is not None:
                detail += f" 1d={r1d}"
            return "oversold", detail

    return None, ""


def detect_derivative_flow(
    *,
    funding_rate: float | None,
    oi_change_pct: float | None,
    price_change_24h_pct: float | None,
    sell_ratio_delta: float | None,
    buy_ratio_delta: float | None,
    config: ScreenerConfig,
) -> tuple[DerivativeFlow | None, str]:
    """
    Visual Screener — fluxo de posições em derivativos.

    shorts_entering: OI↑ + preço fraco, funding positivo (longs lotados), sell ratio↑
    longs_entering:  OI↑ + preço forte, funding negativo (short squeeze), buy ratio↑
    """
    funding = funding_rate or 0.0
    price_chg = price_change_24h_pct or 0.0
    oi_chg = oi_change_pct
    reasons: list[tuple[DerivativeFlow, float, str]] = []

    if oi_chg is not None and oi_chg >= config.oi_change_min_pct:
        if price_chg <= 1.0:
            reasons.append((
                "shorts_entering",
                oi_chg + abs(min(price_chg, 0)),
                f"OI +{oi_chg:.1f}% com preço fraco ({price_chg:+.1f}%)",
            ))
        if price_chg >= 0:
            reasons.append((
                "longs_entering",
                oi_chg + max(price_chg, 0),
                f"OI +{oi_chg:.1f}% com preço forte ({price_chg:+.1f}%)",
            ))

    if funding >= config.funding_crowded_min:
        reasons.append((
            "shorts_entering",
            funding * 10_000,
            f"Funding crowded longs {funding:.4%}",
        ))

    if funding <= config.funding_squeeze_max:
        reasons.append((
            "longs_entering",
            abs(funding) * 10_000,
            f"Funding squeeze shorts {funding:.4%}",
        ))

    if sell_ratio_delta is not None and sell_ratio_delta >= config.account_ratio_delta_min:
        reasons.append((
            "shorts_entering",
            sell_ratio_delta * 100,
            f"Sell ratio +{sell_ratio_delta:.2%} (shorts entering)",
        ))

    if buy_ratio_delta is not None and buy_ratio_delta >= config.account_ratio_delta_min:
        reasons.append((
            "longs_entering",
            buy_ratio_delta * 100,
            f"Buy ratio +{buy_ratio_delta:.2%} (longs entering)",
        ))

    if not reasons:
        return None, ""

    flow, _, detail = max(reasons, key=lambda r: r[1])
    return flow, detail


def classify_trend_bias(
    rsi_by_tf: dict[str, float],
    config: ScreenerConfig,
) -> tuple[SetupDirection | None, str]:
    """
    RSI Heatmap para TENDÊNCIA (não reversão) — escolha de moeda.

    LONG: RSI alto em TFs maiores + momentum de alta.
    SHORT: RSI baixo em TFs maiores + momentum de baixa.
    """
    r15 = _rsi(rsi_by_tf, "15m")
    r1h = _rsi(rsi_by_tf, "1h")
    r4h = _rsi(rsi_by_tf, "4h")
    r1d = _rsi(rsi_by_tf, "1d")
    r30 = _rsi(rsi_by_tf, "30m")

    highs = _high_tf_rsi_values(rsi_by_tf)
    if not highs:
        return None, ""

    avg_high = sum(highs) / len(highs)
    mid = r15 if r15 is not None else (r30 if r30 is not None else (r1h or avg_high))

    if avg_high >= 55 and mid >= config.long_rsi_mid_tf_min:
        detail = f"RSI trend UP avg={avg_high:.0f} 4h={r4h} 1h={r1h}"
        if r30 is not None:
            detail += f" 30m={r30}"
        if r15 is not None:
            detail += f" 15m={r15}"
        return "LONG", detail

    if avg_high <= 45 and mid <= config.short_rsi_mid_tf_max:
        detail = f"RSI trend DN avg={avg_high:.0f} 4h={r4h} 1h={r1h}"
        if r30 is not None:
            detail += f" 30m={r30}"
        if r15 is not None:
            detail += f" 15m={r15}"
        return "SHORT", detail

    return None, ""


def evaluate_screener_trend(
    symbol: str,
    rsi_by_tf: dict[str, float],
    *,
    funding_rate: float | None,
    turnover_24h: float | None,
    price_change_24h_pct: float | None,
    oi_change_pct: float | None = None,
    sell_ratio: float | None = None,
    sell_ratio_delta: float | None = None,
    buy_ratio_delta: float | None = None,
    config: ScreenerConfig,
) -> ScreenerHit | None:
    """Screener só para tendência da moeda — RSI + derivativos confirmam direção."""
    trend_bias, rsi_detail = classify_trend_bias(rsi_by_tf, config)
    deriv_flow, deriv_detail = detect_derivative_flow(
        funding_rate=funding_rate,
        oi_change_pct=oi_change_pct,
        price_change_24h_pct=price_change_24h_pct,
        sell_ratio_delta=sell_ratio_delta,
        buy_ratio_delta=buy_ratio_delta,
        config=config,
    )

    if trend_bias is None:
        return None

    price_chg = price_change_24h_pct or 0.0

    if config.require_confluence:
        if deriv_flow is None:
            return None
        if trend_bias == "LONG" and deriv_flow != "longs_entering":
            if price_chg < 0:
                return None
        if trend_bias == "SHORT" and deriv_flow != "shorts_entering":
            if price_chg > 0:
                return None

    direction: SetupDirection = trend_bias
    r4h = _rsi(rsi_by_tf, "4h") or 50.0
    score = abs(r4h - 50)
    if trend_bias == "LONG":
        score += max(price_chg, 0)
    else:
        score += abs(min(price_chg, 0))
    if oi_change_pct:
        score += min(abs(oi_change_pct), 10)
    if funding_rate:
        score += abs(funding_rate) * 5000

    reason = f"TREND {direction} | {rsi_detail}"
    if deriv_detail:
        reason += f" + {deriv_detail}"

    return ScreenerHit(
        symbol=symbol,
        direction=direction,
        score=score,
        rsi_by_tf=rsi_by_tf,
        rsi_bias=trend_bias,
        derivative_flow=deriv_flow or "",
        funding_rate=funding_rate,
        turnover_24h=turnover_24h,
        price_change_24h_pct=price_change_24h_pct,
        oi_change_pct=oi_change_pct,
        sell_ratio=sell_ratio,
        reason=reason,
    )


def evaluate_screener_setup(
    symbol: str,
    rsi_by_tf: dict[str, float],
    *,
    funding_rate: float | None,
    turnover_24h: float | None,
    price_change_24h_pct: float | None,
    oi_change_pct: float | None = None,
    sell_ratio: float | None = None,
    sell_ratio_delta: float | None = None,
    buy_ratio_delta: float | None = None,
    config: ScreenerConfig,
) -> ScreenerHit | None:
    """Confluência obrigatória: RSI Heatmap + Visual Screener na mesma direção."""
    rsi_bias, rsi_detail = classify_rsi_bias(rsi_by_tf, config)
    deriv_flow, deriv_detail = detect_derivative_flow(
        funding_rate=funding_rate,
        oi_change_pct=oi_change_pct,
        price_change_24h_pct=price_change_24h_pct,
        sell_ratio_delta=sell_ratio_delta,
        buy_ratio_delta=buy_ratio_delta,
        config=config,
    )

    if config.require_confluence:
        if rsi_bias is None or deriv_flow is None:
            return None
        if rsi_bias == "overbought" and deriv_flow != "shorts_entering":
            return None
        if rsi_bias == "oversold" and deriv_flow != "longs_entering":
            return None
    else:
        if rsi_bias is None and deriv_flow is None:
            return None

    if rsi_bias == "overbought" or deriv_flow == "shorts_entering":
        direction: SetupDirection = "SHORT"
    elif rsi_bias == "oversold" or deriv_flow == "longs_entering":
        direction = "LONG"
    else:
        return None

    if config.require_confluence:
        direction = "SHORT" if rsi_bias == "overbought" else "LONG"

    r4h = _rsi(rsi_by_tf, "4h") or 50.0
    score = abs(r4h - 50)
    if oi_change_pct:
        score += min(oi_change_pct, 10)
    if funding_rate:
        score += abs(funding_rate) * 5000

    reason = f"CONFLUÊNCIA {direction} | {rsi_detail} + {deriv_detail}"

    return ScreenerHit(
        symbol=symbol,
        direction=direction,
        score=score,
        rsi_by_tf=rsi_by_tf,
        rsi_bias=rsi_bias or "",
        derivative_flow=deriv_flow or "",
        funding_rate=funding_rate,
        turnover_24h=turnover_24h,
        price_change_24h_pct=price_change_24h_pct,
        oi_change_pct=oi_change_pct,
        sell_ratio=sell_ratio,
        reason=reason,
    )


class MarketScreener:
    """Varre perpétuos USDT — só passa moedas com RSI + derivativos alinhados."""

    def __init__(self, exchange: ExchangeClient) -> None:
        self._exchange = exchange
        self._last_run: float = 0.0
        self._cached_symbols: list[str] = []
        self._cached_hits: list[ScreenerHit] = []
        self._prev_oi: dict[str, float] = {}

    @property
    def symbols(self) -> list[str]:
        return list(self._cached_symbols)

    @property
    def hits(self) -> list[ScreenerHit]:
        return list(self._cached_hits)

    def trend_bias_for(self, symbol: str) -> SetupDirection | None:
        """Tendência da moeda pelo screener (só escolha, não entrada)."""
        for hit in self._cached_hits:
            if hit.symbol == symbol:
                return hit.direction
        return None

    def needs_refresh(self, interval_seconds: int) -> bool:
        if not self._cached_symbols:
            return True
        return (time.monotonic() - self._last_run) >= interval_seconds

    def _enrich_oi_delta(self, liquid: dict[str, dict[str, Any]]) -> None:
        for symbol, info in liquid.items():
            oi = info.get("open_interest")
            if oi is None:
                info["oi_change_pct"] = None
                continue
            prev = self._prev_oi.get(symbol)
            if prev and prev > 0:
                info["oi_change_pct"] = (float(oi) - prev) / prev * 100
            else:
                info["oi_change_pct"] = None

    def _update_oi_cache(self, liquid: dict[str, dict[str, Any]]) -> None:
        for symbol, info in liquid.items():
            oi = info.get("open_interest")
            if oi is not None:
                self._prev_oi[symbol] = float(oi)

    async def refresh(self, config: ScreenerConfig) -> list[str]:
        """Executa varredura completa e atualiza cache."""
        if not config.enabled:
            self._cached_symbols = []
            self._cached_hits = []
            return []

        t0 = time.monotonic()
        market_data = await self._exchange.fetch_linear_market_snapshot()
        liquid = self._filter_by_liquidity(market_data, config.min_turnover_24h_usd)
        liquid = self._limit_prescan_universe(liquid, config.max_prescan_symbols)
        self._enrich_oi_delta(liquid)
        logger.info(
            "Screener fase 1 | %d pares líquidos (min $%.0f vol)",
            len(liquid),
            config.min_turnover_24h_usd,
        )

        hits = await self._scan_rsi_batch(liquid, config)
        self._update_oi_cache(liquid)

        hits.sort(key=lambda h: h.score, reverse=True)
        top = hits[: config.max_candidates]

        self._cached_hits = top
        self._cached_symbols = [h.symbol for h in top]
        self._last_run = time.monotonic()

        for hit in top[:10]:
            logger.info(
                "Screener %s | %s %s | score=%.1f | %s",
                config.mode.upper(),
                hit.direction,
                hit.symbol,
                hit.score,
                hit.reason,
            )
        if len(top) > 10:
            logger.info("Screener | +%d candidatos adicionais", len(top) - 10)

        logger.info(
            "Screener concluído | %d com confluência RSI+derivativos em %.1fs",
            len(top),
            time.monotonic() - t0,
        )
        return self._cached_symbols

    def _filter_by_liquidity(
        self,
        market_data: dict[str, dict[str, Any]],
        min_turnover: float,
    ) -> dict[str, dict[str, Any]]:
        filtered: dict[str, dict[str, Any]] = {}
        for symbol, info in market_data.items():
            turnover = float(info.get("turnover_24h") or 0)
            if turnover >= min_turnover:
                filtered[symbol] = info
        return filtered

    def _limit_prescan_universe(
        self,
        liquid: dict[str, dict[str, Any]],
        max_symbols: int,
    ) -> dict[str, dict[str, Any]]:
        """Mantém só os pares com maior volume — evita varrer 300+ moedas no startup."""
        if len(liquid) <= max_symbols:
            return liquid
        ranked = sorted(
            liquid.items(),
            key=lambda item: float(item[1].get("turnover_24h") or 0),
            reverse=True,
        )
        top = dict(ranked[:max_symbols])
        logger.info(
            "Screener universo | %d pares (top volume de %d líquidos)",
            len(top),
            len(liquid),
        )
        return top

    async def _scan_rsi_batch(
        self,
        liquid: dict[str, dict[str, Any]],
        config: ScreenerConfig,
    ) -> list[ScreenerHit]:
        items = list(liquid.items())
        sem = asyncio.Semaphore(config.ohlcv_concurrency)

        async def _one(symbol: str, info: dict[str, Any]) -> ScreenerHit | None:
            async with sem:
                try:
                    async def _fetch_tf(tf: str) -> tuple[str, list[list[float]] | None]:
                        candles = await self._exchange.fetch_ohlcv(
                            symbol,
                            timeframe=tf,
                            limit=max(config.rsi_period + 5, 30),
                        )
                        return tf, candles if candles else None

                    tf_pairs = await asyncio.gather(
                        *[_fetch_tf(tf) for tf in config.timeframes]
                    )
                    ohlcv_by_tf = {tf: c for tf, c in tf_pairs if c}

                    rsi_map = rsi_map_from_ohlcv(ohlcv_by_tf, config.rsi_period)

                    if config.mode == "trend":
                        trend_bias, _ = classify_trend_bias(rsi_map, config)
                        needs_derivatives = trend_bias is not None
                    else:
                        rsi_bias, _ = classify_rsi_bias(rsi_map, config)
                        needs_derivatives = rsi_bias is not None

                    ratio_data: dict[str, float | None] = {
                        "buy_ratio": None,
                        "sell_ratio": None,
                        "sell_ratio_delta": None,
                        "buy_ratio_delta": None,
                    }
                    if needs_derivatives:
                        ratio_data = await self._exchange.fetch_account_ratio_delta(
                            symbol,
                            period=config.account_ratio_period,
                        )

                    eval_fn = (
                        evaluate_screener_trend
                        if config.mode == "trend"
                        else evaluate_screener_setup
                    )
                    return eval_fn(
                        symbol,
                        rsi_map,
                        funding_rate=info.get("funding_rate"),
                        turnover_24h=info.get("turnover_24h"),
                        price_change_24h_pct=info.get("price_change_24h_pct"),
                        oi_change_pct=info.get("oi_change_pct"),
                        sell_ratio=ratio_data.get("sell_ratio"),
                        sell_ratio_delta=ratio_data.get("sell_ratio_delta"),
                        buy_ratio_delta=ratio_data.get("buy_ratio_delta"),
                        config=config,
                    )
                except Exception:
                    logger.debug("Screener skip | %s", symbol, exc_info=True)
                    return None

        def _on_batch(start: int, end: int, hit_count: int) -> None:
            logger.info(
                "Screener lote | %d-%d/%d | hits=%d",
                start + 1,
                end,
                len(items),
                hit_count,
            )

        return await map_batched(
            items,
            lambda pair: _one(pair[0], pair[1]),
            batch_size=config.prescan_batch_size,
            concurrency=config.ohlcv_concurrency,
            on_batch_done=_on_batch,
        )
