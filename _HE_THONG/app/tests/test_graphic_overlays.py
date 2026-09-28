from __future__ import annotations

import shutil
import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from youtube_monitor.ffmpeg_renderer import _segment_arguments, render_timeline_with_ffmpeg
from youtube_monitor.graphic_overlays import normalize_graphic_overlay, retime_graphic_overlays


def test_graphic_plan_normalizes_legacy_callout_and_rejects_unrenderable_kind() -> None:
    item = normalize_graphic_overlay({"kind": "callout", "text": "  Giá  299k  "}, 3)
    assert item["text"] == "Giá 299k"
    assert (item["style"], item["animation"], item["start_seconds"], item["end_seconds"]) == (
        "card", "fade", 0, 3,
    )
    with pytest.raises(ValueError, match="chưa hỗ trợ"):
        normalize_graphic_overlay({"kind": "highlight", "text": ""}, 3)
    with pytest.raises(ValueError, match="ngoài thời lượng"):
        normalize_graphic_overlay({"kind": "title", "text": "Ví dụ", "end_seconds": 5}, 3)
    assert retime_graphic_overlays([{
        "kind": "title", "text": "Ví dụ", "start_seconds": 2, "end_seconds": 4,
    }], 4, 5)[0]["start_seconds"] == 2.5


@pytest.mark.parametrize("animation,style", [("fade", "clean"), ("pop", "card"), ("slide_up", "neon")])
def test_ffmpeg_renders_timed_vietnamese_graphic(animation: str, style: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not Path("C:/Windows/Fonts/arial.ttf").is_file():
        pytest.skip("FFmpeg/Arial unavailable")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        clip = root / "source.mp4"
        output = root / "result.mp4"
        subprocess.run([
            ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
            "color=c=black:s=320x568:r=12:d=3", "-c:v", "libx264", str(clip),
        ], check=True, capture_output=True)
        args = _segment_arguments(
            ffmpeg, {}, clip, None, output, 3, 320, 568, 12, 1, "libx264",
            transition="cut", effect="static", overlays=[{
                "kind": "title", "text": "Tương tác", "style": style,
                "animation": animation, "position": "top_center",
                "start_seconds": 0.5, "end_seconds": 2.0,
            }],
        )
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert result.returncode == 0, result.stderr[-2500:]
        assert output.is_file()

        def frame_at(second: float) -> bytes:
            result = subprocess.run([
                ffmpeg, "-v", "error", "-ss", str(second), "-i", str(output),
                "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
            ], capture_output=True, check=True)
            return result.stdout

        before, visible, after = frame_at(0.2), frame_at(1.0), frame_at(2.5)
        assert len(before) == len(visible) == len(after) == 320 * 568 * 3
        assert sum(visible) > sum(before) + 100_000
        assert sum(visible) > sum(after) + 100_000


def test_timeline_json_overlay_reaches_final_render() -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not Path("C:/Windows/Fonts/arial.ttf").is_file():
        pytest.skip("FFmpeg/Arial unavailable")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        clip = root / "source.mp4"
        subprocess.run([
            ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
            "color=c=black:s=320x568:r=12:d=2", "-c:v", "libx264", str(clip),
        ], check=True, capture_output=True)
        output = render_timeline_with_ffmpeg([{
            "segment_index": 1, "visual_path": str(clip), "duration_seconds": 2,
            "edit_transition": "cut", "edit_effect": "static",
            "overlays": json.dumps([{
                "kind": "callout", "text": "Giá 299k", "style": "card", "animation": "fade",
                "position": "top_center", "start_seconds": 0.2, "end_seconds": 1.5,
            }], ensure_ascii=False),
        }], root / "render", binary=ffmpeg, width=320, height=568, fps=12)
        assert Path(output).is_file()
        assert (root / "render" / "segments" / "segment-001-graphic-01.txt").read_text(encoding="utf-8") == "Giá 299k"
