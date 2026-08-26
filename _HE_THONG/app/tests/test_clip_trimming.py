"""Taking the dead weight off a source clip without changing the scene length."""

from __future__ import annotations

from pathlib import Path

import pytest

from youtube_monitor import ffmpeg_renderer
from youtube_monitor.ffmpeg_renderer import _usable_clip_window

CLIP = Path("clip.mp4")


@pytest.fixture
def clip_of(monkeypatch):
    def _set(seconds: float | None) -> None:
        monkeypatch.setattr(ffmpeg_renderer, "media_duration_seconds", lambda *_: seconds)
    return _set


def test_no_trim_asked_for_means_the_clip_is_opened_as_it_was(clip_of) -> None:
    """Probing every clip for a duration nobody is going to use costs a
    subprocess per scene, and this app renders eighty-five of them."""
    clip_of(7.0)
    assert _usable_clip_window(CLIP, "ffmpeg", 0, 0) is None


def test_a_trim_narrows_the_window_at_both_ends(clip_of) -> None:
    clip_of(7.0)
    assert _usable_clip_window(CLIP, "ffmpeg", 1.0, 0.5) == (1.0, 5.5)


def test_trimming_more_than_the_clip_holds_leaves_it_whole(clip_of) -> None:
    """The plan is written from a description of the scene, not from the file,
    so it can ask for more than exists. Emptying the scene would put a black
    hole in the middle of the video; showing the untrimmed clip does not."""
    clip_of(7.0)
    assert _usable_clip_window(CLIP, "ffmpeg", 99, 99) is None
    assert _usable_clip_window(CLIP, "ffmpeg", 3.5, 3.5) is None


def test_an_unreadable_clip_is_left_alone(clip_of) -> None:
    clip_of(None)
    assert _usable_clip_window(CLIP, "ffmpeg", 1.0, 0.5) is None


def test_negative_trims_are_treated_as_no_trim(clip_of) -> None:
    """A model returning -0.5 must not extend the clip past its own start."""
    clip_of(7.0)
    assert _usable_clip_window(CLIP, "ffmpeg", -1.0, -1.0) is None


def test_the_trim_is_an_input_option_so_the_scene_keeps_its_length(clip_of, tmp_path) -> None:
    """The scene runs as long as the voiceover does. Trimming must move which
    part of the clip is shown, never how long the scene lasts - so -ss and -t
    belong before -i, where they choose what FFmpeg reads and loops.
    """
    clip_of(7.0)
    visual = tmp_path / "clip.mp4"
    visual.write_bytes(b"")

    args = ffmpeg_renderer._segment_arguments(
        "ffmpeg", {}, visual, None, tmp_path / "out.mp4", 4.0, 1280, 720, 30, 0,
        "libx264", None, None, 0.12, "cut", "static", [], 1.0, 0.5,
    )

    assert args.index("-ss") < args.index("-i")
    assert args.index("-t") < args.index("-i")
    assert args[args.index("-ss") + 1] == "1.000"
    assert args[args.index("-t") + 1] == "5.500"
