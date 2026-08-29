import unittest

from youtube_monitor.codex_bridge import CodexBridgeError, _parse_json_output, _strict_output_schema


class CodexBridgeTests(unittest.TestCase):
    def test_parse_json_output_returns_object(self):
        self.assertEqual(_parse_json_output('{"topic":"test"}'), {"topic": "test"})

    def test_parse_json_output_accepts_code_fence(self):
        self.assertEqual(_parse_json_output('```json\n{"ok":true}\n```'), {"ok": True})

    def test_parse_json_output_rejects_non_object(self):
        with self.assertRaises(CodexBridgeError):
            _parse_json_output('["not", "an", "object"]')

    def test_output_schema_is_made_strict_recursively_without_mutation(self):
        original = {
            "type": "object",
            "properties": {
                "approved": {"type": "boolean"},
                "review": {
                    "type": "object",
                    "properties": {
                        "score": {"type": "integer"},
                        "note": {"type": "string"},
                    },
                    "required": ["score"],
                },
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                    },
                },
            },
            "required": ["approved"],
        }

        strict = _strict_output_schema(original)

        self.assertIs(strict["additionalProperties"], False)
        self.assertEqual(set(strict["required"]), set(strict["properties"]))
        nested = strict["properties"]["review"]
        self.assertIs(nested["additionalProperties"], False)
        self.assertEqual(set(nested["required"]), {"score", "note"})
        item = strict["properties"]["issues"]["items"]
        self.assertIs(item["additionalProperties"], False)
        self.assertEqual(item["required"], ["message"])
        self.assertNotIn("additionalProperties", original)
        self.assertEqual(original["required"], ["approved"])


if __name__ == "__main__":
    unittest.main()
