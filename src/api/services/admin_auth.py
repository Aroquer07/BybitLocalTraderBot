"""Admin único — primeira conta Google via ngrok OAuth vira admin permanente."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.api.services.dashboard_data import project_root

_ADMIN_FILE = project_root() / "data" / "admin.json"


def _load() -> dict[str, Any]:
    if not _ADMIN_FILE.is_file():
        return {}
    try:
        return json.loads(_ADMIN_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict[str, Any]) -> None:
    _ADMIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ADMIN_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_admin_email() -> str | None:
    email = _load().get("email")
    if not email:
        return None
    return str(email).strip().lower()


def set_admin_email(email: str) -> dict[str, Any]:
    normalized = email.strip().lower()
    existing = get_admin_email()
    if existing and existing != normalized:
        raise ValueError("Admin já definido — apenas a conta original pode acessar.")
    payload = {
        "email": normalized,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": "google",
    }
    _save(payload)
    return payload


def get_admin_info() -> dict[str, Any]:
    data = _load()
    if not data.get("email"):
        return {"configured": False, "email": None, "created_at": None}
    return {
        "configured": True,
        "email": data.get("email"),
        "created_at": data.get("created_at"),
        "provider": data.get("provider", "google"),
    }


def is_allowed_email(email: str | None) -> bool:
    if not email:
        return False
    admin = get_admin_email()
    if admin is None:
        return True
    return email.strip().lower() == admin
