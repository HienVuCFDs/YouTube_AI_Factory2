"""A file is what its streams say, not what its name claims.

An extension is a promise. A .mp4 that is really an .m4a, a download that
stopped halfway, an "audio" file with no audio track - each passes a suffix
check and then fails much later, inside a render or a voiceover, with an
FFmpeg error the user cannot act on.

The same probe answers the other question the app needs: whether the source
is a film to cut pictures from or a recording to put a voice over. Getting
that wrong is what makes "cut scenes from the source" fail on a podcast.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from youtube_monitor.ffmpeg_renderer import resolve_ffmpeg
from youtube_monitor.media_probe import (
    AUDIO_KIND,
    BROKEN_KIND,
    VIDEO_KIND,
    describe,
    probe_media,
    reject_reason,
)


class RealFilesTests(unittest.TestCase):
    """These touch FFmpeg because the whole point is the real streams."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._executable = resolve_ffmpeg("ffmpeg")
        if not cls._executable:
            raise unittest.SkipTest("FFmpeg không có trên máy chạy test")
        cls._dir = tempfile.TemporaryDirectory()
        root = Path(cls._dir.name)
        subprocess.run(
            [cls._executable, "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc=d=1:s=320x240",
             "-f", "lavfi", "-i", "sine=d=1", "-shortest", str(root / "phim.mp4")],
            check=True, capture_output=True,
        )
        subprocess.run(
            [cls._executable, "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", "sine=d=1", str(root / "tieng.m4a")],
            check=True, capture_output=True,
        )
        # The case that gets through every name-based check.
        (root / "gia.mp4").write_bytes((root / "tieng.m4a").read_bytes())
        (root / "hong.mp4").write_text("day khong phai video", encoding="utf-8")
        (root / "rong.mp4").write_bytes(b"")
        cls.root = root

    @classmethod
    def tearDownClass(cls) -> None:
        cls._dir.cleanup()

    def test_a_real_video_reads_as_a_video(self) -> None:
        probe = probe_media(self.root / "phim.mp4")

        self.assertTrue(probe["ok"])
        self.assertEqual(probe["kind"], VIDEO_KIND)
        self.assertTrue(probe["has_video"])
        self.assertTrue(probe["has_audio"])
        self.assertEqual((probe["width"], probe["height"]), (320, 240))

    def test_an_audio_file_renamed_to_mp4_is_still_audio(self) -> None:
        probe = probe_media(self.root / "gia.mp4")

        self.assertEqual(probe["kind"], AUDIO_KIND)
        self.assertFalse(probe["has_video"])

    def test_it_is_refused_as_a_video_source_with_a_usable_reason(self) -> None:
        reason = reject_reason(probe_media(self.root / "gia.mp4"), VIDEO_KIND)

        self.assertIn("chỉ có tiếng", reason)
        self.assertIn("audio", reason)

    def test_a_text_file_renamed_to_mp4_is_broken(self) -> None:
        probe = probe_media(self.root / "hong.mp4")

        self.assertEqual(probe["kind"], BROKEN_KIND)
        self.assertFalse(probe["ok"])

    def test_the_reason_does_not_repeat_the_path_back_at_the_user(self) -> None:
        """ffprobe leads with the whole filename, burying the actual cause."""
        probe = probe_media(self.root / "hong.mp4")

        self.assertNotIn(str(self.root), probe["error"])
        self.assertIn("Invalid data", probe["error"])

    def test_an_empty_file_says_the_download_may_be_unfinished(self) -> None:
        probe = probe_media(self.root / "rong.mp4")

        self.assertIn("0 byte", probe["error"])

    def test_a_missing_file_is_a_result_not_an_exception(self) -> None:
        probe = probe_media(self.root / "khong-co.mp4")

        self.assertFalse(probe["ok"])
        self.assertIn("Không tìm thấy", probe["error"])

    def test_describe_says_something_a_person_can_read(self) -> None:
        self.assertIn("320x240", describe(probe_media(self.root / "phim.mp4")))
        self.assertIn("Chỉ có tiếng", describe(probe_media(self.root / "tieng.m4a")))

    def test_an_audio_file_is_accepted_as_audio(self) -> None:
        self.assertEqual(reject_reason(probe_media(self.root / "tieng.m4a"), AUDIO_KIND), "")

    def test_a_video_is_accepted_as_a_video(self) -> None:
        self.assertEqual(reject_reason(probe_media(self.root / "phim.mp4"), VIDEO_KIND), "")


class UploadRefusesWhatItCannotUseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = (
            Path(__file__).resolve().parent.parent / "youtube_monitor" / "main.py"
        ).read_text(encoding="utf-8")

    def test_the_upload_probes_before_it_keeps_the_file(self) -> None:
        self.assertIn("reason = reject_reason(media, asset_type)", self.source)
        self.assertIn("target.unlink(missing_ok=True)", self.source)

    def test_the_same_file_twice_is_not_stored_twice(self) -> None:
        """Matched on content: the second copy usually has a different name."""
        self.assertIn('if str(item.get("sha256") or "") == checksum', self.source)
        self.assertIn('"status": "duplicate"', self.source)


class AnAudioSourceCannotHaveScenesCutFromItTests(unittest.TestCase):
    """The reup workflow cuts pictures out of the source.

    A podcast or a music track has no pictures, and the pipeline used to hand
    one to FFmpeg anyway and fail deep inside the cut.
    """

    def setUp(self) -> None:
        root = Path(__file__).resolve().parent.parent / "youtube_monitor"
        self.main = (root / "main.py").read_text(encoding="utf-8")
        self.worker = (root / "production_worker.py").read_text(encoding="utf-8")

    def test_the_kind_is_recorded_when_the_source_is_downloaded(self) -> None:
        self.assertIn("_source_media_kind(", self.main)
        self.assertIn("def _source_media_kind(path: Path) -> str:", self.main)

    def test_the_job_is_refused_before_it_is_even_queued(self) -> None:
        self.assertIn("chỉ có tiếng, không có hình", self.main)

    def test_the_worker_refuses_it_too(self) -> None:
        """The queue guard is not the only caller the worker can get a job from."""
        self.assertIn('if kind and kind != "video":', self.worker)
        self.assertIn("không có hình (chỉ có tiếng)", self.worker)

    def test_an_unknown_kind_is_measured_rather_than_assumed(self) -> None:
        """Projects downloaded before the column existed have no kind yet."""
        self.assertIn("database.set_video_media_kind(", self.worker)

    def test_the_database_keeps_the_kind_with_the_file(self) -> None:
        database = (
            Path(__file__).resolve().parent.parent / "youtube_monitor" / "database.py"
        ).read_text(encoding="utf-8")

        self.assertIn('"videos", "media_kind"', database)
        self.assertIn("def set_video_media_kind", database)
