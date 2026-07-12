from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from localcontrol.api.deps import log_success
from localcontrol.artifacts_ops import (
    artifact_file_response,
    create_text_artifact,
    delete_artifact,
    fetch_url_artifact,
    from_path_artifact,
    get_artifact,
    list_artifacts,
    upload_base64_artifact,
    write_artifact_to_path,
)
from localcontrol.auth import require_auth
from localcontrol.models import (
    ArtifactCreateTextRequest,
    ArtifactDeleteRequest,
    ArtifactDeleteResponse,
    ArtifactFetchUrlRequest,
    ArtifactFromPathRequest,
    ArtifactInfo,
    ArtifactListRequest,
    ArtifactListResponse,
    ArtifactUploadBase64Request,
    ArtifactWriteToPathRequest,
)
from localcontrol.utils import normalize_path

router = APIRouter(tags=["artifacts"], dependencies=[Depends(require_auth)])


@router.post("/artifacts/create_text", response_model=ArtifactInfo, operation_id="artifacts_create_text")
async def artifacts_create_text(payload: ArtifactCreateTextRequest, request: Request) -> ArtifactInfo:
    response = create_text_artifact(payload)
    log_success(
        request,
        "artifacts.create_text",
        target=response.local_path,
        details={"artifact_id": response.artifact_id, "name": response.name, "size": response.size},
    )
    return response


@router.post("/artifacts/upload_base64", response_model=ArtifactInfo, operation_id="artifacts_upload_base64")
async def artifacts_upload_base64(payload: ArtifactUploadBase64Request, request: Request) -> ArtifactInfo:
    response = upload_base64_artifact(payload)
    log_success(
        request,
        "artifacts.upload_base64",
        target=response.local_path,
        details={"artifact_id": response.artifact_id, "name": response.name, "size": response.size},
    )
    return response


@router.post("/artifacts/fetch_url", response_model=ArtifactInfo, operation_id="artifacts_fetch_url")
async def artifacts_fetch_url(payload: ArtifactFetchUrlRequest, request: Request) -> ArtifactInfo:
    response = fetch_url_artifact(payload)
    log_success(
        request,
        "artifacts.fetch_url",
        target=payload.url,
        risk="medium",
        details={"artifact_id": response.artifact_id, "final_name": response.name, "size": response.size},
    )
    return response


@router.post("/artifacts/from_path", response_model=ArtifactInfo, operation_id="artifacts_from_path")
async def artifacts_from_path(payload: ArtifactFromPathRequest, request: Request) -> ArtifactInfo:
    path = normalize_path(payload.path)
    response = from_path_artifact(payload)
    log_success(
        request,
        "artifacts.from_path",
        target=str(path),
        details={"artifact_id": response.artifact_id, "managed": response.managed, "size": response.size, "full_control": True},
    )
    return response


@router.post("/artifacts/list", response_model=ArtifactListResponse, operation_id="artifacts_list")
async def artifacts_list(payload: ArtifactListRequest, request: Request) -> ArtifactListResponse:
    response = list_artifacts(payload.max_results)
    log_success(request, "artifacts.list", details={"count": len(response.artifacts)})
    return response


@router.get("/artifacts/{artifact_id}", response_model=ArtifactInfo, operation_id="artifacts_get")
async def artifacts_get(artifact_id: str, request: Request) -> ArtifactInfo:
    response = get_artifact(artifact_id)
    log_success(request, "artifacts.get", target=response.local_path, details={"artifact_id": response.artifact_id, "size": response.size})
    return response


@router.get("/artifacts/{artifact_id}/download", operation_id="artifacts_download")
async def artifacts_download(artifact_id: str, request: Request):
    info = get_artifact(artifact_id)
    response = artifact_file_response(artifact_id)
    log_success(request, "artifacts.download", target=info.local_path, details={"artifact_id": info.artifact_id, "size": info.size})
    return response


@router.post("/artifacts/{artifact_id}/write_to_path", response_model=ArtifactInfo, operation_id="artifacts_write_to_path")
async def artifacts_write_to_path(artifact_id: str, payload: ArtifactWriteToPathRequest, request: Request) -> ArtifactInfo:
    destination = normalize_path(payload.path)
    operation = "overwrite" if destination.exists() else "write"
    response = write_artifact_to_path(artifact_id, payload)
    log_success(
        request,
        "artifacts.write_to_path",
        target=str(destination),
        details={"artifact_id": response.artifact_id, "operation": operation, "size": response.size, "full_control": True},
    )
    return response


@router.post("/artifacts/{artifact_id}/delete", response_model=ArtifactDeleteResponse, operation_id="artifacts_delete")
async def artifacts_delete(artifact_id: str, payload: ArtifactDeleteRequest, request: Request) -> ArtifactDeleteResponse:
    info = get_artifact(artifact_id)
    deleted, removed_file = delete_artifact(artifact_id)
    log_success(
        request,
        "artifacts.delete",
        target=info.local_path,
        details={"artifact_id": artifact_id, "removed_file": removed_file, "full_control": True},
    )
    return ArtifactDeleteResponse(artifact_id=artifact_id, deleted=deleted, removed_file=removed_file)

