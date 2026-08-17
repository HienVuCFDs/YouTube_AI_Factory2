import unittest

from youtube_monitor.transcriber import build_srt


class TranscriberTests(unittest.TestCase):
    def test_build_srt_formats_segments_with_timestamps(self):
        segments = [
            {"start": 0.0, "end": 1.5, "text": " Xin chào "},
            {"start": 1.5, "end": 63.25, "text": "Cảm ơn đã theo dõi."},
        ]
        srt = build_srt(segments)
        self.assertEqual(
            srt,
            "1\n"
            "00:00:00,000 --> 00:00:01,500\n"
            "Xin chào\n\n"
            "2\n"
            "00:00:01,500 --> 00:01:03,250\n"
            "Cảm ơn đã theo dõi.",
        )

    def test_build_srt_with_no_segments_is_empty(self):
        self.assertEqual(build_srt([]), "")


if __name__ == "__main__":
    unittest.main()
