from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from youtube_monitor import settings


class SaveIntegrationValuesTests(unittest.TestCase):
    def test_rejects_disallowed_keys_with_readable_vietnamese_message(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            with self.assertRaises(ValueError) as ctx:
                settings.save_integration_values({"NOT_ALLOWED_KEY": "x"})
        message = str(ctx.exception)
        self.assertIn("Không được phép thay đổi", message)
        self.assertIn("NOT_ALLOWED_KEY", message)

    def test_rejects_multiline_values_with_readable_vietnamese_message(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            with self.assertRaises(ValueError) as ctx:
                settings.save_integration_values({"OPENAI_API_KEY": "line1\nline2"})
        self.assertIn("không được chứa xuống dòng", str(ctx.exception))

    def test_repeated_saves_do_not_duplicate_the_header_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("EXISTING_KEY=keep\n", encoding="utf-8")
            with mock.patch.object(settings, "ENV_PATH", env_path):
                with mock.patch.dict(os.environ, {}, clear=False):
                    settings.save_integration_values({"OPENAI_MODEL": "gpt-4o-mini"})
                    settings.save_integration_values({"ANTHROPIC_MODEL": "claude-opus-5"})
            content = env_path.read_text(encoding="utf-8")
            self.assertEqual(
                content.count("# Local integrations (managed from dashboard)"), 1
            )
            self.assertIn("OPENAI_MODEL=gpt-4o-mini", content)
            self.assertIn("ANTHROPIC_MODEL=claude-opus-5", content)
            self.assertIn("EXISTING_KEY=keep", content)


if __name__ == "__main__":
    unittest.main()
