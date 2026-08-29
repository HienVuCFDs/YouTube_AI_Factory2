from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from youtube_monitor.main import (
    BatchSceneGenerationRequest,
    CreateSceneGenerationRequest,
    _REVIEW_SCENE_SCHEMA,
    _agent_runtime_available,
    _call_orchestrator_json,
    app,
    database,
)


class MainApiTests(unittest.TestCase):
    """HTTP-level smoke tests for the FastAPI app.

    Uses `TestClient` as a context manager so the real `lifespan` runs
    (starts/stops the background job-queue threads) against an isolated
    temp database configured in conftest.py, never the production DB.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._client_cm = TestClient(app)
        cls.client = cls._client_cm.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)

    def test_root_serves_html_shell(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_health_reports_ok(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertIn("whisper_device", body)

    def test_projects_list_answers_with_a_list(self) -> None:
        """The whole suite shares one temp database, so this cannot assume it
        is empty: whether a project exists here depends only on which test
        files happened to run first."""
        response = self.client.get("/api/projects")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_unknown_project_returns_404_with_vietnamese_detail(self) -> None:
        response = self.client.get("/api/projects/999999")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Không tìm thấy dự án")

    def test_videos_and_channels_list_endpoints(self) -> None:
        for path in ("/api/videos", "/api/channels"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIsInstance(response.json(), list)

    def test_model_catalog_lists_known_providers(self) -> None:
        response = self.client.get("/api/model-catalog")
        self.assertEqual(response.status_code, 200)
        providers = {entry["provider"] for entry in response.json()}
        self.assertIn("voxcpm", providers)
        self.assertIn("ffmpeg_builtin", providers)
        self.assertIn("gflow_cli", providers)

    def test_tool_status_returns_a_list(self) -> None:
        response = self.client.get("/api/tool-status")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_provider_gateway_catalog_exposes_routing_metadata(self) -> None:
        response = self.client.get("/api/providers/catalog")
        self.assertEqual(response.status_code, 200)
        providers = response.json()["providers"]
        self.assertGreaterEqual(len(providers), 10)
        flow = next(item for item in providers if item["key"] == "flow_veo")
        self.assertIn("scene.video", flow["capabilities"])
        self.assertEqual(flow["billing_mode"], "subscription")
        self.assertIn("runtime", flow)

    def test_usage_limit_can_be_cleared_to_probe_a_recovered_account(self) -> None:
        database.record_provider_usage_limit("codex_cli", "weekly usage limit", None)

        response = self.client.post("/api/usage-limits/codex_cli/clear")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "retry_enabled")
        self.assertIsNotNone(database.get_provider_usage_limit("codex_cli")["cleared_at"])

    def test_unknown_usage_limit_provider_is_rejected(self) -> None:
        response = self.client.post("/api/usage-limits/not-real/clear")

        self.assertEqual(response.status_code, 404)

    def test_unknown_reset_limit_is_probed_only_after_cooldown(self) -> None:
        database.record_provider_usage_limit("codex_cli", "weekly usage limit", None)
        old = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
        with database._connect() as connection:
            connection.execute(
                "UPDATE provider_usage_limits SET last_failure_at = ? WHERE provider = ?",
                (old, "codex_cli"),
            )

        with patch("youtube_monitor.main.codex_cli_status", return_value={"logged_in": True}):
            self.assertTrue(_agent_runtime_available("codex_cli"))

        database.record_provider_usage_limit("codex_cli", "weekly usage limit", None)
        with patch("youtube_monitor.main.codex_cli_status") as status:
            self.assertFalse(_agent_runtime_available("codex_cli"))
            status.assert_not_called()

    def test_high_level_pipeline_creates_project_and_durable_research_task(self) -> None:
        with patch("youtube_monitor.main.agent_pipeline.start") as start:
            start.return_value = {
                "id": "task-research-1",
                "role": "research",
                "status": "queued",
            }
            response = self.client.post(
                "/api/automation/pipelines",
                json={
                    "goal": "Tao video giai thich cach cac AI hop tac voi nhau",
                    "title": "He thong da AI",
                    "auto_generate_media": False,
                    "auto_render": False,
                },
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["project"]["title"], "He thong da AI")
        start.assert_called_once_with(
            body["project"]["id"],
            "Tao video giai thich cach cac AI hop tac voi nhau",
            auto_generate_media=False,
            auto_render=False,
        )
        status = self.client.get(f"/api/automation/projects/{body['project']['id']}")
        self.assertEqual(status.status_code, 200)
        self.assertTrue(any(item["event_type"] == "project.created" for item in status.json()["events"]))

    def test_integrations_never_leak_api_key_values(self) -> None:
        response = self.client.get("/api/integrations")
        self.assertEqual(response.status_code, 200)
        for item in response.json():
            self.assertNotIn("api_key", item)
            self.assertNotIn("secret", item)
        gflow = next(item for item in response.json() if item["key"] == "gflow_cli")
        self.assertEqual(gflow["connection"], "cloud_subscription")
        self.assertIn("installed", gflow)

    def test_browser_heartbeat_round_trip(self) -> None:
        response = self.client.post(
            "/api/browser/heartbeat",
            json={"client_id": "test-client-0001", "status": "online"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_save_integration_rejects_unknown_provider(self) -> None:
        response = self.client.post(
            "/api/integrations",
            json={"provider": "not_a_real_provider", "api_key": "x"},
        )
        self.assertEqual(response.status_code, 422)

    def test_prune_backups_requires_explicit_confirmation(self) -> None:
        response = self.client.post(
            "/api/maintenance/database-backups/prune",
            json={"keep": 14, "confirmed": False},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"], "Cần xác nhận trước khi dọn bản sao lưu cũ"
        )

    def test_browser_scene_job_next_rejects_unknown_provider(self) -> None:
        response = self.client.get("/api/browser-scene-jobs/next?provider=not_a_real_site")
        self.assertEqual(response.status_code, 400)

    def test_browser_scene_job_next_is_null_on_an_empty_queue(self) -> None:
        for provider in ("flow_veo", "meta_ai_video"):
            response = self.client.get(f"/api/browser-scene-jobs/next?provider={provider}")
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.json()["job"])

    def test_browser_scene_job_complete_404s_for_an_unknown_job(self) -> None:
        response = self.client.post("/api/browser-scene-jobs/999999/complete?asset_id=1")
        self.assertEqual(response.status_code, 404)

    def test_browser_scene_job_fail_404s_for_an_unknown_job(self) -> None:
        response = self.client.post("/api/browser-scene-jobs/999999/fail?error=boom")
        self.assertEqual(response.status_code, 404)

    def test_flow_video_requests_accept_the_real_eight_second_duration(self) -> None:
        single = CreateSceneGenerationRequest(
            timeline_segment_id=1,
            provider="flow_veo",
            prompt="Animate this exact storyboard frame",
            duration_seconds=8,
            reference_asset_id=1,
            requires_reference_image=True,
            confirmed=True,
        )
        batch = BatchSceneGenerationRequest(
            provider="flow_veo",
            duration_seconds=8,
            requires_reference_image=True,
            confirmed=True,
        )
        self.assertEqual(single.duration_seconds, 8)
        self.assertEqual(batch.duration_seconds, 8)

        cli = CreateSceneGenerationRequest(
            timeline_segment_id=1,
            provider="gflow_cli",
            prompt="Animate this exact storyboard frame",
            duration_seconds=8,
            reference_asset_id=1,
            requires_reference_image=True,
            confirmed=True,
        )
        self.assertEqual(cli.provider, "gflow_cli")

    def test_codex_scene_review_schema_is_strict(self) -> None:
        self.assertIs(_REVIEW_SCENE_SCHEMA["additionalProperties"], False)
        self.assertEqual(
            set(_REVIEW_SCENE_SCHEMA["required"]),
            set(_REVIEW_SCENE_SCHEMA["properties"]),
        )

    def test_auto_agent_assignment_uses_ready_stage_specialist(self) -> None:
        assignment = {
            "mode": "auto",
            "executor": "codex_cli",
            "allowed_agents": ["codex_cli", "claude_code_cli", "antigravity"],
            "fallback_agents": [],
            "reviewer": "auto",
        }
        with patch("youtube_monitor.main.settings.agent_assignment", return_value=assignment), patch(
            "youtube_monitor.main.codex_cli_status", return_value={"logged_in": True}
        ), patch(
            "youtube_monitor.main.claude_code_cli_status", return_value={"logged_in": True}
        ), patch(
            "youtube_monitor.main.antigravity_cli_status", return_value={"logged_in": True}
        ), patch(
            "youtube_monitor.main.call_antigravity_json", return_value={"prompt": "chosen"}
        ) as antigravity, patch("youtube_monitor.main.call_codex_json") as codex:
            result = _call_orchestrator_json(
                "system", "user", {"type": "object"}, stage="image_generation"
            )
        self.assertEqual(result["prompt"], "chosen")
        antigravity.assert_called_once()
        codex.assert_not_called()

    def test_image_to_video_rejects_a_missing_reference_before_creating_job(self) -> None:
        response = self.client.post(
            "/api/projects/999999/scene-jobs",
            json={
                "timeline_segment_id": 1,
                "provider": "flow_veo",
                "prompt": "Animate the existing frame",
                "duration_seconds": 8,
                "requires_reference_image": True,
                "confirmed": True,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("chưa có ảnh nguồn", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
