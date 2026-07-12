from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from localcontrol import __version__
from localcontrol.api.routes import routers
from localcontrol.errors import LocalControlError
from localcontrol.middleware import RateLimitMiddleware, RequestIdMiddleware
from localcontrol.models import ErrorResponse


def create_app() -> FastAPI:
    app = FastAPI(
        title="Windows LocalControl GPT Bridge",
        version=__version__,
        description="Private Windows control API intended for a single Custom GPT Action.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(LocalControlError, localcontrol_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    for router in routers:
        app.include_router(router)
    return app


async def localcontrol_error_handler(request: Request, exc: LocalControlError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "code": exc.code, "message": exc.message, "details": exc.details},
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"ok": False, "code": "validation_error", "message": "Request validation failed.", "details": {"errors": exc.errors()}},
    )


app = create_app()
