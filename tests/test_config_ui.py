from __future__ import annotations


def test_config_get_masks_and_reveals_values(client, auth_headers, monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "LOCALCONTROL_PORT=8777",
                "LOCALCONTROL_NGROK_AUTHTOKEN=ngrok-secret-token",
                "LOCALCONTROL_NGROK_DOMAIN=example.ngrok-free.app",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCALCONTROL_CONFIG_ENV_PATH", str(env_path))

    response = client.post("/config/get", headers=auth_headers, json={})
    assert response.status_code == 200
    masked = response.json()
    assert masked["port"] == 8777
    assert masked["api_key"]["configured"] is True
    assert masked["api_key"]["value"] is None
    assert masked["api_key"]["masked"] == "test...oken"
    assert masked["ngrok_authtoken"]["value"] is None
    assert masked["ngrok_authtoken"]["masked"] == "ngro...oken"
    assert masked["ngrok_domain"] == "example.ngrok-free.app"

    response = client.post("/config/get", headers=auth_headers, json={"reveal_secrets": True})
    assert response.status_code == 200
    revealed = response.json()
    assert revealed["api_key"]["value"] == "test-token"
    assert revealed["ngrok_authtoken"]["value"] == "ngrok-secret-token"


def test_config_update_randomizes_api_key_for_current_process(client, auth_headers, monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    monkeypatch.setenv("LOCALCONTROL_CONFIG_ENV_PATH", str(env_path))

    response = client.post(
        "/config/update",
        headers=auth_headers,
        json={"randomize_api_key": True, "reveal_secrets": True},
    )
    assert response.status_code == 200
    payload = response.json()
    generated_key = payload["generated_api_key"]
    assert generated_key
    assert payload["api_key"]["value"] == generated_key
    assert "LOCALCONTROL_API_KEY" in payload["changed_keys"]
    assert "LOCALCONTROL_API_KEY_SHA256" in payload["changed_keys"]
    assert "LOCALCONTROL_API_KEY=" in env_path.read_text(encoding="utf-8")
    assert (tmp_path / "localcontrol-keys.txt").exists()

    old_response = client.get("/system/info", headers=auth_headers)
    assert old_response.status_code == 401

    new_headers = {"Authorization": f"Bearer {generated_key}"}
    new_response = client.get("/system/info", headers=new_headers)
    assert new_response.status_code == 200


def test_config_update_port_reports_restart_required(client, auth_headers, monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    monkeypatch.setenv("LOCALCONTROL_CONFIG_ENV_PATH", str(env_path))

    response = client.post("/config/update", headers=auth_headers, json={"port": 8999})
    assert response.status_code == 200
    payload = response.json()
    assert payload["port"] == 8999
    assert payload["restart_required_keys"] == ["LOCALCONTROL_PORT"]
    assert "LOCALCONTROL_PORT=8999" in env_path.read_text(encoding="utf-8")


def test_ui_index_is_served(client):
    response = client.get("/ui")
    assert response.status_code == 200
    assert "LocalControl" in response.text
    assert "/config/get" in response.text
