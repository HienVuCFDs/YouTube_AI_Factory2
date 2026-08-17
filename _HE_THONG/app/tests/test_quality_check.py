from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from youtube_monitor.quality_check import _parse_audio_metrics, build_quality_report, quality_report_markdown


class QualityCheckTests(unittest.TestCase):
    def test_missing_media_is_reported_without_crashing(self) -> None:
        report = build_quality_report(
            [{"segment_index": 1, "audio_path": "missing-audio.mp3", "visual_path": "missing-visual.mp4"}]
        )
        self.assertEqual(report["status"], "warning")
        self.assertFalse(report["checks"]["has_all_visuals"])
        self.assertFalse(report["checks"]["has_all_voice"])
        self.assertIn("Thiếu cảnh", quality_report_markdown(report))

    def test_existing_thumbnail_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            thumbnail = Path(directory) / "thumbnail.jpg"
            thumbnail.write_bytes(b"jpg")
            report = build_quality_report([], thumbnail_path=str(thumbnail))
        self.assertTrue(report["checks"]["has_thumbnail"])

    def test_missing_voice_does_not_report_long_silence(self) -> None:
        report = build_quality_report([{"segment_index": 1, "audio_path": "not-found.wav"}])
        self.assertTrue(report["checks"]["no_abnormal_voice_silence"])

    def test_ffmpeg_audio_metrics_are_parsed(self) -> None:
        output = '''[Parsed_volumedetect] max_volume: -1.2 dB
{
 "input_i" : "-15.98",
 "input_tp" : "-1.50"
}'''
        metrics = _parse_audio_metrics(output)
        self.assertEqual(metrics["max_volume_db"], -1.2)
        self.assertEqual(metrics["integrated_lufs"], -15.98)
        self.assertEqual(metrics["true_peak_db"], -1.5)


if __name__ == "__main__":
    unittest.main()
