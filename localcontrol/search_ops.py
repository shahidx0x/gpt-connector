from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from .config import get_settings
from .errors import LocalControlError
from .models import (
    ContentMatch,
    SearchContentRequest,
    SearchContentResponse,
    SearchFilesRequest,
    SearchFilesResponse,
)
from .redaction import redact_text
from .utils import file_info, is_hidden_path, normalize_path


def _walk(root: Path, recursive: bool, include_hidden: bool):
    for current_root, dirs, files in os.walk(root):
        current = Path(current_root)
        if not include_hidden:
            dirs[:] = [name for name in dirs if not is_hidden_path(current / name)]
            files = [name for name in files if not is_hidden_path(current / name)]
        for dirname in dirs:
            yield current / dirname
        for filename in files:
            yield current / filename
        if not recursive:
            dirs.clear()


def search_files(payload: SearchFilesRequest) -> SearchFilesResponse:
    settings = get_settings()
    root = normalize_path(payload.root)
    if not root.exists() or not root.is_dir():
        raise LocalControlError("not_directory", "Root must be an existing directory.", status_code=400)

    max_results = min(payload.max_results, settings.max_search_results)
    query = payload.query.lower() if payload.query else None
    glob = payload.glob.lower() if payload.glob else None
    results = []
    truncated = False

    for path in _walk(root, payload.recursive, payload.include_hidden):
        name = path.name.lower()
        if query and query not in name:
            continue
        if glob and not fnmatch.fnmatch(name, glob):
            continue
        results.append(file_info(path))
        if len(results) >= max_results:
            truncated = True
            break

    return SearchFilesResponse(root=str(root), results=results, truncated=truncated)


def search_content(payload: SearchContentRequest) -> SearchContentResponse:
    settings = get_settings()
    root = normalize_path(payload.root)
    if not root.exists() or not root.is_dir():
        raise LocalControlError("not_directory", "Root must be an existing directory.", status_code=400)

    flags = 0 if payload.case_sensitive else re.IGNORECASE
    pattern = re.compile(payload.pattern if payload.regex else re.escape(payload.pattern), flags)
    max_results = min(payload.max_results, settings.max_search_results)
    matches: list[ContentMatch] = []
    truncated = False

    for path in _walk(root, payload.recursive, payload.include_hidden):
        if not path.is_file():
            continue
        if payload.glob and not fnmatch.fnmatch(path.name.lower(), payload.glob.lower()):
            continue
        try:
            if path.stat().st_size > payload.max_file_bytes:
                continue
            data = path.read_bytes()
        except (OSError, PermissionError):
            continue
        if b"\x00" in data:
            continue
        text = data.decode("utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not pattern.search(line):
                continue
            redacted, redactions = redact_text(line)
            matches.append(ContentMatch(path=str(path), line_number=line_number, line=redacted, redactions=redactions))
            if len(matches) >= max_results:
                truncated = True
                break
        if truncated:
            break

    return SearchContentResponse(root=str(root), matches=matches, truncated=truncated)

