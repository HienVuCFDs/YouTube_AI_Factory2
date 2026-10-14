"""Bước 05 · T7 render gate, T8 (F5 · F6 · F8).

Gate A - a planned project's long video renders only what its storyboard and its EditDocument say: the plan applied
to every planned scene's row (edit_not_applied), no row edited since by another path (conflict), no layers made for
other words or timing (stale_layers), the EditDocument of the current storyboard. A scene with no plan renders.
Gate B - its voices are made with the project's voice settings as they are now and say the scene's words; a voice
file whose settings cannot be read is refused unless a person accepts that very file (accept_unverified_voices).
Asked by the job route (409, with every reason and what to do), by the worker as it takes the job (retry included)
and by the render itself on the very rows it reads - before anything is measured, drawn or written.

T8 · F5 a planned scene's subtitle says its narration; F6 a voice attached to it is one made with the project's voice
settings; F8 a scene's description (visual_prompt) is one value, on its row and its shot alike.

Every test runs on the test suite's temporary database (tests/conftest.py), fake models, no app, no worker.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from tests.test_legacy_timeline_writes import _LegacyCase, _RouteCase
from youtube_monitor import main, production_worker


class _GateCase(_RouteCase):
    def _records(self, *, fingerprint: str | None = None, words: dict[int, str] | None = None) -> None:
        """A record beside every voice file, as the voiceover job writes it."""
        current = main._current_voice_fingerprint(self.project_id)
        for row in self._segments():
            production_worker.write_voice_record(
                row["audio_path"], voice_text=(words or {}).get(int(row["id"]), row["voice_text"]), speaker=str(row.get("speaker") or ""),
                fingerprint=fingerprint or current, config={}, segment_id=int(row["id"]))

    def _blockers(self) -> list[dict]:
        return main._render_blockers(self.project_id, self.script_id)

    def _codes(self) -> set:
        return {item["code"] for item in self._blockers()}

    def _render(self, **body):
        return self.client.post(f"/api/projects/{self.project_id}/jobs",
                                json={"job_type": "render", "provider": "dry_run", **body})

    def _jobs(self) -> list:
        return self.database.list_project_jobs(self.project_id, limit=100)


class _ApplyCase(_GateCase):
    def setUp(self) -> None:
        super().setUp()
        self._records()
        self._step(confirmed_apply=True)           # planned and applied
        self.target = int(self._segments()[0]["id"])


# ===========================================================================
# Gate A
# ===========================================================================

class EditDocumentGateTests(_ApplyCase):
    def test_a_plan_applied_to_every_scene_with_its_voices_renders(self) -> None:
        self.assertEqual(self._blockers(), [])
        response = self._render()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(main._job_gate_reason({"job_type": "render", "project_id": self.project_id,
                                                "script_id": self.script_id}), "")

    def test_a_plan_kept_but_not_applied_is_refused_with_its_reason_and_what_to_do(self) -> None:
        self._put(self._scene(self.target)["scene_key"], {"transition": "fade"})   # kept and applied: fine
        planned = main.edit_store.load(self.database, self.project_id, self.script_id)
        self.assertIsNotNone(planned)
        self._step(replan=True)                                                   # planned again, not applied
        if self._blockers() == []:
            self.skipTest("the planner's second plan is the same edit: nothing to apply")
        jobs = self._jobs()
        response = self._render()
        self.assertEqual(response.status_code, 409, response.text)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "render_blocked")
        self.assertIn("edit_not_applied", {item["code"] for item in detail["blockers"]})
        self.assertTrue(all(item["next_step"] for item in detail["blockers"]))
        self.assertEqual(self._jobs(), jobs, "no job made")

    def test_a_row_edited_by_hand_since_the_apply_is_refused_and_never_written_over(self) -> None:
        with self._outside():
            self._patch_plan(self.target, transition="fade" if self._seg(self.target)["edit_transition"] != "fade" else "cut")
        held = self._seg(self.target)["edit_transition"]
        blockers = self._blockers()
        self.assertEqual([(item["code"], item["segment_ids"]) for item in blockers], [("conflict", [self.target])])
        self.assertIn("edit_transition", blockers[0]["columns"])
        self.assertEqual(self._render().status_code, 409)
        self.assertEqual(self._seg(self.target)["edit_transition"], held, "the gate writes nothing")

    def test_the_worker_asks_again_when_it_takes_the_job_and_on_retry(self) -> None:
        job = self.database.create_project_job(self.project_id, self.script_id, "render", "dry_run")
        with self._outside():
            self._patch_plan(self.target, note="sửa ngoài kế hoạch")
        reason = main._job_gate_reason(job)
        self.assertTrue(reason.startswith("Chưa thể dựng video:"), reason)
        self.database.finish_project_job(int(job["id"]), "error", error="x")
        response = self.client.post(f"/api/jobs/{job['id']}/retry")
        self.assertEqual(response.status_code, 409, response.text)

    def test_the_render_checks_the_very_rows_it_reads_before_touching_anything(self) -> None:
        project = self.database.get_production_project(self.project_id)
        script = self.database.get_project_script(self.script_id)
        timeline = self.database.attach_edit_beats_to_timeline(
            self.project_id, self.database.list_project_timeline(self.project_id, script_id=self.script_id), script_id=self.script_id)
        self.assertEqual(production_worker._render_gate(project, script, timeline), "")
        changed = [dict(row) for row in timeline]
        changed[0]["overlays"] = json.dumps([{"kind": "text", "text": "chen giữa chừng", "start_seconds": 0, "end_seconds": 1}])
        self.assertIn("ngoài kế hoạch dựng", production_worker._render_gate(project, script, changed))
        # Through the render itself: refused before the cleanups are measured or anything is drawn.
        with self._outside():
            self._patch_plan(self.target, note="sửa ngoài kế hoạch")
        job = {"id": 1, "project_id": self.project_id, "script_id": self.script_id, "job_type": "render", "provider": "ffmpeg_builtin"}
        with mock.patch.object(production_worker, "_autocover_source_marks", side_effect=AssertionError("measured")) as cover, \
                self.assertRaises(production_worker.ProductionJobError) as refused:
            production_worker.run_render_job(self.database, job, self.tmp, "")
        cover.assert_not_called()
        self.assertIn("Chưa thể dựng video", str(refused.exception))

    def test_storyboard_to_edit_document_to_timeline_to_voice_to_render(self) -> None:
        # The whole way, on the real render (dry_run writes its manifest): what it reads is what the plan applied.
        job = {"id": 1, "project_id": self.project_id, "script_id": self.script_id, "job_type": "render", "provider": "dry_run"}
        manifest = json.loads(Path(production_worker.run_render_job(self.database, job, self.tmp, "")).read_text(encoding="utf-8"))
        self.assertTrue(manifest)
        applied = {int(item["segment_id"]): item["layer_hash"] for entry in self.database.list_edit_applies(self.project_id)
                   for item in entry["payload"]["rows"]}
        self.assertIn(self.target, applied, "the plan was applied to the row rendered")

    def test_layers_made_for_other_timing_are_refused(self) -> None:
        original = main.edit_store.preview

        def marked(*args, **options):
            seen = original(*args, **options)
            for scene in seen["document"]["scenes"]:
                if scene.get("segment_id") == self.target:
                    scene["statuses"] = ["stale_timing"]
            return seen

        with mock.patch.object(main.edit_store, "preview", side_effect=marked):
            blockers = self._blockers()
        self.assertIn(("stale_layers", [self.target]), [(item["code"], item["segment_ids"]) for item in blockers])

    def test_readiness_says_what_the_gate_would_refuse(self) -> None:
        self.assertEqual(main._render_readiness(self.project_id)["render_gate"], [])
        with self._outside():
            self._patch_plan(self.target, note="sửa ngoài kế hoạch")
        readiness = main._render_readiness(self.project_id)
        self.assertFalse(readiness["can_render"])
        self.assertEqual([item["code"] for item in readiness["render_gate"]], ["conflict"])
        self.assertTrue(any("ngoài kế hoạch dựng" in issue for issue in readiness["issues"]))

    def test_a_storyboard_that_is_not_current_is_refused(self) -> None:
        self._reword_in_place(1)
        self.assertEqual(self._render().status_code, 409)
        self.assertIn("storyboard", self._codes())


class NoPlanYetTests(_GateCase):
    def test_scenes_without_any_edit_render_their_rows(self) -> None:
        self._records()
        self.assertEqual(self._blockers(), [], "no EditDocument: plain scenes render")
        self._sync(self.project_id, self.script_id)               # an EditDocument, every scene needs_plan
        self.assertEqual(self._blockers(), [], "a scene that needs a plan is not held")


class OutsideThePlanWorkflowTests(_LegacyCase):
    def test_nothing_is_held_as_before(self) -> None:
        self.assertEqual(main._render_blockers(self.project_id, self.script_id), [])


# ===========================================================================
# Gate B
# ===========================================================================

class VoiceGateTests(_GateCase):
    def test_voices_made_with_other_settings_are_refused_and_the_same_settings_again_need_no_new_voice(self) -> None:
        self._records()
        self.assertEqual(self._codes(), set())
        settings = self.database.get_project_render_settings(self.project_id)
        self.database.update_project_render_settings(self.project_id, voice_provider="edge_tts", voice_model="vi-VN-NamMinhNeural")
        self.assertEqual(self._codes(), {"voice_outdated"})
        self.assertEqual(self._render().status_code, 409)
        self.database.update_project_render_settings(self.project_id, voice_provider=settings.get("voice_provider") or "edge_tts",
                                                     voice_model=settings.get("voice_model") or "vi-VN-HoaiMyNeural")
        self.assertEqual(self._codes(), set(), "back to the settings the voices were made with: they are good again")

    def test_a_voice_that_says_other_words_is_refused(self) -> None:
        self._records(words={self.target: "Một lời khác hẳn."})
        blockers = self._blockers()
        self.assertEqual([(item["code"], item["segment_ids"]) for item in blockers], [("voice_words_changed", [self.target])])

    def test_a_voice_with_no_record_is_refused_unless_that_very_file_is_accepted(self) -> None:
        self.assertEqual(self._codes(), {"voice_unverified"}, "never let through in silence")
        refused = self._render()
        self.assertEqual(refused.status_code, 409)
        self.assertIn("accept_unverified_voices", json.dumps(refused.json(), ensure_ascii=False))
        accepted = self._render(accept_unverified_voices=True)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(self._codes(), set())
        Path(self._seg(self.target)["audio_path"]).write_bytes(b"RIFF-another-file")   # another file now: not accepted
        self.assertEqual([(item["code"], item["segment_ids"]) for item in self._blockers()], [("voice_unverified", [self.target])])


# ===========================================================================
# T8
# ===========================================================================

class SubtitleTests(_GateCase):
    def test_a_planned_scenes_subtitle_says_its_narration(self) -> None:
        row = self._seg(self.target)
        state = self._db_state()
        response = self.client.patch(f"/api/timeline/{self.target}", json={"subtitle_text": "Một câu khác hẳn."})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self._db_state(), state)
        same = row["voice_text"].rstrip(".") + "!"                       # punctuation and spacing only
        self.assertEqual(self.client.patch(f"/api/timeline/{self.target}", json={"subtitle_text": "  " + same}).status_code, 200)


class SubtitleOutsideThePlanWorkflowTests(_LegacyCase):
    def test_any_subtitle_as_before(self) -> None:
        response = self.client.patch(f"/api/timeline/{self.target}", json={"subtitle_text": "Phụ đề riêng."})
        self.assertEqual(response.status_code, 200, response.text)


class AttachVoiceTests(_GateCase):
    def _attach(self, *, fingerprint: str | None, record: bool = True):
        row = self._seg(self.target)
        audio = self.tmp / "thu-vien.wav"
        audio.write_bytes(b"RIFF")
        if record:
            production_worker.write_voice_record(audio, voice_text=row["voice_text"], speaker="", config={}, segment_id=self.target,
                                                 fingerprint=fingerprint or main._current_voice_fingerprint(self.project_id))
        library = {"k": {"audio_path": str(audio), "text": row["voice_text"]}}
        with mock.patch.object(main.voice_library, "index_voices", return_value=library):
            return self.client.post(f"/api/timeline/{self.target}/attach-generated-voice", json={"voice_key": "k"})

    def test_only_a_voice_made_with_the_projects_settings_is_attached(self) -> None:
        before = self._seg(self.target)["audio_path"]
        self.assertEqual(self._attach(fingerprint="khac-cau-hinh").status_code, 409)
        self.assertEqual(self._attach(fingerprint=None, record=False).status_code, 409)
        self.assertEqual(self._seg(self.target)["audio_path"], before)
        attached = self._attach(fingerprint=None)
        self.assertEqual(attached.status_code, 200, attached.text)
        self.assertTrue(self._seg(self.target)["audio_path"].endswith("thu-vien.wav"))


class VisualPromptOneValueTests(_GateCase):
    def _shot_of(self, segment_id: int) -> dict:
        return self.database.get_project_shot(int(self._seg(segment_id)["shot_id"]))

    def test_a_shot_and_its_row_say_the_same_description_whichever_is_edited(self) -> None:
        self.assertTrue(self._seg(self.target)["shot_id"])
        self._patch(self.target, visual_prompt="mô tả sửa trên timeline")
        self.assertEqual(self._shot_of(self.target)["visual_prompt"], "mô tả sửa trên timeline")
        response = self.client.patch(f"/api/shots/{self._seg(self.target)['shot_id']}", json={"visual_prompt": "mô tả sửa trên shot"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._seg(self.target)["visual_prompt"], "mô tả sửa trên shot")

    def test_the_legacy_edit_plans_extra_picture_note_reaches_the_scenes_row(self) -> None:
        self.database.apply_project_edit_plan_scenes(self.project_id, self.script_id, [
            {"segment_id": self.target, "kind": "image", "needs_extra_visual": True, "extra_visual_note": "cần thêm cận cảnh"}])
        self.assertEqual(self._seg(self.target)["visual_prompt"], "cần thêm cận cảnh")
        self.assertEqual(self._shot_of(self.target)["visual_prompt"], "cần thêm cận cảnh")
