"""Filtro de entrada ALGO+Kalman — reversão Kalman + sinal IMBA."""

from __future__ import annotations

from dataclasses import dataclass

from src.models.schemas import TradeDirection


@dataclass(frozen=True)
class KalmanEntryVerdict:
    passed: bool
    reason: str = ""


def kalman_allows_entry(
    direction: TradeDirection,
    indicators: dict | None,
    *,
    require_reversal: bool = True,
) -> KalmanEntryVerdict:
    """
    LONG: kalman_reversal bullish OU kalman_signal bullish.
    SHORT: bearish equivalente.
    """
    if not indicators:
        return KalmanEntryVerdict(False, "Kalman indisponível")

    signal = (indicators.get("kalman_signal") or "").lower()
    reversal = (indicators.get("kalman_reversal") or "").lower()

    if direction == TradeDirection.LONG:
        if reversal == "bullish":
            return KalmanEntryVerdict(True, "Kalman reversal bullish")
        if not require_reversal and signal == "bullish":
            return KalmanEntryVerdict(True, "Kalman signal bullish")
        return KalmanEntryVerdict(
            False,
            f"Kalman não confirma LONG (signal={signal or 'n/a'} rev={reversal or 'n/a'})",
        )

    if reversal == "bearish":
        return KalmanEntryVerdict(True, "Kalman reversal bearish")
    if not require_reversal and signal == "bearish":
        return KalmanEntryVerdict(True, "Kalman signal bearish")
    return KalmanEntryVerdict(
        False,
        f"Kalman não confirma SHORT (signal={signal or 'n/a'} rev={reversal or 'n/a'})",
    )
