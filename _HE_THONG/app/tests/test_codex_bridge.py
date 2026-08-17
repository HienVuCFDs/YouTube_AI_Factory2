import unittest

from youtube_monitor.codex_bridge import CodexBridgeError, _parse_json_output


class CodexBridgeTests(unittest.TestCase):
    def test_parse_json_output_returns_object(self):
        self.assertEqual(_parse_json_output('{"topic":"test"}'), {"topic": "test"})

    def test_parse_json_output_accepts_code_fence(self):
        self.assertEqual(_parse_json_output('```json\n{"ok":true}\n```'), {"ok": True})

    def test_parse_json_output_rejects_non_object(self):
        with self.assertRaises(CodexBridgeError):
            _parse_json_output('["not", "an", "object"]')


if __name__ == "__main__":
    unittest.main()
