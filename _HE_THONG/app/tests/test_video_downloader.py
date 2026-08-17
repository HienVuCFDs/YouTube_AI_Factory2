from __future__ import annotations

import unittest

from youtube_monitor.video_downloader import _download_with_options


class _FakeYdl:
    selectors: list[str] = []

    def __init__(self, options: dict) -> None:
        self.options = options
        type(self).selectors.append(str(options["format"]))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def download(self, _urls: list[str]) -> None:
        if self.options["format"] == "bestvideo*+bestaudio/best":
            raise RuntimeError("Requested format is not available")


class _FakeYtDlp:
    YoutubeDL = _FakeYdl


class VideoDownloaderTests(unittest.TestCase):
    def test_retries_a_less_restrictive_selector_when_primary_format_is_missing(self) -> None:
        _FakeYdl.selectors = []
        _download_with_options(
            _FakeYtDlp,
            "https://www.youtube.com/watch?v=test-video",
            "test-video",
            "video",
            None,
        )
        self.assertEqual(_FakeYdl.selectors[:2], ["bestvideo*+bestaudio/best", "best[ext=mp4]/best"])


if __name__ == "__main__":
    unittest.main()
