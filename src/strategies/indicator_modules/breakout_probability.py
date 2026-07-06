"""Breakout Probability (Zeiierman) — viés e % do próximo candle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.strategies.indicators import ohlcv_to_dataframe

Bias = Literal["BULLISH", "BEARISH"]


@dataclass(frozen=True)
class BreakoutOutlook:
    """Probabilidade histórica de continuação no próximo candle."""

    bias: Bias
    probability_pct: float
    prob_high_pct: float
    prob_low_pct: float
    prev_candle: Literal["green", "red"]
    reason: str


def evaluate_breakout_probability(
    ohlcv: list[list[float]],
    *,
    min_probability_pct: float = 60.0,
    lookback: int = 500,
) -> BreakoutOutlook:
    """
    Replica a lógica do painel Breakout Probability (nível 0):
    - Candle anterior verde: compara % de novo high vs novo low
    - Candle anterior vermelho: idem com histórico em candles vermelhos
    """
    df = ohlcv_to_dataframe(ohlcv)
    if len(df) < 30:
        return BreakoutOutlook(
            bias="BULLISH",
            probability_pct=0.0,
            prob_high_pct=0.0,
            prob_low_pct=0.0,
            prev_candle="green",
            reason="OHLCV insuficiente",
        )

    work = df.tail(min(lookback, len(df)))
    gtotal = rtotal = 0
    ghh = gll = rhh = rll = 0

    for i in range(1, len(work)):
        prev_green = float(work["close"].iloc[i - 1]) > float(work["open"].iloc[i - 1])
        prev_red = float(work["close"].iloc[i - 1]) < float(work["open"].iloc[i - 1])
        hh = float(work["high"].iloc[i]) >= float(work["high"].iloc[i - 1])
        ll = float(work["low"].iloc[i]) <= float(work["low"].iloc[i - 1])

        if prev_green:
            gtotal += 1
            if hh:
                ghh += 1
            if ll:
                gll += 1
        elif prev_red:
            rtotal += 1
            if hh:
                rhh += 1
            if ll:
                rll += 1

    a1 = round(ghh / gtotal * 100, 2) if gtotal else 0.0
    b1 = round(gll / gtotal * 100, 2) if gtotal else 0.0
    a2 = round(rhh / rtotal * 100, 2) if rtotal else 0.0
    b2 = round(rll / rtotal * 100, 2) if rtotal else 0.0

    prev_green = float(work["close"].iloc[-2]) > float(work["open"].iloc[-2])
    prev_red = float(work["close"].iloc[-2]) < float(work["open"].iloc[-2])
    prev_candle: Literal["green", "red"] = "green" if prev_green else "red"

    if prev_green:
        if a1 >= b1:
            bias: Bias = "BULLISH"
            prob = a1
        else:
            bias = "BEARISH"
            prob = b1
        high_p, low_p = a1, b1
    elif prev_red:
        if a2 >= b2:
            bias = "BULLISH"
            prob = a2
        else:
            bias = "BEARISH"
            prob = b2
        high_p, low_p = a2, b2
    else:
        bias = "BULLISH" if a1 >= b1 else "BEARISH"
        prob = a1 if bias == "BULLISH" else b1
        high_p, low_p = a1, b1

    reason = (
        f"Breakout {bias} {prob:.1f}% "
        f"(high={high_p:.1f}% low={low_p:.1f}% | prev={prev_candle})"
    )
    if prob < min_probability_pct:
        reason += f" | abaixo de {min_probability_pct:.0f}%"

    return BreakoutOutlook(
        bias=bias,
        probability_pct=prob,
        prob_high_pct=high_p,
        prob_low_pct=low_p,
        prev_candle=prev_candle,
        reason=reason,
    )


def breakout_confirms_direction(
    outlook: BreakoutOutlook,
    direction: Literal["LONG", "SHORT"],
    *,
    min_probability_pct: float = 60.0,
) -> tuple[bool, str]:
    """Sniper aponta entrada; breakout confirma continuação ≥ min_probability_pct."""
    need: Bias = "BULLISH" if direction == "LONG" else "BEARISH"
    if outlook.bias != need:
        return (
            False,
            f"Breakout {outlook.bias} {outlook.probability_pct:.1f}% "
            f"≠ {direction} (precisa {need})",
        )
    if outlook.probability_pct < min_probability_pct:
        return (
            False,
            f"Breakout {outlook.bias} {outlook.probability_pct:.1f}% "
            f"< {min_probability_pct:.0f}%",
        )
    return True, outlook.reason


def compute_breakout_levels(
    ohlcv: list[list[float]],
    *,
    nbr: int = 5,
    perc: float = 1.0,
    lookback: int = 500,
    hide_zero: bool = True,
) -> list[dict[str, float | str | int]]:
    """
    Níveis stepped do Pine (até 5 linhas high/low com % histórica).
    """
    df = ohlcv_to_dataframe(ohlcv)
    if len(df) < 3:
        return []

    work = df.tail(min(lookback, len(df)))
    n_levels = max(1, min(5, nbr))
    # matrix rows: ghh, gll, rhh, rll per level
    counts = [[0, 0, 0, 0] for _ in range(n_levels)]
    gtotal = rtotal = 0
    close_last = float(work["close"].iloc[-1])
    step = close_last * (perc / 100.0)

    for i in range(1, len(work)):
        prev_green = float(work["close"].iloc[i - 1]) > float(work["open"].iloc[i - 1])
        prev_red = float(work["close"].iloc[i - 1]) < float(work["open"].iloc[i - 1])
        h_prev = float(work["high"].iloc[i - 1])
        l_prev = float(work["low"].iloc[i - 1])
        h = float(work["high"].iloc[i])
        l = float(work["low"].iloc[i])

        if prev_green:
            gtotal += 1
        elif prev_red:
            rtotal += 1
        else:
            continue

        for lvl in range(n_levels):
            offset = step * lvl
            hh = h >= h_prev + offset
            ll = l <= l_prev - offset
            if prev_green:
                if hh:
                    counts[lvl][0] += 1
                if ll:
                    counts[lvl][1] += 1
            elif prev_red:
                if hh:
                    counts[lvl][2] += 1
                if ll:
                    counts[lvl][3] += 1

    prev_green = float(work["close"].iloc[-2]) > float(work["open"].iloc[-2])
    prev_red = float(work["close"].iloc[-2]) < float(work["open"].iloc[-2])
    h_prev = float(work["high"].iloc[-2])
    l_prev = float(work["low"].iloc[-2])

    levels: list[dict[str, float | str | int]] = []
    for lvl in range(n_levels):
        offset = step * lvl
        ghh, gll, rhh, rll = counts[lvl]
        a1 = round(ghh / gtotal * 100, 2) if gtotal else 0.0
        b1 = round(gll / gtotal * 100, 2) if gtotal else 0.0
        a2 = round(rhh / rtotal * 100, 2) if rtotal else 0.0
        b2 = round(rll / rtotal * 100, 2) if rtotal else 0.0

        if prev_green:
            high_pct, low_pct = a1, b1
        elif prev_red:
            high_pct, low_pct = a2, b2
        else:
            high_pct, low_pct = a1, b1

        hi_price = round(h_prev + offset, 8)
        lo_price = round(l_prev - offset, 8)

        if hide_zero and high_pct <= 0 and low_pct <= 0:
            continue

        levels.append(
            {
                "step_index": lvl,
                "price": hi_price,
                "prob_pct": high_pct,
                "side": "high",
                "color": "#22c55e",
            }
        )
        levels.append(
            {
                "step_index": lvl,
                "price": lo_price,
                "prob_pct": low_pct,
                "side": "low",
                "color": "#ef4444",
            }
        )

    return levels


def compute_breakout_backtest(
    ohlcv: list[list[float]],
    *,
    lookback: int = 500,
) -> dict[str, float | int]:
    """Painel WIN/LOSS do Pine (nível escolhido pelo viés do candle anterior)."""
    df = ohlcv_to_dataframe(ohlcv)
    if len(df) < 30:
        return {"wins": 0, "losses": 0, "win_rate_pct": 0.0}

    work = df.tail(min(lookback, len(df)))
    gtotal = rtotal = ghh = gll = rhh = rll = 0

    for i in range(1, len(work)):
        prev_green = float(work["close"].iloc[i - 1]) > float(work["open"].iloc[i - 1])
        prev_red = float(work["close"].iloc[i - 1]) < float(work["open"].iloc[i - 1])
        hh = float(work["high"].iloc[i]) >= float(work["high"].iloc[i - 1])
        ll = float(work["low"].iloc[i]) <= float(work["low"].iloc[i - 1])
        if prev_green:
            gtotal += 1
            if hh:
                ghh += 1
            if ll:
                gll += 1
        elif prev_red:
            rtotal += 1
            if hh:
                rhh += 1
            if ll:
                rll += 1

    a1 = round(ghh / gtotal * 100, 2) if gtotal else 0.0
    b1 = round(gll / gtotal * 100, 2) if gtotal else 0.0
    a2 = round(rhh / rtotal * 100, 2) if rtotal else 0.0
    b2 = round(rll / rtotal * 100, 2) if rtotal else 0.0

    prev_green = float(work["close"].iloc[-2]) > float(work["open"].iloc[-2])
    prev_red = float(work["close"].iloc[-2]) < float(work["open"].iloc[-2])

    if prev_green:
        target = float(work["high"].iloc[-2]) if a1 >= b1 else float(work["low"].iloc[-2])
    elif prev_red:
        target = float(work["high"].iloc[-2]) if a2 >= b2 else float(work["low"].iloc[-2])
    else:
        target = float(work["high"].iloc[-2]) if a1 >= b1 else float(work["low"].iloc[-2])

    wins = losses = 0
    for i in range(1, len(work)):
        h = float(work["high"].iloc[i])
        l = float(work["low"].iloc[i])
        if target == float(work["high"].iloc[i - 1]):
            if h >= target:
                wins += 1
            else:
                losses += 1
        else:
            if l <= target:
                wins += 1
            else:
                losses += 1

    total = wins + losses
    wr = round(wins / total * 100, 2) if total else 0.0
    return {"wins": wins, "losses": losses, "win_rate_pct": wr}


