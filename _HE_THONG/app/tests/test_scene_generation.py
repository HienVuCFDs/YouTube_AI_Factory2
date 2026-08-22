import tempfile
import unittest
from base64 import b64encode
from pathlib import Path
from unittest.mock import patch

from youtube_monitor.database import Database
from youtube_monitor.scene_generator import _cloud_generation_error, _gemini_aspect_ratio, _openai_image_size, generate_gemini_image_scene, generate_gflow_cli_scene, generate_openai_image_scene


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
            meta_job = database.create_scene_generation_job(
                project["id"], segment["id"], "meta_ai_video", "A cinematic sunrise over mountains"
            )
            runway_job = database.create_scene_generation_job(
                project["id"], segment["id"], "runway", "A cinematic sunrise over mountains"
            )
            gflow_cli_job = database.create_scene_generation_job(
                project["id"], segment["id"], "gflow_cli", "A cinematic sunrise over mountains"
            )

            # The in-process worker queue must never pick up sidecar-only jobs.
            queued_ids = database.list_queued_scene_generation_job_ids()
            self.assertIn(runway_job["id"], queued_ids)
            self.assertIn(gflow_cli_job["id"], queued_ids)
            self.assertNotIn(antigravity_job["id"], queued_ids)
            self.assertNotIn(flow_job["id"], queued_ids)
            self.assertNotIn(meta_job["id"], queued_ids)

            # Each sidecar claim must only ever pick up its own provider's job.
            claimed_antigravity = database.claim_next_antigravity_scene_job()
            self.assertEqual(claimed_antigravity["id"], antigravity_job["id"])
            self.assertEqual(claimed_antigravity["status"], "running")
            self.assertIsNone(database.claim_next_antigravity_scene_job())  # none left

            claimed_flow = database.claim_next_scene_job_for_provider("flow_veo")
            self.assertEqual(claimed_flow["id"], flow_job["id"])
            self.assertEqual(claimed_flow["status"], "running")
            self.assertIsNone(database.claim_next_scene_job_for_provider("flow_veo"))  # none left

            claimed_meta = database.claim_next_scene_job_for_provider("meta_ai_video")
            self.assertEqual(claimed_meta["id"], meta_job["id"])
            self.assertEqual(claimed_meta["status"], "running")
            self.assertIsNone(database.claim_next_scene_job_for_provider("meta_ai_video"))  # none left

    def test_gflow_scene_creates_one_cloud_project_then_reuses_it(self):
        with tempfile.TemporaryDirectory() as directory:
            database, project, segment = self._project_with_timeline(directory)
            frame_path = Path(directory) / "frame.png"
            frame_path.write_bytes(b"png")
            frame = database.create_project_asset(
                project["id"],
                asset_type="ai_scene",
                original_name="frame.png",
                file_path=str(frame_path),
                mime_type="image/png",
            )
            job = database.create_scene_generation_job(
                project["id"], segment["id"], "gflow_cli", "Animate the frame",
                reference_asset_id=frame["id"], requires_reference_image=True,
            )
            with patch(
                "youtube_monitor.scene_generator.settings.gflow_config",
                return_value={"profile": "default"},
            ), patch(
                "youtube_monitor.scene_generator.create_gflow_project",
                return_value="flow-project-123",
            ) as create_project, patch(
                "youtube_monitor.scene_generator.generate_gflow_video",
                return_value=str(Path(directory) / "scene.mp4"),
            ) as generate:
                generate_gflow_cli_scene(database, job, Path(directory) / "artifacts")
                generate_gflow_cli_scene(database, job, Path(directory) / "artifacts")

            create_project.assert_called_once()
            self.assertEqual(generate.call_count, 2)
            self.assertEqual(generate.call_args.kwargs["gflow_project_id"], "flow-project-123")
            updated = database.get_production_project(project["id"])
            self.assertEqual(updated["gflow_project_id"], "flow-project-123")
            self.assertEqual(updated["gflow_profile"], "default")

    def test_browser_provider_job_completion_attaches_video_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            database, project, segment = self._project_with_timeline(directory)
            job = database.create_scene_generation_job(
                project["id"], segment["id"], "flow_veo", "A cinematic sunrise over mountains"
            )
            database.claim_next_scene_job_for_provider("flow_veo")
            completed = database.finish_scene_generation_job(
                job["id"], "completed", output_path=str(Path(directory) / "flow-scene.mp4")
            )
            self.assertEqual(completed["status"], "completed")
            timeline = database.list_project_timeline(project["id"])
            self.assertEqual(timeline[0]["visual_path"], str(Path(directory) / "flow-scene.mp4"))

            other_job = database.create_scene_generation_job(
                project["id"], segment["id"], "flow_veo", "A second scene"
            )
            database.claim_next_scene_job_for_provider("flow_veo")
            failed = database.finish_scene_generation_job(
                other_job["id"], "error", error="Flow timed out waiting for the clip"
            )
            self.assertEqual(failed["status"], "error")
            self.assertEqual(failed["error"], "Flow timed out waiting for the clip")

    def test_browser_job_includes_project_title_for_flow_workspace_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            database, project, segment = self._project_with_timeline(directory)
            job = database.create_scene_generation_job(
                project["id"], segment["id"], "flow_image", "Create the first storyboard frame"
            )
            self.assertEqual(job["project_title"], "Scene video")
            claimed = database.claim_next_scene_job_for_provider("flow_image")
            self.assertEqual(claimed["project_title"], "Scene video")

    def test_image_job_releases_dependent_video_with_exact_reference_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            database, project, segment = self._project_with_timeline(directory)
            image_job = database.create_scene_generation_job(
                project["id"], segment["id"], "flow_image", "Create the approved storyboard frame",
                job_kind="image",
            )
            video_job = database.create_scene_generation_job(
                project["id"], segment["id"], "flow_veo", "Animate this exact frame",
                duration_seconds=8,
                job_kind="video",
                depends_on_job_id=image_job["id"],
                requires_reference_image=True,
            )
            self.assertEqual(video_job["status"], "waiting")
            self.assertEqual(video_job["pipeline_stage"], "waiting_for_reference")
            self.assertIsNone(database.claim_scene_generation_job(video_job["id"]))

            image_path = Path(directory) / "approved-frame.png"
            image_path.write_bytes(b"png")
            asset = database.create_project_asset(
                project["id"], "image", image_path.name, str(image_path),
                mime_type="image/png", file_size=image_path.stat().st_size,
            )
            database.claim_scene_generation_job(image_job["id"])
            database.finish_scene_generation_job(
                image_job["id"], "completed", output_path=str(image_path),
                output_asset_id=asset["id"], release_dependents=False,
            )
            self.assertEqual(database.get_scene_generation_job(video_job["id"])["status"], "waiting")

            released = database.release_scene_generation_dependents(image_job["id"])
            self.assertEqual([item["id"] for item in released], [video_job["id"]])
            claimed = database.claim_scene_generation_job(video_job["id"])
            self.assertEqual(claimed["reference_asset_id"], asset["id"])
            self.assertTrue(claimed["requires_reference_image"])
            self.assertEqual(claimed["duration_seconds"], 8)
            self.assertTrue(claimed["claim_token"])

    def test_batch_video_builds_image_then_video_pipeline_when_scene_has_no_image(self):
        from youtube_monitor import main as main_module

        with tempfile.TemporaryDirectory() as directory:
            database, project, segment = self._project_with_timeline(directory)
            payload = main_module.BatchSceneGenerationRequest(
                provider="flow_veo",
                duration_seconds=8,
                requires_reference_image=True,
                reference_image_provider="flow_image",
                confirmed=True,
            )
            with patch.object(main_module, "database", database), patch.object(
                main_module, "_craft_image_prompt", side_effect=lambda prompt, context="": prompt
            ), patch.object(
                main_module, "_craft_video_prompt", side_effect=lambda prompt, **_: prompt
            ):
                result = main_module.queue_scene_generation_batch(project["id"], payload)

            self.assertEqual(result["preparation_count"], 1)
            self.assertEqual(result["queued_count"], 1)
            image_job = result["preparation_jobs"][0]
            video_job = result["jobs"][0]
            self.assertEqual(image_job["job_kind"], "image")
            self.assertEqual(video_job["job_kind"], "video")
            self.assertEqual(video_job["status"], "waiting")
            self.assertEqual(video_job["depends_on_job_id"], image_job["id"])
            self.assertTrue(video_job["requires_reference_image"])
            self.assertIsNone(video_job["reference_asset_id"])
            self.assertEqual(video_job["timeline_segment_id"], segment["id"])

    def test_batch_video_skips_scene_the_plan_wants_as_a_still(self):
        """A still scene must not be dragged through the video pipeline.

        The video batch used to run over the whole timeline, so a scene the
        orchestrator had planned as an image still got an image job plus a
        waiting video job — paying for motion the scene was never meant to
        have.
        """
        from youtube_monitor import main as main_module

        with tempfile.TemporaryDirectory() as directory:
            database, project, segment = self._project_with_timeline(directory)
            database.set_segment_visual_kind(
                segment["id"], "image", reason="Holds one diagram on screen"
            )
            payload = main_module.BatchSceneGenerationRequest(
                provider="flow_veo",
                duration_seconds=8,
                requires_reference_image=True,
                reference_image_provider="flow_image",
                confirmed=True,
            )
            with patch.object(main_module, "database", database), patch.object(
                main_module, "_craft_image_prompt", side_effect=lambda prompt, context="": prompt
            ), patch.object(
                main_module, "_craft_video_prompt", side_effect=lambda prompt, **_: prompt
            ):
                result = main_module.queue_scene_generation_batch(project["id"], payload)

            self.assertEqual(result["queued_count"], 0)
            self.assertEqual(result["preparation_count"], 0)

    def test_batch_video_still_runs_for_a_scene_planned_as_video(self):
        """The same batch must keep working for scenes that do want motion."""
        from youtube_monitor import main as main_module

        with tempfile.TemporaryDirectory() as directory:
            database, project, segment = self._project_with_timeline(directory)
            database.set_segment_visual_kind(
                segment["id"], "video", reason="The movement is the point"
            )
            payload = main_module.BatchSceneGenerationRequest(
                provider="flow_veo",
                duration_seconds=8,
                requires_reference_image=True,
                reference_image_provider="flow_image",
                confirmed=True,
            )
            with patch.object(main_module, "database", database), patch.object(
                main_module, "_craft_image_prompt", side_effect=lambda prompt, context="": prompt
            ), patch.object(
                main_module, "_craft_video_prompt", side_effect=lambda prompt, **_: prompt
            ):
                result = main_module.queue_scene_generation_batch(project["id"], payload)

            self.assertEqual(result["queued_count"], 1)
            self.assertEqual(result["preparation_count"], 1)
            self.assertEqual(result["jobs"][0]["timeline_segment_id"], segment["id"])

    def test_batch_never_creates_text_to_video_without_a_still_first(self):
        """A video scene always gets its still made first.

        Passing only video providers, with no plan and without asking for the
        reference-image pipeline, used to produce a bare text-to-video job.
        A clip generated from the prompt alone cannot match the storyboard
        image the rest of the video is built around, so that path is gone: the
        batch makes the still instead.
        """
        from youtube_monitor import main as main_module

        with tempfile.TemporaryDirectory() as directory:
            database, project, segment = self._project_with_timeline(directory)
            payload = main_module.BatchSceneGenerationRequest(
                providers=["flow_veo"],
                confirmed=True,
            )
            with patch.object(main_module, "database", database), patch.object(
                main_module, "_craft_image_prompt", side_effect=lambda prompt, context="": prompt
            ), patch.object(
                main_module, "_craft_video_prompt", side_effect=lambda prompt, **_: prompt
            ):
                result = main_module.queue_scene_generation_batch(project["id"], payload)

            for job in result["jobs"]:
                self.assertNotEqual(job["job_kind"], "video")
            for job in result["jobs"] + result["preparation_jobs"]:
                if job["job_kind"] == "video":
                    self.assertTrue(job["requires_reference_image"])

    def test_gif_batch_leaves_scenes_the_plan_marked_as_video_alone(self):
        """Asking for GIFs must not rewrite the plan.

        A GIF batch used to convert every moving scene, video included, and
        overwrite its recorded visual_kind — so a request for the two planned
        loops silently took over seven scenes the user had planned as video.
        Turning video scenes into loops is a planning decision
        (motion_policy="gif_only"), where it is recorded with a reason.
        """
        from youtube_monitor import main as main_module

        with tempfile.TemporaryDirectory() as directory:
            database, project, segment = self._project_with_timeline(directory)
            database.set_segment_visual_kind(
                segment["id"], "video", reason="The movement is the point"
            )
            payload = main_module.BatchSceneGenerationRequest(
                providers=["flow_image"],
                respect_plan=True,
                motion_as_gif=True,
                confirmed=True,
            )
            with patch.object(main_module, "database", database), patch.object(
                main_module, "_craft_image_prompt", side_effect=lambda prompt, context="": prompt
            ), patch.object(
                main_module, "_craft_gif_sheet_prompt", side_effect=lambda prompt, context="": prompt
            ):
                result = main_module.queue_scene_generation_batch(project["id"], payload)

            self.assertEqual(result["queued_count"], 0)
            after = database.get_project_timeline_segment(segment["id"])
            self.assertEqual(after["visual_kind"], "video")

    def test_scene_prompt_context_carries_narration_and_neighbours(self):
        """Prompts are written knowing the shots either side of them.

        A visual_prompt read alone says nothing about who the characters are
        or what the previous shot established, so each image came back styled
        independently and the sequence did not look like one film.
        """
        from youtube_monitor import main as main_module

        timeline = [
            {"segment_index": 1, "voice_text": "Mo dau", "visual_prompt": "Canh mot"},
            {"segment_index": 2, "voice_text": "Dien giai", "visual_prompt": "Canh hai"},
            {"segment_index": 3, "voice_text": "Ket", "visual_prompt": "Canh ba"},
        ]
        context = main_module._scene_prompt_context(timeline, 1)
        self.assertIn("Dien giai", context)
        self.assertIn("Canh mot", context)
        self.assertIn("Canh ba", context)
        # First and last scenes simply have one fewer neighbour.
        self.assertNotIn("LIEN TRUOC", main_module._scene_prompt_context(timeline, 0))
        self.assertNotIn("LIEN SAU", main_module._scene_prompt_context(timeline, 2))

    def test_batch_gif_routes_planned_video_to_image_provider_and_caps_smoke_test(self):
        """Opting out of the plan converts a video scene into a loop.

        respect_plan is off here, which is the caller explicitly saying "this
        project makes no video at all". With respect_plan on, the same request
        must leave a video scene alone — see the test above.
        """
        from youtube_monitor import main as main_module

        with tempfile.TemporaryDirectory() as directory:
            database, project, segment = self._project_with_timeline(directory)
            database.set_segment_visual_kind(
                segment["id"], "video", fps=10, reason="Scene needs motion"
            )
            payload = main_module.BatchSceneGenerationRequest(
                providers=["flow_image", "chatgpt_web_image", "gemini_web_image"],
                respect_plan=False,
                motion_as_gif=True,
                limit=1,
                confirmed=True,
            )
            with patch.object(main_module, "database", database), patch.object(
                main_module, "_craft_image_prompt", side_effect=lambda prompt, context="": prompt
            ):
                result = main_module.queue_scene_generation_batch(project["id"], payload)

            self.assertTrue(result["motion_as_gif"])
            self.assertEqual(result["limit"], 1)
            self.assertEqual(result["queued_count"], 1)
            job = result["jobs"][0]
            self.assertEqual(job["provider"], "flow_image")
            self.assertEqual(job["job_kind"], "gif")
            self.assertEqual(job["visual_kind"], "gif")
            self.assertEqual(job["visual_fps"], 10)

    def test_failed_image_review_can_requeue_parent_before_video_is_released(self):
        with tempfile.TemporaryDirectory() as directory:
            database, project, segment = self._project_with_timeline(directory)
            image_job = database.create_scene_generation_job(
                project["id"], segment["id"], "flow_image", "Create frame", job_kind="image"
            )
            video_job = database.create_scene_generation_job(
                project["id"], segment["id"], "flow_veo", "Animate frame",
                job_kind="video", depends_on_job_id=image_job["id"], requires_reference_image=True,
            )
            image_path = Path(directory) / "rejected.png"
            image_path.write_bytes(b"png")
            asset = database.create_project_asset(
                project["id"], "image", image_path.name, str(image_path), mime_type="image/png"
            )
            database.claim_scene_generation_job(image_job["id"])
            database.finish_scene_generation_job(
                image_job["id"], "completed", output_path=str(image_path),
                output_asset_id=asset["id"], release_dependents=False,
            )
            database.save_scene_job_review(image_job["id"], "fail", 3, "Wrong composition")
            retried = database.retry_scene_generation_job(image_job["id"])
            self.assertEqual(retried["status"], "queued")
            self.assertIsNone(retried["output_asset_id"])
            self.assertEqual(database.get_scene_generation_job(video_job["id"])["status"], "waiting")

    def test_watchdog_retries_once_then_fails_stale_scene_job(self):
        with tempfile.TemporaryDirectory() as directory:
            database, project, segment = self._project_with_timeline(directory)
            job = database.create_scene_generation_job(
                project["id"], segment["id"], "flow_veo", "A moving sunrise",
                job_kind="video", max_attempts=2,
            )
            database.claim_scene_generation_job(job["id"])
            with database._connect() as connection:
                connection.execute(
                    "UPDATE scene_generation_jobs SET heartbeat_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
                    (job["id"],),
                )
            first = database.recover_stale_scene_generation_jobs(30)
            self.assertEqual(first, [{"id": job["id"], "provider": "flow_veo", "requeued": True}])
            self.assertEqual(database.get_scene_generation_job(job["id"])["status"], "queued")

            database.claim_scene_generation_job(job["id"])
            with database._connect() as connection:
                connection.execute(
                    "UPDATE scene_generation_jobs SET heartbeat_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
                    (job["id"],),
                )
            second = database.recover_stale_scene_generation_jobs(30)
            self.assertEqual(second, [{"id": job["id"], "provider": "flow_veo", "requeued": False}])
            failed = database.get_scene_generation_job(job["id"])
            self.assertEqual(failed["status"], "error")
            self.assertEqual(failed["failure_kind"], "stale")

    def test_provider_circuit_opens_after_failures_and_success_resets_it(self):
        with tempfile.TemporaryDirectory() as directory:
            database, _, _ = self._project_with_timeline(directory)
            for index in range(3):
                state = database.record_scene_provider_failure(
                    "flow_veo", f"failure {index + 1}", threshold=3, cooldown_seconds=60,
                )
            self.assertTrue(state["circuit_open"])
            self.assertEqual(state["consecutive_failures"], 3)
            database.record_scene_provider_success("flow_veo")
            reset = database.get_scene_provider_state("flow_veo")
            self.assertFalse(reset["circuit_open"])
            self.assertEqual(reset["consecutive_failures"], 0)

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
