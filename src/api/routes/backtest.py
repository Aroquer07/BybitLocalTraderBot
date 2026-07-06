"""Rota isolada de backtest vetorial — não toca execução ao vivo."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from tools.quant_validator import (
    OhlcvFetchError,
    OhlcvRateLimitError,
    QuantBacktester,
    SUPPORTED_TIMEFRAMES,
)

router = APIRouter(prefix="/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    symbol: str = Field(default="SOL/USDT", min_length=3, max_length=32)
    timeframe: str = Field(default="5m")
    days: int = Field(default=30, ge=1, le=90)
    initial_cash: float = Field(default=10_000.0, gt=0, le=10_000_000)


@router.post("")
async def run_backtest(payload: BacktestRequest) -> dict:
    """
    Dispara backtest vetorial em thread pool (CPU-bound).

    Não bloqueia o event loop do FastAPI nem aciona ExchangeClient do bot.
    """
    tf = payload.timeframe.strip().lower()
    if tf not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unsupported_timeframe",
                "message": f"Timeframe '{payload.timeframe}' não suportado.",
                "supported": sorted(SUPPORTED_TIMEFRAMES),
            },
        )

    backtester = QuantBacktester(initial_cash=payload.initial_cash)

    try:
        return await asyncio.to_thread(
            backtester.run,
            payload.symbol,
            timeframe=tf,
            days=payload.days,
            initial_cash=payload.initial_cash,
        )
    except OhlcvRateLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limit",
                "message": str(exc),
            },
        ) from exc
    except OhlcvFetchError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "ohlcv_fetch_failed",
                "message": str(exc),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_request",
                "message": str(exc),
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "backtest_failed",
                "message": str(exc),
            },
        ) from exc
