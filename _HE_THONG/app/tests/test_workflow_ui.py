"""The wizard must show only the workflow the user chose."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.ui_source import studio_ui


@pytest.fixture(scope="module")
def page() -> str:
    return studio_ui()


def test_hidden_is_enforced_against_class_display_rules(page: str) -> None:
    """[hidden] is only the browser's display:none, so any class rule with its
    own display beats it. .studio-actions sets display:flex, which is why rows
    tagged for one workflow stayed on screen in the other - the image and
    motion controls showed during the reup step.

    The file had already patched this four times for four different classes.
    One rule replaces the fifth.
    """
    assert re.search(r"^\s*\[hidden\] \{ display: none !important; \}", page, re.M)


def test_every_workflow_specific_row_is_tagged(page: str) -> None:
    tagged = set(re.findall(r'data-wf="([a-z]+)"', page))

    assert tagged == {"content", "reup"}


def test_short_flow_is_visible_even_during_a_live_server_update(page: str) -> None:
    """The HTML reloads before a non-reload uvicorn process imports new WF files."""
    assert "const SHORT_FLOW_FALLBACKS" in page
    assert "function withVisibleShortFlow(flow)" in page
    assert "WORKFLOWS[flow.key] = withVisibleShortFlow(flow)" in page
    assert "Kịch bản + Short" in page
    assert "Lời bình + Short" in page


def test_content_short_uses_its_own_ai_visual_batch(page: str) -> None:
    """A Content Short has no source footage to cut; it needs vertical AI art."""
    assert "async function generateShortSceneImages()" in page
    assert "runStudioSceneBatch(provider, false, null, 'short')" in page
    assert "variant === 'short' ? '720:1280'" in page
    assert "state.studioWorkflow !== 'reup'" in page


def test_the_image_and_video_controls_belong_to_content_only(page: str) -> None:
    """These queue AI generation, which the reup workflow never does."""
    for control in ("studioSceneImageProviderSelect", "studioSceneVideoProviderSelect"):
        block = page[page.index(control) - 400:page.index(control)]
        assert 'data-wf="content"' in block, control


def test_storyboard_has_no_edit_planning_toolbar(page: str) -> None:
    """Reviewing scenes must not expose the discarded draft/approve/apply
    workflow or make each scene look like a second editing application."""
    for control in (
        "studioPlanEditButton",
        "studioApproveEditPlanButton",
        "studioApplyEditPlanButton",
        "studioProcessMissingButton",
        "studioPreflightButton",
        "studioPlanStatus",
        "studioEditPlan",
    ):
        assert not re.search(fr'<[^>]+id="{control}"', page), control
    assert "▶ Preview dựng</button>" not in page


def test_storyboard_splits_edit_planning_from_apply(page: str) -> None:
    """Planning must stay editable until the user explicitly applies it."""
    assert 'id="studioBuildEditPlanButton"' in page
    assert 'id="studioApplyEditPlanToScenesButton"' in page
    assert "AI dựng từng cảnh" in page
    assert "1. Lập kế hoạch dựng" in page
    assert "2. Áp dụng kế hoạch dựng" in page
    assert '<option value="phantom_canvas_image">Gemini Web · Phantom Canvas (đề xuất)</option>' in page
    assert "$('studioEditPlanProviderSelect')?.value || 'phantom_canvas_image'" in page
    assert "function planAllStudioSceneEdits()" in page
    assert "function applyAllStudioSceneEdits()" in page
    assert "function saveStudioSceneEditPlan(segmentId" in page
    assert "function storyboardEditSummary(segment)" in page
    assert "/edit-beats/plan" in page
    assert "/edit-beats/apply" in page
    assert "Sửa kế hoạch cảnh" in page


def test_source_step_previews_video_inside_the_app(page: str) -> None:
    """After loading source videos, selecting one should show a playable source."""
    assert 'id="studioVideoPreview"' in page
    assert "function sourcePreviewPlayer(video)" in page
    assert "function youtubeEmbedUrl(video)" in page
    assert "youtube-nocookie.com/embed" in page
    assert "/api/videos/${videoId}/source-preview" in page
    assert "class=\"studio-source-video\"" in page
    assert "class=\"studio-source-embed\"" in page


def test_storyboard_no_longer_contains_timeline_preview_editor(page: str) -> None:
    """The abandoned mini-editor must be fully removed from Storyboard."""
    removed_tokens = (
        "studioStoryboardTimeline",
        "studioStoryboardPreview",
        "studioCompositePreviewVideo",
        "studioTimelinePlayButton",
        "studioTimelinePlayhead",
        "renderStudioStoryboardTimeline",
        "renderStudioStoryboardScenePreview",
        "renderStudioTimelineCompositePreview",
        "seekStudioTimeline",
        "syncStudioTimelineFromVideo",
        "storyboard-timeline",
        "storyboard-editor-video-track",
        "storyboard-editor-audio-track",
        "/timeline/preview-video",
        "Màn hình preview & Timeline Storyboard",
        "Dựng preview tổng hợp",
    )
    for token in removed_tokens:
        assert token not in page, token


def test_the_source_cutting_controls_belong_to_reup_only(page: str) -> None:
    for control in ("studioCutByDialogueButton", "studioCutSourceScenesButton"):
        block = page[page.index(control) - 400:page.index(control)]
        assert 'data-wf="reup"' in block, control
    assert not re.search(r'<[^>]+id="studioPlanSourceCuesButton"', page)
    assert not re.search(r'<[^>]+id="studioSourceCuePlan"', page)


def test_the_reup_actions_are_numbered_in_the_order_they_run(page: str) -> None:
    """Cutting scenes was numbered before downloading the file they are cut
    from, which reads as nonsense even though both work."""
    order = [
        page.index("1. Tải video nguồn về máy"),
        page.index("2. Tạo mốc cắt theo lời thoại"),
        page.index("3. Xuất clip theo mốc cắt"),
    ]

    assert order == sorted(order)


def test_moving_between_steps_stays_available_in_both_workflows(page: str) -> None:
    """Only the workflow-specific half of that row may be tagged, or the reup
    user loses the button that leaves the step."""
    marker = "Mở xưởng dựng →"
    row_start = page.rindex('<div class="studio-actions"', 0, page.index(marker))
    row = page[row_start:page.index(marker)]

    assert 'data-wf' not in row.split("<span")[0], "ca hang khong duoc gan cho mot WF"


def test_a_card_short_of_pictures_is_visible_as_such(page: str) -> None:
    """The edit plan writes this status onto the shot; if the storyboard has no
    word for it the card renders a bare "NEEDS_VISUAL" and reads as a glitch."""
    assert "needs_visual: ['red', 'THIẾU HÌNH']" in page
    assert "Cảnh này thiếu hình minh hoạ" in page


def test_single_scene_image_picker_has_real_providers_only(page: str) -> None:
    """The batch-only pseudo-provider must not be sent to the single-job API."""
    options = re.search(r"const IMAGE_PROVIDER_OPTIONS = '([^']+)'", page)

    assert options is not None
    assert 'value="auto_parallel"' not in options.group(1)
    assert 'value="gflow_image"' in options.group(1)


def test_gflow_image_is_exposed_in_the_content_batch_picker(page: str) -> None:
    picker_at = page.index('id="studioSceneImageProviderSelect"')
    picker = page[picker_at:page.index('</select>', picker_at)]

    assert 'value="gflow_image"' in picker


def test_auto_pipeline_distinguishes_waiting_for_cross_review(page: str) -> None:
    assert "CHỜ AI NGHIỆM THU" in page
    assert "task.status === 'review_required'" in page


def test_orchestration_has_its_own_workspace(page: str) -> None:
    """Operations must not be buried among API keys and local tools."""
    assert 'data-workspace-nav="orchestration"' in page
    workspace = page[page.index("orchestration: {"):page.index("settings: {", page.index("orchestration: {"))]
    assert "automationCommandCenter" in workspace
    assert "automationPipeline" in workspace
    assert "orchestratorSettings" in workspace
    assert "automationPolicyPanel" in workspace


def test_orchestration_exposes_approval_media_and_cost_state(page: str) -> None:
    assert 'id="automationInboxBody"' in page
    assert 'id="automationStageFlow"' in page
    assert 'id="automationMediaBoard"' in page
    assert "API trả phí:" in page
    assert "không tính phí phát sinh" in page


def test_orchestration_loads_existing_runs_not_only_local_storage(page: str) -> None:
    assert "async function loadAutomationProjectList()" in page
    assert "state.automationProjects = data.projects || []" in page
    assert "async function loadAutomationInbox()" in page
    assert "/api/automation/approvals?status=pending" in page


def test_usage_limit_banner_can_allow_a_safe_retry(page: str) -> None:
    assert "Cho thử lại" in page
    assert "/api/usage-limits/${encodeURIComponent(provider)}/clear" in page


def test_the_storyboard_reloads_itself_when_a_job_finishes(page: str) -> None:
    """A finished voiceover left the page showing the timeline from before it.

    The files were on disk and attached in the database, but no play button
    had been drawn, so the run looked like a failure and the obvious next
    move was to run something that destroyed it.
    """
    assert "refreshStudioAfterFinishedJobs" in page
    assert "finishedJobSignature" in page
    assert "renderStudioStoryboard(bundle.latest_shots || [], state.timeline);" in page


def test_legacy_edit_beats_no_longer_block_render_or_script_import(page: str) -> None:
    """The discarded planning experiment must not leave an invisible render
    preflight behind after its controls have been removed from Storyboard."""
    render_start = page.index("async function queueStudioRender")
    render_end = page.index("async function watchStudioProductionJob", render_start)
    render_body = page[render_start:render_end]
    assert "incompleteBeats" not in render_body

    import_start = page.index("async function importStudioPastedScript")
    import_end = page.index("async function writeStudioScript", import_start)
    assert "incompleteBeats" not in page[import_start:import_end]


def test_render_workshop_checks_real_scene_files_not_an_edit_plan(page: str) -> None:
    render_start = page.index("async function queueStudioRender")
    render_end = page.index("async function watchStudioProductionJob", render_start)
    render_body = page[render_start:render_end]
    assert "/render-readiness" in render_body
    assert "/edit-plan/preflight" not in render_body
    assert "renderStudioRenderReadiness(check)" in render_body
    assert 'id="studioRenderReadinessNote"' in page


def test_render_button_tracks_the_current_storyboard_readiness(page: str) -> None:
    start = page.index("function renderStudioRenderReadiness")
    end = page.index("async function refreshStudioRenderReadiness", start)
    body = page[start:end]
    assert "renderButton.disabled = !check.can_render" in body
    assert "Quay lại Storyboard và lọc cảnh thiếu" in body


def test_storyboard_cards_are_review_cards_not_a_second_cutting_workspace(page: str) -> None:
    render_start = page.index("function renderStudioStoryboard")
    render_end = page.index("async function refreshStudioStoryboard", render_start)
    render_body = page[render_start:render_end]

    assert "studioCutStart-" not in render_body
    assert "studioTrimHead-" not in render_body
    assert "studioTrimTail-" not in render_body
    assert "Cắt lại cảnh này" not in render_body
    assert "studioPlanAllScenesButton" not in render_body
    assert "studioApplyAllScenesButton" not in render_body
    assert "Thay ảnh/video bằng AI (tùy chọn)" in render_body
    assert "<details" in render_body


def test_storyboard_counts_missing_picture_and_voice_independently(page: str) -> None:
    facts_start = page.index("function storyboardSceneFacts")
    facts_end = page.index("function storyboardSceneState", facts_start)
    facts_body = page[facts_start:facts_end]
    assert "missingVisual && missingAudio" in facts_body
    assert "Thiếu hình + tiếng" in facts_body

    render_start = page.index("function renderStudioStoryboard")
    render_end = page.index("async function refreshStudioStoryboard", render_start)
    render_body = page[render_start:render_end]
    assert "if (facts.missingVisual) summary.missing_visual += 1" in render_body
    assert "if (facts.missingAudio) summary.missing_audio += 1" in render_body
    assert 'data-missing-visual="${sceneFacts.missingVisual' in render_body
    assert 'data-missing-audio="${sceneFacts.missingAudio' in render_body


def test_storyboard_filters_include_scenes_missing_both_inputs(page: str) -> None:
    start = page.index("function filterStudioStoryboard")
    end = page.index("function renderStudioStoryboard", start)
    body = page[start:end]
    assert "card.dataset.missingVisual === '1'" in body
    assert "card.dataset.missingAudio === '1'" in body
    assert "card.dataset.ready === '1'" in body


def test_reloaded_storyboard_actions_use_the_timeline_visible_on_screen(page: str) -> None:
    render_start = page.index("function renderStudioStoryboard")
    render_end = page.index("async function refreshStudioStoryboard", render_start)
    render_body = page[render_start:render_end]
    assert "if (containerId === 'studioStoryboardResult')" in render_body
    assert "state.timeline = Array.isArray(timeline) ? timeline : [];" in render_body

    resume_start = page.index("const savedWorkflow = bundle.project?.workflow")
    resume_end = page.index("setStudioStep(nextStep);", resume_start)
    resume_body = page[resume_start:resume_end]
    assert "state.timeline = bundle.latest_timeline || [];" in resume_body
    assert "state.projectAssets = bundle.project_assets || [];" in resume_body
    assert "state.editBeats = bundle.edit_beats || {};" not in resume_body
    assert resume_body.index("state.timeline = bundle.latest_timeline || [];") < resume_body.index(
        "renderStudioStoryboard(state.shots, state.timeline);"
    )


def test_the_refresh_never_breaks_the_polling_loop(page: str) -> None:
    start = page.index("async function refreshStudioAfterFinishedJobs")
    body = page[start:start + 900]
    assert "catch" in body


def test_legacy_edit_plan_javascript_is_removed_from_the_wizard(page: str) -> None:
    """The retired edit-planning workflow should not linger in wizard JS."""
    retired_tokens = (
        "Legacy edit-planning UI intentionally disabled",
        "function studioEditPlanImpact(plan)",
        "function planStudioEdit()",
        "function applyStudioEditPlan()",
        "function renderStudioEditBeatEditor()",
        "function generateStudioEditBeatImage(",
        "studioPlanAllScenesButton",
        "studioApplyAllScenesButton",
    )
    for token in retired_tokens:
        assert token not in page


def test_retired_planning_labels_do_not_show_as_scene_status(page: str) -> None:
    """Scene status should read like production readiness, not the old plan UI."""
    start = page.index("function shotStatusTag")
    end = page.index("function productionJobStatusTag", start)
    status_body = page[start:end]
    assert "ĐANG CHUẨN BỊ" in status_body
    assert "CHƯA TRIỂN KHAI" in page
    assert "KẾ HOẠCH" not in status_body
    assert ">Kế hoạch<" not in status_body
    assert "Storyboard & kế hoạch" not in page


def test_the_voice_is_recorded_before_the_storyboard(page: str) -> None:
    """Pictures are timed against the voice, so the voice comes first.

    A scene's duration is a guess until its narration exists; the renderer
    then writes the measured length back over it. Planning overlays and SFX
    before that meant planning against numbers that were about to change -
    and the edit plan was marked stale the moment the voice landed.
    """
    voice = page.index('id="studioStep4"')
    storyboard = page.index('id="studioStep5"')
    workshop = page.index('id="studioStep6"')
    assert voice < storyboard < workshop

    assert '<span>04</span><strong>Giọng đọc</strong>' in page
    assert '<span>05</span><strong>Storyboard &amp; Edit</strong>' in page

    # Voice is recorded per scene, so this step cuts the script into scenes
    # itself rather than sending the user two steps ahead for a timeline.
    assert page.index('id="studioGenerateVoiceoverButton"') < storyboard
    assert "Chia cảnh &amp; tạo giọng đọc" in page
    assert '<button id="studioGenerateTimelineButton"' not in page


def test_studio_wizard_is_presented_as_seven_ai_steps(page: str) -> None:
    """Every step the wizard has is a tab, and the stepper is the only label.

    Voice and the build workshop were once folded into the storyboard tab,
    which named neither: the only way to find them was a button inside
    another step. The eyebrow and the "BƯỚC 1 / 5" badge are still gone -
    the numbered tabs already say where the user is.
    """
    assert "AI STUDIO 5 BƯỚC" not in page
    assert "BƯỚC 1 / 5" not in page
    for number, label in enumerate(
        ("Phân tích", "Kế hoạch", "Kịch bản", "Storyboard &amp; Edit",
         "Giọng đọc", "Xưởng dựng", "Render &amp; Xuất bản"), start=1,
    ):
        assert f'data-studio-tab="{number}" onclick="setStudioStep({number})"' in page
        assert f"<strong>{label}</strong>" in page
    assert 'data-studio-tab="8"' not in page
    # A step panel exists for each tab, so no tab lands on an empty page.
    for number in range(1, 8):
        assert f'data-studio-step="{number}"' in page
    assert "Render &amp; Xuất bản" in page
