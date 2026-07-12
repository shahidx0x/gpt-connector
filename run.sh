#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PY="${PYTHON:-.venv/bin/python}"
MODE="launch"
APP_MODE="tunnel"
PORT="8765"
ALLOW_ALL=""

case "${1:-}" in
  help) MODE="help" ;;
  stop) MODE="stop" ;;
  test) MODE="test" ;;
  schema) MODE="schema" ;;
  check) MODE="check" ;;
  launch) MODE="launch" ;;
  serve) MODE="launch"; APP_MODE="serve" ;;
  tunnel|ngrok) MODE="launch"; APP_MODE="tunnel" ;;
  serve-direct) MODE="serve" ;;
  tunnel-direct) MODE="tunnel" ;;
  --allow-all) ALLOW_ALL="1" ;;
  "") ;;
  *) MODE="unknown" ;;
esac

for arg in "$@"; do
  if [ "$arg" = "--allow-all" ]; then
    ALLOW_ALL="1"
  fi
done

if [ -f ".env" ]; then
  env_port="$(grep -E '^(export[[:space:]]+)?LOCALCONTROL_PORT=' .env | tail -n 1 | sed -E 's/^(export[[:space:]]+)?LOCALCONTROL_PORT=//' | tr -d '\"' || true)"
  if [ -n "$env_port" ]; then
    PORT="$env_port"
  fi
fi

ensure() {
  if [ ! -f ".env" ]; then
    echo "No .env found yet. The settings UI can create it."
  fi

  if [ ! -x "$PY" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
  fi

  if ! "$PY" -m pip show gpt-connect >/dev/null 2>&1; then
    echo "Installing GPT-Connect dependencies..."
    "$PY" -m pip install -e ".[dev]"
  fi
}

stop_port() {
  local pids=""
  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
  elif command -v fuser >/dev/null 2>&1; then
    pids="$(fuser "$PORT"/tcp 2>/dev/null || true)"
  fi

  if [ -z "$pids" ]; then
    echo "No existing listener found on port $PORT."
    return 0
  fi

  for pid in $pids; do
    if [ "$pid" != "0" ]; then
      echo "Stopping existing listener on port $PORT (PID $pid)..."
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
}

case "$MODE" in
  help)
    cat <<EOF
Usage:
  ./run.sh          Open settings UI, then start API + ngrok tunnel
  ./run.sh tunnel   Open settings UI with tunnel mode selected
  ./run.sh serve    Open settings UI with API-only mode selected
  ./run.sh ngrok    Alias for tunnel
                   Downloads ngrok to .local-tools/ngrok if missing
  ./run.sh --allow-all
  ./run.sh serve-direct   Start API server without settings UI
  ./run.sh tunnel-direct  Start API + ngrok without settings UI
  ./run.sh stop     Stop any process listening on the configured port
  ./run.sh check    Test health and authenticated system/info endpoint
  ./run.sh test     Run automated tests
  ./run.sh schema   Regenerate gpt-actions.openapi.yaml
  ./run.sh help     Show this help
EOF
    ;;
  launch)
    ensure
    stop_port
    echo "Opening GPT-Connect settings before startup..."
    args=(launch --mode "$APP_MODE")
    if [ -n "$ALLOW_ALL" ]; then
      args+=(--allow-all)
    fi
    exec "$PY" -m localcontrol.cli "${args[@]}"
    ;;
  serve)
    ensure
    stop_port
    if [ -n "$ALLOW_ALL" ]; then
      export LOCALCONTROL_ALLOW_ALL=1
      echo "WARNING: approval prompts are disabled for dangerous operations (--allow-all)."
    fi
    echo "Starting GPT-Connect Bridge..."
    echo "URL: http://127.0.0.1:$PORT"
    echo "Health: http://127.0.0.1:$PORT/health"
    echo
    echo "Press Ctrl+C to stop."
    exec "$PY" -m uvicorn localcontrol.main:app --host 127.0.0.1 --port "$PORT"
    ;;
  tunnel)
    ensure
    stop_port
    args=(tunnel --host 127.0.0.1 --port "$PORT")
    if [ -n "$ALLOW_ALL" ]; then
      args+=(--allow-all)
    fi
    echo "Starting GPT-Connect with ngrok tunnel..."
    exec "$PY" -m localcontrol.cli "${args[@]}"
    ;;
  stop)
    stop_port
    ;;
  test)
    ensure
    exec "$PY" -m pytest
    ;;
  schema)
    ensure
    exec "$PY" scripts/export_openapi.py
    ;;
  check)
    ensure
    LOCALCONTROL_PORT="$PORT" "$PY" - <<'PY'
from pathlib import Path
import json
import os
import urllib.request

port = os.getenv("LOCALCONTROL_PORT", "8765")
key_file = Path("localcontrol-keys.txt")
api_key = ""
if key_file.exists():
    for line in key_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("LOCALCONTROL_API_KEY="):
            api_key = line.split("=", 1)[1]
            break
headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

for label, path in (("Health", "/health"), ("System info", "/system/info")):
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        print(f"{label}:")
        print(json.dumps(json.loads(response.read().decode("utf-8")), indent=2))
PY
    ;;
  *)
    echo "Unknown command: ${1:-}"
    "$0" help
    exit 1
    ;;
esac
