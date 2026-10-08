"""Bước 5.3 · T5 · the planner: a current storyboard's scenes given an edit, in the EditDocument.

    current storyboard ─→ edit_store.sync() ─→ scenes that need an edit ─→ one AI call ─→ scene edits
        ─→ edit_store.plan_scenes() (one version) ─→ (T4) _apply_edit_document ─→ timeline

What is pure here: which scenes are planned, how one planned scene (the AI's
answer, already normalised the way the legacy Edit Plan normalises it)
becomes an EditDocument edit, which overlays may stay, and what the outcome is
called. Reading the database, asking the model and normalising are main's.

* A scene is found by its timeline row (`segment_id`) in what the model
  answers - never by its place in the list, never by an orphan's candidate.
* Planned: a scene with no edit (`needs_plan`) or a stale one. A scene whose
  edit still holds (ready, or kept for a visual review) is left alone unless
  a replan names it - so the same storyboard planned twice plans nothing.
* An edit names no picture: the planner chooses how a scene is shown, it does
  not make the picture, so the row's picture - legacy or not - stays (T3 H2).
* Every overlay's words pass the script's own text checks (text_errors),
  like the script's on-screen text; one that fails is left out and named.
* Nothing here is applied: that is T4's _apply_edit_document, and only when
  the caller confirms it.
"""

from __future__ import annotations

from typing import Any, Callable

from . import edit_document

# What became of a planning run.
PLANNED, PARTIAL, BLOCKED, UNCHANGED = "planned", "partial", "blocked", "unchanged"
NOT_CURRENT, NEEDS_REBUILD, ERROR, NOT_APPLICABLE = "not_current", "needs_rebuild", "error", "not_applicable"
# Statuses that leave a scene's edit holding: never planned again unless asked.
_HOLDING = frozenset({edit_document.READY, edit_document.VISUAL_REVIEW})


class PlannerError(ValueError):
    """A planning request that cannot be met as asked (a scene that is not in the document)."""


def select(document: dict[str, Any], *, scene_keys: list[str] | None = None,
           replan: bool = False) -> tuple[list[str], list[dict[str, Any]]]:
    """(the scenes to plan, in document order; the scenes left and why).

    `scene_keys` limits the run to those scenes; `replan` plans them even when
    their edit still holds. A scene without a timeline row has no voice or
    length to plan against yet: it waits.
    """
    known = [item["scene_key"] for item in document["scenes"]]
    if scene_keys is not None:
        unknown = sorted(set(scene_keys) - set(known))
        if unknown:
            raise PlannerError(f"Không có cảnh {', '.join(unknown)} trong EditDocument")
    chosen: list[str] = []
    left: list[dict[str, Any]] = []
    for item in document["scenes"]:
        key = item["scene_key"]
        if scene_keys is not None and key not in scene_keys:
            continue
        if item.get("segment_id") is None:
            left.append({"scene_key": key, "segment_id": None, "reason": "no_row"})
        elif item.get("status") in _HOLDING and not replan:
            left.append({"scene_key": key, "segment_id": item["segment_id"], "reason": "holding"})
        else:
            chosen.append(key)
    return chosen, left


def overlays_through(overlays: list[dict[str, Any]],
                     check: Callable[[list[dict[str, Any]]], list[str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(the overlays whose words pass `check`, the ones left out with why). An overlay without words passes."""
    kept, rejected = [], []
    for overlay in overlays:
        text = str(overlay.get("text") or "").strip()
        errors = check([{"text": text}]) if text else []
        if errors:
            rejected.append({"text": text, "errors": errors})
        else:
            kept.append(overlay)
    return kept, rejected


def scene_edit(*, kind: str, fps: int, reason: str, transform: dict[str, Any], transition: str, effect: str,
               note: str, trim_head: float, trim_tail: float, cleanups: list[dict[str, Any]],
               sound_cues: list[dict[str, Any]], beats: list[dict[str, Any]]) -> dict[str, Any]:
    """One planned scene as an EditDocument edit - the columns the legacy Edit Plan writes, by the same names.

    No `visual_path`: the planner says how the scene is shown, not which file
    shows it, so applying it never replaces the row's picture.
    """
    return edit_document.edit({
        "visual_kind": kind[:20], "visual_fps": max(0, min(int(fps), 60)), "visual_kind_reason": reason[:500],
        "content_dna": transform.get("content_dna") or {}, "visual_strategy": str(transform.get("visual_strategy") or "")[:80],
        "visual_provider": str(transform.get("provider") or "")[:80],
        "source_dependency": str(transform.get("source_dependency") or "")[:20],
        "risk_level": str(transform.get("risk_level") or "")[:20],
        "transform_actions": list(transform.get("transform_actions") or []),
        "required_assets": list(transform.get("required_assets") or []),
        "edit_transition": transition[:20], "edit_effect": effect[:20], "edit_note": note[:400],
        "edit_trim_head": max(0.0, float(trim_head)), "edit_trim_tail": max(0.0, float(trim_tail)),
        "edit_cleanups": list(cleanups),
    }, overlays=list(transform.get("overlays") or []), sound_cues=list(sound_cues),
        direction=dict(transform.get("direction") or {}), beats=list(beats))


def outcome(wanted: list[str], planned: list[str], problems: dict[str, str]) -> str:
    """What a run is called: never a success while a scene it was asked to plan is still without its edit."""
    if not wanted:
        return UNCHANGED
    if not planned:
        return BLOCKED
    return PARTIAL if problems else PLANNED
