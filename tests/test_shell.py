from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor


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


def test_health_remains_responsive_while_sync_shell_waits(client, auth_headers, monkeypatch):
    from localcontrol.api.routes import shell as shell_route

    original_execute = shell_route.execute_command
    command_started = threading.Event()
    release_command = threading.Event()

    def delayed_execute(payload):
        command_started.set()
        release_command.wait(timeout=2)
        return original_execute(payload)

    monkeypatch.setattr(shell_route, "execute_command", delayed_execute)
    release_timer = threading.Timer(1, release_command.set)
    release_timer.start()

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            shell_future = executor.submit(
                client.post,
                "/shell/run",
                headers=auth_headers,
                json=_echo_payload("responsive"),
            )
            assert command_started.wait(timeout=1)

            started_at = time.monotonic()
            health_response = client.get("/health")
            health_elapsed = time.monotonic() - started_at

            assert health_response.status_code == 200
            assert health_elapsed < 0.75
            assert shell_future.result(timeout=3).status_code == 200
    finally:
        release_command.set()
        release_timer.cancel()
