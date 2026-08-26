"""A plan that nothing acts on is a plan the user watched the AI write for nothing."""

from __future__ import annotations

import pytest

from youtube_monitor import ffmpeg_renderer
from youtube_monitor.ffmpeg_renderer import _motion_filters, _segment_arguments


@pytest.fixture
def clip(tmp_path, monkeypatch):
    import subprocess as sp

    path = tmp_path / "canh.mp4"
    path.write_bytes(b"")
    monkeypatch.setattr(
        ffmpeg_renderer.subprocess, "run",
        lambda *_a, **_k: sp.CompletedProcess([], 0, stdout="1920x1080\n", stderr=""),
    )
    monkeypatch.setattr(ffmpeg_renderer, "media_duration_seconds", lambda *_: 8.0)
    return path


def _build(clip, tmp_path, **plan):
    return _segment_arguments(
        "ffmpeg", {}, clip, None, tmp_path / "out.mp4", 4.0, 1080, 1920, 30, 1, "libx264",
        None, None, 0.12,
        plan.get("transition", "cut"), plan.get("effect", ""),
        plan.get("cleanups", []), plan.get("trim_head", 0.0), plan.get("trim_tail", 0.0),
    )


def _graph(args: list[str]) -> str:
    return args[args.index("-vf") + 1]


def test_a_camera_move_reaches_a_source_clip(clip, tmp_path) -> None:
    """The move used to be read only for still images, so on the reup workflow -
    where every scene is a clip cut from the source - zoom_in, zoom_out and
    static all rendered identically. Twenty-seven of eighty-five scenes had a
    move planned that never happened.
    """
    assert "zoompan" in _graph(_build(clip, tmp_path, effect="zoom_in"))
    assert "zoompan" in _graph(_build(clip, tmp_path, effect="zoom_out"))


def test_the_three_moves_do_not_render_the_same(clip, tmp_path) -> None:
    graphs = {effect: _graph(_build(clip, tmp_path, effect=effect))
              for effect in ("static", "zoom_in", "zoom_out")}

    assert len(set(graphs.values())) == 3


def test_holding_still_is_honoured(clip, tmp_path) -> None:
    """Some scenes are meant to be read off the screen, and a clip already
    carries its own movement."""
    assert "zoompan" not in _graph(_build(clip, tmp_path, effect="static"))
    assert "zoompan" not in _graph(_build(clip, tmp_path, effect=""))


def test_a_still_image_keeps_its_default_push(tmp_path) -> None:
    """A photograph with no motion at all reads as a broken video, so silence
    from the plan means a restrained push - unlike a clip, which already moves."""
    image = tmp_path / "canh.png"
    image.write_bytes(b"")

    assert "zoompan" in _graph(_build(image, tmp_path, effect=""))


def test_a_move_on_a_clip_keeps_the_clips_own_shape(clip, tmp_path) -> None:
    """zoompan resizes as it zooms. Pointing it at the vertical output would
    squeeze a 16:9 picture into 9:16 on the way past."""
    graph = _graph(_build(clip, tmp_path, effect="zoom_in"))

    assert "s=1920x1080" in graph, "phai giu ti le clip goc, khong phai khung dich"


def test_every_part_of_one_scenes_plan_lands_together(clip, tmp_path) -> None:
    args = _build(
        clip, tmp_path, transition="fade", effect="zoom_in", trim_head=0.3, trim_tail=0.8,
        cleanups=[{"kind": "subtitle", "position": "bottom_center", "method": "blur"}],
    )
    graph = _graph(args)

    assert "fade=" in graph
    assert "zoompan" in graph
    assert "boxblur" in graph
    assert args.index("-ss") < args.index("-i")


def test_a_scene_that_asked_for_nothing_gets_nothing(clip, tmp_path) -> None:
    """Applying an effect nobody planned is as wrong as ignoring one."""
    graph = _graph(_build(clip, tmp_path, transition="cut"))

    assert "fade=" not in graph
    assert "zoompan" not in graph
    assert "boxblur" not in graph


def test_an_unrecognised_move_is_not_guessed_at() -> None:
    assert _motion_filters("swoop", 1920, 1080, 30) == []
