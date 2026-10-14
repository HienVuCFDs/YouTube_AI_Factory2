"""Bước 05 · T6a · sửa tay lớp dựng ở luồng Kế hoạch đi qua EditDocument.

    PUT /api/projects/{id}/edit-document/scenes/{scene_key}
      ─→ edit_store.sync ─→ edit của cảnh như đang chạy (effective_edit), thay phần được gửi
      ─→ edit_store.plan_scene (một phiên bản mới) ─→ apply_scenes(scene_keys=[cảnh đó]) ─→ hàng timeline

Chỉ cảnh được sửa được áp; phần không gửi giữ nguyên; áp lại không xung đột; dữ liệu sai,
storyboard/kịch bản không hiện hành, dự án ngoài luồng Kế hoạch, job đang giữ nhịp dựng:
không ghi gì. Hàng đang giữ sửa tay ngoài EditDocument: xung đột, không ghi đè (F1/F2).

Mọi test chạy trên DB tạm của bộ test (tests/conftest.py), mô hình AI giả
(tests/test_edit_planner.Director); không gọi AI thật, không chạy app.
"""

from __future__ import annotations

import json
from unittest import mock

from tests.test_edit_manual_conflicts import MANUAL_OVERLAYS, _ManualCase
from youtube_monitor import edit_document as ed, edit_store as es, main
from youtube_monitor.database import EDIT_APPLY_KIND, EDIT_DOCUMENT_KIND

HAND_OVERLAYS = [{"kind": "text", "text": "Chữ sửa tay T6a", "start_seconds": 0.0, "end_seconds": 1.0}]


class _SceneEditCase(_ManualCase):
    def setUp(self) -> None:
        super().setUp()
        # The app's scene worker takes queued jobs every 2 s; a job a test made must stay as the test left it.
        idle = mock.patch.object(self.database, "list_queued_scene_generation_job_ids", return_value=[])
        idle.start()
        self.addCleanup(idle.stop)

    def _put(self, scene_key: str, body: dict, expect: int = 200) -> dict:
        response = self.client.put(f"/api/projects/{self.project_id}/edit-document/scenes/{scene_key}", json=body)
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def _scene(self, segment_id: int) -> dict:
        """The scene of a row in the current stored EditDocument."""
        return next(item for item in self._doc()["scenes"] if item["segment_id"] == segment_id)

    def _count(self, kind: str) -> int:
        with self.database._connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM project_director_artifacts WHERE project_id = ? AND kind = ?",
                                      (self.project_id, kind)).fetchone()[0]

    def _overlays(self, segment_id: int) -> list:
        return json.loads(self._seg(segment_id)["overlays"] or "[]")


class SceneEditTests(_SceneEditCase):
    def test_a_hand_edit_is_one_new_version_and_only_that_scene_is_applied(self) -> None:
        self._step()                                   # planned, not applied
        rows = self._segments()
        target, other = int(rows[0]["id"]), int(rows[1]["id"])
        key = self._scene(target)["scene_key"]
        versions, applies = self._count(EDIT_DOCUMENT_KIND), self._count(EDIT_APPLY_KIND)
        other_before = self._layers(self._seg(other))

        answer = self._put(key, {"overlays": HAND_OVERLAYS})

        self.assertEqual(answer["status"], "applied")
        self.assertEqual([item["segment_id"] for item in answer["applied"]], [target], "only the scene edited")
        self.assertEqual((answer["scene_key"], answer["segment_id"]), (key, target))
        self.assertEqual(self._count(EDIT_DOCUMENT_KIND), versions + 1, "one new version")
        self.assertEqual(self._count(EDIT_APPLY_KIND), applies + 1)
        self.assertEqual([item["text"] for item in self._overlays(target)], ["Chữ sửa tay T6a"])
        self.assertEqual(self._layers(self._seg(other)), other_before, "the other scenes are not applied here")
        read = self._edit_document()
        self.assertEqual(self._scene_of(target, read)["applied"], "applied")
        self.assertEqual(self._scene_of(other, read)["applied"], "not_applied")

    def test_the_parts_not_given_are_kept(self) -> None:
        self._step(confirmed_apply=True)
        target = int(self._segments()[0]["id"])
        before = ed.effective_edit(self._scene(target))
        self._put(self._scene(target)["scene_key"], {"overlays": HAND_OVERLAYS, "note": "ghi chú tay"})
        after = self._scene(target)["edit"]
        self.assertEqual(after["layers"]["sound_cues"], before["layers"]["sound_cues"])
        self.assertEqual(after["layers"]["direction"], before["layers"]["direction"])
        self.assertEqual(after["beats"], before["beats"])
        self.assertEqual({k: v for k, v in after["visual"].items() if k != "edit_note"},
                         {k: v for k, v in before["visual"].items() if k != "edit_note"})
        self.assertEqual(after["visual"]["edit_note"], "ghi chú tay")
        self.assertNotEqual(after["layers"]["overlays"], before["layers"]["overlays"])
        row = self._seg(target)
        self.assertEqual((row["edit_transition"], row["edit_note"]), (before["visual"]["edit_transition"], "ghi chú tay"))

    def test_applying_again_finds_no_conflict(self) -> None:
        self._step(confirmed_apply=True)
        target = int(self._segments()[0]["id"])
        key = self._scene(target)["scene_key"]
        self._put(key, {"transition": "fade", "effect": "zoom_out"})
        again = self._put(key, {"transition": "fade", "effect": "zoom_out"})
        self.assertEqual((again["status"], again["conflicts"]), ("unchanged", []))
        everything = self._step(confirmed_apply=True)["applied"]
        self.assertEqual(self._conflicts(everything), [], "the next apply of the whole document finds no conflict")
        self.assertEqual(self._scene_of(target)["applied"], "applied")
        self.assertEqual((self._seg(target)["edit_transition"], self._seg(target)["edit_effect"]), ("fade", "zoom_out"))

    def test_a_scene_not_planned_yet_takes_the_hand_edit_as_its_plan(self) -> None:
        # No plan run yet: the first hand edit makes the EditDocument (its bootstrap) and plans that scene with it.
        target = int(self._segments()[0]["id"])
        board = self.database.get_latest_project_storyboard(self.project_id, script_id=self.script_id)
        seen = es.preview(self.database, self.project_id, self.script_id, board)
        key = next(item["scene_key"] for item in seen["document"]["scenes"] if item["segment_id"] == target)
        answer = self._put(key, {"overlays": HAND_OVERLAYS})
        self.assertEqual(answer["status"], "applied")
        self.assertEqual(self._scene(target)["status"], ed.READY)
        others = [item for item in self._doc()["scenes"] if item["segment_id"] != target]
        self.assertTrue(others and all(item["status"] == ed.NEEDS_PLAN for item in others), "the others are left unplanned")

    def test_beats_are_written_from_the_scene_start_and_replace_the_rows_beats(self) -> None:
        self._step(confirmed_apply=True)
        target = int(self._segments()[0]["id"])
        seconds = float(self._scene(target)["voice"]["duration_seconds"])
        half = round(seconds / 2, 3)
        answer = self._put(self._scene(target)["scene_key"], {"beats": [
            {"source_kind": "primary", "duration_seconds": half, "effect": "zoom_in", "prompt": "nhịp A"},
            {"source_kind": "primary", "duration_seconds": round(seconds - half, 3), "transition": "fade", "prompt": "nhịp B"}]})
        self.assertEqual(answer["status"], "applied")
        beats = self._beats(target)
        self.assertEqual([(beat["prompt"], beat["start_seconds"]) for beat in beats], [("nhịp A", 0.0), ("nhịp B", half)])
        self.assertEqual(len(self._scene(target)["edit"]["beats"]), 2)


class RefusalTests(_SceneEditCase):
    def setUp(self) -> None:
        super().setUp()
        self._step(confirmed_apply=True)
        self.target = int(self._segments()[0]["id"])
        self.key = self._scene(self.target)["scene_key"]

    def _refused(self, body: dict, expect: int, key: str | None = None) -> dict:
        state = self._db_state()
        answer = self._put(key or self.key, body, expect=expect)
        self.assertEqual(self._db_state(), state, "nothing was written")
        return answer

    def test_wrong_data_is_422_and_writes_nothing(self) -> None:
        seconds = float(self._scene(self.target)["voice"]["duration_seconds"])
        self._refused({}, 422)
        self._refused({"transition": "wipe"}, 422)
        self.assertIn("ít nhất một nhịp", self._refused({"beats": []}, 422)["detail"], "said as such, not as a length")
        self._refused({"beats": [{"duration_seconds": seconds + 3}]}, 422)
        self._refused({"sound_cues": [{"type": "whoosh", "start_seconds": 0.0, "end_seconds": seconds + 5}]}, 422)

    def test_an_unknown_scene_is_404(self) -> None:
        self._refused({"note": "x"}, 404, key="sk-khong-co")

    def test_a_script_revised_since_writes_nothing(self) -> None:
        self._revise(line_of_section=2)              # a new script, no storyboard cut for it yet
        self._refused({"overlays": HAND_OVERLAYS}, 409)

    def test_a_storyboard_that_is_not_current_writes_nothing(self) -> None:
        self._reword_in_place(1)                     # the script changed in place, the storyboard not cut again
        self._refused({"overlays": HAND_OVERLAYS}, 409)

    def test_a_project_outside_the_plan_workflow_writes_nothing_and_keeps_its_timeline_routes(self) -> None:
        with mock.patch.object(main, "_storyboard_gate", return_value=({"mode": "legacy", "state": "not_applicable"}, None)):
            answer = self._refused({"overlays": HAND_OVERLAYS}, 409)
            row = self._patch_plan(self.target, overlays=MANUAL_OVERLAYS)   # the legacy route still writes the row, as before
        self.assertIn("luồng Kế hoạch", answer["detail"])
        self.assertEqual(json.loads(row["overlays"])[0]["text"], MANUAL_OVERLAYS[0]["text"])

    def test_beats_a_scene_job_points_at_are_never_replaced(self) -> None:
        seconds = float(self._scene(self.target)["voice"]["duration_seconds"])
        self._put(self.key, {"beats": [{"duration_seconds": seconds}]})
        beat = self._beats(self.target)[0]
        job = self.database.create_scene_generation_job(self.project_id, self.target, "dry_run", "p",
                                                        edit_beat_id=int(beat["id"]))
        with self.database._connect() as connection:
            connection.execute("UPDATE scene_generation_jobs SET status = 'error' WHERE id = ?", (int(job["id"]),))
        answer = self._refused({"beats": [{"duration_seconds": seconds, "prompt": "khác"}]}, 409)
        self.assertIn("job", answer["detail"])
        # The scene's edit still names its beats: any edit of it would be skipped by the apply (beat_has_jobs),
        # so it is refused before a version is kept that could never reach the row.
        self._refused({"note": "chỉ ghi chú"}, 409)
        self.assertEqual([item["id"] for item in self._beats(self.target)], [beat["id"]])
        self.assertEqual(self.database.get_scene_generation_job(int(job["id"]))["edit_beat_id"], int(beat["id"]))

    def test_a_scene_job_still_running_on_the_row_writes_nothing(self) -> None:
        self.database.create_scene_generation_job(self.project_id, self.target, "dry_run", "p")   # queued
        self._refused({"overlays": HAND_OVERLAYS}, 409)


class ConcurrentEditTests(_SceneEditCase):
    """Two hand edits of one scene: one made from a version another request has moved on from is never kept."""

    def setUp(self) -> None:
        super().setUp()
        self._step(confirmed_apply=True)
        self.target = int(self._segments()[0]["id"])
        self.key = self._scene(self.target)["scene_key"]
        self.planned_note = self._seg(self.target)["edit_note"]

    def _texts(self, overlays: list) -> list:
        return [item["text"] for item in overlays]

    def test_an_edit_kept_in_between_is_never_written_over_by_one_made_before_it(self) -> None:
        real_sync = es.sync
        first: dict = {}

        def sync_then_another_request(*args, **kwargs):
            synced = real_sync(*args, **kwargs)
            if "a" not in first:
                first["a"] = None   # set before A runs: A's own sync goes straight through
                # B has checked its version (preview == sync): A is kept and applied right then, before B writes.
                first["a"] = self._put(self.key, {"overlays": HAND_OVERLAYS})
            return synced

        versions = self._count(EDIT_DOCUMENT_KIND)
        with mock.patch.object(es, "sync", side_effect=sync_then_another_request):
            response = self.client.put(f"/api/projects/{self.project_id}/edit-document/scenes/{self.key}",
                                       json={"note": "ghi chú của B"})

        self.assertEqual(first["a"]["status"], "applied", "A was kept and applied")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("phiên bản mới hơn", response.json()["detail"], "B is told the document moved on")
        self.assertEqual(self._count(EDIT_DOCUMENT_KIND), versions + 1, "A's version only; nothing kept for B")
        edit = self._scene(self.target)["edit"]
        self.assertEqual(self._texts(edit["layers"]["overlays"]), ["Chữ sửa tay T6a"], "A's overlays kept in the document")
        self.assertEqual(edit["visual"].get("edit_note") or "", self.planned_note or "", "B's note was not kept")
        row = self._seg(self.target)
        self.assertEqual(self._texts(self._overlays(self.target)), ["Chữ sửa tay T6a"], "and on the timeline")
        self.assertEqual(row["edit_note"], self.planned_note, "B's note did not reach the row")
        self.assertEqual(self._scene_of(self.target)["applied"], "applied")

    def test_two_edits_one_after_the_other_both_stand(self) -> None:
        a = self._put(self.key, {"overlays": HAND_OVERLAYS})
        b = self._put(self.key, {"note": "ghi chú của B"})   # made from A's version, the latest
        self.assertEqual((a["status"], b["status"]), ("applied", "applied"))
        edit = self._scene(self.target)["edit"]
        self.assertEqual((self._texts(edit["layers"]["overlays"]), edit["visual"]["edit_note"]),
                         (["Chữ sửa tay T6a"], "ghi chú của B"))
        self.assertEqual((self._texts(self._overlays(self.target)), self._seg(self.target)["edit_note"]),
                         (["Chữ sửa tay T6a"], "ghi chú của B"))


class ConflictTests(_SceneEditCase):
    def test_a_row_holding_a_hand_edit_outside_the_document_is_a_conflict_never_overwritten(self) -> None:
        self._step(confirmed_apply=True)
        target = int(self._segments()[0]["id"])
        self._patch_plan(target, overlays=MANUAL_OVERLAYS)               # straight to the timeline, outside the document
        held = self._layers(self._seg(target))
        answer = self._put(self._scene(target)["scene_key"], {"transition": "fade"})
        self.assertEqual(answer["status"], "blocked", "never called applied")
        self.assertEqual([item["segment_id"] for item in answer["conflicts"]], [target])
        self.assertIn("overlays", answer["conflicts"][0]["columns"])
        self.assertEqual(self._layers(self._seg(target)), held, "the row keeps what it holds")
        self.assertEqual(self._scene(target)["edit"]["visual"]["edit_transition"], "fade",
                         "the hand edit is kept in the EditDocument, not on the row")
