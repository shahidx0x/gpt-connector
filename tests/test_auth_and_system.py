from __future__ import annotations


def test_auth_required(client):
    response = client.get("/system/info")
    assert response.status_code == 401


def test_system_info(client, auth_headers):
    response = client.get("/system/info", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["hostname"]
    assert body["process_id"] > 0
    assert body is not None


def test_openapi_is_protected_and_available(client, auth_headers):
    assert client.get("/openapi.json").status_code == 401
    response = client.get("/openapi.json", headers=auth_headers)
    assert response.status_code == 200
    schema = response.json()
    assert "/fs/read" in schema["paths"]
    assert "/shell/run" in schema["paths"]


def test_gpt_actions_yaml_is_public(client):
    response = client.get("/gpt-actions.openapi.yaml")
    assert response.status_code == 200
    assert "application/yaml" in response.headers["content-type"]
    assert b"Windows LocalControl GPT Actions" in response.content


def test_curated_gpt_schema_stays_under_30_operations():
    from scripts.export_openapi import MAX_GPT_ACTION_OPERATIONS, build_schema

    schema = build_schema("https://oblong-bonus-retrace.ngrok-free.dev")
    operation_count = sum(len(methods) for methods in schema["paths"].values())
    assert operation_count <= MAX_GPT_ACTION_OPERATIONS
    assert "/terminal/sessions/{session_id}/exec" in schema["paths"]
    assert "/execution/logs" in schema["paths"]
    assert "/projects/register" in schema["paths"]
    assert "/projects/list" in schema["paths"]
    assert "/artifacts/fetch_url" in schema["paths"]
    assert "/artifacts/upload_base64" not in schema["paths"]
    assert "/artifacts/{artifact_id}/download" not in schema["paths"]
    assert "/artifacts/{artifact_id}/delete" not in schema["paths"]
    assert "/process/kill" not in schema["paths"]
    assert not any(path.startswith("/git/") for path in schema["paths"])


def test_health_reports_full_control_mode(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["allow_all"] is True
    assert response.json()["full_control"] is True
    assert response.json()["cpu_count"] >= 1
    assert response.json()["max_shell_workers"] >= 1
