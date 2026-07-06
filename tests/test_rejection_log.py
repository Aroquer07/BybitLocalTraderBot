"""Testes do log de trades rejeitados."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config.runtime_config import BotRuntimeConfig, LearningConfig
from src.models.schemas import TradeDirection, TradeSource
from src.services.rejection_log import RejectionLog, record_rejection
from src.services.runtime_config_store import RuntimeConfigStore


class _FakeRuntimeStore:
    def __init__(self, config: BotRuntimeConfig, path: Path) -> None:
        self._config = config
        self._path = path

    def reload(self) -> BotRuntimeConfig:
        return self._config


@pytest.fixture
def rejection_setup(tmp_path: Path) -> tuple[_FakeRuntimeStore, Path]:
    rejections_path = tmp_path / "rejections.json"
    config = BotRuntimeConfig(
        learning=LearningConfig(
            enabled=True,
            log_rejections=True,
            rejections_path=str(rejections_path),
        )
    )
    store = _FakeRuntimeStore(config, rejections_path)
    return store, rejections_path


class TestRejectionLog:
    def test_record_persists_entry(self, rejection_setup) -> None:
        store, path = rejection_setup
        log = RejectionLog(store)  # type: ignore[arg-type]
        entry = log.record(
            symbol="ETH/USDT",
            source=TradeSource.SCANNER,
            stage="llm",
            reason="Confluência fraca",
            direction=TradeDirection.LONG,
            llm_confidence=0.55,
        )
        assert entry.symbol == "ETH/USDT"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["total"] == 1
        assert data["rejections"][0]["stage"] == "llm"

    def test_record_rejection_respects_disabled_flag(self, rejection_setup) -> None:
        store, path = rejection_setup
        store._config = BotRuntimeConfig(
            learning=LearningConfig(enabled=True, log_rejections=False)
        )
        record_rejection(
            store,  # type: ignore[arg-type]
            symbol="BTC/USDT",
            source=TradeSource.TELEGRAM,
            stage="filter",
            reason="Fora da watchlist",
        )
        assert not path.exists()
