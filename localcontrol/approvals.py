from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from .errors import LocalControlError
from .models import ApprovalRecordModel, ApprovalStatus, RiskLevel
from .utils import utc_now_iso


def _payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in {"content", "stdout", "stderr", "token", "secret", "password"}:
            summary[key] = "[omitted]"
        else:
            text = str(value)
            summary[key] = text if len(text) <= 300 else f"{text[:300]}..."
    return summary


@dataclass
class ApprovalRecord:
    id: str
    action: str
    reason: str
    risk: RiskLevel
    status: ApprovalStatus
    created_at: str
    payload_summary: dict[str, Any] = field(default_factory=dict)
    approved_at: str | None = None
    denied_at: str | None = None
    consumed_at: str | None = None
    note: str | None = None

    def public(self) -> ApprovalRecordModel:
        status = ApprovalStatus.consumed if self.consumed_at else self.status
        return ApprovalRecordModel(
            id=self.id,
            action=self.action,
            reason=self.reason,
            risk=self.risk,
            status=status,
            created_at=self.created_at,
            approved_at=self.approved_at,
            denied_at=self.denied_at,
            consumed_at=self.consumed_at,
            note=self.note,
            payload_summary=self.payload_summary,
        )


class ApprovalStore:
    def __init__(self) -> None:
        self._items: dict[str, ApprovalRecord] = {}
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._items.clear()

    def create(
        self,
        *,
        action: str,
        reason: str,
        risk: RiskLevel,
        payload: dict[str, Any] | None = None,
    ) -> ApprovalRecordModel:
        payload = payload or {}
        record = ApprovalRecord(
            id=str(uuid.uuid4()),
            action=action,
            reason=reason,
            risk=risk,
            status=ApprovalStatus.pending,
            created_at=utc_now_iso(),
            payload_summary=_payload_summary(payload),
        )
        with self._lock:
            self._items[record.id] = record
        return record.public()

    def get(self, approval_id: str) -> ApprovalRecordModel:
        with self._lock:
            record = self._items.get(approval_id)
            if not record:
                raise LocalControlError("approval_not_found", "Approval was not found.", status_code=404)
            return record.public()

    def approve(self, approval_id: str, note: str | None = None) -> ApprovalRecordModel:
        with self._lock:
            record = self._items.get(approval_id)
            if not record:
                raise LocalControlError("approval_not_found", "Approval was not found.", status_code=404)
            if record.status == ApprovalStatus.denied:
                raise LocalControlError("approval_denied", "Denied approvals cannot be approved.", status_code=409)
            if record.consumed_at:
                raise LocalControlError("approval_consumed", "Approval has already been consumed.", status_code=409)
            record.status = ApprovalStatus.approved
            record.approved_at = utc_now_iso()
            record.note = note
            return record.public()

    def deny(self, approval_id: str, note: str | None = None) -> ApprovalRecordModel:
        with self._lock:
            record = self._items.get(approval_id)
            if not record:
                raise LocalControlError("approval_not_found", "Approval was not found.", status_code=404)
            if record.consumed_at:
                raise LocalControlError("approval_consumed", "Approval has already been consumed.", status_code=409)
            record.status = ApprovalStatus.denied
            record.denied_at = utc_now_iso()
            record.note = note
            return record.public()


approval_store = ApprovalStore()
