"""Gemini 3.8 TTS, the adapter: what is sent, what is written, what is retried.

No call leaves the machine: every request goes to an httpx.MockTransport that
answers the way the Gemini Interactions API documents. The key below is not a
key, and the tests check it is never repeated back.
"""

from __future__ import annotations

import base64
import io
import json
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import httpx

from youtube_monitor import gemini_tts, tts_catalog, usage_limits

KEY = "fake-gemini-key-for-tests"
VIETNAMESE = "Đây là một đoạn thử giọng đọc tiếng Việt."


def wav_bytes(frames: int = 2400, rate: int = 24_000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"\x01\x00" * frames)
    return buffer.getvalue()


def answer(audio: bytes, mime: str = "audio/wav") -> dict:
    return {"id": "interaction-1", "steps": [
        {"type": "user_input", "content": []},
        {"type": "model_output", "content": [
            {"type": "audio", "mime_type": mime, "sample_rate": 24_000, "channels": 1,
             "data": base64.b64encode(audio).decode("ascii")}]},
    ], "usage": {"total_input_tokens": 12, "total_output_tokens": 340, "total_tokens": 352}}


# The shape GET /voices?language_code=vi-VN really answers with: catalog ids, listed under vi-VN.
VI_CATALOG_VOICE = {"id": "vi-vn-advisor-6", "display_name": "Authoritative Advisor 6", "language_code": "vi-VN",
                    "gender": "male", "type": "prebuilt"}


def error(code: int, message: str, status: str = "", details: list | None = None) -> dict:
    return {"error": {"code": code, "message": message, "status": status, "details": details or []}}


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)
        self.requests: list[httpx.Request] = []
        self.replies: list[httpx.Response] = []
        self.waits: list[float] = []
        gemini_tts._last_failure.clear()
        gemini_tts._voice_cache.clear()
        gemini_tts._voice_failures.clear()
        patches = [
            mock.patch.object(gemini_tts, "_client_factory", self._client),
            mock.patch.object(gemini_tts, "_sleep", self.waits.append),
            mock.patch.object(usage_limits, "_recorder", self._record_limit),
            mock.patch.object(usage_limits, "_clearer", self._clear_limit),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.limits: list[tuple] = []
        self.cleared: list[str] = []

    def _record_limit(self, provider, message, reset):
        self.limits.append((provider, message, reset))

    def _clear_limit(self, provider):
        self.cleared.append(provider)

    def _client(self) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self.replies.pop(0)
        return httpx.Client(transport=httpx.MockTransport(handler))

    def reply(self, status: int, body: dict) -> None:
        self.replies.append(httpx.Response(status, json=body))

    def sent(self, index: int = -1) -> dict:
        return json.loads(self.requests[index].content.decode("utf-8"))


class RegistrationTests(unittest.TestCase):
    def test_two_models_two_keys_one_vendor(self) -> None:
        self.assertEqual({key: item.model for key, item in gemini_tts.MODELS.items()}, {
            "google_gemini_3_8_flash_tts": "gemini-3.8-flash-tts",
            "google_gemini_3_8_flash_lite_tts": "gemini-3.8-flash-lite-tts",
        })
        for key, model in (("google_gemini_3_8_flash_tts", "gemini-3.8-flash-tts"),
                           ("google_gemini_3_8_flash_lite_tts", "gemini-3.8-flash-lite-tts")):
            engine = tts_catalog.engine(key)
            self.assertEqual((engine.vendor, engine.model, engine.suffix, engine.paid), ("google", model, "wav", True))
        # Edge stays what it was.
        edge = tts_catalog.engine("edge_tts")
        self.assertEqual((edge.vendor, edge.model, edge.suffix), ("microsoft", "edge-tts", "mp3"))

    def test_the_worker_the_settings_and_the_studio_all_know_them(self) -> None:
        from youtube_monitor.database import Database
        from youtube_monitor.production_worker import VOICE_PROVIDERS

        for key in gemini_tts.MODELS:
            self.assertIn(key, VOICE_PROVIDERS)
            self.assertIn(key, Database.RENDER_VOICE_PROVIDERS)
            self.assertIn(key, tts_catalog.STUDIO_ENGINES)
        self.assertEqual(tts_catalog.STUDIO_ENGINES[0], "edge_tts")


class RequestTests(_Case):
    def test_one_speaker_the_documented_shape(self) -> None:
        self.reply(200, answer(wav_bytes()))
        gemini_tts.synthesize("Xin chào các bạn.", self.root / "a.wav", provider="google_gemini_3_8_flash_tts",
                              api_key=KEY, voice="Puck", language="vi")
        request = self.requests[0]
        self.assertEqual(str(request.url), "https://generativelanguage.googleapis.com/v1beta/interactions")
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.headers["x-goog-api-key"], KEY)
        self.assertNotIn(KEY, str(request.url), "the key travels in a header, never in the URL")
        self.assertEqual(self.sent(), {
            "model": "gemini-3.8-flash-tts",
            "input": [{"type": "user_input", "content": [{"type": "text", "text": "Xin chào các bạn."}]}],
            "response_format": {"type": "audio", "mime_type": "audio/wav"},
            "generation_config": {"speech_config": [{"voice": "Puck", "language": "vi"}]},
        })

    def test_flash_lite_is_its_own_model(self) -> None:
        self.reply(200, answer(wav_bytes()))
        result = gemini_tts.synthesize("Xin chào.", self.root / "a.wav", provider="google_gemini_3_8_flash_lite_tts",
                                       api_key=KEY, voice="Kore")
        self.assertEqual(self.sent()["model"], "gemini-3.8-flash-lite-tts")
        self.assertEqual((result["vendor"], result["provider"], result["model"]),
                         ("google", "google_gemini_3_8_flash_lite_tts", "gemini-3.8-flash-lite-tts"))

    def test_the_style_goes_into_speech_metadata_and_the_words_stay_the_words(self) -> None:
        style = "Giọng kể chuyện tự nhiên, rõ ràng, hơi ấm, tốc độ vừa phải, nhấn mạnh các từ quan trọng."
        self.reply(200, answer(wav_bytes()))
        result = gemini_tts.synthesize(VIETNAMESE, self.root / "a.wav", provider="google_gemini_3_8_flash_tts",
                                       api_key=KEY, voice="Kore", style=style, speaker="narrator")
        item = self.sent()["input"][0]["content"][0]
        self.assertEqual(item["text"], VIETNAMESE, "nothing added to the transcript")
        self.assertEqual(item["annotations"], [{"type": "speech_metadata", "style": style}])
        self.assertNotIn(style, item["text"])
        self.assertEqual((result["style"], result["speaker"]), (style, "narrator"))

    def test_inline_vocal_tags_already_in_the_words_pass_through_untouched(self) -> None:
        self.reply(200, answer(wav_bytes()))
        text = "Khoan đã... <short pause> bạn có nghe thấy không? <sigh>"
        gemini_tts.synthesize(text, self.root / "a.wav", provider="google_gemini_3_8_flash_tts", api_key=KEY)
        self.assertEqual(self.sent()["input"][0]["content"][0]["text"], text)

    def test_vietnamese_is_sent_as_utf8_and_comes_back_whole(self) -> None:
        self.reply(200, answer(wav_bytes()))
        gemini_tts.synthesize(VIETNAMESE, self.root / "a.wav", provider="google_gemini_3_8_flash_tts", api_key=KEY)
        raw = self.requests[0].content
        self.assertIn("Đây là một đoạn thử giọng đọc tiếng Việt.".encode("utf-8"), raw, "not escaped, not lost")
        self.assertIn("charset=utf-8", self.requests[0].headers["content-type"])
        self.assertEqual(self.sent()["input"][0]["content"][0]["text"], VIETNAMESE)

    def test_two_speakers_are_structured_turns_not_name_prefixes(self) -> None:
        self.reply(200, answer(wav_bytes()))
        turns = [gemini_tts.Turn("Chào Bình, hôm nay thế nào?", speaker="An", style="vui vẻ"),
                 gemini_tts.Turn("Cũng ổn, còn An?", speaker="Bình"),
                 gemini_tts.Turn("Mình khoẻ.", speaker="An")]
        result = gemini_tts.synthesize_turns(turns, self.root / "a.wav", provider="google_gemini_3_8_flash_tts",
                                             api_key=KEY, voices={"An": "Kore", "Bình": "Puck"}, language="vi")
        body = self.sent()
        self.assertEqual(body["generation_config"]["speech_config"], {
            "mode": "conversational",
            "speakers": [{"speaker": "An", "voice": "Kore", "language": "vi"},
                         {"speaker": "Bình", "voice": "Puck", "language": "vi"}],
        })
        content = body["input"][0]["content"]
        self.assertEqual([item["annotations"][0]["speaker"] for item in content], ["An", "Bình", "An"])
        self.assertEqual(content[0]["annotations"][0]["style"], "vui vẻ")
        self.assertNotIn("style", content[1]["annotations"][0])
        self.assertEqual([item["text"] for item in content], [turn.text for turn in turns])
        for item in content:
            self.assertFalse(item["text"].startswith(("An:", "Bình:")))
        self.assertEqual(result["speakers"], ["An", "Bình"])

    def test_two_speakers_and_an_unattributed_line_is_refused_before_anything_is_sent(self) -> None:
        turns = [gemini_tts.Turn("Chào Bình.", speaker="An"), gemini_tts.Turn("Chào An.", speaker="Bình"),
                 gemini_tts.Turn("Ai nói câu này?")]
        with self.assertRaises(gemini_tts.GeminiTtsError) as raised:
            gemini_tts.synthesize_turns(turns, self.root / "a.wav", provider="google_gemini_3_8_flash_tts",
                                        api_key=KEY, voices={"An": "Kore", "Bình": "Puck"})
        self.assertEqual(raised.exception.kind, "input")
        self.assertEqual(self.requests, [])

    def test_more_than_two_speakers_is_refused_before_anything_is_sent(self) -> None:
        turns = [gemini_tts.Turn("Một", speaker="A"), gemini_tts.Turn("Hai", speaker="B"), gemini_tts.Turn("Ba", speaker="C")]
        with self.assertRaises(gemini_tts.GeminiTtsError) as raised:
            gemini_tts.synthesize_turns(turns, self.root / "a.wav", provider="google_gemini_3_8_flash_tts", api_key=KEY)
        self.assertEqual(raised.exception.kind, "input")
        self.assertEqual(self.requests, [])

    def test_a_voice_from_another_engine_is_replaced_and_the_replacement_recorded(self) -> None:
        self.reply(200, {"voices": [VI_CATALOG_VOICE]})
        self.reply(200, answer(wav_bytes()))
        result = gemini_tts.synthesize("Xin chào.", self.root / "a.wav", provider="google_gemini_3_8_flash_tts",
                                       api_key=KEY, voice="vi-VN-HoaiMyNeural", language="vi")
        self.assertEqual([request.url.path for request in self.requests], ["/v1beta/voices", "/v1beta/interactions"],
                         "the catalog is read before a stored voice is called foreign")
        self.assertEqual(self.sent()["generation_config"]["speech_config"], [{"voice": gemini_tts.DEFAULT_VOICE, "language": "vi"}])
        self.assertEqual((result["voice"], result["voice_fallback_from"]), ("Kore", "vi-VN-HoaiMyNeural"))

    def test_no_key_no_request(self) -> None:
        with self.assertRaises(gemini_tts.GeminiTtsError) as raised:
            gemini_tts.synthesize("Xin chào.", self.root / "a.wav", provider="google_gemini_3_8_flash_tts", api_key="")
        self.assertIn("GEMINI_API_KEY", str(raised.exception))
        self.assertEqual(self.requests, [])


class AudioTests(_Case):
    def test_a_wav_is_written_as_it_came_never_wrapped_twice(self) -> None:
        audio = wav_bytes()
        self.reply(200, answer(audio))
        out = self.root / "segment-001.wav"
        result = gemini_tts.synthesize("Xin chào.", out, provider="google_gemini_3_8_flash_tts", api_key=KEY)
        written = out.read_bytes()
        self.assertEqual(written, audio)
        self.assertEqual((written[:4], written[8:12]), (b"RIFF", b"WAVE"))
        self.assertEqual(written.count(b"RIFF"), 1)
        self.assertEqual((result["mime_type"], result["sample_rate"], result["bytes"]), ("audio/wav", 24_000, len(audio)))
        self.assertEqual(result["usage"], {"total_input_tokens": 12, "total_output_tokens": 340, "total_tokens": 352})

    def test_headerless_pcm_gets_one_header_in_the_adapter(self) -> None:
        pcm = b"\x02\x00" * 4800
        self.reply(200, answer(pcm, mime="audio/l16;rate=24000"))
        out = self.root / "segment-002.wav"
        gemini_tts.synthesize("Xin chào.", out, provider="google_gemini_3_8_flash_tts", api_key=KEY)
        with wave.open(str(out), "rb") as reader:
            self.assertEqual((reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getnframes()),
                             (1, 2, 24_000, 4800))
        self.assertEqual(out.read_bytes().count(b"RIFF"), 1)

    def test_an_answer_without_audio_writes_no_file(self) -> None:
        self.reply(200, {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "xin lỗi"}]}]})
        out = self.root / "segment-003.wav"
        with self.assertRaises(gemini_tts.GeminiTtsError) as raised:
            gemini_tts.synthesize("Xin chào.", out, provider="google_gemini_3_8_flash_tts", api_key=KEY)
        self.assertEqual(raised.exception.kind, "response")
        self.assertFalse(out.exists())

    def test_unreadable_audio_parameters_are_a_response_error_not_a_crash(self) -> None:
        reply = answer(b"\x02\x00" * 480, mime="audio/l16")
        reply["steps"][1]["content"][0]["sample_rate"] = "24kHz"
        self.reply(200, reply)
        out = self.root / "segment-004.wav"
        with self.assertRaises(gemini_tts.GeminiTtsError) as raised:
            gemini_tts.synthesize("Xin chào.", out, provider="google_gemini_3_8_flash_tts", api_key=KEY)
        self.assertEqual(raised.exception.kind, "response")
        self.assertFalse(out.exists())

    def test_an_unknown_format_is_refused_rather_than_written(self) -> None:
        self.reply(200, answer(b"\xff\xfb mp3 bytes", mime="audio/mpeg"))
        with self.assertRaises(gemini_tts.GeminiTtsError):
            gemini_tts.synthesize("Xin chào.", self.root / "x.wav", provider="google_gemini_3_8_flash_tts", api_key=KEY)


class RetryAndQuotaTests(_Case):
    def test_a_transient_failure_is_tried_again(self) -> None:
        self.reply(503, error(503, "The service is currently unavailable.", "UNAVAILABLE"))
        self.reply(200, answer(wav_bytes()))
        result = gemini_tts.synthesize("Xin chào.", self.root / "a.wav", provider="google_gemini_3_8_flash_tts", api_key=KEY)
        self.assertEqual((result["attempts"], self.waits), (2, [2.0]))
        self.assertEqual(self.limits, [], "an outage of the service is not the account running out")
        self.assertEqual(self.cleared, ["google_gemini_3_8_flash_tts"])

    def test_three_transient_failures_end_it_without_recording_a_quota(self) -> None:
        for _ in range(3):
            self.reply(500, error(500, "Internal error", "INTERNAL"))
        with self.assertRaises(gemini_tts.GeminiTtsError) as raised:
            gemini_tts.synthesize("Xin chào.", self.root / "a.wav", provider="google_gemini_3_8_flash_tts", api_key=KEY)
        self.assertEqual((raised.exception.kind, len(self.requests), self.waits), ("transient", 3, [2.0, 5.0]))
        self.assertEqual(self.limits, [])
        status = gemini_tts.status("google_gemini_3_8_flash_tts", api_key=KEY, usage_limit=None)
        self.assertEqual((status["status"], status["status_label"]), ("error", "Lỗi kết nối"))

    def test_a_per_minute_rate_limit_is_waited_out_as_google_says(self) -> None:
        details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel"}]},
                   {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "7s"}]
        self.reply(429, error(429, "You exceeded your current quota.", "RESOURCE_EXHAUSTED", details))
        self.reply(200, answer(wav_bytes()))
        gemini_tts.synthesize("Xin chào.", self.root / "a.wav", provider="google_gemini_3_8_flash_tts", api_key=KEY)
        self.assertEqual(self.waits, [7.0])
        self.assertEqual(self.limits, [], "a per-minute limit does not mark the account as out")

    def test_a_daily_quota_is_recorded_and_not_retried(self) -> None:
        details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]
        self.reply(429, error(429, "You exceeded your current quota.", "RESOURCE_EXHAUSTED", details))
        with self.assertRaises(gemini_tts.GeminiTtsError) as raised:
            gemini_tts.synthesize("Xin chào.", self.root / "a.wav", provider="google_gemini_3_8_flash_lite_tts", api_key=KEY)
        self.assertEqual((raised.exception.kind, len(self.requests), self.waits), ("quota", 1, []))
        self.assertEqual([provider for provider, *_ in self.limits], ["google_gemini_3_8_flash_lite_tts"])
        self.assertTrue(usage_limits.is_usage_limit(self.limits[0][1]))
        blocking = {"provider": "google_gemini_3_8_flash_lite_tts", "message": self.limits[0][1],
                    "detected_at": "2099-01-01T00:00:00+00:00", "last_failure_at": "2099-01-01T00:00:00+00:00"}
        status = gemini_tts.status("google_gemini_3_8_flash_lite_tts", api_key=KEY, usage_limit=blocking)
        self.assertEqual((status["status"], status["status_label"]), ("quota", "Hết quota"))

    def test_a_rejected_key_is_final_and_never_repeated_back(self) -> None:
        self.reply(403, error(403, f"API key not valid. Please pass a valid API key. ({KEY})", "PERMISSION_DENIED"))
        with self.assertRaises(gemini_tts.GeminiTtsError) as raised:
            gemini_tts.synthesize("Xin chào.", self.root / "a.wav", provider="google_gemini_3_8_flash_tts", api_key=KEY)
        self.assertEqual((raised.exception.kind, len(self.requests)), ("auth", 1))
        self.assertNotIn(KEY, str(raised.exception))
        self.assertIn("GEMINI_API_KEY", str(raised.exception))
        self.assertEqual(self.limits, [])
        self.assertNotIn(KEY, json.dumps(gemini_tts._last_failure))

    def test_a_network_failure_is_transient(self) -> None:
        def broken() -> httpx.Client:
            def handler(request):
                raise httpx.ConnectError("no route", request=request)
            return httpx.Client(transport=httpx.MockTransport(handler))
        with mock.patch.object(gemini_tts, "_client_factory", broken), self.assertRaises(gemini_tts.GeminiTtsError) as raised:
            gemini_tts.synthesize("Xin chào.", self.root / "a.wav", provider="google_gemini_3_8_flash_tts", api_key=KEY)
        self.assertEqual(raised.exception.kind, "transient")
        self.assertEqual(self.waits, [2.0, 5.0])

    def test_a_success_clears_an_earlier_failure(self) -> None:
        for _ in range(3):
            self.reply(503, error(503, "unavailable", "UNAVAILABLE"))
        with self.assertRaises(gemini_tts.GeminiTtsError):
            gemini_tts.synthesize("Xin chào.", self.root / "a.wav", provider="google_gemini_3_8_flash_tts", api_key=KEY)
        self.assertEqual(gemini_tts.status("google_gemini_3_8_flash_tts", api_key=KEY, usage_limit=None)["status"], "error")
        self.reply(200, answer(wav_bytes()))
        gemini_tts.synthesize("Xin chào.", self.root / "a.wav", provider="google_gemini_3_8_flash_tts", api_key=KEY)
        status = gemini_tts.status("google_gemini_3_8_flash_tts", api_key=KEY, usage_limit=None)
        self.assertEqual((status["status"], status["status_label"]), ("ready", "Sẵn sàng"))

    def test_a_request_refused_for_what_it_asked_does_not_mark_the_model_unreachable(self) -> None:
        # The acceptance run met exactly this: one voice refused (HTTP 400) while the model worked.
        self.reply(400, error(400, "No matching speaker voice found for name: x and language: vi", "INVALID_ARGUMENT"))
        with self.assertRaises(gemini_tts.GeminiTtsError) as raised:
            gemini_tts.synthesize("Xin chào.", self.root / "a.wav", provider="google_gemini_3_8_flash_tts", api_key=KEY)
        self.assertEqual((raised.exception.kind, raised.exception.status_code, len(self.requests)), ("input", 400, 1))
        self.assertIn("No matching speaker voice", str(raised.exception), "Google's own words are kept")
        status = gemini_tts.status("google_gemini_3_8_flash_tts", api_key=KEY, usage_limit=None)
        self.assertEqual((status["status"], status["status_label"]), ("ready", "Sẵn sàng"))
        self.assertEqual(self.limits, [])

    def test_without_a_key_the_model_is_not_configured(self) -> None:
        status = gemini_tts.status("google_gemini_3_8_flash_tts", api_key="", usage_limit=None)
        self.assertEqual((status["status"], status["status_label"], status["model"]), ("not_configured", "Chưa cấu hình", "gemini-3.8-flash-tts"))


class VoiceCatalogTests(_Case):
    def test_the_catalog_is_asked_for_prebuilt_voices_of_the_language_and_cached(self) -> None:
        self.reply(200, {"voices": [{"id": "Kore", "display_name": "Kore", "language_code": "vi-VN", "gender": "female", "type": "prebuilt"},
                                    {"id": "Puck", "display_name": "Puck", "language_code": "vi-VN", "gender": "male", "type": "prebuilt"}]})
        found = gemini_tts.list_voices(KEY, "vi")
        self.assertEqual(([voice["id"] for voice in found["voices"]], found["source"]), (["Kore", "Puck"], "api"))
        request = self.requests[0]
        self.assertEqual((request.url.path, request.url.params.get("language_code"), request.url.params.get("type")),
                         ("/v1beta/voices", "vi-VN", "prebuilt"))
        self.assertEqual(request.headers["x-goog-api-key"], KEY)
        again = gemini_tts.list_voices(KEY, "vi")
        self.assertEqual((len(self.requests), again["source"]), (1, "api"), "the second ask is the cache")

    def test_an_empty_answer_for_the_language_asks_for_all_prebuilt_voices(self) -> None:
        self.reply(200, {"voices": []})
        self.reply(200, {"voices": [{"id": "Charon", "display_name": "Charon", "type": "prebuilt"}]})
        found = gemini_tts.list_voices(KEY, "vi")
        self.assertEqual([voice["id"] for voice in found["voices"]], ["Charon"])
        self.assertIsNone(self.requests[1].url.params.get("language_code"))

    def test_without_a_key_or_when_the_catalog_fails_the_documented_voices_are_offered(self) -> None:
        offline = gemini_tts.list_voices("", "vi")
        self.assertEqual((offline["source"], len(offline["voices"])), ("builtin", len(gemini_tts.PREBUILT_VOICES)))
        self.assertEqual(self.requests, [])
        self.reply(503, error(503, "unavailable", "UNAVAILABLE"))
        failed = gemini_tts.list_voices(KEY, "en")
        self.assertEqual(failed["source"], "builtin")
        self.assertTrue(failed["error"])
        self.assertNotIn(KEY, failed["error"])

    def test_a_voice_the_catalog_listed_is_accepted(self) -> None:
        self.reply(200, {"voices": [{"id": "vi-VN-Narrator-Lan", "display_name": "Lan", "type": "prebuilt"}]})
        gemini_tts.list_voices(KEY, "vi")
        self.assertEqual(gemini_tts.resolve_voice("vi-VN-Narrator-Lan"), ("vi-VN-Narrator-Lan", ""))

    def test_a_catalog_voice_is_named_with_the_language_the_catalog_lists_it_under(self) -> None:
        # Google answered "No matching speaker voice found for name: vi-vn-advisor-6 and language: vi"
        # when the app's "vi" went beside a voice the catalog lists under "vi-VN".
        self.reply(200, {"voices": [VI_CATALOG_VOICE]})
        gemini_tts.list_voices(KEY, "vi")
        self.reply(200, answer(wav_bytes()))
        result = gemini_tts.synthesize(VIETNAMESE, self.root / "a.wav", provider="google_gemini_3_8_flash_tts",
                                       api_key=KEY, voice="vi-vn-advisor-6", language="vi")
        self.assertEqual(self.sent()["generation_config"]["speech_config"], [{"voice": "vi-vn-advisor-6", "language": "vi-VN"}])
        self.assertEqual((result["voice"], result["voice_fallback_from"], result["language"], result["voice_language"]),
                         ("vi-vn-advisor-6", "", "vi", "vi-VN"))
        self.reply(200, answer(wav_bytes()))
        gemini_tts.synthesize(VIETNAMESE, self.root / "b.wav", provider="google_gemini_3_8_flash_tts",
                              api_key=KEY, voice="Kore", language="vi")
        self.assertEqual(self.sent()["generation_config"]["speech_config"], [{"voice": "Kore", "language": "vi"}],
                         "a prebuilt voice keeps the language as given")
        self.assertEqual(len(self.requests), 3, "the catalog was read once")

    def test_a_catalog_voice_survives_a_cold_cache(self) -> None:
        # A job started after the app restarts: nothing has read the catalog yet in this process.
        self.reply(200, {"voices": [VI_CATALOG_VOICE]})
        self.reply(200, answer(wav_bytes()))
        result = gemini_tts.synthesize(VIETNAMESE, self.root / "a.wav", provider="google_gemini_3_8_flash_lite_tts",
                                       api_key=KEY, voice="vi-vn-advisor-6", language="vi")
        self.assertEqual(self.requests[0].url.params.get("language_code"), "vi-VN")
        self.assertEqual(self.sent()["generation_config"]["speech_config"], [{"voice": "vi-vn-advisor-6", "language": "vi-VN"}])
        self.assertEqual(result["voice_fallback_from"], "")

    def test_a_catalog_voice_is_never_replaced_because_the_catalog_could_not_be_read(self) -> None:
        # Regression: after a restart (nothing cached) with the catalog down, the stored catalog
        # voice used to become Kore and every scene was read in a voice nobody chose.
        self.reply(503, error(503, "unavailable", "UNAVAILABLE"))
        for index in range(3):
            out = self.root / f"{index}.wav"
            with self.assertRaises(gemini_tts.GeminiTtsError) as raised:
                gemini_tts.synthesize(VIETNAMESE, out, provider="google_gemini_3_8_flash_tts",
                                      api_key=KEY, voice="vi-vn-advisor-6", language="vi")
            self.assertEqual(raised.exception.kind, "transient")
            self.assertIn("vi-vn-advisor-6", str(raised.exception))
            self.assertIn("không bị thay", str(raised.exception))
            self.assertNotIn(KEY, str(raised.exception))
            self.assertFalse(out.exists())
        paths = [request.url.path for request in self.requests]
        self.assertEqual((paths.count("/v1beta/voices"), paths.count("/v1beta/interactions")), (1, 0),
                         "the catalog is not asked again scene after scene, and nothing is spoken")
        self.assertEqual(self.limits, [], "a catalog outage is not the account running out")
        # Once the catalog can be read, the same voice is the voice.
        self.reply(200, {"voices": [VI_CATALOG_VOICE]})
        self.assertEqual(gemini_tts.list_voices(KEY, "vi", refresh=True)["source"], "api", "a refresh asks again")
        self.reply(200, answer(wav_bytes()))
        result = gemini_tts.synthesize(VIETNAMESE, self.root / "ok.wav", provider="google_gemini_3_8_flash_tts",
                                       api_key=KEY, voice="vi-vn-advisor-6", language="vi")
        self.assertEqual((result["voice"], result["voice_fallback_from"], result["voice_language"]), ("vi-vn-advisor-6", "", "vi-VN"))

    def test_an_empty_catalog_does_not_replace_a_stored_voice_either(self) -> None:
        self.reply(200, {"voices": []})
        self.reply(200, {"voices": []})
        with self.assertRaises(gemini_tts.GeminiTtsError) as raised:
            gemini_tts.synthesize(VIETNAMESE, self.root / "a.wav", provider="google_gemini_3_8_flash_tts",
                                  api_key=KEY, voice="vi-vn-advisor-6", language="vi")
        self.assertEqual(raised.exception.kind, "transient")
        self.assertNotIn("/v1beta/interactions", [request.url.path for request in self.requests])

    def test_a_known_voice_needs_no_catalog_even_when_it_is_down(self) -> None:
        self.reply(200, answer(wav_bytes()))
        result = gemini_tts.synthesize(VIETNAMESE, self.root / "a.wav", provider="google_gemini_3_8_flash_tts",
                                       api_key=KEY, voice="Kore", language="vi")
        self.assertEqual(([request.url.path for request in self.requests], result["voice"]), (["/v1beta/interactions"], "Kore"))

    def test_the_catalog_is_kept_for_an_hour_and_a_failure_for_five_minutes(self) -> None:
        self.reply(200, {"voices": [VI_CATALOG_VOICE]})
        gemini_tts.list_voices(KEY, "vi")
        gemini_tts._voice_cache["vi-VN"]["fetched_at"] -= gemini_tts.VOICE_CACHE_SECONDS - 60
        gemini_tts.list_voices(KEY, "vi")
        self.assertEqual(len(self.requests), 1, "within the hour: the cache")
        gemini_tts._voice_cache["vi-VN"]["fetched_at"] -= 61
        self.reply(503, error(503, "unavailable", "UNAVAILABLE"))
        failed = gemini_tts.list_voices(KEY, "vi")
        self.assertEqual(len(self.requests), 2, "after the hour: asked again")
        # The refresh failed; the list read before still holds the voice a project chose.
        self.assertEqual(([voice["id"] for voice in failed["voices"]], failed["source"], failed.get("stale")),
                         (["vi-vn-advisor-6"], "api", True))
        self.assertTrue(failed["error"])
        again = gemini_tts.list_voices(KEY, "vi")
        self.assertEqual((len(self.requests), [voice["id"] for voice in again["voices"]]), (2, ["vi-vn-advisor-6"]),
                         "a failure is not asked again at once")
        self.assertEqual(gemini_tts.voice_for(KEY, "vi-vn-advisor-6", "vi"), ("vi-vn-advisor-6", ""),
                         "a voice read from the catalog before stays the voice while a refresh fails")
        self.assertEqual(len(self.requests), 2)
        gemini_tts._voice_failures["vi-VN"]["at"] -= gemini_tts.VOICE_FAILURE_SECONDS + 1
        self.reply(200, {"voices": [VI_CATALOG_VOICE]})
        self.assertEqual(gemini_tts.list_voices(KEY, "vi")["source"], "api")
        self.assertEqual((len(self.requests), gemini_tts._voice_failures), (3, {}), "five minutes on, asked again")

    def test_an_unreadable_catalog_answer_is_a_failure_not_a_crash(self) -> None:
        self.reply(200, ["not", "an", "object"])
        found = gemini_tts.list_voices(KEY, "vi")
        self.assertEqual(found["source"], "builtin")
        self.assertTrue(found["error"])

    def test_an_empty_catalog_offers_the_documented_voices_and_is_not_kept(self) -> None:
        self.reply(200, {"voices": []})
        self.reply(200, {"voices": []})
        empty = gemini_tts.list_voices(KEY, "vi")
        self.assertEqual((empty["source"], len(empty["voices"])), ("builtin", len(gemini_tts.PREBUILT_VOICES)))
        self.assertTrue(empty["error"])
        self.assertEqual(gemini_tts._voice_cache, {})


if __name__ == "__main__":
    unittest.main()
