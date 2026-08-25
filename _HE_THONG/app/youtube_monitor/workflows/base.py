"""What one production workflow is, independent of any particular one.

The two workflows used to be described in three places at once: a registry
inside index.html, a remake mode chosen by a JavaScript equality check, and
branches scattered through the writer and the shot planner. Changing one
without the others is how the reup workflow ended up analysed with remake
rules and its scenes forced through the image generators.

A workflow is now one object in one file, and both the app and the browser
read the same one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Workflow:
    key: str
    label: str
    state: str
    summary: str
    # Step names in order. Both workflows share the wizard's panels; these are
    # only what each step is called, because the work at step five is genuinely
    # different even though the panel is the same.
    steps: tuple[str, ...]
    notes: tuple[str, ...]
    # Which brief the writer works under. This decides whether the script
    # invents or retells, and it belongs with the workflow rather than being
    # re-derived from a string comparison in the browser.
    script_mode: str
    # What a scene's picture is: drawn by an image model, or cut from the
    # source this workflow is rebuilding.
    scene_asset_type: str
    # Looking up folklore motifs only makes sense when inventing.
    uses_web_research: bool
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "state": self.state,
            "summary": self.summary,
            "steps": list(self.steps),
            "notes": list(self.notes),
            "script_mode": self.script_mode,
            "scene_asset_type": self.scene_asset_type,
            "uses_web_research": self.uses_web_research,
            **self.extra,
        }
