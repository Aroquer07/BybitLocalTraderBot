"""FastAPI application for the BybitBot dashboard."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from src.api.middleware.admin_auth import AdminAuthMiddleware
from src.api.routes import (
    account_router,
    analysis_router,
    auth_router,
    indicators_router,
    learning_router,
    settings_router,
    status_router,
    trades_router,
    watchlist_router,
)
from src.api.services import dashboard_data


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="BybitBot Dashboard API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
        allow_origin_regex=r"https://.*\.ngrok(-free)?\.(app|dev)|https://.*\.ngrok\.io",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AdminAuthMiddleware)

    app.include_router(auth_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(status_router, prefix="/api")
    app.include_router(trades_router, prefix="/api")
    app.include_router(learning_router, prefix="/api")
    app.include_router(analysis_router, prefix="/api")
    app.include_router(account_router, prefix="/api")
    app.include_router(watchlist_router, prefix="/api")
    app.include_router(indicators_router, prefix="/api")

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        async def stream():
            last_version = ""
            while True:
                version = dashboard_data.snapshot_version()
                if version != last_version:
                    payload = {
                        "type": "update",
                        "status": dashboard_data.get_bot_status(),
                        "stats": dashboard_data.get_trades_payload().get("stats", {}),
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    last_version = version
                await asyncio.sleep(2)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    return app


app = create_app()
