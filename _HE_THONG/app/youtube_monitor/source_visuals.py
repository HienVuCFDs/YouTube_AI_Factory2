from __future__ import annotations

import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .ffmpeg_renderer import media_duration_seconds, resolve_ffmpeg
from .settings import GPU_ONLY


class SourceVisualError(RuntimeError):
    pass


_CHAPTER_PATTERN = re.compile(r"(?m)^\s*(?P<minute>\d{1,3}):(?P<second>\d{2})\s+(?P<title>.+?)\s*$")


def chapter_cues(description: str) -> list[tuple[float, str]]:
    """Extract ordinary YouTube chapter headings from a video description."""
    cues: list[tuple[float, str]] = []
    for match in _CHAPTER_PATTERN.finditer(str(description or "")):
        second = int(match.group("minute")) * 60 + int(match.group("second"))
        title = match.group("title").strip().lower()
        cues.append((float(second), title))
    return sorted(dict.fromkeys(cues))


def _cue_for_segment(item: dict[str, Any], index: int, cues: list[tuple[float, str]]) -> float:
    """Choose which moment of the source video this scene should show.

    A planned cue wins outright: an AI that has read the source transcript with
    its timestamps knows which moment matches this narration, which is more
    than the keyword table below can tell. The table only ever worked on videos
    whose description carried chapters, and only for the vocabulary someone
    typed into it — with neither, every scene cut from the very first second.
    """
    planned = item.get("source_start_seconds")
    if planned is not None and float(planned) >= 0:
        return float(planned)
    if not cues:
        return 0.0
    text = " ".join(
        str(item.get(key) or "").lower()
        for key in ("section", "voice_text", "visual_prompt")
    )
    topic_hints = (
        (("ky vong", "kỳ vọng", "ty le thang", "tỷ lệ thắng", "du lieu", "dữ liệu", "backtest", "data", "stat", "result"), ("data", "stat", "result")),
        (("thien huong", "thiên hướng", "xu huong", "xu hướng", "cau truc", "cấu trúc", "directional", "direction", "bias", "structure"), ("direction", "bias", "structure")),
        (("vi tri", "vị trí", "hoi", "hồi", "vung", "vùng", "location"), ("location",)),
        (("xac nhan", "xác nhận", "tin hieu", "tín hiệu", "confirmation"), ("confirmation",)),
        (("thuc thi", "thực thi", "rui ro", "rủi ro", "muc tieu", "mục tiêu", "point of interest"), ("point of interest", "trade")),
        (("checklist", "giao dich", "giao dịch", "tu dong hoa", "tự động hóa", "trade", "playing out"), ("trade", "playing out")),
    )
    for vietnamese_terms, chapter_terms in topic_hints:
        if any(term in text for term in vietnamese_terms):
            for seconds, title in cues:
                if any(term in title for term in chapter_terms):
                    return seconds

    # A predictable fallback still uses moving footage rather than a text card.
    return cues[min(max(0, index - 1), len(cues) - 1)][0]


def _run(arguments: list[str], cwd: Path) -> None:
    try:
        result = subprocess.run(
            arguments,
            cwd=str(cwd),
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=3600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceVisualError(f"Không thể chạy FFmpeg để cắt cảnh nguồn: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-2500:]
        raise SourceVisualError(f"FFmpeg không cắt được cảnh nguồn: {detail}")


def _encoding_args(codec: str) -> list[str]:
    if codec == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23", "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22"]


def _supports_nvenc(executable: str) -> bool:
    try:
        result = subprocess.run(
            [executable, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and "h264_nvenc" in (result.stdout or "")


def prepare_source_visuals(
    timeline: list[dict[str, Any]],
    source_path: Path,
    output_dir: Path,
    description: str = "",
    ffmpeg_binary: str = "ffmpeg",
) -> list[dict[str, Any]]:
    """Cut one real, muted visual clip per timeline segment.

    Each cut is matched to the *actual* generated voice duration.  Source sound is
    intentionally excluded so the commentary voice track remains clean.
    """
    source_path = Path(source_path)
    if not source_path.is_file():
        raise SourceVisualError(f"Không tìm thấy video nguồn đã tải: {source_path}")
    executable = resolve_ffmpeg(ffmpeg_binary)
    if not executable:
        raise SourceVisualError(f"Không tìm thấy FFmpeg: {ffmpeg_binary}")
    source_duration = media_duration_seconds(source_path, executable)
    if not source_duration:
        raise SourceVisualError("Không đọc được thời lượng video nguồn")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cues = chapter_cues(description)
    codec = "h264_nvenc" if _supports_nvenc(executable) else "libx264"
    if GPU_ONLY and codec != "h264_nvenc":
        raise SourceVisualError(
            "GPU-only mode is enabled but FFmpeg has no h264_nvenc encoder. "
            "The app will not cut source visuals with libx264/CPU."
        )
    results: list[dict[str, Any]] = []

    for fallback_index, item in enumerate(timeline, start=1):
        index = int(item.get("segment_index") or fallback_index)
        audio_path = Path(str(item.get("audio_path") or ""))
        actual_duration = media_duration_seconds(audio_path, executable) if audio_path.is_file() else None
        duration = max(0.5, float(actual_duration or item.get("duration_seconds") or 1))
        cue_start = _cue_for_segment(item, index, cues)
        # Move a little into the chapter to avoid title cards, while keeping the
        # selected cut inside the available source video.
        available_start = max(0.0, source_duration - duration - 0.15)
        source_start = min(max(0.0, cue_start + 2.0), available_start)
        output_path = output_dir / f"source-segment-{index:03d}.mp4"
        args = [
            executable, "-y", "-ss", f"{source_start:.3f}", "-i", str(source_path),
            "-t", f"{duration:.3f}", "-map", "0:v:0", "-an",
            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            "-r", "30", *_encoding_args(codec), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output_path),
        ]
        try:
            _run(args, output_dir)
        except SourceVisualError:
            if codec != "h264_nvenc" or GPU_ONLY:
                raise
            args = [
                executable, "-y", "-ss", f"{source_start:.3f}", "-i", str(source_path),
                "-t", f"{duration:.3f}", "-map", "0:v:0", "-an",
                "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                "-r", "30", *_encoding_args("libx264"), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output_path),
            ]
            _run(args, output_dir)
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise SourceVisualError(f"Không tạo được cảnh nguồn cho segment {index}")
        results.append(
            {
                "segment_id": int(item["id"]),
                "segment_index": index,
                "visual_path": str(output_path),
                "source_start_seconds": round(source_start, 3),
                "source_end_seconds": round(source_start + duration, 3),
                "duration_seconds": int(math.ceil(duration)),
            }
        )
    return results
