from __future__ import annotations

import functools
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or (Path.cwd() / ".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _strip_quotes(value)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_key_hash: str | None
    approval_key_hash: str | None
    bind_host: str
    port: int
    data_dir: Path
    audit_log_path: Path
    quarantine_dir: Path
    rate_limit_per_minute: int
    max_response_bytes: int
    default_shell_timeout_seconds: int
    max_sync_shell_timeout_seconds: int
    max_unapproved_shell_timeout_seconds: int
    max_search_results: int
    allow_all: bool
    artifact_dir: Path
    max_artifact_bytes: int
    max_terminal_sessions: int
    terminal_idle_timeout_seconds: int
    terminal_event_buffer_bytes: int


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()

    data_dir = Path(os.getenv("LOCALCONTROL_DATA_DIR", "localcontrol-data")).expanduser()
    if not data_dir.is_absolute():
        data_dir = (Path.cwd() / data_dir).resolve(strict=False)

    api_key = os.getenv("LOCALCONTROL_API_KEY")
    api_key_hash = sha256_hex(api_key) if api_key else os.getenv("LOCALCONTROL_API_KEY_SHA256")

    approval_key = os.getenv("LOCALCONTROL_APPROVAL_KEY")
    approval_key_hash = sha256_hex(approval_key) if approval_key else os.getenv("LOCALCONTROL_APPROVAL_KEY_SHA256")

    return Settings(
        api_key_hash=api_key_hash,
        approval_key_hash=approval_key_hash,
        bind_host=os.getenv("LOCALCONTROL_BIND_HOST", "127.0.0.1"),
        port=_int_env("LOCALCONTROL_PORT", 8765),
        data_dir=data_dir,
        audit_log_path=data_dir / "audit.jsonl",
        quarantine_dir=data_dir / "quarantine",
        rate_limit_per_minute=_int_env("LOCALCONTROL_RATE_LIMIT_PER_MINUTE", 120),
        max_response_bytes=_int_env("LOCALCONTROL_MAX_RESPONSE_BYTES", 65536),
        default_shell_timeout_seconds=_int_env("LOCALCONTROL_DEFAULT_SHELL_TIMEOUT_SECONDS", 10),
        max_sync_shell_timeout_seconds=_int_env("LOCALCONTROL_MAX_SYNC_SHELL_TIMEOUT_SECONDS", 25),
        max_unapproved_shell_timeout_seconds=_int_env("LOCALCONTROL_MAX_UNAPPROVED_SHELL_TIMEOUT_SECONDS", 30),
        max_search_results=_int_env("LOCALCONTROL_MAX_SEARCH_RESULTS", 200),
        allow_all=_bool_env("LOCALCONTROL_ALLOW_ALL", False),
        artifact_dir=data_dir / "artifacts",
        max_artifact_bytes=_int_env("LOCALCONTROL_MAX_ARTIFACT_BYTES", 52_428_800),
        max_terminal_sessions=_int_env("LOCALCONTROL_MAX_TERMINAL_SESSIONS", 5),
        terminal_idle_timeout_seconds=_int_env("LOCALCONTROL_TERMINAL_IDLE_TIMEOUT_SECONDS", 1800),
        terminal_event_buffer_bytes=_int_env("LOCALCONTROL_TERMINAL_EVENT_BUFFER_BYTES", 1_048_576),
    )
