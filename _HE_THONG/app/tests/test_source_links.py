"""A source video should be able to come from any site, not only YouTube.

Importing went through the YouTube Data API, so a Bilibili or TikTok link
could not be imported at all — the only route was downloading by hand and
uploading the file, which is how the two Bilibili projects in this database
arrived. yt-dlp, which the downloader already used, reads about 1800 sites.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from youtube_monitor import main
from youtube_monitor.database import Database
from youtube_monitor.source_links import (
    SourceLinkError,
    channel_id_for,
    describe,
    is_http_url,
    probe_url,
    video_id_for,
)
from tests.ui_source import studio_ui

_INFO = {
    "id": "BV1xx411c7mD",
    "extractor_key": "BiliBili",
    "title": "Video thử",
    "description": "Mô tả",
    "uploader": "Kênh nguồn",
    "uploader_id": "12345",
    "uploader_url": "https://space.bilibili.com/12345",
    "duration": 754.4,
    "thumbnail": "https://i0.hdslb.com/x.jpg",
    "webpage_url": "https://www.bilibili.com/video/BV1xx411c7mD",
}


class UrlShapeTests(unittest.TestCase):
    def test_only_web_links_are_treated_as_links(self) -> None:
        self.assertTrue(is_http_url("https://www.bilibili.com/video/BV1"))
        self.assertTrue(is_http_url("http://vimeo.com/1"))
        for value in ("dQw4w9WgXcQ", "@handle", "", "file:///C:/x.mp4", "https://"):
            self.assertFalse(is_http_url(value), value)


class IdentityTests(unittest.TestCase):
    def test_a_channel_id_fits_the_column_it_shares_with_youtube(self) -> None:
        for uploader in ("12345", "a" * 200, ""):
            self.assertLessEqual(len(channel_id_for("BiliBili", uploader)), 24)

    def test_the_same_uploader_always_lands_on_the_same_channel(self) -> None:
        self.assertEqual(channel_id_for("BiliBili", "12345"), channel_id_for("BiliBili", "12345"))

    def test_the_same_id_on_two_sites_does_not_collide(self) -> None:
        self.assertNotEqual(video_id_for("BiliBili", "1", "u"), video_id_for("TikTok", "1", "u"))
        self.assertNotEqual(channel_id_for("BiliBili", "1"), channel_id_for("TikTok", "1"))

    def test_a_video_without_a_native_id_still_gets_a_stable_one(self) -> None:
        url = "https://example.invalid/watch"
        self.assertEqual(video_id_for("Web", "", url), video_id_for("Web", "", url))


class DescribeTests(unittest.TestCase):
    def test_the_fields_the_app_stores_are_read_off_the_metadata(self) -> None:
        details = describe(_INFO, _INFO["webpage_url"])
        self.assertEqual(details["platform"], "BiliBili")
        self.assertEqual(details["title"], "Video thử")
        self.assertEqual(details["uploader"], "Kênh nguồn")
        self.assertEqual(details["duration_seconds"], 754)
        self.assertFalse(details["is_live"])

    def test_missing_fields_do_not_break_the_import(self) -> None:
        details = describe({"extractor": "tiktok"}, "https://www.tiktok.com/@a/video/1")
        self.assertEqual(details["platform"], "tiktok")
        self.assertEqual(details["duration_seconds"], 0)
        self.assertTrue(details["video_id"].startswith("web-"))

    def test_an_unreadable_duration_becomes_zero_rather_than_an_error(self) -> None:
        self.assertEqual(describe({"duration": "khong ro"}, "https://x.invalid/1")["duration_seconds"], 0)


class ProbeTests(unittest.TestCase):
    def test_a_reference_that_is_not_a_link_is_refused_before_any_network_call(self) -> None:
        with self.assertRaises(SourceLinkError):
            probe_url("dQw4w9WgXcQ")

    def test_a_playlist_link_yields_its_first_video_not_all_of_them(self) -> None:
        payload = {"entries": [dict(_INFO), {"id": "second"}]}
        with mock.patch("yt_dlp.YoutubeDL") as ydl:
            ydl.return_value.__enter__.return_value.extract_info.return_value = payload
            details = probe_url("https://www.bilibili.com/playlist")
        self.assertEqual(details["native_id"], _INFO["id"])

    def test_an_extractor_failure_is_reported_in_the_users_language(self) -> None:
        with mock.patch("yt_dlp.YoutubeDL") as ydl:
            ydl.return_value.__enter__.return_value.extract_info.side_effect = RuntimeError("403")
            with self.assertRaises(SourceLinkError) as ctx:
                probe_url("https://www.bilibili.com/video/BV1")
        self.assertIn("Không đọc được video", str(ctx.exception))


def _database(directory: str) -> Database:
    return Database(Path(directory) / "links.db")


class ImportTests(unittest.TestCase):
    def _import(self, details: dict, database: Database):
        with mock.patch.object(main, "database", database):
            with mock.patch.object(main, "probe_source_link", return_value=details):
                return main._import_video_from_link("https://x.invalid/1", group_name="Nhom")

    def test_a_link_becomes_an_ordinary_video_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            details = describe(_INFO, _INFO["webpage_url"])
            result = self._import(details, database)
            video = database.get_video(details["video_id"])
            self.assertEqual(result["platform"], "BiliBili")
            self.assertEqual(video["video_url"], _INFO["webpage_url"])
            self.assertEqual(video["duration_seconds"], 754)

    def test_its_uploader_becomes_a_channel_so_the_rest_of_the_app_works(self) -> None:
        """Everything downstream is keyed to a video, which needs a channel."""
        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            details = describe(_INFO, _INFO["webpage_url"])
            self._import(details, database)
            channel = database.get_channel(details["channel_id"])
            self.assertIsNotNone(channel)
            self.assertIn("BiliBili", channel["title"])

    def test_a_live_stream_is_refused_rather_than_half_imported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            details = {**describe(_INFO, _INFO["webpage_url"]), "is_live": True}
            with self.assertRaises(main.HTTPException) as ctx:
                self._import(details, database)
            self.assertEqual(ctx.exception.status_code, 400)

    def test_importing_the_same_link_twice_does_not_duplicate_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            details = describe(_INFO, _INFO["webpage_url"])
            self._import(details, database)
            self._import(details, database)
            with mock.patch.object(main, "database", database):
                self.assertEqual(len(database.list_videos(limit=50)), 1)


class RoutingTests(unittest.TestCase):
    def test_a_youtube_link_keeps_the_data_api_path(self) -> None:
        """The API gives channel membership and counts yt-dlp does not."""
        for url in (
            "https://www.youtube.com/watch?v=abc",
            "https://youtu.be/abc",
            "https://www.youtube-nocookie.com/embed/abc",
        ):
            self.assertTrue(main._looks_like_youtube(url), url)

    def test_another_platform_is_not_mistaken_for_youtube(self) -> None:
        for url in (
            "https://www.bilibili.com/video/BV1",
            "https://www.tiktok.com/@a/video/1",
            "https://vimeo.com/1",
        ):
            self.assertFalse(main._looks_like_youtube(url), url)

    def test_the_shared_import_endpoint_sends_a_link_down_the_link_path(self) -> None:
        with mock.patch.object(main, "_import_video_from_link", return_value={"ok": True}) as taken:
            with TestClient(main.app) as client:
                client.post(
                    "/api/videos/import",
                    json={"reference": "https://www.bilibili.com/video/BV1"},
                )
        taken.assert_called_once()


class ReachableFromThePageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page = studio_ui()

    def test_any_link_goes_in_the_one_box(self) -> None:
        # No type to pick first: the box sends the link, the server routes it.
        self.assertNotIn('<option value="link">', self.page)
        self.assertIn("/api/sources/import", self.page)

    def test_a_video_link_from_another_site_reaches_the_link_importer(self) -> None:
        with mock.patch.object(main, "_import_video_from_link", return_value={"video": None}) as taken, \
                mock.patch.object(main.database, "record_source_item", return_value={}):
            with TestClient(main.app) as client:
                client.post("/api/sources/import", json={"text": "https://www.bilibili.com/video/BV1xx411c7mD"})
        taken.assert_called_once()
        self.assertEqual(taken.call_args.kwargs.get("as_page"), "")

    def test_the_endpoints_exist(self) -> None:
        paths = {getattr(route, "path", "") for route in main.app.routes}
        self.assertIn("/api/videos/import-link", paths)
        self.assertIn("/api/videos/probe-link", paths)


if __name__ == "__main__":
    unittest.main()
