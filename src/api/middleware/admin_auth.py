"""Middleware: valida conta Google do ngrok OAuth e restringe ao admin."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.services.admin_auth import get_admin_email, set_admin_email

_NGROK_EMAIL_HEADERS = (
    "ngrok-auth-user-email",
    "Ngrok-Auth-User-Email",
)

_PUBLIC_PATHS = frozenset({"/api/health"})


def extract_ngrok_email(request: Request) -> str | None:
    for key in _NGROK_EMAIL_HEADERS:
        value = request.headers.get(key)
        if value:
            return value.strip().lower()
    return None


class AdminAuthMiddleware(BaseHTTPMiddleware):
    """Exige Google OAuth (ngrok) no acesso remoto; primeira conta vira admin."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in _PUBLIC_PATHS:
            return await call_next(request)

        email = extract_ngrok_email(request)
        if not email:
            # Acesso local (sem túnel ngrok) — sem bloqueio
            request.state.user_email = None
            request.state.is_ngrok_auth = False
            return await call_next(request)

        request.state.is_ngrok_auth = True
        admin = get_admin_email()

        if admin is None:
            try:
                set_admin_email(email)
                admin = email
            except ValueError as exc:
                return JSONResponse(
                    status_code=403,
                    content={"detail": str(exc)},
                )

        if email != admin:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Acesso negado. Apenas o administrador pode acessar este dashboard.",
                    "admin_configured": True,
                },
            )

        request.state.user_email = email
        request.state.is_admin = True
        return await call_next(request)
