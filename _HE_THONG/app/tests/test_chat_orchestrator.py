"""GPT Work and Claude Cowork direct a run; a step never calls them mid-way.

The desktop chat apps pull their own work over MCP. Choosing one to direct
used to be written into the `orchestration` stage as well - and that stage is
also who the analysis step calls and waits on, so the step found no AI it was
allowed to run and stopped.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from unittest import mock

from youtube_monitor import main, settings
from youtube_monitor.api import routes_system
from youtube_monitor.database import Database


_KEYS = ("AI_ORCHESTRATOR_PROVIDER", "AI_ORCHESTRATOR_FALLBACK_PROVIDER", "AI_STAGE_ASSIGNMENTS_JSON")


@contextmanager
def _orchestrator_env(**values: str) -> Iterator[None]:
    """Only what the test sets: settings otherwise read the machine's .env."""
    with mock.patch.dict(os.environ, values, clear=False):
        for key in _KEYS:
            if key not in values:
                os.environ.pop(key, None)
        yield


class ChoosingAChatAppToDirectTests(unittest.TestCase):
    def test_every_stage_keeps_an_ai_the_app_can_call(self) -> None:
        with _orchestrator_env(
            AI_ORCHESTRATOR_PROVIDER="chatgpt_app", AI_ORCHESTRATOR_FALLBACK_PROVIDER="claude_chat",
        ):
            assignments = settings.agent_assignments()

        for stage, assignment in assignments.items():
            self.assertNotIn(assignment["executor"], settings.CHAT_AGENT_IDS, stage)
            for agent in assignment["fallback_agents"]:
                self.assertNotIn(agent, settings.CHAT_AGENT_IDS, stage)

    def test_saving_it_leaves_the_analysis_worker_alone(self) -> None:
        saved = {
            "orchestration": {
                "mode": "fallback",
                "executor": "astra",
                "allowed_agents": ["astra", "claude", "antigravity"],
                "fallback_agents": ["claude"],
                "reviewer": "auto",
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("", encoding="utf-8")
            with _orchestrator_env(AI_STAGE_ASSIGNMENTS_JSON=json.dumps(saved)), \
                    mock.patch.object(settings, "ENV_PATH", env_path), \
                    mock.patch.object(routes_system, "_orchestrator_settings", return_value={}):
                routes_system.save_orchestrator_settings(
                    routes_system.OrchestratorSettingsRequest(
                        provider="chatgpt_app", fallback_provider="claude_chat",
                    )
                )
                self.assertEqual(settings.orchestrator_provider(), "chatgpt_app")
                self.assertEqual(settings.orchestrator_fallback_provider(), "claude_chat")
                stage = settings.agent_assignment("orchestration")
            written = env_path.read_text(encoding="utf-8")

        self.assertEqual(stage["executor"], "astra")
        self.assertEqual(stage["fallback_agents"], ["claude"])
        self.assertNotIn("AI_STAGE_ASSIGNMENTS_JSON", written)

    def test_choosing_a_cli_still_moves_the_stage(self) -> None:
        """What it did before, minus a chat fallback the stage could never call."""
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("", encoding="utf-8")
            with _orchestrator_env(), \
                    mock.patch.object(settings, "ENV_PATH", env_path), \
                    mock.patch.object(routes_system, "_orchestrator_settings", return_value={}):
                routes_system.save_orchestrator_settings(
                    routes_system.OrchestratorSettingsRequest(provider="claude", fallback_provider="claude_chat")
                )
                stage = settings.agent_assignment("orchestration")

        self.assertEqual(stage["executor"], "claude")
        self.assertEqual(stage["fallback_agents"], [])
        self.assertEqual(stage["mode"], "auto")


class WhoTakesTheNextRunTests(unittest.TestCase):
    def _directing(self, attached: set[str], **env: str) -> str:
        with _orchestrator_env(**env), mock.patch.object(
            main.chat_agent_presence, "connected", side_effect=lambda agent: agent in attached,
        ):
            return main._directing_chat_agent()

    def test_with_nobody_attached_the_run_waits_for_the_primary(self) -> None:
        chosen = self._directing(
            set(), AI_ORCHESTRATOR_PROVIDER="chatgpt_app", AI_ORCHESTRATOR_FALLBACK_PROVIDER="claude_chat",
        )
        self.assertEqual(chosen, "chatgpt_app")

    def test_only_the_fallback_attached_takes_it(self) -> None:
        chosen = self._directing(
            {"claude_chat"},
            AI_ORCHESTRATOR_PROVIDER="chatgpt_app", AI_ORCHESTRATOR_FALLBACK_PROVIDER="claude_chat",
        )
        self.assertEqual(chosen, "claude_chat")

    def test_both_attached_the_primary_takes_it(self) -> None:
        chosen = self._directing(
            {"chatgpt_app", "claude_chat"},
            AI_ORCHESTRATOR_PROVIDER="chatgpt_app", AI_ORCHESTRATOR_FALLBACK_PROVIDER="claude_chat",
        )
        self.assertEqual(chosen, "chatgpt_app")

    def test_a_cli_primary_keeps_runs_in_the_app(self) -> None:
        """Even with a chat fallback attached: the user chose the CLI to direct."""
        chosen = self._directing(
            {"claude_chat"}, AI_ORCHESTRATOR_PROVIDER="astra", AI_ORCHESTRATOR_FALLBACK_PROVIDER="claude_chat",
        )
        self.assertEqual(chosen, "")

    def test_a_cli_fallback_never_takes_a_chat_primarys_run(self) -> None:
        """A quiet chat app is usually idle, not gone."""
        chosen = self._directing(
            set(), AI_ORCHESTRATOR_PROVIDER="chatgpt_app", AI_ORCHESTRATOR_FALLBACK_PROVIDER="claude",
        )
        self.assertEqual(chosen, "chatgpt_app")


def _project(database: Database) -> int:
    database.upsert_channel(
        {
            "youtube_channel_id": "UC0000000000000000000031",
            "channel_url": "https://www.youtube.com/channel/UC0000000000000000000031",
            "title": "Chat orchestrator channel",
            "uploads_playlist_id": "UU0000000000000000000031",
        }
    )
    database.upsert_video(
        {
            "youtube_video_id": "video-chat-orch-1",
            "youtube_channel_id": "UC0000000000000000000031",
            "video_url": "https://www.youtube.com/watch?v=video-chat-orch-1",
            "title": "Chat orchestrator source",
            "metadata_hash": "hash-chat-orch-1",
            "raw_payload": {},
        }
    )
    return int(database.create_production_project("video-chat-orch-1")["id"])


class ARequestedChangeStaysWithWhoDirectsTests(unittest.TestCase):
    """The hand-off to the next role reads `chat_agent` from the task input.

    The rework task was assigned to ChatGPT but did not carry it there, so the
    first role went to the chat app and every role after it to the CLI.
    """

    def _request_changes(self, directing: str) -> tuple[dict, mock.Mock]:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "chat_orchestrator.db")
            project_id = _project(database)
            approval = database.create_automation_approval(
                project_id, "final_publish", title="Chờ duyệt", payload={},
            )
            with mock.patch.object(main, "database", database), \
                    mock.patch.object(main, "event_bus"), \
                    mock.patch.object(main, "_directing_chat_agent", return_value=directing), \
                    mock.patch.object(main.agent_task_worker, "enqueue") as enqueue:
                result = main.decide_automation_approval(
                    int(approval["id"]),
                    main.AutomationApprovalDecisionRequest(
                        decision="changes_requested", note="Sửa lại cảnh 3 cho đúng nguồn", resume_role="script",
                    ),
                )
        return result["task"], enqueue

    def test_the_rework_is_handed_to_the_chat_app_and_says_so(self) -> None:
        task, enqueue = self._request_changes("claude_chat")

        self.assertEqual(task["assigned_agent"], "claude_chat")
        self.assertEqual(task["input"]["chat_agent"], "claude_chat")
        enqueue.assert_not_called()

    def test_with_a_cli_directing_the_rework_goes_to_the_in_app_worker(self) -> None:
        task, enqueue = self._request_changes("")

        self.assertEqual(task["assigned_agent"], "")
        enqueue.assert_called_once_with(str(task["id"]))


class TheChatIsToldHowToDirectTests(unittest.TestCase):
    def test_the_task_it_pulls_points_at_the_steps_the_buttons_run(self) -> None:
        with mock.patch.object(main.database, "get_production_project", return_value=None), \
                mock.patch.object(main.database, "get_latest_project_script", return_value=None):
            envelope = main._chat_task_envelope({"id": "agt_1", "role": "script", "project_id": 0}, "claude_chat")

        self.assertIn("youtube_factory_list_steps", envelope["how_to_direct"])
        self.assertIn("youtube_factory_run_step", envelope["how_to_direct"])
        self.assertNotIn("ChatGPT", envelope["instruction"])


if __name__ == "__main__":
    unittest.main()
