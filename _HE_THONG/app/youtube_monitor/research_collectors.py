"""Research collectors: what the plan reads beyond the source itself.

Each collector returns evidence (research_evidence.make_evidence), says what it
could not collect (`failed`: collector, source, reason), and never raises for
one source going wrong - a plan is not lost because comments were turned off
on one video. None of them asks a model anything: the counts in a comment
sample, the ranking of similar videos, the dates of a news timeline are all
computed here.

What is still fresh is reused instead of fetched again, by the freshness
policies already in freshness.py: similar videos 7/30 days, comment samples
24 h / 30 days, captions 30 days, web pages by topic volatility. Reuse reads
the database only.

Budgets (approved): 8 similar videos, keeping 5-10; up to 100 comments on the
source and 50 on each of the top 3 similar videos; public captions of the top
3 similar videos. Whisper is not run: a video without public captions is a
recorded gap.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from . import freshness, research_evidence, research_text, web_research
from .channel_research import video_row
from .knowledge_store import AudienceObservations, ContentPatterns
from .youtube_client import YouTubeApiError

COLLECTOR_VERSION = "phase2-2"
OFFICIAL_SUFFIXES = (".gov.vn", ".gov", ".edu.vn", ".edu", ".int", ".mil", ".un.org")
OFFICIAL_HOSTS = frozenset({"chinhphu.vn", "baochinhphu.vn", "who.int", "un.org", "europa.eu"})
CAPTIONS_REUSE = timedelta(days=30)
# How the similar videos are ordered for the comment and caption budget. Views
# are one signal of four, so a huge but loosely related video cannot take the
# whole budget.
RANK_WEIGHTS = {"relevance": 0.40, "freshness": 0.20, "performance": 0.25, "availability": 0.15}
_PUBLISHED = re.compile(
    r'(?:property|name|itemprop)=["\'](?:article:published_time|datePublished|pubdate|publishdate|og:updated_time)["\']'
    r'[^>]*content=["\']([^"\']{8,40})["\']'
    r'|"datePublished"\s*:\s*"([^"]{8,40})"',
    re.IGNORECASE,
)


@dataclass
class Budget:
    similar_videos: int = 8
    keep_min: int = 5
    keep_max: int = 10
    source_comments: int = 100
    similar_comment_videos: int = 3
    similar_comments: int = 50
    transcripts: int = 3
    web_queries: int = 2
    web_read_pages: int = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def failure(collector: str, source: str, reason: str) -> dict[str, str]:
    return {"collector": collector, "source": str(source)[:300], "reason": str(reason)[:300]}


def _days_since(published: Any, now: datetime | None = None) -> float | None:
    """Days since publication, at least 1; None when the date is unknown."""
    moment = freshness.parse_time(published)
    if moment is None:
        return None
    return max(1.0, ((now or _now()) - moment).total_seconds() / 86400)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def comment_patterns(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What a sample shows, as comments-containing / comments-sampled.

    A comment that says "pin pin pin pin" is one comment about "pin": every
    count here is of comments, never of words.
    """
    texts = [str(item.get("text") or "") for item in comments]
    total = len(texts)
    if not total:
        return []
    by_likes = sorted(comments, key=lambda item: int(item.get("like_count") or 0), reverse=True)
    questions = [item for item in by_likes if research_text.is_question(item.get("text", ""))]
    negative = [item for item in by_likes if research_text.is_negative(item.get("text", ""))]
    floor = max(3, math.ceil(0.03 * total))
    return [
        {
            "kind": "questions", "count": len(questions), "of": total,
            "examples": [research_text.excerpt(item["text"]) for item in questions[:3]],
        },
        {
            "kind": "negative", "count": len(negative), "of": total, "method": "từ khoá tiêu cực",
            "examples": [research_text.excerpt(item["text"]) for item in negative[:3]],
        },
        {"kind": "terms", "counting": "comments_containing", "items": research_text.document_frequency(texts, top=10, min_count=floor)},
        {
            "kind": "most_liked",
            "examples": [
                {"text": research_text.excerpt(item["text"]), "like_count": int(item.get("like_count") or 0)}
                for item in by_likes[:3] if item.get("text")
            ],
        },
    ]


def rank_similar(rows: list[dict[str, Any]], *, topic_terms: set[str], now: datetime | None = None) -> list[dict[str, Any]]:
    """Order similar videos by a fixed formula, recording each part of it.

    relevance    - the search engine's own order, and how many topic words the title shares
    freshness    - newer is better, halving at about six months
    performance  - views per day, on a log scale, against the best in the set
    availability - whether it has comments and a running time to read from
    """
    moment = now or _now()
    count = len(rows)
    per_day = []
    for row in rows:
        days = _days_since(row.get("published_at"), moment)
        per_day.append((row.get("view_count") or 0) / days if days else 0.0)
    best = max(per_day, default=0.0)
    ranked = []
    for index, row in enumerate(rows):
        title_terms = set(research_text.tokens(row.get("title", "")))
        overlap = len(title_terms & topic_terms) / max(1, min(len(topic_terms), 5)) if topic_terms else 0.0
        relevance = 0.5 * (1 - index / max(1, count)) + 0.5 * min(1.0, overlap)
        days = _days_since(row.get("published_at"), moment)
        fresh = 1 / (1 + days / 180) if days else 0.0
        performance = math.log1p(per_day[index]) / math.log1p(best) if best > 0 else 0.0
        availability = (0.5 if (row.get("comment_count") or 0) > 0 else 0.0) + (0.5 if row.get("duration_seconds") else 0.0)
        parts = {"relevance": relevance, "freshness": fresh, "performance": performance, "availability": availability}
        score = sum(RANK_WEIGHTS[key] * value for key, value in parts.items())
        ranked.append({
            **row,
            "views_per_day": round(per_day[index], 1) if days else None,
            "score": round(score, 3),
            "score_parts": {key: round(value, 3) for key, value in parts.items()},
            "search_rank": index + 1,
        })
    ranked.sort(key=lambda row: (-row["score"], row["search_rank"]))
    return ranked


def published_at_of(html: str) -> str | None:
    match = _PUBLISHED.search(str(html or ""))
    return (match.group(1) or match.group(2)) if match else None


def is_official(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return host in OFFICIAL_HOSTS or host.endswith(OFFICIAL_SUFFIXES)


def public_captions(url: str, languages: tuple[str, ...] = ("vi", "en")) -> dict[str, Any] | None:
    """The captions a video publishes (its own, else automatic), as plain text.

    yt-dlp reads the caption list without downloading the video; the caption
    file itself is a small text download. None when the video has none.
    """
    try:
        import yt_dlp
    except ImportError:
        return None
    options = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    for source, kind in ((info.get("subtitles") or {}, "captions"), (info.get("automatic_captions") or {}, "auto_captions")):
        for language in (*languages, *(f"{lang}-orig" for lang in languages), *list(source)[:1]):
            tracks = source.get(language) or []
            track = next((item for item in tracks if item.get("ext") == "json3"), None) or next(
                (item for item in tracks if item.get("ext") == "vtt"), None)
            if not track or not track.get("url"):
                continue
            response = httpx.get(track["url"], timeout=15.0, follow_redirects=True)
            response.raise_for_status()
            text = _caption_text(response.text, track["ext"])
            if text:
                return {"text": text, "language": language, "kind": kind}
    return None


def _caption_text(body: str, ext: str) -> str:
    if ext == "json3":
        try:
            events = json.loads(body).get("events") or []
        except ValueError:
            return ""
        parts = ["".join(seg.get("utf8", "") for seg in event.get("segs") or []) for event in events]
        return " ".join(" ".join(parts).split())
    lines = [
        line for line in body.splitlines()
        if line.strip() and "-->" not in line and not line.startswith(("WEBVTT", "Kind:", "Language:")) and not line.strip().isdigit()
    ]
    words = re.sub(r"<[^>]+>", "", " ".join(lines)).split()
    # Automatic captions repeat each line as it scrolls.
    return " ".join(word for index, word in enumerate(words) if index == 0 or word != words[index - 1])


def _fetch_page(url: str) -> str:
    from .page_source import fetch_static

    return fetch_static(url)


def _article_text(html: str) -> str:
    from .source_brief import article_text

    return article_text(html, max_chars=4000)


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------

class Collectors:
    def __init__(
        self,
        database: Any,
        youtube: Any,
        *,
        budget: Budget | None = None,
        web_search: Callable[..., list[dict[str, Any]]] = web_research.search,
        fetch_page: Callable[[str], str] | None = None,
        captions: Callable[[str], dict[str, Any] | None] = public_captions,
    ):
        self.database = database
        self.youtube = youtube
        self.budget = budget or Budget()
        self.web_search = web_search
        self.fetch_page = fetch_page or _fetch_page
        self.captions = captions
        self._reports: list[dict[str, Any]] | None = None

    @property
    def youtube_ready(self) -> bool:
        return bool(getattr(self.youtube, "api_key", ""))

    def _recent_reports(self) -> list[dict[str, Any]]:
        if self._reports is None:
            self._reports = [item.get("report") or {} for item in self.database.list_recent_research_reports(60)]
        return self._reports

    # -- YouTube: similar videos -------------------------------------------

    def similar_videos(
        self, *, query: str, exclude_ids: set[str], language: str = "vi", label: str = "similar",
        topic_terms: set[str] | None = None, volatility: str = "evergreen",
    ) -> dict[str, Any]:
        """Videos on the same subject with their counts, ranked by rank_similar."""
        result: dict[str, Any] = {"videos": [], "evidence": [], "failed": [], "limitations": [],
                                  "reused": False, "query": query, "captured_at": None}
        collector = f"youtube.{label}"
        if not query.strip():
            result["failed"].append(failure(collector, "query", "Không có chủ đề để tìm video tương tự"))
            return result
        reused = self._reusable_similar(query, volatility)
        if reused:
            return {**result, **reused, "reused": True}
        if not self.youtube_ready:
            result["failed"].append(failure(collector, "YouTube Data API", "Chưa cấu hình YouTube API key"))
            return result
        try:
            hits = self.youtube.search_videos(
                query, max_results=self.budget.similar_videos, relevance_language=language or None,
                region_code="VN" if language == "vi" else None,
            )
            ids = [hit["video_id"] for hit in hits if hit["video_id"] not in exclude_ids]
            channel_titles = {hit["video_id"]: hit.get("channel_title", "") for hit in hits}
            fetched = {row["video_id"]: row for row in (video_row(item) for item in self.youtube.get_videos(ids))} if ids else {}
        except YouTubeApiError as exc:
            result["failed"].append(failure(collector, "YouTube Data API", str(exc)))
            return result
        # Keep the search engine's order: it is the relevance signal.
        rows = [{**fetched[video_id], "channel_title": channel_titles.get(video_id, "")} for video_id in ids if video_id in fetched]
        ranked = rank_similar(rows, topic_terms=topic_terms or set())[: self.budget.keep_max]
        if len(ranked) < self.budget.keep_min:
            result["limitations"].append(
                f"Chỉ tìm được {len(ranked)} video tương tự (mục tiêu {self.budget.keep_min}–{self.budget.keep_max})."
            )
        captured = _now().isoformat()
        for row in ranked:
            url = f"https://www.youtube.com/watch?v={row['video_id']}"
            evidence = research_evidence.make_evidence(
                "video_meta", source_url=url, collector=collector, collector_version=COLLECTOR_VERSION,
                native_source_id=row["video_id"], platform="youtube", title=row["title"],
                metrics={
                    **{key: row.get(key) for key in (
                        "view_count", "like_count", "comment_count", "published_at", "duration_seconds",
                        "views_per_day", "score", "search_rank",
                    )},
                    **{f"score_{key}": value for key, value in row["score_parts"].items()},
                },
                sampling={"query": query[:200], "api": "search.list", "order": "relevance"},
                captured_at=captured,
            )
            result["evidence"].append(evidence)
            result["videos"].append({
                **{key: row.get(key) for key in (
                    "video_id", "title", "channel_title", "published_at", "duration_seconds", "view_count",
                    "like_count", "comment_count", "views_per_day", "score", "score_parts", "search_rank",
                )},
                "url": url, "evidence_id": evidence["id"],
            })
        result["captured_at"] = captured
        return result

    def _reusable_similar(self, query: str, volatility: str) -> dict[str, Any] | None:
        for report in self._recent_reports():
            if report.get("similar_query") != query or not report.get("similar_content"):
                continue
            if freshness.similar_videos(report.get("similar_captured_at"), volatility=volatility)["state"] != freshness.FRESH:
                return None
            wanted = {video.get("evidence_id") for video in report["similar_content"]}
            evidence = [item for item in report.get("evidence") or [] if item.get("id") in wanted]
            return {"videos": report["similar_content"], "evidence": evidence, "captured_at": report["similar_captured_at"]}
        return None

    # -- YouTube: comments ---------------------------------------------------

    def comments(
        self, *, video_id: str, url: str, title: str, max_comments: int, channel_ref: str = "",
        project_id: int | None = None, published_at: Any = None,
    ) -> dict[str, Any]:
        """A sample of comments, counted and filed; nothing that names a commenter is kept.

        A sample still fresh by the comments policy is reused; a stale one is
        topped up with a new sample next to it, never overwritten.
        """
        result: dict[str, Any] = {"evidence": [], "patterns": [], "failed": [], "limitations": [], "reused": False}
        scope = f"youtube:{video_id}"
        store = AudienceObservations(self.database)
        latest = next(iter(store.list("video", scope, limit=1)), None)
        if latest and freshness.comments(latest["captured_at"], video_published_at=published_at)["state"] == freshness.FRESH:
            result["evidence"].append(self._comment_evidence(latest, video_id, url, title))
            result["patterns"] = latest["patterns"]
            result["reused"] = True
            return result
        if not self.youtube_ready:
            result["failed"].append(failure("youtube.comments", url, "Chưa cấu hình YouTube API key"))
            return result
        comments: list[dict[str, Any]] = []
        token = None
        try:
            while len(comments) < max_comments:
                page = self.youtube.list_comment_threads(
                    video_id, max_results=min(100, max_comments - len(comments)), order="relevance", page_token=token,
                )
                if page.get("disabled"):
                    result["failed"].append(failure("youtube.comments", url, "Video tắt comment"))
                    return result
                comments.extend(page.get("comments") or [])
                token = page.get("next_page_token")
                if not token:
                    break
        except YouTubeApiError as exc:
            result["failed"].append(failure("youtube.comments", url, str(exc)))
            return result
        comments = comments[:max_comments]
        if not comments:
            result["failed"].append(failure("youtube.comments", url, "Video chưa có comment"))
            return result
        patterns = comment_patterns(comments)
        observation = store.append(
            "video", scope, platform="youtube", source_url=url,
            method=f"commentThreads.list · relevance · top-level · tối đa {max_comments}", sample_size=len(comments),
            patterns=patterns, project_id=project_id, channel_ref=channel_ref,
        )
        result["evidence"].append(self._comment_evidence(observation, video_id, url, title))
        result["patterns"] = patterns
        return result

    @staticmethod
    def _comment_evidence(observation: dict[str, Any], video_id: str, url: str, title: str) -> dict[str, Any]:
        by_kind = {item.get("kind"): item for item in observation.get("patterns") or []}
        return research_evidence.make_evidence(
            "comment_sample", source_url=url, collector="youtube.comments", collector_version=COLLECTOR_VERSION,
            native_source_id=video_id, platform="youtube", title=title, sample_size=int(observation["sample_size"]),
            sampling={"method": observation.get("method", ""), "observation_id": observation.get("id")},
            metrics={"questions": by_kind.get("questions", {}).get("count"), "negative": by_kind.get("negative", {}).get("count")},
            captured_at=observation["captured_at"],
        )

    # -- YouTube: captions ----------------------------------------------------

    def transcripts(self, videos: list[dict[str, Any]]) -> dict[str, Any]:
        """The opening of each top video's own public captions. No Whisper."""
        result: dict[str, Any] = {"evidence": [], "items": [], "failed": [], "limitations": [], "reused": 0}
        for video in videos[: self.budget.transcripts]:
            kept = self._reusable_transcript(video["video_id"])
            if kept:
                result["evidence"].append(kept)
                result["items"].append({"video_id": video["video_id"], "opening": kept["excerpt"], "evidence_id": kept["id"], "reused": True})
                result["reused"] += 1
                continue
            try:
                found = self.captions(video["url"])
            except Exception as exc:  # yt-dlp raises its own types
                result["failed"].append(failure("youtube.captions", video["url"], f"Không đọc được phụ đề: {str(exc)[:160]}"))
                continue
            if not found or not found.get("text"):
                result["failed"].append(failure("youtube.captions", video["url"], "Không có phụ đề công khai (chưa dùng Whisper)"))
                continue
            words = found["text"].split()
            opening = " ".join(words[:45])
            evidence = research_evidence.make_evidence(
                "transcript", source_url=video["url"], collector="youtube.captions", collector_version=COLLECTOR_VERSION,
                native_source_id=video["video_id"], platform="youtube", title=video["title"], excerpt=opening,
                metrics={"words": len(words), "caption_kind": found.get("kind"), "language": found.get("language"),
                         "duration_seconds": video.get("duration_seconds")},
                sampling={"part": "opening 45 words", "source": "public captions via yt-dlp"},
            )
            result["evidence"].append(evidence)
            result["items"].append({"video_id": video["video_id"], "words": len(words), "opening": opening,
                                    "kind": found.get("kind"), "evidence_id": evidence["id"]})
        return result

    def _reusable_transcript(self, video_id: str) -> dict[str, Any] | None:
        for report in self._recent_reports():
            for item in report.get("evidence") or []:
                if item.get("source_kind") == "transcript" and item.get("native_source_id") == video_id:
                    captured = freshness.parse_time(item.get("captured_at"))
                    if captured and _now() - captured < CAPTIONS_REUSE:
                        return item
        return None

    def record_topic_title_patterns(self, topic_key: str, videos: list[dict[str, Any]]) -> None:
        """Title shapes that recur among the similar videos of a topic."""
        titled = [video for video in videos if video.get("title")]
        if len(titled) < 3 or not topic_key:
            return
        store = ContentPatterns(self.database)
        for shape in research_text.title_pattern_counts([video["title"] for video in titled]):
            if shape["count"] < 2 or shape["count"] / len(titled) < 0.2:
                continue
            for index in shape["indices"]:
                video = titled[index]
                store.record(
                    "title", "topic", topic_key, signature=f"title-{shape['key']}",
                    description=f"{shape['label']} ({shape['count']}/{len(titled)} video tương tự)",
                    example={"url": video["url"], "title": video["title"], "metrics": {"view_count": video.get("view_count")}},
                )

    # -- Web / news -----------------------------------------------------------

    def web(self, queries: list[str], *, news: bool = False, volatility: str = "evergreen") -> dict[str, Any]:
        """Pages read for the subject. A search snippet is recorded as a snippet,
        never as an article; only a page actually read counts as one."""
        result: dict[str, Any] = {"evidence": [], "timeline": [], "failed": [], "limitations": [],
                                  "queries": {}, "reused": 0}
        collector = "web.news" if news else "web.search"
        seen: set[str] = set()
        for query in [item for item in queries if item.strip()][: self.budget.web_queries]:
            kept = self._reusable_web(query, volatility)
            if kept is not None:
                result["evidence"].extend(kept["evidence"])
                # What could not be read then is still missing now: reuse
                # carries the gaps along with the pages.
                result["failed"].extend(kept["failed"])
                result["queries"][query] = kept["captured_at"]
                result["reused"] += 1
                continue
            captured = _now().isoformat()
            try:
                hits = self.web_search(query, limit=5)
            except Exception as exc:
                result["failed"].append(failure(collector, f"search: {query}", str(exc)))
                continue
            if not hits:
                result["failed"].append(failure(collector, f"search: {query}", "Không có kết quả tìm kiếm"))
                continue
            result["queries"][query] = captured
            read = 0
            for hit in hits:
                url = hit.get("url") or ""
                if not url or url in seen:
                    continue
                seen.add(url)
                html = ""
                if read < self.budget.web_read_pages:
                    read += 1
                    try:
                        html = self.fetch_page(url)
                    except Exception as exc:
                        result["failed"].append(failure(collector, url, f"Không đọc được trang: {str(exc)[:160]}"))
                text = research_text.excerpt(_article_text(html), 300) if html else ""
                published = published_at_of(html) if html else None
                was_read = bool(text)
                kind = ("official" if is_official(url) else "article") if was_read else "search_result"
                result["evidence"].append(research_evidence.make_evidence(
                    kind, source_url=url, collector=collector, collector_version=COLLECTOR_VERSION,
                    platform="web", title=hit.get("title", ""), excerpt=text or hit.get("snippet", ""),
                    metrics={"published_at": published, "host": hit.get("source"), "read": was_read},
                    sampling={"query": query[:200], "engine": "duckduckgo", "rank": hits.index(hit) + 1},
                    captured_at=captured,
                ))
        for item in result["evidence"]:
            published = (item.get("metrics") or {}).get("published_at")
            if published and item["source_kind"] in {"article", "official"}:
                result["timeline"].append({"date": published, "title": item.get("title", ""),
                                           "url": item["source_url"], "evidence_id": item["id"]})
        result["timeline"].sort(key=lambda entry: entry["date"])
        if news:
            result["limitations"].append("Chưa đối chiếu các nguồn để tìm thông tin mâu thuẫn (cần AI, để Phase 3).")
        return result

    def _reusable_web(self, query: str, volatility: str) -> dict[str, Any] | None:
        for report in self._recent_reports():
            captured = (report.get("web_queries") or {}).get(query)
            if not captured:
                continue
            if freshness.topic(captured, volatility=volatility)["state"] != freshness.FRESH:
                return None
            evidence = [
                item for item in report.get("evidence") or []
                if (item.get("sampling") or {}).get("query") == query[:200] and item.get("collector", "").startswith("web.")
            ]
            urls = {item["source_url"] for item in evidence} | {f"search: {query}"}
            # Every report that carries this same capture - the one that made
            # it and any that reused it - may hold its gaps; none may drop them.
            failed: dict[tuple[str, str], dict[str, Any]] = {}
            for other in self._recent_reports():
                if (other.get("web_queries") or {}).get(query) != captured:
                    continue
                for item in other.get("failed_sources") or []:
                    if str(item.get("collector", "")).startswith("web") and item.get("source") in urls:
                        failed.setdefault((item["source"], item.get("reason", "")), {**item, "reused_from": captured})
            return {"evidence": evidence, "captured_at": captured, "failed": list(failed.values())}
        return None


# ---------------------------------------------------------------------------
# Count statements drawn from the evidence - validated like any insight
# ---------------------------------------------------------------------------

def observation_insights(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Plain count statements from comment samples, each citing its sample.

    `samples` are (evidence, patterns) pairs from `Collectors.comments`. A term
    heard under several videos is stated once over all of them, as comments
    containing it over comments sampled.
    """
    raw: list[dict[str, Any]] = []
    term_hits: dict[str, list[tuple[dict[str, Any], int]]] = {}
    for sample in samples:
        evidence, patterns = sample["evidence"], sample["patterns"]
        size = evidence["sample_size"] or 0
        title = evidence.get("title", "")[:60]
        by_kind = {item["kind"]: item for item in patterns}
        questions = by_kind.get("questions", {})
        if questions.get("count", 0) >= 3:
            raw.append({"text": f"{questions['count']}/{size} comment mẫu dưới “{title}” là câu hỏi", "evidence_ids": [evidence["id"]]})
        negative = by_kind.get("negative", {})
        if negative.get("count", 0) >= 3:
            raw.append({"text": f"{negative['count']}/{size} comment mẫu dưới “{title}” có từ khoá tiêu cực", "evidence_ids": [evidence["id"]]})
        for item in (by_kind.get("terms") or {}).get("items", [])[:5]:
            term_hits.setdefault(item["term"], []).append((evidence, item["count"]))
    for term, hits in sorted(term_hits.items(), key=lambda pair: -sum(count for _, count in pair[1]))[:8]:
        mentioned = sum(count for _, count in hits)
        sampled = sum(evidence["sample_size"] or 0 for evidence, _ in hits)
        where = f"{len(hits)} video" if len(hits) > 1 else f"“{hits[0][0].get('title', '')[:60]}”"
        raw.append({
            "text": f"{mentioned}/{sampled} comment mẫu ({where}) đề cập “{term}”",
            "evidence_ids": [evidence["id"] for evidence, _ in hits],
        })
    return raw


def title_shape_insights(videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """How the similar videos title themselves, counted over the ones found."""
    titled = [video for video in videos if video.get("title") and video.get("evidence_id")]
    if len(titled) < 3:
        return []
    raw = []
    for shape in research_text.title_pattern_counts([video["title"] for video in titled]):
        if shape["count"] >= 2 and shape["count"] / len(titled) >= 0.25:
            raw.append({
                "text": f"{shape['count']}/{len(titled)} video tương tự: {shape['label'].lower()}",
                "evidence_ids": [titled[index]["evidence_id"] for index in shape["indices"]],
            })
    return raw
