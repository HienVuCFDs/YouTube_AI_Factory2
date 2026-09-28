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
                "youtube_factory_get_next_task",
                "youtube_factory_complete_task",
                "youtube_factory_fail_task",
                "youtube_factory_get_project_context",
                "youtube_factory_get_source_package",
                "youtube_factory_get_project_edit_plan",
                "youtube_factory_plan_project_edit",
                "youtube_factory_update_project_edit_scene",
                "youtube_factory_approve_project_edit_plan",
                "youtube_factory_apply_project_edit_plan",
                "youtube_factory_get_storyboard_required_jobs",
                "youtube_factory_plan_scene_edit_beats",
                "youtube_factory_apply_scene_edit_beats",
                "youtube_factory_get_render_readiness",
                "youtube_factory_save_script",
                "youtube_factory_update_shot",
            }.issubset(names)
        )

    @patch.object(ai_desktop_mcp, "_factory_request")
    def test_astra_context_tools_use_compact_project_endpoints(self, request):
        request.side_effect = [
            {"context_version": "youtube_ai_factory.project_context.v1", "project": {"id": 7}},
            {"source_package_version": "youtube_ai_factory.source_package.v1", "project_id": 7},
        ]

        context = ai_desktop_mcp._call_tool("youtube_factory_get_project_context", {"project_id": 7})
        package = ai_desktop_mcp._call_tool("youtube_factory_get_source_package", {"project_id": 7})

        self.assertEqual(request.call_args_list[0].args[0], "/api/projects/7/astra-context")
        self.assertEqual(request.call_args_list[1].args[0], "/api/projects/7/source-package")
        self.assertEqual(json.loads(context["content"][0]["text"])["project"]["id"], 7)
        self.assertEqual(json.loads(package["content"][0]["text"])["project_id"], 7)

    @patch.object(ai_desktop_mcp, "_factory_request")
    def test_astra_edit_plan_tools_call_project_endpoints(self, request):
        request.side_effect = [
            {"status": "missing"},
            {"status": "draft"},
            {"status": "draft", "plan": {"id": 10}},
            {"status": "approved"},
            {"status": "ready"},
            {"status": "ok", "required_jobs": []},
            {"can_render": False},
        ]

        ai_desktop_mcp._call_tool("youtube_factory_get_project_edit_plan", {"project_id": 7})
        ai_desktop_mcp._call_tool("youtube_factory_plan_project_edit", {"project_id": 7, "motion_policy": "gif_only"})
        ai_desktop_mcp._call_tool("youtube_factory_update_project_edit_scene", {"project_id": 7, "segment_id": 22, "changes": {"effect": "static"}})
        ai_desktop_mcp._call_tool("youtube_factory_approve_project_edit_plan", {"project_id": 7})
        ai_desktop_mcp._call_tool("youtube_factory_apply_project_edit_plan", {"project_id": 7})
        ai_desktop_mcp._call_tool("youtube_factory_get_storyboard_required_jobs", {"project_id": 7})
        ai_desktop_mcp._call_tool("youtube_factory_get_render_readiness", {"project_id": 7})

        self.assertEqual(request.call_args_list[0].args[0], "/api/projects/7/edit-plan")
        self.assertEqual(request.call_args_list[1].args[0], "/api/projects/7/edit-plan?motion_policy=gif_only")
        self.assertEqual(request.call_args_list[1].kwargs["method"], "POST")
        self.assertEqual(request.call_args_list[2].args[0], "/api/projects/7/edit-plan/scenes/22")
        self.assertEqual(request.call_args_list[2].kwargs["method"], "PATCH")
        self.assertEqual(json.loads(request.call_args_list[2].kwargs["data"].decode("utf-8"))["effect"], "static")
        self.assertEqual(request.call_args_list[3].args[0], "/api/projects/7/edit-plan/approve")
        self.assertEqual(request.call_args_list[4].args[0], "/api/projects/7/edit-plan/apply")
        self.assertEqual(request.call_args_list[5].args[0], "/api/projects/7/storyboard/required-jobs")
        self.assertEqual(request.call_args_list[6].args[0], "/api/projects/7/render-readiness")

    @patch.object(ai_desktop_mcp, "_factory_request")
    def test_astra_scene_edit_beat_tools_call_timeline_endpoints(self, request):
        def fake(path, method="GET", data=None, headers=None, timeout=None):
            payload = json.loads(data.decode("utf-8")) if data else {}
            if path == "/api/providers/route":
                self.assertEqual(payload["capability"], "scene.image")
                return {"selected_provider": "gflow_image"}
            if path == "/api/timeline/22/edit-beats/plan":
                self.assertEqual(payload["max_beats"], 5)
                return {"status": "planned"}
            if path == "/api/timeline/22/edit-beats/apply":
                self.assertEqual(payload["image_provider"], "gflow_image")
                self.assertEqual(payload["ratio"], "720:1280")
                return {"status": "ready"}
            self.fail(f"Unexpected path: {path}")

        request.side_effect = fake

        ai_desktop_mcp._call_tool(
            "youtube_factory_plan_scene_edit_beats",
            {"project_id": 7, "segment_id": 22, "max_beats": 5},
        )
        ai_desktop_mcp._call_tool(
            "youtube_factory_apply_scene_edit_beats",
            {"project_id": 7, "segment_id": 22, "image_provider": "auto", "ratio": "720:1280", "confirmed": True},
        )

        self.assertEqual(request.call_count, 3)

    @patch.object(ai_desktop_mcp, "_factory_request")
    def test_generate_image_routes_provider_then_queues_job(self, request):
        def fake(path, method="GET", data=None, headers=None, timeout=None):
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

    @patch.object(ai_desktop_mcp, "_factory_request")
    def test_chatgpt_task_claim_and_completion_use_local_api(self, request):
        request.side_effect = [
            {"status": "claimed", "task": {"id": "task-1", "role": "script"}},
            {"status": "completed", "task": {"id": "task-1", "status": "completed"}},
        ]
        claimed = ai_desktop_mcp._call_tool("youtube_factory_get_next_task", {})
        completed = ai_desktop_mcp._call_tool(
            "youtube_factory_complete_task",
            {"task_id": "task-1", "output": {"script_id": 42}},
        )
        self.assertEqual(json.loads(claimed["content"][0]["text"])["task"]["role"], "script")
        self.assertEqual(json.loads(completed["content"][0]["text"])["status"], "completed")
        # The queue is per chat agent now - the same bridge serves the ChatGPT
        # app and the Claude app, told apart by YOUTUBE_CHAT_AGENT - so the
        # path carries which one is claiming.
        agent = ai_desktop_mcp.CHAT_AGENT
        self.assertEqual(request.call_args_list[0].args[0], f"/api/chat-agents/{agent}/tasks/next")
        self.assertEqual(
            request.call_args_list[1].args[0], f"/api/chat-agents/{agent}/tasks/task-1/complete",
        )

    @patch.object(ai_desktop_mcp, "_factory_request")
    def test_save_script_preserves_chatgpt_text(self, request):
        request.return_value = {"status": "saved", "script": {"id": 17}}
        result = ai_desktop_mcp._call_tool(
            "youtube_factory_save_script",
            {"project_id": 3, "title": "Demo", "text": "Noi dung do ChatGPT viet", "language": "vi"},
        )
        payload = json.loads(request.call_args.kwargs["data"].decode("utf-8"))
        self.assertEqual(request.call_args.args[0], "/api/scripts/import")
        self.assertEqual(payload["project_id"], 3)
        self.assertEqual(payload["text"], "Noi dung do ChatGPT viet")
        self.assertEqual(json.loads(result["content"][0]["text"])["script"]["id"], 17)


if __name__ == "__main__":
    unittest.main()


class ConnectingIsAnnouncedOnConnectTests(unittest.TestCase):
    """The one screen that says whether the desktop app is reachable answered
    "not connected" while it was plainly attached, because the signal was only
    sent when the client happened to touch a tool."""

    def _handle(self, method: str):
        from unittest import mock

        from youtube_monitor import ai_desktop_mcp

        with mock.patch.object(ai_desktop_mcp, "_report_chat_contact") as announced:
            ai_desktop_mcp._handle({
                "jsonrpc": "2.0", "id": 1, "method": method,
                "params": {"protocolVersion": "2025-03-26"} if method == "initialize" else {},
            })
        return announced

    def test_initialize_reports_the_client_as_present(self) -> None:
        self._handle("initialize").assert_called_once()

    def test_listing_tools_still_reports_it(self) -> None:
        self._handle("tools/list").assert_called_once()
