from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


@pytest.fixture()
def approval_headers(auth_headers: dict[str, str]) -> dict[str, str]:
    return {**auth_headers, "X-LocalControl-Approval-Key": "approval-token"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("LOCALCONTROL_API_KEY", "test-token")
    monkeypatch.setenv("LOCALCONTROL_APPROVAL_KEY", "approval-token")
    monkeypatch.setenv("LOCALCONTROL_CONFIG_ENV_PATH", str(tmp_path / ".env"))
    monkeypatch.setenv("LOCALCONTROL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LOCALCONTROL_RATE_LIMIT_PER_MINUTE", "0")

    from localcontrol.approvals import approval_store
    from localcontrol.config import get_settings
    from localcontrol.execution_log import execution_log
    from localcontrol.project_ops import project_store
    from localcontrol.shell_ops import job_manager
    from localcontrol.terminal_ops import terminal_manager

    get_settings.cache_clear()
    approval_store.reset()
    execution_log.reset()
    project_store.reset()
    job_manager.reset()
    terminal_manager.reset()

    from localcontrol.main import app

    with TestClient(app) as test_client:
        yield test_client
