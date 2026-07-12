#!/usr/bin/env bash
set -euo pipefail

onefile=0
skip_install=0
no_bundle_ngrok=0
ngrok_exe="${LOCALCONTROL_NGROK_EXE:-ngrok}"
ngrok_download_url="${LOCALCONTROL_NGROK_DOWNLOAD_URL:-}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --onefile|-OneFile)
      onefile=1
      ;;
    --skip-install|-SkipInstall)
      skip_install=1
      ;;
    --no-bundle-ngrok|-NoBundleNgrok)
      no_bundle_ngrok=1
      ;;
    --ngrok-exe)
      shift
      ngrok_exe="${1:?--ngrok-exe requires a value}"
      ;;
    --ngrok-download-url)
      shift
      ngrok_download_url="${1:?--ngrok-download-url requires a value}"
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
  shift
done

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"

if [ -n "${PYTHON:-}" ]; then
  python="$PYTHON"
elif [ -x ".venv/bin/python" ]; then
  python=".venv/bin/python"
else
  python="python3"
fi

default_ngrok_download_url() {
  case "$(uname -m)" in
    x86_64|amd64)
      echo "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz"
      ;;
    aarch64|arm64)
      echo "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.tgz"
      ;;
    *)
      echo "No default ngrok download URL is configured for $(uname -s) $(uname -m)." >&2
      echo "Install ngrok yourself or set LOCALCONTROL_NGROK_EXE/LOCALCONTROL_NGROK_DOWNLOAD_URL." >&2
      return 1
      ;;
  esac
}

install_local_ngrok() {
  local download_url="$1"
  local install_dir="$2"
  local temp_root archive downloaded local_exe

  mkdir -p "$install_dir"
  temp_root="$(mktemp -d)"
  archive="$temp_root/ngrok.tgz"
  echo "Downloading ngrok for bundled executable..." >&2
  echo "Source: $download_url" >&2
  "$python" - "$download_url" "$archive" <<'PY'
from __future__ import annotations

import sys
import urllib.request

urllib.request.urlretrieve(sys.argv[1], sys.argv[2])
PY
  tar -xzf "$archive" -C "$temp_root"
  downloaded="$(find "$temp_root" -type f -name ngrok | head -n 1)"
  if [ -z "$downloaded" ]; then
    echo "Downloaded archive did not contain ngrok." >&2
    exit 1
  fi
  local_exe="$install_dir/ngrok"
  install -m 755 "$downloaded" "$local_exe"
  rm -rf "$temp_root"
  echo "$local_exe"
}

resolve_ngrok_for_bundle() {
  local requested="$1"
  local download_url="$2"
  local install_dir="$repo/.local-tools/ngrok"
  local local_exe="$install_dir/ngrok"

  if [ -n "$requested" ] && [ "$requested" != "ngrok" ]; then
    if command -v "$requested" >/dev/null 2>&1; then
      command -v "$requested"
      return
    fi
    if [ -f "$requested" ]; then
      realpath "$requested"
      return
    fi
  fi

  if [ -f "$local_exe" ]; then
    realpath "$local_exe"
    return
  fi

  if command -v ngrok >/dev/null 2>&1; then
    command -v ngrok
    return
  fi

  if [ -z "$download_url" ]; then
    download_url="$(default_ngrok_download_url)"
  fi
  install_local_ngrok "$download_url" "$install_dir"
}

if [ "$skip_install" -eq 0 ]; then
  "$python" -m pip install -e ".[dev]"
  "$python" -m pip install "pyinstaller>=6"
fi

mode="--onedir"
if [ "$onefile" -eq 1 ]; then
  mode="--onefile"
fi

web_assets="$repo/localcontrol/web"
pyinstaller_args=(
  "--noconfirm"
  "--clean"
  "$mode"
  "--console"
  "--name" "GPT-Connect"
  "--distpath" "dist"
  "--workpath" "build/pyinstaller-work"
  "--specpath" "build/pyinstaller-spec"
  "--collect-submodules" "localcontrol"
  "--collect-submodules" "uvicorn"
  "--collect-submodules" "fastapi"
  "--collect-submodules" "pydantic"
  "--collect-submodules" "starlette"
  "--collect-data" "fastapi"
  "--collect-data" "pydantic"
  "--add-data" "$web_assets:localcontrol/web"
  "--copy-metadata" "fastapi"
  "--copy-metadata" "pydantic"
  "--copy-metadata" "starlette"
  "--copy-metadata" "uvicorn"
  "localcontrol/cli.py"
)

if [ "$no_bundle_ngrok" -eq 0 ]; then
  ngrok_path="$(resolve_ngrok_for_bundle "$ngrok_exe" "$ngrok_download_url")"
  echo "Bundling ngrok: $ngrok_path"
  pyinstaller_args=("--add-binary" "$ngrok_path:." "${pyinstaller_args[@]}")
fi

"$python" -m PyInstaller "${pyinstaller_args[@]}"

if [ "$onefile" -eq 1 ]; then
  echo "Built: $repo/dist/GPT-Connect"
else
  echo "Built: $repo/dist/GPT-Connect/GPT-Connect"
fi
