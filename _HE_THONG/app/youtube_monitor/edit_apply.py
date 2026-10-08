"""Bước 5.3 · T3 · applying a planned project's EditDocument to its timeline.

    current EditDocument ─→ each scene's effective_edit() ─→ apply_edit_document_rows() ─→ timeline rows + edit beats
                                                                                      └→ edit_apply record (what each row now holds)

The one way an EditDocument reaches the timeline. Nothing calls it yet: the
reconcile still copies edit columns (until T4), and manual and AI edits are
wired to the EditDocument in T6.

What is applied, scene by scene:

* only a scene whose edit was made for it and still holds: `ready`, or kept
  for a `visual_review`. A scene with no edit (`needs_plan`) or a stale one
  (`stale_content`, `stale_overlays`, `stale_timing`) is skipped and its row
  left as it is;
* its edit as it plays now (effective_edit: retimed to the voice), into the
  owned columns (database.EDIT_OWNED_COLUMNS) and the row's edit beats -
  never its voice, subtitles, length or status;
* its picture only when the edit names one (`visual.visual_path`): then the
  EditDocument owns the row's visual and writes all of it. An edit without
  one leaves the picture the row has - a legacy one included - as it is.
  No file is ever deleted;
* its edit beats only when the edit names some: then they replace the row's.
  An edit without beats leaves the row's beats - a legacy insert included -
  as they are: naming none is not asking for none. Beats a scene job points
  at are never replaced (the row is skipped, `beat_has_jobs`);
* an edit whose values the timeline cannot hold (a value of the wrong type,
  an empty value where one is needed, a beat with fields no beat has) is
  skipped as `invalid_edit` - the other scenes are still applied. Only an
  error of the system itself rolls the whole apply back.

Before a row is written, what it holds is checked against what the
EditDocument last knew it to hold: the state the latest apply left it in;
else the legacy layers kept as an orphan of that very row (by segment_id -
never by the orphan's `candidate`, which names a scene of an older cut); else
nothing ever written. A row that holds anything else was written since by
another path (a scene job, the legacy Edit Plan, a hand edit, a reconcile):
it is a conflict, not written, and the other scenes are still applied.
"""

from __future__ import annotations

import json
from typing import Any

from . import edit_document, edit_store
from .database import EDIT_BEAT_COLUMNS, EDIT_OWNED_COLUMNS, StoredEditApplyError

# Why a scene was not applied (besides a conflict).
NEEDS_PLAN, STALE, NO_ROW, INVALID_EDIT = "needs_plan", "stale", "no_row", "invalid_edit"
_APPLICABLE = frozenset({edit_document.VISUAL_REVIEW})
_SCALAR = (str, int, float, bool, type(None))
# The visual columns kept as JSON text, and what that text must hold.
_JSON_COLUMNS = {"content_dna": dict, "transform_actions": list, "required_assets": list, "edit_cleanups": list}


class InvalidEditError(Exception):
    """An edit the timeline cannot hold - a fault of the EditDocument's data, never of the system."""


def state_hash(segment: dict[str, Any], beats: list[dict[str, Any]]) -> str:
    """What a timeline row holds of an edit, as one hash - read the way the legacy orphans were read (timeline_edit)."""
    return edit_document.edit_hash(edit_store.timeline_edit(segment, beats))


DEFAULT_HASH = edit_document.edit_hash(edit_document.normalize_edit(None))


def _column_value(column: str, value: Any) -> Any:
    """A value as the column keeps it: the JSON columns as JSON text of their kind, the rest as they are.

    Whether a plain value fits its column (type, NOT NULL) is the table's own
    declaration, checked by the database before it writes.
    """
    kind = _JSON_COLUMNS.get(column)
    if kind is not None:
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except ValueError:
                raise InvalidEditError(f"{column}: không phải JSON") from None
            if not isinstance(parsed, kind):
                raise InvalidEditError(f"{column}: phải là {kind.__name__}")
            return value
        if not isinstance(value, kind):
            raise InvalidEditError(f"{column}: phải là {kind.__name__}")
        return json.dumps(value, ensure_ascii=False)
    if not isinstance(value, _SCALAR):
        raise InvalidEditError(f"{column}: giá trị không phải số hoặc chữ")
    return value


def row_writes(effective: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]] | None, bool]:
    """(the owned columns to write, the edit beats or None, whether the EditDocument owns the row's picture).

    An edit that names a picture owns the row's whole visual: every visual
    column is written, the ones it does not name back to their default. An
    edit that names none writes only the look it names, never the picture.
    An edit that names no beats gives None: the row's beats are left alone.
    Raises InvalidEditError for an edit the timeline cannot hold.
    """
    value = edit_document.normalize_edit(effective)
    visual = value["visual"]
    owned = bool(str(visual.get("visual_path") or "").strip())
    if owned:
        updates = {column: _column_value(column, visual.get(column, default))
                   for column, default in edit_store._VISUAL_COLUMNS.items()}
        if "asset_type" in visual:
            updates["asset_type"] = _column_value("asset_type", visual["asset_type"])
    else:
        updates = {column: _column_value(column, visual[column]) for column in visual
                   if column in edit_store._VISUAL_COLUMNS and column != "visual_path"}
    for name, column in (("overlays", "overlays"), ("sound_cues", "sound_cues")):
        if any(not isinstance(item, dict) for item in value["layers"][name]):
            raise InvalidEditError(f"{column}: mỗi phần tử phải là object")
        updates[column] = _json_text(column, value["layers"][name])
    updates["edit_direction"] = _json_text("edit_direction", value["layers"]["direction"])
    if not value["beats"]:
        return updates, None, owned
    beats = []
    for number, beat in enumerate(value["beats"], start=1):
        if not isinstance(beat, dict):
            raise InvalidEditError(f"beat {number}: không phải object")
        fields = {key: item for key, item in beat.items() if key not in edit_store._BEAT_SKIP and key != "beat_index"}
        unknown = sorted(set(fields) - set(EDIT_BEAT_COLUMNS))
        if unknown:
            raise InvalidEditError(f"beat {number}: trường không có trong beat: {', '.join(unknown)}")
        if any(not isinstance(item, _SCALAR) for item in fields.values()):
            raise InvalidEditError(f"beat {number}: giá trị không phải số hoặc chữ")
        beats.append(fields)
    return updates, beats, owned


def _json_text(column: str, value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise InvalidEditError(f"{column}: không ghi được thành JSON") from None


def _fresh(document: dict[str, Any], now: dict[str, Any]) -> bool:
    """Whether the document was built against the timeline and voices as they are now."""
    if str(document["provenance"].get("voice_fingerprint") or "") != str(now["voice_fingerprint"] or ""):
        return False
    for scene in document["scenes"]:
        key = scene["scene_key"]
        if scene.get("segment_id") != now["segments"].get(key):
            return False
        if key in now["voices"]:
            voice, held = now["voices"][key], scene.get("voice") or {}
            if (str(voice["audio_signature"]), str(voice["voice_fingerprint"]), float(voice["duration_seconds"]),
                    bool(voice["fits"])) != (str(held.get("audio_signature") or ""), str(held.get("voice_fingerprint") or ""),
                                             float(held.get("duration_seconds") or 0), bool(held.get("fits"))):
                return False
    return True


def plan(document: dict[str, Any], *, scene_keys: list[str] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(the rows to apply, the scenes skipped and why) - pure, from the document alone."""
    known = [scene["scene_key"] for scene in document["scenes"]]
    if scene_keys is not None:
        unknown = sorted(set(scene_keys) - set(known))
        if unknown:
            raise edit_store.EditStoreError(f"Không có cảnh {', '.join(unknown)} trong EditDocument", status_code=422)
    # The legacy layers each row had before any EditDocument, by the row they were read from.
    legacy = {int(item["segment_id"]): edit_document.edit_hash(item["edit"])
              for item in document.get("orphans") or []
              if item.get("reason") == edit_document.LEGACY and item.get("segment_id") is not None}
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for scene in document["scenes"]:
        key = scene["scene_key"]
        if scene_keys is not None and key not in scene_keys:
            continue
        segment_id = scene.get("segment_id")
        statuses = set(scene.get("statuses") or [])
        if segment_id is None:
            skipped.append({"segment_id": None, "scene_key": key, "reason": NO_ROW})
            continue
        if edit_document.NEEDS_PLAN in statuses:
            skipped.append({"segment_id": segment_id, "scene_key": key, "reason": NEEDS_PLAN})
            continue
        if statuses - _APPLICABLE:
            skipped.append({"segment_id": segment_id, "scene_key": key, "reason": STALE,
                            "statuses": [status for status in edit_document.STATUSES if status in statuses]})
            continue
        effective = edit_document.effective_edit(scene)
        try:
            updates, beats, owned = row_writes(effective)
        except InvalidEditError as exc:
            skipped.append({"segment_id": segment_id, "scene_key": key, "reason": INVALID_EDIT, "detail": str(exc)})
            continue
        rows.append({"segment_id": int(segment_id), "scene_key": key, "layer_hash": edit_document.edit_hash(effective),
                     "legacy_hash": legacy.get(int(segment_id)), "default_hash": DEFAULT_HASH,
                     "updates": updates, "beats": beats, "visual_owned": owned})
    return rows, skipped


def apply_scenes(database: Any, project_id: int, script_id: int, storyboard_row: dict[str, Any], *,
                 scene_keys: list[str] | None = None) -> dict[str, Any]:
    """Apply the script's current EditDocument to its timeline: {"applied", "unchanged", "skipped", "conflicts", ...}.

    The document must be the current storyboard's (edit_store.current) and
    built against the timeline rows and voices as they are now - otherwise
    nothing is written (EditStoreError: sync it first). `scene_keys` limits
    the apply to those scenes.
    """
    found = edit_store.current(database, project_id, script_id, storyboard_row)
    if found["state"] != edit_store.CURRENT:
        raise edit_store.EditStoreError("Chưa có EditDocument của storyboard hiện hành: hãy đồng bộ trước khi áp xuống timeline")
    document = found["document"]
    now = edit_store.snapshot(database, project_id, script_id, found["storyboard"])
    if not _fresh(document, now):
        raise edit_store.EditStoreError("EditDocument chưa theo kịp timeline và giọng hiện tại: hãy đồng bộ trước khi áp")
    rows, skipped = plan(document, scene_keys=scene_keys)
    if not rows:
        return {"document_hash": found["document_hash"], "artifact_id": None, "applied": [], "unchanged": [],
                "skipped": skipped, "conflicts": []}
    record = {"document_hash": found["document_hash"], "document_artifact_id": found["artifact_id"],
              "storyboard_hash": document["provenance"]["storyboard_hash"], "skipped_scenes": skipped}
    try:
        done = database.apply_edit_document_rows(project_id, script_id, rows, state_hash=state_hash, record=record)
    except StoredEditApplyError as exc:
        raise edit_store.EditStoreError(str(exc)) from exc
    return {"document_hash": found["document_hash"], "artifact_id": done["artifact_id"], "applied": done["written"],
            "unchanged": done["unchanged"], "skipped": skipped + done["skipped"], "conflicts": done["conflicts"]}


assert set(edit_store._VISUAL_COLUMNS) | {"asset_type", "overlays", "sound_cues", "edit_direction"} == EDIT_OWNED_COLUMNS, \
    "the columns an apply writes are the ones an EditDocument reads back"
