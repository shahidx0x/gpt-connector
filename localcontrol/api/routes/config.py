from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from localcontrol.api.deps import log_success
from localcontrol.auth import require_auth
from localcontrol.config_store import config_snapshot, update_config
from localcontrol.models import ConfigGetRequest, ConfigSnapshotResponse, ConfigUpdateRequest, ConfigUpdateResponse

router = APIRouter(tags=["config"], dependencies=[Depends(require_auth)])


@router.post("/config/get", response_model=ConfigSnapshotResponse, operation_id="config_get")
async def config_get(payload: ConfigGetRequest, request: Request) -> ConfigSnapshotResponse:
    response = ConfigSnapshotResponse(**config_snapshot(reveal_secrets=payload.reveal_secrets))
    log_success(request, "config.get", details={"reveal_secrets": payload.reveal_secrets})
    return response


@router.post("/config/update", response_model=ConfigUpdateResponse, operation_id="config_update")
async def config_update(payload: ConfigUpdateRequest, request: Request) -> ConfigUpdateResponse:
    response = ConfigUpdateResponse(
        **update_config(
            port=payload.port,
            api_key=payload.api_key,
            randomize_api_key=payload.randomize_api_key,
            ngrok_authtoken=payload.ngrok_authtoken,
            ngrok_domain=payload.ngrok_domain,
            public_url=payload.public_url,
            reveal_secrets=payload.reveal_secrets,
        )
    )
    log_success(
        request,
        "config.update",
        details={"changed_keys": response.changed_keys, "restart_required_keys": response.restart_required_keys},
    )
    return response
