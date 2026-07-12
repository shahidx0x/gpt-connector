from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from .config import get_settings
from .console import mirror_execution_event
from .errors import LocalControlError
from .models import (
    TerminalEvent,
    TerminalEventsResponse,
    TerminalExecResponse,
    TerminalSessionCreateRequest,
    TerminalSessionInfo,
    TerminalSessionListResponse,
    TerminalStdinResponse,
    TerminalTerminateResponse,
)
from .redaction import redact_text
from .utils import normalize_path, utc_now_iso


def _shell_args(shell: str) -> list[str]:
    if shell == "cmd":
        return [shutil.which("cmd.exe") or "cmd.exe", "/Q", "/K"]
    exe = shutil.which("powershell.exe") or shutil.which("pwsh") or "powershell.exe"
    return [exe, "-NoLogo", "-NoProfile", "-NoExit", "-Command", "-"]


@dataclass
class _TerminalSession:
    session_id: str
    shell: str
    cwd: str | None
    name: str | None
    process: subprocess.Popen
    created_at: str
    last_active_at: str
    events: deque[TerminalEvent] = field(default_factory=deque)
    next_event_id: int = 1
    event_bytes: int = 0
    history: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    status: str = "running"
    redact_output: bool = True


class TerminalSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, _TerminalSession] = {}
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            self._terminate_process(session)

    def create(self, payload: TerminalSessionCreateRequest) -> TerminalSessionInfo:
        self._prune_idle()
        with self._lock:
            active_count = sum(1 for session in self._sessions.values() if session.status == "running")
            if active_count >= get_settings().max_terminal_sessions:
                raise LocalControlError("terminal_session_limit", "Maximum active terminal sessions reached.", status_code=429)

        cwd_path = normalize_path(payload.cwd) if payload.cwd else None
        if cwd_path and not cwd_path.is_dir():
            raise LocalControlError("invalid_cwd", "cwd must be an existing directory.", status_code=400)
        env = os.environ.copy()
        env.update(payload.env)
        try:
            process = subprocess.Popen(
                _shell_args(payload.shell),
                cwd=str(cwd_path) if cwd_path else None,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
        except FileNotFoundError as exc:
            raise LocalControlError("shell_not_found", f"Shell executable not found: {exc}", status_code=500) from exc

        session = _TerminalSession(
            session_id=str(uuid.uuid4()),
            shell=payload.shell,
            cwd=str(cwd_path) if cwd_path else None,
            name=payload.name,
            process=process,
            created_at=utc_now_iso(),
            last_active_at=utc_now_iso(),
        )
        with self._lock:
            self._sessions[session.session_id] = session
        self._append_event(session, "system", f"session started pid={process.pid}")
        threading.Thread(target=self._read_stream, args=(session.session_id, "stdout", process.stdout), daemon=True).start()
        threading.Thread(target=self._read_stream, args=(session.session_id, "stderr", process.stderr), daemon=True).start()
        return self._info(session)

    def list(self, include_exited: bool) -> TerminalSessionListResponse:
        self._prune_idle()
        with self._lock:
            sessions = list(self._sessions.values())
        infos = [self._info(session) for session in sessions if include_exited or session.status == "running"]
        return TerminalSessionListResponse(sessions=infos)

    def get(self, session_id: str) -> TerminalSessionInfo:
        return self._info(self._get(session_id))

    def exec(self, session_id: str, command: str, include_secrets: bool = False) -> TerminalExecResponse:
        session = self._get(session_id)
        if session.status != "running" or session.process.poll() is not None:
            session.status = "exited"
            raise LocalControlError("terminal_session_exited", "Terminal session is not running.", status_code=409)
        text = command if include_secrets else redact_text(command)[0]
        command_id = str(uuid.uuid4())
        with session.lock:
            session.redact_output = not include_secrets
            session.history.append(command)
            session.last_active_at = utc_now_iso()
        self._append_event(session, "command", f"{text}\n# command_id={command_id}", redact=False)
        assert session.process.stdin is not None
        session.process.stdin.write(command + "\n")
        session.process.stdin.flush()
        return TerminalExecResponse(session=self._info(session), command_id=command_id)

    def stdin(self, session_id: str, text: str) -> TerminalStdinResponse:
        session = self._get(session_id)
        if session.status != "running" or session.process.poll() is not None:
            session.status = "exited"
            raise LocalControlError("terminal_session_exited", "Terminal session is not running.", status_code=409)
        assert session.process.stdin is not None
        session.process.stdin.write(text)
        session.process.stdin.flush()
        self._append_event(session, "stdin", redact_text(text)[0], redact=False)
        with session.lock:
            session.last_active_at = utc_now_iso()
        return TerminalStdinResponse(session_id=session_id, bytes_written=len(text.encode("utf-8")))

    def events(self, session_id: str, after_event_id: int, max_events: int) -> TerminalEventsResponse:
        session = self._get(session_id)
        if session.process.poll() is not None and session.status == "running":
            session.status = "exited"
            self._append_event(session, "system", f"session exited code={session.process.returncode}")
        with session.lock:
            events = [event for event in session.events if event.event_id > after_event_id][:max_events]
            next_event_id = session.next_event_id
            status = session.status
        return TerminalEventsResponse(session_id=session_id, status=status, events=events, next_event_id=next_event_id)

    def terminate(self, session_id: str) -> TerminalTerminateResponse:
        session = self._get(session_id)
        self._terminate_process(session)
        session.status = "terminated"
        self._append_event(session, "system", "session terminated")
        return TerminalTerminateResponse(session_id=session_id, status=session.status)

    def _get(self, session_id: str) -> _TerminalSession:
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            raise LocalControlError("terminal_session_not_found", "Terminal session was not found.", status_code=404)
        return session

    def _info(self, session: _TerminalSession) -> TerminalSessionInfo:
        if session.process.poll() is not None and session.status == "running":
            session.status = "exited"
        with session.lock:
            command_count = len(session.history)
            last_active_at = session.last_active_at
        return TerminalSessionInfo(
            session_id=session.session_id,
            name=session.name,
            shell=session.shell,
            cwd=session.cwd,
            status=session.status,
            created_at=session.created_at,
            last_active_at=last_active_at,
            process_id=session.process.pid if session.status == "running" else None,
            command_count=command_count,
        )

    def _append_event(self, session: _TerminalSession, stream: str, text: str, *, redact: bool | None = None) -> None:
        if redact is None:
            with session.lock:
                redact = session.redact_output
        redacted = redact_text(text)[0] if redact else text
        event = TerminalEvent(event_id=session.next_event_id, timestamp=utc_now_iso(), stream=stream, text=redacted)
        with session.lock:
            session.events.append(event)
            session.next_event_id += 1
            session.event_bytes += len(redacted.encode("utf-8"))
            limit = get_settings().terminal_event_buffer_bytes
            while session.events and session.event_bytes > limit:
                removed = session.events.popleft()
                session.event_bytes -= len(removed.text.encode("utf-8"))
            session.last_active_at = utc_now_iso()
        mirror_execution_event(session_id=session.session_id, stream=stream, text=redacted, shell=session.shell, cwd=session.cwd)

    def _read_stream(self, session_id: str, stream: str, stream_obj) -> None:
        if stream_obj is None:
            return
        while True:
            try:
                line = stream_obj.readline()
            except ValueError:
                return
            if line == "":
                session = self._sessions.get(session_id)
                if session and session.process.poll() is not None:
                    return
                time.sleep(0.05)
                continue
            session = self._sessions.get(session_id)
            if not session:
                return
            self._append_event(session, stream, line)

    def _terminate_process(self, session: _TerminalSession) -> None:
        if session.process.poll() is None:
            session.process.terminate()
            try:
                session.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                session.process.kill()

    def _prune_idle(self) -> None:
        timeout = get_settings().terminal_idle_timeout_seconds
        cutoff = time.time() - timeout
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            if session.status != "running":
                continue
            try:
                parsed = datetime.fromisoformat(session.last_active_at).timestamp()
            except ValueError:
                continue
            if parsed < cutoff:
                self.terminate(session.session_id)


terminal_manager = TerminalSessionManager()
