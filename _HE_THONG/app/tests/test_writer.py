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

    def test_build_prompt_includes_creative_direction_and_reference_brief(self):
        prompt = _build_prompt(
            {"title": "Chó", "description": "", "tags": []},
            "Lời kể nguồn",
            creative_direction="Đổi nhân vật chính thành mèo ở chung cư.",
            reference_analysis={"narrative_formula": ["mở đầu", "thử thách"], "visual_style": {"art_direction": "ấm áp"}, "remake_guardrails": ["đổi sự kiện"]},
        )
        self.assertIn("Đổi nhân vật chính thành mèo", prompt)
        self.assertIn("Narrative formula", prompt)


if __name__ == "__main__":
    unittest.main()
