"""Bước 2 · Kế hoạch as a step: analyze → plan → script.

It goes through the same door as every other step - the requirement check,
the one-at-a-time guard, the running state a reloaded page reads - and saves
a ResearchReport and a ProjectPlan of its own, never the old research output.
"""

from __future__ import annotations

import inspect
import json
import threading
import unittest
import uuid
from unittest import mock

from fastapi import HTTPException

from youtube_monitor import main, project_planner, steps
from youtube_monitor.knowledge_store import ChannelIntelligence

UC = "UCabcdefghijklmnopqrstuv"


class _FakeYouTube:
    api_key = "test-key"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def get_videos(self, ids: list[str]) -> list[dict]:
        self.calls.append(list(ids))
        return [{
            "id": ids[0],
            "snippet": {"channelId": UC, "channelTitle": "Kênh Thật", "publishedAt": "2026-09-01T10:00:00Z"},
            "statistics": {"viewCount": "2000", "likeCount": "150", "commentCount": "40"},
        }]


_BRIEF = {
    "topic": "Trái Đất được tạo ra như thế nào",
    "content_summary": "Video giải thích sự hình thành Trái Đất.",
    "keywords": ["trái đất", {"keyword": "hệ mặt trời"}],
    "characters": [{"name": "Người dẫn", "role": "narrator"}],
    "limitations": ["Không rõ nguồn số liệu 4,5 tỉ năm"],
    "scene_map": [{"what_happens": "Mở đầu"}],
    "language": "vi",
    "source_type": "video",
}


class PlanStepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient

        cls._client_cm = TestClient(main.app)
        cls.client = cls._client_cm.__enter__()
        cls.database = main.database

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)

    def setUp(self) -> None:
        self.youtube = _FakeYouTube()
        for patcher in (
            mock.patch.object(main, "youtube", self.youtube),
            mock.patch.object(main, "probe_source_link", side_effect=AssertionError("yt-dlp not expected")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        # A YouTube video imported by link before identity was kept.
        self.video_id = f"web-{uuid.uuid4().hex[:16]}"
        self.database.upsert_channel({"youtube_channel_id": "WEB-YOUTUBE-740f513895b0", "channel_url": "https://x"})
        self.database.upsert_video({
            "youtube_video_id": self.video_id, "youtube_channel_id": "WEB-YOUTUBE-740f513895b0",
            "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "Trái Đất",
            "duration_seconds": 62, "metadata_hash": self.video_id,
            "raw_payload": {"source": "link_import", "platform": "Youtube", "native_id": "dQw4w9WgXcQ"},
        })
        self.database.set_video_source_identity(self.video_id, source_platform="youtube", native_video_id="dQw4w9WgXcQ")
        self.project_id = int(self.database.create_production_project(self.video_id, title="Trái Đất")["id"])

    def _analyze(self, brief: dict | None = None) -> None:
        self.database.save_video_analysis(self.video_id, brief or _BRIEF, analysis_type="reference", provider="test")

    def _run(self, **options) -> dict:
        # These tests hold the Phase 1 skeleton; the collectors have their own
        # tests with a complete fake YouTube (test_channel_research.py).
        options.setdefault("collect", False)
        return self.client.post(f"/api/projects/{self.project_id}/steps/plan", json={"options": options})

    def _row(self) -> dict:
        body = self.client.get(f"/api/projects/{self.project_id}/steps").json()
        return next(row for row in body["steps"] if row["key"] == "plan")

    def test_the_registry_puts_plan_between_analysis_and_script(self) -> None:
        keys = list(steps.STEP_KEYS)
        self.assertLess(keys.index("analyze"), keys.index("plan"))
        self.assertLess(keys.index("plan"), keys.index("script"))
        self.assertEqual(steps.get("plan").requires, ("analyze",))
        self.assertFalse(steps.get("plan").legacy)
        self.assertTrue(steps.get("research").legacy)
        self.assertIn("plan", main._SINGLE_RUN_STEPS)

    def test_planning_before_the_analysis_is_refused(self) -> None:
        response = self._run()
        self.assertEqual(response.status_code, 409)
        self.assertIn("Phân tích nguồn", response.json()["detail"])

    def test_a_plan_is_saved_with_its_research_report(self) -> None:
        self._analyze()
        response = self._run()
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        self.assertEqual(result["status"], "draft")
        self.assertEqual(result["source_kind"], "video")
        self.assertIn("similar_videos", result["pending_collectors"])
        self.assertEqual(result["identity"]["native_channel_id"], UC, "the old row learned its real channel")
        self.assertEqual(self.youtube.calls, [["dQw4w9WgXcQ"]])

        body = self.client.get(f"/api/projects/{self.project_id}/plan").json()
        plan, report = body["plan"], body["research_report"]
        self.assertEqual(plan["status"], "draft")
        self.assertFalse(plan["stale"])
        self.assertEqual(plan["research_report_id"], report["id"])
        self.assertEqual(plan["plan"]["platform"], "youtube")
        self.assertEqual(plan["plan"]["aspect_ratio"], "16:9")
        self.assertIsNone(plan["plan"]["primary_angle"], "nothing research must decide is guessed")
        self.assertIn("primary_angle", plan["plan"]["pending_fields"])
        self.assertEqual(plan["plan"]["constraints"]["must_not_invent"], ["Không rõ nguồn số liệu 4,5 tỉ năm"])
        self.assertEqual(plan["feasibility"]["status"], "not_checked")
        evidence = report["report"]["evidence"]
        self.assertEqual([item["source_kind"] for item in evidence], ["source"])
        self.assertEqual(evidence[0]["native_source_id"], "dQw4w9WgXcQ")
        self.assertEqual(evidence[0]["collector"], "planner.source")
        self.assertEqual(evidence[0]["metrics"]["view_count"], 2000)
        self.assertEqual(report["report"]["knowledge_used"]["channel"]["state"], "missing")
        # Research alone is not a finished Bước 2: the row stays runnable and says what it holds.
        row = self._row()
        self.assertEqual((row["state"], row["outcome"]["status"], row["outcome"]["completed"]), ("ready", "draft", False))
        self.assertNotIn("plan", main._steps_done(self.project_id))

    def test_a_reused_channel_profile_is_reported_as_fresh(self) -> None:
        self._analyze()
        ChannelIntelligence(self.database).save_full("youtube", UC, profile={"style": "nhanh"}, video_ids=["a"])
        result = self._run().json()["result"]
        self.assertEqual(result["knowledge"]["channel"]["state"], "fresh")

    def test_every_run_is_a_new_version(self) -> None:
        self._analyze()
        first = self._run().json()["result"]
        second = self._run().json()["result"]
        self.assertEqual((first["plan_version"], second["plan_version"]), (1, 2))
        self.assertEqual((first["research_report_version"], second["research_report_version"]), (1, 2))

    def test_a_new_analysis_makes_the_plan_stale(self) -> None:
        self._analyze()
        self._run()
        self._analyze({**_BRIEF, "topic": "Trái Đất (phân tích lại)"})
        plan = self.client.get(f"/api/projects/{self.project_id}/plan").json()["plan"]
        self.assertTrue(plan["stale"])
        self.assertEqual(plan["effective_status"], "stale")
        self.assertNotIn("plan", main._steps_done(self.project_id))

    def test_a_product_without_a_price_forbids_price_claims(self) -> None:
        self._analyze({**_BRIEF, "source_type": "product", "source_facts": {"name": "Tai nghe", "price": "", "captured_at": None}})
        result = self._run(refresh_identity=False).json()["result"]
        plan = self.client.get(f"/api/projects/{self.project_id}/plan").json()
        self.assertEqual(result["source_kind"], "product")
        self.assertTrue(plan["plan"]["plan"]["constraints"]["no_price_claims"])
        self.assertEqual(plan["research_report"]["report"]["evidence"][0]["source_kind"], "product_page")
        self.assertEqual(result["knowledge"]["product_price"], "missing")
        self.assertEqual(self.youtube.calls, [], "refresh_identity=False asks nobody")

    def test_the_old_research_output_does_not_reach_the_plan(self) -> None:
        self._analyze()
        self.database.save_director_artifact(self.project_id, "research", {"findings": ["LEGACY_MARKER_ARTIFACT"]})
        task = self.database.create_agent_task(self.project_id, "research", "pipeline.research", {"goal": "x"})
        self.database.finish_agent_task(str(task["id"]), "completed", output={"summary": "LEGACY_MARKER_AGENT"})
        self._run()
        body = json.dumps(self.client.get(f"/api/projects/{self.project_id}/plan").json(), ensure_ascii=False)
        self.assertNotIn("LEGACY_MARKER", body)
        from youtube_monitor import channel_research, research_collectors

        # The web search transport is fine to use; what must not be read is
        # the old research OUTPUT: its artifact, the agent task, folklore.
        for module in (project_planner, research_collectors, channel_research):
            code = inspect.getsource(module).split('"""', 2)[2]  # after the module docstring
            for legacy in ("director_artifact", "agent_task", "folklore", "_step_research"):
                self.assertNotIn(legacy, code, f"{module.__name__}: {legacy}")


class PlanRunsOneAtATimeTests(unittest.TestCase):
    """The same guard the analysis has: one run per project, visible while it runs."""

    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient

        cls._client_cm = TestClient(main.app)
        cls.client = cls._client_cm.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)

    def test_a_second_plan_is_refused_while_one_runs(self) -> None:
        database = main.database
        project = database.create_idea_project("Thu nghiem ke hoach dang chay", title="Plan runs")
        project_id = int(project["id"])
        database.save_video_analysis(project["youtube_video_id"], _BRIEF, analysis_type="reference", provider="test")
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def blocking(*args, **kwargs):
            entered.set()
            release.wait(10)
            return {"status": "draft"}

        patcher = mock.patch.object(project_planner, "run", side_effect=blocking)
        patcher.start()
        self.addCleanup(patcher.stop)
        errors: list[BaseException] = []
        thread = threading.Thread(
            target=lambda: _capture(errors, main.run_project_step, project_id, "plan", {"refresh_identity": False}),
            daemon=True,
        )
        thread.start()
        self.assertTrue(entered.wait(5))

        row = next(item for item in self.client.get(f"/api/projects/{project_id}/steps").json()["steps"] if item["key"] == "plan")
        self.assertEqual(row["state"], "running")
        self.assertTrue(row["run"]["run_id"])
        second = self.client.post(f"/api/projects/{project_id}/steps/plan", json={"options": {"refresh_identity": False}})
        self.assertEqual(second.status_code, 409)
        self.assertIn("đang chạy", second.json()["detail"])

        release.set()
        thread.join(5)
        self.assertEqual(errors, [])
        row = next(item for item in self.client.get(f"/api/projects/{project_id}/steps").json()["steps"] if item["key"] == "plan")
        self.assertEqual(row["last_run"]["status"], "success")


def _capture(errors: list, function, *args) -> None:
    try:
        function(*args)
    except HTTPException as exc:
        errors.append(exc)


if __name__ == "__main__":
    unittest.main()
