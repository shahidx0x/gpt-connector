from __future__ import annotations

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


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "LocalControl Test")
    _git(repo, "config", "user.email", "localcontrol@example.com")


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git is not installed")
def test_git_status_diff_add_commit_checkout_and_log(client, auth_headers, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)

    (repo / "notes.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-m", "initial")

    (repo / "notes.txt").write_text("hello\ngit change\n", encoding="utf-8")

    response = client.post("/git/status", headers=auth_headers, json={"repo_path": str(repo)})
    assert response.status_code == 200
    status_body = response.json()
    assert status_body["clean"] is False
    assert status_body["files"][0]["path"] == "notes.txt"

    response = client.post("/git/diff", headers=auth_headers, json={"repo_path": str(repo)})
    assert response.status_code == 200
    assert "git change" in response.json()["diff"]

    response = client.post("/git/add", headers=auth_headers, json={"repo_path": str(repo), "paths": ["notes.txt"]})
    assert response.status_code == 200

    response = client.post("/git/commit", headers=auth_headers, json={"repo_path": str(repo), "message": "update notes"})
    assert response.status_code == 200
    assert response.json()["subject"] == "update notes"

    response = client.post("/git/log", headers=auth_headers, json={"repo_path": str(repo), "max_count": 2})
    assert response.status_code == 200
    assert response.json()["entries"][0]["subject"] == "update notes"

    response = client.post("/git/checkout", headers=auth_headers, json={"repo_path": str(repo), "ref": "feature/demo", "create_branch": True})
    assert response.status_code == 200
    assert response.json()["branch"] == "feature/demo"

    response = client.post("/git/branches", headers=auth_headers, json={"repo_path": str(repo)})
    assert response.status_code == 200
    assert any(branch["name"] == "feature/demo" and branch["current"] for branch in response.json()["branches"])


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git is not installed")
def test_git_reset_requires_approval(client, auth_headers, approval_headers, tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)

    (repo / "notes.txt").write_text("first\n", encoding="utf-8")
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-m", "first")

    (repo / "notes.txt").write_text("second\n", encoding="utf-8")
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-m", "second")

    response = client.post("/git/reset", headers=auth_headers, json={"repo_path": str(repo), "ref": "HEAD~1", "mode": "hard"})
    assert response.status_code == 409
    approval_id = response.json()["details"]["approval"]["id"]

    response = client.post(f"/approval/{approval_id}/approve", headers=approval_headers, json={"note": "allow reset"})
    assert response.status_code == 200

    response = client.post(
        "/git/reset",
        headers=auth_headers,
        json={"repo_path": str(repo), "ref": "HEAD~1", "mode": "hard", "approval_id": approval_id},
    )
    assert response.status_code == 200
    assert response.json()["subject"] == "first"
