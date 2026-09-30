"""Who a source is on its own platform, read the same way for old and new rows.

A video row is keyed by an id of the app's own for anything imported by link
("web-…"), and until now its channel was too ("WEB-YOUTUBE-…"). Research
needs the platform's own ids - to look the channel up, to fetch the video's
comments - so this reads them from the identity columns, falls back to what
older rows kept in their payload or their URL, and says plainly when the
channel is not known yet instead of passing a made-up key off as a real one.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from .source_links import platform_of
from .youtube_client import parse_video_reference

NATIVE = "native"          # the platform's own channel id is known
SYNTHETIC = "synthetic"    # only the app's own grouping key is known
NONE = "none"              # a page, an upload or an idea: there is no channel

_YOUTUBE_CHANNEL = re.compile(r"UC[\w-]{22}")
_CHANNEL_PLATFORMS = frozenset({"youtube", "tiktok", "facebook", "instagram", "bilibili", "vimeo", "dailymotion"})


def _platform_from_row(video: dict[str, Any], payload: dict[str, Any]) -> str:
    stated = str(video.get("source_platform") or "").strip().lower()
    if stated:
        return stated
    video_id = str(video.get("youtube_video_id") or "")
    if video_id.startswith("idea-"):
        return "idea"
    if video_id.startswith(("upload-", "local-", "file-")):
        return "upload"
    raw_platform = str(payload.get("platform") or "").strip()
    if raw_platform:
        return platform_of(raw_platform)
    if payload.get("kind") == "youtube#video" or _YOUTUBE_CHANNEL.fullmatch(str(video.get("youtube_channel_id") or "")):
        return "youtube"
    url = str(video.get("video_url") or "").lower()
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    return ""


def describe(video: dict[str, Any] | None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """The identity of one video row, with where each part came from."""
    video = dict(video or {})
    payload = dict(payload or {})
    platform = _platform_from_row(video, payload)
    row_channel = str(video.get("youtube_channel_id") or "")

    native_video = str(video.get("native_video_id") or "").strip()
    if not native_video and platform == "youtube":
        if payload.get("kind") == "youtube#video" or not str(video.get("youtube_video_id") or "").startswith("web-"):
            native_video = str(video.get("youtube_video_id") or "")
        else:
            native_video = str(payload.get("native_id") or "")
            if not native_video:
                try:
                    native_video = parse_video_reference(str(video.get("video_url") or ""))
                except ValueError:
                    native_video = ""
    elif not native_video and platform in _CHANNEL_PLATFORMS:
        native_video = str(payload.get("native_id") or "")

    native_channel = str(video.get("native_channel_id") or "").strip()
    if not native_channel and platform == "youtube" and _YOUTUBE_CHANNEL.fullmatch(row_channel):
        native_channel = row_channel

    if platform not in _CHANNEL_PLATFORMS:
        channel_identity = NONE
    elif native_channel:
        channel_identity = NATIVE
    else:
        channel_identity = SYNTHETIC

    # Only a platform whose channel can be looked up is worth a lookup; a
    # page or an upload has nothing more to find.
    needs_refresh = platform in _CHANNEL_PLATFORMS and (not native_channel or not native_video)
    return {
        "platform": platform or "unknown",
        "extractor": str(video.get("source_extractor") or payload.get("platform") or ""),
        "native_video_id": native_video,
        "native_channel_id": native_channel,
        "channel_name": str(video.get("native_channel_name") or ""),
        "channel_key": row_channel,
        "channel_identity": channel_identity,
        "metrics": {
            "view_count": video.get("view_count"),
            "like_count": video.get("like_count"),
            "comment_count": video.get("comment_count"),
            "published_at": video.get("published_at"),
            "duration_seconds": video.get("duration_seconds"),
            "source": str(video.get("metrics_source") or ""),
            # When these counts were read - not when the row last changed.
            "captured_at": video.get("metrics_captured_at") or (
                video.get("last_metadata_sync_at")
                if any(video.get(key) is not None for key in ("view_count", "like_count", "comment_count"))
                else None
            ),
        },
        "checked_at": video.get("identity_checked_at"),
        "needs_refresh": needs_refresh,
    }


def of(database: Any, video_id: str) -> dict[str, Any]:
    video = database.get_video(video_id) or {}
    return describe(video, database.get_video_raw_payload(video_id) if video else {})


def refresh(
    database: Any,
    video_id: str,
    *,
    youtube: Any = None,
    probe: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Look up what an older row never stored, and record it.

    YouTube is asked through the Data API first (one quota unit); yt-dlp is
    the fallback, and the only way for other platforms. The row's keys are
    never changed - projects, transcripts and analyses hang off them - only
    the identity columns and the counts. Never raises: a lookup that fails
    leaves the identity as it was, with the reason attached.
    """
    identity = of(database, video_id)
    if not identity["needs_refresh"]:
        return {**identity, "refreshed": False, "refresh_error": ""}
    video = database.get_video(video_id) or {}
    errors: list[str] = []

    if identity["platform"] == "youtube" and identity["native_video_id"] and youtube is not None and getattr(youtube, "api_key", ""):
        try:
            items = youtube.get_videos([identity["native_video_id"]])
        except Exception as exc:  # the API is the preferred path, not the only one
            items = []
            errors.append(f"YouTube Data API: {str(exc)[:160]}")
        if items:
            item = items[0]
            snippet = item.get("snippet") or {}
            statistics = item.get("statistics") or {}
            database.set_video_source_identity(
                video_id,
                source_platform="youtube",
                native_video_id=str(item.get("id") or identity["native_video_id"]),
                native_channel_id=str(snippet.get("channelId") or ""),
                native_channel_name=str(snippet.get("channelTitle") or ""),
                metrics_source="youtube_data_api",
            )
            database.update_video_metrics(
                video_id,
                view_count=_int(statistics.get("viewCount")),
                like_count=_int(statistics.get("likeCount")),
                comment_count=_int(statistics.get("commentCount")),
                published_at=snippet.get("publishedAt"),
            )
            return {**of(database, video_id), "refreshed": True, "refresh_error": ""}

    if probe is not None and video.get("video_url"):
        try:
            details = probe(str(video["video_url"]))
        except Exception as exc:
            details = {}
            errors.append(f"yt-dlp: {str(exc)[:160]}")
        if details:
            database.set_video_source_identity(
                video_id,
                source_platform=str(details.get("platform_slug") or identity["platform"]),
                source_extractor=str(details.get("platform") or ""),
                native_video_id=str(details.get("native_id") or ""),
                native_channel_id=str(details.get("native_channel_id") or ""),
                native_channel_name=str(details.get("channel_name") or ""),
                metrics_source="yt_dlp" if details.get("view_count") is not None else "",
            )
            database.update_video_metrics(
                video_id,
                view_count=details.get("view_count"),
                like_count=details.get("like_count"),
                comment_count=details.get("comment_count"),
                published_at=details.get("published_at"),
            )
            return {**of(database, video_id), "refreshed": True, "refresh_error": "; ".join(errors)}

    return {**identity, "refreshed": False, "refresh_error": "; ".join(errors) or "Không có cách tra cứu"}


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
