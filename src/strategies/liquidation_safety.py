"""Validação de SL vs preço de liquidação — impede SL além da liquidação."""

from __future__ import annotations

from typing import Literal

from src.models.schemas import TradeDirection

Side = Literal["LONG", "SHORT", "long", "short", "buy", "sell"]


def estimate_liquidation_price(
    entry: float,
    leverage: int,
    side: Side,
    *,
    maintenance_margin_rate: float = 0.005,
) -> float:
    """
    Estimativa conservadora para margem isolada USDT perpetual (Bybit).

    SHORT: liquidação acima da entrada.
    LONG: liquidação abaixo da entrada.
    """
    if entry <= 0:
        raise ValueError(f"entry inválida: {entry}")
    lev = max(int(leverage), 1)
    imr = 1.0 / lev
    side_norm = _normalize_side(side)
    if side_norm == "SHORT":
        return entry * (1.0 + imr - maintenance_margin_rate)
    return entry * (1.0 - imr + maintenance_margin_rate)


def parse_liquidation_from_position(pos: dict) -> float | None:
    """Extrai preço de liquidação de posição CCXT/Bybit."""
    for key in ("liquidationPrice", "liquidation_price"):
        val = pos.get(key)
        if val is not None:
            try:
                parsed = float(val)
                if parsed > 0:
                    return parsed
            except (TypeError, ValueError):
                pass
    info = pos.get("info") or {}
    for key in ("liqPrice", "liquidationPrice"):
        val = info.get(key)
        if val is not None:
            try:
                parsed = float(val)
                if parsed > 0:
                    return parsed
            except (TypeError, ValueError):
                pass
    return None


def safe_stop_loss_bounds(
    direction: TradeDirection | Side,
    liquidation_price: float,
    buffer_pct: float,
) -> tuple[float | None, float | None]:
    """
    Limites seguros para SL em relação à liquidação.

    LONG: SL > min_sl (liq abaixo).
    SHORT: SL < max_sl (liq acima).
    """
    buffer = buffer_pct / 100.0
    side = _normalize_side(direction)
    if side == "LONG":
        return liquidation_price * (1.0 + buffer), None
    return None, liquidation_price * (1.0 - buffer)


def validate_stop_loss_vs_liquidation(
    direction: TradeDirection | Side,
    entry: float,
    stop_loss: float,
    liquidation_price: float,
    buffer_pct: float,
) -> str | None:
    """Retorna mensagem de erro se SL não dispara antes da liquidação."""
    side = _normalize_side(direction)
    min_sl, max_sl = safe_stop_loss_bounds(direction, liquidation_price, buffer_pct)

    if side == "LONG":
        if stop_loss >= entry:
            return "SL deve ficar abaixo da entrada (LONG)"
        if min_sl is not None and stop_loss < min_sl:
            return (
                f"SL {stop_loss:.6g} < limite seguro {min_sl:.6g} "
                f"(liq={liquidation_price:.6g})"
            )
    else:
        if stop_loss <= entry:
            return "SL deve ficar acima da entrada (SHORT)"
        if max_sl is not None and stop_loss > max_sl:
            return (
                f"SL {stop_loss:.6g} > limite seguro {max_sl:.6g} "
                f"(liq={liquidation_price:.6g}) — liquidação antes do SL"
            )
    return None


def clamp_stop_loss_to_liquidation(
    direction: TradeDirection | Side,
    entry: float,
    stop_loss: float,
    liquidation_price: float,
    buffer_pct: float,
) -> tuple[float, bool, str | None]:
    """
    Ajusta SL para ficar do lado seguro da liquidação.

    Retorna (sl_ajustado, foi_clampado, motivo_rejeição).
    """
    side = _normalize_side(direction)
    min_sl, max_sl = safe_stop_loss_bounds(direction, liquidation_price, buffer_pct)
    original = stop_loss
    adjusted = stop_loss

    if max_sl is not None and adjusted >= max_sl:
        adjusted = max_sl
    if min_sl is not None and adjusted <= min_sl:
        adjusted = min_sl

    clamped = abs(adjusted - original) > 1e-12

    if side == "SHORT":
        if adjusted <= entry:
            return adjusted, clamped, (
                f"SL seguro {adjusted:.6g} <= entrada {entry:.6g} "
                f"(liq={liquidation_price:.6g})"
            )
    elif adjusted >= entry:
        return adjusted, clamped, (
            f"SL seguro {adjusted:.6g} >= entrada {entry:.6g} "
            f"(liq={liquidation_price:.6g})"
        )

    err = validate_stop_loss_vs_liquidation(
        direction, entry, adjusted, liquidation_price, buffer_pct
    )
    if err:
        return adjusted, clamped, err
    return adjusted, clamped, None


def _normalize_side(side: TradeDirection | Side) -> Literal["LONG", "SHORT"]:
    if isinstance(side, TradeDirection):
        return "LONG" if side == TradeDirection.LONG else "SHORT"
    s = str(side).upper()
    if s in ("LONG", "BUY"):
        return "LONG"
    return "SHORT"
