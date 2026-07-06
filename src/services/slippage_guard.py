"""Detecção e alerta de slippage (preço da ordem vs preço de execução)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

SLIPPAGE_ALERT_THRESHOLD_PCT = 1.0


@dataclass(frozen=True)
class SlippageEvent:
    symbol: str
    context: str
    order_price: float
    exec_price: float
    slippage_pct: float
    side: str = ""
    order_type: str = ""
    exec_time_ms: int = 0


def compute_slippage_pct(order_price: float, exec_price: float) -> float:
    """Slippage absoluto em % entre preço ordenado e preço executado."""
    if order_price <= 0 or exec_price <= 0:
        return 0.0
    return abs(exec_price - order_price) / order_price * 100.0


def detect_slippage(
    *,
    symbol: str,
    order_price: float,
    exec_price: float,
    context: str,
    side: str = "",
    order_type: str = "",
    exec_time_ms: int = 0,
    threshold_pct: float = SLIPPAGE_ALERT_THRESHOLD_PCT,
) -> SlippageEvent | None:
    """Retorna evento se slippage >= threshold."""
    slip = compute_slippage_pct(order_price, exec_price)
    if slip < threshold_pct:
        return None
    return SlippageEvent(
        symbol=symbol,
        context=context,
        order_price=order_price,
        exec_price=exec_price,
        slippage_pct=round(slip, 4),
        side=side,
        order_type=order_type,
        exec_time_ms=exec_time_ms,
    )


def log_slippage(event: SlippageEvent) -> None:
    logger.warning(
        "SLIPPAGE %.2f%% | %s | %s | ordem=%.8g exec=%.8g | side=%s type=%s",
        event.slippage_pct,
        event.symbol,
        event.context,
        event.order_price,
        event.exec_price,
        event.side or "-",
        event.order_type or "-",
    )


def format_slippage_alert(event: SlippageEvent) -> str:
    pair = event.symbol.replace("/", "").replace("USDT", "USDT")
    if "/" not in event.symbol and pair.endswith("USDT"):
        pair = event.symbol
    return (
        f"⚠️ SLIPPAGE {event.slippage_pct:.2f}%\n"
        f"{pair} | {event.context.upper()}\n"
        f"Ordem: {event.order_price:.8g}\n"
        f"Exec:  {event.exec_price:.8g}"
    )


def scan_execution_rows(
    rows: list[dict[str, Any]],
    *,
    threshold_pct: float = SLIPPAGE_ALERT_THRESHOLD_PCT,
) -> list[SlippageEvent]:
    """Varre fills da API e detecta slippage ordem vs execução."""
    events: list[SlippageEvent] = []
    for row in rows:
        order_price = float(row.get("orderPrice") or 0)
        exec_price = float(row.get("execPrice") or 0)
        stop_type = str(row.get("stopOrderType") or "")
        order_type = str(row.get("orderType") or "")
        context = "execution"
        if stop_type and stop_type.upper() not in ("", "UNKNOWN"):
            context = "stop" if "TAKE" not in stop_type.upper() else "take_profit"
        elif order_type.upper() == "MARKET":
            context = "entry"
        event = detect_slippage(
            symbol=str(row.get("symbol") or ""),
            order_price=order_price,
            exec_price=exec_price,
            context=context,
            side=str(row.get("side") or ""),
            order_type=order_type,
            exec_time_ms=int(row.get("execTime") or 0),
            threshold_pct=threshold_pct,
        )
        if event is not None:
            events.append(event)
    return events


async def notify_slippage_events(
    events: list[SlippageEvent],
    notifier: Any,
) -> None:
    """Envia alertas Telegram para eventos de slippage (dedupe por símbolo+contexto)."""
    if not events or notifier is None or not getattr(notifier, "enabled", False):
        return
    seen: set[tuple[str, str]] = set()
    for event in events:
        key = (event.symbol, event.context)
        if key in seen:
            continue
        seen.add(key)
        log_slippage(event)
        await notifier.send_message(format_slippage_alert(event))
