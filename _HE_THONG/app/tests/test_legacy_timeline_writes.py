"""Bước 05 · T7 · các đường ghi timeline cũ.

T7b · sửa lớp dựng của một cảnh (PATCH /api/timeline/{id}/plan, POST …/edit-beats/plan) không bao giờ làm mất
      trim đầu/cuối và lớp che logo/phụ đề (edit_trim_head, edit_trim_tail, edit_cleanups) khi request không nói gì
      về chúng. Các đường sửa chúng tường minh (PATCH …/cut, POST …/timeline/cleanups) vẫn sửa được.
T7a · dự án theo luồng Kế hoạch: các đường ghi cũ vào cảnh của kịch bản hiện hành bị từ chối (409) và không ghi gì
      - lớp dựng đi qua EditDocument. Đường đọc, lập/duyệt Edit Plan cũ (chỉ ghi project_edit_plans) và gắn
      hình/giọng (attach-asset: chỉ visual_path/audio_path) vẫn mở. Luồng legacy giữ nguyên.
T7c · đường cũ còn mở (luồng legacy) không thay hay xoá nhịp dựng khi có job trỏ vào nhịp (mọi trạng thái: job
      xong vẫn có thể bị chấm lại và chạy lại) hoặc khi cảnh còn job chưa xong; liên kết job giữ nguyên.

Mọi test chạy trên DB tạm của bộ test (tests/conftest.py), mô hình AI giả; không gọi AI thật, không chạy app.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

from tests.test_edit_manual_document import HAND_OVERLAYS, _SceneEditCase
from youtube_monitor import ai_desktop_mcp, main

CLEANUP = [{"kind": "logo", "position": "top_right", "method": "blur", "source": "user"}]
REFUSED = "luồng Kế hoạch"


class _RouteCase(_SceneEditCase):
    def setUp(self) -> None:
        super().setUp()
        self.target = int(self._segments()[0]["id"])

    def _over_mcp(self):
        """The desktop MCP's HTTP calls, sent to this app (as tests/test_production_gate_worker does)."""
        def request(path, method="GET", data=None, headers=None, timeout=None):
            response = self.client.request(method, path, content=data, headers=headers or {})
            if response.status_code >= 400:
                raise RuntimeError(str(response.json().get("detail")))
            return response.json()
        return mock.patch.object(ai_desktop_mcp, "_factory_request", side_effect=request)

    def _seconds(self) -> float:
        return float(self._seg(self.target)["duration_seconds"])

    def _state(self) -> dict:
        """_db_state and what else an old route writes: scene jobs, assets, the legacy Edit Plan."""
        state = self._db_state()
        with self.database._connect() as connection:
            for table, column in (("scene_generation_jobs", "project_id"), ("project_assets", "project_id"),
                                  ("project_edit_plans", "project_id")):
                state[table] = [dict(row) for row in connection.execute(
                    f"SELECT * FROM {table} WHERE {column} = ? ORDER BY id", (self.project_id,))]
        return state


class _LegacyCase(_RouteCase):
    """A project outside the plan workflow (the Storyboard Gate's legacy mode): the old routes are its own."""

    def setUp(self) -> None:
        super().setUp()
        outside = mock.patch.object(main, "_in_plan_workflow", return_value=False)
        outside.start()
        self.addCleanup(outside.stop)


# ===========================================================================
# T7b · trims and cleanups are never reset by an edit that does not name them
# ===========================================================================

class TrimsAndCleanupsTests(_LegacyCase):
    def setUp(self) -> None:
        super().setUp()
        self.database.save_segment_edit(self.target, "cut", "static", "trước", trim_head_seconds=0.4,
                                        trim_tail_seconds=0.3, cleanups=CLEANUP)

    def _trims_and_cleanups(self) -> tuple:
        row = self._seg(self.target)
        return float(row["edit_trim_head"]), float(row["edit_trim_tail"]), json.loads(row["edit_cleanups"] or "[]")

    def test_editing_the_note_only_keeps_trims_and_cleanups(self) -> None:
        self._patch_plan(self.target, note="chỉ sửa ghi chú")
        self.assertEqual(self._trims_and_cleanups(), (0.4, 0.3, CLEANUP))
        self.assertEqual(self._seg(self.target)["edit_note"], "chỉ sửa ghi chú")

    def test_editing_the_transition_and_effect_keeps_trims_and_cleanups(self) -> None:
        self._patch_plan(self.target, transition="fade", effect="zoom_out")
        self.assertEqual(self._trims_and_cleanups(), (0.4, 0.3, CLEANUP))
        self.assertEqual((self._seg(self.target)["edit_transition"], self._seg(self.target)["edit_effect"]), ("fade", "zoom_out"))

    def test_planning_a_scenes_beats_keeps_trims_and_cleanups(self) -> None:
        with mock.patch.object(main, "_call_orchestrator_json", return_value={}):
            response = self.client.post(f"/api/timeline/{self.target}/edit-beats/plan", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._trims_and_cleanups(), (0.4, 0.3, CLEANUP))

    def test_planning_a_scenes_beats_over_mcp_keeps_trims_and_cleanups(self) -> None:
        with self._over_mcp(), mock.patch.object(main, "_call_orchestrator_json", return_value={}):
            ai_desktop_mcp._call_tool("youtube_factory_plan_scene_edit_beats",
                                      {"project_id": self.project_id, "segment_id": self.target})
        self.assertEqual(self._trims_and_cleanups(), (0.4, 0.3, CLEANUP))

    def test_cleanups_that_cannot_be_read_are_never_touched(self) -> None:
        # Neither route writes the trims or the cleanups at all: what is there stays, readable or not.
        with self.database._connect() as connection:
            connection.execute("UPDATE project_timeline_segments SET edit_cleanups = ? WHERE id = ?", ("{hỏng", self.target))
        self._patch_plan(self.target, note="x", visual_kind="gif")
        with mock.patch.object(main, "_call_orchestrator_json", return_value={}):
            response = self.client.post(f"/api/timeline/{self.target}/edit-beats/plan", json={})
        self.assertEqual(response.status_code, 200, response.text)
        row = self._seg(self.target)
        self.assertEqual((row["edit_cleanups"], float(row["edit_trim_head"]), float(row["edit_trim_tail"])), ("{hỏng", 0.4, 0.3))

    def test_the_cut_route_still_sets_the_trims_and_keeps_the_cleanups(self) -> None:
        response = self.client.patch(f"/api/timeline/{self.target}/cut",
                                     json={"edit_trim_head": 1.0, "edit_trim_tail": 0.5, "recut": False})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._trims_and_cleanups(), (1.0, 0.5, CLEANUP))

    def test_the_cleanups_route_still_sets_the_cleanups_and_keeps_the_trims(self) -> None:
        response = self.client.post(f"/api/projects/{self.project_id}/timeline/cleanups",
                                    json={"position": "bottom_center", "method": "crop"})
        self.assertEqual(response.status_code, 200, response.text)
        head, tail, cleanups = self._trims_and_cleanups()
        self.assertEqual((head, tail), (0.4, 0.3))
        self.assertEqual([(item["position"], item["method"]) for item in cleanups], [("bottom_center", "crop")])


class PlanPatchIsAllOrNothingTests(_LegacyCase):
    """PATCH …/plan checks and normalises every part before its one write: a refused request leaves the row as it was."""

    def setUp(self) -> None:
        super().setUp()
        self.database.save_segment_edit(self.target, "cut", "static", "trước", trim_head_seconds=0.4,
                                        trim_tail_seconds=0.3, cleanups=CLEANUP)

    def test_a_refused_part_writes_none_of_the_others(self) -> None:
        bad_overlay = [{"kind": "không có", "text": "x", "start_seconds": 0, "end_seconds": 1}]
        late_overlay = [{"kind": "text", "text": "x", "start_seconds": 0, "end_seconds": 999}]
        bad_sound = [{"cue": "whoosh", "start_seconds": 999, "end_seconds": 1000}]
        bad_direction = {"graphic_layers": [{"id": "a", "preset": "không có"}]}
        for body in ({"visual_kind": "gif", "overlays": bad_overlay},
                     {"visual_kind": "video", "visual_fps": 12, "transition": "fade", "overlays": late_overlay},
                     {"visual_fps": 6, "note": "ghi chú", "sound_cues": bad_sound},
                     {"transition": "fade", "effect": "zoom_out", "direction": bad_direction},
                     {"visual_kind": "gif", "overlays": HAND_OVERLAYS, "sound_cues": bad_sound},
                     {"visual_kind": "gif", "transition": "wipe"}):                  # refused by the request model
            with self.subTest(body=body):
                state = self._state()
                response = self.client.patch(f"/api/timeline/{self.target}/plan", json=body)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(self._state(), state, "nothing written, updated_at included")

    def test_the_one_write_is_all_or_nothing_in_the_database_too(self) -> None:
        # A part the table refuses (NULL in a NOT NULL column) after another part: neither is written.
        state = self._state()
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.save_segment_plan(self.target, {"visual_kind": "gif", "edit_note": "x", "overlays": None})
        self.assertEqual(self._state(), state)
        with self.assertRaises(ValueError):
            self.database.save_segment_plan(self.target, {"visual_kind": "gif", "edit_trim_head": 0.0})
        self.assertEqual(self._state(), state, "the trims are not a part of a scene's plan")

    def test_every_part_of_an_accepted_request_is_written_together(self) -> None:
        before = self._seg(self.target)
        row = self._patch_plan(self.target, visual_kind="gif", visual_fps=8, transition="fade", note="cùng lúc",
                               overlays=HAND_OVERLAYS, direction={"camera": "slow_push"})
        self.assertEqual((row["visual_kind"], int(row["visual_fps"]), row["edit_transition"], row["edit_effect"], row["edit_note"]),
                         ("gif", 8, "fade", "static", "cùng lúc"))
        self.assertEqual([item["text"] for item in json.loads(row["overlays"])], [HAND_OVERLAYS[0]["text"]])
        self.assertEqual((float(row["edit_trim_head"]), float(row["edit_trim_tail"]), json.loads(row["edit_cleanups"])),
                         (0.4, 0.3, CLEANUP))
        self.assertEqual(row["sound_cues"], before["sound_cues"], "a part not named is not written")
        self.assertNotEqual(row["updated_at"], before["updated_at"])


# ===========================================================================
# T7a · a planned project: the old timeline writes are refused and write nothing
# ===========================================================================

class PlanWorkflowRefusalTests(_RouteCase):
    def setUp(self) -> None:
        super().setUp()
        self._step(confirmed_apply=True)
        self.target = int(self._segments()[0]["id"])

    def _refused(self, method: str, path: str, body: dict | None = None) -> str:
        state = self._state()
        with mock.patch.object(main, "_call_orchestrator_json") as model:
            response = self.client.request(method, path, json=body)
        self.assertEqual(response.status_code, 409, (path, response.text))
        self.assertIn(REFUSED, response.json()["detail"], path)
        self.assertIn("EditDocument", response.json()["detail"], path)
        self.assertEqual(self._state(), state, f"{path} wrote nothing")
        model.assert_not_called()
        return response.json()["detail"]

    def test_every_old_write_to_a_scene_is_refused_and_writes_nothing(self) -> None:
        seconds = self._seconds()
        # What the old routes would act on: a beat, and a legacy Edit Plan whose revision is no longer the
        # timeline's (reading it would mark it stale - a write too).
        self.database.replace_timeline_edit_beats(self.target, [{"beat_index": 1, "source_kind": "ai_image",
                                                                 "duration_seconds": seconds, "prompt": "x"}])
        self.database.save_project_edit_plan(self.project_id, self.script_id_now(), "cũ", {"scenes": [
            {"segment_id": self.target, "transition": "cut"}]}, status="draft")
        segment = f"/api/timeline/{self.target}"
        project = f"/api/projects/{self.project_id}"
        for method, path, body in (
                ("PATCH", f"{segment}/plan", {"note": "đường cũ"}),
                ("PATCH", f"{segment}/plan", {"overlays": HAND_OVERLAYS}),
                ("PUT", f"{segment}/edit-beats", {"beats": [{"duration_seconds": seconds}]}),
                ("POST", f"{segment}/edit-beats/plan", {}),
                ("POST", f"{segment}/edit-beats/apply", {"image_provider": "gemini_web_image", "confirmed": True}),
                ("POST", f"{segment}/edit-beats/1/generate", {"image_provider": "gemini_web_image", "confirmed": True}),
                ("POST", f"{segment}/edit-beats/1/extract-frame", None),
                ("POST", f"{project}/edit-plan/apply", None),
                ("PATCH", f"{project}/edit-plan/scenes/{self.target}", {"transition": "fade"})):
            self._refused(method, path, body)

    def script_id_now(self) -> int:
        return int(self.database.get_latest_project_script(self.project_id)["id"])

    def test_the_trims_of_the_cut_route_are_refused_its_cut_point_stays_open(self) -> None:
        # The plan writes the trims (edit_planner.scene_edit), not the cut point in the source.
        for body in ({"edit_trim_head": 1.0, "recut": False},
                     {"source_start_seconds": 3.0, "edit_trim_tail": 0.5, "recut": False}):
            with self.subTest(body=body):
                self._refused("PATCH", f"/api/timeline/{self.target}/cut", body)
        response = self.client.patch(f"/api/timeline/{self.target}/cut", json={"source_start_seconds": 3.0, "recut": False})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(float(self._seg(self.target)["source_start_seconds"]), 3.0)

    def test_the_mcp_tools_get_the_same_refusal(self) -> None:
        self.database.save_project_edit_plan(self.project_id, self.script_id_now(), "cũ", {"scenes": [
            {"segment_id": self.target, "transition": "cut"}]}, status="approved")
        state = self._state()
        for tool, arguments in (
                ("youtube_factory_plan_scene_edit_beats", {"project_id": self.project_id, "segment_id": self.target}),
                ("youtube_factory_apply_scene_edit_beats", {"project_id": self.project_id, "segment_id": self.target,
                                                            "image_provider": "gemini_web_image", "confirmed": True}),
                ("youtube_factory_apply_project_edit_plan", {"project_id": self.project_id}),
                ("youtube_factory_update_project_edit_scene", {"project_id": self.project_id, "segment_id": self.target,
                                                               "changes": {"transition": "fade"}})):
            with self._over_mcp(), self.assertRaises(RuntimeError) as refused:
                ai_desktop_mcp._call_tool(tool, arguments)
            self.assertIn(REFUSED, str(refused.exception), tool)
        self.assertEqual(self._state(), state)

    def test_the_agents_scene_edit_tools_get_the_same_refusal(self) -> None:
        # The orchestrator's own tools call the routes in-process, not over HTTP: each scene comes back refused.
        state = self._state()
        with mock.patch.object(main, "_call_orchestrator_json") as model:
            for step in ({"tool": "plan_scene_edits", "limit": 2},
                         {"tool": "apply_scene_edits", "limit": 2, "image_provider": "gemini_web_image"}):
                result = main._run_orchestrator_tool(self.project_id, step)
                self.assertEqual(result["failed"], len(result["results"]), step)
                self.assertGreater(len(result["results"]), 0)
                self.assertTrue(all(REFUSED in item["detail"] for item in result["results"]), result)
        model.assert_not_called()
        self.assertEqual(self._state(), state)

    def test_reading_stays_open(self) -> None:
        response = self.client.get(f"/api/timeline/{self.target}/edit-beats")
        self.assertEqual(response.status_code, 200, response.text)
        read = self.client.get(f"/api/projects/{self.project_id}/edit-plan")
        self.assertNotIn(REFUSED, read.text)

    def test_planning_and_approving_the_legacy_edit_plan_are_not_refused_by_the_guard(self) -> None:
        # They write project_edit_plans only (audited): not the timeline, so the guard leaves them as they were.
        with mock.patch.object(main, "_call_orchestrator_json", return_value={"scenes": []}):
            for path in (f"/api/projects/{self.project_id}/edit-plan", f"/api/projects/{self.project_id}/edit-plan/approve"):
                response = self.client.post(path)
                self.assertNotIn(REFUSED, response.text, path)

    def test_attaching_a_picture_stays_open_and_the_plan_still_applies(self) -> None:
        folder = tempfile.TemporaryDirectory(prefix="t7_attach_")
        self.addCleanup(folder.cleanup)
        picture = Path(folder.name) / "gan-tay.png"
        picture.write_bytes(b"\x89PNG\r\n\x1a\n")
        asset = self.database.create_project_asset(self.project_id, "image", picture.name, str(picture), "image/png", 8)
        response = self.client.post(f"/api/timeline/{self.target}/attach-asset", json={"asset_id": int(asset["id"])})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._seg(self.target)["visual_path"], str(picture))
        applied = self._step(confirmed_apply=True)["applied"]
        self.assertEqual(self._conflicts(applied), [], "the plan never writes the picture: no conflict")
        self.assertEqual(self._seg(self.target)["visual_path"], str(picture), "and never writes over it")

    def test_reups_cut_by_dialogue_keeps_the_old_routes(self) -> None:
        with mock.patch.object(main, "_in_reup_cut", return_value=True):
            response = self.client.patch(f"/api/timeline/{self.target}/plan", json={"note": "reup"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._seg(self.target)["edit_note"], "reup")

    def test_a_row_of_a_script_that_is_not_the_current_one_is_not_refused(self) -> None:
        old_target = self.target
        self._revise(line_of_section=2)                       # a new current script; the old rows stay the old script's
        response = self.client.patch(f"/api/timeline/{old_target}/plan", json={"note": "kịch bản cũ"})
        self.assertEqual(response.status_code, 200, response.text)


class LegacyStillWritesTests(_LegacyCase):
    def test_the_old_routes_write_as_before(self) -> None:
        segment = f"/api/timeline/{self.target}"
        plan = self.client.patch(f"{segment}/plan", json={"overlays": HAND_OVERLAYS, "note": "legacy"})
        self.assertEqual(plan.status_code, 200, plan.text)
        self.assertEqual([item["text"] for item in self._overlays(self.target)], [HAND_OVERLAYS[0]["text"]])
        beats = self.client.put(f"{segment}/edit-beats", json={"beats": [{"duration_seconds": self._seconds()}]})
        self.assertEqual(beats.status_code, 200, beats.text)
        self.assertEqual(len(self._beats(self.target)), 1)
        applied = self.client.post(f"{segment}/edit-beats/apply", json={"image_provider": "gemini_web_image"})
        self.assertEqual(applied.status_code, 200, applied.text)


# ===========================================================================
# T7c · beats a scene job points at, or a scene with a job not finished, are never replaced
# ===========================================================================

class BeatJobGuardTests(_LegacyCase):
    def setUp(self) -> None:
        super().setUp()
        response = self.client.put(f"/api/timeline/{self.target}/edit-beats", json={"beats": [
            {"duration_seconds": self._seconds(), "prompt": "nhịp có job"}]})
        self.assertEqual(response.status_code, 200, response.text)
        self.beat = self._beats(self.target)[0]

    def _job(self, status: str, *, on_beat: bool = True) -> dict:
        job = self.database.create_scene_generation_job(self.project_id, self.target, "dry_run", "p",
                                                        **({"edit_beat_id": int(self.beat["id"])} if on_beat else {}))
        with self.database._connect() as connection:
            connection.execute("UPDATE scene_generation_jobs SET status = ? WHERE id = ?", (status, int(job["id"])))
        return job

    def _both_refused(self, job: dict | None, status: str) -> None:
        state = self._state()
        replace = self.client.put(f"/api/timeline/{self.target}/edit-beats", json={"beats": [
            {"duration_seconds": round(self._seconds() / 2, 3)}, {"duration_seconds": round(self._seconds() / 2, 3)}]})
        self.assertEqual(replace.status_code, 409, (status, replace.text))
        with mock.patch.object(main, "_call_orchestrator_json") as model:
            plan = self.client.post(f"/api/timeline/{self.target}/edit-beats/plan", json={})
        self.assertEqual(plan.status_code, 409, (status, plan.text))
        model.assert_not_called()
        self.assertEqual(self._state(), state, status)
        self.assertEqual([beat["id"] for beat in self._beats(self.target)], [self.beat["id"]], status)
        if job is not None:
            self.assertEqual(self.database.get_scene_generation_job(int(job["id"]))["edit_beat_id"], int(self.beat["id"]), status)

    def test_a_job_pointing_at_a_beat_holds_it_in_every_status(self) -> None:
        for status in ("queued", "waiting", "running", "error", "cancelled", "completed"):
            with self.subTest(status=status):
                job = self._job(status)
                self._both_refused(job, status)
                with self.database._connect() as connection:
                    connection.execute("DELETE FROM scene_generation_jobs WHERE id = ?", (int(job["id"]),))

    def test_a_scene_job_not_finished_holds_the_beats(self) -> None:
        for status in ("queued", "waiting", "running"):
            with self.subTest(status=status):
                job = self._job(status, on_beat=False)
                self._both_refused(None, status)
                with self.database._connect() as connection:
                    connection.execute("DELETE FROM scene_generation_jobs WHERE id = ?", (int(job["id"]),))

    def test_a_job_queued_while_the_model_plans_still_holds_the_beats(self) -> None:
        made = []

        def model(*_args, **_options):
            made.append(self._job("queued"))
            return {}

        with mock.patch.object(main, "_call_orchestrator_json", side_effect=model):
            response = self.client.post(f"/api/timeline/{self.target}/edit-beats/plan", json={})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(len(made), 1)
        self.assertEqual([beat["id"] for beat in self._beats(self.target)], [self.beat["id"]])
        self.assertEqual(self.database.get_scene_generation_job(int(made[0]["id"]))["edit_beat_id"], int(self.beat["id"]))

    def test_a_finished_scene_job_not_on_a_beat_or_no_job_at_all_lets_the_beats_change(self) -> None:
        for status in ("completed", "error", "cancelled"):
            self._job(status, on_beat=False)
        response = self.client.put(f"/api/timeline/{self.target}/edit-beats", json={"beats": [
            {"duration_seconds": round(self._seconds() / 2, 3), "prompt": "A"},
            {"duration_seconds": round(self._seconds() - round(self._seconds() / 2, 3), 3), "prompt": "B"}]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([beat["prompt"] for beat in self._beats(self.target)], ["A", "B"])
