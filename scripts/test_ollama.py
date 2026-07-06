"""Testa Ollama: lista modelos e inferência JSON mínima (think=false)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ollama

from src.config.settings import get_settings
from src.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)


def ok(msg: str) -> None:
    print(f"  OK  {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL  {msg}")


async def main() -> int:
    settings = get_settings()
    setup_logging()
    host = settings.ollama_host
    model = settings.ollama_model
    print(f"Ollama host: {host}")
    print(f"OLLAMA_MODEL (.env): {model}")
    print(f"OLLAMA_KEEP_ALIVE: {settings.ollama_keep_alive}")

    client = ollama.AsyncClient(host=host)
    try:
        listed = await client.list()
    except Exception as exc:
        fail(f"Não conectou em {host}: {exc}")
        print("Dica: inicie o Ollama (app na bandeja ou: ollama serve)")
        return 1

    names = [m.model for m in listed.models]
    if not names:
        fail("Nenhum modelo instalado. Ex.: ollama pull qwen3:8b")
        return 1

    print("Modelos instalados:")
    for name in names:
        mark = " <-- .env" if name == model or name.split(":")[0] == model.split(":")[0] else ""
        print(f"  - {name}{mark}")

    if model not in names and not any(n.startswith(model + ":") for n in names):
        fail(f"OLLAMA_MODEL={model!r} não está na lista. Ajuste o .env.")
        return 1

    use_model = model if model in names else next(n for n in names if n.startswith(model + ":"))

    try:
        response = await asyncio.wait_for(
            client.chat(
                model=use_model,
                messages=[
                    {
                        "role": "user",
                        "content": 'Responda só JSON: {"approved": false, "confidence": 0.0} /no_think',
                    }
                ],
                format="json",
                think=False,
                keep_alive=settings.ollama_keep_alive,
            ),
            timeout=settings.ollama_timeout_seconds,
        )
        raw = response["message"]["content"]
        thinking = response["message"].get("thinking")
        if thinking:
            fail(f"Thinking mode ativo (len={len(thinking)}). Esperado think=false.")
            return 1
        ok("Thinking desabilitado (sem campo thinking na resposta)")

        parsed = json.loads(raw)
        ok(f"JSON válido: keys={list(parsed.keys())}")
    except Exception as exc:
        fail(f"Inferência: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
