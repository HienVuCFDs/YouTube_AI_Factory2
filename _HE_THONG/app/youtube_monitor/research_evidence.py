"""Evidence and the insights drawn from it, with the numbers kept honest.

An insight is only as good as what it rests on, so every one must point at
evidence the app actually collected. Its sample size, source count and
confidence are worked out here from that evidence, by rule - whatever figure
a model wrote next to its sentence is thrown away. A model that says "25% of
viewers" when it read 25% of forty sampled comments is not reporting a fact
about the audience, and the rule below refuses the sentence rather than
repeating it.

Nothing here keeps who wrote a comment: author names, handles, channel ids
and profile links are dropped on the way in, and @mentions are blanked.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

EVIDENCE_KINDS = frozenset({
    "source",           # the analysed source itself
    "video_meta",       # a video's title, counts, dates
    "channel_stats",    # a channel's counts or recent uploads
    "comment_sample",   # a sample of comments under one video
    "article",          # a news or blog article
    "official",         # an official source: maker, government, the event's owner
    "product_page",     # a listing read from a shop
    "review",           # a review article or video
    "search_result",    # a search hit that was not opened
    "transcript",       # a video's own captions (a short opening excerpt is kept)
})
# Evidence whose sample_size counts people's messages. Only these add up to
# an insight's sample size; a video's view count is not a sample of anything.
SAMPLE_KINDS = frozenset({"comment_sample"})
AUTHORITATIVE_KINDS = frozenset({"official", "product_page"})
WEAK_KINDS = frozenset({"search_result"})

# Keys that would identify a person who commented. Dropped wherever they
# appear, at any depth.
PERSONAL_KEYS = frozenset({
    "author", "author_name", "author_id", "author_url", "authordisplayname", "authorchannelid",
    "authorchannelurl", "authorprofileimageurl", "username", "user_name", "user_id", "userid",
    "commenter", "commenter_id", "commenter_name", "handle", "profile_url", "profile_image",
    "avatar", "display_name", "channel_of_commenter",
})
_MENTION = re.compile(r"@[\w.\-]{2,}", re.UNICODE)
EXCERPT_LIMIT = 300

# A proportion stated about the whole audience. Allowed only when it is
# about the sample itself ("trong 40 comment mẫu").
_PERCENT = re.compile(r"\d+(?:[.,]\d+)?\s*%|phần\s*trăm", re.IGNORECASE)
_AUDIENCE_WORDS = re.compile(
    r"người\s*xem|khán\s*giả|audience|viewers?|mọi\s*người|đa\s*số\s*người|người\s*dùng|khách\s*hàng",
    re.IGNORECASE,
)
_SAMPLE_WORDS = re.compile(r"comment|bình\s*luận|mẫu", re.IGNORECASE)

CONFIDENCE_LEVELS = ("low", "medium", "high")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def strip_personal(value: Any) -> Any:
    """The same data without anything that names the person who wrote it."""
    if isinstance(value, dict):
        return {
            key: strip_personal(item)
            for key, item in value.items()
            if str(key).replace("-", "_").lower() not in PERSONAL_KEYS
        }
    if isinstance(value, list):
        return [strip_personal(item) for item in value]
    if isinstance(value, str):
        return _MENTION.sub("@…", value)
    return value


def _host(url: str) -> str:
    return (urlparse(str(url or "")).hostname or "").lower()


def evidence_id(kind: str, source_url: str, captured_at: str, sampling: dict[str, Any] | None) -> str:
    basis = f"{kind}|{source_url}|{captured_at}|{sorted((sampling or {}).items())}"
    return "ev-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:10]


def make_evidence(
    source_kind: str,
    *,
    source_url: str,
    collector: str,
    collector_version: str = "1",
    native_source_id: str = "",
    title: str = "",
    platform: str = "",
    excerpt: str = "",
    metrics: dict[str, Any] | None = None,
    sample_size: int | None = None,
    sampling: dict[str, Any] | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """One piece of evidence, checked. Raises ValueError when it is not usable.

    `collector` and `collector_version` say which code gathered it, so a
    collector found to be wrong later can have its evidence found and redone.
    """
    if source_kind not in EVIDENCE_KINDS:
        raise ValueError(f"Loại bằng chứng không hợp lệ: {source_kind}")
    url = str(source_url or "").strip()
    if not url:
        raise ValueError("Bằng chứng phải có nguồn (source_url)")
    if not str(collector or "").strip():
        raise ValueError("Bằng chứng phải ghi rõ collector đã thu thập nó")
    size: int | None
    try:
        size = int(sample_size) if sample_size is not None else None
    except (TypeError, ValueError):
        size = None
    if size is not None and size < 0:
        size = None
    if source_kind in SAMPLE_KINDS and not size:
        raise ValueError("Mẫu comment phải có sample_size lớn hơn 0")
    moment = str(captured_at or _now())
    clean_sampling = strip_personal(dict(sampling or {}))
    text = strip_personal(" ".join(str(excerpt or "").split()))
    return {
        "id": evidence_id(source_kind, url, moment, clean_sampling),
        "source_kind": source_kind,
        "source_url": url[:600],
        "native_source_id": str(native_source_id or "")[:200],
        "platform": str(platform or "")[:40],
        "title": str(title or "")[:300],
        "excerpt": text[:EXCERPT_LIMIT],
        "metrics": {
            key: value for key, value in strip_personal(dict(metrics or {})).items()
            if isinstance(value, (int, float, str)) or value is None
        },
        "sample_size": size,
        "sampling": clean_sampling,
        "captured_at": moment,
        "collector": str(collector).strip()[:80],
        "collector_version": str(collector_version or "1")[:40],
    }


def _confidence(cited: list[dict[str, Any]], sample_size: int | None, source_count: int) -> str:
    """The rule, in one place.

    Samples (comments): how many messages, from how many places.
    Facts (pages, videos, official sources): how many independent sources,
    with an official one counting for more.
    """
    if sample_size:
        if sample_size >= 100 and source_count >= 2:
            return "high"
        if sample_size >= 30 or source_count >= 2:
            return "medium"
        return "low"
    # A search snippet was never read: it points at a source, it is not one.
    read = [item for item in cited if item["source_kind"] not in WEAK_KINDS]
    source_count = len({item["source_url"] for item in read})
    authoritative = any(item["source_kind"] in AUTHORITATIVE_KINDS for item in read)
    if source_count >= 3 or (authoritative and source_count >= 2):
        return "high"
    if source_count >= 2 or authoritative:
        return "medium"
    return "low"


def _scope_note(cited: list[dict[str, Any]], sample_size: int | None, source_count: int) -> str:
    if sample_size:
        places = len({item["source_url"] for item in cited if item["source_kind"] in SAMPLE_KINDS})
        return (
            f"Dựa trên {sample_size} comment mẫu từ {places} nguồn; "
            "chỉ phản ánh mẫu đã đọc, không đại diện cho toàn bộ người xem."
        )
    snippets = len({item["source_url"] for item in cited if item["source_kind"] in WEAK_KINDS})
    read = source_count - snippets
    return f"Dựa trên {read} nguồn đã đọc" + (f" và {snippets} trích đoạn tìm kiếm chưa mở." if snippets else ".")


def validate_insights(
    raw_insights: list[dict[str, Any]] | None,
    evidence: list[dict[str, Any]],
    *,
    group: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep the insights that rest on real evidence; say why the rest were refused.

    Returns (accepted, rejected). Every number on an accepted insight is
    recomputed from the evidence it cites.
    """
    by_id = {item["id"]: item for item in evidence}
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_insights or [], start=1):
        text = " ".join(str((raw or {}).get("text") or (raw or {}).get("insight") or "").split())
        if not text:
            rejected.append({"text": "", "reason": "Insight trống"})
            continue
        cited_ids = [str(item) for item in (raw or {}).get("evidence_ids") or []]
        cited = [by_id[item] for item in dict.fromkeys(cited_ids) if item in by_id]
        unknown = [item for item in cited_ids if item not in by_id]
        if not cited:
            rejected.append({
                "text": text,
                "reason": "Không có bằng chứng" if not cited_ids else "Chỉ dẫn tới bằng chứng không tồn tại",
                "unknown_evidence_ids": unknown,
            })
            continue
        samples = [item["sample_size"] for item in cited if item["source_kind"] in SAMPLE_KINDS and item["sample_size"]]
        sample_size = sum(samples) if samples else None
        source_count = len({item["source_url"] for item in cited})
        if _PERCENT.search(text) and _AUDIENCE_WORDS.search(text) and not _SAMPLE_WORDS.search(text):
            rejected.append({
                "text": text,
                "reason": (
                    "Nêu tỉ lệ cho toàn bộ người xem trong khi chỉ có mẫu"
                    + (f" {sample_size} comment" if sample_size else "")
                    + ". Hãy nói tỉ lệ trên mẫu đã đọc."
                ),
            })
            continue
        accepted.append({
            "id": f"{group or 'in'}-{index}",
            "text": text[:500],
            "evidence_ids": [item["id"] for item in cited],
            "sample_size": sample_size,
            "source_count": source_count,
            "confidence": _confidence(cited, sample_size, source_count),
            "scope_note": _scope_note(cited, sample_size, source_count),
            "captured_at": max(item["captured_at"] for item in cited),
            "ignored_evidence_ids": unknown,
        })
    return accepted, rejected


INSIGHT_GROUPS = ("audience_insights", "competitor_patterns", "content_gaps", "opportunities")


def coverage(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """What was actually read, counted from the evidence rather than claimed."""
    kinds: dict[str, int] = {}
    for item in evidence:
        kinds[item["source_kind"]] = kinds.get(item["source_kind"], 0) + 1
    return {
        "evidence": len(evidence),
        "by_kind": kinds,
        "videos": kinds.get("video_meta", 0) + (1 if any(
            item["source_kind"] == "source" and item.get("platform") not in {"web", "shop", "upload", "idea", ""}
            for item in evidence
        ) else 0),
        "comments_sampled": sum(item["sample_size"] or 0 for item in evidence if item["source_kind"] in SAMPLE_KINDS),
        "articles": kinds.get("article", 0) + kinds.get("official", 0),
        "product_pages": kinds.get("product_page", 0),
        "sources": len({_host(item["source_url"]) for item in evidence if _host(item["source_url"])}),
    }


def build_report(
    *,
    brief: dict[str, Any],
    evidence: list[dict[str, Any]],
    raw_insights: dict[str, list[dict[str, Any]]] | None = None,
    topic: dict[str, Any] | None = None,
    latest_facts: list[dict[str, Any]] | None = None,
    source_channel: dict[str, Any] | None = None,
    similar_content: list[dict[str, Any]] | None = None,
    risks_uncertainty: list[dict[str, Any]] | None = None,
    knowledge_used: dict[str, Any] | None = None,
    pending: list[str] | None = None,
    timeline: list[dict[str, Any]] | None = None,
    limitations: list[str] | None = None,
    failed_sources: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """A ResearchReport, with every insight group validated against the evidence."""
    groups: dict[str, list[dict[str, Any]]] = {}
    rejected: list[dict[str, Any]] = []
    for group in INSIGHT_GROUPS:
        accepted, refused = validate_insights((raw_insights or {}).get(group), evidence, group=group)
        groups[group] = accepted
        rejected.extend({**item, "group": group} for item in refused)
    by_id = {item["id"] for item in evidence}
    facts = []
    for fact in latest_facts or []:
        cited = [item for item in fact.get("evidence_ids") or [] if item in by_id]
        if cited and str(fact.get("fact") or "").strip():
            facts.append({**fact, "evidence_ids": cited})
        else:
            rejected.append({"text": str(fact.get("fact") or ""), "reason": "Dữ kiện không có bằng chứng", "group": "latest_facts"})
    return {
        "brief": brief,
        "topic": topic or {},
        "latest_facts": facts,
        "source_channel": source_channel or {},
        "similar_content": similar_content or [],
        **groups,
        "risks_uncertainty": risks_uncertainty or [],
        "evidence": evidence,
        "rejected_insights": rejected,
        "coverage": coverage(evidence),
        "knowledge_used": knowledge_used or {},
        "pending": pending or [],
        "timeline": timeline or [],
        # What could not be collected, and why - said, not silently skipped.
        "limitations": limitations or [],
        # Which collector, which source, why - one entry per thing not collected.
        "failed_sources": failed_sources or [],
        "captured_at": _now(),
    }
