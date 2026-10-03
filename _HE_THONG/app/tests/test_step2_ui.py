"""Bước 2 · Kế hoạch on screen: one step for the person, drawn from what the server says.

Research and insights are not steps of their own; the page has no prompt box
and no rule of its own about what is feasible, missing or relevant. It reads
GET …/steps and GET …/plan and sends POST …/steps/plan - the contract the
backend already had. How it behaves is run for real in
tests/step2_plan_ui.test.cjs; this file holds the page's shape and runs that.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.ui_source import studio_markup, studio_ui

_START = "  // ---- Bước 2 · Kế hoạch ----"
_END = "  // ---- hết Bước 2 · Kế hoạch ----"


def _step2(markup: str) -> str:
    start = markup.index('<div id="studioStep2"')
    return markup[start:markup.index('<div id="studioStep3"')]


def _block() -> str:
    ui = studio_ui()
    return ui[ui.index(_START):ui.index(_END)]


def test_step_two_is_the_plan_and_one_step() -> None:
    markup = studio_markup()
    assert '<button class="studio-step-tab" data-studio-tab="2" onclick="setStudioStep(2)"><span>02</span><strong>Kế hoạch</strong></button>' in markup
    step = _step2(markup)
    assert "<h3>Kế hoạch</h3>" in step
    assert 'id="studioPlanHead"' in step and 'id="studioPlanBody"' in step
    # Research and insight are inside the step, never tabs or steps beside it.
    tabs = re.findall(r"data-studio-tab=\"\d\"[^>]*><span>\d\d</span><strong>([^<]+)</strong>", markup)
    assert tabs[:3] == ["Phân tích", "Kế hoạch", "Kịch bản"]
    for word in ("Nghiên cứu", "Insight", "Research"):
        assert word not in " ".join(tabs), word


def test_there_is_no_prompt_box_and_no_hand_it_to_ai_button() -> None:
    step = _step2(studio_markup())
    block = _block()
    for gone in ("<textarea", 'type="text"', "Giao cho AI", "Giao việc cho AI", "prompt"):
        assert gone not in step, gone
    for gone in ("<textarea", "Giao cho AI", "Giao việc cho AI", "placeholder="):
        assert gone not in block, gone
    # The only inputs are the two settings a person may change.
    assert re.findall(r"<(?:input|select) id=\"(\w+)\"", block) == ["studioPlanProfile", "studioPlanSeconds"]


def test_the_page_talks_to_the_existing_step_contract_only() -> None:
    block = _block()
    called = set(re.findall(r"api\(`(/api/[^`]+)`", block))
    assert called == {"/api/projects/${projectId}/steps", "/api/projects/${projectId}/plan", "/api/projects/${projectId}/steps/plan"}
    # Every action is one of the options that step already takes.
    assert "runStudioPlan({mode: 'auto'})" in block
    assert "runStudioPlan({primary_angle_id: String(angleId)})" in block
    assert "runStudioPlan({mode, settings})" in block
    for invented in ("mode: 'full'", "mode: 'reason'"):
        assert invented not in block, invented
    assert len(re.findall(r"/api/", block)) == 6, "three calls, and the three lines of the comment that name them"


def test_what_is_running_is_read_from_the_server() -> None:
    block = _block()
    watch = block[block.index("function watchStudioPlan("):block.index("function stopStudioPlanWatch(")]
    assert "studioPlanRow(projectId)" in watch
    assert "row.state === 'running'" in watch
    assert "document.hidden ? STUDIO_PLAN_HIDDEN_POLL_MS : STUDIO_PLAN_POLL_MS" in watch
    assert "setInterval" not in block
    for kept_in_the_browser in ("localStorage", "sessionStorage"):
        assert kept_in_the_browser not in block, kept_in_the_browser
    run = block[block.index("async function runStudioPlan("):block.index("function announceStudioPlan(")]
    assert "if (plan.running) return;" in run, "a second click starts nothing"
    # Reopening a project asks the server, and stops at step two when a plan exists or is being made.
    ui = studio_ui()
    assert "if (await loadStudioPlan(existingProject.id)) nextStep = 2;" in ui
    assert "if (next === 2) void loadStudioPlan(state.studioProjectId);" in ui


def test_the_status_shown_is_the_servers_and_only_completed_finishes_the_step() -> None:
    block = _block()
    status = block[block.index("function studioPlanStatus("):block.index("function startStudioPlan(")]
    assert "plan.row?.outcome?.status" in status
    for label in ("Chưa lập kế hoạch", "Đang lập kế hoạch…", "Sẵn sàng", "Cần bạn quyết định", "Chưa thể thực hiện", "Kế hoạch đã cũ"):
        assert label in block, label
    sync = block[block.index("function syncStudioPlanStep("):block.index("function studioPlanDecisions(")]
    assert "next.disabled = status !== 'completed';" in sync
    assert "tab.classList.toggle('done', status === 'completed' && Number(state.studioStep) > 2);" in sync
    ui = studio_ui()
    assert "tab.classList.toggle('done', value < next && (value !== 2 || studioPlanReady()));" in ui
    assert 'id="studioToScriptButton" class="btn primary" type="button" disabled' in _step2(studio_markup())


def test_the_script_step_has_one_door_and_it_is_guarded() -> None:
    """Bước 3 opens only on a ready plan, whichever way it is reached."""
    ui = studio_ui()
    gate = ui[ui.index("function studioPlanReady() {"):ui.index("function syncStudioScriptGate() {")]
    for condition in ("Number(plan.projectId) === Number(state.studioProjectId)", "!plan.running", "plan.row?.state !== 'running'",
                      "plan.row?.outcome?.completed === true"):
        assert condition in gate, condition
    step = ui[ui.index("function setStudioStep(step) {"):ui.index("  // Audio hangs off a timeline row")]
    assert "if (next === 3 && !studioPlanReady()) {" in step
    assert "setMessage(STUDIO_SCRIPT_GATE_MESSAGE, 'error');" in step
    assert "const STUDIO_SCRIPT_GATE_MESSAGE = 'Bạn cần hoàn thành Kế hoạch trước khi viết kịch bản.';" in ui
    # One function shows a step and remembers it; nothing else does, so nothing goes round the guard.
    assert ui.count("state.studioStep = ") == 1
    assert len(re.findall(r"querySelectorAll\('\[data-studio-step\]'\)", ui)) == 1
    assert not re.findall(r"\$\('studioStep\d'\)\.hidden", ui)
    # Every control that leads to the script step calls it: the tab, "continue" and "back".
    markup = studio_markup()
    assert markup.count('onclick="setStudioStep(3)"') == 3
    # Reopening a project or a saved session lands on the plan instead, without an error.
    assert "if (nextStep >= 3 && !studioPlanReady()) nextStep = 2;" in ui
    assert "(savedStep !== 3 || studioPlanReady())) setStudioStep(savedStep);" in ui


def test_a_re_plan_does_not_read_as_research_run_again() -> None:
    block = _block()
    assert "const STUDIO_PLAN_KEPT_STAGES = ['research', 'insights', 'angles'];" in block
    run = block[block.index("async function runStudioPlan("):block.index("function announceStudioPlan(")]
    assert "plan.runKind = options.primary_angle_id || options.mode === 'replan' ? 'replan' : 'full';" in run
    running = block[block.index("function studioPlanRunning(plan) {"):block.index("function studioPlanReason(")]
    assert "Nghiên cứu và insight hiện tại được giữ nguyên; app chỉ lập lại phần kế hoạch." in running
    assert "' · giữ nguyên'" in running
    # A stage is "done" only when the page saw the server on it - never because of where it sits in the list.
    assert "(plan.seen || []).includes(item.key) ? 'past'" in running
    assert "index < now" not in block


def test_nothing_about_feasibility_assets_or_relevance_is_decided_in_the_page() -> None:
    block = _block()
    resources = block[block.index("function studioPlanResources("):block.index("function studioPlanResearch(")]
    for group in ("resources.available", "resources.app_generates", "resources.missing", "resources.proposed"):
        assert group in resources, group
    # The model's proposals are not read here at all: the server has already sorted them.
    for decided_by_the_server in ("ai_proposed_assets", "verdict", "missing_assets", "relevance", "low_relevance", "needs_attention'"):
        assert decided_by_the_server not in block, decided_by_the_server
    decisions = block[block.index("function studioPlanDecisions("):block.index("function studioPlanSourceLine(")]
    assert "outcome.decisions" in decisions and "item.options" in decisions


def test_technical_words_stay_out_of_what_is_shown() -> None:
    block = _block()
    research = block[block.index("function studioPlanResearch("):block.index("function renderStudioPlan(")]
    assert "<summary>Chi tiết nghiên cứu</summary>" in research
    assert "<summary>Nâng cao: dữ liệu kế hoạch (JSON)</summary>" in research
    # Evidence ids, confidence and collector names are never written into the page.
    for hidden in ("evidence_ids", "confidence", "item.collector}", "ResearchReport", "InsightReport"):
        assert hidden not in block.replace("// ", ""), hidden
    errors = block[block.index("function studioPlanErrorText("):block.index("function studioPlanStatus(")]
    for case in ("status === 409", "status === 400", "status === 502", "studioPlainText(text)"):
        assert case in errors, case
    assert "Đang có một lần lập kế hoạch khác." in errors


def test_step_one_still_continues_to_the_plan() -> None:
    markup = studio_markup()
    assert 'onclick="setStudioStep(2)">Tiếp tục Kế hoạch →</button>' in markup
    # The old analysis view keeps its place to write to, out of sight.
    assert '<div id="studioAnalysisResult" class="studio-result" hidden></div>' in _step2(markup)


@pytest.mark.parametrize("script", ["step2_plan_ui.test.cjs", "studio_navigation.test.cjs"])
def test_the_screen_behaves_as_described(script: str) -> None:
    """The code itself, run against a scripted server and a scripted page (node:test)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node không có trên máy chạy test")
    result = subprocess.run([node, "--test", str(Path(__file__).with_name(script))], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, (result.stdout + result.stderr)[-3000:]
