from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.config import get_settings
from app.services.fei_keywords import FeiKeywordError, list_keywords, replace_favorite_keywords

router = APIRouter(prefix="/api/fei-keywords", tags=["fei-keywords"])


def _require_admin_key(x_panel_admin_key: str | None = Header(default=None)) -> None:
    expected = get_settings().panel_admin_key
    if not expected or x_panel_admin_key != expected:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Admin control key rejected."})


@router.get("")
def fei_keywords() -> dict[str, object]:
    return list_keywords()


@router.get("/favorites")
def fei_favorite_keywords() -> dict[str, object]:
    return list_keywords(favorites_only=True)


@router.put("/favorites")
def fei_keyword_favorites(
    payload: dict[str, object],
    x_panel_admin_key: str | None = Header(default=None),
) -> dict[str, object]:
    _require_admin_key(x_panel_admin_key)
    try:
        return replace_favorite_keywords(payload.get("keyword_ids"))
    except FeiKeywordError as exc:
        raise HTTPException(status_code=400, detail={"code": str(exc), "message": str(exc)}) from exc
