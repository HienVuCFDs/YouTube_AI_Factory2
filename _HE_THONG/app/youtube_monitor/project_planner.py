"""Bước 2 · Kế hoạch: the plan step, start to finish.

    AnalysisResult → ResearchReport → InsightReport → ProjectPlan → Feasibility

Research (Phase 1-2, no model): the research brief from the analysis, what
the knowledge stores already hold, the collectors, and a ResearchReport of
evidence. Reasoning (Phase 3, two model calls): insight_engine reads the
report and says what it means; plan_engine turns that into a plan and checks
by rule whether it can be made. Each artefact is versioned and names the one
it was built from, so a plan goes stale when anything under it changes, and
a change of settings alone re-plans from the stored research and insights
without fetching anything.

It reads nothing from the old research paths - `run_step("research")`'s
director artifact, the five-role pipeline's Research Agent, the folklore
lookup - so the plan does not inherit their unsourced output.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from math import gcd
from typing import Any, Callable

from . import freshness, insight_engine, plan_engine, research_collectors, research_evidence, source_kinds, workflows
from .knowledge_store import AudienceObservations, ChannelIntelligence, ContentPatterns, TopicIntelligence, slug
from .shorts import OUTPUT_PROFILE_SIZES

ENGINE_VERSION = "plan-phase2"

PLAN_FIELDS = (
    "video_type", "platform", "output_profile", "aspect_ratio", "target_duration_seconds",
    "target_audience", "goal", "primary_angle", "hook_strategy", "content_structure",
    "media_strategy", "edit_direction", "subtitle_style", "music_strategy", "sfx_strategy",
    "cta", "missing_assets", "constraints",
)
# Fields a plan can only fill from research and a model; left empty until then.
RESEARCH_FIELDS = (
    "video_type", "target_duration_seconds", "target_audience", "goal", "primary_angle",
    "hook_strategy", "content_structure", "media_strategy", "edit_direction",
    "subtitle_style", "music_strategy", "sfx_strategy", "cta",
)

PENDING_COLLECTORS = {
    "video": [
        "source_channel_profile", "similar_videos", "source_comments", "similar_video_comments",
        "hooks_structure_pacing", "topic_research",
    ],
    "article": [
        "event_origin", "official_sources", "other_articles", "latest_updates",
        "timeline", "disputed_or_unconfirmed", "community_reaction",
    ],
    "product": [
        "official_specs", "current_offer", "reviews", "review_videos", "review_comments",
        "pain_points_faq", "competitors_alternatives",
    ],
    "images": ["topic_research_if_needed"],
    "idea": ["topic_research", "similar_videos"],
}
# The pace a topic changes at, assumed from the kind of source until research
# can say better. It decides how long topic knowledge stays usable.
ASSUMED_VOLATILITY = {"article": "news", "product": "tech"}

PROFILE_PLATFORM = {
    "youtube_landscape": "youtube", "youtube_shorts": "youtube", "tiktok": "tiktok",
    "instagram_reels": "instagram", "facebook_reels": "facebook", "facebook_feed": "facebook",
}


def _aspect(profile: str) -> str:
    width, height = OUTPUT_PROFILE_SIZES.get(profile, (1920, 1080))
    divisor = gcd(width, height) or 1
    return f"{width // divisor}:{height // divisor}"


# What each kind is researched as, in PENDING_COLLECTORS' terms: spoken audio
# like a video's content, a web page like an article.
_RESEARCH_KIND = {"audio": "video", "web": "article", "image": "images", "image_collection": "images"}


def source_kind(result: dict[str, Any], identity: dict[str, Any], stored: str = "") -> str:
    """What to research from: the kind the analysis read, else the row's source_kind.

    The platform is only read for a row from before source_kind existed.
    """
    analysed = str(result.get("source_kind") or result.get("source_type") or "").strip().lower()
    on_row = source_kinds.ANALYSIS_KIND.get(str(stored or "").strip().lower(), "")
    for kind in (analysed, on_row):
        kind = _RESEARCH_KIND.get(kind, kind)
        if kind in PENDING_COLLECTORS:
            return kind
    if identity.get("platform") == "shop":
        return "product"
    if identity.get("platform") == "web":
        return "article"
    if identity.get("platform") == "idea":
        return "idea"
    return "video"


def _texts(values: Any, limit: int, size: int = 120) -> list[str]:
    found: list[str] = []
    for item in values or []:
        text = item.get("keyword") if isinstance(item, dict) else item
        text = " ".join(str(text or "").split())
        if text and text not in found:
            found.append(text[:size])
        if len(found) >= limit:
            break
    return found


_LANGUAGE_NAMES = {"tiếng việt": "vi", "tieng viet": "vi", "vietnamese": "vi", "tiếng anh": "en", "english": "en"}


def language_code(value: Any) -> str:
    """The two-letter code of a language however the analysis wrote it ("vi", "vi-VN", "Tiếng Việt (vi)").

    It is sent to search APIs as it stands, and one that is not a code is refused there.
    """
    text = str(value or "").strip().lower()
    if re.fullmatch(r"[a-z]{2}([-_][a-z0-9]{2,4})?", text):
        return text[:2]
    bracketed = re.search(r"\(([a-z]{2})(?:[-_][a-z0-9]{2,4})?\)", text)
    if bracketed:
        return bracketed.group(1)
    return next((code for name, code in _LANGUAGE_NAMES.items() if name in text), "vi")


def research_brief(
    video: dict[str, Any], analysis: dict[str, Any], identity: dict[str, Any],
) -> dict[str, Any]:
    """2.1 - what to find out, from the analysis alone. No model, no network."""
    result = dict(analysis.get("result") or {})
    kind = source_kind(result, identity, str(video.get("source_kind") or ""))
    facts = dict(result.get("source_facts") or {})
    topic = " ".join(str(result.get("topic") or video.get("title") or "").split())[:200]
    entities = _texts([item.get("name") for item in result.get("characters") or [] if isinstance(item, dict)], 12)
    if facts.get("name"):
        entities.insert(0, str(facts["name"])[:120])
    brief = {
        "source_kind": kind,
        "topic": topic,
        "topic_key": slug(topic),
        "language": language_code(result.get("language")),
        "volatility_assumed": ASSUMED_VOLATILITY.get(kind, "evergreen"),
        "keywords": _texts(result.get("keywords"), 15),
        "entities": entities,
        # What the analysis could not settle becomes a question for research,
        # not a gap for the writer to fill.
        # A whole sentence each: a question cut mid-word is no use to whoever reads it.
        "questions": _texts(result.get("limitations"), 12, 300),
        "source": {
            "title": str(video.get("title") or "")[:300],
            "url": str(video.get("video_url") or ""),
            "platform": identity.get("platform"),
            "native_video_id": identity.get("native_video_id"),
            "native_channel_id": identity.get("native_channel_id"),
            "channel_name": identity.get("channel_name"),
            "channel_identity": identity.get("channel_identity"),
        },
        "collectors": PENDING_COLLECTORS.get(kind, []),
    }
    if kind == "product":
        brief["product"] = {
            "name": str(facts.get("name") or "")[:200],
            "price": str(facts.get("price") or ""),
            "price_captured_at": facts.get("captured_at"),
        }
    return brief


def knowledge_status(database: Any, brief: dict[str, Any], identity: dict[str, Any], video: dict[str, Any]) -> dict[str, Any]:
    """2.2 - what the stores already hold, and whether it can be reused."""
    status: dict[str, Any] = {}
    channel_id = identity.get("native_channel_id") or ""
    if identity.get("channel_identity") == "native" and channel_id:
        profile = ChannelIntelligence(database).get(identity["platform"], channel_id)
        status["channel"] = {
            "state": profile["freshness"]["profile"]["state"] if profile else freshness.MISSING,
            "performance": profile["freshness"]["performance"]["state"] if profile else freshness.MISSING,
            "version": (profile or {}).get("version"),
            "native_channel_id": channel_id,
        }
        status["patterns"] = {"channel": len(ContentPatterns(database).list("channel", f"{identity['platform']}:{channel_id}"))}
    else:
        status["channel"] = {
            "state": "unavailable",
            "reason": (
                "Nguồn không thuộc một kênh" if identity.get("channel_identity") == "none"
                else "Chưa biết mã kênh gốc của nguồn này"
            ),
        }
    topic = TopicIntelligence(database).get(brief["topic_key"], brief["language"]) if brief["topic_key"] else None
    status["topic"] = {
        "state": topic["freshness"]["state"] if topic else freshness.MISSING,
        "volatility": (topic or {}).get("volatility") or brief["volatility_assumed"],
        "facts": len((topic or {}).get("facts") or []),
    }
    scope_key = video_scope_key(identity, video)
    audience = AudienceObservations(database).summary("video", scope_key, video_published_at=video.get("published_at"))
    status["audience"] = {
        "state": audience["freshness"]["state"],
        "observations": audience["observations"],
        "total_sample": audience["total_sample"],
        "scope_key": scope_key,
    }
    if brief["source_kind"] == "product":
        status["product_price"] = freshness.product_price((brief.get("product") or {}).get("price_captured_at"))["state"]
    return status


def video_scope_key(identity: dict[str, Any], video: dict[str, Any]) -> str:
    """The key audience samples of this source are filed under."""
    if identity.get("native_video_id"):
        return f"{identity['platform']}:{identity['native_video_id']}"
    return f"row:{video.get('youtube_video_id')}"


def source_unread(brief: dict[str, Any], analysis: dict[str, Any]) -> tuple[str, str]:
    """(status, why) when the source's own page was never read; ("", "") when it was.

    A listing behind a sign-in or a verification is analysed from its link
    alone. That analysis exists, but the page is not evidence of anything.
    """
    if brief["source_kind"] != "product":
        return "", ""
    facts = (analysis.get("result") or {}).get("source_facts") or {}
    status = str(facts.get("read_status") or "")
    if not status or status == "OK":
        return "", ""
    refused = status in {"NEED_LOGIN", "NEED_HUMAN_VERIFY"}
    why = "trang đòi đăng nhập hoặc xác minh" if refused else "trang không đọc được"
    return (research_collectors.BLOCKED if refused else research_collectors.FAILED), f"Chưa đọc được trang sản phẩm: {why}."


def source_evidence(video: dict[str, Any], identity: dict[str, Any], brief: dict[str, Any], analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """The one piece of evidence every plan has: the source that was analysed - when it was read."""
    if source_unread(brief, analysis)[0]:
        return []
    kind = {"product": "product_page", "article": "article"}.get(brief["source_kind"], "source")
    known = dict(identity.get("metrics") or {})
    if brief["source_kind"] == "product":
        facts = (analysis.get("result") or {}).get("source_facts") or {}
        metrics = {
            "price": facts.get("price"), "original_price": facts.get("original_price"),
            "rating": facts.get("rating"), "sold_count": facts.get("sold_count"),
        }
    elif brief["source_kind"] in {"article", "images", "idea"}:
        metrics = {"published_at": known.get("published_at")}
    else:
        metrics = {
            "view_count": known.get("view_count"), "like_count": known.get("like_count"),
            "comment_count": known.get("comment_count"), "published_at": known.get("published_at"),
            "duration_seconds": known.get("duration_seconds"), "metrics_source": known.get("source"),
        }
    # Only what was actually read; an empty figure is not a zero.
    metrics = {key: value for key, value in metrics.items() if value not in (None, "")}
    captured = (
        (brief.get("product") or {}).get("price_captured_at")
        or (identity.get("metrics") or {}).get("captured_at")
        or analysis.get("created_at")
    )
    url = str(video.get("video_url") or "")
    if not url:
        return []
    native_id = identity.get("native_video_id") or ""
    if brief["source_kind"] == "product":
        native_id = str(((analysis.get("result") or {}).get("source_facts") or {}).get("product_id") or native_id)
    return [research_evidence.make_evidence(
        kind, source_url=url, collector="planner.source", collector_version=ENGINE_VERSION,
        native_source_id=native_id, title=str(video.get("title") or ""), platform=str(identity.get("platform") or ""),
        metrics=metrics, captured_at=str(captured) if captured else None,
    )]


def draft_plan(
    brief: dict[str, Any], project: dict[str, Any], render_settings: dict[str, Any], video: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """2.7 - only what already follows from the project's own settings."""
    profile = str(render_settings.get("output_profile") or "youtube_landscape")
    workflow = workflows.get(project.get("workflow"))
    plan: dict[str, Any] = {field: None for field in PLAN_FIELDS}
    plan.update({
        "platform": PROFILE_PLATFORM.get(profile, "youtube"),
        "output_profile": profile,
        "aspect_ratio": _aspect(profile),
        "missing_assets": [],
        "constraints": {
            "script_mode": workflow.script_mode,
            "scene_asset_type": workflow.scene_asset_type,
            "language": str(render_settings.get("publish_language") or brief["language"] or "vi"),
            "source_duration_seconds": int(video.get("duration_seconds") or 0) or None,
            # What the analysis could not settle must not be filled in by the
            # script either.
            "must_not_invent": brief["questions"],
        },
        "pending_fields": list(RESEARCH_FIELDS),
        "decided_from": {
            "platform": "project_render_settings.output_profile",
            "aspect_ratio": "project_render_settings.output_profile",
            "constraints.script_mode": f"workflow:{workflow.key}",
        },
    })
    if brief["source_kind"] == "product" and not (brief.get("product") or {}).get("price"):
        plan["constraints"]["no_price_claims"] = True
    feasibility = {
        "status": "not_checked",
        "reason": "Chưa kiểm tra khả thi: kế hoạch chưa có thời lượng và chiến lược media (Phase 1).",
        "checks": [],
    }
    return plan, feasibility


def research(
    database: Any,
    project: dict[str, Any],
    video: dict[str, Any],
    analysis: dict[str, Any],
    *,
    identify: Callable[[], dict[str, Any]],
    channel_service: Any = None,
    collectors: Any = None,
    quota_used: Callable[[], int] | None = None,
) -> dict[str, Any]:
    """Research the source and save a ResearchReport. No model is asked anything.

    AnalysisResult → research brief → knowledge reuse → collectors →
    ResearchReport. The source's channel goes through the one
    ChannelResearchService the channel manager also uses; nothing here
    researches a channel itself. Insights at this stage are counts, each
    citing its evidence. A collector that fails is recorded and the rest go
    on; the report is `failed` only when nothing was collected.
    """
    units_before = quota_used() if quota_used else None
    identity = identify()
    brief = research_brief(video, analysis, identity)
    evidence = source_evidence(video, identity, brief, analysis)
    limitations: list[str] = []
    failed_sources: list[dict[str, Any]] = []
    unread_status, unread_why = source_unread(brief, analysis)
    if unread_status:
        failed_sources.append(research_collectors.failure(
            "planner.source", str(video.get("video_url") or ""), unread_why, unread_status))
        limitations.append(f"{unread_why} Trang này không được dùng làm bằng chứng.")
    risks = [{"item": question, "why": "Bước phân tích không xác định được", "evidence_ids": []} for question in brief["questions"]]
    if identity.get("refresh_error"):
        risks.append({"item": "Chưa tra được mã kênh gốc", "why": identity["refresh_error"][:300], "evidence_ids": []})

    source_channel: dict[str, Any] = {
        "platform": identity.get("platform"),
        "native_channel_id": identity.get("native_channel_id"),
        "channel_name": identity.get("channel_name"),
        "channel_identity": identity.get("channel_identity"),
        "status": "not_researched",
    }
    project_id = int(project["id"])
    similar: list[dict[str, Any]] = []
    raw_insights: dict[str, list[dict[str, Any]]] = {}
    timeline: list[dict[str, Any]] = []
    collected: list[str] = []
    reuse: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    kind = brief["source_kind"]
    stored_kind = source_kinds.valid(video.get("source_kind"))

    def safe(name: str, call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """One collector; whatever it raises becomes a recorded failure."""
        try:
            result = call()
        except Exception as exc:  # a collector must never take the plan down
            failed_sources.append(research_collectors.failure(
                name, "", f"{type(exc).__name__}: {str(exc)[:200]}",
                research_collectors.BLOCKED if research_collectors.refused(exc) else research_collectors.FAILED))
            return {}
        evidence.extend(result.get("evidence") or [])
        limitations.extend(result.get("limitations") or [])
        failed_sources.extend(result.get("failed") or [])
        return result

    if collectors is not None:
        # The source's own channel: the shared Channel Intelligence engine.
        if channel_service is not None and identity.get("channel_identity") == "native":
            from .channel_research import ChannelResearchError

            ref = f"{identity['platform']}:{identity['native_channel_id']}"
            try:
                outcome = channel_service.ensure(channel_service.resolve(ref))
                source_channel.update({
                    "profile_ref": outcome["profile_ref"], "status": outcome["status"],
                    "profile_version": outcome["profile_version"], "quota_units": outcome["quota_units"],
                })
                collected.append("source_channel_profile")
            except ChannelResearchError as exc:
                source_channel["status"] = "unavailable"
                failed_sources.append(research_collectors.failure("channel_research", ref, str(exc)))
            except Exception as exc:
                source_channel["status"] = "unavailable"
                failed_sources.append(research_collectors.failure("channel_research", ref, f"{type(exc).__name__}: {str(exc)[:200]}"))
        elif identity.get("platform") in {"tiktok", "facebook", "instagram"}:
            limitations.append(
                f"Chưa nghiên cứu kênh {identity['platform']}: chưa có nguồn dữ liệu chính thức; "
                "Browser Bridge chưa được dùng cho việc này (không vượt CAPTCHA/bảo mật)."
            )
        channel_ref = f"{identity['platform']}:{identity['native_channel_id']}" if identity.get("channel_identity") == "native" else ""
        comment_samples: list[dict[str, Any]] = []
        reused_comments = 0

        def sample_comments(name: str, **arguments: Any) -> None:
            nonlocal reused_comments
            sample = safe(name, lambda: collectors.comments(project_id=project_id, **arguments))
            if sample.get("evidence"):
                comment_samples.append({"evidence": sample["evidence"][0], "patterns": sample["patterns"]})
                if name not in collected:
                    collected.append(name)
                reused_comments += int(bool(sample.get("reused")))

        if kind == "video" and identity.get("platform") == "youtube" and identity.get("native_video_id"):
            sample_comments(
                "source_comments", video_id=identity["native_video_id"], url=str(video.get("video_url") or ""),
                title=str(video.get("title") or ""), max_comments=collectors.budget.source_comments,
                channel_ref=channel_ref, published_at=video.get("published_at"),
            )

        # Similar videos: the subject for a video, an article or an idea; the
        # reviews for a product.
        product_name = (brief.get("product") or {}).get("name") or ""
        query = (f"{product_name} review" if kind == "product" and product_name
                 else " ".join([brief["topic"], *brief["keywords"][:2]]).strip())
        # A source that is not a video is not owed similar videos: what the
        # search returns for it counts only when it is plainly on the subject.
        strict = kind in {"article", "product", "images"} or stored_kind in {"audio", "web", "image_collection"}
        found = safe("youtube.similar", lambda: collectors.similar_videos(
            query=query, exclude_ids={str(identity.get("native_video_id") or "")}, language=brief["language"],
            label="reviews" if kind == "product" else "similar", topic_terms=research_collectors.topic_terms(brief),
            volatility=brief["volatility_assumed"], strict=strict,
        ))
        similar = found.get("videos") or []
        # Only these go on to comments, captions, counts and patterns. The rest
        # stay in the report, marked, and support nothing.
        relevant = [item for item in similar if item.get("relevance") != research_collectors.LOW]
        if similar:
            extra.update(similar_query=found.get("query"), similar_captured_at=found.get("captured_at"))
            reuse["similar_videos"] = bool(found.get("reused"))
            low = [item for item in similar if item.get("relevance") == research_collectors.LOW]
            if low:
                extra["low_relevance"] = {"videos": len(low), "of": len(similar),
                                          "evidence_ids": [item["evidence_id"] for item in low if item.get("evidence_id")]}
            if not relevant:
                limitations.append("Không video nào tìm được thực sự liên quan tới nguồn này: không dùng video tương tự.")
        if relevant:
            collected.append("review_videos" if kind == "product" else "similar_videos")
            safe("topic.patterns", lambda: collectors.record_topic_title_patterns(brief["topic_key"], relevant) or {})
        # The comment and caption budget goes by rank, not by views alone.
        with_comments = [item for item in relevant if (item.get("comment_count") or 0) > 0]
        for item in with_comments[: collectors.budget.similar_comment_videos]:
            sample_comments(
                "review_comments" if kind == "product" else "similar_video_comments",
                video_id=item["video_id"], url=item["url"], title=item["title"],
                max_comments=collectors.budget.similar_comments, published_at=item.get("published_at"),
            )
        reuse["comment_samples"] = f"{reused_comments}/{len(comment_samples)}"
        if relevant and kind in {"video", "idea", "product"}:
            captions = safe("youtube.captions", lambda: collectors.transcripts(relevant))
            if captions.get("evidence"):
                collected.append("review_captions" if kind == "product" else "hooks_structure_pacing")
            reuse["captions"] = f"{captions.get('reused', 0)}/{len(captions.get('evidence') or [])}"

        # The web: the news around an article, reviews of a product, the subject of anything else.
        if kind == "article":
            queries = [brief["topic"], *brief["entities"][:1]]
        elif kind == "product" and product_name:
            queries = [f"{product_name} đánh giá", f"{product_name} so sánh"]
        else:
            queries = [brief["topic"]]
        web = safe("web", lambda: collectors.web(queries, news=kind == "article", volatility=brief["volatility_assumed"]))
        timeline = web.get("timeline") or []
        extra["web_queries"] = web.get("queries") or {}
        reuse["web_queries"] = f"{web.get('reused', 0)}/{len(extra['web_queries'])}"
        read_kinds = {item["source_kind"] for item in web.get("evidence") or []}
        if kind == "article":
            if "article" in read_kinds:
                collected.append("other_articles")
            if "official" in read_kinds:
                collected.append("official_sources")
            if timeline:
                collected.append("timeline")
        elif kind == "product":
            if read_kinds & {"article", "official"}:
                collected.append("reviews")
            if "official" in read_kinds:
                collected.append("official_specs")
            if (brief.get("product") or {}).get("price"):
                collected.append("current_offer")
        elif read_kinds & {"article", "official"}:
            collected.append("topic_research_if_needed" if kind == "images" else "topic_research")

        raw_insights = {
            "audience_insights": research_collectors.observation_insights(comment_samples),
            "competitor_patterns": research_collectors.title_shape_insights(relevant),
        }
    else:
        limitations.append("Chưa chạy collectors (plan chạy ở chế độ khung, collect=false).")

    blocked = [item for item in failed_sources if item.get("collector_status") == research_collectors.BLOCKED]
    if blocked:
        limitations.append(
            f"{len(blocked)} nguồn bị chặn hoặc không trả lời (chặn truy cập tự động, đòi xác minh hay đăng nhập, hết giờ): "
            "không đọc được nên không dùng làm bằng chứng."
        )
    knowledge = knowledge_status(database, brief, identity, video)
    pending = [name for name in brief["collectors"] if name not in collected]
    report = research_evidence.build_report(
        brief=brief,
        evidence=evidence,
        raw_insights=raw_insights,
        topic={"name": brief["topic"], "key": brief["topic_key"], "volatility": brief["volatility_assumed"]},
        source_channel={**source_channel, "knowledge": knowledge.get("channel")},
        similar_content=similar,
        risks_uncertainty=risks,
        knowledge_used={**knowledge, "reuse": reuse},
        pending=pending,
        timeline=timeline,
        limitations=list(dict.fromkeys(limitations)),
        failed_sources=failed_sources,
    )
    report.update(extra)
    if units_before is not None and quota_used is not None:
        report["quota"] = {"youtube_units": max(0, quota_used() - units_before)}
    report["collected"] = list(dict.fromkeys(collected))
    # complete: everything attempted came back; partial: some did; failed:
    # nothing beyond the source itself could be collected.
    gathered = len(evidence) > len(source_evidence(video, identity, brief, analysis)) or "source_channel_profile" in collected
    if collectors is None:
        status = "partial"
    elif not gathered:
        status = "failed"
    elif failed_sources:
        status = "partial"
    else:
        status = "complete"
    analysis_at = str(analysis.get("created_at") or "")
    saved_report = database.create_research_report(
        project_id, status=status, source_kind=kind, analysis_created_at=analysis_at,
        engine_version=ENGINE_VERSION, report=report, captured_at=report["captured_at"],
    )
    return {
        "row": saved_report,
        "brief": brief,
        "summary": {
            "research_status": status,
            "research_report_id": saved_report.get("id"),
            "research_report_version": saved_report.get("version"),
            "source_kind": kind,
            "identity": {key: identity.get(key) for key in (
                "platform", "native_video_id", "native_channel_id", "channel_name", "channel_identity", "refreshed",
            )},
            "source_channel": source_channel,
            "knowledge": knowledge,
            "reuse": reuse,
            "pending_collectors": pending,
            "coverage": report["coverage"],
            "insights": {group: len(report[group]) for group in research_evidence.INSIGHT_GROUPS},
            "limitations": report["limitations"],
            "failed_sources": report["failed_sources"],
            "quota": report.get("quota"),
        },
    }


# ---------------------------------------------------------------------------
# The step
# ---------------------------------------------------------------------------

# What a caller can watch the step go through (GET …/steps → run.stage).
STAGES = (
    ("read_analysis", "Đọc phân tích"),
    ("research", "Nghiên cứu dữ liệu"),
    ("insights", "Phân tích insight"),
    ("angles", "Tìm góc nội dung"),
    ("strategy", "Xây dựng chiến lược"),
    ("feasibility", "Kiểm tra tính khả thi"),
    ("finalize", "Hoàn thiện kế hoạch"),
)
MODES = ("auto", "full", "reason", "replan")
# How long a report's collected evidence is good for: as fast as the subject
# moves, and never longer than the comment and similar-video samples in it.
REPORT_REUSE = {"news": freshness.POLICIES["topic_news"].max_age, "hot": freshness.POLICIES["topic_hot"].max_age}
REPORT_REUSE_DEFAULT = freshness.POLICIES["similar_videos"].max_age


class PlanError(RuntimeError):
    """The step could not finish, said in words a person can act on."""

    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


class ReasonerFailed(RuntimeError):
    """No model runtime answered (after the orchestrator's own fallbacks)."""


class _Ai:
    """The model calls of one run: one for insights, one for the plan, and one repair between them."""

    def __init__(self, reasoner: Callable[..., tuple[Any, dict[str, Any]]]):
        self.reasoner = reasoner
        self.calls: list[dict[str, Any]] = []
        self.repair_used = False

    def ask(
        self, label: str, system: str, prompt: str, schema: dict[str, Any], *,
        check: Callable[[Any], tuple[list[str], Any]], repair: Callable[[str, list[str]], str],
    ) -> tuple[Any, Any]:
        parsed = self._call(label, system, prompt, schema)
        errors, extra = check(parsed)
        if errors and not self.repair_used:
            # One repair for the whole run, spent on whichever answer first needs it.
            self.repair_used = True
            parsed = self._call(f"{label} (sửa)", system, repair(prompt, errors), schema)
            errors, extra = check(parsed)
        if errors:
            raise PlanError(f"AI trả lời chưa dùng được ở bước {label}: " + "; ".join(errors[:3]), 502)
        return parsed, extra

    def _call(self, label: str, system: str, prompt: str, schema: dict[str, Any]) -> Any:
        started = time.monotonic()
        try:
            parsed, info = self.reasoner(system, prompt, schema, label)
        except ReasonerFailed as exc:
            self.calls.append({"step": label, "status": "failed", "seconds": round(time.monotonic() - started, 1)})
            raise PlanError(f"AI chưa chạy được bước {label}. {str(exc)[:300]}", 502) from exc
        self.calls.append({
            "step": label, "status": "ok", "runtime": str((info or {}).get("runtime") or ""),
            "seconds": round(time.monotonic() - started, 1),
            "fallback_from": [item.get("runtime") for item in (info or {}).get("attempts") or [] if item.get("status") == "failed"],
        })
        return parsed

    def summary(self) -> dict[str, Any]:
        done = [item for item in self.calls if item["status"] == "ok"]
        return {"calls": len(self.calls), "repair_used": self.repair_used,
                "runtimes": list(dict.fromkeys(item["runtime"] for item in done if item.get("runtime"))),
                "seconds": round(sum(item["seconds"] for item in self.calls), 1), "detail": self.calls}


def report_state(report_row: dict[str, Any] | None, analysis_created_at: str) -> dict[str, Any]:
    """Whether a stored ResearchReport can stand in for researching again.

    usable: it was built on the analysis the project has now, and something
    was collected. fresh: usable, and young enough for its subject.
    """
    if not report_row:
        return {"usable": False, "fresh": False, "reason": "Chưa có báo cáo nghiên cứu"}
    report = report_row.get("report") or {}
    if str(report_row.get("analysis_created_at") or "") != str(analysis_created_at or ""):
        return {"usable": False, "fresh": False, "reason": "Báo cáo nghiên cứu thuộc về bản phân tích cũ"}
    if report_row.get("status") == "failed" or not report.get("evidence"):
        return {"usable": False, "fresh": False, "reason": "Lần nghiên cứu trước không thu được gì"}
    if not report.get("collected") and "Chưa chạy collectors" in " ".join(report.get("limitations") or []):
        return {"usable": False, "fresh": False, "reason": "Báo cáo trước chỉ là khung, chưa nghiên cứu"}
    volatility = str((report.get("brief") or {}).get("volatility_assumed") or "evergreen")
    limit: timedelta = REPORT_REUSE.get(volatility, REPORT_REUSE_DEFAULT)
    captured = freshness.parse_time(report.get("captured_at"))
    age = (datetime.now(timezone.utc) - captured) if captured else None
    fresh = age is not None and age <= limit
    return {
        "usable": True, "fresh": fresh, "volatility": volatility,
        "age_seconds": int(age.total_seconds()) if age is not None else None, "max_age_seconds": int(limit.total_seconds()),
        "reason": "" if fresh else "Báo cáo nghiên cứu đã quá hạn dùng lại",
    }


def run(
    database: Any,
    project: dict[str, Any],
    video: dict[str, Any],
    analysis: dict[str, Any],
    *,
    identify: Callable[[], dict[str, Any]],
    channel_service: Any = None,
    collectors: Any = None,
    quota_used: Callable[[], int] | None = None,
    reasoner: Callable[..., tuple[Any, dict[str, Any]]] | None = None,
    options: dict[str, Any] | None = None,
    progress: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """The plan step. With no `reasoner` it stops at research and a skeleton plan (Phase 1-2).

    options.mode
      auto    research unless a ResearchReport for this analysis is still fresh (default)
      full    research again whatever is stored (the collectors still reuse what is fresh)
      reason  no network: insights and plan from the stored ResearchReport
      replan  no network, one model call: a new plan from the stored report and insights -
              what changing the platform, duration, aspect ratio, video type or angle needs
    options.settings          {output_profile, target_duration_seconds, video_type} for this plan
    options.primary_angle_id  the angle to plan for, among the stored candidates; implies replan

    What a person asked for stays asked for: the settings of the plan before
    carry over until they are given again (a null clears one), and so does the
    chosen angle for as long as the insights it was chosen among are the same.
    The step's status follows the feasibility check (plan_engine.STEP_STATUS):
    only `completed` is a finished Bước 2.
    """
    options = dict(options or {})
    project_id = int(project["id"])
    analysis_at = str(analysis.get("created_at") or "")
    timings: dict[str, float] = {}
    clock = {"stage": "", "started": time.monotonic(), "run": time.monotonic()}

    def stage(key: str) -> None:
        now = time.monotonic()
        if clock["stage"]:
            timings[clock["stage"]] = round(timings.get(clock["stage"], 0.0) + now - clock["started"], 1)
        clock.update(stage=key, started=now)
        if key and progress:
            progress(key, dict(STAGES).get(key, key))

    stage("read_analysis")
    if reasoner is None:
        stage("research")
        found = research(database, project, video, analysis, identify=identify, channel_service=channel_service,
                         collectors=collectors, quota_used=quota_used)
        stage("finalize")
        return _skeleton(database, project, video, found, analysis_at)

    asked_angle = str(options.get("primary_angle_id") or (options.get("settings") or {}).get("primary_angle_id") or "").strip()
    mode = str(options.get("mode") or ("replan" if asked_angle else "auto")).lower()
    if mode not in MODES:
        raise PlanError(f"Chế độ lập kế hoạch không hợp lệ: {mode}. Chọn một trong: {', '.join(MODES)}.", 400)
    if asked_angle and mode != "replan":
        # Any other mode reads the insights again, and the angles get new ids.
        raise PlanError("primary_angle_id chỉ dùng với mode=replan: các chế độ khác phân tích insight lại nên mã góc sẽ đổi.", 400)
    latest = database.get_latest_research_report(project_id)
    state = report_state(latest, analysis_at)
    reuse_research = mode in {"reason", "replan"} or (mode == "auto" and state["fresh"])
    summary: dict[str, Any] = {}
    if reuse_research:
        if not state["usable"]:
            raise PlanError(
                f"Chưa có nghiên cứu dùng lại được ({state['reason']}). Hãy chạy lập kế hoạch đầy đủ (mode=auto hoặc full).", 409)
        report_row = latest
    else:
        stage("research")
        found = research(database, project, video, analysis, identify=identify, channel_service=channel_service,
                         collectors=collectors, quota_used=quota_used)
        report_row, summary = found["row"], found["summary"]
        if report_row.get("status") == "failed" and collectors is not None:
            summary["limitations"] = [*summary.get("limitations", []), "Nghiên cứu không thu được gì ngoài chính nguồn."]
    report = report_row.get("report") or {}
    brief = report.get("brief") or {}
    kind = insight_engine.reasoning_kind(video, report)
    render_settings = database.get_project_render_settings(project_id)
    ai = _Ai(reasoner)
    insight_row: dict[str, Any] | None = None
    if mode == "replan":
        insight_row = current_insight(database, project_id, analysis_at)
        if not insight_row or insight_row["stale"] or not (insight_row.get("report") or {}).get("angle_candidates"):
            why = "; ".join((insight_row or {}).get("stale_reasons") or ["Chưa có báo cáo insight"])
            raise PlanError(
                f"Chưa có insight dùng lại được ({why}). Chạy mode=reason để phân tích lại từ nghiên cứu đã lưu, không cần Internet.", 409)
    settings = plan_engine.settings_for(
        project, render_settings, language=language_code(brief.get("language")),
        requested=requested_settings(database, project_id, options, (insight_row or {}).get("id")),
    )

    if insight_row is not None:
        insight = insight_row["report"]
        known = [item["id"] for item in insight.get("angle_candidates") or []]
        if settings["primary_angle_id"] and settings["primary_angle_id"] not in known:
            raise PlanError(
                f"Không có góc nội dung {settings['primary_angle_id']} trong báo cáo insight hiện tại. Chọn một trong: {', '.join(known)}.", 400)
    else:
        stage("insights")
        pack = insight_engine.build_pack(database, video, analysis, report, kind)
        prompt = insight_engine.build_prompt(pack, language=settings["language"], platform=settings["platform"])
        _, validated = ai.ask(
            "Phân tích insight", insight_engine.SYSTEM_PROMPT, prompt, insight_engine.INSIGHT_SCHEMA,
            check=lambda parsed: insight_engine.validation_errors(parsed, pack["evidence"], kind=kind, excluded=pack["excluded"]),
            repair=insight_engine.repair_prompt,
        )
        stage("angles")
        insight = insight_engine.assemble(
            validated, pack, kind=kind, research_report_id=report_row.get("id"), analysis=analysis, ai=ai.summary(),
        )
        insight_row = database.create_insight_report(
            project_id, status="complete" if len(insight["angle_candidates"]) >= insight_engine.MIN_ANGLES else "partial",
            research_report_id=report_row.get("id"), analysis_created_at=analysis_at, source_kind=kind,
            engine_version=insight_engine.ENGINE_VERSION, report=insight,
            provider=", ".join(ai.summary()["runtimes"]),
        )
        _remember_facts(database, report, insight)

    stage("strategy")
    must_not_invent = list(brief.get("questions") or [])
    assets = plan_engine.available_assets(database, project, video, analysis, source_kind=kind)
    plan_prompt = plan_engine.build_prompt(
        kind=kind, video=video, analysis=analysis, insight=insight, settings=settings, assets=assets,
        must_not_invent=must_not_invent,
    )
    parsed_plan, _ = ai.ask(
        "Lập kế hoạch", plan_engine.SYSTEM_PROMPT, plan_prompt, plan_engine.PLAN_SCHEMA,
        check=lambda parsed: (plan_engine.shape_errors(parsed, insight, settings["primary_angle_id"]), None),
        repair=plan_engine.repair_prompt,
    )
    plan = plan_engine.finalise(
        parsed_plan, kind=kind, insight=insight, settings=settings, assets=assets, must_not_invent=must_not_invent,
        refs={
            "analysis_ref": {"created_at": analysis_at, "provider": analysis.get("provider")},
            "research_report_id": report_row.get("id"),
            "insight_report_id": insight_row.get("id"),
        },
    )
    stage("feasibility")
    feasibility = plan_engine.feasibility(plan, settings=settings, assets=assets)
    stage("finalize")
    status = plan_engine.step_status(feasibility["status"])
    plan["ai"] = ai.summary()
    saved_plan = database.create_project_plan(
        project_id, status=status, research_report_id=report_row.get("id"), analysis_created_at=analysis_at,
        engine_version=plan_engine.ENGINE_VERSION, plan=plan, feasibility=feasibility,
        provider=", ".join(ai.summary()["runtimes"]), insight_report_id=insight_row.get("id"),
    )
    stage("")
    by_type: dict[str, list[str]] = {}
    for item in insight.get("insights") or []:
        by_type.setdefault(item["type"], []).append(item["statement"])
    return {
        **summary,
        "status": status,
        "mode": mode,
        "source_kind": kind,
        "research_kind": brief.get("source_kind"),
        "research_status": report_row.get("status"),
        "research_report_id": report_row.get("id"),
        "research_report_version": report_row.get("version"),
        "research_reused": reuse_research,
        "insight_report_id": insight_row.get("id"),
        "insight_report_version": insight_row.get("version"),
        "insight_reused": mode == "replan",
        "plan_id": saved_plan.get("id"),
        "plan_version": saved_plan.get("version"),
        "evidence_count": len(report.get("evidence") or []),
        "insight_summary": insight.get("summary"),
        "top_insights": [
            {key: item.get(key) for key in ("id", "type", "statement", "confidence", "sample_size", "source_count")}
            for item in (insight.get("insights") or [])[:6]
        ],
        "content_gaps": by_type.get("content_gap", []),
        "angle_candidates": [{"id": item["id"], "statement": item["statement"]} for item in insight.get("angle_candidates") or []],
        "primary_angle": plan["primary_angle"]["statement"],
        "primary_angle_id": plan["primary_angle_id"],
        "primary_angle_from": plan["primary_angle_from"],
        "requested": plan["requested"],
        "missing_assets": plan["missing_assets"],
        "ai_proposed_assets": plan["ai_proposed_assets"],
        "target_duration_seconds": plan["target_duration_seconds"],
        "structure": [{"name": item["name"], "seconds": item["estimated_seconds"]} for item in plan["content_structure"]],
        "feasibility": {"status": feasibility["status"], "reason": feasibility["reason"],
                        "attention": [item for item in feasibility["checks"] if item["status"] not in (plan_engine.OK,)],
                        "adjustments": feasibility["adjustments"]},
        "plan_limitations": plan["limitations"],
        "factual_guardrails": plan["factual_guardrails"],
        "claims_to_avoid": plan["claims_to_avoid"],
        "pending_fields": [],
        "ai": ai.summary(),
        "timings": {**timings, "total": round(time.monotonic() - clock["run"], 1)},
    }


def requested_settings(database: Any, project_id: int, options: dict[str, Any], insight_report_id: int | None = None) -> dict[str, Any]:
    """What a person asked this plan to be: what the plan before was asked, changed by what is asked now.

    A value given as null clears it. The chosen angle carries over only onto
    the same InsightReport - under new insights its id names another angle.
    """
    previous = database.get_latest_project_plan(project_id) or {}
    carried = dict((previous.get("plan") or {}).get("requested") or {})
    chosen_before = carried.pop("primary_angle_id", None)
    asked = dict(options.get("settings") or {})
    if "primary_angle_id" in options:
        asked["primary_angle_id"] = options["primary_angle_id"]
    merged = {**carried, **asked}
    if "primary_angle_id" not in asked and chosen_before and insight_report_id and previous.get("insight_report_id") == insight_report_id:
        merged["primary_angle_id"] = chosen_before
    return {key: value for key, value in merged.items() if value not in (None, "", 0)}


def _remember_facts(database: Any, report: dict[str, Any], insight: dict[str, Any]) -> None:
    """Keep the checked claims, with the pages they were read on, for the next plan on this subject."""
    topic = report.get("topic") or {}
    facts = insight_engine.topic_facts(insight)
    if not facts or not topic.get("key"):
        return
    try:
        TopicIntelligence(database).upsert(
            str(topic["key"]), str((report.get("brief") or {}).get("language") or "vi"),
            title=str(topic.get("name") or ""), volatility=str(topic.get("volatility") or "evergreen"), facts=facts,
        )
    except Exception:
        pass  # a store that will not take a fact must not cost the plan


def _skeleton(database: Any, project: dict[str, Any], video: dict[str, Any], found: dict[str, Any], analysis_at: str) -> dict[str, Any]:
    """Research only: the report, and a plan holding just what the project's settings already decide."""
    project_id = int(project["id"])
    render_settings = database.get_project_render_settings(project_id)
    plan, feasibility = draft_plan(found["brief"], project, render_settings, video)
    plan["research_report_id"] = found["row"].get("id")
    saved_plan = database.create_project_plan(
        project_id, status="draft", research_report_id=found["row"].get("id"), analysis_created_at=analysis_at,
        engine_version=ENGINE_VERSION, plan=plan, feasibility=feasibility,
    )
    return {
        "status": "draft",
        **found["summary"],
        "plan_id": saved_plan.get("id"),
        "plan_version": saved_plan.get("version"),
        "pending_fields": plan["pending_fields"],
    }


def current_insight(database: Any, project_id: int, analysis_created_at: str) -> dict[str, Any] | None:
    """The latest InsightReport, stale when the analysis or the research under it has changed."""
    row = database.get_latest_insight_report(project_id)
    if not row:
        return None
    reasons = []
    if analysis_created_at and str(row.get("analysis_created_at") or "") != analysis_created_at:
        reasons.append("Bản phân tích nguồn đã thay đổi")
    latest_report = database.get_latest_research_report(project_id)
    if latest_report and row.get("research_report_id") and latest_report.get("id") != row.get("research_report_id"):
        reasons.append("Có báo cáo nghiên cứu mới hơn")
    return {**row, "stale": bool(reasons), "stale_reasons": reasons}


def current_plan(database: Any, project_id: int, analysis_created_at: str) -> dict[str, Any] | None:
    """The latest plan, stale when anything it was built on has changed.

    The analysis, the ResearchReport or the InsightReport: a newer one of any
    of them means this plan answers a question that has since moved.
    """
    plan = database.get_latest_project_plan(project_id)
    if not plan:
        return None
    # A plan saved before the statuses were renamed means what it meant.
    plan = {**plan, "status": plan_engine.LEGACY_STATUS.get(str(plan.get("status") or ""), plan.get("status"))}
    reasons = []
    if plan.get("status") == plan_engine.STALE:
        reasons.append("Kế hoạch đã được đánh dấu là cũ")
    if analysis_created_at and str(plan.get("analysis_created_at") or "") != analysis_created_at:
        reasons.append("Bản phân tích nguồn đã thay đổi")
    latest_report = database.get_latest_research_report(project_id)
    if latest_report and plan.get("research_report_id") and latest_report.get("id") != plan.get("research_report_id"):
        reasons.append("Có báo cáo nghiên cứu mới hơn")
    latest_insight = database.get_latest_insight_report(project_id)
    if latest_insight and plan.get("insight_report_id") and latest_insight.get("id") != plan.get("insight_report_id"):
        reasons.append("Có báo cáo insight mới hơn")
    stale = bool(reasons)
    return {**plan, "stale": stale, "stale_reasons": reasons,
            "effective_status": plan_engine.STALE if stale else plan.get("status")}


def step_outcome(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    """Where Bước 2 stands, from the plan `current_plan` returned. None before any plan.

    completed            feasibility ok or adjusted, and nothing under the plan has changed
    needs_user_decision  the plan exists; a person has to choose before it is usable
    blocked              there is nothing to make the video from
    stale                the analysis, the research or the insights have moved on
    draft                research only (no reasoning was run)
    """
    if not plan:
        return None
    status = str(plan.get("effective_status") or "")
    feasibility = plan.get("feasibility") or {}
    decisions = [
        {key: item.get(key) for key in ("key", "detail", "options")}
        for item in feasibility.get("checks") or [] if item.get("status") in (plan_engine.NEEDS_ATTENTION, plan_engine.BLOCKED)
    ]
    reason = "; ".join(plan.get("stale_reasons") or []) if status == plan_engine.STALE else str(feasibility.get("reason") or "")
    return {
        "status": status, "completed": status == plan_engine.COMPLETED, "reason": reason, "decisions": decisions,
        "plan_id": plan.get("id"), "plan_version": plan.get("version"), "feasibility": feasibility.get("status"),
    }
