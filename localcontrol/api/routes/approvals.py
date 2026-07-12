from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from localcontrol.api.deps import log_success
from localcontrol.approvals import approval_store
from localcontrol.auth import require_approval_key, require_auth
from localcontrol.models import ApprovalDecisionRequest, ApprovalRecordModel, ApprovalRequest

router = APIRouter(tags=["approval"], dependencies=[Depends(require_auth)])


@router.post("/approval/request", response_model=ApprovalRecordModel, operation_id="approval_request")
async def approval_request(payload: ApprovalRequest, request: Request) -> ApprovalRecordModel:
    response = approval_store.create(action=payload.action, reason=payload.reason, risk=payload.risk, payload=payload.payload)
    log_success(request, "approval.request", target=response.id, risk=payload.risk.value, details={"action": payload.action})
    return response


@router.get("/approval/{approval_id}", response_model=ApprovalRecordModel, operation_id="approval_get")
async def approval_get(approval_id: str, request: Request) -> ApprovalRecordModel:
    response = approval_store.get(approval_id)
    log_success(request, "approval.get", target=approval_id, risk=response.risk.value, details={"status": response.status.value})
    return response


@router.post(
    "/approval/{approval_id}/approve",
    response_model=ApprovalRecordModel,
    operation_id="approval_approve",
    dependencies=[Depends(require_approval_key)],
)
async def approval_approve(approval_id: str, payload: ApprovalDecisionRequest, request: Request) -> ApprovalRecordModel:
    response = approval_store.approve(approval_id, payload.note)
    log_success(request, "approval.approve", target=approval_id, risk=response.risk.value, details={"action": response.action})
    return response


@router.post(
    "/approval/{approval_id}/deny",
    response_model=ApprovalRecordModel,
    operation_id="approval_deny",
    dependencies=[Depends(require_approval_key)],
)
async def approval_deny(approval_id: str, payload: ApprovalDecisionRequest, request: Request) -> ApprovalRecordModel:
    response = approval_store.deny(approval_id, payload.note)
    log_success(request, "approval.deny", target=approval_id, risk=response.risk.value, details={"action": response.action})
    return response

