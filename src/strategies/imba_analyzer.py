"""Análise multi-timeframe do indicador [IMBA] ALGO."""

from __future__ import annotations

from src.config.runtime_config import BotRuntimeConfig
from src.models.schemas import ImbaAnalysis, ImbaTimeframeResult, TradeDirection
from src.strategies.imba_algo import (
    ImbaAlgoConfig,
    ImbaSignal,
    ImbaTrendState,
    Side,
    compute_channel_levels,
    compute_stop_loss,
    compute_take_profits,
    evaluate_dataframe,
    evaluate_ohlcv,
)
from src.strategies.indicators import ohlcv_to_dataframe

DEFAULT_EXECUTION_TIMEFRAME = "5m"


def imba_analysis_timeframes(runtime: BotRuntimeConfig) -> list[str]:
    """TFs IMBA — execução 5m + confirmação 15m/30m/1h (scalp)."""
    preferred = ("5m", "15m", "30m", "1h")
    tfs: list[str] = []
    for tf in preferred:
        if tf in runtime.timeframes.analysis and tf not in tfs:
            tfs.append(tf)
    if runtime.timeframes.execution not in tfs:
        tfs.insert(0, runtime.timeframes.execution)
    return tfs


def fresh_signal_priority(runtime: BotRuntimeConfig) -> tuple[str, ...]:
    """Sinal fresco prioriza TF de execução (5m)."""
    exec_tf = runtime.timeframes.execution
    order = [exec_tf]
    for tf in ("15m", "30m", "1h"):
        if tf not in order:
            order.append(tf)
    return tuple(order)


def config_from_runtime(runtime: BotRuntimeConfig) -> ImbaAlgoConfig:
    return ImbaAlgoConfig(
        sensitivity=runtime.imba.sensitivity,
        tp_percents=runtime.imba.tp_percent_tuple(),
        tp_close_pcts=runtime.imba.tp_close_tuple(),
    )


def config_from_settings(settings: object) -> ImbaAlgoConfig:
    """Compat: aceita BotRuntimeConfig ou objeto legado com attrs imba."""
    if isinstance(settings, BotRuntimeConfig):
        return config_from_runtime(settings)
    return ImbaAlgoConfig(
        sensitivity=getattr(settings, "imba_sensitivity", 2.0),
        tp_percents=getattr(settings, "imba_tp_percent_tuple", lambda: (1.0, 2.0, 3.0, 4.0))(),
        tp_close_pcts=getattr(settings, "imba_tp_close_tuple", lambda: (50.0, 30.0, 20.0))(),
    )


def _trend_label(state: ImbaTrendState) -> str:
    if state.is_long_trend:
        return "LONG"
    if state.is_short_trend:
        return "SHORT"
    return "NEUTRAL"


def _signal_fresh_on_last_bar(
    ohlcv: list[list[float]],
    config: ImbaAlgoConfig,
) -> tuple[ImbaTrendState, ImbaSignal | None, bool]:
    """Avalia se o sinal surgiu especificamente no último candle fechado."""
    df = ohlcv_to_dataframe(ohlcv)
    if len(df) < config.lookback + 1:
        state, _ = evaluate_ohlcv(ohlcv, config, exclude_forming_candle=True)
        return state, None, False

    closed_df = df.iloc[:-1]
    prev_state, prev_signal = evaluate_dataframe(closed_df.iloc[:-1], config)
    state, signal = evaluate_dataframe(closed_df, config, prev_state)

    fresh = signal is not None and (
        prev_signal is None
        or prev_signal.side != signal.side
        or prev_signal.entry_price != signal.entry_price
    )
    return state, signal if fresh else None, fresh


def analyze_timeframe(
    ohlcv: list[list[float]],
    timeframe: str,
    config: ImbaAlgoConfig,
) -> ImbaTimeframeResult:
    state, signal, fresh = _signal_fresh_on_last_bar(ohlcv, config)
    direction = None
    if signal:
        direction = TradeDirection.LONG if signal.side == "LONG" else TradeDirection.SHORT

    return ImbaTimeframeResult(
        timeframe=timeframe,
        trend=_trend_label(state),
        signal_on_last_bar=fresh and signal is not None,
        signal_side=direction,
        entry_price=signal.entry_price if signal else None,
        stop_loss=signal.stop_loss if signal else None,
        take_profits=list(signal.take_profits) if signal else [],
    )


def _tf_weights(timeframes: dict[str, ImbaTimeframeResult]) -> dict[str, float]:
    """Pesos scalp — 1h/30m confirmam, 5m dispara entrada."""
    weights: dict[str, float] = {}
    for tf in timeframes:
        if tf == "1h":
            weights[tf] = 0.35
        elif tf == "30m":
            weights[tf] = 0.30
        elif tf == "15m":
            weights[tf] = 0.25
        elif tf == "5m":
            weights[tf] = 0.10
        else:
            weights[tf] = 0.15
    total = sum(weights.values()) or 1.0
    return {tf: w / total for tf, w in weights.items()}


def _compute_confidence(
    results: dict[str, ImbaTimeframeResult],
    primary_direction: TradeDirection | None,
) -> float:
    if primary_direction is None:
        return 0.0

    weights = _tf_weights(results)
    score = 0.0
    for tf, weight in weights.items():
        r = results.get(tf)
        if r is None:
            continue
        if r.signal_on_last_bar and r.signal_side == primary_direction:
            score += weight
        elif r.trend == primary_direction.value:
            score += weight * 0.75
        elif r.trend == "NEUTRAL":
            score += weight * 0.25

    return round(min(score, 1.0), 4)


def analyze_multi_timeframe(
    symbol: str,
    ohlcv_by_tf: dict[str, list[list[float]]],
    config: ImbaAlgoConfig | None = None,
    *,
    settings: BotRuntimeConfig | None = None,
) -> ImbaAnalysis:
    """Analisa IMBA ALGO em múltiplos timeframes e calcula score de confiança."""
    if config is None:
        if settings is None:
            config = ImbaAlgoConfig()
        else:
            config = config_from_settings(settings)

    exec_tf = (
        settings.timeframes.execution if settings else DEFAULT_EXECUTION_TIMEFRAME
    )
    signal_order = (
        fresh_signal_priority(settings) if settings else ("5m", "3m", "15m")
    )

    tf_results: dict[str, ImbaTimeframeResult] = {}
    for tf, ohlcv in ohlcv_by_tf.items():
        if not ohlcv:
            continue
        tf_results[tf] = analyze_timeframe(ohlcv, tf, config)

    fresh_direction: TradeDirection | None = None
    for tf in signal_order:
        r = tf_results.get(tf)
        if r and r.signal_on_last_bar and r.signal_side:
            fresh_direction = r.signal_side
            break

    aligned: TradeDirection | None = None
    trends = [r.trend for r in tf_results.values() if r.trend != "NEUTRAL"]
    if trends and all(t == trends[0] for t in trends):
        aligned = TradeDirection(trends[0])

    primary = fresh_direction or aligned
    confidence = _compute_confidence(tf_results, primary)

    parts: list[str] = []
    for tf in sorted(tf_results.keys()):
        r = tf_results[tf]
        flag = " [SINAL]" if r.signal_on_last_bar else ""
        parts.append(f"{tf}={r.trend}{flag}")
    summary = f"IMBA {symbol}: " + ", ".join(parts)
    if primary:
        summary += f" | direção={primary.value} score={confidence:.0%}"
        summary += f" | SL/TP=IMBA {exec_tf}"

    return ImbaAnalysis(
        symbol=symbol,
        timeframes=tf_results,
        aligned_direction=aligned,
        fresh_signal_direction=fresh_direction,
        confidence_score=confidence,
        summary=summary,
    )


def resolve_entry_direction(
    analysis: ImbaAnalysis,
    *,
    exec_tf: str,
    require_fresh: bool = False,
) -> TradeDirection | None:
    """
    Direção de entrada: sinal fresco no candle OU tendência no TF de execução.
    """
    if analysis.fresh_signal_direction is not None:
        return analysis.fresh_signal_direction
    if require_fresh:
        return None
    if analysis.aligned_direction is not None:
        exec_r = analysis.timeframes.get(exec_tf)
        if exec_r and exec_r.trend == analysis.aligned_direction.value:
            return analysis.aligned_direction
    exec_r = analysis.timeframes.get(exec_tf)
    if exec_r and exec_r.trend in ("LONG", "SHORT"):
        return TradeDirection(exec_r.trend)
    return None


def build_execution_signal_for_direction(
    direction: TradeDirection,
    ohlcv: list[list[float]],
    config: ImbaAlgoConfig,
) -> ImbaSignal | None:
    """
    Monta entry/SL/TPs exclusivamente a partir do canal IMBA no TF de execução (5m).

    Usa o último candle fechado como entrada e fib do canal para SL.
    """
    df = ohlcv_to_dataframe(ohlcv)
    if len(df) < config.lookback:
        return None

    closed = df.iloc[:-1] if len(df) > 1 else df
    if len(closed) < config.lookback:
        return None

    idx = len(closed) - 1
    window_high = closed["high"].iloc[idx - config.lookback + 1 : idx + 1]
    window_low = closed["low"].iloc[idx - config.lookback + 1 : idx + 1]
    levels = compute_channel_levels(window_high, window_low)
    entry = float(closed["close"].iloc[idx])
    side: Side = "LONG" if direction == TradeDirection.LONG else "SHORT"

    return ImbaSignal(
        side=side,
        entry_price=entry,
        stop_loss=compute_stop_loss(side, entry, levels, config),
        take_profits=compute_take_profits(side, entry, config),
        levels=levels,
    )


def pick_execution_levels(
    analysis: ImbaAnalysis,
    config: ImbaAlgoConfig,
    ohlcv_by_tf: dict[str, list[list[float]]] | None = None,
    *,
    execution_timeframe: str = DEFAULT_EXECUTION_TIMEFRAME,
) -> ImbaSignal | None:
    """
    Direção vem da análise multi-TF (3m/5m/15m).
    Entry, SL e TPs são SEMPRE calculados no timeframe de execução (default 5m).
    """
    direction = analysis.fresh_signal_direction or analysis.aligned_direction
    if direction is None:
        return None

    if ohlcv_by_tf and execution_timeframe in ohlcv_by_tf:
        signal = build_execution_signal_for_direction(
            direction,
            ohlcv_by_tf[execution_timeframe],
            config,
        )
        if signal:
            return signal

    r = analysis.timeframes.get(execution_timeframe)
    if r and r.stop_loss:
        side: Side = "LONG" if direction == TradeDirection.LONG else "SHORT"
        entry = r.entry_price or 0.0
        tps = r.take_profits
        if len(tps) < 4 and entry > 0:
            tps = list(compute_take_profits(side, entry, config))
        if entry > 0:
            return ImbaSignal(
                side=side,
                entry_price=entry,
                stop_loss=r.stop_loss,
                take_profits=(tps[0], tps[1], tps[2], tps[3]),
            )
    return None
