from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from youtube_monitor.database import Database
from youtube_monitor.ffmpeg_renderer import _segment_arguments
from youtube_monitor.gif_generator import materialize_gif_asset


class GifPipelineTests(unittest.TestCase):
    def test_materialize_gif_registers_final_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "gif.db")
            channel_id = "UC1234567890123456789012"
            video_id = "gif-video-1"
            database.upsert_channel({
                "youtube_channel_id": channel_id,
                "channel_url": f"https://youtube.com/channel/{channel_id}",
                "title": "GIF channel",
                "uploads_playlist_id": "UU1234567890123456789012",
            })
            database.upsert_video({
                "youtube_video_id": video_id,
                "youtube_channel_id": channel_id,
                "video_url": f"https://youtube.com/watch?v={video_id}",
                "title": "GIF project",
                "metadata_hash": "gif-hash",
                "raw_payload": {},
            })
            project = database.create_production_project(video_id)
            script = database.create_project_script(project["id"], script_title="GIF script")
            segment = database.create_project_timeline(project["id"], script["id"], [{
                "segment_index": 1,
                "voice_text": "Narration",
                "subtitle_text": "Narration",
                "visual_prompt": "A moving diagram",
                "duration_seconds": 4,
            }])[0]
            database.set_segment_visual_kind(segment["id"], "gif", fps=8, reason="Loop")
            job = database.create_scene_generation_job(
                project["id"], segment["id"], "flow_image", "A moving diagram", job_kind="gif"
            )
            source_path = root / "source.jpg"
            source_path.write_bytes(b"jpeg")
            source = database.create_project_asset(
                project["id"], "image", source_path.name, str(source_path), mime_type="image/jpeg"
            )

            def fake_create(_source, output, **_kwargs):
                Path(output).write_bytes(b"GIF89a-test")
                return str(output)

            with patch("youtube_monitor.gif_generator.create_animated_gif", side_effect=fake_create):
                gif_asset = materialize_gif_asset(database, job, source)

            self.assertEqual(gif_asset["asset_type"], "image")
            self.assertEqual(gif_asset["mime_type"], "image/gif")
            self.assertTrue(str(gif_asset["file_path"]).endswith("-motion.gif"))
            self.assertTrue(Path(gif_asset["file_path"]).is_file())

    def test_renderer_loops_gif_as_animation_without_still_zoompan(self) -> None:
        args = _segment_arguments(
            "ffmpeg",
            {"segment_index": 1},
            Path("F:/project/scene.gif"),
            None,
            Path("F:/project/segment.mp4"),
            5.0,
            1920,
            1080,
            30,
            1,
            "h264_nvenc",
        )
        self.assertIn("-stream_loop", args)
        self.assertNotEqual(args[args.index("-stream_loop") + 1], "0")
        video_filter = args[args.index("-vf") + 1]
        self.assertNotIn("zoompan", video_filter)


if __name__ == "__main__":
    unittest.main()
