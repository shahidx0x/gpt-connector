from __future__ import annotations

import base64
import os
from datetime import datetime, timezone
from pathlib import Path

from .errors import LocalControlError
from .models import FileInfo


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def normalize_path(raw_path: str) -> Path:
    if not raw_path or not raw_path.strip():
        raise LocalControlError("invalid_path", "Path must not be empty.", status_code=422)
    expanded = os.path.expandvars(raw_path.strip())
    try:
        return Path(expanded).expanduser().resolve(strict=False)
    except OSError as exc:
        raise LocalControlError("invalid_path", f"Could not normalize path: {exc}", status_code=422) from exc


def is_hidden_path(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts if part not in {path.anchor, "."})


def file_info(path: Path) -> FileInfo:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return FileInfo(path=str(path), name=path.name, is_dir=False, size=None, modified_at=None)
    return FileInfo(
        path=str(path),
        name=path.name or str(path),
        is_dir=path.is_dir(),
        size=None if path.is_dir() else stat.st_size,
        modified_at=timestamp_iso(stat.st_mtime),
    )


def truncate_text(text: str, max_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text, False
    cut = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return f"{cut}\n[truncated to {max_bytes} bytes]", True


def bytes_to_text_or_base64(data: bytes, encoding: str) -> tuple[str | None, str | None, bool]:
    if b"\x00" in data:
        return None, base64.b64encode(data).decode("ascii"), True
    try:
        return data.decode(encoding), None, False
    except UnicodeDecodeError:
        return None, base64.b64encode(data).decode("ascii"), True

