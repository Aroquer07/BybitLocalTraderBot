"""Fixtures compartilhadas para testes."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config.runtime_config import BotRuntimeConfig
from src.config.settings import Settings
from src.services.runtime_config_store import RuntimeConfigStore


@pytest.fixture
def env_settings() -> Settings:
    return Settings(
        telegram_api_id=1,
        telegram_api_hash="x",
        telegram_channel_id=1,
        bybit_api_key="k",
        bybit_api_secret="s",
        bybit_mode="demo",
    )


@pytest.fixture
def runtime_config() -> BotRuntimeConfig:
    return BotRuntimeConfig()


@pytest.fixture
def runtime_store(tmp_path: Path) -> RuntimeConfigStore:
    path = tmp_path / "settings.json"
    BotRuntimeConfig().model_dump_json()
    path.write_text(BotRuntimeConfig().model_dump_json(indent=2), encoding="utf-8")
    return RuntimeConfigStore(str(path))
