"""Testes de settings.json e hot-reload."""

from __future__ import annotations

import json
from pathlib import Path

from src.config.runtime_config import BotRuntimeConfig
from src.services.runtime_config_store import RuntimeConfigStore


class TestRuntimeConfig:
    def test_unifies_confidence(self) -> None:
        cfg = BotRuntimeConfig()
        assert cfg.confidence.telegram == 0.90
        assert cfg.confidence.scanner == 0.65

    def test_unifies_timeframes(self) -> None:
        cfg = BotRuntimeConfig()
        assert cfg.timeframes.primary == "15m"
        assert cfg.timeframes.execution == "5m"
        assert cfg.timeframes.primary in cfg.timeframes.analysis

    def test_hot_reload_picks_changes(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps({"confidence": {"telegram": 0.85, "scanner": 0.70}}),
            encoding="utf-8",
        )
        store = RuntimeConfigStore(str(path))
        assert store.reload().confidence.telegram == 0.85
        path.write_text(
            json.dumps({"confidence": {"telegram": 0.92, "scanner": 0.80}}),
            encoding="utf-8",
        )
        reloaded = store.reload()
        assert reloaded.confidence.telegram == 0.92
        assert reloaded.confidence.scanner == 0.80
