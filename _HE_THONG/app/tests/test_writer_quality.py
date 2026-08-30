from __future__ import annotations

import unittest

from youtube_monitor.folklore_research import source_animal
from youtube_monitor.writer import WriterError, parse_duration_text, resolve_target_duration_seconds, validate_voiceover_plan


class WriterQualityTests(unittest.TestCase):
    def test_extracts_animal_from_vietnamese_origin_story_title(self):
        self.assertEqual(source_animal("Sự Tích Con Rết | Truyện cổ tích"), "rết")

    def test_reads_twelve_minutes_from_prompt_when_duration_is_empty(self):
        self.assertEqual(resolve_target_duration_seconds(None, "Kể chuyện trong 12 phút, lời dẫn chi tiết."), 720)

    def test_explicit_duration_has_priority_over_prompt(self):
        self.assertEqual(resolve_target_duration_seconds(300, "Kể chuyện trong 12 phút."), 300)

    def test_parses_human_duration_formats(self):
        self.assertEqual(parse_duration_text("00:12:00"), 720)
        self.assertEqual(parse_duration_text("12:30"), 750)
        self.assertEqual(parse_duration_text("1 giờ 12 phút 30 giây"), 4350)

    def test_duration_text_overrides_prompt_duration(self):
        self.assertEqual(resolve_target_duration_seconds(None, "Kể trong 10 phút", "00:12:00"), 720)

    def test_source_duration_is_used_when_user_leaves_duration_blank(self):
        self.assertEqual(resolve_target_duration_seconds(None, "Viết truyện mới", "", 735), 735)

    def test_warns_for_short_voiceover_without_rejecting_script(self):
        content = {
            "scene_blueprints": [
                {"duration_seconds": 60, "narration": "Một câu rất ngắn."},
                {"duration_seconds": 60, "narration": "Một câu rất ngắn khác."},
            ]
        }
        warnings = validate_voiceover_plan(content, 120)
        self.assertTrue(warnings)
        self.assertIn("Lời dẫn", " ".join(warnings))

    def test_accepts_duration_and_voiceover_that_meet_plan(self):
        narration = " ".join(["Mèo nhỏ đi qua khu vườn, quan sát kỹ mọi dấu vết, kể lại điều mình hiểu và tiếp tục tìm nguyên nhân của sự việc."] * 10)
        content = {
            "scene_blueprints": [
                {"duration_seconds": 45, "narration": narration},
                {"duration_seconds": 45, "narration": narration},
            ]
        }
        validate_voiceover_plan(content, 90)

    def test_accepts_voiceover_within_duration_tolerance(self):
        content = {
            "scene_blueprints": [
                {"duration_seconds": 60, "narration": " ".join(["lời"] * 172)},
            ]
        }
        # 172 words is 95.5% of the 180-word target for one minute.
        validate_voiceover_plan(content, 60)

class ScriptLengthWarningReachesTheUserTests(unittest.TestCase):
    """The writer's output is measured against the requested length already.

    A reup script came back half the length of the 9.6 minute source, which
    became a 4.6 minute video — found only after a voiceover and a render,
    because the warning was computed, returned, and never displayed.
    """

    def setUp(self) -> None:
        from pathlib import Path

        self.page = (
            Path(__file__).resolve().parent.parent
            / "youtube_monitor" / "templates" / "index.html"
        ).read_text(encoding="utf-8")

    def test_the_page_has_somewhere_to_show_them(self) -> None:
        self.assertIn('id="studioWriterWarnings"', self.page)

    def test_the_writer_response_is_checked_for_them(self) -> None:
        self.assertIn("reportScriptLengthWarnings(response);", self.page)
        self.assertIn("quality_warnings", self.page)

    def test_it_explains_what_governs_the_length(self) -> None:
        self.assertIn("số cảnh của storyboard bằng số đoạn trong kịch bản", self.page)

    def test_a_short_script_is_still_reported_by_the_validator(self) -> None:
        from youtube_monitor.writer import validate_voiceover_plan

        content = {"scene_blueprints": [
            {"narration": "mot cau rat ngan", "duration_seconds": 5},
        ]}
        warnings = validate_voiceover_plan(content, target_duration_seconds=575)
        self.assertTrue(warnings)
        self.assertTrue(any("575" in w for w in warnings), warnings)
