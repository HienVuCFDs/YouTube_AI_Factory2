"""The wizard must show only the workflow the user chose."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parent.parent / "youtube_monitor" / "templates" / "index.html"


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


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


def test_the_image_and_video_controls_belong_to_content_only(page: str) -> None:
    """These queue AI generation, which the reup workflow never does."""
    for control in ("studioSceneImageProviderSelect", "studioMotionPolicySelect",
                    "studioSceneVideoProviderSelect"):
        block = page[page.index(control) - 400:page.index(control)]
        assert 'data-wf="content"' in block, control


def test_the_source_cutting_controls_belong_to_reup_only(page: str) -> None:
    for control in ("studioCutByDialogueButton", "studioCutSourceScenesButton"):
        block = page[page.index(control) - 400:page.index(control)]
        assert 'data-wf="reup"' in block, control


def test_the_reup_actions_are_numbered_in_the_order_they_run(page: str) -> None:
    """Cutting scenes was numbered before downloading the file they are cut
    from, which reads as nonsense even though both work."""
    order = [
        page.index("1. Tải video nguồn về máy"),
        page.index("2. Cắt cảnh theo lời thoại"),
        page.index("3. Xuất clip từ video gốc"),
    ]

    assert order == sorted(order)


def test_moving_between_steps_stays_available_in_both_workflows(page: str) -> None:
    """Only the workflow-specific half of that row may be tagged, or the reup
    user loses the button that leaves the step."""
    marker = "Tiếp tục dựng →"
    row_start = page.rindex('<div class="studio-actions"', 0, page.index(marker))
    row = page[row_start:page.index(marker)]

    assert 'data-wf' not in row.split("<span")[0], "ca hang khong duoc gan cho mot WF"


def test_a_card_short_of_pictures_is_visible_as_such(page: str) -> None:
    """The edit plan writes this status onto the shot; if the storyboard has no
    word for it the card renders a bare "NEEDS_VISUAL" and reads as a glitch."""
    assert "needs_visual: ['red', 'THIẾU HÌNH']" in page
    assert "Cảnh này thiếu hình minh hoạ" in page
