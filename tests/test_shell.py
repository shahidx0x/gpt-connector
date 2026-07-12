from __future__ import annotations

import os
import time


def _echo_payload(text: str) -> dict:
    if os.name == "nt":
        return {"shell": "cmd", "command": f"echo {text}", "timeout_seconds": 5}
    return {"shell": "bash", "command": f"echo {text}", "timeout_seconds": 5}


def test_shell_run(client, auth_headers):
    response = client.post("/shell/run", headers=auth_headers, json=_echo_payload("hello"))
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"]
    assert body["exit_code"] == 0
    assert "hello" in body["stdout"].lower()

    response = client.post("/execution/logs", headers=auth_headers, json={"run_id": body["job_id"], "max_events": 20})
    assert response.status_code == 200
    events = response.json()["events"]
    assert any(event["stream"] == "command" for event in events)
    assert any(event["stream"] == "stdout" and "hello" in event["text"].lower() for event in events)


def test_shell_timeout(client, auth_headers):
    if os.name == "nt":
        payload = {"shell": "cmd", "command": "ping -n 3 127.0.0.1 > nul", "timeout_seconds": 0.5}
    else:
        payload = {"shell": "bash", "command": "sleep 2", "timeout_seconds": 0.5}
    response = client.post("/shell/run", headers=auth_headers, json=payload)
    assert response.status_code == 200
    assert response.json()["timed_out"] is True


def test_full_control_shell_runs_without_approval(client, auth_headers):
    if os.name == "nt":
        payload = {"shell": "powershell", "command": "Remove-Item C:\\Temp\\not-real.txt", "timeout_seconds": 5}
    else:
        payload = {"shell": "bash", "command": "rm -f /tmp/not-real-gpt-connect.txt", "timeout_seconds": 5}
    response = client.post(
        "/shell/run",
        headers=auth_headers,
        json=payload,
    )
    assert response.status_code == 200
    assert response.json()["job_id"]


def test_async_job(client, auth_headers):
    response = client.post("/shell/run", headers=auth_headers, json={**_echo_payload("async-ok"), "async_job": True})
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    response = client.get(f"/jobs/{job_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] in {"queued", "running", "completed"}

    events = []
    for _ in range(20):
        response = client.post("/execution/logs", headers=auth_headers, json={"run_id": job_id, "max_events": 20})
        assert response.status_code == 200
        events = response.json()["events"]
        if events:
            break
        time.sleep(0.05)
    assert events
