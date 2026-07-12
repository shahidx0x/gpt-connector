from __future__ import annotations

import json
import threading
from typing import Any

from .config import get_settings
from .utils import utc_now_iso


class AuditLogger:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def log(
        self,
        *,
        request_id: str | None,
        action: str,
        status: str,
        risk: str = "low",
        target: str | None = None,
        details: dict[str, Any] | None = None,
        caller: str | None = None,
    ) -> None:
        settings = get_settings()
        settings.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": utc_now_iso(),
            "request_id": request_id,
            "caller": caller or "unknown",
            "action": action,
            "status": status,
            "risk": risk,
            "target": target,
            "details": details or {},
        }
        with self._lock:
            with settings.audit_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


audit_logger = AuditLogger()

