from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.api.services import dashboard_data

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistBody(BaseModel):
    symbols: list[str] = Field(default_factory=list)


@router.get("")
def get_watchlist() -> dict:
    return dashboard_data.get_watchlist()


@router.get("/breakout")
async def get_breakout_outlook(limit: int = 25) -> dict:
    return await dashboard_data.get_breakout_outlook(limit=limit)


@router.put("")
def put_watchlist(body: WatchlistBody) -> dict:
    return dashboard_data.save_watchlist(body.symbols)
