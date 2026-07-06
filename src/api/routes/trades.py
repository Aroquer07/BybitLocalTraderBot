from fastapi import APIRouter

from src.api.services import dashboard_data

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("")
def get_trades() -> dict:
    return dashboard_data.get_trades_payload()


@router.get("/strategies/ranking")
def get_strategy_ranking() -> dict:
    return {"ranking": dashboard_data.get_strategy_ranking()}


@router.get("/charts")
def get_charts() -> dict:
    return dashboard_data.get_chart_payload()


@router.get("/exchange-pnl")
async def get_exchange_pnl(period: str = "week") -> dict:
    return await dashboard_data.get_exchange_pnl_payload(period)
