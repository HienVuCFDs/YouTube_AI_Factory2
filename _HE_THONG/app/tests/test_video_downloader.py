from __future__ import annotations

import unittest
from unittest import mock

from youtube_monitor.video_downloader import _download_with_options, _options


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


class _FakeAudioYdl(_FakeYdl):
    clients: list[str] = []

    def __init__(self, options: dict) -> None:
        super().__init__(options)
        client = ((options.get("extractor_args") or {}).get("youtube") or {}).get("player_client") or [""]
        type(self).clients.append(client[0])

    def download(self, _urls: list[str]) -> None:
        if not self.options.get("extractor_args"):
            raise RuntimeError("HTTP Error 403: Forbidden")


class _FakeAudioYtDlp:
    YoutubeDL = _FakeAudioYdl


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

    def test_transcription_audio_retries_another_client_after_403(self) -> None:
        _FakeAudioYdl.clients = []
        _download_with_options(
            _FakeAudioYtDlp,
            "https://www.youtube.com/watch?v=test-video",
            "audio", "audio", None,
            output_template="audio.%(ext)s", audio_codec="wav",
        )
        self.assertEqual(_FakeAudioYdl.clients, ["", "android_vr"])

    def test_options_enable_installed_node_and_extract_wav_for_whisper(self) -> None:
        with mock.patch("youtube_monitor.video_downloader.shutil.which", return_value="node.exe"):
            options = _options("audio", "audio", output_template="audio.%(ext)s", audio_codec="wav")
        self.assertEqual(options["js_runtimes"], {"deno": {}, "node": {}})
        self.assertEqual(options["outtmpl"], "audio.%(ext)s")
        self.assertEqual(options["postprocessors"][0]["preferredcodec"], "wav")


if __name__ == "__main__":
    unittest.main()
