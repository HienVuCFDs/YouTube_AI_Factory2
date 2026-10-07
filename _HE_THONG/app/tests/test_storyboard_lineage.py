"""Bước 5.3 · T0.5 Identity hardening: lineage() and the anchored cut.

    old storyboard → lineage() → new storyboard → (EditDocument later follows it)

A scene is found again after a re-cut by lineage - lines, section, words,
moves, place inside the same section and part - never because two cuts gave
it the same `scene_key` (a content key another scene can carry). And a
re-cut keeps the previous cut's intact scenes: only what changed is cut again,
so editing one line does not cost unrelated scenes their voice and edit.
"""

from __future__ import annotations

import json
import random
import unittest
from unittest import mock

from tests.test_storyboard_engine import KNOWN, PLAN_ROW, _document, _line, _script, _section
from tests.test_storyboard_gate import GATE, _AppCase, _board, _singles  # noqa: F401  (GATE kept for symmetry)
from youtube_monitor import main, storyboard_engine as sb, storyboard_reconcile as rc
from youtube_monitor.graphic_overlays import normalize_graphic_overlays


def _lineage(old_document: dict, new_document: dict) -> dict:
    return rc.lineage(_board(old_document), _board(new_document))


def _row(result: dict) -> list[tuple]:
    return [(item["status"], item["match"], (item["previous_scene_key"] or "")[-6:]) for item in result["scenes"]]


class LineageTests(unittest.TestCase):
    def test_a_repeated_line_is_followed_by_lineage_not_by_an_equal_key(self) -> None:
        old, new = _board(_singles(["X", "Y", "X"])), _board(_singles(["Y", "X"]))
        result = rc.lineage(old, new)
        old_keys = [scene["scene_key"] for scene in sb.scenes(old)]
        survivor = result["scenes"][1]
        # The surviving X now carries the deleted first X's key - and lineage says it is the second X.
        self.assertEqual(survivor["scene_key"], old_keys[0])
        self.assertEqual(survivor["previous_scene_key"], old_keys[2])
        self.assertEqual([item["scene_key"] for item in result["removed"]], [old_keys[0]])

    def test_moved_added_removed(self) -> None:
        moved = _lineage(_singles(["A1", "A2", "A3"]), _singles(["A3", "A1", "A2"]))
        self.assertEqual([(item["status"], item["match"]) for item in moved["scenes"]],
                         [("unchanged", "moved"), ("unchanged", "section"), ("unchanged", "section")])
        added = _lineage(_singles(["A1", "A2"]), _singles(["A1", "N", "A2"]))
        self.assertEqual([item["status"] for item in added["scenes"]], ["unchanged", "added", "unchanged"])
        removed = _lineage(_singles(["A1", "A2", "A3"]), _singles(["A1", "A3"]))
        self.assertEqual((removed["counts"]["removed"], [item["status"] for item in removed["scenes"]]), (1, ["unchanged", "unchanged"]))

    def test_a_split_gives_the_old_scene_to_its_first_piece_and_a_merge_to_its_first_part(self) -> None:
        document = _document([_section(1, [_line("L1", 5), _line("L2", 5)])])
        whole = sb.build(_script(document), PLAN_ROW, known_ids=KNOWN, groups=[["sec-1#0", "sec-1#1"]])
        halves = sb.build(_script(document), PLAN_ROW, known_ids=KNOWN, groups=[["sec-1#0"], ["sec-1#1"]])
        split = rc.lineage(whole, halves)
        self.assertEqual([(item["status"], item["match"]) for item in split["scenes"]], [("modified", "position"), ("added", None)])
        self.assertIn("narration", split["scenes"][0]["changes"])
        merge = rc.lineage(halves, whole)
        self.assertEqual([(item["status"], item["match"]) for item in merge["scenes"]], [("modified", "position")])
        self.assertEqual(merge["counts"]["removed"], 1)

    def test_lineage_never_crosses_a_section_by_place(self) -> None:
        result = _lineage(_singles(["A1", "A2"], ["B1"]), _singles(["A1"], ["C", "B1"]))
        self.assertEqual([item["status"] for item in result["scenes"]], ["unchanged", "added", "unchanged"])

    def test_rows_fill_in_only_an_old_scene_lineage_left_unplaced_and_it_takes_nothing(self) -> None:
        # X1 is rewritten in place as P; X2 and X3 go; a new section A1-A3 comes. Lineage places only P.
        old, new = _board(_singles(["X1", "X2", "X3"])), _board(_singles(["P"], ["A1", "A2", "A3"]))
        result = rc.lineage(old, new)
        old_keys, new_keys = [s["scene_key"] for s in sb.scenes(old)], [s["scene_key"] for s in sb.scenes(new)]
        self.assertEqual([(item["status"], item["match"]) for item in result["scenes"]],
                         [("modified", "position"), ("added", None), ("added", None), ("added", None)])
        self.assertEqual([item["scene_key"] for item in result["removed"]], old_keys[1:])
        links = {new_keys[1]: 501, new_keys[2]: 502, new_keys[3]: 503}
        filled = rc.with_segments(result, links, {501: old_keys[1], 502: old_keys[1], 503: old_keys[2]})
        self.assertEqual([(item["previous_scene_key"], item["previous_index"], item["match"], item["changes"])
                          for item in filled["scenes"][1:]],
                         [(old_keys[1], 2, "segment", ["unverified"]), (None, None, None, []), (old_keys[2], 3, "segment", ["unverified"])],
                         "one old scene never goes to two new ones")
        self.assertEqual(filled["removed"], [])
        # Found through a row only: never a sure match - it takes no picture, layer or timing on its own.
        for item in (filled["scenes"][1], filled["scenes"][3]):
            self.assertEqual(item["inherit"], {"visual": False, "layers": False, "timing": False, "review": ["unverified"]})
        # Never an old scene lineage already placed, nor a key that is not an old scene of this lineage.
        refused = rc.with_segments(result, links, {501: old_keys[0], 502: "sk-elsewhere"})
        self.assertEqual([item["previous_scene_key"] for item in refused["scenes"][1:]], [None, None, None])
        self.assertEqual(rc.with_segments(rc.lineage(None, new), links, {501: old_keys[1]})["scenes"][1]["previous_scene_key"], None,
                         "with no old cut there is no old scene to name")
        # Where lineage did find the scene, the rows do not override it.
        placed = _lineage(_singles(["A1", "A2"]), _singles(["A1", "A2"]))
        again = rc.with_segments(placed, {item["scene_key"]: 900 + n for n, item in enumerate(placed["scenes"])}, {900: "sk-other"})
        self.assertEqual([item["match"] for item in again["scenes"]], [item["match"] for item in placed["scenes"]])

    def test_a_line_said_twice_follows_the_shift_not_an_equal_reference(self) -> None:
        # A line added first shifts every reference: the second X now sits at the first X's old reference.
        result = _lineage(_singles(["T0", "X", "X", "T3"]), _singles(["N", "T0", "X", "X", "T3"]))
        self.assertEqual([(item["previous_index"], item["status"]) for item in result["scenes"]],
                         [(None, "added"), (1, "unchanged"), (2, "unchanged"), (3, "unchanged"), (4, "unchanged")],
                         "each X keeps its own scene - none swapped by a reference that now points at the other")

    def test_an_edited_copy_of_a_repeated_line_keeps_its_own_scene(self) -> None:
        result = _lineage(_singles(["X", "X"]), _singles(["Y", "X"]))
        self.assertEqual([(item["previous_index"], item["match"], item["status"]) for item in result["scenes"]],
                         [(1, "position", "modified"), (2, "lines", "unchanged")])

    def test_a_moved_line_never_hands_its_scene_to_one_saying_other_words(self) -> None:
        # [T0 T1] [T2] [T3]  →  T2 moved between T0 and T1: [T0 T2] [T1] [T3].
        words = {"T0": 6, "T1": 9, "T2": 15, "T3": 15}
        groups = [["sec-1#0", "sec-1#1"], ["sec-1#2"], ["sec-1#3"]]

        def cut(order: list[str]) -> dict:
            board = sb.build(_script(_document([_section(1, [_line(tag, words[tag]) for tag in order], budget=200)])),
                             PLAN_ROW, known_ids=KNOWN, groups=groups)
            self.assertEqual(board["status"], sb.VALID, board["validation"])
            return board

        result = rc.lineage(cut(["T0", "T1", "T2", "T3"]), cut(["T0", "T2", "T1", "T3"]))
        self.assertEqual([(item["previous_index"], item["status"]) for item in result["scenes"]],
                         [(1, "modified"), (None, "added"), (3, "unchanged")],
                         "[T1] says none of [T2]'s words: it is not [T2] said differently")
        self.assertEqual([item["index"] for item in result["removed"]], [2])


class InheritanceTests(unittest.TestCase):
    """A match says which old scene a new one is - not that all it had still fits."""

    def _entry(self, old_document: dict, new_document: dict, index: int, **rows) -> dict:
        from tests.test_storyboard_gate import _plan
        return _plan(old_document, new_document, **rows)["entries"][index]

    def test_unchanged_keeps_everything(self) -> None:
        entry = self._entry(_singles(["A", "B"]), _singles(["A", "B"]), 1)
        self.assertEqual((entry["status"], entry["keep_voice"]), ("unchanged", True))
        self.assertEqual(entry["inherit"], {"visual": True, "layers": True, "timing": True, "review": []})

    def test_new_words_keep_the_picture_but_not_the_layers_or_their_timing(self) -> None:
        entry = self._entry(_singles(["A", "B"]), _singles(["A", "C"]), 1)
        self.assertEqual((entry["status"], entry["match"], entry["keep_voice"]), ("modified", "position", False))
        self.assertEqual(entry["inherit"], {"visual": True, "layers": False, "timing": False, "review": ["narration"]})

    def test_another_speaker_is_never_inherited_blindly(self) -> None:
        entry = self._entry(_singles(["A", "B"]), _singles(["A", "B"], speakers={"B": "khach"}), 1)
        self.assertIn("speaker", entry["changes"])
        self.assertFalse(entry["keep_voice"])
        self.assertEqual(entry["inherit"], {"visual": True, "layers": False, "timing": False, "review": ["speaker"]})

    def test_another_section_keeps_what_fits_the_words_and_asks_for_a_look(self) -> None:
        entry = self._entry(_singles(["A"], ["B"]), _singles(["B", "A"]), 0)
        self.assertEqual((entry["match"], entry["keep_voice"]), ("moved", True))
        self.assertIn("section", entry["changes"])
        self.assertEqual(entry["inherit"], {"visual": True, "layers": True, "timing": True, "review": ["section"]})
        texts = self._entry(_singles(["A"]), _singles(["A"], texts={1: ["Chữ mới"]}), 0)
        self.assertEqual(texts["inherit"], {"visual": True, "layers": False, "timing": True, "review": ["on_screen_text"]},
                         "an overlay may repeat the on-screen text: new text, stale layers")

    def test_only_the_voice_settles_timing_so_two_verdicts_never_disagree(self) -> None:
        # The same storyboard, voiced with settings the project no longer uses: the words are all the same.
        from tests.test_storyboard_gate import _rows
        board = _board(_singles(["A1", "A2"]))
        shots, timeline = _rows(board)
        records = {item["id"]: {"fingerprint": "fp-a", "voice_text": item["voice_text"], "speaker": item["speaker"]}
                   for item in timeline}
        plan = rc.plan(*rc.source_rows(shots, timeline, board, voice_records=records), board, voice_fingerprint="fp-b")
        self.assertEqual([entry["inherit"] for entry in plan["entries"]],
                         [{"visual": True, "layers": True, "timing": False, "review": []}] * 2, "the voice goes: retimed")
        self.assertEqual([item["inherit"] for item in rc.lineage(board, board)["scenes"]],
                         [{"visual": True, "layers": True, "timing": None, "review": []}] * 2,
                         "lineage has no voice to look at: it leaves timing open rather than say it holds")
        self.assertIsNone(rc.inheritance(rc.MATCH_LINES, []).get("timing"))
        self.assertFalse(rc.inheritance(rc.MATCH_POSITION, ["narration"])["timing"], "new words: no voice survives them")

    def test_split_and_merge(self) -> None:
        document = _document([_section(1, [_line("L1", 5), _line("L2", 5)])])
        whole = sb.build(_script(document), PLAN_ROW, known_ids=KNOWN, groups=[["sec-1#0", "sec-1#1"]])
        halves = sb.build(_script(document), PLAN_ROW, known_ids=KNOWN, groups=[["sec-1#0"], ["sec-1#1"]])
        stale = {"visual": True, "layers": False, "timing": False, "review": ["narration"]}
        split = rc.lineage(whole, halves)["scenes"]
        self.assertEqual([item["inherit"] for item in split],
                         [stale, {"visual": False, "layers": False, "timing": False, "review": []}],
                         "the first piece keeps the picture, its old layers are stale; the second piece starts empty")
        merge = rc.lineage(halves, whole)
        self.assertEqual([item["inherit"] for item in merge["scenes"]], [stale])
        self.assertEqual(merge["counts"]["removed"], 1)


def _origin_cut(sections: list[list[tuple[str, int, object]]], previous: dict | None = None) -> dict:
    document = _document([_section(n + 1, [_line(tag, words) for tag, words, _ in lines], budget=10_000)
                          for n, lines in enumerate(sections) if lines])
    board = sb.build(_script(document), PLAN_ROW, known_ids=KNOWN, previous=previous)
    assert board["status"] == sb.VALID, board["validation"]
    return board


def _origins(board: dict, sections: list[list[tuple[str, int, object]]]) -> list[set]:
    flat = [origin for lines in sections for _, _, origin in lines]
    found, at = [], 0
    for scene in sb.scenes(board):
        found.append(set(flat[at:at + len(scene["spoken_lines"])]))
        at += len(scene["spoken_lines"])
    return found


class LineageTruthTests(unittest.TestCase):
    """Lineage checked against where each line really came from - not by counting re-cut scenes."""

    def test_no_voice_or_layer_lands_on_a_scene_saying_other_words(self) -> None:
        rng = random.Random(31)
        for case in range(160):
            kind = ("edit", "delete", "insert", "move")[case % 4]
            origin, sections = 0, []
            for _ in range(rng.randint(1, 3)):
                lines = []
                for _ in range(rng.randint(4, 10)):
                    if case % 3 == 0 and lines and rng.random() < 0.3:
                        tag, words, _ = rng.choice(lines)  # the same line said again
                    else:
                        tag, words = f"T{origin}", rng.randint(6, 22)
                    lines.append((tag, words, origin))
                    origin += 1
                sections.append(lines)
            old = _origin_cut(sections)
            changed = [list(lines) for lines in sections]
            lines = changed[rng.randrange(len(changed))]
            at = rng.randrange(len(lines))
            if kind == "edit":
                tag, words, source = lines[at]
                lines[at] = (tag, max(1, words + rng.choice([-4, -2, 2, 4])), source)
            elif kind == "delete" and len(lines) > 1:
                del lines[at]
            elif kind == "insert":
                lines.insert(at, ("NEW", rng.randint(6, 22), "new"))
            elif kind == "move":
                lines.insert(rng.randrange(len(lines)), lines.pop(at))
            new = _origin_cut(changed, previous=old)
            old_scenes, new_scenes = sb.scenes(old), sb.scenes(new)
            old_from, new_from = _origins(old, sections), _origins(new, changed)
            result = rc.lineage(old, new)
            given = [item["previous_index"] for item in result["scenes"] if item["previous_index"]]
            self.assertEqual(len(given), len(set(given)), f"case {case}: an old scene given twice")
            for item in result["scenes"]:
                if not item["previous_index"]:
                    continue
                before, after = old_scenes[item["previous_index"] - 1], new_scenes[item["index"] - 1]
                same_words = " ".join(before["narration_text"].split()) == " ".join(after["narration_text"].split())
                self.assertTrue(old_from[item["previous_index"] - 1] & new_from[item["index"] - 1]
                                or (same_words and before["section_id"] == after["section_id"]),
                                f"case {case} ({kind}): scene {item['index']} took old scene {item['previous_index']}, "
                                "which shares none of its lines")
                self.assertEqual(item["inherit"]["layers"], same_words and "on_screen_text" not in item["changes"], f"case {case}")
            # Rows that are the old cut's copy, voiced: the reconcile takes the same old scene for each new
            # one, and keeps a voice only where it says exactly the new scene's words.
            from tests.test_storyboard_gate import _rows
            plan = rc.plan(*rc.source_rows(*_rows(old), old), new)
            self.assertEqual([entry["previous_scene_key"] for entry in plan["entries"]],
                             [item["previous_scene_key"] for item in result["scenes"]], f"case {case}")
            for entry, scene in zip(plan["entries"], new_scenes):
                if entry["keep_voice"]:
                    self.assertEqual(" ".join(entry["row"]["narration_text"].split()), " ".join(scene["narration_text"].split()))
            # One policy: what the reconcile and lineage say a scene may take never disagrees - lineage
            # only leaves open what needs the voice to settle.
            for entry, item in zip(plan["entries"], result["scenes"]):
                verdict, said = entry["inherit"], item["inherit"]
                self.assertEqual({key: verdict[key] for key in ("visual", "layers", "review")},
                                 {key: said[key] for key in ("visual", "layers", "review")}, f"case {case}")
                self.assertIn(said["timing"], (verdict["timing"], None), f"case {case}")


# ===========================================================================
# The anchored cut
# ===========================================================================

def _run(words: list[int], tags: list[str] | None = None) -> dict:
    """One section whose lines have these word counts (3 words/s, 5 s scenes: 15 words a scene)."""
    tags = tags or [f"L{n}" for n in range(len(words))]
    return _document([_section(1, [_line(tag, count) for tag, count in zip(tags, words)], budget=400)])


def _cut(document: dict, previous: dict | None = None, plan_row: dict | None = None) -> dict:
    board = sb.build(_script(document), plan_row or PLAN_ROW, known_ids=KNOWN, previous=previous)
    assert board["status"] == sb.VALID, board["validation"]
    return board


def _scenes_as_tags(board: dict) -> list[tuple[str, ...]]:
    return [tuple(line["text"].split()[0] for line in scene["spoken_lines"]) for scene in sb.scenes(board)]


TAGS = ["A1", "A2", "B1", "B2", "C1", "C2", "D1", "D2", "E1", "E2"]


class AnchoredCutTests(unittest.TestCase):
    def setUp(self) -> None:
        # Five scenes of two lines, 15 words each: A | B | C | D | E.
        self.before = _cut(_run([8, 7] * 5, TAGS))
        self.assertEqual(_scenes_as_tags(self.before), [("A1", "A2"), ("B1", "B2"), ("C1", "C2"), ("D1", "D2"), ("E1", "E2")])

    def test_editing_b_recuts_only_b(self) -> None:
        after = _cut(_run([8, 7, 12, 7, 8, 7, 8, 7, 8, 7], TAGS), previous=self.before)
        scenes = _scenes_as_tags(after)
        for kept in (("A1", "A2"), ("C1", "C2"), ("D1", "D2"), ("E1", "E2")):
            self.assertIn(kept, scenes)
        self.assertEqual({key: after["anchoring"][key] for key in ("anchored", "kept_scenes", "recut_lines", "released_scenes")},
                         {"anchored": True, "kept_scenes": 4, "recut_lines": 2, "released_scenes": 0})

    def test_a_change_that_leaves_a_crumb_releases_the_neighbour_it_fits_best(self) -> None:
        # B shrinks to two words: on its own it would be a two-word scene, so one kept neighbour is cut again with it.
        after = _cut(_run([8, 7, 1, 1, 8, 7, 8, 7, 8, 7], TAGS), previous=self.before)
        scenes = _scenes_as_tags(after)
        self.assertNotIn(("B1", "B2"), scenes, "no crumb of a scene")
        self.assertEqual((after["anchoring"]["released_scenes"], after["anchoring"]["kept_scenes"]), (1, 3))
        for kept in (("D1", "D2"), ("E1", "E2")):
            self.assertIn(kept, scenes)
        self.assertTrue(all(sum(len(line["text"].split()) for line in scene["spoken_lines"]) >= sb.MIN_FRAGMENT_FACTOR * 15
                            for scene in sb.scenes(after)))

    def test_heavy_edits_keep_only_what_is_intact(self) -> None:
        after = _cut(_run([8, 7, 3, 20, 2, 18, 11, 4, 8, 7], TAGS), previous=self.before)
        scenes = _scenes_as_tags(after)
        self.assertEqual((scenes[0], scenes[-1]), (("A1", "A2"), ("E1", "E2")))
        self.assertEqual(after["anchoring"]["kept_scenes"], 2)

    def test_a_line_added_inside_a_scene_recuts_that_scene_and_a_deleted_scene_leaves_the_rest(self) -> None:
        inserted = _cut(_run([8, 7, 8, 7, 8, 5, 7, 8, 7, 8, 7], ["A1", "A2", "B1", "B2", "C1", "Cx", "C2", "D1", "D2", "E1", "E2"]),
                        previous=self.before)
        scenes = _scenes_as_tags(inserted)
        for kept in (("A1", "A2"), ("B1", "B2"), ("D1", "D2"), ("E1", "E2")):
            self.assertIn(kept, scenes)
        self.assertNotIn(("C1", "C2"), scenes)
        removed = _cut(_run([8, 7, 8, 7, 8, 7, 8, 7], ["A1", "A2", "C1", "C2", "D1", "D2", "E1", "E2"]), previous=self.before)
        self.assertEqual(_scenes_as_tags(removed), [("A1", "A2"), ("C1", "C2"), ("D1", "D2"), ("E1", "E2")])

    def test_no_anchoring_when_the_cut_itself_would_differ(self) -> None:
        document = _run([8, 7, 12, 7, 8, 7, 8, 7, 8, 7], TAGS)
        shorter = {**PLAN_ROW, "plan": {**PLAN_ROW["plan"], "edit_direction": {"average_shot_length_seconds": 3.0}}}
        self.assertEqual(_cut(document, previous=self.before, plan_row=shorter)["anchoring"]["reason"], "plan_changed")
        faster = _run([8, 7, 12, 7, 8, 7, 8, 7, 8, 7], TAGS)
        faster["speaking_rate"] = {"tokens_per_second": 4.0, "unit": "từ"}
        self.assertEqual(_cut(faster, previous=self.before)["anchoring"]["reason"], "timing_changed")
        self.assertEqual(_cut(document)["anchoring"]["reason"], "no_previous")
        supplied = sb.build(_script(document), PLAN_ROW, known_ids=KNOWN, groups=[[f"sec-1#{n}"] for n in range(10)])
        self.assertEqual(supplied["anchoring"]["reason"], "supplied")

    def test_cutting_the_same_script_again_is_the_same_document(self) -> None:
        again = _cut(_run([8, 7] * 5, TAGS), previous=self.before)
        self.assertEqual((again["document_hash"], again["anchoring"]["kept_scenes"]), (self.before["document_hash"], 5))
        self.assertEqual(sb.document_hash(again), again["document_hash"], "how it was cut is not part of the hash")

    def test_anchors_never_cross_a_section_part_or_speaker(self) -> None:
        old = _cut(_document([_section(1, [_line("A1", 5), _line("A2", 10)]), _section(2, [_line("B1", 8), _line("B2", 7)])]))
        self.assertEqual(_scenes_as_tags(old), [("A1", "A2"), ("B1", "B2")])
        # A2 moves to section 2: A's old scene is no longer one run, so it is cut again; B is intact.
        moved = _document([_section(1, [_line("A1", 5)]), _section(2, [_line("A2", 10), _line("B1", 8), _line("B2", 7)])])
        new = _cut(moved, previous=old)
        self.assertEqual(_scenes_as_tags(new), [("A1",), ("A2",), ("B1", "B2")])
        self.assertEqual(new["anchoring"]["kept_scenes"], 1)
        self.assertEqual(sb.validate(new, moved), [])

    def test_a_one_line_edit_rarely_costs_an_unrelated_scene(self) -> None:
        """A small, fixed-seed slice of the benchmark, kept as a guard."""
        rng = random.Random(5)
        hit = 0
        for _ in range(150):
            words = [rng.randint(4, 14) for _ in range(rng.randint(6, 14))]
            tags = [f"T{n}" for n in range(len(words))]
            old = _cut(_run(words, tags))
            edited = list(words)
            at = rng.randrange(len(words))
            edited[at] = max(1, words[at] + rng.choice([-3, -2, 2, 3]))
            new = _cut(_run(edited, tags), previous=old)
            touched = f"T{at}"
            untouched = [scene for scene in _scenes_as_tags(old) if touched not in scene]
            lost = [scene for scene in untouched if scene not in _scenes_as_tags(new)]
            # Only a released neighbour (a crumb merged into it) may be cut again.
            hit += len(lost) > new["anchoring"]["released_scenes"]
        self.assertEqual(hit, 0)


class AnchoredReconcileAppTests(_AppCase):
    def test_editing_one_line_keeps_every_other_scene_its_rows_and_voice(self) -> None:
        project_id = self._ready()
        before = self._by_section(project_id)
        board = self._gate(project_id)["storyboard"]
        section_two = [scene for scene in sb.scenes(board) if scene["section_id"] == "sec-2"]
        edited_text = section_two[2]["spoken_lines"][0]["text"]
        at = self._first_of_section(project_id, 1)
        # Halve one line of section 2 (fewer words): only its own scene may be cut again.
        self._patch_lines(project_id, lambda lines: lines.__setitem__(
            lines.index(edited_text, at), " ".join(edited_text.split()[:6]).rstrip(".") + "."))
        done = self.client.post(f"/api/projects/{project_id}/shots/generate", json={"force": True}).json()
        self.assertTrue(done["reconcile"]["anchoring"]["anchored"])
        after = self._by_section(project_id)
        for section in ("sec-1", "sec-3"):
            self.assertEqual(after[section], before[section], section)
        untouched = [item for item in before["sec-2"] if edited_text not in item[1]]
        kept = [item for item in after["sec-2"] if item in untouched]
        lost = len(untouched) - len(kept)
        self.assertLessEqual(lost, done["reconcile"]["anchoring"]["released_scenes"],
                             "untouched scenes of the edited section keep their rows and voice")
        record = self.database.get_director_artifact(project_id, "storyboard_reconcile")["payload"]
        self.assertTrue(all(scene.get("new_segment_id") for scene in record["scenes"]), "the record says where each scene landed")
        self.assertEqual(len(record["lineage"]["scenes"]), len(record["scenes"]))


class RecordAppTests(_AppCase):
    """Where each scene landed, read back from the stored reconcile record and checked against the rows themselves."""

    def _rows(self, project_id: int, script_id: int | None = None) -> tuple[dict[int, dict], dict[int, dict]]:
        script_id = script_id or int(self.database.get_latest_project_script(project_id)["id"])
        return ({int(row["id"]): row for row in self.database.list_project_shots(project_id, script_id=script_id)},
                {int(row["id"]): row for row in self._timeline(project_id, script_id)})

    def _records(self, project_id: int) -> int:
        with self.database._connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM project_director_artifacts WHERE project_id = ? AND kind = ?",
                                      (project_id, "storyboard_reconcile")).fetchone()[0]

    def _check(self, project_id: int, before: tuple[dict[int, dict], dict[int, dict]]) -> dict:
        """Each scene's new_shot_id / new_segment_id is the row that now says it, and every row is some scene's."""
        shots_before, segments_before = before
        record = self.database.get_director_artifact(project_id, "storyboard_reconcile")["payload"]
        shots, segments = self._rows(project_id)
        scenes = sb.scenes(self._gate(project_id)["storyboard"])
        self.assertEqual(len(record["scenes"]), len(scenes))
        for scene, item in zip(scenes, record["scenes"]):
            shot, segment = shots[item["new_shot_id"]], segments[item["new_segment_id"]]
            self.assertEqual((item["index"], item["scene_key"]), (scene["index"], scene["scene_key"]))
            self.assertEqual((shot["shot_index"], shot["narration"]), (scene["index"], scene["narration_text"]))
            self.assertEqual((segment["shot_id"], segment["voice_text"]), (shot["id"], scene["narration_text"]))
            if record["mode"] == "in_place" and item["status"] != rc.ADDED:
                self.assertEqual((item["new_shot_id"], item["new_segment_id"]), (item["shot_id"], item["segment_id"]), "same rows")
            elif record["mode"] == "in_place":
                self.assertIsNone(item["shot_id"])
                self.assertNotIn(item["new_shot_id"], shots_before)
                self.assertNotIn(item["new_segment_id"], segments_before)
        self.assertEqual(set(shots), {item["new_shot_id"] for item in record["scenes"]})
        self.assertEqual(set(segments), {item["new_segment_id"] for item in record["scenes"]})
        if record["mode"] == "in_place":
            gone = {item["shot_id"] for item in record["removed"]}
            self.assertFalse(gone & set(shots))
            self.assertTrue(gone <= set(shots_before))
            self.assertEqual(sorted(item["shot"]["id"] for item in record["archived"]), sorted(gone))
        # The record's lineage names the same old scene as the rows taken over.
        self.assertEqual([item["previous_scene_key"] for item in record["scenes"]],
                         [item["previous_scene_key"] for item in record["lineage"]["scenes"]])
        # A voice kept anywhere still says the words it was made for.
        said = {row["audio_path"]: row["voice_text"] for row in segments_before.values() if row["audio_path"]}
        for segment in segments.values():
            if segment["audio_path"] in said:
                self.assertEqual(segment["voice_text"], said[segment["audio_path"]])
        return record

    def test_every_scene_lands_where_the_record_says_in_place(self) -> None:
        project_id = self._ready()
        lines = sb.document_lines(self._script(project_id)["document"])

        def regroup(groups: list[list[int]]) -> dict:
            before = self._rows(project_id)
            shots = [{"narration": " ".join(lines[n]["text"] for n in group)} for group in groups]
            response = self.client.post(f"/api/projects/{project_id}/steps/shots", json={"options": {"shots": shots, "force": True}})
            self.assertEqual(response.status_code, 200, response.text)
            return self._check(project_id, before)

        singles = [[n] for n in range(len(lines))]
        regroup(singles)
        at = next(n for n in range(len(lines) - 1) if lines[n]["role"] == "body"
                  and (lines[n]["section_key"], lines[n]["role"]) == (lines[n + 1]["section_key"], lines[n + 1]["role"]))
        merged = regroup([*singles[:at], [at, at + 1], *singles[at + 2:]])
        self.assertEqual((merged["scenes"][at]["status"], merged["scenes"][at]["match"], merged["counts"]["removed"]),
                         ("modified", "position", 1))
        split = regroup(singles)
        self.assertEqual([split["scenes"][at]["status"], split["scenes"][at + 1]["status"]], ["modified", "added"])

        # Moved, added and removed: the script itself edited.
        script = self._script(project_id)
        body = script["main_content"].split("\n")
        first = self._first_of_section(project_id, 1)
        before = self._rows(project_id)
        body[first], body[first + 1] = body[first + 1], body[first]
        body.insert(first + 3, "Mọi ý chính đều dễ nhớ khi theo dõi.")
        body.pop(-1)
        self.assertEqual(self.client.patch(f"/api/scripts/{script['id']}", json={"main_content": "\n".join(body)}).status_code, 200)
        done = self.client.post(f"/api/projects/{project_id}/shots/generate", json={"force": True}).json()
        record = self._check(project_id, before)
        self.assertEqual(record["counts"], done["reconcile"]["counts"])
        self.assertTrue({"moved", "lines"} & {item["match"] for item in record["scenes"]})
        self.assertGreaterEqual(record["counts"]["added"], 1)
        self.assertGreaterEqual(record["counts"]["removed"], 1)

    def test_a_carried_over_script_records_the_new_rows_and_the_old_ones_stay(self) -> None:
        project_id = self._ready()
        old = self._script(project_id)
        old_rows = self._rows(project_id, int(old["id"]))
        lines = old["main_content"].split("\n")
        at = self._first_of_section(project_id, 1)
        lines[at] = lines[at].replace(" ", " mỗi ", 1).rsplit(" ", 1)[0] + "."
        lines.insert(at + 2, "Mọi ý chính đều dễ nhớ khi theo dõi.")
        main.run_project_step(project_id, "script", {"revision": {"base_script_id": old["id"],
                                                                  "fields": {"main_content": "\n".join(lines)}, "source": "test"}})
        self.client.post(f"/api/projects/{project_id}/shots/generate", json={})
        record = self._check(project_id, ({}, {}))
        self.assertEqual(record["mode"], "carried_over")
        for item in record["scenes"]:
            if item["status"] == rc.ADDED:
                self.assertIsNone(item["segment_id"])
            else:
                self.assertIn(item["shot_id"], old_rows[0], "taken over from the old script's row")
                self.assertIn(item["segment_id"], old_rows[1])
            self.assertNotIn(item["new_shot_id"], old_rows[0])
            self.assertNotIn(item["new_segment_id"], old_rows[1])
        # (The derived `status` is resynced for the whole project; what the rows hold is not touched.)
        data = lambda rows: ({key: (row["shot_index"], row["narration"]) for key, row in rows[0].items()},  # noqa: E731
                             {key: (row["shot_id"], row["voice_text"], row["audio_path"], row["visual_path"], row["overlays"])
                              for key, row in rows[1].items()})
        self.assertEqual(data(self._rows(project_id, int(old["id"]))), data(old_rows), "the old script's rows are untouched")

    def test_a_failed_reconcile_leaves_no_record_and_no_change(self) -> None:
        project_id = self._ready()
        at = self._first_of_section(project_id, 1)
        before, records = self._rows(project_id), self._records(project_id)
        board = self.database.get_latest_project_storyboard(project_id)
        self._patch_lines(project_id, lambda lines: lines.pop(at))
        with mock.patch.object(type(self.database), "_reflow_project_timeline", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                self.client.post(f"/api/projects/{project_id}/shots/generate", json={"force": True})
        self.assertEqual(self._rows(project_id), before, "rows updated, inserted and removed before the failure are all rolled back")
        self.assertEqual(self._records(project_id), records, "no record of a reconcile that did not happen")
        self.assertEqual(self.database.get_latest_project_storyboard(project_id)["id"], board["id"])
        self.assertEqual(self._gate(project_id)["state"], sb.STALE)
        # Once it can, it goes through - and the record matches the rows.
        self.client.post(f"/api/projects/{project_id}/shots/generate", json={"force": True})
        self._check(project_id, before)

    def test_new_words_keep_the_picture_and_retime_what_was_timed_to_the_old_length(self) -> None:
        project_id = self._ready()
        scenes, timeline = sb.scenes(self._gate(project_id)["storyboard"]), self._timeline(project_id)
        target, other = (next(segment for scene, segment in zip(scenes, timeline) if scene["index"] == index) for index in (3, 4))
        length = float(target["duration_seconds"])
        overlays = [{"kind": "text", "text": "Ba lý do", "start_seconds": length - 2.5, "end_seconds": length - 0.5}]
        cues = [{"cue": "whoosh", "start_seconds": length - 1.0, "end_seconds": length - 0.5}]
        for segment in (target, other):
            with self.database._connect() as connection:
                connection.execute("UPDATE project_timeline_segments SET overlays = ?, sound_cues = ? WHERE id = ?",
                                   (json.dumps(overlays), json.dumps(cues), int(segment["id"])))
            self.database.replace_timeline_edit_beats(int(segment["id"]), [
                {"visual_path": segment["visual_path"], "duration_seconds": length / 2},
                {"visual_path": segment["visual_path"], "duration_seconds": length / 2}])
        # The scene's second line cut to three words: the same scene, a shorter one.
        said = next(scene for scene in scenes if scene["index"] == 3)["spoken_lines"][1]["text"]
        start = self._first_of_section(project_id, 1)
        self._patch_lines(project_id, lambda lines: lines.__setitem__(lines.index(said, start), " ".join(said.split()[:3]).rstrip(".") + "."))
        self.client.post(f"/api/projects/{project_id}/shots/generate", json={"force": True})

        after = self.database.get_project_timeline_segment(int(target["id"]))
        shorter = float(after["duration_seconds"])
        self.assertLess(shorter, length)
        self.assertEqual((after["audio_path"], after["visual_path"]), ("", target["visual_path"]), "the voice goes, the picture stays")
        with self.assertRaises(ValueError, msg="as they were, the overlays run past the new end: the render would stop"):
            normalize_graphic_overlays(overlays, shorter)
        retimed = json.loads(after["overlays"])
        self.assertEqual(normalize_graphic_overlays(retimed, shorter)[0]["end_seconds"], round((length - 0.5) * shorter / length, 3))
        self.assertEqual(json.loads(after["sound_cues"])[0]["end_seconds"], round((length - 0.5) * shorter / length, 3))
        beats = self.database.list_timeline_edit_beats(int(target["id"]))
        self.assertAlmostEqual(sum(float(beat["duration_seconds"]) for beat in beats), shorter, places=2)
        self.assertEqual([float(beat["start_seconds"]) for beat in beats], [0.0, round(length / 2 * shorter / length, 3)])

        record = self.database.get_director_artifact(project_id, "storyboard_reconcile")["payload"]
        changed = next(item for item in record["scenes"] if item["new_segment_id"] == int(target["id"]))
        self.assertEqual((changed["status"], changed["inherit"]),
                         ("modified", {"visual": True, "layers": False, "timing": False, "review": ["narration"]}),
                         "matched, but its overlays were made for other words: kept, retimed, and marked stale")
        self.assertEqual((changed["retimed"]["from_seconds"], changed["retimed"]["to_seconds"]), (length, shorter))
        lineage = next(item for item in record["lineage"]["scenes"] if item["scene_key"] == changed["scene_key"])
        self.assertEqual(lineage["inherit"], {"visual": True, "layers": False, "timing": False, "review": ["narration"]})
        # A scene the edit did not touch keeps all it had, untouched.
        untouched = next(item for item in record["scenes"] if item["new_segment_id"] == int(other["id"]))
        self.assertEqual((untouched["status"], untouched["retimed"], untouched["inherit"]),
                         ("unchanged", None, {"visual": True, "layers": True, "timing": True, "review": []}))
        kept = self.database.get_project_timeline_segment(int(other["id"]))
        self.assertEqual((json.loads(kept["overlays"]), json.loads(kept["sound_cues"]), kept["duration_seconds"]),
                         (overlays, cues, other["duration_seconds"]))


if __name__ == "__main__":
    unittest.main()
