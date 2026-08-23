import unittest

from youtube_monitor.writer import AVAILABLE_WRITER_PROVIDERS, _build_prompt, _finalize


class WriterTests(unittest.TestCase):
    def test_build_prompt_includes_transcript_when_available(self):
        video = {"title": "Video gốc", "description": "Mô tả", "tags": ["a", "b"]}
        prompt = _build_prompt(video, "Nội dung transcript ở đây")
        self.assertIn("Video gốc", prompt)
        self.assertIn("Nội dung transcript ở đây", prompt)

    def test_build_prompt_notes_missing_transcript(self):
        video = {"title": "Video gốc", "description": "", "tags": []}
        prompt = _build_prompt(video, None)
        self.assertIn("Chưa có transcript", prompt)

    def test_finalize_maps_parsed_fields_with_defaults(self):
        video = {"title": "Video gốc"}
        parsed = {
            "summary": "Tóm tắt",
            "new_titles": ["A", "B"],
        }
        result = _finalize(video, "anthropic_claude", parsed, used_transcript=True)
        self.assertEqual(result["provider"], "anthropic_claude")
        self.assertEqual(result["source_type"], "transcript")
        self.assertEqual(result["summary"], "Tóm tắt")
        self.assertEqual(result["new_titles"], ["A", "B"])
        self.assertEqual(result["key_ideas"], [])
        self.assertEqual(result["hashtags"], [])

    def test_finalize_source_type_without_transcript(self):
        result = _finalize({"title": "X"}, "openai_gpt", {}, used_transcript=False)
        self.assertEqual(result["source_type"], "metadata")

    def test_codex_cli_is_a_supported_writer_provider(self):
        self.assertIn("codex_cli", AVAILABLE_WRITER_PROVIDERS)

    def test_build_prompt_carries_the_source_content_and_its_dialogue(self):
        """The brief used to pass abstract beats; the writer needs the source's
        own events and the characters' own words."""
        prompt = _build_prompt(
            {"title": "Chó", "description": "", "tags": []},
            "Lời kể nguồn",
            creative_direction="Giữ nội dung, đổi cách dẫn chuyện.",
            reference_analysis={
                "content_summary": "Hai anh em họ Cao",
                "characters": [{"name": "Tân", "role": "người anh"}],
                "dialogue": [{"order": 1, "speaker": "Cha", "line": "Các con phải thương nhau"}],
                "scene_map": [{"order": 1, "what_happens": "Người cha dặn dò"}],
                "visual_style": "ấm áp",
                "limitations": ["không có khung hình"],
            },
        )
        self.assertIn("Giữ nội dung, đổi cách dẫn chuyện", prompt)
        self.assertIn("Hai anh em họ Cao", prompt)
        self.assertIn("Các con phải thương nhau", prompt)
        self.assertIn("Tân (người anh)", prompt)
        self.assertIn("không có khung hình", prompt)


if __name__ == "__main__":
    unittest.main()
