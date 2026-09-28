from __future__ import annotations

import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from youtube_monitor import settings


class SaveIntegrationValuesTests(unittest.TestCase):
    def test_rejects_disallowed_keys_with_readable_vietnamese_message(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            with self.assertRaises(ValueError) as ctx:
                settings.save_integration_values({"NOT_ALLOWED_KEY": "x"})
        message = str(ctx.exception)
        self.assertIn("Không được phép thay đổi", message)
        self.assertIn("NOT_ALLOWED_KEY", message)

    def test_rejects_multiline_values_with_readable_vietnamese_message(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            with self.assertRaises(ValueError) as ctx:
                settings.save_integration_values({"OPENAI_API_KEY": "line1\nline2"})
        self.assertIn("không được chứa xuống dòng", str(ctx.exception))

    def test_repeated_saves_do_not_duplicate_the_header_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("EXISTING_KEY=keep\n", encoding="utf-8")
            with mock.patch.object(settings, "ENV_PATH", env_path):
                with mock.patch.dict(os.environ, {}, clear=False):
                    settings.save_integration_values({"OPENAI_MODEL": "gpt-4o-mini"})
                    settings.save_integration_values({"ANTHROPIC_MODEL": "claude-opus-5"})
            content = env_path.read_text(encoding="utf-8")
            self.assertEqual(
                content.count("# Local integrations (managed from dashboard)"), 1
            )
            self.assertIn("OPENAI_MODEL=gpt-4o-mini", content)
            self.assertIn("ANTHROPIC_MODEL=claude-opus-5", content)
            self.assertIn("EXISTING_KEY=keep", content)


class AgentAssignmentTests(unittest.TestCase):
    def test_malformed_assignment_json_uses_defaults(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"AI_STAGE_ASSIGNMENTS_JSON": "not-json", "AI_ORCHESTRATOR_PROVIDER": "codex_cli"},
            clear=False,
        ):
            assignments = settings.agent_assignments()
        self.assertEqual(assignments["orchestration"]["executor"], "astra")
        self.assertEqual(assignments["orchestration"]["fallback_agents"], ["claude"])
        self.assertEqual(assignments["video_generation"]["mode"], "auto")

    def test_valid_stage_assignment_is_normalized(self) -> None:
        """A saved choice written under the old CLI names is still honoured.

        The agents used to be named after the CLI behind them. Treating those
        names as malformed silently narrowed a stage to whichever id happened
        to survive, so a stage the user had pointed at three AIs would refuse
        with "every assigned AI failed" while two of them were idle.
        """
        configured = {
            "video_generation": {
                "mode": "fallback",
                "executor": "claude_code_cli",
                "allowed_agents": ["claude_code_cli", "codex_cli", "invalid"],
                "fallback_agents": ["codex_cli", "codex_cli", "claude_code_cli"],
                "reviewer": "codex_cli",
            }
        }
        with mock.patch.dict(
            os.environ,
            {
                "AI_STAGE_ASSIGNMENTS_JSON": json.dumps(configured),
                "AI_ORCHESTRATOR_PROVIDER": "codex_cli",
            },
            clear=False,
        ):
            assignment = settings.agent_assignment("video_generation")
        self.assertEqual(assignment["mode"], "fallback")
        self.assertEqual(assignment["executor"], "claude")
        self.assertEqual(assignment["allowed_agents"], ["claude", "astra"])
        self.assertEqual(assignment["fallback_agents"], ["astra"])
        self.assertEqual(assignment["reviewer"], "astra")

    def test_a_name_nothing_recognises_is_still_dropped(self) -> None:
        configured = {"storyboard": {"executor": "gpt5_web", "allowed_agents": ["nope"]}}
        with mock.patch.dict(
            os.environ, {"AI_STAGE_ASSIGNMENTS_JSON": json.dumps(configured)}, clear=False,
        ):
            assignment = settings.agent_assignment("storyboard")
        self.assertEqual(assignment["executor"], "astra")
        self.assertEqual(assignment["allowed_agents"], list(settings.AGENT_IDS))

    def test_orchestrator_defaults_are_astra_with_claude_fallback(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            # Defaults only: the machine's .env would otherwise answer.
            os.environ.pop("AI_ORCHESTRATOR_PROVIDER", None)
            os.environ.pop("AI_ORCHESTRATOR_FALLBACK_PROVIDER", None)
            self.assertEqual(settings.orchestrator_provider(), "astra")
            self.assertEqual(settings.orchestrator_fallback_provider(), "claude")


if __name__ == "__main__":
    unittest.main()
