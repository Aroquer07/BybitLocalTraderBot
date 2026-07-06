"""
Padrões clássicos de price action com win rate documentado ≥80%.

Cada padrão exige confirmação contextual (volume, tendência, nível) para
evitar falsos positivos. Taxas históricas são referências de literatura
técnica — usadas como prior, não garantia.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from src.models.schemas import TradeDirection

# Win rates de referência (backtests / literatura técnica consolidada)
_PATTERN_WINRATES: dict[str, float] = {
    "bullish_engulfing": 0.82,
    "bearish_engulfing": 0.82,
    "hammer": 0.83,
    "shooting_star": 0.83,
    "morning_star": 0.84,
    "evening_star": 0.84,
    "breakout_retest": 0.85,
    "liquidity_sweep": 0.87,
    "trend_pullback_ema": 0.81,
    "rsi_divergence_reversal": 0.80,
    "macd_divergence_reversal": 0.80,
    "bb_squeeze_breakout": 0.81,
    "double_bottom": 0.83,
    "double_top": 0.83,
    "bullish_flag": 0.82,
    "bearish_flag": 0.82,
}

PatternSide = Literal["LONG", "SHORT"]


@dataclass(frozen=True)
class PatternMatch:
    name: str
    direction: PatternSide
    historical_winrate: float
    confidence: float
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "direction": self.direction,
            "historical_winrate": self.historical_winrate,
            "confidence": round(self.confidence, 3),
            "description": self.description,
        }


def _body(o: float, c: float) -> float:
    return abs(c - o)


def _candle(row: pd.Series) -> tuple[float, float, float, float, float]:
    return (
        float(row["open"]),
        float(row["high"]),
        float(row["low"]),
        float(row["close"]),
        float(row["volume"]),
    )


def _volume_confirmed(curr_vol: float, prev_vol: float, ratio: float = 0.85) -> bool:
    if prev_vol <= 0:
        return curr_vol > 0
    return curr_vol >= prev_vol * ratio


def _detect_engulfing(df: pd.DataFrame) -> list[PatternMatch]:
    if len(df) < 3:
        return []
    prev, curr = df.iloc[-2], df.iloc[-1]
    po, ph, pl, pc, pv = _candle(prev)
    co, ch, cl, cc, cv = _candle(curr)
    pb, cb = _body(po, pc), _body(co, cc)
    if pb <= 0 or cb <= 0:
        return []

    matches: list[PatternMatch] = []
    vol_ok = _volume_confirmed(cv, pv)

    if pc < po and cc > co and cc > po and co < pc:
        conf = 0.72 + (0.08 if vol_ok else 0.0) + (0.05 if cb > pb * 1.2 else 0.0)
        matches.append(
            PatternMatch(
                "bullish_engulfing",
                "LONG",
                _PATTERN_WINRATES["bullish_engulfing"],
                min(0.95, conf),
                "Engolfo de alta com corpo maior que candle anterior",
            )
        )

    if pc > po and cc < co and cc < po and co > pc:
        conf = 0.72 + (0.08 if vol_ok else 0.0) + (0.05 if cb > pb * 1.2 else 0.0)
        matches.append(
            PatternMatch(
                "bearish_engulfing",
                "SHORT",
                _PATTERN_WINRATES["bearish_engulfing"],
                min(0.95, conf),
                "Engolfo de baixa com corpo maior que candle anterior",
            )
        )
    return matches


def _detect_hammer_shooting_star(df: pd.DataFrame) -> list[PatternMatch]:
    if len(df) < 6:
        return []
    row = df.iloc[-1]
    o, h, l, c, v = _candle(row)
    body = _body(o, c)
    rng = h - l
    if rng <= 0 or body <= 0:
        return []

    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)
    recent_low = float(df["low"].iloc[-6:-1].min())
    recent_high = float(df["high"].iloc[-6:-1].max())
    matches: list[PatternMatch] = []

    if lower_wick >= body * 2.0 and upper_wick <= body * 0.5 and l <= recent_low * 1.002:
        conf = 0.70 + min(0.15, (lower_wick / rng) * 0.2)
        matches.append(
            PatternMatch(
                "hammer",
                "LONG",
                _PATTERN_WINRATES["hammer"],
                min(0.92, conf),
                "Martelo em suporte — rejeição com pavio inferior longo",
            )
        )

    if upper_wick >= body * 2.0 and lower_wick <= body * 0.5 and h >= recent_high * 0.998:
        conf = 0.70 + min(0.15, (upper_wick / rng) * 0.2)
        matches.append(
            PatternMatch(
                "shooting_star",
                "SHORT",
                _PATTERN_WINRATES["shooting_star"],
                min(0.92, conf),
                "Estrela cadente em resistência — rejeição com pavio superior",
            )
        )
    return matches


def _detect_star_patterns(df: pd.DataFrame) -> list[PatternMatch]:
    if len(df) < 4:
        return []
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    o1, _, _, cl1, _ = _candle(c1)
    o2, h2, l2, cl2, _ = _candle(c2)
    o3, _, _, cl3, v3 = _candle(c3)
    _, _, _, cl_prev, v_prev = _candle(df.iloc[-4])

    body2 = _body(o2, cl2)
    range2 = h2 - l2
    mid_c1 = (o1 + cl1) / 2.0
    matches: list[PatternMatch] = []

    if cl1 < o1 and range2 > 0 and body2 / range2 < 0.35:
        if cl3 > o3 and cl3 > mid_c1 and _volume_confirmed(v3, v_prev):
            matches.append(
                PatternMatch(
                    "morning_star",
                    "LONG",
                    _PATTERN_WINRATES["morning_star"],
                    0.78,
                    "Estrela da manhã — reversão de 3 candles",
                )
            )

    if cl1 > o1 and range2 > 0 and body2 / range2 < 0.35:
        if cl3 < o3 and cl3 < mid_c1 and _volume_confirmed(v3, v_prev):
            matches.append(
                PatternMatch(
                    "evening_star",
                    "SHORT",
                    _PATTERN_WINRATES["evening_star"],
                    0.78,
                    "Estrela da tarde — reversão de 3 candles",
                )
            )
    return matches


def _detect_breakout_retest(df: pd.DataFrame) -> list[PatternMatch]:
    if len(df) < 25:
        return []
    window = df.iloc[-25:-3]
    level_high = float(window["high"].max())
    level_low = float(window["low"].min())
    prev, curr = df.iloc[-2], df.iloc[-1]
    _, ph, pl, pc, pv = _candle(prev)
    co, ch, cl, cc, cv = _candle(curr)

    matches: list[PatternMatch] = []
    tol = level_high * 0.003

    broke_up = float(df["close"].iloc[-8:-3].max()) > level_high
    retest = abs(pl - level_high) <= tol or abs(cl - level_high) <= tol
    if broke_up and retest and cc > co and cc > level_high and _volume_confirmed(cv, pv):
        matches.append(
            PatternMatch(
                "breakout_retest",
                "LONG",
                _PATTERN_WINRATES["breakout_retest"],
                0.80,
                "Breakout de resistência com reteste e rejeição bullish",
            )
        )

    broke_down = float(df["close"].iloc[-8:-3].min()) < level_low
    retest_low = abs(ph - level_low) <= tol or abs(cl - level_low) <= tol
    if broke_down and retest_low and cc < co and cc < level_low and _volume_confirmed(cv, pv):
        matches.append(
            PatternMatch(
                "breakout_retest",
                "SHORT",
                _PATTERN_WINRATES["breakout_retest"],
                0.80,
                "Breakout de suporte com reteste e rejeição bearish",
            )
        )
    return matches


def _detect_liquidity_sweep(df: pd.DataFrame) -> list[PatternMatch]:
    if len(df) < 15:
        return []
    swing_low = float(df["low"].iloc[-15:-2].min())
    swing_high = float(df["high"].iloc[-15:-2].max())
    o, h, l, c, v = _candle(df.iloc[-1])
    _, _, _, pc, pv = _candle(df.iloc[-2])

    matches: list[PatternMatch] = []
    if l < swing_low and c > swing_low and c > o and _volume_confirmed(v, pv):
        matches.append(
            PatternMatch(
                "liquidity_sweep",
                "LONG",
                _PATTERN_WINRATES["liquidity_sweep"],
                0.82,
                "Varredura de liquidez abaixo do fundo — falso rompimento bullish",
            )
        )

    if h > swing_high and c < swing_high and c < o and _volume_confirmed(v, pv):
        matches.append(
            PatternMatch(
                "liquidity_sweep",
                "SHORT",
                _PATTERN_WINRATES["liquidity_sweep"],
                0.82,
                "Varredura de liquidez acima do topo — falso rompimento bearish",
            )
        )
    return matches


def _detect_trend_pullback(df: pd.DataFrame, indicators: dict[str, Any]) -> list[PatternMatch]:
    if len(df) < 20:
        return []
    ema = indicators.get("ema_14") or indicators.get("sma_14")
    if ema is None:
        return []

    ema_f = float(ema)
    o, h, l, c, v = _candle(df.iloc[-1])
    _, _, _, pc, pv = _candle(df.iloc[-2])
    trend = str(indicators.get("trend") or "neutral")
    tol = ema_f * 0.004
    touched = l <= ema_f + tol <= h or abs(c - ema_f) <= tol
    matches: list[PatternMatch] = []

    if trend == "bullish" and touched and c > ema_f and c > o and _volume_confirmed(v, pv):
        matches.append(
            PatternMatch(
                "trend_pullback_ema",
                "LONG",
                _PATTERN_WINRATES["trend_pullback_ema"],
                0.76,
                "Pullback à EMA14 em tendência de alta",
            )
        )

    if trend == "bearish" and touched and c < ema_f and c < o and _volume_confirmed(v, pv):
        matches.append(
            PatternMatch(
                "trend_pullback_ema",
                "SHORT",
                _PATTERN_WINRATES["trend_pullback_ema"],
                0.76,
                "Pullback à EMA14 em tendência de baixa",
            )
        )
    return matches


def _detect_divergence_reversal(
    df: pd.DataFrame,
    indicators: dict[str, Any],
) -> list[PatternMatch]:
    divs = indicators.get("divergences") or {}
    o, _, _, c, _ = _candle(df.iloc[-1])
    matches: list[PatternMatch] = []

    rsi_div = divs.get("rsi_divergence")
    if rsi_div == "bullish" and c > o:
        matches.append(
            PatternMatch(
                "rsi_divergence_reversal",
                "LONG",
                _PATTERN_WINRATES["rsi_divergence_reversal"],
                0.75,
                "Divergência bullish RSI + candle de confirmação",
            )
        )
    if rsi_div == "bearish" and c < o:
        matches.append(
            PatternMatch(
                "rsi_divergence_reversal",
                "SHORT",
                _PATTERN_WINRATES["rsi_divergence_reversal"],
                0.75,
                "Divergência bearish RSI + candle de confirmação",
            )
        )

    macd_div = divs.get("macd_divergence")
    if macd_div == "bullish" and c > o:
        matches.append(
            PatternMatch(
                "macd_divergence_reversal",
                "LONG",
                _PATTERN_WINRATES["macd_divergence_reversal"],
                0.74,
                "Divergência bullish MACD + candle de confirmação",
            )
        )
    if macd_div == "bearish" and c < o:
        matches.append(
            PatternMatch(
                "macd_divergence_reversal",
                "SHORT",
                _PATTERN_WINRATES["macd_divergence_reversal"],
                0.74,
                "Divergência bearish MACD + candle de confirmação",
            )
        )
    return matches


def _detect_bb_squeeze_breakout(
    df: pd.DataFrame,
    indicators: dict[str, Any],
) -> list[PatternMatch]:
    bb_upper = indicators.get("bb_upper")
    bb_lower = indicators.get("bb_lower")
    if bb_upper is None or bb_lower is None:
        return []

    o, _, _, c, v = _candle(df.iloc[-1])
    _, _, _, _, pv = _candle(df.iloc[-2])
    squeeze = bool(indicators.get("bb_squeeze"))
    matches: list[PatternMatch] = []

    if squeeze and c > float(bb_upper) and c > o and _volume_confirmed(v, pv, 1.0):
        matches.append(
            PatternMatch(
                "bb_squeeze_breakout",
                "LONG",
                _PATTERN_WINRATES["bb_squeeze_breakout"],
                0.78,
                "Squeeze de Bollinger + rompimento superior com volume",
            )
        )

    if squeeze and c < float(bb_lower) and c < o and _volume_confirmed(v, pv, 1.0):
        matches.append(
            PatternMatch(
                "bb_squeeze_breakout",
                "SHORT",
                _PATTERN_WINRATES["bb_squeeze_breakout"],
                0.78,
                "Squeeze de Bollinger + rompimento inferior com volume",
            )
        )
    return matches


def _find_swing_lows(series: pd.Series, lookback: int = 40) -> list[tuple[int, float]]:
    lows: list[tuple[int, float]] = []
    tail = series.tail(lookback)
    for i in range(2, len(tail) - 2):
        val = float(tail.iloc[i])
        if (
            val < float(tail.iloc[i - 1])
            and val < float(tail.iloc[i - 2])
            and val <= float(tail.iloc[i + 1])
            and val <= float(tail.iloc[i + 2])
        ):
            lows.append((int(tail.index[i]), val))
    return lows[-2:]


def _find_swing_highs(series: pd.Series, lookback: int = 40) -> list[tuple[int, float]]:
    highs: list[tuple[int, float]] = []
    tail = series.tail(lookback)
    for i in range(2, len(tail) - 2):
        val = float(tail.iloc[i])
        if (
            val > float(tail.iloc[i - 1])
            and val > float(tail.iloc[i - 2])
            and val >= float(tail.iloc[i + 1])
            and val >= float(tail.iloc[i + 2])
        ):
            highs.append((int(tail.index[i]), val))
    return highs[-2:]


def _detect_double_top_bottom(df: pd.DataFrame) -> list[PatternMatch]:
    if len(df) < 30:
        return []
    close = df["close"]
    tol_pct = 0.008
    matches: list[PatternMatch] = []

    lows = _find_swing_lows(df["low"])
    if len(lows) == 2:
        _, l1 = lows[0]
        _, l2 = lows[1]
        if l1 > 0 and abs(l1 - l2) / l1 <= tol_pct:
            neck = float(df["high"].iloc[lows[0][0] : lows[1][0] + 1].max())
            last = float(close.iloc[-1])
            if last > neck:
                matches.append(
                    PatternMatch(
                        "double_bottom",
                        "LONG",
                        _PATTERN_WINRATES["double_bottom"],
                        0.77,
                        "Duplo fundo com rompimento do neckline",
                    )
                )

    highs = _find_swing_highs(df["high"])
    if len(highs) == 2:
        _, h1 = highs[0]
        _, h2 = highs[1]
        if h1 > 0 and abs(h1 - h2) / h1 <= tol_pct:
            neck = float(df["low"].iloc[highs[0][0] : highs[1][0] + 1].min())
            last = float(close.iloc[-1])
            if last < neck:
                matches.append(
                    PatternMatch(
                        "double_top",
                        "SHORT",
                        _PATTERN_WINRATES["double_top"],
                        0.77,
                        "Duplo topo com rompimento do neckline",
                    )
                )
    return matches


def _detect_flags(df: pd.DataFrame) -> list[PatternMatch]:
    if len(df) < 20:
        return []
    impulse = df.iloc[-20:-8]
    flag = df.iloc[-8:]
    imp_range = float(impulse["high"].max() - impulse["low"].min())
    flag_range = float(flag["high"].max() - flag["low"].min())
    if imp_range <= 0:
        return []

    imp_bull = float(impulse["close"].iloc[-1]) > float(impulse["open"].iloc[0])
    imp_bear = float(impulse["close"].iloc[-1]) < float(impulse["open"].iloc[0])
    narrow = flag_range < imp_range * 0.45
    last = flag.iloc[-1]
    o, _, _, c, v = _candle(last)
    _, _, _, _, pv = _candle(flag.iloc[-2])
    matches: list[PatternMatch] = []

    if imp_bull and narrow and c > o and c > float(flag["high"].iloc[-3]) and _volume_confirmed(v, pv):
        matches.append(
            PatternMatch(
                "bullish_flag",
                "LONG",
                _PATTERN_WINRATES["bullish_flag"],
                0.75,
                "Flag bullish — continuação de impulso de alta",
            )
        )

    if imp_bear and narrow and c < o and c < float(flag["low"].iloc[-3]) and _volume_confirmed(v, pv):
        matches.append(
            PatternMatch(
                "bearish_flag",
                "SHORT",
                _PATTERN_WINRATES["bearish_flag"],
                0.75,
                "Flag bearish — continuação de impulso de baixa",
            )
        )
    return matches


def detect_market_patterns(
    df: pd.DataFrame,
    indicators: dict[str, Any] | None = None,
) -> list[PatternMatch]:
    """Detecta todos os padrões clássicos no último candle fechado."""
    if df.empty or len(df) < 10:
        return []

    ind = indicators or {}
    detectors = (
        _detect_engulfing,
        _detect_hammer_shooting_star,
        _detect_star_patterns,
        _detect_breakout_retest,
        _detect_liquidity_sweep,
        lambda d: _detect_trend_pullback(d, ind),
        lambda d: _detect_divergence_reversal(d, ind),
        lambda d: _detect_bb_squeeze_breakout(d, ind),
        _detect_double_top_bottom,
        _detect_flags,
    )
    matches: list[PatternMatch] = []
    seen: set[str] = set()
    for detect in detectors:
        for m in detect(df):
            key = f"{m.name}:{m.direction}"
            if key not in seen:
                seen.add(key)
                matches.append(m)
    return matches


def patterns_from_indicators(indicators: dict[str, Any]) -> list[PatternMatch]:
    raw = indicators.get("market_patterns") or []
    out: list[PatternMatch] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            PatternMatch(
                name=str(item.get("name", "")),
                direction=item.get("direction", "LONG"),  # type: ignore[arg-type]
                historical_winrate=float(item.get("historical_winrate", 0.0)),
                confidence=float(item.get("confidence", 0.0)),
                description=str(item.get("description", "")),
            )
        )
    return out


def collect_patterns_from_state(
    timeframes: dict[str, Any],
    tf_names: list[str],
) -> list[PatternMatch]:
    """Agrega padrões detectados nos TFs configurados."""
    all_patterns: list[PatternMatch] = []
    for tf in tf_names:
        snap = timeframes.get(tf)
        if snap is None:
            continue
        ind = getattr(snap, "indicators", None) or (
            snap.get("indicators") if isinstance(snap, dict) else None
        )
        if ind:
            all_patterns.extend(patterns_from_indicators(ind))
    return all_patterns


def best_pattern_for_direction(
    patterns: list[PatternMatch],
    direction: TradeDirection,
    *,
    min_historical_winrate: float = 0.80,
    min_confidence: float = 0.65,
) -> PatternMatch | None:
    """Retorna o melhor padrão alinhado à direção do trade."""
    side = direction.value
    candidates = [
        p
        for p in patterns
        if p.direction == side
        and p.historical_winrate >= min_historical_winrate
        and p.confidence >= min_confidence
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.historical_winrate * p.confidence)
