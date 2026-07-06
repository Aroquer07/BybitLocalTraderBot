"""Lista e serve scripts Pine de indicators/."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

router = APIRouter(prefix="/indicators", tags=["indicators"])

_INDICATORS_DIR = Path(__file__).resolve().parents[3] / "indicators"


@router.get("/pine")
def list_pine_indicators() -> dict:
    files: list[dict[str, str]] = []
    if _INDICATORS_DIR.is_dir():
        for path in sorted(_INDICATORS_DIR.iterdir()):
            if path.is_file() and not path.name.startswith("."):
                files.append({"name": path.name, "path": f"/api/indicators/pine/{path.name}"})
    return {"indicators": files}


@router.get("/pine/{name}", response_class=PlainTextResponse)
def get_pine_indicator(name: str) -> str:
    safe = Path(name).name
    if safe != name or ".." in name:
        raise HTTPException(status_code=400, detail="Nome inválido")
    path = _INDICATORS_DIR / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Indicador não encontrado")
    return path.read_text(encoding="utf-8")
