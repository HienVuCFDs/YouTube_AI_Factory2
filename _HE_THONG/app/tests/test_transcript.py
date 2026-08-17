import tempfile
import unittest
from pathlib import Path

from youtube_monitor.database import Database
from youtube_monitor.transcript import normalize_transcript


class TranscriptTests(unittest.TestCase):
    def test_srt_is_normalized_to_plain_text(self):
        source = "1\n00:00:01,000 --> 00:00:03,000\nXin chào <b>mọi người</b>.\n"
        self.assertEqual(normalize_transcript(source, "srt"), "Xin chào mọi người.")

    def test_transcript_is_saved_as_a_version_for_video(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "test.db")
            database.upsert_channel(
                {
                    "youtube_channel_id": "UC1234567890123456789012",
                    "channel_url": "https://www.youtube.com/channel/UC1234567890123456789012",
                    "title": "Test channel",
                    "uploads_playlist_id": "UU1234567890123456789012",
                }
            )
            database.upsert_video(
                {
                    "youtube_video_id": "video-transcript-1",
                    "youtube_channel_id": "UC1234567890123456789012",
                    "video_url": "https://www.youtube.com/watch?v=video-transcript-1",
                    "title": "Transcript video",
                    "description": "Description",
                    "metadata_hash": "hash-transcript-1",
                    "raw_payload": {},
                }
            )

            saved = database.save_transcript(
                "video-transcript-1",
                "Một hai ba bốn",
                source_type="manual",
                language="vi",
            )
            self.assertEqual(saved["word_count"], 4)
            self.assertEqual(database.get_video("video-transcript-1")["has_transcript"], 1)
            self.assertEqual(database.get_transcript("video-transcript-1")["language"], "vi")


if __name__ == "__main__":
    unittest.main()
