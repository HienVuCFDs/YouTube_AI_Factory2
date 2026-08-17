import unittest

from youtube_monitor.youtube_client import parse_channel_reference, parse_duration, parse_video_reference


class YouTubeClientTests(unittest.TestCase):
    def test_parse_channel_references(self):
        self.assertEqual(parse_channel_reference("UC1234567890123456789012")[0], "id")
        self.assertEqual(parse_channel_reference("@GoogleDevelopers"), ("forHandle", "@GoogleDevelopers"))
        self.assertEqual(
            parse_channel_reference("https://www.youtube.com/channel/UC1234567890123456789012"),
            ("id", "UC1234567890123456789012"),
        )
        self.assertEqual(
            parse_channel_reference("youtube.com/@GoogleDevelopers"),
            ("forHandle", "@GoogleDevelopers"),
        )

    def test_parse_iso_duration(self):
        self.assertEqual(parse_duration("PT1H2M3S"), 3723)
        self.assertEqual(parse_duration("PT45S"), 45)
        self.assertIsNone(parse_duration(None))

    def test_parse_video_references(self):
        self.assertEqual(parse_video_reference("https://www.youtube.com/watch?v=dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(parse_video_reference("https://youtu.be/dQw4w9WgXcQ?t=5"), "dQw4w9WgXcQ")
        self.assertEqual(parse_video_reference("https://www.youtube.com/shorts/dQw4w9WgXcQ"), "dQw4w9WgXcQ")


if __name__ == "__main__":
    unittest.main()
