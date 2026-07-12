from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings, sha256_hex

bearer_scheme = HTTPBearer(auto_error=False)


def _verify_secret(raw_secret: str, expected_hash: str | None) -> bool:
    if not expected_hash:
        return False
    return secrets.compare_digest(sha256_hex(raw_secret), expected_hash)


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    settings = get_settings()
    if not settings.api_key_hash:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LOCALCONTROL_API_KEY or LOCALCONTROL_API_KEY_SHA256 is not configured.",
        )
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    if not _verify_secret(credentials.credentials, settings.api_key_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token.")
    request.state.caller = "gpt-action"
    return "gpt-action"


async def require_approval_key(request: Request) -> None:
    settings = get_settings()
    if not settings.approval_key_hash:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LOCALCONTROL_APPROVAL_KEY or LOCALCONTROL_APPROVAL_KEY_SHA256 is not configured.",
        )
    raw_key = request.headers.get("X-LocalControl-Approval-Key")
    if not raw_key or not _verify_secret(raw_key, settings.approval_key_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid approval key.")

