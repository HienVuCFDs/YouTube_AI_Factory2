"""Judging a scene before the render, not inside it.

A voiceover reviewed by pressing play on every scene in turn is a voiceover
whose dead scenes and truncated lines get missed, and a cut point that can
only be judged after a full render is a cut point nobody adjusts.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from youtube_monitor.ffmpeg_renderer import resolve_ffmpeg
from tests.ui_source import studio_ui


class TheEndpointsExistTests(unittest.TestCase):
    def test_a_scene_can_be_shown_as_a_waveform(self) -> None:
        from youtube_monitor.main import app

        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/projects/{project_id}/timeline/{segment_id}/waveform", paths)

    def test_a_scene_cut_point_can_be_moved(self) -> None:
        from youtube_monitor.main import app

        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/timeline/{segment_id}/cut", paths)

    def test_moving_it_re_cuts_the_clip_by_default(self) -> None:
        """Saving the number alone leaves the storyboard showing the old shot,
        so the change could only be judged after a whole render."""
        source = (
            Path(__file__).resolve().parent.parent / "youtube_monitor" / "main.py"
        ).read_text(encoding="utf-8")

        self.assertIn("recut: bool = True", source)
        self.assertIn("prepare_source_visuals(", source)

    def test_an_unset_cut_point_can_be_written_back(self) -> None:
        """-1 is how the column says "never chosen"; refusing it made a scene
        impossible to return to the state it was found in."""
        source = (
            Path(__file__).resolve().parent.parent / "youtube_monitor" / "main.py"
        ).read_text(encoding="utf-8")

        self.assertIn("source_start_seconds: float | None = Field(default=None, ge=-1", source)


class FfmpegCanDrawTheWaveformTests(unittest.TestCase):
    """The filter chain is the part that silently produces nothing."""

    def test_showwavespic_produces_a_png_from_real_audio(self) -> None:
        executable = resolve_ffmpeg("ffmpeg")
        if not executable:
            self.skipTest("FFmpeg không có trên máy chạy test")
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "voice.m4a"
            subprocess.run(
                [executable, "-y", "-loglevel", "error", "-f", "lavfi",
                 "-i", "sine=frequency=440:duration=2", str(audio)],
                check=True, capture_output=True,
            )
            result = subprocess.run(
                [executable, "-v", "error", "-i", str(audio), "-filter_complex",
                 "aformat=channel_layouts=mono,compand,showwavespic=s=640x80:colors=#f59e0b",
                 "-frames:v", "1", "-f", "image2", "-c:v", "png", "-"],
                capture_output=True, check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        self.assertTrue(result.stdout.startswith(b"\x89PNG"))


class TheReviewControlsAreOnTheCardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page = studio_ui()

    def test_every_scene_shows_the_shape_of_its_audio(self) -> None:
        self.assertIn("storyboard-wave", self.page)
        self.assertIn("/waveform", self.page)

    def test_a_missing_waveform_does_not_leave_a_broken_image(self) -> None:
        self.assertIn('onerror="this.remove()"', self.page)

    def test_a_storyboard_card_does_not_duplicate_source_cutting_controls(self) -> None:
        self.assertNotIn("saveSegmentCut(", self.page)
        self.assertNotIn("Cắt lại cảnh này", self.page)

    def test_source_cutting_stays_in_the_reup_preparation_flow(self) -> None:
        """Storyboard is for review; selecting and cutting source clips is one
        explicit operation before the cards are reviewed."""
        self.assertIn('id="studioCutByDialogueButton"', self.page)
        self.assertIn('id="studioCutSourceScenesButton"', self.page)
        self.assertNotIn("studioCutStart-", self.page)
        self.assertNotIn("studioTrimHead-", self.page)

    def test_the_whole_short_can_be_heard_end_to_end(self) -> None:
        self.assertIn("playWholeShortVoice()", self.page)
        self.assertIn("Nghe toàn bộ Short", self.page)
        self.assertIn("stopWholeShortVoice()", self.page)

    def test_playing_it_queues_the_scenes_rather_than_rendering_anything(self) -> None:
        """No file is written to hear a draft."""
        self.assertIn("player.addEventListener('ended', step)", self.page)

    def test_a_second_play_does_not_leave_the_first_running(self) -> None:
        self.assertIn("if (state.shortVoicePlayer) { state.shortVoicePlayer.pause();", self.page)

    def test_it_says_which_scene_is_playing(self) -> None:
        self.assertIn("studioShortPlayAllState", self.page)
        self.assertIn("Đang phát cảnh", self.page)
