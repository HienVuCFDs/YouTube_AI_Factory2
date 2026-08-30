"""Covering the source's own subtitles without being asked to.

Every clip in a reup comes from one film, so what that film burns into its
picture is on all of them. The edit planner was supposed to report these, but
it was only ever given the scene's words - never a frame - so it truthfully
reported nothing, and every finished video kept the source's subtitles under
the new narration.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np
import pytest

from youtube_monitor import production_worker

from youtube_monitor.burned_in_marks import (
    _find_static_marks,
    _find_subtitle_band,
)
from youtube_monitor.ffmpeg_renderer import (
    _blur_filter,
    _cleanup_filters,
    _explicit_box,
)


FRAME = (1920, 1080)


def _film(frames: int = 12, height: int = 216, width: int = 384) -> np.ndarray:
    """A moving picture with no overlay on it: mid grey, never the same twice."""
    generator = np.random.default_rng(20260831)
    return generator.uniform(60, 150, size=(frames, height, width)).astype(np.float32)


def _burn_subtitles(stack: np.ndarray, top: float, bottom: float) -> None:
    """Bright outlined lettering, low in frame, different on every frame."""
    _, height, width = stack.shape
    y0, y1 = int(height * top), int(height * bottom)
    for index in range(stack.shape[0]):
        stack[index, y0 - 2:y1 + 2, :] = 20.0  # the dark outline round the type
        # Where the glyphs fall changes frame to frame, as a subtitle does.
        for start in range(60 + (index * 7) % 11, width - 60, 9):
            stack[index, y0:y1, start:start + 4] = 250.0


def test_a_burned_in_subtitle_is_found_where_it_actually_sits() -> None:
    stack = _film()
    _burn_subtitles(stack, 0.74, 0.78)

    found = _find_subtitle_band(stack)

    assert found is not None
    assert found["kind"] == "subtitle"
    x, y, w, h = found["box"]
    # The measured box has to contain the lettering with room around it: a
    # blur that stops at the ink leaves legible edges behind.
    assert y < 0.74 and y + h > 0.78
    assert w > 0.5 and x + w <= 1.0


def test_a_subtitle_burned_high_is_not_snapped_to_the_bottom_of_the_frame() -> None:
    """The preset boxes are guesses, and this one would miss entirely.

    ``bottom_center`` covers the last 18% of the frame. A source that burns
    its subtitles at three quarters height - as vertical reups do - would have
    had clean picture blurred and its lettering left perfectly readable.
    """
    stack = _film()
    _burn_subtitles(stack, 0.72, 0.76)

    found = _find_subtitle_band(stack)

    assert found is not None
    _, y, _, h = found["box"]
    assert y + h < 0.86, "the box tracks the measured band, not the preset"


def test_clean_footage_is_left_alone() -> None:
    """Blurring a film that carries no marks would be damage, not a fix."""
    assert _find_subtitle_band(_film()) is None


def test_a_still_picture_does_not_read_as_four_logos() -> None:
    """A locked-off shot is still everywhere; that is not a watermark."""
    frozen = np.repeat(_film(frames=1), 10, axis=0)

    assert _find_static_marks(frozen) == []


def test_a_measured_box_beats_the_named_one() -> None:
    box = [0.10, 0.70, 0.80, 0.06]
    _, blurs = _cleanup_filters(
        [{"kind": "subtitle", "position": "bottom_center", "method": "blur", "box": box}],
        *FRAME,
    )

    assert blurs == [(0.10, 0.70, 0.80, 0.06)]


def test_a_cleanup_without_a_box_still_uses_its_preset() -> None:
    _, blurs = _cleanup_filters([{"kind": "logo", "position": "top_right"}], *FRAME)

    assert blurs == [(0.80, 0.0, 0.20, 0.125)]


@pytest.mark.parametrize("box", [None, [0.1, 0.1], [0.1, 0.1, 0, 0.2], "bottom", [0.1, 0.1, 0.2, "x"]])
def test_a_malformed_box_falls_back_rather_than_crashing_the_render(box) -> None:
    assert _explicit_box(box) is None


def test_the_blur_is_sized_to_the_region_it_covers() -> None:
    """One fixed strength cannot serve every resolution.

    The same subtitle band is a few dozen pixels tall on a 480p source and
    four times that on a 4K one; a blur tuned for one leaves the other
    readable. boxblur could not do this at all - it caps its radius against
    the plane, which is why CJK subtitles survived it.
    """
    small = _blur_filter(1920 * 0.9, 1080 * 0.04)
    large = _blur_filter(3840 * 0.9, 2160 * 0.08)

    assert "gblur=sigma=" in small and "gblur=sigma=" in large
    assert float(small.split("sigma=")[1].split(":")[0]) < float(
        large.split("sigma=")[1].split(":")[0]
    )


def test_a_region_of_unknown_size_still_gets_a_usable_blur() -> None:
    """FFmpeg refuses sigma=0, and an unblurred band is the bug being fixed."""
    filter_string = _blur_filter(0, 0)

    assert filter_string.startswith("gblur=sigma=")
    assert float(filter_string.split("sigma=")[1].split(":")[0]) >= 6


class AutoCoverRespectsWhatIsAlreadyDecided(unittest.TestCase):
    """The render covers the source's marks unless someone said otherwise.

    Marking used to be opt-in through a planning step that could not see the
    picture, so in practice no project ever had a mark and every reup shipped
    with the source's subtitles under the new narration. Covering by default
    fixes that, but it must not overrule a person who has already chosen.
    """

    def setUp(self) -> None:
        self.calls: list[Path] = []

    def _worker(self, timeline: list[dict[str, Any]], media: str):
        """The worker's auto-cover with the detector and database stubbed."""
        saved: dict[str, Any] = {}

        class FakeDatabase:
            def get_video(_self, _video_id: str) -> dict[str, Any]:
                return {"local_media_path": media}

            def set_timeline_cleanups(_self, _project, cleanups, script_id=None) -> int:
                saved["cleanups"] = cleanups
                return len(timeline)

            def list_project_timeline(_self, _project, script_id=None):
                return [dict(item, edit_cleanups=json.dumps(saved["cleanups"])) for item in timeline]

        def fake_detect(path, **_kwargs):
            self.calls.append(path)
            return [{"kind": "subtitle", "position": "bottom_center", "method": "blur"}]

        with mock.patch.object(production_worker, "detect_burned_in_marks", fake_detect):
            result = production_worker._autocover_source_marks(
                FakeDatabase(), {"id": 1, "youtube_video_id": "abc"}, {"id": 2}, timeline, "ffmpeg"
            )
        return result, saved

    def test_an_unmarked_reup_gets_its_source_measured(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            media = handle.name
        try:
            result, saved = self._worker([{"edit_cleanups": "[]"}, {"edit_cleanups": None}], media)
        finally:
            os.unlink(media)

        self.assertEqual(len(self.calls), 1)
        self.assertEqual(saved["cleanups"][0]["kind"], "subtitle")
        self.assertIn("subtitle", str(result[0]["edit_cleanups"]))

    def test_a_marking_already_made_is_left_alone(self) -> None:
        """Including the sentinel that says covering was deliberately turned off."""
        for existing in (
            '[{"position": "top_right", "method": "blur"}]',
            '[{"kind": "none", "source": "user_cleared"}]',
        ):
            with self.subTest(existing=existing):
                self.calls.clear()
                timeline = [{"edit_cleanups": existing}, {"edit_cleanups": "[]"}]

                result, saved = self._worker(timeline, "does-not-matter.mp4")

                self.assertEqual(self.calls, [], "the source must not be re-measured")
                self.assertEqual(saved, {})
                self.assertIs(result, timeline)

    def test_a_project_with_no_source_film_is_not_probed(self) -> None:
        """An AI-drawn project has no one else's picture underneath it."""
        result, saved = self._worker([{"edit_cleanups": "[]"}], r"F:\no\such\file.mp4")

        self.assertEqual(self.calls, [])
        self.assertEqual(saved, {})
        self.assertEqual(len(result), 1)
