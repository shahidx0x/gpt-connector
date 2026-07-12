from __future__ import annotations

import os


def test_project_register_list_and_shell_context(client, auth_headers, tmp_path):
    project = tmp_path / "alpha"
    project.mkdir()
    (project / "marker.txt").write_text("project-marker", encoding="utf-8")

    response = client.post(
        "/projects/register",
        headers=auth_headers,
        json={"path": str(project), "project_id": "alpha", "name": "Alpha Project"},
    )
    assert response.status_code == 200
    assert response.json()["project_id"] == "alpha"

    response = client.post("/projects/list", headers=auth_headers)
    assert response.status_code == 200
    assert any(item["project_id"] == "alpha" for item in response.json()["projects"])

    response = client.post("/search/content", headers=auth_headers, json={"project_id": "alpha", "pattern": "project-marker"})
    assert response.status_code == 200
    assert response.json()["matches"][0]["path"].endswith("marker.txt")

    if os.name == "nt":
        payload = {"project_id": "alpha", "shell": "cmd", "command": "cd", "timeout_seconds": 5}
    else:
        payload = {"project_id": "alpha", "shell": "bash", "command": "pwd", "timeout_seconds": 5}
    response = client.post("/shell/run", headers=auth_headers, json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == "alpha"
    assert body["cwd"] == str(project)
