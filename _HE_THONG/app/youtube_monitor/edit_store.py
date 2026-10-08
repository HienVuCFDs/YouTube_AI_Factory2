"""Bước 5.3 · T2 · Keeping a planned project's EditDocument.

    timeline + voices + StoryboardDocument ─→ edit_document.build() ─→ save()
    stored artifact ─→ load(): its storyboard by hash ─→ edit_document.validate() ─→ the document, or a refusal

An EditDocument is stored as a director artifact (kind "edit_document"), one row
per version, never in project_edit_plans - that table and its routes belong to
the legacy Edit Plan, and neither system reads the other.

What this module adds to the engine is only what the engine may not do itself:
read the database and the voice files, and keep the result. Every judgement is
still the engine's: what a scene's edit is worth (build, validate), whether a
voice fits it (keeps_voice, through voice_entry). Nothing here writes to the
timeline (T3), changes the reconcile (T4) or gates anything (T7).

Reading is strict: an artifact that cannot be read, whose hash does not match
its content, whose storyboard cannot be found or is not intact, or which fails
validate() against that storyboard is refused with the reason - never read as
empty, never repaired. A document made for another storyboard than the current
one stays in the history but is never handed back as the current document.

The first EditDocument of a timeline that already has edit layers (made by the
legacy Edit Plan, by hand, or copied by a reconcile) has no basis saying what
those layers were made for: they are kept as `legacy` orphans with their scene
as candidate - never ready, never taken as the scene's edit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import edit_document, storyboard_engine, storyboard_reconcile
from .database import EditDocumentConflict, StoredEditDocumentError
from .production_worker import read_voice_record, voice_fingerprint
from .speech_timing import audio_signature

SCHEMA = 1
CURRENT, OUTDATED, MISSING = "current", "outdated", "missing"

# What of a timeline row is its picture and its look - read back into an edit only to keep it as a legacy orphan.
# A column still at its default holds nothing anyone made, so it is left out.
_VISUAL_COLUMNS = {
    "visual_path": "", "visual_prompt": "", "visual_kind": "", "visual_fps": 0, "visual_kind_reason": "",
    "visual_strategy": "", "visual_provider": "", "source_dependency": "", "risk_level": "", "content_dna": "{}",
    "transform_actions": "[]", "required_assets": "[]", "edit_transition": "", "edit_effect": "", "edit_note": "",
    "edit_trim_head": 0, "edit_trim_tail": 0, "edit_cleanups": "[]", "source_start_seconds": -1, "source_cue_reason": "",
}
_BEAT_SKIP = frozenset({"id", "timeline_segment_id", "created_at", "updated_at", "asset_name", "asset_mime_type",
                        "project_id", "script_id"})


class EditStoreError(RuntimeError):
    """An EditDocument could not be kept or read, said in words a person can act on."""

    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _storyboard(row: dict[str, Any] | None, *, project_id: int, script_id: int) -> dict[str, Any]:
    """The StoryboardDocument of a stored row, intact and of this project's script - or EditStoreError."""
    if not row or int(row["project_id"]) != int(project_id) or int(row["script_id"]) != int(script_id):
        raise EditStoreError("Không tìm thấy storyboard mà EditDocument được lập cho")
    stored = storyboard_engine.decode(row)
    if stored is None or storyboard_engine.document_hash(stored) != row.get("document_hash") \
            or stored.get("document_hash") != row.get("document_hash"):
        raise EditStoreError("Storyboard mà EditDocument được lập cho không còn nguyên vẹn (mã băm khác nội dung)")
    if stored.get("status") != storyboard_engine.VALID:
        raise EditStoreError("Storyboard mà EditDocument được lập cho không hợp lệ")
    return stored


def _verified(database: Any, project_id: int, script_id: int, entry: dict[str, Any]) -> dict[str, Any]:
    """A stored artifact checked end to end: its fields, its hash, its storyboard, and validate() against it."""
    payload = entry["payload"]
    label = f"EditDocument #{entry['id']}"
    if payload.get("schema") != SCHEMA:
        raise EditStoreError(f"{label}: định dạng lưu không đúng (schema {payload.get('schema')!r})")
    document = payload.get("document")
    if not isinstance(document, dict):
        raise EditStoreError(f"{label}: không có nội dung EditDocument")
    if document.get("document_hash") != payload.get("document_hash") \
            or edit_document.document_hash(document) != payload.get("document_hash"):
        raise EditStoreError(f"{label}: document_hash không khớp nội dung")
    provenance = document.get("provenance") if isinstance(document.get("provenance"), dict) else {}
    if provenance.get("script_id") != int(script_id) or payload.get("script_id") != int(script_id):
        raise EditStoreError(f"{label}: không thuộc kịch bản #{script_id}")
    if not provenance.get("storyboard_hash") or provenance.get("storyboard_hash") != payload.get("storyboard_hash"):
        raise EditStoreError(f"{label}: storyboard ghi trong bản lưu khác storyboard ghi trong EditDocument")
    try:
        row = database.get_project_storyboard_by_hash(project_id, provenance["storyboard_hash"])
        board = _storyboard(row, project_id=project_id, script_id=script_id)
    except EditStoreError as exc:
        raise EditStoreError(f"{label}: {exc}") from exc
    problems = edit_document.validate(document, board)
    if problems:
        raise EditStoreError(f"{label} không hợp lệ: {problems[0]}")
    return {"artifact_id": entry["id"], "created_at": entry["created_at"], "document": document,
            "document_hash": payload["document_hash"], "parent_hash": payload.get("parent_hash"),
            "carried_from": payload.get("carried_from"), "storyboard": board, "storyboard_row": row}


def _entries(database: Any, project_id: int, script_id: int | None) -> list[dict[str, Any]]:
    try:
        return database.list_edit_documents(project_id, script_id)
    except StoredEditDocumentError as exc:
        raise EditStoreError(str(exc)) from exc


def history(database: Any, project_id: int, script_id: int) -> list[dict[str, Any]]:
    """Every stored version of a script's EditDocument, newest first, each checked as load() checks it."""
    return [_verified(database, project_id, script_id, entry) for entry in _entries(database, project_id, script_id)]


def load(database: Any, project_id: int, script_id: int) -> dict[str, Any] | None:
    """The latest stored EditDocument of a script, checked - None when there is none, EditStoreError when it is broken.

    Says nothing about whether it is the current storyboard's: that is current().
    """
    entries = _entries(database, project_id, script_id)
    return _verified(database, project_id, script_id, entries[0]) if entries else None


def current(database: Any, project_id: int, script_id: int, storyboard_row: dict[str, Any] | None) -> dict[str, Any]:
    """The script's EditDocument for the current storyboard: state current | outdated | missing.

    `outdated`: the latest one was made for another storyboard. It stays in
    the history but is not handed back (`document` None) - sync() builds the
    current one from it.
    """
    loaded = load(database, project_id, script_id)
    if loaded is None:
        return {"state": MISSING, "document": None}
    if not storyboard_row or loaded["document"]["provenance"]["storyboard_hash"] != storyboard_row.get("document_hash"):
        return {"state": OUTDATED, "document": None, "document_hash": loaded["document_hash"],
                "storyboard_hash": loaded["document"]["provenance"]["storyboard_hash"]}
    return {"state": CURRENT, **loaded}


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def save(database: Any, project_id: int, script_id: int, document: dict[str, Any], *, storyboard_row: dict[str, Any],
         expected_parent: str | None, carried_from: str | None = None) -> dict[str, Any]:
    """Keep a version of a script's EditDocument - only one that validate() accepts against its storyboard.

    `expected_parent`: the document_hash of the latest stored version the
    document was built on (None when there was none); a save that no longer
    follows the latest one is refused, nothing written.
    """
    board = _storyboard(storyboard_row, project_id=project_id, script_id=script_id)
    if (document.get("provenance") or {}).get("storyboard_hash") != board.get("document_hash"):
        raise EditStoreError("EditDocument không thuộc storyboard này")
    if (document.get("provenance") or {}).get("script_id") != int(script_id):
        raise EditStoreError(f"EditDocument không thuộc kịch bản #{script_id}")
    problems = edit_document.validate(document, board)
    if problems:
        raise EditStoreError(f"EditDocument không hợp lệ, không lưu: {problems[0]}")
    try:
        stored = database.save_edit_document(project_id, script_id, document, storyboard_id=int(storyboard_row["id"]),
                                             expected_parent=expected_parent, carried_from=carried_from)
    except EditDocumentConflict as exc:
        raise EditStoreError(str(exc), status_code=409) from exc
    except StoredEditDocumentError as exc:
        raise EditStoreError(str(exc)) from exc
    return {"artifact_id": stored["id"], "created": stored["created"], "document_hash": stored["payload"]["document_hash"],
            "parent_hash": stored["payload"].get("parent_hash")}


# ---------------------------------------------------------------------------
# What the timeline holds now: voices, rows, legacy layers
# ---------------------------------------------------------------------------

def _json(raw: Any, kind: type) -> tuple[Any, bool]:
    """(the column's value, whether it read as `kind`)."""
    if isinstance(raw, kind):
        return raw, True
    try:
        value = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return raw, False
    return (value, True) if isinstance(value, kind) else (raw, False)


def timeline_edit(segment: dict[str, Any], beats: list[dict[str, Any]]) -> dict[str, Any]:
    """What a timeline row already holds of an edit, in the EditDocument's shape - for a legacy orphan only.

    Columns still at their default are left out, so a row nobody edited reads
    as an empty edit. A layer column that does not read as JSON is kept as it
    is under `visual` (unparsed_*), never dropped.
    """
    visual = {}
    for column, default in _VISUAL_COLUMNS.items():
        if column in segment and segment[column] not in (None, default):
            visual[column] = segment[column]
    if visual.get("visual_path"):
        visual["asset_type"] = segment.get("asset_type")
    layers: dict[str, Any] = {}
    for column, name, kind in (("overlays", "overlays", list), ("sound_cues", "sound_cues", list),
                               ("edit_direction", "direction", dict)):
        value, ok = _json(segment.get(column), kind)
        if ok:
            layers[name] = value
        elif str(value or "").strip():
            visual[f"unparsed_{column}"] = value
    return edit_document.normalize_edit({
        "visual": visual, "layers": layers,
        "beats": [{key: value for key, value in beat.items() if key not in _BEAT_SKIP} for beat in beats],
    })


def _signature(audio_path: Any) -> str:
    path = Path(str(audio_path or ""))
    try:
        return audio_signature(path) if str(audio_path or "").strip() and path.is_file() else ""
    except OSError:
        return ""


def snapshot(database: Any, project_id: int, script_id: int, board: dict[str, Any]) -> dict[str, Any]:
    """What the engine is given about the timeline now: {voices, segments, legacy, voice_fingerprint}.

    The shots must be the storyboard's copy and the timeline (when there is
    one) must say its scenes - otherwise which row is which scene is not known
    and nothing is read (EditStoreError).
    """
    shots = database.list_project_shots(project_id, script_id=script_id)
    timeline = database.list_project_timeline(project_id, script_id=script_id)
    if not shots or not storyboard_engine.shots_match(shots, board):
        raise EditStoreError("Danh sách cảnh chưa khớp Storyboard hiện hành: hãy chia cảnh lại trước khi lập EditDocument")
    if timeline and not storyboard_engine.timeline_match(timeline, board):
        raise EditStoreError("Timeline chưa khớp Storyboard hiện hành: hãy đồng bộ timeline trước khi lập EditDocument")
    settings = database.get_project_render_settings(project_id)
    fingerprint = voice_fingerprint(str(settings.get("voice_provider") or ""), settings)
    records = {int(item["id"]): record for item in timeline
               if (record := read_voice_record(item.get("audio_path"))) is not None}
    rows, _ = storyboard_reconcile.source_rows(shots, timeline, board, voice_records=records)
    by_id = {int(item["id"]): item for item in timeline}
    beats = database.list_project_edit_beats(project_id, script_id=script_id) if timeline else {}
    voices: dict[str, dict[str, Any]] = {}
    segments: dict[str, int] = {}
    legacy: dict[str, dict[str, Any]] = {}
    for scene, row in zip(storyboard_engine.scenes(board), rows):
        if row.get("segment_id") is None:
            continue
        segment = by_id[int(row["segment_id"])]
        key = scene["scene_key"]
        segments[key] = int(segment["id"])
        voices[key] = edit_document.voice_entry(
            row, scene, audio_signature=_signature(segment.get("audio_path")),
            duration_seconds=float(segment.get("duration_seconds") or 0), voice_fingerprint=fingerprint)
        held = timeline_edit(segment, beats.get(int(segment["id"]), []))
        if held["visual"] or held["layers"]["overlays"] or held["layers"]["sound_cues"] or held["layers"]["direction"] \
                or held["beats"]:
            legacy[key] = {"segment_id": int(segment["id"]), "edit": held}
    return {"voices": voices, "segments": segments, "legacy": legacy, "voice_fingerprint": fingerprint}


# ---------------------------------------------------------------------------
# Building the current document
# ---------------------------------------------------------------------------

def _carried(database: Any, project_id: int, script_id: int) -> dict[str, Any] | None:
    """The newest EditDocument of another script of the project - what a new script's edit is carried over from."""
    for entry in _entries(database, project_id, None):
        other = int(entry["payload"]["script_id"])
        if other != int(script_id):
            return _verified(database, project_id, other, entry)
    return None


def _held(document: dict[str, Any]) -> list[tuple[Any, ...]]:
    """Per scene, the row it is on, the voice it was judged with and what that made of it - not how it was linked
    this time (a rebuild on the same storyboard links each scene to itself; inheritance() reads no more than that
    the match was verified)."""
    return [(item.get("scene_key"), item.get("segment_id"), item.get("voice"), item.get("statuses"), item.get("timing"))
            for item in document["scenes"]]


def sync(database: Any, project_id: int, script_id: int, storyboard_row: dict[str, Any], *,
         refresh: set[int] | frozenset[int] | None = None) -> dict[str, Any]:
    """The script's EditDocument for this storyboard, built from what came before and kept - nothing applied.

    * the script's latest document (any storyboard) is what it follows, by
      lineage; when the storyboard, the rows and the voices it was judged
      against are all still the same, it is returned as it is - no new version;
    * else, a new script follows the newest document of another script;
    * else (the first one) layers already on the timeline are kept as legacy
      orphans, their scene as candidate - never ready.
    `refresh` (Bước 5.3 · T4): timeline rows a reconcile has just written
    legacy content to (carried to a new row, or retimed) - what they now hold
    is kept as a legacy orphan of that row, so a later apply expects it. Only
    those rows: anything else written to a row the document already knows is
    still a conflict.
    Returns {"state": "current", "created", "document", "document_hash", "artifact_id", "parent_hash", "mode"}.
    """
    board = _storyboard(storyboard_row, project_id=project_id, script_id=script_id)
    now = snapshot(database, project_id, script_id, board)
    own = load(database, project_id, script_id)
    source = own or _carried(database, project_id, script_id)
    options: dict[str, Any] = {"voices": now["voices"], "segments": now["segments"], "storyboard_id": int(storyboard_row["id"]),
                               "voice_fingerprint": now["voice_fingerprint"]}
    if source is not None:
        options.update(previous=source["document"], previous_storyboard=source["storyboard"])
        mode = "follow" if own is not None else "carried_over"
    else:
        options["legacy"] = now["legacy"]
        mode = "bootstrap"
    refreshed = {key: held for key, held in now["legacy"].items() if int(held["segment_id"]) in (refresh or ())}
    if refreshed and source is not None:
        options["refreshed"] = refreshed
    try:
        document = edit_document.build(board, **options)
    except edit_document.EditDocumentError as exc:
        raise EditStoreError(str(exc)) from exc
    if own is not None and not options.get("refreshed") and own["document"]["provenance"] == document["provenance"] \
            and _held(own["document"]) == _held(document):
        # Nothing the engine reads has moved since the latest version: it is still the current one.
        return {"state": CURRENT, "created": False, "mode": "unchanged", **own}
    stored = save(database, project_id, script_id, document, storyboard_row=storyboard_row,
                  expected_parent=own["document_hash"] if own else None,
                  carried_from=source["document_hash"] if source is not None and own is None else None)
    return {"state": CURRENT, "mode": mode, "document": document, "storyboard": board, "storyboard_row": storyboard_row,
            **stored}


def plan_scene(database: Any, project_id: int, script_id: int, storyboard_row: dict[str, Any], scene_key: str,
               value: dict[str, Any] | None = None) -> dict[str, Any]:
    """One scene's edit made for it (edit_document.plan_scene) on the current document, kept as the next version."""
    found = current(database, project_id, script_id, storyboard_row)
    if found["state"] != CURRENT:
        raise EditStoreError("Chưa có EditDocument của storyboard hiện hành: hãy đồng bộ trước khi lập lớp dựng")
    try:
        document = edit_document.plan_scene(found["document"], found["storyboard"], scene_key, value)
    except edit_document.EditDocumentError as exc:
        raise EditStoreError(str(exc), status_code=422) from exc
    stored = save(database, project_id, script_id, document, storyboard_row=storyboard_row,
                  expected_parent=found["document_hash"])
    return {"state": CURRENT, "document": document, **stored}
