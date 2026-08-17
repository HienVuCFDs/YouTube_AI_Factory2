from __future__ import annotations

import unittest

from youtube_monitor.director import _normalize, director_to_script, director_to_shots


class DirectorTests(unittest.TestCase):
    def _raw(self) -> dict:
        return {
            "script_title": "Kiểm tra quy trình",
            "hook": "Đừng vội tin một tín hiệu duy nhất.",
            "intro": "Ta sẽ kiểm tra quy trình theo ba lớp.",
            "cta": "Hãy tự kiểm chứng trước khi áp dụng.",
            "segments": [
                {
                    "section": "hook",
                    "narration": "Đừng vội tin một tín hiệu duy nhất.",
                    "visual_intent": "Mở bằng biểu đồ đang chuyển động.",
                    "source_cue": "directional bias",
                    "asset_type": "source_clip",
                },
                {
                    "section": "main",
                    "narration": "Hãy đối chiếu dữ liệu, bối cảnh và rủi ro trước khi thực thi.",
                    "visual_intent": "Hiện dashboard dữ liệu và phần đánh dấu rủi ro.",
                    "source_cue": "data confirmation",
                    "asset_type": "source_clip",
                },
            ],
        }

    def test_director_output_becomes_a_script_and_shot_list(self) -> None:
        director = _normalize(self._raw())
        script = director_to_script(director)
        shots = director_to_shots({"id": 1}, director)
        self.assertEqual(script["script_title"], "Kiểm tra quy trình")
        self.assertEqual(len(shots), 2)
        self.assertIn("[SOURCE_CUE: directional bias]", shots[0]["visual_prompt"])
        self.assertGreaterEqual(shots[1]["duration_seconds"], 5)

    def test_invalid_asset_type_is_made_safe(self) -> None:
        raw = self._raw()
        raw["segments"][0]["asset_type"] = "anything"
        director = _normalize(raw)
        self.assertEqual(director["segments"][0]["asset_type"], "source_clip")


if __name__ == "__main__":
    unittest.main()
