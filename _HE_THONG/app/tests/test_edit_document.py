"""Bước 5.3 · T1 · the EditDocument engine (pure).

    StoryboardDocument + the voice now + previous EditDocument ─(lineage)→ EditDocument

Each scene's edit is kept with its basis - the scene and the voice it was made
for - and judged again on every build from that basis against what is there
now, through inheritance(): never from the timeline, never from a reconcile
record, never from an equal scene_key.
"""

from __future__ import annotations

import copy
import json
import unittest
from unittest import mock

from tests.test_storyboard_engine import KNOWN, PLAN_ROW, _document, _line, _script, _section
from tests.test_storyboard_gate import _rows
from youtube_monitor import edit_document as ed, storyboard_engine as sb, storyboard_reconcile as rc


def _cut(*sections: list[str], words: dict | None = None, speakers: dict | None = None, texts: dict | None = None,
         groups: list[list[str]] | None = None) -> dict:
    """A storyboard whose lines (15 words = 5 s each, unless `words` says) are one scene each, unless `groups` says."""
    words, speakers = words or {}, speakers or {}
    document = _document([_section(n, [_line(tag, words.get(tag, 15), speakers.get(tag, "narrator")) for tag in tags],
                                   texts=(texts or {}).get(n, ()), budget=400) for n, tags in enumerate(sections, start=1)])
    groups = groups or [[f"sec-{n}#{i}"] for n, tags in enumerate(sections, start=1) for i in range(len(tags))]
    board = sb.build(_script(document), PLAN_ROW, known_ids=KNOWN, groups=groups)
    assert board["status"] == sb.VALID, board["validation"]
    return board


def _voices(board: dict, **overrides) -> dict:
    """Each scene voiced: the audio is named by what it says and who says it, at the scene's length."""
    lengths = {scene["scene_key"]: float(shot["duration_seconds"]) for scene, shot in zip(sb.scenes(board), sb.to_shots(board))}
    found = {scene["scene_key"]: {"audio_signature": f"audio:{scene['speaker']}:{scene['narration_text']}",
                                  "voice_fingerprint": "fp", "duration_seconds": lengths[scene["scene_key"]], "fits": True}
             for scene in sb.scenes(board)}
    for key, change in overrides.items():
        found[key] = {**found[key], **change}
    return found


def _key(board: dict, tag: str, occurrence: int = 1) -> str:
    found = [scene["scene_key"] for scene in sb.scenes(board) if scene["narration_text"].split()[0] == tag]
    return found[occurrence - 1]


def _edit(name: str, seconds: float = 5.0, beats: list | None = None) -> dict:
    return ed.edit({"visual_path": f"{name}.png", "asset_type": "ai_scene", "edit_transition": "fade"},
                   overlays=[{"kind": "text", "text": name, "start_seconds": 1.0, "end_seconds": seconds - 0.5}],
                   sound_cues=[{"cue": "whoosh", "start_seconds": 0.5, "end_seconds": 1.0}],
                   beats=beats if beats is not None else [
                       {"visual_path": f"{name}-a.png", "start_seconds": 0.0, "duration_seconds": seconds / 2},
                       {"visual_path": f"{name}-b.png", "start_seconds": seconds / 2, "duration_seconds": seconds / 2}])


def _planned(board: dict, voices: dict | None = None, edits: dict | None = None, **options) -> dict:
    """A document for `board` with every scene's edit made for it, at its length (edits: scene_key → edit)."""
    document = ed.build(board, voices=voices if voices is not None else _voices(board), **options)
    for scene, item in zip(sb.scenes(board), document["scenes"]):
        key = scene["scene_key"]
        made = (edits or {}).get(key) or _edit(scene["narration_text"].split()[0], seconds=item["voice"]["duration_seconds"])
        document = ed.plan_scene(document, board, key, made)
    return document


def _next(old_board: dict, old_document: dict, new_board: dict, voices: dict | None = None, **options) -> dict:
    return ed.build(new_board, voices=voices if voices is not None else _voices(new_board), previous=old_document,
                    previous_storyboard=old_board, **options)


def _scene(document: dict, key: str) -> dict:
    return next(item for item in document["scenes"] if item["scene_key"] == key)


class ShapeTests(unittest.TestCase):
    def test_a_fresh_document_names_its_sources_and_needs_a_plan_everywhere(self) -> None:
        board = _cut(["A", "B"])
        document = ed.build(board, voices=_voices(board), storyboard_id=7, voice_fingerprint="fp")
        self.assertEqual((document["kind"], document["engine_version"], document["based_on"]), ("edit_document", "edit-phase1", None))
        provenance = document["provenance"]
        self.assertEqual({key: provenance[key] for key in ("storyboard_id", "storyboard_hash", "storyboard_engine", "script_id",
                                                           "script_version", "script_fingerprint", "plan_id", "plan_version",
                                                           "plan_fingerprint", "voice_fingerprint")},
                         {"storyboard_id": 7, "storyboard_hash": board["document_hash"], "storyboard_engine": board["engine_version"],
                          "script_id": board["script_id"], "script_version": board["script_version"],
                          "script_fingerprint": board["script_fingerprint"], "plan_id": board["plan_id"],
                          "plan_version": board["plan_version"], "plan_fingerprint": board["plan_fingerprint"], "voice_fingerprint": "fp"})
        self.assertTrue(provenance["audio_signature"])
        self.assertEqual([(item["status"], item["statuses"], item["ready"], item["basis"]) for item in document["scenes"]],
                         [("needs_plan", ["needs_plan"], False, None)] * 2)
        self.assertEqual(document["counts"], {"ready": 0, "needs_plan": 2, "stale_content": 0, "stale_overlays": 0,
                                              "stale_timing": 0, "visual_review": 0, "orphan": 0})
        self.assertEqual(ed.validate(document, board), [])

    def test_the_same_inputs_give_the_same_document(self) -> None:
        board, changed = _cut(["A", "X", "B"]), _cut(["A", "X", "B"], words={"X": 8})
        first = _next(board, _planned(board), changed)
        again = _next(board, _planned(board), changed)
        self.assertEqual(first, again)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(again, sort_keys=True), "plain data, the same bytes")
        self.assertEqual(first["document_hash"], ed.document_hash(first))
        self.assertEqual(first["based_on"], _planned(board)["document_hash"])

    def test_planning_a_scene_makes_its_basis_and_the_scene_is_ready(self) -> None:
        board = _cut(["A", "B"])
        voices = _voices(board)
        key = _key(board, "A")
        document = ed.plan_scene(ed.build(board, voices=voices), board, key, _edit("a"))
        item = _scene(document, key)
        scene = next(scene for scene in sb.scenes(board) if scene["scene_key"] == key)
        self.assertEqual((item["status"], item["ready"], item["timing"]["state"]), ("ready", True, "kept"))
        self.assertEqual((item["basis"]["scene_key"], item["basis"]["storyboard_hash"], item["basis"]["scene"]["narration_text"]),
                         (key, board["document_hash"], scene["narration_text"]))
        self.assertEqual(item["basis"]["voice"], {key2: voices[key][key2] for key2 in ("audio_signature", "voice_fingerprint", "duration_seconds")})
        self.assertEqual(item["basis"]["edit_hash"], ed.edit_hash(_edit("a")))
        self.assertEqual(_scene(document, _key(board, "B"))["status"], "needs_plan")
        self.assertEqual(ed.validate(document, board), [])

    def test_the_engine_asks_only_the_canonical_policies_and_reads_nothing(self) -> None:
        board, changed = _cut(["A", "X", "B"]), _cut(["A", "X", "B"], words={"X": 8})
        before = _planned(board)
        with mock.patch.object(rc, "plan", side_effect=AssertionError("plan() never decides an edit")), \
                mock.patch.object(ed, "keeps_voice", side_effect=AssertionError("keeps_voice() comes in with the voice")), \
                mock.patch("builtins.open", side_effect=AssertionError("no file is read")), \
                mock.patch.object(ed, "inheritance", wraps=rc.inheritance) as asked, \
                mock.patch.object(ed, "lineage", wraps=rc.lineage) as followed:
            document = _next(board, before, changed)
        self.assertEqual(followed.call_count, 1)
        self.assertEqual(asked.call_count, 3, "one verdict per scene that has an edit")
        self.assertEqual(ed.validate(document, changed), [])


class MatrixTests(unittest.TestCase):
    """What a scene keeps of its edit, by what changed since the edit was made for it."""

    def setUp(self) -> None:
        self.board = _cut(["A", "X", "B"])
        self.document = _planned(self.board)
        self.x = _key(self.board, "X")

    def _after(self, board: dict, voices: dict | None = None) -> dict:
        document = _next(self.board, self.document, board, voices)
        self.assertEqual(ed.validate(document, board), [])
        return document

    def test_a_nothing_changed_keeps_everything(self) -> None:
        document = self._after(self.board)
        self.assertTrue(all(item["ready"] for item in document["scenes"]))
        item = _scene(document, self.x)
        self.assertEqual((item["inherit"], item["timing"]["state"]), (
            {"visual": True, "layers": True, "timing": True, "review": []}, "kept"))
        self.assertEqual(ed.effective_edit(item), _edit("X"))

    def test_b_new_words_keep_the_picture_retime_and_mark_the_layers_stale(self) -> None:
        board = _cut(["A", "X", "B"], words={"X": 8})
        document = self._after(board)
        item = _scene(document, _key(board, "X"))
        self.assertNotEqual(item["voice"]["audio_signature"], item["basis"]["voice"]["audio_signature"], "the old voice is gone")
        self.assertEqual((item["statuses"], item["review"], item["inherit"]),
                         (["stale_content", "visual_review"], ["narration"],
                          {"visual": True, "layers": False, "timing": False, "review": ["narration"]}))
        self.assertEqual((item["timing"]["state"], item["timing"]["basis_seconds"], item["timing"]["current_seconds"]), ("retimed", 5.0, 3.0))
        played = ed.effective_edit(item)
        self.assertEqual(played["visual"], _edit("X")["visual"], "the picture is kept")
        self.assertEqual(played["layers"]["overlays"][0]["end_seconds"], round(4.5 * 3 / 5, 3))
        self.assertEqual([beat["duration_seconds"] for beat in played["beats"]], [1.5, 1.5])
        self.assertEqual(item["edit"], _edit("X"), "kept as it was made: the timing is applied, never accumulated")
        self.assertTrue(all(other["ready"] for other in document["scenes"] if other is not item))

    def test_c_another_speaker(self) -> None:
        board = _cut(["A", "X", "B"], speakers={"X": "khach"})
        item = _scene(self._after(board), _key(board, "X"))
        self.assertEqual((item["statuses"], item["review"], item["timing"]["state"], item["inherit"]["visual"]),
                         (["stale_content", "visual_review"], ["speaker"], "retimed", True))

    def test_d_another_section_with_the_same_words_follows_the_policy(self) -> None:
        board, moved = _cut(["A"], ["B"]), _cut(["B", "A"])
        before = _planned(board)
        document = _next(board, before, moved)
        item = _scene(document, _key(moved, "B"))
        self.assertEqual(item["lineage"]["match"], "moved")
        self.assertEqual(item["inherit"], rc.inheritance("moved", ["section"], True))
        self.assertEqual((item["statuses"], item["timing"]["state"]), (["visual_review"], "kept"),
                         "the same words and voice: layers and times fit, the picture is looked at again")

    def test_e_new_on_screen_text_makes_the_layers_stale_not_the_picture(self) -> None:
        board, texted = _cut(["A"]), _cut(["A"], texts={1: ["Chữ mới"]})
        item = _scene(_next(board, _planned(board), texted), _key(texted, "A"))
        self.assertEqual((item["statuses"], item["review"], item["inherit"]["visual"], item["timing"]["state"]),
                         (["stale_overlays", "visual_review"], ["on_screen_text"], True, "kept"))

    def test_f_new_voice_settings_retime_the_same_words_never_keep_them(self) -> None:
        # The same words, voiced with settings the project no longer uses: keeps_voice() says it does not fit.
        shots, timeline = _rows(self.board)
        records = {item["id"]: {"fingerprint": "fp-a", "voice_text": item["voice_text"], "speaker": item["speaker"]} for item in timeline}
        rows, _ = rc.source_rows(shots, timeline, self.board, voice_records=records)
        scene = next(scene for scene in sb.scenes(self.board) if scene["scene_key"] == self.x)
        row = rows[[item["scene_key"] for item in sb.scenes(self.board)].index(self.x)]
        made = ed.voice_entry(row, scene, audio_signature="a1", duration_seconds=5, voice_fingerprint="fp-a")
        now = ed.voice_entry(row, scene, audio_signature="a1", duration_seconds=5, voice_fingerprint="fp-b")
        self.assertEqual((made["fits"], now["fits"]), (True, False))
        document = _planned(self.board, voices=_voices(self.board, **{self.x: made}))
        item = _scene(_next(self.board, document, self.board, _voices(self.board, **{self.x: now})), self.x)
        self.assertEqual((item["inherit"]["timing"], item["timing"]["state"], item["statuses"]), (False, "retimed", []))
        self.assertIsNone(rc.lineage(self.board, self.board)["scenes"][1]["inherit"]["timing"],
                          "lineage alone leaves it open; the edit's verdict comes from the voice")

    def test_g_the_same_voice_never_marks_timing_stale(self) -> None:
        board = _cut(["A", "X", "B"], texts={1: ["Chữ mới"]})
        document = self._after(board)
        self.assertTrue(all(item["timing"]["state"] == "kept" and "stale_timing" not in item["statuses"] for item in document["scenes"]))

    def test_h_times_that_cannot_follow_the_new_voice_are_stale(self) -> None:
        # A 0.2 s beat on a 5 s scene: at 3 s it would be 0.12 s, shorter than the renderer allows.
        key = self.x
        document = ed.plan_scene(self.document, self.board, key, _edit("X", beats=[
            {"visual_path": "x-a.png", "start_seconds": 0, "duration_seconds": 4.8},
            {"visual_path": "x-b.png", "start_seconds": 4.8, "duration_seconds": 0.2}]))
        board = _cut(["A", "X", "B"], words={"X": 8})
        after = _next(self.board, document, board)
        self.assertEqual(ed.validate(after, board), [])
        item = _scene(after, _key(board, "X"))
        self.assertEqual((item["statuses"], item["timing"]["state"]), (["stale_content", "stale_timing", "visual_review"], "stale"))
        self.assertTrue(item["timing"]["errors"])
        with self.assertRaises(ed.EditDocumentError):
            ed.plan_scene(after, board, item["scene_key"])

    def test_i_a_split_gives_the_old_edit_to_its_first_piece_only(self) -> None:
        whole = _cut(["L1", "L2"], words={"L1": 8, "L2": 7}, groups=[["sec-1#0", "sec-1#1"]])
        halves = _cut(["L1", "L2"], words={"L1": 8, "L2": 7})
        document = _next(whole, _planned(whole), halves)
        first, second = document["scenes"]
        self.assertEqual((first["lineage"]["match"], first["statuses"], first["timing"]["state"], first["edit"]["visual"]),
                         ("position", ["stale_content", "visual_review"], "retimed", _edit("L1")["visual"]))
        self.assertEqual((second["statuses"], second["edit"], second["basis"]), (["needs_plan"], ed.normalize_edit(None), None),
                         "the new piece takes none of the old layers")
        self.assertEqual(document["orphans"], [])

    def test_j_a_merge_takes_one_old_edit_and_holds_the_other(self) -> None:
        halves = _cut(["L1", "L2"], words={"L1": 8, "L2": 7})
        whole = _cut(["L1", "L2"], words={"L1": 8, "L2": 7}, groups=[["sec-1#0", "sec-1#1"]])
        document = _next(halves, _planned(halves), whole)
        (merged,) = document["scenes"]
        self.assertEqual((merged["edit"], merged["statuses"], merged["timing"]["state"]),
                         (_edit("L1", seconds=3.0), ["stale_content", "visual_review"], "retimed"))
        self.assertEqual([(item["reason"], item["edit"], item["candidate"]) for item in document["orphans"]],
                         [("removed", _edit("L2", seconds=3.0), None)], "the other part's layers are held, not merged in")

    def test_k_an_orphan_is_never_ready(self) -> None:
        board = _cut(["A", "B"])
        document = _next(self.board, self.document, board)
        (orphan,) = document["orphans"]
        self.assertEqual((orphan["scene_key"], orphan["reason"], orphan["status"], orphan["ready"], orphan["edit"]),
                         (self.x, "removed", "orphan", False, _edit("X")))
        self.assertEqual(orphan["basis"]["scene"]["narration_text"].split()[0], "X", "what it was made for goes with it")
        self.assertEqual(document["counts"]["orphan"], 1)
        tampered = copy.deepcopy(document)
        tampered["orphans"][0]["ready"] = True
        self.assertIn("Lớp dựng mồ côi 1 không được coi là sẵn sàng", ed.validate(tampered))

    def test_l_an_unverified_or_legacy_edit_is_held_never_taken(self) -> None:
        board = _cut(["A", "B"])
        key = _key(board, "A")
        document = ed.build(board, voices=_voices(board), legacy={key: {"segment_id": 41, "edit": _edit("old")}})
        item = _scene(document, key)
        self.assertEqual((item["statuses"], item["review"], item["edit"], item["lineage"]["match"], item["lineage"]["previous_segment_id"]),
                         (["needs_plan"], ["unverified"], ed.normalize_edit(None), "segment", 41))
        self.assertEqual([(orphan["reason"], orphan["candidate"], orphan["segment_id"]) for orphan in document["orphans"]],
                         [("legacy", key, 41)])
        self.assertEqual(ed.validate(document, board), [])
        # Found only through the timeline row it took over: the same.
        old, new = _cut(["X1", "X2", "X3"]), _cut(["P"], ["A1", "A2", "A3"])
        segments = {scene["scene_key"]: 500 + n for n, scene in enumerate(sb.scenes(old))}
        before = _planned(old, segments=segments)
        after = _next(old, before, new, links={_key(new, "A1"): segments[_key(old, "X2")]})
        a1 = _scene(after, _key(new, "A1"))
        self.assertEqual((a1["lineage"]["match"], a1["statuses"], a1["review"], a1["edit"]),
                         ("segment", ["needs_plan"], ["unverified"], ed.normalize_edit(None)))
        self.assertEqual(sorted((orphan["reason"], orphan["scene_key"], orphan["candidate"]) for orphan in after["orphans"]),
                         [("removed", _key(old, "X3"), None), ("unverified", _key(old, "X2"), _key(new, "A1"))])
        self.assertEqual(_scene(after, _key(new, "P"))["statuses"], ["stale_content", "visual_review"], "X1 rewritten as P")
        self.assertEqual(ed.validate(after, new), [])


class BasisTests(unittest.TestCase):
    """What an edit is worth is judged from its basis - not from what the last re-cut said."""

    def test_a_stale_scene_stays_stale_through_a_later_cut_that_did_not_touch_it(self) -> None:
        first = _cut(["A", "X", "Y"])
        second = _cut(["A", "X", "Y"], words={"X": 8})            # reconcile A: X rewritten
        third = _cut(["A", "X", "Y"], words={"X": 8, "Y": 9})     # reconcile B: only Y rewritten
        after_a = _next(first, _planned(first), second)
        self.assertEqual(_scene(after_a, _key(second, "X"))["status"], "stale_content")
        x_between = next(item for item in rc.lineage(second, third)["scenes"] if item["scene_key"] == _key(third, "X"))
        self.assertEqual(x_between["status"], "unchanged", "the second re-cut, on its own, sees nothing wrong with X")
        after_b = _next(second, after_a, third)
        x, y = _scene(after_b, _key(third, "X")), _scene(after_b, _key(third, "Y"))
        self.assertEqual((x["status"], x["review"]), ("stale_content", ["narration"]), "X's edit is still the one made for its old words")
        self.assertEqual(y["status"], "stale_content")
        self.assertEqual(ed.validate(after_b, third), [])
        # Made again for X: from then on X is judged from its new basis.
        planned = ed.plan_scene(after_b, third, x["scene_key"], _edit("X2", seconds=3.0))
        self.assertEqual(_scene(planned, x["scene_key"])["status"], "ready")
        again = _next(third, planned, third)
        self.assertEqual((_scene(again, x["scene_key"])["status"], _scene(again, y["scene_key"])["status"]), ("ready", "stale_content"))

    def test_accepting_a_retimed_edit_makes_its_times_the_basis(self) -> None:
        first, second = _cut(["A", "X"]), _cut(["A", "X"], words={"X": 8})
        after = _next(first, _planned(first), second)
        key = _key(second, "X")
        accepted = ed.plan_scene(after, second, key)
        item = _scene(accepted, key)
        self.assertEqual((item["status"], item["timing"]["state"], item["basis"]["voice"]["duration_seconds"]), ("ready", "kept", 3.0))
        self.assertEqual(item["edit"], ed.effective_edit(_scene(after, key)))


class DuplicateTests(unittest.TestCase):
    """[X, Y, X]: the two X say the same words; each keeps its own edit through lineage, never by an equal key."""

    def _edits(self, board: dict) -> dict:
        return {_key(board, "X", 1): _edit("x-first"), _key(board, "X", 2): _edit("x-second"), _key(board, "Y"): _edit("y")}

    def _pictures(self, document: dict) -> list[str]:
        return [item["edit"]["visual"].get("visual_path") for item in document["scenes"]]

    def test_an_insertion_before_them_swaps_nothing(self) -> None:
        board = _cut(["X", "Y", "X"])
        document = _next(board, _planned(board, edits=self._edits(board)), _cut(["N", "X", "Y", "X"]))
        self.assertEqual(self._pictures(document), [None, "x-first.png", "y.png", "x-second.png"])

    def test_deleting_the_first_keeps_the_second_its_own(self) -> None:
        board = _cut(["X", "Y", "X"])
        after = _cut(["Y", "X"])
        document = _next(board, _planned(board, edits=self._edits(board)), after)
        self.assertEqual(self._pictures(document), ["y.png", "x-second.png"])
        self.assertEqual([(item["reason"], item["edit"]["visual"]["visual_path"]) for item in document["orphans"]],
                         [("removed", "x-first.png")])
        # The surviving X now carries the deleted first X's scene_key - an equal key would have given it x-first.
        self.assertEqual(_key(after, "X"), _key(board, "X", 1))

    def test_a_move_around_them_swaps_nothing(self) -> None:
        board = _cut(["X", "Y", "X", "Z"])
        edits = {**self._edits(board), _key(board, "Z"): _edit("z")}
        document = _next(board, _planned(board, edits=edits), _cut(["Z", "X", "Y", "X"]))
        self.assertEqual(self._pictures(document), ["z.png", "x-first.png", "y.png", "x-second.png"])


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.board = _cut(["A", "X", "B"])
        self.changed = _cut(["A", "X", "B"], words={"X": 8})
        self.document = _next(self.board, _planned(self.board), self.changed)
        self.x = _key(self.changed, "X")
        self.assertEqual(ed.validate(self.document, self.changed), [])

    def _broken(self, change) -> dict:
        document = copy.deepcopy(self.document)
        change(document)
        return document

    def test_a_stale_scene_said_to_be_ready_is_caught(self) -> None:
        def ready(document: dict) -> None:
            item = _scene(document, self.x)
            item.update(statuses=[], status="ready", ready=True)
        broken = self._broken(ready)
        self.assertIn(f"Cảnh 2 ({self.x}): lớp dựng không còn khớp mà không bị đánh dấu stale", ed.validate(broken))
        self.assertIn(f"Cảnh 2 ({self.x}): trạng thái không khớp basis so với hiện tại", ed.validate(broken, self.changed))

    def test_identity_lineage_and_provenance(self) -> None:
        duplicated = self._broken(lambda document: document["scenes"][2].update(scene_key=document["scenes"][0]["scene_key"]))
        self.assertTrue(any("xuất hiện 2 lần" in error for error in ed.validate(duplicated)))
        twice = self._broken(lambda document: document["scenes"][2]["lineage"].update(
            previous_scene_key=document["scenes"][0]["lineage"]["previous_scene_key"]))
        self.assertTrue(any("được giao cho 2 cảnh mới" in error for error in ed.validate(twice)))
        unexplained = self._broken(lambda document: document["scenes"][0]["lineage"].update(match=None))
        self.assertTrue(any("nhắc cảnh cũ mà không nói nối bằng cách nào" in error for error in ed.validate(unexplained)))
        unsourced = self._broken(lambda document: document["provenance"].update(plan_fingerprint=None))
        self.assertIn("Thiếu nguồn gốc: plan_fingerprint", ed.validate(unsourced))
        self.assertIn("EditDocument không thuộc storyboard này", ed.validate(self.document, self.board))

    def test_an_edit_changed_outside_its_basis_and_inconsistent_timing_are_caught(self) -> None:
        edited = self._broken(lambda document: _scene(document, self.x)["edit"]["layers"]["overlays"][0].update(text="khác"))
        errors = ed.validate(edited)
        self.assertIn(f"Cảnh 2 ({self.x}): lớp dựng đã bị sửa ngoài basis của nó", errors)
        self.assertIn("document_hash không khớp nội dung", errors)
        timing = self._broken(lambda document: _scene(document, self.x)["timing"].update(state="stale"))
        self.assertIn(f"Cảnh 2 ({self.x}): stale_timing không khớp trạng thái thời gian", ed.validate(timing))
        planless = self._broken(lambda document: _scene(document, self.x).update(basis=None))
        self.assertTrue(any("có lớp dựng nhưng không có basis" in error for error in ed.validate(planless)))
        voiceless = self._broken(lambda document: _scene(document, self.x).pop("voice"))
        self.assertIn(f"Cảnh 2 ({self.x}): thiếu giọng hiện tại của cảnh", ed.validate(voiceless, self.changed))


class RefusalTests(unittest.TestCase):
    def test_what_the_engine_refuses(self) -> None:
        board = _cut(["A", "B"])
        document = _planned(board)
        with self.assertRaises(ed.EditDocumentError):
            ed.build({**board, "status": sb.INVALID})
        with self.assertRaises(ed.EditDocumentError, msg="lineage needs the storyboard the previous document was made for"):
            ed.build(_cut(["A", "C"]), previous=document, previous_storyboard=_cut(["A", "C"]))
        with self.assertRaises(ed.EditDocumentError, msg="once there is a document the timeline is not read again"):
            ed.build(board, previous=document, previous_storyboard=board, legacy={_key(board, "A"): {"segment_id": 1, "edit": _edit("a")}})
        with self.assertRaises(ed.EditDocumentError):
            ed.plan_scene(document, _cut(["A", "C"]), _key(board, "A"), _edit("a"))
        with self.assertRaises(ed.EditDocumentError):
            ed.plan_scene(document, board, "sk-none", _edit("a"))
        with self.assertRaises(ed.EditDocumentError, msg="an edit timed past the scene's end is not made for it"):
            ed.plan_scene(document, board, _key(board, "A"), _edit("a", seconds=9.0))


if __name__ == "__main__":
    unittest.main()
