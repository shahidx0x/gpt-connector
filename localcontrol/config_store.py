from __future__ import annotations

import os
import re
import secrets
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from .config import get_settings, load_dotenv, sha256_hex
from .ngrok_values import normalize_ngrok_domain, normalize_public_url

ENV_KEY_RE = re.compile(r"^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=")

API_KEY = "LOCALCONTROL_API_KEY"
API_KEY_HASH = "LOCALCONTROL_API_KEY_SHA256"
PORT = "LOCALCONTROL_PORT"
NGROK_AUTHTOKEN = "LOCALCONTROL_NGROK_AUTHTOKEN"
NGROK_DOMAIN = "LOCALCONTROL_NGROK_DOMAIN"
PUBLIC_URL = "LOCALCONTROL_PUBLIC_URL"


@dataclass(frozen=True)
class SecretSnapshot:
    configured: bool
    source: str | None
    revealable: bool
    masked: str | None
    value: str | None


def active_env_path() -> Path:
    configured = os.getenv("LOCALCONTROL_CONFIG_ENV_PATH")
    if configured:
        return Path(configured).expanduser().resolve(strict=False)

    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        return cwd_env.resolve(strict=False)

    if getattr(sys, "frozen", False):
        exe_env = Path(sys.executable).resolve().parent / ".env"
        if exe_env.exists():
            return exe_env

    return cwd_env.resolve(strict=False)


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _quote_env(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:@%+=,\-]+", value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _read_env_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = _strip_quotes(value)
    return values


def _write_env_values(path: Path, updates: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(updates)
    seen: set[str] = set()
    output: list[str] = []

    for line in lines:
        match = ENV_KEY_RE.match(line)
        if not match:
            output.append(line)
            continue

        key = match.group("key")
        if key in updates:
            if key in seen:
                continue
            output.append(f"{key}={_quote_env(updates[key])}")
            seen.add(key)
            remaining.pop(key, None)
        else:
            output.append(line)

    if remaining and output and output[-1].strip():
        output.append("")
    for key, value in remaining.items():
        output.append(f"{key}={_quote_env(value)}")

    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def _mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def _read_key_file_value(key: str, env_path: Path) -> tuple[str | None, str | None]:
    key_file = env_path.parent / "localcontrol-keys.txt"
    if not key_file.exists():
        return None, None
    for line in key_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip(), str(key_file)
    return None, None


def _write_key_file_value(key: str, value: str, env_path: Path) -> None:
    key_file = env_path.parent / "localcontrol-keys.txt"
    existing: dict[str, str] = {}
    order: list[str] = []
    if key_file.exists():
        for line in key_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line:
                continue
            current_key, current_value = line.split("=", 1)
            current_key = current_key.strip()
            if current_key and current_key not in existing:
                order.append(current_key)
            existing[current_key] = current_value.strip()
    if key not in existing:
        order.append(key)
    existing[key] = value
    key_file.write_text("\n".join(f"{item}={existing[item]}" for item in order if item in existing) + "\n", encoding="utf-8")


def _ngrok_config_paths() -> list[Path]:
    paths: list[Path] = []
    if os.getenv("NGROK_CONFIG"):
        paths.extend(Path(part) for part in os.environ["NGROK_CONFIG"].split(os.pathsep) if part)
    if os.getenv("LOCALAPPDATA"):
        paths.append(Path(os.environ["LOCALAPPDATA"]) / "ngrok" / "ngrok.yml")
    if os.getenv("APPDATA"):
        paths.append(Path(os.environ["APPDATA"]) / "ngrok" / "ngrok.yml")
    home = Path.home()
    paths.append(home / ".config" / "ngrok" / "ngrok.yml")
    paths.append(home / ".ngrok2" / "ngrok.yml")

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path not in seen:
            unique.append(path)
            seen.add(path)
    return unique


def _read_ngrok_config_authtoken() -> tuple[str | None, str | None]:
    for path in _ngrok_config_paths():
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            direct = data.get("authtoken")
            if isinstance(direct, str) and direct:
                return direct, str(path)
            agent = data.get("agent")
            if isinstance(agent, dict):
                nested = agent.get("authtoken")
                if isinstance(nested, str) and nested:
                    return nested, str(path)
    return None, None


def _secret_snapshot(
    value: str | None,
    source: str | None,
    *,
    reveal: bool,
    configured: bool | None = None,
) -> SecretSnapshot:
    is_configured = bool(value) if configured is None else configured
    return SecretSnapshot(
        configured=is_configured,
        source=source,
        revealable=bool(value),
        masked=_mask_secret(value),
        value=value if reveal and value else None,
    )


def read_secret(key: str, env_values: dict[str, str], env_path: Path) -> tuple[str | None, str | None]:
    if os.getenv(key):
        return os.environ[key], "process_env"
    if key in env_values:
        return env_values[key], str(env_path)
    return _read_key_file_value(key, env_path)


def config_snapshot(*, reveal_secrets: bool = False) -> dict[str, Any]:
    env_path = active_env_path()
    load_dotenv(env_path)
    env_values = _read_env_values(env_path)
    if os.getenv("LOCALCONTROL_CONFIG_ENV_PATH"):
        for key in (API_KEY, API_KEY_HASH, PORT, NGROK_AUTHTOKEN, NGROK_DOMAIN, PUBLIC_URL):
            if key in env_values:
                os.environ[key] = env_values[key]
    get_settings.cache_clear()
    settings = get_settings()

    api_key, api_source = read_secret(API_KEY, env_values, env_path)
    if not api_key and settings.api_key_hash:
        api_source = os.getenv(API_KEY_HASH) and "hash_only"

    ngrok_token, ngrok_source = read_secret(NGROK_AUTHTOKEN, env_values, env_path)
    if not ngrok_token and os.getenv("NGROK_AUTHTOKEN"):
        ngrok_token = os.environ["NGROK_AUTHTOKEN"]
        ngrok_source = "process_env"
    if not ngrok_token:
        ngrok_token, ngrok_source = _read_ngrok_config_authtoken()

    return {
        "env_path": str(env_path),
        "port": settings.port,
        "bind_host": settings.bind_host,
        "api_key": asdict(_secret_snapshot(api_key, api_source, reveal=reveal_secrets, configured=bool(settings.api_key_hash))),
        "ngrok_authtoken": asdict(_secret_snapshot(ngrok_token, ngrok_source, reveal=reveal_secrets)),
        "ngrok_domain": os.getenv(NGROK_DOMAIN) or env_values.get(NGROK_DOMAIN),
        "public_url": os.getenv(PUBLIC_URL) or env_values.get(PUBLIC_URL),
    }


def update_config(
    *,
    port: int | None = None,
    api_key: str | None = None,
    randomize_api_key: bool = False,
    ngrok_authtoken: str | None = None,
    ngrok_domain: str | None = None,
    public_url: str | None = None,
    reveal_secrets: bool = False,
) -> dict[str, Any]:
    env_path = active_env_path()
    updates: dict[str, str] = {}
    changed: list[str] = []
    restart_required: list[str] = []
    generated_api_key: str | None = None

    if port is not None:
        updates[PORT] = str(port)
        changed.append(PORT)
        restart_required.append(PORT)

    if randomize_api_key:
        generated_api_key = secrets.token_urlsafe(32)
        api_key = generated_api_key

    if api_key is not None:
        updates[API_KEY] = api_key
        updates[API_KEY_HASH] = sha256_hex(api_key)
        changed.extend([API_KEY, API_KEY_HASH])

    if ngrok_authtoken is not None:
        updates[NGROK_AUTHTOKEN] = ngrok_authtoken
        changed.append(NGROK_AUTHTOKEN)
        restart_required.append(NGROK_AUTHTOKEN)

    if ngrok_domain is not None:
        updates[NGROK_DOMAIN] = normalize_ngrok_domain(ngrok_domain) or ""
        changed.append(NGROK_DOMAIN)
        restart_required.append(NGROK_DOMAIN)

    if public_url is not None:
        updates[PUBLIC_URL] = normalize_public_url(public_url) or ""
        changed.append(PUBLIC_URL)
        restart_required.append(PUBLIC_URL)

    if updates:
        _write_env_values(env_path, updates)
        for key, value in updates.items():
            os.environ[key] = value
        if api_key is not None:
            _write_key_file_value(API_KEY, api_key, env_path)
        get_settings.cache_clear()

    snapshot = config_snapshot(reveal_secrets=reveal_secrets)
    snapshot["changed_keys"] = changed
    snapshot["restart_required_keys"] = sorted(set(restart_required))
    snapshot["generated_api_key"] = generated_api_key
    return snapshot
