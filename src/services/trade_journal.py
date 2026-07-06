"""Persistência de trades para histórico win/loss."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.services.pnl_reporter import realized_pnl_usd
from src.services.trade_learning import log_trade_outcome
from src.services.runtime_config_store import RuntimeConfigStore
from src.models.schemas import (
    StoredTrade,
    TradeDirection,
    TradeSource,
    TradeStatus,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TradeJournal:
    """Armazena trades em JSON para análise posterior de win/loss."""

    def __init__(self, runtime_store: RuntimeConfigStore) -> None:
        self._runtime = runtime_store

    @property
    def _path(self) -> Path:
        path = Path(self._runtime.reload().trade_journal_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _load(self) -> list[StoredTrade]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return [StoredTrade.model_validate(t) for t in raw.get("trades", [])]
        except (json.JSONDecodeError, OSError, ValueError):
            logger.exception("Erro ao carregar trade journal — iniciando vazio")
            return []

    def _save(self, trades: list[StoredTrade]) -> None:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "trades": [t.model_dump(mode="json") for t in trades],
            "stats": self._compute_stats(trades),
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _compute_stats(trades: list[StoredTrade]) -> dict[str, Any]:
        closed = [t for t in trades if t.status == TradeStatus.CLOSED]
        wins = [t for t in closed if (t.pnl_pct or 0) > 0]
        losses = [t for t in closed if (t.pnl_pct or 0) <= 0]
        total = len(closed)
        return {
            "total_trades": len(trades),
            "open_trades": sum(1 for t in trades if t.status == TradeStatus.OPEN),
            "closed_trades": total,
            "wins": len(wins),
            "losses": len(losses),
            "winrate_pct": round(len(wins) / total * 100, 2) if total else 0.0,
            "total_pnl_pct": round(sum(t.pnl_pct or 0 for t in closed), 4),
            "total_pnl_usd": round(sum(realized_pnl_usd(t) for t in closed), 2),
        }

    def list_open(self) -> list[StoredTrade]:
        return [t for t in self._load() if t.status == TradeStatus.OPEN]

    def list_closed(self) -> list[StoredTrade]:
        return [t for t in self._load() if t.status == TradeStatus.CLOSED]

    def count_open(self) -> int:
        return len(self.list_open())

    def get_stats(self) -> dict[str, Any]:
        return self._compute_stats(self._load())

    def has_open_position(self, symbol: str) -> bool:
        sym = symbol.upper()
        return any(t.symbol.upper() == sym and t.status == TradeStatus.OPEN for t in self._load())

    def record_open(
        self,
        *,
        symbol: str,
        direction: TradeDirection,
        source: TradeSource,
        entry_price: float,
        stop_loss: float,
        take_profits: list[float],
        confidence: float,
        leverage: int,
        amount: float | None = None,
        entry_order_id: str | None = None,
        sl_order_id: str | None = None,
        telegram_message_id: int | None = None,
        notes: str = "",
        probability_features: dict[str, Any] | None = None,
    ) -> StoredTrade:
        trade = StoredTrade(
            id=str(uuid.uuid4()),
            symbol=symbol.upper(),
            direction=direction,
            source=source,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profits=take_profits,
            confidence=confidence,
            leverage=leverage,
            amount=amount,
            entry_order_id=entry_order_id,
            sl_order_id=sl_order_id,
            telegram_message_id=telegram_message_id,
            notes=notes,
            probability_features=probability_features,
        )
        trades = self._load()
        trades.append(trade)
        self._save(trades)
        logger.info(
            "Trade registrado | id=%s | %s %s | source=%s",
            trade.id,
            direction.value,
            symbol,
            source.value,
        )
        return trade

    def close_trade(
        self,
        trade_id: str,
        *,
        exit_price: float,
        pnl_pct: float,
        reason: str,
    ) -> StoredTrade | None:
        trades = self._load()
        for i, t in enumerate(trades):
            if t.id != trade_id:
                continue
            updated = t.model_copy(
                update={
                    "status": TradeStatus.CLOSED,
                    "closed_at": datetime.now(timezone.utc),
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct,
                    "close_reason": reason,
                }
            )
            trades[i] = updated
            self._save(trades)
            logger.info(
                "Trade fechado | id=%s | pnl=%.2f%% | %s",
                trade_id,
                pnl_pct,
                reason,
            )
            log_trade_outcome(updated)
            return updated
        return None

    def close_by_symbol_if_flat(
        self,
        symbol: str,
        last_price: float,
    ) -> StoredTrade | None:
        """Marca trade como fechado quando posição não existe mais na exchange."""
        sym = symbol.upper()
        for trade in self.list_open():
            if trade.symbol != sym:
                continue
            if trade.direction == TradeDirection.LONG:
                pnl = (last_price - trade.entry_price) / trade.entry_price * 100
            else:
                pnl = (trade.entry_price - last_price) / trade.entry_price * 100
            return self.close_trade(
                trade.id,
                exit_price=last_price,
                pnl_pct=round(pnl, 4),
                reason="position_closed_on_exchange",
            )
        return None
