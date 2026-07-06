"""Tests for dashboard API endpoints."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.services import dashboard_data
from src.config.settings import get_settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        json.dumps(
            {
                "log_level": "INFO",
                "log_format": "text",
                "trade_journal_path": str(tmp_path / "trades.json"),
                "learning": {"rejections_path": str(tmp_path / "rejections.json")},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "trades.json").write_text(
        json.dumps({"trades": [], "stats": {"total_trades": 0}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SETTINGS_PATH", str(settings_file))
    get_settings.cache_clear()
    from src.config.settings import Settings

    def _settings():
        return Settings(settings_path=str(settings_file))

    monkeypatch.setattr("src.api.services.dashboard_data.get_settings", _settings)
    monkeypatch.setattr("src.api.services.dashboard_data._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "src.api.services.dashboard_data._PID_FILE", tmp_path / ".run" / "bot.pid"
    )
    monkeypatch.setattr(
        "src.api.services.dashboard_data._LOG_FILE", tmp_path / ".run" / "bot.log"
    )
    return TestClient(create_app())


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_settings_roundtrip(client, tmp_path):
    get_resp = client.get("/api/settings")
    assert get_resp.status_code == 200
    payload = get_resp.json()
    payload["log_level"] = "DEBUG"
    put_resp = client.put("/api/settings", json=payload)
    assert put_resp.status_code == 200
    assert put_resp.json()["log_level"] == "DEBUG"


def test_status_and_trades(client):
    assert client.get("/api/status").status_code == 200
    trades = client.get("/api/trades")
    assert trades.status_code == 200
    assert "trades" in trades.json()


def test_learning_and_analysis(client):
    assert client.get("/api/learning").status_code == 200
    resp = client.get("/api/analysis")
    assert resp.status_code == 200
    body = resp.json()
    assert "rejections" in body
    assert "approvals" in body


def test_strategy_ranking(client):
    resp = client.get("/api/trades/strategies/ranking")
    assert resp.status_code == 200
    assert "ranking" in resp.json()


def test_pid_alive_current_process():
    assert dashboard_data._pid_alive(os.getpid()) is True


def test_pid_alive_invalid_pid():
    assert dashboard_data._pid_alive(0) is False
    assert dashboard_data._pid_alive(-1) is False
    assert dashboard_data._pid_alive(999_999_999) is False


def test_status_running_with_live_pid_file(client, tmp_path, monkeypatch):
    pid_file = tmp_path / ".run" / "bot.pid"
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    monkeypatch.setattr(dashboard_data, "_PID_FILE", pid_file)

    status = dashboard_data.get_bot_status()
    assert status["running"] is True
    assert status["status_source"] == "pid_file"
    assert status["pid"] == os.getpid()


def test_status_running_via_log_heartbeat(client, tmp_path, monkeypatch):
    pid_file = tmp_path / ".run" / "bot.pid"
    log_file = tmp_path / ".run" / "bot.log"
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text("999999999", encoding="utf-8")
    log_file.write_text("2026-01-01 | INFO | heartbeat\n", encoding="utf-8")
    monkeypatch.setattr(dashboard_data, "_PID_FILE", pid_file)
    monkeypatch.setattr(dashboard_data, "_LOG_FILE", log_file)
    monkeypatch.setattr(dashboard_data, "_discover_bot_pid", lambda: None)

    status = dashboard_data.get_bot_status()
    assert status["running"] is True
    assert status["status_source"] == "log_heartbeat"


def test_status_stopped_when_no_signals(client, tmp_path, monkeypatch):
    pid_file = tmp_path / ".run" / "bot.pid"
    log_file = tmp_path / ".run" / "bot.log"
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text("999999999", encoding="utf-8")
    log_file.write_text("stale\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(log_file, (old, old))
    monkeypatch.setattr(dashboard_data, "_PID_FILE", pid_file)
    monkeypatch.setattr(dashboard_data, "_LOG_FILE", log_file)
    monkeypatch.setattr(dashboard_data, "_discover_bot_pid", lambda: None)

    status = dashboard_data.get_bot_status()
    assert status["running"] is False
    assert status["status_source"] == "stopped"


def test_breakout_outlook_empty_watchlist(client, monkeypatch):
    async def _empty_outlook(limit: int = 25):
        return {
            "timeframe": "5m",
            "min_probability_pct": 60.0,
            "outlooks": [],
            "error": None,
            "updated_at": "2026-01-01T00:00:00+00:00",
        }

    monkeypatch.setattr(dashboard_data, "get_breakout_outlook", _empty_outlook)
    resp = client.get("/api/watchlist/breakout")
    assert resp.status_code == 200
    body = resp.json()
    assert body["timeframe"] == "5m"
    assert body["outlooks"] == []
