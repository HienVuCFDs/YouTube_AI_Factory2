"""Measuring what is left of the source before the video goes out.

The platform's reused-content policy is not about credit; it is about how
much of the original is still there and how much was added. That is a
question of numbers - seconds of borrowed picture, whether its audio came
too, how much of the narration is the source's own words - so the numbers are
taken first and the model is asked to weigh them, never to guess them.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from youtube_monitor.reuse_check import (
    HEAVY_REUSE_SHARE,
    SAME_NARRATION_OVERLAP,
    measure_reuse,
    narration_overlap,
    rule_findings,
    rule_verdict,
)
from tests.ui_source import studio_ui


SOURCE = {"title": "Cabin in the woods", "duration_seconds": 700, "license": ""}
TRANSCRIPT = "anh vào rừng dựng một căn lều nhỏ bằng gỗ và đất sét trong ba mươi ngày"


def _scene(index: int, seconds: int, *, from_source: bool = True, voice: str = "", cleanups: str = "[]") -> dict:
    return {
        "segment_index": index,
        "duration_seconds": seconds,
        "visual_path": (
            rf"F:\proj\03_TAI_NGUYEN\source_clips\source-segment-{index:03d}.mp4"
            if from_source else rf"F:\proj\assets\scene-{index:03d}.png"
        ),
        "voice_text": voice,
        "edit_cleanups": cleanups,
    }


class WhatIsMeasuredTests(unittest.TestCase):
    def test_it_counts_the_seconds_that_came_from_the_source(self) -> None:
        timeline = [
            _scene(1, 10), _scene(2, 10),
            _scene(3, 20, from_source=False),
        ]

        facts = measure_reuse(timeline, source_video=SOURCE)

        self.assertEqual(facts["source_seconds"], 20)
        self.assertEqual(facts["total_seconds"], 40)
        self.assertEqual(facts["source_share"], 0.5)
        self.assertEqual(facts["source_scenes"], 2)

    def test_a_project_that_drew_its_own_pictures_borrows_nothing(self) -> None:
        facts = measure_reuse([_scene(1, 10, from_source=False)], source_video=SOURCE)

        self.assertEqual(facts["source_share"], 0.0)
        self.assertEqual(facts["source_scenes"], 0)

    def test_it_notices_scenes_whose_marks_were_never_covered(self) -> None:
        timeline = [
            _scene(1, 5, cleanups='[{"kind": "subtitle", "position": "bottom_center"}]'),
            _scene(2, 5, cleanups="[]"),
            _scene(3, 5, cleanups='[{"kind": "none", "source": "user_cleared"}]'),
        ]

        facts = measure_reuse(timeline, source_video=SOURCE)

        self.assertEqual(facts["scenes_with_marks_uncovered"], 2)

    def test_reusing_the_sources_headline_is_recorded(self) -> None:
        facts = measure_reuse(
            [_scene(1, 5)], source_video=SOURCE,
            publish_title="Cabin in the woods — full build",
        )

        self.assertTrue(facts["reuses_source_title"])

    def test_a_title_of_its_own_is_not(self) -> None:
        facts = measure_reuse(
            [_scene(1, 5)], source_video=SOURCE, publish_title="Ba mươi ngày giữa rừng",
        )

        self.assertFalse(facts["reuses_source_title"])


class NarrationOverlapTests(unittest.TestCase):
    """Catches a narration that is the transcript lightly reworded."""

    def test_reading_the_transcript_back_scores_high(self) -> None:
        self.assertGreaterEqual(narration_overlap(TRANSCRIPT, TRANSCRIPT), 0.9)

    def test_a_narration_of_its_own_scores_low(self) -> None:
        written = "He left the city with nothing but an axe and a tarpaulin"

        self.assertLess(narration_overlap(written, TRANSCRIPT), SAME_NARRATION_OVERLAP)

    def test_an_empty_transcript_cannot_accuse_anyone(self) -> None:
        """Reading the wrong database column made this vacuous once already.

        The transcript lives in content_text; asking for text returned an
        empty string, so every project scored 0% overlap and the check
        silently passed whatever it was given.
        """
        self.assertEqual(narration_overlap("bất kỳ lời nào", ""), 0.0)


class WhatTheNumbersAlreadySayTests(unittest.TestCase):
    def _facts(self, **overrides) -> dict:
        base = {
            "total_seconds": 100.0, "source_seconds": 100.0, "source_share": 1.0,
            "source_scenes": 10, "scene_count": 10, "carries_source_audio": False,
            "scenes_with_marks_uncovered": 0, "narration_overlap": 0.05,
            "narration_words": 300, "publish_language": "en", "source_license": "",
            "source_duration_seconds": 700.0, "reuses_source_title": False,
            "source_title": "Cabin in the woods",
        }
        base.update(overrides)
        return base

    def test_borrowed_footage_with_a_narration_of_its_own_is_not_the_alarm(self) -> None:
        """Every reup is ~100% source footage; an always-on alarm is ignored.

        What separates an accepted retelling from reused content is what was
        added, so the severity follows the narration rather than the footage.
        """
        findings = rule_findings(self._facts())

        self.assertEqual(rule_verdict(findings), "medium")
        self.assertEqual([item["code"] for item in findings], ["reused_footage"])

    def test_borrowed_footage_read_over_with_the_sources_own_words_is(self) -> None:
        findings = rule_findings(self._facts(narration_overlap=0.91))

        self.assertEqual(rule_verdict(findings), "high")
        self.assertIn("reused_footage", [item["code"] for item in findings])

    def test_borrowed_footage_with_no_narration_at_all_is(self) -> None:
        findings = rule_findings(self._facts(narration_words=0))

        self.assertEqual(rule_verdict(findings), "high")

    def test_keeping_the_sources_audio_is_always_serious(self) -> None:
        findings = rule_findings(self._facts(carries_source_audio=True))

        self.assertEqual(rule_verdict(findings), "high")
        self.assertIn("source_audio", [item["code"] for item in findings])

    def test_uncovered_logos_are_reported_with_where_to_fix_them(self) -> None:
        findings = rule_findings(self._facts(scenes_with_marks_uncovered=4))
        marks = next(item for item in findings if item["code"] == "source_marks")

        self.assertIn("4/10", marks["detail"])
        self.assertIn("Storyboard", marks["fix"])

    def test_an_original_video_raises_nothing(self) -> None:
        clean = self._facts(source_share=0.0, source_scenes=0, source_seconds=0.0)

        self.assertEqual(rule_findings(clean), [])
        self.assertEqual(rule_verdict([]), "low")

    def test_every_finding_says_what_to_do_about_it(self) -> None:
        findings = rule_findings(self._facts(
            narration_overlap=0.91, carries_source_audio=True,
            scenes_with_marks_uncovered=2, reuses_source_title=True,
        ))

        self.assertGreaterEqual(len(findings), 4)
        for item in findings:
            with self.subTest(code=item["code"]):
                self.assertTrue(item["fix"].strip())
                self.assertTrue(item["detail"].strip())

    def test_the_reuse_threshold_is_not_so_low_it_flags_a_short_clip(self) -> None:
        self.assertGreaterEqual(HEAVY_REUSE_SHARE, 0.5)


class TheCheckIsReachableBeforePublishingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page = studio_ui()

    def test_the_endpoint_exists(self) -> None:
        from youtube_monitor.main import app

        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/projects/{project_id}/copyright-check", paths)

    def test_it_sits_on_the_publish_step(self) -> None:
        import re

        position = self.page.index('id="studioCopyrightPanel"')
        enclosing = None
        for match in re.finditer(r'<div id="(studioStep\d)"', self.page[:position]):
            enclosing = match.group(1)

        self.assertEqual(enclosing, "studioStep7")

    def test_both_videos_can_be_checked_separately(self) -> None:
        self.assertIn("['long', 'short'].map((variant)", self.page)
        self.assertIn("runCopyrightCheck(", self.page)

    def test_the_panel_is_drawn_and_not_merely_defined(self) -> None:
        self.assertIn("renderCopyrightPanel();", self.page)

    def test_publishing_unchecked_or_high_risk_asks_first(self) -> None:
        """Their channel, their call - but not by nobody mentioning it."""
        self.assertIn("Chưa kiểm tra bản quyền cho bản này", self.page)
        self.assertIn("RỦI RO CAO", self.page)

    def test_a_reassuring_model_cannot_lower_a_measured_verdict(self) -> None:
        source = (
            Path(__file__).resolve().parent.parent / "youtube_monitor" / "main.py"
        ).read_text(encoding="utf-8")

        self.assertIn('if order.get(model_verdict, -1) > order[verdict]:', source)

    def test_it_reads_the_transcript_column_that_holds_the_text(self) -> None:
        source = (
            Path(__file__).resolve().parent.parent / "youtube_monitor" / "main.py"
        ).read_text(encoding="utf-8")

        self.assertIn('transcript.get("content_text")', source)
