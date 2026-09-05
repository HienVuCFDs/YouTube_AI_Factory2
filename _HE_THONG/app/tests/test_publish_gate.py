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


class AnApiRefusalIsReadableTests(unittest.TestCase):
    """The gate answers with a list of reasons, not a sentence.

    Handed straight to `new Error(...)`, that object stringifies to
    "[object Object]" - which is what appeared where the reasons should have
    been, at the exact moment they mattered.
    """

    def setUp(self) -> None:
        self.page = studio_ui()

    def test_nothing_throws_a_raw_detail_any_more(self) -> None:
        self.assertNotIn("new Error(data.detail", self.page)

    def test_there_is_one_place_that_renders_a_refusal(self) -> None:
        self.assertIn("function apiErrorText(detail, status)", self.page)
        self.assertIn("function apiError(data, response)", self.page)

    def test_an_object_detail_is_unpacked_into_its_reasons(self) -> None:
        body = self.page[self.page.index("function apiErrorText(detail, status)"):]
        body = body[:body.index("\n  }")]

        self.assertIn("detail.message", body)
        self.assertIn("detail.blockers", body)

    def test_the_structured_answer_still_reaches_the_caller(self) -> None:
        """The dialog renders the checklist from it rather than the text."""
        self.assertIn("error.detail = data?.detail;", self.page)


class ChoosingAThumbnailFrameTests(unittest.TestCase):
    """Fixed timestamps land on whatever the video happened to be doing."""

    def test_a_dark_frame_scores_nothing_however_sharp_it_is(self) -> None:
        import numpy as np

        from youtube_monitor.thumbnail_generator import _score_frame

        noisy_black = np.random.default_rng(1).uniform(0, 12, size=(90, 160)).astype(np.float32)

        self.assertEqual(_score_frame(noisy_black), 0.0)

    def test_a_blown_out_frame_scores_nothing_either(self) -> None:
        import numpy as np

        from youtube_monitor.thumbnail_generator import _score_frame

        near_white = np.full((90, 160), 250.0, dtype=np.float32)

        self.assertEqual(_score_frame(near_white), 0.0)

    def test_a_sharp_frame_beats_a_blurred_one(self) -> None:
        """The commonest bad thumbnail is a motion-blurred frame."""
        import numpy as np

        from youtube_monitor.thumbnail_generator import _score_frame

        generator = np.random.default_rng(7)
        sharp = generator.uniform(60, 190, size=(90, 160)).astype(np.float32)
        blurred = np.repeat(np.repeat(sharp[::6, ::6], 6, axis=0), 6, axis=1).astype(np.float32)

        self.assertGreater(_score_frame(sharp), _score_frame(blurred[:90, :160]))

    def test_a_flat_frame_beats_nothing(self) -> None:
        import numpy as np

        from youtube_monitor.thumbnail_generator import _score_frame

        flat = np.full((90, 160), 128.0, dtype=np.float32)
        textured = np.random.default_rng(3).uniform(60, 190, size=(90, 160)).astype(np.float32)

        self.assertGreater(_score_frame(textured), _score_frame(flat))


class ThumbnailBriefTests(unittest.TestCase):
    """A frame is what the camera did; a thumbnail is composed."""

    def _built(self, **kwargs) -> str:
        from youtube_monitor import thumbnail_prompt

        return thumbnail_prompt.build(
            {"hook": "Anh bỏ phố về rừng, dựng một căn hầm bằng tay không."},
            {"title": "Ba mươi ngày"},
            **kwargs,
        )

    def test_it_forbids_the_things_that_make_a_thumbnail_look_generated(self) -> None:
        brief = self._built()

        for banned in ("No text", "no logo", "no watermark", "no borders"):
            with self.subTest(banned=banned):
                self.assertIn(banned, brief)

    def test_it_asks_for_a_composition_not_a_scene(self) -> None:
        brief = self._built()

        self.assertIn("One clear subject", brief)
        self.assertIn("so a title can be placed there later", brief)

    def test_a_short_is_briefed_vertically(self) -> None:
        self.assertIn("Vertical 9:16", self._built(vertical=True))
        self.assertIn("16:9", self._built(vertical=False))

    def test_the_subject_comes_from_the_hook_not_the_title(self) -> None:
        """A title is written to be read; a hook to be pictured."""
        self.assertIn("dựng một căn hầm", self._built())

    def test_each_variant_is_framed_differently(self) -> None:
        """Three renders of one prompt is not a choice."""
        from youtube_monitor import thumbnail_prompt

        prompts = thumbnail_prompt.variant_prompts("BASE", 3)

        self.assertEqual(len(prompts), 3)
        self.assertEqual(len(set(prompts)), 3)

    def test_it_refuses_when_there_is_nothing_to_picture(self) -> None:
        from youtube_monitor import thumbnail_prompt

        with self.assertRaises(ValueError):
            thumbnail_prompt.build({}, {})

    def test_a_failure_names_what_can_be_used_instead(self) -> None:
        source = (
            Path(__file__).resolve().parent.parent / "youtube_monitor" / "main.py"
        ).read_text(encoding="utf-8")

        self.assertIn("def _image_provider_advice", source)
        self.assertIn("Có thể thử model khác", source)


class PublishingNeedsSomewhereToPublishToTests(unittest.TestCase):
    def test_an_unconfigured_youtube_account_stops_it(self) -> None:
        from youtube_monitor import publish_gate

        checks = publish_gate.evaluate(**_ready(youtube_configured=False))
        account = next(item for item in checks if item["key"] == "youtube_account")

        self.assertEqual(account["level"], publish_gate.BLOCK)
        self.assertIn("client id/secret", account["detail"])

    def test_configured_but_not_signed_in_stops_it_too(self) -> None:
        from youtube_monitor import publish_gate

        checks = publish_gate.evaluate(**_ready(youtube_connected=False))

        self.assertEqual(
            next(item for item in checks if item["key"] == "youtube_account")["level"],
            publish_gate.BLOCK,
        )

    def test_a_manual_platform_is_not_asked_for_a_youtube_login(self) -> None:
        from youtube_monitor import publish_gate

        checks = publish_gate.evaluate(**_ready(platform="tiktok", youtube_configured=False))

        self.assertNotIn("youtube_account", [item["key"] for item in checks])


class ThrowingAwayAThumbnailTests(unittest.TestCase):
    """Three at a time, kept for ever, is a grid worth less than no grid."""

    def setUp(self) -> None:
        import tempfile

        from youtube_monitor.database import Database

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.database = Database(self.root / "thumbs.db")
        self.database.upsert_channel({
            "youtube_channel_id": "UC0000000000000000000088",
            "channel_url": "https://www.youtube.com/channel/UC0000000000000000000088",
            "title": "Kênh", "uploads_playlist_id": "UU0000000000000000000088",
        })
        self.database.upsert_video({
            "youtube_video_id": "video-thumb-1",
            "youtube_channel_id": "UC0000000000000000000088",
            "video_url": "https://www.youtube.com/watch?v=video-thumb-1",
            "title": "Nguồn", "metadata_hash": "h", "raw_payload": {},
        })
        project = self.database.create_production_project("video-thumb-1")
        self.project_id = int(project["id"])

    def _thumbnail(self, name: str = "thumb.jpg"):
        path = self.root / name
        path.write_bytes(b"jpeg")
        asset = self.database.create_project_asset(
            self.project_id, "image", name, str(path), mime_type="image/jpeg", file_size=4,
        )
        return self.database.create_project_thumbnail(self.project_id, int(asset["id"]))

    def test_deleting_removes_the_row(self) -> None:
        thumbnail = self._thumbnail()

        removed = self.database.delete_project_thumbnail(int(thumbnail["id"]))

        self.assertIsNotNone(removed)
        self.assertEqual(self.database.list_project_thumbnails(self.project_id), [])

    def test_it_removes_the_asset_behind_it_too(self) -> None:
        """An asset left after its thumbnail is only there to puzzle over."""
        thumbnail = self._thumbnail()
        asset_id = int(thumbnail["asset_id"])

        self.database.delete_project_thumbnail(int(thumbnail["id"]))

        self.assertIsNone(self.database.get_project_asset(asset_id))

    def test_it_returns_the_row_so_the_file_can_be_removed(self) -> None:
        thumbnail = self._thumbnail()

        removed = self.database.delete_project_thumbnail(int(thumbnail["id"]))

        self.assertTrue(str(removed.get("file_path") or "").endswith("thumb.jpg"))

    def test_deleting_one_leaves_the_others(self) -> None:
        keep = self._thumbnail("keep.jpg")
        drop = self._thumbnail("drop.jpg")

        self.database.delete_project_thumbnail(int(drop["id"]))
        left = self.database.list_project_thumbnails(self.project_id)

        self.assertEqual([item["id"] for item in left], [int(keep["id"])])

    def test_deleting_something_that_is_gone_says_so(self) -> None:
        self.assertIsNone(self.database.delete_project_thumbnail(999_999))

    def test_the_endpoint_exists(self) -> None:
        from youtube_monitor.main import app

        routes = {
            (getattr(route, "path", ""), method)
            for route in app.routes
            for method in getattr(route, "methods", set())
        }
        self.assertIn(("/api/thumbnails/{thumbnail_id}", "DELETE"), routes)

    def test_both_thumbnail_panels_can_delete(self) -> None:
        page = studio_ui()

        self.assertIn("deleteProjectThumbnail(", page)
        self.assertIn("deleteStudioThumbnail(", page)


class BothPanelsOfferTheDrawnThumbnailTests(unittest.TestCase):
    """One panel omitted the mode entirely.

    The endpoint defaults to cropping a frame, so the button most within
    reach produced a still from the video however the request was meant -
    which is why "AI thumbnails" kept coming back as screenshots.
    """

    def setUp(self) -> None:
        self.page = studio_ui()

    def test_the_project_panel_names_the_mode_it_wants(self) -> None:
        self.assertIn("generateProjectThumbnails(projectId, mode = 'ai')", self.page)
        self.assertIn("JSON.stringify({prompt, variants: 3, mode})", self.page)

    def test_it_offers_both_kinds(self) -> None:
        self.assertIn("generateProjectThumbnails(${project.id}, 'ai')", self.page)
        self.assertIn("generateProjectThumbnails(${project.id}, 'frame')", self.page)

    def test_the_publish_panel_does_too(self) -> None:
        self.assertIn("generateStudioThumbnails(${project.id}, 'ai')", self.page)
        self.assertIn("generateStudioThumbnails(${project.id}, 'frame')", self.page)


class OneRefusalIsNotTheEndOfDrawingTests(unittest.TestCase):
    """execute_scene runs exactly the model it is handed.

    The thumbnail default is gemini_image, whose image quota on this machine
    is zero, so every attempt ended on the first refusal while other models
    sat there able to draw. The descriptors have declared fallback_keys all
    along; nothing walked them.
    """

    def test_the_chain_starts_with_what_was_asked_for(self) -> None:
        from youtube_monitor.main import _image_provider_chain

        chain = _image_provider_chain("gemini_image")

        self.assertTrue(chain)
        self.assertEqual(chain[0], "gemini_image")

    def test_it_never_offers_a_model_that_cannot_draw_now(self) -> None:
        from youtube_monitor.main import _image_provider_blocked, _image_provider_chain

        for key in _image_provider_chain("gemini_image"):
            with self.subTest(provider=key):
                self.assertEqual(_image_provider_blocked(key), "")

    def test_a_browser_provider_is_never_in_it(self) -> None:
        """A sidecar provider takes work from a queue; calling it raises."""
        from youtube_monitor.main import _image_provider_chain

        chain = _image_provider_chain("gemini_image")

        self.assertNotIn("chatgpt_web_image", chain)
        self.assertNotIn("gemini_web_image", chain)

    def test_a_provider_never_appears_twice(self) -> None:
        from youtube_monitor.main import _image_provider_chain

        chain = _image_provider_chain("gemini_image")

        self.assertEqual(len(chain), len(set(chain)))

    def test_an_unknown_provider_still_gets_the_others(self) -> None:
        from unittest import mock

        from youtube_monitor import main

        with mock.patch.object(main, "_image_provider_blocked", return_value=""):
            chain = main._image_provider_chain("khong-co-provider-nay")

        self.assertIn("gemini_image", chain)
        self.assertIn("gflow_image", chain)

    def test_the_declared_fallbacks_come_before_the_rest(self) -> None:
        from unittest import mock

        from youtube_monitor import main

        with mock.patch.object(main, "_image_provider_blocked", return_value=""):
            chain = main._image_provider_chain("gemini_image")

        # gemini_image declares gflow_image, then gemini_web_image.
        self.assertLess(chain.index("gflow_image"), chain.index("openai_image"))

    def test_a_signed_out_flow_says_what_to_click(self) -> None:
        """"Not configured" is not something a user can act on."""
        from unittest import mock

        from youtube_monitor import main

        with mock.patch.object(
            main, "gflow_cli_status", return_value={"installed": True, "logged_in": False}
        ):
            reason = main._image_provider_blocked("gflow_image")

        self.assertIn("Đăng nhập Flow", reason)

    def test_a_signed_in_flow_is_offered(self) -> None:
        from unittest import mock

        from youtube_monitor import main

        with mock.patch.object(
            main, "gflow_cli_status", return_value={"installed": True, "logged_in": True}
        ):
            self.assertEqual(main._image_provider_blocked("gflow_image"), "")
            self.assertIn("gflow_image", main._image_provider_chain("gemini_image"))

    def test_the_advice_no_longer_recommends_a_signed_out_flow(self) -> None:
        from unittest import mock

        from youtube_monitor import main

        with mock.patch.object(
            main, "gflow_cli_status", return_value={"installed": True, "logged_in": False}
        ):
            advice = main._image_provider_advice("gemini_image")

        self.assertNotIn("Có thể thử model khác: gflow_image", advice)
        self.assertIn("gflow_image (gflow-cli đã cài", advice)
