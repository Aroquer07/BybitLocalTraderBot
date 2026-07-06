"""Montagem do relatório periódico de win/loss e PnL aberto."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from src.models.schemas import StoredTrade, TradeDirection
from src.utils.formatters import format_percentage, format_usd

TZ_BR = ZoneInfo("America/Sao_Paulo")

PnlPeriod = Literal["day", "week", "month", "year"]

PERIOD_DAYS: dict[PnlPeriod, int] = {
    "day": 1,
    "week": 7,
    "month": 30,
    "year": 365,
}

PERIOD_LABELS: dict[PnlPeriod, str] = {
    "day": "último dia",
    "week": "última semana",
    "month": "último mês",
    "year": "último ano",
}

MS_DAY = 86_400_000
MAX_BYBIT_WINDOW_MS = 7 * MS_DAY - 1

_DIRECTION_ICON = {
    "LONG": "📈",
    "SHORT": "📉",
}


def period_range_ms(period: PnlPeriod) -> tuple[int, int]:
    """Retorna (start_ms, end_ms) UTC para o período configurado."""
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - PERIOD_DAYS[period] * MS_DAY
    return start_ms, end_ms


def aggregate_closed_pnl_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Agrega registros closed-pnl da Bybit (fills + posições lógicas agrupadas)."""
    from src.services.closed_pnl_groups import (
        aggregate_position_groups,
        group_closed_pnl_records,
    )

    wins = losses = 0
    total_usd = 0.0
    for row in records:
        pnl = float(row.get("closedPnl") or 0)
        total_usd += pnl
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1

    closed = len(records)
    decisive = wins + losses
    winrate = wins / decisive * 100.0 if decisive else 0.0

    groups = group_closed_pnl_records(records)
    position_stats = aggregate_position_groups(groups)

    return {
        "closed_trades": closed,
        "wins": wins,
        "losses": losses,
        "winrate_pct": round(winrate, 2),
        "total_pnl_usd": round(total_usd, 2),
        "position_groups": position_stats,
        "position_group_rows": groups,
    }


def position_row_from_exchange(pos: dict[str, Any]) -> dict[str, Any] | None:
    """Normaliza posição CCXT para o relatório — usa unrealizedPnl da exchange."""
    contracts = abs(float(pos.get("contracts") or pos.get("contractSize") or 0))
    if contracts <= 0:
        return None

    side = (pos.get("side") or "long").lower()
    direction = "LONG" if side in ("long", "buy") else "SHORT"
    symbol = str(pos.get("symbol") or "").split(":")[0]

    pnl_usd = float(pos.get("unrealizedPnl") or pos.get("unrealisedPnl") or 0)
    notional = abs(float(pos.get("notional") or 0))
    leverage = int(float(pos.get("leverage") or 1))

    if pos.get("percentage") is not None:
        pnl_pct = float(pos["percentage"])
    elif notional > 0 and leverage > 0:
        # ROE% igual ao painel Bybit: PnL / margem * 100
        pnl_pct = pnl_usd * leverage / notional * 100.0
    else:
        entry = float(pos.get("entryPrice") or 0)
        mark = float(pos.get("markPrice") or 0)
        if entry > 0:
            move = ((mark - entry) / entry * 100.0) if direction == "LONG" else (
                (entry - mark) / entry * 100.0
            )
            pnl_pct = move * leverage
        else:
            pnl_pct = 0.0

    return {
        "symbol": symbol,
        "direction": direction,
        "leverage": leverage,
        "pnl_pct": round(pnl_pct, 2),
        "pnl_usd": round(pnl_usd, 2),
    }


def unrealized_pnl_pct(trade: StoredTrade, mark_price: float) -> float:
    """PnL %% não realizado vs preço de entrada."""
    if trade.entry_price <= 0:
        return 0.0
    if trade.direction == TradeDirection.LONG:
        return (mark_price - trade.entry_price) / trade.entry_price * 100.0
    return (trade.entry_price - mark_price) / trade.entry_price * 100.0


def unrealized_pnl_usd(trade: StoredTrade, mark_price: float) -> float:
    """PnL USD não realizado com base no tamanho da posição."""
    amount = trade.amount or 0.0
    if amount <= 0 or trade.entry_price <= 0:
        return 0.0
    if trade.direction == TradeDirection.LONG:
        return (mark_price - trade.entry_price) * amount
    return (trade.entry_price - mark_price) * amount


def realized_pnl_usd(trade: StoredTrade) -> float:
    """PnL USD realizado de trade fechado."""
    if trade.amount and trade.amount > 0 and trade.exit_price is not None:
        if trade.direction == TradeDirection.LONG:
            return (trade.exit_price - trade.entry_price) * trade.amount
        return (trade.entry_price - trade.exit_price) * trade.amount
    if trade.pnl_pct is not None and trade.amount and trade.entry_price > 0:
        notional = trade.amount * trade.entry_price
        return notional * (trade.pnl_pct / 100.0)
    return 0.0


def _direction_icon(direction: str) -> str:
    return _DIRECTION_ICON.get(direction.upper(), "📊")


def _format_position_line(row: dict[str, Any]) -> str:
    pair = str(row["symbol"]).replace("/", "")
    icon = _direction_icon(str(row["direction"]))
    pnl_pct = float(row["pnl_pct"])
    pnl_usd = float(row["pnl_usd"])
    return (
        f"{icon} {pair} {row['direction']} {row['leverage']}x | "
        f"{format_percentage(pnl_pct)}% | {format_usd(pnl_usd)}"
    )


def _render_position_block(
    rows: list[dict[str, Any]],
    *,
    title: str,
) -> list[str]:
    if not rows:
        return []
    lines = [title, f"({len(rows)})"]
    for row in rows:
        lines.append(_format_position_line(row))
    lines.append("")
    return lines


def build_pnl_report_message(
    *,
    stats: dict[str, Any],
    open_positions: list[dict[str, Any]],
    bybit_mode: str,
    period: PnlPeriod = "week",
    generated_at: datetime | None = None,
) -> str:
    """Formata relatório horário para Telegram."""
    now = (generated_at or datetime.now(TZ_BR)).astimezone(TZ_BR)
    stamp = now.strftime("%d/%m/%Y %H:%M")

    wins = stats.get("wins", 0)
    losses = stats.get("losses", 0)
    closed = stats.get("closed_trades", 0)
    winrate = stats.get("winrate_pct", 0.0)
    realized_usd = float(stats.get("total_pnl_usd", 0.0))
    open_count = len(open_positions)
    pos = stats.get("position_groups") or {}

    lines = [
        f"📊 RELATÓRIO BYBITBOT | {bybit_mode.upper()}",
        f"🕐 {stamp}",
        "",
        "═══ WIN/LOSS (fechados) ═══",
        f"Período: {PERIOD_LABELS[period]}",
        f"Fechamentos API: {closed} | Abertos agora: {open_count}",
        f"Fills W/L: {wins}W / {losses}L ({winrate:.1f}%)",
        f"PnL realizado: {format_usd(realized_usd)}",
        "",
    ]

    if pos:
        lines.extend(
            [
                "═══ POSIÇÕES (agrupadas) ═══",
                f"Trades lógicos: {pos.get('position_trades', 0)} "
                f"({pos.get('total_fills', 0)} fills)",
                f"W/L: {pos.get('wins', 0)}W / {pos.get('losses', 0)}L "
                f"({float(pos.get('winrate_pct', 0)):.1f}%)",
                f"Avg Win/Loss: {format_usd(float(pos.get('avg_win_usd', 0)))} / "
                f"{format_usd(float(pos.get('avg_loss_usd', 0)))}",
                f"Profit Factor: {pos.get('profit_factor') or '—'}",
                "",
            ]
        )

    if not open_positions:
        lines.append("═══ POSIÇÕES ABERTAS ═══")
        lines.append("Nenhuma posição aberta na Bybit.")
        return "\n".join(lines)

    winners = sorted(
        [r for r in open_positions if float(r["pnl_usd"]) >= 0],
        key=lambda r: float(r["pnl_usd"]),
        reverse=True,
    )
    losers = sorted(
        [r for r in open_positions if float(r["pnl_usd"]) < 0],
        key=lambda r: float(r["pnl_usd"]),
    )

    lines.append("═══ POSIÇÕES ABERTAS ═══")
    lines.extend(_render_position_block(winners, title="✅ No lucro"))
    lines.extend(_render_position_block(losers, title="❌ No prejuízo"))

    total_unrealized_usd = sum(float(r["pnl_usd"]) for r in open_positions)
    total_unrealized_pct = sum(float(r["pnl_pct"]) for r in open_positions)
    avg_unrealized_pct = total_unrealized_pct / len(open_positions)
    combined_usd = realized_usd + total_unrealized_usd

    lines.extend(
        [
            f"PnL flutuante total: {format_usd(total_unrealized_usd)} "
            f"({format_percentage(avg_unrealized_pct)}% ROE médio)",
            f"PnL combinado: {format_usd(combined_usd)}",
        ]
    )
    return "\n".join(lines)
