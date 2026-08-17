import unittest

from youtube_monitor.reference_analyzer import _prompt


class ReferenceAnalyzerTests(unittest.TestCase):
    def test_prompt_marks_missing_evidence(self):
        prompt = _prompt({"title": "Video mẫu", "description": "", "tags": []}, None)
        self.assertIn("No transcript", prompt)

    def test_prompt_includes_transcript_when_available(self):
        prompt = _prompt({"title": "Video mẫu", "description": "", "tags": []}, "Cảnh mở đầu")
        self.assertIn("Cảnh mở đầu", prompt)


if __name__ == "__main__":
    unittest.main()
