"""The older link endpoints go through the same importer as "Thêm nguồn".

On 30/09 an older link import of a YouTube video was re-imported through the
importer directly. Its row moved from the synthetic channel it was filed under
onto the real channel; the old channel row was left empty and KÊNH showed the
channel twice. The incident is rebuilt here, on a database of its own - the
app's real database is never opened.
"""

from __future__ import annotations

import contextlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from youtube_monitor import main
from youtube_monitor.database import Database
from youtube_monitor.source_links import describe

SYNTHETIC = "WEB-YOUTUBE-740f513895b0"  # the channel row the old import was filed under
NATIVE = "UCw0YZ5HG7zOJsV3ZMRZZwvA"  # the video's real channel, followed separately
ROW = "web-cc2aba7cb65fe6e0"  # the old import's row key
VIDEO = "glYtv6VartM"  # the YouTube video it stands for
URL = f"https://www.youtube.com/watch?v={VIDEO}"
REAL_DATABASE = Path(__file__).resolve().parents[2] / "data" / "youtube_monitor.db"


class _NoNetwork:
    """A YouTube client that fails the test if it is asked anything."""

    api_key = "k"

    def __getattr__(self, name: str):
        raise AssertionError(f"YouTube API used: {name}")


class _Incident(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.database = Database(str(Path(self._tmp.name) / "incident.db"))
        self.database.initialize()
        self.database.upsert_channel({"youtube_channel_id": NATIVE, "handle": "@vuive", "title": "Vui Vẻ",
                                      "channel_url": f"https://www.youtube.com/channel/{NATIVE}",
                                      "uploads_playlist_id": "UU" + NATIVE[2:], "subscriber_count": 1240000})
        self.database.upsert_channel({"youtube_channel_id": SYNTHETIC, "title": "Vui Vẻ · Youtube",
                                      "channel_url": "https://www.youtube.com/@VuiVe", "group_name": "Youtube"})
        self.database.upsert_video({
            "youtube_video_id": ROW, "youtube_channel_id": SYNTHETIC, "video_url": URL,
            "title": "Trái Đất được tạo ra như thế nào??", "duration_seconds": 62, "metadata_hash": ROW,
            "raw_payload": {"source": "link_import", "platform": "Youtube", "native_id": VIDEO},
        })
        self.database.set_video_source_identity(ROW, source_platform="youtube", source_extractor="Youtube",
                                                native_video_id=VIDEO, native_channel_id=NATIVE,
                                                native_channel_name="Vui Vẻ")
        # Like project #57: made from that row, already transcribed and analysed.
        self.project_id = int(self.database.create_production_project(ROW, title="Trái Đất được tạo ra như thế nào??")["id"])
        self.database.save_transcript(ROW, "Trái Đất hình thành từ đĩa bụi quanh Mặt Trời.", source_type="whisper_auto")
        self.database.save_video_analysis(ROW, {"topic": "Trái Đất hình thành", "source_type": "video"}, analysis_type="reference")
        for patcher in (
            mock.patch.object(main, "database", self.database),
            mock.patch.object(main, "youtube", _NoNetwork()),
            mock.patch.object(main, "probe_source_link", side_effect=AssertionError("yt-dlp asked")),
            mock.patch("httpx.get", side_effect=AssertionError("network")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        client = TestClient(main.app)
        self.client = client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)

    def state(self) -> dict:
        """Everything the incident changed or could have: rows, channels, the project and what hangs off it."""
        with contextlib.closing(sqlite3.connect(self.database.path)) as connection:
            read = lambda sql: connection.execute(sql).fetchall()  # noqa: E731
            return {
                "videos": read("SELECT youtube_video_id, youtube_channel_id, native_video_id, native_channel_id, title FROM videos ORDER BY id"),
                "channels": read("SELECT youtube_channel_id, title, channel_url, group_name, tracking_enabled, uploads_playlist_id FROM channels ORDER BY id"),
                "projects": read("SELECT id, youtube_video_id, title FROM production_projects ORDER BY id"),
                "transcripts": read("SELECT youtube_video_id, content_text FROM transcripts ORDER BY id"),
                "analyses": read("SELECT youtube_video_id, analysis_type, result_json FROM video_analyses ORDER BY id"),
            }


class TheIncidentDoesNotRepeatTests(_Incident):
    CALLS = (
        ("/api/videos/import-link", {"url": URL}),
        ("/api/videos/import-link", {"url": f"https://youtu.be/{VIDEO}?si=abc"}),
        ("/api/videos/import", {"reference": URL}),
        ("/api/sources/import", {"text": URL}),
    )

    def test_importing_the_same_video_again_reuses_the_row_and_moves_nothing(self) -> None:
        before = self.state()
        for path, body in self.CALLS:
            with self.subTest(path=path, body=body):
                response = self.client.post(path, json=body)
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertEqual((result["status"], result["reused_row"]), ("exists", True))
                self.assertEqual(result["video"]["youtube_video_id"], ROW, "the existing row is the answer")
                self.assertEqual(result["video"]["youtube_channel_id"], SYNTHETIC, "its channel key is not changed")
                self.assertEqual(result["channel"]["youtube_channel_id"], SYNTHETIC)
                after = self.state()
                self.assertEqual(after, before, "no row, channel, project, transcript or analysis changed")
        # One identity for the video, one row.
        self.assertEqual([row["youtube_video_id"] for row in self.database.find_videos_by_native_id("youtube", VIDEO)], [ROW])
        self.assertEqual(self.database.duplicate_native_videos(), [])
        self.assertIsNone(self.database.get_video(VIDEO), "no second row under the native id")
        # What KÊNH groups the two channel rows by is still there.
        self.assertEqual([item["native_channel_id"] for item in self.database.native_channels_of_row(SYNTHETIC)], [NATIVE])
        # The project, its transcript and its analysis are where they were.
        self.assertEqual(self.database.get_production_project(self.project_id)["youtube_video_id"], ROW)
        self.assertTrue(self.database.get_transcript(ROW)["content_text"].startswith("Trái Đất hình thành"))
        self.assertEqual(self.database.get_video_analysis(ROW, analysis_type="reference")["result"]["topic"], "Trái Đất hình thành")

    def test_even_the_importer_called_directly_leaves_the_row_on_its_channel(self) -> None:
        # What happened on 30/09: the read succeeds and names the real channel.
        info = {"id": VIDEO, "extractor_key": "Youtube", "title": "Trái Đất được tạo ra như thế nào??",
                "channel_id": NATIVE, "channel": "Vui Vẻ", "duration": 62, "webpage_url": URL, "view_count": 4200}
        channels = self.state()["channels"]
        with mock.patch.object(main, "probe_source_link", return_value=describe(info, URL)), \
                mock.patch.object(main, "_official_youtube_details",
                                  return_value={"native_channel_id": NATIVE, "channel_name": "Vui Vẻ", "view_count": 4300}):
            result = main._import_video_from_link(URL)
        self.assertEqual(result["video"]["youtube_video_id"], ROW)
        self.assertEqual(self.database.get_video(ROW)["youtube_channel_id"], SYNTHETIC)
        self.assertEqual(self.state()["channels"], channels, "neither channel row was rewritten")
        self.assertEqual(self.database.get_video(ROW)["view_count"], 4300, "what was read is still recorded")
        self.assertEqual(len(self.state()["videos"]), 1)


class OneImporterTests(_Incident):
    def test_both_endpoints_are_adapters_over_the_same_helper(self) -> None:
        with mock.patch.object(main, "_add_link_source", return_value={"status": "exists"}) as shared:
            self.client.post("/api/videos/import-link", json={"url": URL, "group_name": "A"})
            self.client.post("/api/sources/import", json={"text": URL, "group_name": "A"})
            self.client.post("/api/videos/import", json={"reference": "https://www.bilibili.com/video/BV1xx411c7mD"})
        self.assertEqual(shared.call_count, 3)
        legacy, universal, reference = shared.call_args_list
        self.assertEqual((legacy.args[0], universal.args[0]), (URL, URL))
        self.assertEqual(legacy.kwargs, {"group_name": "A", "allow_channel": False})
        self.assertEqual(universal.kwargs, {"group_name": "A"})
        self.assertFalse(reference.kwargs["allow_channel"])

    def test_the_importer_has_no_caller_but_the_helper(self) -> None:
        import inspect
        import re

        source = inspect.getsource(main)
        calls = re.findall(r"^(?!def ).*\b_import_video_from_link\(", source, flags=re.M)
        self.assertEqual(len(calls), 1, "only _add_link_source reaches the importer")
        self.assertIn("_import_video_from_link(", inspect.getsource(main._add_link_source))

    def test_a_new_link_is_still_imported_through_the_older_endpoint(self) -> None:
        url = "https://www.tiktok.com/@kenh/video/7300000000000000001"
        info = {"id": "7300000000000000001", "extractor_key": "TikTok", "title": "Clip mới", "uploader": "kenh",
                "uploader_id": "MS4w_kenh", "duration": 15, "webpage_url": url}
        with mock.patch.object(main, "probe_source_link", return_value=describe(info, url)):
            result = self.client.post("/api/videos/import-link", json={"url": url}).json()
            again = self.client.post("/api/videos/import-link", json={"url": url + "?lang=vi"}).json()
        self.assertEqual((result["status"], result["kind"], result["video"]["source_kind"]), ("imported", "video", "video"))
        self.assertEqual((again["status"], again["video"]["youtube_video_id"]), ("exists", result["video"]["youtube_video_id"]))
        self.assertTrue(self.database.is_source_item(result["video"]["youtube_video_id"]))

    def test_a_channel_link_is_not_a_video(self) -> None:
        response = self.client.post("/api/videos/import-link", json={"url": f"https://www.youtube.com/channel/{NATIVE}"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("kênh", response.json()["detail"])


class TheRealDatabaseIsNotOpenedTests(unittest.TestCase):
    def test_these_tests_run_on_databases_of_their_own(self) -> None:
        self.assertNotEqual(Path(main.database.path).resolve(), REAL_DATABASE)
        self.assertNotIn("_HE_THONG", str(Path(main.database.path).resolve()))


if __name__ == "__main__":
    unittest.main()
