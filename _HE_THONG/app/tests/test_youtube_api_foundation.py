"""The YouTube Data API calls research will need, priced before they are spent.

A search costs 100 of the day's 10,000 units, a page of comments costs 1. The
wrappers below are the official path for YouTube metrics, search and comments;
every call is written to the usage ledger and refused once the day's limit
would be passed. No test here reaches the network.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from youtube_monitor import youtube_client
from youtube_monitor.database import Database
from youtube_monitor.youtube_client import YouTubeClient, YouTubeQuotaExceeded
from youtube_monitor.youtube_quota import PROVIDER, YouTubeQuota, day_start_utc

UC = "UCabcdefghijklmnopqrstuv"


class _Response:
    def __init__(self, status: int, payload: dict):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _Api:
    """A scripted Data API: resource name → response."""

    def __init__(self, responses: dict[str, _Response]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict, timeout: float) -> _Response:
        resource = url.rsplit("/", 1)[-1]
        self.calls.append((resource, params))
        return self.responses[resource]


def _video(video_id: str, published: str, views: int) -> dict:
    return {
        "id": video_id,
        "snippet": {"channelId": UC, "title": video_id, "publishedAt": published, "thumbnails": {}},
        "contentDetails": {"duration": "PT3M"},
        "statistics": {"viewCount": str(views), "likeCount": "1", "commentCount": "2"},
    }


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self._directory.name) / "quota.db")
        self.quota = YouTubeQuota(self.database, daily_limit=10_000)
        self.client = YouTubeClient("test-key", quota=self.quota)

    def tearDown(self) -> None:
        self._directory.cleanup()

    def _with(self, api: _Api):
        return mock.patch.object(youtube_client.httpx, "get", side_effect=api.get)


class SearchTests(_Case):
    def test_a_search_returns_ids_and_costs_a_hundred_units(self) -> None:
        api = _Api({"search": _Response(200, {"items": [
            {"id": {"videoId": "v1"}, "snippet": {"channelId": UC, "channelTitle": "Kênh", "title": "Một", "publishedAt": "2026-09-01T00:00:00Z"}},
            {"id": {"channelId": "UCnotavideo"}, "snippet": {}},
        ]})})
        with self._with(api):
            found = self.client.search_videos("trái đất hình thành", max_results=5, relevance_language="vi")
        self.assertEqual([item["video_id"] for item in found], ["v1"])
        self.assertEqual(api.calls[0][1]["type"], "video")
        self.assertEqual(api.calls[0][1]["relevanceLanguage"], "vi")
        self.assertEqual(self.quota.used_today(), 100)

    def test_an_empty_query_spends_nothing(self) -> None:
        with self._with(_Api({})) as get:
            self.assertEqual(self.client.search_videos("  "), [])
        get.assert_not_called()


class ChannelRecentVideosTests(_Case):
    def test_recent_uploads_come_with_counts_for_two_units(self) -> None:
        api = _Api({
            "playlistItems": _Response(200, {"items": [
                {"contentDetails": {"videoId": "old"}}, {"contentDetails": {"videoId": "new"}},
            ]}),
            "videos": _Response(200, {"items": [
                _video("old", "2026-08-01T00:00:00Z", 10), _video("new", "2026-09-20T00:00:00Z", 99),
            ]}),
        })
        with self._with(api):
            videos = self.client.list_channel_recent_videos(UC, max_results=10)
        self.assertEqual([call[0] for call in api.calls], ["playlistItems", "videos"], "no channels call for a UC id")
        self.assertEqual(api.calls[0][1]["playlistId"], "UU" + UC[2:])
        self.assertEqual([video["video_id"] for video in videos], ["new", "old"])
        self.assertEqual(videos[0]["view_count"], 99)
        self.assertEqual(videos[0]["duration_seconds"], 180)
        self.assertEqual(self.quota.used_today(), 2)


class CommentThreadTests(_Case):
    def test_comments_come_back_without_anyone_named(self) -> None:
        api = _Api({"commentThreads": _Response(200, {"nextPageToken": "p2", "items": [{
            "snippet": {"totalReplyCount": 2, "topLevelComment": {"snippet": {
                "textDisplay": "Pin dùng được bao lâu?", "likeCount": 7, "publishedAt": "2026-09-02T00:00:00Z",
                "authorDisplayName": "Ai Đó", "authorChannelId": {"value": "UCsomeone"},
                "authorProfileImageUrl": "https://x/y.jpg", "authorChannelUrl": "https://youtube.com/@aido",
            }}},
        }]})})
        with self._with(api):
            page = self.client.list_comment_threads("abc", max_results=500)
        self.assertEqual(api.calls[0][1]["maxResults"], 100, "the API's page limit")
        comment = page["comments"][0]
        self.assertEqual(set(comment), {"text", "like_count", "reply_count", "published_at"})
        self.assertEqual(comment["like_count"], 7)
        self.assertEqual(page["next_page_token"], "p2")
        self.assertFalse(page["disabled"])
        self.assertEqual(self.quota.used_today(), 1)

    def test_comments_turned_off_are_an_empty_sample_not_an_error(self) -> None:
        api = _Api({"commentThreads": _Response(403, {"error": {
            "message": "disabled", "errors": [{"reason": "commentsDisabled"}],
        }})})
        with self._with(api):
            page = self.client.list_comment_threads("abc")
        self.assertTrue(page["disabled"])
        self.assertEqual(page["comments"], [])

    def test_other_errors_are_raised_and_still_charged(self) -> None:
        api = _Api({"commentThreads": _Response(404, {"error": {"message": "videoNotFound", "errors": [{"reason": "videoNotFound"}]}})})
        with self._with(api), self.assertRaises(youtube_client.YouTubeApiError):
            self.client.list_comment_threads("abc")
        self.assertEqual(self.quota.used_today(), 1)


class QuotaTests(_Case):
    def test_a_call_over_the_days_limit_is_refused_before_it_is_made(self) -> None:
        self.quota.daily_limit = 150
        api = _Api({"search": _Response(200, {"items": []})})
        with self._with(api):
            self.client.search_videos("một")
            with self.assertRaises(YouTubeQuotaExceeded):
                self.client.search_videos("hai")
        self.assertEqual(len(api.calls), 1, "the refused call never reached Google")
        self.assertEqual(self.quota.remaining(), 50)

    def test_the_monitors_own_calls_are_counted_too(self) -> None:
        api = _Api({"videos": _Response(200, {"items": [_video("v", "2026-09-01T00:00:00Z", 1)]})})
        with self._with(api):
            self.client.get_videos(["v"])
        self.assertEqual(self.database.provider_units_since(PROVIDER, day_start_utc()), 1)

    def test_a_network_failure_spends_nothing(self) -> None:
        with mock.patch.object(youtube_client.httpx, "get", side_effect=youtube_client.httpx.ConnectError("offline")):
            with self.assertRaises(youtube_client.YouTubeApiError):
                self.client.get_videos(["v"])
        self.assertEqual(self.quota.used_today(), 0)

    def test_the_day_is_pacific_time(self) -> None:
        # 07:30 UTC on 29 Sep is 00:30 in Los Angeles (PDT, UTC-7): the day began at 07:00 UTC.
        start = day_start_utc(datetime(2026, 9, 29, 7, 30, tzinfo=timezone.utc))
        self.assertEqual(start, "2026-09-29T07:00:00+00:00")

    def test_a_client_without_a_quota_behaves_as_before(self) -> None:
        api = _Api({"videos": _Response(200, {"items": []})})
        with self._with(api):
            YouTubeClient("test-key").get_videos(["v"])
        self.assertEqual(self.quota.used_today(), 0)


class TheKeyNeverShowsTests(_Case):
    KEY = "AIzaSyTEST-not-a-real-key-000000000"

    def setUp(self) -> None:
        super().setUp()
        self.client = YouTubeClient(self.KEY, quota=self.quota)

    def test_a_network_error_quoting_the_url_does_not_leak_it(self) -> None:
        failure = youtube_client.httpx.ConnectError(
            f"failed: https://www.googleapis.com/youtube/v3/videos?part=snippet&key={self.KEY}&id=x"
        )
        with mock.patch.object(youtube_client.httpx, "get", side_effect=failure):
            with self.assertRaises(youtube_client.YouTubeApiError) as caught:
                self.client.get_videos(["x"])
        self.assertNotIn(self.KEY, str(caught.exception))
        self.assertIn("key=***", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__, "the original error, URL and all, is not chained on")

    def test_an_error_body_echoing_the_key_does_not_leak_it(self) -> None:
        api = _Api({"videos": _Response(400, {"error": {"message": f"Bad request for key {self.KEY}", "errors": []}})})
        with self._with(api), self.assertRaises(youtube_client.YouTubeApiError) as caught:
            self.client.get_videos(["x"])
        self.assertNotIn(self.KEY, str(caught.exception))

    def test_the_client_does_not_print_its_key(self) -> None:
        self.assertNotIn(self.KEY, repr(self.client))
        self.assertNotIn(self.KEY, str(self.quota.status()))


class ChannelMonitoringStillWorksTests(_Case):
    """The monitor's own sync goes through the same client, now priced."""

    def test_adding_and_syncing_a_channel_still_works_and_is_counted(self) -> None:
        from youtube_monitor.service import SyncService

        api = _Api({
            "channels": _Response(200, {"items": [{
                "id": UC, "snippet": {"title": "Kênh theo dõi", "thumbnails": {}},
                "contentDetails": {"relatedPlaylists": {"uploads": "UU" + UC[2:]}},
                "statistics": {"subscriberCount": "1000", "videoCount": "2"},
            }]}),
            "playlistItems": _Response(200, {"items": [{"contentDetails": {"videoId": "v1"}}]}),
            "videos": _Response(200, {"items": [_video("v1", "2026-09-20T00:00:00Z", 55)]}),
        })
        service = SyncService(self.database, self.client)
        with self._with(api):
            result = service.add_channel(UC)
        self.assertEqual(result["videos_new"], 1)
        channel = self.database.get_channel(UC)
        self.assertEqual((channel["title"], channel["subscriber_count"], channel["tracking_enabled"]), ("Kênh theo dõi", 1000, 1))
        video = self.database.get_video("v1")
        self.assertEqual(video["view_count"], 55)
        self.assertIsNotNone(video["metrics_captured_at"], "counts carry the time they were read")
        self.assertEqual(self.quota.used_today(), 4, "channels twice, playlistItems, videos")


if __name__ == "__main__":
    unittest.main()
