from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from localcontrol import __version__
from localcontrol.api.deps import log_success
from localcontrol.auth import require_auth
from localcontrol.config import get_settings
from localcontrol.errors import LocalControlError
from localcontrol.models import HealthResponse, SystemInfoResponse
from localcontrol.system_ops import system_info

router = APIRouter(tags=["system"])

ROOT_DIR = Path(__file__).resolve().parents[3]
GPT_ACTIONS_SCHEMA_PATH = ROOT_DIR / "gpt-actions.openapi.yaml"


@router.get("/health", response_model=HealthResponse, operation_id="health")
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        ok=True,
        auth_configured=bool(settings.api_key_hash),
        approval_configured=bool(settings.approval_key_hash),
        allow_all=True,
        full_control=True,
        cpu_count=settings.cpu_count,
        max_shell_workers=settings.max_shell_workers,
        version=__version__,
    )


@router.get("/openapi.json", include_in_schema=False, dependencies=[Depends(require_auth)])
async def openapi_json(request: Request) -> dict[str, Any]:
    return request.app.openapi()


@router.get("/gpt-actions.openapi.yaml", include_in_schema=False)
@router.get("/gpt-actions.yml", include_in_schema=False)
async def gpt_actions_yaml(request: Request) -> FileResponse:
    if not GPT_ACTIONS_SCHEMA_PATH.exists():
        raise LocalControlError(
            "schema_not_found",
            "gpt-actions.openapi.yaml has not been generated yet.",
            status_code=404,
            details={"expected_path": str(GPT_ACTIONS_SCHEMA_PATH)},
        )
    log_success(request, "schema.download", target=str(GPT_ACTIONS_SCHEMA_PATH))
    return FileResponse(
        path=GPT_ACTIONS_SCHEMA_PATH,
        filename="gpt-actions.openapi.yaml",
        media_type="application/yaml",
    )


@router.get("/system/info", response_model=SystemInfoResponse, operation_id="system_info", dependencies=[Depends(require_auth)])
async def system_info_endpoint(request: Request) -> SystemInfoResponse:
    response = system_info()
    log_success(request, "system.info", target=response.hostname)
    return response

