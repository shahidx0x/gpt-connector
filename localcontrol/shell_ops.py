from __future__ import annotations

import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .config import get_settings
from .console import mirror_execution_event
from .errors import LocalControlError
from .models import JobCancelResponse, JobResponse, JobStartedResponse, ShellRunRequest, ShellRunResponse
from .project_ops import project_store
from .redaction import redact_text
from .utils import truncate_text, utc_now_iso


def _command_args(shell: str, command: str) -> list[str]:
    if shell == "cmd":
        exe = shutil.which("cmd.exe") or "cmd.exe"
        return [exe, "/d", "/s", "/c", command]
    exe = shutil.which("powershell.exe") or shutil.which("pwsh") or "powershell.exe"
    if exe.lower().endswith("pwsh"):
        return [exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command]
    return [exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command]


def execute_command(payload: ShellRunRequest) -> ShellRunResponse:
    return job_manager.run_sync(payload)


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
    completed: threading.Event = field(default_factory=threading.Event)
    exception: Exception | None = None


class ShellJobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, _JobRecord] = {}
        self._lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._executor_workers = 0
        self._executor_lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
            self._jobs.clear()
        for job in jobs:
            if job.process and job.process.poll() is None:
                job.process.terminate()
        with self._executor_lock:
            if self._executor:
                self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
            self._executor_workers = 0

    def start(self, payload: ShellRunRequest) -> JobStartedResponse:
        job = _JobRecord(job_id=str(uuid.uuid4()), payload=payload, status="queued", created_at=utc_now_iso())
        with self._lock:
            self._jobs[job.job_id] = job
        self._get_executor().submit(self._run, job.job_id)
        return JobStartedResponse(job_id=job.job_id, status=job.status)

    def stats(self) -> dict[str, int]:
        with self._lock:
            jobs = list(self._jobs.values())
        return {
            "max_workers": get_settings().max_shell_workers,
            "queued": sum(1 for job in jobs if job.status == "queued"),
            "running": sum(1 for job in jobs if job.status == "running"),
            "completed": sum(1 for job in jobs if job.status == "completed"),
            "failed": sum(1 for job in jobs if job.status == "failed"),
            "cancelled": sum(1 for job in jobs if job.status == "cancelled"),
        }

    def _get_executor(self) -> ThreadPoolExecutor:
        workers = get_settings().max_shell_workers
        with self._executor_lock:
            if self._executor and self._executor_workers == workers:
                return self._executor
            if self._executor:
                self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="localcontrol-shell")
            self._executor_workers = workers
            return self._executor

    def run_sync(self, payload: ShellRunRequest) -> ShellRunResponse:
        started = self.start(payload)
        with self._lock:
            job = self._jobs[started.job_id]
        if not job.completed.wait(timeout=payload.timeout_seconds + 10):
            self.cancel(job.job_id)
            raise LocalControlError("shell_job_wait_timeout", "Command worker did not finish cleanly.", status_code=504)
        if job.exception:
            if isinstance(job.exception, LocalControlError):
                raise job.exception
            raise LocalControlError("shell_job_failed", str(job.exception), status_code=500) from job.exception
        if not job.result:
            raise LocalControlError("shell_job_failed", job.error or "Command did not produce a result.", status_code=500)
        return job.result

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
                job.exception = exc
                job.finished_at = utc_now_iso()
                job.process = None
                job.process_id = None
        finally:
            job.completed.set()

    def _execute_job(self, job: _JobRecord) -> ShellRunResponse:
        payload = job.payload
        cwd = project_store.resolve_path(payload.project_id, payload.cwd, require_path=False)
        if cwd and not cwd.is_dir():
            raise LocalControlError("invalid_cwd", "cwd must be an existing directory.", status_code=400)
        args = _command_args(payload.shell, payload.command)
        mirror_execution_event(
            session_id=job.job_id,
            stream="command",
            text=payload.command if payload.include_secrets else redact_text(payload.command)[0],
            shell=payload.shell,
            cwd=str(cwd) if cwd else None,
            source="shell",
        )
        start = time.monotonic()
        timed_out = False
        exit_code: int | None = None
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        try:
            proc = subprocess.Popen(
                args,
                cwd=str(cwd) if cwd else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise LocalControlError("shell_not_found", f"Shell executable not found: {exc}", status_code=500) from exc
        with self._lock:
            job.process = proc
            job.process_id = proc.pid

        def read_stream(stream_name: str, stream_obj, chunks: list[str]) -> None:
            if stream_obj is None:
                return
            while True:
                line = stream_obj.readline()
                if line == "":
                    return
                chunks.append(line)
                text = line if payload.include_secrets else redact_text(line)[0]
                mirror_execution_event(
                    session_id=job.job_id,
                    stream=stream_name,
                    text=text,
                    shell=payload.shell,
                    cwd=str(cwd) if cwd else None,
                    source="shell",
                )

        stdout_thread = threading.Thread(target=read_stream, args=("stdout", proc.stdout, stdout_chunks), daemon=True)
        stderr_thread = threading.Thread(target=read_stream, args=("stderr", proc.stderr, stderr_chunks), daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        try:
            proc.wait(timeout=payload.timeout_seconds)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            proc.wait()
            exit_code = proc.returncode
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)

        stdout = "".join(stdout_chunks)
        stderr = "".join(stderr_chunks)
        redactions = 0
        if not payload.include_secrets:
            stdout, count = redact_text(stdout)
            redactions += count
            stderr, count = redact_text(stderr)
            redactions += count
        stdout, truncated_stdout = truncate_text(stdout, payload.max_output_bytes)
        stderr, truncated_stderr = truncate_text(stderr, payload.max_output_bytes)
        duration_ms = int((time.monotonic() - start) * 1000)
        mirror_execution_event(
            session_id=job.job_id,
            stream="system",
            text=f"exit_code={exit_code} timed_out={timed_out} duration_ms={duration_ms}",
            shell=payload.shell,
            cwd=str(cwd) if cwd else None,
            source="shell",
        )
        return ShellRunResponse(
            job_id=job.job_id,
            project_id=payload.project_id,
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
                project_id=job.payload.project_id,
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
