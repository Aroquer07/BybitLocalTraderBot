"""Configuração centralizada de logging assíncrono-friendly."""

import logging
import sys
from typing import Literal


def setup_logging(
    log_level: str = "INFO",
    log_format: Literal["json", "text"] = "text",
) -> None:
    """Configura o root logger com formato text ou JSON."""
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, log_level))

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, log_level))

    if log_format == "json":
        formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler.setFormatter(formatter)
    root.addHandler(handler)

    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("ccxt").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Retorna logger nomeado para o módulo."""
    return logging.getLogger(name)


class _JsonFormatter(logging.Formatter):
    """Formatter JSON simples para ambientes de produção."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        payload = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)
