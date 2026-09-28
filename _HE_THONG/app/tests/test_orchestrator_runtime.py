from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from youtube_monitor import orchestrator_runtime
from youtube_monitor.database import Database


def _statuses(**ready: bool) -> dict[str, object]:
    """CLI status probes with the login state each test needs."""
    return {
        key: (lambda state=state: {"installed": True, "logged_in": state, "detail": ""})
        for key, state in ready.items()
    }


class RuntimeMappingTests(unittest.TestCase):
    def test_product_names_map_to_the_runtime_that_executes_them(self) -> None:
        """Astra is a Codex model, not an Antigravity one.

        `codex exec` reports `model: gpt-6-astra`, while `agy models` lists
        only Gemini, Claude and GPT-OSS. Sending Astra to Antigravity ran
        every Astra step on another vendor's model.
        """
        self.assertEqual(orchestrator_runtime.runtime_id("astra"), "codex_cli")
        self.assertEqual(orchestrator_runtime.runtime_id("antigravity"), "antigravity")
        self.assertEqual(orchestrator_runtime.runtime_id("claude"), "claude_code_cli")

    def test_the_chatgpt_app_has_no_local_runtime_standing_in_for_it(self) -> None:
        """A chat subscription cannot be called like an API.

        Mapping it onto Codex meant work assigned to the ChatGPT app was run
        by a different product and reported as if the app had done it.
        """
        self.assertEqual(orchestrator_runtime.runtime_id("chatgpt_app"), "chatgpt_app")
        self.assertNotIn("chatgpt_app", orchestrator_runtime.CALLABLE_RUNTIMES)

    def test_an_unknown_agent_is_left_alone_rather_than_guessed(self) -> None:
        self.assertEqual(orchestrator_runtime.runtime_id("mystery_ai"), "mystery_ai")


class ReadinessTests(unittest.TestCase):
    def test_a_missing_api_key_blocks_gpt_and_says_so(self) -> None:
        with patch("youtube_monitor.orchestrator_runtime.settings.openai_config", return_value=("", "gpt-4o-mini")):
            readiness = orchestrator_runtime.runtime_readiness(
                statuses=_statuses(antigravity=True, claude_code_cli=False, codex_cli=False),
            )
        gpt = orchestrator_runtime.readiness_index(readiness)["openai_gpt"]
        self.assertFalse(gpt["ready"])
        self.assertEqual(gpt["blocked_reason"], "missing_key")
        self.assertIn("OPENAI_API_KEY", gpt["detail"])

    def test_an_installed_cli_without_login_is_not_ready(self) -> None:
        readiness = orchestrator_runtime.runtime_readiness(
            statuses=_statuses(antigravity=False, claude_code_cli=True, codex_cli=False),
        )
        index = orchestrator_runtime.readiness_index(readiness)
        self.assertFalse(index["antigravity"]["ready"])
        self.assertEqual(index["antigravity"]["blocked_reason"], "missing_login")
        self.assertTrue(index["claude_code_cli"]["ready"])

    def test_a_configured_chat_tunnel_alone_is_not_readiness(self) -> None:
        with patch(
            "youtube_monitor.orchestrator_runtime.settings.integration_value", return_value="tunnel-123"
        ), patch(
            "youtube_monitor.orchestrator_runtime.chat_agent_presence.connected", return_value=False
        ):
            readiness = orchestrator_runtime.runtime_readiness(statuses=_statuses(codex_cli=True))
        chat = orchestrator_runtime.readiness_index(readiness)["chatgpt_app_mcp"]
        self.assertFalse(chat["ready"])
        self.assertEqual(chat["blocked_reason"], "no_live_tunnel")

    def test_a_recorded_usage_limit_outranks_a_green_login(self, ) -> None:
        """A current outage: failed just now, reset still ahead.

        The fixture used to be a fixed date that has since passed, and the
        test kept passing only because readiness ignored the reset time - the
        stale-outage bug itself. It is dated from now instead.
        """
        now = datetime.now(timezone.utc)
        resets = (now + timedelta(hours=3)).isoformat()
        with patch(
            "youtube_monitor.orchestrator_runtime.settings.openai_config", return_value=("", "gpt-4o-mini")
        ):
            readiness = orchestrator_runtime.runtime_readiness(
                _FakeDatabase([{"provider": "antigravity", "message": "Hết lượt tới 9h", "resets_at": resets,
                                "detected_at": now.isoformat(), "last_failure_at": now.isoformat()}]),
                statuses=_statuses(antigravity=True, claude_code_cli=True, codex_cli=True),
            )
        antigravity = orchestrator_runtime.readiness_index(readiness)["antigravity"]
        self.assertFalse(antigravity["ready"])
        self.assertEqual(antigravity["blocked_reason"], "usage_limit")
        self.assertEqual(antigravity["resets_at"], resets)
        self.assertEqual(antigravity["quota_state"], "active")

    def test_writer_order_prefers_the_api_key_then_the_subscriptions(self) -> None:
        with patch(
            "youtube_monitor.orchestrator_runtime.settings.openai_config", return_value=("sk-test", "gpt-4o-mini")
        ), patch(
            "youtube_monitor.orchestrator_runtime.settings.anthropic_config", return_value=("", "claude-opus-5")
        ):
            readiness = orchestrator_runtime.runtime_readiness(
                statuses=_statuses(antigravity=True, claude_code_cli=True, codex_cli=False),
            )
        self.assertEqual(
            orchestrator_runtime.writer_order(readiness),
            ["openai_gpt", "claude_code_cli", "antigravity"],
        )

    def test_the_gate_reports_why_a_blocked_candidate_cannot_run(self) -> None:
        readiness = orchestrator_runtime.runtime_readiness(
            statuses=_statuses(antigravity=False, claude_code_cli=True, codex_cli=False),
        )
        gated = orchestrator_runtime.gate(readiness, ["antigravity", "claude_code_cli"])
        self.assertEqual(gated["ready"], ["claude_code_cli"])
        self.assertEqual(gated["blocked"][0]["runtime"], "antigravity")
        self.assertIn("antigravity", orchestrator_runtime.blocked_summary(gated["blocked"]))


class TheModelListEachStepOffersTests(unittest.TestCase):
    """What the step selectors show has to match what the router will do."""

    def test_a_model_out_of_quota_is_offered_as_unavailable_with_the_reason(self) -> None:
        """Signed in is not the same as able to run, and the old list asked
        only whether the CLI was signed in."""
        limits = _FakeDatabase([{"provider": "codex_cli", "message": "Hết lượt tới 27/09", "resets_at": "",
                                 "last_failure_at": datetime.now(timezone.utc).isoformat()}])
        with patch(
            "youtube_monitor.orchestrator_runtime.settings.openai_config", return_value=("", "gpt-4o-mini")
        ), patch(
            "youtube_monitor.orchestrator_runtime.settings.anthropic_config", return_value=("", "claude-opus-5")
        ):
            rows = orchestrator_runtime.text_providers(
                limits, statuses=_statuses(codex_cli=True, claude_code_cli=True, antigravity=True),
            )

        by_key = {row["provider"]: row for row in rows}
        self.assertFalse(by_key["codex_cli"]["available"])
        self.assertEqual(by_key["codex_cli"]["blocked_reason"], "usage_limit")
        self.assertIn("Hết lượt", by_key["codex_cli"]["detail"])
        self.assertTrue(by_key["claude_code_cli"]["available"])

    def test_chat_only_agents_are_not_offered_as_writers(self) -> None:
        """They cannot be called like an API, so listing them would put a
        choice in the box that fails the moment it is picked."""
        rows = orchestrator_runtime.text_providers(statuses=_statuses(codex_cli=True))

        self.assertNotIn("chatgpt_app_mcp", {row["provider"] for row in rows})
        self.assertNotIn("claude_chat_mcp", {row["provider"] for row in rows})


class _FakeDatabase:
    def __init__(self, limits: list[dict[str, object]]):
        self._limits = limits

    def list_active_usage_limits(self) -> list[dict[str, object]]:
        return self._limits


class RunReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = Path(__file__).parent / "_tmp_orchestrator_report"
        self._dir.mkdir(exist_ok=True)
        self.database = Database(self._dir / "report.db")

    def tearDown(self) -> None:
        for item in self._dir.glob("report.db*"):
            item.unlink(missing_ok=True)
        self._dir.rmdir()

    def test_a_step_is_stored_with_the_runtime_that_ran_it(self) -> None:
        self.database.record_orchestrator_step(
            stage="storyboard",
            step="Kế hoạch dựng",
            status="success",
            runtime="antigravity",
            why="Được gán làm executor",
            input_summary="12 cảnh",
            output_ref="edit plan 7",
            attempts=[{"runtime": "antigravity", "status": "success"}],
        )
        steps = self.database.list_orchestrator_steps()
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["runtime"], "antigravity")
        self.assertFalse(steps[0]["fallback_used"])
        self.assertEqual(steps[0]["attempts"][0]["status"], "success")

    def test_steps_read_back_oldest_first_for_a_run_report(self) -> None:
        for index in range(3):
            self.database.record_orchestrator_step(
                stage="script", step=f"Bước {index}", status="success", runtime="codex_cli"
            )
        steps = self.database.list_orchestrator_steps()
        self.assertEqual([step["step"] for step in steps], ["Bước 0", "Bước 1", "Bước 2"])

    def test_a_run_that_used_a_template_is_not_reported_as_ai_complete(self) -> None:
        steps = [
            {"step": "Kịch bản", "runtime": "antigravity", "status": "success", "fallback_used": False},
            {"step": "Kế hoạch dựng", "runtime": "app_template", "status": "fallback", "fallback_used": True},
        ]
        summary = orchestrator_runtime.report_summary(steps)
        self.assertFalse(summary["ai_complete"])
        self.assertEqual(summary["fallback_steps"], 1)

    def test_report_markdown_has_one_row_per_step_and_marks_the_fallback(self) -> None:
        markdown = orchestrator_runtime.report_markdown([
            {"step": "Viết kịch bản", "runtime": "antigravity", "why": "GPT chưa có key",
             "input_summary": "brief", "output_ref": "script 4", "status": "success", "fallback_used": False},
            {"step": "Kế hoạch dựng", "runtime": "app_template", "why": "AI thất bại",
             "input_summary": "12 cảnh", "output_ref": "", "status": "fallback", "fallback_used": True},
        ])
        rows = markdown.splitlines()
        self.assertEqual(len(rows), 4)
        self.assertIn("| không |", rows[2])
        self.assertIn("| có |", rows[3])

    def test_an_empty_report_says_no_ai_step_was_recorded(self) -> None:
        self.assertIn("Chưa ghi nhận bước AI nào", orchestrator_runtime.report_markdown([]))


class RoutingTests(unittest.TestCase):
    """How the app picks a runtime once readiness is known."""

    def setUp(self) -> None:
        from youtube_monitor import main

        self.main = main

    def _assignment(self, executor: str, fallback: str) -> dict[str, object]:
        return {
            "mode": "fallback",
            "executor": executor,
            "allowed_agents": ["astra", "claude", "chatgpt_app"],
            "fallback_agents": [fallback],
            "reviewer": "auto",
        }

    def test_a_runtime_that_cannot_run_now_is_tried_after_one_that_can(self) -> None:
        with patch(
            "youtube_monitor.main.settings.agent_assignment",
            return_value=self._assignment("astra", "claude"),
        ), patch(
            "youtube_monitor.main.antigravity_cli_status", return_value={"installed": True, "logged_in": False}
        ), patch(
            "youtube_monitor.main.claude_code_cli_status", return_value={"installed": True, "logged_in": True}
        ), patch(
            "youtube_monitor.main.codex_cli_status", return_value={"installed": False, "logged_in": False}
        ), patch(
            "youtube_monitor.main.call_claude_code_cli_json", return_value={"ok": True}
        ) as claude, patch("youtube_monitor.main.call_antigravity_json") as antigravity:
            result = self.main._call_orchestrator_json(
                "system", "user", {"type": "object"}, stage="storyboard", step="Kiểm thử định tuyến"
            )

        self.assertEqual(result, {"ok": True})
        claude.assert_called_once()
        antigravity.assert_not_called()
        step = self.main.database.list_orchestrator_steps()[-1]
        self.assertEqual(step["step"], "Kiểm thử định tuyến")
        self.assertEqual(step["runtime"], "claude_code_cli")
        self.assertEqual(step["status"], "success")

    def test_when_every_runtime_fails_the_error_names_the_missing_sign_in(self) -> None:
        from youtube_monitor.llm_client import LlmError

        with patch(
            "youtube_monitor.main.settings.agent_assignment",
            return_value=self._assignment("astra", "claude"),
        ), patch(
            "youtube_monitor.main.codex_cli_status", return_value={"installed": True, "logged_in": False, "detail": "Codex CLI chưa đăng nhập"}
        ), patch(
            "youtube_monitor.main.claude_code_cli_status", return_value={"installed": False, "logged_in": False}
        ), patch(
            "youtube_monitor.main.antigravity_cli_status", return_value={"installed": False, "logged_in": False}
        ), patch(
            "youtube_monitor.main.call_claude_code_cli_json", side_effect=LlmError("claude hỏng")
        ), patch(
            "youtube_monitor.main.call_codex_json", side_effect=LlmError("codex hỏng")
        ), patch(
            "youtube_monitor.main.call_antigravity_json", side_effect=LlmError("antigravity hỏng")
        ):
            with self.assertRaises(LlmError) as raised:
                self.main._call_orchestrator_json(
                    "system", "user", {"type": "object"}, stage="storyboard", step="Kiểm thử thất bại"
                )

        self.assertIn("Chưa sẵn sàng", str(raised.exception))
        self.assertIn("chưa đăng nhập", str(raised.exception))
        step = self.main.database.list_orchestrator_steps()[-1]
        self.assertEqual(step["status"], "failed")
        self.assertEqual(len(step["attempts"]), 2)


class ReportEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient
        from youtube_monitor.main import app

        cls._client_cm = TestClient(app)
        cls.client = cls._client_cm.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)

    def test_runtime_endpoint_lists_who_can_execute_and_who_cannot(self) -> None:
        response = self.client.get("/api/orchestrator/runtimes")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["agent_runtimes"]["astra"], "codex_cli")
        ids = {item["id"] for item in body["runtimes"]}
        self.assertIn("openai_gpt", ids)
        self.assertIn("antigravity", ids)
        for item in body["runtimes"]:
            if not item["ready"]:
                self.assertTrue(item["detail"], f"{item['id']} bị chặn mà không nói lý do")

    def test_the_step_model_list_carries_auto_local_and_every_text_ai(self) -> None:
        response = self.client.get("/api/analysis-providers")
        self.assertEqual(response.status_code, 200)
        rows = {item["provider"]: item for item in response.json()}

        self.assertIn("auto", rows)
        self.assertIn("local_metadata", rows)
        for runtime in ("codex_cli", "claude_code_cli", "antigravity", "openai_gpt"):
            self.assertIn(runtime, rows, f"{runtime} phải có trong danh sách model")
        for item in rows.values():
            if not item["available"]:
                self.assertTrue(item["detail"], f"{item['provider']} bị khoá mà không nói lý do")

    def test_report_endpoint_rejects_an_unknown_project(self) -> None:
        response = self.client.get("/api/projects/99999999/orchestrator-report")
        self.assertEqual(response.status_code, 404)

    def test_report_endpoint_returns_a_table_for_a_real_project(self) -> None:
        from youtube_monitor.main import database

        project = database.create_idea_project("Kiểm thử nhật ký điều phối", title="Audit")
        project_id = int(project["id"])
        database.record_orchestrator_step(
            project_id=project_id, stage="script", step="Viết kịch bản",
            status="success", runtime="antigravity", why="GPT chưa có key", output_ref="script 1",
        )
        response = self.client.get(f"/api/projects/{project_id}/orchestrator-report")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["summary"]["steps"], 1)
        self.assertTrue(body["summary"]["ai_complete"])
        self.assertIn("antigravity", body["markdown"])


if __name__ == "__main__":
    unittest.main()
