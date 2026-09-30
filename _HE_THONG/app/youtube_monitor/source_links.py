"""Read a source video's details from a link on any site yt-dlp supports.

Importing a reference video went through the YouTube Data API, so it needed
a YouTube video id and returned YouTube's own metadata. A Bilibili, TikTok
or Facebook link could not be imported at all — the only way to work on one
was to download it by hand and upload the file, which is exactly how the two
Bilibili projects in this database got here.

The downloader underneath has always been yt-dlp, which reads roughly 1800
sites. This module asks it for the metadata alone, so a link from any of
them can become an ordinary video row and flow through the existing
transcript, analysis and reup pipeline.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


class SourceLinkError(RuntimeError):
    pass


# A channel id is the key every downstream table hangs off, and the column
# was sized for YouTube's. One per site+uploader keeps a platform's videos
# together without teaching the rest of the app about a second kind of source.
_CHANNEL_PREFIX = "WEB"
_MAX_CHANNEL_ID = 24


def is_http_url(reference: str) -> bool:
    parsed = urlparse(str(reference or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "", str(value or "")).upper()


def channel_id_for(extractor: str, uploader_id: str) -> str:
    """One stable synthetic channel per uploader on a site."""
    site = _slug(extractor)[:8] or "WEB"
    digest = hashlib.sha256(f"{extractor}:{uploader_id}".encode("utf-8")).hexdigest()
    return f"{_CHANNEL_PREFIX}-{site}-{digest}"[:_MAX_CHANNEL_ID]


def video_id_for(extractor: str, native_id: str, url: str) -> str:
    """A key of our own: site ids collide across platforms and change shape."""
    digest = hashlib.sha256(f"{extractor}:{native_id or url}".encode("utf-8")).hexdigest()
    return f"web-{digest[:16]}"


def probe_url(url: str, *, cookie_file: str = "") -> dict[str, Any]:
    """Read a link's metadata without downloading the video itself."""
    reference = str(url or "").strip()
    if not is_http_url(reference):
        raise SourceLinkError("Cần một đường dẫn http/https tới video")
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise SourceLinkError(
            "Thiếu thư viện yt-dlp. Cài đặt bằng: pip install yt-dlp"
        ) from exc
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        # A playlist link would otherwise pull in every entry; one link is
        # meant to become one source video.
        "noplaylist": True,
        "extract_flat": False,
    }
    if cookie_file:
        options["cookiefile"] = cookie_file
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(reference, download=False)
    except Exception as exc:
        raise SourceLinkError(f"Không đọc được video từ link: {exc}") from exc
    if not isinstance(info, dict):
        raise SourceLinkError("Link không trả về thông tin video")
    if info.get("entries"):
        entries = [item for item in info["entries"] if isinstance(item, dict)]
        if not entries:
            raise SourceLinkError("Link là danh sách phát nhưng không có video nào")
        info = entries[0]
    return describe(info, reference)


_YOUTUBE_CHANNEL = re.compile(r"UC[\w-]{22}")
_PLATFORM_ALIASES = {
    "youtube": "youtube", "youtubetab": "youtube", "youtubeshorts": "youtube",
    "tiktok": "tiktok", "tiktokuser": "tiktok",
    "facebook": "facebook", "facebookreel": "facebook",
    "instagram": "instagram", "instagramstory": "instagram",
    "bilibili": "bilibili", "vimeo": "vimeo", "dailymotion": "dailymotion",
    # yt-dlp's catch-alls read a media tag off any page; the page has no
    # platform identity (a TikTok Shop listing came in this way).
    "generic": "web", "html5mediaembed": "web",
}


def platform_of(extractor: str) -> str:
    """The platform an extractor reads, as one lowercase word."""
    slug = re.sub(r"[^a-z0-9]+", "", str(extractor or "").lower())
    return _PLATFORM_ALIASES.get(slug, slug or "web")


def _count(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _published_at(info: dict[str, Any]) -> str | None:
    """When the platform says it was published, in ISO form, or nothing."""
    for key in ("timestamp", "release_timestamp"):
        try:
            stamp = float(info.get(key))
        except (TypeError, ValueError):
            continue
        return datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat()
    day = str(info.get("upload_date") or info.get("release_date") or "")
    if re.fullmatch(r"\d{8}", day):
        # A date without a time is kept as a date, not given a made-up hour.
        return f"{day[:4]}-{day[4:6]}-{day[6:]}"
    return None


def describe(info: dict[str, Any], url: str) -> dict[str, Any]:
    """Normalise one yt-dlp info dict into the fields the app stores.

    The platform's own identity and counts are kept. They used to be read and
    dropped, and a YouTube video imported by link ended up on a made-up
    "WEB-YOUTUBE-…" channel, cut off from the channel it actually belongs to.
    """
    extractor = str(info.get("extractor_key") or info.get("extractor") or "web")
    platform = platform_of(extractor)
    native_id = str(info.get("id") or "")
    uploader_id = str(info.get("uploader_id") or info.get("channel_id") or info.get("uploader") or extractor)
    uploader = str(info.get("uploader") or info.get("channel") or extractor)
    native_channel_id = str(info.get("channel_id") or info.get("uploader_id") or "")
    webpage = str(info.get("webpage_url") or url)
    try:
        duration = int(float(info.get("duration") or 0))
    except (TypeError, ValueError):
        duration = 0
    # A YouTube channel id is the key the monitoring side already uses for
    # that channel, so the video joins its real channel. Other sites keep a
    # key of our own: their ids collide across platforms and change shape.
    if platform == "youtube" and _YOUTUBE_CHANNEL.fullmatch(native_channel_id):
        channel_key = native_channel_id
    else:
        channel_key = channel_id_for(extractor, uploader_id)
    return {
        "video_id": video_id_for(extractor, native_id, webpage),
        "channel_id": channel_key,
        "platform": extractor,
        "platform_slug": platform,
        "native_id": native_id,
        "native_channel_id": native_channel_id[:200],
        "channel_name": str(info.get("channel") or info.get("uploader") or "")[:200],
        "title": str(info.get("title") or webpage)[:200],
        "description": str(info.get("description") or "")[:5000],
        "uploader": uploader[:200],
        "uploader_url": str(info.get("uploader_url") or info.get("channel_url") or ""),
        "duration_seconds": max(0, duration),
        "view_count": _count(info.get("view_count")),
        "like_count": _count(info.get("like_count")),
        "comment_count": _count(info.get("comment_count")),
        "published_at": _published_at(info),
        "thumbnail": str(info.get("thumbnail") or ""),
        "webpage_url": webpage,
        "is_live": bool(info.get("is_live")),
    }
