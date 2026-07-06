"""Testes do analisador IMBA multi-TF e trade journal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config.runtime_config import BotRuntimeConfig
from src.services.runtime_config_store import RuntimeConfigStore
from src.models.schemas import TradeDirection, TradeSource, TradeStatus
from src.services.trade_journal import TradeJournal
from src.strategies.imba_algo import ImbaAlgoConfig
from src.strategies.imba_analyzer import (
    analyze_multi_timeframe,
    build_execution_signal_for_direction,
    pick_execution_levels,
)


def _ohlcv_from_closes(closes: list[float]) -> list[list[float]]:
    rows = []
    for i, close in enumerate(closes):
        rows.append([
            i * 60_000,
            close - 0.5,
            close + 1.0,
            close - 1.0,
            close,
            1000.0,
        ])
    return rows


class TestImbaAnalyzer:
    def test_multi_tf_analysis(self) -> None:
        closes = [100.0] * 25 + [105.0, 110.0, 115.0]
        ohlcv = _ohlcv_from_closes(closes)
        analysis = analyze_multi_timeframe(
            "BTC/USDT",
            {"15m": ohlcv, "5m": ohlcv, "3m": ohlcv},
            ImbaAlgoConfig(sensitivity=1.0),
        )
        assert analysis.symbol == "BTC/USDT"
        assert "15m" in analysis.timeframes
        assert 0.0 <= analysis.confidence_score <= 1.0

    def test_execution_levels_always_from_5m(self) -> None:
        config = ImbaAlgoConfig(sensitivity=1.0)
        base = [100.0] * 25
        ohlcv_15m = _ohlcv_from_closes(base + [120.0, 125.0, 130.0])
        ohlcv_5m = _ohlcv_from_closes(base + [105.0, 108.0, 110.0])
        ohlcv_3m = _ohlcv_from_closes(base + [102.0, 103.0, 104.0])
        by_tf = {"15m": ohlcv_15m, "5m": ohlcv_5m, "3m": ohlcv_3m}
        analysis = analyze_multi_timeframe("BTC/USDT", by_tf, config)
        signal = pick_execution_levels(analysis, config, by_tf, execution_timeframe="5m")
        assert signal is not None
        exec_5m = build_execution_signal_for_direction(
            TradeDirection.LONG, ohlcv_5m, config
        )
        assert exec_5m is not None
        assert signal.entry_price == exec_5m.entry_price
        assert signal.stop_loss == exec_5m.stop_loss
        assert signal.take_profits == exec_5m.take_profits


class TestTradeJournal:
    def test_record_and_stats(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        journal_path = tmp_path / "trades.json"
        cfg = BotRuntimeConfig(trade_journal_path=str(journal_path))
        settings_path.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
        store = RuntimeConfigStore(str(settings_path))
        journal = TradeJournal(store)
        trade = journal.record_open(
            symbol="SOL/USDT",
            direction=TradeDirection.LONG,
            source=TradeSource.SCANNER,
            entry_price=100.0,
            stop_loss=95.0,
            take_profits=[101.0, 102.0, 103.0, 104.0],
            confidence=0.7,
            leverage=15,
        )
        assert journal.count_open() == 1
        journal.close_trade(trade.id, exit_price=102.0, pnl_pct=2.0, reason="tp")
        stats = journal.get_stats()
        assert stats["wins"] == 1
        assert stats["open_trades"] == 0

    def test_persisted_file(self, tmp_path: Path) -> None:
        path = tmp_path / "trades.json"
        settings_path = tmp_path / "settings.json"
        cfg = BotRuntimeConfig(trade_journal_path=str(path))
        settings_path.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
        store = RuntimeConfigStore(str(settings_path))
        TradeJournal(store).record_open(
            symbol="ETH/USDT",
            direction=TradeDirection.SHORT,
            source=TradeSource.TELEGRAM,
            entry_price=2000.0,
            stop_loss=2050.0,
            take_profits=[1980.0, 1960.0, 1940.0, 1920.0],
            confidence=0.92,
            leverage=10,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["trades"]) == 1
        assert data["trades"][0]["status"] == TradeStatus.OPEN.value
