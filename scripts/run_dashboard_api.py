"""Run the dashboard API server (uvicorn)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_PID_FILE = ROOT / ".run" / "api.pid"


def _write_pid() -> None:
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()), encoding="utf-8")


def main() -> None:
    import uvicorn

    from src.api.app import app

    host = os.environ.get("DASHBOARD_API_HOST", "127.0.0.1")
    port = int(os.environ.get("DASHBOARD_API_PORT", "8765"))
    _write_pid()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
