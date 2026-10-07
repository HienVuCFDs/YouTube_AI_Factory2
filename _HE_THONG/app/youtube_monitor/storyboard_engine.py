"""Bước 5 · Storyboard: the scenes of the video, cut from the script.

    ProjectPlan → ScriptDocument → StoryboardDocument → project_shots (compatibility)

The ScriptDocument already says every word of the video and which plan
section each word belongs to. This step only decides where one scene ends and
the next begins. It writes no word, changes none, drops none and decides no
picture:

* a scene is a run of consecutive spoken lines of ONE part of ONE section -
  the hook, a section's body, or the CTA - read by ONE speaker. A line is never
  split, and two sections never share a scene;
* inside such a run the lines are grouped into scenes near the plan's scene
  length (edit_direction.average_shot_length_seconds), measured at the script's
  own speaking rate. No model is asked: the same script and plan always give
  the same scenes;
* the on-screen text, insight ids and evidence ids are the script's, handed
  down to the scenes of the section they belong to - none is written here;
* the document names the script (id, version and a fingerprint of its content)
  and the plan (id, version) it was cut from, so it is stale the moment either
  moves - an in-place edit of the script included, which keeps id and version.

The StoryboardDocument is the storyboard. `project_shots` is written from it
(`to_shots`) for the parts of the app that still read shots - the timeline, the
voice, the render - as a copy, never as a second source. Pictures (prompts,
cameras, transitions, B-roll) belong to the phases after this one.

Compatibility boundary: a project in the plan workflow whose script is a
ScriptDocument is cut here. A project outside it - pasted words alone, the old
writer's scene list, the Short - keeps shot_planner.build_shot_plan. Reup's cut
by dialogue (/timeline/from-dialogue) stays a mode of its own: it reads the
source's transcript, writes no StoryboardDocument, and its shots are not one.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import re
from collections import Counter
from typing import Any

from . import script_engine

# phase2: every scene carries its section and a content key (scene_key).
# phase3: the document carries the fingerprint of the plan inputs it was cut with.
# phase4: a re-cut keeps the previous cut's intact scenes (anchored cut).
ENGINE_VERSION = "storyboard-phase4"
# Previous cuts whose scenes can anchor a new one: same scene structure (lines, role, speaker).
_ANCHORABLE_ENGINES = frozenset({"storyboard-phase3", "storyboard-phase4"})
# A piece of a re-cut shorter than this share of a scene releases the kept neighbour it fits best
# (0.35, chosen at the T0.5 review: no scene under 5 words in the benchmark, three times fewer re-cuts than 0.5).
MIN_FRAGMENT_FACTOR = 0.35

VALID, INVALID = "valid", "invalid"
CURRENT, STALE, MISSING = "current", "stale", "missing"
# The storyboard is the current script's, but what downstream reads from it
# (project_shots, the timeline) says something else.
OUT_OF_SYNC = "out_of_sync"
# Which flow a project's scenes follow. Only "plan" is held by the Storyboard
# Gate: Reup's cut by dialogue is a mode of its own (the scenes are the
# source's turns), and a project outside the plan workflow keeps the legacy one.
PLAN_MODE, REUP_MODE, LEGACY_MODE = "plan", "reup", "legacy"
# What the gate answers for a project it does not stand in front of.
NOT_APPLICABLE = "not_applicable"

# How long one scene runs when the plan does not say. The plan's own figure is
# kept inside a sane range so a typo there cannot cut a scene per word or one
# scene per section.
DEFAULT_SCENE_SECONDS = 6.0
MIN_SCENE_SECONDS, MAX_SCENE_SECONDS = 2.0, 30.0
# A scene of several lines may not run past this many times the scene length:
# lines are only grouped while that keeps them near it.
OVERLONG_FACTOR = 2.0

ROLES = ("hook", "body", "cta")
# What `project_shots.section` has always meant (hook / main / cta).
SHOT_SECTION = {"hook": "hook", "body": "main", "cta": "cta"}

# Bookkeeping of the script that says nothing about what is said or shown:
# when it was checked, by whom, its revision log. Leaving it out of the
# fingerprint keeps a re-check of unchanged words from staling the storyboard.
_SCRIPT_VOLATILE = frozenset({"validation", "checks", "revisions", "captured_at", "ai", "analysis_ref"})
# Derived from the document, so not part of what its hash covers. `anchoring` says how the cut was
# made (which previous cut it kept scenes of): the same scenes cut twice are the same document.
_STORYBOARD_DERIVED = frozenset({"document_hash", "status", "validation", "anchoring"})

NARRATION_LOCKED = ("Ở luồng Kế hoạch, lời của từng cảnh lấy nguyên văn từ kịch bản. "
                    "Muốn đổi lời, hãy sửa kịch bản ở Bước 3 rồi chia cảnh lại.")
STRUCTURE_LOCKED = ("Ở luồng Kế hoạch, cảnh được chia từ kịch bản nên không thêm, nhân bản, xoá hay đổi thứ tự cảnh bằng tay. "
                    "Muốn đổi, hãy sửa kịch bản ở Bước 3 rồi chia cảnh lại.")
SEGMENTS_LOCKED = ("Ở luồng Kế hoạch, lời của timeline phải đúng lời các cảnh của Storyboard hiện hành. "
                   "Hãy chia cảnh từ kịch bản hiện tại rồi dựng timeline từ đó.")
TRANSLATE_LOCKED = ("Ở luồng Kế hoạch, lời đọc lấy nguyên văn từ kịch bản nên không dịch từng cảnh ở đây. "
                    "Muốn video bằng ngôn ngữ khác, hãy đặt ngôn ngữ ở Kế hoạch (Bước 2) rồi viết lại kịch bản (Bước 3).")
VOICE_MISMATCH = "File giọng này đọc lời khác với lời của cảnh trong Storyboard hiện hành."

# What every door past the storyboard answers when it may not go on - voice,
# render, timeline - one wording per state, whichever door was used.
GATE_MESSAGES = {
    MISSING: "Chưa chia cảnh từ kịch bản hiện tại. Hãy chia cảnh (Storyboard) trước khi tiếp tục.",
    STALE: "Storyboard đã cũ so với kịch bản hoặc kế hoạch hiện tại. Hãy chia cảnh lại trước khi tiếp tục.",
    INVALID: "Storyboard không hợp lệ. Hãy chia cảnh lại từ kịch bản hiện tại.",
    OUT_OF_SYNC: "Cảnh hoặc timeline không còn khớp Storyboard. Hãy chia cảnh lại để đồng bộ trước khi tiếp tục.",
}


class StoryboardError(RuntimeError):
    """The step could not finish, said in words a person can act on."""

    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------

def canonical_json(value: Any) -> str:
    """One spelling for one value: sorted keys, no spaces, UTF-8 kept."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def script_fingerprint(document: dict[str, Any]) -> str:
    """What the script says and shows, hashed. Changes with any edit of its content, whatever the id and version say."""
    return _sha256({key: value for key, value in (document or {}).items() if key not in _SCRIPT_VOLATILE})


def plan_fingerprint(plan: dict[str, Any]) -> str:
    """What of the plan a storyboard is cut with - its scene length and its media strategy - hashed.

    The plan id and version say which plan; this says the plan's inputs to the
    cut are the same ones, so a storyboard (or an agent's grouping) is never
    kept over a scene length or a visual strategy it was not cut for.
    """
    return _sha256({"scene_seconds": scene_seconds(plan or {})[0], "visual_strategy": _visual_strategy(plan or {})})


def document_hash(storyboard: dict[str, Any]) -> str:
    """The storyboard's own content, hashed (its status and check results are derived from it, so left out)."""
    return _sha256({key: value for key, value in (storyboard or {}).items() if key not in _STORYBOARD_DERIVED})


# ---------------------------------------------------------------------------
# Reading the script
# ---------------------------------------------------------------------------

def _texts(values: Any) -> list[str]:
    return [str(item) for item in values or [] if isinstance(item, str) and item.strip()]


def _words(text: str) -> int:
    # The same count script_engine.spoken_seconds makes, so the two agree on a scene's length.
    return len(re.findall(r"\w+", str(text or ""), flags=re.UNICODE))


def _norm(text: Any) -> str:
    return " ".join(str(text or "").split())


def speaking_rate(document: dict[str, Any]) -> dict[str, Any]:
    """The rate the script was measured at: its own, or its language's."""
    stored = document.get("speaking_rate") or {}
    try:
        rate = float(stored.get("tokens_per_second") or 0)
    except (TypeError, ValueError):
        rate = 0.0
    if rate > 0 and math.isfinite(rate):
        return {"tokens_per_second": rate, "unit": str(stored.get("unit") or "từ")}
    return script_engine.speaking_rate(str(document.get("language") or "vi"))


def scene_seconds(plan: dict[str, Any]) -> tuple[float, str]:
    """(how long a scene should run, where that figure came from: "plan" or "default")."""
    value = (plan.get("edit_direction") or {}).get("average_shot_length_seconds") if isinstance(plan, dict) else None
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if number > 0 and math.isfinite(number):
        return round(min(MAX_SCENE_SECONDS, max(MIN_SCENE_SECONDS, number)), 2), "plan"
    return DEFAULT_SCENE_SECONDS, "default"


def structure(document: dict[str, Any]) -> list[dict[str, Any]]:
    """The script's sections in order, each with its parts (hook | body | cta) and their lines.

    The hook belongs to the first section and the CTA to the last, as the
    Script Engine counts them. Every line carries a reference (`sec-2#3`,
    `hook#0`, `cta#1`) that stays the same however the lines are grouped.
    """
    sections = [item for item in document.get("sections") or [] if isinstance(item, dict)]
    found: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        key = str(section.get("id") or f"sec-{index + 1}")
        blocks = []
        if index == 0:
            blocks.append(("hook", "hook", document.get("hook") or {}))
        blocks.append(("body", key, section))
        if index == len(sections) - 1:
            blocks.append(("cta", "cta", document.get("cta") or {}))
        parts = []
        for role, prefix, block in blocks:
            block = block if isinstance(block, dict) else {}
            lines = []
            for position, line in enumerate(block.get("spoken_lines") or []):
                if not isinstance(line, dict) or not str(line.get("text") or "").strip():
                    continue
                entry = {"ref": f"{prefix}#{position}", "section_key": key, "role": role,
                         "speaker": str(line.get("speaker") or ""), "text": str(line.get("text") or "")}
                if line.get("price_captured_at"):
                    entry["price_captured_at"] = line["price_captured_at"]
                lines.append(entry)
            parts.append({"role": role, "lines": lines, "on_screen_text": _texts(block.get("on_screen_text"))})
        found.append({"key": key, "index": index, "section": section, "parts": parts})
    return found


def document_lines(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Every spoken line of the script, in the order it is said."""
    return [line for item in structure(document) for part in item["parts"] for line in part["lines"]]


# ---------------------------------------------------------------------------
# Cutting the scenes
# ---------------------------------------------------------------------------

def _partition(weights: list[int], target: float) -> list[tuple[int, int]]:
    """Contiguous groups of lines whose lengths stay as close to `target` as whole lines allow.

    Minimises the sum of (group length - target)² over every way of cutting
    between lines, so neither a crumb of a scene nor one swollen past the
    target survives when a better cut exists. Ties go to the earliest cut.
    """
    count = len(weights)
    prefix = [0]
    for weight in weights:
        prefix.append(prefix[-1] + weight)
    best = [0.0] + [math.inf] * count
    cut = [0] * (count + 1)
    for end in range(1, count + 1):
        for start in range(end):
            cost = best[start] + (prefix[end] - prefix[start] - target) ** 2
            if cost < best[end]:
                best[end], cut[end] = cost, start
    groups: list[tuple[int, int]] = []
    end = count
    while end > 0:
        groups.append((cut[end], end))
        end = cut[end]
    return groups[::-1]


def _runs(lines: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Consecutive lines read by the same speaker."""
    runs: list[list[dict[str, Any]]] = []
    for line in lines:
        if runs and runs[-1][-1]["speaker"] == line["speaker"]:
            runs[-1].append(line)
        else:
            runs.append([line])
    return runs


def _cost(weights: list[int], target: float) -> float:
    return sum((sum(weights[start:end]) - target) ** 2 for start, end in _partition(weights, target)) if weights else 0.0


def _line_identity(role: Any, speaker: Any, text: Any) -> tuple[str, str, str]:
    return str(role or ""), str(speaker or ""), _norm(text)


def anchors(document: dict[str, Any], previous: dict[str, Any] | None, *, plan: dict[str, Any], tokens: float,
            target: float) -> tuple[list[tuple[int, int]], dict[str, Any]]:
    """The scenes of the previous cut that are still intact in this script: ([start, end) in the script's line order, why).

    A previous scene is kept only when every one of its lines is still here,
    word for word and in order, said by the same speaker in the same part, one
    run of consecutive lines of one section - so a scene that only moved, or
    whose neighbours changed, is not cut again. Nothing is kept when the cut
    itself would differ: no previous storyboard, another scene length or
    media strategy (plan fingerprint), another speaking rate.
    """
    info: dict[str, Any] = {"anchored": False, "reason": "", "previous_document_hash": None,
                            "kept_scenes": 0, "released_scenes": 0, "recut_lines": 0}
    if not previous:
        return [], {**info, "reason": "no_previous"}
    if str(previous.get("engine_version") or "") not in _ANCHORABLE_ENGINES:
        return [], {**info, "reason": "previous_engine"}
    if previous.get("plan_fingerprint") != plan_fingerprint(plan):
        return [], {**info, "reason": "plan_changed"}
    if abs(float((previous.get("timing") or {}).get("tokens_per_second") or 0) - tokens) > 1e-9 \
            or abs(float((previous.get("timing") or {}).get("scene_seconds") or 0) - target) > 1e-9:
        return [], {**info, "reason": "timing_changed"}
    new_lines = document_lines(document)
    old_scenes = scenes(previous)
    old_lines = [_line_identity(scene.get("role"), line.get("speaker"), line.get("text"))
                 for scene in old_scenes for line in scene.get("spoken_lines") or []]
    new_keys = [_line_identity(line["role"], line["speaker"], line["text"]) for line in new_lines]
    mapped: dict[int, int] = {}
    for op, i1, i2, j1, _ in difflib.SequenceMatcher(a=old_lines, b=new_keys, autojunk=False).get_opcodes():
        if op == "equal":
            mapped.update({i1 + k: j1 + k for k in range(i2 - i1)})
    kept: list[tuple[int, int]] = []
    at = 0
    for scene in old_scenes:
        count = len(scene.get("spoken_lines") or [])
        targets = [mapped.get(position) for position in range(at, at + count)]
        at += count
        if not count or None in targets or targets != list(range(targets[0], targets[0] + count)):
            continue
        places = {(new_lines[t]["section_key"], new_lines[t]["role"], new_lines[t]["speaker"]) for t in targets}
        if len(places) == 1:
            kept.append((targets[0], targets[0] + count))
    return kept, {**info, "anchored": True, "reason": "previous_storyboard",
                  "previous_document_hash": previous.get("document_hash"), "kept_scenes": len(kept)}


def _engine_groups(document: dict[str, Any], target_words: float, kept: list[tuple[int, int]] | None = None,
                   info: dict[str, Any] | None = None) -> list[list[str]]:
    """The engine's cut: every run partitioned near the scene length, the previous cut's intact scenes kept as they were.

    Only the lines between kept scenes are cut again. A piece left there that
    is shorter than half a scene would become a crumb of a scene, so the kept
    neighbour it fits best (lowest cost) is released and cut together with it.
    """
    kept = kept or []
    starts = {start: end for start, end in kept}
    position = {line["ref"]: n for n, line in enumerate(document_lines(document))}
    groups: list[list[str]] = []
    released = recut = 0
    for item in structure(document):
        for part in item["parts"]:
            for run in _runs(part["lines"]):
                weights = [_words(line["text"]) for line in run]
                first = position[run[0]["ref"]]
                # The run as pieces: kept scenes (locked) and the lines between them (free).
                pieces: list[dict[str, Any]] = []
                k = 0
                while k < len(run):
                    end = starts.get(first + k)
                    if end is not None and end - first <= len(run):
                        pieces.append({"locked": True, "start": k, "end": end - first})
                        k = end - first
                    else:
                        if pieces and not pieces[-1]["locked"]:
                            pieces[-1]["end"] = k + 1
                        else:
                            pieces.append({"locked": False, "start": k, "end": k + 1})
                        k += 1
                # A free piece too short to stand as a scene is cut together with the kept neighbour it fits best.
                changed = True
                while changed:
                    changed = False
                    for n, piece in enumerate(pieces):
                        size = sum(weights[piece["start"]:piece["end"]])
                        if piece["locked"] or size >= MIN_FRAGMENT_FACTOR * target_words:
                            continue
                        options = []
                        for m in (n - 1, n + 1):
                            if 0 <= m < len(pieces) and pieces[m]["locked"]:
                                lo, hi = min(piece["start"], pieces[m]["start"]), max(piece["end"], pieces[m]["end"])
                                options.append((_cost(weights[lo:hi], target_words), m, lo, hi))
                        if not options:
                            continue
                        _, m, lo, hi = min(options, key=lambda option: (option[0], option[1]))
                        merged = {"locked": False, "start": lo, "end": hi}
                        pieces[min(n, m)] = merged
                        del pieces[max(n, m)]
                        released += 1
                        # Free neighbours now touching the merged piece join it.
                        joined: list[dict[str, Any]] = []
                        for current in pieces:
                            if joined and not joined[-1]["locked"] and not current["locked"]:
                                joined[-1]["end"] = current["end"]
                            else:
                                joined.append(current)
                        pieces = joined
                        changed = True
                        break
                for piece in pieces:
                    lines = run[piece["start"]:piece["end"]]
                    if piece["locked"]:
                        groups.append([line["ref"] for line in lines])
                        continue
                    recut += len(lines)
                    for start, end in _partition(weights[piece["start"]:piece["end"]], target_words):
                        groups.append([line["ref"] for line in lines[start:end]])
    if info is not None:
        info["released_scenes"] = released
        info["kept_scenes"] = max(0, int(info.get("kept_scenes") or 0) - released)
        info["recut_lines"] = recut
    return groups


def grouping_from_shots(document: dict[str, Any], shots: list[dict[str, Any]]) -> list[list[str]]:
    """The script's lines grouped the way a supplied scene list groups them - or StoryboardError.

    Each scene's narration must be exactly a run of the script's next lines,
    joined (whitespace aside): no word added, dropped, changed or moved. The
    grouping is then checked like any other (`validate`).
    """
    lines = document_lines(document)
    ordered = sorted(enumerate(shots), key=lambda pair: (_shot_order(pair[1], pair[0]), pair[0]))
    groups: list[list[str]] = []
    position = 0
    for number, (_, shot) in enumerate(ordered, start=1):
        wanted = _norm(shot.get("narration") if isinstance(shot, dict) else "")
        if not wanted:
            raise StoryboardError(f"Cảnh {number} gửi lên không có lời; mọi cảnh phải đọc lời của kịch bản.")
        taken: list[dict[str, Any]] = []
        joined = ""
        while position < len(lines):
            taken.append(lines[position])
            position += 1
            joined = _norm(" ".join(line["text"] for line in taken))
            if joined == wanted or not wanted.startswith(joined + " "):
                break
        if joined != wanted:
            raise StoryboardError(f"Lời của cảnh {number} gửi lên không phải lời kịch bản theo đúng thứ tự "
                                  "(thêm, bớt, đổi hoặc đảo chữ). Cảnh chỉ được gom nguyên văn các dòng liền nhau của kịch bản.")
        groups.append([line["ref"] for line in taken])
    if position < len(lines):
        raise StoryboardError(f"Các cảnh gửi lên thiếu {len(lines) - position} dòng lời cuối của kịch bản.")
    return groups


def _shot_order(shot: Any, fallback: int) -> int:
    try:
        return int((shot or {}).get("shot_index"))
    except (TypeError, ValueError, AttributeError):
        return fallback + 1


def scene_key_base(section: Any, role: str, speaker: str, narration: str) -> str:
    """A scene's identity from what it is - section, part, speaker, words - never from its position.

    The same words in the same place get the same key in every cut of every
    version of the script; a repeat within one cut is told apart by `-2`, `-3`.
    """
    return "sk-" + _sha256([str(section or ""), str(role or ""), str(speaker or ""), _norm(narration)])[:16]


def _visual_strategy(plan: dict[str, Any]) -> dict[str, Any]:
    """The plan's own media strategy, as it stands - the only picture this document carries."""
    media = plan.get("media_strategy") if isinstance(plan.get("media_strategy"), dict) else {}
    return {
        "primary_sources": list(media.get("primary_sources") or []),
        "supporting_sources": list(media.get("supporting_sources") or []),
        "notes": str(media.get("notes") or ""),
        "scene_asset_type": str((plan.get("constraints") or {}).get("scene_asset_type") or ""),
    }


def build(
    script: dict[str, Any], plan_row: dict[str, Any] | None, *, known_ids: dict[str, set[str]] | None = None,
    groups: list[list[str]] | None = None, previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The StoryboardDocument of one script under one plan, checked. `groups` replaces the engine's own cut.

    `previous` is the storyboard this one follows (the script's last cut, or
    the previous script's): its intact scenes are kept, and only what changed
    is cut again (`anchors`). Never raises for a storyboard that fails its
    checks: it comes back with status "invalid" and the reasons in
    `validation`, and nothing is built on it.
    """
    document = script.get("document") if isinstance(script.get("document"), dict) else script_engine.decode(script)
    if not isinstance(document, dict):
        raise StoryboardError("Kịch bản này không có ScriptDocument nên không chia cảnh bằng Storyboard Engine được.")
    plan_row = plan_row or {}
    plan = plan_row.get("plan") or {}
    rate = speaking_rate(document)
    target, target_from = scene_seconds(plan)
    tokens = rate["tokens_per_second"]
    if groups is None:
        kept, anchoring = anchors(document, previous, plan=plan, tokens=tokens, target=target)
        groups = _engine_groups(document, target * tokens, kept, anchoring)
        grouping = "engine"
    else:
        grouping = "supplied"
        anchoring = {"anchored": False, "reason": "supplied", "previous_document_hash": None,
                     "kept_scenes": 0, "released_scenes": 0, "recut_lines": 0}

    sections = structure(document)
    by_ref = {line["ref"]: line for item in sections for part in item["parts"] for line in part["lines"]}
    strategy = _visual_strategy(plan)
    out_sections = [{
        "section_id": item["key"], "plan_section_id": item["section"].get("plan_section_id"),
        "name": str(item["section"].get("name") or ""), "purpose": str(item["section"].get("purpose") or ""),
        "budget_seconds": item["section"].get("budget_seconds"), "estimated_seconds": 0.0, "scenes": [],
    } for item in sections]
    section_at = {item["key"]: position for position, item in enumerate(sections)}
    seen: Counter = Counter()

    for number, refs in enumerate(groups, start=1):
        lines = [by_ref[ref] for ref in refs if ref in by_ref]
        if not lines:
            raise StoryboardError(f"Cảnh {number} không có dòng lời nào của kịch bản.")
        first = lines[0]
        section = sections[section_at[first["section_key"]]]["section"]
        body = first["role"] == "body"
        seconds = sum(script_engine.spoken_seconds(line["text"], tokens) for line in lines)
        narration = " ".join(line["text"] for line in lines)
        base = scene_key_base(section.get("plan_section_id") or first["section_key"], first["role"], first["speaker"], narration)
        seen[base] += 1
        scene = {
            "scene_id": f"sc-{number:03d}",
            "scene_key": base if seen[base] == 1 else f"{base}-{seen[base]}",
            "index": number,
            "section_id": first["section_key"],
            "plan_section_id": section.get("plan_section_id"),
            "role": first["role"],
            "speaker": first["speaker"],
            "spoken_lines": [{key: value for key, value in line.items() if key not in {"section_key", "role"}} for line in lines],
            "narration_text": narration,
            "on_screen_text": [],
            # The script cites insights and evidence per section, never for the hook or the CTA.
            "insight_ids": [str(item) for item in section.get("insight_ids") or []] if body else [],
            "evidence_ids": [str(item) for item in section.get("evidence_ids") or []] if body else [],
            "estimated_seconds": round(seconds, 2),
            "visual_intent": {
                "role": first["role"],
                "section_name": str(section.get("name") or ""),
                "section_purpose": str(section.get("purpose") or ""),
                "asset_type": strategy["scene_asset_type"],
            },
        }
        out_sections[section_at[first["section_key"]]]["scenes"].append(scene)

    _hand_down_screen_text(sections, out_sections)
    for item in out_sections:
        item["estimated_seconds"] = round(sum(scene["estimated_seconds"] for scene in item["scenes"]), 2)
    scene_total = sum(len(item["scenes"]) for item in out_sections)

    storyboard: dict[str, Any] = {
        "engine_version": ENGINE_VERSION,
        "script_id": int(script["id"]) if script.get("id") is not None else None,
        "script_version": int(script["version"]) if script.get("version") is not None else None,
        "script_fingerprint": script_fingerprint(document),
        "script_engine_version": str(script.get("engine_version") or document.get("engine_version") or ""),
        "plan_id": plan_row.get("id"),
        "plan_version": plan_row.get("version"),
        "plan_fingerprint": plan_fingerprint(plan),
        "language": str(document.get("language") or ""),
        "grouping": grouping,
        "timing": {
            "tokens_per_second": tokens, "unit": rate["unit"],
            "scene_seconds": target, "scene_seconds_from": target_from,
            "target_duration_seconds": document.get("target_duration_seconds"),
            "estimated_seconds": round(sum(item["estimated_seconds"] for item in out_sections), 2),
        },
        "visual_strategy": {key: value for key, value in strategy.items() if key != "scene_asset_type"},
        "scene_count": scene_total,
        "sections": out_sections,
    }
    errors = validate(storyboard, document, known_ids=known_ids, plan=plan)
    storyboard["document_hash"] = document_hash(storyboard)
    storyboard["status"] = INVALID if errors else VALID
    storyboard["validation"] = {"ok": not errors, "errors": errors}
    storyboard["anchoring"] = anchoring
    return storyboard


def _hand_down_screen_text(sections: list[dict[str, Any]], out_sections: list[dict[str, Any]]) -> None:
    """Each part's on-screen text, in order, onto the scenes cut from that part.

    Text j of k goes to scene ⌊j·m/k⌋ of the part's m scenes - spread evenly,
    order kept, nothing written. A part with text but no scene of its own (a
    hook with no line) hands it to the nearest scene of the same section.
    """
    for item, out in zip(sections, out_sections):
        scenes = out["scenes"]
        for part in item["parts"]:
            texts = part["on_screen_text"]
            if not texts:
                continue
            refs = {line["ref"] for line in part["lines"]}
            own = [scene for scene in scenes if scene["spoken_lines"] and scene["spoken_lines"][0]["ref"] in refs]
            if own:
                for position, text in enumerate(texts):
                    own[position * len(own) // len(texts)]["on_screen_text"].append(text)
            elif scenes:
                (scenes[0] if part["role"] == "hook" else scenes[-1])["on_screen_text"].extend(texts)
            # A section without any scene keeps its text nowhere: validate says so.


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

def validate(
    storyboard: dict[str, Any], document: dict[str, Any], *, known_ids: dict[str, set[str]] | None = None,
    plan: dict[str, Any] | None = None,
) -> list[str]:
    """Everything wrong with a storyboard against the script it claims to be cut from. Empty when it holds."""
    errors: list[str] = []
    sections = structure(document)
    expected = [line for item in sections for part in item["parts"] for line in part["lines"]]
    by_ref = {line["ref"]: line for line in expected}
    out_sections = [item for item in storyboard.get("sections") or [] if isinstance(item, dict)]
    scenes = [scene for item in out_sections for scene in item.get("scenes") or [] if isinstance(scene, dict)]
    said = [line for scene in scenes for line in scene.get("spoken_lines") or [] if isinstance(line, dict)]

    # Provenance.
    for key in ("script_id", "script_version", "script_fingerprint", "plan_id", "plan_version", "plan_fingerprint",
                "engine_version"):
        if storyboard.get(key) in (None, ""):
            errors.append(f"Storyboard thiếu nguồn gốc: {key}")
    if plan is not None and storyboard.get("plan_fingerprint") and storyboard["plan_fingerprint"] != plan_fingerprint(plan):
        errors.append("Storyboard không khớp thiết lập của kế hoạch (độ dài cảnh, chiến lược hình)")
    if storyboard.get("script_fingerprint") and storyboard["script_fingerprint"] != script_fingerprint(document):
        errors.append("Storyboard không khớp nội dung kịch bản hiện có (dấu vân tay kịch bản khác)")

    # Every line of the script exactly once, in order, word for word, same speaker.
    expected_refs = [line["ref"] for line in expected]
    place = {ref: position for position, ref in enumerate(expected_refs)}
    said_refs = [str(line.get("ref") or "") for line in said]
    counts = Counter(said_refs)
    missing = [ref for ref in expected_refs if ref not in counts]
    extra = [ref for ref in said_refs if ref not in by_ref]
    repeated = sorted({ref for ref, count in counts.items() if count > 1 and ref in by_ref})
    if missing:
        errors.append(f"Thiếu {len(missing)} dòng lời của kịch bản: {', '.join(missing[:6])}")
    if extra:
        errors.append(f"Có {len(extra)} dòng lời không thuộc kịch bản: {', '.join(extra[:6])}")
    if repeated:
        errors.append(f"Dòng lời xuất hiện nhiều lần: {', '.join(repeated[:6])}")
    if not missing and not extra and not repeated and said_refs != expected_refs:
        errors.append("Thứ tự lời khác thứ tự trong kịch bản")
    for line in said:
        source = by_ref.get(str(line.get("ref") or ""))
        if not source:
            continue
        if str(line.get("text") or "") != source["text"]:
            errors.append(f"Lời của dòng {source['ref']} khác kịch bản")
        if str(line.get("speaker") or "") != source["speaker"]:
            errors.append(f"Người nói của dòng {source['ref']} khác kịch bản")

    # The scenes.
    tokens = float(((storyboard.get("timing") or {}).get("tokens_per_second")) or speaking_rate(document)["tokens_per_second"])
    target = float(((storyboard.get("timing") or {}).get("scene_seconds")) or DEFAULT_SCENE_SECONDS)
    if plan is not None and scene_seconds(plan)[0] != target:
        errors.append(f"Độ dài cảnh {target:g} giây khác độ dài cảnh của kế hoạch ({scene_seconds(plan)[0]:g} giây)")
    section_ids = {str(item.get("section_id") or ""): item for item in out_sections}
    doc_sections = {item["key"]: item["section"] for item in sections}
    known_insights = (known_ids or {}).get("insight_ids")
    known_evidence = (known_ids or {}).get("evidence_ids")
    keys: set[str] = set()
    for item in out_sections:
        for scene in item.get("scenes") or []:
            label = f"Cảnh {scene.get('index')}"
            lines = [by_ref[ref] for ref in (str(line.get("ref") or "") for line in scene.get("spoken_lines") or []) if ref in by_ref]
            if not scene.get("spoken_lines"):
                errors.append(f"{label} không có lời")
                continue
            if not lines:
                continue
            homes = list(dict.fromkeys(line["section_key"] for line in lines))
            if len(homes) > 1:
                errors.append(f"{label} gộp lời của nhiều phần ({', '.join(homes)})")
            elif homes[0] != str(item.get("section_id") or ""):
                errors.append(f"{label} nằm ở phần {item.get('section_id')} nhưng lời thuộc phần {homes[0]}")
            roles = list(dict.fromkeys(line["role"] for line in lines))
            if len(roles) > 1:
                errors.append(f"{label} gộp {' và '.join(roles)} vào một cảnh")
            elif scene.get("role") != roles[0]:
                errors.append(f"{label} ghi vai trò {scene.get('role')} nhưng lời là {roles[0]}")
            speakers = list(dict.fromkeys(line["speaker"] for line in lines))
            if len(speakers) > 1:
                errors.append(f"{label} có nhiều người nói ({', '.join(speakers)})")
            elif str(scene.get("speaker") or "") != speakers[0]:
                errors.append(f"{label} ghi người nói {scene.get('speaker')!r} khác kịch bản ({speakers[0]!r})")
            positions = [place[line["ref"]] for line in lines]
            if positions != list(range(positions[0], positions[0] + len(positions))):
                errors.append(f"{label} gom các dòng không liền nhau")
            if str(scene.get("narration_text") or "") != " ".join(line["text"] for line in lines):
                errors.append(f"{label}: lời đọc khác đúng các dòng kịch bản của cảnh")
            source_section = doc_sections.get(homes[0]) or {}
            base = scene_key_base(source_section.get("plan_section_id") or homes[0], roles[0], speakers[0],
                                  " ".join(line["text"] for line in lines))
            key = str(scene.get("scene_key") or "")
            if key != base and not re.fullmatch(re.escape(base) + r"-\d+", key):
                errors.append(f"{label}: scene_key không khớp nội dung của cảnh")
            elif key in keys:
                errors.append(f"{label}: scene_key trùng với một cảnh khác")
            keys.add(key)
            if str(scene.get("section_id") or "") != homes[0]:
                errors.append(f"{label} ghi phần {scene.get('section_id')} nhưng lời thuộc phần {homes[0]}")
            seconds = sum(script_engine.spoken_seconds(line["text"], tokens) for line in lines)
            if abs(float(scene.get("estimated_seconds") or 0) - seconds) > 0.05:
                errors.append(f"{label}: thời lượng {scene.get('estimated_seconds')} giây không khớp số chữ ({seconds:.2f} giây)")
            if len(lines) > 1 and seconds > OVERLONG_FACTOR * target:
                errors.append(f"{label} gom nhiều dòng tới {seconds:.1f} giây, quá {OVERLONG_FACTOR:g} lần độ dài cảnh {target:g} giây")
            source = doc_sections.get(homes[0]) or {}
            body = roles[0] == "body"
            allowed_insights = {str(value) for value in source.get("insight_ids") or []} if body else set()
            allowed_evidence = {str(value) for value in source.get("evidence_ids") or []} if body else set()
            invented = [str(value) for value in scene.get("insight_ids") or [] if str(value) not in allowed_insights]
            invented += [str(value) for value in scene.get("evidence_ids") or [] if str(value) not in allowed_evidence]
            if invented:
                errors.append(f"{label} dẫn mã không có ở phần này của kịch bản: {', '.join(invented[:6])}")
            unknown = [str(value) for value in scene.get("insight_ids") or []
                       if known_insights is not None and str(value) not in known_insights]
            unknown += [str(value) for value in scene.get("evidence_ids") or []
                        if known_evidence is not None and str(value) not in known_evidence]
            if unknown:
                errors.append(f"{label} dẫn mã insight/bằng chứng không tồn tại: {', '.join(unknown[:6])}")

    # Every section of the script, in order, with at least one scene, its on-screen text and its time.
    if not sections:
        errors.append("Kịch bản không có phần nào nên không có cảnh nào")
    expected_keys = [item["key"] for item in sections]
    got_keys = [str(item.get("section_id") or "") for item in out_sections]
    if got_keys != expected_keys:
        errors.append(f"Các phần của storyboard ({', '.join(got_keys)}) khác các phần của kịch bản ({', '.join(expected_keys)})")
    for item in sections:
        label = f"[{item['section'].get('plan_section_id') or item['key']}]"
        own = section_ids.get(item["key"]) or {}
        scenes_here = [scene for scene in own.get("scenes") or [] if isinstance(scene, dict)]
        if not any(part["lines"] for part in item["parts"]):
            errors.append(f"{label} không có lời nói nên không có cảnh nào")
        elif not scenes_here:
            errors.append(f"{label} không có cảnh nào")
        wanted_text = [text for part in item["parts"] for text in part["on_screen_text"]]
        shown = [str(text) for scene in scenes_here for text in scene.get("on_screen_text") or []]
        if shown != wanted_text:
            added = [text for text in shown if text not in wanted_text]
            dropped = [text for text in wanted_text if text not in shown]
            detail = "; ".join(part for part in (
                f"thêm {added[:3]}" if added else "", f"thiếu {dropped[:3]}" if dropped else "",
                "sai thứ tự" if not added and not dropped else "") if part)
            errors.append(f"{label} chữ trên màn hình khác kịch bản ({detail})")
        budget = item["section"].get("budget_seconds")
        counted = sum(script_engine.spoken_seconds(line["text"], tokens) for part in item["parts"] for line in part["lines"])
        try:
            budget = float(budget)
        except (TypeError, ValueError):
            budget = 0.0
        if budget > 0 and counted > max(budget * script_engine.SECTION_OVERRUN, budget + script_engine.SECTION_SLACK_SECONDS):
            errors.append(f"{label} dài khoảng {round(counted)} giây trong khi kế hoạch dành {budget:g} giây")
    return list(dict.fromkeys(errors))


def known_ids(database: Any, plan_row: dict[str, Any] | None) -> dict[str, set[str]] | None:
    """The insight and evidence ids that exist for this plan - the same sets the Script Engine checks against."""
    if not plan_row:
        return None
    insight_row = database.get_insight_report(int(plan_row["insight_report_id"])) if plan_row.get("insight_report_id") else None
    insight = (insight_row or {}).get("report") or {}
    sections = script_engine.plan_sections(plan_row.get("plan") or {})
    return {
        "insight_ids": {str(item.get("id")) for item in insight.get("insights") or [] if item.get("id")},
        "evidence_ids": {str(key) for key in insight.get("evidence_index") or {}}
        | {str(eid) for item in sections for eid in item["evidence_ids"]},
    }


def refusal(storyboard: dict[str, Any]) -> str:
    errors = (storyboard.get("validation") or {}).get("errors") or []
    return "Chưa chia cảnh được từ kịch bản này: " + "; ".join(errors[:6])


# ---------------------------------------------------------------------------
# Stored storyboards: decoding, and whether one is still current
# ---------------------------------------------------------------------------

def decode(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    try:
        document = json.loads(row.get("document_json") or "null")
    except ValueError:
        return None
    return document if isinstance(document, dict) else None


def state(row: dict[str, Any] | None, script: dict[str, Any] | None, plan_row: dict[str, Any] | None) -> dict[str, Any]:
    """Whether the stored storyboard is the one of the project's current script and plan.

    `script` is what script_engine.current_script returns, `plan_row` the
    project's current plan. Current only when script id, version and
    fingerprint and plan id and version all match, the script is the plan's
    completed one, and the stored document is intact and passed its checks.
    """
    if not row:
        return {"state": MISSING, "current": False, "reasons": ["Chưa chia cảnh từ kịch bản hiện tại"]}
    stored = decode(row)
    reasons: list[str] = []
    if stored is None or document_hash(stored) != row.get("document_hash") or stored.get("document_hash") != row.get("document_hash"):
        return {"state": INVALID, "current": False, "storyboard_id": row.get("id"),
                "reasons": ["Storyboard đã lưu không còn nguyên vẹn (mã băm khác nội dung)"]}
    if not script:
        reasons.append("Dự án không còn kịch bản")
    else:
        if int(row["script_id"]) != int(script["id"]):
            reasons.append(f"Storyboard được chia từ kịch bản #{row['script_id']}, kịch bản hiện tại là #{script['id']}")
        elif int(row["script_version"]) != int(script.get("version") or 0):
            reasons.append("Phiên bản kịch bản đã đổi sau khi chia cảnh")
        elif row["script_fingerprint"] != script_fingerprint(script.get("document") or script_engine.decode(script) or {}):
            reasons.append("Kịch bản đã được sửa sau khi chia cảnh")
        if script.get("state") not in (None, script_engine.COMPLETED):
            reasons.append("Kịch bản hiện tại chưa phải bản hoàn chỉnh của kế hoạch")
    if not plan_row:
        reasons.append("Dự án không còn kế hoạch")
    elif (row.get("plan_id"), row.get("plan_version")) != (plan_row.get("id"), plan_row.get("version")):
        reasons.append(f"Kế hoạch đã đổi (storyboard theo bản {row.get('plan_version')}, hiện tại là bản {plan_row.get('version')})")
    elif stored.get("plan_fingerprint") != plan_fingerprint(plan_row.get("plan") or {}):
        reasons.append("Thiết lập của kế hoạch mà storyboard dựa vào (độ dài cảnh, chiến lược hình) đã đổi")
    if str(row.get("engine_version") or "") != ENGINE_VERSION:
        reasons.append(f"Storyboard được chia bằng phiên bản Storyboard Engine cũ ({row.get('engine_version')})")
    base = {"storyboard_id": row.get("id"), "document_hash": row.get("document_hash"), "script_id": row.get("script_id"),
            "script_version": row.get("script_version"), "plan_id": row.get("plan_id"), "plan_version": row.get("plan_version"),
            "engine_version": row.get("engine_version")}
    if reasons:
        return {**base, "state": STALE, "current": False, "reasons": list(dict.fromkeys(reasons))}
    if row.get("status") != VALID:
        return {**base, "state": INVALID, "current": False, "reasons": list((stored.get("validation") or {}).get("errors") or [])}
    # Same script content and an intact document: its structure is checked
    # again against that script, so a storyboard is current only while it holds.
    errors = validate(stored, (script or {}).get("document") or script_engine.decode(script) or {})
    if errors:
        return {**base, "state": INVALID, "current": False, "reasons": errors}
    return {**base, "state": CURRENT, "current": True, "reasons": []}


_NOT_APPLICABLE_REASONS = {
    REUP_MODE: "Dự án đang ở chế độ Reup (cắt theo lời thoại): Storyboard Gate không áp dụng.",
    LEGACY_MODE: "Dự án ngoài luồng Kế hoạch: Storyboard Gate không áp dụng.",
}


def gate(
    row: dict[str, Any] | None, script: dict[str, Any] | None, plan_row: dict[str, Any] | None, *,
    shots: list[dict[str, Any]], timeline: list[dict[str, Any]], mode: str = PLAN_MODE,
) -> dict[str, Any]:
    """The Storyboard Gate: where a planned project's storyboard stands, and whether what downstream reads agrees with it.

    For the plan workflow (`mode` "plan"), `state` is:
      missing | stale | invalid  - the storyboard itself
      out_of_sync                - the storyboard is the current script's, but
                                   project_shots or the timeline say something else
      current                    - storyboard current, shots and (when there is
                                   one) the timeline saying exactly its scenes
    For Reup's cut by dialogue ("reup") and a project outside the plan
    workflow ("legacy") the gate does not apply: `state` is "not_applicable",
    never a refusal, and `storyboard_state` keeps what the storyboard itself is.
    Having shots, a timeline or audio is never what makes it current.
    """
    status = state(row, script, plan_row)
    stored = decode(row)
    shots_in_sync = bool(stored) and bool(shots) and shots_match(shots, stored)
    timeline_in_sync = bool(stored) and bool(timeline) and timeline_match(timeline, stored)
    result = {**status, "shots_in_sync": shots_in_sync, "timeline_in_sync": timeline_in_sync,
              "has_shots": bool(shots), "has_timeline": bool(timeline), "mode": mode, "applies": mode == PLAN_MODE}
    if status["state"] == CURRENT and not shots_in_sync:
        result = {**result, "state": OUT_OF_SYNC, "current": False,
                  "reasons": ["Danh sách cảnh (project_shots) không còn khớp lời các cảnh của Storyboard"]}
    elif status["state"] == CURRENT and timeline and not timeline_in_sync:
        result = {**result, "state": OUT_OF_SYNC, "current": False,
                  "reasons": ["Timeline không còn khớp lời các cảnh của Storyboard"]}
    result["storyboard_state"] = result["state"]
    if mode != PLAN_MODE:
        result.update(state=NOT_APPLICABLE, current=False, reasons=[_NOT_APPLICABLE_REASONS.get(mode, "")])
    return result


def refusal_for(status: dict[str, Any], *, need: str = "timeline") -> str:
    """Why a door may not go on, in the gate's one wording - "" when it may (and always where the gate does not apply).

    need="timeline": voice, render - the timeline must say the storyboard.
    need="shots": building the timeline - the shots must; the timeline is what is being made.
    """
    if status.get("mode", PLAN_MODE) != PLAN_MODE or status.get("state") == NOT_APPLICABLE:
        return ""
    state_ = status.get("state")
    if state_ == CURRENT or (state_ == OUT_OF_SYNC and need == "shots" and status.get("shots_in_sync")):
        return ""
    message = GATE_MESSAGES.get(state_, GATE_MESSAGES[INVALID])
    reasons = status.get("reasons") or []
    return f"{message} Lý do: {reasons[0]}" if reasons else message


def summary(storyboard: dict[str, Any]) -> dict[str, Any]:
    return {key: storyboard.get(key) for key in (
        "engine_version", "document_hash", "status", "script_id", "script_version", "script_fingerprint", "plan_id",
        "plan_version", "grouping", "scene_count")} | {"estimated_seconds": (storyboard.get("timing") or {}).get("estimated_seconds"),
                                                       "scene_seconds": (storyboard.get("timing") or {}).get("scene_seconds")}


# ---------------------------------------------------------------------------
# Compatibility: project_shots written from the storyboard
# ---------------------------------------------------------------------------

def scenes(storyboard: dict[str, Any]) -> list[dict[str, Any]]:
    return [scene for item in storyboard.get("sections") or [] for scene in item.get("scenes") or []]


def to_shots(storyboard: dict[str, Any]) -> list[dict[str, Any]]:
    """The rows `project_shots` holds for this storyboard: one per scene, in order, words unchanged.

    `visual_prompt` stays empty - pictures are planned after this step - and
    the asset type is the plan's own (`constraints.scene_asset_type`), or the
    column's default when the plan names none.
    """
    return [{
        "shot_index": int(scene["index"]),
        "section": SHOT_SECTION.get(str(scene.get("role")), "main"),
        "narration": str(scene["narration_text"]),
        "speaker": str(scene.get("speaker") or ""),
        "visual_prompt": "",
        "asset_type": str((scene.get("visual_intent") or {}).get("asset_type") or "") or "broll",
        "duration_seconds": max(1, int(math.ceil(float(scene.get("estimated_seconds") or 0)))),
        "status": "planned",
    } for scene in scenes(storyboard)]


def shots_match(shots: list[dict[str, Any]], storyboard: dict[str, Any]) -> bool:
    """Whether stored shots say exactly the storyboard's scenes, in order, by the same speakers."""
    wanted = [(str(scene["narration_text"]), str(scene.get("speaker") or "")) for scene in scenes(storyboard)]
    return [(str(shot.get("narration") or ""), str(shot.get("speaker") or "")) for shot in shots] == wanted


def timeline_match(segments: list[dict[str, Any]], storyboard: dict[str, Any]) -> bool:
    """Whether the timeline reads exactly the storyboard's scenes, in order, by the same speakers (whitespace aside)."""
    wanted = [(_norm(scene["narration_text"]), str(scene.get("speaker") or "")) for scene in scenes(storyboard)]
    return [(_norm(item.get("voice_text")), str(item.get("speaker") or "")) for item in segments] == wanted


def segments_match(segments: list[dict[str, Any]], storyboard: dict[str, Any]) -> bool:
    """Whether supplied timeline segments read exactly the storyboard's scenes, in order (whitespace aside)."""
    wanted = [_norm(scene["narration_text"]) for scene in scenes(storyboard)]
    spoken = [_norm(item.get("voice_text")) for item in segments if isinstance(item, dict)]
    shown = [_norm(item.get("subtitle_text") if item.get("subtitle_text") is not None else item.get("voice_text"))
             for item in segments if isinstance(item, dict)]
    return len(spoken) == len(segments) and spoken == wanted and shown == wanted
