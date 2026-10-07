"""Bước 5.2 · Storyboard Gate + reconcile without loss.

    ScriptDocument → StoryboardDocument → project_shots / timeline → voice / render

The gate says whether a planned project's storyboard is the current script's
and plan's, and whether what downstream reads (project_shots, the timeline)
says exactly its scenes: missing | current | stale | invalid | out_of_sync.
Voice, render and the timeline build go on only past it - at the route, in
run_step and again in the worker. A changed script is reconciled scene by
scene, never rebuilt by position: unchanged scenes keep their rows and voice,
a scene whose words changed loses its voice and nothing else.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from tests.script_fixtures import PLAN, Scripted, planned_project
from tests.test_storyboard_engine import KNOWN, PLAN_ROW, _document, _line, _script, _section
from youtube_monitor import main, production_worker as worker_module, script_engine
from youtube_monitor import storyboard_engine as sb, storyboard_reconcile as rc

GATE = sb.GATE_MESSAGES


# ===========================================================================
# The reconcile plan (pure)
# ===========================================================================

def _board(document: dict) -> dict:
    board = sb.build(_script(document), PLAN_ROW, known_ids=KNOWN)
    assert board["status"] == sb.VALID, board["validation"]
    return board


def _rows(board: dict, *, voiced: bool = True, translate: int | None = None) -> tuple[list[dict], list[dict]]:
    """The shots and timeline a cut of `board` left in the database, each scene voiced and illustrated."""
    shots = [{**shot, "id": 100 + n} for n, shot in enumerate(sb.to_shots(board))]
    timeline = [{"id": 500 + n, "shot_id": shot["id"], "voice_text": shot["narration"], "speaker": shot["speaker"],
                 "audio_path": f"a{n}.wav" if voiced else "", "visual_path": f"v{n}.png"} for n, shot in enumerate(shots)]
    if translate is not None:
        timeline[translate]["voice_text"] = "Translated line."
    return shots, timeline


def _plan(old_document: dict, new_document: dict, **rows) -> dict:
    old = _board(old_document)
    shots, timeline = _rows(old, **rows)
    return rc.plan(*rc.source_rows(shots, timeline, old), _board(new_document))


def _singles(*sections: list[str], speakers: dict | None = None, texts: dict | None = None) -> dict:
    """A script whose lines each fill one scene (15 words = the plan's 5 s at 3 words/s)."""
    return _document([_section(n, [_line(tag, 15, (speakers or {}).get(tag, "narrator")) for tag in tags],
                               texts=(texts or {}).get(n, ()), budget=200)
                      for n, tags in enumerate(sections, start=1)])


class ReconcilePlanTests(unittest.TestCase):
    def test_unchanged_scenes_keep_their_rows_and_voice(self) -> None:
        plan = _plan(_singles(["A1", "A2"], ["B1"]), _singles(["A1", "A2"], ["B1"]))
        self.assertEqual(plan["counts"], {"unchanged": 3, "modified": 0, "added": 0, "removed": 0})
        self.assertEqual([entry["row"]["shot_id"] for entry in plan["entries"]], [100, 101, 102])
        self.assertTrue(all(entry["keep_voice"] for entry in plan["entries"]))
        self.assertFalse(rc.destructive(plan))

    def test_a_modified_scene_loses_its_voice_and_nothing_else_does(self) -> None:
        old, new = _singles(["A1", "A2"], ["B1"]), _singles(["A1", "A2"], ["B1"])
        new["sections"][0]["spoken_lines"][1]["text"] = new["sections"][0]["spoken_lines"][1]["text"].replace("chữ3", "chữ ba")
        plan = _plan(old, new)
        self.assertEqual([(entry["status"], entry["changes"], entry["keep_voice"]) for entry in plan["entries"]],
                         [("unchanged", [], True), ("modified", ["narration"], False), ("unchanged", [], True)])
        self.assertEqual(plan["entries"][1]["row"]["shot_id"], 101, "the same row, re-voiced")
        self.assertEqual((plan["voice_invalidated"], rc.destructive(plan)), (1, True))

    def test_an_added_scene_is_new_and_the_ones_after_it_keep_their_identity(self) -> None:
        plan = _plan(_singles(["A1", "A2"], ["B1", "B2"]), _singles(["A0", "A1", "A2"], ["B1", "B2"]))
        self.assertEqual([entry["status"] for entry in plan["entries"]], ["added", "unchanged", "unchanged", "unchanged", "unchanged"])
        # Every scene after the new one moved down one place; each is still found by what it is.
        self.assertEqual([entry["row"]["shot_id"] for entry in plan["entries"][1:]], [100, 101, 102, 103])
        self.assertEqual([entry["index"] for entry in plan["entries"][1:]], [2, 3, 4, 5])
        self.assertFalse(rc.destructive(plan))

    def test_a_removed_scene_goes_and_the_rest_stay(self) -> None:
        plan = _plan(_singles(["A1", "A2"], ["B1", "B2"]), _singles(["A1"], ["B1", "B2"]))
        self.assertEqual([entry["row"]["shot_id"] for entry in plan["entries"]], [100, 102, 103])
        self.assertEqual([row["shot_id"] for row in plan["removed"]], [101])
        self.assertTrue(rc.destructive(plan))

    def test_many_changes_at_once(self) -> None:
        old = _singles(["A1", "A2", "A3"], ["B1", "B2", "B3"])
        new = _singles(["A1", "A2", "A3"], ["B1", "B3", "B4"])
        new["sections"][0]["spoken_lines"][0]["text"] = new["sections"][0]["spoken_lines"][0]["text"].replace("chữ1", "chữ một")
        plan = _plan(old, new)
        self.assertEqual([entry["status"] for entry in plan["entries"]], ["modified", "unchanged", "unchanged", "unchanged", "unchanged", "added"])
        self.assertEqual([row["shot_id"] for row in plan["removed"]], [104])
        self.assertEqual(plan["counts"], {"unchanged": 4, "modified": 1, "added": 1, "removed": 1})

    def test_a_scene_that_moved_to_another_section_keeps_its_voice(self) -> None:
        plan = _plan(_singles(["A1", "A2"], ["B1"]), _singles(["A1"], ["A2", "B1"]))
        moved = plan["entries"][1]
        self.assertEqual((moved["status"], moved["changes"], moved["keep_voice"], moved["row"]["shot_id"]),
                         ("modified", ["section"], True, 101))
        self.assertFalse(rc.destructive(plan))

    def test_a_new_speaker_takes_the_voice(self) -> None:
        plan = _plan(_singles(["A1", "A2"]), _singles(["A1", "A2"], speakers={"A2": "Ông Ba"}))
        self.assertEqual((plan["entries"][1]["status"], plan["entries"][1]["changes"], plan["entries"][1]["keep_voice"]),
                         ("modified", ["speaker"], False))

    def test_new_on_screen_text_keeps_the_voice(self) -> None:
        plan = _plan(_singles(["A1"], ["B1"], texts={2: ["Cũ"]}), _singles(["A1"], ["B1"], texts={2: ["Mới"]}))
        self.assertEqual([(entry["status"], entry["changes"], entry["keep_voice"]) for entry in plan["entries"]],
                         [("unchanged", [], True), ("modified", ["on_screen_text"], True)])

    def test_a_timeline_that_voiced_other_words_is_re_voiced(self) -> None:
        plan = _plan(_singles(["A1", "A2"]), _singles(["A1", "A2"]), translate=1)
        self.assertEqual((plan["entries"][1]["changes"], plan["entries"][1]["keep_voice"]), (["voiced_text"], False))

    def test_rows_without_a_known_storyboard_are_still_matched_by_their_words(self) -> None:
        old, new = _board(_singles(["A1", "A2"])), _board(_singles(["A1", "A2", "A3"]))
        shots, timeline = _rows(old)
        timeline.append({"id": 999, "shot_id": None, "voice_text": "Mồ côi.", "speaker": "", "audio_path": "", "visual_path": ""})
        plan = rc.plan(*rc.source_rows(shots, timeline, None), new)
        self.assertEqual([entry["status"] for entry in plan["entries"]], ["unchanged", "unchanged", "added"])
        self.assertEqual([row["segment_id"] for row in plan["removed"]], [999], "a segment tied to no shot leaves")

    def test_scene_keys_are_stable_across_cuts_and_positions(self) -> None:
        first, second = _board(_singles(["A1", "A2"])), _board(_singles(["A0", "A1", "A2"]))
        self.assertEqual([scene["scene_key"] for scene in sb.scenes(first)], [scene["scene_key"] for scene in sb.scenes(second)][1:])
        repeated = _board(_document([_section(1, [_line("A1", 15), _line("A1", 15)], budget=200)]))
        keys = [scene["scene_key"] for scene in sb.scenes(repeated)]
        self.assertEqual((len(set(keys)), keys[1]), (2, f"{keys[0]}-2"))


class IdentityTests(unittest.TestCase):
    """Which old row a new scene is: by its lines first, then its section, then its words - never position alone."""

    def test_the_same_line_twice_keeps_each_its_own_row(self) -> None:
        old, new = _singles(["X", "Y", "X"]), _singles(["X", "Y", "X"])
        new["sections"][0]["spoken_lines"][1]["text"] = new["sections"][0]["spoken_lines"][1]["text"].replace("chữ2", "chữ hai")
        plan = _plan(old, new)
        self.assertEqual([(entry["status"], entry["row"]["shot_id"], entry["match"]) for entry in plan["entries"]],
                         [("unchanged", 100, "lines"), ("modified", 101, "position"), ("unchanged", 102, "lines")])
        # One more copy said first: the original first one stays first, the new copy is new.
        plan = _plan(_singles(["X", "Y", "X"]), _singles(["X", "X", "Y", "X"]))
        self.assertEqual([(entry["status"], (entry["row"] or {}).get("shot_id")) for entry in plan["entries"]],
                         [("unchanged", 100), ("added", None), ("unchanged", 101), ("unchanged", 102)])

    def test_the_same_words_in_two_sections_are_told_apart_by_their_section(self) -> None:
        # Section 1's X is rewritten; section 2's identical X must keep its own row, not section 1's.
        plan = _plan(_singles(["X"], ["X"]), _singles(["Z"], ["X"]))
        self.assertEqual([(entry["status"], entry["row"]["shot_id"], entry["match"]) for entry in plan["entries"]],
                         [("modified", 100, "position"), ("unchanged", 101, "lines")])

    def test_a_reordered_scene_keeps_its_row_and_voice(self) -> None:
        plan = _plan(_singles(["A1", "A2", "A3"]), _singles(["A3", "A1", "A2"]))
        self.assertEqual([(entry["status"], entry["row"]["shot_id"], entry["match"], entry["keep_voice"]) for entry in plan["entries"]],
                         [("unchanged", 102, "moved", True), ("unchanged", 100, "section", True), ("unchanged", 101, "section", True)])
        self.assertEqual((plan["removed"], rc.destructive(plan)), ([], False))


class PlacePairingTests(unittest.TestCase):
    """F2: what is left between matched scenes is paired by place only inside the same section and part."""

    def test_a_scene_of_another_section_never_takes_over_a_row(self) -> None:
        # Section 1 loses A2, section 2 gains C: C is new, A2's row (and its picture) goes - never to C.
        plan = _plan(_singles(["A1", "A2"], ["B1"]), _singles(["A1"], ["C", "B1"]))
        self.assertEqual([(entry["status"], (entry["row"] or {}).get("shot_id")) for entry in plan["entries"]],
                         [("unchanged", 100), ("added", None), ("unchanged", 102)])
        self.assertEqual([row["shot_id"] for row in plan["removed"]], [101])

    def test_inside_one_section_a_rewritten_scene_still_keeps_its_row(self) -> None:
        old, new = _singles(["A1", "A2"], ["B1"]), _singles(["A1", "A2"], ["B1"])
        new["sections"][0]["spoken_lines"][1]["text"] = new["sections"][0]["spoken_lines"][1]["text"].replace("chữ1", "chữ một")
        entry = _plan(old, new)["entries"][1]
        self.assertEqual((entry["status"], entry["match"], entry["row"]["shot_id"]), ("modified", "position", 101))

    def test_a_row_whose_scene_is_unknown_is_never_paired_by_place(self) -> None:
        old, new = _board(_singles(["A1", "A2", "A3"])), _singles(["A1", "A2", "A3"])
        new["sections"][0]["spoken_lines"][1]["text"] = new["sections"][0]["spoken_lines"][1]["text"].replace("chữ1", "chữ một")
        shots, timeline = _rows(old)
        plan = rc.plan(*rc.source_rows(shots, timeline, None), _board(new))
        self.assertEqual([(entry["status"], (entry["row"] or {}).get("shot_id")) for entry in plan["entries"]],
                         [("unchanged", 100), ("added", None), ("unchanged", 102)])
        self.assertEqual([row["shot_id"] for row in plan["removed"]], [101])


class VoiceConfigTests(unittest.TestCase):
    """A voice is reused only when it says the scene's words, by its speaker, made with the project's current voice settings."""

    def _plan(self, *, records: str | None, now: str, text: str | None = None) -> dict:
        board = _board(_singles(["A1", "A2"]))
        shots, timeline = _rows(board)
        voice_records = None if records is None else {
            item["id"]: {"fingerprint": records, "voice_text": text or item["voice_text"], "speaker": item["speaker"]}
            for item in timeline}
        return rc.plan(*rc.source_rows(shots, timeline, board, voice_records=voice_records), board, voice_fingerprint=now)

    def test_new_voice_settings_take_the_voice_and_nothing_else(self) -> None:
        same = self._plan(records="fp-a", now="fp-a")
        self.assertEqual(([entry["status"] for entry in same["entries"]], same["voice_invalidated"]), (["unchanged", "unchanged"], 0))
        changed = self._plan(records="fp-a", now="fp-b")
        self.assertEqual([(entry["status"], entry["changes"], entry["keep_voice"]) for entry in changed["entries"]],
                         [("modified", ["voice_config"], False)] * 2)
        self.assertEqual((changed["voice_invalidated"], rc.destructive(changed)), (2, True))

    def test_a_record_that_says_other_words_is_not_reused(self) -> None:
        plan = self._plan(records="fp-a", now="fp-a", text="Lời khác.")
        self.assertFalse(any(entry["keep_voice"] for entry in plan["entries"]))

    def test_a_voice_with_no_record_is_kept_and_counted_unverified(self) -> None:
        plan = self._plan(records=None, now="fp-b")
        self.assertEqual((all(entry["keep_voice"] for entry in plan["entries"]), plan["voice_unverified"]), (True, 2))

    def test_the_fingerprint_follows_what_the_engine_reads(self) -> None:
        settings = {"voice_model": "vi-VN-HoaiMyNeural", "voice_rate": "+0%", "publish_language": "vi", "voice_style": "",
                    "voice_reference_file_path": "", "voice_prompt_text": ""}
        base = worker_module.voice_fingerprint("edge_tts", settings)
        for provider, change in (("edge_tts", {"voice_model": "vi-VN-NamMinhNeural"}), ("edge_tts", {"voice_rate": "+15%"}),
                                 ("edge_tts", {"publish_language": "en"})):
            self.assertNotEqual(worker_module.voice_fingerprint(provider, {**settings, **change}), base, change)
        self.assertNotEqual(worker_module.voice_fingerprint("google_gemini_3_8_flash_tts", settings), base, "another engine")
        gemini = worker_module.voice_fingerprint("google_gemini_3_8_flash_tts", settings)
        self.assertNotEqual(worker_module.voice_fingerprint("google_gemini_3_8_flash_tts", {**settings, "voice_style": "chậm rãi"}), gemini)
        self.assertEqual(worker_module.voice_fingerprint("edge_tts", {**settings, "voice_style": "chậm rãi"}), base,
                         "Edge does not read the style, so its voice still fits")
        voxcpm = worker_module.voice_fingerprint("voxcpm", settings)
        self.assertNotEqual(worker_module.voice_fingerprint("voxcpm", {**settings, "voice_reference_file_path": "C:/mau.wav"}), voxcpm)


# ===========================================================================
# The gate (pure)
# ===========================================================================

class GateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = _singles(["A1", "A2"], ["B1"])
        self.board = _board(self.document)
        self.script = {**_script(self.document), "state": script_engine.COMPLETED}
        self.row = {"id": 1, "script_id": 98, "script_version": 1, "script_fingerprint": self.board["script_fingerprint"],
                    "plan_id": 16, "plan_version": 5, "document_hash": self.board["document_hash"],
                    "engine_version": sb.ENGINE_VERSION, "status": sb.VALID,
                    "document_json": json.dumps(self.board, ensure_ascii=False)}
        self.shots, self.timeline = _rows(self.board)

    def _gate(self, row=..., script=..., plan=PLAN_ROW, shots=..., timeline=..., mode=sb.PLAN_MODE) -> dict:
        return sb.gate(self.row if row is ... else row, self.script if script is ... else script, plan,
                       shots=self.shots if shots is ... else shots, timeline=self.timeline if timeline is ... else timeline, mode=mode)

    def test_current_needs_the_storyboard_and_what_downstream_reads(self) -> None:
        gate = self._gate()
        self.assertEqual((gate["state"], gate["shots_in_sync"], gate["timeline_in_sync"]), (sb.CURRENT, True, True))
        self.assertEqual(sb.refusal_for(gate), "")
        self.assertEqual(self._gate(timeline=[])["state"], sb.CURRENT, "no timeline yet is not a mismatch")

    def test_missing_stale_invalid(self) -> None:
        self.assertEqual(self._gate(row=None)["state"], sb.MISSING)
        edited = copy.deepcopy(self.document)
        edited["sections"][0]["spoken_lines"][0]["text"] = "Lời đã sửa."
        self.assertEqual(self._gate(script={**self.script, "document": edited})["state"], sb.STALE)
        self.assertEqual(self._gate(plan={**PLAN_ROW, "version": 6})["state"], sb.STALE)
        self.assertEqual(self._gate(row={**self.row, "engine_version": "storyboard-phase1"})["state"], sb.STALE)
        self.assertEqual(self._gate(row={**self.row, "status": sb.INVALID})["state"], sb.INVALID)
        tampered = copy.deepcopy(self.board)
        tampered["sections"][0]["scenes"][0]["narration_text"] = "Lời lén sửa."
        self.assertEqual(self._gate(row={**self.row, "document_json": json.dumps(tampered, ensure_ascii=False)})["state"], sb.INVALID)
        for state_, row in ((sb.MISSING, None), (sb.STALE, {**self.row, "plan_version": 4})):
            self.assertTrue(sb.refusal_for(self._gate(row=row)).startswith(GATE[state_]))

    def test_a_plan_whose_inputs_changed_stales_it_even_with_the_same_script(self) -> None:
        for change in ({"edit_direction": {"average_shot_length_seconds": 3.0}},
                       {"media_strategy": {**PLAN_ROW["plan"]["media_strategy"], "primary_sources": ["ai_media"]}},
                       {"constraints": {"scene_asset_type": "source_clip"}}):
            moved = {**PLAN_ROW, "plan": {**PLAN_ROW["plan"], **change}}
            gate = self._gate(plan=moved)
            self.assertEqual(gate["state"], sb.STALE, change)
            self.assertIn("Thiết lập của kế hoạch", gate["reasons"][0])
        self.assertEqual(self._gate(plan={**PLAN_ROW, "plan": {**PLAN_ROW["plan"], "goal": "Mục tiêu khác"}})["state"], sb.CURRENT,
                         "what the cut does not read does not stale it")

    def test_not_applicable_is_never_a_refusal(self) -> None:
        for mode in (sb.REUP_MODE, sb.LEGACY_MODE):
            gate = self._gate(row=None, mode=mode)
            self.assertEqual((gate["state"], gate["storyboard_state"], gate["applies"], sb.refusal_for(gate)),
                             (sb.NOT_APPLICABLE, sb.MISSING, False, ""), mode)

    def test_shots_or_timeline_out_of_sync(self) -> None:
        shots = copy.deepcopy(self.shots)
        shots[1]["narration"] = "Lời khác."
        gate = self._gate(shots=shots)
        self.assertEqual((gate["state"], gate["shots_in_sync"]), (sb.OUT_OF_SYNC, False))
        self.assertTrue(sb.refusal_for(gate, need="shots").startswith(GATE[sb.OUT_OF_SYNC]))
        speaker = copy.deepcopy(self.shots)
        speaker[1]["speaker"] = "Ông Ba"
        self.assertEqual(self._gate(shots=speaker)["state"], sb.OUT_OF_SYNC)
        timeline = copy.deepcopy(self.timeline)
        timeline[2]["voice_text"] = "Lời khác."
        gate = self._gate(timeline=timeline)
        self.assertEqual((gate["state"], gate["shots_in_sync"], gate["timeline_in_sync"]), (sb.OUT_OF_SYNC, True, False))
        self.assertTrue(sb.refusal_for(gate).startswith(GATE[sb.OUT_OF_SYNC]), "voice and render need the timeline to agree")
        self.assertEqual(sb.refusal_for(gate, need="shots"), "", "building the timeline needs only the shots to agree")
        # Reup's cut by dialogue is its own mode.
        self.assertEqual(sb.refusal_for(self._gate(timeline=timeline, mode=sb.REUP_MODE)), "")


# ===========================================================================
# Through the app
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
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.model = Scripted()
        for target, name, value in ((main, "_call_orchestrator_json", self.model),
                                    (main.production_worker, "enqueue", mock.Mock(return_value={"id": 1, "status": "queued"}))):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    # --- a project in a given state ----------------------------------------------

    def _ready(self, **setup) -> int:
        """Plan completed, script written, storyboard and timeline cut, every scene voiced and illustrated."""
        project_id = planned_project(self.database, **setup)
        self.assertEqual(self.client.post(f"/api/projects/{project_id}/script/generate", json={"options": {}}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/projects/{project_id}/shots/generate", json={}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/projects/{project_id}/timeline/generate", json={}).status_code, 200)
        for segment in self._timeline(project_id):
            audio, visual = self.tmp / f"voice-{segment['id']}.wav", self.tmp / f"pic-{segment['id']}.png"
            audio.write_bytes(b"RIFF")
            visual.write_bytes(b"PNG")
            self.database.update_project_timeline_segment(int(segment["id"]), audio_path=str(audio), visual_path=str(visual))
        return project_id

    def _script(self, project_id: int) -> dict:
        return self.client.get(f"/api/projects/{project_id}/script").json()

    def _timeline(self, project_id: int, script_id: int | None = None) -> list[dict]:
        script_id = script_id or int(self.database.get_latest_project_script(project_id)["id"])
        return self.database.list_project_timeline(project_id, script_id=script_id)

    def _gate(self, project_id: int) -> dict:
        return self.client.get(f"/api/projects/{project_id}/storyboard").json()

    def _patch_lines(self, project_id: int, change) -> list[str]:
        """Edit the script in place (same id, same version) through its body lines."""
        script = self._script(project_id)
        lines = script["main_content"].split("\n")
        change(lines)
        response = self.client.patch(f"/api/scripts/{script['id']}", json={"main_content": "\n".join(lines)})
        self.assertEqual((response.status_code, response.json()["state"]), (200, "completed"), response.text)
        return lines

    def _first_of_section(self, project_id: int, section: int) -> int:
        document = self._script(project_id)["document"]
        return sum(len(item["spoken_lines"]) for item in document["sections"][:section])

    def _by_section(self, project_id: int) -> dict[str, list[tuple[int, str, str]]]:
        """Per section of the storyboard: (segment id, words, audio) of its scenes, read from the timeline."""
        board = self._gate(project_id)["storyboard"]
        timeline = self._timeline(project_id)
        found: dict[str, list[tuple[int, str, str]]] = {}
        for scene, segment in zip(sb.scenes(board), timeline):
            found.setdefault(scene["section_id"], []).append((segment["id"], segment["voice_text"], segment["audio_path"]))
        return found

    def _voice(self, project_id: int, **body) -> object:
        return self.client.post(f"/api/projects/{project_id}/jobs", json={"job_type": "voiceover", "provider": "dry_run", **body})


class ReconcileAppTests(_AppCase):
    def test_an_edited_word_re_voices_one_scene_and_keeps_every_other(self) -> None:
        project_id = self._ready()
        before = self._timeline(project_id)
        at = self._first_of_section(project_id, 1)
        self._patch_lines(project_id, lambda lines: lines.__setitem__(at, lines[at].replace(" ", " mỗi ", 1).rsplit(" ", 1)[0] + "."))
        self.assertEqual(self._gate(project_id)["state"], sb.STALE)
        # A voice would be lost: shown, not done, without force.
        preview = self.client.post(f"/api/projects/{project_id}/shots/generate", json={}).json()
        self.assertEqual((preview["status"], preview["reconcile"]["applied"], preview["reconcile"]["voice_invalidated"]), ("stale", False, 1))
        self.assertEqual(self._timeline(project_id), before, "nothing changed yet")
        done = self.client.post(f"/api/projects/{project_id}/shots/generate", json={"force": True}).json()
        self.assertEqual((done["reconcile"]["counts"]["modified"], done["reconcile"]["mode"]), (1, "in_place"))
        after = self._timeline(project_id)
        self.assertEqual([item["id"] for item in after], [item["id"] for item in before], "same rows, nothing rebuilt")
        changed = [(old, new) for old, new in zip(before, after) if old["voice_text"] != new["voice_text"]]
        self.assertEqual(len(changed), 1)
        old, new = changed[0]
        self.assertEqual((new["audio_path"], new["visual_path"]), ("", old["visual_path"]), "the voice goes, the picture stays")
        for old_item, new_item in zip(before, after):
            if old_item["id"] != old["id"]:
                self.assertEqual(new_item["audio_path"], old_item["audio_path"])
                self.assertTrue(Path(new_item["audio_path"]).is_file())
        gate = self._gate(project_id)
        self.assertEqual((gate["state"], gate["timeline_in_sync"], gate["last_reconcile"]["counts"]["modified"]), (sb.CURRENT, True, 1))

    def test_a_line_added_earlier_moves_later_scenes_without_losing_them(self) -> None:
        project_id = self._ready()
        before = self._by_section(project_id)
        at = self._first_of_section(project_id, 1)
        self._patch_lines(project_id, lambda lines: lines.insert(at, "Mọi ý chính đều dễ nhớ khi theo dõi."))
        self.client.post(f"/api/projects/{project_id}/shots/generate", json={"force": True})
        after = self._by_section(project_id)
        # The later sections' scenes moved down the timeline and are the same rows, with their voice.
        for section in ("sec-2", "sec-3"):
            self.assertEqual(after[section], before[section], section)
        self.assertEqual(self._gate(project_id)["state"], sb.CURRENT)

    def test_a_removed_line_is_recorded_before_its_rows_go_and_no_file_is_deleted(self) -> None:
        project_id = self._ready()
        before = self._by_section(project_id)
        files = [Path(item["audio_path"]) for item in self._timeline(project_id)]
        at = self._first_of_section(project_id, 1)
        self._patch_lines(project_id, lambda lines: lines.pop(at))
        done = self.client.post(f"/api/projects/{project_id}/shots/generate", json={"force": True}).json()
        self.assertTrue(done["reconcile"]["counts"]["removed"] + done["reconcile"]["counts"]["modified"] >= 1)
        after = self._by_section(project_id)
        for section in ("sec-1", "sec-3"):
            self.assertEqual(after[section], before[section], section)
        self.assertTrue(all(path.is_file() for path in files), "no file is deleted")
        record = self.database.get_director_artifact(project_id, "storyboard_reconcile")["payload"]
        self.assertEqual(len(record["archived"]), done["reconcile"]["counts"]["removed"])
        for archived in record["archived"]:
            self.assertTrue(archived["segment"]["audio_path"], "what the row had is kept in the record")

    def test_a_revised_script_carries_the_unchanged_scenes_over(self) -> None:
        project_id = self._ready()
        old = self._script(project_id)
        old_rows = self._timeline(project_id, old["id"])
        lines = old["main_content"].split("\n")
        at = self._first_of_section(project_id, 1)
        lines[at] = lines[at].replace(" ", " mỗi ", 1).rsplit(" ", 1)[0] + "."
        main.run_project_step(project_id, "script", {"revision": {"base_script_id": old["id"],
                                                                  "fields": {"main_content": "\n".join(lines)}, "source": "test"}})
        new = self._script(project_id)
        self.assertNotEqual(new["id"], old["id"])
        self.assertEqual(self._gate(project_id)["state"], sb.STALE)
        done = self.client.post(f"/api/projects/{project_id}/shots/generate", json={}).json()
        self.assertEqual((done["status"], done["reconcile"]["mode"], done["reconcile"]["counts"]["modified"]), ("saved", "carried_over", 1))
        rows = self._timeline(project_id, new["id"])
        self.assertEqual(len(rows), len(old_rows))
        kept = [(row["voice_text"], row["audio_path"]) for row in rows if row["audio_path"]]
        self.assertEqual(len(kept), len(rows) - 1)
        self.assertTrue(set(kept) <= {(row["voice_text"], row["audio_path"]) for row in old_rows})
        self.assertTrue(all(row["visual_path"] for row in rows), "pictures carried over, the changed scene's too")
        data = lambda items: [(row["id"], row["voice_text"], row["audio_path"], row["visual_path"]) for row in items]  # noqa: E731
        self.assertEqual(data(self._timeline(project_id, old["id"])), data(old_rows), "the old script's rows are untouched")
        self.assertEqual(self._gate(project_id)["state"], sb.CURRENT)

    def test_force_never_skips_a_check(self) -> None:
        project_id = self._ready()
        lines = [line["text"] for line in sb.document_lines(self._script(project_id)["document"])]
        hook = len(self._script(project_id)["document"]["hook"]["spoken_lines"])
        # The hook's last line and the body's first, said as one scene: a grouping the checks refuse.
        across = [*({"narration": text} for text in lines[:hook - 1]), {"narration": f"{lines[hook - 1]} {lines[hook]}"},
                  *({"narration": text} for text in lines[hook + 1:])]
        before = self._timeline(project_id)
        for force in (False, True):
            refused = self.client.post(f"/api/projects/{project_id}/steps/shots", json={"options": {"shots": across, "force": force}})
            self.assertEqual(refused.status_code, 409, force)
        self.assertEqual(self._timeline(project_id), before)
        # And force on an unchanged storyboard touches nothing.
        self.client.post(f"/api/projects/{project_id}/shots/generate", json={"force": True})
        self.client.post(f"/api/projects/{project_id}/timeline/generate", json={"force": True})
        self.assertEqual(self._timeline(project_id), before)


class GateAppTests(_AppCase):
    def test_voice_and_render_need_a_current_storyboard(self) -> None:
        project_id = self._ready()
        self.assertEqual(self._voice(project_id).status_code, 200)
        at = self._first_of_section(project_id, 1)
        self._patch_lines(project_id, lambda lines: lines.__setitem__(at, lines[at].replace(" ", " mỗi ", 1).rsplit(" ", 1)[0] + "."))
        for body in ({}, {"force": True, "confirmed": True}, {"job_type": "render"}, {"job_type": "voiceover_segment", "segment_id": 1}):
            response = self._voice(project_id, **body)
            self.assertEqual(response.status_code, 409, body)
            self.assertTrue(response.json()["detail"].startswith(GATE[sb.STALE]), body)
        refused = self.client.post(f"/api/projects/{project_id}/steps/voice", json={"options": {"force": True, "provider": "dry_run"}})
        self.assertEqual(refused.status_code, 409)
        # The timeline is not built on it either, force or not.
        for force in (False, True):
            timeline = self.client.post(f"/api/projects/{project_id}/timeline/generate", json={"force": force})
            self.assertTrue(timeline.json()["detail"].startswith(GATE[sb.STALE]), force)
        self.assertNotIn("shots", main._steps_done(project_id))
        shots_row = next(row for row in main._describe_steps(project_id, main._steps_done(project_id)) if row["key"] == "shots")
        self.assertEqual(shots_row["outcome"]["state"], sb.STALE)

    def test_voice_needs_the_shots_and_the_timeline_to_say_the_storyboard(self) -> None:
        project_id = self._ready()
        script_id = int(self.database.get_latest_project_script(project_id)["id"])
        shot = self.database.list_project_shots(project_id, script_id=script_id)[0]
        # Written behind the API's back: the gate reads what is there.
        self.database.update_project_shot(int(shot["id"]), narration="Lời không có trong kịch bản.")
        self.assertEqual(self._gate(project_id)["state"], sb.OUT_OF_SYNC)
        self.assertTrue(self._voice(project_id).json()["detail"].startswith(GATE[sb.OUT_OF_SYNC]))
        self.database.update_project_shot(int(shot["id"]), narration=shot["narration"])
        segment = self._timeline(project_id)[0]
        self.database.update_project_timeline_segment(int(segment["id"]), voice_text="Lời không có trong kịch bản.")
        gate = self._gate(project_id)
        self.assertEqual((gate["state"], gate["shots_in_sync"], gate["timeline_in_sync"]), (sb.OUT_OF_SYNC, True, False))
        self.assertEqual(self._voice(project_id).status_code, 409)
        # Re-syncing puts the script's words back, and that scene's voice goes with the wrong ones.
        self.client.post(f"/api/projects/{project_id}/timeline/generate", json={"force": True})
        fixed = self._timeline(project_id)[0]
        self.assertEqual((fixed["id"], fixed["voice_text"], fixed["audio_path"]), (segment["id"], segment["voice_text"], ""))
        self.assertEqual(self._voice(project_id).status_code, 200)

    def test_an_invalid_storyboard_holds_everything(self) -> None:
        project_id = self._ready()
        row = self.database.get_latest_project_storyboard(project_id)
        stored = json.loads(row["document_json"])
        stored["sections"][0]["scenes"][0]["narration_text"] = "Lén sửa."
        with self.database._connect() as connection:
            connection.execute("UPDATE project_storyboards SET document_json = ? WHERE id = ?",
                               (json.dumps(stored, ensure_ascii=False), row["id"]))
        self.assertEqual(self._gate(project_id)["state"], sb.INVALID)
        self.assertTrue(self._voice(project_id).json()["detail"].startswith(GATE[sb.INVALID]))

    def test_no_route_rewords_a_storyboard_scene(self) -> None:
        project_id = self._ready()
        segment = self._timeline(project_id)[0]
        reworded = self.client.patch(f"/api/timeline/{segment['id']}", json={"voice_text": "Lời khác."})
        self.assertEqual((reworded.status_code, reworded.json()["detail"]), (409, sb.NARRATION_LOCKED))
        self.assertEqual(self.client.patch(f"/api/timeline/{segment['id']}", json={"visual_prompt": "Một sơ đồ"}).status_code, 200)
        translate = self.client.post(f"/api/projects/{project_id}/script/translate?target_language=en")
        self.assertEqual((translate.status_code, translate.json()["detail"]), (409, sb.TRANSLATE_LOCKED))
        library = {main.voice_library.normalise("Lời khác."): {"audio_path": str(self.tmp / "x.wav"), "text": "Lời khác."}}
        with mock.patch.object(main.voice_library, "index_voices", return_value=library):
            attached = self.client.post(f"/api/timeline/{segment['id']}/attach-generated-voice",
                                        json={"voice_key": main.voice_library.normalise("Lời khác.")})
        self.assertEqual((attached.status_code, attached.json()["detail"]), (409, sb.VOICE_MISMATCH))
        self.assertEqual(self._gate(project_id)["state"], sb.CURRENT)


class WorkerTests(_AppCase):
    def _run(self, job_id: int) -> list[str]:
        calls: list[str] = []
        patches = [mock.patch.object(worker_module, name, side_effect=lambda *a, _n=name, **k: calls.append(_n) or str(self.tmp / "out"))
                   for name in ("run_voiceover_job", "run_render_job", "run_premiere_draft_job", "run_director_production_job")]
        for patcher in patches:
            patcher.start()
        try:
            main.production_worker._process(job_id)
        finally:
            for patcher in patches:
                patcher.stop()
        return calls

    def test_the_worker_asks_the_gate_again_when_it_takes_the_job(self) -> None:
        project_id = self._ready()
        script_id = int(self.database.get_latest_project_script(project_id)["id"])
        ran = self.database.create_project_job(project_id, script_id, "voiceover", "dry_run")
        self.assertEqual(self._run(int(ran["id"])), ["run_voiceover_job"])
        for job_type in ("voiceover", "render"):
            job = self.database.create_project_job(project_id, script_id, job_type, "dry_run", force=True)
            # The API let it through; then the timeline changed behind everyone's back.
            segment = self._timeline(project_id)[0]
            self.database.update_project_timeline_segment(int(segment["id"]), voice_text="Lời không có trong kịch bản.")
            self.assertEqual(self._run(int(job["id"])), [], job_type)
            stored = self.database.get_project_job(int(job["id"]))
            self.assertEqual(stored["status"], "error")
            self.assertTrue(stored["error"].startswith(GATE[sb.OUT_OF_SYNC]), stored["error"])
            self.database.update_project_timeline_segment(int(segment["id"]), voice_text=segment["voice_text"])

    def test_voice_files_are_named_by_their_own_row_and_words_never_their_place(self) -> None:
        scene = {"id": 11, "segment_index": 3, "voice_text": "Một câu.", "speaker": "narrator"}
        name = worker_module._voice_stem(scene, "fp")
        self.assertRegex(name, r"^voice-s11-[0-9a-f]{12}$")
        self.assertEqual(worker_module._voice_stem({**scene, "segment_index": 9}, "fp"), name, "moving it keeps its file")
        for other in ({**scene, "id": 12}, {**scene, "voice_text": "Câu khác."}, {**scene, "speaker": "Ông Ba"}):
            self.assertNotEqual(worker_module._voice_stem(other, "fp"), name, other)
        self.assertNotEqual(worker_module._voice_stem(scene, "fp-2"), name, "other voice settings, another file")


class IdentityAppTests(_AppCase):
    def test_a_scene_moved_up_keeps_its_row_its_voice_and_its_file(self) -> None:
        # A 4 s scene: every body line is a scene of its own, so moving a line moves one scene.
        project_id = self._ready(plan={**PLAN, "edit_direction": {"average_shot_length_seconds": 4}})
        document = self._script(project_id)["document"]
        at, count = self._first_of_section(project_id, 1), len(document["sections"][1]["spoken_lines"])
        moved_text = document["sections"][1]["spoken_lines"][-1]["text"]
        before_rows = self._timeline(project_id)
        moved = next(item for item in before_rows if item["voice_text"] == moved_text)
        content = Path(moved["audio_path"]).read_bytes()
        self._patch_lines(project_id, lambda lines: lines.insert(at + 1, lines.pop(at + count - 1)))
        done = self.client.post(f"/api/projects/{project_id}/shots/generate", json={}).json()
        self.assertEqual((done["status"], done["reconcile"]["counts"]["removed"], done["reconcile"]["voice_invalidated"]),
                         ("saved", 0, 0), "a move loses nothing, so it needs no force")
        self.assertIn("moved", {item["match"] for item in done["reconcile"]["scenes"]})
        after = self._timeline(project_id)
        now = next(item for item in after if item["voice_text"] == moved_text)
        self.assertEqual((now["id"], now["audio_path"], now["visual_path"]), (moved["id"], moved["audio_path"], moved["visual_path"]))
        self.assertLess(now["segment_index"], moved["segment_index"], "it moved up the timeline")
        self.assertEqual(Path(now["audio_path"]).read_bytes(), content, "its file was not touched")
        self.assertEqual({item["id"]: item["audio_path"] for item in after}, {item["id"]: item["audio_path"] for item in before_rows},
                         "every row kept, each with its own voice")
        self.assertEqual(self._gate(project_id)["state"], sb.CURRENT)

    def test_a_plan_change_under_the_same_script_is_not_kept_blindly(self) -> None:
        project_id = self._ready()
        lines = [line["text"] for line in sb.document_lines(self._script(project_id)["document"])]
        given = self.client.post(f"/api/projects/{project_id}/steps/shots", json={"options": {
            "shots": [{"shot_index": n, "narration": text} for n, text in enumerate(lines, start=1)], "force": True}})
        self.assertEqual(given.status_code, 200, given.text)
        plan_row = main._current_project_plan(project_id)
        current = script_engine.current_script(self.database, project_id, plan_row)
        self.assertIsNotNone(main._kept_grouping(project_id, current), "the agent's grouping is kept for its plan")
        moved = {**plan_row, "plan": {**plan_row["plan"], "edit_direction": {"average_shot_length_seconds": 3}}}
        with mock.patch.object(main, "_current_project_plan", return_value=moved):
            self.assertIsNone(main._kept_grouping(project_id, current), "not for a plan that cuts scenes another length")
            gate = self._gate(project_id)
            self.assertEqual(gate["state"], sb.STALE)
            self.assertTrue(self._voice(project_id).json()["detail"].startswith(GATE[sb.STALE]))
        # A new plan version is a new plan: stale too (and the script with it).
        latest = self.database.get_latest_project_plan(project_id)
        self.database.create_project_plan(
            project_id, status="completed", research_report_id=latest["research_report_id"],
            analysis_created_at=latest["analysis_created_at"], engine_version="plan-phase3",
            plan={**latest["plan"], "edit_direction": {"average_shot_length_seconds": 3}},
            feasibility={"status": "ok", "checks": []}, insight_report_id=latest["insight_report_id"])
        self.assertEqual(self._gate(project_id)["state"], sb.STALE)


class VoiceAppTests(_AppCase):
    def _record_voices(self, project_id: int) -> str:
        """As the worker does: beside each voice file, its words and the settings it was made with."""
        now = main._current_voice_fingerprint(project_id)
        for segment in self._timeline(project_id):
            worker_module.write_voice_record(segment["audio_path"], voice_text=segment["voice_text"], speaker=segment["speaker"],
                                             fingerprint=now, config={}, segment_id=int(segment["id"]))
        return now

    def test_new_voice_settings_invalidate_voices_whose_words_did_not_change(self) -> None:
        project_id = self._ready()
        self._record_voices(project_id)
        self.assertEqual(self._gate(project_id)["voice_outdated"], 0)
        same = self.client.post(f"/api/projects/{project_id}/shots/generate", json={}).json()
        self.assertEqual((same["status"], same["reconcile"]["applied"]), ("saved", False), "same words, same voice: nothing to do")
        before = self._timeline(project_id)
        self.database.update_project_render_settings(project_id, voice_model="vi-VN-NamMinhNeural")
        self.assertEqual(self._gate(project_id)["voice_outdated"], len(before))
        preview = self.client.post(f"/api/projects/{project_id}/shots/generate", json={}).json()
        self.assertEqual((preview["status"], preview["reconcile"]["voice_invalidated"]), ("stale", len(before)))
        self.assertEqual({tuple(item["changes"]) for item in preview["reconcile"]["scenes"]}, {("voice_config",)})
        self.client.post(f"/api/projects/{project_id}/shots/generate", json={"force": True})
        after = self._timeline(project_id)
        self.assertEqual([(item["id"], item["voice_text"], item["visual_path"]) for item in after],
                         [(item["id"], item["voice_text"], item["visual_path"]) for item in before])
        self.assertEqual({item["audio_path"] for item in after}, {""}, "every voice made with the old settings goes")
        self.assertEqual(self._gate(project_id)["voice_outdated"], 0)

    def test_the_worker_names_each_voice_by_its_row_and_words_and_records_how_it_was_made(self) -> None:
        project_id = self._ready()
        script_id = int(self.database.get_latest_project_script(project_id)["id"])
        provider = "google_gemini_3_8_flash_tts"
        job = self.database.create_project_job(project_id, script_id, "voiceover", provider, force=True)

        def speak(text, output_path, **options):
            Path(output_path).write_bytes(b"RIFF" + text.encode("utf-8"))
            return {"model": "gemini-3.8-flash-tts", "voice": options.get("voice")}

        with mock.patch.object(worker_module.gemini_tts, "synthesize", side_effect=speak), \
                mock.patch.object(worker_module, "media_duration_seconds", return_value=2.0):
            worker_module.run_voiceover_job(self.database, job, self.tmp / "artifacts", "")
        settings = self.database.get_project_render_settings(project_id)
        expected = worker_module.voice_fingerprint(provider, settings)
        for segment in self._timeline(project_id):
            name = Path(segment["audio_path"]).name
            self.assertRegex(name, rf"^voice-s{segment['id']}-[0-9a-f]{{12}}\.wav$")
            self.assertNotIn(f"{int(segment['segment_index']):03d}", name.split("-")[1], "never the scene's place")
            record = worker_module.read_voice_record(segment["audio_path"])
            self.assertEqual((record["fingerprint"], record["voice_text"], record["segment_id"]),
                             (expected, segment["voice_text"], segment["id"]))
        self.assertEqual(len({item["audio_path"] for item in self._timeline(project_id)}), len(self._timeline(project_id)))

    def test_timeline_row_ids_are_never_reused(self) -> None:
        project_id = int(self.database.create_idea_project("x", title="x")["id"])
        script_id = int(self.database.create_project_script(project_id, script_title="x", main_content="x")["id"])
        first = self.database.create_project_timeline(project_id, script_id, [{"segment_index": 1, "voice_text": "a"}])[0]["id"]
        with self.database._connect() as connection:
            connection.execute("DELETE FROM project_timeline_segments WHERE id = ?", (first,))
            ddl = connection.execute("SELECT sql FROM sqlite_master WHERE name = 'project_timeline_segments'").fetchone()[0]
        second = self.database.create_project_timeline(project_id, script_id, [{"segment_index": 1, "voice_text": "b"}])[0]["id"]
        self.assertIn("AUTOINCREMENT", ddl.upper())
        self.assertGreater(second, first)


class AgentAndGateCostTests(_AppCase):
    def _segments(self, project_id: int, prompt: str) -> list[dict]:
        board = self._gate(project_id)["storyboard"]
        return [{"segment_index": n, "voice_text": scene["narration_text"], "visual_prompt": f"{prompt} {n}"}
                for n, scene in enumerate(sb.scenes(board), start=1)]

    def test_f3_an_agents_timeline_writes_nothing_while_the_sync_it_needs_is_not_forced(self) -> None:
        project_id = self._ready()
        segment = self._timeline(project_id)[1]
        # The timeline voiced other words for one scene: re-syncing it would cost that scene's voice.
        self.database.update_project_timeline_segment(int(segment["id"]), voice_text="Lời không có trong kịch bản.")
        before = self._timeline(project_id)
        response = self.client.post(f"/api/projects/{project_id}/steps/timeline",
                                    json={"options": {"segments": self._segments(project_id, "Sơ đồ"), "force": False}})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        self.assertEqual((result["status"], result["stale"], result["reconcile"]["voice_invalidated"]), ("stale", True, 1))
        self.assertEqual(self._timeline(project_id), before, "not even the picture fields")
        forced = self.client.post(f"/api/projects/{project_id}/steps/timeline",
                                  json={"options": {"segments": self._segments(project_id, "Sơ đồ"), "force": True}})
        self.assertEqual((forced.status_code, forced.json()["result"]["status"]), (200, "saved"), forced.text)
        after = self._timeline(project_id)
        self.assertEqual([item["visual_prompt"] for item in after], [f"Sơ đồ {n}" for n in range(1, len(after) + 1)],
                         "each scene's own picture field, row for row")
        fixed = next(item for item in after if item["id"] == segment["id"])
        self.assertEqual((fixed["voice_text"], fixed["audio_path"]), (segment["voice_text"], ""))
        self.assertEqual(self._gate(project_id)["state"], sb.CURRENT)

    def test_f4_an_agents_regrouping_costs_no_voice_without_force(self) -> None:
        project_id = self._ready()
        lines = [line["text"] for line in sb.document_lines(self._script(project_id)["document"])]
        shots_before, timeline_before = self.database.list_project_shots(project_id, script_id=int(self._script(project_id)["id"])), \
            self._timeline(project_id)
        options = {"shots": [{"shot_index": n, "narration": text} for n, text in enumerate(lines, start=1)]}
        default = self.client.post(f"/api/projects/{project_id}/steps/shots", json={"options": options}).json()["result"]
        self.assertEqual((default["status"], default["reconcile"]["applied"]), ("stale", False))
        self.assertGreater(default["reconcile"]["voice_invalidated"], 0)
        self.assertEqual(self.database.list_project_shots(project_id, script_id=int(self._script(project_id)["id"])), shots_before)
        self.assertEqual(self._timeline(project_id), timeline_before)
        forced = self.client.post(f"/api/projects/{project_id}/steps/shots", json={"options": {**options, "force": True}}).json()["result"]
        self.assertEqual(forced["status"], "saved")
        self.assertEqual(self._gate(project_id)["storyboard"]["grouping"], "supplied")

    def test_f7_only_the_status_reads_the_voice_records(self) -> None:
        project_id = self._ready()
        with mock.patch.object(main, "read_voice_record", wraps=main.read_voice_record) as read:
            gate, _ = main._storyboard_gate(project_id)
            main._steps_done(project_id)
            main._describe_steps(project_id, main._steps_done(project_id))
            self.assertEqual(self._voice(project_id).status_code, 200)
            self.assertEqual(read.call_count, 0, "the gate on every door reads no voice file")
            self.assertNotIn("voice_outdated", gate)
            body = self._gate(project_id)
            self.assertEqual(read.call_count, len(self._timeline(project_id)), "the status reads one per scene")
        self.assertEqual(body["voice_outdated"], 0)


class RegressionTests(_AppCase):
    def test_reup_cut_by_dialogue_keeps_working_as_its_own_mode(self) -> None:
        turns = [{"order": 1, "speaker": "Người dẫn", "line": "Ngày xưa có hai anh em.", "start_seconds": 0, "end_seconds": 5},
                 {"order": 2, "speaker": "Cha", "line": "Các con phải thương nhau.", "start_seconds": 5, "end_seconds": 9}]
        project_id = planned_project(self.database, analysis={
            "topic": "Hai anh em", "content_summary": "Chuyện hai anh em.", "dialogue": turns, "language": "vi", "limitations": []})
        self.assertEqual(self.client.post(f"/api/projects/{project_id}/script/generate", json={"options": {}}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/projects/{project_id}/timeline/from-dialogue").status_code, 200)
        gate = self._gate(project_id)
        self.assertEqual((gate["mode"], gate["state"], gate["applies"], gate["blocked"]), ("reup", sb.NOT_APPLICABLE, False, ""))
        self.assertEqual(self._voice(project_id).status_code, 200)
        translated = lambda system, user, schema, **options: {"lines": [  # noqa: E731
            {"segment_index": item["segment_index"], "text": f"Line {item['segment_index']}."} for item in self._timeline(project_id)]}
        with mock.patch.object(main, "_call_orchestrator_json", translated):
            self.assertEqual(self.client.post(f"/api/projects/{project_id}/script/translate?target_language=en").status_code, 200)
        self.assertEqual([item["voice_text"] for item in self._timeline(project_id)], ["Line 1.", "Line 2."])
        self.assertEqual((self._gate(project_id)["mode"], self._voice(project_id).status_code), ("reup", 200))

    def test_the_legacy_workflow_is_not_gated(self) -> None:
        project = self.database.create_idea_project("Kịch bản nhập thủ công", title="Dán tay")
        project_id = int(project["id"])
        self.database.create_project_script(project_id, script_title="x", hook="Mở đầu.", main_content="Câu một.\nCâu hai.", cta="Hết.")
        self.assertEqual(self.client.post(f"/api/projects/{project_id}/shots/generate", json={}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/projects/{project_id}/timeline/generate", json={}).status_code, 200)
        self.assertEqual(self._voice(project_id).status_code, 200)
        segment = self._timeline(project_id)[0]
        self.assertEqual(self.client.patch(f"/api/timeline/{segment['id']}", json={"voice_text": "Mở đầu khác."}).status_code, 200)
        gate = self._gate(project_id)
        self.assertEqual((gate["state"], gate["mode"], gate["applies"], gate["blocked"]), (sb.NOT_APPLICABLE, "legacy", False, ""))
        self.assertEqual(self.database.list_project_storyboards(project_id), [])


if __name__ == "__main__":
    unittest.main()
