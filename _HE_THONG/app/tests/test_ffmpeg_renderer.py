from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from youtube_monitor.ffmpeg_renderer import FfmpegRenderError, _encoding_arguments, _segment_arguments, generate_local_visual_draft


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
