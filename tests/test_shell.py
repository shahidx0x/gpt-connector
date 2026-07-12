from __future__ import annotations

import os


def _echo_payload(text: str) -> dict:
    if os.name == "nt":
        return {"shell": "cmd", "command": f"echo {text}", "timeout_seconds": 5}
    return {"shell": "powershell", "command": f"echo {text}", "timeout_seconds": 5}


def test_shell_run(client, auth_headers):
    response = client.post("/shell/run", headers=auth_headers, json=_echo_payload("hello"))
    assert response.status_code == 200
    body = response.json()
    assert body["exit_code"] == 0
    assert "hello" in body["stdout"].lower()


def test_shell_timeout(client, auth_headers):
    if os.name == "nt":
        payload = {"shell": "cmd", "command": "ping -n 3 127.0.0.1 > nul", "timeout_seconds": 0.5}
    else:
        payload = {"shell": "powershell", "command": "Start-Sleep -Seconds 2", "timeout_seconds": 0.5}
    response = client.post("/shell/run", headers=auth_headers, json=payload)
    assert response.status_code == 200
    assert response.json()["timed_out"] is True


def test_risky_shell_requires_approval(client, auth_headers):
    response = client.post(
        "/shell/run",
        headers=auth_headers,
        json={"shell": "powershell", "command": "Remove-Item C:\\Temp\\not-real.txt", "timeout_seconds": 5},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "approval_required"


def test_async_job(client, auth_headers):
    response = client.post("/shell/run", headers=auth_headers, json={**_echo_payload("async-ok"), "async_job": True})
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    response = client.get(f"/jobs/{job_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] in {"queued", "running", "completed"}
