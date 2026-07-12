from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from localcontrol.main import app  # noqa: E402

MAX_GPT_ACTION_OPERATIONS = 30

GPT_ACTION_OPERATIONS: dict[str, set[str]] = {
    "/fs/list": {"post"},
    "/fs/read": {"post"},
    "/fs/write": {"post"},
    "/fs/replace": {"post"},
    "/fs/delete": {"post"},
    "/fs/stat": {"post"},
    "/artifacts/create_text": {"post"},
    "/artifacts/upload_base64": {"post"},
    "/artifacts/fetch_url": {"post"},
    "/artifacts/from_path": {"post"},
    "/artifacts/list": {"post"},
    "/artifacts/{artifact_id}": {"get"},
    "/artifacts/{artifact_id}/download": {"get"},
    "/artifacts/{artifact_id}/write_to_path": {"post"},
    "/artifacts/{artifact_id}/delete": {"post"},
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
    "/system/info": {"get"},
    "/git/status": {"post"},
    "/git/diff": {"post"},
    "/git/add": {"post"},
    "/git/commit": {"post"},
}


def build_schema(server_url: str) -> dict:
    schema = deepcopy(app.openapi())
    schema["servers"] = [{"url": server_url}]
    schema["info"]["title"] = "Windows LocalControl GPT Actions"
    schema["info"]["description"] = (
        "Private Custom GPT action schema for a single-user Windows LocalControl bridge. "
        "Approving or denying risky operations is intentionally omitted; use the local approval key outside ChatGPT."
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
    return schema


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the curated Custom GPT Actions OpenAPI schema.")
    parser.add_argument("--server-url", default="https://YOUR-RESERVED-NGROK-DOMAIN.ngrok-free.app")
    parser.add_argument("--output", default=str(ROOT / "gpt-actions.openapi.yaml"))
    args = parser.parse_args()

    schema = build_schema(args.server_url)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() in {".yaml", ".yml"}:
        import yaml

        output.write_text(yaml.safe_dump(schema, sort_keys=False, allow_unicode=True), encoding="utf-8")
    else:
        output.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
