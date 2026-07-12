from __future__ import annotations

import os
import platform
import shutil

from .errors import LocalControlError

WINDOWS_NGROK_DOWNLOAD_URL = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip"
LINUX_AMD64_NGROK_DOWNLOAD_URL = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz"
LINUX_ARM64_NGROK_DOWNLOAD_URL = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.tgz"


def is_windows() -> bool:
    return os.name == "nt"


def default_shell() -> str:
    return "powershell" if is_windows() else "bash"


def resolve_shell(shell: str) -> str:
    return default_shell() if shell == "auto" else shell


def _powershell_executable() -> str | None:
    names = ("powershell.exe", "pwsh") if is_windows() else ("pwsh", "powershell")
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _bash_executable() -> str | None:
    return shutil.which("bash") or ("/bin/bash" if os.path.exists("/bin/bash") else None)


def _sh_executable() -> str | None:
    return shutil.which("sh") or ("/bin/sh" if os.path.exists("/bin/sh") else None)


def shell_command_args(shell: str, command: str) -> tuple[str, list[str]]:
    resolved = resolve_shell(shell)
    if resolved == "cmd":
        if not is_windows():
            raise LocalControlError("shell_not_supported", "cmd.exe is only available on Windows.", status_code=422)
        exe = shutil.which("cmd.exe") or "cmd.exe"
        return resolved, [exe, "/d", "/s", "/c", command]
    if resolved == "powershell":
        exe = _powershell_executable()
        if not exe:
            raise LocalControlError("shell_not_found", "PowerShell was not found. Install pwsh or choose bash/sh.", status_code=500)
        args = [exe, "-NoLogo", "-NoProfile", "-NonInteractive"]
        if is_windows():
            args.extend(["-ExecutionPolicy", "Bypass"])
        args.extend(["-Command", command])
        return resolved, args
    if resolved == "bash":
        exe = _bash_executable()
        if not exe:
            raise LocalControlError("shell_not_found", "bash was not found. Install bash or choose sh.", status_code=500)
        return resolved, [exe, "--noprofile", "--norc", "-c", command]
    if resolved == "sh":
        exe = _sh_executable()
        if not exe:
            raise LocalControlError("shell_not_found", "sh was not found.", status_code=500)
        return resolved, [exe, "-c", command]
    raise LocalControlError("shell_not_supported", f"Unsupported shell: {shell}", status_code=422)


def shell_session_args(shell: str) -> tuple[str, list[str]]:
    resolved = resolve_shell(shell)
    if resolved == "cmd":
        if not is_windows():
            raise LocalControlError("shell_not_supported", "cmd.exe is only available on Windows.", status_code=422)
        return resolved, [shutil.which("cmd.exe") or "cmd.exe", "/Q", "/D", "/K"]
    if resolved == "powershell":
        exe = _powershell_executable()
        if not exe:
            raise LocalControlError("shell_not_found", "PowerShell was not found. Install pwsh or choose bash/sh.", status_code=500)
        args = [exe, "-NoLogo", "-NoProfile", "-NoExit"]
        if is_windows():
            args.extend(["-ExecutionPolicy", "Bypass"])
        args.extend(["-Command", "-"])
        return resolved, args
    if resolved == "bash":
        exe = _bash_executable()
        if not exe:
            raise LocalControlError("shell_not_found", "bash was not found. Install bash or choose sh.", status_code=500)
        return resolved, [exe, "--noprofile", "--norc"]
    if resolved == "sh":
        exe = _sh_executable()
        if not exe:
            raise LocalControlError("shell_not_found", "sh was not found.", status_code=500)
        return resolved, [exe]
    raise LocalControlError("shell_not_supported", f"Unsupported shell: {shell}", status_code=422)


def ngrok_binary_name() -> str:
    return "ngrok.exe" if is_windows() else "ngrok"


def default_ngrok_download_url() -> str:
    if is_windows():
        return WINDOWS_NGROK_DOWNLOAD_URL
    if platform.system().lower() == "linux":
        machine = platform.machine().lower()
        if machine in {"x86_64", "amd64"}:
            return LINUX_AMD64_NGROK_DOWNLOAD_URL
        if machine in {"aarch64", "arm64"}:
            return LINUX_ARM64_NGROK_DOWNLOAD_URL
    raise LocalControlError(
        "ngrok_platform_unsupported",
        f"No default ngrok download URL is configured for {platform.system()} {platform.machine()}. "
        "Install ngrok yourself or set LOCALCONTROL_NGROK_EXE/LOCALCONTROL_NGROK_DOWNLOAD_URL.",
        status_code=500,
    )
