"""Bước 4 · Giọng đọc with Gemini 3.8 TTS beside Edge: settings, the job, the worker, the page.

Edge is not replaced. Two Gemini models are added to the same pipeline: the
same render settings, the same /jobs, the same ProductionWorker, the same
timeline audio. The project's voice style is its own column (voice_style),
never voice_prompt_text, and it reaches Gemini as speech_metadata - never
the words. No call leaves the machine: Gemini answers from a MockTransport.
"""

from __future__ import annotations

import base64
import io
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
import wave
from contextlib import closing
from pathlib import Path
from unittest import mock

import httpx
from fastapi.testclient import TestClient

from tests.script_fixtures import Scripted, planned_project, write_current_script
from tests.ui_source import studio_markup, studio_ui
from youtube_monitor import gemini_tts, main, settings as app_settings, tts_catalog
from youtube_monitor.database import Database
from youtube_monitor.production_worker import ProductionWorker

KEY = "fake-gemini-key-for-tests"
STYLE = "Giọng kể chuyện tự nhiên, rõ ràng, hơi ấm, tốc độ vừa phải, nhấn mạnh các từ quan trọng."
FLASH, LITE = "google_gemini_3_8_flash_tts", "google_gemini_3_8_flash_lite_tts"


def wav_bytes(frames: int = 4800) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(24_000)
        writer.writeframes(b"\x01\x00" * frames)
    return buffer.getvalue()


def answer() -> dict:
    return {"steps": [{"type": "model_output", "content": [
        {"type": "audio", "mime_type": "audio/wav", "sample_rate": 24_000,
         "data": base64.b64encode(wav_bytes()).decode("ascii")}]}],
        "usage": {"total_input_tokens": 9, "total_output_tokens": 200, "total_tokens": 209}}


class _GeminiMock:
    """Stands in for the Gemini API: records each request, answers with a WAV (or what it is told)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.reply = lambda request: httpx.Response(200, json=answer())

    def client(self) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self.reply(request)
        return httpx.Client(transport=httpx.MockTransport(handler))

    def bodies(self) -> list[dict]:
        return [json.loads(request.content.decode("utf-8")) for request in self.requests if request.method == "POST"]

    def start(self, case: unittest.TestCase, key: str = KEY) -> "_GeminiMock":
        gemini_tts._last_failure.clear()
        gemini_tts._voice_cache.clear()
        gemini_tts._voice_failures.clear()
        for patcher in (mock.patch.object(gemini_tts, "_client_factory", self.client),
                        mock.patch.object(gemini_tts, "_sleep", lambda seconds: None),
                        mock.patch.object(app_settings, "gemini_config", return_value=(key, "img", "vid"))):
            patcher.start()
            case.addCleanup(patcher.stop)
        return self


def _ledger(database: Database, capability: str = tts_catalog.VOICE_CAPABILITY) -> list[dict]:
    with closing(sqlite3.connect(database.path)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM provider_usage_ledger WHERE capability = ? ORDER BY id", (capability,)).fetchall()
    return [{**dict(row), "metadata": json.loads(row["metadata_json"] or "{}")} for row in rows]


# ---------------------------------------------------------------------------
# The one migration of this phase
# ---------------------------------------------------------------------------

class VoiceStyleMigrationTests(unittest.TestCase):
    def test_an_existing_database_gains_voice_style_and_keeps_everything_else(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.db"
            database = Database(path)
            database.upsert_channel({"youtube_channel_id": "UC4444444444444444444444", "channel_url": "https://x"})
            database.upsert_video({"youtube_video_id": "v-migrate", "youtube_channel_id": "UC4444444444444444444444",
                                   "video_url": "https://x/v", "title": "Nguồn", "metadata_hash": "h", "raw_payload": {}})
            project = database.create_production_project("v-migrate")
            database.update_project_render_settings(
                int(project["id"]), voice_provider="voxcpm", voice_model="design:Giọng nữ ấm",
                voice_prompt_text="Xin chào. Đây là giọng đọc thử.", publish_language="vi")
            # The database as it was before this phase: no voice_style column.
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("ALTER TABLE project_render_settings DROP COLUMN voice_style")
                connection.commit()
                before = connection.execute("SELECT * FROM project_render_settings").fetchall()
                columns_before = [row[1] for row in connection.execute("PRAGMA table_info(project_render_settings)")]
                counts_before = {name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                                 for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            self.assertNotIn("voice_style", columns_before)

            Database(path)          # the app opening it: initialize() runs the migration
            Database(path)          # and again: nothing more happens

            with closing(sqlite3.connect(path)) as connection:
                info = {row[1]: (row[2], row[3], row[4]) for row in connection.execute("PRAGMA table_info(project_render_settings)")}
                after = connection.execute(f"SELECT {', '.join(columns_before)} FROM project_render_settings").fetchall()
                counts_after = {name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in counts_before}
            self.assertEqual(info["voice_style"], ("TEXT", 1, "''"))
            self.assertEqual([name for name in info if name not in columns_before], ["voice_style"])
            self.assertEqual(after, before, "every existing value as it was")
            self.assertEqual(counts_after, counts_before)
            stored = Database(path).get_project_render_settings(int(project["id"]))
            self.assertEqual((stored["voice_style"], stored["voice_prompt_text"], stored["voice_model"]),
                             ("", "Xin chào. Đây là giọng đọc thử.", "design:Giọng nữ ấm"))


class RenderSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.database = Database(Path(self._dir.name) / "s.db")
        self.database.upsert_channel({"youtube_channel_id": "UC5555555555555555555555", "channel_url": "https://x"})
        self.database.upsert_video({"youtube_video_id": "v-settings", "youtube_channel_id": "UC5555555555555555555555",
                                    "video_url": "https://x/v", "title": "Nguồn", "metadata_hash": "h", "raw_payload": {}})
        self.project_id = int(self.database.create_production_project("v-settings")["id"])

    def save(self, **values) -> dict:
        return self.database.update_project_render_settings(self.project_id, **values)

    def test_the_gemini_models_are_accepted_and_the_style_is_kept_in_its_own_column(self) -> None:
        for provider in (FLASH, LITE):
            saved = self.save(voice_provider=provider, voice_model="Puck", voice_style=STYLE, voice_prompt_text="")
            self.assertEqual((saved["voice_provider"], saved["voice_model"], saved["voice_style"], saved["voice_prompt_text"]),
                             (provider, "Puck", STYLE, ""))

    def test_saving_without_a_style_keeps_the_stored_one(self) -> None:
        self.save(voice_provider=FLASH, voice_model="Kore", voice_style=STYLE)
        kept = self.save(voice_provider="edge_tts", voice_model="vi-VN-HoaiMyNeural")
        self.assertEqual((kept["voice_provider"], kept["voice_style"]), ("edge_tts", STYLE))
        cleared = self.save(voice_provider=FLASH, voice_model="Kore", voice_style="")
        self.assertEqual(cleared["voice_style"], "")

    def test_the_style_and_voxcpms_prompt_text_never_touch(self) -> None:
        self.save(voice_provider="voxcpm", voice_model="preset:female_warm", voice_prompt_text="Xin chào. Đây là giọng đọc thử.")
        moved = self.save(voice_provider=FLASH, voice_model="Kore", voice_style=STYLE,
                          voice_prompt_text="Xin chào. Đây là giọng đọc thử.")
        self.assertEqual((moved["voice_prompt_text"], moved["voice_style"]), ("Xin chào. Đây là giọng đọc thử.", STYLE))

    def test_unknown_providers_and_overlong_styles_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.save(voice_provider="gemini_2_5_tts")
        with self.assertRaises(ValueError):
            self.save(voice_provider=FLASH, voice_model="Kore", voice_style="x" * (gemini_tts.MAX_STYLE_CHARS + 1))


# ---------------------------------------------------------------------------
# The worker: the real ProductionWorker._process, Gemini mocked at the HTTP edge
# ---------------------------------------------------------------------------

class GeminiWorkerTests(unittest.TestCase):
    LINES = [("Đây là một đoạn thử giọng đọc tiếng Việt.", "narrator"),
             ("Trái Đất tự quay quanh trục của nó, mỗi vòng mất một ngày.", "khách mời")]

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)
        self.database = Database(self.root / "w.db")
        self.database.upsert_channel({"youtube_channel_id": "UC6666666666666666666666", "channel_url": "https://x"})
        self.database.upsert_video({"youtube_video_id": "v-worker", "youtube_channel_id": "UC6666666666666666666666",
                                    "video_url": "https://x/v", "title": "Nguồn", "metadata_hash": "h", "raw_payload": {}})
        self.project = self.database.create_production_project("v-worker")
        self.script = self.database.create_project_script(self.project["id"], script_title="Kịch bản", hook="Mở đầu")
        self.database.create_project_timeline(self.project["id"], self.script["id"], [
            {"segment_index": index, "section": "main", "voice_text": text, "subtitle_text": text, "speaker": speaker,
             "visual_prompt": "x", "asset_type": "broll", "duration_seconds": 4}
            for index, (text, speaker) in enumerate(self.LINES, start=1)
        ])
        self.gemini = _GeminiMock().start(self)

    def run_job(self, provider: str, *, edge_command: str = "") -> dict:
        worker = ProductionWorker(self.database, self.root / "artifacts", edge_tts_command=edge_command)
        job = worker.enqueue(self.project["id"], self.script["id"], "voiceover", provider)
        worker._process(int(job["id"]))
        return self.database.get_project_job(int(job["id"]))

    def test_each_scene_is_read_by_the_chosen_model_in_the_projects_style(self) -> None:
        for provider, model in ((FLASH, "gemini-3.8-flash-tts"), (LITE, "gemini-3.8-flash-lite-tts")):
            with self.subTest(provider=provider):
                self.gemini.requests.clear()
                self.database.update_project_render_settings(self.project["id"], voice_provider=provider, voice_model="Puck",
                                                             voice_style=STYLE, publish_language="vi")
                job = self.run_job(provider)
                self.assertEqual(job["status"], "completed", job["error"])
                bodies = self.gemini.bodies()
                self.assertEqual(len(bodies), 2, "one request per scene")
                for body, (text, _) in zip(bodies, self.LINES):
                    self.assertEqual(body["model"], model)
                    item = body["input"][0]["content"][0]
                    self.assertEqual(item["text"], text, "the scene's words exactly - nothing added, nothing cut")
                    self.assertEqual(item["annotations"], [{"type": "speech_metadata", "style": STYLE}])
                    self.assertEqual(body["generation_config"]["speech_config"], [{"voice": "Puck", "language": "vi"}])
                for segment in self.database.list_project_timeline(self.project["id"]):
                    path = Path(segment["audio_path"])
                    self.assertEqual(path.suffix, ".wav")
                    data = path.read_bytes()
                    self.assertEqual((data[:4], data[8:12], data.count(b"RIFF")), (b"RIFF", b"WAVE", 1))
                rows = [row for row in _ledger(self.database) if row["provider"] == provider]
                self.assertEqual(len(rows), 2)
                segments = {int(segment["id"]): segment for segment in self.database.list_project_timeline(self.project["id"])}
                for row in rows:
                    meta = row["metadata"]
                    self.assertEqual((meta["vendor"], meta["model"], meta["voice"], meta["language"], meta["voice_language"], meta["style"]),
                                     ("google", model, "Puck", "vi", "vi", STYLE))
                    segment = segments[meta["segment_id"]]
                    self.assertEqual((meta["speaker"], meta["audio_path"]), (segment["speaker"], segment["audio_path"]))
                    self.assertEqual(meta["usage"]["total_tokens"], 209)
                    self.assertEqual(meta["job_id"], job["id"])

    def test_the_script_documents_spoken_lines_are_read_word_for_word_and_left_untouched(self) -> None:
        # Bước 3's ScriptDocument is where the words live. Bước 4 reads them - with the project's
        # voice_style beside them, and VoxCPM's voice_prompt_text nowhere - and changes nothing in it.
        project_id = planned_project(self.database)
        script = write_current_script(self.database, project_id)
        document = json.loads(self.database.get_project_script(int(script["id"]))["document_json"])
        spoken = [line["text"] for part in (document["hook"], *document["sections"], document["cta"])
                  for line in part["spoken_lines"]]
        self.assertTrue(spoken)
        self.database.create_project_timeline(project_id, int(script["id"]), [
            {"segment_index": index, "section": "main", "voice_text": text, "subtitle_text": text, "speaker": "narrator",
             "visual_prompt": "x", "asset_type": "broll", "duration_seconds": 4}
            for index, text in enumerate(spoken, start=1)
        ])
        prompt_text = "Xin chào. Đây là lời của file giọng mẫu VoxCPM."
        self.database.update_project_render_settings(project_id, voice_provider=LITE, voice_model="Kore", voice_style=STYLE,
                                                     voice_prompt_text=prompt_text, publish_language="vi")
        before = self.database.get_project_script(int(script["id"]))
        worker = ProductionWorker(self.database, self.root / "artifacts")
        job = worker.enqueue(project_id, int(script["id"]), "voiceover", LITE)
        worker._process(int(job["id"]))
        self.assertEqual(self.database.get_project_job(int(job["id"]))["status"], "completed")
        bodies = self.gemini.bodies()
        self.assertEqual([body["input"][0]["content"][0]["text"] for body in bodies], spoken)
        for body in bodies:
            self.assertEqual(body["input"][0]["content"][0]["annotations"], [{"type": "speech_metadata", "style": STYLE}])
            self.assertNotIn(prompt_text, json.dumps(body, ensure_ascii=False))
        after = self.database.get_project_script(int(script["id"]))
        self.assertEqual((after["document_json"], after["main_content"], after["hook"], after["cta"]),
                         (before["document_json"], before["main_content"], before["hook"], before["cta"]))

    def test_after_a_restart_with_the_catalog_down_the_job_stops_rather_than_read_in_kore(self) -> None:
        # Regression: the job used to "complete" with every scene in Kore. Now it stops on the
        # first scene with the reason, speaks nothing, and the project keeps its voice.
        self.gemini.reply = lambda request: httpx.Response(
            503, json={"error": {"code": 503, "message": "unavailable", "status": "UNAVAILABLE"}})
        self.database.update_project_render_settings(self.project["id"], voice_provider=FLASH, voice_model="vi-vn-advisor-6",
                                                     voice_style=STYLE, publish_language="vi")
        job = self.run_job(FLASH)
        self.assertEqual(job["status"], "error")
        self.assertIn("vi-vn-advisor-6", job["error"])
        self.assertIn("không bị thay", job["error"])
        self.assertNotIn(KEY, job["error"])
        self.assertNotIn("/v1beta/interactions", [request.url.path for request in self.gemini.requests])
        self.assertTrue(all(not segment.get("audio_path") for segment in self.database.list_project_timeline(self.project["id"])))
        self.assertEqual([row for row in _ledger(self.database) if row["provider"] == FLASH], [])
        self.assertEqual(self.database.get_project_render_settings(self.project["id"])["voice_model"], "vi-vn-advisor-6")

    def test_a_catalog_voice_is_still_the_voice_after_the_app_restarts(self) -> None:
        # A project saved with a catalog voice; the app restarted, so nothing has read the
        # catalog in this process. The job reads it once and speaks with that voice - not Kore -
        # named with the language the catalog lists it under.
        catalog = {"voices": [{"id": "vi-vn-advisor-6", "display_name": "Authoritative Advisor 6",
                               "language_code": "vi-VN", "gender": "male", "type": "prebuilt"}]}
        self.gemini.reply = lambda request: httpx.Response(
            200, json=catalog if request.url.path.endswith("/voices") else answer())
        self.database.update_project_render_settings(self.project["id"], voice_provider=FLASH, voice_model="vi-vn-advisor-6",
                                                     voice_style=STYLE, publish_language="vi")
        job = self.run_job(FLASH)
        self.assertEqual(job["status"], "completed", job["error"])
        paths = [request.url.path for request in self.gemini.requests]
        self.assertEqual((paths.count("/v1beta/voices"), paths.count("/v1beta/interactions")), (1, len(self.LINES)))
        for body in self.gemini.bodies():
            self.assertEqual(body["generation_config"]["speech_config"], [{"voice": "vi-vn-advisor-6", "language": "vi-VN"}])
        for row in [row for row in _ledger(self.database) if row["provider"] == FLASH]:
            meta = row["metadata"]
            self.assertEqual((meta["voice"], meta["language"], meta["voice_language"]), ("vi-vn-advisor-6", "vi", "vi-VN"))
            self.assertNotIn("voice_fallback_from", meta)

    def test_no_secret_reaches_the_job_the_files_or_the_ledger(self) -> None:
        self.database.update_project_render_settings(self.project["id"], voice_provider=FLASH, voice_model="Kore", voice_style=STYLE)
        job = self.run_job(FLASH)
        self.assertEqual(job["status"], "completed", job["error"])
        self.assertNotIn(KEY, json.dumps(job))
        self.assertNotIn(KEY, json.dumps(_ledger(self.database)))
        for path in (self.root / "artifacts").rglob("*"):
            if path.is_file():
                self.assertNotIn(KEY.encode("utf-8"), path.read_bytes(), str(path))
        for event in self.database.list_project_job_events(int(job["id"])):
            self.assertNotIn(KEY, event["message"])

    def test_a_daily_quota_fails_the_job_with_its_reason_and_records_the_limit(self) -> None:
        self.database.update_project_render_settings(self.project["id"], voice_provider=LITE, voice_model="Kore")
        details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}]}]
        self.gemini.reply = lambda request: httpx.Response(429, json={"error": {
            "code": 429, "message": "You exceeded your current quota.", "status": "RESOURCE_EXHAUSTED", "details": details}})
        recorded: list[str] = []
        with mock.patch("youtube_monitor.usage_limits._recorder", lambda provider, message, reset: recorded.append(provider)):
            job = self.run_job(LITE)
        self.assertEqual(job["status"], "error")
        self.assertIn("hết hạn mức", job["error"])
        self.assertEqual(recorded, [LITE])
        self.assertEqual(len(self.gemini.requests), 1, "a daily quota is not retried")

    def test_edge_reads_as_before_and_is_recorded_without_a_style(self) -> None:
        self.database.update_project_render_settings(self.project["id"], voice_provider="edge_tts",
                                                     voice_model="vi-VN-HoaiMyNeural", voice_style=STYLE)
        calls: list[dict] = []

        def fake_edge(template, values, cwd, require_cuda=False):
            calls.append({**values, "text": Path(values["text_file"]).read_text(encoding="utf-8")})
            Path(values["output_file"]).write_bytes(b"ID3 edge mp3")

        with mock.patch("youtube_monitor.production_worker._run_command", side_effect=fake_edge):
            job = self.run_job("edge_tts", edge_command="edge-tts --text-file {text_file} --write-media {output_file}")
        self.assertEqual(job["status"], "completed", job["error"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.gemini.requests, [], "Edge never calls Gemini")
        for values, (text, _) in zip(calls, self.LINES):
            self.assertEqual(values["voice_role"], "vi-VN-HoaiMyNeural")
            self.assertEqual(values["text"].strip(), text, "Edge reads the scene's words, and only them")
            self.assertNotIn(STYLE, json.dumps({key: str(value) for key, value in values.items()}, ensure_ascii=False))
        for segment in self.database.list_project_timeline(self.project["id"]):
            self.assertTrue(segment["audio_path"].endswith(".mp3"))
        rows = _ledger(self.database)
        self.assertEqual({(row["provider"], row["metadata"]["vendor"], row["metadata"]["model"]) for row in rows},
                         {("edge_tts", "microsoft", "edge-tts")})
        self.assertTrue(all("style" not in row["metadata"] for row in rows))


# ---------------------------------------------------------------------------
# The API the page uses
# ---------------------------------------------------------------------------

class GeminiApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._client_cm = TestClient(main.app)
        cls.client = cls._client_cm.__enter__()
        cls.database = main.database

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)

    def setUp(self) -> None:
        self.model = Scripted()
        patcher = mock.patch.object(main, "_call_orchestrator_json", self.model)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ready_project(self) -> int:
        project_id = planned_project(self.database)
        write_current_script(self.database, project_id)
        main.generate_project_shots(project_id, main.GenerateShotsRequest(force=True))
        main.generate_project_timeline(project_id, main.GenerateTimelineRequest(force=True))
        return project_id

    def test_the_render_settings_api_saves_and_returns_the_style(self) -> None:
        _GeminiMock().start(self)
        project_id = planned_project(self.database)
        saved = self.client.patch(f"/api/projects/{project_id}/render-settings", json={
            "voice_provider": FLASH, "voice_model": "Puck", "voice_style": STYLE, "publish_language": "vi"})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["settings"]["voice_style"], STYLE)
        kept = self.client.patch(f"/api/projects/{project_id}/render-settings", json={"voice_provider": "edge_tts"})
        self.assertEqual(kept.json()["settings"]["voice_style"], STYLE, "a client that does not send it keeps it")
        self.assertEqual(self.client.get(f"/api/projects/{project_id}/render-settings").json()["voice_style"], STYLE)

    def test_readiness_is_reported_with_the_production_queue_without_calling_google(self) -> None:
        gemini = _GeminiMock().start(self, key="")
        providers = {item["key"]: item for item in self.client.get("/api/production-queue").json()["tts_providers"]}
        self.assertEqual(list(providers), list(tts_catalog.STUDIO_ENGINES))
        for key in (FLASH, LITE):
            self.assertEqual((providers[key]["status"], providers[key]["status_label"], providers[key]["vendor"]),
                             ("not_configured", "Chưa cấu hình", "google"))
        self.assertEqual(gemini.requests, [])
        with mock.patch.object(app_settings, "gemini_config", return_value=(KEY, "", "")):
            providers = {item["key"]: item for item in self.client.get("/api/production-queue").json()["tts_providers"]}
        self.assertEqual(providers[FLASH]["status"], "ready")
        self.assertEqual(providers[LITE]["model"], "gemini-3.8-flash-lite-tts")
        self.assertEqual(gemini.requests, [])

    def test_a_gemini_job_without_a_key_is_refused_and_with_one_is_queued(self) -> None:
        project_id = self.ready_project()
        _GeminiMock().start(self, key="")
        refused = self.client.post(f"/api/projects/{project_id}/jobs", json={"job_type": "voiceover", "provider": FLASH, "confirmed": True})
        self.assertEqual(refused.status_code, 400)
        self.assertIn("Chưa cấu hình", refused.json()["detail"])
        with mock.patch.object(app_settings, "gemini_config", return_value=(KEY, "", "")), \
                mock.patch.object(main.production_worker, "_jobs") as queue:
            queued = self.client.post(f"/api/projects/{project_id}/jobs", json={"job_type": "voiceover", "provider": LITE, "confirmed": True})
        self.assertEqual(queued.status_code, 200, queued.text)
        job = queued.json()["job"]
        self.assertEqual((job["provider"], job["job_type"]), (LITE, "voiceover"))
        queue.put.assert_called_once()
        self.database.cancel_queued_project_job(int(job["id"]))

    def test_the_short_uses_the_same_providers(self) -> None:
        project_id = self.ready_project()
        main.write_project_short_script(project_id, main.ShortScriptRequest(seconds=30, use_model=False))
        with mock.patch.object(app_settings, "gemini_config", return_value=(KEY, "", "")), \
                mock.patch.object(main.production_worker, "_jobs"):
            queued = self.client.post(f"/api/projects/{project_id}/jobs", json={
                "job_type": "voiceover", "provider": FLASH, "confirmed": True, "variant": "short"})
        self.assertEqual(queued.status_code, 200, queued.text)
        short = self.database.get_latest_project_script(project_id, variant="short")
        self.assertEqual(int(queued.json()["job"]["script_id"]), int(short["id"]))
        self.database.cancel_queued_project_job(int(queued.json()["job"]["id"]))

    def test_the_voice_list_comes_from_the_catalog_and_edge_keeps_its_own(self) -> None:
        gemini = _GeminiMock().start(self)
        gemini.reply = lambda request: httpx.Response(200, json={"voices": [
            {"id": "Kore", "display_name": "Kore", "language_code": "vi-VN", "gender": "female", "type": "prebuilt"}]})
        body = self.client.get(f"/api/tts/voices?provider={FLASH}&language=vi").json()
        self.assertEqual((body["provider"], body["model"], body["source"], [voice["id"] for voice in body["voices"]]),
                         (FLASH, "gemini-3.8-flash-tts", "api", ["Kore"]))
        self.assertEqual(gemini.requests[0].url.params.get("language_code"), "vi-VN")
        self.assertEqual(self.client.get("/api/tts/voices?provider=voxcpm").status_code, 400)

    def test_an_audition_reads_the_fixed_sample_never_the_script_and_is_cached(self) -> None:
        project_id = self.ready_project()
        jobs_before = len(self.database.list_project_jobs(project_id))
        gemini = _GeminiMock().start(self)
        url = f"/api/voice-previews/gemini/{FLASH}?voice=Charon&style=chậm%20rãi&language=vi"
        first = self.client.get(url)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.headers["content-type"], "audio/wav")
        self.assertEqual(first.content[:4], b"RIFF")
        body = gemini.bodies()[0]
        item = body["input"][0]["content"][0]
        self.assertEqual(item["text"], main._EDGE_PREVIEW_TEXT)
        script = self.database.get_latest_project_script(project_id)
        self.assertNotIn(item["text"], str(script["main_content"]))
        self.assertEqual(item["annotations"], [{"type": "speech_metadata", "style": "chậm rãi"}])
        self.assertEqual(body["generation_config"]["speech_config"][0]["voice"], "Charon")
        self.client.get(url)
        self.assertEqual(len(gemini.requests), 1, "an audition is paid for once")
        self.assertEqual(len(self.database.list_project_jobs(project_id)), jobs_before, "no production job")
        previews = [row for row in _ledger(self.database, tts_catalog.PREVIEW_CAPABILITY) if row["metadata"].get("voice") == "Charon"]
        self.assertEqual(previews[-1]["metadata"]["model"], "gemini-3.8-flash-tts")
        with mock.patch.object(app_settings, "gemini_config", return_value=("", "", "")):
            self.assertEqual(self.client.get(f"/api/voice-previews/gemini/{LITE}?voice=Kore").status_code, 400)
        self.assertEqual(self.client.get("/api/voice-previews/gemini/edge_tts").status_code, 404)

    def test_an_audition_of_a_catalog_voice_uses_that_voice_after_a_restart(self) -> None:
        # Nothing has read the catalog in this process yet; the audition reads it rather than
        # quietly auditioning Kore, and names the voice with the language the catalog lists.
        gemini = _GeminiMock().start(self)
        catalog = {"voices": [{"id": "vi-vn-advisor-6", "display_name": "Authoritative Advisor 6",
                               "language_code": "vi-VN", "gender": "male", "type": "prebuilt"}]}
        gemini.reply = lambda request: httpx.Response(
            200, json=catalog if request.url.path.endswith("/voices") else answer())
        response = self.client.get(f"/api/voice-previews/gemini/{LITE}?voice=vi-vn-advisor-6&language=vi")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([request.url.path for request in gemini.requests], ["/v1beta/voices", "/v1beta/interactions"])
        self.assertEqual(gemini.bodies()[-1]["generation_config"]["speech_config"],
                         [{"voice": "vi-vn-advisor-6", "language": "vi-VN"}])
        preview = _ledger(self.database, tts_catalog.PREVIEW_CAPABILITY)[-1]["metadata"]
        self.assertEqual((preview["voice"], preview["voice_fallback_from"], preview["language"], preview["voice_language"]),
                         ("vi-vn-advisor-6", "", "vi", "vi-VN"))

    def test_an_audition_after_a_restart_with_the_catalog_down_is_refused_not_played_in_kore(self) -> None:
        gemini = _GeminiMock().start(self)
        gemini.reply = lambda request: httpx.Response(
            503, json={"error": {"code": 503, "message": "unavailable", "status": "UNAVAILABLE"}})
        style = "thử khi danh mục giọng không đọc được"
        previews_before = len(_ledger(self.database, tts_catalog.PREVIEW_CAPABILITY))
        response = self.client.get(f"/api/voice-previews/gemini/{FLASH}", params={"voice": "vi-vn-advisor-6", "style": style, "language": "vi"})
        self.assertEqual(response.status_code, 502, response.text)
        self.assertIn("vi-vn-advisor-6", response.json()["detail"])
        self.assertNotIn(KEY, response.text)
        self.assertEqual([request.url.path for request in gemini.requests], ["/v1beta/voices"], "nothing is spoken")
        self.assertEqual(len(_ledger(self.database, tts_catalog.PREVIEW_CAPABILITY)), previews_before)
        for voice in ("vi-vn-advisor-6", "Kore"):
            self.assertFalse(main._gemini_voice_preview_path(FLASH, voice, style, "vi").exists())


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

def _step4(markup: str) -> str:
    return markup[markup.index('<div id="studioStep4"'):markup.index('<div id="studioStep5"')]


class StepFourPageTests(unittest.TestCase):
    def test_provider_model_voice_style_and_preview_are_offered(self) -> None:
        step = _step4(studio_markup())
        provider = step[step.index('<select id="studioVoiceProviderSelect">'):]
        provider = provider[:provider.index("</select>")]
        self.assertEqual(re.findall(r'<optgroup label="([^"]+)"', provider), ["Microsoft", "Google Gemini", "Local GPU"])
        self.assertEqual(re.findall(r'<option value="([^"]+)"', provider),
                         ["edge_tts", FLASH, LITE, "pyvideotrans", "voxcpm"])
        self.assertIn(f'id="studioGeminiVoiceGroup" label="Google Gemini · giọng dựng sẵn" data-voice-providers="{FLASH} {LITE}"', step)
        style = step[step.index(f'<section class="voice-panel voice-style" data-voice-provider-panel="{FLASH} {LITE}" hidden'):]
        style = style[:style.index("</section>")]
        self.assertIn('<label class="voice-sr-only" for="studioVoiceStyleInput">Kiểu đọc / phong cách</label><textarea id="studioVoiceStyleInput"', style,
                      "the style box is shown for the Gemini models only")
        self.assertIn('<input id="studioVoicePromptText" type="hidden" />', step, "VoxCPM's field is untouched")
        self.assertEqual(step.count('onclick="previewStudioSelectedVoice()"'), 1, "one Nghe thử for every engine")

    def test_the_desk_is_engines_voices_current_style_or_speed_player_advanced_and_save(self) -> None:
        """Bước 4, the minimal desk: what is chosen, what to pick, how it is read, a player, one save."""
        step = _step4(studio_markup())
        header = step[step.index('<div class="voice-head">'):step.index('<div id="studioVoiceProjectNotice"')]
        self.assertIn("<h3>Bước 4 · Giọng đọc</h3><p>Chọn giọng và cách đọc cho video.</p>", header)
        self.assertIn('<li class="now" aria-current="step"><b>4</b><span>Giọng đọc</span></li>', header)
        for wanted in ('id="studioVoiceEngineCards"', 'id="studioVoiceLocalChoice"', 'id="studioVoiceList" class="voice-list" role="listbox"',
                       'id="studioVoiceSearch"', 'data-voice-gender="male"', 'data-voice-gender="female"', 'data-voice-gender="other"',
                       'id="studioVoiceCurrent"', 'id="studioVoiceSavedBadge"', 'id="studioVoiceRateRange"', 'id="studioVoicePreviewBar"',
                       'id="studioVoicePreviewTime"', 'id="studioVoicePreviewState"', '<details class="voice-panel voice-advanced">',
                       '<details class="voice-tech"><summary>Chi tiết kỹ thuật</summary>', 'id="studioSaveVoiceButton" class="btn voice-save"',
                       'Chưa mở dự án · thay đổi chỉ để xem thử'):
            with self.subTest(wanted=wanted):
                self.assertIn(wanted, step)
        # The form controls the desk draws from are all still there, out of sight behind it.
        source = step[step.index('<div class="voice-source" hidden>'):]
        source = source[:source.index("</details>")]
        for control in ("studioVoiceProviderSelect", "studioVoiceModelSelect", "studioVoiceReferenceAsset", "studioVoiceRateSelect"):
            with self.subTest(control=control):
                self.assertIn(f'id="{control}"', source)
        for control in ("studioVoiceModelSelect", "studioVoiceRateSelect", "studioVoiceStyleInput", "studioSubtitleModelSelect",
                        "studioPublishLanguageSelect", "studioVoiceReferenceAsset", "studioGenerateVoicePreviewsButton",
                        "studioGenerateVoiceoverButton", "studioReviewVoiceButton", "studioVoiceSummary"):
            with self.subTest(control=control):
                self.assertEqual(step.count(f'id="{control}"'), 1)
        # Style for Gemini, speed for Edge and the local engines - the same place, never both.
        self.assertIn(f'data-voice-provider-panel="{FLASH} {LITE}" hidden aria-labelledby="studioVoiceStyleTitle"', step)
        self.assertIn('data-voice-provider-panel="edge_tts pyvideotrans voxcpm" aria-labelledby="studioVoiceSpeedTitle"', step)
        self.assertIn('<div class="voice-advanced-row" data-voice-provider-panel="voxcpm" hidden>', step, "VoxCPM's tools, for VoxCPM, under Nâng cao")
        self.assertIn('onclick="reattachStudioVoice()"', step)
        # One primary action; the rest weigh less.
        actions = step[step.index('<div class="voice-actions">'):]
        actions = actions[:actions.index("</div>")]
        self.assertEqual(actions.count("btn primary"), 0)
        self.assertEqual(actions.count("voice-save"), 1)
        presets = re.findall(r'data-voice-style="([^"]+)" aria-pressed="false">([^<]+)<', step)
        self.assertEqual([name for _, name in presets], ["Tự nhiên", "Thân thiện", "Tin tức", "Chuyên nghiệp", "Năng lượng", "Điềm tĩnh", "Kể chuyện"])
        self.assertNotIn("vi-vn-advisor", step, "no Gemini voice is written into the page")

    def test_the_desk_says_little(self) -> None:
        """A production desk, not documentation: no catalog, model or tips blocks, no internals on show."""
        step = _step4(studio_markup())
        pane = step[step.index('data-lane-step="studioStep4" data-lane="long">'):step.index('<div class="studio-lane-pane" data-lane-step="studioStep4" data-lane="short"')]
        # What is shown by default: the markup without the folded Nâng cao, the hidden form, tooltips and options.
        shown = re.sub(r'<details class="voice-panel voice-advanced">.*?</details>\s*</div>', "", pane, flags=re.S)
        shown = re.sub(r'<label class="voice-sr-only".*?</label>|<details id="studioVoicePreviewDetail".*?</details>', "", shown, flags=re.S)
        shown = re.sub(r"<(select|textarea)\b.*?</\1>", "", shown, flags=re.S)
        shown = re.sub(r"<[^>]+>", " ", shown)
        words = re.sub(r"\s+", " ", shown).strip()
        self.assertLess(len(words), 560, words)
        for gone in ("Danh mục giọng", "Thông tin model", "Mẹo sử dụng", "speech_metadata", "lưu đệm", "1 giờ", "token", "24 kHz", "WAV",
                     "Chia kịch bản thành cảnh, chọn một model"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, words)

    def test_the_desk_is_a_view_over_the_form_and_saves_only_what_the_server_confirms(self) -> None:
        ui = studio_ui()
        sync = ui[ui.index("  function syncStudioVoiceModelOptions() {"):ui.index("  function syncStudioSubtitleOptions() {")]
        self.assertIn("if (typeof renderStudioVoiceDesk === 'function') renderStudioVoiceDesk();", sync)
        hydrate = ui[ui.index("async function hydrateStudioVoiceSettings() {"):ui.index("async function refreshStudioVoicePreviews() {")]
        self.assertIn("rememberStudioVoiceSaved(state.studioProjectId, settings);", hydrate)
        save = ui[ui.index("async function saveRenderSettings(projectId"):]
        save = save[:save.index("\n  }\n")]
        self.assertIn("rememberStudioVoiceSaved(projectId, response.settings);", save)
        self.assertIn("return response.settings || null;", save)
        self.assertIn("return null; }", save, "a failed save is not reported as saved")
        studio_save = ui[ui.index("async function saveStudioVoiceSettings() {"):ui.index("async function generateStudioVoiceover() {")]
        self.assertIn("await (state.geminiVoicesLoading || Promise.resolve());", studio_save,
                      "the save waits for the Gemini voice list, as the provider change does")
        self.assertIn("if (!saved) {", studio_save)
        engine = ui[ui.index("function chooseStudioVoiceEngine(key) {"):ui.index("function chooseStudioVoice(value) {")]
        self.assertIn("select.dispatchEvent(new Event('change', {bubbles: true}));", engine,
                      "a card goes through the provider select's own change: its save-after-load stays the only path")

    def test_the_voice_desk_is_run_against_a_scripted_page(self) -> None:
        """The desk itself, in node: cards, readiness, list, filters, status, save state, catalog, presets."""
        node = shutil.which("node")
        if not node:
            self.skipTest("node không có trên máy chạy test")
        script = Path(__file__).with_name("step4_voice_desk.test.cjs")
        result = subprocess.run([node, "--test", str(script)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_page_reads_readiness_and_voices_from_the_server(self) -> None:
        ui = studio_ui()
        sync = ui[ui.index("function syncStudioGeminiTts() {"):ui.index("async function previewStudioSelectedVoice()")]
        self.assertIn("state.productionQueue?.tts_providers", ui)
        self.assertIn("option.disabled = Boolean(status) && ['not_configured', 'quota'].includes(status.status);", sync)
        self.assertIn("return loadGeminiVoices(provider);", sync)
        load = ui[ui.index("function loadGeminiVoices(provider) {"):ui.index("function voiceLocaleLabel(")]
        self.assertIn("/api/tts/voices?provider=", load)
        # A project's provider change is saved only once the Gemini voice list has loaded and
        # a voice is chosen: saving at once stored the placeholder (Kore) while the list then
        # showed another voice - seen on a real project during the Bước 4 review.
        listener = ui[ui.index("$('studioVoiceProviderSelect')?.addEventListener('change', () => {"):]
        listener = listener[:listener.index("});")]
        self.assertIn("const voices = syncStudioGeminiTts();", listener)
        self.assertIn("void Promise.resolve(voices).then(() => saveRenderSettings(projectId, {quiet: true}));", listener)
        self.assertNotIn("void saveRenderSettings(", listener)
        hydrate = ui[ui.index("modelSelect.value = modelValue;"):]
        self.assertIn("modelSelect.selectedOptions[0].dataset.stored = '1';", hydrate[:600])
        # Opening the page asks Google nothing: the catalog is read only once a Gemini model is picked.
        boot = ui[ui.index("loadHealth(), loadWorkflows(), loadEdgeVoices()"):]
        self.assertNotIn("loadGeminiVoices", boot[:boot.index("\n")])
        preview = ui[ui.index("async function previewStudioSelectedVoice() {"):]
        preview = preview[:preview.index("if (provider === 'edge_tts' || provider === 'pyvideotrans')")]
        self.assertIn("/api/voice-previews/gemini/", preview)
        self.assertIn("style: $('studioVoiceStyleInput')?.value", preview)

    def test_the_style_is_saved_with_the_settings_and_left_alone_elsewhere(self) -> None:
        ui = studio_ui()
        self.assertIn("voice_style: usingStudio && $('studioVoiceStyleInput') ? $('studioVoiceStyleInput').value : undefined,", ui)
        self.assertIn("if ($('studioVoiceStyleInput')) $('studioVoiceStyleInput').value = settings.voice_style || '';", ui)
        self.assertIn("$('studioVoiceStyleInput')?.addEventListener('change'", ui)
        panels = ui[ui.index("document.querySelectorAll('[data-voice-provider-panel]')"):]
        self.assertIn(".split(/\\s+/).includes(provider)", panels[:300])

    def test_the_voice_list_is_run_against_a_catalog_without_the_default_voice(self) -> None:
        """loadGeminiVoices itself, run in node against Google's real vi-VN shape (no Kore in it)."""
        node = shutil.which("node")
        if not node:
            self.skipTest("node không có trên máy chạy test")
        script = Path(__file__).with_name("step4_gemini_voices.test.cjs")
        result = subprocess.run([node, "--test", str(script)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
