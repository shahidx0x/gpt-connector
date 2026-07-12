from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from localcontrol.api.deps import log_success
from localcontrol.auth import require_auth
from localcontrol.models import JobStartedResponse, ShellRunRequest, ShellRunResponse
from localcontrol.shell_ops import execute_command, job_manager

router = APIRouter(tags=["shell"], dependencies=[Depends(require_auth)])


@router.post("/shell/run", response_model=ShellRunResponse | JobStartedResponse, operation_id="shell_run")
async def shell_run(payload: ShellRunRequest, request: Request) -> ShellRunResponse | JobStartedResponse:
    if payload.async_job:
        response = job_manager.start(payload)
        log_success(
            request,
            "shell.run.async",
            target=payload.cwd,
            details={"job_id": response.job_id, "full_control": True},
        )
        return response

    response = execute_command(payload)
    log_success(
        request,
        "shell.run",
        target=payload.cwd,
        details={
            "job_id": response.job_id,
            "exit_code": response.exit_code,
            "timed_out": response.timed_out,
            "redactions": response.redactions,
            "full_control": True,
        },
    )
    return response

