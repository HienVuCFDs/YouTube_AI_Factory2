import unittest

from youtube_monitor.timeline_builder import build_timeline, timeline_to_manifest, timeline_to_markdown


class TimelineBuilderTests(unittest.TestCase):
    def test_build_timeline_assigns_contiguous_time_ranges(self):
        timeline = build_timeline(
            {"id": 2, "title": "Project"},
            {"id": 5, "script_title": "Script"},
            [
                {
                    "id": 11,
                    "section": "hook",
                    "narration": "Hook",
                    "visual_prompt": "Hook prompt",
                    "asset_type": "talking_head",
                    "duration_seconds": 8,
                },
                {
                    "id": 12,
                    "section": "main",
                    "narration": "Main",
                    "visual_prompt": "Main prompt",
                    "asset_type": "broll",
                    "duration_seconds": 12,
                },
            ],
        )
        self.assertEqual([(item["start_seconds"], item["end_seconds"]) for item in timeline], [(0, 8), (8, 20)])
        self.assertEqual(timeline[1]["shot_id"], 12)

    def test_manifest_and_markdown_include_duration_and_paths(self):
        timeline = [
            {
                "segment_index": 1,
                "section": "hook",
                "duration_seconds": 8,
                "start_seconds": 0,
                "end_seconds": 8,
                "status": "planned",
                "shot_id": 11,
                "voice_text": "Hook",
                "visual_prompt": "Prompt",
                "asset_type": "talking_head",
                "audio_path": "",
                "visual_path": "",
            }
        ]
        manifest = timeline_to_manifest({"id": 2, "title": "Project"}, {"id": 5}, timeline)
        self.assertEqual(manifest["total_duration_seconds"], 8)
        self.assertEqual(manifest["manifest_version"], "youtube_ai_factory.timeline.v1")
        markdown = timeline_to_markdown({"id": 2, "title": "Project"}, {"id": 5}, timeline)
        self.assertIn("# Timeline: Project", markdown)
        self.assertIn("### Voiceover / subtitle", markdown)


if __name__ == "__main__":
    unittest.main()
