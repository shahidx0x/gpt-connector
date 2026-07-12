from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import get_settings


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        if request.url.path == "/health" or settings.rate_limit_per_minute <= 0:
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        client = request.client.host if request.client else "unknown"
        key = f"{client}:{auth[-16:]}"
        now = time.monotonic()
        window_start = now - 60

        with self._lock:
            events = self._events[key]
            while events and events[0] < window_start:
                events.popleft()
            if len(events) >= settings.rate_limit_per_minute:
                return JSONResponse(
                    status_code=429,
                    content={"ok": False, "code": "rate_limited", "message": "Rate limit exceeded.", "details": {}},
                )
            events.append(now)

        return await call_next(request)

