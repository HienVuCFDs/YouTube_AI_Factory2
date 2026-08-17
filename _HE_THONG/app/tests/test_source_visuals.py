from __future__ import annotations

import unittest

from youtube_monitor.source_visuals import _cue_for_segment, chapter_cues


class SourceVisualTests(unittest.TestCase):
    def test_extracts_chapters_and_matches_smc_topic(self) -> None:
        cues = chapter_cues("0:29 Step 1 - Directional Bias\n3:19 The Data Behind the Strategy\n9:20 Step 2 - Location")
        self.assertEqual(cues[1], (199.0, "the data behind the strategy"))
        selected = _cue_for_segment(
            {"voice_text": "Minh họa kỳ vọng và dữ liệu backtest"}, 1, cues
        )
        self.assertEqual(selected, 199.0)

    def test_director_source_cue_is_used_for_chapter_matching(self) -> None:
        cues = chapter_cues("0:29 Step 1 - Directional Bias\n3:19 The Data Behind the Strategy")
        selected = _cue_for_segment(
            {"voice_text": "Kiểm chứng trước khi vào lệnh", "visual_prompt": "[SOURCE_CUE: data] dashboard dữ liệu"},
            1,
            cues,
        )
        self.assertEqual(selected, 199.0)


if __name__ == "__main__":
    unittest.main()
