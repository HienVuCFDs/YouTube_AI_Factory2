"""Bước 5.1 · Storyboard Engine: ScriptDocument → StoryboardDocument, with provenance and its checks.

    ProjectPlan → ScriptDocument → StoryboardDocument → project_shots (compatibility)

A scene groups whole, consecutive spoken lines of one part (hook, a section's
body, CTA) of one section, read by one speaker, near the plan's scene length.
Nothing is written, changed, dropped or invented; the storyboard names the
script (id, version, fingerprint) and plan (id, version) it was cut from and
is stale when either moves. project_shots is a copy of it.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from tests.script_fixtures import FIXTURE_78, Scripted, planned_project
from tests.test_script_paths import _legacy_project, _snapshot
from youtube_monitor import main, script_engine, storyboard_engine as sb
from youtube_monitor.database import Database

RATE = 3.0  # words per second: a 15-word scene is the plan's 5 seconds
PLAN_ROW = {"id": 16, "version": 5, "plan": {
    "edit_direction": {"average_shot_length_seconds": 5.0},
    "constraints": {"scene_asset_type": "ai_scene"},
    "media_strategy": {"primary_sources": ["graphics"], "supporting_sources": ["ai_media"], "notes": "Sơ đồ là chính"},
}}
KNOWN = {"insight_ids": {"in-1", "in-2"}, "evidence_ids": {"ev-1", "ev-2"}}


def _text(tag: str, words: int) -> str:
    """A line of exactly `words` words, the first one naming it."""
    return " ".join([tag, *(f"chữ{n}" for n in range(1, words))]) + "."


def _line(tag: str, words: int, speaker: str = "narrator") -> dict:
    return {"speaker": speaker, "text": _text(tag, words)}


def _section(n: int, lines: list[dict], *, texts=(), insights=(), evidence=(), budget: int = 120) -> dict:
    return {"id": f"sec-{n}", "plan_section_id": f"s{n}", "name": f"Phần {n}", "purpose": f"Mục đích {n}",
            "budget_seconds": budget, "spoken_lines": lines, "on_screen_text": list(texts), "estimated_seconds": 0,
            "insight_ids": list(insights), "evidence_ids": list(evidence)}


def _document(sections: list[dict], *, hook=(), cta=(), hook_text=(), cta_text=()) -> dict:
    return {
        "engine_version": script_engine.ENGINE_VERSION, "title": "Thử", "language": "vi",
        "speaking_rate": {"tokens_per_second": RATE, "unit": "từ"}, "target_duration_seconds": 120,
        "plan": {"plan_id": 16, "plan_version": 5},
        "hook": {"plan_section_id": "s1", "spoken_lines": list(hook), "on_screen_text": list(hook_text)},
        "sections": sections,
        "cta": {"plan_section_id": f"s{len(sections)}", "spoken_lines": list(cta), "on_screen_text": list(cta_text)},
        "validation": {"ok": True, "errors": [], "checked_at": "2026-10-06T00:00:00+00:00", "source": "engine"},
        "checks": {"plan_alignment": "ok"}, "captured_at": "2026-10-06T00:00:00+00:00", "ai": {"runtime": "fake"},
    }


def _script(document: dict, *, script_id: int = 98, version: int = 1) -> dict:
    return {"id": script_id, "version": version, "variant": "long", "engine_version": script_engine.ENGINE_VERSION,
            "plan_id": 16, "plan_version": 5, "document": document}


def _build(document: dict, plan_row: dict | None = None, **options) -> dict:
    return sb.build(_script(document), plan_row or PLAN_ROW, known_ids=options.pop("known_ids", KNOWN), **options)


def _scenes(storyboard: dict) -> list[dict]:
    return sb.scenes(storyboard)


def _refs(scene: dict) -> list[str]:
    return [line["ref"] for line in scene["spoken_lines"]]


def _standard() -> dict:
    """Three sections, a hook and a CTA, on-screen text and citations."""
    return _document([
        _section(1, [_line("A1", 8), _line("A2", 8)], texts=["Dự thảo"], insights=["in-1"], evidence=["ev-1"], budget=20),
        _section(2, [_line(f"B{n}", 8) for n in range(1, 7)], texts=["Ai tính giá", "Giá gồm gì", "Nhà nước"],
                 insights=["in-1", "in-2"], evidence=["ev-2"], budget=40),
        _section(3, [_line("C1", 6)], budget=20),
    ], hook=[_line("H1", 7)], cta=[_line("K1", 6)], hook_text=["Câu hỏi"], cta_text=["Theo dõi"])


# ===========================================================================
# Cutting the scenes
# ===========================================================================

class SplittingTests(unittest.TestCase):
    def test_1_one_section_gives_one_scene(self) -> None:
        board = _build(_document([_section(1, [_line("A1", 5), _line("A2", 5)])]))
        self.assertEqual(board["status"], sb.VALID, board["validation"])
        self.assertEqual([_refs(scene) for scene in _scenes(board)], [["sec-1#0", "sec-1#1"]])

    def test_2_one_section_gives_many_scenes(self) -> None:
        # Six lines of 8 words (2.67 s each) against a 5 s scene: pairs, 16 words each.
        board = _build(_document([_section(1, [_line(f"A{n}", 8) for n in range(1, 7)])]))
        self.assertEqual([len(scene["spoken_lines"]) for scene in _scenes(board)], [2, 2, 2])
        self.assertEqual(board["status"], sb.VALID)

    def test_3_many_spoken_lines_are_grouped_not_one_per_scene(self) -> None:
        lines = [_line(f"A{n}", 4) for n in range(1, 41)]
        board = _build(_document([_section(1, lines, budget=60)]))
        scenes = _scenes(board)
        self.assertEqual(board["status"], sb.VALID, board["validation"])
        self.assertLess(len(scenes), 40)
        self.assertEqual([ref for scene in scenes for ref in _refs(scene)], [f"sec-1#{n}" for n in range(40)])
        target = board["timing"]["scene_seconds"]
        self.assertTrue(all(scene["estimated_seconds"] <= sb.OVERLONG_FACTOR * target for scene in scenes))

    def test_4_a_line_is_never_split(self) -> None:
        long_line = _line("DÀI", 90)
        board = _build(_document([_section(1, [_line("A1", 5), long_line, _line("A3", 5)], budget=60)]))
        scenes = _scenes(board)
        self.assertEqual(board["status"], sb.VALID, board["validation"])
        alone = next(scene for scene in scenes if "sec-1#1" in _refs(scene))
        self.assertEqual((_refs(alone), alone["narration_text"]), (["sec-1#1"], long_line["text"]))
        for scene in scenes:
            self.assertEqual(scene["narration_text"], " ".join(line["text"] for line in scene["spoken_lines"]))

    def test_5_two_sections_never_share_a_scene(self) -> None:
        document = _document([_section(1, [_line("A1", 3)]), _section(2, [_line("B1", 3)])])
        board = _build(document)
        self.assertEqual([_refs(scene) for scene in _scenes(board)], [["sec-1#0"], ["sec-2#0"]])
        merged = _build(document, groups=[["sec-1#0", "sec-2#0"]])
        self.assertEqual(merged["status"], sb.INVALID)
        self.assertTrue(any("gộp lời của nhiều phần" in error for error in merged["validation"]["errors"]))

    def test_the_hook_and_the_cta_are_scenes_of_their_own_in_the_first_and_last_section(self) -> None:
        board = _build(_standard())
        first, last = board["sections"][0]["scenes"], board["sections"][-1]["scenes"]
        self.assertEqual((first[0]["role"], _refs(first[0])), ("hook", ["hook#0"]))
        self.assertEqual((last[-1]["role"], _refs(last[-1])), ("cta", ["cta#0"]))
        self.assertTrue(all(scene["role"] == "body" for scene in board["sections"][1]["scenes"]))
        self.assertEqual([shot["section"] for shot in sb.to_shots(board)][0::len(sb.to_shots(board)) - 1], ["hook", "cta"])

    def test_24_a_scene_has_one_speaker(self) -> None:
        lines = [_line("N1", 3), _line("B1", 3, "Ông Ba"), _line("B2", 3, "Ông Ba"), _line("N2", 3)]
        document = _document([_section(1, lines)])
        board = _build(document)
        self.assertEqual([(scene["speaker"], _refs(scene)) for scene in _scenes(board)],
                         [("narrator", ["sec-1#0"]), ("Ông Ba", ["sec-1#1", "sec-1#2"]), ("narrator", ["sec-1#3"])])
        self.assertEqual([shot["speaker"] for shot in sb.to_shots(board)], ["narrator", "Ông Ba", "narrator"])
        mixed = _build(document, groups=[["sec-1#0", "sec-1#1"], ["sec-1#2", "sec-1#3"]])
        self.assertTrue(any("nhiều người nói" in error for error in mixed["validation"]["errors"]))

    def test_22_the_same_script_and_plan_give_the_same_storyboard(self) -> None:
        first, second = _build(_standard()), _build(copy.deepcopy(_standard()))
        self.assertEqual(sb.canonical_json(first), sb.canonical_json(second))
        self.assertEqual(first["document_hash"], second["document_hash"])

    def test_23_edge_sections(self) -> None:
        # A section with nothing to say has no scene: the storyboard says so and is not usable.
        empty = _build(_document([_section(1, [_line("A1", 4)]), _section(2, [])]))
        self.assertEqual(empty["status"], sb.INVALID)
        self.assertIn("[s2] không có lời nói nên không có cảnh nào", empty["validation"]["errors"])
        # No section at all.
        nothing = _build(_document([]))
        self.assertEqual(nothing["status"], sb.INVALID)
        # A blank line is not a line; one word is.
        tiny = _build(_document([_section(1, [{"speaker": "narrator", "text": "   "}, _line("A", 1)])]))
        self.assertEqual((tiny["status"], [_refs(scene) for scene in _scenes(tiny)]), (sb.VALID, [["sec-1#1"]]))
        # A hook with on-screen text but no line hands it to the section's first scene.
        hookless = _build(_document([_section(1, [_line("A1", 4)])], hook_text=["Nhãn mở đầu"]))
        self.assertEqual((hookless["status"], _scenes(hookless)[0]["on_screen_text"]), (sb.VALID, ["Nhãn mở đầu"]))
        # An agent's own draft: one block, no plan section ids.
        draft = _document([{**_section(1, [_line("A1", 5)]), "plan_section_id": None}])
        draft["hook"]["plan_section_id"] = draft["cta"]["plan_section_id"] = None
        self.assertEqual(_build(draft)["status"], sb.VALID)
        # A script without a ScriptDocument is not cut here.
        with self.assertRaises(sb.StoryboardError):
            sb.build({"id": 1, "version": 1, "variant": "long", "document_json": ""}, PLAN_ROW)


# ===========================================================================
# What the scenes carry
# ===========================================================================

class ContentTests(unittest.TestCase):
    def test_9_on_screen_text_is_the_scripts_spread_over_its_scenes(self) -> None:
        board = _build(_standard())
        body = board["sections"][1]["scenes"]
        self.assertEqual(len(body), 3)
        self.assertEqual([scene["on_screen_text"] for scene in body], [["Ai tính giá"], ["Giá gồm gì"], ["Nhà nước"]])
        self.assertEqual(board["sections"][0]["scenes"][0]["on_screen_text"], ["Câu hỏi"])
        self.assertEqual(board["sections"][-1]["scenes"][-1]["on_screen_text"], ["Theo dõi"])
        invented = copy.deepcopy(board)
        invented["sections"][1]["scenes"][0]["on_screen_text"].append("Giá tăng mạnh")
        self.assertTrue(any("chữ trên màn hình khác kịch bản" in error for error in sb.validate(invented, _standard())))
        dropped = copy.deepcopy(board)
        dropped["sections"][1]["scenes"][2]["on_screen_text"] = []
        self.assertTrue(any("thiếu" in error for error in sb.validate(dropped, _standard())))

    def test_10_and_11_insight_and_evidence_ids_come_down_from_their_section(self) -> None:
        board = _build(_standard())
        for scene in board["sections"][1]["scenes"]:
            self.assertEqual((scene["insight_ids"], scene["evidence_ids"]), (["in-1", "in-2"], ["ev-2"]))
        hook = board["sections"][0]["scenes"][0]
        self.assertEqual((hook["insight_ids"], hook["evidence_ids"]), ([], []), "the script cites none for the hook")
        for key, value in (("insight_ids", "in-9"), ("evidence_ids", "ev-9")):
            tampered = copy.deepcopy(board)
            tampered["sections"][1]["scenes"][0][key].append(value)
            self.assertTrue(any("không có ở phần này" in error for error in sb.validate(tampered, _standard())), key)

    def test_20_and_21_an_id_that_does_not_exist_makes_it_invalid(self) -> None:
        for key, value in (("evidence_ids", "ev-không-có"), ("insight_ids", "in-không-có")):
            document = _standard()
            document["sections"][1][key].append(value)
            board = sb.build(_script(document), PLAN_ROW, known_ids=KNOWN)
            self.assertEqual(board["status"], sb.INVALID, key)
            self.assertTrue(any("không tồn tại" in error and value in error for error in board["validation"]["errors"]), key)

    def test_12_timing_comes_from_the_scripts_rate_and_the_plans_scene_length(self) -> None:
        board = _build(_standard())
        self.assertEqual((board["timing"]["scene_seconds"], board["timing"]["scene_seconds_from"]), (5.0, "plan"))
        for scene in _scenes(board):
            words = sum(len(line["text"].split()) for line in scene["spoken_lines"])
            self.assertAlmostEqual(scene["estimated_seconds"], words / RATE, places=2)
        for section in board["sections"]:
            self.assertAlmostEqual(section["estimated_seconds"], sum(scene["estimated_seconds"] for scene in section["scenes"]), places=2)
        # The plan says nothing - the default; a figure out of range is held inside it.
        self.assertEqual(sb.scene_seconds({}), (sb.DEFAULT_SCENE_SECONDS, "default"))
        self.assertEqual(sb.scene_seconds({"edit_direction": {"average_shot_length_seconds": 0.5}})[0], sb.MIN_SCENE_SECONDS)
        self.assertEqual(sb.scene_seconds({"edit_direction": {"average_shot_length_seconds": 99}})[0], sb.MAX_SCENE_SECONDS)
        # A wrong time, a scene swollen past twice the scene length, a section far past its budget.
        tampered = copy.deepcopy(board)
        tampered["sections"][1]["scenes"][0]["estimated_seconds"] = 1
        self.assertTrue(any("không khớp số chữ" in error for error in sb.validate(tampered, _standard())))
        swollen = _build(_standard(), groups=[["hook#0"], ["sec-1#0", "sec-1#1"], [f"sec-2#{n}" for n in range(6)],
                                              ["sec-3#0"], ["cta#0"]])
        self.assertTrue(any("quá 2 lần độ dài cảnh" in error for error in swollen["validation"]["errors"]))
        over = _document([_section(1, [_line(f"A{n}", 15) for n in range(1, 9)], budget=10)])
        self.assertTrue(any("kế hoạch dành 10 giây" in error for error in _build(over)["validation"]["errors"]))
        self.assertTrue(any("độ dài cảnh của kế hoạch" in error for error in sb.validate(board, _standard(), plan={})))

    def test_visual_intent_is_the_plans_and_no_picture_is_planned_here(self) -> None:
        board = _build(_standard())
        self.assertEqual(board["visual_strategy"], {"primary_sources": ["graphics"], "supporting_sources": ["ai_media"],
                                                    "notes": "Sơ đồ là chính"})
        scene = board["sections"][1]["scenes"][0]
        self.assertEqual(scene["visual_intent"], {"role": "body", "section_name": "Phần 2", "section_purpose": "Mục đích 2",
                                                  "asset_type": "ai_scene"})
        text = sb.canonical_json(board).lower()
        for word in ("visual_prompt", "camera", "transition", "b-roll"):
            self.assertNotIn(word, text)
        shots = sb.to_shots(board)
        self.assertEqual({shot["visual_prompt"] for shot in shots}, {""})
        self.assertEqual({shot["asset_type"] for shot in shots}, {"ai_scene"})
        self.assertEqual([shot["narration"] for shot in shots], [scene["narration_text"] for scene in _scenes(board)])
        self.assertEqual([shot["shot_index"] for shot in shots], list(range(1, len(shots) + 1)))


# ===========================================================================
# The checks against a storyboard that was tampered with
# ===========================================================================

class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = _standard()
        self.board = _build(self.document)
        self.assertEqual(self.board["status"], sb.VALID, self.board["validation"])
        self.assertEqual(sb.validate(self.board, self.document, known_ids=KNOWN, plan=PLAN_ROW["plan"]), [])

    def _errors(self, change) -> list[str]:
        tampered = copy.deepcopy(self.board)
        change(tampered)
        return sb.validate(tampered, self.document)

    def test_6_every_line_exactly_once(self) -> None:
        body = lambda board: board["sections"][1]["scenes"]  # noqa: E731
        self.assertTrue(any("Thiếu 1 dòng" in error for error in self._errors(lambda b: body(b)[0]["spoken_lines"].pop())))
        self.assertTrue(any("xuất hiện nhiều lần" in error for error in self._errors(
            lambda b: body(b)[1]["spoken_lines"].insert(0, dict(body(b)[0]["spoken_lines"][-1])))))
        self.assertTrue(any("không thuộc kịch bản" in error for error in self._errors(
            lambda b: body(b)[0]["spoken_lines"].append({"ref": "sec-2#99", "speaker": "narrator", "text": "Lời thêm."}))))

    def test_7_the_order_is_the_scripts(self) -> None:
        def swap(board):
            scenes = board["sections"][1]["scenes"]
            scenes[0]["spoken_lines"], scenes[1]["spoken_lines"] = scenes[1]["spoken_lines"], scenes[0]["spoken_lines"]
        self.assertIn("Thứ tự lời khác thứ tự trong kịch bản", self._errors(swap))

    def test_words_and_speakers_are_the_scripts(self) -> None:
        line = lambda board: board["sections"][1]["scenes"][0]["spoken_lines"][0]  # noqa: E731
        self.assertTrue(any("khác kịch bản" in error for error in self._errors(lambda b: line(b).update(text="Lời đã sửa."))))
        self.assertTrue(any("Người nói" in error for error in self._errors(lambda b: line(b).update(speaker="Ông Ba"))))
        self.assertTrue(any("lời đọc khác" in error for error in self._errors(
            lambda b: b["sections"][1]["scenes"][0].update(narration_text="Một câu khác."))))

    def test_8_the_scene_speaker_is_its_lines(self) -> None:
        self.assertTrue(any("người nói" in error for error in self._errors(
            lambda b: b["sections"][1]["scenes"][0].update(speaker="Ông Ba"))))

    def test_a_scene_in_the_wrong_section_or_role(self) -> None:
        def move(board):
            board["sections"][2]["scenes"].insert(0, board["sections"][1]["scenes"].pop())
        self.assertTrue(any("nằm ở phần sec-3" in error for error in self._errors(move)))
        self.assertTrue(any("vai trò" in error for error in self._errors(lambda b: b["sections"][1]["scenes"][0].update(role="hook"))))


# ===========================================================================
# Provenance, fingerprint, hash, whether a stored storyboard is current
# ===========================================================================

class ProvenanceTests(unittest.TestCase):
    def test_13_14_17_it_names_its_script_plan_and_engine(self) -> None:
        board = _build(_standard())
        self.assertEqual({key: board[key] for key in ("script_id", "script_version", "plan_id", "plan_version", "engine_version")},
                         {"script_id": 98, "script_version": 1, "plan_id": 16, "plan_version": 5,
                          "engine_version": "storyboard-phase4"})
        self.assertEqual(board["script_fingerprint"], sb.script_fingerprint(_standard()))
        for key in ("script_id", "plan_version", "script_fingerprint"):
            missing = copy.deepcopy(board)
            missing[key] = None
            self.assertTrue(any(key in error for error in sb.validate(missing, _standard())), key)

    def test_15_the_fingerprint_follows_the_content_not_the_bookkeeping(self) -> None:
        document = _standard()
        rechecked = copy.deepcopy(document)
        rechecked.update(validation={"ok": True, "errors": [], "checked_at": "2027-01-01T00:00:00+00:00", "source": "edit"},
                         revisions=[{"source": "edit"}], captured_at="2027-01-01T00:00:00+00:00", ai={"runtime": "other"})
        self.assertEqual(sb.script_fingerprint(document), sb.script_fingerprint(rechecked))
        reworded = copy.deepcopy(document)
        reworded["sections"][1]["spoken_lines"][0]["text"] = reworded["sections"][1]["spoken_lines"][0]["text"].replace("chữ1", "chữ một")
        relabelled = copy.deepcopy(document)
        relabelled["sections"][1]["on_screen_text"][0] = "Nhãn khác"
        for changed in (reworded, relabelled):
            self.assertNotEqual(sb.script_fingerprint(document), sb.script_fingerprint(changed))

    def test_16_the_document_hash_covers_the_storyboard_and_only_it(self) -> None:
        board = _build(_standard())
        self.assertEqual(board["document_hash"], sb.document_hash(board))
        self.assertEqual(sb.document_hash({**board, "status": "x", "validation": {}}), board["document_hash"])
        moved = copy.deepcopy(board)
        moved["sections"][1]["scenes"][0]["on_screen_text"] = []
        self.assertNotEqual(sb.document_hash(moved), board["document_hash"])

    def _row(self, board: dict, **changes) -> dict:
        row = {"id": 1, "script_id": board["script_id"], "script_version": board["script_version"],
               "script_fingerprint": board["script_fingerprint"], "plan_id": board["plan_id"], "plan_version": board["plan_version"],
               "document_hash": board["document_hash"], "engine_version": board["engine_version"], "status": board["status"],
               "document_json": json.dumps(board, ensure_ascii=False)}
        return {**row, **changes}

    def test_18_19_whether_a_stored_storyboard_is_current(self) -> None:
        document = _standard()
        board = _build(document)
        current = {**_script(document), "state": script_engine.COMPLETED}
        self.assertEqual(sb.state(self._row(board), current, PLAN_ROW)["state"], sb.CURRENT)
        self.assertEqual(sb.state(None, current, PLAN_ROW)["state"], sb.MISSING)
        # 18. Edited in place: same id, same version, other words.
        edited = copy.deepcopy(document)
        edited["sections"][0]["spoken_lines"][0]["text"] = "Lời mở đã sửa tại chỗ."
        status = sb.state(self._row(board), {**current, "document": edited}, PLAN_ROW)
        self.assertEqual((status["state"], status["reasons"]), (sb.STALE, ["Kịch bản đã được sửa sau khi chia cảnh"]))
        # 19. The plan moved on, or the script did.
        self.assertEqual(sb.state(self._row(board), current, {**PLAN_ROW, "version": 6})["state"], sb.STALE)
        self.assertEqual(sb.state(self._row(board), {**current, "id": 99}, PLAN_ROW)["state"], sb.STALE)
        self.assertEqual(sb.state(self._row(board), {**current, "version": 2}, PLAN_ROW)["state"], sb.STALE)
        self.assertEqual(sb.state(self._row(board), {**current, "state": script_engine.INVALID}, PLAN_ROW)["state"], sb.STALE)
        # A stored document that no longer matches its own hash, or one that failed its checks.
        tampered = copy.deepcopy(board)
        tampered["sections"][1]["scenes"][0]["narration_text"] = "Lời lén sửa."
        self.assertEqual(sb.state(self._row(board, document_json=json.dumps(tampered, ensure_ascii=False)), current, PLAN_ROW)["state"],
                         sb.INVALID)
        self.assertEqual(sb.state(self._row(board, status=sb.INVALID), current, PLAN_ROW)["state"], sb.INVALID)


# ===========================================================================
# An agent's own scene list
# ===========================================================================

class SuppliedGroupingTests(unittest.TestCase):
    def test_25_an_agents_list_is_only_a_grouping_of_the_scripts_words(self) -> None:
        document = _standard()
        lines = sb.document_lines(document)
        # One line per scene, whitespace aside: accepted, and checked like the engine's own cut.
        groups = sb.grouping_from_shots(document, [{"shot_index": n, "narration": "  " + line["text"].replace(" ", "  ")}
                                                   for n, line in enumerate(lines, start=1)])
        board = _build(document, groups=groups)
        self.assertEqual((board["status"], board["grouping"], len(_scenes(board))), (sb.VALID, "supplied", len(lines)))
        # Out of order by list position, in order by shot_index.
        backwards = [{"shot_index": n, "narration": line["text"]} for n, line in reversed(list(enumerate(lines, start=1)))]
        self.assertEqual(sb.grouping_from_shots(document, backwards), groups)
        # A word changed, a line dropped at the end, a line added, an empty scene: refused.
        cases = {
            "changed": [{"narration": lines[0]["text"].replace("H1", "H9")}],
            "dropped": [{"narration": line["text"]} for line in lines[:-1]],
            "added": [{"narration": line["text"]} for line in lines] + [{"narration": "Lời thêm."}],
            "empty": [{"narration": ""}],
        }
        for name, shots in cases.items():
            with self.assertRaises(sb.StoryboardError, msg=name):
                sb.grouping_from_shots(document, shots)
        # Joining the end of one section to the start of the next maps, but fails the checks.
        across = [{"narration": lines[0]["text"]}, {"narration": lines[1]["text"]},
                  {"narration": f"{lines[2]['text']} {lines[3]['text']}"}, *({"narration": line["text"]} for line in lines[4:])]
        board = _build(document, groups=sb.grouping_from_shots(document, across))
        self.assertEqual(board["status"], sb.INVALID)


# ===========================================================================
# The table
# ===========================================================================

class DatabaseTests(unittest.TestCase):
    def test_project_storyboards_is_added_and_nothing_else_moves(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder) / "t.db")
            with database._connect() as connection:
                columns = [row["name"] for row in connection.execute("PRAGMA table_info(project_storyboards)")]
                shots = [row["name"] for row in connection.execute("PRAGMA table_info(project_shots)")]
            self.assertEqual(columns, ["id", "project_id", "script_id", "script_version", "script_fingerprint", "plan_id",
                                       "plan_version", "document_hash", "engine_version", "status", "document_json",
                                       "created_at", "updated_at"])
            self.assertNotIn("scene_json", shots)
            Database(Path(folder) / "t.db")  # a second start changes nothing and does not fail

    def test_a_cut_is_kept_once(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder) / "t.db")
            project = database.create_idea_project("x", title="x")
            script = database.create_project_script(int(project["id"]), script_title="x", main_content="x")
            board = sb.build({**_script(_standard()), "id": script["id"], "version": script["version"]}, PLAN_ROW, known_ids=KNOWN)
            first = database.save_project_storyboard(int(project["id"]), int(script["id"]), board)
            again = database.save_project_storyboard(int(project["id"]), int(script["id"]), board)
            self.assertEqual(first["id"], again["id"])
            self.assertEqual(len(database.list_project_storyboards(int(project["id"]))), 1)
            self.assertEqual(sb.decode(first), json.loads(json.dumps(board, ensure_ascii=False)))
            self.assertIsNone(database.save_project_storyboard(int(project["id"]) + 999, int(script["id"]), board))


# ===========================================================================
# Through the app: the plan workflow is cut here, the legacy one is not
# ===========================================================================

class _AppCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._client_cm = TestClient(main.app)
        cls.client = cls._client_cm.__enter__()
        cls.database = main.database

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)

    def setUp(self) -> None:
        self.model = Scripted()
        for target, name, value in ((main, "_call_orchestrator_json", self.model),
                                    (main.production_worker, "enqueue", mock.Mock(return_value={"id": 1, "status": "queued"}))):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _project_78(self) -> int:
        """Project 78 at plan v5 (four earlier versions, then the fixture's)."""
        older = {**FIXTURE_78["plan"], "target_duration_seconds": 90}
        return planned_project(self.database, kind="article", plan=FIXTURE_78["plan"], insight=FIXTURE_78["insight"],
                               analysis=FIXTURE_78["analysis"], earlier_plans=[older] * 4, title=FIXTURE_78["video"]["title"])

    def _write(self, project_id: int) -> dict:
        response = self.client.post(f"/api/projects/{project_id}/script/generate", json={"options": {}})
        self.assertEqual(response.status_code, 200, response.text)
        return self.client.get(f"/api/projects/{project_id}/script").json()

    def _cut(self, project_id: int, **body) -> dict:
        response = self.client.post(f"/api/projects/{project_id}/shots/generate", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _storyboard(self, project_id: int) -> dict:
        return self.client.get(f"/api/projects/{project_id}/storyboard").json()

    def _bump_plan(self, project_id: int) -> dict:
        latest = self.database.get_latest_project_plan(project_id)
        return self.database.create_project_plan(
            project_id, status="completed", research_report_id=latest["research_report_id"],
            analysis_created_at=latest["analysis_created_at"], engine_version="plan-phase3", plan=latest["plan"],
            feasibility={"status": "ok", "checks": []}, insight_report_id=latest["insight_report_id"])


class AppTests(_AppCase):
    def test_project_78_is_cut_from_its_script_document(self) -> None:
        project_id = self._project_78()
        script = self._write(project_id)
        cut = self._cut(project_id)
        body = self._storyboard(project_id)
        board = body["storyboard"]
        self.assertEqual((body["state"], body["current"], cut["storyboard"]["document_hash"]), ("current", True, board["document_hash"]))
        self.assertEqual((board["script_id"], board["script_version"], board["plan_version"]), (script["id"], script["version"], 5))
        self.assertEqual((board["timing"]["scene_seconds"], board["timing"]["scene_seconds_from"]), (5.0, "plan"))
        self.assertEqual([item["plan_section_id"] for item in board["sections"]], ["s1", "s2", "s3", "s4", "s5"])
        self.assertTrue(all(item["scenes"] for item in board["sections"]))
        lines = [line["text"] for line in sb.document_lines(script["document"])]
        self.assertEqual([line["text"] for scene in sb.scenes(board) for line in scene["spoken_lines"]], lines)
        known = sb.known_ids(self.database, self.database.get_latest_project_plan(project_id))
        cited = {value for scene in sb.scenes(board) for value in scene["insight_ids"] + scene["evidence_ids"]}
        self.assertTrue(cited <= known["insight_ids"] | known["evidence_ids"])
        shots = cut["shots"]
        self.assertEqual([shot["narration"] for shot in shots], [scene["narration_text"] for scene in sb.scenes(board)])
        self.assertEqual({shot["visual_prompt"] for shot in shots}, {""})

    def test_cutting_again_keeps_what_is_there(self) -> None:
        project_id = self._project_78()
        self._write(project_id)
        first = self._cut(project_id)
        for force in (False, True):
            again = self._cut(project_id, force=force)
            self.assertEqual([shot["id"] for shot in again["shots"]], [shot["id"] for shot in first["shots"]], force)
        self.assertEqual(len(self.database.list_project_storyboards(project_id)), 1)

    def test_18_an_in_place_edit_of_the_script_stales_the_storyboard(self) -> None:
        project_id = self._project_78()
        script = self._write(project_id)
        self._cut(project_id)
        patched = self.client.patch(f"/api/scripts/{script['id']}", json={
            "main_content": script["main_content"].replace("từng", "mỗi", 1)})
        self.assertEqual((patched.status_code, patched.json()["state"]), (200, "completed"), patched.text)
        after = self.client.get(f"/api/projects/{project_id}/script").json()
        self.assertEqual((after["id"], after["version"]), (script["id"], script["version"]), "same id and version")
        body = self._storyboard(project_id)
        self.assertEqual((body["state"], body["reasons"]), ("stale", ["Kịch bản đã được sửa sau khi chia cảnh"]))
        # Bước 5.2: nothing voiced yet, so re-cutting loses nothing and is applied - scene by scene.
        cut = self._cut(project_id)
        self.assertEqual((cut["status"], cut["reconcile"]["applied"], cut["reconcile"]["counts"]["modified"]), ("saved", True, 1))
        self.assertEqual(self._storyboard(project_id)["state"], "current")

    def test_19_a_new_plan_version_stales_the_storyboard(self) -> None:
        project_id = self._project_78()
        self._write(project_id)
        self._cut(project_id)
        self._bump_plan(project_id)
        body = self._storyboard(project_id)
        self.assertEqual(body["state"], "stale")
        self.assertTrue(any("Kế hoạch đã đổi" in reason for reason in body["reasons"]))
        script = self._write(project_id)
        body = self._storyboard(project_id)
        self.assertEqual(body["state"], "stale", "the old script's cut is not the new script's")
        self._cut(project_id)
        body = self._storyboard(project_id)
        self.assertEqual((body["state"], body["plan_version"], body["script_id"]), ("current", 6, script["id"]))

    def test_25_no_door_puts_other_words_into_a_planned_projects_scenes(self) -> None:
        project_id = self._project_78()
        script = self._write(project_id)
        cut = self._cut(project_id)
        shots = cut["shots"]
        lines = [line["text"] for line in sb.document_lines(script["document"])]
        steps = lambda options: self.client.post(f"/api/projects/{project_id}/steps/shots", json={"options": options})  # noqa: E731
        changed = [{**shot, "narration": shot["narration"].replace(".", " thêm.", 1) if index == 0 else shot["narration"]}
                   for index, shot in enumerate(shots)]
        for force in (False, True):
            refused = steps({"shots": changed, "force": force})
            self.assertEqual(refused.status_code, 409, force)
        # Grouped another way, word for word: accepted, and kept as the storyboard.
        accepted = steps({"shots": [{"shot_index": n, "narration": text} for n, text in enumerate(lines, start=1)]})
        self.assertEqual(accepted.status_code, 200, accepted.text)
        board = self._storyboard(project_id)["storyboard"]
        self.assertEqual((board["grouping"], board["scene_count"]), ("supplied", len(lines)))
        # A timeline that says something else.
        segments = [{"segment_index": n, "voice_text": text, "duration_seconds": 3} for n, text in enumerate(lines, start=1)]
        bad = [dict(item) for item in segments]
        bad[0]["voice_text"] = "Lời khác."
        self.assertEqual(self.client.post(f"/api/projects/{project_id}/steps/timeline",
                                          json={"options": {"segments": bad, "force": True}}).status_code, 409)
        good = self.client.post(f"/api/projects/{project_id}/steps/timeline", json={"options": {"segments": segments, "force": True}})
        self.assertEqual(good.status_code, 200, good.text)
        # The shot routes: no rewording, no adding, copying, removing or reordering.
        shot = self.database.list_project_shots(project_id, script_id=int(script["id"]))[0]
        reworded = self.client.patch(f"/api/shots/{shot['id']}", json={"narration": "Lời khác."})
        self.assertEqual((reworded.status_code, reworded.json()["detail"]), (409, sb.NARRATION_LOCKED))
        same = self.client.patch(f"/api/shots/{shot['id']}", json={"narration": shot["narration"], "duration_seconds": 9})
        self.assertEqual(same.status_code, 200, same.text)
        ids = [item["id"] for item in self.database.list_project_shots(project_id, script_id=int(script["id"]))]
        for response in (
            self.client.post(f"/api/projects/{project_id}/shots", json={"narration": "Cảnh thêm."}),
            self.client.post(f"/api/shots/{shot['id']}/duplicate"),
            self.client.delete(f"/api/shots/{shot['id']}"),
            self.client.post(f"/api/projects/{project_id}/shots/reorder", json={"shot_ids": list(reversed(ids))}),
        ):
            self.assertEqual((response.status_code, response.json()["detail"]), (409, sb.STRUCTURE_LOCKED))
        self.assertEqual([item["narration"] for item in self.database.list_project_shots(project_id, script_id=int(script["id"]))], lines)

    def test_reup_cut_by_dialogue_stays_a_mode_of_its_own(self) -> None:
        turns = [{"order": 1, "speaker": "Người dẫn", "line": "Ngày xưa có hai anh em.", "start_seconds": 0, "end_seconds": 5},
                 {"order": 2, "speaker": "Cha", "line": "Các con phải thương nhau.", "start_seconds": 5, "end_seconds": 9}]
        project_id = planned_project(self.database, analysis={
            "topic": "Hai anh em", "content_summary": "Chuyện hai anh em.", "dialogue": turns, "language": "vi", "limitations": []})
        script = self._write(project_id)
        self._cut(project_id)
        storyboards = self.database.list_project_storyboards(project_id)
        reup = self.client.post(f"/api/projects/{project_id}/timeline/from-dialogue")
        self.assertEqual(reup.status_code, 200, reup.text)
        self.assertEqual(self.database.list_project_storyboards(project_id), storyboards, "it writes no storyboard")
        body = self._storyboard(project_id)
        self.assertEqual((body["state"], body["storyboard_state"], body["shots_in_sync"], body["mode"], body["blocked"]),
                         ("not_applicable", "out_of_sync", False, "reup", ""))
        # Its shots say the source's words and are edited as they always were.
        shot = self.database.list_project_shots(project_id, script_id=int(script["id"]))[0]
        self.assertEqual(shot["narration"], "Ngày xưa có hai anh em.")
        self.assertEqual(self.client.patch(f"/api/shots/{shot['id']}", json={"narration": "Ngày xưa có ba anh em."}).status_code, 200)

    def test_26_the_legacy_workflow_keeps_its_planner(self) -> None:
        project = self.database.create_idea_project("Kịch bản nhập thủ công", title="Dán tay")
        project_id = int(project["id"])
        self.database.create_project_script(project_id, script_title="x", hook="Mở đầu.", main_content="Câu một.\nCâu hai.", cta="Hết.")
        cut = self._cut(project_id)
        self.assertEqual([shot["narration"] for shot in cut["shots"]], ["Mở đầu.", "Câu một.", "Câu hai.", "Hết."])
        self.assertNotIn("storyboard", cut)
        self.assertEqual(self.database.list_project_storyboards(project_id), [])
        body = self._storyboard(project_id)
        self.assertEqual((body["state"], body["mode"], body["storyboard_state"]), ("not_applicable", "legacy", "missing"))
        shot = cut["shots"][1]
        self.assertEqual(self.client.patch(f"/api/shots/{shot['id']}", json={"narration": "Câu một sửa."}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/shots/{shot['id']}/duplicate").status_code, 200)

    def test_project_57_keeps_its_old_shots_and_gets_no_storyboard(self) -> None:
        project_id = _legacy_project(self.database)
        before = _snapshot(self.database, project_id)
        body = self._storyboard(project_id)
        self.assertEqual((body["state"], body["storyboard"]), ("missing", None))
        refused = self.client.post(f"/api/projects/{project_id}/shots/generate", json={"force": True})
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(_snapshot(self.database, project_id), before)
        self.assertEqual(self.database.list_project_storyboards(project_id), [])


if __name__ == "__main__":
    unittest.main()
