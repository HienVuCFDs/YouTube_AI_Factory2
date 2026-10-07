"""Bước 5.3 · T1 · EditDocument: the canonical edit of a planned project's scenes.

    StoryboardDocument ──┐
    the voice now ───────┼─→ build() ─→ EditDocument ─→ (T3: applied to the timeline)
    previous EditDocument┘    lineage()

What each scene is shown with - its picture (`visual`), and what is drawn and
heard over it (`layers`: overlays, graphic direction, sound cues; and its edit
`beats`) - is kept here scene by scene, with its basis: the scene's words,
speaker, place and on-screen text, and the voice it was timed against, as they
were when that edit was made. The production strategy comes in with the
storyboard (its visual_strategy and plan_fingerprint).

What a scene's edit is worth now is judged again on every build, from its
basis against the storyboard and the voice now - never from the timeline, and
never from a reconcile record. A scene whose words changed stays stale through
any later re-cut, until its edit is made again for it (plan_scene).

Three policies, none restated here:

* lineage() says which old scene a new one is - never an equal scene_key;
* inheritance() says what a scene may take from the edit it was given: asked
  with what changed since the edit's basis (scene_changes, the comparison
  lineage makes) and whether the voice the edit was timed against is still
  the scene's;
* keeps_voice() says whether a voice still fits a scene. Its verdict comes in
  with the voice (`fits`, voice_entry()); it is never worked out here.

Pure: no database, files, network, clock or randomness. The same inputs give
the same document, to the byte (document_hash). Nothing here is stored or
applied (Bước 5.3 · T2, T3).
"""

from __future__ import annotations

import copy
import hashlib
from collections import Counter
from typing import Any

from .storyboard_engine import VALID, canonical_json, scenes, to_shots
from .storyboard_reconcile import (
    MATCH_LINES, MATCH_SEGMENT, VERIFIED_MATCHES, inheritance, keeps_voice, lineage, scene_changes, with_segments,
)

KIND = "edit_document"
ENGINE_VERSION = "edit-phase1"

# A scene's state. Every one that applies is kept (`statuses`), in this order; the first is its `status`.
# A scene with none is ready.
NEEDS_PLAN = "needs_plan"            # no edit was ever made for it
STALE_CONTENT = "stale_content"      # its layers were made for other words or another speaker
STALE_OVERLAYS = "stale_overlays"    # its layers were made for other on-screen text
STALE_TIMING = "stale_timing"        # its voice changed and its times cannot follow it
VISUAL_REVIEW = "visual_review"      # its picture is kept, but the scene changed under it
STATUSES = (NEEDS_PLAN, STALE_CONTENT, STALE_OVERLAYS, STALE_TIMING, VISUAL_REVIEW)
STALE = frozenset({STALE_CONTENT, STALE_OVERLAYS, STALE_TIMING})
READY = "ready"
# An edit with no scene to be on: never ready, kept until someone decides.
ORPHAN = "orphan"
REMOVED, UNVERIFIED, LEGACY = "removed", "unverified", "legacy"
ORPHAN_REASONS = (REMOVED, UNVERIFIED, LEGACY)

# A scene's edit timed against its voice now.
TIMING_KEPT, TIMING_RETIMED, TIMING_STALE = "kept", "retimed", "stale"

# What the renderer accepts of a timed edit.
TIME_TOLERANCE = 0.05     # an overlay may end this much past its scene (graphic_overlays)
MIN_BEAT_SECONDS = 0.15   # a beat is never shorter (ffmpeg_renderer)

# What of a storyboard scene an edit is made for, kept in its basis - what scene_changes() reads.
_BASIS_SCENE = ("narration_text", "speaker", "section_id", "plan_section_id", "role", "spoken_lines", "on_screen_text",
                "insight_ids", "evidence_ids")
_CONTENT = frozenset({"narration", "speaker"})


class EditDocumentError(RuntimeError):
    """An EditDocument could not be built or changed, said in words a person can act on."""


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


# ---------------------------------------------------------------------------
# An edit
# ---------------------------------------------------------------------------

def edit(visual: dict[str, Any] | None = None, *, overlays: list | None = None, sound_cues: list | None = None,
         direction: dict[str, Any] | None = None, beats: list | None = None) -> dict[str, Any]:
    """A scene's edit, in the document's shape.

    visual  the picture and its look (visual_path, visual_prompt, asset_type,
            trims, transition, effect, ...), as the timeline row will hold them;
    layers  overlays and sound cues (each with start/end seconds), and the
            graphic direction (which carries its own length and scales itself);
    beats   the edit beats (start and duration seconds).
    """
    return normalize_edit({"visual": visual, "layers": {"overlays": overlays, "sound_cues": sound_cues, "direction": direction},
                           "beats": beats})


def normalize_edit(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    layers = raw.get("layers") if isinstance(raw.get("layers"), dict) else {}
    return {"visual": _copy(dict(raw.get("visual") or {})),
            "layers": {"overlays": _copy(list(layers.get("overlays") or [])),
                       "sound_cues": _copy(list(layers.get("sound_cues") or [])),
                       "direction": _copy(dict(layers.get("direction") or {}))},
            "beats": _copy(list(raw.get("beats") or []))}


def _has_layers(value: dict[str, Any]) -> bool:
    layers = value["layers"]
    return bool(layers["overlays"] or layers["sound_cues"] or layers["direction"] or value["beats"])


def _is_empty(value: dict[str, Any]) -> bool:
    return not value["visual"] and not _has_layers(value)


def edit_hash(value: dict[str, Any]) -> str:
    return _hash(normalize_edit(value))


def _scaled(items: list, ratio: float, keys: tuple[str, ...]) -> list:
    return [{**item, **{key: round(float(item[key]) * ratio, 3) for key in keys
                        if isinstance(item.get(key), (int, float)) and not isinstance(item.get(key), bool)}}
            if isinstance(item, dict) else item for item in items]


def retimed(value: dict[str, Any], ratio: float) -> dict[str, Any]:
    """An edit with every time scaled by `ratio` - overlays, sound cues, beats; the same scale for all."""
    value = normalize_edit(value)
    value["layers"]["overlays"] = _scaled(value["layers"]["overlays"], ratio, ("start_seconds", "end_seconds"))
    value["layers"]["sound_cues"] = _scaled(value["layers"]["sound_cues"], ratio, ("start_seconds", "end_seconds"))
    value["beats"] = _scaled(value["beats"], ratio, ("start_seconds", "duration_seconds"))
    return value


def timing_errors(value: dict[str, Any], seconds: float) -> list[str]:
    """Why an edit's times do not fit a scene of `seconds` - what the renderer would refuse or bend."""
    errors: list[str] = []
    for name, items in (("overlay", value["layers"]["overlays"]), ("sound cue", value["layers"]["sound_cues"])):
        for number, item in enumerate(items, start=1):
            try:
                start, end = float(item.get("start_seconds", 0)), float(item.get("end_seconds", 0))
            except (AttributeError, TypeError, ValueError):
                errors.append(f"{name} {number}: thời điểm không phải số")
                continue
            if start < 0 or end <= start or end > seconds + TIME_TOLERANCE:
                errors.append(f"{name} {number}: {start:g}–{end:g} nằm ngoài cảnh {seconds:g}s")
    for number, beat in enumerate(value["beats"], start=1):
        try:
            start, length = float(beat.get("start_seconds", 0)), float(beat.get("duration_seconds", 0))
        except (AttributeError, TypeError, ValueError):
            errors.append(f"beat {number}: thời điểm không phải số")
            continue
        if start < 0 or length < MIN_BEAT_SECONDS or start + length > seconds + TIME_TOLERANCE:
            errors.append(f"beat {number}: {start:g}+{length:g}s không vừa cảnh {seconds:g}s (tối thiểu {MIN_BEAT_SECONDS:g}s)")
    return errors


# ---------------------------------------------------------------------------
# The voice a scene's edit is timed against
# ---------------------------------------------------------------------------

def voice_entry(row: dict[str, Any], scene: dict[str, Any], *, audio_signature: str, duration_seconds: float,
                voice_fingerprint: str | None = None) -> dict[str, Any]:
    """A scene's voice now, from the timeline row that holds it (a storyboard_reconcile.source_rows() row).

    `fits` is keeps_voice()'s verdict - the voice says this scene's words, by
    its speaker, with the project's voice settings - never worked out again.
    `audio_signature` names the audio itself (its file and how it was made);
    `duration_seconds` is the row's length, measured or estimated.
    """
    has_audio = bool(row.get("has_audio"))
    return {"audio_signature": str(audio_signature or "") if has_audio else "",
            "voice_fingerprint": str(voice_fingerprint or ""), "duration_seconds": float(duration_seconds),
            "fits": keeps_voice(row, scene, voice_fingerprint) if has_audio else True}


def _voice_now(entry: dict[str, Any] | None, seconds: float) -> dict[str, Any]:
    """A voice entry in full. With no entry the scene has no voice yet, at its estimated length. Audio whose
    fit was not given is never assumed to fit."""
    entry = entry or {}
    audio = str(entry.get("audio_signature") or "")
    return {"audio_signature": audio, "voice_fingerprint": str(entry.get("voice_fingerprint") or ""),
            "duration_seconds": float(entry.get("duration_seconds") or seconds),
            "fits": bool(entry.get("fits", not audio))}


def _voice_kept(basis: dict[str, Any], now: dict[str, Any]) -> bool:
    """Whether the voice an edit was timed against is still the scene's: the same audio - or still none, at the
    same length - and keeps_voice() says it fits. The words alone never say so."""
    return bool(now["fits"]) and now["audio_signature"] == basis["audio_signature"] \
        and abs(float(now["duration_seconds"]) - float(basis["duration_seconds"])) < 1e-6


# ---------------------------------------------------------------------------
# Judging a scene's edit
# ---------------------------------------------------------------------------

def _snapshot(scene: dict[str, Any]) -> dict[str, Any]:
    return {key: _copy(scene.get(key)) for key in _BASIS_SCENE}


def _basis(scene: dict[str, Any], voice: dict[str, Any], storyboard_hash: str, value: dict[str, Any]) -> dict[str, Any]:
    """What an edit is made for: this scene, as it is in this storyboard, timed against this voice."""
    return {"scene_key": scene.get("scene_key"), "storyboard_hash": storyboard_hash, "scene": _snapshot(scene),
            "voice": {key: voice[key] for key in ("audio_signature", "voice_fingerprint", "duration_seconds")},
            "edit_hash": edit_hash(value)}


def _link(lineage_ref: dict[str, Any]) -> str:
    """How a scene's edit is tied to it, for inheritance(): the verified match it was carried by - or, made for
    this very scene, its own lines. An edit reaches a scene by no other way (an unverified match takes nothing)."""
    match = lineage_ref.get("match")
    return match if match in VERIFIED_MATCHES else MATCH_LINES


def _timing(value: dict[str, Any], before: float, now: float, holds: bool) -> dict[str, Any]:
    if holds:
        return {"state": TIMING_KEPT, "basis_seconds": before, "current_seconds": now, "ratio": 1.0, "errors": []}
    if before <= 0 or now <= 0:
        return {"state": TIMING_STALE, "basis_seconds": before, "current_seconds": now, "ratio": None,
                "errors": ["không biết độ dài cảnh để căn lại thời gian"]}
    ratio = now / before
    errors = timing_errors(retimed(value, ratio), now)
    return {"state": TIMING_STALE if errors else TIMING_RETIMED, "basis_seconds": before, "current_seconds": now,
            "ratio": ratio, "errors": errors}


def judge(scene: dict[str, Any], basis: dict[str, Any] | None, value: dict[str, Any], voice: dict[str, Any],
          link: str = MATCH_LINES) -> dict[str, Any]:
    """What a scene's edit is worth now - its basis against the scene and the voice now, through inheritance().

    Several things can be true at once (new words: the picture kept for a
    review, the layers stale, the times following the new voice) - all are
    kept in `statuses`, none folded into one flag.
    """
    if basis is None:
        return {"changes": [], "inherit": None, "timing": None, "statuses": [NEEDS_PLAN]}
    found = scene_changes(basis["scene"], scene)
    verdict = inheritance(link, found, _voice_kept(basis["voice"], voice))
    statuses = []
    if _has_layers(value) and not verdict["layers"]:
        statuses.append(STALE_CONTENT if _CONTENT & set(verdict["review"]) else STALE_OVERLAYS)
    timing = _timing(value, float(basis["voice"]["duration_seconds"]), float(voice["duration_seconds"]), bool(verdict["timing"]))
    if timing["state"] == TIMING_STALE:
        statuses.append(STALE_TIMING)
    if verdict["review"] and value["visual"]:
        statuses.append(VISUAL_REVIEW)
    return {"changes": found, "inherit": verdict, "timing": timing, "statuses": [item for item in STATUSES if item in statuses]}


def _scene(scene: dict[str, Any], value: dict[str, Any], basis: dict[str, Any] | None, voice: dict[str, Any],
           lineage_ref: dict[str, Any], segment_id: int | None, unverified: bool) -> dict[str, Any]:
    judged = judge(scene, basis, value, voice, _link(lineage_ref))
    review = list((judged["inherit"] or {}).get("review") or [])
    if unverified:
        review.append("unverified")
    statuses = judged["statuses"]
    return {"scene_key": scene["scene_key"], "index": int(scene["index"]), "segment_id": segment_id,
            "lineage": lineage_ref, "basis": basis, "edit": value, "voice": voice, "changes": judged["changes"],
            "inherit": judged["inherit"], "timing": judged["timing"], "statuses": statuses,
            "status": statuses[0] if statuses else READY, "ready": not statuses, "review": review}


def effective_edit(scene: dict[str, Any]) -> dict[str, Any]:
    """The scene's edit as it plays now: retimed to its voice when that changed (and could follow)."""
    timing = scene.get("timing") or {}
    if timing.get("state") == TIMING_RETIMED and timing.get("ratio"):
        return retimed(scene["edit"], float(timing["ratio"]))
    return normalize_edit(scene["edit"])


def _orphan(scene: dict[str, Any], reason: str, *, storyboard_hash: str | None, candidate: str | None = None) -> dict[str, Any]:
    return {"scene_key": scene.get("scene_key"), "storyboard_hash": storyboard_hash, "segment_id": scene.get("segment_id"),
            "reason": reason, "candidate": candidate, "edit": normalize_edit(scene.get("edit")),
            "basis": _copy(scene.get("basis")), "status": ORPHAN, "ready": False}


# ---------------------------------------------------------------------------
# Building the document
# ---------------------------------------------------------------------------

def _lengths(storyboard: dict[str, Any]) -> dict[str, float]:
    """Each scene's estimated length, as the timeline row is given it before any voice."""
    return {scene["scene_key"]: float(shot["duration_seconds"]) for scene, shot in zip(scenes(storyboard), to_shots(storyboard))}


def _provenance(storyboard: dict[str, Any], voices: list[tuple[str, dict[str, Any]]], *, storyboard_id: int | None,
                voice_fingerprint: str) -> dict[str, Any]:
    return {"storyboard_id": storyboard_id, "storyboard_hash": storyboard.get("document_hash"),
            "storyboard_engine": storyboard.get("engine_version"),
            "script_id": storyboard.get("script_id"), "script_version": storyboard.get("script_version"),
            "script_fingerprint": storyboard.get("script_fingerprint"),
            "plan_id": storyboard.get("plan_id"), "plan_version": storyboard.get("plan_version"),
            "plan_fingerprint": storyboard.get("plan_fingerprint"),
            "voice_fingerprint": str(voice_fingerprint or ""),
            "audio_signature": _hash([[key, voice["audio_signature"], voice["duration_seconds"]] for key, voice in voices])}


def _finish(document: dict[str, Any]) -> dict[str, Any]:
    counts = Counter(scene["status"] for scene in document["scenes"])
    document["counts"] = {READY: counts[READY], **{status: counts[status] for status in STATUSES}, ORPHAN: len(document["orphans"])}
    document["document_hash"] = document_hash(document)
    return document


def document_hash(document: dict[str, Any]) -> str:
    return _hash({key: value for key, value in document.items() if key != "document_hash"})


def build(storyboard: dict[str, Any], *, voices: dict[str, dict[str, Any]] | None = None,
          previous: dict[str, Any] | None = None, previous_storyboard: dict[str, Any] | None = None,
          segments: dict[str, int] | None = None, links: dict[str, int] | None = None,
          legacy: dict[str, dict[str, Any]] | None = None, storyboard_id: int | None = None,
          voice_fingerprint: str = "") -> dict[str, Any]:
    """The EditDocument of a storyboard: each scene's edit carried over from the previous document by lineage, and judged.

    voices     scene_key → the scene's voice now (voice_entry()); a scene
               without one has no voice yet, at its estimated length;
    previous   the document this follows, with `previous_storyboard`, the
               storyboard it was built for (lineage runs from it);
    segments   scene_key → the timeline row the scene is now (where T3 applies it);
    links      scene_key → the old row its row took over (the reconcile
               record): only where lineage found nothing, through
               with_segments() - unverified, so the old edit is held, not taken;
    legacy     scene_key → {"segment_id", "edit"}: what the timeline already
               has, from before any EditDocument. No basis says what it was
               made for, so it is held for review, never adopted unseen.
    """
    if not isinstance(storyboard, dict) or storyboard.get("status") != VALID or not storyboard.get("document_hash"):
        raise EditDocumentError("Storyboard chưa hợp lệ: chưa thể lập EditDocument")
    if previous is not None:
        problems = validate(previous)
        if problems:
            raise EditDocumentError(f"EditDocument trước không hợp lệ: {problems[0]}")
        if not isinstance(previous_storyboard, dict) \
                or previous_storyboard.get("document_hash") != previous["provenance"]["storyboard_hash"]:
            raise EditDocumentError("Thiếu storyboard mà EditDocument trước được lập cho: không thể nối cảnh cũ sang cảnh mới")
        if legacy:
            raise EditDocumentError("Đã có EditDocument: lớp dựng trên timeline không còn là nguồn để đọc lại")
    current = scenes(storyboard)
    lengths = _lengths(storyboard)
    now = [(scene["scene_key"], _voice_now((voices or {}).get(scene["scene_key"]), lengths[scene["scene_key"]]))
           for scene in current]
    result = lineage(previous_storyboard if previous is not None else None, storyboard)
    before = {item["scene_key"]: item for item in (previous or {}).get("scenes") or []}
    if previous is not None and links:
        owners = {int(item["segment_id"]): item["scene_key"] for item in before.values()
                  if item.get("segment_id") is not None and item.get("basis")}
        result = with_segments(result, links, owners)
    from_hash = (previous or {}).get("provenance", {}).get("storyboard_hash")
    orphans = [_copy(item) for item in (previous or {}).get("orphans") or []]
    claimed: set[str] = set()
    out = []
    for scene, item, (_, voice) in zip(current, result["scenes"], now):
        key = scene["scene_key"]
        old = before.get(item["previous_scene_key"]) if item["previous_scene_key"] else None
        lineage_ref = {"previous_scene_key": item["previous_scene_key"], "previous_index": item["previous_index"],
                       "previous_segment_id": (old or {}).get("segment_id") if old else (links or {}).get(key),
                       "match": item["match"]}
        value, basis, unverified = normalize_edit(None), None, False
        if old is not None:
            claimed.add(old["scene_key"])
            if old.get("basis") and item["match"] in VERIFIED_MATCHES:
                value, basis = normalize_edit(old["edit"]), _copy(old["basis"])
            elif old.get("basis"):
                # Found only through its row: the old edit is held for review, never taken on its own.
                orphans.append(_orphan(old, UNVERIFIED, storyboard_hash=from_hash, candidate=key))
                unverified = True
        held = (legacy or {}).get(key)
        if held and not _is_empty(normalize_edit(held.get("edit"))):
            orphans.append(_orphan({"scene_key": None, "segment_id": held.get("segment_id"), "edit": held.get("edit")},
                                   LEGACY, storyboard_hash=None, candidate=key))
            lineage_ref = {**lineage_ref, "previous_segment_id": held.get("segment_id"), "match": MATCH_SEGMENT}
            unverified = True
        out.append(_scene(scene, value, basis, voice, lineage_ref, (segments or {}).get(key), unverified))
    for item in before.values():
        if item["scene_key"] not in claimed and item.get("basis"):
            orphans.append(_orphan(item, REMOVED, storyboard_hash=from_hash))
    document = {"kind": KIND, "engine_version": ENGINE_VERSION,
                "provenance": _provenance(storyboard, now, storyboard_id=storyboard_id, voice_fingerprint=voice_fingerprint),
                "based_on": (previous or {}).get("document_hash"), "scenes": out, "orphans": orphans}
    return _finish(document)


def plan_scene(document: dict[str, Any], storyboard: dict[str, Any], scene_key: str,
               value: dict[str, Any] | None = None) -> dict[str, Any]:
    """The document with one scene's edit made for it as it is now: its basis becomes this scene and this voice.

    `value` is the new edit; None keeps the scene's edit as it plays now
    (effective_edit) - someone looked at it and it still fits. An edit whose
    times cannot follow the voice is not kept that way: it is made again.
    """
    if storyboard.get("document_hash") != document["provenance"]["storyboard_hash"]:
        raise EditDocumentError("EditDocument không thuộc storyboard này")
    position = next((n for n, item in enumerate(document["scenes"]) if item["scene_key"] == scene_key), None)
    if position is None:
        raise EditDocumentError(f"Không có cảnh {scene_key} trong EditDocument")
    current = next(scene for scene in scenes(storyboard) if scene["scene_key"] == scene_key)
    item = document["scenes"][position]
    if value is None:
        if (item.get("timing") or {}).get("state") == TIMING_STALE:
            raise EditDocumentError("Thời gian lớp dựng không theo được giọng mới: cần lập lại lớp dựng cho cảnh này")
        value = effective_edit(item)
    value = normalize_edit(value)
    problems = timing_errors(value, float(item["voice"]["duration_seconds"]))
    if problems:
        raise EditDocumentError(f"Lớp dựng không vừa cảnh: {problems[0]}")
    basis = _basis(current, item["voice"], document["provenance"]["storyboard_hash"], value)
    updated = _copy(document)
    updated["scenes"][position] = _scene(current, value, basis, item["voice"], item["lineage"], item.get("segment_id"), False)
    return _finish(updated)


# ---------------------------------------------------------------------------
# Checking a document
# ---------------------------------------------------------------------------

_PROVENANCE = ("storyboard_hash", "storyboard_engine", "script_id", "script_version", "script_fingerprint",
               "plan_id", "plan_version", "plan_fingerprint", "audio_signature")


def validate(document: dict[str, Any], storyboard: dict[str, Any] | None = None) -> list[str]:
    """Why a document cannot be trusted - empty when it can. Given its storyboard, each scene is judged again too."""
    if not isinstance(document, dict):
        return ["EditDocument không phải object"]
    errors: list[str] = []
    if (document.get("kind"), document.get("engine_version")) != (KIND, ENGINE_VERSION):
        errors.append(f"Không phải EditDocument {ENGINE_VERSION}")
    provenance = document.get("provenance") if isinstance(document.get("provenance"), dict) else {}
    errors += [f"Thiếu nguồn gốc: {key}" for key in _PROVENANCE if provenance.get(key) in (None, "")]
    items = document.get("scenes") if isinstance(document.get("scenes"), list) else []
    if not items:
        errors.append("EditDocument không có cảnh nào")
    keys = [item.get("scene_key") for item in items]
    if any(not isinstance(key, str) or not key for key in keys):
        errors.append("Có cảnh thiếu scene_key")
    errors += [f"scene_key {key} xuất hiện {count} lần" for key, count in Counter(keys).items() if count > 1]
    previous_keys = [(item.get("lineage") or {}).get("previous_scene_key") for item in items]
    errors += [f"Cảnh cũ {key} được giao cho {count} cảnh mới" for key, count in Counter(k for k in previous_keys if k).items() if count > 1]
    for number, item in enumerate(items, start=1):
        errors += [f"Cảnh {number} ({item.get('scene_key')}): {problem}" for problem in _scene_errors(item, number)]
    for number, item in enumerate(document.get("orphans") or [], start=1):
        if item.get("status") != ORPHAN or item.get("ready") is not False:
            errors.append(f"Lớp dựng mồ côi {number} không được coi là sẵn sàng")
        if item.get("reason") not in ORPHAN_REASONS:
            errors.append(f"Lớp dựng mồ côi {number}: lý do không hợp lệ")
    if document.get("document_hash") != document_hash(document):
        errors.append("document_hash không khớp nội dung")
    if storyboard is not None:
        errors += _against(document, storyboard)
    return errors


def _scene_errors(item: dict[str, Any], number: int) -> list[str]:
    errors: list[str] = []
    if item.get("index") != number:
        errors.append("thứ tự cảnh không liền mạch")
    ref = item.get("lineage") if isinstance(item.get("lineage"), dict) else {}
    match = ref.get("match")
    if match not in (*VERIFIED_MATCHES, MATCH_SEGMENT, None):
        errors.append(f"cách nối cảnh không hợp lệ: {match}")
    if match in VERIFIED_MATCHES and not ref.get("previous_scene_key"):
        errors.append("nối với cảnh cũ mà không nói cảnh nào")
    if ref.get("previous_scene_key") and match is None:
        errors.append("nhắc cảnh cũ mà không nói nối bằng cách nào")
    if match == MATCH_SEGMENT and ref.get("previous_segment_id") is None:
        errors.append("nối qua hàng timeline mà không nói hàng nào")
    voice = item.get("voice")
    if not isinstance(voice, dict) or not {"audio_signature", "duration_seconds", "fits"} <= set(voice):
        errors.append("thiếu giọng hiện tại của cảnh")
    statuses = item.get("statuses") if isinstance(item.get("statuses"), list) else None
    if statuses is None or any(status not in STATUSES for status in statuses):
        return [*errors, "trạng thái không hợp lệ"]
    if statuses != [status for status in STATUSES if status in statuses]:
        errors.append("trạng thái không theo thứ tự chuẩn")
    if item.get("ready") is not (not statuses) or item.get("status") != (statuses[0] if statuses else READY):
        errors.append("trạng thái tổng không khớp các trạng thái chi tiết")
    value = normalize_edit(item.get("edit"))
    basis = item.get("basis")
    if basis is None:
        if NEEDS_PLAN not in statuses:
            errors.append("chưa có lớp dựng nào được lập mà không ở needs_plan")
        if not _is_empty(value):
            errors.append("có lớp dựng nhưng không có basis")
        return errors
    if NEEDS_PLAN in statuses:
        errors.append("đã có basis mà vẫn needs_plan")
    if not isinstance(basis, dict) or not isinstance(basis.get("scene"), dict) or not isinstance(basis.get("voice"), dict):
        return [*errors, "basis thiếu cảnh hoặc giọng"]
    if basis.get("edit_hash") != edit_hash(value):
        errors.append("lớp dựng đã bị sửa ngoài basis của nó")
    timing = item.get("timing") if isinstance(item.get("timing"), dict) else {}
    state = timing.get("state")
    if state not in (TIMING_KEPT, TIMING_RETIMED, TIMING_STALE):
        errors.append("thời gian không hợp lệ")
    elif (state == TIMING_STALE) != (STALE_TIMING in statuses):
        errors.append("stale_timing không khớp trạng thái thời gian")
    elif state == TIMING_RETIMED and not (isinstance(timing.get("ratio"), (int, float)) and timing["ratio"] > 0):
        errors.append("căn lại thời gian mà không có tỉ lệ")
    elif state == TIMING_RETIMED and timing_errors(effective_edit(item), float(timing.get("current_seconds") or 0)):
        errors.append("thời gian sau khi căn lại vẫn không vừa cảnh")
    verdict = item.get("inherit") if isinstance(item.get("inherit"), dict) else {}
    if _has_layers(value) and verdict.get("layers") is False and not (STALE & set(statuses) - {STALE_TIMING}):
        errors.append("lớp dựng không còn khớp mà không bị đánh dấu stale")
    return errors


def _against(document: dict[str, Any], storyboard: dict[str, Any]) -> list[str]:
    """The document checked against its storyboard: the same scenes, each judged as it says."""
    if document.get("provenance", {}).get("storyboard_hash") != storyboard.get("document_hash"):
        return ["EditDocument không thuộc storyboard này"]
    current = scenes(storyboard)
    if [item.get("scene_key") for item in document.get("scenes") or []] != [scene["scene_key"] for scene in current]:
        return ["Các cảnh của EditDocument không phải các cảnh của storyboard"]
    errors = []
    for scene, item in zip(current, document["scenes"]):
        if not isinstance(item.get("voice"), dict):
            continue  # said by _scene_errors
        judged = judge(scene, item.get("basis"), normalize_edit(item.get("edit")), item["voice"], _link(item.get("lineage") or {}))
        if (judged["statuses"], judged["timing"], judged["changes"]) != (item.get("statuses"), item.get("timing"), item.get("changes")):
            errors.append(f"Cảnh {item.get('index')} ({item.get('scene_key')}): trạng thái không khớp basis so với hiện tại")
    return errors
