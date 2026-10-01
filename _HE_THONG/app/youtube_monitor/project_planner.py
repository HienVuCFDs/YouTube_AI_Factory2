"""Bước 2 · Kế hoạch - Phase 1: the foundation the planner will stand on.

    AnalysisResult → Research → Insight → ProjectPlan → Bước 3 Kịch bản

This phase does the parts that need no collector and no model:

2.1 the research brief, worked out from the analysis alone;
2.2 what the knowledge stores already hold about this channel, topic and
    audience, and whether it is fresh, stale or missing;
2.5 a ResearchReport holding the evidence the app already has (the source
    itself), with every collector still to run listed as pending;
2.7 a ProjectPlan draft with only the fields that follow from settings the
    project already has; every field that needs research is left empty and
    named as pending, rather than filled with a guess.

It reads nothing from the old research paths - `run_step("research")`'s
director artifact, the five-role pipeline's Research Agent, the folklore
lookup - so the plan does not inherit their unsourced output.
"""

from __future__ import annotations

from math import gcd
from typing import Any, Callable

from . import freshness, research_evidence, source_kinds, workflows
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


def _texts(values: Any, limit: int) -> list[str]:
    found: list[str] = []
    for item in values or []:
        text = item.get("keyword") if isinstance(item, dict) else item
        text = " ".join(str(text or "").split())
        if text and text not in found:
            found.append(text[:120])
        if len(found) >= limit:
            break
    return found


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
        "language": str(result.get("language") or "vi")[:12],
        "volatility_assumed": ASSUMED_VOLATILITY.get(kind, "evergreen"),
        "keywords": _texts(result.get("keywords"), 15),
        "entities": entities,
        # What the analysis could not settle becomes a question for research,
        # not a gap for the writer to fill.
        "questions": _texts(result.get("limitations"), 12),
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


def source_evidence(video: dict[str, Any], identity: dict[str, Any], brief: dict[str, Any], analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """The one piece of evidence every plan has: the source that was analysed."""
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
) -> dict[str, Any]:
    """The plan step: research the source, save a ResearchReport and a draft plan.

    AnalysisResult → research brief → knowledge reuse → collectors →
    ResearchReport → ProjectPlan skeleton. The source's channel goes through
    the one ChannelResearchService the channel manager also uses; nothing here
    researches a channel itself. No model is asked anything: insights are
    counts, each citing its evidence. A collector that fails is recorded and
    the rest go on; the report is `failed` only when nothing was collected.
    """
    units_before = quota_used() if quota_used else None
    identity = identify()
    brief = research_brief(video, analysis, identity)
    evidence = source_evidence(video, identity, brief, analysis)
    limitations: list[str] = []
    failed_sources: list[dict[str, str]] = []
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

    def safe(name: str, call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """One collector; whatever it raises becomes a recorded failure."""
        try:
            result = call()
        except Exception as exc:  # a collector must never take the plan down
            failed_sources.append({"collector": name, "source": "", "reason": f"{type(exc).__name__}: {str(exc)[:200]}"})
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
                failed_sources.append({"collector": "channel_research", "source": ref, "reason": str(exc)[:300]})
            except Exception as exc:
                source_channel["status"] = "unavailable"
                failed_sources.append({"collector": "channel_research", "source": ref, "reason": f"{type(exc).__name__}: {str(exc)[:200]}"})
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
        topic_terms = set(research_text_tokens(" ".join([brief["topic"], *brief["keywords"][:5], product_name])))
        found = safe("youtube.similar", lambda: collectors.similar_videos(
            query=query, exclude_ids={str(identity.get("native_video_id") or "")}, language=brief["language"],
            label="reviews" if kind == "product" else "similar", topic_terms=topic_terms,
            volatility=brief["volatility_assumed"],
        ))
        similar = found.get("videos") or []
        if similar:
            collected.append("review_videos" if kind == "product" else "similar_videos")
            extra.update(similar_query=found.get("query"), similar_captured_at=found.get("captured_at"))
            reuse["similar_videos"] = bool(found.get("reused"))
            safe("topic.patterns", lambda: collectors.record_topic_title_patterns(brief["topic_key"], similar) or {})
        # The comment and caption budget goes by rank, not by views alone.
        with_comments = [item for item in similar if (item.get("comment_count") or 0) > 0]
        for item in with_comments[: collectors.budget.similar_comment_videos]:
            sample_comments(
                "review_comments" if kind == "product" else "similar_video_comments",
                video_id=item["video_id"], url=item["url"], title=item["title"],
                max_comments=collectors.budget.similar_comments, published_at=item.get("published_at"),
            )
        reuse["comment_samples"] = f"{reused_comments}/{len(comment_samples)}"
        if similar and kind in {"video", "idea", "product"}:
            captions = safe("youtube.captions", lambda: collectors.transcripts(similar))
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

        from .research_collectors import observation_insights, title_shape_insights

        raw_insights = {
            "audience_insights": observation_insights(comment_samples),
            "competitor_patterns": title_shape_insights(similar),
        }
    else:
        limitations.append("Chưa chạy collectors (plan chạy ở chế độ khung, collect=false).")

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
    render_settings = database.get_project_render_settings(project_id)
    plan, feasibility = draft_plan(brief, project, render_settings, video)
    plan["research_report_id"] = saved_report.get("id")
    saved_plan = database.create_project_plan(
        project_id, status="draft", research_report_id=saved_report.get("id"), analysis_created_at=analysis_at,
        engine_version=ENGINE_VERSION, plan=plan, feasibility=feasibility,
    )
    return {
        "status": "draft",
        "research_status": status,
        "research_report_id": saved_report.get("id"),
        "research_report_version": saved_report.get("version"),
        "plan_id": saved_plan.get("id"),
        "plan_version": saved_plan.get("version"),
        "source_kind": kind,
        "identity": {key: identity.get(key) for key in (
            "platform", "native_video_id", "native_channel_id", "channel_name", "channel_identity", "refreshed",
        )},
        "source_channel": source_channel,
        "knowledge": knowledge,
        "reuse": reuse,
        "pending_fields": plan["pending_fields"],
        "pending_collectors": pending,
        "coverage": report["coverage"],
        "insights": {group: len(report[group]) for group in research_evidence.INSIGHT_GROUPS},
        "limitations": report["limitations"],
        "failed_sources": report["failed_sources"],
        "quota": report.get("quota"),
    }


def research_text_tokens(text: str) -> list[str]:
    from .research_text import tokens

    return tokens(text)


def current_plan(database: Any, project_id: int, analysis_created_at: str) -> dict[str, Any] | None:
    """The latest plan, marked stale when the analysis it was built on has changed."""
    plan = database.get_latest_project_plan(project_id)
    if not plan:
        return None
    built_on = str(plan.get("analysis_created_at") or "")
    stale = plan.get("status") == "stale" or (bool(analysis_created_at) and built_on != analysis_created_at)
    return {**plan, "stale": stale, "effective_status": "stale" if stale else plan.get("status")}
