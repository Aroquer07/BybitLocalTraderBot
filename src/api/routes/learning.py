from fastapi import APIRouter

from src.api.services import dashboard_data

router = APIRouter(prefix="/learning", tags=["learning"])


@router.get("")
def get_learning() -> dict:
    return dashboard_data.get_learning_payload()
