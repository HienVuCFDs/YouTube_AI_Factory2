"""The frame-sequence GIF builder, checked against what FFmpeg actually writes."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from youtube_monitor.gif_generator import GifGenerationError, create_gif_from_frames

FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="Can FFmpeg de dung GIF that")


def _frame(path: Path, bar_width: int) -> Path:
    """A black plate with a yellow bar, so a frame's identity is measurable."""
    subprocess.run(
        [
            str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=640x360:d=1",
            "-vf", f"drawbox=x=100:y=150:w={bar_width}:h=60:color=yellow@1:t=fill",
            "-frames:v", "1", str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def _bar_widths(gif: Path, workspace: Path) -> list[int]:
    from PIL import Image

    subprocess.run(
        [str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error", "-i", str(gif),
         str(workspace / "out_%03d.png")],
        check=True,
        capture_output=True,
    )
    widths: list[int] = []
    for extracted in sorted(workspace.glob("out_*.png")):
        image = Image.open(extracted).convert("RGB")
        row = (image.getpixel((x, image.height // 2)) for x in range(image.width))
        widths.append(sum(1 for red, green, blue in row if red > 180 and green > 150 and blue < 120))
    return widths


def test_loop_plays_forward_then_back_without_repeating_the_ends(tmp_path: Path) -> None:
    """1-2-3-4-3-2, each held equally — a turn-around that reads as motion.

    The end frames must appear once per cycle: repeating them makes the loop
    hesitate at both extremes, which is what the trailing-entry trim fixes.
    """
    frames = [_frame(tmp_path / f"f{index}.png", 40 + index * 120) for index in range(4)]
    extracted = tmp_path / "extracted"
    extracted.mkdir()

    gif = create_gif_from_frames(
        list(frames), tmp_path / "loop.gif", duration_seconds=3, fps=8, ffmpeg_binary=str(FFMPEG)
    )

    widths = _bar_widths(Path(gif), extracted)
    states = [width for index, width in enumerate(widths) if index == 0 or width != widths[index - 1]]
    assert states == [60, 240, 420, 600, 420, 240]
    holds = {state: widths.count(state) for state in (60, 600)}
    assert holds[60] == holds[600], f"hai dau vong lap giu khong deu: {widths}"


def test_content_actually_changes_between_frames(tmp_path: Path) -> None:
    """The failure this route exists to fix: a loop where nothing moves."""
    frames = [_frame(tmp_path / f"f{index}.png", 40 + index * 120) for index in range(4)]
    extracted = tmp_path / "extracted"
    extracted.mkdir()

    gif = create_gif_from_frames(
        list(frames), tmp_path / "loop.gif", duration_seconds=3, fps=8, ffmpeg_binary=str(FFMPEG)
    )

    widths = _bar_widths(Path(gif), extracted)
    assert max(widths) - min(widths) > 100


def test_a_single_frame_is_refused(tmp_path: Path) -> None:
    frame = _frame(tmp_path / "only.png", 100)

    with pytest.raises(GifGenerationError):
        create_gif_from_frames([frame], tmp_path / "loop.gif", ffmpeg_binary=str(FFMPEG))


def test_a_missing_frame_is_named(tmp_path: Path) -> None:
    frame = _frame(tmp_path / "first.png", 100)

    with pytest.raises(GifGenerationError, match="khung hinh"):
        create_gif_from_frames(
            [frame, tmp_path / "gone.png"], tmp_path / "loop.gif", ffmpeg_binary=str(FFMPEG)
        )
