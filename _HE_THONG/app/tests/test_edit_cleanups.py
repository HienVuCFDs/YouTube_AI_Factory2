"""Taking the source's own logo, watermark and subtitles off the picture."""

from __future__ import annotations

import pytest

from youtube_monitor.ffmpeg_renderer import _cleanup_filters

FRAME = (1280, 720)


def test_no_cleanups_adds_no_filters() -> None:
    """Most scenes need nothing; a filter that does nothing still costs a pass."""
    assert _cleanup_filters([], *FRAME) == []


def test_a_corner_logo_becomes_a_delogo_box_inside_the_frame() -> None:
    """delogo rebuilds from the pixels around its box, so a box touching the
    edge has no border to read and FFmpeg refuses the filter outright."""
    width, height = FRAME

    for position in ("top_left", "top_right", "bottom_left", "bottom_right"):
        chain = _cleanup_filters([{"kind": "logo", "position": position, "method": "delogo"}], *FRAME)
        assert len(chain) == 1
        values = dict(part.split("=") for part in chain[0].replace("delogo=", "").split(":"))
        x, y, w, h = (int(values[key]) for key in ("x", "y", "w", "h"))
        assert x >= 1 and y >= 1
        assert x + w < width and y + h < height


def test_a_subtitle_band_covers_the_width_it_actually_occupies() -> None:
    """Burned-in subtitles run most of the way across, low in the frame."""
    chain = _cleanup_filters([{"kind": "subtitle", "position": "bottom_center", "method": "blur"}], *FRAME)

    values = dict(part.split("=") for part in chain[0].replace("delogo=", "").split(":"))
    assert int(values["w"]) > FRAME[0] * 0.8
    assert int(values["y"]) > FRAME[1] * 0.7


def test_several_marks_produce_several_filters_in_order() -> None:
    chain = _cleanup_filters([
        {"kind": "logo", "position": "top_left", "method": "delogo"},
        {"kind": "subtitle", "position": "bottom_center", "method": "blur"},
    ], *FRAME)

    assert len(chain) == 2


def test_crop_is_only_used_against_an_edge() -> None:
    """Cropping a mark out of the middle would take the picture with it."""
    edge = _cleanup_filters([{"kind": "watermark", "position": "top_center", "method": "crop"}], *FRAME)
    middle = _cleanup_filters([{"kind": "watermark", "position": "center", "method": "crop"}], *FRAME)

    assert edge[0].startswith("crop=")
    assert middle[0].startswith("delogo="), "giua khung thi phai xoa, khong duoc cat"


def test_an_unknown_position_is_skipped_rather_than_guessed() -> None:
    """Blurring the wrong rectangle damages the picture for nothing."""
    assert _cleanup_filters([{"kind": "logo", "position": "somewhere", "method": "blur"}], *FRAME) == []


def test_a_malformed_entry_does_not_break_the_render() -> None:
    assert _cleanup_filters(["khong phai dict", {"kind": "logo"}], *FRAME) == []


@pytest.mark.parametrize("size", [(640, 360), (1920, 1080), (720, 1280)])
def test_boxes_stay_inside_every_frame_size(size: tuple[int, int]) -> None:
    """Vertical output is a real target here, and a box sized for landscape
    would fall outside it."""
    width, height = size

    for position in ("top_left", "top_right", "bottom_right", "bottom_center", "center", "full"):
        chain = _cleanup_filters([{"kind": "logo", "position": position, "method": "delogo"}], width, height)
        values = dict(part.split("=") for part in chain[0].replace("delogo=", "").split(":"))
        x, y, w, h = (int(values[key]) for key in ("x", "y", "w", "h"))
        assert 1 <= x and 1 <= y, position
        assert x + w < width and y + h < height, position
