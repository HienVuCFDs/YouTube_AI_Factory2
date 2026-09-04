"""Publishing sends the right file, in the right shape, to the right place.

Both are failures the app cannot take back. A video uploaded to the wrong
channel is a real video on a real account that has to be found and deleted; a
16:9 master accepted as a Reel is filed by YouTube as an ordinary video and
letterboxed into a stamp by every vertical feed, and by then the only fix is
to render it again.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from youtube_monitor.database import Database
from youtube_monitor.ffmpeg_renderer import resolve_ffmpeg, video_frame_size
from youtube_monitor.publisher import (
    SUPPORTED_PLATFORMS,
    PublisherError,
    YouTubePublisher,
)
from youtube_monitor.shorts import frame_matches_profile, profile_label
from tests.ui_source import studio_ui


class TheQueueOnlyOffersWhatItCanDeliverTests(unittest.TestCase):
    """The uploader speaks to YouTube and nothing else.

    A publication records the platform it was made for, and the queue used to
    hand every queued row to that uploader without looking. Publishing is not
    reversible enough to leave that to the endpoint that creates the row.
    """

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.database = Database(self.root / "publish.db")
        self.database.upsert_channel({
            "youtube_channel_id": "UC0000000000000000000077",
            "channel_url": "https://www.youtube.com/channel/UC0000000000000000000077",
            "title": "Kênh thử",
            "uploads_playlist_id": "UU0000000000000000000077",
        })
        self.database.upsert_video({
            "youtube_video_id": "video-publish-1",
            "youtube_channel_id": "UC0000000000000000000077",
            "video_url": "https://www.youtube.com/watch?v=video-publish-1",
            "title": "Nguồn",
            "metadata_hash": "hash-publish-1",
            "raw_payload": {},
        })
        project = self.database.create_production_project("video-publish-1")
        self.project_id = int(project["id"])
        self.video = self.root / "final.mp4"
        self.video.write_bytes(b"not really a video")

    def _queue(self, platform: str) -> dict:
        return self.database.create_project_publication(
            self.project_id,
            local_file_path=str(self.video),
            title=f"bài {platform}",
            platform=platform,
            status="queued",
        )

    def test_only_youtube_rows_reach_the_youtube_uploader(self) -> None:
        for platform in ("youtube", "facebook", "tiktok", "instagram"):
            self._queue(platform)

        due = self.database.list_due_project_publications(
            "2099-01-01T00:00:00Z", limit=50, platforms=SUPPORTED_PLATFORMS,
        )

        self.assertEqual([row["platform"] for row in due], ["youtube"])

    def test_the_others_are_held_and_counted_rather_than_lost(self) -> None:
        """A queue that never empties looks broken unless it says why."""
        for platform in ("facebook", "tiktok", "instagram"):
            self._queue(platform)

        waiting = self.database.publications_awaiting_platform(SUPPORTED_PLATFORMS)

        self.assertEqual(waiting, {"facebook": 1, "tiktok": 1, "instagram": 1})

    def test_the_uploader_itself_refuses_a_platform_it_cannot_serve(self) -> None:
        """The filter is not the only guard; a direct call is refused too."""
        with self.assertRaises(PublisherError) as caught:
            YouTubePublisher().upload_video(
                {"platform": "facebook", "local_file_path": str(self.video)}
            )

        self.assertIn("facebook", str(caught.exception))
        self.assertNotIn("mojibake", str(caught.exception))

    def test_a_publication_with_no_platform_is_treated_as_youtube(self) -> None:
        """Rows written before the column existed default to youtube."""
        publication = self.database.create_project_publication(
            self.project_id, local_file_path=str(self.video), title="cũ", status="queued",
        )

        self.assertEqual(publication["platform"], "youtube")


class TheFileMustBeTheShapeTheDestinationWantsTests(unittest.TestCase):
    """Resolution and codec were checked; the shape never was.

    So a landscape master could be published as a Short, a Reel or a square
    feed post and nothing objected.
    """

    def test_each_shape_is_accepted_only_by_the_profiles_it_fits(self) -> None:
        cases = {
            (1920, 1080): "youtube_landscape",
            (1080, 1920): "youtube_shorts",
            (1080, 1080): "facebook_feed",
        }
        profiles = ["youtube_landscape", "youtube_shorts", "facebook_feed"]
        for (width, height), fits in cases.items():
            for profile in profiles:
                with self.subTest(size=(width, height), profile=profile):
                    self.assertEqual(
                        frame_matches_profile(width, height, profile),
                        profile == fits,
                    )

    def test_reels_and_shorts_share_a_shape_so_either_file_serves_both(self) -> None:
        self.assertTrue(frame_matches_profile(1080, 1920, "facebook_reels"))
        self.assertTrue(frame_matches_profile(1080, 1920, "tiktok"))

    def test_a_slightly_off_encode_is_not_rejected_over_a_few_pixels(self) -> None:
        """Encoders round to even dimensions; that is not a wrong shape."""
        self.assertTrue(frame_matches_profile(1080, 1918, "youtube_shorts"))
        self.assertTrue(frame_matches_profile(1918, 1080, "youtube_landscape"))

    def test_an_unreadable_file_does_not_block_publishing(self) -> None:
        """Not being able to measure is not evidence of being wrong."""
        self.assertTrue(frame_matches_profile(0, 0, "youtube_shorts"))

    def test_the_message_can_name_the_size_that_was_wanted(self) -> None:
        self.assertEqual(profile_label("youtube_shorts"), "1080x1920")
        self.assertEqual(profile_label("youtube_landscape"), "1920x1080")

    def test_it_measures_a_real_file(self) -> None:
        executable = resolve_ffmpeg("ffmpeg")
        if not executable:
            self.skipTest("FFmpeg không có trên máy chạy test")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "doc.mp4"
            subprocess.run(
                [executable, "-y", "-loglevel", "error", "-f", "lavfi",
                 "-i", "color=c=black:s=1080x1920:d=1", "-pix_fmt", "yuv420p", str(path)],
                check=True, capture_output=True,
            )

            self.assertEqual(video_frame_size(path, "ffmpeg"), (1080, 1920))

    def test_a_missing_file_measures_as_nothing_rather_than_raising(self) -> None:
        self.assertIsNone(video_frame_size(Path("F:/khong/co/that.mp4"), "ffmpeg"))


class ThePublishEndpointAppliesTheCheckTests(unittest.TestCase):
    def test_publishing_refuses_a_file_of_the_wrong_shape(self) -> None:
        """The check moved into the publish gate, which covers every
        precondition rather than this one alone - but it still blocks."""
        from youtube_monitor import publish_gate

        checks = publish_gate.evaluate(
            timeline=[{"audio_path": "a", "visual_path": "b"}],
            script={"status": "approved"},
            video_path=None,
            frame_size=(1920, 1080),
            output_profile="youtube_shorts",
            title="Tiêu đề riêng",
            description="mô tả",
            tags=["a"],
            thumbnail_path="",
            platform="youtube",
            reuse_verdict="low",
        )
        aspect = next(item for item in checks if item["key"] == "aspect")

        self.assertEqual(aspect["level"], publish_gate.BLOCK)
        self.assertIn("không đúng khổ", aspect["detail"])

    def test_the_right_shape_passes_that_same_check(self) -> None:
        from youtube_monitor import publish_gate

        checks = publish_gate.evaluate(
            timeline=[{"audio_path": "a", "visual_path": "b"}],
            script={"status": "approved"},
            video_path=None,
            frame_size=(1080, 1920),
            output_profile="youtube_shorts",
            title="Tiêu đề riêng",
            description="mô tả",
            tags=["a"],
            thumbnail_path="",
            platform="youtube",
            reuse_verdict="low",
        )

        self.assertEqual(
            next(item for item in checks if item["key"] == "aspect")["level"],
            publish_gate.PASS,
        )


class ThePanelSaysWhyAQueuedPostIsWaitingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page = studio_ui()

    def test_it_names_the_platforms_that_cannot_be_posted_automatically(self) -> None:
        self.assertIn("publisherWaitingNote", self.page)
        self.assertIn("Chờ đăng thủ công", self.page)

    def test_it_says_the_post_was_not_sent_to_youtube_by_mistake(self) -> None:
        """The reassurance is the point: nothing went to the wrong channel."""
        self.assertIn("không bị đưa nhầm lên YouTube", self.page)

    def test_the_note_is_rendered_not_merely_defined(self) -> None:
        """Written but never called is the defect this project keeps hitting."""
        self.assertIn("${publisherWaitingNote(publications)}", self.page)

    def test_a_manual_destination_downloads_a_complete_handoff_package(self) -> None:
        self.assertIn("/manual-package", self.page)
        self.assertIn("Tải gói đăng", self.page)


class ThereIsSomewhereToActuallyPressUploadTests(unittest.TestCase):
    """The controls existed; nothing ever put them on the page.

    ``publisherActions`` was built into a template string inside the project
    detail renderer and then discarded - defined once, inserted nowhere - so
    the app had no upload button at all. The last wizard step offered only a
    link across to the channel list, which has no upload button either, and
    that is exactly what a user pressing "Sang xuất bản" found.
    """

    def setUp(self) -> None:
        self.page = studio_ui()

    def test_the_publish_panel_lives_on_the_publish_step(self) -> None:
        import re

        position = self.page.index('id="studioPublishPanel"')
        enclosing = None
        for match in re.finditer(r'<div id="(studioStep\d)"', self.page[:position]):
            enclosing = match.group(1)

        self.assertEqual(enclosing, "studioStep7")

    def test_there_is_an_upload_button_wired_to_the_publish_call(self) -> None:
        self.assertIn("Đăng video dài", self.page)
        self.assertIn("Đăng Short", self.page)
        self.assertIn("onclick=\"submitPublishDialog()\"", self.page)

    def test_the_panel_is_rendered_and_not_merely_built(self) -> None:
        """The whole defect was a template string nobody inserted."""
        self.assertIn("renderStudioPublish(bundle);", self.page)

    def test_a_queued_publication_appears_without_leaving_the_wizard(self) -> None:
        self.assertIn("refreshStudioPublish(projectId)", self.page)

    def test_the_panel_offers_every_destination_the_api_accepts(self) -> None:
        for profile in (
            "youtube_landscape", "youtube_shorts", "instagram_reels",
            "tiktok", "facebook_reels", "facebook_feed",
        ):
            with self.subTest(profile=profile):
                self.assertIn(profile, self.page)

    def test_it_can_publish_either_the_long_video_or_the_short(self) -> None:
        """Which video is decided by the button pressed, not by a dropdown.

        They are separate files with separate destinations, so a shared form
        asking "which one" could offer a platform the chosen file cannot serve.
        """
        self.assertIn("openPublishDialog('long')", self.page)
        self.assertIn("openPublishDialog('short')", self.page)
        self.assertIn("state.publishVariant = variant;", self.page)


class BothFinishedVideosLiveOnThePublishStepTests(unittest.TestCase):
    """The short's finished file was shown back in the build step.

    So the last step of the wizard listed one of the two videos the project
    had just produced, and gave no way to publish the other.
    """

    def setUp(self) -> None:
        self.page = studio_ui()

    def _step_of(self, needle: str) -> str | None:
        import re

        position = self.page.index(needle)
        enclosing = None
        for match in re.finditer(r'<div id="(studioStep\d)"', self.page[:position]):
            enclosing = match.group(1)
        return enclosing

    def test_the_long_video_the_short_and_the_upload_form_are_together(self) -> None:
        for element in ('id="studioFinalResult"', 'id="studioShortFinal"', 'id="studioPublishPanel"'):
            with self.subTest(element=element):
                self.assertEqual(self._step_of(element), "studioStep7")

    def test_the_short_output_no_longer_sits_in_the_build_step(self) -> None:
        self.assertNotIn('id="studioShortOutput"', self.page)

    def test_arriving_at_the_step_reloads_what_it_shows(self) -> None:
        """It is reached after rendering, so the bundle from open is stale."""
        self.assertIn(
            "if (next === 7 && state.studioProjectId) void refreshStudioPublish(state.studioProjectId);",
            self.page,
        )

    def test_that_refresh_brings_the_short_with_it(self) -> None:
        import re

        body = self.page[self.page.index("async function refreshStudioPublish("):]
        body = body[:body.index("\n  }")]

        self.assertIn("loadShortLane()", body)


class ThePageJavascriptParsesTests(unittest.TestCase):
    """A syntax error anywhere kills every button on the page at once."""

    def test_the_inline_script_is_valid_javascript(self) -> None:
        import re
        import shutil
        import subprocess
        import tempfile

        node = shutil.which("node")
        if not node:
            self.skipTest("node không có trên máy chạy test")
        page = studio_ui()
        blocks = re.findall(r"<script[^>]*>(.*?)</script>", page, re.S)
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "page.js"
            script.write_text("\n".join(blocks), encoding="utf-8")
            result = subprocess.run(
                [node, "--check", str(script)], capture_output=True, text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr[-2000:])


class ThePublishFormIsFilledFromThisVideoNotTheSourceTests(unittest.TestCase):
    """The writer already produced all of it and none of it arrived.

    Titles, a description and hashtags are written for the new video at the
    script step. The publish form ignored every one of them and opened
    pre-filled with the SOURCE video's title - the single piece of text a
    retelling must not reuse, since it is someone else's headline and often
    still carries their view count.
    """

    def setUp(self) -> None:
        self.page = studio_ui()

    def test_the_title_field_is_seeded_from_the_writers_suggestions(self) -> None:
        self.assertIn("state.publishTitles = (writer.new_titles || [])", self.page)
        self.assertIn("String((state.publishTitles || [])[0] || '')", self.page)

    def test_the_source_videos_title_is_no_longer_used_as_the_default(self) -> None:
        self.assertNotIn('value="${esc(project.title || \'\')}"', self.page)

    def test_all_the_suggested_titles_can_be_picked(self) -> None:
        self.assertIn('id="publishDialogTitlePick"', self.page)
        self.assertIn("useSuggestedTitle()", self.page)

    def test_the_description_and_hashtags_are_carried_over(self) -> None:
        self.assertIn("writer.new_description", self.page)
        self.assertIn("(writer.hashtags || []).join(', ')", self.page)

    def test_the_short_publishes_under_its_own_title_and_shape(self) -> None:
        """Its own video, so its own headline - and only vertical destinations."""
        self.assertIn("state.shortLane?.script?.script_title", self.page)
        self.assertIn("short: VERTICAL_PUBLISH_PROFILES", self.page)

    def test_a_thumbnail_can_be_made_and_chosen_on_the_publish_step(self) -> None:
        self.assertIn("generateStudioThumbnails(", self.page)
        self.assertIn("selectStudioThumbnail(", self.page)
        self.assertIn("/api/thumbnails/${thumbnailId}/select", self.page)

    def test_the_thumbnail_grid_uses_a_url_that_exists(self) -> None:
        """An invented preview route would render a grid of broken images."""
        from youtube_monitor.main import app

        self.assertIn("/api/assets/${item.asset_id}/download", self.page)
        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/assets/{asset_id}/download", paths)


class EachVideoHasItsOwnPublishFlowTests(unittest.TestCase):
    """Two different files, two different sets of destinations.

    A 16:9 master cannot be a Reel and a 9:16 short is not a YouTube video, so
    one shared form with a "which one" dropdown kept offering combinations
    that the server would measure and refuse.
    """

    def setUp(self) -> None:
        self.page = studio_ui()

    def test_each_finished_video_has_its_own_publish_button(self) -> None:
        self.assertIn("openPublishDialog('long')", self.page)
        self.assertIn("openPublishDialog('short')", self.page)

    def test_each_finished_video_has_its_own_download(self) -> None:
        self.assertIn('id="studioFinalDownload"', self.page)
        self.assertIn("/api/projects/${projectId}/short-video", self.page)

    def test_the_dialog_offers_platforms_and_a_format_for_each(self) -> None:
        self.assertIn('id="publishDialog"', self.page)
        self.assertIn("PUBLISH_TARGETS", self.page)
        self.assertIn("publish-target-profile", self.page)
        for platform in ("youtube", "tiktok", "facebook", "instagram"):
            with self.subTest(platform=platform):
                self.assertIn(f"platform: '{platform}'", self.page)

    def test_it_can_post_to_several_platforms_in_one_go(self) -> None:
        self.assertIn("submitPublishDialog", self.page)
        self.assertIn("for (const target of chosen)", self.page)

    def test_one_platform_failing_does_not_lose_the_others(self) -> None:
        self.assertIn("failed.push(", self.page)
        self.assertIn("done.push(target.platform)", self.page)

    def test_the_offered_formats_match_what_the_file_can_actually_be(self) -> None:
        """Written out by hand this had already lost Instagram from the short.

        Every combination the dialog offers must be one the server's own
        measurement would accept, or the user fills in the whole form to be
        told no.
        """
        from youtube_monitor.shorts import frame_matches_profile

        vertical = ["youtube_shorts", "instagram_reels", "tiktok", "facebook_reels"]
        variants = {"long": (["youtube_landscape"], (1920, 1080)),
                    "short": (vertical, (1080, 1920))}
        targets = {
            "youtube": ["youtube_landscape", "youtube_shorts"],
            "tiktok": ["tiktok"],
            "facebook": ["facebook_reels", "facebook_feed"],
            "instagram": ["instagram_reels"],
        }
        for variant, (allowed, (width, height)) in variants.items():
            for platform, profiles in targets.items():
                with self.subTest(variant=variant, platform=platform):
                    offered = {item for item in profiles if item in allowed}
                    accepted = {
                        item for item in profiles
                        if frame_matches_profile(width, height, item)
                    }
                    self.assertEqual(offered, accepted)

    def test_the_allowed_list_is_derived_rather_than_typed_out(self) -> None:
        self.assertIn("short: VERTICAL_PUBLISH_PROFILES", self.page)
        self.assertIn("VERTICAL_PUBLISH_PROFILES = ['youtube_shorts', 'instagram_reels'", self.page)

    def test_a_platform_the_file_cannot_serve_says_which_video_to_use(self) -> None:
        self.assertIn("is-blocked", self.page)
        self.assertIn("cho n\u1ec1n t\u1ea3ng n\u00e0y", self.page)


class EveryDestinationNamesItsChannelTests(unittest.TestCase):
    """A destination is a channel, not just a platform.

    An account holds several, grouped by topic, and they are not the same
    account across platforms. Choosing only the platform meant publishing to
    whichever channel happened to come first in the list.
    """

    def setUp(self) -> None:
        self.page = studio_ui()

    def test_the_dialog_picks_a_channel_group_first(self) -> None:
        self.assertIn('id="publishDialogGroup"', self.page)
        self.assertIn("Nh\u00f3m th\u1ebb k\u00eanh", self.page)
        self.assertIn("function publishChannelGroups()", self.page)

    def test_each_platform_row_has_its_own_channel(self) -> None:
        self.assertIn("publish-target-channel", self.page)
        self.assertIn("function publishChannelsFor(platform, group)", self.page)

    def test_changing_the_group_redraws_the_destinations(self) -> None:
        self.assertIn('onchange="renderPublishTargets()"', self.page)

    def test_the_chosen_channel_is_what_gets_sent(self) -> None:
        """One publish can span accounts that are not related at all."""
        self.assertIn("managed_channel_id: target.channelId", self.page)
        self.assertIn("class=\"publish-target-channel\"", self.page)

    def test_the_single_shared_channel_select_is_gone(self) -> None:
        self.assertNotIn("publishDialogChannel", self.page)

    def test_a_platform_with_no_channel_in_the_group_is_blocked(self) -> None:
        """Offering it would queue a publication with nowhere to go."""
        self.assertIn("const noChannel = !channels.length;", self.page)
        self.assertIn("const blocked = wrongShape || noChannel;", self.page)
        self.assertIn("Ch\u01b0a c\u00f3 k\u00eanh", self.page)

    def test_it_says_whether_the_problem_is_the_group_or_the_setup(self) -> None:
        self.assertIn("trong nh\u00f3m", self.page)
        self.assertIn("Ch\u01b0a khai b\u00e1o k\u00eanh", self.page)
