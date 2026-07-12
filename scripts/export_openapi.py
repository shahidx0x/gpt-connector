from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from localcontrol.openapi_export import MAX_GPT_ACTION_OPERATIONS, build_schema, export_schema  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the curated Custom GPT Actions OpenAPI schema.")
    parser.add_argument("--server-url", default="https://YOUR-RESERVED-NGROK-DOMAIN.ngrok-free.app")
    parser.add_argument("--output", default=str(ROOT / "gpt-actions.openapi.yaml"))
    args = parser.parse_args()

    output = export_schema(args.server_url, args.output)
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
