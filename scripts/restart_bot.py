"""Reinicia o BybitBot (mata main.py do repo e inicia de novo)."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _kill_existing() -> list[int]:
    killed: list[int] = []
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    f"$root = '{str(ROOT).replace(chr(92), chr(92)*2)}'; "
                    "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
                    "Where-Object { $_.CommandLine -like ('*' + $root + '*main.py*') } | "
                    "Select-Object -ExpandProperty ProcessId"
                ),
            ],
            text=True,
            errors="ignore",
        )
        for line in out.splitlines():
            line = line.strip()
            if line.isdigit():
                pid = int(line)
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True,
                )
                killed.append(pid)
                print(f"Parado PID {pid}")
    except subprocess.CalledProcessError:
        pass
    return killed


def main() -> None:
    killed = _kill_existing()
    if not killed:
        print("Nenhum main.py anterior encontrado.")
    time.sleep(3)
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = Path(sys.executable)
    log = ROOT / ".run" / "bot.log"
    log.parent.mkdir(exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write("\n--- restart ---\n")
        proc = subprocess.Popen(
            [str(python), "-X", "utf8", "main.py"],
            cwd=str(ROOT),
            stdout=fh,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    print(f"BybitBot iniciado PID {proc.pid}")
    print(f"Log: {log}")


if __name__ == "__main__":
    main()
