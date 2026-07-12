from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

router = APIRouter(tags=["ui"])

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
INDEX_PATH = WEB_DIR / "index.html"


@router.get("/", include_in_schema=False)
async def root_ui() -> RedirectResponse:
    return RedirectResponse(url="/ui")


@router.get("/ui", include_in_schema=False)
@router.get("/ui/", include_in_schema=False)
async def ui_index() -> FileResponse:
    return FileResponse(INDEX_PATH, media_type="text/html")
