import unittest

from youtube_monitor.claude_code_bridge import ClaudeCodeBridgeError, _parse_json_output


class ClaudeCodeBridgeTests(unittest.TestCase):
    def test_parse_json_output_accepts_bare_object(self):
        self.assertEqual(_parse_json_output('{"found": true}'), {"found": True})

    def test_parse_json_output_accepts_code_fence(self):
        self.assertEqual(_parse_json_output('```json\n{"ok":true}\n```'), {"ok": True})

    def test_parse_json_output_unwraps_object_result_envelope(self):
        self.assertEqual(
            _parse_json_output('{"type":"result","result":{"x":10,"y":20}}'),
            {"x": 10, "y": 20},
        )

    def test_parse_json_output_unwraps_string_result_envelope(self):
        self.assertEqual(
            _parse_json_output('{"type":"result","result":"{\\"x\\":10}"}'),
            {"x": 10},
        )

    def test_parse_json_output_rejects_non_object(self):
        with self.assertRaises(ClaudeCodeBridgeError):
            _parse_json_output('["not", "an", "object"]')


if __name__ == "__main__":
    unittest.main()
