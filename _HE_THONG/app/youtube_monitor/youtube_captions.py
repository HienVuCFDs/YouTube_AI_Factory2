from __future__ import annotations

from typing import Any

import httpx

from .oauth import get_access_token


API_BASE = "https://www.googleapis.com/youtube/v3"


class CaptionsError(RuntimeError):
    pass


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
        message = payload.get("error", {}).get("message", response.text)
    except ValueError:
        message = response.text
    return f"YouTube API lỗi {response.status_code}: {message}"


def list_captions(video_id: str) -> list[dict[str, Any]]:
    """List official caption tracks for a video. Requires OAuth (not just an API key)."""
    access_token = get_access_token()
    try:
        response = httpx.get(
            f"{API_BASE}/captions",
            params={"part": "snippet", "videoId": video_id},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise CaptionsError(f"Không kết nối được YouTube API: {exc}") from exc

    if response.status_code >= 400:
        raise CaptionsError(_error_message(response))

    items = response.json().get("items", [])
    return [
        {
            "caption_id": item["id"],
            "language": item.get("snippet", {}).get("language", ""),
            "name": item.get("snippet", {}).get("name", ""),
            "track_kind": item.get("snippet", {}).get("trackKind", ""),
            "is_auto_synced": item.get("snippet", {}).get("trackKind") == "ASR",
        }
        for item in items
    ]


def download_caption(caption_id: str) -> str:
    """Download a caption track as SRT. Only succeeds for videos the OAuth account owns/manages."""
    access_token = get_access_token()
    try:
        response = httpx.get(
            f"{API_BASE}/captions/{caption_id}",
            params={"tfmt": "srt"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise CaptionsError(f"Không kết nối được YouTube API: {exc}") from exc

    if response.status_code == 403:
        raise CaptionsError(
            "YouTube từ chối tải caption (403) — thường vì video không thuộc kênh của tài "
            "khoản đã kết nối OAuth. YouTube chỉ cho phép tải nội dung caption đầy đủ cho "
            "video do chính tài khoản sở hữu/quản lý; với kênh của người khác chỉ xem được "
            "danh sách caption có sẵn, không tải được nội dung."
        )
    if response.status_code >= 400:
        raise CaptionsError(_error_message(response))

    return response.text
