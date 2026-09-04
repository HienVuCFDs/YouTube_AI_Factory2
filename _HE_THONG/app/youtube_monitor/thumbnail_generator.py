from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .ffmpeg_renderer import media_duration_seconds, resolve_ffmpeg


class ThumbnailGenerationError(RuntimeError):
    pass


# Sampled before choosing. Enough to have real candidates, few enough that
# picking a thumbnail stays a few seconds rather than a job of its own.
FRAME_CANDIDATES = 36

# A thumbnail wants a lit, sharp frame. These bound "lit": near black is a
# cut, near white is a flash or a title card, and neither is a thumbnail.
_MIN_BRIGHTNESS = 42.0
_MAX_BRIGHTNESS = 214.0


def _score_frame(frame: "Any") -> float:
    """How much of a picture this frame is.

    Sharpness first, because a motion-blurred frame is the commonest bad
    thumbnail and the one a fixed timestamp lands on most often; then
    contrast, because a flat frame reads as nothing at thumbnail size. A
    frame outside a sane exposure band scores zero however sharp it is - a
    crisp black frame is still a black frame.
    """
    import numpy as np

    mean = float(frame.mean())
    if mean < _MIN_BRIGHTNESS or mean > _MAX_BRIGHTNESS:
        return 0.0
    rows = np.diff(frame, axis=0)
    columns = np.diff(frame, axis=1)
    sharpness = float(rows.var() + columns.var())
    contrast = float(frame.std())
    return sharpness * 0.7 + contrast * contrast * 0.3


def choose_frame_positions(
    source: Path, duration: float, count: int, executable: str
) -> list[float]:
    """Timestamps worth cutting a thumbnail from, measured rather than assumed.

    Fixed positions - a sixth in, halfway, five sixths - land on whatever the
    video happens to be doing: a blink, a pan, a fade. Sampling and scoring
    costs a few seconds and picks a frame that is at least in focus and lit.

    Falls back to the fixed positions if the sampling cannot run, because a
    mediocre thumbnail beats no thumbnail.
    """
    spread = [
        duration * (0.16 + (0.68 * index / max(1, count - 1)))
        for index in range(count)
    ]
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return spread

    first, last = duration * 0.08, duration * 0.94
    step = (last - first) / max(1, FRAME_CANDIDATES - 1)
    scored: list[tuple[float, float]] = []
    with tempfile.TemporaryDirectory(prefix="thumb-") as tmp:
        for index in range(FRAME_CANDIDATES):
            at = first + step * index
            path = Path(tmp) / f"c{index:03d}.png"
            try:
                subprocess.run(
                    [executable, "-y", "-loglevel", "error", "-ss", f"{at:.3f}",
                     "-i", str(source), "-frames:v", "1", "-vf", "scale=320:-2",
                     "-f", "image2", str(path)],
                    capture_output=True, timeout=60, check=False,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if not path.is_file() or path.stat().st_size == 0:
                continue
            with Image.open(path) as image:
                scored.append((_score_frame(np.asarray(image.convert("L"), dtype=np.float32)), at))

    usable = [item for item in scored if item[0] > 0]
    if len(usable) < count:
        return spread

    # Best first, but never two thumbnails of the same moment: a gap keeps
    # the set a choice rather than one frame three times.
    usable.sort(key=lambda item: item[0], reverse=True)
    minimum_gap = max(1.0, duration / (count * 4))
    chosen: list[float] = []
    for _, at in usable:
        if all(abs(at - taken) >= minimum_gap for taken in chosen):
            chosen.append(at)
        if len(chosen) == count:
            break
    if len(chosen) < count:
        return spread
    return sorted(chosen)


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
    positions = choose_frame_positions(source, duration, count, executable)
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
