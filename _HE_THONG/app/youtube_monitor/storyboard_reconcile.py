"""Bước 5.2 · Reconcile: carrying a project's scenes over to a new cut of its script.

When the script changes - edited in place, revised into a new version, written
again under a new plan - the Storyboard Engine cuts a new StoryboardDocument.
What the old scenes already have downstream (voice, pictures, edit layers,
review notes) is carried over to the new ones scene by scene, never by
position. Each new scene is matched to an old row in this order:

1. lines     the same words in the same section and part, by the same speaker,
             with the same spoken-line references (sec-2#3, hook#0, ...);
2. section   the same, with the lines renumbered (something was added or
             removed earlier);
3. words     the same words by the same speaker, wherever they now are;
4. moved     a scene whose words reappear out of order (reordered) - found by
             section, then by words, among what is still unmatched;
5. position  what is left between two matched scenes, in the same section and
             part: first a scene still saying some of an old scene's lines (a
             split, a merge, a moved line), then a scene rewritten in place -
             an old scene that lost a line and a new one with a line of its
             own, in order (modified). Never across sections, and never for a
             row whose scene is unknown.

Levels 1-3 are an order-preserving alignment - as many pairs as can be, each
level only inside the gaps the level above left. Where scenes say the same
words twice, the pairing the lines themselves took wins: every line of both
cuts is aligned first, so a repeated line is told apart by what surrounds it,
never by a line reference that an earlier insertion shifted onto another line.
Then each match is classified:

* unchanged   same words, speaker, section and part, lines, on-screen text and
              citations: kept as it is;
* modified    something differs. Only what depends on the difference is
              invalidated - the voice when the words or the speaker changed,
              when the timeline voiced other words, or when the voice settings
              it was made with are no longer the project's; nothing when only
              the section, the line split, the on-screen text or the citations did;
* added       a new scene: new rows;
* removed     an old scene with no counterpart: its rows leave the timeline,
              their contents are kept in the reconcile record, no file is deleted.

`lineage()` runs the same matcher storyboard against storyboard (no rows),
and is how anything kept per scene (the EditDocument) finds its scene again
after a re-cut - never by equal `scene_key`, which is a content key the same
words can carry for another scene. `with_segments()` completes it from the
timeline rows where it found nothing.

A voice is reused only when it says the scene's words, by the scene's speaker,
made with the project's current voice settings (provider, model, voice,
language and whatever that engine reads). A voice with no record of how it was
made (uploaded by hand, or older than Bước 5.2) is kept as the user's and
counted as unverified - never assumed to match.

Pure: it reads rows and documents and returns a plan; the database applies it
(Database.apply_storyboard_reconcile) in one transaction.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .storyboard_engine import scenes, shots_match

UNCHANGED, MODIFIED, ADDED, REMOVED = "unchanged", "modified", "added", "removed"
# How a new scene found the old row it takes over.
MATCH_LINES, MATCH_SECTION, MATCH_WORDS, MATCH_MOVED, MATCH_POSITION = "lines", "section", "words", "moved", "position"
# Found through the timeline row a scene took over, where lineage could not place it (with_segments).
MATCH_SEGMENT = "segment"
# Matches the matcher checked itself - by the words, the lines, the place. A scene found only through
# the timeline row it took over (with_segments) is not one of them.
VERIFIED_MATCHES = frozenset({MATCH_LINES, MATCH_SECTION, MATCH_WORDS, MATCH_MOVED, MATCH_POSITION})
# Changes that make what a matched scene kept worth a second look, in the order they are shown.
_REVIEW = ("narration", "speaker", "section", "on_screen_text")


def _norm(text: Any) -> str:
    return " ".join(str(text or "").split())


def source_rows(
    shots: list[dict[str, Any]], timeline: list[dict[str, Any]], storyboard: dict[str, Any] | None, *,
    voice_records: dict[int, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(the rows a script already has - one per shot, in order - and timeline segments tied to no shot).

    Each row knows the scene it was cut as only when the shots are exactly
    that storyboard's copy; otherwise (Reup's cut, rows from before the
    Storyboard Engine) only its words and speaker are known. `voice_records`
    (segment id → the record written beside its voice file) says how a voice
    was made.
    """
    records = voice_records or {}
    linked = {int(item["shot_id"]): item for item in timeline if item.get("shot_id")}
    known = scenes(storyboard) if storyboard and shots and shots_match(shots, storyboard) else None
    rows: list[dict[str, Any]] = []
    used: set[int] = set()

    def voice(segment: dict[str, Any] | None) -> dict[str, Any]:
        record = records.get(int(segment["id"])) if segment else None
        return {"has_audio": bool(segment and str(segment.get("audio_path") or "").strip()),
                "has_visual": bool(segment and str(segment.get("visual_path") or "").strip()),
                "voice_fingerprint": (record or {}).get("fingerprint"),
                "voice_record_text": (record or {}).get("voice_text"),
                "voice_record_speaker": (record or {}).get("speaker")}

    for position, shot in enumerate(shots):
        segment = linked.get(int(shot["id"]))
        if segment:
            used.add(int(segment["id"]))
        rows.append({
            "shot_id": int(shot["id"]), "segment_id": int(segment["id"]) if segment else None,
            "narration_text": str(shot.get("narration") or ""), "speaker": str(shot.get("speaker") or ""),
            "voiced_text": str(segment.get("voice_text") or "") if segment else None,
            "voiced_speaker": str(segment.get("speaker") or "") if segment else None,
            "scene": dict(known[position]) if known else None, **voice(segment),
        })
    orphans = [{
        "shot_id": None, "segment_id": int(item["id"]), "narration_text": str(item.get("voice_text") or ""),
        "speaker": str(item.get("speaker") or ""), "voiced_text": str(item.get("voice_text") or ""),
        "voiced_speaker": str(item.get("speaker") or ""), "scene": None, **voice(item),
    } for item in timeline if int(item["id"]) not in used]
    return rows, orphans


def _key(item: dict[str, Any], level: int, *, old: bool) -> Any:
    """What a row or scene is, at a matching level. A row whose scene is unknown matches nothing above `words`."""
    narration, speaker = _norm(item.get("narration_text")), str(item.get("speaker") or "")
    if level == 3:
        return speaker, narration
    scene = item.get("scene") if old else item
    if not scene or "section_id" not in scene:
        return "unknown", id(item)
    place = (scene.get("section_id"), scene.get("role"), speaker)
    if level == 2:
        return (*place, narration)
    return (*place, tuple(str(line.get("ref") or "") for line in scene.get("spoken_lines") or []), narration)


_LEVEL_MATCH = {2: MATCH_SECTION, 3: MATCH_WORDS}


def _same_place(row: dict[str, Any], scene: dict[str, Any]) -> bool:
    """Whether an old row's scene is known to sit in the same section and part as the new scene."""
    old = row.get("scene")
    return bool(old) and "section_id" in old         and (old.get("section_id"), old.get("role")) == (scene.get("section_id"), scene.get("role"))


def _shared(row: dict[str, Any], scene: dict[str, Any]) -> int:
    """How many spoken lines an old row's scene and a new scene both say, word for word."""
    old = Counter(_norm(line.get("text")) for line in (row.get("scene") or {}).get("spoken_lines") or [])
    return sum((old & Counter(_norm(line.get("text")) for line in scene.get("spoken_lines") or [])).values())


def _align(a: list[Any], b: list[Any], bonus, *, trim: bool = False) -> list[tuple[int, int]]:
    """Order-preserving pairs of equal keys: as many as there can be, then as many as can be where `bonus(i, j)`.

    A longest common subsequence rather than greedy longest blocks: the number
    of pairs comes first, so after a line added or removed earlier the same
    words said twice still pair with their own; the bonus only decides between
    equally long pairings - which of two identical lines an edit left alone.
    `trim` pairs an equal head and tail first (the lines of an untouched
    beginning and end), which no longer pairing can improve on.
    """
    n, m = len(a), len(b)
    head = tail = 0
    if trim:
        while head < min(n, m) and a[head] == b[head]:
            head += 1
        while tail < min(n, m) - head and a[n - 1 - tail] == b[m - 1 - tail]:
            tail += 1
    a_mid, b_mid = a[head:n - tail], b[head:m - tail]
    rows, cols = len(a_mid), len(b_mid)
    score = [[(0, 0)] * (cols + 1) for _ in range(rows + 1)]
    for i in range(rows - 1, -1, -1):
        below, here = score[i + 1], score[i]
        for j in range(cols - 1, -1, -1):
            best = max(below[j], here[j + 1])
            if a_mid[i] == b_mid[j]:
                count, extra = below[j + 1]
                best = max(best, (count + 1, extra + bonus(head + i, head + j)))
            here[j] = best
    pairs = [(k, k) for k in range(head)]
    i = j = 0
    while i < rows and j < cols:
        if a_mid[i] == b_mid[j] and (score[i + 1][j + 1][0] + 1, score[i + 1][j + 1][1] + bonus(head + i, head + j)) == score[i][j]:
            pairs.append((head + i, head + j))
            i, j = i + 1, j + 1
        elif score[i + 1][j] == score[i][j]:
            i += 1
        else:
            j += 1
    return pairs + [(n - tail + k, m - tail + k) for k in range(tail)]


def _lines(item: dict[str, Any], *, old: bool) -> list[tuple[tuple[Any, ...], str]]:
    """(what the line is: section, part, speaker, words - and its reference) for each line of a row's known scene or a new scene."""
    scene = item.get("scene") if old else item
    if not scene or "section_id" not in scene:
        return []
    return [((scene.get("section_id"), scene.get("role"), str(line.get("speaker") or ""), _norm(line.get("text"))),
             str(line.get("ref") or "")) for line in scene.get("spoken_lines") or []]


def _line_flow(rows: list[dict[str, Any]], new: list[dict[str, Any]]) -> tuple[dict[int, Counter], set[int], set[int]]:
    """Where the old scenes' lines went: ({old index: Counter(new index: lines)}, old scenes that lost a line,
    new scenes with a line of their own).

    Every line of both cuts aligned as one sequence: the same words in the same
    section, part and voice, as many as can be, the same reference deciding
    only between equally long alignments. A line said twice is told apart by
    what surrounds it, a line added or removed earlier shifts nothing, and a
    line found again out of order is moved, neither lost nor new. Lines of a
    row whose scene is unknown have no place here.
    """
    a = [(i, key, ref) for i, row in enumerate(rows) for key, ref in _lines(row, old=True)]
    b = [(j, key, ref) for j, scene in enumerate(new) for key, ref in _lines(scene, old=False)]
    pairs = _align([key for _, key, _ in a], [key for _, key, _ in b], lambda x, y: int(a[x][2] == b[y][2]), trim=True)
    flow: dict[int, Counter] = {}
    for x, y in pairs:
        flow.setdefault(a[x][0], Counter())[b[y][0]] += 1
    left_a = set(range(len(a))) - {x for x, _ in pairs}
    left_b = set(range(len(b))) - {y for _, y in pairs}
    moved_a, moved_b = {a[x][1] for x in left_a}, {b[y][1] for y in left_b}
    lost = {a[x][0] for x in left_a if a[x][1] not in moved_b}
    fresh = {b[y][0] for y in left_b if b[y][1] not in moved_a}
    return flow, lost, fresh


def _anchors(rows: list[dict[str, Any]], new: list[dict[str, Any]], old_ids: list[int], new_ids: list[int],
             flow: dict[int, Counter], level: int = 2) -> list[tuple[int, int, str]]:
    """Order-preserving matches of equal keys: the same words in the same section and part first (`lines` when
    the line references are the same too, `section` when they were renumbered), then the same words anywhere
    (`words`) only inside the gaps that left. Between equally long pairings, the one the lines themselves took
    wins (`flow`): line references never pair two scenes on their own, since after an earlier line was added
    or removed they point at other lines."""
    if level > 3 or not old_ids or not new_ids:
        return []
    a = [_key(rows[i], level, old=True) for i in old_ids]
    b = [_key(new[j], level, old=False) for j in new_ids]
    pairs = _align(a, b, lambda x, y: (flow.get(old_ids[x]) or {}).get(new_ids[y], 0))
    found: list[tuple[int, int, str]] = [
        (old_ids[x], new_ids[y], MATCH_LINES if level == 2 and _key(rows[old_ids[x]], 1, old=True) == _key(new[new_ids[y]], 1, old=False)
         else _LEVEL_MATCH[level]) for x, y in pairs]
    for (x0, y0), (x1, y1) in zip([(-1, -1), *pairs], [*pairs, (len(a), len(b))]):
        found += _anchors(rows, new, old_ids[x0 + 1:x1], new_ids[y0 + 1:y1], flow, level + 1)
    return found


def keeps_voice(row: dict[str, Any], scene: dict[str, Any], voice_fingerprint: str | None = None) -> bool:
    """Whether a row's voice still says exactly this scene: same words, same speaker, the project's current voice settings."""
    if row.get("segment_id") is None or row.get("voiced_text") is None:
        return False
    if (_norm(row["voiced_text"]), str(row.get("voiced_speaker") or "")) != (_norm(scene["narration_text"]), str(scene.get("speaker") or "")):
        return False
    if row.get("has_audio") and row.get("voice_fingerprint") is not None:
        # The record beside the file says what it says and how it was made: both must still hold.
        if voice_fingerprint is not None and row["voice_fingerprint"] != voice_fingerprint:
            return False
        if _norm(row.get("voice_record_text")) != _norm(scene["narration_text"]) \
                or str(row.get("voice_record_speaker") or "") != str(scene.get("speaker") or ""):
            return False
    return True


def changes(row: dict[str, Any], scene: dict[str, Any], voice_fingerprint: str | None = None) -> list[str]:
    """What differs between an old row (and the scene it was cut as, when known) and the new scene."""
    found: list[str] = []
    if _norm(row["narration_text"]) != _norm(scene["narration_text"]):
        found.append("narration")
    if str(row.get("speaker") or "") != str(scene.get("speaker") or ""):
        found.append("speaker")
    old = row.get("scene")
    if old:
        # Only what the old document recorded is compared.
        if any(key in old and old.get(key) != scene.get(key) for key in ("section_id", "plan_section_id", "role")):
            found.append("section")
        if [line.get("text") for line in old.get("spoken_lines") or []] != [line.get("text") for line in scene.get("spoken_lines") or []] \
                and "narration" not in found:
            found.append("lines")
        if list(old.get("on_screen_text") or []) != list(scene.get("on_screen_text") or []):
            found.append("on_screen_text")
        if (list(old.get("insight_ids") or []), list(old.get("evidence_ids") or [])) != \
                (list(scene.get("insight_ids") or []), list(scene.get("evidence_ids") or [])):
            found.append("citations")
    if row.get("segment_id") is not None and not {"narration", "speaker"} & set(found):
        if (_norm(row.get("voiced_text")), str(row.get("voiced_speaker") or "")) != (_norm(scene["narration_text"]), str(scene.get("speaker") or "")):
            # The shot says the scene, but the timeline voiced something else (a translation, an edit).
            found.append("voiced_text")
        elif row.get("has_audio") and not keeps_voice(row, scene, voice_fingerprint):
            # The words are the scene's, but the voice was made with other settings (or says other words).
            found.append("voice_config")
    return found


def _match(rows: list[dict[str, Any]], new: list[dict[str, Any]]) -> tuple[dict[int, tuple[int, str]], set[int]]:
    """({new index: (old index, how)}, the old indexes taken) - the one matcher rows and storyboards both use.

    Each old scene goes to one new scene at most, and each new scene takes one
    old scene at most: every step below only looks at what no step before took.
    """
    flow, lost, fresh = _line_flow(rows, new)
    anchors = _anchors(rows, new, list(range(len(rows))), list(range(len(new))), flow)
    taken_old = {i for i, _, _ in anchors}
    taken_new = {j for _, j, _ in anchors}
    matches: dict[int, tuple[int, str]] = {j: (i, how) for i, j, how in anchors}

    # Reordered scenes: the same words met again out of order - by section first, then anywhere.
    for level in (2, 3):
        for j in range(len(new)):
            if j in taken_new:
                continue
            key = _key(new[j], level, old=False)
            i = next((i for i in range(len(rows)) if i not in taken_old and _key(rows[i], level, old=True) == key), None)
            if i is not None:
                matches[j] = (i, MATCH_MOVED)
                taken_old.add(i)
                taken_new.add(j)

    # What is left between two in-order matches is the same place in the story, said differently -
    # but only inside the same section and part: a scene of another section is another scene, so its
    # picture and edit never pass to this one. A row whose scene is unknown is never paired by place.
    # First a new scene still saying some of an old scene's lines (a scene split or merged, a line
    # moved) takes the old scene whose lines it holds most - the earlier on a tie, each new scene in
    # order. Then a scene rewritten in place: an old scene that lost a line and a new scene with a line
    # of its own, paired in order, never across a pair made by shared lines. A scene whose lines all
    # live on elsewhere is not "said differently" here: it went, and its row is recorded.
    bounds = [(-1, -1), *sorted((i, j) for i, j, _ in anchors), (len(rows), len(new))]
    for (i0, j0), (i1, j1) in zip(bounds, bounds[1:]):
        left_old = [i for i in range(i0 + 1, i1) if i not in taken_old]
        left_new = [j for j in range(j0 + 1, j1) if j not in taken_new]
        sharing: list[tuple[int, int]] = []
        for j in left_new:
            scored = [((flow.get(i) or {}).get(j, 0), _shared(rows[i], new[j]), -i) for i in left_old
                      if i not in taken_old and _same_place(rows[i], new[j])]
            best = max(scored, default=(0, 0, 0))
            if best[0] or best[1]:
                sharing.append((-best[2], j))
                matches[j] = (-best[2], MATCH_POSITION)
                taken_old.add(-best[2])
                taken_new.add(j)
        at = 0
        for j in [j for j in left_new if j not in taken_new and j in fresh]:
            found = next((k for k in range(at, len(left_old)) if left_old[k] not in taken_old and left_old[k] in lost
                          and _same_place(rows[left_old[k]], new[j])
                          and all((p < left_old[k]) == (q < j) for p, q in sharing)), None)
            if found is None:
                continue
            i = left_old[found]
            matches[j] = (i, MATCH_POSITION)
            taken_old.add(i)
            taken_new.add(j)
            at = found + 1
    return matches, taken_old


def inheritance(match: str | None, found: list[str], keep_voice: bool | None = None) -> dict[str, Any]:
    """What a new scene may take from the old scene it was matched to.

    A match says which old scene a new one is - not that everything the old one
    had still fits it:

    * visual  the picture, and the look it was edited with (transition, effect,
              trims, cleanups), follows any verified match - kept when the
              words change too, with `review` saying why to look at it again;
    * layers  overlays, graphic direction, sound cues and edit beats are made
              for what is said: they still fit only while the words, the
              speaker and the on-screen text are the scene's own - otherwise
              they are stale;
    * timing  times set against the scene's voice hold while that voice is kept
              (`keep_voice` - only the rows know it, keeps_voice()); otherwise
              they are retimed to the scene's new length. Without the rows
              (lineage) new words or another speaker still settle it - no voice
              survives them - but the same words do not: a voice made with
              other settings moves the times as much, so the answer is None,
              left to the voice, never guessed;
    * a scene found only through its timeline row (`segment`), or not found,
      takes nothing: unverified, it is shown for review.

    The one policy: the reconcile (plan) and lineage both ask it, and so does
    anything kept per scene after them (the EditDocument), with the changes
    since what it keeps was made.
    """
    if match not in VERIFIED_MATCHES:
        return {"visual": False, "layers": False, "timing": False, "review": ["unverified"] if match else []}
    changed = set(found)
    words = not {"narration", "speaker"} & changed
    return {"visual": True, "layers": words and "on_screen_text" not in changed,
            "timing": bool(keep_voice) if keep_voice is not None else (None if words else False),
            "review": [reason for reason in _REVIEW if reason in changed]}


def plan(rows: list[dict[str, Any]], orphans: list[dict[str, Any]], storyboard: dict[str, Any], *,
         voice_fingerprint: str | None = None) -> dict[str, Any]:
    """How each new scene takes over an old row, which are new, and which old rows go.

    Decides the row each scene takes over and whether its voice is kept
    (keeps_voice) - nothing else: what the scene may take besides is
    inheritance()'s, the same policy lineage asks.
    """
    new = scenes(storyboard)
    matches, taken_old = _match(rows, new)
    entries: list[dict[str, Any]] = []
    for j, scene in enumerate(new):
        if j in matches:
            i, how = matches[j]
            row = rows[i]
            found = changes(row, scene, voice_fingerprint)
            keep = keeps_voice(row, scene, voice_fingerprint)
            entries.append({"status": MODIFIED if found else UNCHANGED, "changes": found, "row": row, "match": how,
                            "keep_voice": keep, "inherit": inheritance(how, found, keep)})
        else:
            entries.append({"status": ADDED, "changes": [], "row": None, "match": None, "keep_voice": False,
                            "inherit": inheritance(None, [])})
        entries[-1].update(index=j + 1, scene_key=scene.get("scene_key"),
                           previous_scene_key=((entries[-1]["row"] or {}).get("scene") or {}).get("scene_key"))
    removed = [row for i, row in enumerate(rows) if i not in taken_old] + list(orphans)
    counts = Counter(entry["status"] for entry in entries)
    return {
        "entries": entries,
        "removed": removed,
        "counts": {UNCHANGED: counts[UNCHANGED], MODIFIED: counts[MODIFIED], ADDED: counts[ADDED], REMOVED: len(removed)},
        "voice_invalidated": sum(1 for entry in entries if entry["row"] and entry["row"].get("has_audio") and not entry["keep_voice"]),
        "voice_unverified": sum(1 for entry in entries if entry["row"] and entry["row"].get("has_audio") and entry["keep_voice"]
                                and entry["row"].get("voice_fingerprint") is None),
    }


def _scene_row(scene: dict[str, Any]) -> dict[str, Any]:
    """An old scene, shaped like a row with no timeline behind it, for the shared matcher."""
    return {"shot_id": None, "segment_id": None, "narration_text": str(scene.get("narration_text") or ""),
            "speaker": str(scene.get("speaker") or ""), "voiced_text": None, "voiced_speaker": None,
            "has_audio": False, "has_visual": False, "voice_fingerprint": None, "voice_record_text": None,
            "voice_record_speaker": None, "scene": dict(scene)}


def scene_changes(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """What differs between a scene as it was and a scene now, in the words inheritance() reads - no voice involved.

    The comparison lineage makes between two cuts, and the EditDocument makes
    between the scene an edit was made for (its basis) and the scene now.
    """
    return changes(_scene_row(before), after)


def lineage(old_board: dict[str, Any] | None, new_board: dict[str, Any]) -> dict[str, Any]:
    """Which scene of the old storyboard each scene of the new one is - the only way an old scene is found again.

    Storyboard against storyboard, with the same matcher as the rows: lines,
    then section, then words, then moved, then place inside the same section
    and part. `scene_key` equality is never the test: it is a content key, and
    the same words can carry the same key for another scene (a line said twice,
    the first one deleted). A split leaves the old scene to the first piece
    still saying its lines and the rest added; a merge gives the new scene to
    the first old part whose lines it says and the others removed. Each scene
    says what it may take from the one it came from (`inherit`): a match is
    not leave to keep everything. Needs no database rows, so it holds whatever
    state the timeline is in.
    """
    old = scenes(old_board) if old_board else []
    new = scenes(new_board)
    rows = [_scene_row(scene) for scene in old]
    matches, taken = _match(rows, new)
    placed: list[dict[str, Any]] = []
    for j, scene in enumerate(new):
        if j in matches:
            i, how = matches[j]
            found = scene_changes(old[i], scene)
            placed.append({"index": j + 1, "scene_key": scene.get("scene_key"), "previous_scene_key": old[i].get("scene_key"),
                           "previous_index": old[i].get("index"), "match": how, "status": MODIFIED if found else UNCHANGED,
                           "changes": found, "inherit": inheritance(how, found)})
        else:
            placed.append({"index": j + 1, "scene_key": scene.get("scene_key"), "previous_scene_key": None,
                           "previous_index": None, "match": None, "status": ADDED, "changes": [],
                           "inherit": inheritance(None, [])})
    removed = [{"scene_key": old[i].get("scene_key"), "index": old[i].get("index")} for i in range(len(old)) if i not in taken]
    counts = Counter(item["status"] for item in placed)
    return {
        "from_document_hash": (old_board or {}).get("document_hash"), "to_document_hash": new_board.get("document_hash"),
        "scenes": placed, "removed": removed,
        "counts": {UNCHANGED: counts[UNCHANGED], MODIFIED: counts[MODIFIED], ADDED: counts[ADDED], REMOVED: len(removed)},
    }


def with_segments(result: dict[str, Any], links: dict[str, int | None], owners: dict[int, str]) -> dict[str, Any]:
    """Lineage completed from the rows, for new scenes it could not place.

    `links`: new scene_key → the old segment id that scene's row took over (the
    reconcile record). `owners`: old segment id → the old scene_key it carried
    (an EditDocument's applied map, say). Used only where lineage found nothing,
    only for an old scene of this lineage that lineage left unplaced, never to
    give one old scene to two new ones. Marked "segment" and unverified - the
    words behind the row are not compared here - so it takes nothing on its
    own (`inherit`): whatever it had is shown for review, not carried over.
    """
    placed = [dict(item) for item in result["scenes"]]
    claimed = {item["previous_scene_key"] for item in placed if item["previous_scene_key"]}
    unplaced = {item["scene_key"]: item.get("index") for item in result["removed"]}
    for item in placed:
        if item["previous_scene_key"]:
            continue
        owner = owners.get(links.get(item["scene_key"])) if links.get(item["scene_key"]) is not None else None
        if owner and owner in unplaced and owner not in claimed:
            item.update(previous_scene_key=owner, previous_index=unplaced[owner], match=MATCH_SEGMENT, status=MODIFIED,
                        changes=["unverified"], inherit=inheritance(MATCH_SEGMENT, ["unverified"]))
            claimed.add(owner)
    removed = [item for item in result["removed"] if item["scene_key"] not in claimed]
    counts = Counter(item["status"] for item in placed)
    return {**result, "scenes": placed, "removed": removed,
            "counts": {UNCHANGED: counts[UNCHANGED], MODIFIED: counts[MODIFIED], ADDED: counts[ADDED], REMOVED: len(removed)}}


def destructive(result: dict[str, Any]) -> bool:
    """Whether applying a plan to a script's own rows loses something: a voice that no longer fits, or rows that go."""
    return bool(result["removed"]) or result["voice_invalidated"] > 0


def report(result: dict[str, Any]) -> dict[str, Any]:
    """The plan as it is shown and kept: what happened to each scene, without the rows themselves."""
    return {
        "counts": dict(result["counts"]),
        "voice_invalidated": result["voice_invalidated"],
        "voice_unverified": result["voice_unverified"],
        "scenes": [{"index": entry["index"], "scene_key": entry["scene_key"], "status": entry["status"],
                    "match": entry["match"], "changes": entry["changes"], "keep_voice": entry["keep_voice"],
                    "inherit": entry["inherit"], "previous_scene_key": entry["previous_scene_key"],
                    "shot_id": (entry["row"] or {}).get("shot_id"), "segment_id": (entry["row"] or {}).get("segment_id")}
                   for entry in result["entries"]],
        "removed": [{"shot_id": row.get("shot_id"), "segment_id": row.get("segment_id"),
                     "narration_text": row.get("narration_text"), "has_audio": row.get("has_audio"),
                     "has_visual": row.get("has_visual")} for row in result["removed"]],
    }
