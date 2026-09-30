"""Tab NGUỒN: paste a link or drop files - no type to pick first.

The page asks the server what it was given, shows that, and adds nothing
until the person confirms; adding goes through the endpoints that existed.
"""

from __future__ import annotations

from tests.ui_source import studio_markup, studio_ui


def _between(text: str, start: str, end: str = "\n  }\n") -> str:
    return text[text.index(start):text.index(end, text.index(start))]


def _panel(markup: str, panel_id: str) -> str:
    start = markup.index(f'id="{panel_id}"')
    return markup[start:markup.index("</section>", start)]


def test_one_box_for_a_link_or_files_and_no_type_to_pick() -> None:
    markup = studio_markup()
    box = _panel(markup, "sourceAddPanel")
    assert 'placeholder="Dán link YouTube, TikTok, Shopee, bài viết…"' in box
    assert ">Nhận dạng</button>" in box and "hoặc kéo thả file / ảnh / video vào đây" in box
    assert ">Chọn từ máy</label>" in box
    assert box.count('type="file"') == 1 and '<input id="sourceFileInput" type="file" multiple' in box
    for handler in ('ondragover="sourceDragOver(event)"', 'ondrop="sourceDrop(event)"', 'onsubmit="event.preventDefault(); detectSourceLink()"'):
        assert handler in box, handler
    for old in ("sourceImportType", "Loại nguồn", "URL kênh / @handle / ID", "Tải thư mục ảnh", "Tải video/audio", "webkitdirectory"):
        assert old not in markup, old


def test_the_four_kinds_are_filters_with_counts_not_choices() -> None:
    ui = studio_ui()
    assert "const SOURCE_GROUPS = [['all', 'Tất cả'], ['video', 'Video'], ['article', 'Bài viết'], ['product', 'Sản phẩm'], ['file', 'Ảnh/File']];" in ui
    render = _between(ui, "function renderSourceList() {")
    assert "onclick=\"setSourceGroup('${key}')\"" in render and "number(counts[key] || 0)" in render
    assert 'id="sourceKindsPanel"' not in studio_markup()


def test_a_link_is_detected_quickly_then_read_and_nothing_is_added_yet() -> None:
    ui = studio_ui()
    detect = _between(ui, "async function detectSourceLink() {")
    assert detect.index("probe: false") < detect.index("probe: true")
    assert "state.sourceTicket !== ticket" in detect, "a newer paste wins over a slower answer"
    for writer in ("/api/sources/import", "/api/uploads/source", "assets/upload", "image-collection"):
        assert writer not in detect, writer
        assert writer not in _between(ui, "async function detectSourceFiles(picked) {"), writer
    assert "/api/sources/detect-files" in _between(ui, "async function detectSourceFiles(picked) {")


def test_the_page_says_how_far_detection_got() -> None:
    ui = studio_ui()
    for words in ("Đang nhận dạng…", "Đã nhận dạng", "Không đọc được nguồn", "Cần đăng nhập/kết nối"):
        assert words in ui, words
    preview = _between(ui, "function renderSourcePreview() {")
    assert ">Hủy</button>" in preview
    assert "'Thêm kênh & đồng bộ'" in preview and "'Thêm nguồn'" in preview and "'Mở kênh'" in preview
    assert "onclick=\"setWorkspace('settings')\">Mở Công cụ & kết nối</button>" in preview


def test_only_what_was_read_is_shown() -> None:
    facts = _between(studio_ui(), "function sourceFacts(item) {")
    for guarded in ("if (meta.channel_name)", "if (meta.price_text)", "if (meta.seller)", "if (meta.subscriber_count != null)"):
        assert guarded in facts, guarded
    assert "đọc lúc" in facts, "a price comes with when it was read"


def test_adding_goes_through_the_importers_that_existed() -> None:
    ui = studio_ui()
    link = _between(ui, "async function importSourceLink(item) {")
    assert "'/api/sources/import'" in link
    files = _between(ui, "async function importSourceFiles(item, files) {")
    assert "fetch('/api/uploads/source'" in files
    assert "'/api/sources/image-collection'" in files and "/assets/upload`" in files


def test_files_go_where_the_router_says() -> None:
    files = _between(studio_ui(), "async function importSourceFiles(item, files) {")
    assert "['upload', 'image_collection'].includes(item.route)" in files
    assert "item.route === 'image_collection'" in files
    assert "item.kind ===" not in files, "the page does not choose the importer itself"


def test_step_one_reads_the_stored_kind_and_guesses_nothing() -> None:
    kind = _between(studio_ui(), "function studioSourceKind(video, analysis = state.studioAnalysis?.result) {")
    assert "STUDIO_ANALYSIS_KIND[String(video?.source_kind || '')]" in kind
    for guess in ("duration_seconds", "startsWith('web-')", "playable", "startsWith('idea-')"):
        assert guess not in kind, guess


def test_a_channel_is_opened_in_the_channel_tab_not_listed_as_a_source() -> None:
    ui = studio_ui()
    add = _between(ui, "async function addDetectedSources() {")
    assert "suggested_action === 'open_channel'" in add and "openDetectedChannel(" in add
    opened = _between(ui, "async function openDetectedChannel(channelId) {")
    assert "setSourceTab('channels')" in opened and "state.selectedChannel = channelId" in opened


def test_a_dropped_folder_is_read_and_its_files_classified() -> None:
    ui = studio_ui()
    drop = _between(ui, "async function sourceDrop(event) {")
    assert "webkitGetAsEntry" in drop and "readDroppedEntry(" in drop
    assert "text/uri-list" in drop, "a dragged link is detected too"
    assert "createReader()" in _between(ui, "async function readDroppedEntry(entry, prefix) {")


def test_each_saved_source_shows_what_it_is_and_its_analysis() -> None:
    ui = studio_ui()
    row = _between(ui, "function sourceRow(item) {")
    for part in ("item.thumbnail_url", "SOURCE_KIND_LABELS[item.kind]", "sourceRowMeta(item)", "Đã phân tích", "Đang phân tích",
                 "date(item.added_at)", "openSourceMenu("):
        assert part in row, part
    menu = _between(ui, "function openSourceMenu(videoId, button) {")
    for action in ("useSource(", "openProjectDetail(", "Mở trang gốc", "Sao chép link"):
        assert action in menu, action
    use = _between(ui, "async function useSource(videoId) {")
    assert "startStudioFromVideo(videoId)" in use and "resumeStudioProject(" in use


def test_the_list_is_read_when_the_tab_opens() -> None:
    apply = _between(studio_ui(), "function applySourceTab() {")
    assert "if (tab === 'sources') void loadSources();" in apply


def test_no_model_is_asked_to_detect() -> None:
    ui = studio_ui()
    block = ui[ui.index("// ---- Tab NGUỒN: một ô cho link hoặc file ----"):ui.index("// ---- Tab KÊNH:")]
    for model in ("analyze-images", "/api/agent", "llm", "orchestrat", "claude", "chatgpt"):
        assert model not in block.lower(), model
