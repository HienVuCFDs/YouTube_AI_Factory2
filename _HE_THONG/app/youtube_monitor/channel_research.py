"""Channel Intelligence: one engine, read by the channel manager and the planner.

A channel is researched once and then kept up to date, not researched again
for every video made from it:

    load the profile → how fresh is it? → any new uploads?
        fresh, checked lately      → reuse, no network
        fresh, few new uploads     → reuse (one cheap check)
        many new uploads           → incremental: read the window again, refold
        missing or over 30 days    → full research

Everything numeric - cadence, durations, medians, standouts, title shapes -
is computed here from what the YouTube Data API returned. Nothing is asked of
a model, so nothing is invented. The profile holds the channel's summary and
statistics only; comment samples live in audience_observations and title
shapes in content_patterns, each with their own evidence.

The page that shows a channel only reads (`bundle`). Only an explicit
refresh - the button, or the plan step when it needs the channel - spends
network and quota.
"""

from __future__ import annotations

import re
import statistics
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from . import freshness, research_text
from .knowledge_store import AudienceObservations, ChannelIntelligence, ContentPatterns
from .run_registry import RunRegistry
from .youtube_client import YouTubeApiError, parse_duration

ENGINE_VERSION = "channel-research-1"
SAMPLE_VIDEOS = 50
# A profile checked this recently is reused without even asking for new uploads.
RECHECK_AFTER = timedelta(hours=6)
STANDOUT_RATIO = 1.5
PATTERN_MIN_SHARE = 0.2

STAGES: tuple[tuple[str, str], ...] = (
    ("read_channel", "Đọc dữ liệu kênh"),
    ("check_new_uploads", "Kiểm tra video mới"),
    ("analyze_performance", "Phân tích hiệu suất"),
    ("update_profile", "Cập nhật hồ sơ"),
)
STATUS_LABELS = {
    "none": "Chưa nghiên cứu",
    "running": "Đang nghiên cứu",
    "fresh": "Mới cập nhật",
    "stale": "Cần cập nhật",
    "partial": "Nghiên cứu chưa đầy đủ",
    "unresolved": "Chưa xác định kênh gốc",
    "unsupported": "Chưa hỗ trợ nền tảng này",
    "not_applicable": "Không có kênh để nghiên cứu",
}
RESEARCHABLE = frozenset({"youtube"})
_YOUTUBE_CHANNEL = re.compile(r"UC[\w-]{22}")

# Shared by every caller in this process: the button and the planner see the
# same runs, and a channel is never researched twice at once.
registry = RunRegistry()
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class ChannelResearchError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class ChannelResearchBusy(ChannelResearchError):
    def __init__(self) -> None:
        super().__init__("Kênh này đang được nghiên cứu. Chờ lượt đó xong.", 409)


def channel_ref(platform: str, native_channel_id: str) -> str:
    return f"{platform}:{native_channel_id}"


def _lock_for(ref: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(ref, threading.Lock())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Statistics: plain arithmetic over the videos that were read
# ---------------------------------------------------------------------------

def video_row(item: dict[str, Any]) -> dict[str, Any]:
    """One Data API video, reduced to what the statistics use."""
    snippet = item.get("snippet") or {}
    stats = item.get("statistics") or {}
    thumbnails = snippet.get("thumbnails") or {}

    def count(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    return {
        "video_id": item.get("id"),
        "title": str(snippet.get("title") or ""),
        "published_at": snippet.get("publishedAt"),
        "duration_seconds": parse_duration((item.get("contentDetails") or {}).get("duration")),
        "view_count": count(stats.get("viewCount")),
        "like_count": count(stats.get("likeCount")),
        "comment_count": count(stats.get("commentCount")),
        "tags": [str(tag) for tag in (snippet.get("tags") or [])][:30],
        "has_maxres_thumbnail": "maxres" in thumbnails,
        "thumbnail_url": ((thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default") or {}).get("url") or ""),
    }


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _quartiles(values: list[float]) -> tuple[float | None, float | None]:
    if len(values) < 2:
        return None, None
    q1, _, q3 = statistics.quantiles(values, n=4)
    return float(q1), float(q3)


def compute_profile(videos: list[dict[str, Any]], *, now: datetime | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """(profile statistics, performance) for a window of the channel's uploads."""
    moment = now or _now()
    dated = [video for video in videos if freshness.parse_time(video.get("published_at"))]
    dated.sort(key=lambda video: freshness.parse_time(video["published_at"]), reverse=True)
    times = [freshness.parse_time(video["published_at"]) for video in dated]

    cadence: dict[str, Any] = {}
    if times:
        gaps = [(times[index] - times[index + 1]).total_seconds() / 86400 for index in range(len(times) - 1)]
        span_weeks = max(1.0, (times[0] - times[-1]).total_seconds() / (7 * 86400))
        cadence = {
            "last_upload_at": times[0].isoformat(),
            "uploads_last_30_days": sum(1 for moment_ in times if moment - moment_ <= timedelta(days=30)),
            "median_gap_days": round(_median(gaps), 1) if gaps else None,
            "uploads_per_week": round(len(times) / span_weeks, 2),
        }

    durations = [int(video["duration_seconds"]) for video in videos if video.get("duration_seconds")]
    buckets = {"≤1 phút": 0, "1–4 phút": 0, "4–10 phút": 0, "10–20 phút": 0, ">20 phút": 0}
    for seconds in durations:
        key = ("≤1 phút" if seconds <= 60 else "1–4 phút" if seconds <= 240 else "4–10 phút" if seconds <= 600
               else "10–20 phút" if seconds <= 1200 else ">20 phút")
        buckets[key] += 1
    duration = {
        "median_seconds": int(_median(durations)) if durations else None,
        "buckets": buckets,
        "measured": len(durations),
        "shorts": sum(1 for seconds in durations if seconds <= 60),
    } if durations else {}

    titles = [video["title"] for video in videos if video.get("title")]
    patterns = [
        {key: value for key, value in item.items() if key != "indices"}
        for item in research_text.title_pattern_counts(titles) if item["count"]
    ]
    tag_counts = Counter(tag.lower() for video in videos for tag in dict.fromkeys(video.get("tags") or []))
    title_info = {
        "measured": len(titles),
        "average_length": round(sum(len(title) for title in titles) / len(titles), 1) if titles else None,
        "shapes": patterns,
        "top_terms": research_text.document_frequency(titles, top=12, min_count=2),
    } if titles else {}
    # Tags the channel puts on (nearly) every video say who it is, not what a
    # video is about; they are listed apart so the topics show what varies.
    everywhere = {tag for tag, count in tag_counts.items() if len(videos) >= 5 and count >= 0.8 * len(videos)}
    channel_tags = [{"term": tag, "videos": tag_counts[tag]} for tag in sorted(everywhere, key=lambda tag: -tag_counts[tag])][:12]
    topics = [
        {"term": tag, "videos": count} for tag, count in tag_counts.most_common(40)
        if count >= 2 and tag not in everywhere
    ][:12]

    thumbs = [video for video in videos if video.get("thumbnail_url")]
    thumbnails = {
        "measured": len(thumbs),
        "maxres_available": sum(1 for video in thumbs if video.get("has_maxres_thumbnail")),
    } if thumbs else {}

    profile = {
        "sample": {
            "videos": len(videos),
            "from": times[-1].isoformat() if times else None,
            "to": times[0].isoformat() if times else None,
            "source": "youtube_data_api",
        },
        "cadence": cadence,
        "duration": duration,
        "titles": title_info,
        "topics": topics,
        "channel_tags": channel_tags,
        "thumbnails": thumbnails,
        # The window itself, compact: what the next incremental refresh
        # recomputes from, and the titles the patterns cite.
        "recent_videos": [
            {key: video.get(key) for key in (
                "video_id", "title", "published_at", "duration_seconds", "view_count", "like_count", "comment_count",
            )}
            for video in dated[:SAMPLE_VIDEOS]
        ],
    }
    return {key: value for key, value in profile.items() if value}, compute_performance(dated, now=moment)


def compute_performance(videos: list[dict[str, Any]], *, now: datetime | None = None) -> dict[str, Any]:
    """Views, relative to the channel's own median - never a "score"."""
    moment = now or _now()
    measured = [video for video in videos if video.get("view_count") is not None]
    views = [float(video["view_count"]) for video in measured]
    if not views:
        return {}
    median = _median(views) or 0.0
    q1, q3 = _quartiles(views)

    def age_days(video: dict[str, Any]) -> float:
        published = freshness.parse_time(video.get("published_at"))
        return max(1.0, (moment - published).total_seconds() / 86400) if published else 0.0

    # Relative performance only among videos old enough to have had views.
    settled = [video for video in measured if age_days(video) >= 3]
    standouts = sorted(
        (video for video in settled if median and video["view_count"] >= STANDOUT_RATIO * median),
        key=lambda video: video["view_count"], reverse=True,
    )[:5]
    dated = sorted(
        (video for video in measured if freshness.parse_time(video.get("published_at"))),
        key=lambda video: freshness.parse_time(video["published_at"]), reverse=True,
    )
    recent = [video for video in dated if age_days(video) >= 7][:10]
    recent_median = _median([float(video["view_count"]) for video in recent])
    like_rates = [
        video["like_count"] / video["view_count"]
        for video in measured if video.get("like_count") is not None and video["view_count"]
    ]
    return {
        "measured_videos": len(views),
        "median_views": int(median),
        "p25_views": int(q1) if q1 is not None else None,
        "p75_views": int(q3) if q3 is not None else None,
        "recent_videos": len(recent),
        "recent_median_views": int(recent_median) if recent_median is not None else None,
        "recent_vs_overall": round(recent_median / median, 2) if recent_median is not None and median else None,
        "median_like_rate_percent": round(100 * _median(like_rates), 2) if like_rates else None,
        "standouts": [
            {
                "video_id": video["video_id"], "title": video["title"][:200], "view_count": video["view_count"],
                "times_median": round(video["view_count"] / median, 1), "published_at": video.get("published_at"),
            }
            for video in standouts
        ],
    }


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------

class ChannelResearchService:
    def __init__(self, database: Any, youtube: Any):
        self.database = database
        self.youtube = youtube
        self.store = ChannelIntelligence(database)

    # -- identity ---------------------------------------------------------

    def resolve(self, ref: str) -> dict[str, Any]:
        """The canonical channel behind any key: a row key, "youtube:UC…", or a video id.

        No network. A synthetic row ("WEB-YOUTUBE-…") resolves through the
        native channel id its videos carry; old rows are neither changed nor
        removed, only read.
        """
        text = str(ref or "").strip()
        platform = native = ""
        name = ""
        if ":" in text and text.split(":", 1)[0] in {"youtube", "tiktok", "facebook", "instagram", "bilibili"}:
            platform, native = text.split(":", 1)
        elif _YOUTUBE_CHANNEL.fullmatch(text):
            platform, native = "youtube", text
        elif self.database.get_channel(text):
            natives = self.database.native_channels_of_row(text)
            if natives:
                platform, native = natives[0]["platform"], natives[0]["native_channel_id"]
                name = natives[0].get("channel_name") or ""
        elif self.database.get_video(text):
            video = self.database.get_video(text) or {}
            platform = str(video.get("source_platform") or "")
            native = str(video.get("native_channel_id") or "")
            name = str(video.get("native_channel_name") or "")
        if not native:
            row = self.database.get_channel(text)
            guessed = "youtube" if text.upper().startswith("WEB-YOUTUBE") else ""
            # A website, the uploads folder, the ideas bucket: rows the app made
            # to hold sources that have no channel at all.
            # A catch-all extractor ("WEB-HTML5MED-…", "WEB-GENERIC-…") read a page, not a channel.
            applicable = not (
                text.startswith(("site-", "LOCAL-", "WEB-HTML5", "WEB-GENERIC")) or text == "UC_YOUTUBE_AI_FACTORY_IDEAS"
            )
            return {
                "ref": "", "input": text, "resolved": False, "platform": guessed, "native_channel_id": "",
                "row_keys": [text] if row else [], "channel_row": row, "channel_name": (row or {}).get("title", ""),
                "applicable": applicable,
                "reason": "Chưa biết mã kênh gốc của kênh này" if applicable else "Nguồn này là trang web hoặc tệp, không thuộc kênh nào",
            }
        keys = self.database.row_keys_of_native_channel(platform, native)
        if text and self.database.get_channel(text) and text not in keys:
            keys.append(text)
        row = next((self.database.get_channel(key) for key in keys if self.database.get_channel(key)), None)
        return {
            "ref": channel_ref(platform, native), "input": text, "resolved": True,
            "platform": platform, "native_channel_id": native, "row_keys": keys, "channel_row": row,
            "channel_name": name or (row or {}).get("title", ""), "reason": "",
        }

    def resolve_with_lookup(self, ref: str, *, identify: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
        """resolve(), and for an unresolved row, look up one of its videos (network)."""
        identity = self.resolve(ref)
        if identity["resolved"] or not identity["row_keys"]:
            return identity
        for video in self.database.list_videos(channel_id=identity["row_keys"][0], limit=3):
            found = identify(str(video["youtube_video_id"]))
            if found.get("native_channel_id"):
                return self.resolve(ref)
        return identity

    # -- read only --------------------------------------------------------

    def summary(self, identity: dict[str, Any]) -> dict[str, Any]:
        """Research status for a card: computed from the DB, never fetched."""
        if not identity.get("resolved"):
            state = "unresolved" if identity.get("applicable", True) else "not_applicable"
            return {"state": state, "label": STATUS_LABELS[state], "reason": identity.get("reason"), "coverage": {}}
        ref = identity["ref"]
        if identity["platform"] not in RESEARCHABLE:
            state = "unsupported"
            return {"state": state, "label": STATUS_LABELS[state], "coverage": {}}
        profile = self.store.get(identity["platform"], identity["native_channel_id"])
        audience = AudienceObservations(self.database).channel_summary(ref)
        running, last = registry.state(("channel", ref))
        if running:
            state = "running"
        elif not profile:
            state = "none"
        elif profile.get("status") != "complete":
            state = "partial"
        elif freshness.STALE in (profile["freshness"]["profile"]["state"], profile["freshness"]["performance"]["state"]):
            state = "stale"
        else:
            state = "fresh"
        updated = max(
            (value for value in ((profile or {}).get("last_full_at"), (profile or {}).get("last_incremental_at"),
                                 (profile or {}).get("performance_at")) if value),
            default=None,
        )
        return {
            "state": state,
            "label": STATUS_LABELS[state],
            "updated_at": updated,
            "checked_at": (profile or {}).get("last_checked_at"),
            "profile_version": (profile or {}).get("version"),
            "freshness": (profile or {}).get("freshness"),
            "coverage": {
                "videos": ((profile or {}).get("profile") or {}).get("sample", {}).get("videos", 0),
                "comments_sampled": audience["total_sample"],
                "comment_videos": audience["videos"],
            },
            "run": running,
            "last_run": last,
        }

    def bundle(self, ref: str) -> dict[str, Any]:
        """Everything the channel page shows, assembled here - the page does no joining."""
        identity = self.resolve(ref)
        summary = self.summary(identity)
        row = identity.get("channel_row") or {}
        profile = (
            self.store.get(identity["platform"], identity["native_channel_id"])
            if identity.get("resolved") and identity["platform"] in RESEARCHABLE else None
        ) or {}
        body = profile.get("profile") or {}
        channel_info = body.get("channel") or {}
        performance = profile.get("performance") or {}
        audience = AudienceObservations(self.database).channel_summary(identity.get("ref") or "")
        patterns = ContentPatterns(self.database).list("channel", identity["ref"]) if identity.get("resolved") else []
        return {
            "identity": {key: identity.get(key) for key in (
                "ref", "input", "resolved", "platform", "native_channel_id", "row_keys", "channel_name", "reason",
            )},
            "overview": {
                "title": channel_info.get("title") or row.get("title") or identity.get("channel_name"),
                "platform": identity.get("platform"),
                "native_channel_id": identity.get("native_channel_id"),
                "subscriber_count": channel_info.get("subscriber_count", row.get("subscriber_count")),
                "video_count": channel_info.get("video_count", row.get("video_count")),
                "recent_median_views": performance.get("recent_median_views"),
                "channel_url": row.get("channel_url") or (
                    f"https://www.youtube.com/channel/{identity['native_channel_id']}"
                    if identity.get("platform") == "youtube" and identity.get("native_channel_id") else ""
                ),
            },
            "monitoring": {
                "rows": [self._monitoring_row(key) for key in identity.get("row_keys") or []],
                **self.database.channel_monitoring_summary(identity.get("row_keys") or []),
            },
            "research": {
                "summary": summary,
                "channel": {key: value for key, value in channel_info.items() if value not in (None, "", [])},
                "profile": {key: value for key, value in body.items() if key not in {"channel", "recent_videos"} and value},
                "performance": {key: value for key, value in performance.items() if value not in (None, [], {})},
                "patterns": [
                    {
                        "pattern_type": item["pattern_type"], "description": item["description"],
                        "evidence_count": item["evidence_count"], "examples": item["examples"][:3],
                        "last_seen_at": item["last_seen_at"],
                    }
                    for item in patterns
                ],
                "audience": {
                    "observations": audience["observations"],
                    "total_sample": audience["total_sample"],
                    "videos": audience["videos"],
                    "latest_captured_at": audience["latest_captured_at"],
                    "samples": [
                        {key: row_.get(key) for key in ("scope_key", "source_url", "method", "sample_size", "captured_at", "patterns")}
                        for row_ in audience["rows"][:10]
                    ],
                },
            },
            "stages": [{"key": key, "label": label} for key, label in STAGES],
        }

    def _monitoring_row(self, key: str) -> dict[str, Any]:
        row = self.database.get_channel(key) or {}
        return {"channel_key": key, **{field: row.get(field) for field in (
            "title", "tracking_enabled", "sync_status", "last_sync_at", "last_error", "group_name",
        )}}

    # -- work -------------------------------------------------------------

    def refresh(self, ref: str, *, mode: str = "auto", identify: Callable[[str], dict[str, Any]] | None = None) -> dict[str, Any]:
        """The button: refused while the same channel is being researched."""
        identity = self.resolve_with_lookup(ref, identify=identify) if identify else self.resolve(ref)
        return self._run(identity, mode=mode, blocking=False)

    def ensure(self, identity: dict[str, Any], *, mode: str = "auto") -> dict[str, Any]:
        """The planner: waits for a refresh already under way, then reuses it."""
        return self._run(identity, mode=mode, blocking=True)

    def _run(self, identity: dict[str, Any], *, mode: str, blocking: bool) -> dict[str, Any]:
        if not identity.get("resolved"):
            raise ChannelResearchError(identity.get("reason") or "Chưa xác định được kênh gốc", 422)
        if identity["platform"] not in RESEARCHABLE:
            raise ChannelResearchError(
                f"Chưa hỗ trợ nghiên cứu kênh {identity['platform']}: chưa có nguồn dữ liệu chính thức cho nền tảng này.", 422,
            )
        ref = identity["ref"]
        lock = _lock_for(ref)
        if not lock.acquire(blocking=blocking):
            raise ChannelResearchBusy()
        key = ("channel", ref)
        try:
            registry.claim(key, stage=STAGES[0][0], stages_done=[], mode=mode)
            outcome: dict[str, Any] = {"status": "failed", "error": "Dừng giữa chừng."}
            try:
                result = self._research(identity, mode=mode, progress=lambda stage, done: registry.update(key, stage=stage, stages_done=done))
                outcome = {"status": "success", "result": result["status"], "profile_version": result.get("profile_version")}
                return result
            except YouTubeApiError as exc:
                outcome = {"status": "failed", "error": str(exc)[:300], "status_code": exc.status_code or 502}
                raise ChannelResearchError(f"YouTube API: {str(exc)[:300]}", 502) from None
            except ChannelResearchError as exc:
                outcome = {"status": "failed", "error": str(exc)[:300], "status_code": exc.status_code}
                raise
            finally:
                registry.finish(key, outcome)
        finally:
            lock.release()

    def _research(self, identity: dict[str, Any], *, mode: str, progress: Callable[[str, list[str]], None]) -> dict[str, Any]:
        platform, native = identity["platform"], identity["native_channel_id"]
        if not getattr(self.youtube, "api_key", ""):
            raise ChannelResearchError("Chưa cấu hình YouTube API key nên chưa nghiên cứu kênh được.", 424)
        done: list[str] = []

        def step(name: str) -> None:
            progress(name, list(done))

        def finished(name: str) -> None:
            done.append(name)
            progress(name, list(done))

        step("read_channel")
        profile = self.store.get(platform, native)
        checked = freshness.parse_time((profile or {}).get("last_checked_at"))
        if (
            mode == "auto" and profile and profile.get("status") == "complete"
            and profile["freshness"]["profile"]["state"] == freshness.FRESH
            and profile["freshness"]["performance"]["state"] == freshness.FRESH
            and checked and _now() - checked < RECHECK_AFTER
        ):
            finished("read_channel")
            return self._result("reused", profile, network=False, units=0)

        needs_full = mode == "full" or not profile or profile.get("status") != "complete" or (
            profile["freshness"]["profile"]["state"] == freshness.STALE
            and (profile["freshness"]["profile"]["age_seconds"] or 0) > freshness.POLICIES["channel_profile"].max_age.total_seconds()
        )
        units = 0
        channel_info = ((profile or {}).get("profile") or {}).get("channel") or {}
        if needs_full:
            channel = self.youtube.get_channel_by_id(native)
            units += 1
            channel_info = {
                "title": channel.get("title", ""),
                "description": str(channel.get("description") or "")[:500],
                "custom_url": channel.get("handle", ""),
                "subscriber_count": channel.get("subscriber_count"),
                "video_count": channel.get("video_count"),
                "published_at": channel.get("published_at"),
                "thumbnail_url": channel.get("thumbnail_url", ""),
            }
        finished("read_channel")

        step("check_new_uploads")
        uploads = "UU" + native[2:] if native.startswith("UC") else ""
        ids = self.youtube.list_upload_video_ids(uploads, max_videos=SAMPLE_VIDEOS)
        units += 1
        decision = {"action": "full", "new_video_ids": ids} if needs_full else self.store.refresh_plan(profile, latest_upload_ids=ids)
        finished("check_new_uploads")

        if decision["action"] == "none" and profile["freshness"]["performance"]["state"] == freshness.FRESH:
            self.store.mark_checked(platform, native)
            finished("analyze_performance")
            finished("update_profile")
            return self._result("reused", self.store.get(platform, native), network=True, units=units, new_uploads=len(decision["new_video_ids"]))

        step("analyze_performance")
        videos = [video_row(item) for item in self.youtube.get_videos(ids)]
        if ids:
            units += (len(ids) + 49) // 50  # one videos call per 50 ids
        stats, performance = compute_profile(videos)
        stats["channel"] = channel_info
        finished("analyze_performance")

        step("update_profile")
        newest = (stats.get("cadence") or {}).get("last_upload_at")
        name = channel_info.get("title") or identity.get("channel_name") or ""
        key = next((row for row in identity.get("row_keys") or []), "")
        if decision["action"] == "none":
            # Only the counts were old: the profile stays, its numbers move.
            saved = self.store.update_performance(platform, native, performance)
            status = "reused"
        elif decision["action"] == "incremental":
            saved = self.store.update_incremental(
                platform, native, new_video_ids=decision["new_video_ids"], profile_patch=stats,
                performance=performance, last_seen_upload_at=newest,
            )
            status = "incremental"
        else:
            saved = self.store.save_full(
                platform, native, channel_name=name, channel_key=key, profile=stats,
                performance=performance, video_ids=ids, last_seen_upload_at=newest,
            )
            status = "new" if not profile else "refreshed"
        self._record_title_patterns(identity["ref"], videos)
        finished("update_profile")
        return self._result(status, saved, network=True, units=units, new_uploads=len(decision.get("new_video_ids") or []))

    def _record_title_patterns(self, ref: str, videos: list[dict[str, Any]]) -> None:
        """Title shapes that recur, each with the titles that show it.

        Only shapes seen in at least two titles and a fifth of the sample: one
        title in a question is not a habit.
        """
        titled = [video for video in videos if video.get("title")]
        if not titled:
            return
        store = ContentPatterns(self.database)
        for shape in research_text.title_pattern_counts([video["title"] for video in titled]):
            if shape["count"] < 2 or shape["count"] / len(titled) < PATTERN_MIN_SHARE:
                continue
            description = f"{shape['label']} ({shape['count']}/{len(titled)} video gần nhất)"
            signature = f"title-{shape['key']}"
            for index in shape["indices"][:20]:
                video = titled[index]
                store.record(
                    "title", "channel", ref, description=description, signature=signature,
                    example={
                        "url": f"https://www.youtube.com/watch?v={video['video_id']}",
                        "title": video["title"], "metrics": {"view_count": video.get("view_count")},
                    },
                )

    def _result(self, status: str, profile: dict[str, Any] | None, *, network: bool, units: int, new_uploads: int = 0) -> dict[str, Any]:
        profile = profile or {}
        return {
            "status": status,
            "profile_ref": f"channel_profiles:{profile.get('id')}" if profile.get("id") else "",
            "profile_version": profile.get("version"),
            "network": network,
            "quota_units": units,
            "new_uploads": new_uploads,
            "engine_version": ENGINE_VERSION,
        }
