from __future__ import annotations

from typing import Any


class LocalControlError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
        risk: str = "low",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.risk = risk


class ApprovalRequiredError(LocalControlError):
    def __init__(self, approval: dict[str, Any], message: str = "Approval is required.") -> None:
        super().__init__(
            "approval_required",
            message,
            status_code=409,
            details={"approval": approval},
            risk=str(approval.get("risk", "high")),
        )

