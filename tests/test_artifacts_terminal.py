from __future__ import annotations

import base64
import os
import time

import pytest


def test_text_artifact_write_download_and_delete(client, auth_headers, tmp_path):
    response = client.post(
        "/artifacts/create_text",
        headers=auth_headers,
        json={"name": "note.txt", "content": "hello artifact"},
    )
    assert response.status_code == 200
    artifact = response.json()
    artifact_id = artifact["artifact_id"]
    assert artifact["sha256"]

    response = client.post("/artifacts/list", headers=auth_headers, json={})
    assert response.status_code == 200
    assert any(item["artifact_id"] == artifact_id for item in response.json()["artifacts"])

    target = tmp_path / "out" / "note.txt"
    response = client.post(
        f"/artifacts/{artifact_id}/write_to_path",
        headers=auth_headers,
        json={"path": str(target)},
    )
    assert response.status_code == 200
    assert target.read_text(encoding="utf-8") == "hello artifact"

    response = client.get(f"/artifacts/{artifact_id}/download", headers=auth_headers)
    assert response.status_code == 200
    assert response.content == b"hello artifact"

    response = client.post(f"/artifacts/{artifact_id}/delete", headers=auth_headers, json={})
    assert response.status_code == 200
    assert response.json()["deleted"] is True


def test_artifact_upload_and_overwrite_runs_without_approval(client, auth_headers, tmp_path):
    response = client.post(
        "/artifacts/upload_base64",
        headers=auth_headers,
        json={"name": "binary.bin", "content_base64": base64.b64encode(b"new-bytes").decode("ascii")},
    )
    assert response.status_code == 200
    artifact_id = response.json()["artifact_id"]

    target = tmp_path / "existing.bin"
    target.write_bytes(b"old-bytes")

    response = client.post(
        f"/artifacts/{artifact_id}/write_to_path",
        headers=auth_headers,
        json={"path": str(target), "overwrite": True},
    )
    assert response.status_code == 200
    assert target.read_bytes() == b"new-bytes"


@pytest.mark.skipif(os.name != "nt", reason="terminal sessions target Windows shells")
def test_terminal_session_exec_and_poll_events(client, auth_headers, tmp_path):
    response = client.post(
        "/terminal/sessions",
        headers=auth_headers,
        json={"shell": "cmd", "cwd": str(tmp_path), "name": "pytest-cmd"},
    )
    assert response.status_code == 200
    session_id = response.json()["session_id"]

    response = client.post(
        f"/terminal/sessions/{session_id}/exec",
        headers=auth_headers,
        json={"command": "echo terminal-ok"},
    )
    assert response.status_code == 200

    events = []
    for _ in range(30):
        response = client.post(
            f"/terminal/sessions/{session_id}/events",
            headers=auth_headers,
            json={"after_event_id": 0, "max_events": 100},
        )
        assert response.status_code == 200
        events = response.json()["events"]
        if any("terminal-ok" in event["text"].lower() for event in events):
            break
        time.sleep(0.1)

    assert any(event["stream"] == "command" and "echo terminal-ok" in event["text"] for event in events)
    assert any("terminal-ok" in event["text"].lower() for event in events)

    response = client.post("/execution/logs", headers=auth_headers, json={"run_id": session_id, "max_events": 100})
    assert response.status_code == 200
    log_events = response.json()["events"]
    assert any(event["stream"] == "command" and "echo terminal-ok" in event["text"] for event in log_events)

    response = client.post(f"/terminal/sessions/{session_id}/terminate", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "terminated"


@pytest.mark.skipif(os.name != "nt", reason="terminal sessions target Windows shells")
def test_full_control_terminal_exec_runs_without_approval(client, auth_headers, tmp_path):
    response = client.post(
        "/terminal/sessions",
        headers=auth_headers,
        json={"shell": "cmd", "cwd": str(tmp_path)},
    )
    assert response.status_code == 200
    session_id = response.json()["session_id"]

    response = client.post(
        f"/terminal/sessions/{session_id}/exec",
        headers=auth_headers,
        json={"command": "del C:\\Temp\\not-real-localcontrol.txt"},
    )
    assert response.status_code == 200
    assert response.json()["command_id"]

    client.post(f"/terminal/sessions/{session_id}/terminate", headers=auth_headers)
