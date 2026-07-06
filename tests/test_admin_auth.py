"""Tests for Google admin auth via ngrok OAuth headers."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.services import admin_auth
from src.config.settings import get_settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        json.dumps(
            {
                "log_level": "INFO",
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
    monkeypatch.setattr(admin_auth, "_ADMIN_FILE", tmp_path / "admin.json")
    monkeypatch.setattr(
        "src.api.services.dashboard_data._PROJECT_ROOT",
        tmp_path,
    )
    return TestClient(create_app())


def test_local_access_without_ngrok_header(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ngrok_auth"] is False


def test_first_ngrok_login_becomes_admin(client, tmp_path):
    admin_auth._ADMIN_FILE.unlink(missing_ok=True)
    headers = {"Ngrok-Auth-User-Email": "admin@gmail.com"}
    resp = client.get("/api/status", headers=headers)
    assert resp.status_code == 200
    assert admin_auth.get_admin_email() == "admin@gmail.com"

    me = client.get("/api/auth/me", headers=headers).json()
    assert me["is_admin"] is True
    assert me["admin_email"] == "admin@gmail.com"


def test_second_account_denied(client):
    admin_auth.set_admin_email("owner@gmail.com")
    resp = client.get("/api/status", headers={"Ngrok-Auth-User-Email": "other@gmail.com"})
    assert resp.status_code == 403


def test_admin_can_access(client):
    admin_auth.set_admin_email("owner@gmail.com")
    resp = client.get("/api/status", headers={"Ngrok-Auth-User-Email": "owner@gmail.com"})
    assert resp.status_code == 200
