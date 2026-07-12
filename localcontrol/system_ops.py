from __future__ import annotations

import ctypes
import getpass
import os
import platform
import socket
import sys

from .models import SystemInfoResponse


def _is_admin() -> bool | None:
    if os.name != "nt":
        return os.geteuid() == 0 if hasattr(os, "geteuid") else None
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001 - Windows API can fail in restricted hosts.
        return None


def system_info() -> SystemInfoResponse:
    return SystemInfoResponse(
        os=os.name,
        platform=platform.platform(),
        hostname=socket.gethostname(),
        user=getpass.getuser(),
        process_id=os.getpid(),
        python=sys.version,
        cwd=os.getcwd(),
        is_admin=_is_admin(),
    )

