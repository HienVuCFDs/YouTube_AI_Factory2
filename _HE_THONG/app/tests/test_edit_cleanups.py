"""Taking the source's own logo, watermark and subtitles off the picture."""

from __future__ import annotations

import pytest

from youtube_monitor.ffmpeg_renderer import _cleanup_filters, _compose_video_graph
import unittest
from tests.ui_source import studio_ui

FRAME = (1280, 720)
AFTER = ["scale=1280:720:force_original_aspect_ratio=decrease", "format=yuv420p"]


def _values(filter_string: str, name: str) -> dict[str, int]:
    return {
        key: int(value)
        for key, value in (part.split("=") for part in filter_string.replace(f"{name}=", "").split(":"))
    }


def test_no_cleanups_adds_nothing() -> None:
    assert _cleanup_filters([], *FRAME) == ([], [])


def test_a_mark_is_blurred_by_default() -> None:
    """Blur is what the plan asks for on burned-in subtitles, and what the
    user asked for by name. It used to be quietly turned into a delogo."""
    linear, blurs = _cleanup_filters([{"kind": "subtitle", "position": "bottom_center"}], *FRAME)

    assert linear == []
    assert len(blurs) == 1


def test_a_blur_region_is_a_fraction_not_a_pixel_count() -> None:
    """The frame these land on is the source clip's - 1920x1080 here - while
    the video may go out as a 1080x1920 Short. Pixels worked out against the
    output put the subtitle box off the picture entirely, which is why foreign
    subtitles survived being 'removed'."""
    _, blurs = _cleanup_filters([{"kind": "subtitle", "position": "bottom_center"}], *FRAME)
    x, y, w, h = blurs[0]

    assert all(0.0 <= value <= 1.0 for value in (x, y, w, h))
    assert w > 0.8, "phu de chay gan het chieu ngang"
    assert y > 0.7, "phu de nam thap trong khung"


def test_the_blur_graph_splits_crops_and_lays_the_copy_back() -> None:
    """A blur cannot be one filter in a flat chain: the region has to be taken
    out of the frame, blurred, and put back where it came from."""
    _, blurs = _cleanup_filters([{"kind": "subtitle", "position": "bottom_center"}], *FRAME)
    graph = _compose_video_graph([], blurs, AFTER)

    assert graph.startswith("split[base][b0]")
    assert "crop=" in graph and "gblur=" in graph and "overlay=" in graph
    assert graph.endswith(",".join(AFTER)), "phan con lai cua chuoi phai chay tiep sau overlay"


def test_the_graph_has_one_way_in_and_one_way_out() -> None:
    """-vf accepts a labelled graph, but only if every branch it opens is
    joined back up - otherwise FFmpeg refuses the whole command."""
    _, blurs = _cleanup_filters([
        {"kind": "subtitle", "position": "bottom_center"},
        {"kind": "logo", "position": "top_right"},
        {"kind": "watermark", "position": "bottom_left"},
    ], *FRAME)
    graph = _compose_video_graph(["zoompan=z=1"], blurs, AFTER)

    assert "split=4[base][b0][b1][b2]" in graph
    for index in range(3):
        assert f"[f{index}]" in graph
    assert graph.count("overlay=") == 3


def test_a_graph_without_blurs_stays_a_flat_chain() -> None:
    """Most scenes need no blur, and a split/overlay costs a frame copy."""
    assert _compose_video_graph(["zoompan=z=1"], [], AFTER) == ",".join(["zoompan=z=1", *AFTER])


def test_delogo_is_sized_in_pixels_and_stays_inside_the_frame() -> None:
    """delogo rebuilds from the pixels around its box, so a box touching the
    edge has no border to read and FFmpeg refuses the filter outright."""
    width, height = FRAME

    for position in ("top_left", "top_right", "bottom_left", "bottom_right", "center", "full"):
        linear, blurs = _cleanup_filters(
            [{"kind": "logo", "position": position, "method": "delogo"}], *FRAME
        )
        assert blurs == []
        box = _values(linear[0], "delogo")
        assert box["x"] >= 1 and box["y"] >= 1, position
        assert box["x"] + box["w"] < width and box["y"] + box["h"] < height, position


@pytest.mark.parametrize("size", [(640, 360), (1920, 1080), (720, 1280)])
def test_delogo_stays_inside_every_frame_size(size: tuple[int, int]) -> None:
    for position in ("top_left", "bottom_right", "bottom_center", "full"):
        linear, _ = _cleanup_filters(
            [{"kind": "logo", "position": position, "method": "delogo"}], *size
        )
        box = _values(linear[0], "delogo")
        assert 1 <= box["x"] and 1 <= box["y"], position
        assert box["x"] + box["w"] < size[0] and box["y"] + box["h"] < size[1], position


def test_crop_is_only_used_against_an_edge() -> None:
    """Cropping a mark out of the middle would take the picture with it."""
    edge, _ = _cleanup_filters([{"kind": "watermark", "position": "top_center", "method": "crop"}], *FRAME)
    _, middle_blurs = _cleanup_filters([{"kind": "watermark", "position": "center", "method": "crop"}], *FRAME)

    assert edge[0].startswith("crop=")
    assert len(middle_blurs) == 1, "giua khung thi lam mo, khong duoc cat"


def test_an_unknown_position_is_skipped_rather_than_guessed() -> None:
    """Blurring the wrong rectangle damages the picture for nothing."""
    assert _cleanup_filters([{"kind": "logo", "position": "somewhere"}], *FRAME) == ([], [])


def test_a_malformed_entry_does_not_break_the_render() -> None:
    assert _cleanup_filters(["khong phai dict", {"kind": "logo"}], *FRAME) == ([], [])


def test_a_video_mark_is_measured_against_the_clip_not_the_output(monkeypatch, tmp_path) -> None:
    """This is the bug that left foreign subtitles legible: the source clips
    are 1920x1080 landscape, the project renders 1080x1920 Shorts, and a
    bottom-of-frame box worked out for the vertical output lands below the
    bottom of a landscape frame."""
    import subprocess as sp

    from youtube_monitor import ffmpeg_renderer

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"")
    monkeypatch.setattr(
        ffmpeg_renderer.subprocess, "run",
        lambda *_a, **_k: sp.CompletedProcess([], 0, stdout="1920x1080\n", stderr=""),
    )

    assert ffmpeg_renderer._mark_frame_size(clip, "ffmpeg", 1080, 1920) == (1920, 1080)


def test_ffprobe_path_does_not_rewrite_a_winget_ffmpeg_directory(monkeypatch, tmp_path) -> None:
    """WinGet installs FFmpeg below a directory whose name also contains
    'ffmpeg'. Replacing that word in the entire path creates a directory that
    does not exist and used to abort every source-video render with WinError 2.
    """
    import subprocess as sp

    from youtube_monitor import ffmpeg_renderer

    bin_dir = tmp_path / "ffmpeg-8.1-full_build" / "bin"
    bin_dir.mkdir(parents=True)
    ffmpeg = bin_dir / "ffmpeg.exe"
    ffprobe = bin_dir / "ffprobe.exe"
    ffmpeg.write_bytes(b"")
    ffprobe.write_bytes(b"")
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"")
    invoked: list[str] = []

    def fake_run(args, **_kwargs):
        invoked.append(args[0])
        return sp.CompletedProcess(args, 0, stdout="1920x1080\n", stderr="")

    monkeypatch.setattr(ffmpeg_renderer.subprocess, "run", fake_run)

    assert ffmpeg_renderer._mark_frame_size(clip, str(ffmpeg), 1080, 1920) == (1920, 1080)
    assert invoked == [str(ffprobe)]


def test_a_still_image_is_already_at_the_output_size(tmp_path) -> None:
    """zoompan has run by then, so the picture is the output's shape."""
    from youtube_monitor import ffmpeg_renderer

    image = tmp_path / "canh.png"
    image.write_bytes(b"")

    assert ffmpeg_renderer._mark_frame_size(image, "ffmpeg", 1080, 1920) == (1080, 1920)


def test_an_unreadable_clip_falls_back_to_the_output_size(monkeypatch, tmp_path) -> None:
    """Guessing is better than refusing to render the scene at all."""
    import subprocess as sp

    from youtube_monitor import ffmpeg_renderer

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"")
    monkeypatch.setattr(
        ffmpeg_renderer.subprocess, "run",
        lambda *_a, **_k: sp.CompletedProcess([], 1, stdout="", stderr="hong"),
    )

    assert ffmpeg_renderer._mark_frame_size(clip, "ffmpeg", 1280, 720) == (1280, 720)


class CleanupIsSetForTheWholeSourceTests(unittest.TestCase):
    """A logo or burned-in subtitle belongs to the source, not to a scene.

    It sits in the same place on every clip cut from that film, so marking it
    per scene meant marking the same rectangle dozens of times — which is why
    nobody did, and why it survived into every render.
    """

    def _database(self, directory: str):
        from youtube_monitor.database import Database
        from pathlib import Path

        database = Database(Path(directory) / "cleanup.db")
        database.upsert_channel({
            "youtube_channel_id": "UC000000000000000000000E",
            "channel_url": "https://www.youtube.com/channel/UC000000000000000000000E",
            "title": "c", "uploads_playlist_id": "UU000000000000000000000E",
        })
        database.upsert_video({
            "youtube_video_id": "video-cleanup-1",
            "youtube_channel_id": "UC000000000000000000000E",
            "video_url": "https://www.youtube.com/watch?v=video-cleanup-1",
            "title": "t", "metadata_hash": "h", "raw_payload": {},
        })
        project = database.create_production_project("video-cleanup-1")
        script = database.create_project_script(project["id"], script_title="s")
        database.create_project_timeline(project["id"], script["id"], [
            {"segment_index": i, "voice_text": "a", "subtitle_text": "a",
             "visual_prompt": "p", "duration_seconds": 5}
            for i in range(1, 4)
        ])
        return database, int(project["id"]), int(script["id"])

    def test_one_call_marks_every_scene(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            database, project_id, script_id = self._database(directory)
            changed = database.set_timeline_cleanups(
                project_id, [{"position": "bottom_center", "method": "blur"}], script_id=script_id
            )
            self.assertEqual(changed, 3)
            for segment in database.list_project_timeline(project_id, script_id=script_id):
                self.assertIn("bottom_center", segment["edit_cleanups"])

    def test_clearing_puts_every_scene_back(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            database, project_id, script_id = self._database(directory)
            database.set_timeline_cleanups(project_id, [{"position": "bottom_center", "method": "blur"}])
            database.set_timeline_cleanups(project_id, [])
            for segment in database.list_project_timeline(project_id, script_id=script_id):
                self.assertEqual(segment["edit_cleanups"], "[]")

    def test_it_leaves_the_scene_own_transition_alone(self) -> None:
        """Only the cleanup list is this call's business."""
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            database, project_id, script_id = self._database(directory)
            segments = database.list_project_timeline(project_id, script_id=script_id)
            database.save_segment_edit(int(segments[0]["id"]), "cut", "zoom-in", note="giu lai")
            database.set_timeline_cleanups(project_id, [{"position": "top_right", "method": "blur"}])
            again = database.get_project_timeline_segment(int(segments[0]["id"]))
            self.assertEqual(again["edit_transition"], "cut")
            self.assertEqual(again["edit_effect"], "zoom-in")


class CleanupIsReachableFromTheStoryboardTests(unittest.TestCase):
    def setUp(self) -> None:
        from pathlib import Path

        self.page = studio_ui()

    def test_the_storyboard_can_mark_and_unmark_it(self) -> None:
        self.assertIn('id="studioCleanupPosition"', self.page)
        self.assertIn("applyTimelineCleanup(false)", self.page)
        self.assertIn("applyTimelineCleanup(true)", self.page)

    def test_it_says_what_happens_when_nothing_is_marked(self) -> None:
        """Nothing marked no longer means nothing covered.

        Leaving it unmarked was the normal case, not the rare one - the only
        way to mark anything was a planning step that could not see the
        picture - so an unmarked timeline now has the source measured at
        render time, and the storyboard has to say so rather than warn that
        the marks will survive.
        """
        self.assertIn("tự đo trên video gốc", self.page)

    def test_turning_covering_off_is_its_own_state(self) -> None:
        """Otherwise the next render would quietly switch it back on.

        An empty cleanup list is what an untouched project looks like, and
        that is exactly the state auto-covering acts on. A deliberate "leave
        the picture alone" has to be distinguishable from it.
        """
        self.assertIn("Đã tắt che", self.page)

    def test_the_storyboard_can_ask_for_a_measurement(self) -> None:
        self.assertIn("detectTimelineCleanup()", self.page)

    def test_the_endpoint_exists(self) -> None:
        from youtube_monitor.main import app

        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/projects/{project_id}/timeline/cleanups", paths)
