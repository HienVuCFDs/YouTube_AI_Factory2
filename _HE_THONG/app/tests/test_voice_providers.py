"""More than two Vietnamese voices.

Edge ships exactly two, HoaiMy and NamMinh, so every video a Vietnamese
channel makes is narrated by one of the same pair - and Edge answers from a
public endpoint that intermittently returns no audio at all, which stops a
render that has already been paid for in images. These tests cover the two
ways out: Google's vi-VN voices, and a local Piper model that no quota and no
network can take away.
"""

from __future__ import annotations

import base64
import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from youtube_monitor import google_tts, piper_tts


class WhatGoogleIsAskedForTests(unittest.TestCase):
    def test_the_language_is_taken_from_the_voice_name(self) -> None:
        body = google_tts.request_body("Xin chào", "vi-VN-Neural2-A")

        self.assertEqual(body["voice"]["languageCode"], "vi-VN")
        self.assertEqual(body["voice"]["name"], "vi-VN-Neural2-A")

    def test_a_rate_from_another_engines_scale_cannot_become_a_bad_request(self) -> None:
        """A speaking rate carried over from Edge would otherwise fail every
        scene of a job that has already spoken half of them."""
        body = google_tts.request_body("Xin chào", "vi-VN-Neural2-A", rate=99.0)

        self.assertEqual(body["audioConfig"]["speakingRate"], 4.0)

    def test_an_edge_voice_is_not_mistaken_for_a_google_one(self) -> None:
        self.assertFalse(google_tts.is_google_voice("vi-VN-HoaiMyNeural"))
        self.assertFalse(google_tts.is_google_voice("vi-VN-NamMinhNeural"))

    def test_googles_own_voice_names_are_recognised(self) -> None:
        for voice in ("vi-VN-Neural2-A", "vi-VN-Chirp3-HD-Aoede", "vi-VN-Standard-B"):
            self.assertTrue(google_tts.is_google_voice(voice), voice)


class WhatGoogleWritesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def _response(self, payload: dict):
        stream = mock.MagicMock()
        stream.read.return_value = json.dumps(payload).encode("utf-8")
        stream.__enter__.return_value = stream
        stream.__exit__.return_value = False
        return stream

    def test_the_audio_that_comes_back_is_written_out(self) -> None:
        audio = b"ID3 pretend mp3"
        payload = {"audioContent": base64.b64encode(audio).decode("ascii")}
        out = self.root / "segment-001.mp3"

        with mock.patch.object(google_tts.urllib.request, "urlopen", return_value=self._response(payload)):
            google_tts.synthesize("Xin chào", out, api_key="k", voice="vi-VN-Neural2-A")

        self.assertEqual(out.read_bytes(), audio)

    def test_a_missing_key_says_where_to_get_one(self) -> None:
        with self.assertRaises(google_tts.GoogleTtsError) as raised:
            google_tts.synthesize("Xin chào", self.root / "a.mp3", api_key="")

        self.assertIn("GOOGLE_TTS_API_KEY", str(raised.exception))

    def test_an_empty_answer_is_not_written_as_a_file(self) -> None:
        out = self.root / "segment-001.mp3"

        with mock.patch.object(google_tts.urllib.request, "urlopen", return_value=self._response({})):
            with self.assertRaises(google_tts.GoogleTtsError):
                google_tts.synthesize("Xin chào", out, api_key="k")

        self.assertFalse(out.exists())

    def test_the_api_key_is_never_repeated_back_in_an_error(self) -> None:
        """The key rides in the query string, so an error that echoed the URL
        would put it in a job record the user later pastes into a report."""
        import urllib.error

        failure = urllib.error.HTTPError(
            "https://x/?key=SECRET123", 403, "Forbidden", {}, None,
        )
        failure.read = lambda: b'{"error":{"message":"API key not valid"}}'

        with mock.patch.object(google_tts.urllib.request, "urlopen", side_effect=failure):
            with self.assertRaises(google_tts.GoogleTtsError) as raised:
                google_tts.synthesize("Xin chào", self.root / "a.mp3", api_key="SECRET123")

        self.assertNotIn("SECRET123", str(raised.exception))
        self.assertIn("API key not valid", str(raised.exception))


class WhatPiperNeedsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def test_the_narration_goes_in_on_stdin(self) -> None:
        """An apostrophe or a quote in the narration must not be able to break
        the command that speaks it."""
        model = self.root / "vi_VN-vais1000-medium.onnx"
        model.write_bytes(b"model")
        out = self.root / "segment-001.wav"
        recorded: dict = {}

        def capture(args, **kwargs):
            recorded["args"] = args
            recorded["input"] = kwargs.get("input")
            out.write_bytes(b"RIFF")
            return subprocess.CompletedProcess(args, 0, "", "")

        with mock.patch.object(piper_tts.shutil, "which", return_value="piper"), \
                mock.patch.object(piper_tts.subprocess, "run", side_effect=capture):
            piper_tts.synthesize("Trái Đất 'xanh'", out, model=str(model))

        self.assertEqual(recorded["input"], "Trái Đất 'xanh'")
        self.assertNotIn("Trái Đất 'xanh'", " ".join(recorded["args"]))

    def test_a_missing_model_says_which_one_to_download(self) -> None:
        with mock.patch.object(piper_tts.shutil, "which", return_value="piper"):
            with self.assertRaises(piper_tts.PiperTtsError) as raised:
                piper_tts.synthesize("Xin chào", self.root / "a.wav", model="")

        self.assertIn("vi_VN", str(raised.exception))

    def test_piper_not_installed_is_reported_as_such(self) -> None:
        with mock.patch.object(piper_tts.shutil, "which", return_value=None):
            with self.assertRaises(piper_tts.PiperTtsError) as raised:
                piper_tts.synthesize("Xin chào", self.root / "a.wav", model="m.onnx")

        self.assertIn("piper", str(raised.exception))

    def test_a_run_that_writes_nothing_is_a_failure(self) -> None:
        model = self.root / "m.onnx"
        model.write_bytes(b"model")

        with mock.patch.object(piper_tts.shutil, "which", return_value="piper"), \
                mock.patch.object(
                    piper_tts.subprocess, "run",
                    return_value=subprocess.CompletedProcess([], 0, "", ""),
                ):
            with self.assertRaises(piper_tts.PiperTtsError):
                piper_tts.synthesize("Xin chào", self.root / "a.wav", model=str(model))


class TheWorkerAcceptsThemTests(unittest.TestCase):
    def test_both_engines_are_voice_providers(self) -> None:
        from youtube_monitor.production_worker import VOICE_PROVIDERS

        self.assertIn("google_tts", VOICE_PROVIDERS)
        self.assertIn("piper", VOICE_PROVIDERS)

    def test_the_api_accepts_them_too(self) -> None:
        """A provider the worker can run but the request model rejects is a
        setting the user can never actually choose."""
        from youtube_monitor.main import CreateProductionJobRequest, RenderSettingsRequest

        for provider in ("google_tts", "piper"):
            RenderSettingsRequest(voice_provider=provider)
        CreateProductionJobRequest(job_type="voiceover", provider="google_tts", confirmed=True)


if __name__ == "__main__":
    unittest.main()
