import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import json

from youtube_monitor.database import Database
from youtube_monitor.ffmpeg_renderer import ffmpeg_available
from youtube_monitor.production_worker import ProductionJobError, ProductionWorker, _run_voxcpm_batch, run_director_production_job


class ProductionWorkerTests(unittest.TestCase):
    def _database_with_timeline(self, directory: str) -> tuple[Database, dict]:
        database = Database(Path(directory) / "test.db")
        database.upsert_channel(
            {
                "youtube_channel_id": "UC1234567890123456789012",
                "channel_url": "https://www.youtube.com/channel/UC1234567890123456789012",
                "title": "Test channel",
                "uploads_playlist_id": "UU1234567890123456789012",
            }
        )
        database.upsert_video(
            {
                "youtube_video_id": "video-production-1",
                "youtube_channel_id": "UC1234567890123456789012",
                "video_url": "https://www.youtube.com/watch?v=video-production-1",
                "title": "Production source",
                "metadata_hash": "hash-production-1",
                "raw_payload": {},
            }
        )
        project = database.create_production_project("video-production-1")
        script = database.create_project_script(
            project["id"],
            script_title="Production script",
            hook="Hook",
        )
        database.create_project_timeline(
            project["id"],
            script["id"],
            [
                {
                    "segment_index": 1,
                    "section": "hook",
                    "voice_text": "Hello production",
                    "subtitle_text": "Hello production",
                    "visual_prompt": "A clean opening frame",
                    "asset_type": "talking_head",
                    "duration_seconds": 8,
                }
            ],
        )
        return database, project

    def test_dry_run_jobs_create_plans_without_media(self):
        with tempfile.TemporaryDirectory() as directory:
            database, project = self._database_with_timeline(directory)
            script = database.get_latest_project_script(project["id"])
            worker = ProductionWorker(database, Path(directory) / "artifacts")
            voice_job = worker.enqueue(project["id"], script["id"], "voiceover", "dry_run")
            worker._process(voice_job["id"])
            finished_voice = database.get_project_job(voice_job["id"])
            self.assertEqual(finished_voice["status"], "completed")
            self.assertTrue(Path(finished_voice["output_path"]).is_file())
            self.assertEqual(database.list_project_timeline(project["id"])[0]["audio_path"], "")
            self.assertTrue(any("hoàn tất" in event["message"].lower() for event in database.list_project_job_events(voice_job["id"])))

            segment = database.list_project_timeline(project["id"])[0]
            visual = Path(directory) / "source.mp4"
            visual.write_bytes(b"source")
            database.update_project_timeline_segment(int(segment["id"]), visual_path=str(visual))
            database.replace_timeline_edit_beats(
                int(segment["id"]),
                [
                    {"source_kind": "primary", "visual_path": str(visual), "duration_seconds": 4},
                    {"source_kind": "source_frame", "visual_path": str(visual), "duration_seconds": 4},
                ],
            )

            render_job = worker.enqueue(project["id"], script["id"], "render", "dry_run")
            worker._process(render_job["id"])
            finished_render = database.get_project_job(render_job["id"])
            self.assertEqual(finished_render["status"], "completed")
            self.assertTrue(Path(finished_render["output_path"]).is_file())
            manifest = json.loads(Path(finished_render["output_path"]).read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["segments"][0]["edit_beats"]), 2)

            premiere_job = worker.enqueue(project["id"], script["id"], "premiere_draft", "dry_run")
            worker._process(premiere_job["id"])
            finished_premiere = database.get_project_job(premiere_job["id"])
            self.assertEqual(finished_premiere["status"], "completed")
            self.assertTrue(Path(finished_premiere["output_path"]).is_file())

    def test_voiceover_segment_job_is_scoped_and_does_not_block_other_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            database, project = self._database_with_timeline(directory)
            script = database.get_latest_project_script(project["id"])
            timeline = database.list_project_timeline(project["id"])
            segment_id = int(timeline[0]["id"])
            worker = ProductionWorker(database, Path(directory) / "artifacts")

            job = worker.enqueue(
                project["id"], script["id"], "voiceover_segment", "dry_run", segment_id=segment_id,
            )
            self.assertEqual(job["segment_id"], segment_id)

            # A whole-project "voiceover" job must not be treated as a duplicate
            # of a segment-scoped one (different segment_id, same job_type
            # prefix) — the dedup check added for segment_id has to actually
            # distinguish them, not just always match on job_type.
            whole_project_job = worker.enqueue(project["id"], script["id"], "voiceover", "dry_run")
            self.assertNotEqual(whole_project_job["id"], job["id"])

            worker._process(job["id"])
            finished = database.get_project_job(job["id"])
            self.assertEqual(finished["status"], "completed")
            self.assertEqual(finished["segment_id"], segment_id)

    def test_voxcpm_batch_sends_reference_style_not_prompt_text(self):
        """Regression test: VoxCPM's `prompt_text` must be an exact transcript
        of the reference clip (per the model's own docs) — sending our
        free-text voice *description* there broke audio/text alignment and
        produced wrong-language speech. It belongs in `style` instead, which
        voxcpm_runner.py prepends to the narration as "(style) text"."""
        with tempfile.TemporaryDirectory() as directory:
            work_dir = Path(directory) / "work"
            work_dir.mkdir()
            reference = Path(directory) / "reference.wav"
            reference.write_bytes(b"fake-wav-bytes")

            captured = {}

            def fake_prepare(ref, cwd, python_executable):
                return ref

            def fake_run(command, **kwargs):
                manifest_path = Path(command[command.index("--manifest") + 1])
                captured["manifest"] = json.loads(manifest_path.read_text(encoding="utf-8"))
                class Result:
                    returncode = 0
                    stdout = ""
                    stderr = ""
                return Result()

            with patch("youtube_monitor.production_worker._prepare_voxcpm_reference_audio", side_effect=fake_prepare), \
                 patch("youtube_monitor.production_worker.subprocess.run", side_effect=fake_run):
                _run_voxcpm_batch(
                    "python.exe", "runner.py", "openbmb/VoxCPM2", "cuda",
                    [{"text": "Xin chao", "output": str(work_dir / "out.wav")}],
                    work_dir,
                    reference_audio=str(reference),
                    prompt_text="Giọng kể chuyện tiếng Việt tự nhiên, dùng mẫu Giọng mẫu 2.",
                )

            request = captured["manifest"][0]
            self.assertEqual(request["style"], "Giọng kể chuyện tiếng Việt tự nhiên, dùng mẫu Giọng mẫu 2.")
            self.assertNotIn("prompt_text", request)
            self.assertEqual(request["reference_audio"], str(reference))

    def test_real_provider_requires_command(self):
        with tempfile.TemporaryDirectory() as directory:
            database, project = self._database_with_timeline(directory)
            script = database.get_latest_project_script(project["id"])
            worker = ProductionWorker(database, Path(directory) / "artifacts")
            job = database.create_project_job(project["id"], script["id"], "voiceover", "pyvideotrans")
            with self.assertRaises(ProductionJobError):
                from youtube_monitor.production_worker import run_voiceover_job

                run_voiceover_job(database, job, Path(directory) / "artifacts", "")

    def test_queued_job_can_be_cancelled_and_is_not_claimed(self):
        with tempfile.TemporaryDirectory() as directory:
            database, project = self._database_with_timeline(directory)
            script = database.get_latest_project_script(project["id"])
            job = database.create_project_job(project["id"], script["id"], "voiceover", "dry_run")
            cancelled = database.cancel_queued_project_job(job["id"])
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertIn("người dùng", cancelled["error"])
            self.assertIsNone(database.claim_project_job(job["id"]))
            self.assertEqual(database.project_job_status(project["id"])["cancelled"], 1)
            self.assertTrue(any("hủy" in event["message"].lower() for event in database.list_project_job_events(job["id"])))

    def test_builtin_ffmpeg_provider_rejects_a_timeline_without_visuals(self):
        if not ffmpeg_available():
            self.skipTest("FFmpeg is not installed")
        with tempfile.TemporaryDirectory() as directory:
            database, project = self._database_with_timeline(directory)
            script = database.get_latest_project_script(project["id"])
            worker = ProductionWorker(database, Path(directory) / "artifacts")
            job = worker.enqueue(project["id"], script["id"], "render", "ffmpeg_builtin")
            worker._process(job["id"])
            finished = database.get_project_job(job["id"])
            self.assertEqual(finished["status"], "error")
            self.assertIn("cảnh", finished["error"])

    def test_director_keeps_a_rendered_video_when_quality_only_warns_about_thumbnail(self):
        with tempfile.TemporaryDirectory() as directory:
            database, project = self._database_with_timeline(directory)
            script = database.get_latest_project_script(project["id"])
            job = database.create_project_job(project["id"], script["id"], "director_production", "edge_tts")
            final_path = Path(directory) / "final.mp4"
            final_path.write_bytes(b"mp4")
            segment = database.list_project_timeline(project["id"], script_id=script["id"])[0]
            with patch("youtube_monitor.production_worker.run_voiceover_job"), patch(
                "youtube_monitor.production_worker.generate_local_visual_draft",
                return_value=[{"segment_id": segment["id"], "visual_path": str(final_path), "duration_seconds": 8}],
            ), patch("youtube_monitor.production_worker.run_render_job", return_value=str(final_path)), patch(
                "youtube_monitor.production_worker.build_quality_report",
                return_value={"status": "warning", "issues": ["thumbnail missing"]},
            ), patch("youtube_monitor.production_worker.quality_report_markdown", return_value="# Quality Check\n"):
                result = run_director_production_job(
                    database, job, Path(directory) / "artifacts", "", "edge", "", "ffmpeg"
                )
            self.assertEqual(Path(result), final_path)
            self.assertTrue((Path(directory) / "artifacts" / str(project["id"]) / "04_XUAT_BAN" / "quality-report.md").is_file())


if __name__ == "__main__":
    unittest.main()
