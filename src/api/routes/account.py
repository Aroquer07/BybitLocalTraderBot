from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.api.services import dashboard_data

router = APIRouter(prefix="/account", tags=["account"])


class AccountModeBody(BaseModel):
    mode: str = Field(description="testnet | demo | live")


@router.get("")
async def get_account() -> dict:
    return await dashboard_data.get_account_info()


@router.put("/mode")
def put_account_mode(body: AccountModeBody) -> dict:
    try:
        return dashboard_data.update_account_mode(body.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
