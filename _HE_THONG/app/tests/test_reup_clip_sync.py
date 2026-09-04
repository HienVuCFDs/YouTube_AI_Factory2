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


class SegmentStateNamesBothHalvesTests(unittest.TestCase):
    """One status column cannot say "has voice" and "has picture" at once.

    The voiceover wrote voice_ready over the cut's asset_ready and the cut
    wrote asset_ready back, so a finished scene always read as holding only
    the half that finished last — which is what looked like losing the other.
    """

    def _database(self, directory: str):
        from youtube_monitor.database import Database

        database = Database(Path(directory) / "state.db")
        database.upsert_channel({
            "youtube_channel_id": "UC000000000000000000000C",
            "channel_url": "https://www.youtube.com/channel/UC000000000000000000000C",
            "title": "c", "uploads_playlist_id": "UU000000000000000000000C",
        })
        database.upsert_video({
            "youtube_video_id": "video-state-1",
            "youtube_channel_id": "UC000000000000000000000C",
            "video_url": "https://www.youtube.com/watch?v=video-state-1",
            "title": "t", "metadata_hash": "h", "raw_payload": {},
        })
        project = database.create_production_project("video-state-1")
        script = database.create_project_script(project["id"], script_title="s")
        timeline = database.create_project_timeline(project["id"], script["id"], [
            {"segment_index": 1, "voice_text": "a", "subtitle_text": "a", "visual_prompt": "p", "duration_seconds": 5},
            {"segment_index": 2, "voice_text": "b", "subtitle_text": "b", "visual_prompt": "p", "duration_seconds": 5},
            {"segment_index": 3, "voice_text": "c", "subtitle_text": "c", "visual_prompt": "p", "duration_seconds": 5},
        ])
        return database, timeline

    def test_a_scene_holding_both_is_marked_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, timeline = self._database(directory)
            database.update_project_timeline_segment(
                timeline[0]["id"], visual_path="C:/x/a.mp4", audio_path="C:/x/a.wav",
                status="voice_ready",
            )
            database.resync_timeline_segment_states()
            self.assertEqual(
                database.get_project_timeline_segment(timeline[0]["id"])["status"], "ready"
            )

    def test_a_scene_holding_one_half_keeps_naming_that_half(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, timeline = self._database(directory)
            database.update_project_timeline_segment(
                timeline[1]["id"], visual_path="C:/x/b.mp4", status="voice_ready"
            )
            database.update_project_timeline_segment(
                timeline[2]["id"], audio_path="C:/x/c.wav", status="asset_ready"
            )
            database.resync_timeline_segment_states()
            self.assertEqual(
                database.get_project_timeline_segment(timeline[1]["id"])["status"], "asset_ready"
            )
            self.assertEqual(
                database.get_project_timeline_segment(timeline[2]["id"])["status"], "voice_ready"
            )

    def test_running_it_twice_changes_nothing_the_second_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, timeline = self._database(directory)
            database.update_project_timeline_segment(
                timeline[0]["id"], visual_path="C:/x/a.mp4", audio_path="C:/x/a.wav",
                status="voice_ready",
            )
            self.assertEqual(database.resync_timeline_segment_states(), 1)
            self.assertEqual(database.resync_timeline_segment_states(), 0)

    def test_the_storyboard_reads_the_files_rather_than_the_label(self) -> None:
        page = (
            Path(__file__).resolve().parent.parent
            / "youtube_monitor" / "templates" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn("function segmentHaveBadges", page)
        self.assertIn("segment.visual_path", page)
        self.assertIn("segment.audio_path", page)


class ConcurrentJobsDoNotEraseEachOtherTests(unittest.TestCase):
    """Cutting the scene and generating its voice run at the same time.

    The update used to read the whole row, merge, and write all nine columns
    back. Two jobs each read before the other had written, so whichever
    finished last restored an empty path for the half it had never seen — the
    picture and the voice took turns erasing each other, which is what looked
    like the storyboard losing one of them.
    """

    def _segment(self, directory: str):
        from youtube_monitor.database import Database

        database = Database(Path(directory) / "race.db")
        database.upsert_channel({
            "youtube_channel_id": "UC000000000000000000000D",
            "channel_url": "https://www.youtube.com/channel/UC000000000000000000000D",
            "title": "c", "uploads_playlist_id": "UU000000000000000000000D",
        })
        database.upsert_video({
            "youtube_video_id": "video-race-1",
            "youtube_channel_id": "UC000000000000000000000D",
            "video_url": "https://www.youtube.com/watch?v=video-race-1",
            "title": "t", "metadata_hash": "h", "raw_payload": {},
        })
        project = database.create_production_project("video-race-1")
        script = database.create_project_script(project["id"], script_title="s")
        timeline = database.create_project_timeline(project["id"], script["id"], [
            {"segment_index": 1, "voice_text": "a", "subtitle_text": "a",
             "visual_prompt": "p", "duration_seconds": 5},
        ])
        return database, int(project["id"]), int(timeline[0]["id"])

    def test_the_voice_written_last_keeps_the_picture_written_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id, segment_id = self._segment(directory)
            # Both jobs read the row here, before either has written.
            database.get_project_timeline_segment(segment_id)
            database.get_project_timeline_segment(segment_id)
            database.update_project_timeline_segment(segment_id, visual_path="C:/x/clip.mp4")
            database.update_project_timeline_segment(segment_id, audio_path="C:/x/voice.wav")
            row = database.get_project_timeline_segment(segment_id)
            self.assertEqual(row["visual_path"], "C:/x/clip.mp4")
            self.assertEqual(row["audio_path"], "C:/x/voice.wav")

    def test_the_picture_written_last_keeps_the_voice_written_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id, segment_id = self._segment(directory)
            database.update_project_timeline_segment(segment_id, audio_path="C:/x/voice.wav")
            database.update_project_timeline_segment(segment_id, visual_path="C:/x/clip.mp4")
            row = database.get_project_timeline_segment(segment_id)
            self.assertEqual(row["audio_path"], "C:/x/voice.wav")
            self.assertEqual(row["visual_path"], "C:/x/clip.mp4")

    def test_an_update_leaves_every_column_it_was_not_given(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, _project_id, segment_id = self._segment(directory)
            database.update_project_timeline_segment(
                segment_id, audio_path="C:/x/voice.wav", subtitle_text="phu de",
            )
            database.update_project_timeline_segment(segment_id, visual_path="C:/x/clip.mp4")
            row = database.get_project_timeline_segment(segment_id)
            self.assertEqual(row["subtitle_text"], "phu de")
            self.assertEqual(row["voice_text"], "a")

    def test_an_update_with_nothing_to_change_is_harmless(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, _project_id, segment_id = self._segment(directory)
            database.update_project_timeline_segment(segment_id, audio_path="C:/x/voice.wav")
            row = database.update_project_timeline_segment(segment_id)
            self.assertEqual(row["audio_path"], "C:/x/voice.wav")

    def test_a_scene_holding_both_ends_up_ready_whichever_finished_last(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id, segment_id = self._segment(directory)
            database.update_project_timeline_segment(segment_id, visual_path="C:/x/clip.mp4")
            database.update_project_timeline_segment(segment_id, audio_path="C:/x/voice.wav")
            database.resync_timeline_segment_states(project_id)
            self.assertEqual(
                database.get_project_timeline_segment(segment_id)["status"], "ready"
            )


class DialogueCutWarnsWhatItDestroysTests(unittest.TestCase):
    """Cutting by dialogue rebuilds from the source transcript.

    It drops whatever is attached to the current timeline, and its narration
    comes from the transcript rather than from any script that was written.
    The confirm said only "the timeline will be replaced", which cost a user
    twenty minutes of voice they had just generated.
    """

    def setUp(self) -> None:
        self.page = (
            Path(__file__).resolve().parent.parent
            / "youtube_monitor" / "templates" / "index.html"
        ).read_text(encoding="utf-8")

    def test_the_warning_counts_the_work_that_will_be_lost(self) -> None:
        self.assertIn("const withVoice = current.filter", self.page)
        self.assertIn("const withVisual = current.filter", self.page)
        self.assertIn("Phải tạo lại từ đầu", self.page)

    def test_the_warning_says_where_the_words_will_come_from(self) -> None:
        self.assertIn("TRANSCRIPT của video gốc", self.page)
        self.assertIn("KHÔNG phải từ kịch bản", self.page)

    def test_it_still_asks_before_replacing_anything(self) -> None:
        self.assertIn("if (!confirm(warning)) return;", self.page)


class DialogueCutRefusesToDestroyVoiceTests(unittest.TestCase):
    """A confirm in the page cannot protect a browser left open on old code.

    Cutting by dialogue replaces every scene. One user lost the same
    twenty-minute voiceover to it three times, because their page still
    showed the previous, vaguer wording. The server refuses now.
    """

    def _timeline(self, voiced: int):
        return [
            {"id": i, "segment_index": i, "audio_path": "C:/x/v.mp3" if i <= voiced else ""}
            for i in range(1, 4)
        ]

    def _call(self, voiced: int, force: bool = False):
        with mock.patch.object(main.database, "get_production_project", return_value={"id": 1, "youtube_video_id": "v"}):
            with mock.patch.object(main.database, "get_latest_project_script", return_value={"id": 9}):
                with mock.patch.object(main.database, "list_project_timeline", return_value=self._timeline(voiced)):
                    with mock.patch.object(main.database, "get_video_analysis", return_value=None):
                        return main.build_timeline_from_dialogue(1, force=force)

    def test_it_refuses_when_scenes_already_carry_voice(self) -> None:
        with self.assertRaises(main.HTTPException) as ctx:
            self._call(voiced=2)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("2 cảnh đã có giọng đọc", ctx.exception.detail)

    def test_it_says_the_words_revert_to_the_transcript(self) -> None:
        with self.assertRaises(main.HTTPException) as ctx:
            self._call(voiced=1)
        self.assertIn("transcript", ctx.exception.detail)

    def test_force_gets_past_it(self) -> None:
        """Forced, it fails later for want of a transcript - not on the guard."""
        with self.assertRaises(main.HTTPException) as ctx:
            self._call(voiced=2, force=True)
        self.assertNotEqual(ctx.exception.status_code, 409)

    def test_it_refuses_even_when_no_voice_has_been_made_yet(self) -> None:
        """This test used to assert the opposite, and it was wrong.

        Losing a voiceover is not the only damage. Cutting by dialogue fills
        every scene with the source's own transcript, so a project whose
        script was written in another language ends up narrating the original
        - in the original language, transcription errors included. With no
        voice attached there was nothing for the guard to find, so that
        happened in silence, and the finished storyboard read as Vietnamese
        for an English script.
        """
        with self.assertRaises(main.HTTPException) as ctx:
            self._call(voiced=0)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("3 cảnh hiện có sẽ bị thay hết", ctx.exception.detail)

    def test_an_empty_timeline_has_nothing_to_protect(self) -> None:
        """The first cut on a fresh project must not need confirming."""
        with mock.patch.object(main.database, "get_production_project", return_value={"id": 1, "youtube_video_id": "v"}):
            with mock.patch.object(main.database, "get_latest_project_script", return_value={"id": 9}):
                with mock.patch.object(main.database, "list_project_timeline", return_value=[]):
                    with mock.patch.object(main.database, "get_video_analysis", return_value=None):
                        with self.assertRaises(main.HTTPException) as ctx:
                            main.build_timeline_from_dialogue(1, force=False)

        self.assertNotEqual(ctx.exception.status_code, 409)

    def test_the_page_confirms_before_it_forces(self) -> None:
        """And it asks with the server's words, not its own.

        The page used to force on every call, so the refusal it was meant to
        surface never reached anyone.
        """
        page = (
            Path(__file__).resolve().parent.parent
            / "youtube_monitor" / "templates" / "index.html"
        ).read_text(encoding="utf-8")

        confirm_at = page.index("Vẫn cắt lại theo lời thoại?")
        call_at = page.index("timeline/from-dialogue?force=true")

        self.assertLess(confirm_at, call_at)
        self.assertEqual(page.count("timeline/from-dialogue?force=true"), 1)


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
