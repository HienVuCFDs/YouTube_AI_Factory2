"""Bước 5 · Storyboard & Edit on screen: the page plans through T5 and shows the EditDocument as the server holds it.

The page's side is run for real in tests/step5_edit_document_ui.test.cjs
(one POST to …/steps/edit_plan, confirmed_apply only after the user
confirms, every status shown as the server said it, `force` in the body).
This file runs that, and pins the server's side the page reads:

* GET …/edit-document says where the EditDocument stands scene by scene -
  planned, stale, not planned, and whether the row holds that very edit - and
  reads only: no version, no apply, no sync;
* the storyboard routes take `force` from the JSON body (where the page now
  sends it), not the query string;
* planning without confirmed_apply leaves the timeline as it was; T4 applies
  the planned scenes at the next sync of the storyboard (shots/timeline
  generate) - the behaviour the page names to the user.
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

_NODE_TEST = Path(__file__).with_name("step5_edit_document_ui.test.cjs")


def test_the_page_runs_its_step5_contract_for_real() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node không có trên máy chạy test")
    result = subprocess.run([node, "--test", str(_NODE_TEST)], capture_output=True, text=True, timeout=120)
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
