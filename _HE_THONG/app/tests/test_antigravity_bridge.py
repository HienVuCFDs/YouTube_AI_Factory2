import unittest

from youtube_monitor.antigravity_bridge import AntigravityBridgeError, _parse_json_output


class AntigravityBridgeTests(unittest.TestCase):
    def test_parse_json_output_accepts_bare_object(self):
        self.assertEqual(_parse_json_output('{"topic": "test"}'), {"topic": "test"})

    def test_parse_json_output_accepts_code_fence(self):
        self.assertEqual(_parse_json_output('```json\n{"ok":true}\n```'), {"ok": True})

    def test_parse_json_output_unwraps_object_result_envelope(self):
        self.assertEqual(
            _parse_json_output('{"type":"result","result":{"a":1}}'),
            {"a": 1},
        )

    def test_parse_json_output_unwraps_string_result_envelope(self):
        self.assertEqual(
            _parse_json_output('{"type":"result","result":"{\\"a\\":1}"}'),
            {"a": 1},
        )

    def test_parse_json_output_rejects_non_object(self):
        with self.assertRaises(AntigravityBridgeError):
            _parse_json_output('["not", "an", "object"]')


if __name__ == "__main__":
    unittest.main()
