from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from youtube_monitor.subtitle_builder import subtitle_chunks, write_segment_srt


class SubtitleBuilderTests(unittest.TestCase):
    def test_long_line_is_split_into_readable_chunks(self) -> None:
        chunks = subtitle_chunks("một hai ba bốn năm sáu bảy tám chín mười mười một mười hai", maximum_words=4)
        self.assertEqual(chunks, ["một hai ba bốn", "năm sáu bảy tám", "chín mười mười một", "mười hai"])

    def test_srt_spans_the_whole_audio_duration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = write_segment_srt(Path(directory) / "segment.srt", "Câu đầu tiên. Câu thứ hai dài hơn.", 10.0)
            content = output.read_text(encoding="utf-8")
        self.assertIn("00:00:00,000", content)
        self.assertIn("00:00:10,000", content)
        self.assertIn("Câu đầu tiên.", content)


if __name__ == "__main__":
    unittest.main()
