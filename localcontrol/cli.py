from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Sequence

import uvicorn

from localcontrol import __version__
from localcontrol.config import load_dotenv
from localcontrol.openapi_export import export_schema

DEFAULT_NGROK_DOWNLOAD_URL = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip"
MAX_NGROK_AUTH_RETRIES = 3


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _load_env() -> None:
    cwd_env = Path.cwd() / ".env"
    load_dotenv(cwd_env)
    if getattr(sys, "frozen", False):
        exe_env = Path(sys.executable).resolve().parent / ".env"
        if exe_env != cwd_env:
            load_dotenv(exe_env)


def _target_host(host: str) -> str:
    if host in {"0.0.0.0", "::", "[::]"}:
        return "127.0.0.1"
    return host


def _entry_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "localcontrol.cli"]


def _bundled_ngrok_path() -> Path | None:
    candidate_roots: list[Path] = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidate_roots.append(Path(bundle_root))
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidate_roots.extend([exe_dir, exe_dir / "_internal"])

    for root in candidate_roots:
        candidate = root / "ngrok.exe"
        if candidate.exists():
            return candidate
    return None


def _http_json(url: str, timeout: float = 2.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_health(url: str, process: subprocess.Popen, timeout_seconds: int = 40) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"GPT-Connect exited early with code {process.returncode}.")
        try:
            _http_json(url)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for GPT-Connect health at {url}.")


def _is_windows_app_alias(path: str | None) -> bool:
    if not path:
        return False
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        return False
    windows_apps = str(Path(local_app_data) / "Microsoft" / "WindowsApps").lower()
    return path.lower().startswith(windows_apps)


def _install_ngrok(download_url: str, install_dir: Path) -> Path:
    install_dir.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix="localcontrol-ngrok-"))
    zip_path = temp_root / "ngrok.zip"
    try:
        print("ngrok not found. Downloading ngrok for Windows...")
        print(f"Source: {download_url}")
        urllib.request.urlretrieve(download_url, zip_path)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(temp_root)
        downloaded = next(temp_root.rglob("ngrok.exe"), None)
        if not downloaded:
            raise RuntimeError("Downloaded ngrok archive did not contain ngrok.exe.")
        local_exe = install_dir / "ngrok.exe"
        shutil.copy2(downloaded, local_exe)
        print(f"Installed local ngrok: {local_exe}")
        return local_exe
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _clean_ngrok_authtoken(token: str) -> str:
    cleaned = re.sub(r"^[^A-Za-z0-9_-]+|[^A-Za-z0-9_-]+$", "", token.strip())
    if cleaned != token.strip():
        print("Removed invalid edge characters from the ngrok authtoken.")
    return cleaned


def _resolve_ngrok_executable(requested: str, download_url: str, no_auto_install: bool) -> Path:
    install_dir = Path.cwd() / ".local-tools" / "ngrok"
    local_exe = install_dir / "ngrok.exe"

    if requested and requested != "ngrok":
        found = shutil.which(requested)
        if found:
            return Path(found)
        candidate = Path(requested)
        if candidate.exists():
            return candidate.resolve()
        if no_auto_install:
            raise RuntimeError(f"Could not find ngrok at {requested}.")
        return _install_ngrok(download_url, install_dir)

    bundled_exe = _bundled_ngrok_path()
    if bundled_exe:
        return bundled_exe

    if local_exe.exists():
        return local_exe.resolve()

    found = shutil.which("ngrok")
    if found and not _is_windows_app_alias(found):
        return Path(found)

    if no_auto_install:
        raise RuntimeError("Could not find ngrok. Install ngrok, add it to PATH, or set LOCALCONTROL_NGROK_EXE.")
    return _install_ngrok(download_url, install_dir)


def _ngrok_config_paths() -> list[Path]:
    paths: list[Path] = []
    if os.getenv("NGROK_CONFIG"):
        paths.extend(Path(part) for part in os.environ["NGROK_CONFIG"].split(os.pathsep) if part)
    if os.getenv("LOCALAPPDATA"):
        paths.append(Path(os.environ["LOCALAPPDATA"]) / "ngrok" / "ngrok.yml")
    if os.getenv("APPDATA"):
        paths.append(Path(os.environ["APPDATA"]) / "ngrok" / "ngrok.yml")
    home = Path.home()
    paths.append(home / ".config" / "ngrok" / "ngrok.yml")
    paths.append(home / ".ngrok2" / "ngrok.yml")
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def _ngrok_authtoken_configured() -> bool:
    token_re = re.compile(r"(?m)^\s*authtoken\s*:")
    nested_re = re.compile(r"(?ms)^\s*agent\s*:.*?^\s+authtoken\s*:")
    for path in _ngrok_config_paths():
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if token_re.search(content) or nested_re.search(content):
            return True
    return False


def _set_ngrok_authtoken(ngrok_path: Path, token: str) -> None:
    token = _clean_ngrok_authtoken(token)
    if not token:
        raise RuntimeError("ngrok authtoken was empty.")
    print("Saving ngrok authtoken...")
    completed = subprocess.run(
        [str(ngrok_path), "config", "add-authtoken", token],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "ngrok rejected the authtoken. Get a valid token from "
            "https://dashboard.ngrok.com/get-started/your-authtoken"
        )


def _remember_ngrok_authtoken(token: str) -> None:
    os.environ["LOCALCONTROL_NGROK_AUTHTOKEN"] = token
    try:
        from localcontrol.config_store import update_config

        update_config(ngrok_authtoken=token)
    except Exception as exc:
        print(f"Warning: saved token to ngrok config, but could not update .env: {exc}")


def _prompt_and_save_ngrok_authtoken(ngrok_path: Path, reason: str | None = None) -> str:
    if reason:
        print()
        print(reason)
    print("Paste a fresh ngrok authtoken. Press Ctrl+C to stop.")
    print("Get one from: https://dashboard.ngrok.com/get-started/your-authtoken")
    while True:
        token = _clean_ngrok_authtoken(getpass.getpass("Paste ngrok authtoken: "))
        try:
            _set_ngrok_authtoken(ngrok_path, token)
        except RuntimeError as exc:
            print(str(exc))
            print("Try again with a valid ngrok authtoken.")
            continue
        _remember_ngrok_authtoken(token)
        return token


def _ensure_ngrok_authenticated(ngrok_path: Path, token: str | None, no_prompt: bool) -> None:
    if token:
        try:
            _set_ngrok_authtoken(ngrok_path, token)
            return
        except RuntimeError:
            if no_prompt:
                raise
            _prompt_and_save_ngrok_authtoken(ngrok_path, "ngrok rejected the configured authtoken.")
            return
    if _ngrok_authtoken_configured():
        return
    if no_prompt:
        raise RuntimeError("ngrok is not authenticated. Set LOCALCONTROL_NGROK_AUTHTOKEN or run ngrok config add-authtoken.")
    _prompt_and_save_ngrok_authtoken(ngrok_path, "ngrok needs an authtoken before it can start a tunnel.")


def _wait_ngrok_process_stable(process: subprocess.Popen, seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"ngrok exited early with code {process.returncode}.")
        time.sleep(0.25)


def _ngrok_public_url(configured_url: str | None, api_port: int, process: subprocess.Popen, timeout_seconds: int) -> str:
    if configured_url:
        return configured_url.rstrip("/")

    api_url = f"http://127.0.0.1:{api_port}/api/tunnels"
    deadline = time.monotonic() + max(10, timeout_seconds)
    started = time.monotonic()
    last_status = "ngrok local API has not responded yet."
    last_progress = 0.0
    last_error: str | None = None

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"ngrok exited early with code {process.returncode}. Last status: {last_status}")
        try:
            response = _http_json(api_url)
            tunnels = response.get("tunnels") or []
            for tunnel in tunnels:
                public_url = str(tunnel.get("public_url") or "")
                if public_url.startswith("https://"):
                    return public_url.rstrip("/")
            if tunnels:
                summaries = [
                    f"{tunnel.get('name') or 'unnamed'}/{tunnel.get('proto') or 'unknown'}/{tunnel.get('public_url') or '(no public_url yet)'}"
                    for tunnel in tunnels
                ]
                last_status = "ngrok tunnels: " + "; ".join(summaries)
            else:
                last_status = "ngrok local API is reachable, but no tunnel has been published yet."
            last_error = None
        except Exception as exc:
            last_error = str(exc)
            last_status = f"ngrok local API error: {last_error}"

        elapsed = time.monotonic() - started
        if elapsed - last_progress >= 15:
            print(f"Waiting for ngrok public URL... {int(elapsed)}s/{timeout_seconds}s. {last_status}")
            last_progress = elapsed
        time.sleep(1)

    message = (
        f"ngrok did not publish an HTTPS tunnel URL within {timeout_seconds} seconds. "
        f"Last status: {last_status} "
        f"Check ngrok's web interface at http://127.0.0.1:{api_port}, your authtoken/account status, "
        "and outbound network/firewall access. You can also set LOCALCONTROL_PUBLIC_URL or "
        "LOCALCONTROL_NGROK_DOMAIN to skip public URL discovery, or increase LOCALCONTROL_NGROK_URL_TIMEOUT_SECONDS."
    )
    if last_error:
        message += f" Last API error: {last_error}"
    raise RuntimeError(message)


def serve_command(args: argparse.Namespace) -> int:
    _load_env()
    if args.allow_all:
        os.environ["LOCALCONTROL_ALLOW_ALL"] = "1"
    host = args.host or os.getenv("LOCALCONTROL_BIND_HOST") or "127.0.0.1"
    port = args.port or _env_int("LOCALCONTROL_PORT", 8765)
    uvicorn.run("localcontrol.main:app", host=host, port=port)
    return 0


def tunnel_command(args: argparse.Namespace) -> int:
    _load_env()
    if args.allow_all:
        os.environ["LOCALCONTROL_ALLOW_ALL"] = "1"
    host = args.host or os.getenv("LOCALCONTROL_BIND_HOST") or "127.0.0.1"
    port = args.port or _env_int("LOCALCONTROL_PORT", 8765)
    target_host = _target_host(host)
    local_base_url = f"http://{target_host}:{port}"
    public_url = args.public_url or os.getenv("LOCALCONTROL_PUBLIC_URL")
    domain = args.ngrok_domain or os.getenv("LOCALCONTROL_NGROK_DOMAIN")
    if domain and not public_url:
        public_url = f"https://{domain}"
    download_url = args.ngrok_download_url or os.getenv("LOCALCONTROL_NGROK_DOWNLOAD_URL") or DEFAULT_NGROK_DOWNLOAD_URL
    ngrok_exe = args.ngrok_exe or os.getenv("LOCALCONTROL_NGROK_EXE") or "ngrok"
    ngrok_api_port = args.ngrok_api_port or _env_int("LOCALCONTROL_NGROK_API_PORT", 4040)
    timeout_seconds = args.ngrok_url_timeout_seconds or _env_int("LOCALCONTROL_NGROK_URL_TIMEOUT_SECONDS", 180)
    token = args.ngrok_authtoken or os.getenv("LOCALCONTROL_NGROK_AUTHTOKEN") or os.getenv("NGROK_AUTHTOKEN")

    ngrok_path = _resolve_ngrok_executable(ngrok_exe, download_url, args.no_ngrok_auto_install)
    _ensure_ngrok_authenticated(ngrok_path, token, args.no_ngrok_auth_prompt)

    api_cmd = [*_entry_command(), "serve", "--host", host, "--port", str(port)]
    if args.allow_all:
        api_cmd.append("--allow-all")

    api_process: subprocess.Popen | None = None
    ngrok_process: subprocess.Popen | None = None
    try:
        print("Starting GPT-Connect API...")
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        api_process = subprocess.Popen(api_cmd, cwd=Path.cwd(), creationflags=creationflags)
        _wait_health(f"{local_base_url}/health", api_process)

        ngrok_args = [str(ngrok_path), "http"]
        if domain:
            ngrok_args.append(f"--domain={domain}")
        ngrok_args.append(f"{target_host}:{port}")

        retry_count = 0
        while True:
            print("Starting ngrok...")
            ngrok_process = subprocess.Popen(ngrok_args, cwd=Path.cwd())
            try:
                if public_url:
                    _wait_ngrok_process_stable(ngrok_process)
                resolved_public_url = _ngrok_public_url(public_url, ngrok_api_port, ngrok_process, timeout_seconds)
                break
            except RuntimeError as exc:
                if ngrok_process and ngrok_process.poll() is None:
                    ngrok_process.terminate()
                    try:
                        ngrok_process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        ngrok_process.kill()
                if args.no_ngrok_auth_prompt or retry_count >= MAX_NGROK_AUTH_RETRIES:
                    raise
                retry_count += 1
                _prompt_and_save_ngrok_authtoken(
                    ngrok_path,
                    f"ngrok could not start or connect: {exc}",
                )

        print(f"Regenerating GPT Actions schema for {resolved_public_url}")
        output = export_schema(resolved_public_url, Path.cwd() / "gpt-actions.openapi.yaml")
        print(f"Wrote {output}")
        print()
        print(f"GPT-Connect: {local_base_url}")
        print(f"Public URL:   {resolved_public_url}")
        print(f"Schema URL:   {resolved_public_url}/gpt-actions.openapi.yaml")
        print()
        print("Leave this window open while your GPT is using GPT-Connect. Press Ctrl+C to stop.")
        ngrok_process.wait()
        return ngrok_process.returncode or 0
    finally:
        for process in (ngrok_process, api_process):
            if process and process.poll() is None:
                process.terminate()


def schema_command(args: argparse.Namespace) -> int:
    _load_env()
    output = export_schema(args.server_url, args.output)
    print(f"Wrote {output}")
    return 0


def launch_command(args: argparse.Namespace) -> int:
    from localcontrol.launcher_ui import run_prelaunch_ui

    result = run_prelaunch_ui(args.mode, open_browser=not args.no_browser)
    if result.action != "start":
        print("GPT-Connect startup canceled.")
        return 0

    next_args = argparse.Namespace(
        host=args.host,
        port=None,
        allow_all=args.allow_all,
        ngrok_domain=args.ngrok_domain,
        public_url=args.public_url,
        ngrok_exe=args.ngrok_exe,
        ngrok_download_url=args.ngrok_download_url,
        ngrok_authtoken=args.ngrok_authtoken,
        ngrok_api_port=args.ngrok_api_port,
        ngrok_url_timeout_seconds=args.ngrok_url_timeout_seconds,
        no_ngrok_auto_install=args.no_ngrok_auto_install,
        no_ngrok_auth_prompt=args.no_ngrok_auth_prompt,
    )
    if result.mode == "serve":
        return serve_command(next_args)
    return tunnel_command(next_args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="GPT-Connect", description="Windows GPT-Connect Bridge")
    parser.add_argument("--version", action="version", version=f"GPT-Connect {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="Start the API server.")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--allow-all", action="store_true")
    serve.set_defaults(func=serve_command)

    tunnel = subparsers.add_parser("tunnel", help="Start the API server and ngrok tunnel.")
    tunnel.add_argument("--host", default=None)
    tunnel.add_argument("--port", type=int, default=None)
    tunnel.add_argument("--allow-all", action="store_true")
    tunnel.add_argument("--ngrok-domain", default=None)
    tunnel.add_argument("--public-url", default=None)
    tunnel.add_argument("--ngrok-exe", default=None)
    tunnel.add_argument("--ngrok-download-url", default=None)
    tunnel.add_argument("--ngrok-authtoken", default=None)
    tunnel.add_argument("--ngrok-api-port", type=int, default=None)
    tunnel.add_argument("--ngrok-url-timeout-seconds", type=int, default=None)
    tunnel.add_argument("--no-ngrok-auto-install", action="store_true")
    tunnel.add_argument("--no-ngrok-auth-prompt", action="store_true")
    tunnel.set_defaults(func=tunnel_command)

    schema = subparsers.add_parser("schema", help="Regenerate the GPT Actions OpenAPI schema.")
    schema.add_argument("--server-url", default="https://YOUR-RESERVED-NGROK-DOMAIN.ngrok-free.app")
    schema.add_argument("--output", default=str(Path.cwd() / "gpt-actions.openapi.yaml"))
    schema.set_defaults(func=schema_command)

    launch = subparsers.add_parser("launch", help="Open settings UI first, then start GPT-Connect.")
    launch.add_argument("--mode", choices=["serve", "tunnel"], default="tunnel")
    launch.add_argument("--host", default=None)
    launch.add_argument("--allow-all", action="store_true")
    launch.add_argument("--ngrok-domain", default=None)
    launch.add_argument("--public-url", default=None)
    launch.add_argument("--ngrok-exe", default=None)
    launch.add_argument("--ngrok-download-url", default=None)
    launch.add_argument("--ngrok-authtoken", default=None)
    launch.add_argument("--ngrok-api-port", type=int, default=None)
    launch.add_argument("--ngrok-url-timeout-seconds", type=int, default=None)
    launch.add_argument("--no-ngrok-auto-install", action="store_true")
    launch.add_argument("--no-ngrok-auth-prompt", action="store_true")
    launch.add_argument("--no-browser", action="store_true")
    launch.set_defaults(func=launch_command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(argv if argv is not None else sys.argv[1:])
    if not args_list:
        args_list = ["launch", "--mode", "tunnel"] if getattr(sys, "frozen", False) else ["launch", "--mode", "serve"]
    parser = build_parser()
    args = parser.parse_args(args_list)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
