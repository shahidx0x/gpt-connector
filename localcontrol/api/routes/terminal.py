from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from localcontrol.api.deps import log_success
from localcontrol.auth import require_auth
from localcontrol.models import (
    TerminalEventsRequest,
    TerminalEventsResponse,
    TerminalExecRequest,
    TerminalExecResponse,
    TerminalSessionCreateRequest,
    TerminalSessionInfo,
    TerminalSessionListRequest,
    TerminalSessionListResponse,
    TerminalStdinRequest,
    TerminalStdinResponse,
    TerminalTerminateResponse,
)
from localcontrol.terminal_ops import terminal_manager

router = APIRouter(tags=["terminal"], dependencies=[Depends(require_auth)])


@router.post("/terminal/sessions", response_model=TerminalSessionInfo, operation_id="terminal_create_session")
async def terminal_create_session(payload: TerminalSessionCreateRequest, request: Request) -> TerminalSessionInfo:
    response = terminal_manager.create(payload)
    log_success(
        request,
        "terminal.sessions.create",
        target=response.session_id,
        details={"shell": response.shell, "cwd": response.cwd, "process_id": response.process_id},
    )
    return response


@router.post("/terminal/sessions/list", response_model=TerminalSessionListResponse, operation_id="terminal_list_sessions")
async def terminal_list_sessions(payload: TerminalSessionListRequest, request: Request) -> TerminalSessionListResponse:
    response = terminal_manager.list(payload.include_exited)
    log_success(request, "terminal.sessions.list", details={"count": len(response.sessions), "include_exited": payload.include_exited})
    return response


@router.get("/terminal/sessions/{session_id}", response_model=TerminalSessionInfo, operation_id="terminal_get_session")
async def terminal_get_session(session_id: str, request: Request) -> TerminalSessionInfo:
    response = terminal_manager.get(session_id)
    log_success(request, "terminal.sessions.get", target=session_id, details={"status": response.status, "command_count": response.command_count})
    return response


@router.post("/terminal/sessions/{session_id}/exec", response_model=TerminalExecResponse, operation_id="terminal_exec")
async def terminal_exec(session_id: str, payload: TerminalExecRequest, request: Request) -> TerminalExecResponse:
    response = terminal_manager.exec(session_id, payload.command, payload.include_secrets)
    log_success(
        request,
        "terminal.exec",
        target=session_id,
        details={
            "command_id": response.command_id,
            "command_count": response.session.command_count,
            "redacted": not payload.include_secrets,
            "full_control": True,
        },
    )
    return response


@router.post("/terminal/sessions/{session_id}/stdin", response_model=TerminalStdinResponse, operation_id="terminal_stdin")
async def terminal_stdin(session_id: str, payload: TerminalStdinRequest, request: Request) -> TerminalStdinResponse:
    response = terminal_manager.stdin(session_id, payload.input)
    log_success(request, "terminal.stdin", target=session_id, details={"bytes_written": response.bytes_written})
    return response


@router.post("/terminal/sessions/{session_id}/events", response_model=TerminalEventsResponse, operation_id="terminal_events")
async def terminal_events(session_id: str, payload: TerminalEventsRequest, request: Request) -> TerminalEventsResponse:
    response = terminal_manager.events(session_id, payload.after_event_id, payload.max_events)
    log_success(
        request,
        "terminal.events",
        target=session_id,
        details={"event_count": len(response.events), "after_event_id": payload.after_event_id, "status": response.status},
    )
    return response


@router.post("/terminal/sessions/{session_id}/terminate", response_model=TerminalTerminateResponse, operation_id="terminal_terminate")
async def terminal_terminate(session_id: str, request: Request) -> TerminalTerminateResponse:
    response = terminal_manager.terminate(session_id)
    log_success(request, "terminal.terminate", target=session_id, details={"status": response.status})
    return response

