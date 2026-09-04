import tempfile
import unittest
import sqlite3
from pathlib import Path

from youtube_monitor.database import Database


class DatabaseTests(unittest.TestCase):
    def test_video_upsert_is_idempotent_and_tracks_metadata_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "test.db")
            database.upsert_channel(
                {
                    "youtube_channel_id": "UC1234567890123456789012",
                    "channel_url": "https://www.youtube.com/channel/UC1234567890123456789012",
                    "title": "Test channel",
                    "uploads_playlist_id": "UU1234567890123456789012",
                }
            )
            video = {
                "youtube_video_id": "video-1",
                "youtube_channel_id": "UC1234567890123456789012",
                "video_url": "https://www.youtube.com/watch?v=video-1",
                "title": "First title",
                "description": "Description",
                "metadata_hash": "hash-1",
                "raw_payload": {},
                "view_count": 10,
            }
            first = database.upsert_video(video)
            second = database.upsert_video(video)
            video["title"] = "Updated title"
            video["metadata_hash"] = "hash-2"
            third = database.upsert_video(video)

            self.assertTrue(first["is_new"])
            self.assertFalse(second["is_new"])
            self.assertFalse(second["metadata_changed"])
            self.assertTrue(third["metadata_changed"])
            self.assertEqual(len(database.list_videos()), 1)

    def test_existing_channel_group_can_be_changed_without_resyncing(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "test.db")
            channel_id = "UC1234567890123456789012"
            database.upsert_channel({"youtube_channel_id": channel_id, "channel_url": "https://youtube.com/channel/test", "uploads_playlist_id": "UU1234567890123456789012"})
            updated = database.set_channel_group(channel_id, "Hoạt hình thiếu nhi")
            self.assertEqual(updated["group_name"], "Hoạt hình thiếu nhi")

    def test_analysis_queue_claims_and_requeues_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
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
                    "youtube_video_id": "video-queue-1",
                    "youtube_channel_id": "UC1234567890123456789012",
                    "video_url": "https://www.youtube.com/watch?v=video-queue-1",
                    "title": "Queued video",
                    "description": "Description",
                    "metadata_hash": "hash-queue-1",
                    "raw_payload": {},
                }
            )

            jobs = database.queue_analysis_jobs(["video-queue-1"])
            self.assertEqual(len(jobs), 1)
            claimed = database.claim_analysis_job(jobs[0]["job_id"])
            self.assertEqual(claimed["status"], "running")
            self.assertEqual(database.requeue_interrupted_analysis_jobs(), 1)
            self.assertEqual(database.list_queued_analysis_job_ids(), [jobs[0]["job_id"]])

            claimed_again = database.claim_analysis_job(jobs[0]["job_id"])
            self.assertEqual(claimed_again["status"], "running")
            database.finish_analysis_job(jobs[0]["job_id"], "completed")
            self.assertEqual(database.analysis_queue_status()["completed"], 1)

    def test_transcript_jobs_do_not_disturb_metadata_analysis_status(self):
        with tempfile.TemporaryDirectory() as directory:
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
                    "youtube_video_id": "video-mixed-1",
                    "youtube_channel_id": "UC1234567890123456789012",
                    "video_url": "https://www.youtube.com/watch?v=video-mixed-1",
                    "title": "Mixed pipeline video",
                    "description": "Description",
                    "metadata_hash": "hash-mixed-1",
                    "raw_payload": {},
                }
            )
            database.save_video_analysis("video-mixed-1", {"topic": "x"})
            self.assertEqual(database.get_video("video-mixed-1")["analysis_status"], "completed")

            jobs = database.queue_analysis_jobs(
                ["video-mixed-1"], analysis_type="transcript", provider="faster_whisper"
            )
            self.assertEqual(len(jobs), 1)
            self.assertEqual(database.get_video("video-mixed-1")["analysis_status"], "completed")

            claimed = database.claim_analysis_job(jobs[0]["job_id"])
            self.assertEqual(claimed["analysis_type"], "transcript")
            self.assertEqual(database.get_video("video-mixed-1")["analysis_status"], "completed")

            self.assertEqual(
                database.requeue_interrupted_analysis_jobs(analysis_type="transcript"), 1
            )
            self.assertEqual(database.get_video("video-mixed-1")["analysis_status"], "completed")
            self.assertEqual(
                database.list_queued_analysis_job_ids(analysis_type="transcript"),
                [jobs[0]["job_id"]],
            )
            self.assertEqual(database.list_queued_analysis_job_ids(analysis_type="metadata"), [])

    def test_writer_analysis_does_not_disturb_metadata_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
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
                    "youtube_video_id": "video-writer-1",
                    "youtube_channel_id": "UC1234567890123456789012",
                    "video_url": "https://www.youtube.com/watch?v=video-writer-1",
                    "title": "Writer video",
                    "description": "Description",
                    "metadata_hash": "hash-writer-1",
                    "raw_payload": {},
                }
            )

            # Saving a writer result before metadata analysis must not mark
            # analysis_status as completed — that column tracks metadata only.
            database.save_video_analysis(
                "video-writer-1", {"summary": "x"}, analysis_type="writer", provider="anthropic_claude"
            )
            self.assertEqual(database.get_video("video-writer-1")["analysis_status"], "pending")
            self.assertIsNone(database.get_video_analysis("video-writer-1", analysis_type="metadata"))
            self.assertEqual(
                database.get_video_analysis("video-writer-1", analysis_type="writer")["analysis_type"],
                "writer",
            )

            database.save_video_analysis(
                "video-writer-1", {"topic": "y"}, analysis_type="metadata", provider="local_metadata"
            )
            self.assertEqual(database.get_video("video-writer-1")["analysis_status"], "completed")
            self.assertEqual(
                database.get_video_analysis("video-writer-1", analysis_type="metadata")["analysis_type"],
                "metadata",
            )
            # Latest overall (no filter) is the most recently saved row — metadata.
            self.assertEqual(database.get_video_analysis("video-writer-1")["analysis_type"], "metadata")

    def test_production_project_tracks_video_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
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
                    "youtube_video_id": "video-project-1",
                    "youtube_channel_id": "UC1234567890123456789012",
                    "video_url": "https://www.youtube.com/watch?v=video-project-1",
                    "title": "Project source video",
                    "description": "Description",
                    "metadata_hash": "hash-project-1",
                    "raw_payload": {},
                }
            )
            database.save_transcript("video-project-1", "hello world")
            database.save_video_analysis(
                "video-project-1", {"summary": "x"}, analysis_type="writer", provider="openai_gpt"
            )

            project = database.create_production_project("video-project-1")
            self.assertIsNotNone(project)
            self.assertEqual(project["status"], "draft")
            self.assertTrue(project["has_transcript"])
            self.assertTrue(project["has_writer_content"])

            same_project = database.create_production_project("video-project-1")
            self.assertEqual(same_project["id"], project["id"])
            self.assertEqual(len(database.list_production_projects()), 1)

            updated = database.update_production_project(
                project["id"], status="review", notes="ready for review"
            )
            self.assertEqual(updated["status"], "review")
            self.assertEqual(updated["notes"], "ready for review")
            self.assertEqual(database.summary()["production_projects"], 1)

            bundle = database.get_production_project_bundle(project["id"], transcript_text_limit=5)
            self.assertEqual(bundle["project"]["id"], project["id"])
            self.assertEqual(bundle["source_video"]["youtube_video_id"], "video-project-1")
            self.assertTrue(bundle["readiness"]["has_transcript"])
            self.assertTrue(bundle["readiness"]["has_writer_content"])
            self.assertEqual(bundle["latest_transcript"]["content_text"], "hello")
            self.assertTrue(bundle["latest_transcript"]["content_text_truncated"])
            self.assertIn("metadata", " ".join(bundle["next_actions"]))

            script = database.create_project_script(
                project["id"],
                script_title="Draft script",
                hook="Hook",
                intro="Intro",
                main_content="Body",
                cta="CTA",
            )
            self.assertEqual(script["version"], 1)
            self.assertEqual(script["status"], "draft")
            self.assertEqual(database.get_latest_project_script(project["id"])["id"], script["id"])
            self.assertEqual(database.get_production_project(project["id"])["status"], "script")

            updated_script = database.update_project_script(script["id"], status="review")
            self.assertEqual(updated_script["status"], "review")

            second_script = database.create_project_script(project["id"], script_title="Second draft")
            self.assertEqual(second_script["version"], 2)
            self.assertEqual(len(database.list_project_scripts(project["id"])), 2)

            approved = database.approve_project_script(second_script["id"])
            self.assertEqual(approved["status"], "approved")
            self.assertEqual(database.get_production_project(project["id"])["status"], "approved")
            self.assertTrue(database.get_production_project_bundle(project["id"])["readiness"]["script_approved"])

            shots = database.create_project_shots(
                project["id"],
                second_script["id"],
                [
                    {
                        "shot_index": 1,
                        "section": "hook",
                        "narration": "Hook narration",
                        "visual_prompt": "Hook prompt",
                        "asset_type": "talking_head",
                        "duration_seconds": 8,
                    },
                    {
                        "shot_index": 2,
                        "section": "main",
                        "narration": "Main narration",
                        "visual_prompt": "Main prompt",
                        "asset_type": "broll",
                        "duration_seconds": 12,
                    },
                ],
            )
            self.assertEqual(len(shots), 2)
            self.assertEqual(shots[0]["status"], "planned")
            self.assertEqual(
                len(database.create_project_shots(project["id"], second_script["id"], [], force=False)),
                2,
            )

            updated_shot = database.update_project_shot(
                shots[0]["id"], visual_prompt="Updated prompt", status="ready"
            )
            self.assertEqual(updated_shot["visual_prompt"], "Updated prompt")
            self.assertEqual(updated_shot["status"], "ready")
            self.assertTrue(database.get_production_project_bundle(project["id"])["readiness"]["has_shot_plan"])

            timeline = database.create_project_timeline(
                project["id"],
                second_script["id"],
                [
                    {
                        "segment_index": 1,
                        "shot_id": shots[0]["id"],
                        "section": "hook",
                        "voice_text": "Hook voice",
                        "subtitle_text": "Hook subtitle",
                        "visual_prompt": "Hook prompt",
                        "asset_type": "talking_head",
                        "duration_seconds": 8,
                    },
                    {
                        "segment_index": 2,
                        "shot_id": shots[1]["id"],
                        "section": "main",
                        "voice_text": "Main voice",
                        "subtitle_text": "Main subtitle",
                        "visual_prompt": "Main prompt",
                        "asset_type": "broll",
                        "duration_seconds": 12,
                    },
                ],
            )
            self.assertEqual(len(timeline), 2)
            self.assertEqual((timeline[0]["start_seconds"], timeline[0]["end_seconds"]), (0, 8))
            self.assertEqual((timeline[1]["start_seconds"], timeline[1]["end_seconds"]), (8, 20))
            updated_segment = database.update_project_timeline_segment(
                timeline[0]["id"], duration_seconds=10, status="voice_ready", audio_path="voice.wav"
            )
            self.assertEqual(updated_segment["status"], "voice_ready")
            self.assertEqual(updated_segment["audio_path"], "voice.wav")
            refreshed_timeline = database.list_project_timeline(project["id"], script_id=second_script["id"])
            self.assertEqual((refreshed_timeline[1]["start_seconds"], refreshed_timeline[1]["end_seconds"]), (10, 22))
            bundle = database.get_production_project_bundle(project["id"])
            self.assertTrue(bundle["readiness"]["has_timeline"])
            self.assertEqual(len(bundle["latest_timeline"]), 2)

            asset = database.create_project_asset(
                project["id"],
                "audio",
                "voice.wav",
                "F:/assets/voice.wav",
                mime_type="audio/wav",
                file_size=1234,
                sha256="abc123",
            )
            self.assertEqual(asset["asset_type"], "audio")
            self.assertEqual(len(database.list_project_assets(project["id"])), 1)
            database.update_project_asset_analysis(asset["id"], "completed")
            transcript = database.save_asset_transcript(asset["id"], "local asset transcript")
            self.assertEqual(transcript["word_count"], 3)
            self.assertTrue(database.get_project_asset(asset["id"])["has_transcript"])
            attached = database.attach_asset_to_timeline_segment(timeline[0]["id"], asset["id"])
            self.assertEqual(attached["segment"]["audio_path"], "F:/assets/voice.wav")
            self.assertTrue(database.get_production_project_bundle(project["id"])["readiness"]["has_assets"])

    def test_storyboard_cards_can_be_added_duplicated_reordered_and_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
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
                    "youtube_video_id": "video-storyboard-1",
                    "youtube_channel_id": "UC1234567890123456789012",
                    "video_url": "https://www.youtube.com/watch?v=video-storyboard-1",
                    "title": "Storyboard source",
                    "description": "Description",
                    "metadata_hash": "hash-storyboard-1",
                    "raw_payload": {},
                }
            )
            project = database.create_production_project("video-storyboard-1")
            old_script = database.create_project_script(project["id"], script_title="Old script")
            database.create_project_shot(project["id"], old_script["id"], narration="Old scene")
            script = database.create_project_script(project["id"], script_title="Current script")
            first = database.create_project_shot(
                project["id"], script["id"], section="hook", narration="First scene"
            )
            second = database.create_project_shot(
                project["id"], script["id"], section="main", narration="Second scene"
            )

            duplicate = database.duplicate_project_shot(first["id"])
            current = database.list_project_shots(project["id"], script_id=script["id"])
            self.assertEqual([item["shot_index"] for item in current], [1, 2, 3])
            self.assertEqual([item["narration"] for item in current], ["First scene", "First scene", "Second scene"])
            self.assertEqual(duplicate["status"], "planned")

            added = database.create_project_shot(project["id"], script["id"], narration="New scene")
            reordered = database.reorder_project_shots(
                project["id"], [added["id"], second["id"], duplicate["id"], first["id"]], script_id=script["id"]
            )
            self.assertEqual([item["shot_index"] for item in reordered], [1, 2, 3, 4])
            self.assertEqual(reordered[0]["narration"], "New scene")
            self.assertEqual(
                [item["narration"] for item in database.list_project_shots(project["id"], script_id=old_script["id"])],
                ["Old scene"],
            )

            self.assertTrue(database.delete_project_shot(duplicate["id"]))
            after_delete = database.list_project_shots(project["id"], script_id=script["id"])
            self.assertEqual([item["shot_index"] for item in after_delete], [1, 2, 3])

    def test_project_thumbnail_selection_keeps_provider_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "test.db")
            database.upsert_channel({"youtube_channel_id": "UC1234567890123456789012", "channel_url": "https://youtube.com/channel/test", "uploads_playlist_id": "UU1234567890123456789012"})
            database.upsert_video({"youtube_video_id": "video-thumb-1", "youtube_channel_id": "UC1234567890123456789012", "video_url": "https://youtube.com/watch?v=video-thumb-1", "metadata_hash": "thumb-hash", "raw_payload": {}})
            project = database.create_production_project("video-thumb-1")
            first_asset = database.create_project_asset(project["id"], "image", "first.jpg", "F:/thumbs/first.jpg")
            second_asset = database.create_project_asset(project["id"], "image", "second.jpg", "F:/thumbs/second.jpg")
            first = database.create_project_thumbnail(project["id"], first_asset["id"], "ffmpeg_frame", "ffmpeg", "First prompt", 11)
            second = database.create_project_thumbnail(project["id"], second_asset["id"], "ffmpeg_frame", "ffmpeg", "Second prompt", 12)
            selected = database.select_project_thumbnail(second["id"])
            self.assertEqual(selected["seed"], 12)
            self.assertEqual(selected["prompt"], "Second prompt")
            thumbnails = database.list_project_thumbnails(project["id"])
            self.assertTrue(thumbnails[0]["selected"])
            self.assertFalse(next(item for item in thumbnails if item["id"] == first["id"])["selected"])
            self.assertTrue(database.get_production_project_bundle(project["id"])["readiness"]["has_thumbnail"])

    def test_managed_channel_preset_is_applied_to_new_and_existing_projects(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "test.db")
            database.upsert_channel({"youtube_channel_id": "UC1234567890123456789012", "channel_url": "https://youtube.com/channel/test", "uploads_playlist_id": "UU1234567890123456789012"})
            database.upsert_video({"youtube_video_id": "video-preset-1", "youtube_channel_id": "UC1234567890123456789012", "video_url": "https://youtube.com/watch?v=video-preset-1", "metadata_hash": "preset-hash", "raw_payload": {}})
            channel = database.create_managed_channel(
                "Shorts English",
                "https://youtube.com/@mychannel",
                output_profile="youtube_shorts",
                language="en",
                default_voice_provider="edge_tts",
                default_voice_model="en-US-AriaNeural",
                default_subtitle_provider="faster_whisper_local",
                default_subtitle_model="small",
                default_transition_style="none",
            )
            project = database.create_production_project("video-preset-1", managed_channel_id=channel["id"])
            initial = database.get_project_render_settings(project["id"])
            self.assertEqual(initial["output_profile"], "youtube_shorts")
            self.assertEqual(initial["voice_model"], "en-US-AriaNeural")
            self.assertEqual(initial["subtitle_provider"], "faster_whisper_local")
            self.assertEqual(initial["publish_language"], "en")
            database.update_managed_channel(channel["id"], default_voice_model="en-US-GuyNeural", default_transition_style="fade")
            applied = database.apply_managed_channel_preset(project["id"])
            self.assertEqual(applied["voice_model"], "en-US-GuyNeural")
            self.assertEqual(applied["transition_style"], "fade")

    def test_publication_keeps_platform_profile_and_manual_delivery_state(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "test.db")
            source_channel = "UC1234567890123456789012"
            database.upsert_channel({"youtube_channel_id": source_channel, "channel_url": "https://youtube.com/channel/test", "uploads_playlist_id": "UU1234567890123456789012"})
            database.upsert_video({"youtube_video_id": "video-publish-facebook", "youtube_channel_id": source_channel, "video_url": "https://youtube.com/watch?v=video-publish-facebook", "metadata_hash": "publish-facebook", "raw_payload": {}})
            destination = database.create_managed_channel(
                "Facebook Reels chính", "https://facebook.com/my-page",
                platform="facebook", output_profile="facebook_reels",
            )
            project = database.create_production_project("video-publish-facebook", managed_channel_id=destination["id"])
            publication = database.create_project_publication(
                project["id"], "F:/exports/reel.mp4", "Bản Reel",
                managed_channel_id=destination["id"], platform="facebook",
                output_profile="facebook_reels", video_variant="short", status="ready_manual",
            )

            self.assertEqual(destination["platform"], "facebook")
            self.assertEqual(publication["platform"], "facebook")
            self.assertEqual(publication["output_profile"], "facebook_reels")
            self.assertEqual(publication["video_variant"], "short")
            self.assertEqual(publication["status"], "ready_manual")

    def test_sqlite_backup_is_a_readable_consistent_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "source.db")
            database.upsert_channel({"youtube_channel_id": "UC1234567890123456789012", "channel_url": "https://youtube.com/channel/test", "uploads_playlist_id": "UU1234567890123456789012"})
            backup = database.backup_to(root / "backups" / "snapshot.db")
            restored = sqlite3.connect(backup)
            try:
                row = restored.execute("SELECT youtube_channel_id FROM channels WHERE youtube_channel_id = ?", ("UC1234567890123456789012",)).fetchone()
            finally:
                restored.close()
            self.assertTrue(backup.is_file())
            self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
