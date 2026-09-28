"""Recent contact from an interactive chat's MCP bridge.

This is deliberately a liveness hint, not proof that the chat can execute a
particular task. A configured tunnel ID alone is never treated as readiness.
"""

from __future__ import annotations

from threading import Lock
from time import monotonic


CHAT_AGENTS = {"chatgpt_app", "claude_chat"}
_LAST_SEEN: dict[str, float] = {}
_LOCK = Lock()
_TTL_SECONDS = 300.0


def record_contact(agent: str) -> None:
    if agent not in CHAT_AGENTS:
        raise ValueError("Unknown chat agent")
    with _LOCK:
        _LAST_SEEN[agent] = monotonic()


def connected(agent: str) -> bool:
    if agent not in CHAT_AGENTS:
        return False
    with _LOCK:
        last_seen = _LAST_SEEN.get(agent)
    return last_seen is not None and monotonic() - last_seen <= _TTL_SECONDS
