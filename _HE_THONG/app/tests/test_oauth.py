import json
import tempfile
import unittest
from pathlib import Path

from youtube_monitor import oauth


class OAuthTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_path = oauth.OAUTH_TOKEN_PATH
        oauth.OAUTH_TOKEN_PATH = Path(self._tmpdir.name) / "oauth_token.json"

    def tearDown(self):
        oauth.OAUTH_TOKEN_PATH = self._original_path
        self._tmpdir.cleanup()

    def test_status_reports_not_connected_without_token_file(self):
        self.assertFalse(oauth.status()["connected"])

    def test_status_reports_connected_when_refresh_token_present(self):
        oauth.OAUTH_TOKEN_PATH.write_text(
            json.dumps({"refresh_token": "r-token", "access_token": "a-token"}),
            encoding="utf-8",
        )
        self.assertTrue(oauth.status()["connected"])

    def test_disconnect_removes_token_file(self):
        oauth.OAUTH_TOKEN_PATH.write_text(json.dumps({"refresh_token": "r-token"}), encoding="utf-8")
        oauth.disconnect()
        self.assertFalse(oauth.OAUTH_TOKEN_PATH.exists())
        self.assertFalse(oauth.status()["connected"])

    def test_get_access_token_without_saved_token_raises(self):
        with self.assertRaises(oauth.OAuthError):
            oauth.get_access_token()


if __name__ == "__main__":
    unittest.main()
