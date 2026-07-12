from __future__ import annotations

from typing import Any

from fastapi import Request


def request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def caller(request: Request) -> str | None:
    return getattr(request.state, "caller", None)


def log_success(
    request: Request,
    action: str,
    *,
    target: str | None = None,
    risk: str = "low",
    details: dict[str, Any] | None = None,
) -> None:
    return None
