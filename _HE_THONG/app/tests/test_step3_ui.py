"""Bước 3 · Kịch bản on screen: one way to write the script, drawn from what the server says.

"Viết kịch bản" is one POST to …/steps/script - run_project_step("script"),
the Script Engine. The page draws the ScriptDocument GET …/script returns,
with its state, whether production may go on from it (`current`) and why not,
in the server's own words. The old writer is not called on the way, and the
editor has nothing the plan decides. How the page behaves is run for real in
tests/step3_script_ui.test.cjs; this file holds the page's shape, runs that,
and pins the server's side of the contract the page reads.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from tests.script_fixtures import PLAN, Scripted, planned_project
from tests.ui_source import studio_markup, studio_ui
from youtube_monitor import main, script_engine

_START = "  // ---- Bước 3 · Kịch bản ----"
_END = "  // ---- hết Bước 3 · Kịch bản ----"
_STATIC = Path(__file__).resolve().parent.parent / "youtube_monitor" / "static"
_NODE_TEST = Path(__file__).with_name("step3_script_ui.test.cjs")

GO = script_engine.CONTINUE_MESSAGES
NO_PLAN = "Bạn cần hoàn thành Kế hoạch trước khi viết kịch bản."
BUSY = "Bước Viết kịch bản đang chạy cho dự án này. Chờ lượt đó xong rồi hãy chạy lại."
FORBIDDEN = "Mọi khán giả đều thích video ngắn về vũ trụ hơn video dài."


def _boom(*args, **kwargs):
    raise AssertionError("must not be called")


def _block() -> str:
    ui = studio_ui()
    return ui[ui.index(_START):ui.index(_END)]


def _code(text: str) -> str:
    """The code without its comments, for questions about what it does."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(line for line in text.split("\n") if not line.strip().startswith("//"))


def _step3(markup: str) -> str:
    start = markup.index('<div id="studioStep3"')
    return markup[start:markup.index('<div id="studioStep4"')]


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

def test_the_write_button_is_one_call_to_the_step() -> None:
    block = _block()
    handler = block[block.index("async function writeStudioScript("):block.index("async function finishStudioScriptRun(")]
    assert re.findall(r"api\(`([^`]+)`", handler) == ["/api/projects/${projectId}/steps/script"]
    assert "method: 'POST', body: JSON.stringify({options})" in handler
    # Only what the step takes; the plan decides angle, length, structure, CTA and format.
    assert "const options = {create_standalone_short: createStandaloneShort, short_seconds: shortSeconds};" in handler
    assert "if (provider !== 'auto') options.provider = provider;" in handler
    for gone in ("/writer", "script/draft", "/project`", "/workflow", "short_direction", "target_duration", "creative_direction"):
        assert gone not in handler, gone


def test_the_step_talks_to_the_existing_contract_only() -> None:
    called = set(re.findall(r"api\(`(/api/[^`]+)`", _block()))
    assert called == {
        "/api/projects/${projectId}/steps",
        "/api/projects/${projectId}/script",
        "/api/projects/${projectId}/steps/script",
        "/api/scripts/${view.body.id}",
        "/api/scripts/${view.body.id}/approve",
        "/api/projects/${state.studioProjectId}/script/review",
        "/api/projects/${projectId}/script/chat",
    }


def test_nothing_of_the_old_writer_is_in_step_three() -> None:
    code = _code(_block())
    for gone in ("/writer", "script/draft", "scene_blueprints", "visual_prompt", "folklore", "director-draft", "writer_content",
                 "state.studioWriter", "new_titles", "creative_direction", "hashtags", "force"):
        assert gone not in code, gone
    # The studio's own files no longer reach the writer at all; what still does is the library's
    # separate "AI Writer" tool and the publishing suggestions, outside Bước 3.
    for name in ("project-detail.js", "studio-lanes.js"):
        assert "/writer`" not in (_STATIC / name).read_text(encoding="utf-8"), name
    reaching = {name for name in ("core.js", "library.js", "publish.js") if "/writer`" in (_STATIC / name).read_text(encoding="utf-8")}
    assert reaching == {"library.js", "publish.js"}
    ui = studio_ui()
    for caller in ("async function batchWriter(", "async function generateWriterContent(", "async function generatePublicationAiSuggestions("):
        assert caller in ui, caller


def test_the_step_has_no_input_the_plan_decides() -> None:
    step = _step3(studio_markup())
    for gone in ('id="studioTargetDurationSeconds"', 'id="studioScriptInstructionInput"', 'id="studioFolkloreResearchEnabled"',
                 'id="studioWriteButton"', "Thời lượng video mục tiêu", "Yêu cầu cho kịch bản"):
        assert gone not in step, gone
    for kept in ('id="studioScriptHead"', 'id="studioScriptResult"', 'id="studioCreateStandaloneShort"', 'id="studioShortWorkflowNote"',
                 'id="studioWriterProviderSelect"', 'id="studioChatBox"', "<h3>Kịch bản</h3>"):
        assert kept in step, kept
    # The AI choice is an advanced option, not the step.
    advanced = step[step.index('<details id="studioScriptAdvanced"'):]
    assert advanced.index('id="studioWriterProviderSelect"') < advanced.index("</details>")
    editor = _code(_block())
    editor = editor[editor.index("function studioScriptEditor("):editor.index("function renderStudioScript(")]
    assert re.findall(r'id="(studioScript\w+Input)"', editor) == [
        "studioScriptTitleInput", "studioScriptHookInput", "studioScriptMainInput", "studioScriptCtaInput"]
    block = _block()
    payload = block[block.index("function studioScriptPayload("):block.index("async function saveStudioScript(")]
    assert re.findall(r"^\s+(\w+): \$\(", payload, flags=re.M) == ["script_title", "hook", "main_content", "cta"]


def test_removed_controls_leave_no_binding_behind() -> None:
    ui = studio_ui()
    assert "$('studioWriteButton')" not in ui
    assert "$('studioScriptInstructionInput').addEventListener" not in ui
    assert "$('studioChatButton').addEventListener('click', chatStudioScript);" in ui


def test_what_is_running_and_what_holds_is_read_from_the_server() -> None:
    block = _block()
    watch = block[block.index("function watchStudioScript("):block.index("function stopStudioScriptWatch(")]
    assert "studioScriptRow(projectId)" in watch
    assert "row.state === 'running'" in watch
    assert "document.hidden ? STUDIO_SCRIPT_HIDDEN_POLL_MS : STUDIO_SCRIPT_POLL_MS" in watch
    for kept_in_the_browser in ("setInterval", "localStorage", "sessionStorage"):
        assert kept_in_the_browser not in block, kept_in_the_browser
    assert "if (view.requesting || studioScriptStatus(view) === 'running') return;" in block
    status = block[block.index("function studioScriptStatus("):block.index("function studioScriptActions(")]
    for read in ("view.row?.state === 'running'", "body?.generation?.status === 'running'", "body.write_blocked_reason",
                 "body.state === 'invalid'", "body.stale_kind === 'mismatch'", "body.current === true"):
        assert read in status, read
    # The server's sentences are shown, never written again here.
    code = _code(block)
    for said in (*GO.values(), NO_PLAN, BUSY, *script_engine._PLAN_REFUSALS.values()):
        assert said not in code, said
    # Reopening a project, or the step, asks the server.
    ui = studio_ui()
    assert "if (await loadStudioScript(existingProject.id)) nextStep = 3;" in ui
    assert "if (next === 3) void loadStudioScript(state.studioProjectId);" in ui
    assert "resetStudioScript();" in ui


def test_the_short_lane_reads_the_shorts_provenance() -> None:
    ui = studio_ui()
    assert "api(`/api/projects/${projectId}/short-script`)" in ui
    held = ui[ui.index("function shortLaneHeld("):ui.index("function stopShortVoiceSequence(")]
    assert "short.current === false ? String(short.blocked_reason || '') : ''" in held


def test_the_node_scripts_speak_the_servers_words() -> None:
    """The scripted server in the .cjs test answers with the backend's real sentences."""
    text = _NODE_TEST.read_text(encoding="utf-8")
    for said in (GO[script_engine.MISSING], GO[script_engine.STALE], GO[script_engine.INVALID], GO["mismatch"], GO["running"],
                 GO["short_stale"], NO_PLAN, BUSY, *script_engine._PLAN_REFUSALS.values()):
        assert said in text, said
    assert [key for key, _ in script_engine.STAGES] == ["read_plan", "write", "check", "finalize"]
    for _, label in script_engine.STAGES:
        assert label in text, label


def test_the_screen_behaves_as_described() -> None:
    """The code itself, run against a scripted server and a scripted page (node:test)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node không có trên máy chạy test")
    result = subprocess.run([node, "--test", str(_NODE_TEST)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, (result.stdout + result.stderr)[-3000:]


# ---------------------------------------------------------------------------
# The server's side of what the page reads
# ---------------------------------------------------------------------------

class ScriptStepContractTests(unittest.TestCase):
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

    def _script(self, project_id: int) -> dict:
        response = self.client.get(f"/api/projects/{project_id}/script")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _row(self, project_id: int) -> dict:
        return next(row for row in self.client.get(f"/api/projects/{project_id}/steps").json()["steps"] if row["key"] == "script")

    def _write(self, project_id: int) -> dict:
        """What the button sends: POST …/steps/script, and nothing of the old writer on the way."""
        with mock.patch.object(main, "generate_video_writer_content", _boom), mock.patch.object(main, "resolve_writer", _boom), \
                mock.patch.object(main, "build_script_draft", _boom):
            response = self.client.post(f"/api/projects/{project_id}/steps/script",
                                        json={"options": {"create_standalone_short": False, "short_seconds": 45}})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _bump_plan(self, project_id: int) -> dict:
        latest = self.database.get_latest_project_plan(project_id)
        return self.database.create_project_plan(
            project_id, status="completed", research_report_id=latest["research_report_id"],
            analysis_created_at=latest["analysis_created_at"], engine_version="plan-phase3", plan=latest["plan"],
            feasibility={"status": "ok", "checks": []}, insight_report_id=latest["insight_report_id"])

    def test_before_any_script_the_page_is_told_it_may_write_one(self) -> None:
        project_id = planned_project(self.database)
        body = self._script(project_id)
        self.assertEqual((body["state"], body["current"], body["blocked_reason"], body["write_blocked_reason"]),
                         ("missing", False, GO[script_engine.MISSING], ""))
        self.assertEqual(body["current_plan"]["status"], "completed")

    def test_a_plan_that_is_not_ready_refuses_writing_in_the_words_the_page_shows(self) -> None:
        for status, said in (("needs_user_decision", script_engine._PLAN_REFUSALS["needs_user_decision"]),
                             ("blocked", script_engine._PLAN_REFUSALS["blocked"])):
            with self.subTest(status=status):
                project_id = planned_project(self.database, status=status)
                body = self._script(project_id)
                self.assertEqual((body["write_blocked_reason"], body["current_plan"]["status"], body["current"]), (said, status, False))
                response = self.client.post(f"/api/projects/{project_id}/steps/script", json={"options": {}})
                self.assertEqual((response.status_code, response.json()["detail"]), (409, said), "word for word, as the page shows it")
        project_id = planned_project(self.database, with_plan=False)
        self.assertEqual(self._script(project_id)["write_blocked_reason"], NO_PLAN)
        self.assertEqual(self.model.calls, [], "no model is asked")

    def test_the_button_writes_a_scriptdocument_through_the_step(self) -> None:
        project_id = planned_project(self.database)
        ran = self._write(project_id)
        self.assertEqual(ran["step"], "script")
        self.assertEqual([call["stage"] for call in self.model.calls], ["script"])
        body = self._script(project_id)
        self.assertEqual((body["state"], body["current"], body["blocked_reason"], body["write_blocked_reason"]), ("completed", True, "", ""))
        self.assertEqual(body["engine_version"], script_engine.ENGINE_VERSION)
        document = body["document"]
        self.assertEqual([item["plan_section_id"] for item in document["sections"]], ["s1", "s2", "s3"], "in the plan's order")
        for part in ("hook", "cta"):
            self.assertIn("spoken_lines", document[part])
            self.assertIn("on_screen_text", document[part])
        for section in document["sections"]:
            for key in ("spoken_lines", "on_screen_text", "estimated_seconds", "insight_ids", "evidence_ids"):
                self.assertIn(key, section)
        for storyboard in ("visual_prompt", "camera", "shot", "b_roll", "scene_blueprints"):
            self.assertNotIn(storyboard, json.dumps(document, ensure_ascii=False).lower())
        self.assertEqual((body["plan_id"], body["plan_version"]), (body["current_plan"]["id"], body["current_plan"]["version"]))

    def test_a_script_left_behind_by_a_new_plan_says_so(self) -> None:
        project_id = planned_project(self.database)
        self._write(project_id)
        self._bump_plan(project_id)
        body = self._script(project_id)
        self.assertEqual((body["state"], body["current"], body["blocked_reason"]), ("stale", False, GO[script_engine.STALE]))
        self.assertTrue(body["stale_reasons"])
        self.assertEqual(self._row(project_id)["state"], "stale")

    def test_an_edit_that_breaks_the_plan_is_saved_and_reported_invalid_and_cannot_move_the_plan(self) -> None:
        project_id = planned_project(self.database)
        self._write(project_id)
        before = self._script(project_id)
        response = self.client.patch(f"/api/scripts/{before['id']}", json={
            "main_content": before["main_content"] + "\n" + FORBIDDEN, "plan_id": 999, "plan_version": 99,
            "target_duration_seconds": 5, "primary_angle_id": "ang-9"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], script_engine.INVALID)
        body = self._script(project_id)
        self.assertEqual((body["state"], body["current"], body["blocked_reason"]), ("invalid", False, GO[script_engine.INVALID]))
        self.assertTrue(body["validation_errors"])
        self.assertEqual((body["id"], body["version"], body["plan_id"], body["plan_version"]),
                         (before["id"], before["version"], before["plan_id"], before["plan_version"]), "the plan link is not the editor's")
        self.assertEqual(body["document"]["target_duration_seconds"], before["document"]["target_duration_seconds"])

    def test_a_run_going_on_is_told_to_the_page_and_a_second_one_is_refused_in_words(self) -> None:
        project_id = planned_project(self.database)
        key = (project_id, "script")
        self.assertIsNotNone(main._step_registry.claim(key))
        try:
            body = self._script(project_id)
            self.assertEqual(body["generation"]["status"], "running")
            self.assertEqual((body["current"], body["blocked_reason"]), (False, GO["running"]))
            self.assertEqual(self._row(project_id)["state"], "running")
            response = self.client.post(f"/api/projects/{project_id}/steps/script", json={"options": {}})
            self.assertEqual((response.status_code, response.json()["detail"]), (409, BUSY))
        finally:
            main._step_registry.finish(key, {"status": "success"})
        self.assertEqual(self.model.calls, [])

    def test_the_short_carries_where_it_came_from_and_is_held_once_the_script_moves_on(self) -> None:
        project_id = planned_project(self.database)
        self._write(project_id)
        long_script = self._script(project_id)
        written = self.client.post(f"/api/projects/{project_id}/short-script", json={"seconds": 30, "use_model": False})
        self.assertEqual(written.status_code, 200, written.text)
        short = self.client.get(f"/api/projects/{project_id}/short-script").json()
        self.assertEqual((short["current"], short["blocked_reason"]), (True, ""))
        self.assertEqual((short["provenance"]["source_script_id"], short["provenance"]["plan_version"]),
                         (long_script["id"], long_script["plan_version"]))
        self._write(project_id)   # the long script is written again: the Short above was made from the one before
        short = self.client.get(f"/api/projects/{project_id}/short-script").json()
        self.assertEqual((short["current"], short["blocked_reason"]), (False, GO["short_stale"]))

    def test_a_project_outside_the_plan_workflow_keeps_what_it_had(self) -> None:
        project = self.database.create_idea_project("Kịch bản dán tay", title="Ngoài kế hoạch")
        script = self.database.create_project_script(int(project["id"]), script_title="x", main_content="Một câu.")
        body = self._script(int(project["id"]))
        # The production gate does not apply to it; writing with the engine still needs a plan.
        self.assertEqual((body["id"], body["current"], body["blocked_reason"], body["write_blocked_reason"]),
                         (script["id"], True, "", NO_PLAN))
        self.assertEqual(body["state"], "stale", "as before: written without a plan")
        self.assertIsNone(body["document"])
