from __future__ import annotations

from fastapi import APIRouter

from app.services.admin_settings import get_admin_settings

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/settings")
def admin_settings() -> dict[str, object]:
    return get_admin_settings()
