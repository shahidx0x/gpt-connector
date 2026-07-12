from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from . import __version__
from .approvals import approval_store
from .audit import audit_logger
from .artifacts_ops import (
    artifact_file_response,
    create_text_artifact,
    delete_artifact,
    fetch_url_artifact,
    from_path_artifact,
    get_artifact,
    list_artifacts,
    upload_base64_artifact,
    write_artifact_to_path,
)
from .auth import require_approval_key, require_auth
from .config import get_settings
from .errors import LocalControlError
from .fs_ops import delete_path, list_path, read_file, replace_file, stat_path, write_file
from .git_ops import git_add, git_branches, git_checkout, git_commit, git_diff, git_log, git_reset, git_status
from .middleware import RateLimitMiddleware, RequestIdMiddleware
from .models import (
    ApprovalDecisionRequest,
    ApprovalRecordModel,
    ApprovalRequest,
    ArtifactCreateTextRequest,
    ArtifactDeleteRequest,
    ArtifactDeleteResponse,
    ArtifactFetchUrlRequest,
    ArtifactFromPathRequest,
    ArtifactInfo,
    ArtifactListRequest,
    ArtifactListResponse,
    ArtifactUploadBase64Request,
    ArtifactWriteToPathRequest,
    ErrorResponse,
    FsDeleteRequest,
    FsDeleteResponse,
    FsListRequest,
    FsListResponse,
    FsReadRequest,
    FsReadResponse,
    FsReplaceRequest,
    FsReplaceResponse,
    FsStatRequest,
    FsStatResponse,
    FsWriteRequest,
    FsWriteResponse,
    GitAddRequest,
    GitAddResponse,
    GitBranchesRequest,
    GitBranchesResponse,
    GitCheckoutRequest,
    GitCheckoutResponse,
    GitCommitRequest,
    GitCommitResponse,
    GitDiffRequest,
    GitDiffResponse,
    GitLogRequest,
    GitLogResponse,
    GitResetRequest,
    GitResetResponse,
    GitStatusRequest,
    GitStatusResponse,
    HealthResponse,
    JobCancelResponse,
    JobResponse,
    JobStartedResponse,
    ProcessKillRequest,
    ProcessKillResponse,
    ProcessListRequest,
    ProcessListResponse,
    RiskLevel,
    SearchContentRequest,
    SearchContentResponse,
    SearchFilesRequest,
    SearchFilesResponse,
    ShellRunRequest,
    ShellRunResponse,
    SystemInfoResponse,
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
from .process_ops import kill_process, list_processes
from .safety import assess_path_mutation, assess_path_read, assess_shell_command, is_sensitive_path
from .search_ops import search_content, search_files
from .shell_ops import execute_command, job_manager
from .system_ops import system_info
from .terminal_ops import terminal_manager
from .utils import normalize_path

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

ROOT_DIR = Path(__file__).resolve().parents[1]
GPT_ACTIONS_SCHEMA_PATH = ROOT_DIR / "gpt-actions.openapi.yaml"


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _caller(request: Request) -> str | None:
    return getattr(request.state, "caller", None)


def _log_success(request: Request, action: str, *, target: str | None = None, risk: str = "low", details: dict[str, Any] | None = None) -> None:
    audit_logger.log(
        request_id=_request_id(request),
        caller=_caller(request),
        action=action,
        status="success",
        risk=risk,
        target=target,
        details=details,
    )


def _enforce_approval(
    request: Request,
    *,
    action: str,
    reason: str,
    risk: RiskLevel,
    approval_id: str | None,
    payload: dict[str, Any],
    target: str | None = None,
) -> bool:
    settings = get_settings()
    if settings.allow_all:
        audit_logger.log(
            request_id=_request_id(request),
            caller=_caller(request),
            action=f"{action}.approval_bypassed",
            status="success",
            risk=risk.value,
            target=target,
            details={"reason": reason, "allow_all": True},
        )
        return True
    approval_store.ensure_approved(
        action=action,
        reason=reason,
        risk=risk,
        approval_id=approval_id,
        payload=payload,
    )
    return False


@app.exception_handler(LocalControlError)
async def localcontrol_error_handler(request: Request, exc: LocalControlError) -> JSONResponse:
    audit_logger.log(
        request_id=_request_id(request),
        caller=_caller(request),
        action=exc.code,
        status="error",
        risk=exc.risk,
        details=exc.details,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "code": exc.code, "message": exc.message, "details": exc.details},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    audit_logger.log(
        request_id=_request_id(request),
        caller=_caller(request),
        action="validation_error",
        status="error",
        risk="low",
        details={"errors": exc.errors()},
    )
    return JSONResponse(
        status_code=422,
        content={"ok": False, "code": "validation_error", "message": "Request validation failed.", "details": {"errors": exc.errors()}},
    )


@app.get("/health", response_model=HealthResponse, operation_id="health", tags=["system"])
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        ok=True,
        auth_configured=bool(settings.api_key_hash),
        approval_configured=bool(settings.approval_key_hash),
        allow_all=settings.allow_all,
        version=__version__,
    )


@app.get("/openapi.json", include_in_schema=False, dependencies=[Depends(require_auth)])
async def openapi_json() -> dict[str, Any]:
    return app.openapi()


@app.get("/gpt-actions.openapi.yaml", include_in_schema=False)
@app.get("/gpt-actions.yml", include_in_schema=False)
async def gpt_actions_yaml(request: Request) -> FileResponse:
    if not GPT_ACTIONS_SCHEMA_PATH.exists():
        raise LocalControlError(
            "schema_not_found",
            "gpt-actions.openapi.yaml has not been generated yet.",
            status_code=404,
            details={"expected_path": str(GPT_ACTIONS_SCHEMA_PATH)},
        )
    _log_success(request, "schema.download", target=str(GPT_ACTIONS_SCHEMA_PATH))
    return FileResponse(
        path=GPT_ACTIONS_SCHEMA_PATH,
        filename="gpt-actions.openapi.yaml",
        media_type="application/yaml",
    )


@app.post("/fs/list", response_model=FsListResponse, operation_id="fs_list", tags=["filesystem"], dependencies=[Depends(require_auth)])
async def fs_list(payload: FsListRequest, request: Request) -> FsListResponse:
    response = list_path(payload)
    _log_success(request, "fs.list", target=response.path, details={"count": len(response.entries), "truncated": response.truncated})
    return response


@app.post("/fs/read", response_model=FsReadResponse, operation_id="fs_read", tags=["filesystem"], dependencies=[Depends(require_auth)])
async def fs_read(payload: FsReadRequest, request: Request) -> FsReadResponse:
    path = normalize_path(payload.path)
    assessment = assess_path_read(path, payload.include_secrets)
    approval_bypassed = False
    if assessment.approval_required:
        approval_bypassed = _enforce_approval(
            request,
            action="fs.read",
            reason=assessment.reason,
            risk=assessment.risk,
            approval_id=payload.approval_id,
            payload={"path": str(path), "include_secrets": payload.include_secrets},
            target=str(path),
        )
    response = read_file(payload)
    _log_success(
        request,
        "fs.read",
        target=response.path,
        risk=assessment.risk.value,
        details={"bytes_read": response.bytes_read, "truncated": response.truncated, "redactions": response.redactions, "approval_bypassed": approval_bypassed},
    )
    return response


@app.post("/fs/write", response_model=FsWriteResponse, operation_id="fs_write", tags=["filesystem"], dependencies=[Depends(require_auth)])
async def fs_write(payload: FsWriteRequest, request: Request) -> FsWriteResponse:
    path = normalize_path(payload.path)
    operation = "append" if payload.append else ("overwrite" if path.exists() else "write")
    assessment = assess_path_mutation(path, operation)
    approval_bypassed = False
    if assessment.approval_required:
        approval_bypassed = _enforce_approval(
            request,
            action="fs.write",
            reason=assessment.reason,
            risk=assessment.risk,
            approval_id=payload.approval_id,
            payload={"path": str(path), "operation": operation},
            target=str(path),
        )
    response = write_file(payload)
    _log_success(
        request,
        "fs.write",
        target=response.path,
        risk=assessment.risk.value,
        details={"mode": response.mode, "bytes": response.bytes_written, "approval_bypassed": approval_bypassed},
    )
    return response


@app.post("/fs/replace", response_model=FsReplaceResponse, operation_id="fs_replace", tags=["filesystem"], dependencies=[Depends(require_auth)])
async def fs_replace(payload: FsReplaceRequest, request: Request) -> FsReplaceResponse:
    path = normalize_path(payload.path)
    assessment = assess_path_mutation(path, "replace")
    approval_bypassed = False
    if assessment.approval_required:
        approval_bypassed = _enforce_approval(
            request,
            action="fs.replace",
            reason=assessment.reason,
            risk=assessment.risk,
            approval_id=payload.approval_id,
            payload={"path": str(path), "old": payload.old, "new": payload.new, "count": payload.count},
            target=str(path),
        )
    response = replace_file(payload)
    _log_success(
        request,
        "fs.replace",
        target=response.path,
        risk=assessment.risk.value,
        details={"replacements": response.replacements, "approval_bypassed": approval_bypassed},
    )
    return response


@app.post("/fs/delete", response_model=FsDeleteResponse, operation_id="fs_delete", tags=["filesystem"], dependencies=[Depends(require_auth)])
async def fs_delete(payload: FsDeleteRequest, request: Request) -> FsDeleteResponse:
    path = normalize_path(payload.path)
    assessment = assess_path_mutation(path, "delete")
    approval_bypassed = _enforce_approval(
        request,
        action="fs.delete",
        reason=assessment.reason,
        risk=RiskLevel.high,
        approval_id=payload.approval_id,
        payload={"path": str(path), "recursive": payload.recursive, "permanent": payload.permanent},
        target=str(path),
    )
    response = delete_path(payload)
    _log_success(request, "fs.delete", target=response.path, risk="high", details={"permanent": response.permanent, "approval_bypassed": approval_bypassed})
    return response


@app.post("/fs/stat", response_model=FsStatResponse, operation_id="fs_stat", tags=["filesystem"], dependencies=[Depends(require_auth)])
async def fs_stat(payload: FsStatRequest, request: Request) -> FsStatResponse:
    response = stat_path(payload.path)
    _log_success(request, "fs.stat", target=response.file.path, details={"exists": response.exists})
    return response


@app.post(
    "/artifacts/create_text",
    response_model=ArtifactInfo,
    operation_id="artifacts_create_text",
    tags=["artifacts"],
    dependencies=[Depends(require_auth)],
)
async def artifacts_create_text(payload: ArtifactCreateTextRequest, request: Request) -> ArtifactInfo:
    response = create_text_artifact(payload)
    _log_success(
        request,
        "artifacts.create_text",
        target=response.local_path,
        details={"artifact_id": response.artifact_id, "name": response.name, "size": response.size},
    )
    return response


@app.post(
    "/artifacts/upload_base64",
    response_model=ArtifactInfo,
    operation_id="artifacts_upload_base64",
    tags=["artifacts"],
    dependencies=[Depends(require_auth)],
)
async def artifacts_upload_base64(payload: ArtifactUploadBase64Request, request: Request) -> ArtifactInfo:
    response = upload_base64_artifact(payload)
    _log_success(
        request,
        "artifacts.upload_base64",
        target=response.local_path,
        details={"artifact_id": response.artifact_id, "name": response.name, "size": response.size},
    )
    return response


@app.post(
    "/artifacts/fetch_url",
    response_model=ArtifactInfo,
    operation_id="artifacts_fetch_url",
    tags=["artifacts"],
    dependencies=[Depends(require_auth)],
)
async def artifacts_fetch_url(payload: ArtifactFetchUrlRequest, request: Request) -> ArtifactInfo:
    response = fetch_url_artifact(payload)
    _log_success(
        request,
        "artifacts.fetch_url",
        target=payload.url,
        risk="medium",
        details={"artifact_id": response.artifact_id, "final_name": response.name, "size": response.size},
    )
    return response


@app.post(
    "/artifacts/from_path",
    response_model=ArtifactInfo,
    operation_id="artifacts_from_path",
    tags=["artifacts"],
    dependencies=[Depends(require_auth)],
)
async def artifacts_from_path(payload: ArtifactFromPathRequest, request: Request) -> ArtifactInfo:
    path = normalize_path(payload.path)
    approval_bypassed = False
    if is_sensitive_path(path):
        approval_bypassed = _enforce_approval(
            request,
            action="artifacts.from_path",
            reason="Registering a sensitive local file as an artifact can reveal raw secrets.",
            risk=RiskLevel.high,
            approval_id=payload.approval_id,
            payload={"path": str(path), "copy": payload.copy_file, "name": payload.name},
            target=str(path),
        )
    response = from_path_artifact(payload)
    _log_success(
        request,
        "artifacts.from_path",
        target=str(path),
        risk="high" if is_sensitive_path(path) else "low",
        details={
            "artifact_id": response.artifact_id,
            "managed": response.managed,
            "size": response.size,
            "approval_bypassed": approval_bypassed,
        },
    )
    return response


@app.post(
    "/artifacts/list",
    response_model=ArtifactListResponse,
    operation_id="artifacts_list",
    tags=["artifacts"],
    dependencies=[Depends(require_auth)],
)
async def artifacts_list(payload: ArtifactListRequest, request: Request) -> ArtifactListResponse:
    response = list_artifacts(payload.max_results)
    _log_success(request, "artifacts.list", details={"count": len(response.artifacts)})
    return response


@app.get(
    "/artifacts/{artifact_id}",
    response_model=ArtifactInfo,
    operation_id="artifacts_get",
    tags=["artifacts"],
    dependencies=[Depends(require_auth)],
)
async def artifacts_get(artifact_id: str, request: Request) -> ArtifactInfo:
    response = get_artifact(artifact_id)
    _log_success(request, "artifacts.get", target=response.local_path, details={"artifact_id": response.artifact_id, "size": response.size})
    return response


@app.get(
    "/artifacts/{artifact_id}/download",
    operation_id="artifacts_download",
    tags=["artifacts"],
    dependencies=[Depends(require_auth)],
)
async def artifacts_download(artifact_id: str, request: Request):
    info = get_artifact(artifact_id)
    response = artifact_file_response(artifact_id)
    _log_success(request, "artifacts.download", target=info.local_path, details={"artifact_id": info.artifact_id, "size": info.size})
    return response


@app.post(
    "/artifacts/{artifact_id}/write_to_path",
    response_model=ArtifactInfo,
    operation_id="artifacts_write_to_path",
    tags=["artifacts"],
    dependencies=[Depends(require_auth)],
)
async def artifacts_write_to_path(artifact_id: str, payload: ArtifactWriteToPathRequest, request: Request) -> ArtifactInfo:
    destination = normalize_path(payload.path)
    operation = "overwrite" if destination.exists() else "write"
    assessment = assess_path_mutation(destination, operation)
    overwrite_requires_approval = destination.exists() and payload.overwrite
    approval_bypassed = False
    if assessment.approval_required or overwrite_requires_approval:
        approval_bypassed = _enforce_approval(
            request,
            action="artifacts.write_to_path",
            reason=assessment.reason if assessment.approval_required else "Overwriting an existing file with an artifact requires approval.",
            risk=RiskLevel.high if overwrite_requires_approval else assessment.risk,
            approval_id=payload.approval_id,
            payload={"artifact_id": artifact_id, "path": str(destination), "overwrite": payload.overwrite},
            target=str(destination),
        )
    response = write_artifact_to_path(artifact_id, payload)
    _log_success(
        request,
        "artifacts.write_to_path",
        target=str(destination),
        risk="high" if overwrite_requires_approval else assessment.risk.value,
        details={"artifact_id": response.artifact_id, "size": response.size, "approval_bypassed": approval_bypassed},
    )
    return response


@app.post(
    "/artifacts/{artifact_id}/delete",
    response_model=ArtifactDeleteResponse,
    operation_id="artifacts_delete",
    tags=["artifacts"],
    dependencies=[Depends(require_auth)],
)
async def artifacts_delete(artifact_id: str, payload: ArtifactDeleteRequest, request: Request) -> ArtifactDeleteResponse:
    info = get_artifact(artifact_id)
    approval_bypassed = _enforce_approval(
        request,
        action="artifacts.delete",
        reason="Deleting an artifact removes its metadata and may remove its managed file.",
        risk=RiskLevel.medium,
        approval_id=payload.approval_id,
        payload={"artifact_id": artifact_id, "local_path": info.local_path, "managed": info.managed},
        target=info.local_path,
    )
    deleted, removed_file = delete_artifact(artifact_id)
    _log_success(
        request,
        "artifacts.delete",
        target=info.local_path,
        risk="medium",
        details={"artifact_id": artifact_id, "removed_file": removed_file, "approval_bypassed": approval_bypassed},
    )
    return ArtifactDeleteResponse(artifact_id=artifact_id, deleted=deleted, removed_file=removed_file)


@app.post("/search/files", response_model=SearchFilesResponse, operation_id="search_files", tags=["search"], dependencies=[Depends(require_auth)])
async def search_files_endpoint(payload: SearchFilesRequest, request: Request) -> SearchFilesResponse:
    response = search_files(payload)
    _log_success(request, "search.files", target=response.root, details={"count": len(response.results), "truncated": response.truncated})
    return response


@app.post("/search/content", response_model=SearchContentResponse, operation_id="search_content", tags=["search"], dependencies=[Depends(require_auth)])
async def search_content_endpoint(payload: SearchContentRequest, request: Request) -> SearchContentResponse:
    response = search_content(payload)
    _log_success(request, "search.content", target=response.root, details={"count": len(response.matches), "truncated": response.truncated})
    return response


@app.post(
    "/shell/run",
    response_model=ShellRunResponse | JobStartedResponse,
    operation_id="shell_run",
    tags=["shell"],
    dependencies=[Depends(require_auth)],
)
async def shell_run(payload: ShellRunRequest, request: Request) -> ShellRunResponse | JobStartedResponse:
    settings = get_settings()
    if not payload.async_job and payload.timeout_seconds > settings.max_sync_shell_timeout_seconds:
        raise LocalControlError(
            "sync_timeout_too_large",
            "Use async_job=true for commands with longer timeouts.",
            status_code=422,
            details={"max_sync_shell_timeout_seconds": settings.max_sync_shell_timeout_seconds},
        )
    assessment = assess_shell_command(payload.command, payload.timeout_seconds, payload.include_secrets, settings)
    approval_bypassed = False
    if assessment.approval_required:
        approval_bypassed = _enforce_approval(
            request,
            action="shell.run",
            reason=assessment.reason,
            risk=assessment.risk,
            approval_id=payload.approval_id,
            payload={"command": payload.command, "cwd": payload.cwd, "shell": payload.shell, "timeout_seconds": payload.timeout_seconds},
            target=payload.cwd,
        )
    if payload.async_job:
        response = job_manager.start(payload)
        _log_success(
            request,
            "shell.run.async",
            target=payload.cwd,
            risk=assessment.risk.value,
            details={"job_id": response.job_id, "approval_bypassed": approval_bypassed},
        )
        return response
    response = execute_command(payload)
    _log_success(
        request,
        "shell.run",
        target=payload.cwd,
        risk=assessment.risk.value,
        details={"exit_code": response.exit_code, "timed_out": response.timed_out, "redactions": response.redactions, "approval_bypassed": approval_bypassed},
    )
    return response


@app.post(
    "/terminal/sessions",
    response_model=TerminalSessionInfo,
    operation_id="terminal_create_session",
    tags=["terminal"],
    dependencies=[Depends(require_auth)],
)
async def terminal_create_session(payload: TerminalSessionCreateRequest, request: Request) -> TerminalSessionInfo:
    response = terminal_manager.create(payload)
    _log_success(
        request,
        "terminal.sessions.create",
        target=response.session_id,
        details={"shell": response.shell, "cwd": response.cwd, "process_id": response.process_id},
    )
    return response


@app.post(
    "/terminal/sessions/list",
    response_model=TerminalSessionListResponse,
    operation_id="terminal_list_sessions",
    tags=["terminal"],
    dependencies=[Depends(require_auth)],
)
async def terminal_list_sessions(payload: TerminalSessionListRequest, request: Request) -> TerminalSessionListResponse:
    response = terminal_manager.list(payload.include_exited)
    _log_success(request, "terminal.sessions.list", details={"count": len(response.sessions), "include_exited": payload.include_exited})
    return response


@app.get(
    "/terminal/sessions/{session_id}",
    response_model=TerminalSessionInfo,
    operation_id="terminal_get_session",
    tags=["terminal"],
    dependencies=[Depends(require_auth)],
)
async def terminal_get_session(session_id: str, request: Request) -> TerminalSessionInfo:
    response = terminal_manager.get(session_id)
    _log_success(request, "terminal.sessions.get", target=session_id, details={"status": response.status, "command_count": response.command_count})
    return response


@app.post(
    "/terminal/sessions/{session_id}/exec",
    response_model=TerminalExecResponse,
    operation_id="terminal_exec",
    tags=["terminal"],
    dependencies=[Depends(require_auth)],
)
async def terminal_exec(session_id: str, payload: TerminalExecRequest, request: Request) -> TerminalExecResponse:
    settings = get_settings()
    assessment = assess_shell_command(payload.command, settings.default_shell_timeout_seconds, payload.include_secrets, settings)
    approval_bypassed = False
    if assessment.approval_required:
        approval_bypassed = _enforce_approval(
            request,
            action="terminal.exec",
            reason=assessment.reason,
            risk=assessment.risk,
            approval_id=payload.approval_id,
            payload={"session_id": session_id, "command": payload.command, "include_secrets": payload.include_secrets},
            target=session_id,
        )
    response = terminal_manager.exec(session_id, payload.command, payload.include_secrets)
    _log_success(
        request,
        "terminal.exec",
        target=session_id,
        risk=assessment.risk.value,
        details={
            "command_id": response.command_id,
            "command_count": response.session.command_count,
            "redacted": not payload.include_secrets,
            "approval_bypassed": approval_bypassed,
        },
    )
    return response


@app.post(
    "/terminal/sessions/{session_id}/stdin",
    response_model=TerminalStdinResponse,
    operation_id="terminal_stdin",
    tags=["terminal"],
    dependencies=[Depends(require_auth)],
)
async def terminal_stdin(session_id: str, payload: TerminalStdinRequest, request: Request) -> TerminalStdinResponse:
    response = terminal_manager.stdin(session_id, payload.input)
    _log_success(request, "terminal.stdin", target=session_id, details={"bytes_written": response.bytes_written})
    return response


@app.post(
    "/terminal/sessions/{session_id}/events",
    response_model=TerminalEventsResponse,
    operation_id="terminal_events",
    tags=["terminal"],
    dependencies=[Depends(require_auth)],
)
async def terminal_events(session_id: str, payload: TerminalEventsRequest, request: Request) -> TerminalEventsResponse:
    response = terminal_manager.events(session_id, payload.after_event_id, payload.max_events)
    _log_success(
        request,
        "terminal.events",
        target=session_id,
        details={"event_count": len(response.events), "after_event_id": payload.after_event_id, "status": response.status},
    )
    return response


@app.post(
    "/terminal/sessions/{session_id}/terminate",
    response_model=TerminalTerminateResponse,
    operation_id="terminal_terminate",
    tags=["terminal"],
    dependencies=[Depends(require_auth)],
)
async def terminal_terminate(session_id: str, request: Request) -> TerminalTerminateResponse:
    response = terminal_manager.terminate(session_id)
    _log_success(request, "terminal.terminate", target=session_id, details={"status": response.status})
    return response


@app.get("/jobs/{job_id}", response_model=JobResponse, operation_id="job_get", tags=["jobs"], dependencies=[Depends(require_auth)])
async def job_get(job_id: str, request: Request) -> JobResponse:
    response = job_manager.get(job_id)
    _log_success(request, "job.get", target=job_id, details={"status": response.status})
    return response


@app.post("/jobs/{job_id}/cancel", response_model=JobCancelResponse, operation_id="job_cancel", tags=["jobs"], dependencies=[Depends(require_auth)])
async def job_cancel(job_id: str, request: Request) -> JobCancelResponse:
    response = job_manager.cancel(job_id)
    _log_success(request, "job.cancel", target=job_id, details={"status": response.status})
    return response


@app.get("/system/info", response_model=SystemInfoResponse, operation_id="system_info", tags=["system"], dependencies=[Depends(require_auth)])
async def system_info_endpoint(request: Request) -> SystemInfoResponse:
    response = system_info()
    _log_success(request, "system.info", target=response.hostname)
    return response


@app.post("/process/list", response_model=ProcessListResponse, operation_id="process_list", tags=["process"], dependencies=[Depends(require_auth)])
async def process_list_endpoint(payload: ProcessListRequest, request: Request) -> ProcessListResponse:
    response = list_processes(payload)
    _log_success(request, "process.list", details={"count": len(response.processes), "truncated": response.truncated})
    return response


@app.post("/process/kill", response_model=ProcessKillResponse, operation_id="process_kill", tags=["process"], dependencies=[Depends(require_auth)])
async def process_kill_endpoint(payload: ProcessKillRequest, request: Request) -> ProcessKillResponse:
    approval_bypassed = _enforce_approval(
        request,
        action="process.kill",
        reason="Killing processes can disrupt the system and requires approval.",
        risk=RiskLevel.high,
        approval_id=payload.approval_id,
        payload={"pid": payload.pid, "force": payload.force, "tree": payload.tree},
        target=str(payload.pid),
    )
    response = kill_process(payload)
    _log_success(request, "process.kill", target=str(payload.pid), risk="high", details={"killed": response.killed, "approval_bypassed": approval_bypassed})
    return response


@app.post("/git/status", response_model=GitStatusResponse, operation_id="git_status", tags=["git"], dependencies=[Depends(require_auth)])
async def git_status_endpoint(payload: GitStatusRequest, request: Request) -> GitStatusResponse:
    response = git_status(payload.repo_path)
    _log_success(request, "git.status", target=response.repo_root, details={"clean": response.clean, "files": len(response.files)})
    return response


@app.post("/git/log", response_model=GitLogResponse, operation_id="git_log", tags=["git"], dependencies=[Depends(require_auth)])
async def git_log_endpoint(payload: GitLogRequest, request: Request) -> GitLogResponse:
    response = git_log(payload)
    _log_success(request, "git.log", target=response.repo_root, details={"count": len(response.entries)})
    return response


@app.post("/git/diff", response_model=GitDiffResponse, operation_id="git_diff", tags=["git"], dependencies=[Depends(require_auth)])
async def git_diff_endpoint(payload: GitDiffRequest, request: Request) -> GitDiffResponse:
    response = git_diff(payload)
    _log_success(request, "git.diff", target=response.repo_root, details={"truncated": response.truncated})
    return response


@app.post("/git/branches", response_model=GitBranchesResponse, operation_id="git_branches", tags=["git"], dependencies=[Depends(require_auth)])
async def git_branches_endpoint(payload: GitBranchesRequest, request: Request) -> GitBranchesResponse:
    response = git_branches(payload.repo_path)
    _log_success(request, "git.branches", target=response.repo_root, details={"count": len(response.branches)})
    return response


@app.post("/git/add", response_model=GitAddResponse, operation_id="git_add", tags=["git"], dependencies=[Depends(require_auth)])
async def git_add_endpoint(payload: GitAddRequest, request: Request) -> GitAddResponse:
    response = git_add(payload)
    _log_success(request, "git.add", target=response.repo_root, details={"all": payload.all, "paths": len(payload.paths)})
    return response


@app.post("/git/commit", response_model=GitCommitResponse, operation_id="git_commit", tags=["git"], dependencies=[Depends(require_auth)])
async def git_commit_endpoint(payload: GitCommitRequest, request: Request) -> GitCommitResponse:
    response = git_commit(payload)
    _log_success(request, "git.commit", target=response.repo_root, details={"commit": response.short_commit, "amend": payload.amend})
    return response


@app.post("/git/checkout", response_model=GitCheckoutResponse, operation_id="git_checkout", tags=["git"], dependencies=[Depends(require_auth)])
async def git_checkout_endpoint(payload: GitCheckoutRequest, request: Request) -> GitCheckoutResponse:
    response = git_checkout(payload)
    _log_success(request, "git.checkout", target=response.repo_root, details={"branch": response.branch, "detached": response.detached, "create_branch": payload.create_branch})
    return response


@app.post("/git/reset", response_model=GitResetResponse, operation_id="git_reset", tags=["git"], dependencies=[Depends(require_auth)])
async def git_reset_endpoint(payload: GitResetRequest, request: Request) -> GitResetResponse:
    approval_bypassed = _enforce_approval(
        request,
        action="git.reset",
        reason="Resetting git history can discard or rewrite work and requires approval.",
        risk=RiskLevel.high,
        approval_id=payload.approval_id,
        payload={"repo_path": payload.repo_path, "ref": payload.ref, "mode": payload.mode.value},
        target=payload.repo_path,
    )
    response = git_reset(payload)
    _log_success(request, "git.reset", target=response.repo_root, risk="high", details={"head": response.short_head, "mode": payload.mode.value, "approval_bypassed": approval_bypassed})
    return response


@app.post("/approval/request", response_model=ApprovalRecordModel, operation_id="approval_request", tags=["approval"], dependencies=[Depends(require_auth)])
async def approval_request(payload: ApprovalRequest, request: Request) -> ApprovalRecordModel:
    response = approval_store.create(action=payload.action, reason=payload.reason, risk=payload.risk, payload=payload.payload)
    _log_success(request, "approval.request", target=response.id, risk=payload.risk.value, details={"action": payload.action})
    return response


@app.get("/approval/{approval_id}", response_model=ApprovalRecordModel, operation_id="approval_get", tags=["approval"], dependencies=[Depends(require_auth)])
async def approval_get(approval_id: str, request: Request) -> ApprovalRecordModel:
    response = approval_store.get(approval_id)
    _log_success(request, "approval.get", target=approval_id, risk=response.risk.value, details={"status": response.status.value})
    return response


@app.post(
    "/approval/{approval_id}/approve",
    response_model=ApprovalRecordModel,
    operation_id="approval_approve",
    tags=["approval"],
    dependencies=[Depends(require_auth), Depends(require_approval_key)],
)
async def approval_approve(approval_id: str, payload: ApprovalDecisionRequest, request: Request) -> ApprovalRecordModel:
    response = approval_store.approve(approval_id, payload.note)
    _log_success(request, "approval.approve", target=approval_id, risk=response.risk.value, details={"action": response.action})
    return response


@app.post(
    "/approval/{approval_id}/deny",
    response_model=ApprovalRecordModel,
    operation_id="approval_deny",
    tags=["approval"],
    dependencies=[Depends(require_auth), Depends(require_approval_key)],
)
async def approval_deny(approval_id: str, payload: ApprovalDecisionRequest, request: Request) -> ApprovalRecordModel:
    response = approval_store.deny(approval_id, payload.note)
    _log_success(request, "approval.deny", target=approval_id, risk=response.risk.value, details={"action": response.action})
    return response
