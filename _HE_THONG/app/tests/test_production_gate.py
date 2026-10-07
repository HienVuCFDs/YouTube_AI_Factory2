"""Bước 3 · Phase 2.1: one production gate in front of everything after the script.

    PLAN READY → SCRIPT FRESH → VOICE → STORYBOARD / TIMELINE → RENDER → PUBLISH

A planned project goes past Bước 3 only on the script written from its
current, completed plan. The same gate stands in front of every door - the
direct REST routes (voice and render jobs and their retries, translation,
publishing and its retry, the Short, the storyboard and timeline), run_step,
MCP, the AI orchestrator and the automation - in the same words, before any
model is asked or any job, file or row is made. `force` never opens it.
A project outside the plan workflow keeps the path it always had.
"""

from __future__ import annotations

import unittest
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from tests.script_fixtures import FIXTURE_78, PLAN, Scripted, planned_project
from tests.test_script_paths import _legacy_project, _snapshot
from youtube_monitor import ai_desktop_mcp, main, script_engine, storyboard_engine

GO = script_engine.CONTINUE_MESSAGES
STALE = script_engine.STALE_SCRIPT_MESSAGE
QUEUED = {"id": 990001, "status": "queued"}


def _boom(*args, **kwargs):
    raise AssertionError("must not be called")


class _Case(unittest.TestCase):
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
        for target, value in ((main, "_call_orchestrator_json"), (main.production_worker, "enqueue")):
            patcher = mock.patch.object(target, value, self.model if value == "_call_orchestrator_json"
                                        else mock.Mock(return_value=QUEUED))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.enqueue = main.production_worker.enqueue

    # --- making a project in a given state ------------------------------------------

    def _write(self, project_id: int) -> None:
        response = self.client.post(f"/api/projects/{project_id}/script/generate", json={"options": {}})
        self.assertEqual(response.status_code, 200, response.text)

    def _build(self, project_id: int) -> None:
        self.assertEqual(self.client.post(f"/api/projects/{project_id}/shots/generate", json={"force": True}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/projects/{project_id}/timeline/generate", json={"force": True}).status_code, 200)

    def _ready(self, **setup) -> int:
        """Plan completed, script written from it, storyboard and timeline cut: ready for voice."""
        project_id = planned_project(self.database, **setup)
        self._write(project_id)
        self._build(project_id)
        return project_id

    def _bump_plan(self, project_id: int, plan: dict | None = None) -> dict:
        """The plan moves on (a new version), as Bước 2 would save it."""
        latest = self.database.get_latest_project_plan(project_id)
        return self.database.create_project_plan(
            project_id, status="completed", research_report_id=latest["research_report_id"],
            analysis_created_at=latest["analysis_created_at"], engine_version="plan-phase3", plan=plan or latest["plan"],
            feasibility={"status": "ok", "checks": []}, insight_report_id=latest["insight_report_id"])

    def _invalidate(self, project_id: int) -> None:
        script = self.database.get_latest_project_script(project_id)
        response = self.client.patch(f"/api/scripts/{script['id']}", json={
            "main_content": script["main_content"] + "\nMọi khán giả đều thích video ngắn về vũ trụ hơn video dài."})
        self.assertEqual(response.json()["state"], "invalid")

    def _mismatch(self, project_id: int) -> None:
        plan = self.database.get_latest_project_plan(project_id)
        self.database.create_project_script(project_id, script_title="x", main_content="Một câu.", plan_id=plan["id"],
                                            plan_version=99, document={"sections": [], "validation": {"ok": True}},
                                            engine_version=script_engine.ENGINE_VERSION)

    def _failed_job(self, project_id: int) -> int:
        """A voice job that failed - what /jobs/{id}/retry takes. Never queued, so no worker picks it up."""
        script = self.database.get_latest_project_script(project_id)
        with self.database._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO project_jobs (project_id, script_id, job_type, provider, status, created_at, updated_at) "
                "VALUES (?, ?, 'voiceover', 'dry_run', 'error', datetime('now'), datetime('now'))",
                (project_id, int(script["id"])))
            return int(cursor.lastrowid)

    def _failed_publication(self, project_id: int) -> int:
        publication = self.database.create_project_publication(project_id, "C:/x/final.mp4", "Video", status="ready_manual")
        self.database.finish_project_publication(int(publication["id"]), "error")
        return int(publication["id"])

    def _over_mcp(self):
        """MCP tools post to the app over HTTP; here they reach the same app through the test client."""
        def request(path, method="GET", data=None, headers=None, timeout=None):
            response = self.client.request(method, path, content=data, headers=headers or {})
            if response.status_code >= 400:
                raise RuntimeError(str(response.json().get("detail")))
            return response.json()
        return mock.patch.object(ai_desktop_mcp, "_factory_request", side_effect=request)

    # --- the doors --------------------------------------------------------------------

    def _doors(self, project_id: int, *, job_id: int | None = None, publication_id: int | None = None) -> dict:
        """Every direct way past Bước 3, each with `force` where it takes one."""
        post = self.client.post
        doors = {
            "jobs voice": post(f"/api/projects/{project_id}/jobs", json={"job_type": "voiceover", "provider": "dry_run"}),
            "jobs voice force": post(f"/api/projects/{project_id}/jobs", json={
                "job_type": "voiceover", "provider": "edge_tts", "confirmed": True, "force": True}),
            "jobs render force": post(f"/api/projects/{project_id}/jobs", json={
                "job_type": "render", "provider": "ffmpeg_builtin", "confirmed": True, "force": True}),
            "jobs short voice": post(f"/api/projects/{project_id}/jobs", json={
                "job_type": "voiceover", "provider": "dry_run", "variant": "short"}),
            "translate": post(f"/api/projects/{project_id}/script/translate?target_language=en&force=true"),
            "publish": post(f"/api/projects/{project_id}/publish", json={"confirmed": True, "override_checklist": True}),
            "short-script": post(f"/api/projects/{project_id}/short-script", json={"seconds": 30, "use_model": True}),
            "short/plan": post(f"/api/projects/{project_id}/short/plan", json={"use_model": True}),
            "shots/generate force": post(f"/api/projects/{project_id}/shots/generate", json={"force": True}),
            "timeline/generate force": post(f"/api/projects/{project_id}/timeline/generate", json={"force": True}),
            "timeline/from-dialogue force": post(f"/api/projects/{project_id}/timeline/from-dialogue?force=true&replace_existing=true"),
            "orchestrate": post(f"/api/projects/{project_id}/orchestrate", json={"intent": "Làm hình cho các cảnh", "dry_run": False}),
            "run_step voice force": post(f"/api/projects/{project_id}/steps/voice", json={"options": {"force": True}}),
            "run_step render force": post(f"/api/projects/{project_id}/steps/render", json={"options": {"force": True, "confirmed": True}}),
            "run_step publish force": post(f"/api/projects/{project_id}/steps/publish", json={"options": {
                "force": True, "confirmed_publish": True}}),
            "run_step shots force": post(f"/api/projects/{project_id}/steps/shots", json={"options": {"force": True}}),
            "run_step timeline force": post(f"/api/projects/{project_id}/steps/timeline", json={"options": {"force": True}}),
        }
        if job_id:
            doors["jobs retry"] = post(f"/api/jobs/{job_id}/retry")
        if publication_id:
            doors["publication retry"] = post(f"/api/publications/{publication_id}/retry")
        return doors

    def _all_blocked(self, project_id: int, message: str, **ids) -> None:
        before = self._artifacts(project_id)
        for name, response in self._doors(project_id, **ids).items():
            self.assertEqual(response.status_code, 409, (name, response.text))
            self.assertEqual(response.json()["detail"], message, name)
        self.assertEqual(self.model.calls, [], "the gate comes before any model")
        self.enqueue.assert_not_called()
        self.assertEqual(self._artifacts(project_id), before, "and before any job, scene, segment, Short or publication")

    def _artifacts(self, project_id: int) -> dict:
        jobs = [(job["id"], job["status"]) for job in self.database.list_project_jobs(project_id, limit=500)]
        publications = [(item["id"], item["status"]) for item in self.database.list_project_publications(project_id=project_id)]
        return {**_snapshot(self.database, project_id), "jobs": jobs, "publications": publications,
                "short": self.database.get_project_short(project_id)}


# ===========================================================================
# A. Voice and render jobs (/jobs and its retry)
# ===========================================================================

class VoiceRenderTests(_Case):
    def test_1_a_fresh_script_queues_voice_and_render(self) -> None:
        project_id = self._ready()
        script = self.database.get_latest_project_script(project_id)
        voice = self.client.post(f"/api/projects/{project_id}/jobs", json={"job_type": "voiceover", "provider": "dry_run"})
        self.assertEqual(voice.status_code, 200, voice.text)
        render = self.client.post(f"/api/projects/{project_id}/jobs", json={"job_type": "render", "provider": "dry_run"})
        self.assertEqual(render.status_code, 200, render.text)
        self.assertEqual([call.args[:4] for call in self.enqueue.call_args_list],
                         [(project_id, int(script["id"]), "voiceover", "dry_run"), (project_id, int(script["id"]), "render", "dry_run")])
        job_id = self._failed_job(project_id)
        self.assertEqual(self.client.post(f"/api/jobs/{job_id}/retry").status_code, 200)

    def _blocked(self, project_id: int, message: str) -> None:
        job_id = self._failed_job(project_id) if self.database.get_latest_project_script(project_id) else None
        jobs_before = self.database.list_project_jobs(project_id, limit=500)
        for body in ({"job_type": "voiceover", "provider": "dry_run"},
                     {"job_type": "voiceover", "provider": "edge_tts", "confirmed": True, "force": True},
                     {"job_type": "render", "provider": "ffmpeg_builtin", "confirmed": True, "force": True},
                     {"job_type": "voiceover_segment", "provider": "dry_run", "segment_id": 1, "force": True}):
            response = self.client.post(f"/api/projects/{project_id}/jobs", json=body)
            self.assertEqual((response.status_code, response.json()["detail"]), (409, message), body)
        if job_id:
            retried = self.client.post(f"/api/jobs/{job_id}/retry")
            self.assertEqual((retried.status_code, retried.json()["detail"]), (409, message))
        self.enqueue.assert_not_called()
        self.assertEqual(self.database.list_project_jobs(project_id, limit=500), jobs_before)

    def test_2_a_plan_without_a_script_is_blocked(self) -> None:
        self._blocked(planned_project(self.database), GO["missing"])

    def test_3_a_stale_script_is_blocked(self) -> None:
        project_id = self._ready()
        self._bump_plan(project_id)
        self._blocked(project_id, STALE)

    def test_4_an_invalid_script_is_blocked(self) -> None:
        project_id = self._ready()
        self._invalidate(project_id)
        self._blocked(project_id, GO["invalid"])

    def test_5_a_plan_version_mismatch_is_blocked(self) -> None:
        project_id = self._ready()
        self._mismatch(project_id)
        self._blocked(project_id, GO["mismatch"])

    def test_6_and_7_force_does_not_open_it_and_nothing_is_queued_first(self) -> None:
        project_id = self._ready()
        self._bump_plan(project_id)
        with mock.patch.object(main.database, "create_project_job", _boom):
            response = self.client.post(f"/api/projects/{project_id}/jobs", json={
                "job_type": "render", "provider": "ffmpeg_builtin", "confirmed": True, "force": True})
        self.assertEqual(response.status_code, 409)
        self.enqueue.assert_not_called()

    def test_a_script_being_written_holds_every_job(self) -> None:
        project_id = self._ready()
        self.assertIsNotNone(main._step_registry.claim((project_id, "script")))
        try:
            self._blocked(project_id, GO["running"])
        finally:
            main._step_registry.finish((project_id, "script"), {"status": "success"})


# ===========================================================================
# B. Translate
# ===========================================================================

class TranslateTests(_Case):
    def test_8_a_fresh_script_past_the_gate_is_not_translated_scene_by_scene(self) -> None:
        # Bước 5.2: the narration of a planned project is its script's, word for word,
        # so per-scene translation - which rewrote it outside the script - is refused.
        project_id = self._ready()
        script = self.database.get_latest_project_script(project_id)
        before = [item["voice_text"] for item in self.database.list_project_timeline(project_id, script_id=int(script["id"]))]
        with mock.patch.object(main, "_call_orchestrator_json", _boom):
            response = self.client.post(f"/api/projects/{project_id}/script/translate?target_language=en")
        self.assertEqual((response.status_code, response.json()["detail"]), (409, storyboard_engine.TRANSLATE_LOCKED))
        texts = [item["voice_text"] for item in self.database.list_project_timeline(project_id, script_id=int(script["id"]))]
        self.assertEqual(texts, before)

    def test_9_and_10_a_stale_script_is_not_translated_force_or_not(self) -> None:
        project_id = self._ready()
        self._bump_plan(project_id)
        before = _snapshot(self.database, project_id)
        with mock.patch.object(main, "_call_orchestrator_json", _boom):
            for query in ("", "&force=true"):
                response = self.client.post(f"/api/projects/{project_id}/script/translate?target_language=en{query}")
                self.assertEqual((response.status_code, response.json()["detail"]), (409, STALE))
        self.assertEqual(_snapshot(self.database, project_id), before)


# ===========================================================================
# C. Publish
# ===========================================================================

class PublishTests(_Case):
    def test_11_a_fresh_script_reaches_publishing_as_before(self) -> None:
        project_id = self._ready()
        # The direct route goes on to its own checks (here: nothing rendered, not approved) - not the gate.
        response = self.client.post(f"/api/projects/{project_id}/publish", json={"confirmed": True})
        self.assertNotEqual(response.status_code, 409, response.text)
        self.assertNotIn(response.json().get("detail"), list(GO.values()))
        with mock.patch.object(main, "project_publish_checklist", return_value={"ok": True}), \
                mock.patch.object(main, "queue_project_publication", return_value={"id": 5}) as publish:
            result = main.run_project_step(project_id, "publish", {"force": True, "confirmed_publish": True})["result"]
        publish.assert_called_once()
        self.assertTrue(result["published"])

    def test_12_and_13_a_stale_script_is_not_published_force_or_not(self) -> None:
        project_id = self._ready()
        publication_id = self._failed_publication(project_id)
        self._bump_plan(project_id)
        before = [(item["id"], item["status"]) for item in self.database.list_project_publications(project_id=project_id)]
        for body in ({"confirmed": True}, {"confirmed": True, "override_checklist": True}):
            response = self.client.post(f"/api/projects/{project_id}/publish", json=body)
            self.assertEqual((response.status_code, response.json()["detail"]), (409, STALE), body)
        retried = self.client.post(f"/api/publications/{publication_id}/retry")
        self.assertEqual((retried.status_code, retried.json()["detail"]), (409, STALE))
        with mock.patch.object(main, "project_publish_checklist", return_value={"ok": True}), \
                mock.patch.object(main, "queue_project_publication") as publish, self.assertRaises(HTTPException) as refused:
            main.run_project_step(project_id, "publish", {"force": True, "confirmed_publish": True})
        publish.assert_not_called()
        self.assertEqual((refused.exception.status_code, refused.exception.detail), (409, STALE))
        self.assertEqual([(item["id"], item["status"]) for item in self.database.list_project_publications(project_id=project_id)], before)


# ===========================================================================
# D. The Short
# ===========================================================================

class ShortTests(_Case):
    def test_14_a_fresh_script_writes_the_short(self) -> None:
        project_id = self._ready()
        long_script = self.database.get_latest_project_script(project_id)
        response = self.client.post(f"/api/projects/{project_id}/short-script", json={"seconds": 30, "use_model": False})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["script"]["variant"], "short")
        words = set(long_script["main_content"].split()) | set(long_script["hook"].split()) | set(long_script["cta"].split())
        self.assertTrue(set(response.json()["script"]["main_content"].split()) <= words, "written from the current long script")
        # The re-cut Short gets past the gate to its own check (no scene has picture and voice yet).
        cut = self.client.post(f"/api/projects/{project_id}/short/plan", json={"use_model": False})
        self.assertEqual(cut.status_code, 400, cut.text)
        self.assertNotIn(cut.json()["detail"], list(GO.values()))

    def _short_blocked(self, project_id: int, message: str) -> None:
        shorts = self.database.list_project_scripts(project_id, variant="short")
        for path, body in (("short-script", {"seconds": 30, "use_model": True}), ("short/plan", {"use_model": True})):
            response = self.client.post(f"/api/projects/{project_id}/{path}", json=body)
            self.assertEqual((response.status_code, response.json()["detail"]), (409, message), path)
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self.database.list_project_scripts(project_id, variant="short"), shorts)
        self.assertIsNone(self.database.get_project_short(project_id))

    def test_15_a_stale_script_writes_no_short(self) -> None:
        project_id = self._ready()
        self._bump_plan(project_id)
        self.model.calls.clear()
        self._short_blocked(project_id, STALE)

    def test_16_an_invalid_script_writes_no_short(self) -> None:
        project_id = self._ready()
        self._invalidate(project_id)
        self.model.calls.clear()
        self._short_blocked(project_id, GO["invalid"])

    def test_17_a_short_outside_the_plan_workflow_works_as_before(self) -> None:
        project = self.database.create_idea_project("Chỉ làm Short", title="Short riêng")
        project_id = int(project["id"])
        self.database.create_project_script(project_id, script_title="Bản dài", hook="Mở đầu thật nhanh.",
                                            main_content="Anh dựng nhà giữa rừng. " * 30, cta="Theo dõi nhé.")
        response = self.client.post(f"/api/projects/{project_id}/short-script", json={"seconds": 30, "use_model": False})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["script"]["variant"], "short")
        self.assertIsNone(self.database.get_latest_project_plan(project_id))

    def test_18_and_19_the_short_touches_neither_the_plan_nor_the_long_script(self) -> None:
        project_id = self._ready()
        plan = self.database.get_latest_project_plan(project_id)
        long_ids = [item["id"] for item in self.database.list_project_scripts(project_id)]
        current = self.client.get(f"/api/projects/{project_id}/script").json()
        self.client.post(f"/api/projects/{project_id}/short-script", json={"seconds": 30, "use_model": False})
        after = self.database.get_latest_project_plan(project_id)
        self.assertEqual((after["id"], after["version"], after["plan"]), (plan["id"], plan["version"], plan["plan"]))
        self.assertEqual([item["id"] for item in self.database.list_project_scripts(project_id)], long_ids)
        again = self.client.get(f"/api/projects/{project_id}/script").json()
        self.assertEqual((again["id"], again["state"]), (current["id"], "completed"))
        for short in self.database.list_project_scripts(project_id, variant="short"):
            # It records what it was made from (Phase 2.2), and is still not a ScriptDocument.
            self.assertEqual((script_engine.decode(short), script_engine.short_provenance(short)["source_script_id"]),
                             (None, current["id"]))


# ===========================================================================
# E. Storyboard and timeline: the Phase 2 gate, unchanged
# ===========================================================================

class StoryboardTests(_Case):
    def test_20_to_26_the_storyboard_gate(self) -> None:
        # 20. Fresh: through.
        project_id = self._ready()
        self.assertEqual(self.client.post(f"/api/projects/{project_id}/shots/generate", json={}).status_code, 200)
        cases = {
            "21 stale": (self._ready(), lambda pid: self._bump_plan(pid), STALE),
            "22 missing plan": (planned_project(self.database, with_plan=False), lambda pid: self.database.create_project_script(
                pid, script_title="x", main_content="Một câu."), GO["no_plan"]),
            "23 mismatch": (self._ready(), self._mismatch, GO["mismatch"]),
        }
        for name, (pid, make, message) in cases.items():
            make(pid)
            before = _snapshot(self.database, pid)
            direct = {
                "shots/generate": self.client.post(f"/api/projects/{pid}/shots/generate", json={}),
                # 24. force does not open it.
                "shots/generate force": self.client.post(f"/api/projects/{pid}/shots/generate", json={"force": True}),
                "timeline/generate force": self.client.post(f"/api/projects/{pid}/timeline/generate", json={"force": True}),
                # 25. run_step, with and without a scene list of its own.
                "run_step shots": self.client.post(f"/api/projects/{pid}/steps/shots", json={"options": {"force": True}}),
                "run_step shots supplied": self.client.post(f"/api/projects/{pid}/steps/shots", json={"options": {"force": True, "shots": [
                    {"shot_index": 1, "section": "main", "narration": "x", "visual_prompt": "x", "asset_type": "ai_scene",
                     "duration_seconds": 4}]}}),
                "run_step timeline": self.client.post(f"/api/projects/{pid}/steps/timeline", json={"options": {"force": True}}),
            }
            for door, response in direct.items():
                self.assertEqual((response.status_code, response.json()["detail"]), (409, message), (name, door))
            # 26. MCP and the agents reach the same gate.
            for tool, arguments in (("youtube_factory_run_step", {"project_id": pid, "step": "shots", "options": {"force": True}}),
                                    ("youtube_factory_build_timeline", {"project_id": pid, "force": True})):
                with self._over_mcp(), self.assertRaises(RuntimeError) as refused:
                    ai_desktop_mcp._call_tool(tool, arguments)
                self.assertEqual(str(refused.exception), message, (name, tool))
            self.assertEqual(_snapshot(self.database, pid), before, name)


# ===========================================================================
# F. Project 57
# ===========================================================================

class Project57Tests(_Case):
    def test_27_to_31_the_old_project_is_kept_and_continues_nothing(self) -> None:
        project_id = _legacy_project(self.database)
        job_id = self._failed_job(project_id)
        publication_id = self._failed_publication(project_id)
        scripts_before = [dict(item) for item in self.database.list_project_scripts(project_id, variant=None)]
        # 28. Still stale, with its reasons.
        body = self.client.get(f"/api/projects/{project_id}/script").json()
        self.assertEqual((body["state"], body["document"]), ("stale", None))
        # 29-31. No door continues it, no model is asked, nothing is made or changed.
        self._all_blocked(project_id, GO["needs_user_decision"], job_id=job_id, publication_id=publication_id)
        # 27. The old scripts are all still there.
        self.assertEqual([dict(item) for item in self.database.list_project_scripts(project_id, variant=None)], scripts_before)
        # Once the decision is made the old script is what it is: stale - still nothing continues on it.
        self._bump_plan(project_id, PLAN)
        self._all_blocked(project_id, STALE, job_id=job_id, publication_id=publication_id)


# ===========================================================================
# G. Project 78
# ===========================================================================

class Project78Tests(_Case):
    def test_32_to_37_project_78_from_plan_v5_through_a_plan_change_and_back(self) -> None:
        older = {**FIXTURE_78["plan"], "primary_angle_id": "ang-1", "target_duration_seconds": 90,
                 "primary_angle": {**FIXTURE_78["plan"]["primary_angle"], "id": "ang-1", "statement": "Góc cũ"}}
        project_id = planned_project(self.database, kind="article", plan=FIXTURE_78["plan"], insight=FIXTURE_78["insight"],
                                     analysis=FIXTURE_78["analysis"], earlier_plans=[older] * 4, title=FIXTURE_78["video"]["title"])
        # 32. Plan v5: ang-2, 100 s, five sections.
        plan = self.database.get_latest_project_plan(project_id)
        self.assertEqual((plan["version"], plan["plan"]["primary_angle_id"], plan["plan"]["target_duration_seconds"],
                          [item["estimated_seconds"] for item in plan["plan"]["content_structure"]]),
                         (5, "ang-2", 100, [10, 24, 27, 20, 19]))
        # 33. Fresh script: storyboard, timeline and voice go ahead.
        self._write(project_id)
        self._build(project_id)
        self.assertEqual(self.client.post(f"/api/projects/{project_id}/jobs", json={"job_type": "voiceover", "provider": "dry_run"}).status_code, 200)
        self.enqueue.reset_mock()
        self.model.calls.clear()
        # 34. The plan moves to v6: the script is stale.
        self._bump_plan(project_id)
        body = self.client.get(f"/api/projects/{project_id}/script").json()
        self.assertEqual((body["state"], body["plan_version"], body["current_plan"]["version"]), ("stale", 5, 6))
        # 35, 36. Every door is shut, force or not.
        self._all_blocked(project_id, STALE, job_id=self._failed_job(project_id), publication_id=self._failed_publication(project_id))
        # 37. Written again from v6: fresh, and the doors open again.
        self._write(project_id)
        self.assertEqual(self.client.get(f"/api/projects/{project_id}/script").json()["plan_version"], 6)
        self._build(project_id)
        self.assertEqual(self.client.post(f"/api/projects/{project_id}/jobs", json={"job_type": "voiceover", "provider": "dry_run"}).status_code, 200)
        self.enqueue.assert_called_once()


# ===========================================================================
# H. MCP, the AI orchestrator, the automation - and the same words everywhere
# ===========================================================================

class OrchestrationTests(_Case):
    def test_38_mcp_voice_and_render_tools_meet_the_gate(self) -> None:
        project_id = self._ready()
        self._bump_plan(project_id)
        for tool, arguments in (("youtube_factory_run_step", {"project_id": project_id, "step": "voice", "options": {"force": True}}),
                                ("youtube_factory_generate_voice", {"project_id": project_id, "confirmed": True, "force": True}),
                                ("youtube_factory_render_video", {"project_id": project_id, "confirmed": True, "force": True})):
            with self._over_mcp(), self.assertRaises(RuntimeError) as refused:
                ai_desktop_mcp._call_tool(tool, arguments)
            self.assertEqual(str(refused.exception), STALE, tool)
        self.enqueue.assert_not_called()

    def test_39_the_ai_orchestrator_meets_the_gate_before_its_model(self) -> None:
        project_id = self._ready()
        self._bump_plan(project_id)
        self.model.calls.clear()
        for dry_run in (True, False):
            response = self.client.post(f"/api/projects/{project_id}/orchestrate", json={"intent": "Tạo hình cho các cảnh", "dry_run": dry_run})
            self.assertEqual((response.status_code, response.json()["detail"]), (409, STALE))
        self.assertEqual(self.model.calls, [])

    def test_40_the_automation_meets_the_gate(self) -> None:
        project_id = self._ready()
        self._bump_plan(project_id)
        with mock.patch.object(main, "_call_specific_agent_json", _boom), self.assertRaises(HTTPException) as refused:
            main._execute_agent_task({"role": "media", "project_id": project_id, "input": {"goal": "x"}}, "codex_cli")
        self.assertEqual((refused.exception.status_code, refused.exception.detail), (409, STALE))
        # The automatic render after QC is not queued either; the refusal is on the record.
        main._agent_pipeline_completed({"role": "qc", "project_id": project_id, "input": {},
                                        "output": {"ready_for_render": True, "pipeline": {"auto_render": True}}})
        self.enqueue.assert_not_called()
        refused_rows = [row for row in self.database.list_orchestrator_steps(project_id) if row["why"] == "auto_render"]
        self.assertEqual([(row["status"], row["error"]) for row in refused_rows], [("refused", STALE)])

    def test_41_direct_routes_and_run_step_say_the_same_thing(self) -> None:
        states = {
            "no plan": (planned_project(self.database, with_plan=False), lambda pid: self.database.create_project_script(
                pid, script_title="x", main_content="x")),
            "needs decision": (planned_project(self.database, status="needs_user_decision"), lambda pid: None),
            "blocked": (planned_project(self.database, status="blocked"), lambda pid: None),
            "missing": (planned_project(self.database), lambda pid: None),
            "stale": (self._ready(), lambda pid: self._bump_plan(pid)),
            "invalid": (self._ready(), self._invalidate),
            "mismatch": (self._ready(), self._mismatch),
        }
        for name, (project_id, make) in states.items():
            make(project_id)
            direct = {
                "voice": self.client.post(f"/api/projects/{project_id}/jobs", json={"job_type": "voiceover", "provider": "dry_run", "force": True}),
                "render": self.client.post(f"/api/projects/{project_id}/jobs", json={"job_type": "render", "provider": "dry_run", "force": True}),
                "shots": self.client.post(f"/api/projects/{project_id}/shots/generate", json={"force": True}),
                "publish": self.client.post(f"/api/projects/{project_id}/publish", json={"confirmed": True}),
            }
            stepped = {key: self.client.post(f"/api/projects/{project_id}/steps/{key}", json={"options": {"force": True, "confirmed": True}})
                       for key in ("voice", "render", "shots", "publish")}
            details = {response.json()["detail"] for response in [*direct.values(), *stepped.values()]}
            self.assertEqual(len(details), 1, (name, details))
            self.assertIn(details.pop(), set(GO.values()), name)
            self.assertTrue(all(response.status_code == 409 for response in [*direct.values(), *stepped.values()]), name)
        self.enqueue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
