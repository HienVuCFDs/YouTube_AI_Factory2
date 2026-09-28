from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .settings import GPU_ONLY
from .subtitle_builder import write_segment_srt
from .graphic_overlays import graphic_overlay_filters, retime_graphic_overlays
from .scene_direction import resolve_direction
from .scene_compositor import composite_scene_direction


class FfmpegRenderError(RuntimeError):
    pass


STILL_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
IMAGE_EXTENSIONS = {*STILL_IMAGE_EXTENSIONS, ".gif"}
CARD_COLORS = ("0x0B1020", "0x111827", "0x172033", "0x0F172A")
WINDOWS_FONT = Path("C:/Windows/Fonts/arial.ttf")


def resolve_ffmpeg(binary: str = "ffmpeg") -> str | None:
    candidate = str(binary or "ffmpeg").strip() or "ffmpeg"
    path = Path(candidate)
    if path.is_file():
        return str(path)
    return shutil.which(candidate)


def resolve_ffprobe(ffmpeg_binary: str = "ffmpeg") -> str | None:
    """Find ffprobe without rewriting directory names containing ``ffmpeg``."""
    ffmpeg_path = resolve_ffmpeg(ffmpeg_binary)
    if ffmpeg_path:
        for name in ("ffprobe.exe", "ffprobe"):
            sibling = Path(ffmpeg_path).with_name(name)
            if sibling.is_file():
                return str(sibling)
    return shutil.which("ffprobe")


def ffmpeg_available(binary: str = "ffmpeg") -> bool:
    return resolve_ffmpeg(binary) is not None


def media_duration_seconds(path: Path, ffmpeg_binary: str = "ffmpeg") -> float | None:
    """Return the measured media duration, or None when ffprobe is unavailable."""
    target = Path(path)
    if not target.is_file():
        return None
    probe = resolve_ffprobe(ffmpeg_binary)
    if probe:
        try:
            result = subprocess.run(
                [
                    probe, "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", str(target),
                ],
                capture_output=True,
                text=True, encoding="utf-8", errors="replace",
                timeout=30,
                check=False,
            )
            if result.returncode == 0:
                duration = float((result.stdout or "").strip())
                if duration > 0:
                    return duration
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return None


def _run(args: list[str], cwd: Path) -> None:
    try:
        result = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
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


def _transition_name(value: Any) -> str:
    transition = str(value or "").strip().lower()
    if transition in {"", "none", "cut"}:
        return "cut"
    if transition in {"fade", "crossfade"}:
        return "fade"
    return "cut"


def _boundary_transitions(timeline: list[dict[str, Any]], default_transition: str) -> list[str]:
    """The transition into each next scene.

    The timeline stores edit_transition on a scene row. For the final stitch,
    that reads most naturally as "how this scene enters", so the boundary
    between scene N and N+1 is controlled by scene N+1 when it has a value,
    otherwise by the project default.
    """
    if len(timeline) < 2:
        return []
    return [
        _transition_name(timeline[index].get("edit_transition") or default_transition)
        for index in range(1, len(timeline))
    ]


def _has_final_crossfades(timeline: list[dict[str, Any]], default_transition: str) -> bool:
    return "fade" in _boundary_transitions(timeline, default_transition)


def _crossfade_seconds(left_duration: float, right_duration: float) -> float:
    """A short editorial dissolve that cannot eat a whole tiny scene."""
    return max(0.0, min(0.35, left_duration * 0.25, right_duration * 0.25))


def _write_concat_final(
    executable: str,
    segment_outputs: list[Path],
    concat_file: Path,
    final_path: Path,
    output_dir: Path,
) -> None:
    concat_file.write_text(
        "\n".join(_concat_line(path) for path in segment_outputs) + "\n",
        encoding="utf-8",
    )
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


def _render_final_with_transitions(
    executable: str,
    segment_outputs: list[Path],
    segment_durations: list[float],
    boundary_transitions: list[str],
    final_path: Path,
    output_dir: Path,
    fps: int,
    codec: str,
) -> None:
    """Join finished scenes, using real crossfades at scene boundaries.

    Segment rendering owns per-scene effects, subtitles and overlays. The last
    pass owns how scenes meet each other. A concat-copy pass cannot express a
    dissolve, so when any boundary asks for fade this builds one filter graph
    for both picture and audio.
    """
    if len(segment_outputs) == 1 or "fade" not in boundary_transitions:
        _write_concat_final(executable, segment_outputs, output_dir / "concat.txt", final_path, output_dir)
        return

    args = [executable, "-y"]
    for path in segment_outputs:
        args += ["-i", str(path)]

    graph: list[str] = []
    normalized_video_labels: list[str] = []
    normalized_audio_labels: list[str] = []
    for input_index in range(len(segment_outputs)):
        video_out = f"[v{input_index}n]"
        audio_out = f"[a{input_index}n]"
        graph.append(
            f"[{input_index}:v]fps={fps},settb=AVTB,setpts=PTS-STARTPTS,"
            f"format=yuv420p{video_out}"
        )
        graph.append(
            f"[{input_index}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"asetpts=PTS-STARTPTS{audio_out}"
        )
        normalized_video_labels.append(video_out)
        normalized_audio_labels.append(audio_out)

    video_label = normalized_video_labels[0]
    audio_label = normalized_audio_labels[0]
    composed_duration = max(0.1, float(segment_durations[0]))
    for index, next_path in enumerate(segment_outputs[1:], start=1):
        next_duration = max(0.1, float(segment_durations[index]))
        transition = boundary_transitions[index - 1] if index - 1 < len(boundary_transitions) else "cut"
        next_video = normalized_video_labels[index]
        next_audio = normalized_audio_labels[index]
        out_video = f"[v{index}]"
        out_audio = f"[a{index}]"
        if transition == "fade":
            fade = _crossfade_seconds(composed_duration, next_duration)
            if fade >= 0.08:
                offset = max(0.0, composed_duration - fade)
                graph.append(
                    f"{video_label}{next_video}xfade=transition=fade:duration={fade:.3f}:"
                    f"offset={offset:.3f}{out_video}"
                )
                graph.append(
                    f"{audio_label}{next_audio}acrossfade=d={fade:.3f}:c1=tri:c2=tri{out_audio}"
                )
                composed_duration += next_duration - fade
            else:
                graph.append(
                    f"{video_label}{audio_label}{next_video}{next_audio}"
                    f"concat=n=2:v=1:a=1{out_video}{out_audio}"
                )
                composed_duration += next_duration
        else:
            graph.append(
                f"{video_label}{audio_label}{next_video}{next_audio}"
                f"concat=n=2:v=1:a=1{out_video}{out_audio}"
            )
            composed_duration += next_duration
        video_label = out_video
        audio_label = out_audio

    _run(
        args + [
            "-filter_complex",
            ";".join(graph),
            "-map",
            video_label,
            "-map",
            audio_label,
            "-r",
            str(fps),
            *_encoding_arguments(codec),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(final_path),
        ],
        output_dir,
    )


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


# Bounded, and overridable, because the encoder sessions and the memory are
# shared with everything else on the machine.
RENDER_WORKERS = max(1, min(int(os.getenv("RENDER_WORKER_COUNT", "3")), 8))


def _supports_nvenc(executable: str) -> bool:
    """Check whether the local FFmpeg build exposes NVIDIA NVENC."""
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


def nvenc_available(binary: str = "ffmpeg") -> bool:
    executable = resolve_ffmpeg(binary)
    return bool(executable and _supports_nvenc(executable))


def _encoding_arguments(codec: str) -> list[str]:
    if codec == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23", "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]


# A trimmed clip shorter than this reads as a glitch rather than a shot.
_MINIMUM_TRIMMED_CLIP_SECONDS = 0.4


# Where each mark sits, as a fraction of the frame. Fractions rather than
# pixels because the frame these land on is the source clip's own - 1920x1080
# for the material this app reups - while the finished video may be anything,
# and this project renders Shorts at 1080x1920. Boxes worked out against the
# output size were landing outside a landscape frame entirely, which is why
# burned-in subtitles were still legible after being "removed".
_MARK_BOXES: dict[str, tuple[float, float, float, float]] = {
    "top_left": (0.0, 0.0, 0.20, 0.125),
    "top_right": (0.80, 0.0, 0.20, 0.125),
    "top_center": (0.05, 0.0, 0.90, 0.125),
    "bottom_left": (0.0, 0.875, 0.20, 0.125),
    "bottom_right": (0.80, 0.875, 0.20, 0.125),
    "bottom_center": (0.05, 0.82, 0.90, 0.18),
    "center": (0.05, 0.41, 0.90, 0.18),
    "full": (0.0, 0.0, 1.0, 1.0),
}

# boxblur caps its radius against the plane it is given - on a subtitle band,
# which is wide and only a few dozen rows tall, the chroma cap lands around 16
# and FFmpeg refuses anything larger. Blurring a whole line of type at that
# radius smeared the letters without destroying them: CJK subtitles stayed
# legible through it. gblur takes a sigma with no such ceiling.
_BLUR_FALLBACK = "gblur=sigma=16:steps=3"


def _blur_filter(region_width: float, region_height: float) -> str:
    """A blur sized to the region, strong enough that type stops resolving.

    Fixed strength cannot work: the same band is 40 pixels tall on a 480p
    source and 160 on a 4K one. Tied to the shorter side of the region, a
    subtitle dissolves at any resolution without the patch reading as a plain
    grey rectangle laid over the picture.
    """
    shorter = min(float(region_width), float(region_height))
    if shorter <= 0:
        return _BLUR_FALLBACK
    sigma = max(6.0, min(shorter / 2.5, 120.0))
    return f"gblur=sigma={sigma:.1f}:steps=3"


def _explicit_box(value: Any) -> tuple[float, float, float, float] | None:
    """A cleanup's own rectangle, as fractions of the frame, if it has one."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x, y, w, h = (float(part) for part in value)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    x = min(max(x, 0.0), 1.0)
    y = min(max(y, 0.0), 1.0)
    return x, y, min(w, 1.0 - x), min(h, 1.0 - y)


def _cleanup_filters(
    cleanups: list[dict[str, Any]],
    width: int,
    height: int,
) -> tuple[list[str], list[tuple[float, float, float, float]]]:
    """What it takes to get the source's own marks off the picture.

    A retold clip still carries the original channel's logo, its watermark and
    its burned-in subtitles - the last in a language this audience is not being
    given, and already replaced by the new narration.

    Returns the filters that go straight into the chain (delogo, crop) and,
    separately, the regions to blur: a blur cannot be written as one filter,
    it needs the frame split, a copy cropped and blurred, and that copy laid
    back over the original. The caller weaves those into the graph.
    """
    linear: list[str] = []
    blurs: list[tuple[float, float, float, float]] = []
    for cleanup in cleanups:
        if not isinstance(cleanup, dict):
            continue
        # A measured box beats a named one. The presets are guesses at where a
        # mark usually sits, and a subtitle that a source burns higher than
        # usual falls outside them entirely - blurring the preset then covers
        # clean picture and leaves the lettering legible.
        box = _explicit_box(cleanup.get("box")) or _MARK_BOXES.get(
            str(cleanup.get("position") or "").strip().lower()
        )
        if not box:
            continue
        fx, fy, fw, fh = box
        method = str(cleanup.get("method") or "blur").strip().lower()
        if method == "crop" and (fy <= 0.001 or fy + fh >= 0.999):
            # Only safe against an edge; the scale/pad further down the chain
            # puts the frame back to its target size.
            keep = max(16, int(round(height * (1 - fh))))
            linear.append(f"crop={width}:{keep}:0:{int(round(height * fh)) if fy <= 0.001 else 0}")
            continue
        if method == "delogo":
            # delogo rebuilds a rectangle from the pixels around it, so it takes
            # integers, not expressions - it is the one cleanup that has to be
            # sized against a known frame. It must also stay a pixel inside on
            # every side, or it has no border to read and FFmpeg refuses it.
            x = max(1, min(int(round(width * fx)), width - 3))
            y = max(1, min(int(round(height * fy)), height - 3))
            w = max(1, min(int(round(width * fw)), width - x - 1))
            h = max(1, min(int(round(height * fh)), height - y - 1))
            linear.append(f"delogo=x={x}:y={y}:w={w}:h={h}")
            continue
        blurs.append(box)
    return linear, blurs


def _compose_video_graph(
    before: list[str],
    blurs: list[tuple[float, float, float, float]],
    after: list[str],
    frame_size: tuple[int, int] | None = None,
) -> str:
    """One filtergraph for -vf, blurred regions and all.

    -vf takes a labelled graph as happily as a flat chain, provided the graph
    has exactly one input and one output. Each blurred region costs a branch:
    the frame is split, one copy is cropped to the region and blurred, and that
    copy is laid back over the picture at the same place.
    """
    if not blurs:
        return ",".join(before + after)
    branches = len(blurs) + 1
    split = "split" if branches == 2 else f"split={branches}"
    head = ",".join([*before, split])
    chains = [head + "[base]" + "".join(f"[b{i}]" for i in range(len(blurs)))]
    frame_width, frame_height = frame_size or (1920, 1080)
    for index, (fx, fy, fw, fh) in enumerate(blurs):
        chains.append(
            f"[b{index}]crop=w=iw*{fw:.4f}:h=ih*{fh:.4f}:x=iw*{fx:.4f}:y=ih*{fy:.4f},"
            f"{_blur_filter(frame_width * fw, frame_height * fh)}[f{index}]"
        )
    source = "[base]"
    for index, (fx, fy, _w, _h) in enumerate(blurs):
        overlay = f"{source}[f{index}]overlay=x=W*{fx:.4f}:y=H*{fy:.4f}"
        if index == len(blurs) - 1:
            chains.append(",".join([overlay, *after]))
        else:
            chains.append(f"{overlay}[o{index}]")
            source = f"[o{index}]"
    return ";".join(chains)


def _usable_clip_window(
    visual: Path,
    executable: str,
    trim_head: float,
    trim_tail: float,
) -> tuple[float, float] | None:
    """What is left of a source clip once the plan's trims are taken off.

    Returns None when there is nothing to do, and also when the trims would
    leave too little to show: a plan that asks for more than the clip holds
    must not empty the scene, so the clip is used whole instead.
    """
    head = max(0.0, float(trim_head or 0))
    tail = max(0.0, float(trim_tail or 0))
    if head <= 0 and tail <= 0:
        return None
    clip_seconds = media_duration_seconds(visual, executable)
    if not clip_seconds:
        return None
    keep = clip_seconds - head - tail
    if keep < _MINIMUM_TRIMMED_CLIP_SECONDS:
        return None
    return head, keep


def video_frame_size(path: Path, binary: str = "ffmpeg") -> tuple[int, int] | None:
    """The real pixel size of a rendered file, or None if it cannot be read."""
    path = Path(path)
    if not path.is_file():
        return None
    width, height = _mark_frame_size(path, binary, 0, 0)
    return (width, height) if width > 0 and height > 0 else None


def _mark_frame_size(
    visual: Path,
    executable: str,
    width: int,
    height: int,
) -> tuple[int, int]:
    """The frame a source mark is actually sitting on.

    A still image has already been through zoompan by this point and is at the
    output size. A video clip has not been touched yet, so its own resolution
    is the one that matters - and it is usually not the output's.
    """
    if visual.suffix.lower() in STILL_IMAGE_EXTENSIONS:
        return width, height
    ffprobe = resolve_ffprobe(executable)
    if not ffprobe:
        return width, height
    try:
        probe = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-select_streams", "v:0", "-show_entries", "stream=width,height",
                "-of", "csv=p=0:s=x", str(visual),
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return width, height
    try:
        source_width, source_height = (int(part) for part in probe.stdout.strip().split("x")[:2])
    except (TypeError, ValueError):
        return width, height
    return (source_width, source_height) if source_width > 0 and source_height > 0 else (width, height)


def _motion_filters(effect: str, width: int, height: int, fps: int) -> list[str]:
    """The camera move the edit plan asked for.

    This used to be read only for still images, so on the reup workflow - where
    every scene is a clip cut from the source - the plan's camera moves did
    nothing at all: zoom_in, zoom_out and static all rendered the same.

    The input is looped at the frame rate, so d=1 advances the zoom a little
    per output frame without changing how long the scene lasts.
    """
    motion = str(effect or "").strip().lower()
    if motion == "zoom_in":
        zoom = "min(zoom+0.0007,1.055)"
    elif motion == "zoom_out":
        zoom = "max(1.055-0.0007*on,1.0)"
    else:
        # 'static' means hold, and an effect nobody recognises is not worth
        # guessing at - some scenes are meant to be read off the screen.
        return []
    return [
        f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d=1:s={width}x{height}:fps={fps}"
    ]


def _sound_cue_inputs(raw: Any, segment_index: int) -> list[dict[str, Any]]:
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise FfmpegRenderError(f"Sound cue của cảnh {segment_index} không phải JSON hợp lệ") from exc
    if not isinstance(raw, list):
        return []
    cues: list[dict[str, Any]] = []
    for cue in raw[:8]:
        if not isinstance(cue, dict):
            continue
        path_value = str(cue.get("asset_path") or cue.get("file_path") or "").strip()
        if not path_value:
            continue
        path = Path(path_value).expanduser()
        if not path.is_file():
            raise FfmpegRenderError(f"Không tìm thấy sound cue của segment {segment_index}: {path}")
        try:
            start = max(0.0, float(cue.get("start_seconds") or 0))
            end = float(cue.get("end_seconds") or start + 0.6)
        except (TypeError, ValueError) as exc:
            raise FfmpegRenderError(f"Thời điểm sound cue của segment {segment_index} không hợp lệ") from exc
        length = max(0.05, min(20.0, end - start))
        intensity = str(cue.get("intensity") or "medium").strip().lower()
        volume = {"low": 0.18, "medium": 0.28, "high": 0.42}.get(intensity, 0.28)
        cues.append({"path": path.resolve(), "start_seconds": start, "duration_seconds": length, "volume": volume})
    return cues


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
    cleanups: list[dict[str, Any]] | None = None,
    trim_head: float = 0.0,
    trim_tail: float = 0.0,
    overlays: list[dict[str, Any]] | None = None,
    fit: str = "pad",
    sound_cues: list[dict[str, Any]] | None = None,
) -> list[str]:
    if not visual:
        raise FfmpegRenderError(
            f"Segment {index} chưa có cảnh hình ảnh. Hãy chuẩn bị cảnh nguồn, asset upload hoặc cảnh AI trước khi render."
        )
    args = [executable, "-y"]
    if visual.suffix.lower() in STILL_IMAGE_EXTENSIONS:
        args += ["-loop", "1", "-framerate", str(fps), "-i", str(visual)]
    else:
        # The edit plan can shave dead weight off a source clip: a beat of
        # silence before the line starts, a held frame after it ends. Both are
        # input options, so they narrow the window FFmpeg reads and loops,
        # rather than cutting the finished segment - the segment's length is
        # set by the voiceover, and must not change.
        window = _usable_clip_window(visual, executable, trim_head, trim_tail)
        if window:
            head, keep = window
            args += ["-stream_loop", "-1", "-ss", f"{head:.3f}", "-t", f"{keep:.3f}", "-i", str(visual)]
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
    sfx_inputs = list(sound_cues or [])
    for cue in sfx_inputs:
        args += ["-i", str(cue["path"])]

    # Where the marks are is decided on the frame they are actually on: a
    # still has already been through zoompan and is at the output size, a clip
    # has not been touched and is still its own.
    mark_width, mark_height = _mark_frame_size(visual, executable, width, height)
    linear_cleanups, blur_regions = _cleanup_filters(cleanups or [], mark_width, mark_height)

    filters: list[str] = []
    after: list[str] = []
    if visual.suffix.lower() in STILL_IMAGE_EXTENSIONS:
        # zoompan's ``s=`` changes the output canvas but does not preserve the
        # input aspect ratio by itself.  Fit the still first; otherwise a
        # landscape AI insert becomes a tall, stretched figure in 9:16.
        if str(fit or "pad").strip().lower() == "cover":
            filters.extend([
                f"scale={width}:{height}:force_original_aspect_ratio=increase",
                f"crop={width}:{height}",
            ])
        else:
            filters.extend([
                f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            ])
        # A still with no motion at all reads as a broken video, so the plan's
        # silence means a restrained push rather than nothing.
        filters.extend(_motion_filters(effect or "zoom_in", width, height, fps))
        filters.extend(linear_cleanups)
    else:
        # The clip already moves, so silence here means leave it alone. When
        # the plan does ask for a move, it happens after the marks are covered
        # - so a logo and the patch over it travel together - and at the
        # clip's own shape, or the push would stretch the picture on its way
        # to a vertical frame.
        filters.extend(linear_cleanups)
        after.extend(_motion_filters(effect, mark_width, mark_height, fps))
    if str(fit or "pad").strip().lower() == "cover":
        # A vertical short letterboxed from 16:9 is mostly black bars, and a
        # viewer scrolls past it. Filling the frame loses the sides, which for
        # a short is the right trade; the long edit keeps padding, where
        # losing picture would be the wrong one.
        after.extend([
            f"scale={width}:{height}:force_original_aspect_ratio=increase",
            f"crop={width}:{height}",
            "format=yuv420p",
        ])
    else:
        after.extend([
            f"scale={width}:{height}:force_original_aspect_ratio=decrease",
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "format=yuv420p",
        ])
    if str(transition or "fade").strip().lower() == "fade":
        fade_seconds = 0.12
        after.extend([
            f"fade=t=in:st=0:d={fade_seconds}",
            f"fade=t=out:st={max(0.0, duration - fade_seconds):.3f}:d={fade_seconds}",
        ])
    try:
        after.extend(graphic_overlay_filters(
            overlays or [], duration, width, height, segment_output.parent,
            segment_output.stem, WINDOWS_FONT,
        ))
    except ValueError as exc:
        raise FfmpegRenderError(f"Overlay của cảnh {index} không hợp lệ: {exc}") from exc
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
        after.append(f"subtitles=filename='{escaped_path}':charenc=UTF-8:force_style='{style}'")
    video_filter = _compose_video_graph(
        filters, blur_regions, after, frame_size=(mark_width, mark_height)
    )
    result = args + ["-map", "0:v:0"]
    if background_music or sfx_inputs:
        music_level = max(0.0, min(float(music_volume), 0.5))
        audio_parts = [
            f"[1:a]aresample=48000,highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=11,"
            f"afade=t=in:st=0:d=0.10,afade=t=out:st={max(0.0, duration - 0.12):.3f}:d=0.12[voice]"
        ]
        mix_labels = ["[voice]"]
        next_input = 2
        if background_music:
            audio_parts.append("[voice]asplit=2[voice_mix][voice_sidechain]")
            mix_labels = ["[voice_mix]"]
            ducks = item.get("sound_cues") or []
            if isinstance(ducks, str):
                ducks = json.loads(ducks)
            envelope = "".join(
                f",volume=0.35:enable='between(t,{float(cue['start_seconds']):.3f},{float(cue['end_seconds']):.3f})'"
                for cue in ducks if cue.get("type") == "music_duck"
            )
            audio_parts.append(
                f"[{next_input}:a]aresample=48000,volume={music_level:.3f}{envelope},afade=t=in:st=0:d=0.20[music]"
            )
            audio_parts.append(
                "[music][voice_sidechain]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=250[ducked_music]"
            )
            mix_labels.append("[ducked_music]")
            next_input += 1
        for cue_index, cue in enumerate(sfx_inputs, start=1):
            delay_ms = int(round(float(cue.get("start_seconds") or 0) * 1000))
            cue_duration = max(0.05, float(cue.get("duration_seconds") or 0.5))
            volume = max(0.0, min(float(cue.get("volume") or 0.28), 1.0))
            label = f"[sfx{cue_index}]"
            audio_parts.append(
                f"[{next_input}:a]aresample=48000,atrim=0:{cue_duration:.3f},asetpts=PTS-STARTPTS,"
                f"volume={volume:.3f},adelay={delay_ms}|{delay_ms}{label}"
            )
            mix_labels.append(label)
            next_input += 1
        audio_parts.append(
            "".join(mix_labels)
            + f"amix=inputs={len(mix_labels)}:duration=first:dropout_transition=0:normalize=0[aout]"
        )
        result += ["-map", "[aout]", "-filter_complex", ";".join(audio_parts), "-vf", video_filter]
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
    fit: str = "pad",
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
    segment_durations: list[float] = []
    execution_report: list[dict[str, Any]] = []
    if GPU_ONLY and not _supports_nvenc(executable):
        raise FfmpegRenderError(
            "GPU-only mode is enabled but FFmpeg has no h264_nvenc encoder. "
            "The app will not render with libx264/CPU."
        )
    preferred_codec = "h264_nvenc" if _supports_nvenc(executable) else "libx264"
    final_transitions = _boundary_transitions(timeline, transition)
    final_has_crossfades = "fade" in final_transitions

    def _render_one(position: int, item: dict[str, Any]) -> tuple[Path, float, dict[str, Any]]:
        index = int(item.get("segment_index") or position + 1)
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
        render_transition = "cut" if final_has_crossfades and _transition_name(segment_transition) == "fade" else segment_transition
        try:
            segment_cleanups = json.loads(str(item.get("edit_cleanups") or "[]"))
        except (TypeError, ValueError):
            segment_cleanups = []
        raw_overlays = item.get("overlays") or []
        try:
            segment_overlays = json.loads(raw_overlays) if isinstance(raw_overlays, str) else raw_overlays
        except (TypeError, ValueError) as exc:
            raise FfmpegRenderError(f"Overlay của cảnh {index} không phải JSON hợp lệ") from exc
        if not isinstance(segment_overlays, list):
            raise FfmpegRenderError(f"Overlay của cảnh {index} phải là danh sách")
        try:
            segment_overlays = retime_graphic_overlays(
                segment_overlays, max(0.1, float(item.get("duration_seconds") or duration)), duration,
            )
        except ValueError as exc:
            raise FfmpegRenderError(f"Overlay của cảnh {index} không hợp lệ: {exc}") from exc
        raw_cues = item.get("sound_cues") or []
        if isinstance(raw_cues, str):
            raw_cues = json.loads(raw_cues)
        cue_ratio = duration / max(.1, float(item.get("duration_seconds") or duration))
        timed_cues = [{**cue, "start_seconds": float(cue.get("start_seconds") or 0) * cue_ratio,
                      "end_seconds": float(cue.get("end_seconds") or .5) * cue_ratio} for cue in raw_cues]
        item = {**item, "sound_cues": timed_cues}
        segment_sound_cues = _sound_cue_inputs(timed_cues, index)
        trim_head = float(item.get("edit_trim_head") or 0)
        trim_tail = float(item.get("edit_trim_tail") or 0)

        # A storyboard scene may contain several approved edit beats.  First
        # turn them into one silent visual track, then apply the scene's voice
        # exactly once below.  This avoids the old failure mode where splitting
        # a scene into inserts also split or lost its narration.
        beats = [beat for beat in (item.get("edit_beats") or []) if str(beat.get("visual_path") or "").strip()]
        if beats:
            beat_dir = segments_dir / f"beats-{index:03d}"
            beat_dir.mkdir(parents=True, exist_ok=True)
            beat_outputs: list[Path] = []
            for beat_index, beat in enumerate(beats, start=1):
                beat_visual = _existing_path(beat.get("visual_path"), "edit beat", beat_index)
                beat_duration = max(0.15, float(beat.get("duration_seconds") or 0.15))
                beat_output = beat_dir / f"beat-{beat_index:03d}.mp4"
                # Consecutive primary beats must continue through the source
                # clip.  Starting every beat at frame zero made the same first
                # seconds repeat whenever the plan split one clip into several
                # effects.  Inserted frames/AI stills are independent assets,
                # so their timeline offset must not be used as an input seek.
                source_kind = str(beat.get("source_kind") or "").strip().lower()
                beat_trim_head = (
                    max(0.0, float(beat.get("start_seconds") or 0.0))
                    if source_kind == "primary" and beat_visual.suffix.lower() not in STILL_IMAGE_EXTENSIONS
                    else 0.0
                )
                beat_args = _segment_arguments(
                    executable, item, beat_visual, None, beat_output, beat_duration,
                    width, height, fps, index, preferred_codec, None, None, 0.0,
                    str(beat.get("transition") or "cut"), str(beat.get("effect") or "static"),
                    [], beat_trim_head, 0.0, fit=fit,
                )
                _run(beat_args, output_dir)
                beat_outputs.append(beat_output)
            beat_concat = beat_dir / "concat.txt"
            beat_concat.write_text("\n".join(_concat_line(path) for path in beat_outputs) + "\n", encoding="utf-8")
            compound = beat_dir / "composition.mp4"
            _run([executable, "-y", "-f", "concat", "-safe", "0", "-i", str(beat_concat), "-an", "-c:v", "copy", str(compound)], output_dir)
            visual = compound
            trim_head = trim_tail = 0.0
            # The composition already carries each beat's movement and fade.
            segment_effect = "static"
            render_transition = "cut"
        args = _segment_arguments(
            executable, item, visual, audio, segment_output, duration,
            width, height, fps, index, preferred_codec, subtitle_path,
            background_music, music_volume, render_transition, segment_effect,
            segment_cleanups, trim_head, trim_tail,
            fit=fit, overlays=segment_overlays, sound_cues=segment_sound_cues,
        )
        segment_codec = preferred_codec
        try:
            _run(args, output_dir)
        except FfmpegRenderError:
            if preferred_codec != "h264_nvenc" or GPU_ONLY:
                raise
            segment_codec = "libx264"
            # Some FFmpeg builds expose NVENC although the active driver cannot use it.
            _run(
                _segment_arguments(
                    executable, item, visual, audio, segment_output, duration,
                    width, height, fps, index, "libx264", subtitle_path,
                    background_music, music_volume, render_transition, segment_effect,
                    segment_cleanups, trim_head, trim_tail,
                    fit=fit, overlays=segment_overlays, sound_cues=segment_sound_cues,
                ),
                output_dir,
            )
        if not segment_output.is_file():
            raise FfmpegRenderError(f"FFmpeg không tạo segment {index}: {segment_output}")
        raw_direction = item.get("edit_direction") or {}
        if isinstance(raw_direction, str):
            raw_direction = json.loads(raw_direction)
        report = {"segment_id": item.get("id"), "segment_index": index,
                  "overlays": len(segment_overlays), "sound_cues": len(segment_sound_cues)}
        if raw_direction:
            from .speech_timing import scene_speech_timing
            timing = scene_speech_timing(item) if any(
                layer.get("anchor_text") for layer in raw_direction.get("graphic_layers", [])
            ) else {"words": [], "timing_basis": "estimated"}
            resolved = resolve_direction(raw_direction, duration, timing.get("words"))
            segment_output, applied = composite_scene_direction(
                segment_output, resolved, executable, width, height, fps, segment_codec)
            report.update(applied, timing_basis=timing.get("timing_basis"))
        return segment_output, duration, report

    # The scenes are independent - each writes its own file from its own
    # visual and its own audio - but they were rendered strictly one after
    # another, which on a machine with NVENC and several cores is time spent
    # queueing rather than encoding. Order is restored from the position, so
    # the cut is the same whichever finishes first.
    rendered: list[tuple[Path, float, dict[str, Any]]] = [None] * len(timeline)  # type: ignore[list-item]
    if RENDER_WORKERS > 1 and len(timeline) > 1:
        with ThreadPoolExecutor(max_workers=min(RENDER_WORKERS, len(timeline))) as pool:
            futures = {
                pool.submit(_render_one, position, item): position
                for position, item in enumerate(timeline)
            }
            for future in as_completed(futures):
                # The first failure is raised, and the pool's context manager
                # waits for the rest rather than leaving ffmpeg processes
                # writing into a directory the caller is about to report on.
                rendered[futures[future]] = future.result()
    else:
        for position, item in enumerate(timeline):
            rendered[position] = _render_one(position, item)
    for segment_output, duration, report in rendered:
        segment_outputs.append(segment_output)
        segment_durations.append(duration)
        execution_report.append(report)

    final_path = output_dir / output_filename
    try:
        _render_final_with_transitions(
            executable, segment_outputs, segment_durations, final_transitions,
            final_path, output_dir, fps, preferred_codec,
        )
    except FfmpegRenderError:
        if preferred_codec != "h264_nvenc" or GPU_ONLY:
            raise
        _render_final_with_transitions(
            executable, segment_outputs, segment_durations, final_transitions,
            final_path, output_dir, fps, "libx264",
        )
    if not final_path.is_file():
        raise FfmpegRenderError(f"FFmpeg không tạo file cuối: {final_path}")
    final_path.with_suffix(".execution.json").write_text(
        json.dumps({"scenes": execution_report}, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(final_path)
