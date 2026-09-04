"""Voice a project has already made, found again after a rebuild.

Audio is attached to a timeline row, not to the words it was spoken from, so
anything that replaces the rows loses it: cutting scenes by dialogue,
rebuilding the storyboard, rewriting the script. Measured on a real project,
that left 86 generated files on disk and not one scene with a voice, and the
app's only answer was to generate them all again.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.ui_source import studio_ui
from youtube_monitor import voice_library


class FindingWhatWasAlreadySpokenTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.work = self.root / "work" / "voiceover"
        self.audio = self.root / "audio"
        self.work.mkdir(parents=True)
        self.audio.mkdir(parents=True)

    def _voice(self, index: int, text: str, suffix: str = ".mp3") -> Path:
        (self.work / f"segment-{index:03d}.txt").write_text(text, encoding="utf-8")
        path = self.audio / f"segment-{index:03d}{suffix}"
        path.write_bytes(b"audio")
        return path

    def test_it_indexes_a_voice_by_the_words_it_was_made_from(self) -> None:
        self._voice(1, "Anh vào rừng với hai bàn tay trắng.")

        library = voice_library.index_voices(self.work, self.audio)

        self.assertEqual(len(library), 1)
        self.assertIn(voice_library.normalise("Anh vào rừng với hai bàn tay trắng."), library)

    def test_a_sidecar_with_no_audio_beside_it_is_not_offered(self) -> None:
        (self.work / "segment-009.txt").write_text("không có tiếng", encoding="utf-8")

        self.assertEqual(voice_library.index_voices(self.work, self.audio), {})

    def test_an_empty_audio_file_is_not_offered_either(self) -> None:
        (self.work / "segment-002.txt").write_text("rỗng", encoding="utf-8")
        (self.audio / "segment-002.mp3").write_bytes(b"")

        self.assertEqual(voice_library.index_voices(self.work, self.audio), {})

    def test_wav_is_found_as_readily_as_mp3(self) -> None:
        """VoxCPM writes wav and edge_tts writes mp3; both are voice."""
        self._voice(3, "giọng wav", suffix=".wav")

        self.assertEqual(len(voice_library.index_voices(self.work, self.audio)), 1)

    def test_scenes_are_matched_on_words_not_on_scene_number(self) -> None:
        """A rebuild renumbers everything; scene 3 is rarely scene 3 again."""
        self._voice(1, "Cảnh mở đầu.")
        self._voice(2, "Cảnh thứ hai.")
        library = voice_library.index_voices(self.work, self.audio)
        timeline = [
            {"id": 50, "segment_index": 1, "voice_text": "Cảnh thứ hai.", "audio_path": ""},
            {"id": 51, "segment_index": 2, "voice_text": "Cảnh mở đầu.", "audio_path": ""},
        ]

        matched, missing = voice_library.match_timeline(timeline, library)

        self.assertEqual(missing, [])
        self.assertTrue(matched[0]["audio_path"].endswith("segment-002.mp3"))
        self.assertTrue(matched[1]["audio_path"].endswith("segment-001.mp3"))

    def test_punctuation_and_case_do_not_prevent_a_match(self) -> None:
        self._voice(1, "Anh vào rừng, với hai bàn tay trắng!")
        library = voice_library.index_voices(self.work, self.audio)
        timeline = [{"id": 1, "segment_index": 1, "voice_text": "anh vào rừng với hai bàn tay trắng", "audio_path": ""}]

        matched, _ = voice_library.match_timeline(timeline, library)

        self.assertEqual(len(matched), 1)

    def test_a_scene_that_already_has_a_playable_file_is_left_alone(self) -> None:
        """Re-attaching would be a no-op at best, and a loss if it was replaced."""
        existing = self._voice(1, "đã có sẵn")
        library = voice_library.index_voices(self.work, self.audio)
        timeline = [{"id": 1, "segment_index": 1, "voice_text": "đã có sẵn", "audio_path": str(existing)}]

        matched, missing = voice_library.match_timeline(timeline, library)

        self.assertEqual(matched, [])
        self.assertEqual(missing, [])

    def test_a_scene_whose_path_points_at_a_deleted_file_is_restored(self) -> None:
        self._voice(1, "lời này")
        library = voice_library.index_voices(self.work, self.audio)
        timeline = [{"id": 1, "segment_index": 1, "voice_text": "lời này", "audio_path": "F:/da/xoa.mp3"}]

        matched, _ = voice_library.match_timeline(timeline, library)

        self.assertEqual(len(matched), 1)

    def test_words_with_no_voice_are_reported_rather_than_guessed(self) -> None:
        """Attaching the nearest file would put the wrong words in the video."""
        self._voice(1, "lời cũ")
        library = voice_library.index_voices(self.work, self.audio)
        timeline = [{"id": 1, "segment_index": 4, "voice_text": "lời hoàn toàn khác", "audio_path": ""}]

        matched, missing = voice_library.match_timeline(timeline, library)

        self.assertEqual(matched, [])
        self.assertEqual(missing[0]["segment_index"], 4)

    def test_the_newest_recording_of_the_same_words_wins(self) -> None:
        """It is the one the user last chose to make."""
        import os
        import time

        first = self._voice(1, "cùng một câu")
        time.sleep(0.01)
        second = self._voice(2, "cùng một câu")
        os.utime(second, (time.time() + 60, time.time() + 60))

        library = voice_library.index_voices(self.work, self.audio)

        self.assertEqual(len(library), 1)
        self.assertTrue(next(iter(library.values()))["audio_path"].endswith(second.name))

    def test_a_missing_directory_is_empty_rather_than_an_error(self) -> None:
        self.assertEqual(voice_library.index_voices(self.root / "no", self.root / "no"), {})


class ItIsWiredIntoTheAppTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parent.parent
        self.source = (root / "youtube_monitor" / "main.py").read_text(encoding="utf-8")
        self.page = studio_ui()

    def test_the_endpoint_exists(self) -> None:
        from youtube_monitor.main import app

        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/projects/{project_id}/timeline/reattach-voice", paths)

    def test_cutting_by_dialogue_restores_the_voice_it_can(self) -> None:
        """This rebuild cost the same voiceover three times over."""
        rebuild_at = self.source.index('database.create_project_timeline(project_id, int(script["id"]), planned, force=True)')
        after = self.source[rebuild_at:rebuild_at + 500]

        self.assertIn("_reattach_project_voice(project_id)", after)

    def test_rebuilding_the_shorts_storyboard_restores_its_voice_too(self) -> None:
        self.assertIn('_reattach_project_voice(project_id, "short")', self.source)

    def test_the_voice_step_can_attach_them_by_hand(self) -> None:
        self.assertIn("reattachStudioVoice()", self.page)
        self.assertIn("Gắn giọng đã có vào storyboard", self.page)

    def test_it_redraws_the_storyboard_so_the_play_buttons_appear(self) -> None:
        """Attaching without redrawing looks exactly like not attaching."""
        body = self.page[self.page.index("async function reattachStudioVoice"):]
        body = body[:body.index("\n  }")]

        self.assertIn("renderStudioStoryboard(", body)

    def test_it_says_when_nothing_matched_and_why(self) -> None:
        self.assertIn("lời trong storyboard đã khác", self.page)
