from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.core.config import get_settings


def require_admin(x_api_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not settings.admin_api_key or settings.admin_api_key == "replace-before-deployment":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Admin API is not configured")
    if x_api_key != settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin API key")
