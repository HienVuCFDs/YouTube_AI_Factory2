"""Letting whoever is directing actually look at the video.

An orchestrator could queue every step, approve a plan and start a render
without ever seeing a frame. These tests cover the one image that fixes that:
what it samples, and what it refuses rather than returning something empty.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from youtube_monitor import contact_sheet


class WhatTheSheetSamplesTests(unittest.TestCase):
    def test_a_long_video_and_a_short_one_both_give_the_same_tile_count(self) -> None:
        """The sample rate comes from the video's own length, so a ten second
        clip is not reduced to one tile and a ten minute one to hundreds."""
        short = contact_sheet.video_command(
            Path("a.mp4"), Path("out.jpg"), ffmpeg="ffmpeg", tiles=12, duration_seconds=10,
        )
        long = contact_sheet.video_command(
            Path("a.mp4"), Path("out.jpg"), ffmpeg="ffmpeg", tiles=12, duration_seconds=600,
        )

        self.assertIn("fps=12/10.000", " ".join(short))
        self.assertIn("fps=12/600.000", " ".join(long))
        self.assertIn("tile=4x3", " ".join(short))

    def test_an_unknown_length_is_refused_rather_than_guessed(self) -> None:
        """One frame a second returns the opening seconds of the film in a
        sheet indistinguishable from one of the whole film, so a reader
        reports confidently on footage they never saw."""
        with self.assertRaises(contact_sheet.ContactSheetError):
            contact_sheet.video_command(
                Path("a.mp4"), Path("out.jpg"), ffmpeg="ffmpeg", tiles=6, duration_seconds=0,
            )

    def test_the_length_is_measured_when_the_caller_does_not_know_it(self) -> None:
        """A caller that omits the length still gets the whole film sampled."""
        with TemporaryDirectory() as folder:
            video = Path(folder) / "clip.mp4"
            video.write_bytes(b"x")
            recorded: list[list[str]] = []

            def capture(command, **kwargs):
                recorded.append(command)
                Path(command[-1]).write_bytes(b"sheet")
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch.object(contact_sheet, "media_duration_seconds", return_value=70.4),                     mock.patch.object(contact_sheet.subprocess, "run", side_effect=capture):
                contact_sheet.from_video(video, Path(folder) / "out.jpg", ffmpeg="ffmpeg", tiles=12)

        self.assertIn("fps=12/70.400", " ".join(recorded[0]))

    def test_the_grid_never_asks_for_more_columns_than_there_are_tiles(self) -> None:
        command = contact_sheet.stills_command(Path("d"), Path("out.jpg"), ffmpeg="ffmpeg", count=2)

        self.assertIn("tile=2x1", " ".join(command))

    def test_a_sheet_is_capped_so_it_stays_readable(self) -> None:
        command = contact_sheet.video_command(
            Path("a.mp4"), Path("out.jpg"), ffmpeg="ffmpeg", tiles=500, duration_seconds=60,
        )

        self.assertIn(f"fps={contact_sheet.MAX_TILES}/60.000", " ".join(command))


class WhatItRefusesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def test_a_missing_video_is_named_rather_than_handed_to_ffmpeg(self) -> None:
        with self.assertRaises(contact_sheet.ContactSheetError) as raised:
            contact_sheet.from_video(self.root / "gone.mp4", self.root / "out.jpg", ffmpeg="ffmpeg")

        self.assertIn("Không tìm thấy video", str(raised.exception))

    def test_a_storyboard_with_no_pictures_yet_says_so(self) -> None:
        with self.assertRaises(contact_sheet.ContactSheetError) as raised:
            contact_sheet.from_scene_visuals([self.root / "a.png"], self.root / "out.jpg", ffmpeg="ffmpeg")

        self.assertIn("Chưa cảnh nào có hình", str(raised.exception))

    def test_an_empty_file_does_not_count_as_a_picture(self) -> None:
        empty = self.root / "empty.png"
        empty.write_bytes(b"")

        with self.assertRaises(contact_sheet.ContactSheetError):
            contact_sheet.from_scene_visuals([empty], self.root / "out.jpg", ffmpeg="ffmpeg")

    def test_ffmpeg_failing_reports_what_ffmpeg_said(self) -> None:
        video = self.root / "clip.mp4"
        video.write_bytes(b"not really a video")

        with mock.patch.object(
            contact_sheet.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 1, "", "Invalid data found"),
        ):
            with self.assertRaises(contact_sheet.ContactSheetError) as raised:
                contact_sheet.from_video(
                    video, self.root / "out.jpg", ffmpeg="ffmpeg", duration_seconds=12.0)

        self.assertIn("Invalid data found", str(raised.exception))

    def test_a_missing_ffmpeg_is_reported_as_such(self) -> None:
        video = self.root / "clip.mp4"
        video.write_bytes(b"x")

        with mock.patch.object(contact_sheet.subprocess, "run", side_effect=OSError("not found")):
            with self.assertRaises(contact_sheet.ContactSheetError) as raised:
                contact_sheet.from_video(
                    video, self.root / "out.jpg", ffmpeg="ffmpeg", duration_seconds=12.0)

        self.assertIn("Không chạy được ffmpeg", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
