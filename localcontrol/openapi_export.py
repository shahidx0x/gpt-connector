from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from localcontrol.api.app import app

MAX_GPT_ACTION_OPERATIONS = 30

GPT_ACTION_OPERATIONS: dict[str, set[str]] = {
    "/fs/list": {"post"},
    "/fs/read": {"post"},
    "/fs/write": {"post"},
    "/fs/replace": {"post"},
    "/fs/delete": {"post"},
    "/fs/stat": {"post"},
    "/artifacts/create_text": {"post"},
    "/artifacts/fetch_url": {"post"},
    "/artifacts/from_path": {"post"},
    "/artifacts/list": {"post"},
    "/artifacts/{artifact_id}": {"get"},
    "/artifacts/{artifact_id}/write_to_path": {"post"},
    "/search/files": {"post"},
    "/search/content": {"post"},
    "/shell/run": {"post"},
    "/terminal/sessions": {"post"},
    "/terminal/sessions/list": {"post"},
    "/terminal/sessions/{session_id}": {"get"},
    "/terminal/sessions/{session_id}/exec": {"post"},
    "/terminal/sessions/{session_id}/stdin": {"post"},
    "/terminal/sessions/{session_id}/events": {"post"},
    "/terminal/sessions/{session_id}/terminate": {"post"},
    "/execution/logs": {"post"},
    "/projects/register": {"post"},
    "/projects/list": {"post"},
    "/system/info": {"get"},
}


def _collect_schema_refs(value, refs: set[str]) -> None:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            refs.add(ref.rsplit("/", 1)[-1])
        for child in value.values():
            _collect_schema_refs(child, refs)
    elif isinstance(value, list):
        for item in value:
            _collect_schema_refs(item, refs)


def _prune_unused_components(schema: dict) -> None:
    schemas = schema.get("components", {}).get("schemas")
    if not isinstance(schemas, dict):
        return

    used: set[str] = set()
    _collect_schema_refs(schema.get("paths", {}), used)
    pending = list(used)
    while pending:
        name = pending.pop()
        component = schemas.get(name)
        if not component:
            continue
        discovered: set[str] = set()
        _collect_schema_refs(component, discovered)
        for ref_name in discovered:
            if ref_name not in used:
                used.add(ref_name)
                pending.append(ref_name)

    schema["components"]["schemas"] = {name: value for name, value in schemas.items() if name in used}


def build_schema(server_url: str) -> dict:
    schema = deepcopy(app.openapi())
    schema["servers"] = [{"url": server_url}]
    schema["info"]["title"] = "Windows GPT-Connect Actions"
    schema["info"]["description"] = (
        "Private Custom GPT action schema for a single-user Windows GPT-Connect bridge. "
        "Full-control execution mode is enabled; use /execution/logs to retrieve command and terminal output."
    )

    filtered_paths: dict[str, dict] = {}
    for path, allowed_methods in GPT_ACTION_OPERATIONS.items():
        if path not in schema["paths"]:
            continue
        filtered_paths[path] = {
            method: operation
            for method, operation in schema["paths"][path].items()
            if method.lower() in allowed_methods
        }
    schema["paths"] = filtered_paths
    operation_count = sum(len(methods) for methods in filtered_paths.values())
    if operation_count > MAX_GPT_ACTION_OPERATIONS:
        raise RuntimeError(f"Curated GPT schema has {operation_count} operations; max is {MAX_GPT_ACTION_OPERATIONS}.")
    _prune_unused_components(schema)
    return schema


def export_schema(server_url: str, output: str | Path) -> Path:
    output_path = Path(output)
    schema = build_schema(server_url)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() in {".yaml", ".yml"}:
        import yaml

        output_path.write_text(yaml.safe_dump(schema, sort_keys=False, allow_unicode=True), encoding="utf-8")
    else:
        output_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    return output_path
