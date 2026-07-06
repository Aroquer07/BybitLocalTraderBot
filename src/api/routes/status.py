from fastapi import APIRouter

from src.api.services import dashboard_data

router = APIRouter(prefix="/status", tags=["status"])


@router.get("")
def get_status() -> dict:
    return dashboard_data.get_bot_status()


@router.get("/logs")
def get_logs(limit: int = 100) -> dict:
    limit = max(10, min(limit, 500))
    return {"lines": dashboard_data.tail_log(limit)}
