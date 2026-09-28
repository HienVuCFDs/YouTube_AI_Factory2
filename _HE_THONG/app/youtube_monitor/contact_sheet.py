"""One picture of what the project currently looks like.

An AI orchestrator can queue every step, approve a plan and start a render
without ever seeing a frame - it has been directing with its eyes shut. So has
anyone reading the app over MCP. A contact sheet is the cheapest way to fix
that: a single image holding either the scenes as they stand or frames sampled
across the finished video, small enough to hand to a model in one go.

Built with the ffmpeg the app already renders with, so it needs nothing new
installed and fails the same way renders do when ffmpeg is missing.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .ffmpeg_renderer import media_duration_seconds

# Small enough that a model can take the whole sheet in, large enough that a
# wrong picture in a scene is still recognisable.
TILE_WIDTH = 320
DEFAULT_COLUMNS = 4
MAX_TILES = 24
_STILL_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class ContactSheetError(RuntimeError):
    pass


def _grid(count: int, columns: int) -> tuple[int, int]:
    columns = max(1, min(columns, count))
    rows = (count + columns - 1) // columns
    return columns, rows


def video_command(
    video: Path, output: Path, *, ffmpeg: str, tiles: int = 12, columns: int = DEFAULT_COLUMNS,
    duration_seconds: float = 0.0,
) -> list[str]:
    """Sample frames evenly across a video into one sheet.

    The sample rate is derived from the video's own length so a short clip and
    a ten minute one both come back with the same number of tiles; without a
    known length it falls back to one frame a second.
    """
    tiles = max(1, min(tiles, MAX_TILES))
    columns, rows = _grid(tiles, columns)
    if duration_seconds <= 0:
        raise ContactSheetError("Chưa biết độ dài video nên không lấy mẫu đều được")
    rate = f"{tiles}/{duration_seconds:.3f}"
    return [
        ffmpeg, "-y", "-v", "error", "-i", str(video),
        "-vf", f"fps={rate},scale={TILE_WIDTH}:-2,tile={columns}x{rows}",
        "-frames:v", "1", str(output),
    ]


def stills_command(
    pattern_dir: Path, output: Path, *, ffmpeg: str, count: int, columns: int = DEFAULT_COLUMNS,
) -> list[str]:
    columns, rows = _grid(count, columns)
    return [
        ffmpeg, "-y", "-v", "error", "-framerate", "1",
        "-i", str(pattern_dir / "tile-%03d.jpg"),
        "-vf", f"scale={TILE_WIDTH}:-2,tile={columns}x{rows}",
        "-frames:v", "1", str(output),
    ]


def _run(command: list[str]) -> None:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContactSheetError(f"Không chạy được ffmpeg: {exc}") from exc
    if result.returncode != 0:
        raise ContactSheetError((result.stderr or result.stdout or "ffmpeg thất bại").strip()[-600:])


def from_video(video: Path, output: Path, *, ffmpeg: str, tiles: int = 12, duration_seconds: float = 0.0) -> Path:
    if not video.is_file():
        raise ContactSheetError(f"Không tìm thấy video: {video}")
    if duration_seconds <= 0:
        # Measured here rather than trusted from the caller. Sampling at one
        # frame a second when the length is unknown returns a sheet of the
        # opening seconds that looks exactly like a sheet of the whole video,
        # and an orchestrator reading it would report on a film it never saw.
        duration_seconds = float(media_duration_seconds(video, ffmpeg) or 0.0)
    output.parent.mkdir(parents=True, exist_ok=True)
    _run(video_command(video, output, ffmpeg=ffmpeg, tiles=tiles, duration_seconds=duration_seconds))
    if not output.is_file() or output.stat().st_size == 0:
        raise ContactSheetError("ffmpeg chạy xong nhưng không tạo được ảnh")
    return output


def from_scene_visuals(visuals: list[Path], output: Path, *, ffmpeg: str) -> Path:
    """Tile whatever each scene currently shows.

    Video scenes contribute their first frame, so a storyboard that mixes
    stills and clips still comes back as one readable sheet.
    """
    usable = [item for item in visuals if item.is_file() and item.stat().st_size > 0][:MAX_TILES]
    if not usable:
        raise ContactSheetError("Chưa cảnh nào có hình để xem")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ytf-sheet-") as directory:
        workdir = Path(directory)
        for index, source in enumerate(usable, start=1):
            tile = workdir / f"tile-{index:03d}.jpg"
            if source.suffix.lower() in _STILL_SUFFIXES:
                # Re-encoded rather than copied: the tiler needs one format,
                # and a storyboard mixes png, webp and jpg freely.
                _run([ffmpeg, "-y", "-v", "error", "-i", str(source), "-frames:v", "1", str(tile)])
            else:
                _run([ffmpeg, "-y", "-v", "error", "-i", str(source), "-frames:v", "1", "-q:v", "3", str(tile)])
        _run(stills_command(workdir, output, ffmpeg=ffmpeg, count=len(usable)))
    if not output.is_file() or output.stat().st_size == 0:
        raise ContactSheetError("ffmpeg chạy xong nhưng không tạo được ảnh")
    return output


def ffmpeg_available(ffmpeg: str) -> bool:
    return bool(shutil.which(ffmpeg) or Path(ffmpeg).is_file())
