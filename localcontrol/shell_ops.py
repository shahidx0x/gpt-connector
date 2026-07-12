from __future__ import annotations

import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass

from .console import mirror_execution_event
from .errors import LocalControlError
from .models import JobCancelResponse, JobResponse, JobStartedResponse, ShellRunRequest, ShellRunResponse
from .redaction import redact_text
from .utils import normalize_path, truncate_text, utc_now_iso


def _command_args(shell: str, command: str) -> list[str]:
    if shell == "cmd":
        exe = shutil.which("cmd.exe") or "cmd.exe"
        return [exe, "/d", "/s", "/c", command]
    exe = shutil.which("powershell.exe") or shutil.which("pwsh") or "powershell.exe"
    if exe.lower().endswith("pwsh"):
        return [exe, "-NoProfile", "-Command", command]
    return [exe, "-NoProfile", "-Command", command]


def execute_command(payload: ShellRunRequest) -> ShellRunResponse:
    cwd = normalize_path(payload.cwd) if payload.cwd else None
    if cwd and not cwd.is_dir():
        raise LocalControlError("invalid_cwd", "cwd must be an existing directory.", status_code=400)

    args = _command_args(payload.shell, payload.command)
    mirror_execution_event(
        session_id="oneshot",
        stream="command",
        text=payload.command if payload.include_secrets else redact_text(payload.command)[0],
        shell=payload.shell,
        cwd=str(cwd) if cwd else None,
    )
    start = time.monotonic()
    timed_out = False
    exit_code: int | None = None
    stdout = ""
    stderr = ""
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=payload.timeout_seconds,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
    except FileNotFoundError as exc:
        raise LocalControlError("shell_not_found", f"Shell executable not found: {exc}", status_code=500) from exc

    redactions = 0
    if not payload.include_secrets:
        stdout, count = redact_text(stdout)
        redactions += count
        stderr, count = redact_text(stderr)
        redactions += count

    stdout, truncated_stdout = truncate_text(stdout, payload.max_output_bytes)
    stderr, truncated_stderr = truncate_text(stderr, payload.max_output_bytes)
    if stdout:
        mirror_execution_event(session_id="oneshot", stream="stdout", text=stdout, shell=payload.shell, cwd=str(cwd) if cwd else None)
    if stderr:
        mirror_execution_event(session_id="oneshot", stream="stderr", text=stderr, shell=payload.shell, cwd=str(cwd) if cwd else None)
    duration_ms = int((time.monotonic() - start) * 1000)
    mirror_execution_event(
        session_id="oneshot",
        stream="system",
        text=f"exit_code={exit_code} timed_out={timed_out} duration_ms={duration_ms}",
        shell=payload.shell,
        cwd=str(cwd) if cwd else None,
    )

    return ShellRunResponse(
        command=payload.command,
        cwd=str(cwd) if cwd else None,
        shell=payload.shell,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        duration_ms=duration_ms,
        truncated_stdout=truncated_stdout,
        truncated_stderr=truncated_stderr,
        redactions=redactions,
    )


@dataclass
class _JobRecord:
    job_id: str
    payload: ShellRunRequest
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    process_id: int | None = None
    result: ShellRunResponse | None = None
    error: str | None = None
    process: subprocess.Popen | None = None
    cancel_requested: bool = False


class ShellJobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, _JobRecord] = {}
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._jobs.clear()

    def start(self, payload: ShellRunRequest) -> JobStartedResponse:
        job = _JobRecord(job_id=str(uuid.uuid4()), payload=payload, status="queued", created_at=utc_now_iso())
        with self._lock:
            self._jobs[job.job_id] = job
        thread = threading.Thread(target=self._run, args=(job.job_id,), daemon=True)
        thread.start()
        return JobStartedResponse(job_id=job.job_id, status=job.status)

    def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
            job.started_at = utc_now_iso()
        try:
            result = self._execute_job(job)
            with self._lock:
                if job.cancel_requested:
                    job.status = "cancelled"
                else:
                    job.status = "completed"
                job.result = result
                job.finished_at = utc_now_iso()
                job.process = None
                job.process_id = None
        except Exception as exc:  # noqa: BLE001 - record unexpected job failures for polling.
            with self._lock:
                job.status = "failed"
                job.error = str(exc)
                job.finished_at = utc_now_iso()
                job.process = None
                job.process_id = None

    def _execute_job(self, job: _JobRecord) -> ShellRunResponse:
        payload = job.payload
        cwd = normalize_path(payload.cwd) if payload.cwd else None
        if cwd and not cwd.is_dir():
            raise LocalControlError("invalid_cwd", "cwd must be an existing directory.", status_code=400)
        args = _command_args(payload.shell, payload.command)
        mirror_execution_event(
            session_id=job.job_id,
            stream="command",
            text=payload.command if payload.include_secrets else redact_text(payload.command)[0],
            shell=payload.shell,
            cwd=str(cwd) if cwd else None,
        )
        start = time.monotonic()
        timed_out = False
        exit_code: int | None = None
        stdout = ""
        stderr = ""

        proc = subprocess.Popen(
            args,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        with self._lock:
            job.process = proc
            job.process_id = proc.pid
        try:
            stdout, stderr = proc.communicate(timeout=payload.timeout_seconds)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            stdout, stderr = proc.communicate()
            exit_code = proc.returncode

        redactions = 0
        if not payload.include_secrets:
            stdout, count = redact_text(stdout)
            redactions += count
            stderr, count = redact_text(stderr)
            redactions += count
        stdout, truncated_stdout = truncate_text(stdout, payload.max_output_bytes)
        stderr, truncated_stderr = truncate_text(stderr, payload.max_output_bytes)
        if stdout:
            mirror_execution_event(session_id=job.job_id, stream="stdout", text=stdout, shell=payload.shell, cwd=str(cwd) if cwd else None)
        if stderr:
            mirror_execution_event(session_id=job.job_id, stream="stderr", text=stderr, shell=payload.shell, cwd=str(cwd) if cwd else None)
        duration_ms = int((time.monotonic() - start) * 1000)
        mirror_execution_event(
            session_id=job.job_id,
            stream="system",
            text=f"exit_code={exit_code} timed_out={timed_out} duration_ms={duration_ms}",
            shell=payload.shell,
            cwd=str(cwd) if cwd else None,
        )
        return ShellRunResponse(
            command=payload.command,
            cwd=str(cwd) if cwd else None,
            shell=payload.shell,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            duration_ms=duration_ms,
            truncated_stdout=truncated_stdout,
            truncated_stderr=truncated_stderr,
            redactions=redactions,
        )

    def get(self, job_id: str) -> JobResponse:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise LocalControlError("job_not_found", "Job was not found.", status_code=404)
            return JobResponse(
                job_id=job.job_id,
                status=job.status,
                command=job.payload.command,
                shell=job.payload.shell,
                cwd=job.payload.cwd,
                created_at=job.created_at,
                started_at=job.started_at,
                finished_at=job.finished_at,
                process_id=job.process_id,
                result=job.result,
                error=job.error,
            )

    def cancel(self, job_id: str) -> JobCancelResponse:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise LocalControlError("job_not_found", "Job was not found.", status_code=404)
            if job.status not in {"queued", "running"}:
                return JobCancelResponse(job_id=job_id, status=job.status, message="Job is not running.")
            job.cancel_requested = True
            process = job.process
            job.status = "cancelled"
        if process and process.poll() is None:
            process.terminate()
        return JobCancelResponse(job_id=job_id, status="cancelled", message="Cancellation requested.")


job_manager = ShellJobManager()
