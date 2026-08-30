"""Serve a tool's last known status now, and find out the truth in the background.

Checking whether a CLI is logged in means launching it, which costs one to
two seconds each. Six endpoints the page polls every three seconds ask for
those statuses, so a twenty-second cache still left every request that
happened to land on an expiry paying the full probe — several of them at
once, each holding a worker thread. The interface stalled for seconds at a
time on a rhythm nobody could see, and changing a single dropdown could take
longer than the work it configured.

A status that is a couple of seconds out of date is not worth blocking a
request for. The first caller waits, because there is nothing to serve yet;
after that the cached answer goes back immediately and one background thread
goes and gets a fresh one.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable


class BackgroundStatus:
    """One tool's cached status, refreshed off the request path."""

    def __init__(self, probe: Callable[[], dict[str, Any]], ttl_seconds: float = 20.0):
        self._probe = probe
        self._ttl = max(1.0, float(ttl_seconds))
        self._lock = threading.Lock()
        self._value: dict[str, Any] | None = None
        self._fetched_at = 0.0
        self._refreshing = False

    def _run_probe(self) -> dict[str, Any]:
        result = self._probe()
        with self._lock:
            self._value = result
            self._fetched_at = time.monotonic()
            self._refreshing = False
        return result

    def _refresh_later(self) -> None:
        thread = threading.Thread(target=self._safe_probe, daemon=True)
        thread.start()

    def _safe_probe(self) -> None:
        try:
            self._run_probe()
        except Exception:
            # A failed refresh must not kill the thread's process or wedge the
            # flag; the stale value keeps being served until the next attempt.
            with self._lock:
                self._refreshing = False

    def get(self, *, force: bool = False) -> dict[str, Any]:
        with self._lock:
            value = self._value
            stale = value is None or (time.monotonic() - self._fetched_at) >= self._ttl
            start_refresh = bool(value is not None and stale and not self._refreshing and not force)
            if start_refresh:
                self._refreshing = True
        if force or value is None:
            # Nothing to serve yet, or the caller asked for the truth.
            return self._run_probe()
        if start_refresh:
            self._refresh_later()
        return value

    def invalidate(self) -> None:
        with self._lock:
            self._value = None
            self._fetched_at = 0.0
