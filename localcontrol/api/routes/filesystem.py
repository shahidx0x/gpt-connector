from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from localcontrol.api.deps import log_success
from localcontrol.auth import require_auth
from localcontrol.fs_ops import delete_path, list_path, read_file, replace_file, stat_path, write_file
from localcontrol.models import (
    FsDeleteRequest,
    FsDeleteResponse,
    FsListRequest,
    FsListResponse,
    FsReadRequest,
    FsReadResponse,
    FsReplaceRequest,
    FsReplaceResponse,
    FsStatRequest,
    FsStatResponse,
    FsWriteRequest,
    FsWriteResponse,
)
from localcontrol.utils import normalize_path

router = APIRouter(tags=["filesystem"], dependencies=[Depends(require_auth)])


@router.post("/fs/list", response_model=FsListResponse, operation_id="fs_list")
async def fs_list(payload: FsListRequest, request: Request) -> FsListResponse:
    response = list_path(payload)
    log_success(request, "fs.list", target=response.path, details={"count": len(response.entries), "truncated": response.truncated})
    return response


@router.post("/fs/read", response_model=FsReadResponse, operation_id="fs_read")
async def fs_read(payload: FsReadRequest, request: Request) -> FsReadResponse:
    response = read_file(payload)
    log_success(
        request,
        "fs.read",
        target=response.path,
        details={"bytes_read": response.bytes_read, "truncated": response.truncated, "redactions": response.redactions, "full_control": True},
    )
    return response


@router.post("/fs/write", response_model=FsWriteResponse, operation_id="fs_write")
async def fs_write(payload: FsWriteRequest, request: Request) -> FsWriteResponse:
    path = normalize_path(payload.path)
    operation = "append" if payload.append else ("overwrite" if path.exists() else "write")
    response = write_file(payload)
    log_success(
        request,
        "fs.write",
        target=response.path,
        details={"mode": response.mode, "operation": operation, "bytes": response.bytes_written, "full_control": True},
    )
    return response


@router.post("/fs/replace", response_model=FsReplaceResponse, operation_id="fs_replace")
async def fs_replace(payload: FsReplaceRequest, request: Request) -> FsReplaceResponse:
    response = replace_file(payload)
    log_success(request, "fs.replace", target=response.path, details={"replacements": response.replacements, "full_control": True})
    return response


@router.post("/fs/delete", response_model=FsDeleteResponse, operation_id="fs_delete")
async def fs_delete(payload: FsDeleteRequest, request: Request) -> FsDeleteResponse:
    response = delete_path(payload)
    log_success(request, "fs.delete", target=response.path, details={"deleted": response.deleted, "full_control": True})
    return response


@router.post("/fs/stat", response_model=FsStatResponse, operation_id="fs_stat")
async def fs_stat(payload: FsStatRequest, request: Request) -> FsStatResponse:
    response = stat_path(payload.path)
    log_success(request, "fs.stat", target=response.file.path, details={"exists": response.exists})
    return response
