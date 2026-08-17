import unittest

from youtube_monitor.script_builder import build_script_draft, script_to_markdown


class ScriptBuilderTests(unittest.TestCase):
    def test_build_script_draft_prefers_writer_content(self):
        bundle = {
            "project": {"title": "Project title"},
            "source_video": {"title": "Source title"},
            "metadata_analysis": {"result": {"hook": "Metadata hook"}},
            "writer_content": {
                "result": {
                    "summary": "Writer summary",
                    "new_titles": ["New title"],
                    "script_outline": ["Point A", "Point B"],
                    "cta": "Subscribe now",
                }
            },
        }
        draft = build_script_draft(bundle)
        self.assertEqual(draft["script_title"], "New title")
        self.assertEqual(draft["hook"], "Metadata hook")
        self.assertEqual(draft["intro"], "Writer summary")
        self.assertIn("1. Point A", draft["main_content"])
        self.assertEqual(draft["cta"], "Subscribe now")

    def test_script_to_markdown_exports_sections(self):
        markdown = script_to_markdown(
            {
                "id": 10,
                "project_id": 2,
                "version": 3,
                "status": "draft",
                "script_title": "My Script",
                "hook": "Hook",
                "intro": "Intro",
                "main_content": "Body",
                "cta": "CTA",
            }
        )
        self.assertIn("# My Script", markdown)
        self.assertIn("## Hook", markdown)
        self.assertIn("## Nội dung chính", markdown)
        self.assertIn("CTA", markdown)

    def test_production_script_uses_all_storyboard_narration_not_short_summary(self):
        bundle = {
            "project": {"title": "Project"},
            "writer_content": {"result": {
                "new_script": {"script_title": "Summary", "hook": "Short", "intro": "", "main_content": "Short", "cta": ""},
                "scene_blueprints": [
                    {"order": 1, "section": "hook", "narration": "Narration scene one"},
                    {"order": 2, "section": "intro", "narration": "Narration scene two"},
                    {"order": 3, "section": "main", "narration": "Narration scene three is detailed"},
                    {"order": 4, "section": "cta", "narration": "Narration scene four"},
                ],
            }},
        }
        draft = build_script_draft(bundle)
        combined = " ".join(draft.values())
        self.assertIn("Narration scene one", combined)
        self.assertIn("Narration scene three is detailed", combined)
        self.assertIn("Narration scene four", combined)

    def test_build_script_draft_uses_original_script_from_remake_writer(self):
        bundle = {
            "project": {"title": "Project"},
            "writer_content": {"result": {"new_script": {
                "script_title": "Câu chuyện mèo mới", "hook": "Hook mới", "intro": "Mở đầu mới",
                "main_content": "Diễn biến mới", "cta": "CTA mới",
            }}},
        }
        draft = build_script_draft(bundle)
        self.assertEqual(draft["script_title"], "Câu chuyện mèo mới")
        self.assertEqual(draft["main_content"], "Diễn biến mới")


if __name__ == "__main__":
    unittest.main()
