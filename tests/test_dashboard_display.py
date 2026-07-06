"""UTC offset no payload do dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from src.api.services import dashboard_data


def test_ensure_display_merges_from_file(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"display": {"utc_offset_hours": -3}}),
        encoding="utf-8",
    )
    payload = {"confidence": {"telegram": 0.9, "scanner": 0.65}}
    with patch.object(dashboard_data, "get_settings") as mock_settings:
        mock_settings.return_value.settings_path = str(settings_path)
        merged = dashboard_data._ensure_display_in_payload(payload)
    assert merged["display"]["utc_offset_hours"] == -3


def test_analysis_payload_includes_utc_offset(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "learning": {
                    "rejections_path": str(tmp_path / "rejections.json"),
                    "approvals_path": str(tmp_path / "approvals.json"),
                },
                "display": {"utc_offset_hours": -3},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "rejections.json").write_text('{"rejections": []}', encoding="utf-8")
    (tmp_path / "approvals.json").write_text('{"approvals": []}', encoding="utf-8")

    with patch.object(dashboard_data, "get_settings") as mock_settings:
        mock_settings.return_value.settings_path = str(settings_path)
        payload = dashboard_data.get_analysis_payload()
    assert payload["utc_offset_hours"] == -3.0
