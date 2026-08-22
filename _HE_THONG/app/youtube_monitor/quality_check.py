from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .ffmpeg_renderer import media_duration_seconds, resolve_ffmpeg


def _probe_media(path: Path, ffmpeg_binary: str) -> dict[str, Any]:
    executable = resolve_ffmpeg(ffmpeg_binary)
    probes: list[str] = []
    if executable:
        for name in ("ffprobe.exe", "ffprobe"):
            sibling = Path(executable).with_name(name)
            if sibling.is_file():
                probes.append(str(sibling))
    if system_probe := shutil.which("ffprobe"):
        probes.append(system_probe)
    for probe in dict.fromkeys(probes):
        try:
            result = subprocess.run(
                [probe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                capture_output=True, text=True, timeout=30, check=False,
            )
            if result.returncode == 0:
                return json.loads(result.stdout or "{}")
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            continue
    return {}


def _ratio(value: str) -> float:
    try:
        numerator, denominator = str(value or "0/1").split("/", 1)
        return float(numerator) / max(1.0, float(denominator))
    except (ValueError, ZeroDivisionError):
        return 0.0


def _long_silence_segments(timeline: list[dict[str, Any]], ffmpeg_binary: str, threshold: float = 1.5) -> list[int]:
    """Return voice segments with an abnormal silent gap, without altering media."""
    executable = resolve_ffmpeg(ffmpeg_binary)
    if not executable:
        return []
    flagged: list[int] = []
    for item in timeline:
        path = Path(str(item.get("audio_path") or ""))
        if not path.is_file():
            continue
        try:
            result = subprocess.run(
                [executable, "-hide_banner", "-i", str(path), "-af", f"silencedetect=noise=-45dB:d={threshold}", "-f", "null", "-"],
                capture_output=True, text=True, timeout=120, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        durations = [float(value) for value in re.findall(r"silence_duration:\s*([0-9.]+)", result.stderr or "")]
        if any(duration >= threshold for duration in durations):
            flagged.append(int(item.get("segment_index") or 0))
    return flagged


def _parse_audio_metrics(output: str) -> dict[str, float | None]:
    """Extract FFmpeg volumedetect/loudnorm measurements from diagnostic output."""
    max_match = re.search(r"max_volume:\s*([-+0-9.]+)\s*dB", output or "")
    loudnorm_match = re.findall(r"\{\s*\"input_i\".*?\}", output or "", flags=re.DOTALL)
    loudnorm: dict[str, Any] = {}
    if loudnorm_match:
        try:
            loudnorm = json.loads(loudnorm_match[-1])
        except json.JSONDecodeError:
            pass
    try:
        max_volume = float(max_match.group(1)) if max_match else None
    except ValueError:
        max_volume = None
    try:
        integrated = float(loudnorm["input_i"]) if loudnorm.get("input_i") not in {None, "-inf"} else None
    except (TypeError, ValueError):
        integrated = None
    try:
        true_peak = float(loudnorm["input_tp"]) if loudnorm.get("input_tp") not in {None, "-inf"} else None
    except (TypeError, ValueError):
        true_peak = None
    return {"max_volume_db": max_volume, "integrated_lufs": integrated, "true_peak_db": true_peak}


def _final_audio_metrics(final_path: Path, ffmpeg_binary: str) -> dict[str, float | None]:
    executable = resolve_ffmpeg(ffmpeg_binary)
    if not executable or not final_path.is_file():
        return {"max_volume_db": None, "integrated_lufs": None, "true_peak_db": None}
    try:
        volume = subprocess.run(
            [executable, "-hide_banner", "-i", str(final_path), "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=180, check=False,
        )
        loudness = subprocess.run(
            [executable, "-hide_banner", "-i", str(final_path), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
            capture_output=True, text=True, timeout=180, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"max_volume_db": None, "integrated_lufs": None, "true_peak_db": None}
    return _parse_audio_metrics((volume.stderr or "") + "\n" + (loudness.stderr or ""))


def _uses_nvenc(final_path: Path, ffmpeg_binary: str) -> bool:
    if not final_path.is_file():
        return False
    executable = resolve_ffmpeg(ffmpeg_binary)
    probes: list[str] = []
    if executable:
        for name in ("ffprobe.exe", "ffprobe"):
            sibling = Path(executable).with_name(name)
            if sibling.is_file():
                probes.append(str(sibling))
    system_probe = shutil.which("ffprobe")
    if system_probe:
        probes.append(system_probe)
    for probe in dict.fromkeys(probes):
        try:
            result = subprocess.run(
                [probe, "-v", "error", "-show_entries", "stream_tags=encoder", "-of", "default=nw=1", str(final_path)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and "nvenc" in (result.stdout or "").lower():
            return True
    return False


def build_quality_report(
    timeline: list[dict[str, Any]],
    final_path: str = "",
    ffmpeg_binary: str = "ffmpeg",
    thumbnail_path: str = "",
) -> dict[str, Any]:
    missing_visuals = [int(item.get("segment_index") or 0) for item in timeline if not Path(str(item.get("visual_path") or "")).is_file()]
    missing_audio = [int(item.get("segment_index") or 0) for item in timeline if not Path(str(item.get("audio_path") or "")).is_file()]
    audio_duration = sum(
        media_duration_seconds(Path(str(item.get("audio_path"))), ffmpeg_binary) or 0
        for item in timeline
        if str(item.get("audio_path") or "")
    )
    visual_kinds = {Path(str(item.get("visual_path"))).suffix.lower() for item in timeline if str(item.get("visual_path") or "")}
    final_file = Path(final_path) if final_path else Path()
    thumbnail_file = Path(thumbnail_path) if thumbnail_path else Path()
    final_exists = final_file.is_file()
    final_duration = media_duration_seconds(final_file, ffmpeg_binary) if final_exists else None
    media = _probe_media(final_file, ffmpeg_binary) if final_exists else {}
    streams = media.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    fps = _ratio(str(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"))
    container = str((media.get("format") or {}).get("format_name") or "")
    technical_video = bool(
        video and audio and width >= 720 and height >= 720 and 20 <= fps <= 60
        and str(video.get("codec_name") or "") in {"h264", "hevc", "av1"}
        and "mp4" in container
    )
    duration_gap = abs((final_duration or audio_duration) - audio_duration) if audio_duration else 0.0
    long_silences = _long_silence_segments(timeline, ffmpeg_binary)
    audio_metrics = _final_audio_metrics(final_file, ffmpeg_binary) if final_exists else {
        "max_volume_db": None, "integrated_lufs": None, "true_peak_db": None,
    }
    integrated_lufs = audio_metrics["integrated_lufs"]
    true_peak = audio_metrics["true_peak_db"]
    max_volume = audio_metrics["max_volume_db"]
    # Single-pass normalization and mixed narration can vary slightly; retain
    # a conservative broadcast-safe acceptance band around the -16 LUFS target.
    loudness_valid = integrated_lufs is not None and -19.0 <= integrated_lufs <= -13.0
    no_clipping = (true_peak is not None and true_peak <= -0.1) or (max_volume is not None and max_volume <= -0.1)
    timestamped_subtitles = bool(timeline) and all(
        Path(str(item.get("subtitle_path") or "")).is_file()
        for item in timeline
    )
    checks = {
        "has_all_visuals": not missing_visuals,
        "has_all_voice": not missing_audio,
        "subtitle_ready": bool(timeline) and all(bool(str(item.get("subtitle_text") or item.get("voice_text") or "").strip()) for item in timeline),
        "timestamped_subtitles": timestamped_subtitles,
        "has_final_file": final_exists,
        "has_thumbnail": thumbnail_file.is_file(),
        "technical_video_valid": technical_video,
        "duration_synced": duration_gap <= 1.0,
        "no_abnormal_voice_silence": not long_silences,
        "audio_loudness_valid": loudness_valid,
        "no_audio_clipping": no_clipping,
        "has_moving_visuals": bool(visual_kinds & {".gif", ".mp4", ".mov", ".mkv", ".webm", ".avi"}),
        "gpu_encoded": _uses_nvenc(final_file, ffmpeg_binary),
    }
    issues: list[str] = []
    if missing_visuals:
        issues.append("Thiếu cảnh hình ảnh ở đoạn: " + ", ".join(map(str, missing_visuals)))
    if missing_audio:
        issues.append("Thiếu voice ở đoạn: " + ", ".join(map(str, missing_audio)))
    if final_duration and duration_gap > 1.0:
        issues.append("Thời lượng video và voice lệch quá 1 giây")
    if long_silences:
        issues.append("Voice có khoảng lặng trên 1,5 giây ở đoạn: " + ", ".join(map(str, long_silences)))
    if final_exists and not loudness_valid:
        issues.append("Âm lượng final chưa đạt vùng mục tiêu -16 LUFS ±3 hoặc không đo được")
    if final_exists and not no_clipping:
        issues.append("Audio final có nguy cơ clipping hoặc không đo được true peak")
    if not final_exists:
        issues.append("Chưa có final.mp4 để kiểm tra")
    if not checks["has_thumbnail"]:
        issues.append("Chưa chọn thumbnail hợp lệ cho project")
    if final_exists and not technical_video:
        issues.append("Video cuối không đạt chuẩn MP4/HD/20–60 FPS/có audio")
    if not timestamped_subtitles:
        issues.append("Chưa có SRT timestamp riêng cho từng segment")
    if final_exists and not checks["gpu_encoded"]:
        issues.append("Final video không ghi nhận encoder NVENC")
    return {
        "status": "pass" if all(checks.values()) else "warning",
        "checks": checks,
        "issues": issues,
        "segments": len(timeline),
        "audio_duration_seconds": round(audio_duration, 3),
        "final_duration_seconds": round(final_duration, 3) if final_duration else None,
        "media": {"width": width, "height": height, "fps": round(fps, 3), "video_codec": video.get("codec_name", ""), "audio_codec": audio.get("codec_name", ""), "container": container, **audio_metrics},
    }


def quality_report_markdown(report: dict[str, Any]) -> str:
    lines = ["# Quality Check", "", f"- Status: {report['status']}", f"- Segments: {report['segments']}"]
    if report.get("audio_duration_seconds") is not None:
        lines.append(f"- Voice duration: {report['audio_duration_seconds']}s")
    if report.get("final_duration_seconds") is not None:
        lines.append(f"- Final duration: {report['final_duration_seconds']}s")
    lines.extend(["", "## Checks", ""])
    lines.extend(f"- {'PASS' if value else 'WARN'}: {key}" for key, value in report["checks"].items())
    if report["issues"]:
        lines.extend(["", "## Issues", "", *[f"- {issue}" for issue in report["issues"]]])
    return "\n".join(lines).strip() + "\n"
