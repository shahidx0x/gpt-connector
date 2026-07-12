from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from .config import get_settings
from .errors import LocalControlError
from .models import (
    FsDeleteRequest,
    FsDeleteResponse,
    FsListRequest,
    FsListResponse,
    FsReadRequest,
    FsReadResponse,
    FsReplaceRequest,
    FsReplaceResponse,
    FsStatResponse,
    FsWriteRequest,
    FsWriteResponse,
)
from .redaction import redact_text
from .utils import bytes_to_text_or_base64, file_info, is_hidden_path, normalize_path, utc_now_iso


def list_path(payload: FsListRequest) -> FsListResponse:
    path = normalize_path(payload.path)
    if not path.exists():
        raise LocalControlError("not_found", "Path does not exist.", status_code=404)
    if not path.is_dir():
        raise LocalControlError("not_directory", "Path is not a directory.", status_code=400)

    entries = []
    iterator = path.rglob("*") if payload.recursive else path.iterdir()
    truncated = False
    try:
        for child in iterator:
            if not payload.include_hidden and is_hidden_path(child):
                continue
            entries.append(file_info(child))
            if len(entries) >= payload.max_entries:
                truncated = True
                break
    except PermissionError as exc:
        raise LocalControlError("permission_denied", f"Permission denied while listing: {exc}", status_code=403) from exc
    return FsListResponse(path=str(path), entries=entries, truncated=truncated)


def read_file(payload: FsReadRequest) -> FsReadResponse:
    path = normalize_path(payload.path)
    if not path.exists():
        raise LocalControlError("not_found", "File does not exist.", status_code=404)
    if not path.is_file():
        raise LocalControlError("not_file", "Path is not a file.", status_code=400)

    with path.open("rb") as fh:
        data = fh.read(payload.max_bytes + 1)
    truncated = len(data) > payload.max_bytes
    if truncated:
        data = data[: payload.max_bytes]

    content, content_base64, binary = bytes_to_text_or_base64(data, payload.encoding)
    redactions = 0
    if content is not None and not payload.include_secrets:
        content, redactions = redact_text(content)

    return FsReadResponse(
        path=str(path),
        content=content,
        content_base64=content_base64,
        encoding=payload.encoding,
        binary=binary,
        bytes_read=len(data),
        truncated=truncated,
        redactions=redactions,
    )


def write_file(payload: FsWriteRequest) -> FsWriteResponse:
    path = normalize_path(payload.path)
    exists = path.exists()
    if exists and not path.is_file():
        raise LocalControlError("not_file", "Path exists but is not a file.", status_code=400)
    if exists and not payload.overwrite and not payload.append:
        raise LocalControlError("file_exists", "File exists; set overwrite or append.", status_code=409)
    if not path.parent.exists():
        if payload.create_parents:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            raise LocalControlError("parent_not_found", "Parent directory does not exist.", status_code=404)

    mode = "a" if payload.append else "w"
    with path.open(mode, encoding=payload.encoding, newline="") as fh:
        written = fh.write(payload.content)

    response_mode = "appended" if payload.append else ("overwritten" if exists else "created")
    return FsWriteResponse(
        path=str(path),
        bytes_written=len(payload.content.encode(payload.encoding)),
        mode=response_mode,
        file=file_info(path),
    )


def replace_file(payload: FsReplaceRequest) -> FsReplaceResponse:
    path = normalize_path(payload.path)
    if not path.exists():
        raise LocalControlError("not_found", "File does not exist.", status_code=404)
    if not path.is_file():
        raise LocalControlError("not_file", "Path is not a file.", status_code=400)

    text = path.read_text(encoding=payload.encoding)
    replacements = text.count(payload.old)
    if replacements == 0:
        return FsReplaceResponse(path=str(path), replacements=0, backup_path=None, file=file_info(path))

    backup_path: Path | None = None
    if payload.create_backup:
        backup_path = path.with_name(f"{path.name}.bak.{utc_now_iso().replace(':', '').replace('+', 'Z')}")
        shutil.copy2(path, backup_path)

    count = -1 if payload.count == 0 else payload.count
    new_text = text.replace(payload.old, payload.new, count)
    actual_replacements = replacements if count == -1 else min(replacements, count)
    path.write_text(new_text, encoding=payload.encoding)

    return FsReplaceResponse(
        path=str(path),
        replacements=actual_replacements,
        backup_path=str(backup_path) if backup_path else None,
        file=file_info(path),
    )


def delete_path(payload: FsDeleteRequest) -> FsDeleteResponse:
    settings = get_settings()
    path = normalize_path(payload.path)
    if not path.exists():
        raise LocalControlError("not_found", "Path does not exist.", status_code=404)
    if path.is_dir() and not payload.recursive:
        raise LocalControlError("recursive_required", "Set recursive=true to delete a directory.", status_code=409)

    if payload.permanent:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return FsDeleteResponse(path=str(path), permanent=True, quarantined_path=None)

    settings.quarantine_dir.mkdir(parents=True, exist_ok=True)
    suffix = utc_now_iso().replace(":", "").replace("+", "Z")
    dest = settings.quarantine_dir / f"{path.name or 'root'}-{suffix}-{uuid.uuid4().hex[:8]}"
    shutil.move(str(path), str(dest))
    return FsDeleteResponse(path=str(path), permanent=False, quarantined_path=str(dest))


def stat_path(path_raw: str) -> FsStatResponse:
    path = normalize_path(path_raw)
    return FsStatResponse(file=file_info(path), exists=path.exists())

