from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from youtube_monitor import ai_desktop_mcp


class AiDesktopMcpTests(unittest.TestCase):
    def test_high_level_work_brief_tools_are_exposed(self):
        names = {item["name"] for item in ai_desktop_mcp._tool_definitions()}
        self.assertTrue(
            {
                "youtube_factory_create_project",
                "youtube_factory_start_pipeline",
                "youtube_factory_get_pipeline_status",
                "youtube_factory_list_events",
                "youtube_factory_list_providers",
                "youtube_factory_route_provider",
                "youtube_factory_generate_image",
                "youtube_factory_generate_gif",
                "youtube_factory_generate_video",
                "youtube_factory_approve_scene",
                "youtube_factory_build_timeline",
                "youtube_factory_generate_voice",
                "youtube_factory_render_video",
                "youtube_factory_get_render_status",
            }.issubset(names)
        )

    @patch.object(ai_desktop_mcp, "_factory_request")
    def test_generate_image_routes_provider_then_queues_job(self, request):
        def fake(path, method="GET", data=None, headers=None):
            payload = json.loads(data.decode("utf-8")) if data else {}
            if path == "/api/providers/route":
                self.assertEqual(payload["capability"], "scene.image")
                return {"selected_provider": "gflow_image"}
            self.assertEqual(path, "/api/projects/9/scene-jobs")
            self.assertEqual(payload["provider"], "gflow_image")
            self.assertTrue(payload["confirmed"])
            self.assertFalse(payload["motion_as_gif"])
            return {"status": "queued", "job": {"id": 31}}

        request.side_effect = fake
        result = ai_desktop_mcp._call_tool(
            "youtube_factory_generate_image",
            {
                "project_id": 9,
                "segment_id": 12,
                "prompt": "cinematic forest",
                "confirmed": True,
            },
        )
        text = json.loads(result["content"][0]["text"])
        self.assertEqual(text["job"]["id"], 31)
        self.assertEqual(request.call_count, 2)

    @patch.object(ai_desktop_mcp, "_factory_request")
    def test_video_requires_approved_reference_image(self, request):
        with self.assertRaisesRegex(ValueError, "reference_asset_id"):
            ai_desktop_mcp._call_tool(
                "youtube_factory_generate_video",
                {
                    "project_id": 9,
                    "segment_id": 12,
                    "prompt": "slow camera push",
                    "provider": "flow_veo",
                    "confirmed": True,
                },
            )
        request.assert_not_called()

    @patch.object(ai_desktop_mcp, "_factory_request")
    def test_pipeline_start_posts_durable_request(self, request):
        request.return_value = {"status": "queued", "task": {"id": "abc"}}
        result = ai_desktop_mcp._call_tool(
            "youtube_factory_start_pipeline",
            {"project_id": 7, "goal": "Tao video day du ve lich su AI"},
        )
        path, = request.call_args.args[:1]
        kwargs = request.call_args.kwargs
        payload = json.loads(kwargs["data"].decode("utf-8"))
        self.assertEqual(path, "/api/automation/pipelines")
        self.assertEqual(payload["project_id"], 7)
        self.assertEqual(payload["goal"], "Tao video day du ve lich su AI")
        self.assertEqual(json.loads(result["content"][0]["text"])["status"], "queued")


if __name__ == "__main__":
    unittest.main()
