"""Bước 5.3 · T5 · the planner: the current storyboard's scenes given an edit in the EditDocument.

    run_step("edit_plan") ─→ _plan_edit_document ─→ edit_store.sync() ─→ one model call for the scenes that need
        an edit ─→ edit_store.plan_scenes() (one version) ─→ (confirmed_apply) T4 _apply_edit_document ─→ timeline

The planner works only from current inputs - the gate's current storyboard of
the current script, voices made with the project's settings - and otherwise
makes no document at all. It plans the scenes without an edit or with a stale
one, never one whose edit still holds, so planning the same storyboard twice
plans nothing. The model's answer is matched to each scene by its timeline
row (segment_id), never by place. Overlays pass the script's text checks.
Nothing is applied unless the caller confirms. Every test runs on the
suite's temporary database; the model is faked.
"""

from __future__ import annotations

import json
import re
from unittest import mock

from tests.test_edit_store import _StoreCase
from tests.test_storyboard_gate import PLAN
from youtube_monitor import edit_document as ed, edit_planner as ep, edit_store as es, main, production_worker as worker_module
from youtube_monitor.database import EDIT_APPLY_KIND, EDIT_DOCUMENT_KIND
from youtube_monitor.llm_client import LlmError

_SCENE = re.compile(r"\[segment_id=(\d+)\] \(([\d.]+)s")


class Director:
    """The edit planner's model: one answer per scene it is shown, by segment_id - or what a test makes it do."""

    def __init__(self) -> None:
        self.calls: list[list[int]] = []
        self.skip: set[int] = set()
        self.reverse = False
        self.extra: list[dict] = []
        self.overlay_text = "Ý chính của cảnh"
        self.fail = False

    def __call__(self, system_prompt, user_prompt, schema, **_):
        shown = [(int(found), float(seconds)) for found, seconds in _SCENE.findall(user_prompt)]
        self.calls.append([segment_id for segment_id, _ in shown])
        if self.fail:
            raise LlmError("model down")
        scenes = [{"segment_id": segment_id, "kind": "image", "transition": "cut", "effect": "zoom_in",
                   "reason": f"r-{segment_id}", "note": f"note-{segment_id}",
                   "overlays": [{"kind": "label", "text": self.overlay_text, "position": "top_left", "style": "clean",
                                 "animation": "fade", "start_seconds": 0.0, "end_seconds": round(seconds / 2, 3)}]}
                  for segment_id, seconds in shown if segment_id not in self.skip]
        if self.reverse:
            scenes.reverse()
        return {"pacing": "nhanh", "scenes": scenes + self.extra}


class _PlannerCase(_StoreCase):
    def setUp(self) -> None:
        super().setUp()
        self.director = Director()
        script_model = self.model

        def route(system_prompt, user_prompt, schema, **options):
            if schema is main._EDIT_DOCUMENT_PLAN_SCHEMA:
                return self.director(system_prompt, user_prompt, schema, **options)
            return script_model(system_prompt, user_prompt, schema, **options)

        for name, value in (("_call_orchestrator_json", route),
                            ("scene_speech_timing", lambda segment: {"duration_seconds": float(segment.get("duration_seconds") or 1),
                                                                     "words": [], "timing_basis": "estimated", "audio_signature": ""})):
            patcher = mock.patch.object(main, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _fresh(self, **setup) -> None:
        self.project_id, self.script_id = self._project() if not setup else self._project_with(**setup)

    def _project_with(self, **setup) -> tuple[int, int]:
        project_id = self._ready(**setup)
        return project_id, int(self.database.get_latest_project_script(project_id)["id"])

    def _plan_step(self, **options) -> dict:
        return main.run_project_step(self.project_id, "edit_plan", options)["result"]

    def _doc(self) -> dict | None:
        script_id = int(self.database.get_latest_project_script(self.project_id)["id"])
        row = self.database.get_latest_project_storyboard(self.project_id, script_id=script_id)
        found = es.current(self.database, self.project_id, script_id, row)
        return found.get("document")

    def _count(self, kind: str) -> int:
        with self.database._connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM project_director_artifacts WHERE project_id = ? AND kind = ?",
                                      (self.project_id, kind)).fetchone()[0]

    def _scene_by_segment(self, document: dict) -> dict[int, dict]:
        return {item["segment_id"]: item for item in document["scenes"]}

    def _reword(self, section: int = 1) -> None:
        at = self._first_of_section(self.project_id, section)
        self._patch_lines(self.project_id, lambda lines: lines.__setitem__(at, lines[at].replace(" ", " mỗi ", 1).rsplit(" ", 1)[0] + "."))


# ===========================================================================
# First plan, idempotency, versions
# ===========================================================================

class FirstPlanTests(_PlannerCase):
    def setUp(self) -> None:
        super().setUp()
        self._fresh()

    def test_the_first_plan_makes_the_document_and_gives_every_scene_with_a_row_its_edit(self) -> None:
        self.assertEqual(self._count(EDIT_DOCUMENT_KIND), 0)
        result = self._plan_step()
        document = self._doc()
        rows = self._timeline(self.project_id, self.script_id)
        self.assertEqual(result["status"], ep.PLANNED)
        self.assertEqual(len(result["planned"]), len(rows))
        self.assertEqual(self.director.calls, [[row["id"] for row in rows]], "one call, every scene, by its row")
        self.assertTrue(all(item["status"] == ed.READY for item in document["scenes"]))
        self.assertEqual(document["provenance"]["script_id"], self.script_id)
        self.assertEqual(document["provenance"]["storyboard_hash"], result["storyboard_hash"])
        self.assertEqual(self._count(EDIT_DOCUMENT_KIND), 2, "the document's first version, then the planned one")

    def test_the_answer_is_matched_by_segment_id_never_by_place(self) -> None:
        self.director.reverse = True
        self._plan_step()
        for segment_id, item in self._scene_by_segment(self._doc()).items():
            self.assertEqual(item["edit"]["visual"]["edit_note"], f"note-{segment_id}")
            self.assertEqual(item["segment_id"], segment_id)

    def test_planning_names_no_picture_and_applies_nothing_unless_confirmed(self) -> None:
        before = self._timeline_edit(self.project_id, self.script_id)
        result = self._plan_step()
        self.assertNotIn("applied", result)
        self.assertTrue(all("visual_path" not in item["edit"]["visual"] for item in self._doc()["scenes"]))
        self.assertEqual(self._timeline_edit(self.project_id, self.script_id), before)
        self.assertEqual(self._count(EDIT_APPLY_KIND), 0)
        self.assertIn("edit_plan", main._steps_done(self.project_id), "the step reads as done from the EditDocument")

    def test_the_same_inputs_twice_plan_nothing_and_keep_every_version(self) -> None:
        self._plan_step()
        versions = self._count(EDIT_DOCUMENT_KIND)
        again = self._plan_step()
        self.assertEqual((again["status"], again["planned"], len(self.director.calls)), (ep.UNCHANGED, [], 1))
        self.assertEqual(self._count(EDIT_DOCUMENT_KIND), versions)

    def test_a_replan_of_named_scenes_is_a_new_version_of_only_those(self) -> None:
        self._plan_step()
        first = self._doc()
        key = first["scenes"][1]["scene_key"]
        self.director.overlay_text = "Một ý khác"
        again = self._plan_step(scene_keys=[key], replan=True)
        document = self._doc()
        self.assertEqual((again["status"], again["planned"]), (ep.PLANNED, [key]))
        self.assertEqual(document["based_on"], first["document_hash"])
        self.assertEqual(document["scenes"][1]["edit"]["layers"]["overlays"][0]["text"], "Một ý khác")
        self.assertEqual(document["scenes"][0]["edit"], first["scenes"][0]["edit"], "the others as they were")

    def test_an_unknown_scene_is_refused(self) -> None:
        with self.assertRaises(main.HTTPException) as refused:
            self._plan_step(scene_keys=["sk-nope"])
        self.assertEqual(refused.exception.status_code, 422)


# ===========================================================================
# Only current inputs make a document
# ===========================================================================

class CurrentInputTests(_PlannerCase):
    def setUp(self) -> None:
        super().setUp()
        self._fresh()

    def test_a_stale_storyboard_plans_nothing_and_makes_no_document(self) -> None:
        self._reword()   # the script changed in place; the storyboard has not been cut again
        result = main._plan_edit_document(self.project_id, self.database.get_production_project(self.project_id))
        self.assertEqual(result["status"], ep.NOT_CURRENT)
        self.assertEqual((self._count(EDIT_DOCUMENT_KIND), self.director.calls), (0, []))

    def test_a_new_script_without_its_storyboard_plans_nothing(self) -> None:
        self._plan_step()
        versions = self._count(EDIT_DOCUMENT_KIND)
        old = self._script(self.project_id)
        lines = old["main_content"].split("\n")
        at = self._first_of_section(self.project_id, 1)
        lines[at] = lines[at].replace(" ", " mỗi ", 1).rsplit(" ", 1)[0] + "."
        main.run_project_step(self.project_id, "script", {"revision": {"base_script_id": old["id"],
                                                                       "fields": {"main_content": "\n".join(lines)}, "source": "t"}})
        result = main._plan_edit_document(self.project_id, self.database.get_production_project(self.project_id))
        self.assertEqual(result["status"], ep.NOT_CURRENT)
        self.assertEqual(self._count(EDIT_DOCUMENT_KIND), versions, "the old script's document is not taken as current")
        new_id = int(self.database.get_latest_project_script(self.project_id)["id"])
        self.assertEqual(self.database.list_edit_documents(self.project_id, new_id), [])

    def test_an_old_document_whose_storyboard_is_no_longer_current_is_neither_planned_nor_applied(self) -> None:
        self._plan_step()
        versions = self._count(EDIT_DOCUMENT_KIND)
        old_row = self._board_row(self.project_id, self.script_id)
        self._reword()   # the planned document's storyboard is no longer the script's
        result = main._plan_edit_document(self.project_id, self.database.get_production_project(self.project_id),
                                          confirmed_apply=True)
        self.assertEqual(result["status"], ep.NOT_CURRENT)
        self.assertNotIn("applied", result)
        self.assertEqual((self._count(EDIT_DOCUMENT_KIND), self._count(EDIT_APPLY_KIND), len(self.director.calls)),
                         (versions, 0, 1))
        # Cut again: the document follows the new storyboard as a new version; against the old storyboard it is
        # outdated, and nothing is planned on an outdated document.
        self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={"force": True})
        new_row = self._board_row(self.project_id, self.script_id)
        self.assertNotEqual(new_row["id"], old_row["id"])
        self.assertEqual(es.current(self.database, self.project_id, self.script_id, old_row)["state"], es.OUTDATED)
        self.assertEqual(es.current(self.database, self.project_id, self.script_id, new_row)["state"], es.CURRENT)
        versions = self._count(EDIT_DOCUMENT_KIND)
        with self.assertRaises(es.EditStoreError):
            es.plan_scenes(self.database, self.project_id, self.script_id, old_row, {})
        self.assertEqual(self._count(EDIT_DOCUMENT_KIND), versions)

    def test_a_gate_row_that_is_not_the_scripts_latest_storyboard_is_not_current(self) -> None:
        old_row = self._board_row(self.project_id, self.script_id)
        self._reword()
        self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={"force": True})
        gate = {"mode": main.storyboard_engine.PLAN_MODE, "state": main.storyboard_engine.CURRENT, "voice_outdated": 0}
        with mock.patch.object(main, "_storyboard_gate", return_value=(gate, old_row)):
            result = main._plan_edit_document(self.project_id, self.database.get_production_project(self.project_id))
        self.assertEqual(result["status"], ep.NOT_CURRENT, "only the current script's latest storyboard is planned on")
        self.assertEqual(self.director.calls, [])

    def test_voices_made_with_other_settings_need_a_rebuild_first(self) -> None:
        now = main._current_voice_fingerprint(self.project_id)
        for segment in self._timeline(self.project_id, self.script_id):
            worker_module.write_voice_record(segment["audio_path"], voice_text=segment["voice_text"], speaker=segment["speaker"],
                                             fingerprint=now, config={}, segment_id=int(segment["id"]))
        self.database.update_project_render_settings(self.project_id, voice_model="vi-VN-NamMinhNeural")
        result = self._plan_step()
        self.assertEqual((result["status"], result["voice_outdated"] > 0), (ep.NEEDS_REBUILD, True))
        self.assertEqual((self._count(EDIT_DOCUMENT_KIND), self.director.calls), (0, []))

    def test_a_project_outside_the_plan_workflow_keeps_the_legacy_edit_plan(self) -> None:
        with mock.patch.object(main, "_storyboard_gate", return_value=({"mode": "legacy", "state": "not_applicable"}, None)), \
                mock.patch.object(main, "plan_project_edit", return_value={"status": "draft", "scenes": []}) as legacy, \
                mock.patch.object(main, "approve_project_edit_plan"), \
                mock.patch.object(main, "apply_project_edit_plan", return_value={"status": "ready"}):
            main._step_edit_plan(self.project_id, self.database.get_production_project(self.project_id), {})
        legacy.assert_called_once()
        self.assertEqual(self._count(EDIT_DOCUMENT_KIND), 0)


# ===========================================================================
# The storyboard changes: identity by row, only what changed is planned
# ===========================================================================

class StoryboardChangeTests(_PlannerCase):
    def _planned_project(self, **setup) -> dict:
        self._fresh(**setup)
        self._plan_step()
        return self._doc()

    def test_a_reworded_scene_alone_is_planned_again_in_a_new_version(self) -> None:
        before = self._planned_project()
        self._reword()
        self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={"force": True})
        result = self._plan_step()
        after = self._doc()
        self.assertEqual(len(result["planned"]), 1)
        changed = result["planned"][0]
        self.assertNotEqual(after["provenance"]["storyboard_hash"], before["provenance"]["storyboard_hash"])
        kept = [item for item in after["scenes"] if item["scene_key"] != changed]
        self.assertTrue(all(item["status"] == ed.READY for item in after["scenes"]))
        old = self._scene_by_segment(before)
        self.assertTrue(all(item["edit"] == old[item["segment_id"]]["edit"] for item in kept), "kept scenes kept their edit")

    def test_an_added_scene_is_planned_and_the_others_keep_their_rows_and_edits(self) -> None:
        before = self._planned_project()
        at = self._first_of_section(self.project_id, 1)
        self._patch_lines(self.project_id, lambda lines: lines.insert(at, "Mọi ý chính đều dễ nhớ khi theo dõi."))
        self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={"force": True})
        result = self._plan_step()
        after = self._doc()
        old, new = self._scene_by_segment(before), self._scene_by_segment(after)
        added = set(new) - set(old)
        self.assertTrue(added, "a new row for the new scene")
        self.assertTrue(added <= {new_scene["segment_id"] for new_scene in after["scenes"]
                                  if new_scene["scene_key"] in result["planned"]})
        for segment_id in set(old) & set(new):
            if new[segment_id]["scene_key"] not in result["planned"]:
                self.assertEqual(new[segment_id]["edit"], old[segment_id]["edit"], segment_id)
        self.assertTrue(all(item["status"] == ed.READY for item in after["scenes"]))

    def test_a_removed_scene_leaves_no_edit_on_another_row(self) -> None:
        # Short shots: one line, one scene - so dropping the line drops its scene and its row.
        before = self._planned_project(plan={**PLAN, "edit_direction": {"average_shot_length_seconds": 4}})
        at = self._first_of_section(self.project_id, 1)
        self._patch_lines(self.project_id, lambda lines: lines.pop(at))
        self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={"force": True})
        self._plan_step()
        after = self._doc()
        old, new = self._scene_by_segment(before), self._scene_by_segment(after)
        gone = set(old) - set(new)
        self.assertTrue(gone, "a row went with its scene")
        for item in after["scenes"]:
            self.assertEqual(item["edit"]["visual"]["edit_note"], f"note-{item['segment_id']}",
                             "every edit is its own row's, none moved onto another")
        removed = [orphan for orphan in after["orphans"] if orphan["reason"] == ed.REMOVED]
        self.assertTrue(removed, "the removed scene's edit is kept as an orphan, not handed on")

    def test_a_moved_scene_keeps_its_row_and_its_edit(self) -> None:
        before = self._planned_project(plan={**PLAN, "edit_direction": {"average_shot_length_seconds": 4}})
        document = self._script(self.project_id)["document"]
        at, count = self._first_of_section(self.project_id, 1), len(document["sections"][1]["spoken_lines"])
        self._patch_lines(self.project_id, lambda lines: lines.insert(at + 1, lines.pop(at + count - 1)))
        self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={})
        result = self._plan_step()
        after = self._doc()
        self.assertEqual((result["status"], result["planned"]), (ep.UNCHANGED, []), "nothing to plan: a move keeps every edit")
        old, new = self._scene_by_segment(before), self._scene_by_segment(after)
        self.assertEqual(set(old), set(new))
        self.assertNotEqual([item["segment_id"] for item in before["scenes"]], [item["segment_id"] for item in after["scenes"]])
        for segment_id, item in new.items():
            self.assertEqual(item["edit"], old[segment_id]["edit"], segment_id)

    def test_a_new_length_for_the_same_row_follows_the_voice_without_a_replan(self) -> None:
        before = self._planned_project()
        segment_id = before["scenes"][0]["segment_id"]
        old = float(before["scenes"][0]["voice"]["duration_seconds"])
        self.database.update_project_timeline_segment(segment_id, duration_seconds=int(old) * 2)
        result = self._plan_step()
        scene = self._scene_by_segment(self._doc())[segment_id]
        self.assertEqual((result["status"], scene["status"], scene["timing"]["state"]), (ep.UNCHANGED, ed.READY, ed.TIMING_RETIMED))
        self.assertEqual(scene["edit"], before["scenes"][0]["edit"], "same row, same edit, retimed through effective_edit")


# ===========================================================================
# Partial outcomes are never a success
# ===========================================================================

class OutcomeTests(_PlannerCase):
    def setUp(self) -> None:
        super().setUp()
        self._fresh()

    def test_a_scene_the_model_left_out_is_named_and_the_rest_planned(self) -> None:
        rows = self._timeline(self.project_id, self.script_id)
        self.director.skip = {rows[1]["id"]}
        result = self._plan_step()
        missing = next(item["scene_key"] for item in self._doc()["scenes"] if item["segment_id"] == rows[1]["id"])
        self.assertEqual(result["status"], ep.PARTIAL)
        self.assertEqual(list(result["problems"]), [missing])
        self.assertEqual(self._scene_by_segment(self._doc())[rows[1]["id"]]["status"], ed.NEEDS_PLAN)
        retry = self._plan_step()
        self.assertEqual((retry["status"], retry["wanted"]), (ep.BLOCKED, [missing]),
                         "only the missing scene is asked again - and nothing planned is never a success")
        self.director.skip = set()
        last = self._plan_step()
        self.assertEqual((last["status"], last["planned"]), (ep.PLANNED, [missing]))
        self.assertEqual(self.director.calls[-1], [rows[1]["id"]])

    def test_a_failed_model_call_plans_nothing(self) -> None:
        self.director.fail = True
        result = self._plan_step()
        self.assertEqual((result["status"], result["planned"]), (ep.ERROR, []))
        self.assertIn("model down", result["planner_error"])
        self.assertTrue(all(item["status"] == ed.NEEDS_PLAN for item in self._doc()["scenes"]))
        self.assertNotIn("edit_plan", main._steps_done(self.project_id))

    def test_answers_for_rows_it_was_not_shown_are_ignored(self) -> None:
        self.director.extra = [{"segment_id": 999999, "kind": "image", "transition": "cut", "effect": "static"},
                               {"segment_id": "abc", "kind": "image", "transition": "cut", "effect": "static"}]
        result = self._plan_step()
        self.assertEqual(result["status"], ep.PLANNED)
        self.assertNotIn(999999, self._scene_by_segment(self._doc()))

    def test_an_overlay_whose_words_fail_the_text_checks_is_left_out(self) -> None:
        self.director.overlay_text = "Giảm 98765 đồng"
        result = self._plan_step()
        self.assertEqual(result["status"], ep.PLANNED)
        self.assertTrue(all(item["edit"]["layers"]["overlays"] == [] for item in self._doc()["scenes"]))
        self.assertTrue(result["warnings"] and all("overlays_rejected" in item for item in result["warnings"]))

    def test_an_edit_that_cannot_fit_its_scene_leaves_that_scene_unplanned(self) -> None:
        rows = self._timeline(self.project_id, self.script_id)
        real = main._normalise_visual_transform_fields

        def too_long(entry, segment):
            transform = real(entry, segment)
            if int(segment["id"]) == rows[0]["id"]:
                transform["sound_cues"] = []
                transform["overlays"] = [{"kind": "label", "text": "x", "start_seconds": 0.0, "end_seconds": 999.0}]
            return transform

        with mock.patch.object(main, "_normalise_visual_transform_fields", side_effect=too_long):
            result = self._plan_step()
        self.assertEqual(result["status"], ep.PARTIAL)
        self.assertEqual(self._scene_by_segment(self._doc())[rows[0]["id"]]["status"], ed.NEEDS_PLAN)
        self.assertIn("không vừa cảnh", next(iter(result["problems"].values())))


# ===========================================================================
# Downstream: T4 applies what was planned - only when confirmed
# ===========================================================================

class ApplyTests(_PlannerCase):
    def setUp(self) -> None:
        super().setUp()
        self._fresh()

    def test_a_confirmed_plan_is_applied_by_t4_and_keeps_the_legacy_pictures(self) -> None:
        pictures = {row["id"]: row["visual_path"] for row in self._timeline(self.project_id, self.script_id)}
        result = self._plan_step(confirmed_apply=True)
        self.assertEqual((result["status"], result["applied"]["status"]), (ep.PLANNED, "applied"))
        for row in self._timeline(self.project_id, self.script_id):
            self.assertEqual(row["visual_path"], pictures[row["id"]], "the planner names no picture")
            self.assertEqual(row["edit_transition"], "cut")
            self.assertTrue(json.loads(row["overlays"]))

    def test_owned_rows_are_neither_retimed_nor_copied_by_the_reconcile_and_a_replan_applies(self) -> None:
        self._plan_step(confirmed_apply=True)
        owned = {row["id"]: json.loads(row["overlays"]) for row in self._timeline(self.project_id, self.script_id)}
        self._reword()
        done = self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={"force": True}).json()
        reworded = next(scene["new_segment_id"] for scene in done["reconcile"]["scenes"] if scene.get("edit_owned"))
        self.assertEqual(json.loads(self.database.get_project_timeline_segment(reworded)["overlays"]), owned[reworded], "never retimed by the reconcile")
        result = self._plan_step(confirmed_apply=True)
        self.assertEqual(len(result["planned"]), 1)
        self.assertEqual((result["applied"]["status"], result["applied"]["counts"]["conflicts"]), ("applied", 0))
        self.assertIn(reworded, [item["segment_id"] for item in result["applied"]["applied"]])

    def test_a_project_without_an_edit_document_keeps_t4_legacy_behaviour(self) -> None:
        response = self.client.post(f"/api/projects/{self.project_id}/timeline/generate", json={}).json()
        self.assertEqual(response["edit_document"], {"status": "no_document"})

    def test_a_plan_that_planned_nothing_is_not_applied_even_when_confirmed(self) -> None:
        self.director.skip = {row["id"] for row in self._timeline(self.project_id, self.script_id)}
        result = self._plan_step(confirmed_apply=True)
        self.assertEqual((result["status"], result["planned"]), (ep.BLOCKED, []))
        self.assertNotIn("applied", result)
        self.assertEqual(self._count(EDIT_APPLY_KIND), 0)

    def test_a_blocked_plan_is_never_applied(self) -> None:
        self.director.fail = True
        result = self._plan_step(confirmed_apply=True)
        self.assertEqual(result["status"], ep.ERROR)
        self.assertNotIn("applied", result)
        self.assertEqual(self._count(EDIT_APPLY_KIND), 0)


# ===========================================================================
# The library: selection, overlays, outcome
# ===========================================================================

class LibraryTests(_PlannerCase):
    def test_selection_plans_unplanned_and_stale_scenes_only(self) -> None:
        document = {"scenes": [
            {"scene_key": "a", "segment_id": 1, "status": ed.NEEDS_PLAN}, {"scene_key": "b", "segment_id": 2, "status": ed.READY},
            {"scene_key": "c", "segment_id": 3, "status": ed.STALE_CONTENT}, {"scene_key": "d", "segment_id": 4, "status": ed.VISUAL_REVIEW},
            {"scene_key": "e", "segment_id": None, "status": ed.NEEDS_PLAN}, {"scene_key": "f", "segment_id": 6, "status": ed.STALE_TIMING}]}
        wanted, left = ep.select(document)
        self.assertEqual(wanted, ["a", "c", "f"])
        self.assertEqual({item["scene_key"]: item["reason"] for item in left}, {"b": "holding", "d": "holding", "e": "no_row"})
        self.assertEqual(ep.select(document, scene_keys=["b"], replan=True)[0], ["b"])
        with self.assertRaises(ep.PlannerError):
            ep.select(document, scene_keys=["zz"])

    def test_outcome_is_never_success_while_a_scene_waits(self) -> None:
        self.assertEqual(ep.outcome([], [], {}), ep.UNCHANGED)
        self.assertEqual(ep.outcome(["a"], ["a"], {}), ep.PLANNED)
        self.assertEqual(ep.outcome(["a", "b"], ["a"], {"b": "x"}), ep.PARTIAL)
        self.assertEqual(ep.outcome(["a"], [], {"a": "x"}), ep.BLOCKED)

    def test_plan_scenes_is_one_version_based_on_the_document(self) -> None:
        self._fresh()
        script_id = self.script_id
        row = self._board_row(self.project_id, script_id)
        boot = es.sync(self.database, self.project_id, script_id, row)
        keys = [item["scene_key"] for item in boot["document"]["scenes"][:2]]
        seconds = float(boot["document"]["scenes"][0]["voice"]["duration_seconds"])
        done = es.plan_scenes(self.database, self.project_id, script_id, row, {
            keys[0]: ed.edit({"edit_transition": "cut"}),
            keys[1]: ed.edit({}, overlays=[{"kind": "text", "start_seconds": 0, "end_seconds": seconds * 50}])})
        self.assertEqual((done["created"], list(done["problems"])), (True, [keys[1]]))
        self.assertEqual(done["document"]["based_on"], boot["document_hash"])
        self.assertEqual(len(self.database.list_edit_documents(self.project_id, script_id)), 2)
        nothing = es.plan_scenes(self.database, self.project_id, script_id, row, {
            keys[1]: ed.edit({}, overlays=[{"kind": "text", "start_seconds": 0, "end_seconds": seconds * 50}])})
        self.assertEqual((nothing["created"], len(self.database.list_edit_documents(self.project_id, script_id))), (False, 2))
