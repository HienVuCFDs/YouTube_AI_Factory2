from __future__ import annotations

import subprocess
from pathlib import Path

from .ffmpeg_renderer import media_duration_seconds, resolve_ffmpeg


class ThumbnailGenerationError(RuntimeError):
    pass


def generate_frame_thumbnails(
    video_path: Path,
    output_dir: Path,
    ffmpeg_binary: str = "ffmpeg",
    variants: int = 3,
) -> list[Path]:
    """Extract readable 16:9 frame variants from the rendered project video."""
    executable = resolve_ffmpeg(ffmpeg_binary)
    source = Path(video_path)
    if not executable:
        raise ThumbnailGenerationError("Không tìm thấy FFmpeg để tạo thumbnail")
    if not source.is_file():
        raise ThumbnailGenerationError("Project chưa có final.mp4 để tạo thumbnail")
    count = max(1, min(int(variants), 6))
    duration = media_duration_seconds(source, ffmpeg_binary)
    if not duration:
        raise ThumbnailGenerationError("Không đọc được thời lượng video để tạo thumbnail")
    output_dir.mkdir(parents=True, exist_ok=True)
    # Avoid the first/last frame where fade-in/out often makes a poor thumbnail.
    positions = [duration * (0.16 + (0.68 * index / max(1, count - 1))) for index in range(count)]
    generated: list[Path] = []
    for index, position in enumerate(positions, start=1):
        target = output_dir / f"thumbnail-{index:02d}.jpg"
        result = subprocess.run(
            [
                executable, "-y", "-ss", f"{position:.3f}", "-i", str(source),
                "-frames:v", "1",
                "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih):color=black",
                "-q:v", "2", str(target),
            ],
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=120,
            check=False,
        )
        if result.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
            detail = (result.stderr or result.stdout or "").strip()[-1000:]
            raise ThumbnailGenerationError(f"FFmpeg không tạo được thumbnail {index}: {detail}")
        generated.append(target)
    return generated
