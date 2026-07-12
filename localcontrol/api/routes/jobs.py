from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from localcontrol.api.deps import log_success
from localcontrol.auth import require_auth
from localcontrol.models import JobCancelResponse, JobResponse
from localcontrol.shell_ops import job_manager

router = APIRouter(tags=["jobs"], dependencies=[Depends(require_auth)])


@router.get("/jobs/{job_id}", response_model=JobResponse, operation_id="job_get")
async def job_get(job_id: str, request: Request) -> JobResponse:
    response = job_manager.get(job_id)
    log_success(request, "job.get", target=job_id, details={"status": response.status})
    return response


@router.post("/jobs/{job_id}/cancel", response_model=JobCancelResponse, operation_id="job_cancel")
async def job_cancel(job_id: str, request: Request) -> JobCancelResponse:
    response = job_manager.cancel(job_id)
    log_success(request, "job.cancel", target=job_id, details={"status": response.status})
    return response

