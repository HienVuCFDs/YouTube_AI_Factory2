from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from youtube_monitor.gflow_bridge import (
    _classify_failure,
    _parse_json_output,
    create_gflow_project,
    generate_gflow_video,
)


class GFlowBridgeTests(unittest.TestCase):
    def test_parses_json_after_a_wrapper_log_line(self) -> None:
        payload = _parse_json_output('opening browser\n{"status":"ok","project_id":"abc"}\n')
        self.assertEqual(payload["project_id"], "abc")

    def test_quota_failure_is_not_retried(self) -> None:
        error = _classify_failure(1, {"error_message": "Insufficient credits"}, "")
        self.assertEqual(error.kind, "quota")
        self.assertFalse(error.retryable)

    def test_creates_a_named_project_with_the_selected_profile(self) -> None:
        with patch(
            "youtube_monitor.gflow_bridge.settings.gflow_config",
            return_value={"profile": "factory", "video_model": "", "path": "gflow.exe"},
        ), patch(
            "youtube_monitor.gflow_bridge.run_gflow_json",
            return_value={"status": "ok", "project_id": "flow-project-123"},
        ) as run:
            project_id = create_gflow_project("  My   Video  ")
        self.assertEqual(project_id, "flow-project-123")
        self.assertEqual(
            run.call_args.args[0],
            ["project", "create", "--name", "My Video", "--json", "--profile", "factory"],
        )

    def test_i2v_uses_existing_project_and_does_not_send_unsupported_duration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frame = root / "frame.png"
            frame.write_bytes(b"png")
            output = root / "scene.mp4"

            def fake_run(args, **_kwargs):
                output.write_bytes(b"mp4")
                self.assertEqual(args[:4], ["video", "i2v", "--initial-frame", str(frame)])
                self.assertIn("--project", args)
                self.assertIn("flow-project-123", args)
                self.assertIn("--aspect", args)
                self.assertIn("16:9", args)  # square scenes fall back to Flow landscape
                self.assertNotIn("--duration", args)
                return {"status": "ok", "succeeded": True, "local_path": str(output)}

            job = {
                "prompt": "Slow camera push in",
                "ratio": "1024:1024",
                "duration_seconds": 7,
                "requires_reference_image": True,
            }
            with patch(
                "youtube_monitor.gflow_bridge.settings.gflow_config",
                return_value={"profile": "default", "video_model": "veo-lite", "path": "gflow.exe"},
            ), patch("youtube_monitor.gflow_bridge.run_gflow_json", side_effect=fake_run):
                result = generate_gflow_video(
                    job,
                    frame,
                    output,
                    gflow_project_id="flow-project-123",
                )
            self.assertEqual(result, str(output))

    def test_omni_flash_maps_timeline_duration_to_supported_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "scene.mp4"

            def fake_run(args, **_kwargs):
                output.write_bytes(b"mp4")
                duration_index = args.index("--duration")
                self.assertEqual(args[duration_index + 1], "8")
                return {"status": "ok", "succeeded": True, "local_path": str(output)}

            with patch(
                "youtube_monitor.gflow_bridge.settings.gflow_config",
                return_value={"profile": "default", "video_model": "omni-flash", "path": "gflow.exe"},
            ), patch("youtube_monitor.gflow_bridge.run_gflow_json", side_effect=fake_run):
                generate_gflow_video(
                    {"prompt": "Orbit the subject", "duration_seconds": 7},
                    None,
                    output,
                )


if __name__ == "__main__":
    unittest.main()
