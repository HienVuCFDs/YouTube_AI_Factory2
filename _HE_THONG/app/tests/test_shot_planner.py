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

def test_a_rewritten_script_is_spoken_in_its_own_words() -> None:
    """A new script was being narrated with the first draft's sentences.

    The writer's scene blueprints are attached to the video, not to a script,
    and build_shot_plan returned them whenever they existed. So a rewrite
    produced the same shot list, the same timeline and the same voice — the
    user asked for a new script and heard the old one.
    """
    blueprints = {"scene_blueprints": [
        {"narration": "Cau tu ban nhap dau tien", "section": "main", "duration_seconds": 6},
    ]}
    rewritten = {
        "version": 2, "script_title": "Ban viet lai",
        "hook": "", "intro": "", "main_content": "Cau moi cua ban viet lai", "cta": "",
    }
    shots = build_shot_plan({"title": "p"}, rewritten, writer_content=blueprints)
    assert "viet lai" in shots[0]["narration"]


def test_the_first_draft_still_uses_the_blueprints_it_came_from() -> None:
    blueprints = {"scene_blueprints": [
        {"narration": "Cau tu blueprint", "section": "main", "duration_seconds": 6},
    ]}
    first = {
        "version": 1, "script_title": "Ban dau",
        "hook": "", "intro": "", "main_content": "Chu cua kich ban", "cta": "",
    }
    shots = build_shot_plan({"title": "p"}, first, writer_content=blueprints)
    assert shots[0]["narration"] == "Cau tu blueprint"


def test_a_rewrite_with_no_words_of_its_own_keeps_the_blueprints() -> None:
    """An empty rewrite must not leave the project with no narration at all."""
    blueprints = {"scene_blueprints": [
        {"narration": "Cau tu blueprint", "section": "main", "duration_seconds": 6},
    ]}
    empty = {"version": 3, "script_title": "Rong", "hook": "", "intro": "", "main_content": "", "cta": ""}
    shots = build_shot_plan({"title": "p"}, empty, writer_content=blueprints)
    assert shots[0]["narration"] == "Cau tu blueprint"


def test_the_timeline_endpoint_says_whether_it_rebuilt() -> None:
    """Without force an existing timeline came back untouched and silent, so
    pressing the button after a rewrite looked like it had worked."""
    from youtube_monitor import main
    import inspect

    source = inspect.getsource(main.generate_project_timeline)
    assert '"rebuilt"' in source
    assert '"stale"' in source
    assert '"shot_count"' in source


def test_the_page_refuses_to_voice_a_stale_timeline() -> None:
    from pathlib import Path

    page = (
        Path(__file__).resolve().parent.parent
        / "youtube_monitor" / "templates" / "index.html"
    ).read_text(encoding="utf-8")
    assert "timelineResult?.stale" in page
    assert "force: true" in page
