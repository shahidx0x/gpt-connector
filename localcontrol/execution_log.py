from __future__ import annotations

import threading
from collections import deque
from typing import Iterable, Literal

from .models import ExecutionLogEvent, ExecutionLogResponse
from .utils import utc_now_iso

ExecutionStream = Literal["command", "stdin", "stdout", "stderr", "system"]


class ExecutionLogStore:
    def __init__(self, max_events: int = 20_000) -> None:
        self._events: deque[ExecutionLogEvent] = deque()
        self._next_event_id = 1
        self._max_events = max_events
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._next_event_id = 1

    def append(
        self,
        *,
        run_id: str,
        stream: ExecutionStream,
        text: str,
        shell: str | None = None,
        cwd: str | None = None,
        source: str | None = None,
    ) -> ExecutionLogEvent:
        with self._lock:
            event = ExecutionLogEvent(
                event_id=self._next_event_id,
                timestamp=utc_now_iso(),
                run_id=run_id,
                stream=stream,
                text=text,
                shell=shell,
                cwd=cwd,
                source=source,
            )
            self._events.append(event)
            self._next_event_id += 1
            while len(self._events) > self._max_events:
                self._events.popleft()
            return event

    def query(
        self,
        *,
        after_event_id: int = 0,
        max_events: int = 200,
        run_id: str | None = None,
        streams: Iterable[ExecutionStream] | None = None,
    ) -> ExecutionLogResponse:
        stream_filter = set(streams or [])
        with self._lock:
            matching = [
                event
                for event in self._events
                if event.event_id > after_event_id
                and (run_id is None or event.run_id == run_id)
                and (not stream_filter or event.stream in stream_filter)
            ]
            events = matching[:max_events]
            return ExecutionLogResponse(
                events=events,
                next_event_id=self._next_event_id,
                truncated=len(matching) > len(events),
            )


execution_log = ExecutionLogStore()
