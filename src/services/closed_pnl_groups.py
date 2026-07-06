"""Agrupa registros closed-PnL da Bybit em posições lógicas (1 trade = N fills parciais)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def position_group_key(record: dict[str, Any]) -> tuple[str, str, float]:
    """Chave estável: símbolo + lado do fechamento + preço médio de entrada."""
    symbol = str(record.get("symbol") or "")
    side = str(record.get("side") or "")
    entry = round(_float(record.get("avgEntryPrice")), 8)
    return symbol, side, entry


def group_closed_pnl_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agrupa fills parciais em posições lógicas com PnL e taxas somados."""
    buckets: dict[tuple[str, str, float], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        buckets[position_group_key(row)].append(row)

    groups: list[dict[str, Any]] = []
    for (symbol, side, entry_price), fills in buckets.items():
        total_pnl = sum(_float(r.get("closedPnl")) for r in fills)
        total_fees = sum(
            _float(r.get("openFee")) + _float(r.get("closeFee")) for r in fills
        )
        leverages = [_float(r.get("leverage"), 1) for r in fills if r.get("leverage")]
        avg_lev = sum(leverages) / len(leverages) if leverages else 0.0
        qty = sum(_float(r.get("closedSize") or r.get("qty")) for r in fills)
        exit_prices = [_float(r.get("avgExitPrice")) for r in fills if r.get("avgExitPrice")]
        avg_exit = sum(exit_prices) / len(exit_prices) if exit_prices else 0.0
        times = [
            int(r.get("updatedTime") or r.get("createdTime") or 0) for r in fills
        ]
        groups.append(
            {
                "symbol": symbol,
                "side": side,
                "avg_entry_price": entry_price,
                "avg_exit_price": round(avg_exit, 8),
                "total_pnl": round(total_pnl, 8),
                "total_fees": round(total_fees, 8),
                "fill_count": len(fills),
                "leverage": round(avg_lev, 2),
                "closed_qty": qty,
                "first_time_ms": min(times) if times else 0,
                "last_time_ms": max(times) if times else 0,
            }
        )

    groups.sort(key=lambda g: g["last_time_ms"])
    return groups


def aggregate_position_groups(groups: list[dict[str, Any]]) -> dict[str, Any]:
    """Estatísticas W/L e PF por posição lógica (não por fill parcial)."""
    pnls = [_float(g.get("total_pnl")) for g in groups]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    decisive = len(wins) + len(losses)
    winrate = len(wins) / decisive * 100.0 if decisive else 0.0
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")
    avg_win = gross_win / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0

    return {
        "position_trades": len(groups),
        "wins": len(wins),
        "losses": len(losses),
        "winrate_pct": round(winrate, 2),
        "total_pnl_usd": round(sum(pnls), 2),
        "avg_win_usd": round(avg_win, 2),
        "avg_loss_usd": round(avg_loss, 2),
        "win_loss_ratio": round(abs(avg_win / avg_loss), 2) if avg_loss else 0.0,
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else None,
        "gross_win_usd": round(gross_win, 2),
        "gross_loss_usd": round(gross_loss, 2),
        "total_fees_usd": round(sum(_float(g.get("total_fees")) for g in groups), 2),
        "total_fills": sum(int(g.get("fill_count") or 0) for g in groups),
    }
