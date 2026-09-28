"""Find what the source video draws on its own picture.

A reup is cut from someone else's film, and that film carries its own marks:
a channel logo in a corner, a watermark, and - the one that matters most -
burned-in subtitles in a language this audience is not being given. They are
part of the pixels, so they survive every cut and land in the finished video
underneath the new narration.

The edit planner used to be asked about these, but it was asked in words: it
received the scene's dialogue and a sentence of style, never a frame. A model
with no picture correctly answers that it has no evidence of a mark, so
nothing was ever marked and every render kept the source's subtitles.

This looks instead. It samples frames from the source and measures two things
that separate an overlay from the film under it:

  - burned-in subtitles are bright outlined lettering, packed into a band of
    rows near the bottom, that changes from frame to frame;
  - a logo or watermark is the opposite - a small patch of hard edges that
    does not change at all while the picture behind it moves.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .ffmpeg_renderer import media_duration_seconds, resolve_ffmpeg

# Enough frames to tell a subtitle apart from a bright horizon, few enough
# that the probe stays a few seconds rather than a job of its own.
SAMPLE_COUNT = 14
SAMPLE_WIDTH = 384

# A bright pixel with a dark one within this many pixels is a letter edge:
# subtitles are drawn light with a dark outline or shadow precisely so they
# stay legible over any picture, which is what makes them findable.
_OUTLINE_RADIUS = 3
_BRIGHT = 195.0
_DARK = 95.0


class MarkDetectionError(RuntimeError):
    """Raised when the source cannot be sampled at all."""


def _local_min(values: np.ndarray, radius: int) -> np.ndarray:
    """The darkest pixel within `radius`, horizontally and vertically."""
    out = values.copy()
    for step in range(1, radius + 1):
        out[:, step:] = np.minimum(out[:, step:], values[:, :-step])
        out[:, :-step] = np.minimum(out[:, :-step], values[:, step:])
        out[step:, :] = np.minimum(out[step:, :], values[:-step, :])
        out[:-step, :] = np.minimum(out[:-step, :], values[step:, :])
    return out


def sample_frames(
    video_path: Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
    samples: int = SAMPLE_COUNT,
    width: int = SAMPLE_WIDTH,
) -> np.ndarray:
    """Grey frames spread across the body of the film, as one stacked array."""
    executable = resolve_ffmpeg(ffmpeg_binary)
    if not executable:
        raise MarkDetectionError("Không tìm thấy FFmpeg để đọc video nguồn.")
    video_path = Path(video_path)
    if not video_path.is_file():
        raise MarkDetectionError(f"Không tìm thấy video nguồn: {video_path}")
    duration = media_duration_seconds(video_path, executable) or 0.0
    if duration <= 0:
        raise MarkDetectionError("Không đọc được thời lượng video nguồn.")

    # An intro card and an end card carry marks that are not on the film, so
    # the sample is taken from the body of it.
    first, last = duration * 0.10, duration * 0.90
    span = max(0.0, last - first)
    collected: list[np.ndarray] = []
    with tempfile.TemporaryDirectory(prefix="marks-") as tmp:
        for index in range(max(1, samples)):
            offset = first + (span * index / max(1, samples - 1) if samples > 1 else span / 2)
            frame_path = Path(tmp) / f"frame-{index:03d}.png"
            try:
                subprocess.run(
                    [
                        executable, "-y", "-loglevel", "error",
                        "-ss", f"{offset:.3f}", "-i", str(video_path),
                        "-frames:v", "1", "-vf", f"scale={int(width)}:-2",
                        "-f", "image2", str(frame_path),
                    ],
                    check=True, capture_output=True, timeout=90,
                )
            except (subprocess.SubprocessError, OSError):
                continue
            if not frame_path.is_file():
                continue
            with Image.open(frame_path) as image:
                collected.append(np.asarray(image.convert("L"), dtype=np.float32))

    if len(collected) < 3:
        raise MarkDetectionError("Không lấy đủ khung hình từ video nguồn để dò.")
    # A damaged frame can decode at another size; keep the shape most agree on.
    shapes = [frame.shape for frame in collected]
    common = max(set(shapes), key=shapes.count)
    usable = [frame for frame in collected if frame.shape == common]
    if len(usable) < 3:
        raise MarkDetectionError("Khung hình lấy được không đồng nhất kích thước.")
    return np.stack(usable)


def _lettering(stack: np.ndarray) -> np.ndarray:
    """Per frame, the pixels that look like bright outlined type."""
    marks = np.zeros(stack.shape, dtype=bool)
    for index in range(stack.shape[0]):
        frame = stack[index]
        marks[index] = (frame > _BRIGHT) & (_local_min(frame, _OUTLINE_RADIUS) < _DARK)
    return marks


def _text_rows(marks: np.ndarray) -> np.ndarray:
    """For each row, the share of frames carrying lettering on it."""
    _, _, width = marks.shape
    left, right = int(width * 0.10), int(width * 0.90)
    present = (marks[:, :, left:right].mean(axis=2) > 0.015).astype(np.float32)
    return present.mean(axis=0)


def _runs(mask: np.ndarray, gap: int = 2) -> list[tuple[int, int]]:
    """Contiguous true stretches, joining ones separated by a line or two."""
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for index, flag in enumerate(mask):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            spans.append((start, index))
            start = None
    if start is not None:
        spans.append((start, len(mask)))
    merged: list[tuple[int, int]] = []
    for span in spans:
        if merged and span[0] - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], span[1])
        else:
            merged.append(span)
    return merged


def _find_subtitle_band(stack: np.ndarray) -> dict[str, Any] | None:
    """The band of rows where burned-in subtitles sit, if there is one."""
    _, height, width = stack.shape
    marks = _lettering(stack)
    scores = _text_rows(marks)
    # Subtitles live low. Searching the whole frame would find the picture's
    # own contrast and blur something that belongs to the shot.
    floor = int(height * 0.55)
    lower = np.zeros_like(scores, dtype=bool)
    lower[floor:] = scores[floor:] >= 0.30
    candidates = [
        span for span in _runs(lower)
        if height * 0.015 <= (span[1] - span[0]) <= height * 0.28
    ]
    if not candidates:
        return None
    band = max(candidates, key=lambda span: float(scores[span[0]:span[1]].sum()))
    strength = float(scores[band[0]:band[1]].mean())
    # A bright sky or a lit stage floor scores on every row. Only take the band
    # when it stands out well above the rest of the frame.
    baseline = float(np.median(scores)) if scores.size else 0.0
    if strength < max(0.30, baseline * 1.6):
        return None

    # The measured band is the rows where lettering was actually found, so it
    # stops at the ink. Descenders, a second line and a thicker font in another
    # scene all sit just outside it, and a blur that stops at the ink leaves
    # legible edges - so the band is grown before it is used.
    pad = max((band[1] - band[0]) * 0.45, height * 0.018)
    top = max(floor / height, (band[0] - pad) / height)
    bottom = min(1.0, (band[1] + pad) / height)
    if bottom <= top or (bottom - top) > 0.22:
        return None

    # Horizontally the same: take the columns the lettering occupies rather
    # than the whole width, so the blur covers the line and not the picture
    # either side of it.
    columns = marks[:, band[0]:band[1], :].mean(axis=(0, 1))
    used = np.flatnonzero(columns > 0.01)
    if used.size:
        left = max(0.0, (float(used[0]) / width) - 0.04)
        right = min(1.0, (float(used[-1] + 1) / width) + 0.04)
    else:
        left, right = 0.05, 0.95
    # Subtitles are centred, and a later scene's line can be longer than any
    # sampled here, so the box is mirrored about the centre and never narrow.
    reach = max(0.5 - left, right - 0.5, 0.30)
    left, right = max(0.0, 0.5 - reach), min(1.0, 0.5 + reach)

    return {
        "kind": "subtitle",
        "position": "bottom_center",
        "method": "blur",
        "confidence": round(min(1.0, strength), 3),
        "box": [round(left, 4), round(top, 4), round(right - left, 4), round(bottom - top, 4)],
        "source": "detected",
    }


def _find_static_marks(stack: np.ndarray) -> list[dict[str, Any]]:
    """Corners holding a patch that never changes while the film moves."""
    frames, height, width = stack.shape
    if frames < 4:
        return []
    variation = stack.std(axis=0)
    still = variation < 4.0
    # A locked-off shot makes the entire frame still; a corner is only telling
    # when the picture at large is moving.
    if float(still.mean()) > 0.55:
        return []
    average = stack.mean(axis=0)
    rows, columns = np.gradient(average)
    marked = still & ((np.abs(rows) + np.abs(columns)) > 28.0)

    found: list[dict[str, Any]] = []
    corners = {
        "top_left": (0.0, 0.0), "top_right": (0.80, 0.0),
        "bottom_left": (0.0, 0.875), "bottom_right": (0.80, 0.875),
    }
    for position, (x_ratio, y_ratio) in corners.items():
        x0, x1 = int(width * x_ratio), int(width * (x_ratio + 0.20))
        y0, y1 = int(height * y_ratio), int(height * (y_ratio + 0.125))
        patch = marked[y0:y1, x0:x1]
        if patch.size == 0:
            continue
        density = float(patch.mean())
        if density >= 0.05:
            found.append({
                "kind": "logo",
                "position": position,
                "method": "blur",
                "confidence": round(min(1.0, density * 4), 3),
                "source": "detected",
            })
    # Two corners is a plausible logo and a watermark; four is a still picture
    # that slipped the guard above, and blurring every corner would be worse
    # than blurring none.
    return found if len(found) <= 2 else []


def detect_burned_in_marks(
    video_path: Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
    samples: int = SAMPLE_COUNT,
) -> list[dict[str, Any]]:
    """What the source draws on its own picture, measured from the film."""
    stack = sample_frames(video_path, ffmpeg_binary=ffmpeg_binary, samples=samples)
    marks: list[dict[str, Any]] = []
    band = _find_subtitle_band(stack)
    if band:
        marks.append(band)
    marks.extend(_find_static_marks(stack))
    return marks
