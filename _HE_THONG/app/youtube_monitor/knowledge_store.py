"""What the app has learned across videos, so the next plan does not start over.

Four stores, each with its own rhythm:

* Channel Intelligence - one profile per channel. The first meeting is a full
  profile; later ones check freshness and only add the uploads not yet seen.
* Topic Intelligence - facts about a subject, each with its sources, refreshed
  as fast as the subject changes.
* Audience observations - what samples of comments showed, appended with the
  size, source and date of each sample and never merged into a claim about
  the whole audience. Nothing that names a commenter is kept.
* Content patterns - hooks, titles, structures, edit habits seen repeatedly,
  with the examples that show them.

This is the storage and bookkeeping only. Collecting the data is a later
phase, and nothing here calls the network.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from . import freshness
from .research_evidence import strip_personal

PLATFORMS_WITH_CHANNELS = frozenset({"youtube", "tiktok", "facebook", "instagram", "bilibili", "vimeo", "dailymotion"})
SCOPE_TYPES = frozenset({"video", "channel", "topic", "product", "platform", "global"})
PATTERN_TYPES = frozenset({"hook", "title", "thumbnail", "structure", "pacing", "edit", "cta", "format"})
MAX_KNOWN_VIDEO_IDS = 500
MAX_PATTERN_EXAMPLES = 20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slug(text: str) -> str:
    """A stable key for a topic: no accents, no case, words joined by '-'."""
    decomposed = unicodedata.normalize("NFKD", str(text or "").replace("đ", "d").replace("Đ", "D"))
    plain = "".join(char for char in decomposed if not unicodedata.combining(char)).lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:120]


class ChannelIntelligence:
    def __init__(self, database: Any):
        self.database = database

    def get(self, platform: str, native_channel_id: str) -> dict[str, Any] | None:
        if not native_channel_id:
            return None
        profile = self.database.get_channel_profile(platform, native_channel_id)
        if profile:
            profile["freshness"] = self.freshness(profile)
        return profile

    def freshness(
        self,
        profile: dict[str, Any] | None,
        *,
        latest_upload_ids: list[str] | None = None,
        active: bool | None = None,
    ) -> dict[str, Any]:
        """Profile and performance freshness, judged separately."""
        profile = profile or {}
        new_uploads = None
        if latest_upload_ids is not None:
            known = set(profile.get("known_video_ids") or [])
            new_uploads = len([item for item in latest_upload_ids if item not in known])
        profiled_at = max(
            (value for value in (profile.get("last_full_at"), profile.get("last_incremental_at")) if value),
            default=None,
        )
        return {
            "profile": freshness.channel_profile(profiled_at, new_uploads=new_uploads),
            "performance": freshness.channel_performance(profile.get("performance_at"), active=active),
        }

    def refresh_plan(self, profile: dict[str, Any] | None, *, latest_upload_ids: list[str] | None = None) -> dict[str, Any]:
        """What a collector should do next: nothing, add new uploads, or start over.

        A full profile is redone when there is none, or when it is older than
        the policy allows; a fresh one with a few new uploads only needs those.
        """
        if not profile or not profile.get("last_full_at"):
            return {"action": "full", "new_video_ids": list(latest_upload_ids or []), "reason": "Chưa có hồ sơ kênh"}
        state = self.freshness(profile, latest_upload_ids=latest_upload_ids)["profile"]
        known = set(profile.get("known_video_ids") or [])
        new_ids = [item for item in latest_upload_ids or [] if item not in known]
        age_limit = freshness.POLICIES["channel_profile"].max_age.total_seconds()
        if state["state"] == freshness.STALE and (state["age_seconds"] or 0) > age_limit:
            return {"action": "full", "new_video_ids": new_ids, "reason": "; ".join(state["reasons"])}
        if state["state"] == freshness.STALE:
            # Stale because the channel moved on, not because time passed:
            # only the new uploads need reading.
            return {"action": "incremental", "new_video_ids": new_ids, "reason": "; ".join(state["reasons"])}
        return {
            "action": "none", "new_video_ids": new_ids,
            "reason": f"Hồ sơ còn mới ({len(new_ids)} video mới, chưa tới ngưỡng {freshness.NEW_UPLOADS_FOR_PROFILE_REFRESH})",
        }

    def save_full(
        self,
        platform: str,
        native_channel_id: str,
        *,
        channel_name: str = "",
        channel_key: str = "",
        profile: dict[str, Any],
        performance: dict[str, Any] | None = None,
        video_ids: list[str] | None = None,
        last_seen_upload_at: str | None = None,
    ) -> dict[str, Any]:
        self._check(platform, native_channel_id)
        now = _now()
        return self.database.save_channel_profile(
            platform, native_channel_id,
            channel_name=channel_name, channel_key=channel_key, status="complete",
            profile=strip_personal(profile), performance=strip_personal(performance or {}),
            known_video_ids=list(dict.fromkeys(video_ids or []))[-MAX_KNOWN_VIDEO_IDS:],
            last_full_at=now, last_incremental_at=None,
            performance_at=now if performance else None,
            last_seen_upload_at=last_seen_upload_at, last_checked_at=now,
        )

    def update_incremental(
        self,
        platform: str,
        native_channel_id: str,
        *,
        new_video_ids: list[str],
        profile_patch: dict[str, Any] | None = None,
        performance: dict[str, Any] | None = None,
        last_seen_upload_at: str | None = None,
    ) -> dict[str, Any]:
        """Fold in only what is new. The full-profile date is left alone."""
        self._check(platform, native_channel_id)
        existing = self.database.get_channel_profile(platform, native_channel_id)
        if not existing:
            raise ValueError("Chưa có hồ sơ kênh để cập nhật dần; cần phân tích đầy đủ trước")
        now = _now()
        known = list(dict.fromkeys([*existing.get("known_video_ids", []), *new_video_ids]))[-MAX_KNOWN_VIDEO_IDS:]
        values: dict[str, Any] = {
            "profile": {**existing.get("profile", {}), **strip_personal(profile_patch or {})},
            "known_video_ids": known,
            "last_incremental_at": now,
            "last_checked_at": now,
        }
        if performance is not None:
            values.update(performance=strip_personal(performance), performance_at=now)
        if last_seen_upload_at:
            values["last_seen_upload_at"] = last_seen_upload_at
        return self.database.save_channel_profile(platform, native_channel_id, **values)

    def update_performance(self, platform: str, native_channel_id: str, performance: dict[str, Any]) -> dict[str, Any]:
        self._check(platform, native_channel_id)
        now = _now()
        return self.database.save_channel_profile(
            platform, native_channel_id, performance=strip_personal(performance), performance_at=now,
            last_checked_at=now,
        )

    def mark_checked(self, platform: str, native_channel_id: str) -> None:
        """Checked for new uploads and found nothing to change."""
        self._check(platform, native_channel_id)
        self.database.touch_channel_profile(platform, native_channel_id, _now())

    @staticmethod
    def _check(platform: str, native_channel_id: str) -> None:
        if platform not in PLATFORMS_WITH_CHANNELS:
            raise ValueError(f"Nền tảng không có kênh để lập hồ sơ: {platform}")
        if not str(native_channel_id or "").strip():
            raise ValueError("Cần mã kênh gốc của nền tảng, không dùng khoá tự tạo")
        if str(native_channel_id).startswith(("WEB-", "site-", "LOCAL-")):
            raise ValueError("Đây là khoá do app tự tạo, không phải mã kênh thật")


class TopicIntelligence:
    def __init__(self, database: Any):
        self.database = database

    @staticmethod
    def key(topic: str) -> str:
        return slug(topic)

    def get(self, topic_key: str, language: str = "vi") -> dict[str, Any] | None:
        if not topic_key:
            return None
        row = self.database.get_topic_knowledge(topic_key, language)
        if row:
            row["freshness"] = freshness.topic(row.get("refreshed_at"), volatility=row.get("volatility", "evergreen"))
        return row

    def upsert(
        self,
        topic_key: str,
        language: str = "vi",
        *,
        title: str,
        volatility: str = "evergreen",
        summary: str = "",
        facts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Merge new facts into the topic. A fact without a source is refused."""
        if volatility not in freshness.VOLATILITIES:
            raise ValueError(f"Mức biến động không hợp lệ: {volatility}")
        existing = self.database.get_topic_knowledge(topic_key, language) or {}
        merged: dict[str, dict[str, Any]] = {slug(item.get("fact", "")): item for item in existing.get("facts") or []}
        for fact in facts:
            text = " ".join(str(fact.get("fact") or "").split())
            sources = [str(url) for url in fact.get("source_urls") or [] if str(url).strip()]
            if not text or not sources:
                raise ValueError(f"Dữ kiện phải có nội dung và nguồn: {text[:80]!r}")
            merged[slug(text)] = {
                "fact": text[:500],
                "source_urls": sources[:10],
                "status": str(fact.get("status") or "reported"),
                "captured_at": str(fact.get("captured_at") or _now()),
            }
        return self.database.save_topic_knowledge(
            topic_key, language, title=title, volatility=volatility, summary=summary,
            facts=list(merged.values()),
        )


class AudienceObservations:
    def __init__(self, database: Any):
        self.database = database

    def append(
        self,
        scope_type: str,
        scope_key: str,
        *,
        platform: str,
        source_url: str,
        method: str,
        sample_size: int,
        patterns: list[dict[str, Any]],
        captured_at: str | None = None,
        project_id: int | None = None,
        research_report_id: int | None = None,
        channel_ref: str = "",
    ) -> dict[str, Any]:
        """Add one sample. Its size is what the collector counted, never an estimate.

        `channel_ref` ("youtube:UC…") files the sample under the channel whose
        video it came from, so the channel view can sum samples without a copy.
        """
        if scope_type not in SCOPE_TYPES:
            raise ValueError(f"Phạm vi không hợp lệ: {scope_type}")
        if not str(scope_key or "").strip() or not str(source_url or "").strip():
            raise ValueError("Quan sát phải có phạm vi và nguồn")
        try:
            size = int(sample_size)
        except (TypeError, ValueError):
            size = 0
        if size <= 0:
            raise ValueError("sample_size phải là số comment thật sự đã đọc (> 0)")
        return self.database.append_audience_observation(
            scope_type=scope_type, scope_key=scope_key, platform=platform, source_url=source_url,
            method=method, sample_size=size, patterns=strip_personal(list(patterns or [])),
            captured_at=captured_at or _now(), project_id=project_id, research_report_id=research_report_id,
            channel_ref=channel_ref,
        )

    def list(self, scope_type: str, scope_key: str, limit: int = 50) -> list[dict[str, Any]]:
        return self.database.list_audience_observations(scope_type, scope_key, limit=limit)

    def summary(self, scope_type: str, scope_key: str, *, video_published_at: Any = None) -> dict[str, Any]:
        """How much has been observed, and whether a new sample is due."""
        rows = self.list(scope_type, scope_key, limit=500)
        latest = rows[0]["captured_at"] if rows else None
        return {
            "observations": len(rows),
            "total_sample": sum(int(row["sample_size"]) for row in rows),
            "sources": len({row["source_url"] for row in rows}),
            "latest_captured_at": latest,
            "freshness": freshness.comments(latest, video_published_at=video_published_at),
        }


    def channel_summary(self, channel_ref: str) -> dict[str, Any]:
        """All samples under one channel's videos: sizes added up, never extrapolated."""
        rows = self.database.list_channel_audience_observations(channel_ref, limit=1000) if channel_ref else []
        return {
            "observations": len(rows),
            "total_sample": sum(int(row["sample_size"]) for row in rows),
            "videos": len({row["scope_key"] for row in rows}),
            "latest_captured_at": rows[0]["captured_at"] if rows else None,
            "rows": rows,
        }


class ContentPatterns:
    def __init__(self, database: Any):
        self.database = database

    @staticmethod
    def signature(description: str) -> str:
        return hashlib.sha1(slug(description).encode("utf-8")).hexdigest()[:16]

    def record(
        self,
        pattern_type: str,
        scope_type: str,
        scope_key: str,
        *,
        description: str,
        example: dict[str, Any],
        signature: str | None = None,
        seen_at: str | None = None,
    ) -> dict[str, Any]:
        """Note one more example of a pattern; the same example twice counts once."""
        if pattern_type not in PATTERN_TYPES:
            raise ValueError(f"Loại pattern không hợp lệ: {pattern_type}")
        if scope_type not in SCOPE_TYPES:
            raise ValueError(f"Phạm vi không hợp lệ: {scope_type}")
        url = str((example or {}).get("url") or "").strip()
        if not url:
            raise ValueError("Pattern phải kèm ví dụ có đường dẫn")
        key = signature or self.signature(description)
        existing = self.database.get_content_pattern(pattern_type, scope_type, scope_key, key) or {}
        examples = list(existing.get("examples") or [])
        if url not in {item.get("url") for item in examples}:
            examples.append(strip_personal({
                "url": url, "title": str(example.get("title") or "")[:200],
                "metrics": example.get("metrics") or {}, "seen_at": seen_at or _now(),
            }))
        return self.database.save_content_pattern(
            pattern_type=pattern_type, scope_type=scope_type, scope_key=scope_key, signature=key,
            description=" ".join(str(description or "").split())[:500],
            examples=examples[-MAX_PATTERN_EXAMPLES:], evidence_count=len(examples),
            seen_at=seen_at or _now(),
        )

    def list(self, scope_type: str, scope_key: str, pattern_type: str | None = None) -> list[dict[str, Any]]:
        return self.database.list_content_patterns(scope_type, scope_key, pattern_type)
