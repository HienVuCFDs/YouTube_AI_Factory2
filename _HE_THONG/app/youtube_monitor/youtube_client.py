from __future__ import annotations

import re
from urllib.parse import urlparse
from typing import Any

import httpx


API_BASE = "https://www.googleapis.com/youtube/v3"


class YouTubeApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


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
    def __init__(self, api_key: str, timeout: float = 30.0):
        self.api_key = api_key.strip()
        self.timeout = timeout

    def _get(self, resource: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise YouTubeApiError(
                "Thiếu YOUTUBE_API_KEY. Hãy sao chép .env.example thành .env và thêm API key."
            )
        request_params = {**params, "key": self.api_key}
        try:
            response = httpx.get(
                f"{API_BASE}/{resource}",
                params=request_params,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise YouTubeApiError(f"Không kết nối được YouTube API: {exc}") from exc

        if response.status_code >= 400:
            try:
                payload = response.json()
                message = payload.get("error", {}).get("message", response.text)
            except ValueError:
                message = response.text
            raise YouTubeApiError(
                f"YouTube API lỗi {response.status_code}: {message}",
                status_code=response.status_code,
            )
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
