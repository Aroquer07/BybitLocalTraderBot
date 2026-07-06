"""Carrega watchlist do scanner a partir de arquivo local (hot-reload)."""

from __future__ import annotations

from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)


def normalize_watchlist_symbols(symbols: list[str]) -> list[str]:
    """Normaliza tickers para par CCXT XXX/USDT (deduplica mantendo ordem)."""
    seen: set[str] = set()
    normalized: list[str] = []
    for sym in symbols:
        s = sym.upper().replace("#", "").strip()
        if ":" in s:
            s = s.rsplit(":", 1)[0]
        if not s or s.startswith("#"):
            continue
        if "/" in s:
            base = s.split("/", 1)[0].strip()
        elif s.endswith("USDT") and len(s) > 4:
            base = s[:-4]
        else:
            base = s
        if not base:
            continue
        pair = f"{base}/USDT"
        if pair in seen:
            continue
        seen.add(pair)
        normalized.append(pair)
    return normalized


def parse_watchlist_text(text: str) -> list[str]:
    """Aceita uma linha por símbolo; vírgulas e comentários (#) são ignorados."""
    raw: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for part in line.split(","):
            part = part.strip()
            if part and not part.startswith("#"):
                raw.append(part)
    return normalize_watchlist_symbols(raw)


def load_watchlist_file(path: str | Path) -> list[str]:
    """Lê watchlist do disco; retorna lista vazia se arquivo não existir."""
    file_path = Path(path)
    if not file_path.is_file():
        logger.warning("Watchlist não encontrada | path=%s", file_path)
        return []
    text = file_path.read_text(encoding="utf-8")
    return parse_watchlist_text(text)


class WatchlistStore:
    """Mantém watchlist em memória e recarrega do arquivo quando muda."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._symbols: list[str] = []

    @property
    def path(self) -> str:
        return self._path

    @property
    def symbols(self) -> list[str]:
        return list(self._symbols)

    def reload(self) -> list[str]:
        """Recarrega arquivo; loga apenas se a lista mudou."""
        loaded = load_watchlist_file(self._path)
        if loaded != self._symbols:
            logger.info(
                "Watchlist atualizada | path=%s | count=%d | symbols=%s",
                self._path,
                len(loaded),
                loaded,
            )
            self._symbols = loaded
        return self.symbols
