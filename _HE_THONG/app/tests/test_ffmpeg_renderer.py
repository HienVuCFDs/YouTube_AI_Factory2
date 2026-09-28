from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from youtube_monitor.ffmpeg_renderer import (
    FfmpegRenderError,
    _encoding_arguments,
    _segment_arguments,
    generate_local_visual_draft,
    render_timeline_with_ffmpeg,
)


class FfmpegRendererTests(unittest.TestCase):
    def test_missing_visual_is_rejected_for_a_production_render(self) -> None:
        with self.assertRaises(FfmpegRenderError):
            _segment_arguments(
                "ffmpeg", {"voice_text": "No text-card fallback"}, None, None,
                __import__("pathlib").Path("segment.mp4"), 4, 1920, 1080, 30, 1, "libx264",
            )

    def test_encoder_arguments_support_gpu_and_cpu(self) -> None:
        self.assertIn("h264_nvenc", _encoding_arguments("h264_nvenc"))
        self.assertIn("libx264", _encoding_arguments("libx264"))

    def test_background_music_adds_a_low_volume_mix_and_fade(self) -> None:
        args = _segment_arguments(
            "ffmpeg",
            {"voice_text": "Voice"},
            __import__("pathlib").Path("clip.mp4"),
            __import__("pathlib").Path("voice.mp3"),
            __import__("pathlib").Path("segment.mp4"),
            6,
            1920,
            1080,
            30,
            1,
            "libx264",
            None,
            __import__("pathlib").Path("music.mp3"),
            0.1,
            "fade",
        )
        joined = " ".join(args)
        self.assertIn("-filter_complex", args)
        self.assertIn("amix=inputs=2", joined)
        self.assertIn("sidechaincompress", joined)
        self.assertIn("loudnorm=I=-16:TP=-1.5", joined)
        self.assertIn("[aout]", joined)
        self.assertIn("fade=t=out", joined)

    def test_voice_only_audio_is_loudness_normalized(self) -> None:
        args = _segment_arguments(
            "ffmpeg",
            {"voice_text": "Voice"},
            __import__("pathlib").Path("clip.mp4"),
            __import__("pathlib").Path("voice.mp3"),
            __import__("pathlib").Path("segment.mp4"),
            6,
            1920,
            1080,
            30,
            1,
            "libx264",
        )
        self.assertIn("-af", args)
        self.assertIn("loudnorm=I=-16:TP=-1.5", args[args.index("-af") + 1])
        self.assertIn("192k", args)

    def test_image_visual_uses_subtle_ken_burns_motion(self) -> None:
        args = _segment_arguments(
            "ffmpeg",
            {"voice_text": "Voice"},
            __import__("pathlib").Path("still.jpg"),
            __import__("pathlib").Path("voice.mp3"),
            __import__("pathlib").Path("segment.mp4"),
            6,
            1920,
            1080,
            30,
            1,
            "libx264",
        )
        self.assertIn("zoompan", " ".join(args))

    def test_vertical_image_is_fitted_before_motion_to_avoid_stretching(self) -> None:
        args = _segment_arguments(
            "ffmpeg",
            {"voice_text": "Voice"},
            Path("landscape-still.jpg"),
            Path("voice.mp3"),
            Path("segment.mp4"),
            6,
            720,
            1280,
            30,
            1,
            "libx264",
            fit="cover",
        )
        video_filter = args[args.index("-vf") + 1]
        self.assertLess(video_filter.index("force_original_aspect_ratio=increase"), video_filter.index("zoompan"))
        self.assertLess(video_filter.index("crop=720:1280"), video_filter.index("zoompan"))

    def test_second_primary_edit_beat_continues_from_its_timeline_offset(self) -> None:
        commands: list[list[str]] = []

        def fake_run(arguments: list[str], _cwd: Path) -> None:
            commands.append(arguments)
            target = Path(arguments[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"mp4")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clip = root / "clip.mp4"
            voice = root / "voice.mp3"
            clip.write_bytes(b"video")
            voice.write_bytes(b"audio")
            timeline = [{
                "segment_index": 1,
                "visual_path": str(clip),
                "audio_path": str(voice),
                "duration_seconds": 12,
                "edit_beats": [
                    {"source_kind": "primary", "visual_path": str(clip), "start_seconds": 0, "duration_seconds": 6},
                    {"source_kind": "primary", "visual_path": str(clip), "start_seconds": 6, "duration_seconds": 6},
                ],
            }]
            with patch("youtube_monitor.ffmpeg_renderer.resolve_ffmpeg", return_value="ffmpeg"), patch(
                "youtube_monitor.ffmpeg_renderer._supports_nvenc", return_value=True
            ), patch("youtube_monitor.ffmpeg_renderer.media_duration_seconds", return_value=12.0), patch(
                "youtube_monitor.ffmpeg_renderer._run", side_effect=fake_run
            ):
                render_timeline_with_ffmpeg(timeline, root / "render")

        second_beat = next(command for command in commands if str(command[-1]).endswith("beat-002.mp4"))
        self.assertIn("-ss", second_beat)
        self.assertEqual(second_beat[second_beat.index("-ss") + 1], "6.000")

    def test_final_fade_transition_uses_real_crossfade(self) -> None:
        commands: list[list[str]] = []

        def fake_run(arguments: list[str], _cwd: Path) -> None:
            commands.append(arguments)
            target = Path(arguments[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"mp4")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clip = root / "clip.mp4"
            clip.write_bytes(b"video")
            timeline = [
                {"segment_index": 1, "visual_path": str(clip), "duration_seconds": 2},
                {"segment_index": 2, "visual_path": str(clip), "duration_seconds": 2, "edit_transition": "fade"},
            ]
            with patch("youtube_monitor.ffmpeg_renderer.resolve_ffmpeg", return_value="ffmpeg"), patch(
                "youtube_monitor.ffmpeg_renderer._supports_nvenc", return_value=False
            ), patch("youtube_monitor.ffmpeg_renderer.GPU_ONLY", False), patch(
                "youtube_monitor.ffmpeg_renderer._run", side_effect=fake_run
            ):
                render_timeline_with_ffmpeg(timeline, root / "render", transition="fade")

        final_command = commands[-1]
        self.assertIn("-filter_complex", final_command)
        graph = final_command[final_command.index("-filter_complex") + 1]
        self.assertIn("xfade=transition=fade", graph)
        self.assertIn("acrossfade", graph)
        self.assertNotIn("-f concat", " ".join(final_command))

        first_segment = next(command for command in commands if str(command[-1]).endswith("segment-001.mp4"))
        video_filter = first_segment[first_segment.index("-vf") + 1]
        self.assertNotIn("fade=t=in", video_filter)

    def test_final_cut_transition_keeps_fast_concat_copy(self) -> None:
        commands: list[list[str]] = []

        def fake_run(arguments: list[str], _cwd: Path) -> None:
            commands.append(arguments)
            target = Path(arguments[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"mp4")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clip = root / "clip.mp4"
            clip.write_bytes(b"video")
            timeline = [
                {"segment_index": 1, "visual_path": str(clip), "duration_seconds": 2},
                {"segment_index": 2, "visual_path": str(clip), "duration_seconds": 2, "edit_transition": "cut"},
            ]
            with patch("youtube_monitor.ffmpeg_renderer.resolve_ffmpeg", return_value="ffmpeg"), patch(
                "youtube_monitor.ffmpeg_renderer._supports_nvenc", return_value=False
            ), patch("youtube_monitor.ffmpeg_renderer.GPU_ONLY", False), patch(
                "youtube_monitor.ffmpeg_renderer._run", side_effect=fake_run
            ):
                render_timeline_with_ffmpeg(timeline, root / "render", transition="cut")

        final_command = commands[-1]
        self.assertIn("-f", final_command)
        self.assertEqual(final_command[final_command.index("-f") + 1], "concat")
        self.assertIn("-c", final_command)
        self.assertEqual(final_command[final_command.index("-c") + 1], "copy")
        self.assertNotIn("-filter_complex", final_command)

    def test_director_draft_visuals_use_nvenc_when_gpu_only_is_enabled(self) -> None:
        commands: list[list[str]] = []

        def fake_run(arguments: list[str], _cwd: Path) -> None:
            commands.append(arguments)
            Path(arguments[-1]).write_bytes(b"mp4")

        with tempfile.TemporaryDirectory() as directory, patch("youtube_monitor.ffmpeg_renderer.resolve_ffmpeg", return_value="ffmpeg"), patch("youtube_monitor.ffmpeg_renderer._supports_nvenc", return_value=True), patch("youtube_monitor.ffmpeg_renderer._run", side_effect=fake_run):
            results = generate_local_visual_draft(
                [{"id": 7, "segment_index": 1, "duration_seconds": 4, "voice_text": "Mở đầu"}],
                Path(directory),
            )
        self.assertEqual(results[0]["segment_id"], 7)
        self.assertIn("h264_nvenc", commands[0])
        self.assertIn("drawtext", " ".join(commands[0]))


def test_sound_cues_mix_into_segment_audio(tmp_path) -> None:
    clip = tmp_path / "source.mp4"
    voice = tmp_path / "voice.wav"
    sfx = tmp_path / "whoosh.wav"
    clip.write_bytes(b"video")
    voice.write_bytes(b"voice")
    sfx.write_bytes(b"sfx")

    args = _segment_arguments(
        "ffmpeg", {}, clip, voice, tmp_path / "out.mp4", 3.0, 320, 568, 12, 1, "libx264",
        transition="cut", effect="static", sound_cues=[{
            "path": sfx, "start_seconds": 0.4, "duration_seconds": 0.7, "volume": 0.28,
        }],
    )

    assert str(sfx) in args
    graph = args[args.index("-filter_complex") + 1]
    assert "adelay=400|400" in graph
    assert "amix=inputs=2" in graph
    assert "[sfx1]" in graph


def test_the_scenes_keep_their_order_however_they_finish() -> None:
    """Scenes are independent files and are now encoded several at a time, so
    which one finishes first is no longer which one comes first. Reading the
    order from arrival would silently re-cut the film.
    """
    import youtube_monitor.ffmpeg_renderer as renderer

    timeline = [{"segment_index": index} for index in range(1, 6)]
    finished: list[int] = []

    def render_one(position, item):
        finished.append(position)
        return Path(f"segment-{position}.mp4"), float(position), {"segment_index": position}

    rendered = [None] * len(timeline)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(render_one, position, item): position
                   for position, item in enumerate(timeline)}
        for future in as_completed(futures):
            rendered[futures[future]] = future.result()

    assert [item[0].name for item in rendered] == [
        f"segment-{position}.mp4" for position in range(len(timeline))
    ]
    assert renderer.RENDER_WORKERS >= 1


def test_the_worker_count_stays_within_bounds() -> None:
    """Encoder sessions and memory are shared with everything else running."""
    import youtube_monitor.ffmpeg_renderer as renderer

    assert 1 <= renderer.RENDER_WORKERS <= 8
