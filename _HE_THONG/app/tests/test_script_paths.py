"""Bước 3 · Phase 2: one way to a script, and nothing built on the wrong one.

    ProjectPlan → Script Engine → ScriptDocument → Script Freshness Gate → Storyboard

Every way a long script of a planned project is made - a button, the old
/script/draft endpoint, MCP, the AI orchestrator, the five-role automation,
an AI rewrite in chat, pasted words - goes through run_step("script"). Every
way a storyboard is cut passes the gate: the plan completed, the script
written from it (same id and version) by the engine or as a checked draft,
not stale, not left invalid by an edit. The old writer's words and scene
list are never read for it. Older projects (the shape of project 57) keep
everything they have, and none of it opens the gate.
"""

from __future__ import annotations

import json
from functools import partial
from unittest import mock

import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient

from tests.script_fixtures import (
    ANGLE, FIXTURE_78, PLAN, STRUCTURE_78, Scripted, planned_project, said, script_answer,
)
from youtube_monitor import ai_desktop_mcp, main, script_engine
from youtube_monitor.shot_planner import build_shot_plan
from youtube_monitor.timeline_builder import build_timeline

NO_PLAN = "Bạn cần hoàn thành Kế hoạch trước khi viết kịch bản."
NEEDS_DECISION = "Kế hoạch hiện cần bạn quyết định trước khi viết kịch bản."
BLOCKED = "Kế hoạch hiện chưa thể thực hiện, chưa thể viết kịch bản."
STALE = script_engine.STALE_SCRIPT_MESSAGE
# What every way past Bước 3 answers (the production gate), as opposed to the script step's own words above.
GO = script_engine.CONTINUE_MESSAGES
WRITER_PROMPT = "WRITER_VISUAL_PROMPT_cinematic dolly zoom"


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
        patcher = mock.patch.object(main, "_call_orchestrator_json", self.model)
        patcher.start()
        self.addCleanup(patcher.stop)

    # --- reading -----------------------------------------------------------------

    def _script(self, project_id: int) -> dict:
        return self.client.get(f"/api/projects/{project_id}/script").json()

    def _row(self, project_id: int, key: str = "script") -> dict:
        return next(row for row in self.client.get(f"/api/projects/{project_id}/steps").json()["steps"] if row["key"] == key)

    def _long(self, project_id: int) -> list[dict]:
        return self.database.list_project_scripts(project_id)

    def _video(self, project_id: int) -> str:
        return self.database.get_production_project(project_id)["youtube_video_id"]

    # --- making -------------------------------------------------------------------

    def _written(self, **setup) -> tuple[int, dict]:
        """A planned project with its script written by the engine, as the step does it."""
        project_id = planned_project(self.database, **setup)
        response = self.client.post(f"/api/projects/{project_id}/script/generate", json={"options": {}})
        self.assertEqual(response.status_code, 200, response.text)
        return project_id, self._script(project_id)

    def _new_plan(self, project_id: int, **changes) -> dict:
        plan = self.database.get_latest_project_plan(project_id)
        body = {**PLAN, **changes}
        return self.database.create_project_plan(
            project_id, status="completed", research_report_id=plan["research_report_id"],
            analysis_created_at=plan["analysis_created_at"], engine_version="plan-phase3", plan=body,
            feasibility={"status": "ok", "checks": []}, insight_report_id=plan["insight_report_id"])

    def _shots(self, project_id: int, **body):
        return self.client.post(f"/api/projects/{project_id}/shots/generate", json=body)

    def _every_way_to_build_on_it(self, project_id: int) -> dict:
        """Each way a storyboard (or what follows it) could be made from the project's script."""
        segment = {"segment_index": 1, "start_seconds": 0, "duration_seconds": 4, "voice_text": "x", "subtitle_text": "x",
                   "visual_prompt": "x", "asset_type": "ai_scene"}
        shot = {"shot_index": 1, "section": "main", "narration": "x", "visual_prompt": "x", "asset_type": "ai_scene",
                "duration_seconds": 4}
        post = self.client.post
        return {
            "shots/generate": post(f"/api/projects/{project_id}/shots/generate", json={"force": False}),
            "shots/generate force": post(f"/api/projects/{project_id}/shots/generate", json={"force": True}),
            "run_step shots": post(f"/api/projects/{project_id}/steps/shots", json={"options": {"force": True}}),
            "run_step shots supplied": post(f"/api/projects/{project_id}/steps/shots",
                                            json={"options": {"shots": [shot], "force": True}}),
            "run_step timeline supplied": post(f"/api/projects/{project_id}/steps/timeline",
                                               json={"options": {"segments": [segment], "force": True}}),
            "timeline/generate": post(f"/api/projects/{project_id}/timeline/generate", json={"force": True}),
            "timeline/from-dialogue": post(f"/api/projects/{project_id}/timeline/from-dialogue?force=true&replace_existing=true"),
            "run_step voice": post(f"/api/projects/{project_id}/steps/voice", json={"options": {"force": True}}),
            "run_step render": post(f"/api/projects/{project_id}/steps/render", json={"options": {"force": True}}),
        }

    def _all_refused(self, project_id: int, said_: str) -> None:
        for name, response in self._every_way_to_build_on_it(project_id).items():
            self.assertEqual(response.status_code, 409, (name, response.text))
            self.assertIn(said_, response.json()["detail"], name)


def _legacy_project(database) -> int:
    """The shape of project 57: a writer, two scripts, scenes and a timeline from before the plan; a plan waiting on a decision."""
    project_id = planned_project(database, status="needs_user_decision", title="Dự án cũ kiểu 57")
    project = database.get_production_project(project_id)
    old = [database.create_project_script(project_id, script_title=f"Bản cũ {index}", hook="Bạn có tin không?",
                                          intro="Ngày xưa có một làng.", main_content="Cảnh 1 · Mở đầu\nLời cũ một.\nLời cũ hai.",
                                          cta="Đăng ký kênh nhé.") for index in (1, 2)]
    database.save_video_analysis(project["youtube_video_id"], {
        "new_script": {"hook": "Bạn có tin không?", "main_content": "Lời cũ một."},
        "scene_blueprints": [{"order": index, "narration": f"Lời cũ {index}.", "visual_prompt": f"{WRITER_PROMPT} {index}",
                              "camera": "dolly", "asset_type": "ai_scene"} for index in range(1, 7)],
    }, analysis_type="writer", provider="test")
    shots = database.create_project_shots(project_id, int(old[1]["id"]), build_shot_plan(project, old[1]), force=True)
    database.create_project_timeline(project_id, int(old[1]["id"]), build_timeline(project, old[1], shots), force=True)
    return project_id


def _snapshot(database, project_id: int) -> dict:
    scripts = database.list_project_scripts(project_id, variant=None)
    keys = ("id", "version", "variant", "script_title", "hook", "intro", "main_content", "cta", "status", "plan_id",
            "plan_version", "document_json", "engine_version", "updated_at")
    plan = database.get_latest_project_plan(project_id) or {}
    video_id = database.get_production_project(project_id)["youtube_video_id"]
    return {
        "scripts": [{key: item.get(key) for key in keys} for item in scripts],
        "shots": {item["id"]: [(shot["id"], shot["narration"], shot["visual_prompt"], shot["updated_at"])
                               for shot in database.list_project_shots(project_id, script_id=int(item["id"]))] for item in scripts},
        "timeline": {item["id"]: [(segment["id"], segment["voice_text"], segment["updated_at"])
                                  for segment in database.list_project_timeline(project_id, script_id=int(item["id"]))] for item in scripts},
        "writer": (database.get_video_analysis(video_id, analysis_type="writer") or {}).get("result"),
        "plan": (plan.get("id"), plan.get("version"), plan.get("status"), json.dumps(plan.get("plan"), sort_keys=True)),
    }


# ===========================================================================
# A. The old /script/draft endpoint is an adapter on run_step("script")
# ===========================================================================

class LegacyEndpointTests(_Case):
    def test_1_script_draft_goes_through_the_script_engine(self) -> None:
        project_id = planned_project(self.database)
        with mock.patch.object(main, "generate_video_writer_content", _boom), mock.patch.object(main, "build_script_draft", _boom), \
                mock.patch.object(main, "resolve_writer", _boom):
            response = self.client.post(f"/api/projects/{project_id}/script/draft", json={})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["status"], body["engine_version"]), ("saved", script_engine.ENGINE_VERSION))
        self.assertEqual([call["stage"] for call in self.model.calls], ["script"])
        self.assertIn("GOC NOI DUNG DA CHON [ang-2]", self.model.calls[0]["prompt"])
        self.assertEqual(self._script(project_id)["state"], "completed")
        self.assertEqual(self._row(project_id)["outcome"]["engine_version"], script_engine.ENGINE_VERSION)
        # The same run and the same log as the step itself.
        logged = [row for row in self.database.list_orchestrator_steps(project_id) if row["why"] == "run_step(script)"]
        self.assertEqual([row["status"] for row in logged], ["success"])
        self.assertIsNone(self.database.get_video_analysis(self._video(project_id), analysis_type="writer"))

    def test_the_plan_is_not_the_endpoints_to_override(self) -> None:
        project_id = planned_project(self.database)
        response = self.client.post(f"/api/projects/{project_id}/script/draft", json={
            "target_duration_seconds": 90, "angle_id": "ang-1", "cta": "Mua ngay", "platform": "tiktok", "aspect_ratio": "9:16",
            "content_structure": [{"name": "x"}], "target_audience": "ai cũng được", "factual_guardrails": [],
        })
        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        for field in ("angle_id", "aspect_ratio", "content_structure", "cta", "platform", "target_audience", "target_duration_seconds"):
            self.assertIn(field, detail)
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self._long(project_id), [])

    def test_old_flags_are_named_as_ignored_and_change_nothing(self) -> None:
        project_id = planned_project(self.database)
        response = self.client.post(f"/api/projects/{project_id}/script/draft",
                                    json={"model": "gpt-x", "use_web_research": True, "provider": ""})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["ignored_fields"], ["model", "use_web_research"])
        self.assertIn("THOI LUONG MUC TIEU: 60 giay", self.model.calls[0]["prompt"])

    def _cannot_bypass(self, project_id: int, said_: str) -> None:
        before = _snapshot(self.database, project_id)
        for body in ({}, {"force": True}, {"draft": {"main_content": "Một bản nháp."}, "force": True},
                     {"create_standalone_short": True, "short_seconds": 30}):
            response = self.client.post(f"/api/projects/{project_id}/script/draft", json=body)
            self.assertEqual(response.status_code, 409, (body, response.text))
            self.assertEqual(response.json()["detail"], said_, body)
        self.assertEqual(self.model.calls, [])
        self.assertEqual(_snapshot(self.database, project_id), before, "nothing written, no Short either")

    def test_2_script_draft_cannot_bypass_a_missing_plan(self) -> None:
        self._cannot_bypass(planned_project(self.database, with_plan=False), NO_PLAN)

    def test_3_script_draft_cannot_bypass_a_plan_waiting_on_a_decision(self) -> None:
        self._cannot_bypass(planned_project(self.database, status="needs_user_decision"), NEEDS_DECISION)

    def test_4_script_draft_cannot_bypass_a_blocked_plan(self) -> None:
        self._cannot_bypass(planned_project(self.database, status="blocked"), BLOCKED)

    def test_5_script_draft_cannot_bypass_a_stale_plan(self) -> None:
        project_id = planned_project(self.database)
        plan = self.database.get_latest_project_plan(project_id)
        self.database.create_research_report(project_id, status="complete", source_kind="video",
                                             analysis_created_at=plan["analysis_created_at"], engine_version="test",
                                             report={"evidence": []}, captured_at=plan["created_at"])
        self._cannot_bypass(project_id, script_engine._PLAN_REFUSALS["stale"])


# ===========================================================================
# B. The old writer is never reused
# ===========================================================================

class WriterReuseTests(_Case):
    def test_6_an_old_writer_without_a_script_document_means_the_engine_writes(self) -> None:
        project_id = _legacy_project(self.database)
        # The decision is made: the plan is completed now.
        self._new_plan(project_id)
        writer_before = self.database.get_video_analysis(self._video(project_id), analysis_type="writer")["result"]
        response = self.client.post(f"/api/projects/{project_id}/script/draft", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.model.calls), 1, "written, not reused")
        body = self._script(project_id)
        self.assertEqual((body["state"], body["engine_version"]), ("completed", script_engine.ENGINE_VERSION))
        self.assertNotIn("Lời cũ", body["main_content"])
        self.assertEqual(self.database.get_video_analysis(self._video(project_id), analysis_type="writer")["result"], writer_before)

    def test_7_nothing_of_the_writers_scene_list_reaches_the_script_or_its_storyboard(self) -> None:
        project_id, script = self._written()
        lines = [line["text"] for section in script["document"]["sections"] for line in section["spoken_lines"]]
        # A writer whose scene list says exactly this script's words, recorded
        # before it: the case the old code would have taken it in.
        self.database.save_video_analysis(self._video(project_id), {"scene_blueprints": [
            {"order": index, "narration": text, "visual_prompt": f"{WRITER_PROMPT} {index}", "camera": "crane",
             "transition": "whip pan", "asset_type": "source_clip"} for index, text in enumerate(lines, start=1)
        ]}, analysis_type="writer", provider="test")
        with self.database._connect() as connection:
            connection.execute("UPDATE video_analyses SET created_at = '2000-01-01T00:00:00+00:00' "
                               "WHERE youtube_video_id = ? AND analysis_type = 'writer'", (self._video(project_id),))
        stored = self.database.get_project_script(int(script["id"]))["document_json"]
        for word in ("visual_prompt", "WRITER_VISUAL", "camera", "transition", "shot", "b-roll"):
            self.assertNotIn(word, stored.lower() if word == "b-roll" else stored, word)
        response = self._shots(project_id, force=True)
        self.assertEqual(response.status_code, 200, response.text)
        shots = response.json()["shots"]
        self.assertTrue(shots)
        self.assertFalse(any(WRITER_PROMPT in shot["visual_prompt"] for shot in shots))
        self.assertFalse(any(shot["asset_type"] == "source_clip" for shot in shots))


# ===========================================================================
# C. The Script Freshness Gate in front of the storyboard
# ===========================================================================

class StoryboardGateTests(_Case):
    def test_8_no_plan_no_storyboard(self) -> None:
        project_id = planned_project(self.database, with_plan=False)
        self.database.create_project_script(project_id, script_title="x", main_content="Một câu.\nHai câu.")
        before = _snapshot(self.database, project_id)
        self._all_refused(project_id, GO["no_plan"])
        self.assertEqual(_snapshot(self.database, project_id), before)

    def test_9_a_plan_that_is_not_ready_no_storyboard(self) -> None:
        for status, said_ in (("needs_user_decision", GO["needs_user_decision"]), ("blocked", GO["blocked"])):
            project_id = planned_project(self.database, status=status)
            self.database.create_project_script(project_id, script_title="x", main_content="Một câu.")
            before = _snapshot(self.database, project_id)
            for name in ("shots/generate", "shots/generate force"):
                response = self._every_way_to_build_on_it(project_id)[name]
                self.assertEqual(response.status_code, 409, status)
                self.assertIn(said_, response.json()["detail"], status)
            self.assertEqual(_snapshot(self.database, project_id), before)

    def test_10_a_stale_script_no_storyboard_and_nothing_after_it(self) -> None:
        project_id, script = self._written()
        self._new_plan(project_id, target_duration_seconds=45, content_structure=[
            {**PLAN["content_structure"][0]}, {**PLAN["content_structure"][1], "estimated_seconds": 25}, {**PLAN["content_structure"][2]}])
        self.assertEqual(self._script(project_id)["state"], "stale")
        before = _snapshot(self.database, project_id)
        self._all_refused(project_id, STALE)
        self.assertEqual(_snapshot(self.database, project_id), before)

    def test_11_a_script_missing_or_off_the_plans_version_no_storyboard(self) -> None:
        project_id = planned_project(self.database)
        response = self._shots(project_id, force=True)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], GO["missing"])

        plan = self.database.get_latest_project_plan(project_id)
        document = {"plan": {"plan_id": plan["id"], "plan_version": plan["version"]}, "sections": [], "validation": {"ok": True}}
        for plan_version, engine in ((None, script_engine.ENGINE_VERSION), (99, script_engine.ENGINE_VERSION),
                                     (plan["version"], "writer-legacy")):
            self.database.create_project_script(project_id, script_title="x", main_content="Một câu.", plan_id=plan["id"],
                                                plan_version=plan_version, document=document, engine_version=engine)
            response = self._shots(project_id, force=True)
            self.assertEqual(response.status_code, 409, (plan_version, engine))
            self.assertEqual(response.json()["detail"], GO["mismatch"], (plan_version, engine))
        self.assertEqual(self.database.list_project_shots(project_id), [])

    def test_12_a_current_script_goes_on_to_the_storyboard(self) -> None:
        project_id, script = self._written()
        # Not while the script is being written.
        self.assertIsNotNone(main._step_registry.claim((project_id, "script")))
        try:
            refused = self._shots(project_id)
            self.assertEqual(refused.status_code, 409)
            self.assertEqual(refused.json()["detail"], GO["running"])
        finally:
            main._step_registry.finish((project_id, "script"), {"status": "success"})
        response = self._shots(project_id)
        self.assertEqual(response.status_code, 200, response.text)
        shots = response.json()["shots"]
        lines = [line["text"] for section in script["document"]["sections"] for line in section["spoken_lines"]]
        self.assertEqual([shot["narration"] for shot in shots if shot["section"] == "main"], lines)
        self.assertEqual((shots[0]["section"], shots[-1]["section"]), ("hook", "cta"))
        timeline = self.client.post(f"/api/projects/{project_id}/steps/timeline", json={"options": {}})
        self.assertEqual(timeline.status_code, 200, timeline.text)

    def test_13_project_57_keeps_everything_and_none_of_it_opens_the_gate(self) -> None:
        project_id = _legacy_project(self.database)
        before = _snapshot(self.database, project_id)
        self._all_refused(project_id, GO["needs_user_decision"])
        self.assertEqual(_snapshot(self.database, project_id), before)
        # Still readable: the storyboard and the timeline of the old script.
        latest = self._long(project_id)[0]["id"]
        self.assertEqual(len(self.client.get(f"/api/projects/{project_id}/shots").json()), len(before["shots"][latest]))
        self.assertTrue(before["shots"][latest])
        bundle = self.client.get(f"/api/projects/{project_id}").json()
        self.assertTrue(bundle["latest_shots"])
        self.assertTrue(bundle["latest_timeline"])


# ===========================================================================
# D. PATCH: the document is the script, the columns are written from it
# ===========================================================================

class PatchTests(_Case):
    def _patch(self, script_id: int, **body):
        return self.client.patch(f"/api/scripts/{script_id}", json=body)

    def test_14_an_edit_goes_into_the_document(self) -> None:
        project_id, script = self._written()
        lines = script["main_content"].split("\n")
        first_s2 = len(script["document"]["sections"][0]["spoken_lines"])
        lines[first_s2] = "Trái Đất quay quanh trục nên có ngày và đêm."
        response = self._patch(int(script["id"]), main_content="\n".join(lines))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((response.json()["state"], response.json()["validation"]["ok"]), ("completed", True))
        document = self._script(project_id)["document"]
        self.assertEqual(document["sections"][1]["spoken_lines"][0]["text"], "Trái Đất quay quanh trục nên có ngày và đêm.")
        self.assertEqual(document["revisions"][-1]["source"], "patch")
        stored = self.database.get_project_script(int(script["id"]))
        self.assertEqual(stored["estimated_seconds"], document["estimated_seconds"])
        self.assertEqual((stored["plan_id"], stored["plan_version"], stored["engine_version"]),
                         (script["plan_id"], script["plan_version"], script["engine_version"]))

    def test_15_the_columns_and_the_document_always_say_the_same(self) -> None:
        project_id, script = self._written()
        sections = script["document"]["sections"]
        lines = script["main_content"].split("\n")
        at = len(sections[0]["spoken_lines"]) + 1
        lines.insert(at, "Đó là lý do mặt trời mọc rồi lặn mỗi ngày.")   # into s2, after its first line
        del lines[-1]                                                    # the last line of s3
        response = self._patch(int(script["id"]), main_content="\n".join(lines),
                               hook="Bạn có biết vì sao có ngày và đêm không?", script_title="Ngày và đêm")
        self.assertEqual(response.status_code, 200, response.text)
        stored = self.database.get_project_script(int(script["id"]))
        document = json.loads(stored["document_json"])
        mirror = script_engine.legacy_fields(document)
        for key in ("script_title", "hook", "intro", "main_content", "cta"):
            self.assertEqual(stored[key], mirror[key].strip(), key)
        self.assertEqual(stored["main_content"], "\n".join(lines))
        self.assertEqual(document["hook"]["spoken_lines"], [{"speaker": "narrator", "text": "Bạn có biết vì sao có ngày và đêm không?"}])
        self.assertEqual(document["sections"][1]["spoken_lines"][1]["text"], "Đó là lý do mặt trời mọc rồi lặn mỗi ngày.")
        self.assertEqual(len(document["sections"][1]["spoken_lines"]), len(sections[1]["spoken_lines"]) + 1)
        self.assertEqual(len(document["sections"][2]["spoken_lines"]), len(sections[2]["spoken_lines"]) - 1)
        self.assertEqual(document["title"], "Ngày và đêm")

    def test_16_an_edit_cannot_make_a_script_valid_that_is_not(self) -> None:
        project_id, script = self._written()
        script_id = int(script["id"])
        original = script["main_content"]
        # Saying what the plan forbids: kept, marked invalid, nothing built on it.
        broken = self._patch(script_id, main_content=original + "\nMọi khán giả đều thích video ngắn về vũ trụ hơn video dài.")
        self.assertEqual(broken.status_code, 200)
        self.assertEqual((broken.json()["state"], broken.json()["validation"]["ok"]), ("invalid", False))
        body = self._script(project_id)
        self.assertEqual((body["state"], body["document"]["checks"]["claims"]), ("invalid", "failed"))
        self.assertEqual(self._row(project_id)["state"], "invalid")
        self.assertNotIn("script", main._steps_done(project_id))
        self._all_refused(project_id, GO["invalid"])
        # A picture direction is no better.
        directed = self._patch(script_id, main_content=original + "\nCận cảnh Trái Đất quay chậm giữa không gian.")
        self.assertEqual(directed.json()["state"], "invalid")
        self.assertEqual(self._script(project_id)["document"]["checks"]["boundary"], "failed")
        # Fixed, it holds again.
        fixed = self._patch(script_id, main_content=original)
        self.assertEqual(fixed.json()["state"], "completed")
        self.assertEqual(self._shots(project_id).status_code, 200)

        # When the plan has moved on, no edit brings the script back.
        self._new_plan(project_id, target_duration_seconds=45, content_structure=[
            {**PLAN["content_structure"][0]}, {**PLAN["content_structure"][1], "estimated_seconds": 25}, {**PLAN["content_structure"][2]}])
        edited = self._patch(script_id, main_content=original, plan_id=999, plan_version=999)
        self.assertEqual(edited.status_code, 200)
        stored = self.database.get_project_script(script_id)
        self.assertEqual((stored["plan_id"], stored["plan_version"]), (script["plan_id"], script["plan_version"]))
        self.assertEqual(self._script(project_id)["state"], "stale")
        self.assertEqual(self._shots(project_id).status_code, 409)

    def test_an_older_script_edited_stays_what_it_was(self) -> None:
        project_id = _legacy_project(self.database)
        legacy = self.database.get_latest_project_script(project_id)
        response = self._patch(int(legacy["id"]), main_content="Lời mới hoàn toàn.")
        self.assertEqual(response.status_code, 200)
        stored = self.database.get_project_script(int(legacy["id"]))
        self.assertEqual((stored["document_json"], stored["plan_id"]), ("", None))
        self.assertEqual(self._script(project_id)["state"], "stale")

    def test_an_ai_rewrite_in_chat_is_a_new_version_on_the_same_plan(self) -> None:
        project_id, script = self._written()
        lines = script["main_content"].split("\n")
        lines[0] = "Vì sao có ngày và đêm? Vì Trái Đất tự quay."
        rewrite = {"script_title": script["script_title"], "hook": script["hook"], "intro": "", "main_content": "\n".join(lines),
                   "cta": script["cta"], "provider": "codex_cli"}
        with mock.patch.object(main, "revise_script", return_value=rewrite):
            response = self.client.post(f"/api/projects/{project_id}/script/chat", json={"message": "Mở đầu rõ hơn"})
        self.assertEqual(response.status_code, 200, response.text)
        body = self._script(project_id)
        self.assertEqual((body["version"], body["state"], body["plan_id"], body["engine_version"]),
                         (script["version"] + 1, "completed", script["plan_id"], script["engine_version"]))
        self.assertEqual(body["document"]["sections"][0]["spoken_lines"][0]["text"], lines[0])
        self.assertEqual(body["document"]["revisions"][-1]["source"], "chat")
        # On an older plan's script it is refused before any model is asked.
        self._new_plan(project_id, target_duration_seconds=45, content_structure=[
            {**PLAN["content_structure"][0]}, {**PLAN["content_structure"][1], "estimated_seconds": 25}, {**PLAN["content_structure"][2]}])
        with mock.patch.object(main, "revise_script", _boom):
            refused = self.client.post(f"/api/projects/{project_id}/script/chat", json={"message": "x"})
        self.assertEqual((refused.status_code, refused.json()["detail"]), (409, STALE))


# ===========================================================================
# E. The Short beside it
# ===========================================================================

SHORT = {"script_title": "Bản short", "hook": "Vì sao có ngày và đêm?", "intro": "",
         "main_content": "Trái Đất tự quay quanh trục.", "cta": "Theo dõi để xem tiếp."}


class ShortTests(_Case):
    def test_17_the_standalone_short_is_still_written(self) -> None:
        project_id = planned_project(self.database)
        with mock.patch.object(main, "build_short_script", return_value=SHORT) as writer:
            response = self.client.post(f"/api/projects/{project_id}/script/draft",
                                        json={"create_standalone_short": True, "short_seconds": 30})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["short_error"], body["short"]["script"]["variant"]), ("", "short"))
        self.assertTrue(body["short"]["shots"] and body["short"]["timeline"])
        long_script = body["script"]
        self.assertEqual(writer.call_args.args[1]["id"], long_script["id"], "written from the canonical long script")
        self.assertEqual(writer.call_args.kwargs["seconds"], 30)
        self.assertEqual(writer.call_args.kwargs["direction"], ANGLE["statement"], "the plan's angle is the brief")

        # The same through run_step (MCP, the orchestrator).
        other = planned_project(self.database)
        with mock.patch.object(main, "build_short_script", return_value=SHORT):
            ran = self.client.post(f"/api/projects/{other}/steps/script",
                                   json={"options": {"create_standalone_short": True, "short_direction": "Mở thật nhanh"}})
        self.assertEqual(ran.status_code, 200, ran.text)
        self.assertEqual(ran.json()["result"]["short"]["script"]["variant"], "short")

        # A Short that cannot be written does not undo the long script.
        third = planned_project(self.database)
        with mock.patch.object(main, "build_short_script", side_effect=main.ShortScriptError("không viết được")):
            failed = self.client.post(f"/api/projects/{third}/script/draft", json={"create_standalone_short": True})
        self.assertEqual(failed.status_code, 200)
        self.assertEqual((failed.json()["short"], failed.json()["short_error"]), (None, "không viết được"))
        self.assertEqual(self._script(third)["state"], "completed")

        # And the Short lane can write it again on its own, from the canonical script.
        again = self.client.post(f"/api/projects/{project_id}/short-script", json={"seconds": 30, "use_model": False})
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["script"]["variant"], "short")

    def test_18_the_short_is_never_a_second_canonical_script(self) -> None:
        project_id = planned_project(self.database)
        with mock.patch.object(main, "build_short_script", return_value=SHORT):
            body = self.client.post(f"/api/projects/{project_id}/script/draft", json={"create_standalone_short": True}).json()
        self.client.post(f"/api/projects/{project_id}/short-script", json={"seconds": 30, "use_model": False})
        long_scripts = self._long(project_id)
        self.assertEqual([item["id"] for item in long_scripts], [body["script"]["id"]])
        current = self._script(project_id)
        self.assertEqual((current["id"], current["state"]), (body["script"]["id"], "completed"))
        for short in self.database.list_project_scripts(project_id, variant="short"):
            # It records what it was made from (Phase 2.2), and is still not a ScriptDocument.
            self.assertEqual((short["engine_version"], script_engine.decode(short)), ("", None))
            self.assertEqual(script_engine.short_provenance(short)["source_script_id"], body["script"]["id"])
        self.assertEqual(self._shots(project_id).json()["script_id"], body["script"]["id"])

    def test_19_the_short_does_not_touch_the_plan(self) -> None:
        project_id = planned_project(self.database)
        before = _snapshot(self.database, project_id)["plan"]
        with mock.patch.object(main, "build_short_script", return_value=SHORT):
            self.client.post(f"/api/projects/{project_id}/script/draft", json={"create_standalone_short": True})
        self.client.post(f"/api/projects/{project_id}/short-script", json={"seconds": 30, "use_model": False})
        self.assertEqual(_snapshot(self.database, project_id)["plan"], before)


# ===========================================================================
# F. MCP, the AI orchestrator and the automation: the same step
# ===========================================================================

class OrchestrationTests(_Case):
    def _over_mcp(self):
        """MCP tools post to the app over HTTP; here they reach the same app through the test client."""
        def request(path, method="GET", data=None, headers=None, timeout=None):
            response = self.client.request(method, path, content=data, headers=headers or {})
            if response.status_code >= 400:
                raise RuntimeError(f"YT Factory báo lỗi HTTP {response.status_code}: {response.json().get('detail')}")
            return response.json()
        return mock.patch.object(ai_desktop_mcp, "_factory_request", side_effect=request)

    def test_20_mcp_run_step_script_is_the_same_path(self) -> None:
        project_id = planned_project(self.database)
        with self._over_mcp() as sent:
            result = ai_desktop_mcp._call_tool("youtube_factory_run_step", {"project_id": project_id, "step": "script"})
        self.assertEqual(sent.call_args.args[0], f"/api/projects/{project_id}/steps/script")
        written = json.loads(result["content"][0]["text"])["result"]
        self.assertEqual((written["plan_version"], written["primary_angle_id"]), (1, "ang-2"))
        self.assertEqual(self._script(project_id)["engine_version"], script_engine.ENGINE_VERSION)

        # Refused the same way, with a draft and force as well.
        waiting = planned_project(self.database, status="needs_user_decision")
        with self._over_mcp(), self.assertRaises(RuntimeError) as refused:
            ai_desktop_mcp._call_tool("youtube_factory_run_step", {"project_id": waiting, "step": "script", "options": {
                "draft": {"main_content": "x"}, "force": True}})
        self.assertIn(NEEDS_DECISION, str(refused.exception))

    def test_mcp_save_script_into_a_planned_project_is_a_checked_draft(self) -> None:
        project_id = planned_project(self.database)
        with self._over_mcp(), self.assertRaises(RuntimeError) as short:
            ai_desktop_mcp._call_tool("youtube_factory_save_script", {"project_id": project_id, "text": "Ngắn quá."})
        self.assertIn("kế hoạch đặt 60 giây", str(short.exception))
        self.assertEqual(self._long(project_id), [])

        text = "\n".join(line["text"] for line in said(190))
        with self._over_mcp():
            saved = json.loads(ai_desktop_mcp._call_tool("youtube_factory_save_script", {
                "project_id": project_id, "title": "Bản ChatGPT", "text": text})["content"][0]["text"])
        body = self._script(project_id)
        self.assertEqual((body["state"], body["engine_version"], body["main_content"]), ("completed", "agent-draft", text))
        self.assertEqual(saved["script"]["id"], body["id"])
        self.assertTrue(saved["shots"] and saved["timeline"], "its storyboard is cut through the gate")
        self.assertEqual(self._row(project_id)["outcome"]["engine_version"], "agent-draft")

        waiting = planned_project(self.database, status="blocked")
        with self._over_mcp(), self.assertRaises(RuntimeError) as blocked:
            ai_desktop_mcp._call_tool("youtube_factory_save_script", {"project_id": waiting, "text": text})
        self.assertIn(BLOCKED, str(blocked.exception))

    def test_21_the_ai_orchestrator_counts_only_the_current_script(self) -> None:
        project_id = _legacy_project(self.database)
        check = main._verify_goal(project_id, ["script"], claimed=["script"])
        self.assertEqual((check["missing"], check["false_claims"]), (["script"], ["script"]))
        # Its chat agents are sent to the step, not to writing a script of their own.
        self.assertIn("youtube_factory_run_step", main._CHAT_ROLE_INSTRUCTIONS["script"])
        self.assertIn("step='script'", main._CHAT_ROLE_INSTRUCTIONS["script"])
        self.assertNotIn("youtube_factory_save_script", main._CHAT_ROLE_INSTRUCTIONS["script"])

        planned = planned_project(self.database)
        self.client.post(f"/api/projects/{planned}/steps/script", json={"options": {}})
        self.assertEqual(main._verify_goal(planned, ["script"], claimed=["script"])["missing"], [])
        logged = [row for row in self.database.list_orchestrator_steps(planned) if row["why"] == "run_step(script)"]
        self.assertEqual([(row["stage"], row["status"]) for row in logged], [("script", "success")])

    def test_22_the_automation_script_agent_is_the_step(self) -> None:
        project_id = planned_project(self.database)
        with mock.patch.object(main, "_call_specific_agent_json", _boom):
            output = main._execute_agent_task({"role": "script", "project_id": project_id, "input": {"goal": "Video giải thích"}},
                                              "codex_cli")
        self.assertEqual(output["engine_version"], script_engine.ENGINE_VERSION)
        self.assertEqual(output["script_id"], self._script(project_id)["id"])
        self.assertEqual([call["stage"] for call in self.model.calls], ["script"])
        self.assertEqual(self.model.calls[0]["system"], script_engine.SYSTEM_PROMPT)

        waiting = planned_project(self.database, with_plan=False)
        with mock.patch.object(main, "_call_specific_agent_json", _boom), self.assertRaises(HTTPException) as refused:
            main._execute_agent_task({"role": "script", "project_id": waiting, "input": {}}, "codex_cli")
        self.assertEqual((refused.exception.status_code, refused.exception.detail), (409, NO_PLAN))


# ===========================================================================
# G. Project 78, from its plan v5 snapshot
# ===========================================================================

class Project78Tests(_Case):
    def _project_78(self) -> int:
        older = {**FIXTURE_78["plan"], "primary_angle_id": "ang-1", "target_duration_seconds": 90,
                 "primary_angle": {**FIXTURE_78["plan"]["primary_angle"], "id": "ang-1", "statement": "Góc cũ"}}
        return planned_project(self.database, kind="article", plan=FIXTURE_78["plan"], insight=FIXTURE_78["insight"],
                               analysis=FIXTURE_78["analysis"], earlier_plans=[older] * 4, title=FIXTURE_78["video"]["title"])

    def test_23_to_26_both_ways_write_the_same_script_from_plan_v5(self) -> None:
        project_id = self._project_78()
        # 23. The snapshot: plan v5, ang-2, 100 seconds, five sections.
        plan = self.database.get_latest_project_plan(project_id)
        self.assertEqual((plan["version"], plan["plan"]["primary_angle_id"], plan["plan"]["target_duration_seconds"]), (5, "ang-2", 100))
        self.assertEqual([item["estimated_seconds"] for item in plan["plan"]["content_structure"]], [10, 24, 27, 20, 19])
        self.assertEqual(self._row(project_id, "plan")["outcome"]["status"], "completed")

        # 24. Through run_step.
        first = self.client.post(f"/api/projects/{project_id}/steps/script", json={"options": {}})
        self.assertEqual(first.status_code, 200, first.text)
        a = self._script(project_id)
        # 25. Again through the old endpoint.
        second = self.client.post(f"/api/projects/{project_id}/script/draft", json={})
        self.assertEqual(second.status_code, 200, second.text)
        b = self._script(project_id)

        # 26. The same canonical script, one new version each time, nothing beside it.
        for prompt in (call["prompt"] for call in self.model.calls):
            self.assertIn("KE HOACH DA DUYET (ban 5)", prompt)
            self.assertIn("THOI LUONG MUC TIEU: 100 giay", prompt)
            self.assertNotIn("90 giay", prompt)
        for script in (a, b):
            document = script["document"]
            self.assertEqual((script["plan_id"], script["plan_version"], script["engine_version"]),
                             (plan["id"], 5, script_engine.ENGINE_VERSION))
            self.assertEqual((document["plan"]["primary_angle_id"], document["target_duration_seconds"]), ("ang-2", 100))
            self.assertEqual([(item["plan_section_id"], item["name"], item["budget_seconds"]) for item in document["sections"]],
                             [(f"s{index}", name, seconds) for index, (name, seconds) in enumerate(STRUCTURE_78, start=1)])
            self.assertLessEqual(abs(document["estimated_seconds"] - 100), 15)
            mirror = script_engine.legacy_fields(document)
            self.assertEqual((script["hook"], script["main_content"], script["cta"]), (mirror["hook"], mirror["main_content"], mirror["cta"]))
        self.assertEqual((a["version"] + 1, b["state"]), (b["version"], "completed"))
        self.assertEqual([item["id"] for item in self.database.list_project_scripts(project_id, variant=None)], [b["id"], a["id"]])
        self.assertIsNone(self.database.get_video_analysis(self._video(project_id), analysis_type="writer"))
        self.assertEqual(self._shots(project_id).json()["script_id"], b["id"])


# ===========================================================================
# H. Project 57: everything kept, nothing reopened
# ===========================================================================

class Project57Tests(_Case):
    def test_27_to_30_the_old_project_keeps_its_scripts_and_opens_nothing(self) -> None:
        project_id = _legacy_project(self.database)
        before = _snapshot(self.database, project_id)

        # 28. Stale, with the reason.
        body = self._script(project_id)
        self.assertEqual((body["state"], body["document"]), ("stale", None))
        self.assertIn("trước khi có kế hoạch", body["stale_reasons"][0])
        self.assertEqual(self._row(project_id)["state"], "blocked", "Bước 3 waits on the plan's decision")

        # 29. Nothing writes it again on its own: reading, listing, a storyboard attempt.
        self.client.get(f"/api/projects/{project_id}")
        self.client.get(f"/api/projects/{project_id}/steps")
        self._shots(project_id, force=True)
        self.assertEqual(self.model.calls, [])

        # 30. No way past the gate with it.
        self._all_refused(project_id, GO["needs_user_decision"])
        refusals = {
            "script/draft": self.client.post(f"/api/projects/{project_id}/script/draft", json={"force": True}),
            "import": self.client.post("/api/scripts/import", json={"project_id": project_id, "text": "Lời dán mới."}),
            "chat": self.client.post(f"/api/projects/{project_id}/script/chat", json={"message": "Viết lại"}),
            "director-draft": self.client.post(f"/api/projects/{project_id}/director-draft",
                                               json={"creative_direction": "Một câu chuyện mới hoàn toàn về mèo"}),
        }
        for name, response in refusals.items():
            self.assertEqual(response.status_code, 409, (name, response.text))
        self.assertIn("AI Đạo diễn cũ", refusals["director-draft"].json()["detail"])
        self.assertEqual(self.model.calls, [])

        # 27. Everything is still there, unchanged.
        self.assertEqual(_snapshot(self.database, project_id), before)
        self.assertEqual([item["version"] for item in self._long(project_id)], [2, 1])


if __name__ == "__main__":
    unittest.main()
