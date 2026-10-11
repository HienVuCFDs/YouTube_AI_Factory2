"""Bước 5 · Storyboard & Edit on screen: the page plans through T5 and shows the EditDocument as the server holds it.

The page's side is run for real in tests/step5_edit_document_ui.test.cjs and
tests/step5_storyboard_layout.test.cjs (one POST to …/steps/edit_plan, confirmed_apply only after the user
confirms, every status shown as the server said it, `force` in the body).
This file runs that, and pins the server's side the page reads:

* GET …/edit-document says where the EditDocument stands scene by scene -
  planned, stale, not planned, and whether the row holds that very edit - and
  reads only: no version, no apply, no sync;
* the storyboard routes take `force` from the JSON body (where the page now
  sends it), not the query string;
* planning without confirmed_apply leaves the timeline as it was; T4 applies
  the planned scenes at the next sync of the storyboard (shots/timeline
  generate) - the behaviour the page names to the user;
* what the scene form's save relies on: the routes answer with the row as they
  stored it, refuse with a 4xx before they write, and the project read holds
  both rows the form checks a save against;
* a picture edit through the timeline route writes visual_prompt, a column the
  EditDocument may own: since P2-4 · F1 it is neither a conflict nor written over
  by an apply that does not write that column (VisualPromptOwnershipRiskTests).
  Routing hand edits through the EditDocument itself is still T6/T7.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from tests.test_edit_planner import _PlannerCase
from youtube_monitor import main
from youtube_monitor.database import EDIT_APPLY_KIND, EDIT_DOCUMENT_KIND

_NODE_TESTS = ("step5_edit_document_ui.test.cjs", "step5_storyboard_layout.test.cjs")


@pytest.mark.parametrize("script", _NODE_TESTS)
def test_the_page_runs_its_step5_contract_for_real(script: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node không có trên máy chạy test")
    result = subprocess.run([node, "--test", str(Path(__file__).with_name(script))], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (result.stdout + result.stderr)[-3000:]


class _EditUiCase(_PlannerCase):
    def setUp(self) -> None:
        super().setUp()
        self._fresh()

    def _read(self, project_id: int | None = None) -> dict:
        response = self.client.get(f"/api/projects/{project_id or self.project_id}/edit-document")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _scenes(self, answer: dict) -> dict[int, dict]:
        return {item["segment_id"]: item for item in answer["scenes"]}

    def _stored(self) -> tuple[int, int]:
        return self._count(EDIT_DOCUMENT_KIND), self._count(EDIT_APPLY_KIND)


class EditDocumentReadTests(_EditUiCase):
    def test_an_unknown_project_is_not_found(self) -> None:
        self.assertEqual(self.client.get("/api/projects/987654/edit-document").status_code, 404)

    def test_before_any_plan_there_is_no_document_and_reading_makes_none(self) -> None:
        answer = self._read()
        self.assertEqual((answer["mode"], answer["state"], answer["scenes"]), ("plan", "missing", []))
        self.assertEqual(self._stored(), (0, 0), "a read never bootstraps a document")

    def test_planned_scenes_read_as_planned_and_not_applied_until_applied(self) -> None:
        self._plan_step()
        stored = self._stored()
        answer = self._read()
        rows = self._timeline(self.project_id, self.script_id)
        self.assertEqual(answer["state"], "current")
        self.assertEqual(set(self._scenes(answer)), {row["id"] for row in rows})
        self.assertTrue(all(item["status"] == "ready" and item["applied"] == "not_applied" for item in answer["scenes"]))
        self.assertEqual(answer["counts"], {"scenes": len(rows), "planned": len(rows), "needs_plan": 0, "applied": 0, "stale": 0})
        self.assertEqual(self._stored(), stored, "reading writes nothing")
        self._plan_step(confirmed_apply=True)
        answer = self._read()
        self.assertTrue(all(item["applied"] == "applied" for item in answer["scenes"]))
        self.assertEqual(answer["counts"]["applied"], len(rows))

    def test_a_replanned_scene_reads_older_until_its_new_edit_is_applied(self) -> None:
        self._plan_step(confirmed_apply=True)
        first = self._doc()["scenes"][1]
        self.director.overlay_text = "Một ý khác"
        self._plan_step(scene_keys=[first["scene_key"]], replan=True)
        scenes = self._scenes(self._read())
        self.assertEqual(scenes[first["segment_id"]]["applied"], "older")
        self.assertTrue(all(item["applied"] == "applied" for key, item in scenes.items() if key != first["segment_id"]))

    def test_a_scene_left_unplanned_reads_needs_plan_with_nothing_to_apply(self) -> None:
        rows = self._timeline(self.project_id, self.script_id)
        self.director.skip = {rows[0]["id"]}
        self._plan_step()
        missing = self._scenes(self._read())[rows[0]["id"]]
        self.assertEqual((missing["status"], missing["applied"]), ("needs_plan", None))

    def test_a_reworded_scene_reads_stale_once_the_document_follows_the_storyboard(self) -> None:
        self._plan_step()
        self._reword()
        self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={"force": True})
        answer = self._read()
        stale = [item for item in answer["scenes"] if item["status"].startswith("stale_") or item["status"] == "needs_plan"]
        self.assertTrue(stale, "the reworded scene is not shown as planned")
        self.assertEqual(answer["counts"]["planned"] + answer["counts"]["needs_plan"] + answer["counts"]["stale"],
                         answer["counts"]["scenes"])

    def test_a_project_outside_the_plan_workflow_has_no_edit_document(self) -> None:
        with mock.patch.object(main, "_storyboard_gate", return_value=({"mode": "legacy", "state": "not_applicable"}, None)):
            answer = self._read()
        self.assertEqual((answer["mode"], answer["state"], answer["scenes"]), ("legacy", "not_applicable", []))

    def test_a_broken_apply_record_is_named_not_read_as_unapplied(self) -> None:
        self._plan_step(confirmed_apply=True)
        with self.database._connect() as connection:
            connection.execute("UPDATE project_director_artifacts SET payload_json = '{' WHERE project_id = ? AND kind = ?",
                               (self.project_id, EDIT_APPLY_KIND))
        answer = self._read()
        self.assertEqual(answer["state"], "error")
        self.assertIn("không đọc được", answer["detail"])


class ApplyOnlyWhenAskedTests(_EditUiCase):
    def _edit_columns(self) -> list[tuple]:
        return [(row["id"], row["edit_transition"], row["edit_note"], row["overlays"])
                for row in self._timeline(self.project_id, self.script_id)]

    def test_planning_without_confirmation_leaves_the_timeline_and_t4_applies_at_the_next_sync(self) -> None:
        before = self._edit_columns()
        result = self._plan_step()
        self.assertNotIn("applied", result)
        self.assertEqual(self._edit_columns(), before, "nothing is applied by planning")
        self.assertEqual(self._count(EDIT_APPLY_KIND), 0)
        # The next sync of the storyboard is T4's door: it applies the planned scenes (the page says so).
        done = self.client.post(f"/api/projects/{self.project_id}/timeline/generate", json={}).json()
        self.assertEqual(done["edit_document"]["status"], "applied")
        self.assertTrue(all(row[2] == f"note-{row[0]}" for row in self._edit_columns()), "each row its own scene's edit")
        self.assertTrue(all(item["applied"] == "applied" for item in self._read()["scenes"]))


class ForceIsReadFromTheBodyTests(_EditUiCase):
    def test_force_in_the_body_reaches_the_storyboard_and_in_the_query_it_does_not(self) -> None:
        for route, target in (("shots/generate", "_sync_storyboard"), ("timeline/generate", "_storyboard_timeline")):
            with self.subTest(route=route):
                with mock.patch.object(main, target, wraps=getattr(main, target)) as seen:
                    self.client.post(f"/api/projects/{self.project_id}/{route}?force=true")
                    self.client.post(f"/api/projects/{self.project_id}/{route}", json={"force": True})
                    self.client.post(f"/api/projects/{self.project_id}/{route}", json={})
                self.assertEqual([call.kwargs["force"] for call in seen.call_args_list], [False, True, False])


class PageContractTests(_EditUiCase):
    def test_the_step_answers_with_the_fields_the_page_reads(self) -> None:
        response = self.client.post(f"/api/projects/{self.project_id}/steps/edit_plan", json={"options": {}})
        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertTrue({"status", "planned", "wanted", "problems"} <= set(result), sorted(result))
        applied = self.client.post(f"/api/projects/{self.project_id}/steps/edit_plan",
                                   json={"options": {"confirmed_apply": True}}).json()["result"]["applied"]
        self.assertTrue({"status", "counts"} <= set(applied))
        self.assertTrue({"applied", "conflicts", "skipped"} <= set(applied["counts"]))
        self.assertIsInstance(applied["counts"]["skipped"], dict)
        json.dumps(applied)


class SceneSaveContractTests(_EditUiCase):
    """The routes the scene form saves through, as they are: a field left out is left alone.

    The form relies on exactly this to keep a scene's voice when only its
    picture or length is edited, and drops the voice only by sending
    audio_path '' with changed words.
    """

    def _row(self) -> dict:
        return self._timeline(self.project_id, self.script_id)[0]

    def _shot(self, row: dict) -> dict:
        return self.database.get_project_shot(int(row["shot_id"]))

    def test_a_picture_or_length_edit_without_audio_path_keeps_the_voice(self) -> None:
        row = self._row()
        self.assertTrue(row["audio_path"])
        for body in ({"visual_prompt": "Đồi cây phong lúc hoàng hôn"}, {"duration_seconds": int(row["duration_seconds"]) + 1}):
            with self.subTest(body=body):
                response = self.client.patch(f"/api/timeline/{row['id']}", json=body)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["segment"]["audio_path"], row["audio_path"], "the voice is untouched")
        shot = self._shot(row)
        response = self.client.patch(f"/api/shots/{shot['id']}", json={"visual_prompt": "Đồi cây phong lúc hoàng hôn"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._row()["audio_path"], row["audio_path"])

    def test_audio_path_empty_is_the_explicit_way_to_drop_the_voice(self) -> None:
        row = self._row()
        response = self.client.patch(f"/api/timeline/{row['id']}", json={"audio_path": ""})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["segment"]["audio_path"], "")

    def test_the_words_of_a_planned_scene_are_refused_here_and_nothing_changes(self) -> None:
        row = self._row()
        shot = self._shot(row)
        for url, body in ((f"/api/shots/{shot['id']}", {"narration": "Lời khác hẳn."}),
                          (f"/api/timeline/{row['id']}", {"voice_text": "Lời khác hẳn.", "subtitle_text": "Lời khác hẳn.", "audio_path": ""})):
            with self.subTest(url=url):
                response = self.client.patch(url, json=body)
                self.assertEqual(response.status_code, 409, response.text)
        after = self._row()
        self.assertEqual((after["voice_text"], after["audio_path"]), (row["voice_text"], row["audio_path"]))

    def test_the_same_words_with_other_spacing_are_not_a_change(self) -> None:
        row = self._row()
        spaced = "  " + "  ".join(str(row["voice_text"]).split()) + " "
        response = self.client.patch(f"/api/timeline/{row['id']}", json={"voice_text": spaced})
        self.assertEqual(response.status_code, 200, response.text)

    def test_lengths_are_whole_seconds(self) -> None:
        row = self._row()
        self.assertEqual(self.client.patch(f"/api/timeline/{row['id']}", json={"duration_seconds": 6.5}).status_code, 422)
        self.assertEqual(self.client.patch(f"/api/shots/{row['shot_id']}", json={"duration_seconds": 6.5}).status_code, 422)
        self.assertEqual(self._row()["audio_path"], row["audio_path"])

    def test_each_route_answers_with_the_row_as_it_stored_it(self) -> None:
        # The form takes these answers as the new starting point of the fields it wrote.
        row = self._row()
        shot = self._shot(row)
        answer = self.client.patch(f"/api/shots/{shot['id']}", json={"visual_prompt": "  Hình đã gõ  "})
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(answer.json()["shot"]["visual_prompt"], "Hình đã gõ", "stored stripped, answered as stored")
        answer = self.client.patch(f"/api/timeline/{row['id']}", json={"visual_prompt": "  Hình đã gõ  ", "duration_seconds": 7})
        self.assertEqual(answer.status_code, 200, answer.text)
        segment = answer.json()["segment"]
        self.assertEqual((segment["visual_prompt"], segment["duration_seconds"]), ("Hình đã gõ", 7))
        self.assertEqual(segment["audio_path"], row["audio_path"])

    def test_the_project_read_the_form_checks_a_save_against_says_what_the_routes_answered(self) -> None:
        # A save compares the project read with what the routes answered: they must say the same values,
        # or the form's own write would read as someone else's change.
        row = self._row()
        shot = self._shot(row)
        shot_answer = self.client.patch(f"/api/shots/{shot['id']}", json={"visual_prompt": "Hình đã gõ", "duration_seconds": 7}).json()["shot"]
        segment_answer = self.client.patch(f"/api/timeline/{row['id']}", json={"visual_prompt": "Hình đã gõ", "duration_seconds": 7}).json()["segment"]
        bundle = self.client.get(f"/api/projects/{self.project_id}").json()
        shots = {int(item["id"]): item for item in bundle["latest_shots"]}
        segments = {int(item["id"]): item for item in bundle["latest_timeline"]}
        for field in ("narration", "visual_prompt", "duration_seconds"):
            self.assertEqual(shots[int(shot["id"])][field], shot_answer[field], field)
        for field in ("voice_text", "subtitle_text", "audio_path", "visual_prompt", "duration_seconds"):
            self.assertEqual(segments[int(row["id"])][field], segment_answer[field], field)

    def test_an_unknown_row_is_refused_with_a_4xx_and_nothing_is_written(self) -> None:
        # The form reads a 4xx as "refused before writing"; anything else as "unknown".
        row = self._row()
        self.assertEqual(self.client.patch("/api/shots/987654", json={"visual_prompt": "x"}).status_code, 404)
        self.assertEqual(self.client.patch("/api/timeline/987654", json={"visual_prompt": "x"}).status_code, 404)
        self.assertEqual(self._row()["visual_prompt"], row["visual_prompt"])


class VisualPromptOwnershipRiskTests(_EditUiCase):
    """P2-4 · F1: visual_prompt is a column the EditDocument may own (edit_store._VISUAL_COLUMNS), but a plan that
    names no picture never writes it - so the scene form's picture edit (PATCH /api/timeline/{id}) is neither a
    conflict nor written over: an apply compares only the columns it writes (edit_apply.ScopedCheck).
    """

    def test_a_picture_edit_on_an_applied_row_is_kept_and_never_makes_the_next_apply_a_conflict(self) -> None:
        self._plan_step(confirmed_apply=True)
        row = self._timeline(self.project_id, self.script_id)[0]
        scenes = {item["segment_id"]: item for item in self._read()["scenes"]}
        self.assertEqual(scenes[row["id"]]["applied"], "applied")
        response = self.client.patch(f"/api/timeline/{row['id']}", json={"visual_prompt": "Mô tả hình sửa tay"})
        self.assertEqual(response.status_code, 200, response.text)
        answer = self.client.post(f"/api/projects/{self.project_id}/timeline/generate", json={}).json()["edit_document"]
        self.assertEqual((answer["status"], answer["conflicts"]), ("unchanged", []), "nothing to write, nothing in the way")
        self.assertEqual(self._timeline(self.project_id, self.script_id)[0]["visual_prompt"], "Mô tả hình sửa tay",
                         "the hand edit stays; the EditDocument does not write over it")
