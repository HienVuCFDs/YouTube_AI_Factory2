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
nothing ever written. A row whose columns this apply writes hold anything
else was written since by another path (a scene job, the legacy Edit Plan, a
hand edit, a reconcile): it is a conflict, not written, and the other scenes
are still applied.

P2-4 · F1: only the columns this apply writes are compared (ScopedCheck). A
column it does not write - the scene's picture description, a beat list the
plan names none of - may hold a hand edit without a conflict: the apply leaves
it as it is. What the record keeps as known (`state_edit`) is what the
EditDocument knew before, with only the columns it wrote replaced: a hand edit
it did not write is never taken as known, so an edit that later writes that
column still finds it and stops. A record from before F1 (no `state_edit`) is
read column by column when the edit it wrote can be found and the row it left
is proven by its state_hash; otherwise the whole row is compared, as before.
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

# P2-4 · F1: a row's state read column by column. "beats" names the row's edit beats as one part.
BEATS = "beats"
_LAYER_PARTS = {"overlays": "overlays", "sound_cues": "sound_cues", "edit_direction": "direction"}


def state_edit(segment: dict[str, Any], beats: list[dict[str, Any]]) -> dict[str, Any]:
    """What a timeline row holds of an edit, in the EditDocument's shape (state_hash is its hash)."""
    return edit_store.timeline_edit(segment, beats)


def _part(state: dict[str, Any], column: str) -> Any:
    """One column of a row's state: a visual column, a layer (with its unparsed text, if any) or the beats."""
    if column == BEATS:
        return state["beats"]
    if column in _LAYER_PARTS:
        return [state["layers"][_LAYER_PARTS[column]], state["visual"].get(f"unparsed_{column}")]
    return state["visual"].get(column)


def with_parts(base: dict[str, Any], source: dict[str, Any], columns: set[str] | frozenset[str]) -> dict[str, Any]:
    """`base` with the given columns taken from `source` - the others left exactly as `base` has them."""
    out = edit_document.normalize_edit(base)
    source = edit_document.normalize_edit(source)
    for column in columns:
        if column == BEATS:
            out["beats"] = json.loads(json.dumps(source["beats"]))
            continue
        keys = [f"unparsed_{column}"] if column in _LAYER_PARTS else [column]
        if column in _LAYER_PARTS:
            out["layers"][_LAYER_PARTS[column]] = json.loads(json.dumps(source["layers"][_LAYER_PARTS[column]]))
        for key in keys:
            if key in source["visual"]:
                out["visual"][key] = source["visual"][key]
            else:
                out["visual"].pop(key, None)
    return out


def changed_columns(current: dict[str, Any], expected: dict[str, Any], columns: set[str] | frozenset[str]) -> list[str]:
    """The columns, of those given, whose value in `current` is not the one in `expected`."""
    current, expected = edit_document.normalize_edit(current), edit_document.normalize_edit(expected)
    return sorted(column for column in columns if _part(current, column) != _part(expected, column))


def _written(row: dict[str, Any]) -> set[str]:
    """The columns an apply of this planned row writes: its owned columns, and the beats when it names some."""
    return set(row["updates"]) | ({BEATS} if row.get("beats") is not None else set())


def _target(row: dict[str, Any], segment: dict[str, Any], beats: list[dict[str, Any]]) -> dict[str, Any]:
    """Bước 05 · T6b · 5A: what the row reads as once this apply has written it (state_edit's shape).

    The owned columns as the apply writes them (`updates`, the values the
    columns keep) and its beats as they are inserted - numbered from 1, only
    the columns the plan names. A beat the plan leaves a column out of reads
    without it, so it never equals a stored beat (that has every column): the
    part stays a conflict - never a guess at a default.
    """
    new_beats = row.get("beats")
    after = beats if new_beats is None else [
        {"beat_index": number, **{column: beat[column] for column in EDIT_BEAT_COLUMNS if column in beat}}
        for number, beat in enumerate(new_beats, start=1)]
    return state_edit({**segment, **row["updates"]}, after)


# Bước 05 · T6b: the `expected_from` of a conflict whose decision (ScopedCheck.accept) no longer matches the row or the plan.
DECISION_OUTDATED = "decision_outdated"


class ScopedCheck:
    """P2-4 · F1: whether a planned row may be written - asked by apply_edit_document_rows inside its transaction.

    verdict(): a conflict is a column this apply writes that holds something
    else than the EditDocument last knew (`base`): from the latest apply
    record's `state_edit`; else, for a record from before F1, rebuilt from the
    edit it wrote (`known`: layer_hash → the state that edit writes) and
    proven by its state_hash - or, when that cannot be done, the whole row as
    before F1; else the legacy layers kept as an orphan of that row; else
    nothing ever written. settle(): what the record keeps as known after a
    write - `base` with only the written columns replaced.

    Bước 05 · T6b:
    * 5A - a column that already holds exactly what this apply writes is no
      conflict: writing it changes nothing. It is known as it is (`base`).
    * `accept` - segment_id → {"columns", "state_hash", "layer_hash"}: a
      person's decision to write the plan over those columns ("*": the row
      as a whole). It holds only while the row is still the very one they
      saw (state_hash, read here, inside the apply's transaction) and the
      plan the one they saw (layer_hash); else the row is a conflict
      (DECISION_OUTDATED) and nothing of it is written. `rewrite` in the
      verdict: the row the last apply wrote this very plan to is written
      again (Database.apply_edit_document_rows would take it as unchanged) -
      only when the decided parts do not hold the plan and every other part
      it writes already does (_rewrite).
    """

    def __init__(self, known: dict[str, dict[str, Any]] | None = None,
                 accept: dict[int, dict[str, Any]] | None = None) -> None:
        self.known = known or {}
        self.accept = {int(key): value for key, value in (accept or {}).items()}

    def verdict(self, row: dict[str, Any], segment: dict[str, Any], beats: list[dict[str, Any]],
                applied: dict[str, Any] | None) -> dict[str, Any]:
        current = state_edit(segment, beats)
        written = _written(row)
        decision = self.accept.get(int(row["segment_id"]))
        if decision is not None and (state_hash(segment, beats) != decision["state_hash"]
                                     or row["layer_hash"] != decision["layer_hash"]):
            return {"conflict": True, "source": DECISION_OUTDATED, "columns": sorted(decision["columns"]), "base": None}
        whole = decision is not None and "*" in decision["columns"]
        accepted = set(written) if whole else (set(decision["columns"]) & written if decision is not None else set())
        if applied is not None:
            base, source = applied.get("state_edit"), "applied"
            if base is None:
                base = self._rebuilt(row, current, applied)
            if base is None:
                # Only the whole row can be said to differ. It is known as it stands when nothing in it is unknown to
                # the plan: it is the row the record proves, the plan's own edit is the very row (a decision to keep
                # the timeline, T6b), or a person decided to write the plan over the row as a whole.
                same = edit_document.edit_hash(current) == applied["state_hash"]
                if same or whole or row["layer_hash"] == edit_document.edit_hash(current):
                    return {"conflict": False, "source": source, "columns": [], "base": current,
                            "rewrite": whole and self._rewrite(row, segment, beats, current, written)}
                return {"conflict": True, "source": source, "columns": ["*"], "base": None}
        elif row.get("legacy_edit") is not None:
            base, source = row["legacy_edit"], "legacy"
        else:
            base, source = edit_document.normalize_edit(None), "default"
        base = edit_document.normalize_edit(base)
        if accepted:
            base = with_parts(base, current, accepted)
        found = changed_columns(current, base, written)
        if found:
            # 5A: of the parts that moved, those already holding exactly what this apply writes are no conflict.
            there = set(found) - set(changed_columns(current, _target(row, segment, beats), found))
            if there:
                base = with_parts(base, current, there)
                found = [column for column in found if column not in there]
        return {"conflict": bool(found), "source": source, "columns": found, "base": base,
                "rewrite": bool(accepted) and not found and self._rewrite(row, segment, beats, current, accepted)}

    @staticmethod
    def _rewrite(row: dict[str, Any], segment: dict[str, Any], beats: list[dict[str, Any]], current: dict[str, Any],
                 accepted: set[str]) -> bool:
        """Whether a decision makes this apply write a row it would take as unchanged (it last wrote this very plan).

        Only when the decided parts do not hold the plan yet and every other
        part the apply writes holds it exactly already: the write then changes
        those parts only - never one outside the decision.
        """
        target = _target(row, segment, beats)
        return bool(changed_columns(current, target, accepted)) and not changed_columns(current, target, _written(row) - accepted)

    @staticmethod
    def settle(base: dict[str, Any], segment: dict[str, Any], beats: list[dict[str, Any]], row: dict[str, Any]) -> dict[str, Any]:
        return with_parts(base, state_edit(segment, beats), _written(row))

    def _rebuilt(self, row: dict[str, Any], current: dict[str, Any], applied: dict[str, Any]) -> dict[str, Any] | None:
        """What a record from before F1 knew, column by column - only when its state_hash proves it."""
        wrote = self.known.get(str(applied.get("layer_hash") or ""))
        if wrote is None:
            return None
        columns = set(applied["columns_written"]) if isinstance(applied.get("columns_written"), list) else set(EDIT_OWNED_COLUMNS)
        candidate = with_parts(row.get("legacy_edit") or edit_document.normalize_edit(None), wrote, columns)
        if (applied.get("beats_written") is not None) if "beats_written" in applied else True:
            candidate = with_parts(candidate, current, {BEATS})
        return candidate if edit_document.edit_hash(candidate) == applied["state_hash"] else None


def known_writes(database: Any, project_id: int, script_id: int, document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """layer_hash → the state that edit writes to a row, for every scene edit of the script's EditDocuments (this one and
    its history) - how a record from before F1 is read column by column. Read only; an unreadable history gives less."""
    documents = [document]
    try:
        documents += [entry["document"] for entry in edit_store.history(database, project_id, script_id)]
    except edit_store.EditStoreError:
        pass
    found: dict[str, dict[str, Any]] = {}
    for item in documents:
        for scene in item.get("scenes") or []:
            if scene.get("basis") is None:
                continue
            effective = edit_document.effective_edit(scene)
            key = edit_document.edit_hash(effective)
            if key in found:
                continue
            try:
                updates, _, _ = row_writes(effective)
            except InvalidEditError:
                continue
            found[key] = state_edit(dict(updates), [])
    return found


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


# P2-4 · F2: every part of a row an edit can hold, as changed_columns() names them.
ROW_PARTS = frozenset(edit_store._VISUAL_COLUMNS) | {"asset_type", *_LAYER_PARTS, BEATS}


def unknown_rows(database: Any, project_id: int, script_id: int | None, segments: list[dict[str, Any]]) -> set[int]:
    """The rows of a script that hold something its EditDocument never knew them to hold - read only.

    What a row is expected to hold is what an apply checks (apply_edit_document_rows): the state the latest
    apply left it in; else the legacy layers the document keeps as an orphan of that very row; else nothing
    ever written. A row that holds anything else was written since by another path - a hand edit, most often.
    A reconcile must not make such a row known to the document as it is (edit_store.sync `refresh`): the next
    apply would expect the hand edit and write the plan over it, with no conflict (P2-4 · F2).

    A script without an EditDocument has nothing to compare with: no row is unknown, and the legacy flow is
    left as it was. When what the document knew cannot be read, no row is taken as known: every one is named.
    """
    return set(unknown_parts(database, project_id, script_id, segments))


def unknown_parts(database: Any, project_id: int, script_id: int | None,
                  segments: list[dict[str, Any]]) -> dict[int, dict[str, Any] | None]:
    """unknown_rows() part by part - read only: segment_id → {"known", "columns"}, or None.

    `known` is what the EditDocument knew the row to hold (the state an apply expects, as above), `columns` the
    parts of the row (ROW_PARTS) that hold something else now - a hand edit, most often. None when only the
    whole row can be said to differ: a record from before F1 keeps one hash of the row (no state_edit), and a
    document or record that cannot be read gives no part as known.
    """
    ids = {int(segment["id"]) for segment in segments}
    if script_id is None or not ids:
        return {}
    try:
        loaded = edit_store.load(database, project_id, int(script_id))
        if loaded is None:
            return {}
        applied: dict[int, dict[str, Any]] = {}
        for entry in database.list_edit_applies(project_id):   # newest first, as the apply reads them
            for item in entry["payload"]["rows"]:
                applied.setdefault(int(item["segment_id"]), item)
    except (edit_store.EditStoreError, StoredEditApplyError):
        return {segment_id: None for segment_id in ids}
    legacy = {int(item["segment_id"]): edit_document.normalize_edit(item["edit"])
              for item in loaded["document"].get("orphans") or []
              if item.get("reason") == edit_document.LEGACY and item.get("segment_id") is not None}
    beats = database.list_project_edit_beats(project_id, script_id=int(script_id))
    found: dict[int, dict[str, Any] | None] = {}
    for segment in segments:
        segment_id = int(segment["id"])
        current = state_edit(segment, beats.get(segment_id, []))
        record = applied.get(segment_id)
        if record is not None and not isinstance(record.get("state_edit"), dict):
            # A record from before F1: one hash of the whole row, no part of it known on its own.
            if edit_document.edit_hash(current) != record["state_hash"]:
                found[segment_id] = None
            continue
        # What the document knew (F1: state_edit - a hand edit the apply left alone is not in it), else the orphan.
        known = edit_document.normalize_edit(record["state_edit"] if record is not None else legacy.get(segment_id))
        if edit_document.edit_hash(current) != edit_document.edit_hash(known):
            columns = frozenset(changed_columns(current, known, ROW_PARTS))
            found[segment_id] = {"known": known, "columns": columns} if columns else None
    return found


def held_edits(database: Any, project_id: int, script_id: int,
               held: dict[int, dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """segment_id → what the EditDocument takes a held row to hold after a reconcile (P2-4 · F2) - read only.

    `held`: landed row → {"known", "columns"} (unknown_parts of the row it came from; `columns` the hand-edited
    parts the reconcile carried there). The row as it is now - what the reconcile carried or retimed - except
    those parts: they stay what the document knew before, so an apply that writes one still finds the hand edit
    and reports a conflict, while the parts nobody touched by hand are known and never a conflict (F1).
    """
    if not held:
        return {}
    timeline = {int(segment["id"]): segment for segment in database.list_project_timeline(project_id, script_id=script_id)}
    beats = database.list_project_edit_beats(project_id, script_id=script_id)
    return {segment_id: with_parts(state_edit(timeline[segment_id], beats.get(segment_id, [])), item["known"], item["columns"])
            for segment_id, item in held.items() if segment_id in timeline}


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
    legacy_edits = {int(item["segment_id"]): edit_document.normalize_edit(item["edit"])
                    for item in document.get("orphans") or []
                    if item.get("reason") == edit_document.LEGACY and item.get("segment_id") is not None}
    legacy = {segment_id: edit_document.edit_hash(value) for segment_id, value in legacy_edits.items()}
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
                     "legacy_hash": legacy.get(int(segment_id)), "legacy_edit": legacy_edits.get(int(segment_id)),
                     "default_hash": DEFAULT_HASH, "updates": updates, "beats": beats, "visual_owned": owned})
    return rows, skipped


def apply_scenes(database: Any, project_id: int, script_id: int, storyboard_row: dict[str, Any], *,
                 scene_keys: list[str] | None = None, accept: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Apply the script's current EditDocument to its timeline: {"applied", "unchanged", "skipped", "conflicts", ...}.

    The document must be the current storyboard's (edit_store.current) and
    built against the timeline rows and voices as they are now - otherwise
    nothing is written (EditStoreError: sync it first). `scene_keys` limits
    the apply to those scenes. `accept`: a person's decisions to write the
    plan over a row's conflicting parts (ScopedCheck.accept, Bước 05 · T6b).
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
        known = _known_for(database, project_id, script_id, document, {row["segment_id"] for row in rows})
        done = database.apply_edit_document_rows(project_id, script_id, rows, state_hash=state_hash, record=record,
                                                 rule=ScopedCheck(known, accept))
    except StoredEditApplyError as exc:
        raise edit_store.EditStoreError(str(exc)) from exc
    return {"document_hash": found["document_hash"], "artifact_id": done["artifact_id"], "applied": done["written"],
            "unchanged": done["unchanged"], "skipped": skipped + done["skipped"], "conflicts": done["conflicts"]}


def _known_for(database: Any, project_id: int, script_id: int, document: dict[str, Any],
               segment_ids: set[int]) -> dict[str, dict[str, Any]]:
    """known_writes() when one of these rows has a record from before F1 (read column by column through it), else {}."""
    old = {int(item["segment_id"]) for entry in database.list_edit_applies(project_id) for item in entry["payload"]["rows"]
           if "state_edit" not in item}
    return known_writes(database, project_id, script_id, document) if old & set(segment_ids) else {}


def planned_row(document: dict[str, Any], scene_key: str) -> dict[str, Any] | None:
    """The row an apply of this scene would write (plan()), or None when the scene has no edit to apply."""
    rows, _ = plan(document, scene_keys=[scene_key])
    return rows[0] if rows else None


def parts_hold(row: dict[str, Any], segment: dict[str, Any], beats: list[dict[str, Any]], columns: list[str]) -> bool:
    """Whether the row already holds, in these parts ("*": all it writes), exactly what this planned row writes."""
    parts = _written(row) if "*" in columns else set(columns)
    return not changed_columns(state_edit(segment, beats), _target(row, segment, beats), parts)


def preview_conflicts(database: Any, project_id: int, script_id: int, document: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Bước 05 · T6b: segment_id → the conflict an apply of this document would meet on that row - read only.

    {"columns", "expected_from", "state_hash", "layer_hash"}: the parts of the
    row that hold what the EditDocument never knew (and that the apply would
    write), where its expected state comes from, the row as it is now (what a
    decision about it binds to) and the edit the apply would write. The same
    check the apply runs (ScopedCheck), on the rows as they are read now; a
    planned scene without a row, or without a conflict, is not named.
    """
    rows, _ = plan(document)
    if not rows:
        return {}
    timeline = {int(item["id"]): item for item in database.list_project_timeline(project_id, script_id=script_id)}
    beats = database.list_project_edit_beats(project_id, script_id=script_id)
    latest: dict[int, dict[str, Any]] = {}
    for entry in database.list_edit_applies(project_id):   # newest first, as the apply reads them
        for item in entry["payload"]["rows"]:
            latest.setdefault(int(item["segment_id"]), item)
    rule = ScopedCheck(_known_for(database, project_id, script_id, document, {row["segment_id"] for row in rows}))
    found: dict[int, dict[str, Any]] = {}
    for row in rows:
        segment = timeline.get(int(row["segment_id"]))
        if segment is None:
            continue
        held = beats.get(int(row["segment_id"]), [])
        verdict = rule.verdict(row, segment, held, latest.get(int(row["segment_id"])))
        if verdict["conflict"]:
            found[int(row["segment_id"])] = {"columns": list(verdict["columns"]), "expected_from": verdict["source"],
                                             "state_hash": state_hash(segment, held), "layer_hash": row["layer_hash"]}
    return found


# Bước 05 · T7 render gate: why a planned script's timeline rows, as a render is about to read them, are not what its
# EditDocument says they hold.
NOT_APPLIED = "edit_not_applied"
HAND_EDIT = "conflict"
STALE_LAYERS = "stale_layers"
OUTDATED_DOCUMENT = "edit_document_outdated"


def render_blockers(database: Any, project_id: int, script_id: int, storyboard_row: dict[str, Any] | None,
                    timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """[{"code", "segment_id", "scene_key", ...}] - empty when `timeline` renders exactly what the EditDocument says.

    `timeline` is the rows a render reads (each with its "edit_beats"), so what
    is checked is what is rendered. No EditDocument yet: nothing to hold
    against (plain scenes and legacy layers render as before). An
    EditDocument of another storyboard: refused. Otherwise it is read as the
    next sync would make it (edit_store.preview: retimed to new voices, or
    marked) - read only - and:
      a scene with an edit made for other words, text or timing (STALE) is refused;
      each planned scene's row must hold, in every column its apply writes,
      exactly what that apply would write (_target): else the plan was never
      applied, or was applied before the scene changed (edit_not_applied), or
      the row was edited since by another path (conflict) - never written
      over here.
    A scene that needs a plan (needs_plan) is not held: a scene without an edit renders.
    """
    found = edit_store.current(database, project_id, script_id, storyboard_row)
    if found["state"] == edit_store.MISSING:
        return []
    if found["state"] != edit_store.CURRENT or not storyboard_row:
        return [{"code": OUTDATED_DOCUMENT, "segment_id": None, "scene_key": None}]
    document = edit_store.preview(database, project_id, script_id, storyboard_row)["document"]
    found_rows = {int(item["id"]): item for item in timeline}
    blockers: list[dict[str, Any]] = []
    for scene in document["scenes"]:
        stale = [status for status in edit_document.STATUSES
                 if status in edit_document.STALE and status in (scene.get("statuses") or [])]
        if stale and not edit_document._is_empty(edit_document.normalize_edit(scene.get("edit"))):
            blockers.append({"code": STALE_LAYERS, "segment_id": scene.get("segment_id"), "scene_key": scene["scene_key"],
                             "statuses": stale})
    rows, _ = plan(document)
    latest: dict[int, dict[str, Any]] = {}
    for entry in database.list_edit_applies(project_id):   # newest first
        for item in entry["payload"]["rows"]:
            latest.setdefault(int(item["segment_id"]), item)
    for row in rows:
        segment = found_rows.get(int(row["segment_id"]))
        if segment is None:
            continue   # a scene without its row: the storyboard check of the timeline says so
        beats = list(segment.get("edit_beats") or [])
        columns = changed_columns(state_edit(segment, beats), _target(row, segment, beats), _written(row))
        if not columns:
            continue
        applied = latest.get(int(row["segment_id"]))
        code = HAND_EDIT if applied is not None and applied.get("layer_hash") == row["layer_hash"] else NOT_APPLIED
        blockers.append({"code": code, "segment_id": int(row["segment_id"]), "scene_key": row.get("scene_key"),
                         "columns": columns})
    return blockers


assert set(edit_store._VISUAL_COLUMNS) | {"asset_type", "overlays", "sound_cues", "edit_direction"} == EDIT_OWNED_COLUMNS, \
    "the columns an apply writes are the ones an EditDocument reads back"
