"""A source clip must cover the narration it was cut for.

Cutting before the voiceover exists sizes every clip against the planned
duration. The voiceover then rewrites the segment's duration from the real
audio, but nothing re-cuts the clip — so the picture runs out mid-sentence
and the end of the narration is lost. Measured on a real reup project:
64 of 70 scenes had clips that no longer matched their voice.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from youtube_monitor import main, settings
from youtube_monitor.ffmpeg_renderer import resolve_ffmpeg
from youtube_monitor.source_visuals import (
    CLIP_VOICE_TOLERANCE_SECONDS,
    SourceVisualError,
    mismatched_source_clips,
    prepare_source_visuals,
)


def _make_media(path: Path, seconds: float, kind: str = "video") -> Path:
    executable = resolve_ffmpeg(settings.FFMPEG_BINARY)
    source = (
        f"testsrc=duration={seconds}:size=320x240:rate=10"
        if kind == "video"
        else f"sine=frequency=440:duration={seconds}"
    )
    subprocess.run(
        [executable, "-y", "-v", "error", "-f", "lavfi", "-i", source, str(path)],
        check=True, capture_output=True,
    )
    return path


class MismatchDetectionTests(unittest.TestCase):
    """These touch FFmpeg because the drift is only visible in the files."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._dir = tempfile.TemporaryDirectory()
        root = Path(cls._dir.name)
        clips = root / "source_clips"
        clips.mkdir()
        cls.short_clip = _make_media(clips / "source-segment-001.mp4", 3.0)
        cls.matching_clip = _make_media(clips / "source-segment-002.mp4", 6.0)
        cls.still = _make_media(root / "generated_images.mp4", 1.0)
        cls.voice = _make_media(root / "voice.m4a", 6.0, kind="audio")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._dir.cleanup()

    def _segment(self, visual: Path, index: int = 1) -> dict:
        return {
            "id": index,
            "segment_index": index,
            "visual_path": str(visual),
            "audio_path": str(self.voice),
        }

    def test_a_clip_shorter_than_its_narration_is_reported(self) -> None:
        stale = mismatched_source_clips([self._segment(self.short_clip)], settings.FFMPEG_BINARY)
        self.assertEqual(len(stale), 1)
        self.assertLess(stale[0]["drift_seconds"], 0)
        self.assertEqual(stale[0]["segment_index"], 1)

    def test_a_clip_that_covers_its_narration_is_not_reported(self) -> None:
        stale = mismatched_source_clips([self._segment(self.matching_clip)], settings.FFMPEG_BINARY)
        self.assertEqual(stale, [])

    def test_a_generated_still_is_not_judged_against_the_voice(self) -> None:
        """A still has no length of its own; it is held for as long as needed."""
        stale = mismatched_source_clips([self._segment(self.still)], settings.FFMPEG_BINARY)
        self.assertEqual(stale, [])

    def test_a_scene_with_no_voice_yet_is_not_reported(self) -> None:
        segment = {**self._segment(self.short_clip), "audio_path": ""}
        self.assertEqual(mismatched_source_clips([segment], settings.FFMPEG_BINARY), [])

    def test_the_tolerance_is_small_enough_to_catch_a_lost_sentence(self) -> None:
        self.assertLessEqual(CLIP_VOICE_TOLERANCE_SECONDS, 1.0)


class CuttingOrderTests(unittest.TestCase):
    def test_cutting_before_any_voiceover_is_refused_with_the_right_order(self) -> None:
        timeline = [{"id": 1, "segment_index": 1, "audio_path": "", "duration_seconds": 5}]
        with tempfile.TemporaryDirectory() as directory:
            source = _make_media(Path(directory) / "source.mp4", 2.0)
            with self.assertRaises(SourceVisualError) as ctx:
                prepare_source_visuals(timeline, source, Path(directory) / "out")
        message = str(ctx.exception)
        self.assertIn("voiceover trước", message)

    def test_an_empty_timeline_is_left_to_the_existing_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = _make_media(Path(directory) / "source.mp4", 2.0)
            self.assertEqual(prepare_source_visuals([], source, Path(directory) / "out"), [])


class QcSeesTheMismatchTests(unittest.TestCase):
    def test_qc_reports_a_clip_that_no_longer_covers_its_voice(self) -> None:
        stale = [{"segment_index": 4, "clip_seconds": 3.0, "voice_seconds": 6.4, "drift_seconds": -3.4}]
        captured: dict = {}

        def fake_agent(agent, system, user, schema):
            import json

            captured.update(json.loads(user))
            return {"approved": True, "score": 10, "note": ""}

        task = {"project_id": 1, "role": "qc", "input": {}, "correlation_id": ""}
        timeline = [{"id": 1, "segment_index": 4, "visual_path": "x", "audio_path": "y", "subtitle_text": "z"}]
        with mock.patch.object(main, "mismatched_source_clips", return_value=stale):
            with mock.patch.object(main, "_call_specific_agent_json", side_effect=fake_agent):
                with mock.patch.object(main, "build_quality_report", return_value={"checks": {}, "issues": []}):
                    with mock.patch.object(main.database, "get_production_project", return_value={"id": 1, "title": "T"}):
                        with mock.patch.object(main.database, "get_latest_project_script", return_value={"id": 1}):
                            with mock.patch.object(main.database, "list_project_timeline", return_value=timeline):
                                with mock.patch.object(main.database, "list_scene_generation_jobs", return_value=[]):
                                    with mock.patch.object(main.database, "list_project_jobs", return_value=[]):
                                        result = main._execute_agent_task(task, "codex_cli")
        issues = captured["issues_detected"]
        self.assertTrue(any("cắt lại clip" in issue for issue in issues), issues)
        self.assertFalse(result["ready_for_render"])


class ShortJobIsAcceptedByTheApiTests(unittest.TestCase):
    """The worker knew the job type; the request model did not."""

    def test_the_request_model_allows_the_short_render(self) -> None:
        import typing

        allowed = set(typing.get_args(main.ProductionJobType))
        self.assertIn("render_short", allowed)

    def test_the_short_render_declares_its_provider(self) -> None:
        from youtube_monitor.production_worker import JOB_TYPES

        self.assertIn("render_short", JOB_TYPES)


if __name__ == "__main__":
    unittest.main()
