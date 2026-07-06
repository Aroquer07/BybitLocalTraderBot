"""Testes do endpoint POST /api/backtest (motor isolado, sem rede)."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.config.settings import get_settings
from tools.quant_validator import OhlcvRateLimitError


SAMPLE_RESULT = {
    "ok": True,
    "symbol": "SOL/USDT",
    "timeframe": "5m",
    "days": 7,
    "candles": 2016,
    "period_start": "2026-06-29T18:50:00+00:00",
    "period_end": "2026-07-06T14:35:00+00:00",
    "signals": {"long_entries": 52, "short_entries": 52},
    "strategy": {
        "name": "ema_cross_rsi",
        "ema_fast": 9,
        "ema_slow": 21,
        "rsi_period": 14,
        "rsi_long_min": 50.0,
        "rsi_short_max": 50.0,
        "atr_mult": 1.5,
    },
    "simulation": {"fees": 0.00055, "slippage": 0.001, "initial_cash": 10000.0},
    "metrics": {
        "win_rate_pct": 25.0,
        "profit_factor": 0.288,
        "max_drawdown_pct": 21.49,
        "total_return_pct": -21.08,
        "total_fees_paid": 450.0,
        "total_trades": 73,
        "sharpe_ratio": -32.569,
        "end_value": 7892.0,
    },
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        json.dumps(
            {
                "log_level": "INFO",
                "log_format": "text",
                "trade_journal_path": str(tmp_path / "trades.json"),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "trades.json").write_text(
        json.dumps({"trades": [], "stats": {}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SETTINGS_PATH", str(settings_file))
    get_settings.cache_clear()

    async def _fake_to_thread(fn, *args, **kwargs):
        return SAMPLE_RESULT

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)
    return TestClient(create_app())


def test_backtest_post_success(client):
    resp = client.post(
        "/api/backtest",
        json={"symbol": "SOL/USDT", "timeframe": "5m", "days": 7},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["metrics"]["win_rate_pct"] == 25.0
    assert body["metrics"]["profit_factor"] == 0.288
    assert body["metrics"]["max_drawdown_pct"] == 21.49
    assert body["metrics"]["total_return_pct"] == -21.08
    assert body["metrics"]["total_fees_paid"] == 450.0


def test_backtest_unsupported_timeframe(client):
    resp = client.post(
        "/api/backtest",
        json={"symbol": "SOL/USDT", "timeframe": "2m", "days": 7},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "unsupported_timeframe"


def test_backtest_rate_limit(tmp_path, monkeypatch):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"log_level": "INFO"}), encoding="utf-8")
    monkeypatch.setenv("SETTINGS_PATH", str(settings_file))
    get_settings.cache_clear()

    async def _raise_rate_limit(fn, *args, **kwargs):
        raise OhlcvRateLimitError("rate limited")

    monkeypatch.setattr(asyncio, "to_thread", _raise_rate_limit)
    client = TestClient(create_app())

    resp = client.post("/api/backtest", json={"symbol": "SOL/USDT", "days": 7})
    assert resp.status_code == 429
    assert resp.json()["detail"]["error"] == "rate_limit"
