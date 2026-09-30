"""Nguồn tham khảo: four tabs, and a KÊNH tab that is a list beside a detail.

The page reads one bundle per channel and assembles nothing itself; opening a
tab, a channel or the research view only reads; only the button refreshes
research - through the same engine the plan step uses.
"""

from __future__ import annotations

from tests.ui_source import studio_markup, studio_ui


def _between(text: str, start: str, end: str = "\n  }\n") -> str:
    return text[text.index(start):text.index(end, text.index(start))]


def test_the_workspace_is_four_tabs_under_one_header() -> None:
    markup = studio_markup()
    for tab in ("sources", "channels", "queue", "library"):
        assert f'data-source-tab-button="{tab}"' in markup, tab
    for label in ("NGUỒN", "KÊNH", "HÀNG ĐỢI", "THƯ VIỆN"):
        assert f"</span> {label}</button>" in markup, label
    ui = studio_ui()
    assert "title: 'Nguồn tham khảo'" in ui
    assert "Quản lý nguồn, kênh và dữ liệu nghiên cứu cho video của bạn" in ui
    apply = _between(ui, "function applySourceTab() {")
    assert "panel.dataset.sourceTab !== tab" in apply


def test_every_old_panel_still_has_a_tab() -> None:
    markup = studio_markup()
    placed = {
        "sourceAddPanel": "sources", "sourceListPanel": "sources", "channelWorkspace": "channels",
        "analysis": "queue", "transcriptQueue": "queue", "videos": "library",
    }
    for panel, tab in placed.items():
        start = markup.index(f'id="{panel}"')
        assert f'data-source-tab="{tab}"' in markup[start:start + 200], panel
    # The add-source form is not on the channels screen any more.
    assert 'id="sourceSplit"' not in markup and 'id="channelsBody"' not in markup


def test_the_studio_source_button_lands_on_the_library() -> None:
    ui = studio_ui()
    workspace = _between(ui, "function setWorkspace(name, persist = true) {")
    assert "name === 'source' && state.workspace === 'dashboard'" in workspace and "state.sourceTab = 'library'" in workspace


def test_the_channel_tab_is_a_list_beside_a_detail() -> None:
    markup = studio_markup()
    browser = markup[markup.index('id="channelWorkspace"'):markup.index("</section>\n", markup.index('id="channelDetail"'))]
    for part in ('id="channelSearch"', 'id="channelPlatformFilter"', 'id="channelStatusFilter"', 'id="channelList"', 'id="channelDetail"'):
        assert part in browser, part


def test_a_channel_card_shows_only_real_fields() -> None:
    ui = studio_ui()
    card = _between(ui, "function renderChannelList() {")
    assert "coverage ? `<div class=\"channel-card-stats\">" in card
    assert "channel.research?.updated_at ?" in card
    assert "openChannelMenu(" in card and "selectChannel(" in card
    assert "Chưa có kênh nào" in card, "empty state"
    avatar = _between(ui, "function channelAvatar(")
    assert "initials" in avatar, "a missing avatar falls back to initials"


def test_the_card_menu_only_offers_existing_actions() -> None:
    menu = _between(studio_ui(), "function openChannelMenu(")
    for action in ("syncChannel(", "refreshChannelResearch(", "toggleChannel(", "editChannelGroup("):
        assert action in menu, action
    assert "YOUTUBE_CHANNEL.test(channelId)" in menu, "sync only where the monitor can sync"


def test_the_detail_has_four_tabs() -> None:
    detail = _between(studio_ui(), "function renderChannelDetail(channelId) {")
    for tab in ("TỔNG QUAN", "VIDEO", "GIÁM SÁT", "NGHIÊN CỨU"):
        assert tab in detail, tab


def test_opening_anything_only_reads() -> None:
    ui = studio_ui()
    for function in ("async function loadChannels() {", "function selectChannel(", "async function loadChannelDetail(",
                     "function setChannelDetailTab(", "function renderChannelDetail(", "function renderChannelResearch(",
                     "function renderChannelOverview(", "function applySourceTab("):
        assert "/research/refresh" not in _between(ui, function), function
    assert ui.count("/research/refresh") == 1, "one way to research a channel"
    refresh = _between(ui, "async function refreshChannelResearch(")
    assert "method: 'POST'" in refresh


def test_research_statuses_have_their_labels_from_the_server_and_a_tone() -> None:
    ui = studio_ui()
    assert "item.label || 'Chưa nghiên cứu'" in _between(ui, "function researchBadge(")
    for state_ in ("fresh", "stale", "partial", "running"):
        assert f"{state_}:" in ui[ui.index("const RESEARCH_TONE"):ui.index("\n", ui.index("const RESEARCH_TONE"))], state_
    filters = ui[ui.index("const CHANNEL_STATUS_FILTERS"):ui.index("];", ui.index("const CHANNEL_STATUS_FILTERS"))]
    for label in ("Mới cập nhật", "Cần cập nhật", "Nghiên cứu chưa đầy đủ", "Chưa nghiên cứu", "Đang nghiên cứu"):
        assert label in filters, label


def test_a_running_refresh_is_followed_after_a_reload_and_not_started_twice() -> None:
    ui = studio_ui()
    follow = _between(ui, "function followChannelResearch(")
    assert "setTimeout(tick, CHANNEL_RESEARCH_POLL_MS)" in follow and "setInterval" not in follow
    load = _between(ui, "async function loadChannels() {")
    assert "item.research?.state === 'running'" in load and "followChannelResearch(" in load
    refresh = _between(ui, "async function refreshChannelResearch(")
    assert "if (state.channelResearchPending?.[channelId]) return;" in refresh
    card = _between(ui, "function researchStatusCard(")
    assert "${running ? 'disabled' : ''}" in card and "Đang cập nhật nghiên cứu..." in card


def test_missing_numbers_are_left_out_not_zeroed() -> None:
    ui = studio_ui()
    assert "value === null || value === undefined || value === ''" in _between(ui, "function kpi(")
    overview = _between(ui, "function renderChannelOverview(")
    assert "overview.subscriber_count != null ?" in overview
    assert "Chưa nghiên cứu kênh này." in overview


def test_a_partial_report_is_said_plainly() -> None:
    ui = studio_ui()
    notice = _between(ui, "function partialNotice(")
    assert "⚠ Nghiên cứu dự án #" in notice and "chưa đầy đủ" in notice
    assert "nguồn chưa đọc được" in notice and "Xem chi tiết" in notice
    for technical in ("HTTP", "403", "collector", "web.search", "youtube."):
        assert technical not in notice, technical
        assert technical not in _between(ui, "function renderChannelOverview("), technical


def test_comments_are_spoken_of_as_samples() -> None:
    research = _between(studio_ui(), "function renderChannelResearch(")
    assert "comment mẫu" in research and "không đại diện toàn bộ người xem" in research
    assert "% người xem" not in research and "người xem quan tâm" not in research


def test_charts_are_drawn_only_from_data_and_never_invented() -> None:
    ui = studio_ui()
    assert "if (points.length < 3) return '';" in _between(ui, "function viewsChart(")
    assert "if (!total) return '';" in _between(ui, "function durationChart(")
    assert "return '';" in _between(ui, "function topicBars(")
    for fake in ("Math.random", "demo", "Lorem", "viral", "trend score"):
        assert fake not in ui[ui.index("// ---- Charts:"):ui.index("async function refreshChannelResearch(")], fake


def test_using_a_video_as_a_source_goes_through_existing_endpoints() -> None:
    use = _between(studio_ui(), "async function useChannelVideoAsSource(")
    assert "/api/videos/import" in use and "startStudioFromVideo(" in use


def test_narrow_screens_show_the_list_then_the_detail() -> None:
    from pathlib import Path

    css = (Path(__file__).resolve().parents[1] / "youtube_monitor" / "static" / "app.css").read_text(encoding="utf-8")
    assert ".channel-browser.is-detail-open .channel-list-pane { display: none; }" in css
    assert ".channel-browser:not(.is-detail-open) .channel-detail-pane { display: none; }" in css


def test_one_card_per_real_channel_while_pickers_keep_every_row() -> None:
    ui = studio_ui()
    assert "channel.display?.primary !== false" in _between(ui, "function shownChannels() {")
    assert "return shownChannels()" in _between(ui, "function filteredChannels() {")
    load = _between(ui, "async function loadChannels() {")
    # The queue, filter and studio pickers still get every row: old videos
    # and projects are filed under the old synthetic ones.
    assert "populateChannelSelect($('analysisChannelSelect'));" in load and "populateStudioSourceChannelSelect();" in load
    assert "primaryChannelKey(wanted)" in load, "a remembered old row opens its channel"
    assert "primaryChannelKey(channelId)" in _between(ui, "function selectChannel(")


def test_channel_figures_and_project_figures_are_kept_apart() -> None:
    ui = studio_ui()
    overview = _between(ui, "function renderChannelOverview(")
    tiles = overview[overview.index("const researchTiles = ["):overview.index("].join('');", overview.index("const researchTiles = ["))]
    assert "latest" not in tiles, "no project figure is a channel tile"
    assert "comment của kênh đã lấy mẫu" in tiles
    latest = _between(ui, "function latestResearch(")
    assert "Nghiên cứu gần đây · dự án #" in latest
    assert "không phải toàn bộ comment của kênh" in latest
    research = _between(ui, "function renderChannelResearch(")
    coverage = research[research.index("const coverage = ["):research.index("].filter(Boolean);", research.index("const coverage = ["))]
    assert "latest" not in coverage
    assert "latestResearch(latest)" in research
