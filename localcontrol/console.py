from __future__ import annotations

import sys
import threading

from .utils import utc_now_iso

_console_lock = threading.Lock()


def mirror_execution_event(
    *,
    session_id: str,
    stream: str,
    text: str,
    shell: str | None = None,
    cwd: str | None = None,
) -> None:
    prefix = f"[{utc_now_iso()}] [{session_id}] [{stream}]"
    details = []
    if shell:
        details.append(f"shell={shell}")
    if cwd:
        details.append(f"cwd={cwd}")
    if details:
        prefix = f"{prefix} {' '.join(details)}"
    with _console_lock:
        print(prefix, file=sys.stdout, flush=True)
        if text:
            print(text.rstrip("\n"), file=sys.stdout, flush=True)
