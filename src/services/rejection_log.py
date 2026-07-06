"""Log de trades rejeitados — evita viés de survivorship no aprendizado."""

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


class StoredRejection(BaseModel):
    """Decisão rejeitada com contexto para calibração."""

    id: str
    symbol: str
    direction: TradeDirection | None = None
    source: TradeSource
    stage: str = Field(description="imba | llm | pwin | pattern | filter")
    reason: str
    strategy: str = Field(default="", description="entry_strategy no momento da rejeição")
    rejected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    llm_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    predicted_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    probability_features: dict[str, Any] | None = None
    chart_snapshot: dict[str, Any] | None = None
    notes: str = ""


class RejectionLog:
    """Persistência JSON de rejeições (hot-reload path via settings)."""

    def __init__(self, runtime_store: RuntimeConfigStore) -> None:
        self._runtime = runtime_store

    @property
    def _path(self) -> Path:
        runtime = self._runtime.reload()
        path = Path(runtime.learning.rejections_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _load(self) -> list[StoredRejection]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return [StoredRejection.model_validate(r) for r in raw.get("rejections", [])]
        except (json.JSONDecodeError, OSError, ValueError):
            logger.exception("Erro ao carregar rejection log")
            return []

    def _save(self, items: list[StoredRejection]) -> None:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "rejections": [r.model_dump(mode="json") for r in items],
            "total": len(items),
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_all(self) -> list[StoredRejection]:
        return self._load()

    def record(
        self,
        *,
        symbol: str,
        source: TradeSource,
        stage: str,
        reason: str,
        strategy: str = "",
        direction: TradeDirection | None = None,
        llm_confidence: float | None = None,
        predicted_probability: float | None = None,
        probability_features: dict[str, Any] | None = None,
        chart_snapshot: dict[str, Any] | None = None,
        notes: str = "",
    ) -> StoredRejection:
        entry = StoredRejection(
            id=str(uuid.uuid4()),
            symbol=symbol.upper(),
            direction=direction,
            source=source,
            stage=stage,
            reason=reason[:500],
            strategy=strategy[:40],
            llm_confidence=llm_confidence,
            predicted_probability=predicted_probability,
            probability_features=probability_features,
            chart_snapshot=chart_snapshot,
            notes=notes[:300],
        )
        items = self._load()
        items.append(entry)
        # Mantém últimas 500 entradas
        if len(items) > 500:
            items = items[-500:]
        self._save(items)
        logger.info(
            "Rejeição registrada | %s | %s | stage=%s | %s",
            symbol,
            source.value,
            stage,
            reason[:80],
        )
        return entry


def record_rejection(
    runtime_store: RuntimeConfigStore,
    *,
    ohlcv_by_tf: dict[str, list[list[float]]] | None = None,
    levels: dict[str, Any] | None = None,
    chart_snapshot: dict[str, Any] | None = None,
    indicators_config: IndicatorModulesConfig | None = None,
    module_results: list[ModuleResult] | None = None,
    **kwargs: Any,
) -> None:
    """Grava rejeição se learning.log_rejections estiver ativo."""
    runtime = runtime_store.reload()
    if not runtime.learning.enabled or not runtime.learning.log_rejections:
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
    RejectionLog(runtime_store).record(chart_snapshot=chart_snapshot, **kwargs)
