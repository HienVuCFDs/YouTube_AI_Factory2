"""The channel tab's view model: what GET /api/channels and GET …/research add
for the page, read from the database only.
"""

from __future__ import annotations

import json
import uuid
from unittest import mock

from tests.test_channel_research import _Case, _fake_page, _fake_search
from youtube_monitor import main, research_collectors
from youtube_monitor.research_collectors import Collectors


class ChannelListViewTests(_Case):
    def test_each_channel_says_its_platform_and_identity(self) -> None:
        suffix = uuid.uuid4().hex[:8]
        rows = {
            self.channel_id: "youtube",
            f"site-shopee{suffix}.vn": "shop",
            f"site-bao{suffix}.test": "web",
            f"WEB-TIKTOK-{suffix}": "tiktok",
            f"WEB-HTML5MED-{suffix}": "web",
        }
        for key, _ in rows.items():
            self.database.upsert_channel({"youtube_channel_id": key, "channel_url": "https://x",
                                          "group_name": "shop" if "shopee" in key else ""})
        listed = {item["youtube_channel_id"]: item for item in self.client.get("/api/channels").json()}
        for key, platform in rows.items():
            self.assertEqual(listed[key]["identity"]["platform"], platform, key)
        self.assertEqual(listed[self.channel_id]["identity"]["native_channel_id"], self.channel_id)
        self.assertTrue(listed[self.channel_id]["identity"]["resolved"])
        self.assertEqual(listed[f"site-bao{suffix}.test"]["research"]["state"], "not_applicable")
        self.assertEqual(listed[f"WEB-HTML5MED-{suffix}"]["research"]["state"], "not_applicable",
                         "a page read by a catch-all extractor has no channel")
        self.assertEqual(listed[f"WEB-TIKTOK-{suffix}"]["research"]["state"], "unresolved")
        self.assertEqual(self.youtube.calls, [], "listing fetched nothing")


class DuplicateChannelTests(_Case):
    """A channel filed under an old synthetic row and its real row is one channel."""

    def setUp(self) -> None:
        super().setUp()
        self.synthetic = f"WEB-YOUTUBE-{uuid.uuid4().hex[:12]}"
        self.database.upsert_channel({"youtube_channel_id": self.channel_id, "channel_url": "https://x", "title": "Kênh thật"})
        self.database.upsert_channel({"youtube_channel_id": self.synthetic, "channel_url": "https://x", "title": "Kênh thật · Youtube"})
        self.legacy_video = f"web-{uuid.uuid4().hex[:16]}"
        self.database.upsert_video({
            "youtube_video_id": self.legacy_video, "youtube_channel_id": self.synthetic, "title": "Video cũ",
            "video_url": "https://www.youtube.com/watch?v=abcdefghijk", "metadata_hash": "h",
        })
        self.database.set_video_source_identity(self.legacy_video, source_platform="youtube", native_channel_id=self.channel_id)
        self.project_id = int(self.database.create_production_project(self.legacy_video, title="Dự án cũ")["id"])

    def test_the_list_marks_one_row_per_channel_and_keeps_both(self) -> None:
        listed = {item["youtube_channel_id"]: item for item in self.client.get("/api/channels").json()}
        self.assertIn(self.synthetic, listed, "the old row is still returned for the pickers")
        self.assertTrue(listed[self.channel_id]["display"]["primary"], "the native row is the one shown")
        self.assertFalse(listed[self.synthetic]["display"]["primary"])
        self.assertEqual(listed[self.synthetic]["display"]["primary_key"], self.channel_id)
        self.assertEqual(sorted(listed[self.channel_id]["display"]["group_keys"]), sorted([self.channel_id, self.synthetic]))
        self.assertIsNotNone(self.database.get_channel(self.synthetic), "nothing was deleted")

    def test_the_detail_gathers_both_rows(self) -> None:
        body = self.client.get(f"/api/channels/{self.channel_id}/research").json()
        self.assertEqual({row["channel_key"] for row in body["monitoring"]["rows"]}, {self.channel_id, self.synthetic})
        self.assertIn(self.legacy_video, {item["row_key"] for item in body["videos"]})
        via_old = self.client.get(f"/api/channels/{self.synthetic}/research").json()
        self.assertEqual(via_old["identity"]["ref"], body["identity"]["ref"])

    def test_the_old_project_and_video_still_open(self) -> None:
        self.assertEqual(self.client.get(f"/api/projects/{self.project_id}").status_code, 200)
        # The studio opens a video from the catalogue, by its row key and channel.
        catalogue = {item["youtube_video_id"]: item for item in self.client.get("/api/videos?limit=500").json()}
        self.assertIn(self.legacy_video, catalogue)
        self.assertEqual(catalogue[self.legacy_video]["youtube_channel_id"], self.synthetic, "its row keys are unchanged")


class ChannelDetailViewTests(_Case):
    def setUp(self) -> None:
        super().setUp()
        self.database.upsert_channel({"youtube_channel_id": self.channel_id, "channel_url": "https://x",
                                      "title": "Kênh", "thumbnail_url": "https://yt3/avatar.jpg"})

    def test_videos_merge_the_library_and_the_research_window(self) -> None:
        self.client.post(f"/api/channels/{self.channel_id}/research/refresh", json={})
        in_library = self.youtube.uploads[0]["id"]
        self.database.upsert_video({
            "youtube_video_id": in_library, "youtube_channel_id": self.channel_id, "title": "Có trong kho",
            "video_url": f"https://www.youtube.com/watch?v={in_library}", "metadata_hash": "a",
            "thumbnail_url": "https://i.ytimg.com/own.jpg", "raw_payload": {"kind": "youtube#video"},
        })
        calls = len(self.youtube.calls)
        body = self.client.get(f"/api/channels/{self.channel_id}/research").json()
        self.assertEqual(len(self.youtube.calls), calls, "the detail fetched nothing")
        videos = {item["video_id"]: item for item in body["videos"]}
        self.assertEqual(len(videos), 12, "one entry per video, the library copy not doubled")
        self.assertTrue(videos[in_library]["in_library"])
        self.assertEqual(videos[in_library]["row_key"], in_library)
        other = next(item for key, item in videos.items() if key != in_library)
        self.assertFalse(other["in_library"])
        self.assertEqual(other["thumbnail_url"], f"https://i.ytimg.com/vi/{other['video_id']}/mqdefault.jpg")
        self.assertEqual(len(body["recent_videos"]), 12)
        self.assertEqual(body["avatar_url"], "https://yt3/avatar.jpg")
        dates = [str(item["published_at"] or "") for item in body["videos"]]
        self.assertTrue(videos[in_library]["published_at"], "a date the library lacks comes from research")
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_the_latest_report_is_summed_up_in_plain_words(self) -> None:
        def blocked(url):
            if url.endswith("/1"):
                raise PermissionError("Client error '403 Forbidden' for url https://tin.test/1")
            return _fake_page(url)

        from tests.test_research_engine import _captions, _video_project

        with mock.patch.object(main, "_research_collectors", side_effect=lambda: Collectors(
                self.database, self.youtube, web_search=_fake_search, fetch_page=blocked, captions=_captions)), \
                mock.patch.object(main, "youtube", self.youtube):
            project_id = _video_project(self.database, self.channel_id)
            self.client.post(f"/api/projects/{project_id}/steps/plan", json={"options": {"reason": False}})
        latest = self.client.get(f"/api/channels/{self.channel_id}/research").json()["latest_report"]
        self.assertEqual(latest["project_id"], project_id)
        self.assertEqual(latest["status"], "partial")
        self.assertEqual(latest["similar_videos"], 8)
        self.assertEqual(latest["transcripts"], 3)
        self.assertGreaterEqual(latest["comments_sampled"], 1)
        self.assertEqual(latest["unread_sources"], [{"what": "Trang web", "where": "tin.test", "why": "trang chặn truy cập tự động"}])
        text = json.dumps(latest, ensure_ascii=False)
        for technical in ("403", "Forbidden", "web.search", "collector"):
            self.assertNotIn(technical, text)

    def test_a_channel_without_research_has_empty_extras_not_errors(self) -> None:
        body = self.client.get(f"/api/channels/{self.channel_id}/research").json()
        self.assertEqual(body["videos"], [])
        self.assertEqual(body["recent_videos"], [])
        self.assertIsNone(body["latest_report"])
        self.assertEqual(body["research"]["summary"]["label"], "Chưa nghiên cứu")
        self.assertEqual(self.youtube.calls, [])

    def test_the_detail_never_uses_collectors(self) -> None:
        boom = mock.Mock(side_effect=AssertionError("collector used by a GET"))
        with mock.patch.object(research_collectors.Collectors, "similar_videos", boom), \
                mock.patch.object(research_collectors.Collectors, "web", boom), \
                mock.patch.object(research_collectors.Collectors, "transcripts", boom):
            self.assertEqual(self.client.get(f"/api/channels/{self.channel_id}/research").status_code, 200)
