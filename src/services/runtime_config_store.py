"""Hot-reload de data/settings.json."""

from __future__ import annotations

import json
from pathlib import Path

from src.config.runtime_config import BotRuntimeConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)


def load_runtime_config(path: str | Path) -> BotRuntimeConfig:
    file_path = Path(path)
    if not file_path.is_file():
        logger.warning("settings.json ausente — usando defaults | path=%s", file_path)
        return BotRuntimeConfig()
    raw = json.loads(file_path.read_text(encoding="utf-8"))
    return BotRuntimeConfig.model_validate(raw)


class RuntimeConfigStore:
    """Recarrega settings.json quando o arquivo muda."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._config = BotRuntimeConfig()
        self._mtime: float | None = None
        self._last_reload_error: str | None = None
        self._load_initial()

    @property
    def path(self) -> str:
        return self._path

    @property
    def current(self) -> BotRuntimeConfig:
        return self._config

    def _load_initial(self) -> None:
        file_path = Path(self._path)
        if not file_path.is_file():
            return
        try:
            self._config = load_runtime_config(file_path)
            self._mtime = file_path.stat().st_mtime
        except Exception:
            logger.exception(
                "settings.json inválido no startup — usando defaults | path=%s",
                self._path,
            )
            self._config = BotRuntimeConfig()
            self._mtime = file_path.stat().st_mtime

    def reload(self) -> BotRuntimeConfig:
        file_path = Path(self._path)
        if not file_path.is_file():
            return self._config
        mtime = file_path.stat().st_mtime
        if self._mtime is not None and mtime == self._mtime:
            return self._config
        try:
            loaded = load_runtime_config(file_path)
        except Exception as exc:
            msg = str(exc).split("\n", 1)[0]
            if msg != self._last_reload_error:
                logger.warning(
                    "settings.json inválido — mantendo config anterior | %s",
                    msg,
                )
                self._last_reload_error = msg
            self._mtime = mtime
            return self._config
        self._last_reload_error = None
        if loaded.model_dump() != self._config.model_dump():
            logger.info("settings.json atualizado | path=%s", self._path)
            self._config = loaded
        self._mtime = mtime
        return self._config
