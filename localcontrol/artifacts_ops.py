from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import shutil
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from fastapi.responses import FileResponse

from .config import get_settings
from .errors import LocalControlError
from .models import (
    ArtifactCreateTextRequest,
    ArtifactFetchUrlRequest,
    ArtifactFromPathRequest,
    ArtifactInfo,
    ArtifactListResponse,
    ArtifactUploadBase64Request,
    ArtifactWriteToPathRequest,
)
from .utils import normalize_path, utc_now_iso


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return cleaned or "artifact.bin"


def _artifact_dirs() -> tuple[Path, Path]:
    root = get_settings().artifact_dir
    files = root / "files"
    meta = root / "metadata"
    files.mkdir(parents=True, exist_ok=True)
    meta.mkdir(parents=True, exist_ok=True)
    return files, meta


def _metadata_path(artifact_id: str) -> Path:
    _files, meta = _artifact_dirs()
    return meta / f"{artifact_id}.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _guess_mime(name: str, provided: str | None = None) -> str:
    if provided:
        return provided
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def _load_info(artifact_id: str) -> ArtifactInfo:
    path = _metadata_path(artifact_id)
    if not path.exists():
        raise LocalControlError("artifact_not_found", "Artifact was not found.", status_code=404)
    return ArtifactInfo.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _save_info(info: ArtifactInfo) -> ArtifactInfo:
    _metadata_path(info.artifact_id).write_text(info.model_dump_json(indent=2), encoding="utf-8")
    return info


def _ensure_size(size: int) -> None:
    limit = get_settings().max_artifact_bytes
    if size > limit:
        raise LocalControlError(
            "artifact_too_large",
            "Artifact exceeds configured size limit.",
            status_code=413,
            details={"size": size, "max_artifact_bytes": limit},
        )


def _create_managed_artifact(*, name: str, data: bytes, mime_type: str | None, source: str) -> ArtifactInfo:
    _ensure_size(len(data))
    artifact_id = str(uuid.uuid4())
    safe_name = _safe_name(name)
    files, _meta = _artifact_dirs()
    local_path = files / f"{artifact_id}-{safe_name}"
    local_path.write_bytes(data)
    info = ArtifactInfo(
        artifact_id=artifact_id,
        name=safe_name,
        size=len(data),
        mime_type=_guess_mime(safe_name, mime_type),
        sha256=_sha256(data),
        created_at=utc_now_iso(),
        source=source,
        local_path=str(local_path),
        managed=True,
    )
    return _save_info(info)


def create_text_artifact(payload: ArtifactCreateTextRequest) -> ArtifactInfo:
    return _create_managed_artifact(
        name=payload.name,
        data=payload.content.encode(payload.encoding),
        mime_type=payload.mime_type,
        source="create_text",
    )


def upload_base64_artifact(payload: ArtifactUploadBase64Request) -> ArtifactInfo:
    try:
        data = base64.b64decode(payload.content_base64, validate=True)
    except ValueError as exc:
        raise LocalControlError("invalid_base64", "content_base64 is not valid base64.", status_code=422) from exc
    return _create_managed_artifact(name=payload.name, data=data, mime_type=payload.mime_type, source="upload_base64")


def fetch_url_artifact(payload: ArtifactFetchUrlRequest) -> ArtifactInfo:
    parsed = urllib.parse.urlparse(payload.url)
    if parsed.scheme not in {"http", "https"}:
        raise LocalControlError("unsupported_url_scheme", "Only http and https URLs are supported.", status_code=422)
    limit = get_settings().max_artifact_bytes
    request = urllib.request.Request(payload.url, headers={"User-Agent": "GPT-Connect/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > limit:
                _ensure_size(int(content_length))
            data = response.read(limit + 1)
            _ensure_size(len(data))
            content_type = response.headers.get_content_type()
            final_url_path = urllib.parse.urlparse(response.geturl()).path
    except LocalControlError:
        raise
    except Exception as exc:  # noqa: BLE001 - urllib surfaces many concrete network exceptions.
        raise LocalControlError("artifact_fetch_failed", f"Could not fetch URL: {exc}", status_code=502) from exc

    name = payload.name or Path(urllib.parse.unquote(final_url_path)).name or "downloaded-artifact"
    return _create_managed_artifact(name=name, data=data, mime_type=content_type, source=f"url:{payload.url}")


def from_path_artifact(payload: ArtifactFromPathRequest) -> ArtifactInfo:
    path = normalize_path(payload.path)
    if not path.exists() or not path.is_file():
        raise LocalControlError("not_file", "Path must be an existing file.", status_code=400)
    size = path.stat().st_size
    _ensure_size(size)
    data = path.read_bytes()
    if payload.copy_file:
        return _create_managed_artifact(name=payload.name or path.name, data=data, mime_type=_guess_mime(path.name), source=f"copy_path:{path}")
    info = ArtifactInfo(
        artifact_id=str(uuid.uuid4()),
        name=_safe_name(payload.name or path.name),
        size=size,
        mime_type=_guess_mime(path.name),
        sha256=_sha256(data),
        created_at=utc_now_iso(),
        source=f"path:{path}",
        local_path=str(path),
        managed=False,
    )
    return _save_info(info)


def list_artifacts(max_results: int) -> ArtifactListResponse:
    _files, meta = _artifact_dirs()
    infos = []
    for path in sorted(meta.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            infos.append(ArtifactInfo.model_validate(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
        if len(infos) >= max_results:
            break
    return ArtifactListResponse(artifacts=infos)


def get_artifact(artifact_id: str) -> ArtifactInfo:
    return _load_info(artifact_id)


def artifact_file_response(artifact_id: str) -> FileResponse:
    info = _load_info(artifact_id)
    path = Path(info.local_path)
    if not path.exists() or not path.is_file():
        raise LocalControlError("artifact_file_missing", "Artifact file is missing from disk.", status_code=404)
    return FileResponse(path=path, filename=info.name, media_type=info.mime_type)


def write_artifact_to_path(artifact_id: str, payload: ArtifactWriteToPathRequest) -> ArtifactInfo:
    info = _load_info(artifact_id)
    source = Path(info.local_path)
    if not source.exists() or not source.is_file():
        raise LocalControlError("artifact_file_missing", "Artifact file is missing from disk.", status_code=404)
    destination = normalize_path(payload.path)
    if destination.exists() and not payload.overwrite:
        raise LocalControlError("file_exists", "Destination exists; set overwrite=true.", status_code=409)
    if not destination.parent.exists():
        if payload.create_parents:
            destination.parent.mkdir(parents=True, exist_ok=True)
        else:
            raise LocalControlError("parent_not_found", "Destination parent does not exist.", status_code=404)
    shutil.copy2(source, destination)
    return info


def delete_artifact(artifact_id: str) -> tuple[bool, bool]:
    info = _load_info(artifact_id)
    removed_file = False
    if info.managed:
        path = Path(info.local_path)
        if path.exists():
            path.unlink()
            removed_file = True
    meta_path = _metadata_path(artifact_id)
    if meta_path.exists():
        meta_path.unlink()
    return True, removed_file
