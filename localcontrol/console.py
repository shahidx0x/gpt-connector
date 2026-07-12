from __future__ import annotations

import sys
import threading

from .execution_log import execution_log

_console_lock = threading.Lock()


def mirror_execution_event(
    *,
    session_id: str,
    stream: str,
    text: str,
    shell: str | None = None,
    cwd: str | None = None,
    source: str | None = None,
) -> None:
    event = execution_log.append(
        run_id=session_id,
        stream=stream,  # type: ignore[arg-type]
        text=text,
        shell=shell,
        cwd=cwd,
        source=source,
    )
    prefix = f"[{event.timestamp}] [{session_id}] [{stream}]"
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
