from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from localcontrol.api.deps import log_success
from localcontrol.auth import require_auth
from localcontrol.execution_log import execution_log
from localcontrol.models import ExecutionLogRequest, ExecutionLogResponse

router = APIRouter(tags=["execution"], dependencies=[Depends(require_auth)])


@router.post("/execution/logs", response_model=ExecutionLogResponse, operation_id="execution_logs")
async def execution_logs(payload: ExecutionLogRequest, request: Request) -> ExecutionLogResponse:
    response = execution_log.query(
        after_event_id=payload.after_event_id,
        max_events=payload.max_events,
        run_id=payload.run_id,
        streams=payload.streams,
    )
    log_success(
        request,
        "execution.logs",
        target=payload.run_id,
        details={"event_count": len(response.events), "after_event_id": payload.after_event_id, "truncated": response.truncated},
    )
    return response

