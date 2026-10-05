"""What the Bước 3 tests share: a project planned to a given state, and a model that answers from the prompt.

A project gets a source analysis, a ResearchReport, an InsightReport and a
plan in whatever state a test needs - written straight into the database the
test uses, never the real one. The fake model reads the plan's sections,
budgets, angle and speaking rate back out of the prompt and answers with
exactly enough words for each.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from youtube_monitor import script_engine

NOW = datetime.now(timezone.utc)
READ_AT = (NOW - timedelta(hours=1)).isoformat()
EV = "ev-aaaaaaaaaa"
FIXTURE_78 = json.loads((Path(__file__).parent / "fixtures" / "project78_plan_v5.json").read_text(encoding="utf-8"))

ANGLE = {"id": "ang-2", "statement": "Trả lời câu hỏi vì sao Trái Đất quay", "target_audience": "Người mới tìm hiểu",
         "need_or_problem": "Muốn câu trả lời ngắn", "differentiation": "Trả lời thẳng", "platform_fit": "Hợp video ngang",
         "supporting_insight_ids": ["in-1"], "risks": []}
PLAN = {
    "source_kind": "video", "video_type": "giải thích nhanh", "platform": "youtube", "aspect_ratio": "16:9",
    "output_profile": "youtube_landscape", "language": "vi", "target_duration_seconds": 60, "target_duration_from": "project",
    "target_audience": "Người mới tìm hiểu", "goal": "Giải thích rõ một câu hỏi",
    "primary_angle_id": "ang-2", "primary_angle": ANGLE, "primary_angle_from": "user",
    "alternative_angles": [{**ANGLE, "id": "ang-1", "statement": "Lịch sử của Trái Đất"}],
    "hook_strategy": "Mở bằng câu người xem hay hỏi",
    "content_structure": [
        {"name": "Mở đầu", "purpose": "Giữ người xem", "estimated_seconds": 10, "key_points": ["Nêu câu hỏi"],
         "insight_ids": ["in-1"], "evidence_ids": [EV]},
        {"name": "Thân bài", "purpose": "Trả lời", "estimated_seconds": 40, "key_points": ["Giải thích"], "insight_ids": [], "evidence_ids": []},
        {"name": "Kết", "purpose": "Chốt lại", "estimated_seconds": 10, "key_points": [], "insight_ids": [], "evidence_ids": []},
    ],
    "cta": "Mời xem phần tiếp theo",
    "factual_guardrails": ["Mới có một nguồn đưa, phải nêu rõ nguồn khi nói: Trái Đất tự quay quanh trục của nó."],
    "claims_to_avoid": ["Chưa có bằng chứng, không nói như sự thật: Mọi khán giả đều thích video ngắn về vũ trụ hơn video dài."],
    "claims_needing_proof": [],
    "constraints": {"script_mode": "new_angle_same_topic", "scene_asset_type": "ai_scene", "workflow": "content", "must_not_invent": []},
}
INSIGHT = {
    "insights": [{"id": "in-1", "type": "audience_question", "statement": "Người xem trong mẫu hỏi vì sao Trái Đất quay.",
                  "evidence_ids": [EV], "confidence": "medium"}],
    "hypotheses": [{"statement": "Người xem lớn tuổi thường bỏ video giữa chừng khi nghe thuật ngữ khoa học."}],
    "angle_candidates": [ANGLE],
    "evidence_index": {EV: {"source_kind": "comment_sample", "title": "Video A", "source_url": "https://youtube.test/a", "sample_size": 40}},
}
STRUCTURE_78 = [(item["name"], item["estimated_seconds"]) for item in FIXTURE_78["plan"]["content_structure"]]


# ---------------------------------------------------------------------------
# A project with an analysis, research, insights and a plan in a given state
# ---------------------------------------------------------------------------

def planned_project(database, *, kind: str = "video", plan: dict | None = None, insight: dict | None = None, status: str = "completed",
             analysis: dict | None = None, facts: dict | None = None, with_plan: bool = True, earlier_plans: list[dict] | None = None,
             title: str = "Vì sao Trái Đất quay?") -> int:
    video_id = f"{'web' if kind in {'article', 'product'} else 'n'}-{uuid.uuid4().hex[:12]}"
    group = f"UC{uuid.uuid4().hex[:22]}"
    database.upsert_channel({"youtube_channel_id": group, "channel_url": "https://x"})
    database.upsert_video({"youtube_video_id": video_id, "youtube_channel_id": group, "title": title,
                           "video_url": f"https://nguon.test/{video_id}", "metadata_hash": video_id, "duration_seconds": 62,
                           "source_kind": kind, "raw_payload": {"source": "test"}})
    result = analysis or {"topic": title, "content_summary": "Trái Đất tự quay quanh trục nên có ngày và đêm.",
                          "scene_map": [{"what_happens": "Mở đầu bằng câu hỏi"}], "source_type": kind, "language": "vi",
                          "limitations": []}
    if facts is not None:
        result = {**result, "source_facts": facts}
    database.save_video_analysis(video_id, result, analysis_type="reference", provider="test")
    project_id = int(database.create_production_project(video_id, title=title)["id"])
    if not with_plan:
        return project_id
    analysed = database.get_video_analysis(video_id, analysis_type="reference")["created_at"]
    report = database.create_research_report(
        project_id, status="complete", source_kind=kind, analysis_created_at=analysed, engine_version="test",
        report={"evidence": [{"id": EV, "source_kind": "comment_sample", "title": "Video A", "excerpt": "", "metrics": {}}],
                "brief": {"language": "vi", "volatility_assumed": "evergreen"}, "collected": ["similar_videos"],
                "captured_at": NOW.isoformat(), "limitations": []},
        captured_at=NOW.isoformat())
    insight_row = database.create_insight_report(
        project_id, status="complete", research_report_id=report["id"], analysis_created_at=analysed, source_kind=kind,
        engine_version="test", report=insight or INSIGHT)
    for earlier in earlier_plans or []:
        database.create_project_plan(project_id, status="completed", research_report_id=report["id"], analysis_created_at=analysed,
                                     engine_version="plan-phase3", plan=earlier, feasibility={"status": "ok", "checks": []},
                                     insight_report_id=insight_row["id"])
    feasibility = {"completed": "ok", "needs_user_decision": "needs_attention", "blocked": "blocked"}.get(status, "ok")
    database.create_project_plan(project_id, status=status, research_report_id=report["id"], analysis_created_at=analysed,
                                 engine_version="plan-phase3", plan=plan or {**PLAN, "source_kind": kind},
                                 feasibility={"status": feasibility, "checks": []}, insight_report_id=insight_row["id"])
    return project_id


# ---------------------------------------------------------------------------
# What a model would answer, from the prompt it is given
# ---------------------------------------------------------------------------

_WORDS = "phần này nói rõ từng ý chính để mọi bạn dễ hiểu và nhớ lâu hơn khi theo dõi".split()


def said(tokens: int) -> list[dict]:
    """Lines of plain speech with exactly `tokens` words, in sentences of up to twelve."""
    lines, left, at = [], max(1, tokens), 0
    while left > 0:
        size = min(12, left)
        words = [_WORDS[(at + index) % len(_WORDS)] for index in range(size)]
        lines.append({"speaker": "narrator", "text": " ".join(words).capitalize() + "."})
        left -= size
        at += size
    return lines


HOOK_SECONDS, CTA_SECONDS = 4, 4


def script_answer(prompt: str, *, angle: str = "", scale: float = 1.0, order: list[str] | None = None, edit=None) -> dict:
    sections = re.findall(r"- \[(s\d+)\] .*? — (\d+) giay", prompt)
    rate = float(re.search(r"Toc do doc: khoang ([\d.]+) ", prompt).group(1))
    chosen = angle or re.search(r"GOC NOI DUNG DA CHON \[([\w-]+)\]", prompt).group(1)
    body = []
    for index, (section_id, seconds) in enumerate(sections):
        own = int(seconds) - (HOOK_SECONDS if index == 0 else 0) - (CTA_SECONDS if index == len(sections) - 1 else 0)
        body.append({"plan_section_id": section_id, "spoken_lines": said(round(own * rate * scale)), "on_screen_text": [],
                     "insight_ids": [], "evidence_ids": []})
    if order is not None:
        body = [next(item for item in body if item["plan_section_id"] == wanted) if wanted in {s for s, _ in sections}
                else {**body[0], "plan_section_id": wanted} for wanted in order]
    answer = {"title": "Vì sao Trái Đất quay", "angle_id": chosen, "tone": "rõ ràng, gần gũi",
              "hook": {"spoken_lines": said(round(HOOK_SECONDS * rate * scale)), "on_screen_text": []}, "sections": body,
              "cta": {"spoken_lines": said(round(CTA_SECONDS * rate * scale)), "on_screen_text": []},
              "missing_information": [], "limitations": []}
    if edit:
        edit(answer)
    return answer


def in_turn(*answers):
    queue = list(answers)

    def answer(prompt: str):
        current = queue.pop(0) if len(queue) > 1 else queue[0]
        return current(prompt) if callable(current) else current

    return answer


class Scripted:
    """Stands in for the orchestrator's model call, and keeps what it was asked."""

    def __init__(self, answer=script_answer) -> None:
        self.answer = answer
        self.calls: list[dict] = []

    def __call__(self, system: str, user: str, schema: dict, **options):
        self.calls.append({"system": system, "prompt": user, "stage": options.get("stage"), "step": options.get("step")})
        if options.get("report") is not None:
            options["report"].update(runtime="fake_cli", attempts=[{"runtime": "fake_cli", "status": "success"}])
        return self.answer(user)


# ---------------------------------------------------------------------------
# A script written from the plan, as Bước 3 would write it
# ---------------------------------------------------------------------------

def write_current_script(database, project_id: int, answer=script_answer) -> dict:
    """The project's script, written by the Script Engine from its current plan with the fake model."""
    from youtube_monitor import project_planner

    project = database.get_production_project(project_id)
    video = database.get_video(project["youtube_video_id"]) or {}
    analysis = database.get_video_analysis(project["youtube_video_id"], analysis_type="reference")
    plan = project_planner.current_plan(database, project_id, str(analysis.get("created_at") or ""))

    def reasoner(system: str, prompt: str, schema: dict, label: str):
        return answer(prompt), {"runtime": "fake_cli"}

    return script_engine.run(database, project, video, analysis, plan, reasoner=reasoner)["script"]


def plan_project(database, project_id: int, *, plan: dict | None = None, status: str = "completed") -> dict:
    """A completed plan (with its research and insights) for a project that already has a source analysis."""
    project = database.get_production_project(project_id)
    analysed = database.get_video_analysis(project["youtube_video_id"], analysis_type="reference")["created_at"]
    report = database.create_research_report(
        project_id, status="complete", source_kind="video", analysis_created_at=analysed, engine_version="test",
        report={"evidence": [{"id": EV, "source_kind": "comment_sample", "title": "Video A", "excerpt": "", "metrics": {}}],
                "brief": {"language": "vi"}, "collected": [], "captured_at": NOW.isoformat(), "limitations": []},
        captured_at=NOW.isoformat())
    insight_row = database.create_insight_report(
        project_id, status="complete", research_report_id=report["id"], analysis_created_at=analysed, source_kind="video",
        engine_version="test", report=INSIGHT)
    feasibility = {"completed": "ok", "needs_user_decision": "needs_attention", "blocked": "blocked"}.get(status, "ok")
    return database.create_project_plan(project_id, status=status, research_report_id=report["id"], analysis_created_at=analysed,
                                        engine_version="plan-phase3", plan=plan or PLAN,
                                        feasibility={"status": feasibility, "checks": []}, insight_report_id=insight_row["id"])
