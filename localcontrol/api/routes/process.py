from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from localcontrol.api.deps import log_success
from localcontrol.auth import require_auth
from localcontrol.models import ProcessKillRequest, ProcessKillResponse, ProcessListRequest, ProcessListResponse
from localcontrol.process_ops import kill_process, list_processes

router = APIRouter(tags=["process"], dependencies=[Depends(require_auth)])


@router.post("/process/list", response_model=ProcessListResponse, operation_id="process_list")
async def process_list_endpoint(payload: ProcessListRequest, request: Request) -> ProcessListResponse:
    response = list_processes(payload)
    log_success(request, "process.list", details={"count": len(response.processes), "truncated": response.truncated})
    return response


@router.post("/process/kill", response_model=ProcessKillResponse, operation_id="process_kill")
async def process_kill_endpoint(payload: ProcessKillRequest, request: Request) -> ProcessKillResponse:
    response = kill_process(payload)
    log_success(request, "process.kill", target=str(payload.pid), details={"killed": response.killed, "full_control": True})
    return response

