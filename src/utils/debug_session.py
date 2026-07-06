"""NDJSON debug logger for Cursor debug sessions."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_SESSION_ID = "bad336"
_LOG_PATH = Path(__file__).resolve().parents[2] / "debug-bad336.log"


def debug_log(
    *,
    location: str,
    message: str,
    data: dict[str, Any] | None = None,
    hypothesis_id: str = "",
    run_id: str = "pre-fix",
) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": _SESSION_ID,
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        with _LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion
