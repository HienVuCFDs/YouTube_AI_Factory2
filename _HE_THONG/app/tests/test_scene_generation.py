import tempfile
import unittest
from base64 import b64encode
from pathlib import Path
from unittest.mock import patch

from youtube_monitor.database import Database
from youtube_monitor.scene_generator import _cloud_generation_error, _gemini_aspect_ratio, _openai_image_size, generate_gemini_image_scene, generate_openai_image_scene


class SceneGenerationDatabaseTests(unittest.TestCase):
    def _project_with_timeline(self, directory: str) -> tuple[Database, dict, dict]:
        database = Database(Path(directory) / "scene.db")
        channel_id = "UC1234567890123456789012"
        video_id = "scene-video-1"
        database.upsert_channel(
            {
                "youtube_channel_id": channel_id,
                "channel_url": f"https://youtube.com/channel/{channel_id}",
                "title": "Scene channel",
                "uploads_playlist_id": "UU1234567890123456789012",
            }
        )
        database.upsert_video(
            {
                "youtube_video_id": video_id,
                "youtube_channel_id": channel_id,
                "video_url": f"https://youtube.com/watch?v={video_id}",
                "title": "Scene video",
                "metadata_hash": "scene-hash",
                "raw_payload": {},
            }
        )
        project = database.create_production_project(video_id)
        script = database.create_project_script(project["id"], script_title="Scene script")
        timeline = database.create_project_timeline(
            project["id"],
            script["id"],
            [
                {
                    "segment_index": 1,
                    "voice_text": "Narration",
                    "subtitle_text": "Narration",
                    "visual_prompt": "A cinematic sunrise over mountains",
                    "duration_seconds": 5,
                }
            ],
        )
        return database, project, timeline[0]

    def test_completed_scene_job_attaches_video_to_timeline(self):
        with tempfile.TemporaryDirectory() as directory:
            database, project, segment = self._project_with_timeline(directory)
            job = database.create_scene_generation_job(
                project["id"],
                segment["id"],
                "runway",
                "A cinematic sunrise over mountains",
                duration_seconds=5,
            )
            self.assertEqual(job["status"], "queued")
            claimed = database.claim_scene_generation_job(job["id"])
            self.assertEqual(claimed["status"], "running")
            database.update_scene_generation_task(job["id"], "runway-task-123")
            completed = database.finish_scene_generation_job(
                job["id"], "completed", output_path=str(Path(directory) / "scene.mp4")
            )
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["task_id"], "runway-task-123")
            timeline = database.list_project_timeline(project["id"])
            self.assertEqual(timeline[0]["visual_path"], str(Path(directory) / "scene.mp4"))
            self.assertEqual(timeline[0]["status"], "asset_ready")

    def test_external_sidecar_providers_are_isolated_from_each_other_and_the_worker_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            database, project, segment = self._project_with_timeline(directory)
            antigravity_job = database.create_scene_generation_job(
                project["id"], segment["id"], "antigravity_image", "A cinematic sunrise over mountains"
            )
            flow_job = database.create_scene_generation_job(
                project["id"], segment["id"], "flow_veo", "A cinematic sunrise over mountains"
            )
            runway_job = database.create_scene_generation_job(
                project["id"], segment["id"], "runway", "A cinematic sunrise over mountains"
            )

            # The in-process worker queue must never pick up sidecar-only jobs.
            queued_ids = database.list_queued_scene_generation_job_ids()
            self.assertIn(runway_job["id"], queued_ids)
            self.assertNotIn(antigravity_job["id"], queued_ids)
            self.assertNotIn(flow_job["id"], queued_ids)

            # Each sidecar claim must only ever pick up its own provider's job.
            claimed_antigravity = database.claim_next_antigravity_scene_job()
            self.assertEqual(claimed_antigravity["id"], antigravity_job["id"])
            self.assertEqual(claimed_antigravity["status"], "running")
            self.assertIsNone(database.claim_next_antigravity_scene_job())  # none left

            claimed_flow = database.claim_next_flow_veo_scene_job()
            self.assertEqual(claimed_flow["id"], flow_job["id"])
            self.assertEqual(claimed_flow["status"], "running")
            self.assertIsNone(database.claim_next_flow_veo_scene_job())  # none left

    def test_flow_veo_job_completion_attaches_video_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            database, project, segment = self._project_with_timeline(directory)
            job = database.create_scene_generation_job(
                project["id"], segment["id"], "flow_veo", "A cinematic sunrise over mountains"
            )
            database.claim_next_flow_veo_scene_job()
            completed = database.finish_scene_generation_job(
                job["id"], "completed", output_path=str(Path(directory) / "flow-scene.mp4")
            )
            self.assertEqual(completed["status"], "completed")
            timeline = database.list_project_timeline(project["id"])
            self.assertEqual(timeline[0]["visual_path"], str(Path(directory) / "flow-scene.mp4"))

            other_job = database.create_scene_generation_job(
                project["id"], segment["id"], "flow_veo", "A second scene"
            )
            database.claim_next_flow_veo_scene_job()
            failed = database.finish_scene_generation_job(
                other_job["id"], "error", error="Flow timed out waiting for the clip"
            )
            self.assertEqual(failed["status"], "error")
            self.assertEqual(failed["error"], "Flow timed out waiting for the clip")

    def test_scene_job_requires_segment_from_same_project(self):
        with tempfile.TemporaryDirectory() as directory:
            database, project, segment = self._project_with_timeline(directory)
            self.assertIsNone(
                database.create_scene_generation_job(
                    project["id"] + 999,
                    segment["id"],
                    "runway",
                    "A valid prompt",
                )
            )

    def test_openai_image_scene_writes_png_for_timeline(self):
        class FakeResponse:
            status_code = 200
            text = ""

            def json(self):
                return {"data": [{"b64_json": b64encode(b"png-content").decode("ascii")}]} 

        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def post(self, url, *, headers, json):
                self.url = url
                self.headers = headers
                self.payload = json
                return FakeResponse()

        with tempfile.TemporaryDirectory() as directory:
            database, project, segment = self._project_with_timeline(directory)
            job = database.create_scene_generation_job(
                project["id"], segment["id"], "openai_image", "A warm cat story", ratio="720:1280"
            )
            fake_client = FakeClient()
            with patch("youtube_monitor.scene_generator.settings.openai_config", return_value=("test-key", "gpt-4o-mini")), patch(
                "youtube_monitor.scene_generator.httpx.Client", return_value=fake_client
            ):
                output = generate_openai_image_scene(database, job, Path(directory) / "artifacts")
            self.assertEqual(Path(output).read_bytes(), b"png-content")
            self.assertEqual(fake_client.url, "https://api.openai.com/v1/images/generations")
            self.assertEqual(fake_client.payload["size"], "1024x1536")
            self.assertEqual(fake_client.payload["model"], "gpt-image-1")

    def test_openai_image_size_maps_story_ratios(self):
        self.assertEqual(_openai_image_size("1280:720"), "1536x1024")
        self.assertEqual(_openai_image_size("720:1280"), "1024x1536")
        self.assertEqual(_openai_image_size("1024:1024"), "1024x1024")

    def test_gemini_image_scene_writes_story_image(self):
        class FakeResponse:
            status_code = 200
            text = ""

            def json(self):
                return {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": b64encode(b"gemini-png").decode("ascii")}}]}}]}

        class FakeClient:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def post(self, url, *, headers, json):
                self.url, self.headers, self.payload = url, headers, json
                return FakeResponse()

        with tempfile.TemporaryDirectory() as directory:
            database, project, segment = self._project_with_timeline(directory)
            job = database.create_scene_generation_job(project["id"], segment["id"], "gemini_image", "A cat finds a letter", ratio="1280:720")
            client = FakeClient()
            with patch("youtube_monitor.scene_generator.settings.gemini_config", return_value=("test-key", "gemini-3.1-flash-image", "veo-3.1-lite-generate-preview")), patch("youtube_monitor.scene_generator.httpx.Client", return_value=client):
                output = generate_gemini_image_scene(database, job, Path(directory) / "artifacts")
            self.assertEqual(Path(output).read_bytes(), b"gemini-png")
            self.assertIn("gemini-3.1-flash-image:generateContent", client.url)
            self.assertEqual(client.payload["generationConfig"]["imageConfig"]["aspectRatio"], "16:9")
            self.assertEqual(_gemini_aspect_ratio("720:1280"), "9:16")

    def test_gemini_quota_error_explains_billing_without_raw_payload(self):
        class FakeResponse:
            status_code = 429
            text = '{"code":429,"message":"Quota exceeded"}'

            def read(self):
                return b""

            def json(self):
                return {"code": 429, "message": "Quota exceeded"}

        message = _cloud_generation_error(FakeResponse(), "Google Gemini")
        self.assertIn("quota tạo ảnh/video", message)
        self.assertIn("Billing", message)
        self.assertNotIn("{'code'", message)


if __name__ == "__main__":
    unittest.main()
