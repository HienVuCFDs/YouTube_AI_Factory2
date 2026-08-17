import tempfile
import unittest
from pathlib import Path

from youtube_monitor.openmontage_adapter import (
    OpenMontageAdapter,
    OpenMontageError,
    runtime_for_provider,
)


class OpenMontageAdapterTests(unittest.TestCase):
    def test_runtime_provider_overrides(self):
        self.assertEqual(runtime_for_provider("openmontage", "remotion"), "remotion")
        self.assertEqual(runtime_for_provider("openmontage_ffmpeg", "remotion"), "ffmpeg")
        self.assertEqual(runtime_for_provider("openmontage_remotion", "ffmpeg"), "remotion")
        self.assertEqual(runtime_for_provider("openmontage_hyperframes", "ffmpeg"), "hyperframes")

    def test_runtime_provider_rejects_unknown_runtime(self):
        with self.assertRaises(OpenMontageError):
            runtime_for_provider("openmontage", "unknown")

    def test_adapter_status_reports_isolated_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = OpenMontageAdapter(root, root / ".venv" / "Scripts" / "python.exe")
            status = adapter.status()
        self.assertTrue(status["enabled"])
        self.assertFalse(status["ready"])
        self.assertEqual(set(status["runtimes"]), {"ffmpeg", "remotion", "hyperframes"})

    def test_subtitle_writer_uses_timeline_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "subtitles.srt"
            OpenMontageAdapter(Path(directory))._write_subtitles(
                path,
                [{"start_seconds": 0, "end_seconds": 2.5, "subtitle_text": "Xin chao OpenMontage"}],
            )
            content = path.read_text(encoding="utf-8")
        self.assertIn("00:00:00,000 --> 00:00:02,500", content)
        self.assertIn("Xin chao OpenMontage", content)

    def test_vertical_subtitle_writer_splits_long_voiceover(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "subtitles.srt"
            OpenMontageAdapter(Path(directory))._write_subtitles(
                path,
                [{
                    "start_seconds": 0,
                    "end_seconds": 6,
                    "subtitle_text": "Một hai ba bốn năm sáu bảy tám chín mười",
                }],
                maximum_words=6,
            )
            content = path.read_text(encoding="utf-8")
        self.assertIn("Một hai ba bốn năm sáu", content)
        self.assertIn("bảy tám chín mười", content)
        self.assertIn("00:00:06,000", content)
