"""Testes de watchlist local (arquivo + normalização)."""

from __future__ import annotations

from pathlib import Path

from src.config.runtime_config import BotRuntimeConfig
from src.services.watchlist_loader import (
    WatchlistStore,
    load_watchlist_file,
    normalize_watchlist_symbols,
    parse_watchlist_text,
)


class TestMaxConcurrentTrades:
    def test_demo_mode_allows_ten(self) -> None:
        cfg = BotRuntimeConfig(risk={"max_concurrent_trades": 3})
        assert cfg.effective_max_concurrent_trades("demo") == 10

    def test_live_mode_uses_config(self) -> None:
        cfg = BotRuntimeConfig(risk={"max_concurrent_trades": 3})
        assert cfg.effective_max_concurrent_trades("live") == 3


class TestWatchlistNormalization:
    def test_ticker_only(self) -> None:
        assert normalize_watchlist_symbols(["BTC", "ETH", "SOL"]) == [
            "BTC/USDT",
            "ETH/USDT",
            "SOL/USDT",
        ]

    def test_usdt_suffix(self) -> None:
        assert normalize_watchlist_symbols(["BTCUSDT", "SOLUSDT"]) == [
            "BTC/USDT",
            "SOL/USDT",
        ]

    def test_full_pair(self) -> None:
        assert normalize_watchlist_symbols(["BTC/USDT", "ETH/USDT"]) == [
            "BTC/USDT",
            "ETH/USDT",
        ]

    def test_mixed_formats(self) -> None:
        assert normalize_watchlist_symbols(["BTC", "ETH/USDT", "XRPUSDT"]) == [
            "BTC/USDT",
            "ETH/USDT",
            "XRP/USDT",
        ]

    def test_shib1000(self) -> None:
        assert normalize_watchlist_symbols(["SHIB1000USDT"]) == ["SHIB1000/USDT"]

    def test_linear_swap_suffix(self) -> None:
        assert normalize_watchlist_symbols(["MAGMA/USDT:USDT", "BTC/USDT:USDT"]) == [
            "MAGMA/USDT",
            "BTC/USDT",
        ]


class TestWatchlistFile:
    def test_parse_text_with_comments(self) -> None:
        text = "# favoritos\nHMSTR\nRSR\n# XRP\nXRPUSDT\n"
        assert parse_watchlist_text(text) == [
            "HMSTR/USDT",
            "RSR/USDT",
            "XRP/USDT",
        ]

    def test_load_from_file(self, tmp_path: Path) -> None:
        path = tmp_path / "watchlist.txt"
        path.write_text("BTC\nETHUSDT\n", encoding="utf-8")
        assert load_watchlist_file(path) == ["BTC/USDT", "ETH/USDT"]

    def test_store_reload_detects_changes(self, tmp_path: Path) -> None:
        path = tmp_path / "watchlist.txt"
        path.write_text("BTC\n", encoding="utf-8")
        store = WatchlistStore(str(path))
        assert store.reload() == ["BTC/USDT"]
        path.write_text("BTC\nSOL\n", encoding="utf-8")
        assert store.reload() == ["BTC/USDT", "SOL/USDT"]

    def test_default_watchlist_file_exists(self) -> None:
        symbols = load_watchlist_file("data/watchlist.txt")
        assert len(symbols) == 29
        assert "HMSTR/USDT" in symbols
        assert "SHIB1000/USDT" in symbols
