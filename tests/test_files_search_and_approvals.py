from __future__ import annotations


def _approval_id(response) -> str:
    return response.json()["details"]["approval"]["id"]


def test_file_round_trip_search_and_delete(client, auth_headers, approval_headers, tmp_path):
    target = tmp_path / "scratch" / "hello.txt"

    response = client.post(
        "/fs/write",
        headers=auth_headers,
        json={"path": str(target), "content": "hello api_key=sk-abcdefghijklmnopqrstuvwxyz\nsecond line"},
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "created"

    response = client.post("/fs/read", headers=auth_headers, json={"path": str(target)})
    assert response.status_code == 200
    body = response.json()
    assert "[REDACTED]" in body["content"]
    assert body["redactions"] >= 1

    response = client.post(
        "/fs/replace",
        headers=auth_headers,
        json={"path": str(target), "old": "hello", "new": "goodbye", "create_backup": False},
    )
    assert response.status_code == 200
    assert response.json()["replacements"] == 1

    response = client.post("/search/files", headers=auth_headers, json={"root": str(tmp_path), "query": "hello"})
    assert response.status_code == 200
    assert len(response.json()["results"]) == 1

    response = client.post("/search/content", headers=auth_headers, json={"root": str(tmp_path), "pattern": "goodbye"})
    assert response.status_code == 200
    assert response.json()["matches"][0]["line_number"] == 1

    response = client.post("/fs/delete", headers=auth_headers, json={"path": str(target)})
    assert response.status_code == 409
    approval_id = _approval_id(response)

    response = client.post(f"/approval/{approval_id}/approve", headers=approval_headers, json={"note": "test delete"})
    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    response = client.post("/fs/delete", headers=auth_headers, json={"path": str(target), "approval_id": approval_id})
    assert response.status_code == 200
    assert response.json()["quarantined_path"]
    assert not target.exists()


def test_approval_key_is_required(client, auth_headers, tmp_path):
    target = tmp_path / "delete-me.txt"
    target.write_text("x", encoding="utf-8")
    response = client.post("/fs/delete", headers=auth_headers, json={"path": str(target)})
    approval_id = _approval_id(response)

    response = client.post(f"/approval/{approval_id}/approve", headers=auth_headers, json={})
    assert response.status_code == 403


def test_allow_all_skips_delete_approval(monkeypatch, auth_headers, tmp_path):
    monkeypatch.setenv("LOCALCONTROL_API_KEY", "test-token")
    monkeypatch.setenv("LOCALCONTROL_APPROVAL_KEY", "approval-token")
    monkeypatch.setenv("LOCALCONTROL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LOCALCONTROL_RATE_LIMIT_PER_MINUTE", "0")
    monkeypatch.setenv("LOCALCONTROL_ALLOW_ALL", "1")

    from fastapi.testclient import TestClient
    from localcontrol.approvals import approval_store
    from localcontrol.config import get_settings
    from localcontrol.main import app
    from localcontrol.shell_ops import job_manager
    from localcontrol.terminal_ops import terminal_manager

    get_settings.cache_clear()
    approval_store.reset()
    job_manager.reset()
    terminal_manager.reset()

    target = tmp_path / "allow-all-delete.txt"
    target.write_text("x", encoding="utf-8")

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["allow_all"] is True

        response = client.post("/fs/delete", headers=auth_headers, json={"path": str(target)})
        assert response.status_code == 200
        assert response.json()["quarantined_path"]
        assert not target.exists()
