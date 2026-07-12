from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ApprovalStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    denied = "denied"
    consumed = "consumed"


class HealthResponse(StrictModel):
    ok: bool
    auth_configured: bool
    approval_configured: bool
    allow_all: bool
    version: str


class ErrorResponse(StrictModel):
    ok: bool = False
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class FileInfo(StrictModel):
    path: str
    name: str
    is_dir: bool
    size: int | None = None
    modified_at: str | None = None


class FsListRequest(StrictModel):
    path: str
    recursive: bool = False
    include_hidden: bool = False
    max_entries: int = Field(default=200, ge=1, le=5000)


class FsListResponse(StrictModel):
    path: str
    entries: list[FileInfo]
    truncated: bool


class FsReadRequest(StrictModel):
    path: str
    encoding: str = "utf-8"
    max_bytes: int = Field(default=65536, ge=1, le=10_485_760)
    include_secrets: bool = False
    approval_id: str | None = None


class FsReadResponse(StrictModel):
    path: str
    content: str | None = None
    content_base64: str | None = None
    encoding: str
    binary: bool
    bytes_read: int
    truncated: bool
    redactions: int


class FsWriteRequest(StrictModel):
    path: str
    content: str
    encoding: str = "utf-8"
    create_parents: bool = True
    overwrite: bool = False
    append: bool = False
    approval_id: str | None = None


class FsWriteResponse(StrictModel):
    path: str
    bytes_written: int
    mode: Literal["created", "overwritten", "appended"]
    file: FileInfo


class FsReplaceRequest(StrictModel):
    path: str
    old: str
    new: str
    count: int = Field(default=0, ge=0, description="0 means replace every occurrence.")
    encoding: str = "utf-8"
    create_backup: bool = True
    approval_id: str | None = None


class FsReplaceResponse(StrictModel):
    path: str
    replacements: int
    backup_path: str | None
    file: FileInfo


class FsDeleteRequest(StrictModel):
    path: str
    recursive: bool = False
    permanent: bool = False
    approval_id: str | None = None


class FsDeleteResponse(StrictModel):
    path: str
    permanent: bool
    quarantined_path: str | None = None


class FsStatRequest(StrictModel):
    path: str


class FsStatResponse(StrictModel):
    file: FileInfo
    exists: bool


class ArtifactInfo(StrictModel):
    artifact_id: str
    name: str
    size: int
    mime_type: str
    sha256: str
    created_at: str
    source: str
    local_path: str
    managed: bool


class ArtifactCreateTextRequest(StrictModel):
    name: str
    content: str
    mime_type: str = "text/plain"
    encoding: str = "utf-8"


class ArtifactUploadBase64Request(StrictModel):
    name: str
    content_base64: str
    mime_type: str | None = None


class ArtifactFetchUrlRequest(StrictModel):
    url: str
    name: str | None = None
    approval_id: str | None = None


class ArtifactFromPathRequest(StrictModel):
    path: str
    copy_file: bool = Field(default=False, alias="copy")
    name: str | None = None
    approval_id: str | None = None


class ArtifactListRequest(StrictModel):
    max_results: int = Field(default=100, ge=1, le=1000)


class ArtifactListResponse(StrictModel):
    artifacts: list[ArtifactInfo]


class ArtifactWriteToPathRequest(StrictModel):
    path: str
    overwrite: bool = False
    create_parents: bool = True
    approval_id: str | None = None


class ArtifactDeleteRequest(StrictModel):
    approval_id: str | None = None


class ArtifactDeleteResponse(StrictModel):
    artifact_id: str
    deleted: bool
    removed_file: bool


class SearchFilesRequest(StrictModel):
    root: str
    query: str | None = None
    glob: str | None = None
    recursive: bool = True
    include_hidden: bool = False
    max_results: int = Field(default=100, ge=1, le=5000)


class SearchFilesResponse(StrictModel):
    root: str
    results: list[FileInfo]
    truncated: bool


class ContentMatch(StrictModel):
    path: str
    line_number: int
    line: str
    redactions: int


class SearchContentRequest(StrictModel):
    root: str
    pattern: str
    glob: str | None = None
    regex: bool = False
    case_sensitive: bool = False
    recursive: bool = True
    include_hidden: bool = False
    max_results: int = Field(default=100, ge=1, le=1000)
    max_file_bytes: int = Field(default=1_048_576, ge=1024, le=10_485_760)


class SearchContentResponse(StrictModel):
    root: str
    matches: list[ContentMatch]
    truncated: bool


class ShellRunRequest(StrictModel):
    command: str = Field(min_length=1)
    cwd: str | None = None
    shell: Literal["powershell", "cmd"] = "powershell"
    timeout_seconds: float = Field(default=10, ge=0.1, le=300)
    max_output_bytes: int = Field(default=65536, ge=1024, le=1_048_576)
    async_job: bool = False
    include_secrets: bool = False
    approval_id: str | None = None


class ShellRunResponse(StrictModel):
    command: str
    cwd: str | None
    shell: str
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_ms: int
    truncated_stdout: bool
    truncated_stderr: bool
    redactions: int


class TerminalSessionCreateRequest(StrictModel):
    shell: Literal["powershell", "cmd"] = "powershell"
    cwd: str | None = None
    name: str | None = None
    env: dict[str, str] = Field(default_factory=dict)


class TerminalSessionInfo(StrictModel):
    session_id: str
    name: str | None = None
    shell: str
    cwd: str | None
    status: str
    created_at: str
    last_active_at: str
    process_id: int | None = None
    command_count: int


class TerminalSessionListRequest(StrictModel):
    include_exited: bool = True


class TerminalSessionListResponse(StrictModel):
    sessions: list[TerminalSessionInfo]


class TerminalExecRequest(StrictModel):
    command: str = Field(min_length=1)
    include_secrets: bool = False
    approval_id: str | None = None


class TerminalExecResponse(StrictModel):
    session: TerminalSessionInfo
    command_id: str


class TerminalStdinRequest(StrictModel):
    input: str


class TerminalStdinResponse(StrictModel):
    session_id: str
    bytes_written: int


class TerminalEvent(StrictModel):
    event_id: int
    timestamp: str
    stream: Literal["command", "stdin", "stdout", "stderr", "system"]
    text: str


class TerminalEventsRequest(StrictModel):
    after_event_id: int = Field(default=0, ge=0)
    max_events: int = Field(default=100, ge=1, le=1000)


class TerminalEventsResponse(StrictModel):
    session_id: str
    status: str
    events: list[TerminalEvent]
    next_event_id: int


class TerminalTerminateResponse(StrictModel):
    session_id: str
    status: str


class JobStartedResponse(StrictModel):
    job_id: str
    status: str


class JobResponse(StrictModel):
    job_id: str
    status: str
    command: str
    shell: str
    cwd: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    process_id: int | None
    result: ShellRunResponse | None = None
    error: str | None = None


class JobCancelResponse(StrictModel):
    job_id: str
    status: str
    message: str


class SystemInfoResponse(StrictModel):
    os: str
    platform: str
    hostname: str
    user: str
    process_id: int
    python: str
    cwd: str
    is_admin: bool | None


class ProcessInfo(StrictModel):
    pid: int
    name: str
    session_name: str | None = None
    memory: str | None = None


class ProcessListRequest(StrictModel):
    query: str | None = None
    max_results: int = Field(default=200, ge=1, le=5000)


class ProcessListResponse(StrictModel):
    processes: list[ProcessInfo]
    truncated: bool


class ProcessKillRequest(StrictModel):
    pid: int = Field(gt=0)
    force: bool = True
    tree: bool = True
    approval_id: str | None = None


class ProcessKillResponse(StrictModel):
    pid: int
    killed: bool
    stdout: str
    stderr: str


class GitStatusRequest(StrictModel):
    repo_path: str


class GitFileStatus(StrictModel):
    path: str
    index_status: str
    worktree_status: str
    renamed_from: str | None = None


class GitStatusResponse(StrictModel):
    repo_root: str
    branch: str | None
    upstream: str | None = None
    ahead: int = 0
    behind: int = 0
    detached: bool = False
    clean: bool
    files: list[GitFileStatus]


class GitLogRequest(StrictModel):
    repo_path: str
    ref: str | None = None
    max_count: int = Field(default=20, ge=1, le=200)


class GitLogEntry(StrictModel):
    commit: str
    short_commit: str
    author: str
    committed_at: str
    subject: str


class GitLogResponse(StrictModel):
    repo_root: str
    entries: list[GitLogEntry]


class GitDiffRequest(StrictModel):
    repo_path: str
    ref: str | None = None
    cached: bool = False
    paths: list[str] = Field(default_factory=list)
    max_bytes: int = Field(default=65536, ge=1024, le=1_048_576)


class GitDiffResponse(StrictModel):
    repo_root: str
    diff: str
    truncated: bool


class GitBranchesRequest(StrictModel):
    repo_path: str


class GitBranchEntry(StrictModel):
    name: str
    current: bool
    upstream: str | None = None


class GitBranchesResponse(StrictModel):
    repo_root: str
    current_branch: str | None = None
    branches: list[GitBranchEntry]


class GitAddRequest(StrictModel):
    repo_path: str
    paths: list[str] = Field(default_factory=list)
    all: bool = False


class GitAddResponse(StrictModel):
    repo_root: str
    staged_paths: list[str]
    stdout: str
    stderr: str


class GitCommitRequest(StrictModel):
    repo_path: str
    message: str = Field(min_length=1)
    amend: bool = False


class GitCommitResponse(StrictModel):
    repo_root: str
    commit: str
    short_commit: str
    subject: str


class GitCheckoutRequest(StrictModel):
    repo_path: str
    ref: str = Field(min_length=1)
    create_branch: bool = False
    start_point: str | None = None


class GitCheckoutResponse(StrictModel):
    repo_root: str
    branch: str | None
    detached: bool


class GitResetMode(str, Enum):
    soft = "soft"
    mixed = "mixed"
    hard = "hard"


class GitResetRequest(StrictModel):
    repo_path: str
    ref: str = "HEAD~1"
    mode: GitResetMode = GitResetMode.mixed
    approval_id: str | None = None


class GitResetResponse(StrictModel):
    repo_root: str
    head: str
    short_head: str
    subject: str


class ApprovalRequest(StrictModel):
    action: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    risk: RiskLevel = RiskLevel.high
    payload: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecisionRequest(StrictModel):
    note: str | None = None


class ApprovalRecordModel(StrictModel):
    id: str
    action: str
    reason: str
    risk: RiskLevel
    status: ApprovalStatus
    created_at: str
    approved_at: str | None = None
    denied_at: str | None = None
    consumed_at: str | None = None
    note: str | None = None
    payload_summary: dict[str, Any] = Field(default_factory=dict)
