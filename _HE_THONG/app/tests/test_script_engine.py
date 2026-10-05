"""Bước 3 · Kịch bản, written from the plan.

    ProjectPlan (completed) → script_engine → ScriptDocument → checks by rule

The plan is the source of truth: the script uses its angle, its length and
its sections, and may not research, re-plan, describe pictures or say what
the plan forbids. Each rule is held here, then the step as a whole: who may
run it, what goes stale, what a duplicate run or a broken answer does, and
that older scripts survive. No test here reaches the network or a real model.
"""

from __future__ import annotations

import json
import re
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from youtube_monitor import main, script_engine
from youtube_monitor.llm_client import LlmError

from tests.script_fixtures import (  # noqa: F401 - shared with the other Bước 3 tests
    ANGLE, CTA_SECONDS, EV, FIXTURE_78, HOOK_SECONDS, INSIGHT, NOW, PLAN, READ_AT, STRUCTURE_78, Scripted, in_turn,
    planned_project as _planned, said as _said, script_answer,
)
from tests.script_fixtures import _WORDS  # noqa: F401


def _first_line(text: str):
    """An edit that puts `text` as the first spoken line of the first section."""
    def edit(answer: dict) -> None:
        answer["sections"][0]["spoken_lines"][0] = {"speaker": "narrator", "text": text}
    return edit


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

    def _generate(self, project_id: int, **options):
        return self.client.post(f"/api/projects/{project_id}/script/generate", json={"options": options})

    def _ok(self, project_id: int, **options) -> dict:
        response = self._generate(project_id, **options)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["result"]

    def _script(self, project_id: int) -> dict:
        return self.client.get(f"/api/projects/{project_id}/script").json()

    def _row(self, project_id: int) -> dict:
        body = self.client.get(f"/api/projects/{project_id}/steps").json()
        return next(row for row in body["steps"] if row["key"] == "script")


# ---------------------------------------------------------------------------
# Who may run it
# ---------------------------------------------------------------------------

class StepContractTests(_Case):
    def test_a_completed_plan_is_written_into_a_script(self) -> None:
        project_id = _planned(self.database)
        result = self._ok(project_id)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([call["stage"] for call in self.model.calls], ["script"], "one call, under the script stage's policy")
        body = self._script(project_id)
        self.assertEqual((body["state"], body["stale"], body["approval_status"]), ("completed", False, "draft"))
        self.assertEqual(body["engine_version"], "script-phase1")
        self.assertEqual(self._row(project_id)["state"], "done")
        self.assertIn("script", main._steps_done(project_id))

    def test_without_a_ready_plan_nothing_is_written(self) -> None:
        cases = {
            "no plan": (dict(with_plan=False), "Bạn cần hoàn thành Kế hoạch trước khi viết kịch bản."),
            "needs_user_decision": (dict(status="needs_user_decision"), "cần bạn quyết định"),
            "blocked": (dict(status="blocked"), "chưa thể thực hiện"),
        }
        for name, (setup, said) in cases.items():
            project_id = _planned(self.database, **setup)
            for options in ({}, {"force": True}, {"draft": {"main_content": "Một bản nháp do agent viết."}},
                            {"draft": {"main_content": "Một bản nháp do agent viết."}, "force": True}):
                # The script endpoint, and the step endpoint an orchestrator reaches over MCP (youtube_factory_run_step).
                for response in (self._generate(project_id, **options),
                                 self.client.post(f"/api/projects/{project_id}/steps/script", json={"options": options})):
                    self.assertEqual(response.status_code, 409, (name, options))
                    self.assertIn(said.lower(), response.json()["detail"].lower(), name)
            self.assertEqual(self.model.calls, [], name)
            self.assertIsNone(self.database.get_latest_project_script(project_id), name)

    def test_a_stale_plan_carries_no_script(self) -> None:
        project_id = _planned(self.database)
        plan = self.database.get_latest_project_plan(project_id)
        self.database.create_research_report(project_id, status="complete", source_kind="video",
                                             analysis_created_at=plan["analysis_created_at"], engine_version="test",
                                             report={"evidence": [{"id": EV}]}, captured_at=NOW.isoformat())
        response = self._generate(project_id, force=True)
        self.assertEqual(response.status_code, 409)
        self.assertIn("Kế hoạch đã cũ", response.json()["detail"])

    def test_the_step_and_its_endpoint_are_one_door(self) -> None:
        project_id = _planned(self.database)
        direct = main.run_project_step(project_id, "script", {})
        self.assertEqual(direct["step"], "script")
        self.assertEqual(direct["result"]["status"], "completed")
        # The endpoint holds no logic of its own.
        import inspect
        source = inspect.getsource(main.generate_project_script)
        self.assertIn('run_project_step(project_id, "script", payload.options)', source)


# ---------------------------------------------------------------------------
# What the model is given
# ---------------------------------------------------------------------------

class PlanInputTests(_Case):
    def test_the_prompt_carries_the_plan_and_nothing_researched(self) -> None:
        project_id = _planned(self.database)
        self._ok(project_id)
        prompt = self.model.calls[0]["prompt"]
        self.assertIn("GOC NOI DUNG DA CHON [ang-2]: Trả lời câu hỏi vì sao Trái Đất quay", prompt)
        self.assertIn("THOI LUONG MUC TIEU: 60 giay", prompt)
        for line in ("- [s1] Mở đầu — 10 giay", "- [s2] Thân bài — 40 giay", "- [s3] Kết — 10 giay"):
            self.assertIn(line, prompt)
        self.assertIn("PHAI GIU DUNG:\n- Mới có một nguồn đưa", prompt)
        self.assertIn("KHONG DUOC NOI", prompt)
        self.assertIn("Mọi khán giả đều thích video ngắn", prompt)
        self.assertIn("GIA THUYET (KHONG phai su that", prompt)
        self.assertIn(f"[{EV}]", prompt)
        self.assertIn("Loi ket (CTA): Mời xem phần tiếp theo", prompt)
        self.assertIn("Khong tu nghien cuu them", self.model.calls[0]["system"])

    def test_step_three_neither_researches_nor_reaches_for_the_old_writer(self) -> None:
        project_id = _planned(self.database)
        boom = mock.Mock(side_effect=AssertionError("must not be called"))
        with mock.patch.object(main, "research_folklore_remake", boom), \
                mock.patch.object(main, "generate_video_writer_content", boom), \
                mock.patch.object(main, "resolve_writer", boom), \
                mock.patch.object(main.web_research, "search", boom):
            self._ok(project_id)
        import inspect
        engine = inspect.getsource(script_engine).split('"""', 2)[2]
        for gone in ("folklore", "web_research", "resolve_writer", "research_collectors", "project_planner.run("):
            self.assertNotIn(gone, engine, gone)

    def test_project_78_is_written_from_its_plan_v5_not_from_a_default(self) -> None:
        """Snapshot of the real project 78: plan v5, angle ang-2, 100 seconds, five sections."""
        older = {**FIXTURE_78["plan"], "primary_angle_id": "ang-1", "target_duration_seconds": 90,
                 "primary_angle": {**FIXTURE_78["plan"]["primary_angle"], "id": "ang-1", "statement": "Góc cũ"}}
        project_id = _planned(self.database, kind="article", plan=FIXTURE_78["plan"], insight=FIXTURE_78["insight"],
                              analysis=FIXTURE_78["analysis"], earlier_plans=[older] * 4, title=FIXTURE_78["video"]["title"])
        result = self._ok(project_id)
        prompt = self.model.calls[0]["prompt"]
        self.assertIn("KE HOACH DA DUYET (ban 5)", prompt)
        self.assertIn("GOC NOI DUNG DA CHON [ang-2]", prompt)
        self.assertIn("THOI LUONG MUC TIEU: 100 giay", prompt)
        self.assertNotIn("90 giay", prompt)
        for index, (name, seconds) in enumerate(STRUCTURE_78, start=1):
            self.assertIn(f"- [s{index}] {name} — {seconds} giay", prompt)
        for claim in FIXTURE_78["plan"]["claims_to_avoid"]:
            self.assertIn(" ".join(claim.split())[:120], prompt)
        self.assertEqual((result["plan_version"], result["primary_angle_id"], result["target_duration_seconds"]), (5, "ang-2", 100))
        self.assertLessEqual(abs(result["estimated_seconds"] - 100), 15)
        self.assertEqual([(item["name"], item["budget_seconds"]) for item in result["sections"]], STRUCTURE_78)
        document = self._script(project_id)["document"]
        self.assertEqual((document["plan"]["plan_version"], document["plan"]["primary_angle_id"]), (5, "ang-2"))


# ---------------------------------------------------------------------------
# What the code checks after the model
# ---------------------------------------------------------------------------

class ValidationTests(_Case):
    def _refused(self, answer, said: str, *, kind: str = "video", facts: dict | None = None, plan: dict | None = None) -> None:
        """The answer is refused, the one repair is spent on it, and the step fails cleanly."""
        self.model.answer = answer
        self.model.calls.clear()
        project_id = _planned(self.database, kind=kind, facts=facts, plan=plan)
        response = self._generate(project_id)
        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(len(self.model.calls), 2, "one generation and one repair, no more")
        self.assertIn(said, self.model.calls[1]["prompt"])
        self.assertIsNone(self.database.get_latest_project_script(project_id), "nothing half-written is saved")

    def test_the_wrong_angle_is_refused(self) -> None:
        self._refused(partial(script_answer, angle="ang-1"), "angle_id phải là ang-2")

    def test_sections_must_be_the_plans_in_its_order(self) -> None:
        self._refused(partial(script_answer, order=["s1", "s3"]), "thiếu s2")
        self._refused(partial(script_answer, order=["s1", "s2", "s3", "s9"]), "không có trong kế hoạch: s9")
        self._refused(partial(script_answer, order=["s2", "s1", "s3"]), "sai thứ tự hoặc lặp")

    def test_the_length_is_counted_not_believed(self) -> None:
        self._refused(partial(script_answer, scale=0.5), "kế hoạch đặt 60 giây")
        self._refused(partial(script_answer, scale=1.6), "kế hoạch đặt 60 giây")

    def test_a_section_may_not_run_far_past_its_budget(self) -> None:
        def stretch(answer: dict) -> None:
            answer["sections"][0]["spoken_lines"] = _said(60)          # ~19 s where the plan gives 10 (6 of them after the hook)
            answer["sections"][1]["spoken_lines"] = _said(80)          # and the rest shortened so the total still fits
        self._refused(partial(script_answer, edit=stretch), "[s1] dài khoảng")

    def test_evidence_and_insights_must_exist(self) -> None:
        def cite(answer: dict) -> None:
            answer["sections"][0]["evidence_ids"] = ["ev-0000000000"]
            answer["sections"][1]["insight_ids"] = ["in-9", "hy-1"]
        self._refused(partial(script_answer, edit=cite), "dẫn mã không tồn tại")

    def test_a_number_nobody_read_is_refused(self) -> None:
        self._refused(partial(script_answer, edit=_first_line("Có 1.250 nhà khoa học đã đo được điều này.")), "số liệu không có trong nguồn")

    def test_a_claim_the_plan_forbids_is_refused_but_a_hedged_mention_is_not(self) -> None:
        self._refused(partial(script_answer, edit=_first_line("Mọi khán giả đều thích video ngắn về vũ trụ hơn video dài.")),
                      "nói điều kế hoạch cấm")
        self.model = Scripted(partial(script_answer, edit=_first_line(
            "Chưa có gì cho thấy mọi khán giả đều thích video ngắn về vũ trụ hơn video dài.")))
        with mock.patch.object(main, "_call_orchestrator_json", self.model):
            self.assertEqual(self._generate(_planned(self.database)).status_code, 200)

    def test_a_guess_is_not_said_as_a_fact(self) -> None:
        self._refused(partial(script_answer, edit=_first_line(
            "Người xem lớn tuổi thường bỏ video giữa chừng khi nghe thuật ngữ khoa học.")), "giả thuyết như sự thật")

    def test_no_picture_camera_or_shot_directions(self) -> None:
        self._refused(partial(script_answer, edit=_first_line("Cận cảnh Trái Đất quay chậm giữa không gian.")), "chỉ dẫn hình ảnh")

        def screen(answer: dict) -> None:
            answer["hook"]["on_screen_text"] = ["[B-roll: vũ trụ xoay]"]
        self._refused(partial(script_answer, edit=screen), "chỉ dẫn hình ảnh")

    def test_a_visual_prompt_the_model_adds_never_reaches_the_document(self) -> None:
        def picture(answer: dict) -> None:
            for section in answer["sections"]:
                section["visual_prompt"] = "a planet spinning, cinematic"
            answer["camera"] = "slow push-in"
        self.model.answer = partial(script_answer, edit=picture)
        project_id = _planned(self.database)
        self._ok(project_id)
        stored = self.database.get_latest_project_script(project_id)
        for word in ("visual_prompt", "camera", "asset_type", "shot"):
            self.assertNotIn(word, stored["document_json"], word)
        self.assertNotIn("visual_prompt", json.dumps(self._script(project_id), ensure_ascii=False))


class ProductPriceTests(_Case):
    FACTS = {"name": "Tai nghe X1", "price": "119000", "price_text": "119.000₫", "captured_at": READ_AT}

    def _product(self, facts: dict, line: str):
        self.model.answer = partial(script_answer, edit=_first_line(line))
        plan = {**PLAN, "source_kind": "product", "constraints": {**PLAN["constraints"]}}
        if not facts.get("price"):
            plan["constraints"]["no_price_claims"] = True
        return _planned(self.database, kind="product", facts=facts, plan=plan, title="Tai nghe X1")

    def test_a_price_said_aloud_keeps_the_moment_it_was_read(self) -> None:
        project_id = self._product(self.FACTS, "Giá trên trang bán là 119.000₫ tại thời điểm đọc.")
        self._ok(project_id)
        document = self._script(project_id)["document"]
        line = document["sections"][0]["spoken_lines"][0]
        self.assertEqual(line["price_captured_at"], READ_AT)
        self.assertEqual(document["price_reading"], {"text": "119.000₫", "captured_at": READ_AT})
        self.assertIn("119.000₫", self.model.calls[0]["prompt"])
        self.assertIn(f"Gia duoc doc luc: {READ_AT}", self.model.calls[0]["prompt"])

    def test_a_price_that_was_not_read_wrong_or_old_is_refused(self) -> None:
        for facts, line, said in (
            ({"name": "Tai nghe X1", "price": "", "captured_at": None}, "Giá chỉ 99.000₫ thôi.", "chưa đọc được giá"),
            (self.FACTS, "Giá trên trang bán là 99.000₫.", "không khớp giá đã đọc"),
            ({**self.FACTS, "captured_at": (NOW - timedelta(days=2)).isoformat()}, "Giá trên trang bán là 119.000₫.", "quá 24 giờ"),
        ):
            self.model = Scripted()
            with mock.patch.object(main, "_call_orchestrator_json", self.model):
                project_id = self._product(facts, line)
                response = self._generate(project_id)
                self.assertEqual(response.status_code, 502, said)
                self.assertIn(said, self.model.calls[1]["prompt"])

    def test_a_product_without_a_price_is_written_without_one(self) -> None:
        project_id = self._product({"name": "Tai nghe X1", "price": "", "captured_at": None}, "Tai nghe này có hộp sạc đi kèm.")
        self._ok(project_id)
        self.assertIn("CHUA DOC DUOC GIA", self.model.calls[0]["prompt"])
        self.assertIsNone(self._script(project_id)["document"]["price_reading"])


class DocumentTests(_Case):
    def test_the_document_follows_the_plan_and_fills_the_old_columns(self) -> None:
        project_id = _planned(self.database)
        self._ok(project_id)
        body = self._script(project_id)
        document = body["document"]
        self.assertEqual([section["plan_section_id"] for section in document["sections"]], ["s1", "s2", "s3"])
        self.assertEqual([section["budget_seconds"] for section in document["sections"]], [10, 40, 10])
        self.assertEqual((document["hook"]["plan_section_id"], document["cta"]["plan_section_id"]), ("s1", "s3"))
        self.assertLessEqual(abs(document["estimated_seconds"] - 60), 9)
        self.assertEqual(document["plan"]["primary_angle_id"], "ang-2")
        self.assertEqual(document["checks"], {"plan_alignment": "ok", "duration": "ok", "evidence": "ok", "claims": "ok", "boundary": "ok"})
        self.assertEqual((body["plan_id"], body["plan_version"], body["language"]), (body["current_plan"]["id"], 1, "vi"))
        self.assertEqual(body["estimated_seconds"], document["estimated_seconds"])
        # The columns older readers use are written from the document, one spoken line per line:
        # every section in order in main_content, the hook and the CTA in their own.
        self.assertEqual(body["hook"], "\n".join(line["text"] for line in document["hook"]["spoken_lines"]))
        self.assertEqual(body["intro"], "")
        self.assertEqual(body["main_content"], "\n".join(line["text"] for section in document["sections"]
                                                          for line in section["spoken_lines"]))
        self.assertEqual(body["cta"], "\n".join(line["text"] for line in document["cta"]["spoken_lines"]))
        self.assertNotIn("Cảnh ", body["main_content"])


# ---------------------------------------------------------------------------
# Stale, running, broken answers, runtimes
# ---------------------------------------------------------------------------

class StaleTests(_Case):
    def test_a_new_plan_makes_the_script_stale_and_nothing_is_built_on_it(self) -> None:
        project_id = _planned(self.database)
        self._ok(project_id)
        plan = self.database.get_latest_project_plan(project_id)
        self.database.create_project_plan(project_id, status="completed", research_report_id=plan["research_report_id"],
                                          analysis_created_at=plan["analysis_created_at"], engine_version="plan-phase3",
                                          plan={**PLAN, "target_duration_seconds": 45, "content_structure": [
                                              {**PLAN["content_structure"][0]}, {**PLAN["content_structure"][1], "estimated_seconds": 25},
                                              {**PLAN["content_structure"][2]}]},
                                          feasibility={"status": "ok", "checks": []},
                                          insight_report_id=plan["insight_report_id"])
        body = self._script(project_id)
        self.assertEqual((body["state"], body["stale"]), ("stale", True))
        self.assertIn("Kế hoạch đã thay đổi sau khi viết kịch bản", body["stale_reasons"])
        row = self._row(project_id)
        self.assertEqual((row["state"], row["outcome"]["status"], row["outcome"]["completed"]), ("stale", "stale", False))
        self.assertNotIn("script", main._steps_done(project_id))
        for options in ({}, {"force": True}):
            refused = self.client.post(f"/api/projects/{project_id}/steps/shots", json={"options": options})
            self.assertEqual(refused.status_code, 409)
            self.assertEqual(refused.json()["detail"], script_engine.STALE_SCRIPT_MESSAGE)
        # Written again from the new plan, it is current.
        self._ok(project_id)
        self.assertEqual(self._script(project_id)["state"], "completed")
        self.assertIn("45 giay", self.model.calls[-1]["prompt"])

    def test_a_plan_gone_stale_takes_its_script_with_it(self) -> None:
        project_id = _planned(self.database)
        self._ok(project_id)
        plan = self.database.get_latest_project_plan(project_id)
        self.database.create_research_report(project_id, status="complete", source_kind="video",
                                             analysis_created_at=plan["analysis_created_at"], engine_version="test",
                                             report={"evidence": [{"id": EV}]}, captured_at=NOW.isoformat())
        body = self._script(project_id)
        self.assertEqual(body["state"], "stale")
        self.assertIn("Kế hoạch hiện chưa sẵn sàng", body["stale_reasons"])


class LegacyTests(_Case):
    def test_older_scripts_are_kept_untouched_and_are_not_current(self) -> None:
        """Like project 57: scripts and a writer from before the plan, a plan made since."""
        project_id = _planned(self.database)
        project = self.database.get_production_project(project_id)
        old = [self.database.create_project_script(project_id, script_title="Bản cũ", hook=f"Hook cũ {index}", intro="Mở cũ",
                                                   main_content="Cảnh 3 · Diễn biến\nLời cũ", cta="Đăng ký nhé") for index in (1, 2)]
        self.database.save_video_analysis(project["youtube_video_id"], {"scene_blueprints": [{"order": 1, "narration": "Lời cũ",
                                          "visual_prompt": "x"}]}, analysis_type="writer", provider="test")
        self.database.create_project_shots(project_id, int(old[1]["id"]), [{"shot_index": 1, "section": "main", "narration": "Lời cũ",
                                           "visual_prompt": "x", "asset_type": "ai_scene", "duration_seconds": 5}], force=True)
        body = self._script(project_id)
        self.assertEqual((body["state"], body["document"]), ("stale", None))
        self.assertIn("trước khi có kế hoạch", body["stale_reasons"][0])
        self.assertNotIn("script", main._steps_done(project_id))
        self.assertIn("shots", main._steps_done(project_id), "what was built from it is still there")

        result = self._ok(project_id)
        versions = self.database.list_project_scripts(project_id)
        self.assertEqual([item["version"] for item in versions], [3, 2, 1])
        for before in old:
            after = self.database.get_project_script(int(before["id"]))
            for key in ("script_title", "hook", "intro", "main_content", "cta", "status", "version"):
                self.assertEqual(after[key], before[key], key)
            self.assertIsNone(after["plan_id"])
        self.assertEqual(result["version"], 3)
        self.assertEqual(self.database.get_video_analysis(project["youtube_video_id"], analysis_type="writer")["result"]
                         ["scene_blueprints"][0]["narration"], "Lời cũ", "the old writer's output is left as it was")

    def test_the_old_draft_endpoint_now_writes_through_the_engine(self) -> None:
        """Phase 2: /script/draft is a thin adapter on run_step("script") - see test_script_paths."""
        project_id = _planned(self.database)
        response = self.client.post(f"/api/projects/{project_id}/script/draft", json={})
        self.assertEqual(response.status_code, 200, response.text)
        body = self._script(project_id)
        self.assertEqual((body["state"], body["engine_version"]), ("completed", script_engine.ENGINE_VERSION))
        self.assertEqual(body["plan_id"], body["current_plan"]["id"])


class RunningTests(_Case):
    def test_a_second_run_is_refused_and_a_reload_sees_the_first(self) -> None:
        project_id = _planned(self.database)
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def slow(prompt: str) -> dict:
            entered.set()
            release.wait(10)
            return script_answer(prompt)

        self.model.answer = slow
        errors: list = []

        def run() -> None:
            try:
                main.run_project_step(project_id, "script", {})
            except HTTPException as exc:
                errors.append(exc)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.assertTrue(entered.wait(10))
        row = self._row(project_id)
        self.assertEqual(row["state"], "running")
        self.assertEqual((row["run"]["stage"], row["run"]["stage_label"]), ("write", "Viết lời"))
        self.assertEqual([item["label"] for item in row["run"]["stages"]], [label for _, label in script_engine.STAGES])
        self.assertEqual(self._script(project_id)["generation"]["status"], "running")
        second = self._generate(project_id)
        self.assertEqual(second.status_code, 409)
        self.assertIn("đang chạy", second.json()["detail"])
        release.set()
        thread.join(10)
        self.assertEqual(errors, [])
        self.assertEqual(len(self.model.calls), 1, "never two generations for one project at once")
        self.assertEqual(self._row(project_id)["last_run"]["status"], "success")


class RepairTests(_Case):
    def test_an_answer_that_is_not_json_is_repaired_once(self) -> None:
        self.model.answer = in_turn("đây không phải JSON", script_answer)
        project_id = _planned(self.database)
        result = self._ok(project_id)
        self.assertEqual((result["ai"]["calls"], result["ai"]["repair_used"]), (2, True))
        self.assertIn("Ban kich ban truoc KHONG dung", self.model.calls[1]["prompt"])

    def test_still_unusable_after_the_repair_is_a_clean_failure(self) -> None:
        self.model.answer = in_turn({"sections": []})
        project_id = _planned(self.database)
        response = self._generate(project_id)
        self.assertEqual(response.status_code, 502)
        self.assertIn("khi viết kịch bản", response.json()["detail"])
        self.assertNotIn("Traceback", response.text)
        self.assertEqual(len(self.model.calls), 2)
        self.assertIsNone(self.database.get_latest_project_script(project_id))
        self.assertEqual(self._row(project_id)["last_run"]["status"], "failed")
        self.assertEqual(self._script(project_id)["generation"]["status"], "failed")


class RuntimeFallbackTests(unittest.TestCase):
    """Through the real orchestrator call: the script stage's policy, its fallback, its audit row."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._client_cm = TestClient(main.app)
        cls.client = cls._client_cm.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)

    def test_a_runtime_that_fails_hands_over_to_the_next_one(self) -> None:
        project_id = _planned(main.database)
        assignment = {"mode": "fallback", "executor": "astra", "allowed_agents": ["astra", "claude"],
                      "fallback_agents": ["claude"], "reviewer": "auto"}
        ready = {"installed": True, "logged_in": True}
        asked: list[str] = []

        def claude(system, user, schema):
            asked.append("claude")
            return script_answer(user)

        with mock.patch.object(main.settings, "agent_assignment", side_effect=lambda stage: asked.append(stage) or assignment), \
                mock.patch.object(main, "codex_cli_status", return_value=ready), \
                mock.patch.object(main, "claude_code_cli_status", return_value=ready), \
                mock.patch.object(main, "antigravity_cli_status", return_value={"installed": False, "logged_in": False}), \
                mock.patch.object(main, "call_codex_json", side_effect=LlmError("codex hết giờ")), \
                mock.patch.object(main, "call_claude_code_cli_json", side_effect=claude), \
                mock.patch.object(main, "call_antigravity_json", side_effect=AssertionError("not allowed")):
            response = self.client.post(f"/api/projects/{project_id}/script/generate", json={"options": {}})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        self.assertIn("script", asked, "the script stage's policy decides who writes")
        self.assertEqual(result["ai"]["runtimes"], ["claude_code_cli"])
        self.assertEqual(result["ai"]["detail"][0]["fallback_from"], ["codex_cli"])
        audit = [step for step in main.database.list_orchestrator_steps() if step.get("project_id") == project_id]
        self.assertIn("Viết kịch bản", [step["step"] for step in audit if step["runtime"] == "claude_code_cli"])


class AgentDraftTests(_Case):
    def _draft(self, **over) -> dict:
        words = " ".join(_WORDS)
        sentences = " ".join(f"{words.capitalize()}." for _ in range(10))
        return {"script_title": "Bản nháp của agent", "hook": "Bạn có biết vì sao Trái Đất quay không?", "intro": "",
                "main_content": sentences, "cta": "Mời xem phần tiếp theo.", **over}

    def test_an_agents_own_script_is_held_to_the_same_plan(self) -> None:
        project_id = _planned(self.database)
        result = self._ok(project_id, draft=self._draft())
        self.assertEqual(self.model.calls, [], "a draft costs no model call")
        body = self._script(project_id)
        self.assertEqual((body["state"], body["engine_version"], body["approval_status"]), ("completed", "agent-draft", "review"))
        self.assertEqual(body["document"]["checks"]["plan_alignment"], "not_checked")
        self.assertEqual(result["script_id"], body["id"])

    def test_a_draft_that_breaks_the_plan_is_refused_with_the_reasons(self) -> None:
        project_id = _planned(self.database)
        forbidden = self._generate(project_id, draft=self._draft(cta="Mọi khán giả đều thích video ngắn về vũ trụ hơn video dài."))
        self.assertEqual(forbidden.status_code, 422)
        self.assertIn("nói điều kế hoạch cấm", forbidden.json()["detail"])
        short = self._generate(project_id, draft=self._draft(main_content="Một câu thôi."))
        self.assertEqual(short.status_code, 422)
        self.assertIn("kế hoạch đặt 60 giây", short.json()["detail"])
        self.assertIsNone(self.database.get_latest_project_script(project_id))


if __name__ == "__main__":
    unittest.main()
