"""Log de setups aprovados — replay no dashboard com indicadores."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.config.strategy_config import IndicatorModulesConfig
from src.models.schemas import TradeDirection, TradeSource
from src.services.runtime_config_store import RuntimeConfigStore
from src.strategies.indicator_modules.base import ModuleResult
from src.utils.logger import get_logger

logger = get_logger(__name__)


class StoredApproval(BaseModel):
    """Setup aprovado pelo scanner/brain antes da execução."""

    id: str
    symbol: str
    direction: TradeDirection
    source: TradeSource
    strategy: str = ""
    summary: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    approved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    predicted_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    probability_features: dict[str, Any] | None = None
    chart_snapshot: dict[str, Any] | None = None
    notes: str = ""


class ApprovalLog:
    def __init__(self, runtime_store: RuntimeConfigStore) -> None:
        self._runtime = runtime_store

    @property
    def _path(self) -> Path:
        runtime = self._runtime.reload()
        path = Path(runtime.learning.approvals_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _load(self) -> list[StoredApproval]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return [StoredApproval.model_validate(a) for a in raw.get("approvals", [])]
        except (json.JSONDecodeError, OSError, ValueError):
            logger.exception("Erro ao carregar approval log")
            return []

    def _save(self, items: list[StoredApproval]) -> None:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "approvals": [a.model_dump(mode="json") for a in items],
            "total": len(items),
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_all(self) -> list[StoredApproval]:
        return self._load()

    def record(
        self,
        *,
        symbol: str,
        source: TradeSource,
        direction: TradeDirection,
        strategy: str = "",
        summary: str = "",
        confidence: float = 0.0,
        predicted_probability: float | None = None,
        probability_features: dict[str, Any] | None = None,
        chart_snapshot: dict[str, Any] | None = None,
        notes: str = "",
    ) -> StoredApproval:
        entry = StoredApproval(
            id=str(uuid.uuid4()),
            symbol=symbol.upper(),
            direction=direction,
            source=source,
            strategy=strategy[:80],
            summary=summary[:500],
            confidence=confidence,
            predicted_probability=predicted_probability,
            probability_features=probability_features,
            chart_snapshot=chart_snapshot,
            notes=notes[:300],
        )
        items = self._load()
        items.append(entry)
        if len(items) > 500:
            items = items[-500:]
        self._save(items)
        logger.info("Aprovação registrada | %s | %s | %s", symbol, source.value, strategy)
        return entry


def record_approval(
    runtime_store: RuntimeConfigStore,
    *,
    ohlcv_by_tf: dict[str, list[list[float]]] | None = None,
    levels: dict[str, Any] | None = None,
    chart_snapshot: dict[str, Any] | None = None,
    indicators_config: IndicatorModulesConfig | None = None,
    module_results: list[ModuleResult] | None = None,
    **kwargs: Any,
) -> None:
    """Grava aprovação se learning.log_approvals estiver ativo."""
    runtime = runtime_store.reload()
    if not runtime.learning.enabled or not runtime.learning.log_approvals:
        return
    if indicators_config is None:
        indicators_config = runtime.strategies.scanner.indicators
    entry_strategy = (
        kwargs.pop("entry_strategy", None)
        or kwargs.get("strategy")
        or runtime.strategies.scanner.entry_strategy
    )
    if chart_snapshot is None and ohlcv_by_tf:
        from src.services.chart_snapshot import build_chart_snapshot

        chart_snapshot = build_chart_snapshot(
            ohlcv_by_tf,
            levels=levels,
            config=indicators_config,
            module_results=module_results,
            entry_strategy=entry_strategy,
        )
    if not kwargs.get("strategy"):
        kwargs["strategy"] = entry_strategy
    ApprovalLog(runtime_store).record(chart_snapshot=chart_snapshot, **kwargs)
