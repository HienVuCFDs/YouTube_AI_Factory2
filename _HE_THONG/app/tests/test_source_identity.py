"""A source keeps who it is on its own platform.

A YouTube video imported by link landed on a made-up "WEB-YOUTUBE-…" channel
and its views, likes and comment count were read and thrown away, so nothing
could tell which real channel it came from. Research needs those ids.
"""

from __future__ import annotations

import sqlite3
import tempfile
from contextlib import closing
import unittest
from pathlib import Path
from unittest import mock

from youtube_monitor import main, source_identity
from youtube_monitor.database import Database
from youtube_monitor.source_links import describe, platform_of

UC = "UCabcdefghijklmnopqrstuv"  # 24 characters, the shape of a real channel id

_YOUTUBE_INFO = {
    "id": "dQw4w9WgXcQ",
    "extractor_key": "Youtube",
    "title": "Video YouTube",
    "channel": "Kênh Thật",
    "channel_id": UC,
    "uploader": "Kênh Thật",
    "uploader_id": "@kenhthat",
    "uploader_url": "https://www.youtube.com/@kenhthat",
    "duration": 62,
    "view_count": 1500,
    "like_count": 120,
    "comment_count": 33,
    "timestamp": 1_700_000_000,
    "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
}
_TIKTOK_INFO = {
    "id": "7300000000000000000",
    "extractor_key": "TikTok",
    "title": "Clip",
    "uploader": "nguoidung_test",
    "uploader_id": "6800000000000000000",
    "channel_id": "MS4wLjABAAAA_test",
    "view_count": 90,
    "upload_date": "20260901",
    "webpage_url": "https://www.tiktok.com/@nguoidung_test/video/7300000000000000000",
}


def _database(directory: str) -> Database:
    return Database(Path(directory) / "identity.db")


class _FakeYouTube:
    """Stands in for the Data API; never reaches the network."""

    def __init__(self, channel_id: str = UC, *, api_key: str = "test-key", fail: bool = False):
        self.api_key = api_key
        self.channel_id = channel_id
        self.fail = fail
        self.calls: list[list[str]] = []

    def get_videos(self, ids: list[str]) -> list[dict]:
        self.calls.append(list(ids))
        if self.fail:
            raise main.YouTubeApiError("quota", status_code=403)
        return [{
            "id": ids[0],
            "snippet": {"channelId": self.channel_id, "channelTitle": "Kênh Thật (API)", "publishedAt": "2026-09-01T10:00:00Z"},
            "statistics": {"viewCount": "2000", "likeCount": "150", "commentCount": "40"},
            "contentDetails": {"duration": "PT1M2S"},
        }]


class DescribeKeepsTheNativeIdentityTests(unittest.TestCase):
    def test_a_youtube_link_keeps_its_real_channel_and_counts(self) -> None:
        details = describe(_YOUTUBE_INFO, _YOUTUBE_INFO["webpage_url"])
        self.assertEqual(details["channel_id"], UC)
        self.assertEqual(details["native_channel_id"], UC)
        self.assertEqual(details["native_id"], "dQw4w9WgXcQ")
        self.assertEqual(details["channel_name"], "Kênh Thật")
        self.assertEqual((details["view_count"], details["like_count"], details["comment_count"]), (1500, 120, 33))
        self.assertEqual(details["published_at"], "2023-11-14T22:13:20+00:00")
        self.assertEqual(details["platform_slug"], "youtube")
        self.assertTrue(details["video_id"].startswith("web-"), "describe keeps its own key; the import decides the row")

    def test_another_platform_keeps_its_native_ids_but_a_key_of_its_own(self) -> None:
        details = describe(_TIKTOK_INFO, _TIKTOK_INFO["webpage_url"])
        self.assertTrue(details["channel_id"].startswith("WEB-"))
        self.assertEqual(details["native_channel_id"], "MS4wLjABAAAA_test")
        self.assertEqual(details["view_count"], 90)
        self.assertEqual(details["published_at"], "2026-09-01", "a date is not given a made-up time")
        self.assertEqual(details["platform_slug"], "tiktok")

    def test_a_youtube_id_that_is_not_a_channel_id_is_not_trusted_as_one(self) -> None:
        details = describe({**_YOUTUBE_INFO, "channel_id": "", "uploader_id": "@kenhthat"}, _YOUTUBE_INFO["webpage_url"])
        self.assertTrue(details["channel_id"].startswith("WEB-"))

    def test_platform_names_are_normalised(self) -> None:
        self.assertEqual(platform_of("YoutubeTab"), "youtube")
        self.assertEqual(platform_of("FacebookReel"), "facebook")
        self.assertEqual(platform_of("HTML5MediaEmbed"), "web", "a catch-all extractor has no platform")
        self.assertEqual(platform_of("Generic"), "web")
        self.assertEqual(platform_of("Bilibili"), "bilibili")


class ImportKeepsTheIdentityTests(unittest.TestCase):
    def _import(self, database: Database, info: dict, youtube: _FakeYouTube):
        details = describe(info, info["webpage_url"])
        with mock.patch.object(main, "database", database), \
                mock.patch.object(main, "probe_source_link", return_value=details), \
                mock.patch.object(main, "youtube", youtube):
            result = main._import_video_from_link(info["webpage_url"])
        return result, {**details, "video_id": result["video"]["youtube_video_id"]}

    def test_a_youtube_url_is_filed_under_its_real_channel_with_official_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            youtube = _FakeYouTube()
            result, details = self._import(database, _YOUTUBE_INFO, youtube)
            video = database.get_video(details["video_id"])
            self.assertEqual(video["youtube_channel_id"], UC)
            self.assertEqual(video["native_channel_id"], UC)
            self.assertEqual(video["native_video_id"], "dQw4w9WgXcQ")
            self.assertEqual(video["source_platform"], "youtube")
            self.assertEqual(video["metrics_source"], "youtube_data_api")
            self.assertEqual((video["view_count"], video["like_count"], video["comment_count"]), (2000, 150, 40))
            self.assertEqual(youtube.calls, [["dQw4w9WgXcQ"]])
            self.assertEqual(result["identity"]["channel_identity"], source_identity.NATIVE)
            self.assertIsNotNone(database.latest_video_statistics(details["video_id"]))
            self.assertEqual(database.get_channel(UC)["uploads_playlist_id"], "UU" + UC[2:])

    def test_without_the_api_the_yt_dlp_reading_is_kept(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            _, details = self._import(database, _YOUTUBE_INFO, _FakeYouTube(api_key=""))
            video = database.get_video(details["video_id"])
            self.assertEqual(video["youtube_channel_id"], UC)
            self.assertEqual(video["metrics_source"], "yt_dlp")
            self.assertEqual(video["view_count"], 1500)

    def test_a_failing_api_does_not_fail_the_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            _, details = self._import(database, _YOUTUBE_INFO, _FakeYouTube(fail=True))
            self.assertEqual(database.get_video(details["video_id"])["native_channel_id"], UC)

    def test_a_channel_the_monitor_already_tracks_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            database.upsert_channel({
                "youtube_channel_id": UC, "channel_url": f"https://www.youtube.com/channel/{UC}",
                "title": "Kênh đang theo dõi", "uploads_playlist_id": "UU" + UC[2:], "subscriber_count": 1000,
            })
            self._import(database, _YOUTUBE_INFO, _FakeYouTube())
            channel = database.get_channel(UC)
            self.assertEqual(channel["title"], "Kênh đang theo dõi")
            self.assertEqual(channel["subscriber_count"], 1000)

    def test_a_tiktok_url_keeps_its_native_channel_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            youtube = _FakeYouTube()
            _, details = self._import(database, _TIKTOK_INFO, youtube)
            video = database.get_video(details["video_id"])
            self.assertEqual(video["native_channel_id"], "MS4wLjABAAAA_test")
            self.assertEqual(video["source_platform"], "tiktok")
            self.assertEqual(video["metrics_source"], "yt_dlp")
            self.assertEqual(youtube.calls, [], "the YouTube API is not asked about TikTok")


class ReimportDoesNotMakeItPoorerTests(unittest.TestCase):
    """A second read that fails partway must not erase what the first one found."""

    def _import(self, database: Database, info: dict, youtube: _FakeYouTube) -> dict:
        details = describe(info, _YOUTUBE_INFO["webpage_url"])
        with mock.patch.object(main, "database", database), \
                mock.patch.object(main, "probe_source_link", return_value=details), \
                mock.patch.object(main, "youtube", youtube):
            result = main._import_video_from_link(_YOUTUBE_INFO["webpage_url"])
        return {**details, "video_id": result["video"]["youtube_video_id"]}

    def test_empty_metadata_and_a_lost_channel_do_not_overwrite_good_ones(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            details = self._import(database, {**_YOUTUBE_INFO, "description": "Mô tả tốt",
                                              "thumbnail": "https://i.ytimg.com/a.jpg"}, _FakeYouTube())
            first = database.get_video(details["video_id"])
            snapshots = len(_snapshots(database, details["video_id"]))

            poorer = {
                "id": "dQw4w9WgXcQ", "extractor_key": "Youtube", "webpage_url": _YOUTUBE_INFO["webpage_url"],
                "title": "", "description": "", "duration": 0, "uploader": "", "channel_id": "",
            }
            self._import(database, poorer, _FakeYouTube(api_key=""))
            second = database.get_video(details["video_id"])

            self.assertEqual(second["youtube_channel_id"], UC, "the real channel is kept")
            self.assertEqual(second["native_channel_id"], UC)
            for field in ("title", "description", "thumbnail_url", "duration_seconds", "published_at"):
                self.assertEqual(second[field], first[field], field)
            for field in ("view_count", "like_count", "comment_count", "metrics_captured_at", "metrics_source"):
                self.assertEqual(second[field], first[field], field)
            self.assertEqual(len(_snapshots(database, details["video_id"])), snapshots,
                             "old counts are not re-recorded as a new measurement")

    def test_counts_carry_the_time_they_were_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            details = self._import(database, _YOUTUBE_INFO, _FakeYouTube())
            identity = source_identity.of(database, details["video_id"])
            self.assertEqual(identity["metrics"]["view_count"], 2000)
            self.assertTrue(identity["metrics"]["captured_at"])
            self.assertEqual(identity["metrics"]["source"], "youtube_data_api")

    def test_a_page_without_counts_has_no_count_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            _legacy_rows(database)
            self.assertIsNone(source_identity.of(database, "web-legacyarticle0")["metrics"]["captured_at"])


class ChannelMonitoringIsNotBrokenTests(unittest.TestCase):
    def test_a_link_import_leaves_a_tracked_channel_syncable(self) -> None:
        from youtube_monitor.service import SyncService

        class _MonitorApi(_FakeYouTube):
            def get_channel_by_id(self, channel_id: str) -> dict:
                return {
                    "youtube_channel_id": channel_id, "channel_url": f"https://www.youtube.com/channel/{channel_id}",
                    "title": "Kênh đang theo dõi", "uploads_playlist_id": "UU" + channel_id[2:], "subscriber_count": 1000,
                }

            def list_upload_video_ids(self, playlist: str, max_videos: int | None = None) -> list[str]:
                return ["dQw4w9WgXcQ"]

        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            api = _MonitorApi()
            service = SyncService(database, api)
            database.upsert_channel(api.get_channel_by_id(UC))
            database.set_tracking_enabled(UC, True)
            before = database.get_channel(UC)

            details = describe(_YOUTUBE_INFO, _YOUTUBE_INFO["webpage_url"])
            with mock.patch.object(main, "database", database), \
                    mock.patch.object(main, "probe_source_link", return_value=details), \
                    mock.patch.object(main, "youtube", api):
                main._import_video_from_link(_YOUTUBE_INFO["webpage_url"])

            after = database.get_channel(UC)
            for field in ("title", "subscriber_count", "uploads_playlist_id", "tracking_enabled", "group_name"):
                self.assertEqual(after[field], before[field], field)
            result = service.sync_channel(UC)
            self.assertEqual(result["videos_seen"], 1)
            self.assertEqual(database.get_channel(UC)["sync_status"], "ok")
            # One video, one row: the link import and the monitor share it.
            self.assertIsNotNone(database.get_video("dQw4w9WgXcQ"))
            self.assertIsNone(database.get_video(details["video_id"]), "no web- duplicate was made")


def _snapshots(database: Database, video_id: str) -> list:
    with closing(sqlite3.connect(database.path)) as connection:
        return connection.execute(
            "SELECT captured_at FROM video_statistics WHERE youtube_video_id = ?", (video_id,)
        ).fetchall()


def _legacy_rows(database: Database) -> None:
    """Rows exactly as the app wrote them before identity was kept."""
    database.upsert_channel({"youtube_channel_id": "WEB-YOUTUBE-740f513895b0", "channel_url": "https://x"})
    database.upsert_video({
        "youtube_video_id": "web-legacyyoutube0", "youtube_channel_id": "WEB-YOUTUBE-740f513895b0",
        "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "cũ", "metadata_hash": "a",
        "raw_payload": {"source": "link_import", "platform": "Youtube", "native_id": "dQw4w9WgXcQ"},
    })
    database.upsert_channel({"youtube_channel_id": "site-vnexpress.net", "channel_url": "https://vnexpress.net"})
    database.upsert_video({
        "youtube_video_id": "web-legacyarticle0", "youtube_channel_id": "site-vnexpress.net",
        "video_url": "https://vnexpress.net/bai-viet.html", "title": "bài", "metadata_hash": "b",
        "raw_payload": {"source": "link_import", "platform": "web", "native_id": "https://vnexpress.net/bai-viet.html"},
    })
    database.upsert_channel({"youtube_channel_id": UC, "channel_url": "https://youtube.com"})
    database.upsert_video({
        "youtube_video_id": "abcdefghijk", "youtube_channel_id": UC,
        "video_url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "api", "metadata_hash": "c",
        "view_count": 10, "raw_payload": {"kind": "youtube#video", "id": "abcdefghijk"},
    })


_NEW_COLUMNS = (
    "source_platform", "source_extractor", "native_video_id", "native_channel_id",
    "native_channel_name", "metrics_source", "identity_checked_at", "metrics_captured_at",
)
_NEW_TABLES = (
    "channel_profiles", "topic_knowledge", "audience_observations",
    "content_patterns", "research_reports", "project_plans",
)


class MigrationTests(unittest.TestCase):
    def _make_old(self, path: Path) -> None:
        """Take a database back to the schema before this change."""
        with closing(sqlite3.connect(path)) as connection, connection:
            for table in _NEW_TABLES:
                connection.execute(f"DROP TABLE IF EXISTS {table}")
            for column in _NEW_COLUMNS:
                connection.execute(f"ALTER TABLE videos DROP COLUMN {column}")

    def test_an_old_database_is_upgraded_and_its_rows_described(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.db"
            _legacy_rows(Database(path))
            self._make_old(path)

            database = Database(path)
            with closing(sqlite3.connect(path)) as connection, connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(videos)")}
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue(set(_NEW_COLUMNS) <= columns)
            self.assertTrue(set(_NEW_TABLES) <= tables)

            legacy = source_identity.of(database, "web-legacyyoutube0")
            self.assertEqual(legacy["platform"], "youtube")
            self.assertEqual(legacy["native_video_id"], "dQw4w9WgXcQ")
            self.assertEqual(legacy["native_channel_id"], "", "never stored, so not invented")
            self.assertEqual(legacy["channel_identity"], source_identity.SYNTHETIC)
            self.assertTrue(legacy["needs_refresh"])

            article = source_identity.of(database, "web-legacyarticle0")
            self.assertEqual(article["platform"], "web")
            self.assertEqual(article["native_video_id"], "")
            self.assertEqual(article["channel_identity"], source_identity.NONE)
            self.assertFalse(article["needs_refresh"])

            api = source_identity.of(database, "abcdefghijk")
            self.assertEqual((api["native_video_id"], api["native_channel_id"]), ("abcdefghijk", UC))
            self.assertEqual(api["channel_identity"], source_identity.NATIVE)
            self.assertTrue(api["metrics"]["captured_at"], "old counts get the time of their snapshot")
            self.assertIsNone(database.get_video("web-legacyyoutube0")["metrics_captured_at"], "no counts, no time")

            # The old synthetic channel row itself is still there and readable.
            self.assertIsNotNone(database.get_channel("WEB-YOUTUBE-740f513895b0"))

    def test_running_the_migration_again_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "twice.db"
            _legacy_rows(Database(path))
            first = Database(path).get_video("web-legacyyoutube0")
            second = Database(path).get_video("web-legacyyoutube0")
            self.assertEqual(first, second)

    def test_old_rows_still_read_where_the_identity_columns_are_empty(self) -> None:
        """A row written by another path after the migration falls back to its payload."""
        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            _legacy_rows(database)
            with closing(sqlite3.connect(database.path)) as connection, connection:
                connection.execute("UPDATE videos SET source_platform = '', native_video_id = ''")
            identity = source_identity.of(database, "web-legacyyoutube0")
            self.assertEqual(identity["platform"], "youtube")
            self.assertEqual(identity["native_video_id"], "dQw4w9WgXcQ")
            idea = database.create_idea_project("Một ý tưởng")
            self.assertEqual(source_identity.of(database, idea["youtube_video_id"])["platform"], "idea")


class RefreshTests(unittest.TestCase):
    def test_the_api_fills_in_the_channel_without_changing_the_row_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            _legacy_rows(database)
            youtube = _FakeYouTube()
            identity = source_identity.refresh(database, "web-legacyyoutube0", youtube=youtube)
            self.assertTrue(identity["refreshed"])
            self.assertEqual(identity["native_channel_id"], UC)
            self.assertEqual(identity["channel_identity"], source_identity.NATIVE)
            video = database.get_video("web-legacyyoutube0")
            self.assertEqual(video["youtube_channel_id"], "WEB-YOUTUBE-740f513895b0", "keys stay")
            self.assertEqual(video["view_count"], 2000)
            self.assertEqual(youtube.calls, [["dQw4w9WgXcQ"]])

    def test_yt_dlp_is_the_fallback_when_the_api_cannot_answer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            _legacy_rows(database)
            probe = mock.Mock(return_value=describe(_YOUTUBE_INFO, _YOUTUBE_INFO["webpage_url"]))
            identity = source_identity.refresh(
                database, "web-legacyyoutube0", youtube=_FakeYouTube(fail=True), probe=probe,
            )
            self.assertTrue(identity["refreshed"])
            self.assertEqual(identity["native_channel_id"], UC)
            self.assertIn("YouTube Data API", identity["refresh_error"])

    def test_a_lookup_that_cannot_be_made_is_reported_not_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            _legacy_rows(database)
            identity = source_identity.refresh(database, "web-legacyyoutube0", youtube=None, probe=None)
            self.assertFalse(identity["refreshed"])
            self.assertEqual(identity["native_channel_id"], "")
            self.assertTrue(identity["refresh_error"])

    def test_a_known_identity_is_not_looked_up_again(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            _legacy_rows(database)
            youtube = _FakeYouTube()
            source_identity.refresh(database, "abcdefghijk", youtube=youtube)
            self.assertEqual(youtube.calls, [])

    def test_a_poorer_later_reading_does_not_erase_a_good_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = _database(directory)
            _legacy_rows(database)
            database.set_video_source_identity("web-legacyyoutube0", native_channel_id=UC)
            database.set_video_source_identity("web-legacyyoutube0", native_channel_id="")
            self.assertEqual(database.get_video("web-legacyyoutube0")["native_channel_id"], UC)


if __name__ == "__main__":
    unittest.main()
