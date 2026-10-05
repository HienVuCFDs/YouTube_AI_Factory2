"""Bước 3 · Phase 2.2: the production gate where the work actually runs, and where a Short comes from.

    enqueue ── gate ──► queue ──► worker claims ── gate again ──► TTS / render / model / upload

A job checked when it was queued can be picked up after the plan or the
script has moved on. Each worker - production (voice, render, Short),
scene generation, publishing - asks the same shared gate again the moment it
claims the work, through `_process` itself, and stops before anything costly
or lasting happens. A Short records the script and plan it was made from,
and is held to them. The direct routes that make new artifacts from the
storyboard meet the same gate; review, manual edits and source processing
do not.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from tests.script_fixtures import FIXTURE_78, PLAN, Scripted, planned_project, write_current_script
from tests.test_script_paths import _legacy_project, _snapshot
from youtube_monitor import ai_desktop_mcp, main, production_worker as worker_module, script_engine

GO = script_engine.CONTINUE_MESSAGES
STALE = script_engine.STALE_SCRIPT_MESSAGE
FORBIDDEN = "Mọi khán giả đều thích video ngắn về vũ trụ hơn video dài."
db = main.database


def _boom(*args, **kwargs):
    raise AssertionError("must not be called")


# ---------------------------------------------------------------------------
# Projects in a given state, made without the HTTP layer
# ---------------------------------------------------------------------------

def _build(project_id: int) -> None:
    main.generate_project_shots(project_id, main.GenerateShotsRequest(force=True))
    main.generate_project_timeline(project_id, main.GenerateTimelineRequest(force=True))


def _ready(**setup) -> int:
    """Plan completed, script written by the engine, storyboard and timeline cut."""
    project_id = planned_project(db, **setup)
    write_current_script(db, project_id)
    _build(project_id)
    return project_id


def _bump_plan(project_id: int, plan: dict | None = None) -> dict:
    latest = db.get_latest_project_plan(project_id)
    return db.create_project_plan(
        project_id, status="completed", research_report_id=latest["research_report_id"],
        analysis_created_at=latest["analysis_created_at"], engine_version="plan-phase3", plan=plan or latest["plan"],
        feasibility={"status": "ok", "checks": []}, insight_report_id=latest["insight_report_id"])


def _invalidate(project_id: int) -> None:
    script = db.get_latest_project_script(project_id)
    saved = main.update_script(int(script["id"]), main.UpdateScriptRequest(main_content=script["main_content"] + "\n" + FORBIDDEN))
    assert saved["state"] == "invalid"


def _job(project_id: int, job_type: str = "voiceover", *, script_id: int | None = None, force: bool = False) -> int:
    script_id = script_id or int(db.get_latest_project_script(project_id)["id"])
    return int(db.create_project_job(project_id, script_id, job_type, "dry_run", force=force)["id"])


def _status(job_id: int) -> tuple[str, str]:
    job = db.get_project_job(job_id)
    return job["status"], job["error"]


def _short(project_id: int) -> dict:
    """A standalone Short written by the Short lane from the project's current long script."""
    return main.write_project_short_script(project_id, main.ShortScriptRequest(seconds=30, use_model=False))["script"]


class _Runners:
    """Every expensive thing the production worker could do, replaced by a recorder."""

    def __init__(self, tmp: Path) -> None:
        self.calls: list[str] = []
        self.tmp = tmp

    def __enter__(self):
        self._patches = []
        for name in ("run_voiceover_job", "run_render_job", "run_short_render_job", "run_source_visuals_job",
                     "run_premiere_draft_job", "run_director_production_job", "run_voxcpm_voice_preview_job"):
            def runner(*args, _name=name, **kwargs):
                self.calls.append(_name)
                return str(self.tmp / f"{_name}.out")
            patcher = mock.patch.object(worker_module, name, side_effect=runner)
            patcher.start()
            self._patches.append(patcher)
        return self

    def __exit__(self, *exc):
        for patcher in self._patches:
            patcher.stop()


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.model = Scripted()
        patcher = mock.patch.object(main, "_call_orchestrator_json", self.model)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_job(self, job_id: int) -> list[str]:
        """The production worker's real execution path for one job; returns what it ran."""
        with _Runners(self.tmp) as runners:
            main.production_worker._process(job_id)
        return runners.calls


# ===========================================================================
# 1. The production worker (voice, render, Short render, exports)
# ===========================================================================

class ProductionWorkerTests(_Case):
    def test_1_and_12_a_job_for_the_current_script_runs(self) -> None:
        project_id = _ready()
        job_id = _job(project_id)
        self.assertEqual(self.run_job(job_id), ["run_voiceover_job"])
        self.assertEqual(_status(job_id)[0], "completed")
        # 12. The plan moving on afterwards does not touch a job that already ran.
        _bump_plan(project_id)
        self.assertEqual(_status(job_id)[0], "completed")

    def test_2_7_8_the_plan_moved_on_before_the_worker_took_it(self) -> None:
        project_id = _ready()
        voice, render = _job(project_id), _job(project_id, "render", force=True)
        _bump_plan(project_id)
        for job_id in (voice, render):
            self.assertEqual(self.run_job(job_id), [], "no TTS, no render")
            self.assertEqual(_status(job_id), ("error", STALE))
        self.assertEqual(self.model.calls, [])

    def test_3_a_job_for_an_earlier_version_of_the_script_does_not_run_on_the_new_one(self) -> None:
        project_id = _ready()
        old = _job(project_id)
        write_current_script(db, project_id)   # rewritten from the same plan: the new version is current
        self.assertEqual(self.run_job(old), [])
        self.assertEqual(_status(old), ("error", GO["superseded"]))
        _build(project_id)
        new = _job(project_id)
        self.assertEqual(self.run_job(new), ["run_voiceover_job"])

    def test_4_an_invalid_script_runs_nothing(self) -> None:
        project_id = _ready()
        job_id = _job(project_id)
        _invalidate(project_id)
        self.assertEqual(self.run_job(job_id), [])
        self.assertEqual(_status(job_id), ("error", GO["invalid"]))

    def test_5_a_retry_is_checked_again_and_queues_nothing(self) -> None:
        project_id = _ready()
        job_id = _job(project_id)
        db.finish_project_job(job_id, "error", error="TTS hết giờ")
        _bump_plan(project_id)
        with mock.patch.object(main.production_worker, "enqueue", _boom), self.assertRaises(HTTPException) as refused:
            main.retry_project_job(job_id)
        self.assertEqual((refused.exception.status_code, refused.exception.detail), (409, STALE))
        jobs = db.list_project_jobs(project_id, limit=50)
        self.assertEqual([(job["id"], job["status"]) for job in jobs], [(job_id, "error")])

    def test_6_a_refusal_asks_no_model_and_force_changes_nothing(self) -> None:
        project_id = _ready()
        job_id = _job(project_id, "render", force=True)
        _bump_plan(project_id)
        self.model.calls.clear()
        self.assertEqual(self.run_job(job_id), [])
        self.assertEqual(self.model.calls, [])

    def test_11_what_earlier_jobs_made_is_left_alone(self) -> None:
        project_id = _ready()
        script = db.get_latest_project_script(project_id)
        segment = db.list_project_timeline(project_id, script_id=int(script["id"]))[0]
        voice = self.tmp / "scene-1.mp3"
        voice.write_bytes(b"ID3 valid voice")
        db.update_project_timeline_segment(int(segment["id"]), audio_path=str(voice))
        final = main.ensure_project_layout(main.PRODUCTION_ARTIFACT_DIR, project_id)["exports"] / "final.mp4"
        final.write_bytes(b"valid render")
        job_id = _job(project_id, "render")
        _bump_plan(project_id)
        self.assertEqual(self.run_job(job_id), [])
        self.assertEqual((voice.read_bytes(), final.read_bytes()), (b"ID3 valid voice", b"valid render"))
        self.assertEqual(db.get_project_timeline_segment(int(segment["id"]))["audio_path"], str(voice))

    def test_outside_the_plan_workflow_and_voice_auditions_run_as_before(self) -> None:
        project = db.create_idea_project("Kịch bản dán tay", title="Ngoài kế hoạch")
        script = db.create_project_script(int(project["id"]), script_title="x", main_content="Một câu.")
        job_id = _job(int(project["id"]), script_id=int(script["id"]))
        self.assertEqual(self.run_job(job_id), ["run_voiceover_job"])
        # A voice audition reads a fixed sample sentence, never the script: not gated.
        stale = _ready()
        _bump_plan(stale)
        preview = _job(stale, "voice_preview")
        self.assertEqual(self.run_job(preview), ["run_voxcpm_voice_preview_job"])


# ===========================================================================
# 2. The scene-generation worker and the publisher
# ===========================================================================

class SceneAndPublisherWorkerTests(_Case):
    def _scene_job(self, project_id: int) -> int:
        script = db.get_latest_project_script(project_id)
        segment = db.list_project_timeline(project_id, script_id=int(script["id"]))[0]
        return int(db.create_scene_generation_job(project_id, int(segment["id"]), "gemini_image", "Cảnh mở đầu",
                                                  job_kind="image", prompt_pending=True)["id"])

    def _run_scene(self, job_id: int) -> dict:
        image = self.tmp / f"scene-{job_id}.png"
        image.write_bytes(b"\x89PNG fake")
        seen = {"prompt": 0, "execute": 0}

        def crafter(job):
            seen["prompt"] += 1
            return "A planet turning slowly"

        def execute(*args, **kwargs):
            seen["execute"] += 1
            return str(image)

        worker = main.scene_generation_worker
        with mock.patch.object(worker, "_prompt_crafter", crafter), mock.patch.object(worker, "_completion_callback", None), \
                mock.patch.object(worker, "_failure_router", None), mock.patch.object(worker.provider_gateway, "execute_scene", execute):
            worker._process(job_id)
        return seen

    def test_10_a_scene_job_for_a_stale_script_asks_no_model(self) -> None:
        project_id = _ready()
        fresh = self._scene_job(project_id)
        self.assertEqual(self._run_scene(fresh), {"prompt": 1, "execute": 1})
        self.assertEqual(db.get_scene_generation_job(fresh)["status"], "completed")
        queued = self._scene_job(project_id)
        _bump_plan(project_id)
        self.assertEqual(self._run_scene(queued), {"prompt": 0, "execute": 0}, "no prompt written, no provider called")
        job = db.get_scene_generation_job(queued)
        self.assertEqual((job["status"], job["error"]), ("error", STALE))
        self.assertIsNone(job.get("output_asset_id"))

    def test_9_a_publication_for_a_stale_script_is_not_uploaded(self) -> None:
        def publish(project_id: int, upload) -> dict:
            publication = db.create_project_publication(project_id, str(self.tmp / "final.mp4"), "Video", status="queued")
            with mock.patch.object(db, "list_due_project_publications", return_value=[publication]), \
                    mock.patch.object(main.publisher_worker.publisher, "upload_video", upload):
                main.publisher_worker._process_due()
            return db.get_project_publication(int(publication["id"]))

        project_id = _ready()
        done = publish(project_id, mock.Mock(return_value={"id": "yt-1"}))
        self.assertEqual((done["status"], done["youtube_video_id"]), ("completed", "yt-1"))
        _bump_plan(project_id)
        upload = mock.Mock()
        refused = publish(project_id, upload)
        upload.assert_not_called()
        self.assertEqual((refused["status"], refused["error"]), ("error", STALE))
        self.assertEqual(db.get_project_publication(int(done["id"]))["status"], "completed", "the earlier upload is untouched")


# ===========================================================================
# 3. Short provenance
# ===========================================================================

class ShortProvenanceTests(_Case):
    def test_1_to_12_a_short_is_held_to_the_script_it_was_made_from(self) -> None:
        project_id = _ready()
        script_v1 = db.get_latest_project_script(project_id)
        plan_v1 = db.get_latest_project_plan(project_id)
        plan_before = (plan_v1["id"], plan_v1["version"], plan_v1["plan"])
        long_before = [item["id"] for item in db.list_project_scripts(project_id)]

        # 1. Short A records exactly what it was made from.
        short_a = _short(project_id)
        made = script_engine.short_provenance(db.get_project_script(int(short_a["id"])))
        self.assertEqual((made["source_script_id"], made["source_script_version"], made["plan_id"], made["plan_version"]),
                         (script_v1["id"], script_v1["version"], plan_v1["id"], plan_v1["version"]))
        self.assertEqual((short_a["plan_id"], short_a["plan_version"]), (plan_v1["id"], plan_v1["version"]))
        # 12. It survives a reload and is readable from the API.
        read = main.get_project_short_script(project_id)
        self.assertEqual((read["provenance"]["source_script_id"], read["current"]), (script_v1["id"], True))
        # 10, 11. No second long script, and the plan is untouched.
        self.assertEqual([item["id"] for item in db.list_project_scripts(project_id)], long_before)
        after = db.get_latest_project_plan(project_id)
        self.assertEqual((after["id"], after["version"], after["plan"]), plan_before)

        # 2. Current: its jobs go ahead.
        short_job = _job(project_id, "render_short", script_id=int(short_a["id"]))
        self.assertEqual(self.run_job(short_job), ["run_short_render_job"])

        # 4. The script is rewritten (same plan): Short A is not this script's Short.
        write_current_script(db, project_id)
        queued_a = _job(project_id, "render_short", script_id=int(short_a["id"]))
        self.assertEqual(self.run_job(queued_a), [])
        self.assertEqual(_status(queued_a), ("error", GO["short_stale"]))
        self.assertEqual(main.get_project_short_script(project_id)["blocked_reason"], GO["short_stale"])
        # 6, 7, 8. Retry, render and publish of Short A: 409, no model, nothing queued, Short A unchanged.
        stored_a = db.get_project_script(int(short_a["id"]))
        failed = _job(project_id, "voiceover", script_id=int(short_a["id"]))
        db.finish_project_job(failed, "error", error="x")
        with mock.patch.object(main.production_worker, "enqueue", _boom):
            for call in (lambda: main.retry_project_job(failed),
                         lambda: main.queue_project_job(project_id, main.CreateProductionJobRequest(
                             job_type="render_short", provider="ffmpeg_builtin", confirmed=True, variant="short", force=True)),
                         lambda: main.queue_project_publication(project_id, main.CreatePublicationRequest(
                             confirmed=True, video_variant="short", override_checklist=True))):
                with self.assertRaises(HTTPException) as refused:
                    call()
                self.assertEqual((refused.exception.status_code, refused.exception.detail), (409, GO["short_stale"]))
        self.assertEqual(db.get_project_script(int(short_a["id"])), stored_a, "the old Short is not modified")

        # 3. The plan moves on: Short A is held back (by the plan first).
        _bump_plan(project_id)
        self.assertEqual(main.get_project_short_script(project_id)["blocked_reason"], STALE)

        # 5. Short B, from the script written from the new plan, works.
        write_current_script(db, project_id)
        _build(project_id)
        short_b = _short(project_id)
        script_now = db.get_latest_project_script(project_id)
        self.assertEqual(script_engine.short_provenance(short_b)["source_script_version"], script_now["version"])
        self.assertTrue(main.get_project_short_script(project_id)["current"])
        self.assertEqual(self.run_job(_job(project_id, "render_short", script_id=int(short_b["id"]))), ["run_short_render_job"])
        self.assertEqual(self.model.calls, [], "no model asked along the way (use_model=False, fake engine)")

    def test_a_re_cut_short_records_its_script_too(self) -> None:
        project_id = _ready()
        script = db.get_latest_project_script(project_id)
        for segment in db.list_project_timeline(project_id, script_id=int(script["id"])):
            db.update_project_timeline_segment(int(segment["id"]), audio_path="a.mp3", visual_path="v.png")
        main.plan_project_short(project_id, main.ShortPlanRequest(use_model=False))
        stored = db.get_project_short(project_id)["plan"]["provenance"]
        self.assertEqual((stored["source_script_id"], stored["source_script_version"]), (script["id"], script["version"]))
        self.assertEqual(self.run_job(_job(project_id, "render_short")), ["run_short_render_job"])
        write_current_script(db, project_id)   # a new version: the re-cut belongs to the old one
        recut = _job(project_id, "render_short")
        self.assertEqual(self.run_job(recut), [])
        self.assertEqual(_status(recut), ("error", GO["short_stale"]))

    def test_9_a_short_outside_the_plan_workflow_works_as_before(self) -> None:
        project = db.create_idea_project("Chỉ làm Short", title="Short riêng")
        project_id = int(project["id"])
        db.create_project_script(project_id, script_title="Bản dài", hook="Mở đầu thật nhanh.",
                                 main_content="Anh dựng nhà giữa rừng. " * 30, cta="Theo dõi nhé.")
        short = _short(project_id)
        self.assertIsNone(script_engine.short_provenance(short))
        self.assertEqual(self.run_job(_job(project_id, "render_short", script_id=int(short["id"]))), ["run_short_render_job"])
        self.assertTrue(main.get_project_short_script(project_id)["current"])


# ===========================================================================
# 4. Direct routes that make something new from the storyboard, and those that do not
# ===========================================================================

class DownstreamRouteTests(_Case):
    @classmethod
    def setUpClass(cls) -> None:
        cls._client_cm = TestClient(main.app)
        cls.client = cls._client_cm.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)

    def setUp(self) -> None:
        super().setUp()
        for target, returned in ((main.production_worker, {"id": 1, "status": "queued"}), (main.scene_generation_worker, None)):
            patcher = mock.patch.object(target, "enqueue", mock.Mock(return_value=returned))
            patcher.start()
            self.addCleanup(patcher.stop)

    def _over_mcp(self):
        def request(path, method="GET", data=None, headers=None, timeout=None):
            response = self.client.request(method, path, content=data, headers=headers or {})
            if response.status_code >= 400:
                raise RuntimeError(str(response.json().get("detail")))
            return response.json()
        return mock.patch.object(ai_desktop_mcp, "_factory_request", side_effect=request)

    def _produce(self, project_id: int, client: TestClient | None = None) -> dict:
        """Every direct way of making something new from the storyboard (group A)."""
        script = db.get_latest_project_script(project_id)
        segment = db.list_project_timeline(project_id, script_id=int(script["id"]))[0]
        db.replace_timeline_edit_beats(int(segment["id"]), [{"beat_index": 1, "kind": "ai_image", "duration_seconds": 2,
                                                             "prompt": "x"}])
        # A scene job to retry: cancelled, not failed, so no provider's circuit opens in the shared test database.
        scene = db.create_scene_generation_job(project_id, int(segment["id"]), "gemini_image", "Cảnh mở đầu", job_kind="image")
        db.cancel_queued_scene_generation_job(int(scene["id"]))
        post = (client or self.client).post
        return {
            "scene-jobs": post(f"/api/projects/{project_id}/scene-jobs", json={
                "timeline_segment_id": int(segment["id"]), "provider": "gemini_image", "prompt": "Cảnh", "confirmed": True}),
            "scene-jobs/batch": post(f"/api/projects/{project_id}/scene-jobs/batch", json={"provider": "gemini_image", "confirmed": True}),
            "scene-jobs retry": post(f"/api/scene-jobs/{scene['id']}/retry"),
            "edit-beats generate": post(f"/api/timeline/{segment['id']}/edit-beats/1/generate", json={
                "image_provider": "gemini_image", "confirmed": True}),
            "edit-plan": post(f"/api/projects/{project_id}/edit-plan"),
            "plan-visuals": post(f"/api/projects/{project_id}/timeline/plan-visuals"),
            "plan-source-cues": post(f"/api/projects/{project_id}/timeline/plan-source-cues"),
            "edit-beats/plan": post(f"/api/timeline/{segment['id']}/edit-beats/plan", json={}),
            "thumbnails": post(f"/api/projects/{project_id}/thumbnails/generate", json={}),
            "premiere-export": post(f"/api/projects/{project_id}/premiere-export", json={}),
        }

    def _counts(self, project_id: int) -> tuple:
        return (len(db.list_scene_generation_jobs(project_id, limit=500)), len(db.list_project_thumbnails(project_id)),
                db.get_project_edit_plan(project_id), len(db.list_project_assets(project_id)))

    def test_group_a_is_held_by_the_gate_with_no_model_and_nothing_made(self) -> None:
        project_id = _ready()
        _bump_plan(project_id)
        self.model.calls.clear()
        before = self._counts(project_id)
        for name, response in self._produce(project_id).items():
            self.assertEqual((response.status_code, response.json()["detail"]), (409, STALE), name)
        after = self._counts(project_id)
        self.assertEqual((after[0] - 1, *after[1:]), before, "only the fixture's own cancelled scene job was added")
        self.assertEqual(self.model.calls, [])
        main.scene_generation_worker.enqueue.assert_not_called()
        # MCP reaches the same gate.
        script = db.get_latest_project_script(project_id)
        segment = db.list_project_timeline(project_id, script_id=int(script["id"]))[0]
        for tool, arguments in (("youtube_factory_generate_image", {"project_id": project_id, "segment_id": segment["id"],
                                                                    "provider": "gemini_image", "prompt": "Cảnh mở đầu", "confirmed": True}),
                                ("youtube_factory_plan_project_edit", {"project_id": project_id})):
            with self._over_mcp(), self.assertRaises(RuntimeError) as refused:
                ai_desktop_mcp._call_tool(tool, arguments)
            self.assertEqual(str(refused.exception), STALE, tool)

    def test_group_a_goes_past_the_gate_for_a_current_script(self) -> None:
        """Past the gate each route does what it always did - or fails on its own terms (no provider, no model) - never the gate's."""
        project_id = _ready()
        loose = TestClient(main.app, raise_server_exceptions=False)
        with mock.patch.object(main, "_call_orchestrator_json", return_value={}):
            responses = self._produce(project_id, loose)
        for name, response in responses.items():
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = response.text
            self.assertNotIn(detail, list(GO.values()), name)

    def test_review_manual_edits_and_source_processing_stay_open(self) -> None:
        project_id = _ready()
        _bump_plan(project_id)
        script = db.get_latest_project_script(project_id)
        shot = db.list_project_shots(project_id, script_id=int(script["id"]))[0]
        segment = db.list_project_timeline(project_id, script_id=int(script["id"]))[0]
        post, patch = self.client.post, self.client.patch
        with mock.patch.object(main, "_call_orchestrator_json", return_value={"score": 7, "verdict": "ok", "issues": [], "summary": "ok"}):
            open_doors = {
                "script/review": post(f"/api/projects/{project_id}/script/review"),
                "voice/review": post(f"/api/projects/{project_id}/voice/review"),
                "voice-previews": post(f"/api/projects/{project_id}/voice-previews"),
                "edit-plan/approve": post(f"/api/projects/{project_id}/edit-plan/approve"),
                "edit-plan/apply": post(f"/api/projects/{project_id}/edit-plan/apply"),
                "cleanups": post(f"/api/projects/{project_id}/timeline/cleanups", json={"clear": True}),
                "shot edit": patch(f"/api/shots/{shot['id']}", json={"narration": "Sửa tay một câu."}),
                "segment edit": patch(f"/api/timeline/{segment['id']}", json={"subtitle_text": "Sửa tay."}),
                "transcript translate": post(f"/api/videos/{db.get_production_project(project_id)['youtube_video_id']}/transcript/translate"),
            }
        for name, response in open_doors.items():
            detail = response.json().get("detail") if isinstance(response.json(), dict) else None
            self.assertNotIn(detail, list(GO.values()), (name, response.text))


# ===========================================================================
# 5. Projects 57 and 78
# ===========================================================================

class Project57And78Tests(_Case):
    def test_project_57_continues_nothing_until_it_is_planned_and_written_again(self) -> None:
        project_id = _legacy_project(db)
        old_script = db.get_latest_project_script(project_id)
        before = _snapshot(db, project_id)
        job_id = _job(project_id, "render", script_id=int(old_script["id"]))
        segment = db.list_project_timeline(project_id, script_id=int(old_script["id"]))[0]
        scene = int(db.create_scene_generation_job(project_id, int(segment["id"]), "gemini_image", "Cảnh mở đầu",
                                                   job_kind="image", prompt_pending=True)["id"])
        self.assertEqual(self.run_job(job_id), [])
        self.assertEqual(_status(job_id), ("error", GO["needs_user_decision"]))
        with mock.patch.object(main.scene_generation_worker.provider_gateway, "execute_scene", _boom), \
                mock.patch.object(main.scene_generation_worker, "_prompt_crafter", _boom):
            main.scene_generation_worker._process(scene)
        self.assertEqual(db.get_scene_generation_job(scene)["status"], "error")
        self.assertEqual(self.model.calls, [])
        self.assertEqual(_snapshot(db, project_id), before, "scripts, scenes, timeline, writer and plan untouched")
        # The decision is made and the script written again: production goes ahead.
        _bump_plan(project_id, PLAN)
        write_current_script(db, project_id)
        _build(project_id)
        self.assertEqual(self.run_job(_job(project_id, "render")), ["run_render_job"])

    def test_project_78_v5_then_v6(self) -> None:
        older = {**FIXTURE_78["plan"], "primary_angle_id": "ang-1", "target_duration_seconds": 90,
                 "primary_angle": {**FIXTURE_78["plan"]["primary_angle"], "id": "ang-1", "statement": "Góc cũ"}}
        project_id = planned_project(db, kind="article", plan=FIXTURE_78["plan"], insight=FIXTURE_78["insight"],
                                     analysis=FIXTURE_78["analysis"], earlier_plans=[older] * 4, title=FIXTURE_78["video"]["title"])
        plan = db.get_latest_project_plan(project_id)
        self.assertEqual((plan["version"], plan["plan"]["primary_angle_id"], plan["plan"]["target_duration_seconds"],
                          [item["estimated_seconds"] for item in plan["plan"]["content_structure"]]), (5, "ang-2", 100, [10, 24, 27, 20, 19]))
        # A. Plan v5 + script v5: production goes ahead.
        write_current_script(db, project_id)
        _build(project_id)
        self.assertEqual(self.run_job(_job(project_id)), ["run_voiceover_job"])
        # B, G. A job queued and a Short made from v5.
        queued = _job(project_id, "render")
        short_v5 = _short(project_id)
        # C, D. The plan becomes v6 before the worker takes the job: refused.
        _bump_plan(project_id)
        self.assertEqual(self.run_job(queued), [])
        self.assertEqual(_status(queued), ("error", STALE))
        # E, F. Written again from v6: a new job goes ahead.
        write_current_script(db, project_id)
        self.assertEqual(db.get_latest_project_script(project_id)["plan_version"], 6)
        _build(project_id)
        self.assertEqual(self.run_job(_job(project_id, "render")), ["run_render_job"])
        # H. The v5 Short is held; I. a Short from v6 goes ahead.
        self.assertEqual(self.run_job(_job(project_id, "render_short", script_id=int(short_v5["id"]))), [])
        short_v6 = _short(project_id)
        self.assertEqual(self.run_job(_job(project_id, "render_short", script_id=int(short_v6["id"]))), ["run_short_render_job"])


if __name__ == "__main__":
    unittest.main()
