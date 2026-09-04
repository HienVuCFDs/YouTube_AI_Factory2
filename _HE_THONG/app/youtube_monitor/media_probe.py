"""What a file actually is, rather than what its name claims.

An extension is a promise, not a fact. A .mp4 that is really a rename of a
.txt, a download that stopped halfway, an "audio" file with no audio stream -
all of them pass a suffix check and then fail much later, in the middle of a
render or a voiceover, with an FFmpeg error nobody can act on.

Probing at the point of import turns that into one clear refusal at the point
the user can still do something about it, and it answers a second question
the app needs anyway: whether the source is a film to cut pictures from or a
recording to put a voice over. Those are different workflows, and picking the
wrong one is what makes "cut scenes from the source" fail on a podcast.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .ffmpeg_renderer import resolve_ffprobe

# A video track that is really a poster frame - one still, no motion - is an
# audio file with cover art, and cutting scenes from it gives the same frame
# every time.
COVER_ART_CODECS = {"mjpeg", "png", "bmp", "gif"}

VIDEO_KIND = "video"
AUDIO_KIND = "audio"
IMAGE_KIND = "image"
BROKEN_KIND = "broken"


class MediaProbeError(RuntimeError):
    """Raised only when probing itself cannot run at all."""


def probe_media(path: Path, ffmpeg_binary: str = "ffmpeg", timeout: int = 60) -> dict[str, Any]:
    """Read a file's real streams, or say why it cannot be read.

    Never raises for a bad file: an unreadable file is a result, not an
    exception, because the caller's job is to report it to the user.
    """
    path = Path(path)
    blank: dict[str, Any] = {
        "ok": False, "kind": BROKEN_KIND, "has_video": False, "has_audio": False,
        "duration_seconds": 0.0, "width": 0, "height": 0,
        "video_codec": "", "audio_codec": "", "container": "",
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "error": "",
    }
    if not path.is_file():
        return {**blank, "error": "Không tìm thấy file"}
    if blank["size_bytes"] == 0:
        return {**blank, "error": "File rỗng (0 byte) — có thể tải chưa xong"}

    probe = resolve_ffprobe(ffmpeg_binary)
    if not probe:
        raise MediaProbeError("Không tìm thấy ffprobe để kiểm tra file")
    try:
        result = subprocess.run(
            [probe, "-v", "error", "-show_streams", "-show_format",
             "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {**blank, "error": f"Không đọc được file: {exc}"}
    if result.returncode != 0:
        # ffprobe prefixes its complaint with the whole path, which tells the
        # user nothing they do not already know and buries the reason.
        line = ((result.stderr or "").strip().splitlines() or [""])[-1]
        reason = line.split(": ", 1)[1] if str(path) in line and ": " in line else line
        return {**blank, "error": f"File hỏng hoặc không phải media: {reason.strip()[:160]}"}
    try:
        payload = json.loads(result.stdout or "{}")
    except ValueError:
        return {**blank, "error": "ffprobe trả về dữ liệu không đọc được"}

    streams = payload.get("streams") or []
    container = str((payload.get("format") or {}).get("format_name") or "")
    try:
        duration = float((payload.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0

    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
    video_codec = str(video.get("codec_name") or "")
    # A single still inside an audio container is cover art, not footage.
    is_cover_art = bool(video) and (
        video_codec in COVER_ART_CODECS
        and str(video.get("disposition", {}).get("attached_pic") or "0") == "1"
    )
    has_video = bool(video) and not is_cover_art
    has_audio = bool(audio)

    if not has_video and not has_audio:
        return {**blank, "container": container, "error": "File không có luồng hình hay tiếng nào"}

    if has_video and duration <= 0 and not has_audio:
        kind = IMAGE_KIND
    elif has_video:
        kind = VIDEO_KIND
    else:
        kind = AUDIO_KIND

    return {
        "ok": True,
        "kind": kind,
        "has_video": has_video,
        "has_audio": has_audio,
        "has_cover_art": is_cover_art,
        "duration_seconds": round(duration, 3),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "video_codec": video_codec,
        "audio_codec": str(audio.get("codec_name") or ""),
        "container": container,
        "size_bytes": blank["size_bytes"],
        "error": "",
    }


def describe(probe: dict[str, Any]) -> str:
    """A line a user can read, in place of an ffprobe dump."""
    if not probe.get("ok"):
        return probe.get("error") or "Không đọc được file"
    parts: list[str] = []
    if probe["kind"] == VIDEO_KIND:
        parts.append(f"Video {probe['width']}x{probe['height']}")
    elif probe["kind"] == AUDIO_KIND:
        parts.append("Chỉ có tiếng, không có hình")
    else:
        parts.append("Ảnh tĩnh")
    if probe["duration_seconds"]:
        parts.append(f"{probe['duration_seconds']:.0f} giây")
    if probe["kind"] == VIDEO_KIND:
        parts.append("có tiếng" if probe["has_audio"] else "không có tiếng")
    return " · ".join(parts)


def reject_reason(probe: dict[str, Any], expected: str) -> str:
    """Why this file cannot be used as the kind the caller asked for.

    Empty string means it can. The check is against the streams, not the
    suffix, so a .mp4 that is really an mp3 is caught here rather than at the
    first attempt to cut a scene out of it.
    """
    if not probe.get("ok"):
        return probe.get("error") or "Không đọc được file"
    kind = probe.get("kind")
    if expected == VIDEO_KIND and kind != VIDEO_KIND:
        if kind == AUDIO_KIND:
            return (
                "File này chỉ có tiếng, không có hình. Nếu định dùng làm nguồn tiếng, "
                "hãy chọn loại “audio”; luồng cắt cảnh từ video nguồn sẽ không dùng được."
            )
        return "File này không phải video (không có luồng hình chuyển động)."
    if expected == AUDIO_KIND and not probe.get("has_audio"):
        return "File này không có luồng tiếng nào."
    if expected == IMAGE_KIND and kind not in {IMAGE_KIND, VIDEO_KIND}:
        return "File này không phải ảnh."
    return ""
