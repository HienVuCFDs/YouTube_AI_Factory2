from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from youtube_monitor.agent_system import AGENT_ROLES, AgentPipeline, AgentTaskWorker
from youtube_monitor.database import Database
from youtube_monitor.event_bus import EventBus


class AgentSystemTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.directory.name) / "agent-system.sqlite3")
        self.event_bus = EventBus(self.database)
        self.database.set_event_publisher(self.event_bus.publish)

    def tearDown(self):
        self.directory.cleanup()

    @staticmethod
    def _assignment(_stage):
        return {
            "mode": "auto",
            "executor": "codex_cli",
            "allowed_agents": ["codex_cli", "claude_code_cli"],
            "fallback_agents": ["claude_code_cli"],
            "reviewer": "claude_code_cli",
        }

    def test_worker_uses_distinct_executor_and_reviewer(self):
        worker = AgentTaskWorker(
            self.database,
            assignment_resolver=self._assignment,
            availability_resolver=lambda _agent: True,
        )
        worker.configure(
            executor=lambda task, agent: {"role": task["role"], "executor": agent},
            reviewer=lambda _task, agent, _output: {
                "approved": True,
                "score": 92,
                "note": "ok",
                "reviewer": agent,
            },
        )
        task = self.database.create_agent_task(None, "research", "unit.research", {"goal": "demo"})

        worker._process(str(task["id"]))

        completed = self.database.get_agent_task(str(task["id"]))
        self.assertEqual(completed["status"], "completed")
        execution = completed["output"]["_execution"]
        self.assertEqual(execution["executor"], "codex_cli")
        self.assertEqual(execution["reviewer"], "claude_code_cli")
        self.assertNotEqual(execution["executor"], execution["reviewer"])
        message_types = {
            item["message_type"] for item in self.database.list_agent_messages(task_id=str(task["id"]))
        }
        self.assertTrue({"assignment", "review_request", "review_result"}.issubset(message_types))
        event_types = {item.event_type for item in self.event_bus.history(limit=100)}
        self.assertTrue({"task.started", "review.requested", "review.completed", "task.completed"}.issubset(event_types))

    def test_fixed_executor_still_uses_another_allowed_agent_for_review(self):
        worker = AgentTaskWorker(
            self.database,
            assignment_resolver=lambda _stage: {
                "mode": "fixed",
                "executor": "codex_cli",
                "allowed_agents": ["codex_cli", "claude_code_cli"],
                "fallback_agents": ["claude_code_cli"],
                "reviewer": "auto",
            },
            availability_resolver=lambda _agent: True,
        )
        worker.configure(
            executor=lambda _task, agent: {"executor": agent},
            reviewer=lambda _task, agent, _output: {"approved": True, "reviewer": agent},
        )
        task = self.database.create_agent_task(None, "research", "unit.fixed", {})

        worker._process(str(task["id"]))

        execution = self.database.get_agent_task(str(task["id"]))["output"]["_execution"]
        self.assertEqual(execution["executor"], "codex_cli")
        self.assertEqual(execution["reviewer"], "claude_code_cli")

    def test_reviewer_runtime_error_falls_back_without_rerunning_executor(self):
        executions = []
        worker = AgentTaskWorker(
            self.database,
            assignment_resolver=lambda _stage: {
                "mode": "fixed",
                "executor": "codex_cli",
                "allowed_agents": ["codex_cli", "claude_code_cli", "antigravity"],
                "fallback_agents": ["claude_code_cli", "antigravity"],
                "reviewer": "auto",
            },
            availability_resolver=lambda _agent: True,
        )

        def execute(_task, agent):
            executions.append(agent)
            return {"draft": "ok"}

        def review(_task, agent, _output):
            if agent == "claude_code_cli":
                raise RuntimeError("weekly usage limit")
            return {"approved": True, "score": 88, "note": "accepted"}

        worker.configure(executor=execute, reviewer=review)
        task = self.database.create_agent_task(None, "research", "unit.reviewer-fallback", {})

        worker._process(str(task["id"]))

        completed = self.database.get_agent_task(str(task["id"]))
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["attempt_count"], 1)
        self.assertEqual(executions, ["codex_cli"])
        self.assertEqual(completed["output"]["_execution"]["reviewer"], "antigravity")
        message_types = [
            item["message_type"] for item in self.database.list_agent_messages(task_id=str(task["id"]))
        ]
        self.assertIn("review_error", message_types)
        self.assertIn("review_result", message_types)

    def test_task_waits_for_cross_reviewer_then_resumes_without_rerunning_executor(self):
        available = {"codex_cli"}
        executions = []
        worker = AgentTaskWorker(
            self.database,
            assignment_resolver=lambda _stage: {
                "mode": "fixed",
                "executor": "codex_cli",
                "allowed_agents": ["codex_cli", "claude_code_cli"],
                "fallback_agents": ["claude_code_cli"],
                "reviewer": "auto",
            },
            availability_resolver=lambda agent: agent in available,
        )

        def execute(_task, agent):
            executions.append(agent)
            return {"draft": "kept while waiting"}

        worker.configure(
            executor=execute,
            reviewer=lambda _task, _agent, _output: {"approved": True, "score": 91, "note": "ok"},
        )
        task = self.database.create_agent_task(None, "research", "unit.review-wait", {})

        worker._process(str(task["id"]))
        waiting = self.database.get_agent_task(str(task["id"]))
        self.assertEqual(waiting["status"], "review_required")
        self.assertIsNone(waiting["completed_at"])
        self.assertEqual(executions, ["codex_cli"])

        available.add("claude_code_cli")
        worker._process(str(task["id"]))

        completed = self.database.get_agent_task(str(task["id"]))
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["output"]["draft"], "kept while waiting")
        self.assertEqual(completed["output"]["_execution"]["reviewer"], "claude_code_cli")
        self.assertEqual(executions, ["codex_cli"])

    def test_pipeline_hands_off_all_roles_durably(self):
        worker = AgentTaskWorker(
            self.database,
            assignment_resolver=self._assignment,
            availability_resolver=lambda _agent: True,
        )
        pipeline = AgentPipeline(self.database, worker)
        worker.configure(
            executor=lambda task, agent: {
                "role": task["role"],
                "goal": task["input"].get("goal", ""),
                "pipeline": task["input"].get("pipeline", {}),
                "agent": agent,
            },
            reviewer=lambda _task, _agent, _output: {"approved": True, "score": 90, "note": "ok"},
            completion_handler=pipeline.advance,
        )
        project = self.database.create_idea_project("Lam video giai thich he thong da AI")
        pipeline.start(int(project["id"]), "Lam video giai thich he thong da AI")

        for _ in AGENT_ROLES:
            queued = self.database.list_queued_agent_task_ids()
            self.assertEqual(len(queued), 1)
            worker._process(queued[0])

        tasks = self.database.list_agent_tasks(project_id=int(project["id"]), limit=20)
        self.assertEqual([task["role"] for task in reversed(tasks)], list(AGENT_ROLES))
        self.assertTrue(all(task["status"] == "completed" for task in tasks))
        handoffs = [
            item for item in self.database.list_agent_messages(project_id=int(project["id"]))
            if item["message_type"] == "handoff"
        ]
        self.assertEqual(len(handoffs), len(AGENT_ROLES) - 1)
        correlation_ids = {task["correlation_id"] for task in tasks}
        self.assertEqual(len(correlation_ids), 1)

    def test_failed_cross_review_is_retried_then_failed(self):
        worker = AgentTaskWorker(
            self.database,
            assignment_resolver=self._assignment,
            availability_resolver=lambda _agent: True,
        )
        worker.configure(
            executor=lambda _task, _agent: {"draft": True},
            reviewer=lambda _task, _agent, _output: {"approved": False, "score": 20, "note": "needs work"},
        )
        task = self.database.create_agent_task(
            None,
            "script",
            "unit.review-retry",
            {},
            max_attempts=2,
        )

        worker._process(str(task["id"]))
        self.assertEqual(self.database.get_agent_task(str(task["id"]))["status"], "queued")
        worker._process(str(task["id"]))

        failed = self.database.get_agent_task(str(task["id"]))
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["attempt_count"], 2)
        self.assertIn("needs work", failed["error"])


if __name__ == "__main__":
    unittest.main()
