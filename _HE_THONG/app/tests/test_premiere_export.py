import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from youtube_monitor.premiere_export import (
    build_premiere_export_package,
    timeline_to_srt,
    timeline_to_premiere_xml,
)


class PremiereExportTests(unittest.TestCase):
    def test_srt_and_xml_use_timeline_ranges(self):
        timeline = [
            {
                "segment_index": 1,
                "start_seconds": 0,
                "end_seconds": 8,
                "duration_seconds": 8,
                "voice_text": "Opening line",
                "subtitle_text": "Opening line",
                "audio_path": "",
                "visual_path": "",
            }
        ]
        self.assertIn("00:00:00,000 --> 00:00:08,000", timeline_to_srt(timeline))
        xml = timeline_to_premiere_xml({"id": 1, "title": "Project"}, {"id": 2}, timeline)
        self.assertIn('<xmeml version="5">', xml)
        self.assertIn("Project", xml)

    def test_export_pack_copies_assets_and_writes_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "voice.wav"
            visual = root / "visual.mp4"
            source = root / "source.mp4"
            audio.write_bytes(b"audio")
            visual.write_bytes(b"visual")
            source.write_bytes(b"source")
            package = build_premiere_export_package(
                {"id": 3, "title": "Project"},
                {"id": 4, "script_title": "Script"},
                [
                    {
                        "segment_index": 1,
                        "section": "hook",
                        "start_seconds": 0,
                        "end_seconds": 8,
                        "duration_seconds": 8,
                        "voice_text": "Opening line",
                        "subtitle_text": "Opening line",
                        "audio_path": str(audio),
                        "visual_path": str(visual),
                    }
                ],
                {"local_media_path": str(source)},
                root / "artifacts",
            )
            self.assertEqual(package["missing_assets"], [])
            manifest = json.loads(Path(package["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["manifest_version"], "youtube_ai_factory.premiere.v1")
            self.assertTrue(Path(package["sequence_xml_path"]).is_file())
            self.assertTrue(Path(package["subtitle_path"]).is_file())
            with zipfile.ZipFile(package["zip_path"]) as archive:
                names = set(archive.namelist())
            self.assertIn("premiere_export/premiere_sequence.xml", names)
            self.assertIn("premiere_export/subtitles.srt", names)
            self.assertIn("premiere_export/media/audio/segment-001.wav", names)


if __name__ == "__main__":
    unittest.main()
