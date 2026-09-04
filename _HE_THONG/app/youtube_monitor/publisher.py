from __future__ import annotations

import threading
import time
import mimetypes
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .database import Database
from .oauth import OAuthError, get_access_token, status as oauth_status


UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos"
THUMBNAIL_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
CHANNELS_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels"


# Only YouTube has an uploader. The publication table accepts tiktok,
# facebook and instagram because a project may be planned for them, but
# nothing here can deliver to those yet.
SUPPORTED_PLATFORMS: tuple[str, ...] = ("youtube",)


class PublisherError(RuntimeError):
    pass


def _parse_schedule_days(value: str) -> set[int]:
    names = {
        "mon": 0, "monday": 0,
        "tue": 1, "tuesday": 1,
        "wed": 2, "wednesday": 2,
        "thu": 3, "thursday": 3,
        "fri": 4, "friday": 4,
        "sat": 5, "saturday": 5,
        "sun": 6, "sunday": 6,
    }
    result: set[int] = set()
    for raw in str(value or "").replace(";", ",").split(","):
        key = raw.strip().lower()
        if key in names:
            result.add(names[key])
    return result or {0}


def next_channel_schedule(channel: dict[str, Any], now: datetime | None = None) -> str | None:
    """Return the next schedule time as a UTC ISO value for a managed channel."""
    if not channel.get("schedule_enabled"):
        return None
    timezone_name = str(channel.get("schedule_timezone") or "Asia/Bangkok")
    try:
        zone = ZoneInfo(timezone_name)
    except (KeyError, ValueError):
        zone = timezone.utc
    local_now = (now or datetime.now(timezone.utc)).astimezone(zone)
    hour, minute = (int(part) for part in str(channel.get("schedule_time") or "19:00").split(":", 1))
    frequency = str(channel.get("schedule_frequency") or "weekly").lower()
    selected_days = _parse_schedule_days(str(channel.get("schedule_days") or "mon"))
    for offset in range(0, 32):
        candidate = (local_now + timedelta(days=offset)).replace(
            hour=hour, minute=minute, second=0, microsecond=0,
        )
        if candidate <= local_now:
            continue
        if frequency == "weekdays" and candidate.weekday() >= 5:
            continue
        if frequency in {"weekly", "monthly"} and candidate.weekday() not in selected_days:
            continue
        if frequency == "monthly" and candidate.day > 7:
            continue
        return candidate.astimezone(timezone.utc).isoformat()
    return None


class YouTubePublisher:
    """Small raw HTTP adapter for the YouTube resumable upload API."""

    def list_authorized_channels(self) -> list[dict[str, Any]]:
        try:
            token = get_access_token()
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                response = client.get(
                    CHANNELS_ENDPOINT,
                    params={"part": "snippet,contentDetails,status", "mine": "true"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                if response.status_code >= 400:
                    raise PublisherError(f"Không đọc được kênh YouTube: {response.status_code} {response.text[-1000:]}")
                payload = response.json()
        except OAuthError:
            raise
        except httpx.HTTPError as exc:
            raise PublisherError(f"Không kết nối được YouTube channel API: {exc}") from exc
        return [
            {
                "id": str(item.get("id") or ""),
                "title": str((item.get("snippet") or {}).get("title") or ""),
                "handle": str((item.get("snippet") or {}).get("customUrl") or ""),
                "uploads_playlist_id": str(((item.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads") or ""),
                "privacy_status": str((item.get("status") or {}).get("privacyStatus") or ""),
            }
            for item in payload.get("items", [])
            if item.get("id")
        ]

    def upload_thumbnail(self, video_id: str, thumbnail_path: str, token: str) -> None:
        path = Path(str(thumbnail_path or "")).expanduser()
        if not path.is_file():
            raise PublisherError(f"Không tìm thấy thumbnail để upload: {path}")
        mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        if mime_type not in {"image/jpeg", "image/png"}:
            raise PublisherError("Thumbnail YouTube phải là JPG hoặc PNG")
        try:
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                response = client.post(
                    f"{THUMBNAIL_ENDPOINT}?videoId={video_id}&uploadType=media",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": mime_type,
                        "Content-Length": str(path.stat().st_size),
                    },
                    content=path.read_bytes(),
                )
                if response.status_code >= 400:
                    raise PublisherError(f"YouTube upload thumbnail thất bại: {response.status_code} {response.text[-1200:]}")
        except httpx.HTTPError as exc:
            raise PublisherError(f"Không kết nối được YouTube thumbnail API: {exc}") from exc

    def upload_video(self, publication: dict[str, Any]) -> dict[str, Any]:
        # This uploader speaks to YouTube and nothing else. A publication
        # carries the platform it was made for, and sending a TikTok or
        # Facebook one here would publish it to the user's YouTube channel -
        # a real video, on the wrong account, that they then have to go and
        # delete. The queue filters these out; this refuses them outright, so
        # a direct call cannot get past it either.
        platform = str(publication.get("platform") or "youtube").strip().lower()
        if platform not in SUPPORTED_PLATFORMS:
            raise PublisherError(
                f"Chưa hỗ trợ đăng lên {platform}; app mới chỉ nối được YouTube. "
                "Bản đăng này được giữ lại, không bị đưa nhầm lên YouTube."
            )
        path = Path(str(publication.get("local_file_path") or "")).expanduser()
        if not path.is_file():
            raise PublisherError(f"Không tìm thấy file video để upload: {path}")
        try:
            token = get_access_token()
        except OAuthError as exc:
            raise PublisherError(str(exc)) from exc

        privacy = str(publication.get("privacy_status") or "private").lower()
        scheduled_at = str(publication.get("scheduled_at") or "").strip() or None
        status_payload: dict[str, Any] = {
            "privacyStatus": "private" if scheduled_at else privacy,
            "selfDeclaredMadeForKids": False,
        }
        if scheduled_at:
            status_payload["publishAt"] = scheduled_at
        payload = {
            "snippet": {
                "title": str(publication.get("title") or path.stem)[:100],
                "description": str(publication.get("description") or "")[:5000],
                "tags": [str(tag).strip() for tag in (publication.get("tags") or []) if str(tag).strip()][:500],
                "categoryId": str(publication.get("category_id") or "27"),
            },
            "status": status_payload,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(path.stat().st_size),
        }
        try:
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                start = client.post(
                    f"{UPLOAD_ENDPOINT}?part=snippet,status",
                    headers=headers,
                    json=payload,
                )
                if start.status_code >= 400:
                    raise PublisherError(f"YouTube không tạo upload session: {start.status_code} {start.text[-1000:]}")
                upload_url = start.headers.get("location")
                if not upload_url:
                    raise PublisherError("YouTube không trả upload session URL")
                with path.open("rb") as stream:
                    upload = client.put(
                        upload_url,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "video/mp4",
                            "Content-Length": str(path.stat().st_size),
                        },
                        content=stream,
                    )
                if upload.status_code >= 400:
                    raise PublisherError(f"YouTube upload thất bại: {upload.status_code} {upload.text[-1500:]}")
                result = upload.json()
                thumbnail_path = str(publication.get("thumbnail_path") or "").strip()
                if thumbnail_path:
                    video_id = str(result.get("id") or "")
                    if not video_id:
                        raise PublisherError("YouTube upload không trả video ID để gắn thumbnail")
                    self.upload_thumbnail(video_id, thumbnail_path, token)
                    result["thumbnail_uploaded"] = True
                return result
        except httpx.HTTPError as exc:
            raise PublisherError(f"Không kết nối được YouTube Publisher: {exc}") from exc


class PublisherWorker:
    TICK_INTERVAL = 15.0

    def __init__(self, database: Database, publisher: YouTubePublisher | None = None) -> None:
        self.database = database
        self.publisher = publisher or YouTubePublisher()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error = ""
        self.last_run_at: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="youtube-publisher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.last_run_at = datetime.now(timezone.utc).isoformat()
            # OAuth is deliberately checked before claiming a job. Without a
            # token, queued publications remain visible and recoverable.
            if oauth_status().get("connected"):
                self._process_due()
            self._stop.wait(self.TICK_INTERVAL)

    def _process_due(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for publication in self.database.list_due_project_publications(
            now, limit=3, platforms=SUPPORTED_PLATFORMS,
        ):
            claimed = self.database.claim_project_publication(int(publication["id"]))
            if not claimed:
                continue
            try:
                result = self.publisher.upload_video(claimed)
                video_id = str(result.get("id") or "")
                if not video_id:
                    raise PublisherError("YouTube upload không trả video ID")
                self.database.finish_project_publication(
                    int(claimed["id"]), "completed", youtube_video_id=video_id,
                )
                self.last_error = ""
            except Exception as exc:
                self.last_error = str(exc)
                self.database.finish_project_publication(
                    int(claimed["id"]), "error", error=str(exc),
                )

    def status(self) -> dict[str, Any]:
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "oauth_connected": bool(oauth_status().get("connected")),
            "last_run_at": self.last_run_at,
            "last_error": self.last_error,
            "queue": self.database.publication_status(),
            # Named rather than hidden: a queue that never empties looks
            # broken unless it says what it is waiting for.
            "awaiting_platform": self.database.publications_awaiting_platform(SUPPORTED_PLATFORMS),
            "supported_platforms": list(SUPPORTED_PLATFORMS),
        }
