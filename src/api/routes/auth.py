from fastapi import APIRouter, Request

from src.api.middleware.admin_auth import extract_ngrok_email
from src.api.services.admin_auth import get_admin_info, get_admin_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
def auth_me(request: Request) -> dict:
    email = getattr(request.state, "user_email", None) or extract_ngrok_email(request)
    admin = get_admin_email()
    info = get_admin_info()
    return {
        "email": email,
        "admin_email": admin,
        "admin_configured": info["configured"],
        "is_admin": bool(email and admin and email == admin),
        "ngrok_auth": bool(getattr(request.state, "is_ngrok_auth", False) or email),
        "created_at": info.get("created_at"),
    }
