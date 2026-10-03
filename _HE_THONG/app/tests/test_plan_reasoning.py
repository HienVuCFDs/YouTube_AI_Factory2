"""Bước 2 · Kế hoạch, Phase 3: insights, angles, the plan, and whether it can be made.

    AnalysisResult → ResearchReport → InsightReport → ProjectPlan → Feasibility

A model writes sentences; what it may not decide is decided by rule, and each
rule is held here: evidence that does not exist, numbers it made up, a cause
read off a correlation, a price with no reading, a plan longer than its
target, media that is not there. Then the step as a whole: what goes stale,
what a change of settings costs, what happens when a runtime fails or answers
with something unusable. And the hardening that came after the first real
runs: a blocked page is not evidence, what is off the subject supports
nothing, an asset the project has is never "missing", only a `completed` plan
finishes the step, and an angle can be chosen without researching again.
No test here reaches the network or a real model.
"""

from __future__ import annotations

import json
import re
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from functools import partial
from unittest import mock

from fastapi import HTTPException

from tests.test_channel_research import _fake_page, _fake_search
from tests.test_research_engine import _PlanCase, _captions
from youtube_monitor import insight_engine, main, plan_engine, project_planner, research_collectors, research_evidence
from youtube_monitor.knowledge_store import TopicIntelligence
from youtube_monitor.llm_client import LlmError
from youtube_monitor.research_collectors import Budget, Collectors

NOW = datetime.now(timezone.utc)
READ_AT = (NOW - timedelta(hours=1)).isoformat()
STAGE_LABELS = ["Đọc phân tích", "Nghiên cứu dữ liệu", "Phân tích insight", "Tìm góc nội dung",
                "Xây dựng chiến lược", "Kiểm tra tính khả thi", "Hoàn thiện kế hoạch"]
# What the user's spec asks of a ProjectPlan, at the least.
PLAN_KEYS = (
    "source_kind", "video_type", "platform", "aspect_ratio", "output_profile", "language", "target_duration_seconds",
    "target_audience", "goal", "primary_angle", "alternative_angles", "hook_strategy", "content_structure",
    "media_strategy", "edit_direction", "subtitle_strategy", "music_strategy", "sfx_strategy", "cta",
    "factual_guardrails", "claims_to_avoid", "missing_assets", "limitations", "analysis_ref", "research_report_id",
    "insight_report_id", "ai_proposed_assets", "primary_angle_id", "primary_angle_from",
)


# ---------------------------------------------------------------------------
# What a model would answer, written by hand
# ---------------------------------------------------------------------------

def _raw(key: str, kind: str, statement: str, evidence_ids: list[str], **more) -> dict:
    return {"key": key, "type": kind, "statement": statement, "evidence_ids": list(evidence_ids), "hypothesis": False,
            "fact_status": "", "implications": ["Đưa ý này vào phần mở đầu"], **more}


def _angle(key: str, statement: str, keys: list[str]) -> dict:
    return {"key": key, "statement": statement, "target_audience": "Người mới tìm hiểu chủ đề",
            "need_or_problem": "Muốn một câu trả lời ngắn", "supporting_insight_keys": list(keys),
            "differentiation": "Trả lời đúng câu người xem hỏi", "platform_fit": "Hợp video ngắn", "risks": []}


def _evidence() -> dict[str, dict]:
    make = partial(research_evidence.make_evidence, collector="test")
    return {
        "c1": make("comment_sample", source_url="https://youtube.test/watch?v=1", sample_size=40, title="Video 1"),
        "c2": make("comment_sample", source_url="https://youtube.test/watch?v=2", sample_size=50, title="Video 2"),
        "v1": make("video_meta", source_url="https://youtube.test/watch?v=1", title="Vì sao Trái Đất quay?"),
        "v2": make("video_meta", source_url="https://youtube.test/watch?v=2", title="Trái Đất có tuổi bao nhiêu?"),
        "a1": make("article", source_url="https://bao-a.test/tin", title="Bài A"),
        "a2": make("article", source_url="https://bao-b.test/tin", title="Bài B"),
        "official": make("official", source_url="https://chinhphu.vn/thong-bao", title="Thông báo"),
        "snip": make("search_result", source_url="https://khac.test/x", title="Chưa mở"),
        "page": make("product_page", source_url="https://shop.test/p/1", title="Tai nghe X1",
                     metrics={"price": "119000"}, captured_at="2026-10-01T08:00:00+00:00"),
        "page_no_price": make("product_page", source_url="https://shop.test/p/2", title="Tai nghe X2"),
        "channel": make("channel_stats", source_url="https://youtube.test/channel/UC1", title="Kênh"),
    }


def _validate(insights: list[dict], angles: list[dict] | None = None, *, kind: str = "video") -> dict:
    evidence = _evidence()
    for raw in insights:
        raw["evidence_ids"] = [evidence[name]["id"] if name in evidence else name for name in raw["evidence_ids"]]
    return insight_engine.validate(
        {"insights": insights, "angle_candidates": angles or [], "limitations": []}, list(evidence.values()), kind=kind)


class EvidenceValidatorTests(unittest.TestCase):
    def test_an_insight_citing_evidence_that_does_not_exist_is_refused(self) -> None:
        result = _validate([
            _raw("k1", "content_gap", "Chưa video nào giải thích lõi Trái Đất.", ["ev-0000000000"]),
            # One real id does not carry an invented one.
            _raw("k2", "audience_question", "Người xem trong mẫu hỏi về tuổi Trái Đất.", ["c1", "ev-khong-co"]),
        ], [_angle("a1", "Giải thích lõi Trái Đất", ["k1"])])
        self.assertEqual(result["insights"], [])
        self.assertEqual([item["reason"] for item in result["rejected"]], ["Viện dẫn bằng chứng không tồn tại"] * 2)
        self.assertEqual(result["rejected"][0]["unknown_evidence_ids"], ["ev-0000000000"])
        self.assertEqual(result["angle_candidates"], [], "an angle resting on a refused insight goes with it")
        self.assertEqual(len(result["rejected_angles"]), 1)

    def test_an_insight_without_evidence_is_refused_unless_it_says_it_is_a_guess(self) -> None:
        result = _validate([
            _raw("bare", "audience_need", "Người xem cần phần 2.", []),
            _raw("guess", "opportunity", "Có thể làm thành loạt bài dài.", [], hypothesis=True),
            _raw("real", "audience_question", "Người xem trong mẫu hỏi về tuổi Trái Đất.", ["c1"]),
        ], [_angle("a1", "Loạt bài dài", ["guess"]), _angle("a2", "Trả lời câu hỏi về tuổi", ["real"])])
        self.assertEqual([item["statement"] for item in result["insights"]], ["Người xem trong mẫu hỏi về tuổi Trái Đất."])
        self.assertEqual(result["rejected"][0]["reason"], "Không có bằng chứng và không được đánh dấu là giả thuyết")
        guess = result["hypotheses"][0]
        self.assertEqual((guess["basis"], guess["confidence"], guess["evidence_ids"], guess["sample_size"]),
                         ("hypothesis", "none", [], None))
        self.assertIn("Không được dùng như một dữ kiện", guess["scope_note"])
        # A guess is never something a plan can be built on.
        self.assertEqual([item["statement"] for item in result["angle_candidates"]], ["Trả lời câu hỏi về tuổi"])
        self.assertIn("không dựa trên insight nào có bằng chứng", result["rejected_angles"][0]["reason"])

    def test_sample_size_source_count_and_confidence_are_worked_out_not_believed(self) -> None:
        result = _validate([
            _raw("k1", "audience_question", "Người xem trong mẫu hỏi về tuổi Trái Đất.", ["c1", "c2"],
                 sample_size=99999, source_count=77, confidence="high", scope_note="Đại diện cho toàn bộ người xem"),
            _raw("k2", "fact", "Trái Đất hình thành cách đây khoảng 4,5 tỉ năm.", ["a1"],
                 sample_size=5000, source_count=12, confidence="high", fact_status="confirmed"),
        ])
        sample, fact = result["insights"]
        self.assertEqual((sample["sample_size"], sample["source_count"], sample["confidence"]), (90, 2, "medium"))
        self.assertIn("90 comment mẫu", sample["scope_note"])
        self.assertNotIn("toàn bộ người xem", sample["scope_note"].split(";")[0])
        self.assertEqual((fact["sample_size"], fact["source_count"], fact["confidence"]), (None, 1, "low"))

    def test_a_share_of_the_whole_audience_is_refused(self) -> None:
        result = _validate([_raw("k1", "audience_need", "70% người xem muốn video ngắn hơn.", ["c1"])])
        self.assertEqual(result["insights"], [])
        self.assertIn("tỉ lệ", result["rejected"][0]["reason"])

    def test_a_cause_read_off_a_correlation_is_refused(self) -> None:
        causal = [
            "Video này viral vì tiêu đề là một câu hỏi.",
            "Nhờ mở đầu bằng câu hỏi nên video đạt triệu view.",
            "Lý do video có nhiều view là thumbnail màu đỏ.",
            "Thumbnail màu đỏ giúp video đạt 2 triệu lượt xem.",
        ]
        observed = "Trong nhóm video hiệu suất cao được lấy mẫu, tiêu đề dạng câu hỏi xuất hiện thường xuyên hơn."
        result = _validate(
            [_raw(f"c{index}", "performance_pattern", text, ["v1", "v2"]) for index, text in enumerate(causal)]
            + [_raw("ok", "performance_pattern", observed, ["v1", "v2"])],
            [_angle("a1", "Video này sẽ viral vì dùng tiêu đề câu hỏi", ["ok"]), _angle("a2", "Đặt tiêu đề dạng câu hỏi", ["ok"])],
        )
        self.assertEqual([item["statement"] for item in result["insights"]], [observed])
        self.assertEqual(len(result["rejected"]), len(causal))
        for item in result["rejected"]:
            self.assertIn("nguyên nhân", item["reason"])
        kept = result["insights"][0]
        self.assertEqual(kept["type"], "performance_pattern")
        self.assertIn("không phải nguyên nhân", kept["scope_note"])
        self.assertEqual([item["statement"] for item in result["angle_candidates"]], ["Đặt tiêu đề dạng câu hỏi"])

    def test_one_video_is_not_a_pattern(self) -> None:
        result = _validate([
            _raw("one", "competitor_pattern", "Video tương tự mở đầu bằng câu hỏi.", ["v1"]),
            _raw("two", "competitor_pattern", "Các video tương tự đặt tiêu đề dạng câu hỏi.", ["v1", "v2"]),
            _raw("chan", "channel_pattern", "Kênh nguồn đăng đều mỗi tuần.", ["channel"]),
        ])
        self.assertEqual([item["statement"] for item in result["insights"]],
                         ["Các video tương tự đặt tiêu đề dạng câu hỏi.", "Kênh nguồn đăng đều mỗi tuần."])
        self.assertIn("Một video đơn lẻ không phải là pattern", result["rejected"][0]["reason"])

    def test_a_claim_has_the_status_its_sources_earn(self) -> None:
        result = _validate([
            _raw("one", "fact", "Sự cố xảy ra lúc 9 giờ sáng.", ["a1"], fact_status="confirmed"),
            _raw("two", "fact", "Có 12 khu vực bị ảnh hưởng.", ["a1", "a2"], fact_status="confirmed"),
            _raw("own", "fact", "Điện được cấp lại trong ngày.", ["official"]),
            _raw("split", "fact", "Nguyên nhân là quá tải.", ["a1", "a2"], fact_status="disputed"),
            _raw("typed", "disputed_fact", "Số người bị ảnh hưởng: hai báo nêu hai con số.", ["a1", "a2"]),
            _raw("open", "uncertainty", "Chưa rõ mức bồi thường.", ["a1"], fact_status="confirmed"),
            _raw("hint", "fact", "Sẽ có đợt cắt điện tiếp theo.", ["snip"], fact_status="confirmed"),
        ], kind="article")
        statuses = {item["statement"]: item["fact_status"] for item in result["insights"]}
        self.assertEqual(list(statuses.values()),
                         ["reported", "confirmed", "confirmed", "disputed", "disputed", "unknown", "unknown"])
        hint = result["insights"][-1]
        self.assertEqual(hint["confidence"], "low")
        self.assertIn("chưa mở trang", hint["scope_note"])

    def test_a_price_keeps_the_moment_it_was_read(self) -> None:
        result = _validate([
            _raw("read", "selling_point", "Giá 119.000₫ trên trang bán.", ["page"]),
            _raw("heard", "selling_point", "Giá chỉ 99k, rẻ hơn các mẫu khác.", ["a1"]),
            _raw("blank", "selling_point", "Giá 150.000đ đang được giảm.", ["page_no_price"]),
        ], kind="product")
        read, heard, blank = result["insights"]
        self.assertEqual(read["price_captured_at"], "2026-10-01T08:00:00+00:00")
        self.assertEqual(read["proof"], "supported")
        self.assertNotIn("price_captured_at", heard)
        self.assertEqual(heard["proof"], "needs_proof")
        self.assertEqual(blank["proof"], "needs_proof", "a listing whose price was not read does not vouch for one")

    def test_a_selling_point_nobody_showed_is_refused_or_needs_proof(self) -> None:
        result = _validate([
            _raw("none", "selling_point", "Pin dùng liên tục 40 giờ.", []),
            _raw("weak", "selling_point", "Chống nước chuẩn IPX7.", ["snip"]),
            _raw("page", "selling_point", "Có hộp sạc đi kèm.", ["page"]),
        ], kind="product")
        self.assertEqual([item["statement"] for item in result["rejected"]], ["Pin dùng liên tục 40 giờ."])
        weak, page = result["insights"]
        self.assertEqual((weak["proof"], weak["confidence"]), ("needs_proof", "low"))
        self.assertEqual(page["proof"], "supported")

    def test_what_a_buyer_said_is_kept_without_who_said_it(self) -> None:
        result = _validate([
            _raw("k1", "positive_signal", "Đánh giá của T**n mô tả bàn chải nhỏ gọn; @nguoidung_test cũng khen.", ["page"],
                 implications=["Dẫn lời n*****8 ở phần mở đầu"]),
        ], [_angle("a1", "Điều K**h nói về sản phẩm", ["k1"])], kind="product")
        kept, angle = result["insights"][0], result["angle_candidates"][0]
        self.assertEqual(kept["statement"], "Đánh giá của một người mua mô tả bàn chải nhỏ gọn; @… cũng khen.")
        self.assertEqual(kept["implications"], ["Dẫn lời một người mua ở phần mở đầu"])
        self.assertEqual(angle["statement"], "Điều một người mua nói về sản phẩm")
        # A colour marked "Đen (*)" or a rating is not a name.
        self.assertEqual(research_evidence.impersonal("Màu Đen (*) · 4.5* · 2 ** 3"), "Màu Đen (*) · 4.5* · 2 ** 3")

    def test_an_answer_with_nothing_usable_asks_for_the_repair(self) -> None:
        evidence = list(_evidence().values())
        for parsed in ("không phải json", {"insights": [], "angle_candidates": []},
                       {"insights": [_raw("k", "khong_co_loai_nay", "x", [])], "angle_candidates": [_angle("a", "x", ["k"])]}):
            errors, _ = insight_engine.validation_errors(parsed, evidence, kind="video")
            self.assertTrue(errors, parsed)
        all_fake = {"insights": [_raw("k", "fact", "Một điều.", ["ev-0000000000"])], "angle_candidates": [_angle("a", "x", ["k"])]}
        errors, _ = insight_engine.validation_errors(all_fake, evidence, kind="video")
        self.assertIn("Không insight nào có bằng chứng hợp lệ", errors[0])


class GuardrailTests(unittest.TestCase):
    """What the evidence obliges the video to respect, written by rule."""

    def _assets(self, **over) -> dict:
        return {"price_known": None, "price_captured_at": None, **over}

    def test_a_disputed_or_single_source_claim_becomes_a_factual_guardrail(self) -> None:
        insight = _validate([
            _raw("split", "disputed_fact", "Nguyên nhân sự cố: các báo nêu khác nhau.", ["a1", "a2"]),
            _raw("one", "fact", "Có 12 khu vực bị ảnh hưởng.", ["a1"]),
            _raw("open", "uncertainty", "Chưa rõ mức bồi thường.", ["a1"]),
            _raw("sure", "fact", "Điện được cấp lại trong ngày.", ["official"]),
            _raw("guess", "opportunity", "Có thể sẽ có đợt cắt điện nữa.", [], hypothesis=True),
        ], kind="article")
        rules = plan_engine.guardrails(insight, self._assets(), kind="article")
        factual = rules["factual_guardrails"]
        self.assertTrue(any(item.startswith("Các nguồn nói khác nhau") and "Nguyên nhân sự cố" in item for item in factual))
        self.assertTrue(any(item.startswith("Mới có một nguồn đưa") and "12 khu vực" in item for item in factual))
        self.assertTrue(any(item.startswith("Chưa được xác nhận") and "bồi thường" in item for item in factual))
        self.assertFalse(any("cấp lại trong ngày" in item for item in factual), "a confirmed fact needs no warning")
        self.assertTrue(any("Có thể sẽ có đợt cắt điện nữa" in item for item in rules["claims_to_avoid"]))

    def test_a_product_claim_without_evidence_is_a_claim_to_avoid_or_to_prove(self) -> None:
        insight = _validate([
            _raw("none", "selling_point", "Pin dùng liên tục 40 giờ.", []),
            _raw("weak", "selling_point", "Chống nước chuẩn IPX7.", ["snip"]),
            _raw("read", "selling_point", "Giá 119.000₫ trên trang bán.", ["page"]),
        ], kind="product")
        rules = plan_engine.guardrails(insight, self._assets(price_known=True, price_captured_at=READ_AT), kind="product")
        self.assertTrue(any("Pin dùng liên tục 40 giờ" in item for item in rules["claims_to_avoid"]))
        self.assertEqual(rules["claims_needing_proof"], ["Chống nước chuẩn IPX7."])
        self.assertTrue(any(item.startswith("Giá chỉ đúng tại thời điểm đọc (2026-10-01T08:00)") for item in rules["factual_guardrails"]))
        self.assertTrue(any(item.endswith("nêu kèm thời điểm đọc.") for item in rules["factual_guardrails"]))

    def test_a_missing_or_old_price_is_said_not_guessed(self) -> None:
        missing = plan_engine.guardrails({}, self._assets(price_known=False), kind="product")
        self.assertTrue(any("Không nêu bất kỳ con số giá nào" in item for item in missing["claims_to_avoid"]))
        old = (NOW - timedelta(days=2)).isoformat()
        stale = plan_engine.guardrails({}, self._assets(price_known=True, price_captured_at=old), kind="product")
        self.assertTrue(any("đã quá 24 giờ" in item for item in stale["factual_guardrails"]))


def _settings(profile: str = "youtube_landscape", target: int | None = 60, workflow: str = "content") -> dict:
    return plan_engine.settings_for({"workflow": workflow}, {"output_profile": profile}, language="vi",
                                    requested={"target_duration_seconds": target} if target else None)


def _assets(**over) -> dict:
    return {"source_kind": "video", "source_footage_seconds": 0, "source_has_picture": True, "source_media_local": False,
            "source_images": 0, "has_transcript": True, "has_dialogue": True, "project_assets": {},
            "price_known": None, "price_captured_at": None, **over}


def _plan(seconds: tuple[int, ...], target: int, *, primary=("ai_media",), supporting=(), kind: str = "video",
          missing=(), cited: bool = True) -> dict:
    return {
        "source_kind": kind, "target_duration_seconds": target,
        "content_structure": [
            {"name": f"Phần {index + 1}", "estimated_seconds": value, "key_points": ["Một ý"],
             "insight_ids": ["in-1"] if cited else [], "evidence_ids": []}
            for index, value in enumerate(seconds)
        ],
        "media_strategy": {"primary_sources": list(primary), "supporting_sources": list(supporting)},
        "missing_assets": list(missing),
    }


def _check(result: dict, key: str) -> dict:
    return next(item for item in result["checks"] if item["key"] == key)


class FeasibilityTests(unittest.TestCase):
    """Checked by rule after the model. A gap is reported with options, never quietly closed."""

    def _seconds(self, plan: dict) -> list[int]:
        return [item["estimated_seconds"] for item in plan["content_structure"]]

    def test_a_budget_on_target_is_ok(self) -> None:
        plan = _plan((10, 40, 12), 60)
        result = plan_engine.feasibility(plan, settings=_settings(), assets=_assets())
        self.assertEqual((result["status"], result["adjustments"]), ("ok", []))
        self.assertEqual(self._seconds(plan), [10, 40, 12])

    def test_a_small_drift_is_rescaled_and_recorded(self) -> None:
        plan = _plan((10, 45, 15), 60)
        result = plan_engine.feasibility(plan, settings=_settings(), assets=_assets())
        self.assertEqual(result["status"], "adjusted")
        self.assertEqual(sum(self._seconds(plan)), 60)
        self.assertEqual((result["adjustments"][0]["from_total"], result["adjustments"][0]["to_total"]), (70, 60))
        self.assertEqual(plan["target_duration_seconds"], 60)

    def test_a_sixty_second_video_planned_at_nearly_two_minutes_is_a_decision_for_a_person(self) -> None:
        plan = _plan((20, 60, 30), 60)
        result = plan_engine.feasibility(plan, settings=_settings("youtube_shorts"), assets=_assets())
        budget = _check(result, "duration_budget")
        self.assertEqual((result["status"], budget["status"]), ("needs_attention", "needs_attention"))
        self.assertEqual(len(budget["options"]), 2)
        self.assertEqual(self._seconds(plan), [20, 60, 30], "the structure is not cut to fit")
        self.assertEqual(plan["target_duration_seconds"], 60, "nor is the target moved")
        self.assertEqual(result["adjustments"], [])

    def test_eight_minutes_planned_on_three_minutes_of_footage_needs_attention(self) -> None:
        plan = _plan((60, 360, 60), 480, primary=("source_footage",))
        result = plan_engine.feasibility(plan, settings=_settings(target=480), assets=_assets(source_footage_seconds=180))
        media = _check(result, "available_media")
        self.assertEqual((result["status"], media["status"]), ("needs_attention", "needs_attention"))
        self.assertIn("chỉ đủ khoảng 180 giây", media["detail"])
        self.assertEqual(len(media["options"]), 3)
        self.assertEqual(plan["target_duration_seconds"], 480, "the model's target is not shortened behind anyone's back")
        self.assertEqual(result["estimated"]["finite_media_seconds"], 180)
        # With media that can be made to length, the same plan stands.
        filled = _plan((60, 360, 60), 480, primary=("source_footage",), supporting=("b_roll", "ai_media"))
        self.assertEqual(plan_engine.feasibility(filled, settings=_settings(target=480),
                                                 assets=_assets(source_footage_seconds=180))["status"], "ok")

    def test_images_that_are_not_there_or_not_enough(self) -> None:
        settings = _settings("tiktok", target=60)
        none = plan_engine.feasibility(_plan((10, 40, 10), 60, primary=("product_images",), kind="product"),
                                       settings=settings, assets=_assets(source_kind="product", source_has_picture=False))
        self.assertEqual(_check(none, "image_quantity")["status"], "needs_attention")
        few = plan_engine.feasibility(_plan((10, 40, 10), 60, primary=("product_images",), kind="product"),
                                      settings=settings, assets=_assets(source_kind="product", source_images=6))
        self.assertEqual(_check(few, "image_quantity")["status"], "ok")
        self.assertIn("chỉ đủ khoảng 30 giây", _check(few, "available_media")["detail"])
        enough = plan_engine.feasibility(_plan((5, 20, 5), 30, primary=("product_images",), kind="product"),
                                         settings=_settings("tiktok", target=30), assets=_assets(source_kind="product", source_images=6))
        self.assertEqual(enough["status"], "ok")

    def test_footage_from_a_source_with_no_picture(self) -> None:
        audio = _assets(source_kind="audio", source_has_picture=False)
        only = plan_engine.feasibility(_plan((10, 40, 10), 60, primary=("source_footage",), kind="audio"),
                                       settings=_settings(), assets=audio)
        self.assertEqual((only["status"], _check(only, "source_footage")["status"]), ("blocked", "blocked"))
        mixed = plan_engine.feasibility(_plan((10, 40, 10), 60, primary=("ai_media", "source_footage"), kind="audio"),
                                        settings=_settings(), assets=audio)
        self.assertEqual(mixed["status"], "needs_attention")

    def test_a_reup_cannot_be_longer_than_its_source(self) -> None:
        plan = _plan((30, 240, 30), 300, primary=("source_footage",), supporting=("graphics",))
        result = plan_engine.feasibility(plan, settings=_settings(target=300, workflow="reup"),
                                         assets=_assets(source_footage_seconds=62))
        self.assertEqual(_check(result, "available_media")["status"], "needs_attention")
        self.assertIn("62 giây", _check(result, "available_media")["detail"])

    def test_the_target_against_what_the_format_is_for(self) -> None:
        long_vertical = plan_engine.feasibility(_plan((40, 160, 40), 240), settings=_settings("tiktok", target=240), assets=_assets())
        self.assertEqual(_check(long_vertical, "platform_fit")["status"], "needs_attention")
        landscape = plan_engine.feasibility(_plan((40, 160, 40), 240), settings=_settings(target=240), assets=_assets())
        self.assertEqual(_check(landscape, "platform_fit")["status"], "ok")
        short = plan_engine.feasibility(_plan((2, 3), 5), settings=_settings("tiktok", target=5), assets=_assets())
        self.assertEqual(_check(short, "platform_fit")["status"], "needs_attention")

    def test_words_claims_and_required_assets(self) -> None:
        silent = _assets(has_transcript=False, has_dialogue=False, source_footage_seconds=62)
        retell = plan_engine.feasibility(_plan((10, 40, 10), 60, primary=("source_footage", "graphics")),
                                         settings=_settings(workflow="reup"), assets=silent)
        self.assertEqual(_check(retell, "transcript")["status"], "needs_attention")
        news = plan_engine.feasibility(_plan((10, 40, 10), 60, kind="article", cited=False), settings=_settings(), assets=_assets())
        self.assertEqual(_check(news, "claim_evidence")["status"], "needs_attention")
        wanted = [{"asset": "Ảnh chụp bao bì", "why": "Cần cho phần mở hộp", "required": True},
                  {"asset": "Nhạc nền", "why": "Tuỳ chọn", "required": False}]
        missing = plan_engine.feasibility(_plan((10, 40, 10), 60, missing=wanted), settings=_settings(), assets=_assets())
        self.assertEqual(_check(missing, "missing_assets")["status"], "needs_attention")
        self.assertIn("Ảnh chụp bao bì", _check(missing, "missing_assets")["detail"])
        self.assertNotIn("Nhạc nền", _check(missing, "missing_assets")["detail"])


class ReportReuseTests(unittest.TestCase):
    def _row(self, *, hours: float, volatility: str = "evergreen", **over) -> dict:
        return {"analysis_created_at": "A", "status": "complete", "report": {
            "evidence": [{"id": "ev-1"}], "collected": ["similar_videos"], "limitations": [],
            "brief": {"volatility_assumed": volatility}, "captured_at": (NOW - timedelta(hours=hours)).isoformat(),
        }, **over}

    def test_a_report_is_reused_while_its_subject_has_not_moved(self) -> None:
        self.assertTrue(project_planner.report_state(self._row(hours=48), "A")["fresh"])
        news = project_planner.report_state(self._row(hours=7, volatility="news"), "A")
        self.assertEqual((news["usable"], news["fresh"]), (True, False))
        self.assertFalse(project_planner.report_state(self._row(hours=1), "B")["usable"], "another analysis")
        self.assertFalse(project_planner.report_state(self._row(hours=1, status="failed"), "A")["usable"])
        self.assertFalse(project_planner.report_state(None, "A")["usable"])

    def test_the_language_is_a_code_however_the_analysis_wrote_it(self) -> None:
        # "Tiếng Việt (vi)" once went to the YouTube search as it stood and the search was refused.
        for written, code in (("vi", "vi"), ("vi-VN", "vi"), ("Tiếng Việt (vi)", "vi"), ("Vietnamese", "vi"),
                              ("English", "en"), ("en_US", "en"), ("", "vi"), (None, "vi"), ("Tiếng Anh", "en")):
            self.assertEqual(project_planner.language_code(written), code, written)
        brief = project_planner.research_brief({"title": "x"}, {"result": {"topic": "x", "language": "Tiếng Việt (vi)"}}, {})
        self.assertEqual(brief["language"], "vi")


# ---------------------------------------------------------------------------
# The step, with a model that answers from the prompt it is given
# ---------------------------------------------------------------------------

def _ids(prompt: str, kind: str) -> list[str]:
    """The evidence ids of one kind, as the prompt lists them."""
    return list(dict.fromkeys(re.findall(rf"\[(ev-[0-9a-f]{{10}})\] {kind}\b", prompt)))


def video_insights(prompt: str) -> dict:
    comments, videos = _ids(prompt, "comment_sample"), _ids(prompt, "video_meta")
    return {
        "insights": [
            _raw("ask", "audience_question", "Trong các comment mẫu, người xem hỏi nhiều về giá.", comments[:2],
                 sample_size=99999, source_count=77, confidence="low"),
            _raw("shape", "performance_pattern", "Trong nhóm video được lấy mẫu, tiêu đề dạng câu hỏi xuất hiện thường xuyên hơn.", videos[:3]),
            _raw("fake", "content_gap", "Chưa video nào giải thích lõi Trái Đất.", ["ev-0000000000"]),
            _raw("why", "performance_pattern", "Video này viral vì tiêu đề là một câu hỏi.", videos[:2]),
            _raw("guess", "opportunity", "Có thể làm thành loạt bài dài.", [], hypothesis=True),
            _raw("bare", "audience_need", "Người xem cần phần 2.", []),
        ],
        "angle_candidates": [
            _angle("a1", "Trả lời câu hỏi người xem hay hỏi nhất", ["ask"]),
            _angle("a2", "Đặt lại chủ đề thành một câu hỏi", ["shape"]),
            _angle("a3", "Giải thích lõi Trái Đất", ["fake"]),
            _angle("a4", "Mở thành loạt bài dài", ["guess"]),
        ],
        "limitations": [],
    }


def article_insights(prompt: str) -> dict:
    articles = _ids(prompt, "article")
    return {
        "insights": [
            _raw("when", "fact", "Sự cố xảy ra vào buổi sáng.", articles[:2], fact_status="confirmed"),
            _raw("count", "fact", "Có 12 khu vực bị ảnh hưởng.", articles[:1], fact_status="confirmed"),
            _raw("cause", "disputed_fact", "Nguyên nhân sự cố: các bài nêu khác nhau.", articles[:2]),
            _raw("pay", "uncertainty", "Chưa rõ mức bồi thường.", articles[:1]),
        ],
        "angle_candidates": [_angle("a1", "Điều đã chắc và điều còn tranh cãi", ["when", "cause"]),
                             _angle("a2", "Dòng thời gian của sự cố", ["when"])],
        "limitations": [],
    }


def product_insights(prompt: str) -> dict:
    page, articles, comments = _ids(prompt, "product_page"), _ids(prompt, "article"), _ids(prompt, "comment_sample")
    return {
        "insights": [
            _raw("price", "selling_point", "Giá 119.000₫ trên trang bán.", page),
            _raw("cheap", "selling_point", "Giá chỉ 99k, rẻ hơn các mẫu khác.", articles[:1]),
            _raw("battery", "selling_point", "Pin dùng liên tục 40 giờ.", []),
            _raw("ask", "audience_question", "Trong các comment mẫu, người xem hỏi về giá.", comments[:2]),
        ],
        "angle_candidates": [_angle("a1", "Trả lời thẳng câu hỏi về giá", ["ask"]), _angle("a2", "Đáng tiền ở đâu", ["price"])],
        "limitations": [],
    }


def plan_answer(prompt: str, *, seconds: tuple[int, ...] | None = None, target: int | None = None,
                primary=("ai_media",), supporting=("graphics",), proposed=(), angle: str = "") -> dict:
    """A plan as a model would write it. Unless told otherwise it does what the prompt asks."""
    angles = list(dict.fromkeys(re.findall(r"\[(ang-\d+)\]", prompt)))
    insights = list(dict.fromkeys(re.findall(r"\[(in-\d+)\]", prompt)))
    asked = re.search(r"DA DAT: (\d+) giay", prompt)
    target = target or (int(asked.group(1)) if asked else 60)
    if seconds is None:
        opening, closing = max(3, target // 8), max(3, target // 6)
        seconds = (opening, target - opening - closing, closing)
    return {
        "video_type": "giải thích nhanh", "target_duration_seconds": target,
        "target_audience": "Người mới tìm hiểu chủ đề", "goal": "Giữ người xem tới cuối video",
        "primary_angle_id": angle or angles[0], "alternative_angle_ids": angles[1:],
        "hook_strategy": "Mở bằng chính câu người xem hay hỏi",
        "content_structure": [
            {"name": name, "purpose": f"Vai trò của phần {name}", "estimated_seconds": value,
             "key_points": [f"Ý chính của phần {name}"], "insight_ids": insights[:1], "evidence_ids": []}
            for name, value in zip(("Mở đầu", "Thân bài", "Kết"), seconds)
        ],
        "media_strategy": {"primary_sources": list(primary), "supporting_sources": list(supporting),
                           "notes": "Hình minh hoạ là chính, đồ hoạ làm rõ con số."},
        "edit_direction": {
            "pacing": "nhanh", "average_shot_length_seconds": 3.5, "cut_style": "cắt thẳng theo câu",
            "transitions": "không chuyển cảnh trang trí", "text_animation": "chữ bật theo từ khoá",
            "subtitle_style": "phụ đề lớn giữa khung", "callouts": "khoanh con số", "zoom_punch_in": "ở câu mở đầu",
            "broll_usage": "minh hoạ từng ý", "graphics": "một biểu đồ",
        },
        "subtitle_strategy": "Phụ đề đầy đủ", "music_strategy": "Nhạc nền nhẹ", "sfx_strategy": "Ít hiệu ứng",
        "cta": "Mời xem phần tiếp theo", "factual_guardrails": [], "claims_to_avoid": [],
        "proposed_assets": list(proposed), "limitations": [],
    }


def in_turn(*answers):
    """One answer per call, the last one from then on. A callable is asked with the prompt."""
    queue = list(answers)

    def answer(prompt: str):
        current = queue.pop(0) if len(queue) > 1 else queue[0]
        return current(prompt) if callable(current) else current

    return answer


class Scripted:
    """Stands in for the orchestrator's model call, and keeps what it was asked."""

    def __init__(self, insights=video_insights, plan=plan_answer) -> None:
        self.insights, self.plan = insights, plan
        self.calls: list[dict] = []

    def __call__(self, system: str, user: str, schema: dict, **options):
        kind = "insight" if "insights" in schema["properties"] else "plan"
        self.calls.append({"kind": kind, "prompt": user, "step": options.get("step")})
        if options.get("report") is not None:
            options["report"].update(runtime="fake_cli", attempts=[{"runtime": "fake_cli", "status": "success"}])
        return (self.insights if kind == "insight" else self.plan)(user)

    def kinds(self) -> list[str]:
        return [call["kind"] for call in self.calls]


_TOPICS = {"video": "Trái Đất quay", "article": "Sự cố mất điện", "product": "Tai nghe Bluetooth", "audio": "Chuyện kể đêm khuya"}
_PRICED = {"name": "Tai nghe Bluetooth X1", "price": "119000", "price_text": "119.000₫", "captured_at": READ_AT,
           "product_id": "p-1", "images": ["a.jpg", "b.jpg", "c.jpg"]}


def _project(database, channel_id: str, *, kind: str = "video", seconds: int = 62, facts: dict | None = None,
             keywords: tuple[str, ...] = ("trái đất", "hành tinh")) -> int:
    tag = uuid.uuid4().hex[:6]
    topic = f"{_TOPICS[kind]} {tag}"
    if kind == "video":
        video_id, group, platform = f"n{uuid.uuid4().hex[:10]}", channel_id, ""
        url, payload = f"https://www.youtube.com/watch?v={video_id}", {"kind": "youtube#video", "id": video_id}
    else:
        video_id = f"{'local' if kind == 'audio' else 'web'}-{uuid.uuid4().hex[:16]}"
        group, platform = f"WEB-{kind.upper()}-{tag}", {"product": "shop", "audio": "upload"}.get(kind, "web")
        url, payload = f"https://nguon.test/{kind}/{tag}", {"source": "link_import"}
    database.upsert_channel({"youtube_channel_id": group, "channel_url": "https://x"})
    database.upsert_video({
        "youtube_video_id": video_id, "youtube_channel_id": group, "title": topic, "video_url": url,
        "metadata_hash": video_id, "duration_seconds": seconds, "source_kind": kind,
        "published_at": (NOW - timedelta(days=60)).isoformat(), "raw_payload": payload,
    })
    if platform:
        database.set_video_source_identity(video_id, source_platform=platform)
    result = {
        "topic": topic, "content_summary": f"Tóm tắt về {topic}.", "keywords": list(keywords),
        "scene_map": [{"what_happens": "Mở đầu"}], "source_type": kind, "language": "vi",
        "has_dialogue": kind in {"video", "audio"}, "limitations": ["Không rõ nguồn số liệu"],
    }
    if kind == "product":
        result["source_facts"] = dict(facts if facts is not None else _PRICED)
    if kind == "article":
        result["image_count"] = 2
    database.save_video_analysis(video_id, result, analysis_type="reference", provider="test")
    return int(database.create_production_project(video_id, title=topic)["id"])


class _ReasonCase(_PlanCase):
    def setUp(self) -> None:
        super().setUp()
        self.web_calls: list[str] = []

        def search(query: str, **options):
            self.web_calls.append(query)
            return _fake_search(query, **options)

        self.model = Scripted()
        for patcher in (
            mock.patch.object(main, "_research_collectors", side_effect=lambda: Collectors(
                self.database, self.youtube, web_search=search, fetch_page=_fake_page, captions=_captions)),
            mock.patch.object(main, "_call_orchestrator_json", self.model),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _post(self, project_id: int, **options):
        return self.client.post(f"/api/projects/{project_id}/steps/plan", json={"options": options})

    def _ok(self, project_id: int, **options) -> dict:
        response = self._post(project_id, **options)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["result"]

    def _stored(self, project_id: int) -> dict:
        return self.client.get(f"/api/projects/{project_id}/plan").json()

    def _row(self, project_id: int) -> dict:
        body = self.client.get(f"/api/projects/{project_id}/steps").json()
        return next(row for row in body["steps"] if row["key"] == "plan")

    def _network(self) -> tuple[int, int]:
        return len(self.youtube.calls), len(self.web_calls)


class FullRunTests(_ReasonCase):
    def test_research_then_insights_then_a_plan_each_naming_what_it_was_built_from(self) -> None:
        project_id = _project(self.database, self.channel_id)
        result = self._ok(project_id)
        self.assertEqual((result["status"], result["mode"], result["source_kind"]), ("completed", "auto", "video"))
        self.assertFalse(result["research_reused"])
        self.assertEqual(self.model.kinds(), ["insight", "plan"])
        self.assertEqual((result["ai"]["calls"], result["ai"]["repair_used"], result["ai"]["runtimes"]), (2, False, ["fake_cli"]))

        body = self._stored(project_id)
        plan_row, research, insight_row = body["plan"], body["research_report"], body["insight_report"]
        plan, insight = plan_row["plan"], insight_row["report"]
        self.assertEqual([item["label"] for item in body["stages"]], STAGE_LABELS)

        # The chain: each artefact names the one under it.
        self.assertEqual(insight_row["research_report_id"], research["id"])
        self.assertEqual((plan_row["research_report_id"], plan_row["insight_report_id"]), (research["id"], insight_row["id"]))
        self.assertEqual((plan["research_report_id"], plan["insight_report_id"]), (research["id"], insight_row["id"]))
        self.assertEqual(plan["analysis_ref"]["created_at"], plan_row["analysis_created_at"])
        self.assertEqual((plan_row["status"], plan_row["effective_status"], plan_row["stale"], plan_row["engine_version"]),
                         ("completed", "completed", False, "plan-phase3"))
        self.assertIn("plan", main._steps_done(project_id))

        # No sentence a model wrote is in the ResearchReport.
        collected = json.dumps(research, ensure_ascii=False)
        for item in [*insight["insights"], *insight["angle_candidates"]]:
            self.assertNotIn(item["statement"], collected)

        # What was kept rests on evidence that exists, with numbers worked out from it.
        self.assertEqual([item["type"] for item in insight["insights"]], ["audience_question", "performance_pattern"])
        known = {item["id"]: item for item in research["report"]["evidence"]}
        for item in insight["insights"]:
            self.assertTrue(item["evidence_ids"])
            self.assertTrue(set(item["evidence_ids"]) <= set(known), item)
        asked = insight["insights"][0]
        cited = [known[eid] for eid in asked["evidence_ids"]]
        self.assertEqual(asked["sample_size"], sum(item["sample_size"] for item in cited))
        self.assertEqual((asked["sample_size"], asked["source_count"], asked["confidence"]), (150, 2, "high"))
        reasons = [item["reason"] for item in insight["rejected"]]
        self.assertEqual(len(reasons), 3)
        self.assertIn("Viện dẫn bằng chứng không tồn tại", reasons)
        self.assertTrue(any("nguyên nhân" in reason for reason in reasons))
        self.assertFalse(any(insight_engine.is_causal_claim(item["statement"]) for item in insight["insights"]))
        self.assertEqual([item["statement"] for item in insight["hypotheses"]], ["Có thể làm thành loạt bài dài."])
        self.assertEqual([item["id"] for item in insight["angle_candidates"]], ["ang-1", "ang-2"])
        self.assertEqual(len(insight["rejected_angles"]), 2)
        for angle in insight["angle_candidates"]:
            for key in ("statement", "target_audience", "need_or_problem", "supporting_insight_ids", "differentiation",
                        "platform_fit", "risks"):
                self.assertIn(key, angle)

        # The plan.
        for key in PLAN_KEYS:
            self.assertIn(key, plan)
        self.assertEqual((plan["platform"], plan["aspect_ratio"], plan["output_profile"], plan["language"]),
                         ("youtube", "16:9", "youtube_landscape", "vi"))
        self.assertEqual(plan["primary_angle"]["id"], "ang-1")
        self.assertEqual([item["id"] for item in plan["alternative_angles"]], ["ang-2"])
        self.assertEqual((plan["target_duration_seconds"], plan["target_duration_from"]), (60, "ai_proposed"))
        self.assertEqual(sum(item["estimated_seconds"] for item in plan["content_structure"]), 60)
        for section in plan["content_structure"]:
            self.assertEqual(set(section), {"name", "purpose", "estimated_seconds", "key_points", "insight_ids", "evidence_ids"})
        self.assertEqual(set(plan["media_strategy"]), {"primary_sources", "supporting_sources", "notes"})
        self.assertEqual(plan["edit_direction"]["average_shot_length_seconds"], 3.5)
        self.assertEqual(plan["pending_fields"], [])
        self.assertTrue(any("Có thể làm thành loạt bài dài" in item for item in plan["claims_to_avoid"]))
        # What the analysis could not settle goes to the writer whole, as a constraint.
        self.assertEqual(plan["constraints"]["must_not_invent"], ["Không rõ nguồn số liệu"])
        self.assertEqual(plan["factual_guardrails"], [], "a video with no claim in doubt carries no warning")
        feasibility = plan_row["feasibility"]
        self.assertEqual(feasibility["status"], "ok")
        self.assertEqual([item["key"] for item in feasibility["checks"]],
                         ["duration_budget", "platform_fit", "available_media", "transcript", "claim_evidence", "missing_assets"])

    def test_the_model_reads_a_brief_written_for_what_the_source_is(self) -> None:
        labels = {"video": "NGUON LA MOT VIDEO", "article": "NGUON LA MOT BAI VIET / TIN TUC",
                  "product": "NGUON LA MOT SAN PHAM DANG BAN", "audio": "NGUON LA MOT FILE AM THANH"}
        answers = {"article": article_insights, "product": product_insights}
        for kind, label in labels.items():
            self.model.calls.clear()
            self.model.insights = answers.get(kind, video_insights)
            result = self._ok(_project(self.database, self.channel_id, kind=kind), refresh_identity=kind == "video")
            self.assertEqual(result["source_kind"], kind)
            prompt = self.model.calls[0]["prompt"]
            self.assertIn(label, prompt, kind)
            for other in set(labels.values()) - {label}:
                self.assertNotIn(other, prompt, kind)

    def test_the_stage_reached_can_be_read_while_the_step_runs(self) -> None:
        project_id = _project(self.database, self.channel_id)
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def slow(prompt: str) -> dict:
            entered.set()
            release.wait(10)
            return video_insights(prompt)

        self.model.insights = slow
        errors: list[BaseException] = []
        with mock.patch.object(main._step_registry, "update", wraps=main._step_registry.update) as noted:
            thread = threading.Thread(target=lambda: _capture(errors, main.run_project_step, project_id, "plan", {}), daemon=True)
            thread.start()
            self.assertTrue(entered.wait(10))
            row = self._row(project_id)
            self.assertEqual(row["state"], "running")
            self.assertEqual((row["run"]["stage"], row["run"]["stage_label"]), ("insights", "Phân tích insight"))
            self.assertEqual([item["label"] for item in row["run"]["stages"]], STAGE_LABELS)
            release.set()
            thread.join(10)
        self.assertEqual(errors, [])
        self.assertEqual([call.kwargs["stage_label"] for call in noted.call_args_list], STAGE_LABELS)
        self.assertEqual(self._row(project_id)["last_run"]["status"], "success")


class SourceKindReasoningTests(_ReasonCase):
    def test_a_disputed_claim_in_the_news_becomes_a_factual_guardrail(self) -> None:
        self.model.insights = article_insights
        project_id = _project(self.database, self.channel_id, kind="article")
        result = self._ok(project_id, refresh_identity=False)
        body = self._stored(project_id)
        insight, plan = body["insight_report"]["report"], body["plan"]["plan"]
        self.assertEqual((result["source_kind"], plan["source_kind"]), ("article", "article"))
        statuses = {item["statement"]: item["fact_status"] for item in insight["insights"]}
        self.assertEqual(list(statuses.values()), ["confirmed", "reported", "disputed", "unknown"],
                         "a model saying 'confirmed' on one page read does not make it so")
        self.assertEqual(insight["summary"]["fact_status"], {"confirmed": 1, "reported": 1, "disputed": 1, "unknown": 1})
        guardrails = plan["factual_guardrails"]
        self.assertTrue(any(item.startswith("Các nguồn nói khác nhau") and "Nguyên nhân sự cố" in item for item in guardrails))
        self.assertTrue(any(item.startswith("Mới có một nguồn đưa") and "12 khu vực" in item for item in guardrails))
        self.assertTrue(any(item.startswith("Chưa được xác nhận") and "bồi thường" in item for item in guardrails))
        self.assertEqual(result["factual_guardrails"], guardrails)
        # The checked claims are kept, with the pages they were read on, for the next plan on this subject.
        topic = body["research_report"]["report"]["topic"]
        kept = {item["fact"]: item for item in TopicIntelligence(self.database).get(topic["key"], "vi")["facts"]}
        self.assertEqual(kept["Sự cố xảy ra vào buổi sáng."]["status"], "confirmed")
        self.assertEqual(len(kept["Sự cố xảy ra vào buổi sáng."]["source_urls"]), 2)
        self.assertNotIn("Chưa rõ mức bồi thường.", kept)

    def test_a_product_price_keeps_the_moment_it_was_read(self) -> None:
        self.model.insights = product_insights
        project_id = _project(self.database, self.channel_id, kind="product")
        self._ok(project_id, refresh_identity=False)
        body = self._stored(project_id)
        insight, plan = body["insight_report"]["report"], body["plan"]["plan"]
        priced = next(item for item in insight["insights"] if item["statement"].startswith("Giá 119.000₫"))
        self.assertEqual(priced["price_captured_at"], READ_AT)
        self.assertTrue(any(item.startswith(f"Giá chỉ đúng tại thời điểm đọc ({READ_AT[:16]})") for item in plan["factual_guardrails"]))
        self.assertTrue(any(item.startswith(f"Giá đọc lúc {READ_AT[:16]}") for item in plan["factual_guardrails"]))
        self.assertNotIn("no_price_claims", plan["constraints"])
        # A price heard elsewhere, and a claim nobody showed.
        self.assertEqual(plan["claims_needing_proof"], ["Giá chỉ 99k, rẻ hơn các mẫu khác."])
        self.assertTrue(any("Pin dùng liên tục 40 giờ" in item for item in plan["claims_to_avoid"]))
        self.assertFalse(any("40 giờ" in item["statement"] for item in insight["insights"]))

    def test_a_product_with_no_price_is_still_planned_and_says_so(self) -> None:
        self.model.insights = product_insights
        facts = {"name": "Tai nghe Bluetooth X1", "price": "", "captured_at": None, "images": ["a.jpg"]}
        project_id = _project(self.database, self.channel_id, kind="product", facts=facts)
        result = self._ok(project_id, refresh_identity=False)
        self.assertIn(result["status"], {"completed", "needs_user_decision"})
        self.assertIn("CHUA CO GIA", self.model.calls[0]["prompt"])
        self.assertIn("Gia: CHUA DOC DUOC", self.model.calls[1]["prompt"])
        body = self._stored(project_id)
        insight, plan = body["insight_report"]["report"], body["plan"]["plan"]
        self.assertTrue(plan["constraints"]["no_price_claims"])
        self.assertTrue(any("Không nêu bất kỳ con số giá nào" in item for item in plan["claims_to_avoid"]))
        self.assertTrue(any("Chưa đọc được giá sản phẩm" in item for item in plan["limitations"]))
        # The model named a price anyway: nothing read vouches for it.
        priced = next(item for item in insight["insights"] if item["statement"].startswith("Giá 119.000₫"))
        self.assertEqual(priced["proof"], "needs_proof")
        self.assertNotIn("price_captured_at", priced)
        self.assertIn("Giá 119.000₫ trên trang bán.", plan["claims_needing_proof"])

    def test_an_audio_source_is_not_planned_as_if_it_had_a_picture(self) -> None:
        self.model.plan = partial(plan_answer, primary=("source_footage",), supporting=())
        project_id = _project(self.database, self.channel_id, kind="audio", seconds=120)
        result = self._ok(project_id, refresh_identity=False)
        self.assertIn("Nguon KHONG co hinh anh", self.model.calls[0]["prompt"])
        self.assertIn("nguon khong co hinh de cat", self.model.calls[1]["prompt"])
        self.assertEqual((result["status"], result["feasibility"]["status"]), ("blocked", "blocked"))
        self.assertIn("không có hình để cắt", result["feasibility"]["reason"])
        self.assertNotIn("plan", main._steps_done(project_id), "a plan with nothing to make the video from is not a finished step")


class FeasibilityOnTheStepTests(_ReasonCase):
    def test_a_plan_longer_than_its_target_is_reported_not_trimmed(self) -> None:
        self.model.plan = partial(plan_answer, seconds=(20, 60, 30), target=110)
        project_id = _project(self.database, self.channel_id)
        result = self._ok(project_id, settings={"output_profile": "youtube_shorts", "target_duration_seconds": 60})
        self.assertEqual(result["status"], "needs_user_decision")
        plan_row = self._stored(project_id)["plan"]
        plan = plan_row["plan"]
        self.assertEqual((plan["target_duration_seconds"], plan["target_duration_from"]), (60, "project"))
        self.assertEqual([item["estimated_seconds"] for item in plan["content_structure"]], [20, 60, 30])
        budget = _check(plan_row["feasibility"], "duration_budget")
        self.assertEqual(budget["status"], "needs_attention")
        self.assertTrue(budget["options"])
        self.assertEqual(plan_row["status"], "needs_user_decision")

    def test_a_small_drift_is_adjusted_and_the_plan_is_completed(self) -> None:
        self.model.plan = partial(plan_answer, seconds=(10, 45, 15))
        project_id = _project(self.database, self.channel_id)
        result = self._ok(project_id, settings={"target_duration_seconds": 60})
        self.assertEqual((result["status"], result["feasibility"]["status"]), ("completed", "adjusted"))
        self.assertEqual(sum(item["seconds"] for item in result["structure"]), 60)
        self.assertEqual(result["feasibility"]["adjustments"][0]["from_total"], 70)

    def test_media_that_cannot_cover_the_length_needs_attention(self) -> None:
        self.model.plan = partial(plan_answer, primary=("source_footage",), supporting=())
        project_id = _project(self.database, self.channel_id, seconds=180)
        result = self._ok(project_id, settings={"target_duration_seconds": 480})
        self.assertEqual(result["status"], "needs_user_decision")
        self.assertEqual(result["target_duration_seconds"], 480, "eight minutes asked for stays eight minutes")
        media = next(item for item in result["feasibility"]["attention"] if item["key"] == "available_media")
        self.assertIn("chỉ đủ khoảng 180 giây", media["detail"])
        self.assertEqual(len(media["options"]), 3)

    def test_what_the_project_decided_is_not_the_models_to_change(self) -> None:
        self.model.plan = partial(plan_answer, angle="ang-2")
        project_id = _project(self.database, self.channel_id)
        self._ok(project_id, settings={"output_profile": "tiktok", "target_duration_seconds": 45, "video_type": "review nhanh"})
        plan = self._stored(project_id)["plan"]["plan"]
        self.assertEqual((plan["platform"], plan["aspect_ratio"], plan["output_profile"]), ("tiktok", "9:16", "tiktok"))
        self.assertEqual((plan["target_duration_seconds"], plan["video_type"]), (45, "review nhanh"))
        self.assertEqual(plan["primary_angle"]["id"], "ang-2")
        self.assertEqual([item["id"] for item in plan["alternative_angles"]], ["ang-1"])


class StaleAndReplanTests(_ReasonCase):
    def test_changing_only_the_settings_replans_from_what_is_stored(self) -> None:
        project_id = _project(self.database, self.channel_id)
        first = self._ok(project_id)
        before = self._network()
        self.model.calls.clear()
        with mock.patch.object(main.source_identity, "refresh", side_effect=AssertionError("identity lookup")), \
                mock.patch.object(main, "probe_source_link", side_effect=AssertionError("yt-dlp")):
            again = self._ok(project_id, mode="replan",
                             settings={"output_profile": "tiktok", "target_duration_seconds": 45, "video_type": "review nhanh"})
        self.assertEqual(self._network(), before, "no search, no comment, no page was fetched")
        self.assertEqual(self.model.kinds(), ["plan"], "one model call: the insights are reused")
        self.assertEqual((again["ai"]["calls"], again["research_reused"], again["insight_reused"]), (1, True, True))
        self.assertEqual((again["research_report_id"], again["insight_report_id"]),
                         (first["research_report_id"], first["insight_report_id"]))
        self.assertEqual(again["plan_version"], first["plan_version"] + 1)
        body = self._stored(project_id)
        plan = body["plan"]["plan"]
        self.assertEqual((plan["platform"], plan["aspect_ratio"], plan["target_duration_seconds"], plan["video_type"]),
                         ("tiktok", "9:16", 45, "review nhanh"))
        self.assertEqual(plan["requested"], {"output_profile": "tiktok", "target_duration_seconds": 45, "video_type": "review nhanh"})
        self.assertEqual(sum(item["estimated_seconds"] for item in plan["content_structure"]), 45)
        self.assertFalse(body["plan"]["stale"])
        self.assertEqual(self.database.get_latest_research_report(project_id)["id"], first["research_report_id"])

    def test_a_fresh_report_is_not_researched_again(self) -> None:
        project_id = _project(self.database, self.channel_id)
        first = self._ok(project_id)
        before = self._network()
        self.model.calls.clear()
        second = self._ok(project_id)
        self.assertEqual(self._network(), before)
        self.assertTrue(second["research_reused"])
        self.assertEqual(second["research_report_id"], first["research_report_id"])
        self.assertEqual(self.model.kinds(), ["insight", "plan"])
        self.assertEqual(second["insight_report_version"], first["insight_report_version"] + 1)
        third = self._ok(project_id, mode="full")
        self.assertFalse(third["research_reused"])
        self.assertEqual(third["research_report_version"], first["research_report_version"] + 1)

    def test_a_newer_research_report_makes_the_insights_and_the_plan_stale(self) -> None:
        project_id = _project(self.database, self.channel_id)
        first = self._ok(project_id)
        old = self._stored(project_id)["research_report"]
        newer = self.database.create_research_report(
            project_id, status="complete", source_kind="video", analysis_created_at=old["analysis_created_at"],
            engine_version=old["engine_version"], report=old["report"], captured_at=old["report"]["captured_at"],
        )
        body = self._stored(project_id)
        self.assertTrue(body["plan"]["stale"])
        self.assertEqual(body["plan"]["effective_status"], "stale")
        self.assertIn("Có báo cáo nghiên cứu mới hơn", body["plan"]["stale_reasons"])
        self.assertNotIn("plan", main._steps_done(project_id))
        self.assertTrue(main._current_project_insight(project_id)["stale"])

        # Insights read from the older report cannot carry a new plan...
        refused = self._post(project_id, mode="replan")
        self.assertEqual(refused.status_code, 409)
        self.assertIn("mode=reason", refused.json()["detail"])
        # ...but reasoning again from the stored report needs no network.
        before = self._network()
        self.model.calls.clear()
        again = self._ok(project_id, mode="reason")
        self.assertEqual(self._network(), before)
        self.assertEqual(self.model.kinds(), ["insight", "plan"])
        self.assertEqual(again["research_report_id"], newer["id"])
        self.assertNotEqual(again["insight_report_id"], first["insight_report_id"])
        self.assertFalse(self._stored(project_id)["plan"]["stale"])
        self.assertIn("plan", main._steps_done(project_id))

    def test_a_new_analysis_makes_everything_stale_and_is_researched_again(self) -> None:
        project_id = _project(self.database, self.channel_id)
        first = self._ok(project_id)
        video_id = self.database.get_production_project(project_id)["youtube_video_id"]
        analysis = self.database.get_video_analysis(video_id, analysis_type="reference")["result"]
        self.database.save_video_analysis(video_id, {**analysis, "content_summary": "Phân tích lại."},
                                          analysis_type="reference", provider="test")
        body = self._stored(project_id)
        self.assertIn("Bản phân tích nguồn đã thay đổi", body["plan"]["stale_reasons"])
        for mode in ("replan", "reason"):
            self.assertEqual(self._post(project_id, mode=mode).status_code, 409, mode)
        again = self._ok(project_id)
        self.assertFalse(again["research_reused"], "a report on the older analysis is not reused")
        self.assertEqual(again["research_report_version"], first["research_report_version"] + 1)

    def test_a_newer_insight_report_makes_the_plan_stale(self) -> None:
        project_id = _project(self.database, self.channel_id)
        self._ok(project_id)
        self.model.plan = in_turn({"primary_angle_id": "ang-9"})
        failed = self._post(project_id, mode="reason")
        self.assertEqual(failed.status_code, 502)
        body = self._stored(project_id)
        self.assertEqual(body["plan"]["version"], 1, "the failed run saved no plan")
        self.assertEqual(body["plan"]["stale_reasons"], ["Có báo cáo insight mới hơn"])

    def test_an_unknown_mode_is_refused(self) -> None:
        project_id = _project(self.database, self.channel_id)
        response = self._post(project_id, mode="nhanh")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.model.calls, [])

    def test_replanning_before_anything_was_researched_is_refused(self) -> None:
        project_id = _project(self.database, self.channel_id)
        for mode in ("replan", "reason"):
            response = self._post(project_id, mode=mode)
            self.assertEqual(response.status_code, 409, mode)
            self.assertIn("mode=auto", response.json()["detail"])
        self.assertEqual((self.model.calls, self._network()), ([], (0, 0)))


class RepairTests(_ReasonCase):
    """One insight call, one plan call, and a single repair between them."""

    def test_an_answer_that_is_not_json_is_repaired_once(self) -> None:
        self.model.insights = in_turn("đây không phải JSON", video_insights)
        project_id = _project(self.database, self.channel_id)
        result = self._ok(project_id)
        self.assertEqual(self.model.kinds(), ["insight", "insight", "plan"])
        self.assertEqual((result["ai"]["calls"], result["ai"]["repair_used"]), (3, True))
        self.assertIn("Cau tra loi truoc KHONG dung", self.model.calls[1]["prompt"])
        self.assertEqual(result["status"], "completed")

    def test_an_answer_citing_only_invented_evidence_is_repaired(self) -> None:
        invented = {"insights": [_raw("k", "content_gap", "Một khoảng trống.", ["ev-0000000000"])],
                    "angle_candidates": [_angle("a", "Một góc", ["k"])], "limitations": []}
        self.model.insights = in_turn(invented, video_insights)
        result = self._ok(_project(self.database, self.channel_id))
        self.assertEqual(result["ai"]["calls"], 3)
        self.assertIn("Viện dẫn bằng chứng không tồn tại", self.model.calls[1]["prompt"])

    def test_a_plan_choosing_an_angle_that_was_not_offered_is_repaired(self) -> None:
        self.model.plan = in_turn(partial(plan_answer, angle="ang-9"), plan_answer)
        result = self._ok(_project(self.database, self.channel_id))
        self.assertEqual(self.model.kinds(), ["insight", "plan", "plan"])
        self.assertEqual(result["primary_angle"], "Trả lời câu hỏi người xem hay hỏi nhất")

    def test_an_answer_still_unusable_after_the_repair_fails_cleanly(self) -> None:
        self.model.insights = in_turn({"insights": [], "angle_candidates": []})
        project_id = _project(self.database, self.channel_id)
        response = self._post(project_id)
        self.assertEqual(response.status_code, 502)
        self.assertIn("AI trả lời chưa dùng được ở bước Phân tích insight", response.json()["detail"])
        self.assertEqual(self.model.kinds(), ["insight", "insight"], "one repair, then stop")
        body = self._stored(project_id)
        self.assertIsNone(body["plan"], "no half plan is saved")
        self.assertIsNone(body["insight_report"])
        self.assertEqual(body["research_report"]["status"], "complete", "the research is kept for the next try")
        self.assertEqual(self._row(project_id)["last_run"]["status"], "failed")
        self.assertNotIn("plan", main._steps_done(project_id))

    def test_the_repair_is_not_spent_twice(self) -> None:
        self.model.insights = in_turn("hỏng", video_insights)
        self.model.plan = in_turn({"primary_angle_id": "ang-9"})
        project_id = _project(self.database, self.channel_id)
        response = self._post(project_id)
        self.assertEqual(response.status_code, 502)
        self.assertIn("Lập kế hoạch", response.json()["detail"])
        self.assertEqual(self.model.kinds(), ["insight", "insight", "plan"], "three calls at most")
        body = self._stored(project_id)
        self.assertIsNone(body["plan"])
        self.assertIsNotNone(body["insight_report"], "the insights already validated are kept")
        # The next try needs neither the network nor the insight call's research.
        self.model.plan = plan_answer
        self.model.calls.clear()
        before = self._network()
        self.assertEqual(self._ok(project_id, mode="replan")["status"], "completed")
        self.assertEqual((self.model.kinds(), self._network()), (["plan"], before))


class RuntimeFallbackTests(_PlanCase):
    """Through the real orchestrator call: the stage's policy, its fallback, its audit row."""

    def setUp(self) -> None:
        super().setUp()
        self.model = Scripted()
        assignment = {"mode": "fallback", "executor": "astra", "allowed_agents": ["astra", "claude"],
                      "fallback_agents": ["claude"], "reviewer": "auto"}
        ready = {"installed": True, "logged_in": True}
        for patcher in (
            mock.patch.object(main.settings, "agent_assignment", return_value=assignment),
            mock.patch.object(main, "codex_cli_status", return_value=ready),
            mock.patch.object(main, "claude_code_cli_status", return_value=ready),
            mock.patch.object(main, "antigravity_cli_status", return_value={"installed": False, "logged_in": False}),
            mock.patch.object(main, "call_antigravity_json", side_effect=AssertionError("not allowed for this stage")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_runtime_that_fails_hands_over_to_the_next_one_allowed(self) -> None:
        project_id = _project(self.database, self.channel_id)
        with mock.patch.object(main, "call_codex_json", side_effect=LlmError("codex hết giờ")) as codex, \
                mock.patch.object(main, "call_claude_code_cli_json", side_effect=self.model) as claude:
            response = self.client.post(f"/api/projects/{project_id}/steps/plan", json={"options": {}})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        self.assertEqual((codex.call_count, claude.call_count), (2, 2))
        self.assertEqual(result["ai"]["runtimes"], ["claude_code_cli"])
        self.assertEqual([item["fallback_from"] for item in result["ai"]["detail"]], [["codex_cli"], ["codex_cli"]])
        self.assertEqual(result["status"], "completed")
        plan_row = self.client.get(f"/api/projects/{project_id}/plan").json()["plan"]
        self.assertEqual(plan_row["provider"], "claude_code_cli")
        audit = [step for step in self.database.list_orchestrator_steps() if step.get("project_id") == project_id]
        self.assertEqual([step["step"] for step in audit if step["runtime"] == "claude_code_cli"],
                         ["Phân tích insight", "Lập kế hoạch"])

    def test_when_no_runtime_answers_the_step_fails_cleanly(self) -> None:
        project_id = _project(self.database, self.channel_id)
        with mock.patch.object(main, "call_codex_json", side_effect=LlmError("codex hỏng")), \
                mock.patch.object(main, "call_claude_code_cli_json", side_effect=LlmError("claude hỏng")):
            response = self.client.post(f"/api/projects/{project_id}/steps/plan", json={"options": {}})
        self.assertEqual(response.status_code, 502)
        self.assertIn("AI chưa chạy được bước Phân tích insight", response.json()["detail"])
        body = self.client.get(f"/api/projects/{project_id}/plan").json()
        self.assertIsNone(body["plan"])
        self.assertIsNone(body["insight_report"])
        self.assertIsNotNone(body["research_report"], "what was collected is kept")
        # Reasoning again, once a runtime is back, fetches nothing.
        calls = len(self.youtube.calls)
        with mock.patch.object(main, "call_codex_json", side_effect=self.model):
            again = self.client.post(f"/api/projects/{project_id}/steps/plan", json={"options": {"mode": "reason"}})
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(len(self.youtube.calls), calls)
        self.assertEqual(again.json()["result"]["ai"]["runtimes"], ["codex_cli"])


# ---------------------------------------------------------------------------
# Hardening: blocked sources, relevance, assets, step state, the chosen angle
# ---------------------------------------------------------------------------

_READ = "<html><head><title>Bài viết</title></head><body><p>Nội dung bài viết đã đọc được.</p></body></html>"
_WALLS = {
    "https://chan.test/security": "<html><head><title>Security Check</title></head><body><p>Verify to continue</p></body></html>",
    "https://chan.test/captcha": "<html><head><title>Tin</title></head><body><p>Vui lòng nhập CAPTCHA để tiếp tục.</p></body></html>",
    "https://chan.test/login": "<html><head><title>Tài liệu</title></head><body><p>Đăng nhập để tiếp tục đọc tài liệu này.</p></body></html>",
}
_REFUSED = {"https://chan.test/403": PermissionError("Client error '403 Forbidden'"), "https://chan.test/timeout": TimeoutError("hết giờ")}


def _walled_fetch(url: str) -> str:
    if url in _REFUSED:
        raise _REFUSED[url]
    if url.endswith("/404"):
        raise RuntimeError("Client error '404 Not Found'")
    return _WALLS.get(url, _READ)


class BlockedSourceTests(unittest.TestCase):
    """A source that refused, or never answered, is not evidence - not even as a snippet."""

    def _collect(self, urls: list[str], fetch=_walled_fetch) -> dict:
        def search(query: str, **options):
            return [{"title": f"Kết quả {index}", "url": url, "source": "x", "snippet": "trích đoạn của máy tìm kiếm"}
                    for index, url in enumerate(urls)]

        collectors = Collectors(mock.Mock(list_recent_research_reports=lambda limit: []), mock.Mock(api_key=""),
                                web_search=search, fetch_page=fetch, budget=Budget(web_read_pages=len(urls)))
        return collectors.web(["chủ đề"])

    def test_a_403_a_challenge_a_login_wall_and_a_timeout_leave_no_evidence(self) -> None:
        blocked = [*_REFUSED, *_WALLS]
        result = self._collect(["https://bao.test/doc-duoc", *blocked])
        self.assertEqual([item["source_url"] for item in result["evidence"]], ["https://bao.test/doc-duoc"])
        failed = {item["source"]: item for item in result["failed"]}
        self.assertEqual(sorted(failed), sorted(blocked))
        for url in blocked:
            self.assertEqual(failed[url]["collector_status"], "blocked", url)
        self.assertEqual(result["timeline"], [], "a page that was not read dates nothing")

    def test_a_page_that_is_gone_is_failed_not_blocked_and_is_no_evidence_either(self) -> None:
        result = self._collect(["https://bao.test/404"])
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["failed"][0]["collector_status"], "failed")

    def test_an_article_that_mentions_a_captcha_is_still_an_article(self) -> None:
        long_page = "<html><head><title>Bài dài</title></head><body><p>" + ("Bài viết bàn về captcha và bảo mật web. " * 30) + "</p></body></html>"
        result = self._collect(["https://bao.test/captcha-la-gi"], fetch=lambda url: long_page)
        self.assertEqual([item["source_kind"] for item in result["evidence"]], ["article"])
        self.assertEqual(result["failed"], [])


class BlockedSourceOnTheStepTests(_ReasonCase):
    def test_a_blocked_page_reaches_neither_the_report_nor_the_model(self) -> None:
        def search(query: str, **options):
            return [{"title": "Đọc được", "url": "https://bao.test/doc-duoc", "source": "bao.test", "snippet": "…"},
                    {"title": "Bị chặn", "url": "https://chan.test/403", "source": "chan.test", "snippet": "trích đoạn"},
                    {"title": "Security Check", "url": "https://chan.test/security", "source": "chan.test", "snippet": "trích đoạn"}]

        with mock.patch.object(main, "_research_collectors", side_effect=lambda: Collectors(
                self.database, self.youtube, web_search=search, fetch_page=_walled_fetch, captions=_captions)):
            project_id = _project(self.database, self.channel_id)
            result = self._ok(project_id)
        report = self._stored(project_id)["research_report"]["report"]
        urls = {item["source_url"] for item in report["evidence"]}
        self.assertIn("https://bao.test/doc-duoc", urls)
        self.assertFalse(urls & {"https://chan.test/403", "https://chan.test/security"})
        blocked = [item for item in report["failed_sources"] if item["collector_status"] == "blocked"]
        self.assertEqual(sorted(item["source"] for item in blocked), ["https://chan.test/403", "https://chan.test/security"])
        self.assertTrue(any("nguồn bị chặn" in item for item in report["limitations"]))
        self.assertEqual(result["research_status"], "partial")
        # What the model may cite is what was read.
        by_id = {item["id"]: item for item in report["evidence"]}
        prompt = self.model.calls[0]["prompt"]
        offered = [evidence_id for kind in ("article", "official", "search_result") for evidence_id in _ids(prompt, kind)]
        self.assertTrue(offered)
        for evidence_id in offered:
            self.assertNotIn("chan.test", by_id[evidence_id]["source_url"])

    def test_a_listing_that_was_never_read_is_not_evidence(self) -> None:
        facts = {"name": "", "price": "", "captured_at": None, "read_status": "NEED_HUMAN_VERIFY", "read_detail": "captcha"}
        project_id = _project(self.database, self.channel_id, kind="product", facts=facts)
        self._ok(project_id, reason=False, refresh_identity=False)
        report = self._stored(project_id)["research_report"]["report"]
        self.assertFalse([item for item in report["evidence"] if item["source_kind"] == "product_page"])
        source = next(item for item in report["failed_sources"] if item["collector"] == "planner.source")
        self.assertEqual(source["collector_status"], "blocked")
        self.assertTrue(any("Chưa đọc được trang sản phẩm" in item for item in report["limitations"]))

    def test_a_block_page_kept_by_an_older_report_supports_no_fact_and_no_angle(self) -> None:
        project_id = _project(self.database, self.channel_id)
        self._ok(project_id, reason=False)
        old = self.database.get_latest_research_report(project_id)
        wall = research_evidence.make_evidence(
            "article", source_url="https://chan.test/cu", collector="web.search", title="Security Check",
            excerpt="Verify to continue. Please enable JavaScript.")
        self.database.create_research_report(
            project_id, status="complete", source_kind="video", analysis_created_at=old["analysis_created_at"],
            engine_version=old["engine_version"], report={**old["report"], "evidence": [*old["report"]["evidence"], wall]},
            captured_at=old["report"]["captured_at"],
        )

        def insights(prompt: str) -> dict:
            answer = video_insights(prompt)
            answer["insights"].insert(0, _raw("wall", "fact", "Trang này xác nhận Trái Đất quay nhanh dần.", [wall["id"]]))
            answer["angle_candidates"].insert(0, _angle("a0", "Dựa trên trang bị chặn", ["wall"]))
            return answer

        self.model.insights = insights
        self._ok(project_id, mode="reason")
        self.assertNotIn(wall["id"], self.model.calls[0]["prompt"])
        insight = self._stored(project_id)["insight_report"]["report"]
        self.assertEqual(insight["excluded_evidence"]["blocked"], [wall["id"]])
        refused = next(item for item in insight["rejected"] if "xác nhận Trái Đất quay nhanh dần" in item["statement"])
        self.assertEqual((refused["reason"], refused["excluded_evidence_ids"]), (insight_engine.BLOCKED_SOURCE, [wall["id"]]))
        for item in insight["insights"]:
            self.assertNotIn(wall["id"], item["evidence_ids"])
        self.assertFalse([item for item in insight["insights"] if item["type"] == "fact"])
        self.assertIn("Dựa trên trang bị chặn", [item["statement"] for item in insight["rejected_angles"]])
        self.assertTrue(any("trang bị chặn" in item for item in insight["limitations"]))


class RelevanceTests(unittest.TestCase):
    def test_one_shared_word_does_not_make_a_video_about_an_article(self) -> None:
        terms = research_collectors.topic_terms({"topic": "Doanh nghiệp tự quyết giá xăng dầu", "keywords": ["xăng dầu", "giá bán lẻ"]})
        videos = [{"video_id": "a", "title": "Doanh nghiệp tự quyết giá xăng dầu từ năm sau?"},
                  {"video_id": "b", "title": "Giá quan tài tăng mạnh"},
                  {"video_id": "c", "title": "Chứng khoán hôm nay"}]
        strict = {item["video_id"]: item["relevance"] for item in research_collectors.mark_relevance(videos, terms, strict=True)}
        loose = {item["video_id"]: item["relevance"] for item in research_collectors.mark_relevance(videos, terms, strict=False)}
        self.assertEqual(strict, {"a": "high", "b": "low", "c": "low"})
        self.assertEqual(loose, {"a": "high", "b": "high", "c": "low"})
        unknown = research_collectors.mark_relevance(videos, set(), strict=True)
        self.assertEqual({item["relevance"] for item in unknown}, {"high"}, "with no subject words nothing is judged")
        self.assertEqual(research_collectors.mark_relevance(videos, terms, strict=True)[1]["topic_match"],
                         {"shared": 1, "title_share": 0.2, "strict": True})


    def test_a_report_from_before_the_mark_is_judged_by_the_same_rule(self) -> None:
        make = partial(research_evidence.make_evidence, collector="test", platform="youtube")
        on = make("video_meta", source_url="https://youtube.test/watch?v=on", native_source_id="on", title="Vì sao mất điện diện rộng?")
        off = make("video_meta", source_url="https://youtube.test/watch?v=off", native_source_id="off", title="Chứng khoán hôm nay")
        said = make("comment_sample", source_url="https://youtube.test/watch?v=off", native_source_id="off", sample_size=40)
        page = make("article", source_url="https://bao.test/tin", title="Sự cố mất điện")
        report = {
            "brief": {"topic": "Sự cố mất điện diện rộng", "keywords": ["mất điện"]},
            "similar_content": [{"video_id": "on", "title": on["title"], "evidence_id": on["id"]},
                                {"video_id": "off", "title": off["title"], "evidence_id": off["id"]}],
        }
        excluded = insight_engine.unusable_evidence(report, [on, off, said, page], "article")
        self.assertEqual(excluded, {off["id"]: insight_engine.LOW_RELEVANCE, said["id"]: insight_engine.LOW_RELEVANCE})
        validated = insight_engine.validate(
            {"insights": [_raw("k", "audience_question", "Người xem trong mẫu hỏi về cổ phiếu.", [said["id"]]),
                          _raw("f", "fact", "Mất điện xảy ra buổi sáng.", [page["id"]])],
             "angle_candidates": [_angle("a", "Theo câu hỏi về cổ phiếu", ["k"]), _angle("b", "Diễn biến sự cố", ["f"])],
             "limitations": []},
            [on, page], kind="article", excluded=excluded)
        self.assertEqual([item["statement"] for item in validated["insights"]], ["Mất điện xảy ra buổi sáng."])
        self.assertEqual(validated["rejected"][0]["reason"], insight_engine.LOW_RELEVANCE)
        self.assertEqual([item["statement"] for item in validated["angle_candidates"]], ["Diễn biến sự cố"])
        self.assertEqual([item["statement"] for item in validated["rejected_angles"]], ["Theo câu hỏi về cổ phiếu"])


class RelevanceOnTheStepTests(_ReasonCase):
    def _comment_calls(self) -> list[str]:
        return [call[1] for call in self.youtube.calls if call[0] == "commentThreads"]

    def test_an_article_is_not_made_to_use_videos_that_are_off_its_subject(self) -> None:
        project_id = _project(self.database, self.channel_id, kind="article", keywords=("mất điện", "sự cố"))

        def insights(prompt: str) -> dict:
            low = self.database.get_latest_research_report(project_id)["report"]["low_relevance"]["evidence_ids"]
            answer = article_insights(prompt)
            answer["insights"] += [
                _raw("crowd", "audience_question", "Người xem trong mẫu hỏi vì sao Trái Đất quay.", low[:2]),
                _raw("shape", "competitor_pattern", "Các video tương tự đặt tiêu đề dạng câu hỏi.", low[:3]),
            ]
            answer["angle_candidates"].append(_angle("a9", "Làm theo các video tương tự", ["crowd", "shape"]))
            return answer

        self.model.insights = insights
        result = self._ok(project_id, refresh_identity=False)
        body = self._stored(project_id)
        report, insight = body["research_report"]["report"], body["insight_report"]["report"]

        # The research report keeps what the search returned, marked, and takes nothing further from it.
        self.assertEqual({item["relevance"] for item in report["similar_content"]}, {"low"})
        self.assertEqual((report["low_relevance"]["videos"], report["low_relevance"]["of"]), (8, 8))
        self.assertNotIn("similar_videos", report["collected"])
        self.assertTrue(any("Không video nào tìm được thực sự liên quan" in item for item in report["limitations"]))
        self.assertEqual(self._comment_calls(), [], "no comments are read under a video that is off the subject")
        self.assertFalse([item for item in report["evidence"] if item["source_kind"] in {"comment_sample", "transcript"}])
        self.assertEqual(report["competitor_patterns"], [])

        # The model is not shown them...
        prompt = self.model.calls[0]["prompt"]
        self.assertNotIn("VIDEO TUONG TU DA LAY MAU", prompt)
        self.assertEqual(_ids(prompt, "video_meta"), [])
        # ...and an insight citing one is refused, with the angle built on it.
        self.assertEqual(sorted(insight["excluded_evidence"]["low_relevance"]), sorted(report["low_relevance"]["evidence_ids"]))
        refused = {item["statement"]: item["reason"] for item in insight["rejected"]}
        self.assertEqual(refused["Người xem trong mẫu hỏi vì sao Trái Đất quay."], insight_engine.LOW_RELEVANCE)
        self.assertEqual(refused["Các video tương tự đặt tiêu đề dạng câu hỏi."], insight_engine.LOW_RELEVANCE)
        self.assertFalse([item for item in insight["insights"] if item["type"] in {"audience_question", "competitor_pattern"}])
        self.assertIn("Làm theo các video tương tự", [item["statement"] for item in insight["rejected_angles"]])
        self.assertEqual([item["statement"] for item in insight["angle_candidates"]],
                         ["Điều đã chắc và điều còn tranh cãi", "Dòng thời gian của sự cố"])
        self.assertEqual(result["status"], "completed", "a plan without similar videos is still a plan")

    def test_a_video_reads_comments_only_under_the_similar_videos_that_are_on_its_subject(self) -> None:
        project_id = _project(self.database, self.channel_id)
        self._ok(project_id)
        report = self._stored(project_id)["research_report"]["report"]
        low = [item for item in report["similar_content"] if item["relevance"] == "low"]
        self.assertEqual(sorted(item["title"] for item in low), ["10 điều về Mặt Trăng", "Vũ trụ"])
        self.assertEqual(report["low_relevance"]["videos"], 2)
        self.assertFalse({item["video_id"] for item in low} & set(self._comment_calls()))
        prompt = self.model.calls[0]["prompt"]
        self.assertEqual(len(_ids(prompt, "video_meta")), 6)
        self.assertNotIn("Mặt Trăng", prompt)


class MissingAssetTests(unittest.TestCase):
    """The model proposes; what is missing is read off the project."""

    PROPOSED = [
        {"asset": "Cảnh quay gốc của video nguồn", "why": "Để cắt", "category": "source_footage", "required": True},
        {"asset": "Transcript của nguồn", "why": "", "category": "transcript", "required": True},
        {"asset": "Giọng đọc tiếng Việt mới", "why": "", "category": "generated", "required": True},
        {"asset": "Lời dẫn tiếng Việt mới sau khi duyệt kịch bản", "why": "", "category": "other", "required": True},
        {"asset": "Tài liệu khoa học đã kiểm chứng", "why": "", "category": "reference", "required": True},
        {"asset": "Cảnh quay thử nghiệm thật", "why": "Cần cho phần thử", "category": "user_footage", "required": True},
        {"asset": "Ảnh chụp bao bì", "why": "", "category": "user_images", "required": False},
    ]

    def test_an_asset_the_project_has_is_not_missing_whatever_the_model_says(self) -> None:
        assets = _assets(source_footage_seconds=62, source_audio_seconds=62)
        reviewed = plan_engine.review_assets(self.PROPOSED, assets)
        self.assertEqual([item["verdict"] for item in reviewed],
                         ["exists", "exists", "app_generates", "app_generates", "unverified", "missing", "missing"])
        self.assertIn("62 giây hình", reviewed[0]["note"])
        self.assertTrue(all(item["required_by_ai"] for item in reviewed[:6]))
        missing = plan_engine.missing_assets({"primary_sources": ["source_footage"], "supporting_sources": ["ai_media"]},
                                             reviewed, assets, settings=_settings(), kind="video")
        self.assertEqual([(item["category"], item["required"], item["source"]) for item in missing],
                         [("user_footage", True, "ai_confirmed"), ("user_images", False, "ai_confirmed")])
        # Once it is uploaded it is there, and no longer missing.
        uploaded = plan_engine.review_assets(self.PROPOSED, _assets(source_footage_seconds=62, project_assets={"video": 1, "image": 2}))
        self.assertEqual([item["verdict"] for item in uploaded][-2:], ["exists", "exists"])

    def test_a_proposal_filed_under_other_is_read_by_its_words(self) -> None:
        proposed = [{"asset": name, "why": "", "category": "other", "required": True} for name in (
            "Hình AI minh hoạ giọt nước", "Bộ cảnh quay thử nghiệm thật với đúng mẫu bàn chải", "Ảnh chụp bao bì sản phẩm",
            "Số liệu doanh thu của hãng")]
        reviewed = plan_engine.review_assets(proposed, _assets())
        self.assertEqual([(item["category"], item["verdict"]) for item in reviewed], [
            ("generated", "app_generates"), ("user_footage", "missing"), ("user_images", "missing"), ("other", "unverified")])

    def test_media_the_plan_builds_on_and_the_project_lacks_is_missing_by_rule(self) -> None:
        listing = _assets(source_kind="product", source_has_picture=False)
        missing = plan_engine.missing_assets({"primary_sources": ["product_images"], "supporting_sources": ["source_footage"]},
                                             [], listing, settings=_settings(), kind="product")
        self.assertEqual([(item["category"], item["required"], item["source"]) for item in missing],
                         [("source_footage", False, "rule"), ("product_images", True, "rule")])
        silent = _assets(has_transcript=False, has_dialogue=False, source_footage_seconds=62)
        retell = plan_engine.missing_assets({"primary_sources": ["source_footage"], "supporting_sources": []}, [], silent,
                                            settings=_settings(workflow="reup"), kind="video")
        self.assertEqual([(item["category"], item["required"]) for item in retell], [("transcript", True)])
        self.assertEqual(plan_engine.missing_assets({"primary_sources": ["ai_media"], "supporting_sources": []}, [],
                                                    _assets(), settings=_settings(), kind="video"), [])


class MissingAssetsOnTheStepTests(_ReasonCase):
    def _assets_of(self, project_id: int) -> tuple[dict, dict]:
        row = self._stored(project_id)["plan"]
        return row["plan"], row["feasibility"]

    def test_the_model_saying_an_existing_asset_is_missing_changes_nothing(self) -> None:
        self.model.plan = partial(plan_answer, proposed=MissingAssetTests.PROPOSED[:5])
        project_id = _project(self.database, self.channel_id)
        result = self._ok(project_id)
        plan, feasibility = self._assets_of(project_id)
        self.assertEqual(plan["missing_assets"], [])
        self.assertEqual([item["verdict"] for item in plan["ai_proposed_assets"]],
                         ["exists", "exists", "app_generates", "app_generates", "unverified"])
        self.assertEqual(_check(feasibility, "missing_assets")["status"], "ok")
        self.assertEqual((result["status"], feasibility["status"]), ("completed", "ok"))
        # What cannot be checked against the project stays a suggestion, said as one.
        self.assertTrue(any("không tự đối chiếu được" in item for item in plan["limitations"]))

    def test_an_asset_checked_against_the_project_and_absent_needs_a_decision(self) -> None:
        self.model.plan = partial(plan_answer, proposed=MissingAssetTests.PROPOSED[5:])
        project_id = _project(self.database, self.channel_id)
        result = self._ok(project_id)
        plan, feasibility = self._assets_of(project_id)
        self.assertEqual([(item["category"], item["required"], item["source"]) for item in plan["missing_assets"]],
                         [("user_footage", True, "ai_confirmed"), ("user_images", False, "ai_confirmed")])
        check = _check(feasibility, "missing_assets")
        self.assertEqual(check["status"], "needs_attention")
        self.assertIn("Cảnh quay thử nghiệm thật", check["detail"])
        self.assertNotIn("Ảnh chụp bao bì", check["detail"])
        self.assertEqual(result["status"], "needs_user_decision")


class ResourcesViewTests(_ReasonCase):
    """GET …/plan sorts the plan's resources into what a reader sees; no page works it out again."""

    def _resources(self, project_id: int) -> dict:
        return self._stored(project_id)["resources"]

    def test_before_any_plan_it_lists_what_the_project_has(self) -> None:
        project_id = _project(self.database, self.channel_id)
        view = self._resources(project_id)
        self.assertEqual([item["category"] for item in view["available"]], ["source_footage", "transcript", "source_audio"])
        self.assertIn("62 giây hình", view["available"][0]["detail"])
        self.assertEqual((view["app_generates"], view["missing"], view["proposed"], view["reviewed"]), ([], [], [], True))

    def test_a_plan_sorts_what_the_model_proposed_into_the_four_groups(self) -> None:
        self.model.plan = partial(plan_answer, proposed=MissingAssetTests.PROPOSED)
        project_id = _project(self.database, self.channel_id)
        self._ok(project_id)
        view = self._resources(project_id)
        self.assertEqual([item["category"] for item in view["available"]], ["source_footage", "transcript", "source_audio"])
        made = [item["label"] for item in view["app_generates"]]
        self.assertEqual(made[:6], ["Kịch bản", "Giọng đọc", "Phụ đề", "Hình AI", "Đồ hoạ", "Nhạc nền"])
        self.assertIn("Giọng đọc tiếng Việt mới", made, "what the model asked for and the app makes itself")
        self.assertEqual([(item["asset"], item["required"]) for item in view["missing"]],
                         [("Cảnh quay thử nghiệm thật", True), ("Ảnh chụp bao bì", False)])
        self.assertEqual([item["asset"] for item in view["proposed"]], ["Tài liệu khoa học đã kiểm chứng"])
        # An asset the project has is in neither list, whatever the model said.
        named = " ".join(item["asset"] for item in [*view["missing"], *view["proposed"]])
        self.assertNotIn("Cảnh quay gốc", named)
        self.assertNotIn("Transcript", named)
        self.assertTrue(view["reviewed"])

    def test_each_kind_of_source_has_what_it_has_and_no_more(self) -> None:
        listing = self._resources(_project(self.database, self.channel_id, kind="product"))
        self.assertEqual([item["category"] for item in listing["available"]], ["product_images"])
        self.assertIn("3 ảnh từ trang bán", listing["available"][0]["detail"])
        spoken = self._resources(_project(self.database, self.channel_id, kind="audio", seconds=120))
        self.assertEqual([item["category"] for item in spoken["available"]], ["transcript", "source_audio"])
        written = self._resources(_project(self.database, self.channel_id, kind="article"))
        self.assertEqual([item["category"] for item in written["available"]], ["source_images"])
        for view in (listing, spoken, written):
            self.assertNotIn("source_footage", [item["category"] for item in view["available"]])
        # A collection's pictures are its uploads: said once, as the source.
        pictures = plan_engine.resources(None, _assets(source_kind="image_collection", source_has_picture=False,
                                                       source_images=2, project_assets={"image": 2},
                                                       has_transcript=False, has_dialogue=False))
        self.assertEqual([item["category"] for item in pictures["available"]], ["source_images"])

    def test_a_plan_from_before_proposals_were_checked_shows_them_as_proposals(self) -> None:
        project_id = _project(self.database, self.channel_id)
        old = {"source_kind": "video", "content_structure": [{"name": "Mở đầu", "estimated_seconds": 60}],
               "media_strategy": {"primary_sources": ["ai_media"], "supporting_sources": []},
               "missing_assets": [{"asset": "Lời dẫn tiếng Việt mới", "why": "AI tự nêu", "required": True}]}
        self.database.create_project_plan(
            project_id, status="needs_attention", research_report_id=None, analysis_created_at=main._project_analysis_time(project_id),
            engine_version="plan-phase3", plan=old, feasibility={"status": "needs_attention", "checks": []},
        )
        view = self._resources(project_id)
        self.assertEqual(view["missing"], [], "a list the model wrote alone is not a list of what is missing")
        self.assertEqual([(item["asset"], item["required_by_ai"]) for item in view["proposed"]], [("Lời dẫn tiếng Việt mới", True)])
        self.assertFalse(view["reviewed"])


class StepStateTests(_ReasonCase):
    """ok/adjusted → completed; needs_attention → needs_user_decision; blocked; stale. Only completed is done."""

    def _state(self, project_id: int) -> tuple[dict, list[str]]:
        body = self.client.get(f"/api/projects/{project_id}/steps").json()
        return next(row for row in body["steps"] if row["key"] == "plan"), body["done"]

    def test_a_completed_plan_finishes_the_step(self) -> None:
        project_id = _project(self.database, self.channel_id)
        self._ok(project_id)
        row, done = self._state(project_id)
        self.assertEqual((row["state"], row["outcome"]["status"], row["outcome"]["completed"]), ("done", "completed", True))
        self.assertIn("plan", done)
        self.assertEqual(row["outcome"]["decisions"], [])

    def test_a_plan_waiting_on_a_decision_does_not_finish_the_step(self) -> None:
        self.model.plan = partial(plan_answer, seconds=(20, 60, 30), target=110)
        project_id = _project(self.database, self.channel_id)
        result = self._ok(project_id, settings={"target_duration_seconds": 60})
        row, done = self._state(project_id)
        self.assertEqual((result["status"], row["state"]), ("needs_user_decision", "needs_user_decision"))
        self.assertNotIn("plan", done)
        self.assertNotIn("plan", main._steps_done(project_id))
        outcome = row["outcome"]
        self.assertEqual((outcome["status"], outcome["completed"], outcome["feasibility"]), ("needs_user_decision", False, "needs_attention"))
        self.assertEqual([item["key"] for item in outcome["decisions"]], ["duration_budget"])
        self.assertTrue(outcome["decisions"][0]["options"])
        self.assertEqual(row["last_run"]["status"], "success", "the run itself worked; the plan is what waits")
        # Nothing was moved to make it pass: the target asked for and the structure written both stand.
        plan = self._stored(project_id)["plan"]["plan"]
        self.assertEqual((plan["target_duration_seconds"], sum(item["estimated_seconds"] for item in plan["content_structure"])), (60, 110))
        # The orchestrator's view of the project says the same.
        goal = next(item for item in main._goal_state(project_id)["steps"] if item["key"] == "plan")
        self.assertEqual(goal["state"], "needs_user_decision")

    def test_a_blocked_plan_does_not_finish_the_step(self) -> None:
        self.model.plan = partial(plan_answer, primary=("source_footage",), supporting=())
        project_id = _project(self.database, self.channel_id, kind="audio", seconds=120)
        self._ok(project_id, refresh_identity=False)
        row, done = self._state(project_id)
        self.assertEqual((row["state"], row["outcome"]["status"], row["missing"]), ("blocked", "blocked", []))
        self.assertNotIn("plan", done)
        self.assertIn("source_footage", [item["key"] for item in row["outcome"]["decisions"]])

    def test_a_stale_plan_does_not_finish_the_step(self) -> None:
        project_id = _project(self.database, self.channel_id)
        self._ok(project_id)
        old = self.database.get_latest_research_report(project_id)
        self.database.create_research_report(
            project_id, status="complete", source_kind="video", analysis_created_at=old["analysis_created_at"],
            engine_version=old["engine_version"], report=old["report"], captured_at=old["report"]["captured_at"],
        )
        row, done = self._state(project_id)
        self.assertEqual((row["state"], row["outcome"]["status"], row["outcome"]["completed"]), ("stale", "stale", False))
        self.assertIn("Có báo cáo nghiên cứu mới hơn", row["outcome"]["reason"])
        self.assertNotIn("plan", done)

    def test_plans_saved_under_the_old_names_mean_what_they_meant(self) -> None:
        project_id = _project(self.database, self.channel_id)
        analysis_at = main._project_analysis_time(project_id)
        for stored, now, finished in (("ready", "completed", True), ("needs_attention", "needs_user_decision", False)):
            self.database.create_project_plan(
                project_id, status=stored, research_report_id=None, analysis_created_at=analysis_at,
                engine_version="plan-phase3", plan={}, feasibility={"status": "ok" if finished else "needs_attention", "checks": []},
            )
            plan = self._stored(project_id)["plan"]
            self.assertEqual((plan["status"], plan["effective_status"]), (now, now), stored)
            self.assertEqual("plan" in main._steps_done(project_id), finished, stored)


class PrimaryAngleTests(_ReasonCase):
    """Choosing another angle is a light re-plan: stored research, stored insights, one model call."""

    def _planned(self) -> tuple[int, dict]:
        project_id = _project(self.database, self.channel_id)
        first = self._ok(project_id)
        self.assertEqual((first["primary_angle_id"], first["primary_angle_from"]), ("ang-1", "ai"))
        self.model.calls.clear()
        return project_id, first

    def test_choosing_an_angle_replans_without_research_and_without_the_insight_call(self) -> None:
        project_id, first = self._planned()
        before = self._network()
        with mock.patch.object(main.source_identity, "refresh", side_effect=AssertionError("identity lookup")):
            again = self._ok(project_id, primary_angle_id="ang-2")
        self.assertEqual(self._network(), before, "no research")
        self.assertEqual(self.model.kinds(), ["plan"], "the insights are reused: one model call")
        self.assertEqual((again["mode"], again["research_reused"], again["insight_reused"], again["ai"]["calls"]), ("replan", True, True, 1))
        self.assertEqual((again["research_report_id"], again["insight_report_id"]),
                         (first["research_report_id"], first["insight_report_id"]))
        self.assertEqual((again["primary_angle_id"], again["primary_angle_from"]), ("ang-2", "user"))
        self.assertIn("GOC DA DUOC NGUOI DUNG CHON: [ang-2]", self.model.calls[0]["prompt"])
        body = self._stored(project_id)
        plan_row, plan = body["plan"], body["plan"]["plan"]
        self.assertEqual(plan["primary_angle"]["statement"], "Đặt lại chủ đề thành một câu hỏi")
        self.assertEqual([item["id"] for item in plan["alternative_angles"]], ["ang-1"])
        self.assertEqual(plan["requested"], {"primary_angle_id": "ang-2"})
        self.assertEqual(plan_row["version"], first["plan_version"] + 1)
        # The evidence and the insights are the ones already stored, untouched.
        self.assertEqual(self.database.get_latest_insight_report(project_id)["id"], first["insight_report_id"])
        self.assertEqual(self.database.get_latest_research_report(project_id)["id"], first["research_report_id"])
        # Feasibility ran again on the new plan.
        self.assertEqual(plan_row["feasibility"]["status"], "ok")
        self.assertTrue(plan_row["feasibility"]["checks"])
        self.assertFalse(plan_row["stale"])

    def test_a_plan_written_for_another_angle_is_sent_back(self) -> None:
        project_id, first = self._planned()
        self.model.plan = in_turn(partial(plan_answer, angle="ang-1"), plan_answer)
        again = self._ok(project_id, primary_angle_id="ang-2")
        self.assertEqual(self.model.kinds(), ["plan", "plan"])
        self.assertIn("người dùng đã chọn góc này", self.model.calls[1]["prompt"])
        self.assertEqual(again["primary_angle_id"], "ang-2")
        # A model that will not plan for it fails cleanly; the plan before stays.
        self.model.plan = partial(plan_answer, angle="ang-2")
        refused = self._post(project_id, primary_angle_id="ang-1")
        self.assertEqual(refused.status_code, 502)
        self.assertEqual(self._stored(project_id)["plan"]["version"], again["plan_version"])

    def test_the_choice_and_the_settings_stay_until_they_are_changed(self) -> None:
        project_id, _ = self._planned()
        self._ok(project_id, primary_angle_id="ang-2")
        sized = self._ok(project_id, mode="replan", settings={"output_profile": "tiktok", "target_duration_seconds": 45})
        self.assertEqual((sized["primary_angle_id"], sized["primary_angle_from"], sized["target_duration_seconds"]), ("ang-2", "user", 45))
        back = self._ok(project_id, primary_angle_id="ang-1")
        plan = self._stored(project_id)["plan"]["plan"]
        self.assertEqual((back["primary_angle_id"], plan["platform"], plan["target_duration_seconds"]), ("ang-1", "tiktok", 45))
        self.assertEqual(plan["requested"], {"output_profile": "tiktok", "target_duration_seconds": 45, "primary_angle_id": "ang-1"})
        # Giving it as null hands the choice back to the model; the rest stays.
        free = self._ok(project_id, mode="replan", primary_angle_id=None)
        self.assertEqual((free["primary_angle_from"], free["target_duration_seconds"]), ("ai", 45))
        self.assertNotIn("primary_angle_id", free["requested"])

    def test_an_angle_that_is_not_a_candidate_is_refused(self) -> None:
        project_id, first = self._planned()
        response = self._post(project_id, primary_angle_id="ang-9")
        self.assertEqual(response.status_code, 400)
        self.assertIn("ang-1, ang-2", response.json()["detail"])
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self._stored(project_id)["plan"]["version"], first["plan_version"])

    def test_an_angle_is_chosen_only_among_insights_that_still_stand(self) -> None:
        project_id, first = self._planned()
        for mode in ("auto", "full", "reason"):
            response = self._post(project_id, mode=mode, primary_angle_id="ang-2")
            self.assertEqual(response.status_code, 400, mode)
            self.assertIn("mode=replan", response.json()["detail"])
        old = self.database.get_latest_research_report(project_id)
        self.database.create_research_report(
            project_id, status="complete", source_kind="video", analysis_created_at=old["analysis_created_at"],
            engine_version=old["engine_version"], report=old["report"], captured_at=old["report"]["captured_at"],
        )
        stale = self._post(project_id, primary_angle_id="ang-2")
        self.assertEqual(stale.status_code, 409)
        self.assertIn("mode=reason", stale.json()["detail"])
        self.assertEqual(self.model.calls, [])

    def test_new_insights_drop_the_old_choice_but_keep_the_settings(self) -> None:
        project_id, first = self._planned()
        self._ok(project_id, primary_angle_id="ang-2", settings={"target_duration_seconds": 45})
        again = self._ok(project_id, mode="reason")
        self.assertNotEqual(again["insight_report_id"], first["insight_report_id"])
        self.assertEqual((again["primary_angle_from"], again["target_duration_seconds"]), ("ai", 45))
        self.assertEqual(again["requested"], {"target_duration_seconds": 45})


def _capture(errors: list, function, *args) -> None:
    try:
        function(*args)
    except HTTPException as exc:
        errors.append(exc)


if __name__ == "__main__":
    unittest.main()
