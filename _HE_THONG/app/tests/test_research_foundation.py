"""The research foundation: knowledge that accumulates, and numbers kept honest.

Each video used to be researched - when it was researched at all - from
scratch, and the one research role that existed let a model invent trend and
opportunity scores. These tests hold the stores to their bookkeeping and the
evidence model to its rules: every number is computed, every insight cites
what it rests on, and nothing names a commenter.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from youtube_monitor import freshness, research_evidence
from youtube_monitor.database import Database
from youtube_monitor.knowledge_store import (
    AudienceObservations,
    ChannelIntelligence,
    ContentPatterns,
    TopicIntelligence,
    slug,
)

UC = "UCabcdefghijklmnopqrstuv"
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def ago(**span: float) -> str:
    return (NOW - timedelta(**span)).isoformat()


class _Store(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self._directory.name) / "knowledge.db")

    def tearDown(self) -> None:
        self._directory.cleanup()

    def _set(self, sql: str, *params) -> None:
        with closing(sqlite3.connect(self.database.path)) as connection, connection:
            connection.execute(sql, params)


class SchemaTests(_Store):
    def test_the_tables_and_their_bookkeeping_columns_exist(self) -> None:
        expected = {
            "channel_profiles": {"version", "status", "last_full_at", "last_incremental_at", "performance_at", "known_video_ids_json"},
            "topic_knowledge": {"version", "volatility", "refreshed_at", "facts_json"},
            "audience_observations": {"sample_size", "source_url", "method", "captured_at", "patterns_json"},
            "content_patterns": {"signature", "evidence_count", "examples_json", "first_seen_at", "last_seen_at"},
            "research_reports": {"version", "status", "analysis_created_at", "engine_version", "report_json", "captured_at"},
            "project_plans": {"version", "status", "research_report_id", "analysis_created_at", "plan_json", "feasibility_json"},
        }
        with closing(sqlite3.connect(self.database.path)) as connection:
            for table, columns in expected.items():
                found = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                self.assertTrue(columns <= found, f"{table}: thiếu {columns - found}")

    def test_no_column_is_there_to_hold_a_credential_or_a_commenter(self) -> None:
        with closing(sqlite3.connect(self.database.path)) as connection:
            for table in ("channel_profiles", "topic_knowledge", "audience_observations", "content_patterns",
                          "research_reports", "project_plans"):
                names = " ".join(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))
                for word in ("cookie", "password", "token", "author", "username", "profile_path"):
                    self.assertNotIn(word, names, f"{table}.{word}")


class ChannelIntelligenceTests(_Store):
    def test_a_first_meeting_is_a_full_profile_and_fresh(self) -> None:
        store = ChannelIntelligence(self.database)
        self.assertIsNone(store.get("youtube", UC))
        self.assertEqual(store.refresh_plan(None)["action"], "full")
        store.save_full("youtube", UC, channel_name="Kênh", profile={"topics": ["khoa học"]},
                        performance={"median_views": 1000}, video_ids=["a", "b"])
        profile = store.get("youtube", UC)
        self.assertEqual(profile["status"], "complete")
        self.assertEqual(profile["version"], 1)
        self.assertEqual(profile["freshness"]["profile"]["state"], freshness.FRESH)
        self.assertEqual(profile["known_video_ids"], ["a", "b"])

    def test_later_meetings_only_add_what_is_new(self) -> None:
        store = ChannelIntelligence(self.database)
        full = store.save_full("youtube", UC, profile={"style": "nhanh"}, video_ids=["a", "b"])
        self.assertEqual(store.refresh_plan(full, latest_upload_ids=["c", "a"])["action"], "none",
                         "one new upload is under the threshold")
        plan = store.refresh_plan(full, latest_upload_ids=["c", "d", "e", "f", "g", "a"])
        self.assertEqual(plan["action"], "incremental")
        self.assertEqual(plan["new_video_ids"], ["c", "d", "e", "f", "g"])
        updated = store.update_incremental("youtube", UC, new_video_ids=plan["new_video_ids"], profile_patch={"hooks": ["câu hỏi"]})
        self.assertEqual(updated["version"], 2)
        self.assertEqual(updated["last_full_at"], full["last_full_at"], "a partial update is not a full one")
        self.assertIsNotNone(updated["last_incremental_at"])
        self.assertEqual(updated["profile"], {"style": "nhanh", "hooks": ["câu hỏi"]})
        self.assertEqual(updated["known_video_ids"], ["a", "b", "c", "d", "e", "f", "g"])

    def test_an_old_profile_is_redone_in_full(self) -> None:
        store = ChannelIntelligence(self.database)
        store.save_full("youtube", UC, profile={}, video_ids=["a"])
        self._set("UPDATE channel_profiles SET last_full_at = ?", (datetime.now(timezone.utc) - timedelta(days=31)).isoformat())
        profile = store.get("youtube", UC)
        self.assertEqual(profile["freshness"]["profile"]["state"], freshness.STALE)
        self.assertEqual(store.refresh_plan(profile)["action"], "full")

    def test_an_incremental_update_needs_a_profile_first(self) -> None:
        with self.assertRaises(ValueError):
            ChannelIntelligence(self.database).update_incremental("youtube", UC, new_video_ids=["a"])

    def test_a_made_up_key_is_not_a_channel(self) -> None:
        store = ChannelIntelligence(self.database)
        for key in ("WEB-YOUTUBE-740f513895b0", "site-vnexpress.net", ""):
            with self.assertRaises(ValueError):
                store.save_full("youtube", key, profile={})
        with self.assertRaises(ValueError):
            store.save_full("web", "x", profile={})


class TopicIntelligenceTests(_Store):
    def test_facts_are_kept_with_their_sources_and_merged(self) -> None:
        store = TopicIntelligence(self.database)
        key = store.key("Trái Đất được tạo ra như thế nào?")
        self.assertEqual(key, "trai-dat-duoc-tao-ra-nhu-the-nao")
        store.upsert(key, title="Trái Đất", facts=[{"fact": "Trái Đất 4,5 tỉ năm tuổi", "source_urls": ["https://a"]}])
        row = store.upsert(key, title="Trái Đất", facts=[
            {"fact": "Trái Đất 4,5 tỉ năm tuổi", "source_urls": ["https://b"]},
            {"fact": "Mặt Trăng hình thành sau va chạm", "source_urls": ["https://c"]},
        ])
        self.assertEqual(row["version"], 2)
        self.assertEqual(len(row["facts"]), 2)
        self.assertEqual(store.get(key)["freshness"]["state"], freshness.FRESH)

    def test_a_fact_without_a_source_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            TopicIntelligence(self.database).upsert("x", title="x", facts=[{"fact": "không nguồn", "source_urls": []}])

    def test_news_goes_stale_in_hours_evergreen_in_months(self) -> None:
        store = TopicIntelligence(self.database)
        store.upsert("tin", title="tin", volatility="news", facts=[{"fact": "a", "source_urls": ["https://a"]}])
        store.upsert("kien-thuc", title="kt", volatility="evergreen", facts=[{"fact": "b", "source_urls": ["https://b"]}])
        self._set("UPDATE topic_knowledge SET refreshed_at = ?", (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat())
        self.assertEqual(store.get("tin")["freshness"]["state"], freshness.STALE)
        self.assertEqual(store.get("kien-thuc")["freshness"]["state"], freshness.FRESH)


class AudienceObservationTests(_Store):
    def test_samples_are_appended_with_their_size_and_no_one_is_named(self) -> None:
        store = AudienceObservations(self.database)
        first = store.append(
            "video", "youtube:abc", platform="youtube", source_url="https://youtube.com/watch?v=abc",
            method="commentThreads relevance top 100", sample_size=42,
            patterns=[{"pattern": "hỏi về pin", "count": 9, "author": "Ai Đó", "authorChannelId": "UCx",
                       "quote": "@nguoidung_test pin được bao lâu?"}],
        )
        self.assertNotIn("author", first["patterns"][0])
        self.assertNotIn("authorChannelId", first["patterns"][0])
        self.assertNotIn("nguoidung_test", first["patterns"][0]["quote"])
        store.append("video", "youtube:abc", platform="youtube", source_url="https://youtube.com/watch?v=abc",
                     method="commentThreads time", sample_size=18, patterns=[])
        summary = store.summary("video", "youtube:abc")
        self.assertEqual(summary["observations"], 2, "a new sample is a new row")
        self.assertEqual(summary["total_sample"], 60)
        self.assertEqual(summary["freshness"]["update_mode"], freshness.APPEND)

    def test_a_sample_must_have_been_counted(self) -> None:
        store = AudienceObservations(self.database)
        for size in (0, -3, None, "nhiều"):
            with self.assertRaises(ValueError):
                store.append("video", "k", platform="youtube", source_url="https://x", method="m",
                             sample_size=size, patterns=[])  # type: ignore[arg-type]


class ContentPatternTests(_Store):
    def test_the_same_example_counts_once(self) -> None:
        store = ContentPatterns(self.database)
        args = ("hook", "channel", f"youtube:{UC}")
        store.record(*args, description="Mở đầu bằng câu hỏi", example={"url": "https://a"})
        store.record(*args, description="Mở đầu bằng câu hỏi", example={"url": "https://a"})
        row = store.record(*args, description="Mở đầu bằng câu hỏi", example={"url": "https://b"})
        self.assertEqual(row["evidence_count"], 2)
        self.assertEqual(len(store.list("channel", f"youtube:{UC}", "hook")), 1)

    def test_a_pattern_needs_an_example_and_a_known_type(self) -> None:
        store = ContentPatterns(self.database)
        with self.assertRaises(ValueError):
            store.record("hook", "channel", "k", description="x", example={})
        with self.assertRaises(ValueError):
            store.record("vibe", "channel", "k", description="x", example={"url": "https://a"})


class FreshnessPolicyTests(unittest.TestCase):
    def test_each_kind_has_its_own_clock(self) -> None:
        cases = [
            (freshness.channel_profile(ago(days=29), now=NOW), freshness.FRESH),
            (freshness.channel_profile(ago(days=31), now=NOW), freshness.STALE),
            (freshness.channel_profile(ago(days=2), new_uploads=5, now=NOW), freshness.STALE),
            (freshness.channel_profile(ago(days=2), new_uploads=4, now=NOW), freshness.FRESH),
            (freshness.channel_performance(ago(hours=30), active=True, now=NOW), freshness.STALE),
            (freshness.channel_performance(ago(hours=30), now=NOW), freshness.FRESH),
            (freshness.channel_performance(ago(hours=60), active=False, now=NOW), freshness.FRESH),
            (freshness.channel_performance(ago(hours=73), active=False, now=NOW), freshness.STALE),
            (freshness.topic(ago(hours=7), volatility="news", now=NOW), freshness.STALE),
            (freshness.topic(ago(hours=20), volatility="hot", now=NOW), freshness.FRESH),
            (freshness.topic(ago(days=40), volatility="tech", now=NOW), freshness.STALE),
            (freshness.topic(ago(days=90), volatility="evergreen", now=NOW), freshness.FRESH),
            (freshness.comments(ago(hours=30), video_published_at=ago(days=2), now=NOW), freshness.STALE),
            (freshness.comments(ago(days=10), video_published_at=ago(days=200), now=NOW), freshness.FRESH),
            (freshness.similar_videos(ago(days=8), volatility="hot", now=NOW), freshness.STALE),
            (freshness.similar_videos(ago(days=8), volatility="evergreen", now=NOW), freshness.FRESH),
            (freshness.product_price(ago(hours=25), now=NOW), freshness.STALE),
            (freshness.product_price(None, now=NOW), freshness.MISSING),
        ]
        for index, (result, expected) in enumerate(cases):
            self.assertEqual(result["state"], expected, f"case {index}: {result}")

    def test_the_policies_are_not_one_ttl(self) -> None:
        self.assertGreater(len({policy.max_age for policy in freshness.POLICIES.values()}), 5)

    def test_an_unknown_kind_is_an_error_not_a_guess(self) -> None:
        with self.assertRaises(ValueError):
            freshness.assess("vibes", ago(hours=1))


def _comments(url: str, size: int) -> dict:
    return research_evidence.make_evidence(
        "comment_sample", source_url=url, collector="test.comments", collector_version="t1",
        native_source_id=url.rsplit("=", 1)[-1], sample_size=size, sampling={"order": "relevance"},
        captured_at="2026-09-29T10:00:00+00:00",
    )


class EvidenceTests(unittest.TestCase):
    def test_evidence_carries_the_fields_of_the_model(self) -> None:
        item = _comments("https://youtube.com/watch?v=A", 42)
        for field in (
            "id", "source_kind", "source_url", "native_source_id", "platform", "excerpt", "metrics",
            "sample_size", "sampling", "captured_at", "collector", "collector_version",
        ):
            self.assertIn(field, item, field)
        self.assertEqual(item["source_kind"], "comment_sample")
        self.assertEqual(item["native_source_id"], "A")
        self.assertEqual((item["collector"], item["collector_version"]), ("test.comments", "t1"))

    def test_evidence_is_checked_and_stripped_of_people(self) -> None:
        item = research_evidence.make_evidence(
            "comment_sample", source_url="https://youtube.com/watch?v=a", collector="test", sample_size=42,
            excerpt="@nguoidung_test " + "pin " * 200,
            metrics={"likes": 3, "author": "Ai Đó"}, sampling={"order": "relevance", "username": "x"},
        )
        self.assertNotIn("nguoidung_test", item["excerpt"])
        self.assertLessEqual(len(item["excerpt"]), research_evidence.EXCERPT_LIMIT)
        self.assertNotIn("author", item["metrics"])
        self.assertNotIn("username", item["sampling"])
        for bad in (
            dict(source_kind="rumour", source_url="https://x", collector="test"),
            dict(source_kind="article", source_url="", collector="test"),
            dict(source_kind="comment_sample", source_url="https://x", collector="test"),
            dict(source_kind="article", source_url="https://x", collector=""),
        ):
            with self.assertRaises(ValueError):
                research_evidence.make_evidence(bad.pop("source_kind"), **bad)


class InsightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.a = _comments("https://youtube.com/watch?v=A", 42)
        self.b = _comments("https://youtube.com/watch?v=B", 18)
        self.review = research_evidence.make_evidence("review", source_url="https://review.test/1", collector="test")
        self.official = research_evidence.make_evidence("official", source_url="https://hang.test/spec", collector="test")
        self.evidence = [self.a, self.b, self.review, self.official]

    def _one(self, insight: dict) -> tuple[list, list]:
        return research_evidence.validate_insights([insight], self.evidence)

    def test_an_insight_without_evidence_is_refused(self) -> None:
        accepted, rejected = self._one({"text": "Người xem quan tâm pin"})
        self.assertEqual(accepted, [])
        self.assertEqual(rejected[0]["reason"], "Không có bằng chứng")
        accepted, rejected = self._one({"text": "Người xem quan tâm pin", "evidence_ids": ["ev-khongco"]})
        self.assertEqual(accepted, [])
        self.assertIn("không tồn tại", rejected[0]["reason"])

    def test_the_numbers_are_computed_and_the_models_are_ignored(self) -> None:
        accepted, _ = self._one({
            "text": "Nhiều comment hỏi về thời lượng pin",
            "evidence_ids": [self.a["id"], self.b["id"], self.review["id"]],
            "sample_size": 5000, "confidence": "high", "source_count": 99,
        })
        insight = accepted[0]
        self.assertEqual(insight["sample_size"], 60)
        self.assertEqual(insight["source_count"], 3)
        self.assertEqual(insight["confidence"], "medium", "60 comments: under the 100 needed for high")
        self.assertIn("60 comment mẫu", insight["scope_note"])
        self.assertIn("không đại diện cho toàn bộ người xem", insight["scope_note"])
        self.assertEqual(insight["captured_at"], max(item["captured_at"] for item in self.evidence[:3]))

    def test_confidence_follows_the_rule(self) -> None:
        big = _comments("https://youtube.com/watch?v=C", 80)
        evidence = [*self.evidence, big]
        cases = [
            ([self.b["id"]], "low"),                                   # 18 comments, 1 source
            ([self.a["id"]], "medium"),                                # 42 comments
            ([self.a["id"], big["id"]], "high"),                       # 122 comments, 2 sources
            ([self.review["id"]], "low"),                              # one page
            ([self.official["id"]], "medium"),                         # an official source
            ([self.official["id"], self.review["id"]], "high"),        # official + another
        ]
        for ids, expected in cases:
            accepted, _ = research_evidence.validate_insights([{"text": "x", "evidence_ids": ids}], evidence)
            self.assertEqual(accepted[0]["confidence"], expected, ids)

    def test_the_insight_is_called_text_and_the_old_key_is_still_read(self) -> None:
        accepted, _ = self._one({"text": "Hỏi về pin", "evidence_ids": [self.a["id"]]})
        self.assertEqual(accepted[0]["text"], "Hỏi về pin")
        self.assertEqual(
            set(accepted[0]) >= {"id", "text", "evidence_ids", "sample_size", "source_count", "confidence", "scope_note"},
            True,
        )
        accepted, _ = self._one({"insight": "Hỏi về pin", "evidence_ids": [self.a["id"]]})
        self.assertEqual(accepted[0]["text"], "Hỏi về pin")

    def test_a_share_of_a_sample_is_not_a_share_of_the_audience(self) -> None:
        _, rejected = self._one({"text": "25% người xem quan tâm pin", "evidence_ids": [self.a["id"]]})
        self.assertIn("toàn bộ người xem", rejected[0]["reason"])
        accepted, _ = self._one({"text": "25% comment mẫu hỏi về pin", "evidence_ids": [self.a["id"]]})
        self.assertEqual(len(accepted), 1)

    def test_a_report_validates_every_group_and_counts_coverage(self) -> None:
        report = research_evidence.build_report(
            brief={"topic": "tai nghe"},
            evidence=self.evidence,
            raw_insights={
                "audience_insights": [
                    {"text": "Hỏi về pin", "evidence_ids": [self.a["id"]]},
                    {"text": "Không có nguồn"},
                ],
                "content_gaps": [{"text": "Chưa ai so sánh với bản cũ", "evidence_ids": [self.review["id"]]}],
            },
            latest_facts=[{"fact": "Giá 119.000₫", "evidence_ids": [self.official["id"]]}, {"fact": "đồn đại"}],
        )
        self.assertEqual(len(report["audience_insights"]), 1)
        self.assertEqual(len(report["content_gaps"]), 1)
        self.assertEqual(len(report["latest_facts"]), 1)
        self.assertEqual({item["group"] for item in report["rejected_insights"]}, {"audience_insights", "latest_facts"})
        self.assertEqual(report["coverage"]["comments_sampled"], 60)
        self.assertEqual(report["coverage"]["evidence"], 4)


class ReportAndPlanPersistenceTests(_Store):
    """Saved, numbered, and read back the same after the app restarts."""

    def _project(self) -> int:
        project = self.database.create_idea_project("Kiểm tra lưu kế hoạch")
        return int(project["id"])

    def test_versions_are_kept_and_reload_from_a_fresh_connection(self) -> None:
        from youtube_monitor import project_planner

        project_id = self._project()
        evidence = [_comments("https://youtube.com/watch?v=A", 42)]
        reports, plans = [], []
        for version in (1, 2):
            body = research_evidence.build_report(
                brief={"topic": f"lần {version}"}, evidence=evidence,
                raw_insights={"audience_insights": [{"text": "Hỏi về pin", "evidence_ids": [evidence[0]["id"]]}]},
            )
            report = self.database.create_research_report(
                project_id, status="partial", source_kind="video", analysis_created_at="A1",
                engine_version="t", report=body, captured_at=body["captured_at"],
            )
            plan = self.database.create_project_plan(
                project_id, status="draft", research_report_id=report["id"], analysis_created_at="A1",
                engine_version="t", plan={"platform": "youtube", "pending_fields": ["primary_angle"]},
                feasibility={"status": "not_checked"},
            )
            reports.append(report)
            plans.append(plan)
        self.assertEqual([item["version"] for item in reports], [1, 2])
        self.assertEqual([item["version"] for item in plans], [1, 2])

        reopened = Database(self.database.path)  # a new process would see this
        latest_plan = reopened.get_latest_project_plan(project_id)
        latest_report = reopened.get_latest_research_report(project_id)
        self.assertEqual((latest_plan["version"], latest_report["version"]), (2, 2))
        self.assertEqual(latest_plan["research_report_id"], latest_report["id"])
        self.assertEqual(latest_plan["plan"], {"platform": "youtube", "pending_fields": ["primary_angle"]})
        self.assertEqual(latest_plan["feasibility"], {"status": "not_checked"})
        self.assertEqual(latest_report["report"]["brief"], {"topic": "lần 2"})
        self.assertEqual(latest_report["report"]["audience_insights"][0]["sample_size"], 42)
        self.assertEqual((latest_report["evidence_count"], latest_report["insight_count"]), (1, 1))
        self.assertEqual(reopened.get_project_plan(plans[0]["id"])["version"], 1, "older versions stay readable")

        self.assertFalse(project_planner.current_plan(reopened, project_id, "A1")["stale"])
        self.assertTrue(project_planner.current_plan(reopened, project_id, "A2")["stale"],
                        "a plan built on an older analysis is stale")


class SlugTests(unittest.TestCase):
    def test_vietnamese_topics_get_stable_keys(self) -> None:
        self.assertEqual(slug("Đường Sắt Cao Tốc"), "duong-sat-cao-toc")
        self.assertEqual(slug("  "), "")


if __name__ == "__main__":
    unittest.main()
