from __future__ import annotations

import csv
import io
import os
import signal
import subprocess

from .errors import LocalControlError
from .models import ProcessInfo, ProcessKillRequest, ProcessKillResponse, ProcessListRequest, ProcessListResponse
from .utils import truncate_text


def list_processes(payload: ProcessListRequest) -> ProcessListResponse:
    query = payload.query.lower() if payload.query else None
    processes: list[ProcessInfo] = []
    truncated = False

    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if completed.returncode != 0:
            raise LocalControlError("process_list_failed", completed.stderr.strip() or "tasklist failed.", status_code=500)
        for row in csv.reader(io.StringIO(completed.stdout)):
            if len(row) < 5:
                continue
            name, pid_raw, session_name, _session_number, memory = row[:5]
            if query and query not in name.lower():
                continue
            try:
                pid = int(pid_raw)
            except ValueError:
                continue
            processes.append(ProcessInfo(pid=pid, name=name, session_name=session_name, memory=memory))
            if len(processes) >= payload.max_results:
                truncated = True
                break
    else:
        completed = subprocess.run(
            ["ps", "-eo", "pid=,comm=,rss="],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if completed.returncode != 0:
            raise LocalControlError("process_list_failed", completed.stderr.strip() or "ps failed.", status_code=500)
        for line in completed.stdout.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) < 2:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue
            name = parts[1]
            memory = f"{parts[2]} KiB" if len(parts) > 2 else None
            if query and query not in name.lower():
                continue
            processes.append(ProcessInfo(pid=pid, name=name, memory=memory))
            if len(processes) >= payload.max_results:
                truncated = True
                break

    return ProcessListResponse(processes=processes, truncated=truncated)


def kill_process(payload: ProcessKillRequest) -> ProcessKillResponse:
    if os.name == "nt":
        args = ["taskkill", "/PID", str(payload.pid)]
        if payload.force:
            args.append("/F")
        if payload.tree:
            args.append("/T")
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        stdout, _ = truncate_text(completed.stdout, 8192)
        stderr, _ = truncate_text(completed.stderr, 8192)
        return ProcessKillResponse(pid=payload.pid, killed=completed.returncode == 0, stdout=stdout, stderr=stderr)

    signal_to_send = signal.SIGKILL if payload.force else signal.SIGTERM
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    target_pids = [payload.pid]
    if payload.tree:
        target_pids = [*list(_descendant_pids(payload.pid)), payload.pid]

    for pid in target_pids:
        try:
            os.kill(pid, signal_to_send)
            stdout_lines.append(f"sent {signal_to_send.name} to pid {pid}")
        except ProcessLookupError:
            if pid == payload.pid:
                raise LocalControlError("process_not_found", "Process was not found.", status_code=404) from None
        except PermissionError:
            if pid == payload.pid:
                raise LocalControlError("permission_denied", "Permission denied killing process.", status_code=403) from None
            stderr_lines.append(f"permission denied killing child pid {pid}")
    return ProcessKillResponse(pid=payload.pid, killed=True, stdout="\n".join(stdout_lines), stderr="\n".join(stderr_lines))


def _descendant_pids(pid: int) -> list[int]:
    try:
        completed = subprocess.run(
            ["pgrep", "-P", str(pid)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    children: list[int] = []
    for raw in completed.stdout.split():
        try:
            child = int(raw)
        except ValueError:
            continue
        children.extend(_descendant_pids(child))
        children.append(child)
    return children
