from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

GIT_AVAILABLE = shutil.which("git") is not None


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git is not installed")
def test_git_runs_through_shell_with_project_context(client, auth_headers, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "LocalControl Test")
    _git(repo, "config", "user.email", "localcontrol@example.com")
    (repo / "notes.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-m", "initial")
    (repo / "notes.txt").write_text("hello\nchanged\n", encoding="utf-8")

    response = client.post(
        "/projects/register",
        headers=auth_headers,
        json={"project_id": "git-repo", "path": str(repo), "name": "Git Repo"},
    )
    assert response.status_code == 200

    command = "git status --short" if os.name == "nt" else "git status --short"
    shell = "cmd" if os.name == "nt" else "powershell"
    response = client.post(
        "/shell/run",
        headers=auth_headers,
        json={"project_id": "git-repo", "shell": shell, "command": command, "timeout_seconds": 10},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["exit_code"] == 0
    assert "notes.txt" in body["stdout"]
