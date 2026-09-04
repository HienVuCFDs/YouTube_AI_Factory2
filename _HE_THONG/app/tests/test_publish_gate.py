"""Everything that has to be true before a video goes out, in one answer.

Each of these was already knowable somewhere - the timeline knows which
scenes are silent, the file knows its own shape, the reuse check knows what
is left of the source. Nothing gathered them, so each was found separately
and usually after the upload, which is a step this app cannot take back.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.ui_source import studio_ui
from youtube_monitor import platform_copy, publish_gate


def _ready(**overrides):
    base = {
        "timeline": [{"audio_path": "a.mp3", "visual_path": "b.mp4"}],
        "script": {"status": "approved"},
        "video_path": None,
        "frame_size": (1080, 1920),
        "output_profile": "youtube_shorts",
        "title": "Ba mươi ngày giữa rừng",
        "description": "Mô tả riêng cho video này.",
        "tags": ["survival"],
        "thumbnail_path": "",
        "platform": "youtube",
        "reuse_verdict": "low",
        "source_title": "Cabin in the woods",
    }
    base.update(overrides)
    return base


class WhatStopsAPublicationTests(unittest.TestCase):
    def _levels(self, **overrides) -> dict[str, str]:
        return {item["key"]: item["level"] for item in publish_gate.evaluate(**_ready(**overrides))}

    def test_a_missing_video_stops_it(self) -> None:
        self.assertEqual(self._levels()["rendered"], publish_gate.BLOCK)

    def test_a_real_video_passes_that_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "final.mp4"
            path.write_bytes(b"x")

            self.assertEqual(self._levels(video_path=path)["rendered"], publish_gate.PASS)

    def test_a_silent_scene_stops_it(self) -> None:
        levels = self._levels(timeline=[
            {"audio_path": "a.mp3", "visual_path": "b.mp4"},
            {"audio_path": "", "visual_path": "b.mp4"},
        ])

        self.assertEqual(levels["scenes"], publish_gate.BLOCK)

    def test_a_scene_with_no_picture_stops_it(self) -> None:
        levels = self._levels(timeline=[{"audio_path": "a.mp3", "visual_path": ""}])

        self.assertEqual(levels["scenes"], publish_gate.BLOCK)

    def test_it_says_how_many_scenes_are_short_of_what(self) -> None:
        checks = publish_gate.evaluate(**_ready(timeline=[
            {"audio_path": "", "visual_path": ""},
            {"audio_path": "a", "visual_path": "b"},
        ]))
        scenes = next(item for item in checks if item["key"] == "scenes")

        self.assertIn("1/2 cảnh chưa có giọng", scenes["detail"])
        self.assertIn("1/2 cảnh chưa có hình", scenes["detail"])

    def test_a_landscape_master_cannot_go_out_as_a_short(self) -> None:
        self.assertEqual(self._levels(frame_size=(1920, 1080))["aspect"], publish_gate.BLOCK)

    def test_an_unapproved_script_stops_it(self) -> None:
        self.assertEqual(self._levels(script={"status": "draft"})["approved"], publish_gate.BLOCK)

    def test_a_high_copyright_risk_stops_it(self) -> None:
        self.assertEqual(self._levels(reuse_verdict="high")["reuse"], publish_gate.BLOCK)

    def test_an_unrun_copyright_check_only_warns(self) -> None:
        """Not run is not the same as failed, and the user may still decide."""
        self.assertEqual(self._levels(reuse_verdict="")["reuse"], publish_gate.WARN)

    def test_a_missing_title_stops_it_but_a_missing_description_does_not(self) -> None:
        levels = self._levels(title="", description="")

        self.assertEqual(levels["title"], publish_gate.BLOCK)
        self.assertEqual(levels["description"], publish_gate.WARN)

    def test_reusing_the_sources_headline_warns_without_stopping(self) -> None:
        levels = self._levels(title="Cabin in the woods · full build")

        self.assertEqual(levels["title"], publish_gate.WARN)

    def test_a_missing_thumbnail_warns_rather_than_stopping(self) -> None:
        """YouTube will pick a frame; it will just not be a good one."""
        self.assertEqual(self._levels(thumbnail_path="")["thumbnail"], publish_gate.WARN)

    def test_everything_in_order_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "final.mp4"
            video.write_bytes(b"x")
            thumb = Path(directory) / "thumb.jpg"
            thumb.write_bytes(b"x")
            checks = publish_gate.evaluate(**_ready(
                video_path=video, thumbnail_path=str(thumb),
            ))

        self.assertTrue(publish_gate.is_ready(checks), publish_gate.blockers(checks))

    def test_every_blocker_names_what_to_press(self) -> None:
        checks = publish_gate.evaluate(**_ready(
            timeline=[], script={"status": "draft"}, title="", reuse_verdict="high",
        ))

        for item in publish_gate.blockers(checks):
            with self.subTest(key=item["key"]):
                self.assertTrue(item["fix"].strip())


class TheGateIsEnforcedAndReachableTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parent.parent
        self.source = (root / "youtube_monitor" / "main.py").read_text(encoding="utf-8")
        self.page = studio_ui()

    def test_the_endpoint_exists(self) -> None:
        from youtube_monitor.main import app

        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/projects/{project_id}/publish-checklist", paths)

    def test_publishing_runs_it(self) -> None:
        self.assertIn("stopped = publish_gate.blockers(checks)", self.source)
        self.assertIn("Chưa đủ điều kiện để đăng.", self.source)

    def test_it_reports_the_whole_list_before_any_single_guard(self) -> None:
        """One refusal per attempt is what the gate exists to replace."""
        gate_at = self.source.index("stopped = publish_gate.blockers(checks)")
        guard_at = self.source.index("Project chưa có final.mp4")

        self.assertLess(gate_at, guard_at)

    def test_skipping_it_has_to_be_asked_for(self) -> None:
        self.assertIn("override_checklist: bool = False", self.source)

    def test_the_dialog_can_show_it(self) -> None:
        self.assertIn("loadPublishChecklist()", self.page)
        self.assertIn("Kiểm tra điều kiện đăng", self.page)


class OneVideoManyCaptionsTests(unittest.TestCase):
    """The same words do not work in every feed."""

    def _copy(self, platform: str):
        return platform_copy.build(
            platform,
            title="Ba mươi ngày giữa rừng: dựng căn hầm bí mật trong núi sâu",
            description="Anh vào rừng với hai bàn tay trắng. Anh đào một cái hố. Rồi anh dựng mái.",
            tags=["survival", "bushcraft", "shelter", "offgrid", "wild", "solo",
                  "camp", "diy", "forest", "build", "handmade", "winter",
                  "cabin", "dugout", "nature", "extra"],
        )

    def test_youtube_keeps_hashtags_out_of_the_description(self) -> None:
        copy = self._copy("youtube")

        self.assertFalse(copy["hashtags_in_description"])
        self.assertNotIn("#", copy["description"])
        self.assertTrue(copy["tags"])

    def test_the_short_form_feeds_put_them_in_the_caption(self) -> None:
        for platform in ("tiktok", "instagram", "facebook"):
            with self.subTest(platform=platform):
                copy = self._copy(platform)

                self.assertTrue(copy["hashtags_in_description"])
                self.assertIn("#", copy["description"])

    def test_each_platform_gets_the_call_to_action_it_actually_has(self) -> None:
        """Subscribing is a YouTube idea; following is a TikTok one."""
        self.assertIn("Đăng ký kênh", self._copy("youtube")["cta"])
        self.assertIn("Theo dõi", self._copy("tiktok")["cta"])

    def test_tag_counts_follow_what_the_platform_shows(self) -> None:
        self.assertEqual(len(self._copy("youtube")["tags"]), 15)
        self.assertEqual(len(self._copy("tiktok")["tags"]), 8)

    def test_a_title_is_trimmed_at_a_word_not_mid_word(self) -> None:
        copy = platform_copy.build("tiktok", title="x" * 40 + " " + "y" * 200, description="")

        self.assertLessEqual(len(copy["title"]), platform_copy.PLATFORM_LIMITS["tiktok"]["title"])
        self.assertTrue(copy["title"].endswith("…"))

    def test_a_title_that_fits_is_left_exactly_as_written(self) -> None:
        copy = platform_copy.build("youtube", title="Tiêu đề vừa đủ", description="")

        self.assertEqual(copy["title"], "Tiêu đề vừa đủ")

    def test_duplicate_and_hashed_tags_are_folded_together(self) -> None:
        tags = platform_copy.normalise_tags(["#survival", "survival", "Survival", " bushcraft "])

        self.assertEqual(tags, ["survival", "bushcraft"])

    def test_building_for_several_platforms_at_once(self) -> None:
        built = platform_copy.build_all(
            ["youtube", "tiktok"], title="T", description="D", tags=["a"],
        )

        self.assertEqual(sorted(built), ["tiktok", "youtube"])

    def test_the_endpoint_exists(self) -> None:
        from youtube_monitor.main import app

        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/projects/{project_id}/platform-copy", paths)

    def test_the_scripts_closing_line_is_not_used_as_a_call_to_action(self) -> None:
        """It is the end of the story, not "follow for more"."""
        source = (
            Path(__file__).resolve().parent.parent / "youtube_monitor" / "main.py"
        ).read_text(encoding="utf-8")

        self.assertIn("not the script's cta", source.replace("’", "'").lower())
