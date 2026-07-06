from fastapi import APIRouter

from src.api.services import dashboard_data

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("")
def get_analysis() -> dict:
    return dashboard_data.get_analysis_payload()
