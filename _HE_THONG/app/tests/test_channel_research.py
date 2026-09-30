"""Channel Intelligence and the Phase 2 collectors, against a scripted YouTube.

One engine serves the channel manager and the plan step; a channel is
researched once, then reused, updated incrementally or redone as freshness
requires. Opening a channel never fetches. No test here reaches the network.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import unittest
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from unittest import mock

from youtube_monitor import channel_research, main, research_collectors
from youtube_monitor.channel_research import ChannelResearchService, compute_profile
from youtube_monitor.knowledge_store import ContentPatterns

NOW = datetime.now(timezone.utc)


def _uc() -> str:
    return "UC" + uuid.uuid4().hex[:22]


def _upload(index: int, *, days_ago: float, views: int, seconds: int = 300, title: str | None = None) -> dict:
    return {
        "id": f"v{index:03d}{uuid.uuid4().hex[:6]}",
        "snippet": {
            "title": title or f"Video số {index}",
            "publishedAt": (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z"),
            "tags": ["khoa học", "vũ trụ"] if index % 2 else ["khoa học"],
            "thumbnails": {"high": {"url": f"https://i.ytimg.com/{index}.jpg"}, **({"maxres": {}} if index % 3 == 0 else {})},
        },
        "contentDetails": {"duration": f"PT{seconds // 60}M{seconds % 60}S"},
        "statistics": {"viewCount": str(views), "likeCount": str(views // 20), "commentCount": "5"},
    }


class FakeYouTube:
    """A channel on a scripted Data API. Records every call it is asked."""

    api_key = "test-key-not-real"

    def __init__(self, channel_id: str, uploads: list[dict]):
        self.channel_id = channel_id
        self.uploads = uploads
        self.calls: list[tuple] = []
        self.hold: threading.Event | None = None
        self.entered = threading.Event()

    def get_channel_by_id(self, channel_id: str) -> dict:
        self.calls.append(("channels", channel_id))
        return {
            "youtube_channel_id": channel_id, "title": "Kênh Khoa Học", "description": "Giải thích khoa học",
            "handle": "@khoahoc", "subscriber_count": 12000, "video_count": len(self.uploads),
            "published_at": "2020-01-01T00:00:00Z", "thumbnail_url": "https://yt3/x.jpg",
        }

    def list_upload_video_ids(self, playlist: str, max_videos: int | None = 50) -> list[str]:
        self.calls.append(("playlistItems", playlist))
        return [item["id"] for item in self.uploads][: max_videos or 50]

    def get_videos(self, ids: list[str]) -> list[dict]:
        self.calls.append(("videos", tuple(ids)))
        if self.hold is not None:
            self.entered.set()
            self.hold.wait(10)
        known = {item["id"]: item for item in self.uploads}
        return [known[item] if item in known else _upload(0, days_ago=10, views=500, title=f"Tương tự {item}") | {"id": item} for item in ids]

    def search_videos(self, query: str, **options) -> list[dict]:
        self.calls.append(("search", query))
        titles = ["Vì sao Trái Đất quay?", "Top 5 sự thật về Trái Đất", "Trái Đất hình thành thế nào?",
                  "Hành tinh xanh", "10 điều về Mặt Trăng", "Trái Đất có tuổi bao nhiêu?", "Lõi Trái Đất", "Vũ trụ"]
        # Ids unique to this fake: tests share one database, and reuse is real.
        return [{"video_id": f"s{index}-{self.channel_id[-8:]}", "channel_id": _uc(), "channel_title": f"Kênh {index}", "title": title}
                for index, title in enumerate(titles[: options.get("max_results", 8)])]

    def list_comment_threads(self, video_id: str, **options) -> dict:
        self.calls.append(("commentThreads", video_id))
        texts = ["Giá bao nhiêu vậy?", "Video hay quá", "@nguoidung_test cái này giá sao?", "Giá hơi cao",
                 "Chán quá, sai thông tin", "Pin dùng được bao lâu?", "Giá tốt", "Hay"]
        count = min(options.get("max_results", 100), 40)
        return {
            "video_id": video_id,
            "comments": [{"text": texts[index % len(texts)], "like_count": index % 7, "reply_count": 0,
                          "published_at": "2026-09-01T00:00:00Z"} for index in range(count)],
            "disabled": False, "next_page_token": None,
        }


def _channel(count: int = 12) -> tuple[str, FakeYouTube]:
    channel_id = _uc()
    uploads = [
        _upload(index, days_ago=3 * index + 1, views=1000 + (9000 if index == 4 else 100 * index),
                seconds=45 if index % 4 == 0 else 420,
                title=("Vì sao bầu trời xanh?" if index % 3 == 0 else f"TOP {index} điều về vũ trụ"))
        for index in range(count)
    ]
    return channel_id, FakeYouTube(channel_id, uploads)


def _set(sql: str, *params) -> None:
    with closing(sqlite3.connect(main.database.path)) as connection, connection:
        connection.execute(sql, params)


class _Case(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient

        cls._client_cm = TestClient(main.app)
        cls.client = cls._client_cm.__enter__()
        cls.database = main.database

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)

    def setUp(self) -> None:
        self.channel_id, self.youtube = _channel()
        self.service = ChannelResearchService(self.database, self.youtube)
        patcher = mock.patch.object(main, "channel_research_service", self.service)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _ensure(self, mode: str = "auto") -> dict:
        return self.service.ensure(self.service.resolve(self.channel_id), mode=mode)

    def _calls(self, kind: str) -> int:
        return sum(1 for call in self.youtube.calls if call[0] == kind)


class ComputedStatisticsTests(unittest.TestCase):
    def test_the_numbers_are_arithmetic_over_what_was_read(self) -> None:
        _, youtube = _channel(12)
        from youtube_monitor.channel_research import video_row

        profile, performance = compute_profile([video_row(item) for item in youtube.uploads])
        self.assertEqual(profile["sample"]["videos"], 12)
        self.assertEqual(profile["duration"]["shorts"], 3, "videos 0, 4, 8 are 45 s")
        self.assertEqual(profile["duration"]["median_seconds"], 420)
        self.assertEqual(profile["cadence"]["median_gap_days"], 3.0)
        self.assertEqual(performance["measured_videos"], 12)
        self.assertEqual(performance["standouts"][0]["view_count"], 10000, "the 10,000-view video stands out")
        self.assertGreaterEqual(performance["standouts"][0]["times_median"], 1.5)
        shapes = {item["key"]: item["count"] for item in profile["titles"]["shapes"]}
        self.assertEqual(shapes["question"], 4)
        for word in ("score", "viral", "trend"):
            self.assertNotIn(word, json.dumps([profile, performance]))


class FullIncrementalReuseTests(_Case):
    def test_first_research_is_a_full_profile(self) -> None:
        result = self._ensure()
        self.assertEqual(result["status"], "new")
        self.assertEqual((self._calls("channels"), self._calls("playlistItems"), self._calls("videos")), (1, 1, 1))
        self.assertEqual(result["quota_units"], 3)
        profile = self.service.store.get("youtube", self.channel_id)
        self.assertEqual(profile["status"], "complete")
        self.assertEqual(profile["profile"]["channel"]["subscriber_count"], 12000)
        self.assertEqual(profile["profile"]["sample"]["videos"], 12)
        patterns = ContentPatterns(self.database).list("channel", f"youtube:{self.channel_id}", "title")
        self.assertTrue(any("câu hỏi" in item["description"] for item in patterns))

    def test_a_fresh_profile_checked_lately_is_reused_without_the_network(self) -> None:
        self._ensure()
        calls = len(self.youtube.calls)
        result = self._ensure()
        self.assertEqual(result["status"], "reused")
        self.assertFalse(result["network"])
        self.assertEqual(len(self.youtube.calls), calls)

    def test_a_fresh_profile_with_no_new_uploads_costs_one_check(self) -> None:
        first = self._ensure()
        _set("UPDATE channel_profiles SET last_checked_at = ? WHERE native_channel_id = ?",
             (NOW - timedelta(hours=7)).isoformat(), self.channel_id)
        calls = len(self.youtube.calls)
        result = self._ensure()
        self.assertEqual(result["status"], "reused")
        self.assertEqual(self.youtube.calls[calls:], [("playlistItems", "UU" + self.channel_id[2:])])
        self.assertEqual(result["profile_version"], first["profile_version"], "nothing changed, no new version")

    def test_enough_new_uploads_update_incrementally(self) -> None:
        first = self._ensure()
        full_at = self.service.store.get("youtube", self.channel_id)["last_full_at"]
        self.youtube.uploads = [_upload(100 + index, days_ago=0.5, views=50) for index in range(6)] + self.youtube.uploads
        _set("UPDATE channel_profiles SET last_checked_at = ? WHERE native_channel_id = ?",
             (NOW - timedelta(hours=7)).isoformat(), self.channel_id)
        result = self._ensure()
        self.assertEqual(result["status"], "incremental")
        self.assertEqual(result["new_uploads"], 6)
        profile = self.service.store.get("youtube", self.channel_id)
        self.assertEqual(profile["last_full_at"], full_at, "not a full refresh")
        self.assertGreater(profile["version"], first["profile_version"])
        self.assertEqual(self._calls("channels"), 1, "the channel itself was not read again")

    def test_an_old_profile_is_redone_in_full(self) -> None:
        self._ensure()
        _set("UPDATE channel_profiles SET last_full_at = ?, last_checked_at = ? WHERE native_channel_id = ?",
             (NOW - timedelta(days=31)).isoformat(), (NOW - timedelta(days=31)).isoformat(), self.channel_id)
        result = self._ensure()
        self.assertEqual(result["status"], "refreshed")
        self.assertEqual(self._calls("channels"), 2)

    def test_one_profile_per_channel_whichever_key_it_is_reached_by(self) -> None:
        synthetic = f"WEB-YOUTUBE-{uuid.uuid4().hex[:12]}"
        self.database.upsert_channel({"youtube_channel_id": synthetic, "channel_url": "https://x"})
        video_id = f"web-{uuid.uuid4().hex[:16]}"
        self.database.upsert_video({"youtube_video_id": video_id, "youtube_channel_id": synthetic,
                                    "video_url": "https://www.youtube.com/watch?v=abc", "metadata_hash": "h"})
        self.database.set_video_source_identity(video_id, source_platform="youtube", native_channel_id=self.channel_id)
        by_synthetic = self.service.resolve(synthetic)
        self.assertEqual(by_synthetic["ref"], f"youtube:{self.channel_id}")
        self.assertIn(synthetic, by_synthetic["row_keys"])
        self.service.ensure(by_synthetic)
        self.service.ensure(self.service.resolve(f"youtube:{self.channel_id}"))
        with closing(sqlite3.connect(self.database.path)) as connection:
            rows = connection.execute(
                "SELECT COUNT(*) FROM channel_profiles WHERE native_channel_id = ?", (self.channel_id,)
            ).fetchone()[0]
        self.assertEqual(rows, 1)
        self.assertIsNotNone(self.database.get_channel(synthetic), "the old synthetic row is kept")


class ChannelManagerApiTests(_Case):
    def test_opening_the_channel_manager_fetches_nothing(self) -> None:
        self.database.upsert_channel({"youtube_channel_id": self.channel_id, "channel_url": "https://x", "title": "Kênh"})
        self.client.get("/api/channels")
        body = self.client.get(f"/api/channels/{self.channel_id}/research").json()
        self.assertEqual(self.youtube.calls, [])
        self.assertEqual(body["research"]["summary"]["label"], "Chưa nghiên cứu")
        listed = next(item for item in self.client.get("/api/channels").json() if item["youtube_channel_id"] == self.channel_id)
        self.assertEqual(listed["research"]["state"], "none")
        self.assertEqual(self.youtube.calls, [])

    def test_the_button_runs_the_engine_and_the_status_follows_freshness(self) -> None:
        response = self.client.post(f"/api/channels/{self.channel_id}/research/refresh", json={"mode": "auto"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["result"]["status"], "new")
        body = self.client.get(f"/api/channels/{self.channel_id}/research").json()
        summary = body["research"]["summary"]
        self.assertEqual((summary["state"], summary["label"]), ("fresh", "Mới cập nhật"))
        self.assertEqual(summary["coverage"]["videos"], 12)
        self.assertIn("cadence", body["research"]["profile"])
        self.assertTrue(body["research"]["performance"]["standouts"])
        _set("UPDATE channel_profiles SET performance_at = ? WHERE native_channel_id = ?",
             (NOW - timedelta(days=4)).isoformat(), self.channel_id)
        summary = self.client.get(f"/api/channels/{self.channel_id}/research").json()["research"]["summary"]
        self.assertEqual((summary["state"], summary["label"]), ("stale", "Cần cập nhật"))

    def test_a_refresh_in_progress_is_visible_and_not_started_twice(self) -> None:
        self.youtube.hold = threading.Event()
        self.addCleanup(self.youtube.hold.set)
        thread = threading.Thread(
            target=lambda: self.client.post(f"/api/channels/{self.channel_id}/research/refresh", json={}), daemon=True,
        )
        thread.start()
        self.assertTrue(self.youtube.entered.wait(5))
        # A reloaded page asks the server, which knows.
        summary = self.client.get(f"/api/channels/{self.channel_id}/research").json()["research"]["summary"]
        self.assertEqual(summary["state"], "running")
        self.assertEqual(summary["run"]["stage"], "analyze_performance")
        self.assertIn("check_new_uploads", summary["run"]["stages_done"])
        second = self.client.post(f"/api/channels/{self.channel_id}/research/refresh", json={})
        self.assertEqual(second.status_code, 409)
        self.youtube.hold.set()
        thread.join(5)
        summary = self.client.get(f"/api/channels/{self.channel_id}/research").json()["research"]["summary"]
        self.assertEqual(summary["state"], "fresh")
        self.assertEqual(summary["last_run"]["status"], "success")

    def test_nothing_secret_is_returned(self) -> None:
        self.client.post(f"/api/channels/{self.channel_id}/research/refresh", json={})
        text = json.dumps(self.client.get(f"/api/channels/{self.channel_id}/research").json(), ensure_ascii=False)
        for secret in ("test-key-not-real", "cookie", "password", "profile_path", "api_key"):
            self.assertNotIn(secret, text)

    def test_monitoring_is_unchanged(self) -> None:
        self.database.upsert_channel({"youtube_channel_id": self.channel_id, "channel_url": "https://x",
                                      "title": "Kênh theo dõi", "subscriber_count": 50})
        self.client.post(f"/api/channels/{self.channel_id}/research/refresh", json={})
        channel = self.database.get_channel(self.channel_id)
        self.assertEqual((channel["title"], channel["subscriber_count"], channel["tracking_enabled"]), ("Kênh theo dõi", 50, 1))
        body = self.client.get(f"/api/channels/{self.channel_id}/research").json()
        self.assertEqual(body["monitoring"]["rows"][0]["channel_key"], self.channel_id)
        self.assertIn("statistics_snapshots", body["monitoring"])


def _fake_search(query: str, **options) -> list[dict]:
    return [{"title": f"Bài về {query}", "url": f"https://tin.test/{index}", "source": "tin.test", "snippet": "…"}
            for index in range(3)]


def _fake_page(url: str) -> str:
    return ('<html><head><meta property="article:published_time" content="2026-09-2%sT08:00:00+07:00"></head>'
            '<body><p>Nội dung bài viết về Trái Đất.</p></body></html>') % url[-1]


class PlanWithCollectorsTests(_Case):
    def setUp(self) -> None:
        super().setUp()
        collectors = research_collectors.Collectors(
            self.database, self.youtube, web_search=_fake_search, fetch_page=_fake_page,
            captions=lambda url: {"text": "Xin chào các bạn, hôm nay chúng ta tìm hiểu vì sao Trái Đất quay " * 3,
                                  "kind": "auto_captions", "language": "vi"},
        )
        for patcher in (
            mock.patch.object(main, "_research_collectors", return_value=collectors),
            mock.patch.object(main, "youtube", self.youtube),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _project(self) -> int:
        native = f"n{uuid.uuid4().hex[:10]}"
        self.database.upsert_channel({"youtube_channel_id": self.channel_id, "channel_url": "https://x"})
        self.database.upsert_video({
            "youtube_video_id": native, "youtube_channel_id": self.channel_id, "title": "Trái Đất quay",
            "video_url": f"https://www.youtube.com/watch?v={native}", "metadata_hash": native,
            "raw_payload": {"kind": "youtube#video", "id": native},
        })
        self.database.save_video_analysis(native, {
            "topic": "Trái Đất quay", "content_summary": "x", "keywords": ["trái đất"], "scene_map": [],
            "source_type": "video", "language": "vi",
        }, analysis_type="reference", provider="test")
        return int(self.database.create_production_project(native, title="Trái Đất")["id"])

    def test_a_plan_collects_real_evidence_and_records_the_channel_version_used(self) -> None:
        project_id = self._project()
        response = self.client.post(f"/api/projects/{project_id}/steps/plan", json={"options": {}})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        channel = result["source_channel"]
        self.assertEqual(channel["status"], "new")
        self.assertTrue(channel["profile_ref"].startswith("channel_profiles:"))
        report = self.client.get(f"/api/projects/{project_id}/plan").json()["research_report"]["report"]
        kinds = {}
        for item in report["evidence"]:
            kinds[item["source_kind"]] = kinds.get(item["source_kind"], 0) + 1
        self.assertEqual(kinds["video_meta"], 8)
        self.assertEqual(kinds["comment_sample"], 4, "the source and the top 3 similar videos")
        self.assertEqual(kinds["transcript"], 3)
        self.assertGreaterEqual(kinds.get("article", 0), 1)
        self.assertEqual(len(report["similar_content"]), 8)
        self.assertEqual(report["coverage"]["comments_sampled"], 40 * 4)
        self.assertTrue(report["timeline"])
        texts = [item["text"] for item in report["audience_insights"]]
        self.assertTrue(any("comment mẫu" in text and "/" in text for text in texts), texts)
        self.assertFalse(any("%" in text for text in texts))
        for item in report["audience_insights"]:
            self.assertTrue(item["evidence_ids"])
        self.assertTrue(report["competitor_patterns"], "title shapes of the similar videos")

        # The channel manager shows the same profile version the plan used.
        summary = self.client.get(f"/api/channels/{self.channel_id}/research").json()["research"]["summary"]
        self.assertEqual(summary["profile_version"], channel["profile_version"])
        self.assertEqual(summary["coverage"]["comments_sampled"], 40, "only the source's own comments count for its channel")

    def test_a_second_project_on_the_same_channel_reuses_its_profile(self) -> None:
        first = self.client.post(f"/api/projects/{self._project()}/steps/plan", json={"options": {}}).json()["result"]
        calls = self._calls("channels")
        second = self.client.post(f"/api/projects/{self._project()}/steps/plan", json={"options": {}}).json()["result"]
        self.assertEqual(second["source_channel"]["status"], "reused")
        self.assertEqual(second["source_channel"]["profile_version"], first["source_channel"]["profile_version"])
        self.assertEqual(self._calls("channels"), calls, "the channel was not researched again")

    def test_no_commenter_is_stored(self) -> None:
        self.client.post(f"/api/projects/{self._project()}/steps/plan", json={"options": {}})
        with closing(sqlite3.connect(self.database.path)) as connection:
            stored = " ".join(row[0] for row in connection.execute("SELECT patterns_json FROM audience_observations"))
        self.assertNotIn("nguoidung_test", stored)
        for word in ("author", "authorChannelId", "username", "profile_image"):
            self.assertNotIn(word, stored)


class DataHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = main.database

    def test_a_link_to_a_monitored_video_uses_the_monitors_row(self) -> None:
        from youtube_monitor.source_links import describe

        native = uuid.uuid4().hex[:11]
        channel_id = _uc()
        self.database.upsert_channel({"youtube_channel_id": channel_id, "channel_url": "https://x", "title": "Theo dõi"})
        self.database.upsert_video({
            "youtube_video_id": native, "youtube_channel_id": channel_id, "title": "Bản giám sát",
            "video_url": f"https://www.youtube.com/watch?v={native}", "metadata_hash": "m", "view_count": 10,
            "raw_payload": {"kind": "youtube#video", "id": native},
        })
        info = {"id": native, "extractor_key": "Youtube", "title": "Tiêu đề yt-dlp", "channel_id": channel_id,
                "webpage_url": f"https://www.youtube.com/watch?v={native}", "view_count": 15}
        youtube = FakeYouTube(channel_id, [])
        youtube.api_key = ""
        with mock.patch.object(main, "probe_source_link", return_value=describe(info, info["webpage_url"])), \
                mock.patch.object(main, "youtube", youtube):
            result = main._import_video_from_link(info["webpage_url"])
        self.assertTrue(result["reused_row"])
        self.assertEqual(result["video"]["youtube_video_id"], native)
        self.assertEqual(result["video"]["title"], "Bản giám sát", "the monitor's row is not rewritten")
        self.assertEqual(result["video"]["view_count"], 15)
        self.assertEqual(self.database.get_video_raw_payload(native).get("kind"), "youtube#video")
        self.assertEqual(len(self.database.find_videos_by_native_id("youtube", native)), 1)

    def test_a_partial_read_keeps_the_counts_it_did_not_get(self) -> None:
        video_id = f"p{uuid.uuid4().hex[:10]}"
        channel_id = _uc()
        self.database.upsert_channel({"youtube_channel_id": channel_id, "channel_url": "https://x"})
        base = {"youtube_video_id": video_id, "youtube_channel_id": channel_id, "video_url": "https://x", "metadata_hash": "a"}
        self.database.upsert_video({**base, "view_count": 100, "like_count": 9, "comment_count": 3})
        self.database.upsert_video({**base, "view_count": 120, "like_count": None, "comment_count": None})
        video = self.database.get_video(video_id)
        self.assertEqual((video["view_count"], video["like_count"], video["comment_count"]), (120, 9, 3))

    def test_old_duplicates_are_reported_not_merged(self) -> None:
        native = uuid.uuid4().hex[:11]
        channel_id = _uc()
        self.database.upsert_channel({"youtube_channel_id": channel_id, "channel_url": "https://x"})
        for key in (native, f"web-{uuid.uuid4().hex[:16]}"):
            self.database.upsert_video({"youtube_video_id": key, "youtube_channel_id": channel_id,
                                        "video_url": "https://x", "metadata_hash": key})
            self.database.set_video_source_identity(key, source_platform="youtube", native_video_id=native)
        found = [row for row in self.database.duplicate_native_videos() if row["native_video_id"] == native]
        self.assertEqual(found[0]["rows_count"], 2)
        self.assertEqual(len(self.database.find_videos_by_native_id("youtube", native)), 2, "both rows kept")


if __name__ == "__main__":
    unittest.main()
