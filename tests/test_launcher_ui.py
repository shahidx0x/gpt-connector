from __future__ import annotations


def test_prelaunch_save_generates_api_key_when_missing(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    monkeypatch.setenv("LOCALCONTROL_CONFIG_ENV_PATH", str(env_path))
    monkeypatch.delenv("LOCALCONTROL_API_KEY", raising=False)
    monkeypatch.delenv("LOCALCONTROL_API_KEY_SHA256", raising=False)
    monkeypatch.delenv("LOCALCONTROL_PORT", raising=False)
    monkeypatch.delenv("LOCALCONTROL_NGROK_AUTHTOKEN", raising=False)
    monkeypatch.delenv("LOCALCONTROL_NGROK_DOMAIN", raising=False)
    monkeypatch.delenv("LOCALCONTROL_PUBLIC_URL", raising=False)

    from localcontrol.config import get_settings
    from localcontrol.launcher_ui import _handle_save

    get_settings.cache_clear()
    result = _handle_save({"mode": "tunnel", "port": 8765})

    assert result["generated_api_key"]
    assert result["api_key"]["value"] == result["generated_api_key"]
    assert "LOCALCONTROL_API_KEY=" in env_path.read_text(encoding="utf-8")
    assert (tmp_path / "localcontrol-keys.txt").exists()
