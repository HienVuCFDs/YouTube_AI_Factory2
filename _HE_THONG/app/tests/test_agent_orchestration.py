"""The orchestrating agent: one ID boundary, its own runtime, a loop that observes.

What these pin down:
- agent names (astra, claude) reach runtimes (codex_cli, claude_code_cli) through
  orchestrator_runtime only - the five-role pipeline died "unavailable" without it;
- the structured workers stay tool-less; only the new agent runtimes get the
  app's MCP server, and nothing else;
- in agent-run mode the MCP server logs calls, refuses an identical retry of a
  failed call while the project is unchanged, refuses spending unless allowed,
  and enforces the round's tool budget;
- the loop replaces a failed brain, feeds every round what came before, decides
  completion from the project, and stops when two rounds change nothing.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from youtube_monitor import (
    agent_loop,
    agent_runtime,
    ai_desktop_mcp,
    claude_agent_bridge,
    codex_agent_bridge,
    llm_analyzer,
    main,
    orchestrator_runtime,
    reference_analyzer,
    settings,
    usage_limits,
    writer,
)
from youtube_monitor.agent_runtime import AgentRun, AgentRunError
from youtube_monitor.agent_system import AgentTaskWorker
from youtube_monitor.database import Database


# ---------------------------------------------------------------- ID boundary
class AgentNamesReachTheirRuntimeTests(unittest.TestCase):
    def test_astra_is_available_when_codex_is_signed_in(self) -> None:
        with mock.patch.object(main.database, "get_provider_usage_limit", return_value=None), \
                mock.patch.object(main, "codex_cli_status", return_value={"logged_in": True}):
            self.assertTrue(main._agent_runtime_available("astra"))

    def test_claude_is_available_when_claude_code_is_signed_in(self) -> None:
        with mock.patch.object(main.database, "get_provider_usage_limit", return_value=None), \
                mock.patch.object(main, "claude_code_cli_status", return_value={"logged_in": True}):
            self.assertTrue(main._agent_runtime_available("claude"))

    def test_a_quota_recorded_under_the_runtime_blocks_the_agent_name(self) -> None:
        """Quota rows are written as codex_cli; the worker asks about astra."""
        looked_up: list[str] = []

        def limit(provider: str):
            looked_up.append(provider)
            now = datetime.now(timezone.utc).isoformat()
            return ({"resets_at": "2999-01-01T00:00:00+00:00", "cleared_at": None,
                     "detected_at": now, "last_failure_at": now} if provider == "codex_cli" else None)

        with mock.patch.object(main.database, "get_provider_usage_limit", side_effect=limit), \
                mock.patch.object(main, "codex_cli_status", return_value={"logged_in": True}):
            self.assertFalse(main._agent_runtime_available("astra"))
        self.assertEqual(looked_up, ["codex_cli"])

    def test_a_specific_agent_call_goes_to_the_runtime_behind_the_name(self) -> None:
        with mock.patch.object(main, "call_claude_code_cli_json", return_value={"ok": True}) as claude, \
                mock.patch.object(main, "call_codex_json") as codex:
            self.assertEqual(main._call_specific_agent_json("claude", "s", "u", {}), {"ok": True})
        claude.assert_called_once()
        codex.assert_not_called()


# ------------------------------------------------------- self-verified tasks
class TheOrchestratorTaskIsJudgedByTheProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.directory.name) / "agents.db")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _run(self, output: dict) -> tuple[dict, mock.Mock]:
        reviewer = mock.Mock(return_value={"approved": True, "score": 10})
        worker = AgentTaskWorker(
            self.database,
            assignment_resolver=lambda stage: {"mode": "auto", "executor": "claude", "allowed_agents": ["claude", "astra"]},
            availability_resolver=lambda agent: True,
        )
        worker.configure(executor=lambda task, agent: output, reviewer=reviewer)
        task = self.database.create_agent_task(None, "orchestrator", "orchestrate.goal", {"goal": "x"}, max_attempts=2)
        worker._process(str(task["id"]))
        return self.database.get_agent_task(str(task["id"])), reviewer

    def test_a_verified_goal_completes_without_a_second_ai_reading_the_report(self) -> None:
        task, reviewer = self._run({"verified": True, "status": "completed"})
        self.assertEqual(task["status"], "completed")
        reviewer.assert_not_called()

    def test_an_unverified_goal_fails_and_is_not_rerun_unchanged(self) -> None:
        task, reviewer = self._run({"verified": False, "status": "blocked", "reason": "thiếu kịch bản"})
        self.assertEqual(task["status"], "failed")
        self.assertIn("thiếu kịch bản", task["error"])
        self.assertEqual(task["attempt_count"], 1)
        reviewer.assert_not_called()


# ------------------------------------------------------- MCP agent-run mode
class McpAgentRunModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.log = Path(self.directory.name) / "run.jsonl"
        self.patches = [
            mock.patch.object(ai_desktop_mcp, "AGENT_RUN_LOG", str(self.log)),
            mock.patch.object(ai_desktop_mcp, "AGENT_ROUND", 1),
            mock.patch.object(ai_desktop_mcp, "AGENT_PROJECT_ID", 7),
            mock.patch.object(ai_desktop_mcp, "AGENT_ALLOW_SPEND", False),
            mock.patch.object(ai_desktop_mcp, "AGENT_TOOL_BUDGET", 5),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in self.patches:
            patcher.stop()
        self.directory.cleanup()

    def _entries(self) -> list[dict]:
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def test_it_does_not_pose_as_a_chat_app(self) -> None:
        with mock.patch.object(ai_desktop_mcp.urllib.request, "urlopen") as urlopen:
            ai_desktop_mcp._report_chat_contact()
        urlopen.assert_not_called()

    def test_the_chat_queue_tools_are_hidden(self) -> None:
        response = ai_desktop_mcp._handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertNotIn("youtube_factory_get_next_task", names)
        self.assertIn("youtube_factory_run_step", names)

    def test_a_failed_call_is_not_repeated_while_the_project_is_unchanged(self) -> None:
        with mock.patch.object(ai_desktop_mcp, "_call_tool", side_effect=RuntimeError("HTTP 409: Chưa làm xong bước trước: Viết kịch bản")) as call, \
                mock.patch.object(ai_desktop_mcp, "_state_fingerprint", return_value="same"):
            with self.assertRaises(RuntimeError):
                ai_desktop_mcp._agent_call("youtube_factory_run_step", {"project_id": 7, "step": "shots"})
            with self.assertRaisesRegex(ValueError, "y hệt"):
                ai_desktop_mcp._agent_call("youtube_factory_run_step", {"project_id": 7, "step": "shots"})
        self.assertEqual(call.call_count, 1)
        self.assertEqual(self._entries()[-1]["refused"], "identical_retry")

    def test_the_same_call_is_allowed_again_once_the_project_changed(self) -> None:
        fingerprints = iter(["before", "after"])
        with mock.patch.object(ai_desktop_mcp, "_call_tool", side_effect=[RuntimeError("HTTP 409"), {"content": [{"type": "text", "text": "{}"}], "isError": False}]) as call, \
                mock.patch.object(ai_desktop_mcp, "_state_fingerprint", side_effect=lambda pid: next(fingerprints)):
            with self.assertRaises(RuntimeError):
                ai_desktop_mcp._agent_call("youtube_factory_run_step", {"project_id": 7, "step": "shots"})
            ai_desktop_mcp._agent_call("youtube_factory_run_step", {"project_id": 7, "step": "shots"})
        self.assertEqual(call.call_count, 2)
        self.assertTrue(self._entries()[-1]["ok"])

    def test_a_spending_step_is_refused_unless_the_run_allows_it(self) -> None:
        with mock.patch.object(ai_desktop_mcp, "_call_tool") as call:
            with self.assertRaisesRegex(ValueError, "tiêu lượt"):
                ai_desktop_mcp._agent_call("youtube_factory_run_step", {"project_id": 7, "step": "script"})
            with self.assertRaisesRegex(ValueError, "tiêu lượt"):
                ai_desktop_mcp._agent_call("youtube_factory_generate_image", {"project_id": 7, "segment_id": 1, "prompt": "x", "confirmed": True})
        call.assert_not_called()
        with mock.patch.object(ai_desktop_mcp, "AGENT_ALLOW_SPEND", True), \
                mock.patch.object(ai_desktop_mcp, "_call_tool", return_value={"content": [], "isError": False}) as allowed:
            ai_desktop_mcp._agent_call("youtube_factory_run_step", {"project_id": 7, "step": "script"})
        allowed.assert_called_once()

    def test_publishing_is_never_done_by_an_agent_run(self) -> None:
        with mock.patch.object(ai_desktop_mcp, "AGENT_ALLOW_SPEND", True), \
                mock.patch.object(ai_desktop_mcp, "_call_tool") as call:
            with self.assertRaisesRegex(ValueError, "đăng video"):
                ai_desktop_mcp._agent_call(
                    "youtube_factory_run_step", {"project_id": 7, "step": "publish", "options": {"confirmed_publish": True}},
                )
        call.assert_not_called()

    def test_the_round_budget_is_enforced(self) -> None:
        with mock.patch.object(ai_desktop_mcp, "_call_tool", return_value={"content": [], "isError": False}):
            for _ in range(5):
                ai_desktop_mcp._agent_call("youtube_factory_list_steps", {"project_id": 7})
            with self.assertRaisesRegex(ValueError, "hết 5 lần"):
                ai_desktop_mcp._agent_call("youtube_factory_list_steps", {"project_id": 7})

    def test_the_run_stays_on_its_project(self) -> None:
        with mock.patch.object(ai_desktop_mcp, "_call_tool") as call:
            with self.assertRaisesRegex(ValueError, "dự án 7"):
                ai_desktop_mcp._agent_call("youtube_factory_list_steps", {"project_id": 8})
        call.assert_not_called()


class McpServerTellsClientsToUseToolsTests(unittest.TestCase):
    def test_initialize_carries_instructions(self) -> None:
        with mock.patch.object(ai_desktop_mcp, "_report_chat_contact"):
            response = ai_desktop_mcp._handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertIn("youtube_factory_run_step", response["result"]["instructions"])
        self.assertIn("KHÔNG bằng cách bấm giao diện", response["result"]["instructions"])


# ------------------------------------------------------------ agent runtimes
class AgentRuntimeCommandTests(unittest.TestCase):
    ENV = agent_runtime.mcp_environment(
        run_log=Path("C:/tmp/run.jsonl"), round_number=2, project_id=61,
        allow_spend=True, tool_budget=30, factory_url="http://127.0.0.1:8787",
    )

    def test_codex_gets_the_app_server_and_nothing_of_the_user_config(self) -> None:
        command = codex_agent_bridge.build_command(
            "codex.exe", workdir=Path("C:/tmp/w"), schema_path=Path("C:/tmp/s.json"),
            output_path=Path("C:/tmp/o.json"), mcp_env=self.ENV,
        )
        self.assertIn("--ignore-user-config", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        server = next(item for item in command if item.startswith("mcp_servers.youtube_ai_factory="))
        self.assertIn("YOUTUBE_AGENT_RUN_LOG='C:", server)
        self.assertIn("YOUTUBE_AGENT_ROUND='2'", server)
        self.assertIn("tool_timeout_sec=", server)
        self.assertIn('model_reasoning_effort="high"', command)

    def test_claude_gets_only_the_app_tools(self) -> None:
        command = claude_agent_bridge.build_command(
            "claude.exe", mcp_config_path=Path("C:/tmp/mcp.json"), instructions="x", max_turns=40,
        )
        self.assertIn("--restricted", command)
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", command)
        self.assertEqual(command[command.index("--allowedTools") + 1], "mcp__youtube_ai_factory")
        self.assertEqual(command[command.index("--permission-mode") + 1], "dontAsk")
        self.assertNotIn("--dangerously-skip-permissions", command)

    def test_the_structured_workers_are_untouched(self) -> None:
        """call_claude_code_json still disables every tool."""
        source = Path(main.__file__).with_name("claude_code_bridge.py").read_text(encoding="utf-8")
        self.assertIn('"--tools", "WebFetch" if allow_web else ("Read" if image_path else "")', source)

    def test_claude_output_with_a_structured_report_is_read(self) -> None:
        stdout = json.dumps({
            "type": "result", "subtype": "success", "is_error": False, "num_turns": 9,
            "structured_output": {"status": "done", "summary": "ok", "completed_steps": ["script"],
                                  "attempts": [], "blocked_reason": ""},
        })
        report, meta = claude_agent_bridge.parse_output(stdout)
        self.assertEqual(report["status"], "done")
        self.assertEqual(meta["num_turns"], 9)

    def test_a_claude_run_that_hit_its_turn_limit_still_returns_what_it_did(self) -> None:
        stdout = json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True, "result": ""})
        process = mock.Mock(returncode=1, stdout=stdout, stderr="")
        with mock.patch.object(claude_agent_bridge, "claude_code_cli_status", return_value={"logged_in": True, "path": "claude.exe"}), \
                mock.patch.object(claude_agent_bridge.operations, "run_cancellable", return_value=process):
            run = claude_agent_bridge.run("goal", self.ENV)
        self.assertEqual(run.report["status"], "partial")

    def test_a_brain_that_fails_outright_raises_an_agent_run_error(self) -> None:
        process = mock.Mock(returncode=1, stdout="", stderr="You've hit your usage limit. Try again later.")
        with mock.patch.object(codex_agent_bridge, "codex_cli_status", return_value={"logged_in": True, "path": "codex.exe"}), \
                mock.patch.object(codex_agent_bridge.operations, "run_cancellable", return_value=process):
            with self.assertRaises(AgentRunError) as caught:
                codex_agent_bridge.run("goal", self.ENV)
        self.assertEqual(caught.exception.runtime, "codex_cli")


# ------------------------------------------------------------------ the loop
def _report(status: str = "done", completed: tuple[str, ...] = ()) -> dict:
    return {"status": status, "summary": status, "completed_steps": list(completed), "attempts": [], "blocked_reason": ""}


class OrchestrationLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.log = Path(self.directory.name) / "run.jsonl"
        self.done: set[str] = set()
        self.prompts: list[str] = []

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _verify(self, spec, claimed):
        missing = [name for name in spec.target_steps if name not in self.done]
        return {"passed": not missing, "missing": missing,
                "false_claims": sorted(set(claimed) - self.done), "evidence": {}}

    def _run(self, runners, spec=None, available=lambda runtime: True):
        spec = spec or agent_loop.GoalSpec(project_id=1, goal="chia cảnh", target_steps=("shots",), max_rounds=3,
                                          runtimes=("codex_cli", "claude_code_cli"))
        return agent_loop.run_goal(
            spec,
            runners=runners,
            read_state=lambda pid: {"done": sorted(self.done)},
            verify=self._verify,
            mcp_env=lambda number: {"YOUTUBE_AGENT_ROUND": str(number)},
            log_path=self.log,
            available=available,
        )

    def test_a_brain_that_fails_is_replaced_and_the_goal_still_gets_done(self) -> None:
        def codex(prompt, env):
            raise AgentRunError("codex_cli", "You've hit your usage limit")

        def claude(prompt, env):
            self.prompts.append(prompt)
            self.done.update({"script", "shots"})
            return AgentRun(runtime="claude_code_cli", report=_report("done", ("script", "shots")))

        result = self._run({"codex_cli": codex, "claude_code_cli": claude})
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["verified"])
        self.assertEqual([item["runtime"] for item in result["rounds"]], ["codex_cli", "claude_code_cli"])
        self.assertIn("codex_cli", self.prompts[0])  # the next brain is told which one failed and why

    def test_a_done_report_is_not_taken_on_trust(self) -> None:
        calls = {"n": 0}

        def claude(prompt, env):
            calls["n"] += 1
            self.prompts.append(prompt)
            if calls["n"] == 1:
                self.done.add("script")  # progress, but not the goal - while claiming it
                return AgentRun(runtime="claude_code_cli", report=_report("done", ("script", "shots")))
            self.done.add("shots")
            return AgentRun(runtime="claude_code_cli", report=_report("done", ("shots",)))

        result = self._run({"claude_code_cli": claude})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["rounds"][0]["verification"]["false_claims"], ["shots"])
        self.assertIn("thực tế CHƯA: ['shots']", self.prompts[1])

    def test_every_round_sees_what_earlier_rounds_tried(self) -> None:
        def claude(prompt, env):
            self.prompts.append(prompt)
            with self.log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"round": int(env["YOUTUBE_AGENT_ROUND"]), "tool": "youtube_factory_run_step",
                                         "arguments": {"project_id": 1, "step": "script", "options": {"provider": "antigravity"}},
                                         "ok": False, "error": "Individual quota reached"}) + "\n")
            if len(self.prompts) == 2:
                self.done.add("shots")
            else:
                self.done.add("script")
            return AgentRun(runtime="claude_code_cli", report=_report("partial"))

        self._run({"claude_code_cli": claude})
        self.assertIn("antigravity", self.prompts[1])
        self.assertIn("Individual quota reached", self.prompts[1])

    def test_two_rounds_that_change_nothing_end_the_run(self) -> None:
        runner = mock.Mock(return_value=AgentRun(runtime="claude_code_cli", report=_report("blocked")))
        result = self._run({"claude_code_cli": runner}, spec=agent_loop.GoalSpec(
            project_id=1, goal="x", target_steps=("render",), max_rounds=6, runtimes=("claude_code_cli",)))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(runner.call_count, 2)

    def test_a_goal_already_reached_calls_no_agent(self) -> None:
        self.done.add("shots")
        runner = mock.Mock()
        result = self._run({"claude_code_cli": runner})
        self.assertEqual(result["status"], "completed")
        runner.assert_not_called()

    def test_with_no_brain_left_the_run_is_blocked_not_looping(self) -> None:
        result = self._run({"claude_code_cli": mock.Mock()}, available=lambda runtime: False)
        self.assertEqual(result["status"], "blocked")

    def test_a_goal_must_name_real_steps(self) -> None:
        with self.assertRaises(ValueError):
            agent_loop.GoalSpec(project_id=1, goal="x", target_steps=("make_it_good",))


# ------------------------------------------------------------ wiring in main
class OrchestrateAgentModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = main.database.create_idea_project("Vì sao lá cây màu xanh")

    def test_agent_mode_needs_steps_to_verify_against(self) -> None:
        with self.assertRaises(main.HTTPException) as caught:
            main.orchestrate_project(int(self.project["id"]), main.OrchestrateRequest(intent="làm video", mode="agent"))
        self.assertEqual(caught.exception.status_code, 400)

    def test_agent_mode_queues_an_orchestrator_task_on_the_existing_worker(self) -> None:
        # Never written to the shared test database: a worker started by
        # another test's TestClient would pick it up and run a real agent.
        def fake_create(project_id, role, task_type, payload, **kwargs):
            return {"id": "agt_test", "project_id": project_id, "role": role, "task_type": task_type,
                    "input": payload, **kwargs}

        with mock.patch.object(main.database, "create_agent_task", side_effect=fake_create) as create, \
                mock.patch.object(main.agent_task_worker, "enqueue") as enqueue:
            response = main.orchestrate_project(
                int(self.project["id"]),
                main.OrchestrateRequest(intent="chia cảnh", mode="agent", target_steps=["shots"]),
            )
        self.assertEqual(response["status"], "queued")
        self.assertEqual(create.call_args.args[1], "orchestrator")
        self.assertEqual(response["task"]["input"]["target_steps"], ["shots"])
        self.assertFalse(response["task"]["input"]["allow_spend"])
        self.assertFalse(response["task"]["input"]["allow_overwrite"])
        self.assertEqual(response["task"]["max_attempts"], 1)
        enqueue.assert_called_once_with("agt_test")

    def test_the_directing_ai_can_be_chosen(self) -> None:
        def fake_create(project_id, role, task_type, payload, **kwargs):
            return {"id": "agt_test", "role": role, "input": payload, **kwargs}

        with mock.patch.object(main.database, "create_agent_task", side_effect=fake_create), \
                mock.patch.object(main.agent_task_worker, "enqueue"):
            chosen = main.orchestrate_project(
                int(self.project["id"]),
                main.OrchestrateRequest(intent="dựng timeline", mode="agent", target_steps=["timeline"],
                                        runtime="claude_code_cli"),
            )
            with self.assertRaises(main.HTTPException) as caught:
                main.orchestrate_project(
                    int(self.project["id"]),
                    main.OrchestrateRequest(intent="dựng timeline", mode="agent", target_steps=["timeline"],
                                            runtime="antigravity"),
                )
        self.assertEqual(chosen["task"]["assigned_agent"], "claude")
        self.assertEqual(chosen["task"]["input"]["runtime"], "claude_code_cli")
        self.assertEqual(caught.exception.status_code, 400)  # no agent runtime for Antigravity

    def test_verification_reads_the_project_and_catches_false_claims(self) -> None:
        check = main._verify_goal(int(self.project["id"]), ["shots"], claimed=["script", "shots"])
        self.assertFalse(check["passed"])
        self.assertEqual(check["missing"], ["shots"])
        self.assertEqual(check["false_claims"], ["script", "shots"])

    def test_the_worker_picked_runtime_directs_first_then_policy_order(self) -> None:
        assignment = {"executor": "astra", "fallback_agents": ["claude"], "allowed_agents": ["astra", "claude", "antigravity"]}
        with mock.patch.object(main.settings, "agent_assignment", return_value=assignment):
            self.assertEqual(main._agent_runtime_order("claude"), ("claude_code_cli", "codex_cli"))
            self.assertEqual(main._agent_runtime_order("astra"), ("codex_cli", "claude_code_cli"))


# ---------------------------------------------------------- one mapping only
class OneMappingEverywhereTests(unittest.TestCase):
    """"The AI runs, but another module says unavailable" came from each module
    keeping its own idea of which runtime Astra is."""

    def test_every_alias_resolves_through_the_single_table(self) -> None:
        for name, runtime in {
            "astra": "codex_cli", "codex": "codex_cli", "codex_cli": "codex_cli",
            "claude": "claude_code_cli", "claude_code": "claude_code_cli", "claude_cli": "claude_code_cli",
            "claude_code_cli": "claude_code_cli", "antigravity": "antigravity", "antigravity_cli": "antigravity",
            "openai_gpt": "openai_gpt", "gflow_cli": "gflow_cli",
        }.items():
            self.assertEqual(orchestrator_runtime.runtime_id(name), runtime, name)
        for name, runtime in orchestrator_runtime.AGENT_RUNTIMES.items():
            self.assertEqual(settings.runtime_for(name), runtime)

    def test_every_provider_resolver_accepts_an_agent_name(self) -> None:
        self.assertEqual(writer.resolve_writer("claude").provider, "claude_code_cli")
        self.assertEqual(writer.resolve_writer("astra").provider, "codex_cli")
        self.assertEqual(llm_analyzer.resolve_analyzer("astra").provider, "codex_cli")
        self.assertEqual(main._resolve_auto_text_provider("claude"), "claude_code_cli")
        with mock.patch.object(reference_analyzer, "call_codex_json", return_value={"ok": True}) as codex:
            reference_analyzer._call("astra", "s", "u")
        codex.assert_called_once()


# ------------------------------------------------------- stale quota recovery
class StaleQuotaRecoveryTests(unittest.TestCase):
    NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)

    def _state(self, **row) -> dict:
        return usage_limits.limit_state(row, now=self.NOW)

    def test_the_states_tell_current_from_cooldown_from_history(self) -> None:
        just_failed = (self.NOW - timedelta(minutes=5)).isoformat()
        long_ago = (self.NOW - timedelta(hours=7)).isoformat()
        future = (self.NOW + timedelta(hours=111)).isoformat()
        self.assertEqual(self._state(last_failure_at=just_failed, resets_at=future)["state"], "active")
        self.assertTrue(self._state(last_failure_at=just_failed, resets_at=future)["blocking"])
        # The stated reset is days away, but the outage is old: try it again.
        self.assertEqual(self._state(last_failure_at=long_ago, resets_at=future)["state"], "probe_due")
        self.assertEqual(self._state(last_failure_at=just_failed,
                                     resets_at=(self.NOW - timedelta(minutes=1)).isoformat())["state"], "reset_passed")
        self.assertEqual(self._state(last_failure_at=just_failed, cleared_at=just_failed)["state"], "recovered")
        self.assertTrue(self._state(resets_at="")["blocking"])  # no time of failure: cannot age it

    def test_a_runtime_out_of_quota_is_ready_again_once_a_call_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "quota.db")
            usage_limits.set_sink(database.record_provider_usage_limit, database.clear_provider_usage_limit)
            try:
                usage_limits.note_failure("antigravity", "error: Individual quota reached. Resets in 111h")
                statuses = {key: (lambda: {"installed": True, "logged_in": True})
                            for key in ("antigravity", "claude_code_cli", "codex_cli")}
                before = orchestrator_runtime.readiness_index(
                    orchestrator_runtime.runtime_readiness(database, statuses=statuses))["antigravity"]
                usage_limits.note_success("antigravity")
                after = orchestrator_runtime.readiness_index(
                    orchestrator_runtime.runtime_readiness(database, statuses=statuses))["antigravity"]
                with mock.patch.object(main, "database", database), \
                        mock.patch.object(main, "antigravity_cli_status", return_value={"logged_in": True}):
                    worker_view = main._agent_runtime_available("antigravity")
            finally:
                usage_limits.set_sink(main.database.record_provider_usage_limit, main.database.clear_provider_usage_limit)
        self.assertFalse(before["ready"])
        self.assertEqual(before["quota_state"], "active")
        self.assertTrue(after["ready"])
        self.assertTrue(worker_view)

    def test_a_stale_outage_nobody_retried_does_not_block_forever(self) -> None:
        """Antigravity: reset stated for 30/09, working again on 28/09."""
        old = (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat()
        row = {"provider": "antigravity", "message": "Individual quota reached", "detected_at": old,
               "last_failure_at": old, "resets_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
               "cleared_at": None}
        database = mock.Mock(list_active_usage_limits=mock.Mock(return_value=[row]))
        statuses = {key: (lambda: {"installed": True, "logged_in": True})
                    for key in ("antigravity", "claude_code_cli", "codex_cli")}
        state = orchestrator_runtime.readiness_index(
            orchestrator_runtime.runtime_readiness(database, statuses=statuses))["antigravity"]
        self.assertTrue(state["ready"])
        self.assertEqual(state["quota_state"], "probe_due")
        self.assertIn("Từng hết hạn mức", state["detail"])
        with mock.patch.object(main.database, "get_provider_usage_limit", return_value=row), \
                mock.patch.object(main, "antigravity_cli_status", return_value={"logged_in": True}):
            self.assertTrue(main._agent_runtime_available("antigravity"))

    def test_the_banner_lists_only_what_blocks_now(self) -> None:
        now = datetime.now(timezone.utc)
        rows = [
            {"provider": "codex_cli", "message": "hết", "detected_at": now.isoformat(),
             "last_failure_at": now.isoformat(), "resets_at": (now + timedelta(hours=2)).isoformat()},
            {"provider": "antigravity", "message": "hết", "detected_at": (now - timedelta(days=1)).isoformat(),
             "last_failure_at": (now - timedelta(days=1)).isoformat(), "resets_at": None},
        ]
        with mock.patch.object(main.database, "list_active_usage_limits", return_value=rows):
            body = main.list_usage_limits()
        self.assertEqual([item["provider"] for item in body["limits"]], ["codex_cli"])
        self.assertEqual([(item["provider"], item["state"]) for item in body["history"]], [("antigravity", "probe_due")])


# ------------------------------------------------- five-role pipeline details
class PipelineWorkerTechnicalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.directory.name) / "pipeline.db")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_a_chat_app_is_never_an_executor_or_reviewer_for_the_worker(self) -> None:
        self.assertFalse(main._agent_runtime_available("chatgpt_app"))
        self.assertFalse(main._agent_runtime_available("claude_chat"))

    def test_a_task_assigned_to_a_chat_app_is_left_for_it(self) -> None:
        executor = mock.Mock()
        worker = AgentTaskWorker(self.database, assignment_resolver=lambda stage: {"executor": "astra"},
                                 availability_resolver=lambda agent: True)
        worker.configure(executor=executor, reviewer=mock.Mock())
        task = self.database.create_agent_task(None, "research", "x", {}, assigned_agent="chatgpt_app")
        worker._process(str(task["id"]))
        executor.assert_not_called()
        self.assertEqual(self.database.get_agent_task(str(task["id"]))["status"], "queued")

    def test_a_retry_is_told_why_the_last_attempt_was_turned_back(self) -> None:
        seen: list[str] = []

        def executor(task, agent):
            seen.append(str(task.get("previous_error") or ""))
            return {"plan": "x"}

        reviews = iter([{"approved": False, "score": 6, "note": "kind='video' trái với lý do 'hình tĩnh'"},
                        {"approved": True, "score": 9}])
        worker = AgentTaskWorker(
            self.database,
            assignment_resolver=lambda stage: {"mode": "auto", "executor": "astra", "allowed_agents": ["astra", "claude"]},
            availability_resolver=lambda agent: True,
        )
        worker.configure(executor=executor, reviewer=lambda task, agent, output: next(reviews))
        task = self.database.create_agent_task(None, "media", "pipeline.media", {}, max_attempts=2)
        worker._process(str(task["id"]))
        worker._process(str(task["id"]))
        self.assertEqual(seen[0], "")
        self.assertIn("hình tĩnh", seen[1])
        self.assertEqual(self.database.get_agent_task(str(task["id"]))["status"], "completed")

    def test_the_executor_passes_the_reason_into_the_model_call(self) -> None:
        project = main.database.create_idea_project("Vì sao nước biển mặn")
        task = {"role": "research", "project_id": project["id"], "input": {"goal": "x"},
                "previous_error": "thiếu nguồn cho con số 3,5%"}
        with mock.patch.object(main, "_call_specific_agent_json", return_value={}) as call:
            main._execute_agent_task(task, "astra")
        self.assertIn("LẦN THỬ TRƯỚC BỊ NGHIỆM THU TRẢ VỀ VÌ", call.call_args.args[2])
        self.assertIn("3,5%", call.call_args.args[2])


# ------------------------------------------------------- overwrite guard
class OverwriteGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(ai_desktop_mcp, "AGENT_RUN_LOG", str(Path(self.directory.name) / "run.jsonl")),
            mock.patch.object(ai_desktop_mcp, "AGENT_PROJECT_ID", 7),
            mock.patch.object(ai_desktop_mcp, "AGENT_ALLOW_SPEND", True),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in self.patches:
            patcher.stop()
        self.directory.cleanup()

    def test_force_is_refused_unless_the_run_allows_overwriting(self) -> None:
        with mock.patch.object(ai_desktop_mcp, "_call_tool") as call:
            with self.assertRaisesRegex(ValueError, "ghi đè"):
                ai_desktop_mcp._agent_call("youtube_factory_run_step", {"project_id": 7, "step": "shots", "options": {"force": True}})
            with self.assertRaisesRegex(ValueError, "ghi đè"):
                ai_desktop_mcp._agent_call("youtube_factory_build_timeline", {"project_id": 7, "force": True})
        call.assert_not_called()
        with mock.patch.object(ai_desktop_mcp, "AGENT_ALLOW_OVERWRITE", True), \
                mock.patch.object(ai_desktop_mcp, "_call_tool", return_value={"content": [], "isError": False}) as allowed:
            ai_desktop_mcp._agent_call("youtube_factory_build_timeline", {"project_id": 7, "force": True})
        allowed.assert_called_once()

    def test_ordinary_steps_pass_untouched(self) -> None:
        with mock.patch.object(ai_desktop_mcp, "_call_tool", return_value={"content": [], "isError": False}) as call:
            ai_desktop_mcp._agent_call("youtube_factory_run_step", {"project_id": 7, "step": "timeline"})
        call.assert_called_once()


# -------------------------------------------------------------- diagnostics
class RunDiagnosticsTests(unittest.TestCase):
    def test_a_run_records_its_decisions_and_one_closing_line(self) -> None:
        events: list[dict] = []
        done: set[str] = set()

        def claude(prompt, env):
            done.add("shots")
            return AgentRun(runtime="claude_code_cli", report=_report("done", ("shots",)),
                            meta={"model": "claude-sonnet-5"})

        with tempfile.TemporaryDirectory() as directory:
            result = agent_loop.run_goal(
                agent_loop.GoalSpec(project_id=1, goal="x", target_steps=("shots",),
                                    runtimes=("codex_cli", "claude_code_cli")),
                runners={"codex_cli": mock.Mock(), "claude_code_cli": claude},
                read_state=lambda pid: {"done": sorted(done)},
                verify=lambda spec, claimed: {"passed": "shots" in done, "missing": [] if "shots" in done else ["shots"]},
                mcp_env=lambda number: {},
                log_path=Path(directory) / "run.jsonl",
                available=lambda runtime: runtime != "codex_cli",
                record=events.append,
            )
        round_one = result["rounds"][0]
        self.assertEqual(round_one["model"], "claude-sonnet-5")
        self.assertEqual(round_one["decision"]["chosen"], "claude_code_cli")
        self.assertIn("codex_cli", round_one["decision"]["skipped"])
        self.assertEqual(events[-1]["event"], "run.finished")
        self.assertTrue(events[-1]["verified"])

    def test_credentials_never_reach_the_run_log(self) -> None:
        secret = "sk-proj-" + "a" * 40
        self.assertNotIn(secret, agent_runtime.redact(f"Authorization failed for key {secret}"))
        self.assertNotIn("abcdefghij1234567890", agent_runtime.redact("Bearer abcdefghij1234567890"))
        self.assertIn("Thiếu OPENAI_API_KEY", agent_runtime.redact("Thiếu OPENAI_API_KEY. Hãy thêm vào .env"))
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "run.jsonl"
            with mock.patch.object(ai_desktop_mcp, "AGENT_RUN_LOG", str(log)):
                ai_desktop_mcp._append_agent_log({"tool": "t", "ok": False, "error": f"HTTP 401 token={secret}"})
            self.assertNotIn(secret, log.read_text(encoding="utf-8"))

    def test_the_codex_header_gives_the_model_that_answered(self) -> None:
        meta = codex_agent_bridge.header_meta("workdir: C:\\x\nmodel: gpt-6-astra\nreasoning effort: high\n")
        self.assertEqual(meta, {"model": "gpt-6-astra", "reasoning_effort": "high"})

    def test_the_structured_codex_worker_is_untouched(self) -> None:
        source = Path(main.__file__).with_name("codex_bridge.py").read_text(encoding="utf-8")
        self.assertIn('"--ignore-user-config",\n            "--sandbox",\n            "read-only",', source)
        self.assertNotIn("mcp_servers", source)


if __name__ == "__main__":
    unittest.main()
