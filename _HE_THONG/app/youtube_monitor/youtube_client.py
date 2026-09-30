from __future__ import annotations

import re
from urllib.parse import urlparse
from typing import Any

import httpx

from .youtube_quota import QuotaExceeded


API_BASE = "https://www.googleapis.com/youtube/v3"


class YouTubeApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class YouTubeQuotaExceeded(YouTubeApiError):
    """Refused before the call: it would take the day over its quota."""


def parse_channel_reference(reference: str) -> tuple[str, str]:
    value = reference.strip()
    if not value:
        raise ValueError("Channel reference không được để trống")

    if re.fullmatch(r"UC[\w-]{20,30}", value):
        return "id", value
    if value.startswith("@"):
        return "forHandle", value

    if "://" not in value and value.lower().startswith(("youtube.com/", "www.youtube.com/")):
        value = f"https://{value}"
    parsed = urlparse(value if "://" in value else f"https://www.youtube.com/{value.lstrip('/')}" )
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        raise ValueError("Không nhận diện được URL kênh YouTube")

    if parts[0] == "channel" and len(parts) > 1:
        return "id", parts[1]
    if parts[0].startswith("@"):
        return "forHandle", parts[0]
    if parts[0] == "user" and len(parts) > 1:
        return "forUsername", parts[1]
    if parts[0] == "c" and len(parts) > 1:
        return "forHandle", parts[1]

    raise ValueError("Hãy dùng channel ID, @handle hoặc URL /channel/... của YouTube")


def parse_video_reference(reference: str) -> str:
    """Accept a normal watch, Shorts, embed or youtu.be URL and return its video ID."""
    value = reference.strip()
    if not value:
        raise ValueError("URL video YouTube không được để trống")
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")
    parts = [part for part in parsed.path.split("/") if part]
    candidate = ""
    if host == "youtu.be" and parts:
        candidate = parts[0]
    elif host.endswith("youtube.com"):
        if parsed.path == "/watch":
            candidate = next((part.split("=", 1)[1] for part in parsed.query.split("&") if part.startswith("v=")), "")
        elif parts and parts[0] in {"shorts", "embed", "live"} and len(parts) > 1:
            candidate = parts[1]
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        return candidate
    raise ValueError("Hãy dán URL video YouTube hợp lệ (watch, youtu.be hoặc Shorts)")


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_duration(value: str | None) -> int | None:
    if not value:
        return None
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not match:
        return None
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def thumbnail_url(thumbnails: dict[str, Any] | None) -> str:
    if not thumbnails:
        return ""
    for key in ("maxres", "standard", "high", "medium", "default"):
        if thumbnails.get(key, {}).get("url"):
            return thumbnails[key]["url"]
    return ""


class YouTubeClient:
    def __init__(self, api_key: str, timeout: float = 30.0, quota: Any = None):
        self.api_key = api_key.strip()
        self.timeout = timeout
        # A YouTubeQuota (youtube_quota.py) prices and records every call;
        # without one the client behaves as it always did.
        self.quota = quota

    def __repr__(self) -> str:
        # Never the key, not even in a debugger or a log of the object.
        return f"YouTubeClient(api_key={'set' if self.api_key else 'missing'}, quota={'on' if self.quota else 'off'})"

    def _redact(self, value: Any) -> str:
        """The text with the API key taken out, wherever it appears."""
        text = str(value or "")
        if self.api_key:
            text = text.replace(self.api_key, "***")
        return re.sub(r"([?&]key=)[^&\s\"']+", r"\1***", text)

    def _get(self, resource: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise YouTubeApiError(
                "Thiếu YOUTUBE_API_KEY. Hãy sao chép .env.example thành .env và thêm API key."
            )
        if self.quota is not None:
            try:
                self.quota.check(resource)
            except QuotaExceeded as exc:
                raise YouTubeQuotaExceeded(str(exc), status_code=429) from exc
        request_params = {**params, "key": self.api_key}
        try:
            response = httpx.get(
                f"{API_BASE}/{resource}",
                params=request_params,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            # Never reached Google, so nothing was spent. httpx can quote the
            # request URL - key included - in its message, hence the redaction.
            raise YouTubeApiError(f"Không kết nối được YouTube API: {self._redact(exc)}") from None

        if response.status_code >= 400:
            try:
                payload = response.json()
                message = payload.get("error", {}).get("message", response.text)
                reasons = [item.get("reason", "") for item in payload.get("error", {}).get("errors", [])]
            except (ValueError, AttributeError):
                message, reasons = response.text, []
            if self.quota is not None:
                self.quota.record(resource, ok=False, status_code=response.status_code, note=",".join(reasons))
            error = YouTubeApiError(
                f"YouTube API lỗi {response.status_code}: {self._redact(message)}",
                status_code=response.status_code,
            )
            error.reasons = reasons  # type: ignore[attr-defined]
            raise error
        if self.quota is not None:
            self.quota.record(resource, ok=True)
        return response.json()

    def get_channel(self, reference: str) -> dict[str, Any]:
        selector, value = parse_channel_reference(reference)
        return self.get_channel_by_selector(selector, value)

    def get_channel_by_id(self, channel_id: str) -> dict[str, Any]:
        return self.get_channel_by_selector("id", channel_id)

    def get_channel_by_selector(self, selector: str, value: str) -> dict[str, Any]:
        payload = self._get(
            "channels",
            {"part": "snippet,contentDetails,statistics", selector: value},
        )
        items = payload.get("items", [])
        if not items:
            raise YouTubeApiError(f"Không tìm thấy kênh YouTube: {value}", status_code=404)

        item = items[0]
        snippet = item.get("snippet", {})
        content = item.get("contentDetails", {})
        statistics = item.get("statistics", {})
        channel_id = item["id"]
        return {
            "youtube_channel_id": channel_id,
            "handle": snippet.get("customUrl", ""),
            "channel_url": f"https://www.youtube.com/channel/{channel_id}",
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "thumbnail_url": thumbnail_url(snippet.get("thumbnails")),
            "uploads_playlist_id": content.get("relatedPlaylists", {}).get("uploads", ""),
            "published_at": snippet.get("publishedAt"),
            "subscriber_count": _int_or_none(statistics.get("subscriberCount")),
            "video_count": _int_or_none(statistics.get("videoCount")),
            "raw_payload": item,
        }

    def list_upload_video_ids(self, uploads_playlist_id: str, max_videos: int | None = 100) -> list[str]:
        if not uploads_playlist_id:
            return []
        ids: list[str] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "part": "snippet,contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self._get("playlistItems", params)
            for item in payload.get("items", []):
                video_id = item.get("contentDetails", {}).get("videoId")
                if video_id and video_id not in ids:
                    ids.append(video_id)
                    if max_videos and len(ids) >= max_videos:
                        return ids
            page_token = payload.get("nextPageToken")
            if not page_token:
                return ids

    def get_videos(self, video_ids: list[str]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for start in range(0, len(video_ids), 50):
            batch = video_ids[start : start + 50]
            payload = self._get(
                "videos",
                {
                    "part": "snippet,contentDetails,statistics,status",
                    "id": ",".join(batch),
                },
            )
            results.extend(payload.get("items", []))
        return results

    # -- Research foundation. Official API first for YouTube metrics, search
    # -- and comments; yt-dlp stays the metadata/transcript fallback.

    def search_videos(
        self,
        query: str,
        *,
        max_results: int = 10,
        published_after: str | None = None,
        region_code: str | None = None,
        relevance_language: str | None = None,
        order: str = "relevance",
        video_duration: str | None = None,
    ) -> list[dict[str, Any]]:
        """Videos matching a query. 100 quota units per call - use sparingly.

        Returns ids and snippets only; counts come from get_videos (1 unit per
        50 videos), which is far cheaper than searching again.
        """
        text = " ".join(str(query or "").split())
        if not text:
            return []
        params: dict[str, Any] = {
            "part": "snippet",
            "type": "video",
            "q": text[:200],
            "maxResults": max(1, min(int(max_results or 10), 50)),
            "order": order if order in {"relevance", "date", "viewCount", "rating"} else "relevance",
        }
        if published_after:
            params["publishedAfter"] = published_after
        if region_code:
            params["regionCode"] = region_code
        if relevance_language:
            params["relevanceLanguage"] = relevance_language
        if video_duration in {"short", "medium", "long"}:
            params["videoDuration"] = video_duration
        payload = self._get("search", params)
        found: list[dict[str, Any]] = []
        for item in payload.get("items", []):
            video_id = (item.get("id") or {}).get("videoId")
            snippet = item.get("snippet") or {}
            if not video_id:
                continue
            found.append({
                "video_id": video_id,
                "channel_id": snippet.get("channelId", ""),
                "channel_title": snippet.get("channelTitle", ""),
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "published_at": snippet.get("publishedAt"),
                "thumbnail_url": thumbnail_url(snippet.get("thumbnails")),
            })
        return found

    def list_channel_recent_videos(
        self,
        channel_id: str,
        *,
        max_results: int = 20,
        uploads_playlist_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """A channel's latest uploads with their counts, newest first.

        About 2 units: one page of the uploads playlist and one videos call.
        The uploads playlist of UC… is UU…, so the channels call is skipped
        when the id has that shape.
        """
        playlist = uploads_playlist_id or ""
        if not playlist and re.fullmatch(r"UC[\w-]{22}", channel_id or ""):
            playlist = "UU" + channel_id[2:]
        if not playlist:
            playlist = self.get_channel_by_id(channel_id).get("uploads_playlist_id", "")
        ids = self.list_upload_video_ids(playlist, max_videos=max(1, min(int(max_results or 20), 50)))
        videos: list[dict[str, Any]] = []
        for item in self.get_videos(ids):
            snippet = item.get("snippet", {})
            statistics = item.get("statistics", {})
            videos.append({
                "video_id": item.get("id"),
                "channel_id": snippet.get("channelId", ""),
                "title": snippet.get("title", ""),
                "published_at": snippet.get("publishedAt"),
                "duration_seconds": parse_duration((item.get("contentDetails") or {}).get("duration")),
                "view_count": _int_or_none(statistics.get("viewCount")),
                "like_count": _int_or_none(statistics.get("likeCount")),
                "comment_count": _int_or_none(statistics.get("commentCount")),
                "thumbnail_url": thumbnail_url(snippet.get("thumbnails")),
            })
        videos.sort(key=lambda video: str(video.get("published_at") or ""), reverse=True)
        return videos

    def list_comment_threads(
        self,
        video_id: str,
        *,
        max_results: int = 100,
        order: str = "relevance",
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """One page of top-level comments, without anything naming who wrote them.

        1 unit per page of up to 100. A video with comments turned off comes
        back as an empty, disabled sample rather than an error.
        """
        params: dict[str, Any] = {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": max(1, min(int(max_results or 100), 100)),
            "order": order if order in {"relevance", "time"} else "relevance",
            "textFormat": "plainText",
        }
        if page_token:
            params["pageToken"] = page_token
        try:
            payload = self._get("commentThreads", params)
        except YouTubeApiError as exc:
            if "commentsDisabled" in (getattr(exc, "reasons", None) or []):
                return {"video_id": video_id, "comments": [], "disabled": True, "next_page_token": None}
            raise
        comments: list[dict[str, Any]] = []
        for item in payload.get("items", []):
            snippet = ((item.get("snippet") or {}).get("topLevelComment") or {}).get("snippet") or {}
            # Only what was said and how it was received. Author name, channel
            # id, profile picture and link are never read out of the response.
            comments.append({
                "text": str(snippet.get("textDisplay") or snippet.get("textOriginal") or "")[:2000],
                "like_count": _int_or_none(snippet.get("likeCount")) or 0,
                "reply_count": _int_or_none((item.get("snippet") or {}).get("totalReplyCount")) or 0,
                "published_at": snippet.get("publishedAt"),
            })
        return {
            "video_id": video_id,
            "comments": comments,
            "disabled": False,
            "order": params["order"],
            "next_page_token": payload.get("nextPageToken"),
        }
