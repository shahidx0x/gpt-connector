from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path

from .config import get_settings
from .errors import LocalControlError
from .models import ProjectInfo, ProjectListResponse, ProjectRegisterRequest
from .utils import normalize_path, utc_now_iso

_PROJECT_ID_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


class ProjectStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            path = self._store_path()
            if path.exists():
                path.unlink()

    def register(self, payload: ProjectRegisterRequest) -> ProjectInfo:
        root = normalize_path(payload.path)
        if not root.exists() or not root.is_dir():
            raise LocalControlError("project_not_directory", "Project path must be an existing directory.", status_code=400)

        with self._lock:
            projects = self._load()
            project_id = payload.project_id or self._project_id_for_path(root, projects)
            name = payload.name or root.name or str(root)
            existing = projects.get(project_id, {})
            now = utc_now_iso()
            projects[project_id] = {
                "project_id": project_id,
                "name": name,
                "path": str(root),
                "description": payload.description,
                "created_at": existing.get("created_at") or now,
                "last_used_at": now,
            }
            self._save(projects)
            return self._to_info(projects[project_id])

    def list(self) -> ProjectListResponse:
        with self._lock:
            projects = self._load()
            infos = [self._to_info(record) for record in sorted(projects.values(), key=lambda item: item["name"].lower())]
        return ProjectListResponse(projects=infos)

    def get(self, project_id: str) -> ProjectInfo:
        with self._lock:
            projects = self._load()
            record = projects.get(project_id)
            if not record:
                raise LocalControlError("project_not_found", "Project was not found.", status_code=404, details={"project_id": project_id})
            record["last_used_at"] = utc_now_iso()
            projects[project_id] = record
            self._save(projects)
            return self._to_info(record)

    def resolve_path(self, project_id: str | None, raw_path: str | None, *, require_path: bool = True) -> Path | None:
        if not project_id:
            if raw_path:
                return normalize_path(raw_path)
            if require_path:
                raise LocalControlError("path_or_project_required", "Provide a path or project_id.", status_code=422)
            return None

        project = self.get(project_id)
        root = normalize_path(project.path)
        if not raw_path:
            return root
        expanded = os.path.expandvars(raw_path.strip())
        candidate = Path(expanded).expanduser()
        if candidate.is_absolute():
            return normalize_path(raw_path)
        return (root / candidate).resolve(strict=False)

    def _store_path(self) -> Path:
        return get_settings().data_dir / "projects.json"

    def _load(self) -> dict[str, dict]:
        path = self._store_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(key): value for key, value in data.items() if isinstance(value, dict)}

    def _save(self, projects: dict[str, dict]) -> None:
        path = self._store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(projects, indent=2, ensure_ascii=False), encoding="utf-8")

    def _project_id_for_path(self, path: Path, projects: dict[str, dict]) -> str:
        for project_id, record in projects.items():
            if record.get("path") == str(path):
                return project_id
        base = _PROJECT_ID_RE.sub("-", path.name.lower()).strip("-._") or "project"
        if base not in projects:
            return base
        return f"{base}-{uuid.uuid4().hex[:8]}"

    def _to_info(self, record: dict) -> ProjectInfo:
        path = normalize_path(str(record["path"]))
        return ProjectInfo(
            project_id=str(record["project_id"]),
            name=str(record["name"]),
            path=str(path),
            description=record.get("description"),
            created_at=str(record["created_at"]),
            last_used_at=record.get("last_used_at"),
            exists=path.exists() and path.is_dir(),
        )


project_store = ProjectStore()
