from __future__ import annotations

import hashlib
import mimetypes
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


# Four is what the sheet route used and what reviews were judged against;
# it is also four Flow calls per loop, so raising it costs proportionally.
GFLOW_GIF_FRAME_COUNT = 4


class GifGenerationError(RuntimeError):
    pass


def _resolve_ffmpeg(binary: str) -> str:
    candidate = Path(binary).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    resolved = shutil.which(binary)
    if not resolved:
        raise GifGenerationError(f"Khong tim thay FFmpeg ({binary}) de tao GIF")
    return resolved


def create_animated_gif(
    source_path: str | Path,
    output_path: str | Path,
    *,
    duration_seconds: float = 5,
    fps: int = 8,
    ffmpeg_binary: str = "ffmpeg",
    width: int = 960,
    height: int = 540,
) -> str:
    """Turn a 2x2 AI animation sheet into a compact looping GIF.

    The image provider creates four successive animation frames in reading
    order (top-left, top-right, bottom-left, bottom-right). FFmpeg crops those
    real AI-created frames and plays them 1-2-3-4-3-2, making a seamless
    ping-pong loop without consuming video-generation credit.
    """
    source = Path(source_path).expanduser().resolve()
    target = Path(output_path).expanduser().resolve()
    if not source.is_file():
        raise GifGenerationError(f"Khong tim thay anh nguon de tao GIF: {source}")
    if source.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        raise GifGenerationError("GIF chi duoc tao tu mot anh tinh JPG/PNG/WebP/BMP")
    target.parent.mkdir(parents=True, exist_ok=True)
    duration = max(1.0, min(float(duration_seconds), 12.0))
    frame_rate = max(4, min(int(fps or 8), 12))
    target_width = max(320, min(int(width), 1280))
    target_height = max(180, min(int(height), 720))
    sequence = (0, 1, 2, 3, 2, 1)
    coordinates = {
        0: ("0", "0"),
        1: ("iw/2", "0"),
        2: ("0", "ih/2"),
        3: ("iw/2", "ih/2"),
    }
    split_outputs = "".join(f"[sheet{index}]" for index in range(len(sequence)))
    filters = [f"[0:v]split={len(sequence)}{split_outputs}"]
    for branch, panel in enumerate(sequence):
        x, y = coordinates[panel]
        filters.append(
            f"[sheet{branch}]crop=iw/2:ih/2:{x}:{y},"
            f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase,"
            f"crop={target_width}:{target_height},setsar=1,setpts=PTS-STARTPTS[frame{branch}]"
        )
    inputs = "".join(f"[frame{index}]" for index in range(len(sequence)))
    filters.extend([
        f"{inputs}concat=n={len(sequence)}:v=1:a=0,fps={frame_rate}[sequence]",
        "[sequence]split[gif_frames][palette_frames]",
        "[palette_frames]palettegen=max_colors=128:stats_mode=diff[palette]",
        "[gif_frames][palette]paletteuse=dither=bayer:bayer_scale=3",
    ])
    filter_graph = ";".join(filters)
    panel_duration = duration / len(sequence)
    command = [
        _resolve_ffmpeg(ffmpeg_binary),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-loop",
        "1",
        "-framerate",
        str(frame_rate),
        "-t",
        f"{panel_duration:.6f}",
        "-i",
        str(source),
        "-filter_complex",
        filter_graph,
        "-t",
        f"{duration:.3f}",
        "-loop",
        "0",
        str(target),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=max(60.0, duration * 20.0),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GifGenerationError(f"FFmpeg khong tao duoc GIF: {exc}") from exc
    if result.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        detail = (result.stderr or result.stdout or "khong co chi tiet").strip()[-1500:]
        raise GifGenerationError(f"FFmpeg tao GIF that bai: {detail}")
    return str(target)


def create_gif_from_frames(
    frame_paths: list[str | Path],
    output_path: str | Path,
    *,
    duration_seconds: float = 5,
    fps: int = 8,
    ffmpeg_binary: str = "ffmpeg",
    width: int = 960,
    height: int = 540,
) -> str:
    """Assemble a GIF from frames that were each drawn as a full image.

    The 2x2 sheet in create_animated_gif asks one drawing to hold four moments
    at quarter size, and what came back moved the background while the thing
    the scene is about — a number counting up, a box filling in — stayed put.
    Frames generated one after another, each referencing the last, are full
    resolution and carry the change forward, so this takes them as separate
    files. The ping-pong ordering is the same, so the loop still has no cut.
    """
    frames = [Path(item).expanduser().resolve() for item in frame_paths]
    if len(frames) < 2:
        raise GifGenerationError("Can it nhat hai khung hinh de ghep GIF")
    for frame in frames:
        if not frame.is_file():
            raise GifGenerationError(f"Khong tim thay khung hinh: {frame}")
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    duration = max(1.0, min(float(duration_seconds), 12.0))
    frame_rate = max(4, min(int(fps or 8), 12))
    target_width = max(320, min(int(width), 1280))
    target_height = max(180, min(int(height), 720))
    # Forward then back, without repeating the two ends, so the loop reads as
    # continuous motion rather than a jump back to the start.
    order = [*frames, *reversed(frames[1:-1])]
    hold = duration / len(order)
    lines: list[str] = []
    for frame in order:
        lines.append(f"file '{frame.as_posix()}'")
        lines.append(f"duration {hold:.6f}")
    # The concat demuxer ignores the duration of the final entry, so the last
    # frame is named twice; the repeat is what makes its hold time count.
    lines.append(f"file '{order[-1].as_posix()}'")
    listing = "\n".join(lines) + "\n"
    filter_graph = (
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase,"
        f"crop={target_width}:{target_height},setsar=1,fps={frame_rate},"
        "split[gif_frames][palette_frames];"
        "[palette_frames]palettegen=max_colors=128:stats_mode=diff[palette];"
        "[gif_frames][palette]paletteuse=dither=bayer:bayer_scale=3"
    )
    with tempfile.TemporaryDirectory(prefix="ytaf-gif-frames-") as workspace:
        listing_path = Path(workspace) / "frames.txt"
        listing_path.write_text(listing, encoding="utf-8")
        command = [
            _resolve_ffmpeg(ffmpeg_binary),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing_path),
            "-filter_complex",
            filter_graph,
            # The repeated final entry would otherwise hold twice as long as
            # every other frame, which reads as a stutter each time the loop
            # turns around. Cutting at the requested length drops the excess.
            "-t",
            f"{duration:.3f}",
            "-loop",
            "0",
            str(target),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True, encoding="utf-8", errors="replace",
                timeout=max(60.0, duration * 20.0),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GifGenerationError(f"FFmpeg khong ghep duoc GIF tu cac khung: {exc}") from exc
    if result.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        detail = (result.stderr or result.stdout or "khong co chi tiet").strip()[-1500:]
        raise GifGenerationError(f"FFmpeg ghep GIF tu cac khung that bai: {detail}")
    return str(target)


def materialize_gif_asset(
    database: Any,
    job: dict[str, Any],
    source_asset: dict[str, Any],
    *,
    ffmpeg_binary: str = "ffmpeg",
) -> dict[str, Any]:
    """Create/register the final GIF asset for a scene job marked as GIF."""
    if str(job.get("job_kind") or "") != "gif":
        return source_asset
    if str(source_asset.get("asset_type") or "") != "image":
        raise GifGenerationError("Job GIF bat buoc phai nhan mot anh nguon")
    source = Path(str(source_asset.get("file_path") or ""))
    if not source.is_file():
        raise GifGenerationError("Asset anh nguon cua job GIF khong ton tai")
    # The site may return a real animated GIF — asked directly, ChatGPT and
    # Gemini do produce one. That is already the finished artifact, and
    # running it back through the sheet-cropping path would mangle it.
    if source.suffix.lower() == ".gif":
        return source_asset
    segment_index = int(job.get("segment_index") or 0)
    job_id = int(job.get("id") or 0)
    target = source.with_name(f"segment-{segment_index:03d}-job-{job_id}-motion.gif")
    output_path = create_animated_gif(
        source,
        target,
        duration_seconds=float(job.get("duration_seconds") or 5),
        fps=int(job.get("visual_fps") or job.get("gif_fps") or 8),
        ffmpeg_binary=ffmpeg_binary,
    )
    existing = database.find_project_asset_by_path(int(job["project_id"]), output_path)
    if existing:
        return existing
    output = Path(output_path)
    with output.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    asset = database.create_project_asset(
        int(job["project_id"]),
        "image",
        output.name,
        str(output),
        mime_type=mimetypes.guess_type(output.name)[0] or "image/gif",
        file_size=output.stat().st_size,
        sha256=digest,
    )
    if not asset:
        raise GifGenerationError("Khong dang ky duoc GIF vao project assets")
    return asset
