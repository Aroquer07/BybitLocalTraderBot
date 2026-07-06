"""Base reutilizável para módulos de indicador combináveis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

Direction = Literal["LONG", "SHORT"]
Regime = Literal["trend", "range", "unknown"]


@dataclass(frozen=True)
class ModuleResult:
    """Saída de um módulo individual."""

    name: str
    direction: Direction | None
    confidence: float
    triggered: bool
    reason: str
    regime: Regime = "unknown"
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profits: tuple[float, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CombinedSignal:
    """Sinal final após combinar módulos + alinhamento com screener."""

    direction: Direction
    entry_price: float
    stop_loss: float
    take_profits: tuple[float, float, float, float]
    confidence: float
    regime: Regime
    modules: tuple[str, ...]
    summary: str


class IndicatorModule(Protocol):
    """Contrato para plugar novos indicadores."""

    name: str

    def evaluate(self, ohlcv: list[list[float]], **kwargs) -> ModuleResult: ...
