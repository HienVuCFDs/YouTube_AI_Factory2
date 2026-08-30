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


def describe(info: dict[str, Any], url: str) -> dict[str, Any]:
    """Normalise one yt-dlp info dict into the fields the app stores."""
    extractor = str(info.get("extractor_key") or info.get("extractor") or "web")
    native_id = str(info.get("id") or "")
    uploader_id = str(info.get("uploader_id") or info.get("channel_id") or info.get("uploader") or extractor)
    uploader = str(info.get("uploader") or info.get("channel") or extractor)
    webpage = str(info.get("webpage_url") or url)
    try:
        duration = int(float(info.get("duration") or 0))
    except (TypeError, ValueError):
        duration = 0
    return {
        "video_id": video_id_for(extractor, native_id, webpage),
        "channel_id": channel_id_for(extractor, uploader_id),
        "platform": extractor,
        "native_id": native_id,
        "title": str(info.get("title") or webpage)[:200],
        "description": str(info.get("description") or "")[:5000],
        "uploader": uploader[:200],
        "uploader_url": str(info.get("uploader_url") or info.get("channel_url") or ""),
        "duration_seconds": max(0, duration),
        "thumbnail": str(info.get("thumbnail") or ""),
        "webpage_url": webpage,
        "is_live": bool(info.get("is_live")),
    }
