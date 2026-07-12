from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import LocalControlError
from .models import (
    GitAddRequest,
    GitAddResponse,
    GitBranchEntry,
    GitBranchesResponse,
    GitCheckoutRequest,
    GitCheckoutResponse,
    GitCommitRequest,
    GitCommitResponse,
    GitDiffRequest,
    GitDiffResponse,
    GitFileStatus,
    GitLogEntry,
    GitLogRequest,
    GitLogResponse,
    GitResetRequest,
    GitResetResponse,
    GitStatusResponse,
)
from .utils import normalize_path, truncate_text


@dataclass
class _GitResult:
    stdout: str
    stderr: str
    returncode: int


def _repo_root(repo_path: str) -> Path:
    path = normalize_path(repo_path)
    target = path if path.is_dir() else path.parent
    try:
        completed = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except FileNotFoundError as exc:
        raise LocalControlError("git_not_found", "git executable was not found on this system.", status_code=500) from exc
    except subprocess.TimeoutExpired as exc:
        raise LocalControlError("git_timeout", f"git repo discovery timed out: {exc}", status_code=504) from exc

    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "Path is not inside a git repository."
        raise LocalControlError(
            "git_repo_not_found",
            message,
            status_code=400,
            details={"repo_path": str(path)},
        )
    return Path(completed.stdout.strip()).resolve(strict=False)


def _run_git(repo_root: Path, args: list[str], *, timeout: int = 20, status_code: int = 400) -> _GitResult:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise LocalControlError("git_not_found", "git executable was not found on this system.", status_code=500) from exc
    except subprocess.TimeoutExpired as exc:
        raise LocalControlError("git_timeout", f"git command timed out: {exc}", status_code=504, details={"args": args}) from exc

    result = _GitResult(stdout=completed.stdout, stderr=completed.stderr, returncode=completed.returncode)
    if result.returncode != 0:
        text = result.stderr.strip() or result.stdout.strip() or "git command failed."
        code = "git_command_failed"
        current_status = status_code
        if "nothing to commit" in text.lower():
            code = "git_nothing_to_commit"
            current_status = 409
        raise LocalControlError(
            code,
            text,
            status_code=current_status,
            details={"args": args, "stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode},
        )
    return result


def _head_state(repo_root: Path) -> tuple[str | None, bool]:
    branch_result = _run_git(repo_root, ["branch", "--show-current"])
    branch = branch_result.stdout.strip() or None
    return branch, branch is None


def git_status(repo_path: str) -> GitStatusResponse:
    repo_root = _repo_root(repo_path)
    result = _run_git(repo_root, ["status", "--porcelain=v1", "-b"])
    lines = result.stdout.splitlines()

    branch: str | None = None
    upstream: str | None = None
    ahead = 0
    behind = 0
    detached = False
    files: list[GitFileStatus] = []

    if lines and lines[0].startswith("## "):
        branch_info = lines[0][3:]
        if branch_info.startswith("HEAD "):
            detached = True
        else:
            head_part = branch_info
            counts = ""
            if " [" in branch_info:
                head_part, counts = branch_info.split(" [", 1)
                counts = counts.rstrip("]")
            if "..." in head_part:
                branch, upstream = head_part.split("...", 1)
            else:
                branch = head_part
            if counts:
                for item in counts.split(", "):
                    if item.startswith("ahead "):
                        ahead = int(item.split()[1])
                    elif item.startswith("behind "):
                        behind = int(item.split()[1])

    for line in lines[1:]:
        if len(line) < 4:
            continue
        index_status = line[0]
        worktree_status = line[1]
        payload = line[3:]
        renamed_from = None
        path = payload
        if " -> " in payload:
            renamed_from, path = payload.split(" -> ", 1)
        files.append(
            GitFileStatus(
                path=path,
                index_status=index_status,
                worktree_status=worktree_status,
                renamed_from=renamed_from,
            )
        )

    return GitStatusResponse(
        repo_root=str(repo_root),
        branch=branch,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        detached=detached,
        clean=len(files) == 0,
        files=files,
    )


def git_log(payload: GitLogRequest) -> GitLogResponse:
    repo_root = _repo_root(payload.repo_path)
    args = [
        "log",
        f"--max-count={payload.max_count}",
        "--date=iso-strict",
        "--pretty=format:%H%x1f%h%x1f%an%x1f%ad%x1f%s%x1e",
    ]
    if payload.ref:
        args.append(payload.ref)
    result = _run_git(repo_root, args)
    entries: list[GitLogEntry] = []
    for chunk in result.stdout.strip("\n\x1e").split("\x1e"):
        if not chunk.strip():
            continue
        parts = chunk.split("\x1f")
        if len(parts) != 5:
            continue
        entries.append(
            GitLogEntry(
                commit=parts[0],
                short_commit=parts[1],
                author=parts[2],
                committed_at=parts[3],
                subject=parts[4],
            )
        )
    return GitLogResponse(repo_root=str(repo_root), entries=entries)


def git_diff(payload: GitDiffRequest) -> GitDiffResponse:
    repo_root = _repo_root(payload.repo_path)
    args = ["diff"]
    if payload.cached:
        args.append("--cached")
    if payload.ref:
        args.append(payload.ref)
    if payload.paths:
        args.append("--")
        args.extend(payload.paths)
    result = _run_git(repo_root, args)
    diff, truncated = truncate_text(result.stdout, payload.max_bytes)
    return GitDiffResponse(repo_root=str(repo_root), diff=diff, truncated=truncated)


def git_branches(repo_path: str) -> GitBranchesResponse:
    repo_root = _repo_root(repo_path)
    result = _run_git(repo_root, ["branch", "--format=%(HEAD)|%(refname:short)|%(upstream:short)"])
    branches: list[GitBranchEntry] = []
    current_branch: str | None = None
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        head, name, upstream = (line.split("|", 2) + ["", ""])[:3]
        current = head.strip() == "*"
        if current:
            current_branch = name
        branches.append(GitBranchEntry(name=name, current=current, upstream=upstream or None))
    return GitBranchesResponse(repo_root=str(repo_root), current_branch=current_branch, branches=branches)


def git_add(payload: GitAddRequest) -> GitAddResponse:
    repo_root = _repo_root(payload.repo_path)
    if not payload.all and not payload.paths:
        raise LocalControlError("git_add_empty", "Provide paths or set all=true for git add.", status_code=422)
    args = ["add"]
    if payload.all:
        args.append("--all")
    else:
        args.extend(payload.paths)
    result = _run_git(repo_root, args)
    return GitAddResponse(
        repo_root=str(repo_root),
        staged_paths=list(payload.paths),
        stdout=result.stdout,
        stderr=result.stderr,
    )


def git_commit(payload: GitCommitRequest) -> GitCommitResponse:
    repo_root = _repo_root(payload.repo_path)
    args = ["commit", "-m", payload.message]
    if payload.amend:
        args.append("--amend")
    _run_git(repo_root, args, status_code=409)
    entry = git_log(GitLogRequest(repo_path=str(repo_root), max_count=1)).entries[0]
    return GitCommitResponse(repo_root=str(repo_root), commit=entry.commit, short_commit=entry.short_commit, subject=entry.subject)


def git_checkout(payload: GitCheckoutRequest) -> GitCheckoutResponse:
    repo_root = _repo_root(payload.repo_path)
    if payload.create_branch:
        args = ["checkout", "-b", payload.ref]
        if payload.start_point:
            args.append(payload.start_point)
    else:
        args = ["checkout", payload.ref]
    _run_git(repo_root, args)
    branch, detached = _head_state(repo_root)
    return GitCheckoutResponse(repo_root=str(repo_root), branch=branch, detached=detached)


def git_reset(payload: GitResetRequest) -> GitResetResponse:
    repo_root = _repo_root(payload.repo_path)
    _run_git(repo_root, ["reset", f"--{payload.mode.value}", payload.ref])
    entry = git_log(GitLogRequest(repo_path=str(repo_root), max_count=1)).entries[0]
    return GitResetResponse(repo_root=str(repo_root), head=entry.commit, short_head=entry.short_commit, subject=entry.subject)
