"""The workflows this app can run, one to a file.

Loading a workflow means loading its file. Nothing else describes it, so the
analysis, the script and the storyboard cannot disagree about which one is
running - which they did, when the same two workflows were spelled out
separately in the browser, the writer and the shot planner.
"""

from __future__ import annotations

from .base import Workflow
from .content import WORKFLOW as CONTENT
from .reup import WORKFLOW as REUP

DEFAULT_KEY = CONTENT.key

_WORKFLOWS: dict[str, Workflow] = {CONTENT.key: CONTENT, REUP.key: REUP}


def get(key: str | None) -> Workflow:
    """The workflow for a key, falling back to the default.

    An unknown key returns the default rather than raising: a stale value in a
    saved session or an old project row must not stop the studio opening.
    """
    return _WORKFLOWS.get(str(key or "").strip().lower(), _WORKFLOWS[DEFAULT_KEY])


def keys() -> list[str]:
    return list(_WORKFLOWS)


def all_workflows() -> list[Workflow]:
    return list(_WORKFLOWS.values())


__all__ = ["Workflow", "DEFAULT_KEY", "get", "keys", "all_workflows"]
