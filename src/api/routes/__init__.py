from src.api.routes.account import router as account_router
from src.api.routes.analysis import router as analysis_router
from src.api.routes.auth import router as auth_router
from src.api.routes.indicators import router as indicators_router
from src.api.routes.learning import router as learning_router
from src.api.routes.settings import router as settings_router
from src.api.routes.status import router as status_router
from src.api.routes.trades import router as trades_router
from src.api.routes.watchlist import router as watchlist_router

__all__ = [
    "account_router",
    "analysis_router",
    "auth_router",
    "indicators_router",
    "learning_router",
    "settings_router",
    "status_router",
    "trades_router",
    "watchlist_router",
]
