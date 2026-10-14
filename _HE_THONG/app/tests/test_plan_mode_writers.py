"""Bước 05 · T7 final · the last writers of a planned project's scene edits go through its EditDocument.

1. A scene that has no edit of its own yet (needs_plan) plays the layers its row had before any EditDocument (the
   legacy orphan). A hand edit of some of its parts (T6a, the cleanups below) is made on those layers - never on an
   empty edit that would write empty layers over them with no conflict.
2. POST /api/projects/{id}/timeline/cleanups: in the plan workflow the cleanups become one new EditDocument version
   (every scene of the current script), then those scenes are applied; outside it, the rows as before.
3. scene-jobs/batch: in the plan workflow a GIF batch never rewrites a scene's planned kind (visual_kind is the
   EditDocument's); outside it, as before.
4. The agents (Director, Media): in the plan workflow they never write a scene's kind or rebuild its timeline.

Every test runs on the test suite's temporary database (tests/conftest.py), with fake models; no app, no worker.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

from tests.test_legacy_timeline_writes import CLEANUP, REFUSED, _LegacyCase, _RouteCase
from youtube_monitor import main

LEGACY_OVERLAYS = [{"kind": "text", "text": "Chữ cũ", "start_seconds": 0.0, "end_seconds": 1.0}]
LEGACY_SOUND = [{"cue": "whoosh", "start_seconds": 0.0, "end_seconds": 0.5}]


class _PlannedCase(_RouteCase):
    """A planned project; its first row holds layers from before any EditDocument."""

    def setUp(self) -> None:
        super().setUp()
        self.database.save_segment_edit_layers(self.target, overlays=LEGACY_OVERLAYS, sound_cues=LEGACY_SOUND)
        self._sync(self.project_id, self.script_id)    # the first EditDocument: the row's layers held as a legacy orphan

    def _layers_of(self, segment_id: int) -> tuple:
        row = self._seg(segment_id)
        return ([item["text"] for item in json.loads(row["overlays"] or "[]")],
                [item["cue"] for item in json.loads(row["sound_cues"] or "[]")])


class LegacyOnlySceneTests(_PlannedCase):
    def test_a_hand_edit_of_one_part_keeps_the_legacy_layers_it_does_not_name(self) -> None:
        scene = self._scene_of(self.target)
        self.assertIn("needs_plan", scene["statuses"])
        answer = self._put(scene["scene_key"], {"transition": "fade"})
        self.assertEqual(answer["status"], "applied", answer)
        self.assertEqual(self._layers_of(self.target), (["Chữ cũ"], ["whoosh"]), "the legacy layers are kept")
        self.assertEqual(self._seg(self.target)["edit_transition"], "fade")

    def test_the_legacy_picture_fields_are_never_taken_into_the_edit(self) -> None:
        # The row's picture and its prompt are the asset pipeline's (the planner never names them): a hand edit made
        # on the legacy layers must not make the EditDocument the owner of the row's picture.
        scene = self._scene_of(self.target)
        self._put(scene["scene_key"], {"transition": "fade"})
        visual = self._scene(self.target)["edit"]["visual"]
        for column in ("visual_path", "visual_prompt", "asset_type"):
            self.assertNotIn(column, visual)
        picture = self.tmp_picture()
        response = self.client.post(f"/api/timeline/{self.target}/attach-asset", json={"asset_id": picture})
        self.assertEqual(response.status_code, 200, response.text)
        again = self._put(scene["scene_key"], {"effect": "zoom_out"})
        self.assertEqual((again["status"], again.get("conflicts") or []), ("applied", []))

    def tmp_picture(self) -> int:
        import tempfile
        from pathlib import Path
        folder = tempfile.TemporaryDirectory(prefix="t7f_pic_")
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "hinh.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        return int(self.database.create_project_asset(self.project_id, "image", path.name, str(path), "image/png", 8)["id"])


class _WorkersIdle:
    """The scene and production workers' queues, held: a job a test makes stays as the test left it."""

    def _idle_workers(self) -> None:
        for target, returned in ((main.production_worker, {"id": 1, "status": "queued"}), (main.scene_generation_worker, None)):
            patcher = mock.patch.object(target, "enqueue", mock.Mock(return_value=returned))
            patcher.start()
            self.addCleanup(patcher.stop)


# ===========================================================================
# 2. POST /api/projects/{id}/timeline/cleanups
# ===========================================================================

class CleanupsThroughTheEditDocumentTests(_WorkersIdle, _PlannedCase):
    def setUp(self) -> None:
        super().setUp()
        self._idle_workers()

    def _post_cleanups(self, body: dict, expect: int = 200) -> dict:
        response = self.client.post(f"/api/projects/{self.project_id}/timeline/cleanups", json=body)
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def _row_cleanups(self) -> dict:
        return {int(row["id"]): json.loads(row["edit_cleanups"] or "[]") for row in self._segments()}

    def test_every_scene_takes_them_in_one_version_and_the_rows_never_directly(self) -> None:
        versions = self._count("edit_document")
        with mock.patch.object(self.database, "set_timeline_cleanups") as direct:
            answer = self._post_cleanups({"position": "top_right", "method": "blur"})
        direct.assert_not_called()
        wanted = [{"position": "top_right", "method": "blur"}]
        self.assertEqual((answer["status"], answer["not_applied"]), ("saved", []))
        self.assertEqual(answer["segments"], len(self._segments()))
        self.assertTrue(all(value == wanted for value in self._row_cleanups().values()), self._row_cleanups())
        self.assertEqual(self._count("edit_document"), versions + 1, "one new version for every scene")
        self.assertTrue(all(scene["edit"]["visual"]["edit_cleanups"] == wanted for scene in self._doc()["scenes"]))
        self.assertEqual(self._layers_of(self.target), (["Chữ cũ"], ["whoosh"]), "a legacy scene keeps its layers")

    def test_clearing_goes_the_same_way_and_sent_again_changes_nothing(self) -> None:
        self._post_cleanups({"position": "top_right", "method": "blur"})
        cleared = self._post_cleanups({"clear": True})
        self.assertEqual(cleared["status"], "cleared")
        self.assertTrue(all(value == [{"kind": "none", "source": "user_cleared"}] for value in self._row_cleanups().values()))
        rows = self._db_state()["timeline"]
        again = self._post_cleanups({"clear": True})
        self.assertEqual((again["status"], again["not_applied"]), ("cleared", []))
        self.assertEqual(again["edit_document"]["status"], "unchanged")
        self.assertEqual(self._db_state()["timeline"], rows, "the rows already held them")

    def test_a_row_holding_a_hand_edit_is_a_conflict_never_written_over(self) -> None:
        self._step(confirmed_apply=True)
        with mock.patch.object(main, "_edit_document_owns_timeline", return_value=False):
            response = self.client.post(f"/api/projects/{self.project_id}/timeline/cleanups",
                                        json={"position": "bottom_left", "method": "crop"})   # outside the document
        self.assertEqual(response.status_code, 200, response.text)
        held = self._row_cleanups()
        answer = self._post_cleanups({"position": "top_right", "method": "blur"})
        self.assertEqual((answer["status"], answer["segments"]), ("blocked", 0))
        self.assertEqual({item["segment_id"] for item in answer["not_applied"]}, set(held))
        self.assertTrue(all("Xung đột" in item["reason"] for item in answer["not_applied"]), answer["not_applied"])
        self.assertEqual(self._row_cleanups(), held, "never written over")

    def test_a_row_with_a_scene_job_not_finished_is_left_out_before_anything_is_kept(self) -> None:
        job = self.database.create_scene_generation_job(self.project_id, self.target, "dry_run", "p", job_kind="image")
        before = self._scene(self.target)["edit"]
        answer = self._post_cleanups({"position": "top_right", "method": "blur"})
        self.assertEqual(answer["status"], "partial")
        self.assertEqual([item["segment_id"] for item in answer["not_applied"]], [self.target])
        self.assertIn("job", answer["not_applied"][0]["reason"])
        self.assertEqual(self._row_cleanups()[self.target], [], "the row is as it was")
        self.assertEqual(self._scene(self.target)["edit"], before, "and its edit in the EditDocument too")
        self.assertEqual(self.database.get_scene_generation_job(int(job["id"]))["status"], "queued")

    def test_a_storyboard_that_is_not_current_is_a_409_and_nothing_is_written(self) -> None:
        self._reword_in_place(1)
        state = self._state()
        answer = self._post_cleanups({"position": "top_right", "method": "blur"}, expect=409)
        self.assertIn("không phải bản hiện hành", answer["detail"])
        self.assertEqual(self._state(), state)

    def test_detecting_without_a_source_video_is_refused_before_anything(self) -> None:
        state = self._state()
        self._post_cleanups({"detect": True}, expect=400)
        self.assertEqual(self._state(), state)


class CleanupsOutsideThePlanWorkflowTests(_LegacyCase):
    def test_the_rows_take_them_as_before_and_no_edit_document_is_made(self) -> None:
        versions = self._count("edit_document")
        response = self.client.post(f"/api/projects/{self.project_id}/timeline/cleanups",
                                    json={"position": "top_right", "method": "blur"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "saved")
        self.assertNotIn("not_applied", response.json())
        self.assertTrue(all(json.loads(row["edit_cleanups"]) == [{"position": "top_right", "method": "blur"}]
                            for row in self._segments()))
        self.assertEqual(self._count("edit_document"), versions)


# ===========================================================================
# 3. scene-jobs/batch
# ===========================================================================

class _BatchCase(_WorkersIdle):
    def _batch(self, **body):
        with mock.patch.object(main, "_require_scene_provider_config"), \
                mock.patch.object(main, "_enforce_provider_billing_policy"):
            return self.client.post(f"/api/projects/{self.project_id}/scene-jobs/batch",
                                    json={"provider": "gemini_web_image", "confirmed": True, **body})

    def _kinds(self) -> list:
        return [row["visual_kind"] for row in self._segments()]


class BatchInThePlanWorkflowTests(_BatchCase, _PlannedCase):
    def setUp(self) -> None:
        super().setUp()
        self._idle_workers()

    def test_a_gif_batch_that_overrides_the_plan_is_refused_and_makes_nothing(self) -> None:
        state = self._state()
        response = self._batch(motion_as_gif=True, respect_plan=False)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn(REFUSED, response.json()["detail"])
        self.assertEqual(self._state(), state, "no job, no kind rewritten")

    def test_a_gif_batch_that_follows_the_plan_and_an_ordinary_batch_stay_open(self) -> None:
        kinds = self._kinds()
        for body in ({"motion_as_gif": True, "respect_plan": True}, {}):
            with self.subTest(body=body):
                response = self._batch(**body)
                self.assertNotIn(REFUSED, response.text)
                self.assertEqual(self._kinds(), kinds, "never a kind rewritten")


class BatchOutsideThePlanWorkflowTests(_BatchCase, _LegacyCase):
    def setUp(self) -> None:
        super().setUp()
        self._idle_workers()

    def test_a_gif_batch_that_overrides_the_plan_rewrites_the_kinds_as_before(self) -> None:
        for row in self._segments():
            self.database.update_project_timeline_segment(int(row["id"]), visual_prompt="một cảnh")
        response = self._batch(motion_as_gif=True, respect_plan=False)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["jobs"])
        rewritten = {int(job["timeline_segment_id"]) for job in response.json()["jobs"]}
        self.assertTrue(all(row["visual_kind"] == "gif" for row in self._segments() if int(row["id"]) in rewritten))


# ===========================================================================
# 4. The agents' choice of a scene's kind
# ===========================================================================

class AgentKindsTests(_WorkersIdle, _PlannedCase):
    def setUp(self) -> None:
        super().setUp()
        self._idle_workers()

    def _kinds_for(self, rows: list[dict], kind: str = "gif") -> dict:
        return {int(row["id"]): main._agent_kind(kind, "agent") for row in rows}

    def test_in_the_plan_workflow_they_go_through_the_edit_document_and_wait_for_a_person(self) -> None:
        rows = self._segments()
        before = [row["visual_kind"] for row in rows]
        versions = self._count("edit_document")
        with mock.patch.object(self.database, "set_segment_visual_kind") as direct:
            through = main._agent_kinds_written(self.project_id, rows, self._kinds_for(rows))
        direct.assert_not_called()
        self.assertEqual(self._count("edit_document"), versions + 1)
        self.assertTrue(all(scene["edit"]["visual"]["visual_kind"] == "gif" for scene in self._doc()["scenes"]))
        # T4 phương án B: an agent's change is not a person's - kept, not applied, every row that would change named.
        self.assertEqual([row["visual_kind"] for row in self._segments()], before)
        self.assertEqual({item["segment_id"] for item in through["not_applied"]},
                         {int(row["id"]) for row in rows if row["visual_kind"] != "gif"})
        self.assertTrue(all("xác nhận" in item["reason"] for item in through["not_applied"]))
        self.assertEqual(self._confirm()["applied"]["status"], "applied")             # a person confirms it
        self.assertTrue(all(row["visual_kind"] == "gif" for row in self._segments()))
        self.assertEqual(self._layers_of(self.target), (["Chữ cũ"], ["whoosh"]))

    def test_a_row_holding_a_hand_kind_is_named_and_never_written_over(self) -> None:
        self._step(confirmed_apply=True)
        rows = self._segments()
        with mock.patch.object(main, "_edit_document_owns_timeline", return_value=False):
            self.client.patch(f"/api/timeline/{self.target}/plan", json={"visual_kind": "video"})   # outside the document
        through = main._agent_kinds_written(self.project_id, rows, self._kinds_for(rows, "image"))
        self.assertIn(self.target, [item["segment_id"] for item in through["not_applied"]])
        self.assertEqual(self._seg(self.target)["visual_kind"], "video")
        confirmed = self._confirm()["applied"]                                     # a person confirms the version
        self.assertIn(self.target, [item["segment_id"] for item in confirmed["conflicts"]])
        self.assertEqual(self._seg(self.target)["visual_kind"], "video", "never written over")
        self.assertTrue(all(row["visual_kind"] == "image" for row in self._segments() if int(row["id"]) != self.target))

    def test_a_storyboard_that_is_not_current_writes_no_kind(self) -> None:
        self._reword_in_place(1)
        rows = self._segments()
        state = self._state()
        through = main._agent_kinds_written(self.project_id, rows, self._kinds_for(rows))
        self.assertEqual(len(through["not_applied"]), len(rows))
        self.assertEqual(self._state(), state)

    def test_the_media_agent_makes_no_job_for_a_scene_whose_kind_was_not_taken(self) -> None:
        self._step(confirmed_apply=True)
        with mock.patch.object(main, "_edit_document_owns_timeline", return_value=False):
            self.client.patch(f"/api/timeline/{self.target}/plan", json={"visual_kind": "video"})
        rows = self._segments()
        for row in rows:                                         # no picture yet: the agent would make one
            self.database.update_project_timeline_segment(int(row["id"]), visual_path="")
        decision = {"scenes": [{"segment_id": int(row["id"]), "kind": "image", "treatment": "illustration", "reason": "r"}
                               for row in rows]}

        def route(capability, provider_states=None, policy=None):
            selected = mock.Mock()
            selected.key, selected.estimated_unit_cost = "dry_run", 0
            return mock.Mock(selected=selected, candidates=[], reason="test")

        task = {"project_id": self.project_id, "role": "media", "input": {"pipeline": {"auto_generate_media": True}},
                "correlation_id": ""}
        with mock.patch.object(main, "_call_specific_agent_json", return_value=decision), \
                mock.patch.object(main.scene_provider_gateway, "route", side_effect=route), \
                mock.patch.object(main, "_provider_runtime_states", return_value={}), \
                mock.patch.object(main, "_cost_budget_breach", return_value=""):
            result = main._execute_agent_task(task, "codex_cli")
        held = [item for item in result["assignments"] if item.get("kind_not_applied")]
        self.assertEqual([int(item["segment_id"]) for item in held], [self.target])
        jobs = {int(job["timeline_segment_id"]) for job in self.database.list_scene_generation_jobs(self.project_id, limit=500)}
        self.assertNotIn(self.target, jobs, "no job for the kind the row does not have")
        self.assertEqual(jobs, {int(row["id"]) for row in rows} - {self.target})
        self.assertEqual(self._seg(self.target)["visual_kind"], "video")


class DirectorAgentTests(_WorkersIdle, _PlannedCase):
    def setUp(self) -> None:
        super().setUp()
        self._idle_workers()

    def _direct(self, media_type: str) -> dict:
        rows = self._segments()
        scenes = [{"narration": row["voice_text"], "visual_prompt": "p", "duration": 5, "media_type": media_type}
                  for row in rows]

        def step(project_id, name, options):
            # The shots and timeline steps (storyboard and reconcile) are theirs to test; here they keep the rows.
            return {"result": {"shots": [{"id": None} for _ in rows]} if name == "shots" else {"timeline": rows}}

        task = {"project_id": self.project_id, "role": "director", "input": {}, "correlation_id": ""}
        with mock.patch.object(main, "_call_specific_agent_json", return_value={"scenes": scenes}),                 mock.patch.object(main, "run_project_step", side_effect=step),                 mock.patch.object(main, "_reattach_project_voice"):
            return main._execute_agent_task(task, "codex_cli")

    def test_in_the_plan_workflow_the_kinds_it_chose_go_through_the_edit_document(self) -> None:
        versions = self._count("edit_document")
        with mock.patch.object(self.database, "set_segment_visual_kind") as direct:
            result = self._direct("gif")
        direct.assert_not_called()
        self.assertEqual(self._count("edit_document"), versions + 1)
        self.assertEqual({item["segment_id"] for item in result["kinds_not_applied"]},
                         {int(row["id"]) for row in self._segments() if row["visual_kind"] != "gif"}, "they wait for a person")
        self._confirm()
        self.assertTrue(all((row["visual_kind"], int(row["visual_fps"])) == ("gif", 8) for row in self._segments()))

    def test_a_row_holding_a_hand_kind_keeps_it_and_is_named(self) -> None:
        self._step(confirmed_apply=True)
        with mock.patch.object(main, "_edit_document_owns_timeline", return_value=False):
            self.client.patch(f"/api/timeline/{self.target}/plan", json={"visual_kind": "video"})
        result = self._direct("image")
        self.assertIn(self.target, [item["segment_id"] for item in result["kinds_not_applied"]])
        self._confirm()
        self.assertEqual(self._seg(self.target)["visual_kind"], "video", "a conflict at the confirmation, never written over")


class AgentKindsOutsideThePlanWorkflowTests(_LegacyCase):
    def test_the_rows_take_them_as_before(self) -> None:
        rows = self._segments()
        versions = self._count("edit_document")
        self.assertIsNone(main._agent_kinds_written(self.project_id, rows, {int(rows[0]["id"]): main._agent_kind("gif", "a")}))
        row = self._seg(int(rows[0]["id"]))
        self.assertEqual((row["visual_kind"], int(row["visual_fps"])), ("gif", 8))
        self.assertEqual(self._count("edit_document"), versions)


# ===========================================================================
# 5. A render's measured cleanups (production_worker._autocover_source_marks)
# ===========================================================================

MARKS = [{"kind": "subtitle", "position": "bottom_center", "method": "blur", "source": "detected"}]


class _AutocoverCase:
    def setUp(self) -> None:
        super().setUp()
        with self.database._connect() as connection:       # a scene cut from the source: the render measures it
            connection.execute("UPDATE project_timeline_segments SET visual_strategy = 'source_clip_short' WHERE id = ?",
                               (self.target,))

    def _render_cover(self) -> list[dict]:
        from youtube_monitor import production_worker
        folder = tempfile.TemporaryDirectory(prefix="t7f_src_")
        self.addCleanup(folder.cleanup)
        source = Path(folder.name) / "nguon.mp4"
        source.write_bytes(b"0")
        project = self.database.get_production_project(self.project_id)
        script = self.database.get_latest_project_script(self.project_id)
        timeline = self.database.list_project_timeline(self.project_id, script_id=int(script["id"]))
        with mock.patch.object(self.database, "get_video", return_value={"local_media_path": str(source)}), \
                mock.patch.object(production_worker, "detect_burned_in_marks", return_value=MARKS):
            return production_worker._autocover_source_marks(self.database, project, script, timeline, "ffmpeg")


class AutocoverInThePlanWorkflowTests(_AutocoverCase, _PlannedCase):
    def test_the_render_covers_what_it_measured_and_the_rows_are_left_as_they_are(self) -> None:
        state = self._db_state()
        covered = self._render_cover()
        self.assertTrue(all(json.loads(item["edit_cleanups"]) == MARKS for item in covered))
        self.assertEqual(self._db_state(), state, "no cleanup written behind the EditDocument")


class AutocoverOutsideThePlanWorkflowTests(_AutocoverCase, _LegacyCase):
    def test_the_rows_take_what_was_measured_as_before(self) -> None:
        covered = self._render_cover()
        self.assertTrue(all(json.loads(row["edit_cleanups"]) == MARKS for row in self._segments()))
        self.assertTrue(all(json.loads(item["edit_cleanups"]) == MARKS for item in covered))
