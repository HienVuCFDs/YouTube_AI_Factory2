"""Bước 1 · Phân tích: the screen is source → Phân tích → result → continue.

Everything on it is the project's real state. The audit of 29/09 found a
"Kế hoạch AI" list with fixed statuses, an "AI đang hoạt động" badge, a render
bar stuck at 12/15, a sample storyboard and a technical log on the main
screen, while the real analysis was shown one step later.
"""

from __future__ import annotations

import re

from tests.ui_source import studio_markup, studio_ui


def _step1(markup: str) -> str:
    start = markup.index('<div id="studioStep1"')
    return markup[start:markup.index('<div id="studioStep2"')]


def test_step_one_is_called_what_it_does() -> None:
    markup = studio_markup()
    assert "<strong>Phân tích</strong>" in markup
    step = _step1(markup)
    assert "<h3>Phân tích</h3>" in step
    assert "Phân tích và hiểu nội dung của nguồn tham khảo đang chọn" in step
    assert "Nguồn &amp; mục tiêu" not in markup and "Nguồn & mục tiêu" not in markup


def test_no_sample_data_or_advertising_is_left() -> None:
    markup = studio_markup()
    for gone in (
        "studio-command-center", "Giao việc cho AI", "Astra điều phối", "studio-ai-task", "Kế hoạch AI",
        "AI đang hoạt động", "Astra / ChatGPT app / Claude", "12/15 cảnh", "studio-demo-storyboard",
        "Thêm cảnh mới", "AI tiếp tục",
    ):
        assert gone not in markup, gone


def test_the_technical_log_is_off_the_workflow_screen() -> None:
    markup = studio_markup()
    assert 'id="studioLogPanel"' not in markup
    assert "AI NÀO ĐÃ LÀM BƯỚC NÀO" not in markup


def test_language_and_publishing_channel_are_not_step_one_controls() -> None:
    step = _step1(studio_markup())
    assert 'id="studioAnalysisLanguage"' not in studio_markup()
    # Kept for the writer and the library's "Dựng lại video →", but not shown.
    pickers = step[step.index('class="studio-source-pickers" hidden'):]
    assert pickers.index('id="studioManagedChannelSelect"') < pickers.index("</div>\n")
    assert "Kênh xuất bản</label>" not in step


def test_the_source_is_shown_and_changed_in_the_reference_tab() -> None:
    step = _step1(studio_markup())
    assert "Nguồn đang dùng" in step
    assert """onclick="setWorkspace('source')">Đổi nguồn</button>""" in step
    assert "studioSourceUpload" not in step and 'type="url"' not in step


def test_uploading_lives_in_the_reference_tab() -> None:
    markup = studio_markup()
    panel = markup[markup.index('id="sourceAddPanel"'):]
    panel = panel[:panel.index("</section>")]
    # One picker for every kind of file, beside the link box.
    assert '<input id="sourceFileInput" type="file" multiple' in panel
    for gone in ("studioSourceUpload", "studioImageUpload", "studioFolderUpload"):
        assert gone not in markup, gone


def test_one_main_action_and_it_runs_the_analyze_step() -> None:
    ui = studio_ui()
    step = _step1(studio_markup())
    assert '<button id="studioAnalyzeButton" class="btn primary studio-analyze-cta" disabled>Phân tích</button>' in step
    assert "button.textContent = state.studioAnalysis?.result ? 'Phân tích lại' : 'Phân tích';" in ui
    body = ui[ui.index("async function analyzeStudioVideo() {"):]
    body = body[:body.index("\n  }\n")]
    assert "/steps/analyze" in body
    assert "reference-analysis" not in body
    assert "setStudioStep(2)" not in body


def test_the_result_is_shown_in_step_one_and_continues_to_the_plan() -> None:
    step = _step1(studio_markup())
    assert 'id="studioStep1Result"' in step
    assert 'onclick="setStudioStep(2)">Tiếp tục Kế hoạch →</button>' in step
    ui = studio_ui()
    assert "function renderStudioAnalysis(payload) {\n    renderStudioStep1Result(payload);" in ui


def test_each_kind_of_source_has_its_own_layout() -> None:
    ui = studio_ui()
    for renderer in ("studioVideoSections", "studioProductSections", "studioArticleSections", "studioImageSections"):
        assert f"function {renderer}(" in ui, renderer
    product = ui[ui.index("function studioProductSections("):ui.index("function studioArticleSections(")]
    for field in ("original_price", "discount", "seller", "rating", "sold_count", "captured_at"):
        assert field in product, field
    assert "Nhân vật" not in product and "Lời thoại" not in product


def test_advanced_holds_only_the_model_and_the_raw_data() -> None:
    step = _step1(studio_markup())
    advanced = step[step.index('<details id="studioAdvanced"'):]
    advanced = advanced[:advanced.index("</details>\n", advanced.index("studioAnalysisJson"))]
    assert 'id="studioAnalysisProviderSelect"' in advanced
    assert 'id="studioAnalysisJson"' in advanced
    assert "studioManagedChannelSelect" not in advanced


def test_the_model_list_offers_only_what_analyze_can_run() -> None:
    ui = studio_ui()
    assert "new Set(['auto', 'codex_cli', 'claude_code_cli', 'astra', 'claude'])" in ui
    assert "id === 'studioAnalysisProviderSelect' ? analyzeProviders : writerProviders" in ui


def test_errors_are_told_in_plain_words() -> None:
    ui = studio_ui()
    plain = ui[ui.index("function studioPlainText(text) {"):ui.index("function studioAnalyzeErrorText(error) {")]
    for token in ("HTTP", "agt_", "extension:", "options\\.", "NEED_LOGIN"):
        assert token in plain, token
    notice = ui[ui.index("function studioReadNotice("):ui.index("function studioResultNotes(")]
    assert "cần kết nối tài khoản" in notice
    assert """setWorkspace('settings')">Mở Công cụ & kết nối</button>""" in notice
    assert re.search(r"onclick=\"analyzeStudioVideo\(\)\">Phân tích lại", notice)


def test_ai_prose_does_not_repeat_how_the_page_was_read() -> None:
    ui = studio_ui()
    prose = ui[ui.index("function studioProse(text) {"):ui.index("function studioLongText(")]
    for token in ("session", "extension", "profile", "toLocaleString"):
        assert token in prose, token
    assert "const value = studioProse(text);" in ui
    assert "map((item) => studioProse(item))" in ui
    money = ui[ui.index("function studioMoney("):ui.index("function studioVideoSections(")]
    assert "replace(/^₫\s*(.+)$/, '$1₫')" in money


def test_a_running_analysis_is_read_from_the_server_after_a_reload() -> None:
    ui = studio_ui()
    run = ui[ui.index("async function studioAnalyzeRun("):ui.index("function stopStudioAnalyzeWatch(")]
    assert "/api/projects/${projectId}/steps" in run
    follow = ui[ui.index("async function followStudioAnalyze("):ui.index("async function finishStudioAnalyze(")]
    assert "row?.state !== 'running'" in follow
    assert "setInterval" not in follow
    # Lightly: every 5 s in view, every 30 s in a background tab - never not at
    # all, or a tab left open behind another never learns the run is over.
    assert "document.hidden ? STUDIO_ANALYZE_HIDDEN_POLL_MS : STUDIO_ANALYZE_POLL_MS" in follow
    assert "const STUDIO_ANALYZE_POLL_MS = 5000;" in ui and "const STUDIO_ANALYZE_HIDDEN_POLL_MS = 30000;" in ui
    assert "if (!document.hidden) {" not in follow
    assert "watch.busy" in follow
    assert "document.addEventListener('visibilitychange'" in ui
    # Opening a project asks the server, not the page's memory.
    assert "void followStudioAnalyze(existingProject.id);" in ui
    select = ui[ui.index("async function selectStudioVideo("):ui.index("async function restoreStudioProgress(")]
    assert "stopStudioAnalyzeWatch();" in select and "state.studioAnalyzing = false;" in select


def test_a_second_click_follows_the_run_instead_of_starting_another() -> None:
    ui = studio_ui()
    body = ui[ui.index("async function analyzeStudioVideo() {"):ui.index("const STUDIO_ANALYZE_POLL_MS")]
    assert "if (state.studioAnalyzing) return;" in body
    assert "await followStudioAnalyze(projectId)" in body
    finish = ui[ui.index("async function finishStudioAnalyze("):]
    finish = finish[:finish.index("\n  }\n")]
    assert "studioAnalyzeErrorText({status: last.status_code, message: last.error})" in finish
    assert "renderStudioAnalysis(analysis)" in finish
