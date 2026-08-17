import unittest

from youtube_monitor.shot_planner import build_shot_plan, shots_to_markdown


class ShotPlannerTests(unittest.TestCase):
    def test_build_shot_plan_splits_script_sections(self):
        project = {"id": 2, "title": "Project"}
        script = {
            "id": 5,
            "script_title": "Script",
            "hook": "Hook line",
            "intro": "Intro line",
            "main_content": "1. First point\n2. Second point",
            "cta": "CTA line",
        }
        shots = build_shot_plan(project, script)
        self.assertEqual([shot["section"] for shot in shots], ["hook", "intro", "main", "main", "cta"])
        self.assertEqual(shots[0]["asset_type"], "talking_head")
        self.assertEqual(shots[2]["asset_type"], "broll")
        self.assertIn("First point", shots[2]["narration"])
        self.assertGreaterEqual(shots[0]["duration_seconds"], 6)

    def test_shots_to_markdown_exports_prompts(self):
        markdown = shots_to_markdown(
            {"id": 2, "title": "Project"},
            {"id": 5},
            [
                {
                    "shot_index": 1,
                    "section": "hook",
                    "asset_type": "talking_head",
                    "duration_seconds": 8,
                    "status": "planned",
                    "narration": "Hook",
                    "visual_prompt": "Prompt",
                }
            ],
        )
        self.assertIn("# Shot list: Project", markdown)
        self.assertIn("## Shot 1", markdown)
        self.assertIn("### Visual prompt", markdown)

    def test_build_shot_plan_prefers_original_ai_scene_blueprints(self):
        shots = build_shot_plan(
            {"id": 2, "title": "Mèo"},
            {"hook": "H", "intro": "I", "main_content": "B", "cta": "C"},
            {"scene_blueprints": [{
                "order": 2, "section": "main", "narration": "Chú mèo bước vào khu vườn.",
                "visual_prompt": "original AI scene, orange cat in a sunlit garden, slow dolly", "asset_type": "ai_scene", "duration_seconds": 7,
            }]},
        )
        self.assertEqual(len(shots), 1)
        self.assertEqual(shots[0]["asset_type"], "ai_scene")
        self.assertIn("orange cat", shots[0]["visual_prompt"])


if __name__ == "__main__":
    unittest.main()
