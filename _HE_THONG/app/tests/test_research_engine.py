"""The Phase 2 research engine, checked point by point before any UI.

One channel engine for the manager and the plan; reads that never fetch;
budgets that hold; a ranking where views are one signal of four; counts of
comments, not of words; snippets that are not articles; reports that survive a
collector failing; reuse that makes a second plan cheap; and runs that neither
collide nor duplicate. No test here reaches the network.
"""

from __future__ import annotations

import inspect
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

from tests.test_channel_research import FakeYouTube, _Case, _channel, _fake_page, _fake_search, _uc, _upload
from youtube_monitor import channel_research, main, project_planner, research_collectors, research_evidence
from youtube_monitor.channel_research import ChannelResearchService
from youtube_monitor.research_collectors import Budget, Collectors, comment_patterns, rank_similar

NOW = datetime.now(timezone.utc)


class PagedFakeYouTube(FakeYouTube):
    """Comments in pages, as many as asked for and more: the caps must hold."""

    available_comments = 180

    def list_comment_threads(self, video_id: str, **options) -> dict:
        self.calls.append(("commentThreads", video_id, options.get("max_results"), options.get("page_token")))
        page = int(options.get("page_token") or 0)
        size = min(options.get("max_results", 100), 100)
        start = page * size
        count = max(0, min(size, self.available_comments - start))
        more = start + count < self.available_comments
        return {
            "video_id": video_id,
            "comments": [{"text": "pin pin pin pin" if index % 2 else "giá bao nhiêu?", "like_count": 1,
                          "reply_count": 0, "published_at": "2026-09-01T00:00:00Z"} for index in range(count)],
            "disabled": False, "next_page_token": str(page + 1) if more else None,
        }


def _captions(url: str) -> dict:
    return {"text": "Mở đầu bằng một câu hỏi về Trái Đất " * 5, "kind": "auto_captions", "language": "vi"}


def _video_project(database, channel_id: str, *, topic: str | None = None) -> int:
    # A topic of its own per test unless shared on purpose: reuse is real, and
    # tests share one database.
    topic = topic or f"Trái Đất quay {uuid.uuid4().hex[:6]}"
    native = f"n{uuid.uuid4().hex[:10]}"
    database.upsert_channel({"youtube_channel_id": channel_id, "channel_url": "https://x"})
    database.upsert_video({
        "youtube_video_id": native, "youtube_channel_id": channel_id, "title": topic,
        "video_url": f"https://www.youtube.com/watch?v={native}", "metadata_hash": native,
        "published_at": (NOW - timedelta(days=60)).isoformat(),
        "raw_payload": {"kind": "youtube#video", "id": native},
    })
    database.save_video_analysis(native, {
        "topic": topic, "content_summary": "x", "keywords": ["trái đất", "hành tinh"], "scene_map": [],
        "source_type": "video", "language": "vi",
    }, analysis_type="reference", provider="test")
    return int(database.create_production_project(native, title=topic)["id"])


class _PlanCase(_Case):
    fake_class = PagedFakeYouTube

    def setUp(self) -> None:
        self.channel_id = _uc()
        self.youtube = self.fake_class(self.channel_id, [
            _upload(index, days_ago=2 * index + 1, views=500 + 50 * index) for index in range(10)
        ])
        self.service = ChannelResearchService(self.database, self.youtube)
        self.collectors = Collectors(self.database, self.youtube, web_search=_fake_search, fetch_page=_fake_page,
                                     captions=_captions)
        for patcher in (
            mock.patch.object(main, "channel_research_service", self.service),
            mock.patch.object(main, "_research_collectors", side_effect=lambda: Collectors(
                self.database, self.youtube, web_search=_fake_search, fetch_page=_fake_page, captions=_captions)),
            mock.patch.object(main, "youtube", self.youtube),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _plan(self, project_id: int) -> dict:
        response = self.client.post(f"/api/projects/{project_id}/steps/plan", json={"options": {}})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["result"]

    def _report(self, project_id: int) -> dict:
        return self.client.get(f"/api/projects/{project_id}/plan").json()["research_report"]


class OneEngineTests(unittest.TestCase):
    def test_the_planner_does_not_research_channels_itself(self) -> None:
        code = inspect.getsource(project_planner)
        for call in ("get_channel_by_id", "list_upload_video_ids", "compute_profile", "save_full",
                     "update_incremental", "update_performance", "save_channel_profile"):
            self.assertNotIn(call, code, call)
        self.assertIn("channel_service.ensure(", code)

    def test_the_manager_refresh_and_the_plan_share_one_service(self) -> None:
        refresh = inspect.getsource(main.refresh_channel_research)
        plan = inspect.getsource(main._step_plan)
        self.assertIn("channel_research_service.refresh(", refresh)
        self.assertIn("channel_service=channel_research_service", plan)
        for module in (main, research_collectors):
            self.assertNotIn("ChannelIntelligence(", inspect.getsource(module).split('"""', 2)[2], module.__name__)


class ReadsNeverFetchTests(_PlanCase):
    def test_listing_and_opening_channels_touch_no_network(self) -> None:
        self.database.upsert_channel({"youtube_channel_id": self.channel_id, "channel_url": "https://x", "title": "Kênh"})
        self.service.ensure(self.service.resolve(self.channel_id))
        calls = len(self.youtube.calls)
        boom = mock.Mock(side_effect=AssertionError("network used by a GET"))
        with mock.patch.object(main, "probe_source_link", boom), \
                mock.patch.object(research_collectors.web_research, "search", boom), \
                mock.patch.object(research_collectors, "public_captions", boom), \
                mock.patch.object(research_collectors.Collectors, "comments", boom):
            self.assertEqual(self.client.get("/api/channels").status_code, 200)
            self.assertEqual(self.client.get(f"/api/channels/{self.channel_id}/research").status_code, 200)
        self.assertEqual(len(self.youtube.calls), calls, "no YouTube call from a GET")


class VersionTests(_PlanCase):
    def test_a_check_that_finds_nothing_new_moves_the_clock_not_the_version(self) -> None:
        first = self.service.ensure(self.service.resolve(self.channel_id))
        old = (NOW - timedelta(hours=7)).isoformat()
        from tests.test_channel_research import _set
        _set("UPDATE channel_profiles SET last_checked_at = ? WHERE native_channel_id = ?", old, self.channel_id)
        again = self.service.ensure(self.service.resolve(self.channel_id))
        profile = self.service.store.get("youtube", self.channel_id)
        self.assertEqual(again["profile_version"], first["profile_version"])
        self.assertGreater(profile["last_checked_at"], old)


class BudgetTests(_PlanCase):
    def test_comment_caps_hold_across_pages(self) -> None:
        project_id = _video_project(self.database, self.channel_id)
        self._plan(project_id)
        evidence = self._report(project_id)["report"]["evidence"]
        samples = [item for item in evidence if item["source_kind"] == "comment_sample"]
        self.assertEqual(len(samples), 4, "the source and 3 similar videos")
        self.assertEqual(samples[0]["sample_size"], 100, "source: at most 100")
        self.assertEqual([item["sample_size"] for item in samples[1:]], [50, 50, 50], "similar: at most 50 each")

    def test_similar_videos_default_to_eight_and_keep_five_to_ten(self) -> None:
        collectors = Collectors(self.database, self.youtube)
        found = collectors.similar_videos(query="trái đất", exclude_ids=set())
        self.assertEqual(len(found["videos"]), 8)
        few = Collectors(self.database, self.youtube, budget=Budget(similar_videos=3)).similar_videos(query="vũ trụ xa", exclude_ids=set())
        self.assertEqual(len(few["videos"]), 3)
        self.assertTrue(any("mục tiêu 5–10" in item for item in few["limitations"]))


class RankingTests(unittest.TestCase):
    def test_views_are_one_signal_not_the_ranking(self) -> None:
        rows = [
            {"video_id": "rel1", "title": "Trái Đất hình thành như thế nào", "published_at": (NOW - timedelta(days=20)).isoformat(),
             "view_count": 40_000, "comment_count": 50, "duration_seconds": 400},
            {"video_id": "rel2", "title": "Tuổi của Trái Đất", "published_at": (NOW - timedelta(days=40)).isoformat(),
             "view_count": 30_000, "comment_count": 20, "duration_seconds": 300},
            {"video_id": "huge", "title": "Nhạc remix hay nhất", "published_at": (NOW - timedelta(days=900)).isoformat(),
             "view_count": 90_000_000, "comment_count": 0, "duration_seconds": 0},
        ]
        ranked = rank_similar(rows, topic_terms={"trái", "đất", "hình", "thành"}, now=NOW)
        self.assertEqual([row["video_id"] for row in ranked][:2], ["rel1", "rel2"])
        self.assertEqual(ranked[-1]["video_id"], "huge")
        self.assertEqual(set(ranked[0]["score_parts"]), {"relevance", "freshness", "performance", "availability"})
        self.assertEqual(rank_similar(rows, topic_terms={"trái", "đất"}, now=NOW), rank_similar(rows, topic_terms={"trái", "đất"}, now=NOW))


class CountingTests(unittest.TestCase):
    def test_a_comment_repeating_a_word_counts_once(self) -> None:
        texts = ["pin pin pin pin", "pin tốt", "hết pin nhanh", "pin ổn", "giá rẻ", "giá rẻ", "giá rẻ", "đẹp", "ổn", "hay"]
        terms = next(item for item in comment_patterns([{"text": text} for text in texts]) if item["kind"] == "terms")
        pin = next(item for item in terms["items"] if item["term"] == "pin")
        self.assertEqual((pin["count"], pin["of"]), (4, 10), "4 comments mention pin; the word appears 7 times")
        self.assertEqual(terms["counting"], "comments_containing")


class WebEvidenceTests(unittest.TestCase):
    def test_a_snippet_is_not_an_article_and_counts_for_little(self) -> None:
        def search(query, **options):
            return [{"title": "Chính phủ", "url": "https://chinhphu.vn/a", "source": "chinhphu.vn", "snippet": "s"},
                    {"title": "Báo", "url": "https://bao.test/b", "source": "bao.test", "snippet": "s"},
                    {"title": "Không mở", "url": "https://khac.test/c", "source": "khac.test", "snippet": "chỉ là trích đoạn"}]

        def fetch(url):
            if "bao.test" in url:
                raise TimeoutError("hết giờ")
            return "<html><body><p>Nội dung chính thức đã đọc.</p></body></html>"

        collectors = Collectors(mock.Mock(list_recent_research_reports=lambda limit: []), mock.Mock(api_key=""),
                                web_search=search, fetch_page=fetch, budget=Budget(web_read_pages=2))
        result = collectors.web(["chủ đề"])
        kinds = {item["source_url"]: item["source_kind"] for item in result["evidence"]}
        self.assertEqual(kinds["https://chinhphu.vn/a"], "official")
        self.assertEqual(kinds["https://bao.test/b"], "search_result", "attempted but not read")
        self.assertEqual(kinds["https://khac.test/c"], "search_result", "never opened")
        self.assertTrue(any(item["source"] == "https://bao.test/b" for item in result["failed"]))
        for item in result["evidence"]:
            self.assertTrue(item["collector"] and item["collector_version"] and item["captured_at"])
        snippets = [item for item in result["evidence"] if item["source_kind"] == "search_result"]
        accepted, _ = research_evidence.validate_insights([{"text": "x", "evidence_ids": [item["id"] for item in snippets]}], result["evidence"])
        self.assertEqual(accepted[0]["confidence"], "low", "snippets alone never make a finding confident")


class ReportStatusTests(_PlanCase):
    def test_a_report_is_partial_when_some_collectors_fail(self) -> None:
        def no_comments(video_id, **options):
            return {"video_id": video_id, "comments": [], "disabled": True, "next_page_token": None}

        def web_down(query, **options):
            raise TimeoutError("web timeout")

        self.youtube.list_comment_threads = no_comments
        with mock.patch.object(main, "_research_collectors", side_effect=lambda: Collectors(
                self.database, self.youtube, web_search=web_down, fetch_page=_fake_page, captions=_captions)):
            project_id = _video_project(self.database, self.channel_id)
            result = self._plan(project_id)
        report = self._report(project_id)
        self.assertEqual(result["research_status"], "partial")
        self.assertEqual(report["status"], "partial")
        body = report["report"]
        collectors = {item["collector"] for item in body["failed_sources"]}
        self.assertIn("youtube.comments", collectors)
        self.assertTrue(any(name.startswith("web") for name in collectors), collectors)
        self.assertTrue(body["similar_content"], "the rest was still collected")
        for field in ("coverage", "limitations", "failed_sources", "knowledge_used", "evidence"):
            self.assertIn(field, body)

    def test_a_report_is_failed_only_when_nothing_could_be_collected(self) -> None:
        offline = FakeYouTube(self.channel_id, [])
        offline.api_key = ""
        with mock.patch.object(main, "_research_collectors", side_effect=lambda: Collectors(
                self.database, offline, web_search=lambda query, **options: [], captions=_captions)), \
                mock.patch.object(main, "channel_research_service", ChannelResearchService(self.database, offline)):
            project_id = _video_project(self.database, self.channel_id)
            result = self._plan(project_id)
        self.assertEqual(result["research_status"], "failed")
        self.assertEqual(self._report(project_id)["status"], "failed")
        self.assertIsNotNone(self.client.get(f"/api/projects/{project_id}/plan").json()["plan"], "the plan skeleton is still saved")

    def test_reusing_pages_keeps_the_pages_that_could_not_be_read(self) -> None:
        def blocked_page(url):
            if url.endswith("/1"):
                raise PermissionError("403 Forbidden")
            return _fake_page(url)

        topic = f"Trái Đất quay {uuid.uuid4().hex[:6]}"
        with mock.patch.object(main, "_research_collectors", side_effect=lambda: Collectors(
                self.database, self.youtube, web_search=_fake_search, fetch_page=blocked_page, captions=_captions)):
            first = self._plan(_video_project(self.database, self.channel_id, topic=topic))
            second = self._plan(_video_project(self.database, self.channel_id, topic=topic))
        self.assertEqual(first["research_status"], "partial")
        self.assertEqual(second["reuse"]["web_queries"], "1/1")
        self.assertEqual(second["research_status"], "partial", "the unread page is still unread")
        carried = [item for item in second["failed_sources"] if item.get("reused_from")]
        self.assertEqual([item["source"] for item in carried], ["https://tin.test/1"])

    def test_everything_collected_is_complete(self) -> None:
        result = self._plan(_video_project(self.database, self.channel_id))
        self.assertEqual(result["research_status"], "complete", result["failed_sources"])


class ReuseTests(_PlanCase):
    def test_a_second_plan_reuses_what_is_still_fresh(self) -> None:
        topic = f"Trái Đất quay {uuid.uuid4().hex[:6]}"
        first = self._plan(_video_project(self.database, self.channel_id, topic=topic))
        calls = len(self.youtube.calls)
        second_project = _video_project(self.database, self.channel_id, topic=topic)
        second = self._plan(second_project)
        new_calls = self.youtube.calls[calls:]
        self.assertEqual(first["source_channel"]["status"], "new")
        self.assertEqual(second["source_channel"]["status"], "reused")
        self.assertFalse([call for call in new_calls if call[0] in {"search", "channels"}], new_calls)
        self.assertTrue(second["reuse"]["similar_videos"])
        self.assertEqual(second["reuse"]["captions"], "3/3")
        self.assertEqual(second["reuse"]["web_queries"], "1/1")
        # The new source video's own comments are new; the similar ones are reused.
        self.assertEqual(second["reuse"]["comment_samples"], "3/4")
        report = self._report(second_project)["report"]
        self.assertEqual(len(report["similar_content"]), 8)


class RunIndependenceTests(_PlanCase):
    def _hold(self) -> threading.Event:
        self.youtube.hold = threading.Event()
        self.addCleanup(self.youtube.hold.set)
        return self.youtube.hold

    def test_the_manager_does_not_duplicate_a_refresh_the_plan_started(self) -> None:
        project_id = _video_project(self.database, self.channel_id)
        hold = self._hold()
        thread = threading.Thread(target=lambda: self.client.post(f"/api/projects/{project_id}/steps/plan", json={"options": {}}), daemon=True)
        thread.start()
        self.assertTrue(self.youtube.entered.wait(5))
        response = self.client.post(f"/api/channels/{self.channel_id}/research/refresh", json={})
        self.assertEqual(response.status_code, 409)
        summary = self.client.get(f"/api/channels/{self.channel_id}/research").json()["research"]["summary"]
        self.assertEqual(summary["state"], "running")
        hold.set()
        thread.join(10)
        self.youtube.hold = None

    def test_two_channels_research_independently(self) -> None:
        hold = self._hold()
        thread = threading.Thread(target=lambda: self.client.post(f"/api/channels/{self.channel_id}/research/refresh", json={}), daemon=True)
        thread.start()
        self.assertTrue(self.youtube.entered.wait(5))
        other_id, other = _channel()
        response = self.service.refresh.__func__(ChannelResearchService(self.database, other), other_id)
        self.assertEqual(response["status"], "new")
        hold.set()
        thread.join(10)

    def test_analysis_and_channel_research_do_not_share_a_lock(self) -> None:
        hold = self._hold()
        thread = threading.Thread(target=lambda: self.client.post(f"/api/channels/{self.channel_id}/research/refresh", json={}), daemon=True)
        thread.start()
        self.assertTrue(self.youtube.entered.wait(5))
        project_id = _video_project(self.database, self.channel_id)
        with mock.patch.dict(main._STEP_RUNNERS, {"analyze": lambda *args: {"status": "analyzed"}}):
            response = self.client.post(f"/api/projects/{project_id}/steps/analyze", json={"options": {}})
        self.assertEqual(response.status_code, 200, "a channel refresh does not block an analysis")
        self.assertTrue(channel_research.registry.is_running(("channel", f"youtube:{self.channel_id}")))
        hold.set()
        thread.join(10)


if __name__ == "__main__":
    unittest.main()
