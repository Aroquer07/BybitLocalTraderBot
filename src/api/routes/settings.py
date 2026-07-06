from fastapi import APIRouter

from src.api.services import dashboard_data

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def get_settings() -> dict:
    return dashboard_data.get_settings_payload()


@router.put("")
def put_settings(payload: dict) -> dict:
    return dashboard_data.save_settings_payload(payload)
