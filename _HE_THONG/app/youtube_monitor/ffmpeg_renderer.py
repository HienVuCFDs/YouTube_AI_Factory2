from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

from .settings import GPU_ONLY
from .subtitle_builder import write_segment_srt


class FfmpegRenderError(RuntimeError):
    pass


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
CARD_COLORS = ("0x0B1020", "0x111827", "0x172033", "0x0F172A")
WINDOWS_FONT = Path("C:/Windows/Fonts/arial.ttf")


def resolve_ffmpeg(binary: str = "ffmpeg") -> str | None:
    candidate = str(binary or "ffmpeg").strip() or "ffmpeg"
    path = Path(candidate)
    if path.is_file():
        return str(path)
    return shutil.which(candidate)


def ffmpeg_available(binary: str = "ffmpeg") -> bool:
    return resolve_ffmpeg(binary) is not None


def media_duration_seconds(path: Path, ffmpeg_binary: str = "ffmpeg") -> float | None:
    """Return the measured media duration, or None when ffprobe is unavailable."""
    target = Path(path)
    if not target.is_file():
        return None
    ffmpeg_path = resolve_ffmpeg(ffmpeg_binary)
    candidates: list[str] = []
    if ffmpeg_path:
        for name in ("ffprobe.exe", "ffprobe"):
            sibling = Path(ffmpeg_path).with_name(name)
            if sibling.is_file():
                candidates.append(str(sibling))
    system_probe = shutil.which("ffprobe")
    if system_probe:
        candidates.append(system_probe)
    for probe in dict.fromkeys(candidates):
        try:
            result = subprocess.run(
                [
                    probe, "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", str(target),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode == 0:
                duration = float((result.stdout or "").strip())
                if duration > 0:
                    return duration
        except (OSError, ValueError, subprocess.TimeoutExpired):
            continue
    return None


def _run(args: list[str], cwd: Path) -> None:
    try:
        result = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FfmpegRenderError(f"Không chạy được FFmpeg: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-3000:]
        raise FfmpegRenderError(f"FFmpeg thất bại ({result.returncode}): {detail}")


def _existing_path(value: Any, label: str, segment_index: int) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_file():
        raise FfmpegRenderError(
            f"Không tìm thấy {label} của segment {segment_index}: {path}"
        )
    return path.resolve()


def _concat_line(path: Path) -> str:
    # concat demuxer expects a single-quoted path; escape embedded quotes.
    return "file '" + path.as_posix().replace("'", "'\\''") + "'"


def _escape_drawtext(value: str) -> str:
    """Make arbitrary timeline text safe inside a quoted FFmpeg filter value."""
    # Single quotes end FFmpeg's text='...' value even when escaped on some
    # Windows builds. Normalize instead of relying on nested shell escaping.
    return (
        " ".join(value.split())
        .replace("\\", "/")
        .replace("'", "’")
        .replace(":", " -")
        .replace("%", " percent")
        .replace("[", "(")
        .replace("]", ")")
    )


def _card_lines(value: Any, width: int, maximum_lines: int) -> list[str]:
    text = " ".join(str(value or "").split())
    if not text:
        return []
    characters = 34 if width >= 1280 else 26
    lines = textwrap.wrap(text, width=characters, break_long_words=False)
    if len(lines) > maximum_lines:
        lines = lines[:maximum_lines]
        lines[-1] = lines[-1].rstrip(" .") + "…"
    return lines


def _card_video_filter(item: dict[str, Any], width: int, height: int, index: int) -> str:
    """Build a readable visual card for a segment without a supplied asset."""
    headline = _card_lines(item.get("visual_prompt") or item.get("voice_text"), width, 3)
    subtitle = _card_lines(item.get("voice_text"), width, 3)
    font = WINDOWS_FONT.as_posix().replace(":", "\\:") if WINDOWS_FONT.is_file() else ""
    font_option = f"fontfile='{font}':" if font else ""
    color = CARD_COLORS[(index - 1) % len(CARD_COLORS)]
    parts = [
        "format=yuv420p",
        f"drawbox=x=0:y=0:w=iw:h=ih:color={color}:t=fill",
        "drawbox=x=0:y=0:w=24:h=ih:color=0x22D3EE:t=fill",
        "drawbox=x=96:y=96:w=1728:h=888:color=0x020617@0.38:t=fill",
        f"drawtext={font_option}text='YOUTUBE AI FACTORY  /  PHAN {index:02d}':fontcolor=0x67E8F9:fontsize=30:x=142:y=150",
    ]
    for line_index, line in enumerate(headline):
        parts.append(
            f"drawtext={font_option}text='{_escape_drawtext(line)}':fontcolor=white:fontsize=62:"
            f"x=142:y={300 + line_index * 82}"
        )
    subtitle_start = max(620, 690 - max(0, len(subtitle) - 1) * 48)
    for line_index, line in enumerate(subtitle):
        parts.append(
            f"drawtext={font_option}text='{_escape_drawtext(line)}':fontcolor=0xCBD5E1:fontsize=38:"
            f"x=142:y={subtitle_start + line_index * 52}"
        )
    return ",".join(parts)


def generate_local_visual_draft(
    timeline: list[dict[str, Any]],
    output_dir: Path,
    binary: str = "ffmpeg",
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
) -> list[dict[str, Any]]:
    """Create original local visual cards for an AI Director first cut.

    These are deliberately not presented as AI-generated footage. They give the
    director workflow a complete, reviewable MP4 without downloading/reusing the
    reference video. Users can replace any card with a Runway scene or uploaded
    asset before their final publication render.
    """
    executable = resolve_ffmpeg(binary)
    if not executable:
        raise FfmpegRenderError(f"Không tìm thấy FFmpeg ({binary})")
    if not timeline:
        raise FfmpegRenderError("Timeline không có segment để tạo visual draft")
    if GPU_ONLY and not _supports_nvenc(executable):
        raise FfmpegRenderError(
            "GPU-only mode is enabled but FFmpeg has no h264_nvenc encoder. "
            "The app will not create draft visuals with libx264/CPU."
        )
    codec = "h264_nvenc" if _supports_nvenc(executable) else "libx264"
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for fallback_index, item in enumerate(timeline, start=1):
        index = int(item.get("segment_index") or fallback_index)
        duration = max(0.5, float(item.get("duration_seconds") or 1))
        output_path = target_dir / f"director-draft-{index:03d}.mp4"
        color = CARD_COLORS[(index - 1) % len(CARD_COLORS)]
        args = [
            executable, "-y", "-f", "lavfi", "-i",
            f"color=c={color}:s={width}x{height}:r={fps}:d={duration:.3f}",
            "-map", "0:v:0", "-an", "-vf", _card_video_filter(item, width, height, index),
            "-t", f"{duration:.3f}", "-r", str(fps), *_encoding_arguments(codec),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output_path),
        ]
        _run(args, target_dir)
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise FfmpegRenderError(f"FFmpeg không tạo visual draft cho segment {index}")
        results.append(
            {
                "segment_id": int(item["id"]),
                "segment_index": index,
                "visual_path": str(output_path),
                "duration_seconds": int(round(duration)),
            }
        )
    return results


def _supports_nvenc(executable: str) -> bool:
    """Check whether the local FFmpeg build exposes NVIDIA NVENC."""
    try:
        result = subprocess.run(
            [executable, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and "h264_nvenc" in (result.stdout or "")


def nvenc_available(binary: str = "ffmpeg") -> bool:
    executable = resolve_ffmpeg(binary)
    return bool(executable and _supports_nvenc(executable))


def _encoding_arguments(codec: str) -> list[str]:
    if codec == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23", "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]


def _segment_arguments(
    executable: str,
    item: dict[str, Any],
    visual: Path | None,
    audio: Path | None,
    segment_output: Path,
    duration: float,
    width: int,
    height: int,
    fps: int,
    index: int,
    codec: str,
    subtitle_path: Path | None = None,
    background_music: Path | None = None,
    music_volume: float = 0.12,
    transition: str = "fade",
    effect: str = "",
) -> list[str]:
    if not visual:
        raise FfmpegRenderError(
            f"Segment {index} chưa có cảnh hình ảnh. Hãy chuẩn bị cảnh nguồn, asset upload hoặc cảnh AI trước khi render."
        )
    args = [executable, "-y"]
    if visual.suffix.lower() in IMAGE_EXTENSIONS:
        args += ["-loop", "1", "-framerate", str(fps), "-i", str(visual)]
    else:
        # The visual is looped only to cover a sub-frame duration difference.
        # Its original audio is never mapped into the rendered segment.
        args += ["-stream_loop", "-1", "-i", str(visual)]
    if audio:
        args += ["-i", str(audio)]
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    if background_music:
        args += ["-stream_loop", "-1", "-i", str(background_music)]

    filters: list[str] = []
    if visual.suffix.lower() in IMAGE_EXTENSIONS:
        # Give still images a restrained Ken-Burns motion.  The image input is
        # looped at the project frame rate, therefore d=1 advances the zoom a
        # tiny amount per output frame without changing the segment duration.
        # An edit plan can override the direction per scene, or hold a scene
        # perfectly still — which some scenes want, e.g. a card the script
        # deliberately parks on screen for the viewer to read or screenshot.
        motion = str(effect or "").strip().lower()
        if motion == "static":
            pass
        elif motion == "zoom_out":
            filters.append(
                f"zoompan=z='max(1.055-0.0007*on,1.0)':x='iw/2-(iw/zoom/2)':"
                f"y='ih/2-(ih/zoom/2)':d=1:s={width}x{height}:fps={fps}"
            )
        else:
            filters.append(
                f"zoompan=z='min(zoom+0.0007,1.055)':x='iw/2-(iw/zoom/2)':"
                f"y='ih/2-(ih/zoom/2)':d=1:s={width}x{height}:fps={fps}"
            )
    filters.extend([
        f"scale={width}:{height}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "format=yuv420p",
    ])
    if str(transition or "fade").strip().lower() == "fade":
        fade_seconds = 0.12
        filters.extend([
            f"fade=t=in:st=0:d={fade_seconds}",
            f"fade=t=out:st={max(0.0, duration - fade_seconds):.3f}:d={fade_seconds}",
        ])
    if subtitle_path and subtitle_path.is_file():
        # FFmpeg filter syntax treats ':' as a separator, including the drive
        # letter on Windows.  Escape the path and keep subtitles compact at the
        # bottom so the output remains a video, not a sequence of text cards.
        escaped_path = subtitle_path.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")
        style = (
            # SRT otherwise defaults to the legacy 384x288 subtitle canvas and
            # becomes disproportionately large on a 1080p video.
            "PlayResX=1920,PlayResY=1080,FontName=Arial,FontSize=36,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,"
            "Alignment=2,MarginV=64"
        )
        filters.append(f"subtitles=filename='{escaped_path}':charenc=UTF-8:force_style='{style}'")
    video_filter = ",".join(filters)
    result = args + ["-map", "0:v:0"]
    if background_music:
        music_level = max(0.0, min(float(music_volume), 0.5))
        audio_filter = (
            # Keep speech intelligible and prevent clipping in the final mix.
            # The music stream is side-chained by the voice stream, so its
            # level automatically drops while narration is present.
            f"[1:a]aresample=48000,highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=11,"
            f"afade=t=in:st=0:d=0.10,afade=t=out:st={max(0.0, duration - 0.12):.3f}:d=0.12[voice];"
            f"[2:a]aresample=48000,volume={music_level:.3f},afade=t=in:st=0:d=0.20[music];"
            "[music][voice]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=250[ducked_music];"
            "[voice][ducked_music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
        )
        result += ["-map", "[aout]", "-filter_complex", audio_filter, "-vf", video_filter]
    else:
        result += [
            "-map", "1:a:0", "-vf", video_filter,
            "-af", (
                f"aresample=48000,highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=11,"
                f"afade=t=in:st=0:d=0.10,afade=t=out:st={max(0.0, duration - 0.12):.3f}:d=0.12"
            ),
        ]
    result += [
        "-t", f"{duration:.3f}", "-r", str(fps),
        *_encoding_arguments(codec),
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(segment_output),
    ]
    return result


def render_timeline_with_ffmpeg(
    timeline: list[dict[str, Any]],
    output_dir: Path,
    output_filename: str = "final.mp4",
    binary: str = "ffmpeg",
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    background_music: Path | None = None,
    music_volume: float = 0.12,
    transition: str = "fade",
) -> str:
    """Render timeline segments locally without requiring a custom command template.

    Every segment receives a video stream and a silent or supplied audio stream, so
    the final concat remains compatible even when only some segments have assets.
    """
    executable = resolve_ffmpeg(binary)
    if not executable:
        raise FfmpegRenderError(
            f"Không tìm thấy FFmpeg ({binary}). Cài FFmpeg hoặc đặt FFMPEG_BINARY trong .env"
        )
    if not timeline:
        raise FfmpegRenderError("Timeline không có segment để render")

    missing_visuals = [
        str(item.get("segment_index") or "?")
        for item in timeline
        if not str(item.get("visual_path") or "").strip()
    ]
    if missing_visuals:
        raise FfmpegRenderError(
            "Chưa có cảnh hình ảnh cho segment: " + ", ".join(missing_visuals)
            + ". Hãy chạy ‘Chuẩn bị cảnh nguồn’ hoặc gắn asset/cảnh AI trước."
        )

    output_dir = Path(output_dir)
    if background_music:
        background_music = Path(background_music).expanduser().resolve()
        if not background_music.is_file():
            raise FfmpegRenderError(f"Không tìm thấy nhạc nền: {background_music}")
    segments_dir = output_dir / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    subtitles_dir = output_dir / "subtitles"
    subtitles_dir.mkdir(parents=True, exist_ok=True)
    segment_outputs: list[Path] = []
    if GPU_ONLY and not _supports_nvenc(executable):
        raise FfmpegRenderError(
            "GPU-only mode is enabled but FFmpeg has no h264_nvenc encoder. "
            "The app will not render with libx264/CPU."
        )
    preferred_codec = "h264_nvenc" if _supports_nvenc(executable) else "libx264"

    for item in timeline:
        index = int(item.get("segment_index") or len(segment_outputs) + 1)
        visual = _existing_path(item.get("visual_path"), "visual", index)
        audio = _existing_path(item.get("audio_path"), "audio", index)
        actual_audio_duration = media_duration_seconds(audio, executable) if audio else None
        duration = max(0.1, float(actual_audio_duration or item.get("duration_seconds") or 1))
        segment_output = segments_dir / f"segment-{index:03d}.mp4"
        subtitle_text = str(item.get("subtitle_text") or item.get("voice_text") or "").strip()
        subtitle_path = _existing_path(item.get("subtitle_path"), "subtitle", index)
        if subtitle_path is None and subtitle_text:
            subtitle_path = write_segment_srt(
                subtitles_dir / f"segment-{index:03d}.srt",
                subtitle_text,
                duration,
            )

        # An edit plan can set these per scene (see /api/projects/{id}/edit-plan);
        # without one every scene keeps the project-wide transition and the
        # default gentle push-in.
        segment_transition = str(item.get("edit_transition") or transition or "fade")
        segment_effect = str(item.get("edit_effect") or "")
        args = _segment_arguments(
            executable, item, visual, audio, segment_output, duration,
            width, height, fps, index, preferred_codec, subtitle_path,
            background_music, music_volume, segment_transition, segment_effect,
        )
        try:
            _run(args, output_dir)
        except FfmpegRenderError:
            if preferred_codec != "h264_nvenc" or GPU_ONLY:
                raise
            # Some FFmpeg builds expose NVENC although the active driver cannot use it.
            _run(
                _segment_arguments(
                    executable, item, visual, audio, segment_output, duration,
                    width, height, fps, index, "libx264", subtitle_path,
                    background_music, music_volume, segment_transition, segment_effect,
                ),
                output_dir,
            )
        if not segment_output.is_file():
            raise FfmpegRenderError(f"FFmpeg không tạo segment {index}: {segment_output}")
        segment_outputs.append(segment_output)

    concat_file = output_dir / "concat.txt"
    concat_file.write_text(
        "\n".join(_concat_line(path) for path in segment_outputs) + "\n",
        encoding="utf-8",
    )
    final_path = output_dir / output_filename
    _run(
        [
            executable,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(final_path),
        ],
        output_dir,
    )
    if not final_path.is_file():
        raise FfmpegRenderError(f"FFmpeg không tạo file cuối: {final_path}")
    return str(final_path)
