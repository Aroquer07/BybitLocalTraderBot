"""
Motor de backtest vetorial (VectorBT) — 100% isolado do bot ao vivo.

Usa ccxt em modo leitura (sem API keys) para OHLCV público da Bybit.
Não importa ExchangeClient, ExecutionController nem qualquer loop de execução.

CLI:
    python -m tools.quant_validator --symbol SOL/USDT --days 30
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import ccxt
import numpy as np
import pandas as pd
import pandas_ta as ta
import vectorbt as vbt
from ccxt.base.errors import DDoSProtection, ExchangeError, NetworkError, RateLimitExceeded

# --- Constantes de simulação (custos reais Bybit linear perp) ---
BYBIT_TAKER_FEE = 0.00055
SLIPPAGE = 0.001
DEFAULT_INITIAL_CASH = 10_000.0
CCXT_PAGE_LIMIT = 1_000
MAX_FETCH_RETRIES = 5

# R:R blended das parciais do bot (50%@1.2R + 30%@2R + 20%@3R)
TP_CLOSE_PCTS: tuple[float, ...] = (50.0, 30.0, 20.0)
TP_RR_MULTIPLIERS: tuple[float, ...] = (1.2, 2.0, 3.0)

SUPPORTED_TIMEFRAMES = frozenset({"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"})


class OhlcvFetchError(Exception):
    """Falha ao baixar OHLCV da exchange."""


class OhlcvRateLimitError(OhlcvFetchError):
    """Rate limit da exchange após retries."""


@dataclass(frozen=True)
class BacktestMetrics:
    win_rate_pct: float
    profit_factor: float
    max_drawdown_pct: float
    total_return_pct: float
    total_fees_paid: float
    total_trades: int
    sharpe_ratio: float | None = None
    end_value: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _timeframe_to_ms(timeframe: str) -> int:
    tf = timeframe.strip().lower()
    if tf not in SUPPORTED_TIMEFRAMES:
        raise ValueError(
            f"Timeframe não suportado: {timeframe}. "
            f"Use um de: {sorted(SUPPORTED_TIMEFRAMES)}"
        )
    if tf.endswith("m"):
        return int(tf[:-1]) * 60_000
    if tf.endswith("h"):
        return int(tf[:-1]) * 3_600_000
    if tf.endswith("d"):
        return int(tf[:-1]) * 86_400_000
    raise ValueError(f"Timeframe inválido: {timeframe}")


def _timeframe_to_freq(timeframe: str) -> str:
    tf = timeframe.strip().lower()
    if tf.endswith("m"):
        return f"{tf[:-1]}min"
    if tf.endswith("h"):
        return tf
    if tf.endswith("d"):
        return tf
    raise ValueError(f"Timeframe inválido: {timeframe}")


def _bars_per_day(timeframe: str) -> int:
    return max(1, 86_400_000 // _timeframe_to_ms(timeframe))


def _blended_tp_r_multiple() -> float:
    weights = TP_CLOSE_PCTS[: len(TP_RR_MULTIPLIERS)]
    total_w = sum(weights)
    if total_w <= 0:
        return float(TP_RR_MULTIPLIERS[0])
    return sum((w / total_w) * rr for w, rr in zip(weights, TP_RR_MULTIPLIERS))


def _resolve_symbol(exchange: ccxt.bybit, symbol: str) -> str:
    """Normaliza símbolo para mercado linear USDT perp da Bybit."""
    resolved = symbol.strip().upper()
    if "/" not in resolved:
        base = resolved.replace("USDT", "")
        resolved = f"{base}/USDT:USDT"
    elif ":" not in resolved:
        resolved = f"{resolved}:USDT"

    if resolved in exchange.markets:
        return resolved

    alt = symbol if "/" in symbol else f"{symbol[:3]}/{symbol[3:]}"
    if alt in exchange.markets:
        return alt

    raise ValueError(f"Símbolo não encontrado na Bybit: {symbol}")


class QuantBacktester:
    """
    Backtest vetorizado com VectorBT.

    Estratégia exemplo: cruzamento EMA rápida/lenta + filtro RSI.
    Execução simulada com fees taker e slippage; SL/TP por ATR.
    """

    def __init__(
        self,
        *,
        ema_fast: int = 9,
        ema_slow: int = 21,
        rsi_period: int = 14,
        rsi_long_min: float = 50.0,
        rsi_short_max: float = 50.0,
        atr_period: int = 14,
        atr_mult: float = 1.5,
        initial_cash: float = DEFAULT_INITIAL_CASH,
        warmup_bars: int = 50,
        fees: float = BYBIT_TAKER_FEE,
        slippage: float = SLIPPAGE,
    ) -> None:
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.rsi_period = rsi_period
        self.rsi_long_min = rsi_long_min
        self.rsi_short_max = rsi_short_max
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.initial_cash = initial_cash
        self.warmup_bars = warmup_bars
        self.fees = fees
        self.slippage = slippage

    def _create_readonly_exchange(self) -> ccxt.bybit:
        """ccxt estritamente read-only — sem apiKey/secret."""
        return ccxt.bybit(
            {
                "enableRateLimit": True,
                "options": {"defaultType": "swap"},
            }
        )

    def fetch_ohlcv(
        self,
        symbol: str,
        *,
        days: int = 30,
        timeframe: str = "5m",
    ) -> pd.DataFrame:
        """
        Baixa OHLCV histórico da Bybit com paginação e retry em rate limit.
        """
        if days < 1 or days > 90:
            raise ValueError("days deve estar entre 1 e 90")

        tf_ms = _timeframe_to_ms(timeframe)
        bars_per_day = _bars_per_day(timeframe)
        target_bars = days * bars_per_day
        since = int(
            (datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000
        )

        exchange = self._create_readonly_exchange()
        try:
            exchange.load_markets()
            resolved = _resolve_symbol(exchange, symbol)

            rows: list[list[float]] = []
            cursor = since

            while len(rows) < target_bars:
                batch = self._fetch_batch_with_retry(
                    exchange, resolved, timeframe, cursor
                )
                if not batch:
                    break

                rows.extend(batch)
                cursor = batch[-1][0] + tf_ms

                if len(batch) < CCXT_PAGE_LIMIT:
                    break

            if not rows:
                raise OhlcvFetchError(f"Nenhum dado OHLCV retornado para {resolved}")

            df = pd.DataFrame(
                rows,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            for col in ("open", "high", "low", "close", "volume"):
                df[col] = pd.to_numeric(df[col], errors="coerce")

            return (
                df.dropna()
                .drop_duplicates(subset="timestamp")
                .sort_values("timestamp")
                .set_index("timestamp")
            )
        finally:
            exchange.close()

    def _fetch_batch_with_retry(
        self,
        exchange: ccxt.bybit,
        symbol: str,
        timeframe: str,
        since: int,
    ) -> list[list[float]]:
        last_err: Exception | None = None
        for attempt in range(MAX_FETCH_RETRIES):
            try:
                return exchange.fetch_ohlcv(
                    symbol,
                    timeframe=timeframe,
                    since=since,
                    limit=CCXT_PAGE_LIMIT,
                )
            except (RateLimitExceeded, DDoSProtection) as exc:
                last_err = exc
                wait_s = min(30.0, (2**attempt) * (exchange.rateLimit / 1000.0 + 1.0))
                time.sleep(wait_s)
            except (NetworkError, ExchangeError) as exc:
                last_err = exc
                if attempt < MAX_FETCH_RETRIES - 1:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise OhlcvFetchError(f"Exchange recusou download OHLCV: {exc}") from exc

        raise OhlcvRateLimitError(
            f"Rate limit Bybit após {MAX_FETCH_RETRIES} tentativas: {last_err}"
        ) from last_err

    def _compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        work = df.copy()
        work[f"EMA_{self.ema_fast}"] = ta.ema(work["close"], length=self.ema_fast)
        work[f"EMA_{self.ema_slow}"] = ta.ema(work["close"], length=self.ema_slow)
        work[f"RSI_{self.rsi_period}"] = ta.rsi(work["close"], length=self.rsi_period)
        work[f"ATR_{self.atr_period}"] = ta.atr(
            work["high"], work["low"], work["close"], length=self.atr_period
        )
        return work

    def _generate_signals(
        self, work: pd.DataFrame
    ) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
        ema_fast_col = f"EMA_{self.ema_fast}"
        ema_slow_col = f"EMA_{self.ema_slow}"
        rsi_col = f"RSI_{self.rsi_period}"

        ema_fast_prev = work[ema_fast_col].shift(1)
        ema_slow_prev = work[ema_slow_col].shift(1)

        cross_up = (ema_fast_prev <= ema_slow_prev) & (
            work[ema_fast_col] > work[ema_slow_col]
        )
        cross_dn = (ema_fast_prev >= ema_slow_prev) & (
            work[ema_fast_col] < work[ema_slow_col]
        )

        rsi = work[rsi_col]
        raw_long = cross_up & (rsi >= self.rsi_long_min)
        raw_short = cross_dn & (rsi <= self.rsi_short_max)
        raw_exit_long = cross_dn
        raw_exit_short = cross_up

        def _next_bar(signal: pd.Series) -> pd.Series:
            # Anti-lookahead: sinal no close t, execução no open t+1
            return signal.shift(1).astype("boolean").fillna(False)

        return (
            _next_bar(raw_long),
            _next_bar(raw_exit_long),
            _next_bar(raw_short),
            _next_bar(raw_exit_short),
        )

    def _build_portfolio(
        self,
        work: pd.DataFrame,
        entries_long: pd.Series,
        exits_long: pd.Series,
        entries_short: pd.Series,
        exits_short: pd.Series,
        *,
        timeframe: str,
    ) -> vbt.Portfolio:
        close = work["close"]
        open_ = work["open"]
        atr = work[f"ATR_{self.atr_period}"]

        risk_frac = (atr * self.atr_mult) / close
        risk_frac = risk_frac.replace([np.inf, -np.inf], np.nan).fillna(0.01).clip(
            0.001, 0.15
        )
        blended_tp_r = _blended_tp_r_multiple()

        return vbt.Portfolio.from_signals(
            close,
            entries=entries_long,
            exits=exits_long,
            short_entries=entries_short,
            short_exits=exits_short,
            open=open_,
            price=open_,
            sl_stop=risk_frac,
            tp_stop=risk_frac * blended_tp_r,
            fees=self.fees,
            slippage=self.slippage,
            init_cash=self.initial_cash,
            freq=_timeframe_to_freq(timeframe),
            upon_opposite_entry="ignore",
        )

    @staticmethod
    def _extract_metrics(portfolio: vbt.Portfolio) -> BacktestMetrics:
        stats = portfolio.stats()

        def _get(key: str, default: float = float("nan")) -> float:
            try:
                val = stats.get(key, default)
                return float(val) if val is not None else default
            except (TypeError, ValueError, KeyError):
                return default

        sharpe = _get("Sharpe Ratio")
        return BacktestMetrics(
            win_rate_pct=round(_get("Win Rate [%]"), 4),
            profit_factor=round(_get("Profit Factor"), 4),
            max_drawdown_pct=round(_get("Max Drawdown [%]"), 4),
            total_return_pct=round(_get("Total Return [%]"), 4),
            total_fees_paid=round(_get("Total Fees Paid"), 4),
            total_trades=int(_get("Total Trades", 0)),
            sharpe_ratio=round(sharpe, 4) if not np.isnan(sharpe) else None,
            end_value=round(_get("End Value"), 4),
        )

    def run(
        self,
        symbol: str,
        *,
        timeframe: str = "5m",
        days: int = 30,
        initial_cash: float | None = None,
    ) -> dict[str, Any]:
        """
        Pipeline completo: fetch → indicadores → sinais → portfolio → JSON.
        """
        cash = initial_cash if initial_cash is not None else self.initial_cash
        df = self.fetch_ohlcv(symbol, days=days, timeframe=timeframe)

        if len(df) < self.warmup_bars + 10:
            raise ValueError(
                f"Dados insuficientes ({len(df)} candles) para warmup={self.warmup_bars}"
            )

        work = self._compute_indicators(df).iloc[self.warmup_bars :].copy()
        entries_long, exits_long, entries_short, exits_short = self._generate_signals(work)

        portfolio = self._build_portfolio(
            work,
            entries_long,
            exits_long,
            entries_short,
            exits_short,
            timeframe=timeframe,
        )
        metrics = self._extract_metrics(portfolio)

        return {
            "ok": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "days": days,
            "candles": len(work),
            "period_start": work.index[0].isoformat(),
            "period_end": work.index[-1].isoformat(),
            "signals": {
                "long_entries": int(entries_long.sum()),
                "short_entries": int(entries_short.sum()),
            },
            "strategy": {
                "name": "ema_cross_rsi",
                "ema_fast": self.ema_fast,
                "ema_slow": self.ema_slow,
                "rsi_period": self.rsi_period,
                "rsi_long_min": self.rsi_long_min,
                "rsi_short_max": self.rsi_short_max,
                "atr_mult": self.atr_mult,
            },
            "simulation": {
                "fees": self.fees,
                "slippage": self.slippage,
                "initial_cash": cash,
            },
            "metrics": metrics.to_dict(),
        }


def _print_cli_result(result: dict[str, Any]) -> None:
    m = result["metrics"]
    sep = "=" * 60
    print(f"\n{sep}")
    print(
        f"  BACKTEST — {result['symbol']} | {result['days']}d | "
        f"{result['timeframe']} | fees={result['simulation']['fees']} | "
        f"slip={result['simulation']['slippage']}"
    )
    print(sep)
    print(f"  Win Rate        : {m['win_rate_pct']:>10.2f} %")
    print(f"  Profit Factor   : {m['profit_factor']:>10.3f}")
    print(f"  Max Drawdown    : {m['max_drawdown_pct']:>10.2f} %")
    print(f"  Total Return    : {m['total_return_pct']:>10.2f} %")
    print(f"  Total Fees Paid : {m['total_fees_paid']:>10.2f}")
    print(f"  Total Trades    : {m['total_trades']:>10d}")
    print(sep)
    print("\nJSON:\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest vetorizado isolado (VectorBT + pandas-ta + ccxt read-only)",
    )
    parser.add_argument("--symbol", default="SOL/USDT")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--cash", type=float, default=DEFAULT_INITIAL_CASH)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    backtester = QuantBacktester(initial_cash=args.cash)
    result = backtester.run(
        args.symbol,
        timeframe=args.timeframe,
        days=args.days,
        initial_cash=args.cash,
    )
    _print_cli_result(result)


if __name__ == "__main__":
    main()
