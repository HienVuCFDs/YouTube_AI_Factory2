"""What is running right now in this process, and how the last run ended.

Long work - analysing a source, planning a video, researching a channel -
outlives the request that started it: a reload drops the request, not the
work. The work is recorded here, where it happens, so a page asks instead of
remembering, and a second click, a second tab or an orchestrator cannot start
the same work twice. It goes with a restart, together with the work.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Hashable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: dict[Hashable, dict[str, Any]] = {}
        self._last: dict[Hashable, dict[str, Any]] = {}

    def claim(self, key: Hashable, **info: Any) -> dict[str, Any] | None:
        """Start a run for `key`; None when one is already going."""
        with self._lock:
            if key in self._running:
                return None
            run = {"run_id": uuid.uuid4().hex[:12], "started_at": _now(), **info}
            self._running[key] = run
            return dict(run)

    def update(self, key: Hashable, **fields: Any) -> None:
        """Note progress on a running run (a stage reached, a count)."""
        with self._lock:
            if key in self._running:
                self._running[key].update(fields)

    def finish(self, key: Hashable, outcome: dict[str, Any]) -> None:
        with self._lock:
            run = self._running.pop(key, {})
            self._last[key] = {**run, **outcome, "finished_at": _now()}

    def state(self, key: Hashable) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """The run going on now, and the one that last finished."""
        with self._lock:
            running = self._running.get(key)
            last = self._last.get(key)
            return (dict(running) if running else None), (dict(last) if last else None)

    def is_running(self, key: Hashable) -> bool:
        with self._lock:
            return key in self._running
