from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import mimetypes
import os
import re
import shlex
import shutil
import subprocess
import threading
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import File, Form, FastAPI, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field

from .analysis_queue import AnalysisQueue
from . import settings
from .antigravity_bridge import antigravity_cli_status
from .claude_code_bridge import claude_code_cli_status
from .codex_bridge import CodexBridgeError, call_codex_vision_json, codex_cli_status, launch_codex_login
from .database import Database
from .director import DirectorError, director_to_markdown, director_to_script, director_to_shots, generate_director_draft
from .ffmpeg_renderer import ffmpeg_available, media_duration_seconds, nvenc_available
from . import operations, usage_limits
from . import languages
from .fidelity_guard import unsourced_details
from .gif_generator import GFLOW_GIF_FRAME_COUNT, GifGenerationError, materialize_gif_asset
from .gflow_bridge import gflow_cli_status
from .llm_analyzer import LlmAnalysisError, resolve_analyzer
from .llm_client import LlmError, call_antigravity_json, call_claude_code_cli_json, call_codex_json
from .maintenance import list_database_backups, prune_database_backups
from .oauth import OAuthError
from .oauth import build_authorize_url as build_oauth_authorize_url
from .oauth import disconnect as oauth_disconnect
from .oauth import exchange_code as oauth_exchange_code
from .oauth import status as oauth_status
from .openmontage_adapter import OpenMontageAdapter, OpenMontageError, runtime_for_provider
from .production_worker import (
    ProductionJobError,
    ProductionWorker,
    VOXCPM_PREVIEW_TEXT,
    VOXCPM_VOICE_PRESETS,
)
from .publisher import PublisherError, PublisherWorker, next_channel_schedule
from .project_layout import ensure_project_layout
from .quality_check import build_quality_report
from .scene_generator import SceneGenerationError, SceneGenerationWorker
from .thumbnail_generator import ThumbnailGenerationError, generate_frame_thumbnails
from .premiere_export import build_premiere_export_package
from .service import SyncService, parse_push_feed
from .settings import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    DB_PATH,
    EDGE_TTS_COMMAND,
    EDGE_TTS_RUNTIME_READY,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    FFMPEG_RENDER_COMMAND,
    FFMPEG_BINARY,
    LOCAL_ASSET_MAX_BYTES,
    PRODUCTION_ARTIFACT_DIR,
    PYVIDEOTRANS_COMMAND,
    PYVIDEOTRANS_RUNTIME_READY,
    PYVIDEOTRANS_TTS_TYPE,
    PYVIDEOTRANS_VOICE_ROLE,
    PYVIDEOTRANS_WORKDIR,
    VOXCPM_DEVICE,
    VOXCPM_MODEL,
    VOXCPM_PROMPT_TEXT,
    VOXCPM_PYTHON,
    VOXCPM_REFERENCE_AUDIO,
    VOXCPM_RUNNER,
    VOXCPM_RUNTIME_READY,
    SYSTEM_ROOT,
    YOUTUBE_API_KEY,
    YOUTUBE_MAX_INITIAL_VIDEOS,
    YOUTUBE_PUSH_VERIFY_TOKEN,
)
from .script_builder import build_script_draft, script_to_markdown
from .shot_planner import build_shot_plan, shots_to_markdown
from .timeline_builder import build_timeline, timeline_to_manifest, timeline_to_markdown
from .transcriber import (
    TranscriptionError,
    resolve_whisper_runtime,
    save_asset_transcript_result,
    save_transcript_result,
    transcribe_local_file,
    transcribe_video,
)
from .transcript import normalize_transcript
from .transcript_queue import TranscriptQueue
from .video_downloader import VideoDownloadError, delete_downloaded_video, download_video
from .writer import WriterError, resolve_target_duration_seconds, resolve_writer, revise_script, validate_voiceover_plan
from .folklore_research import research_folklore_remake
from .reference_analyzer import ReferenceAnalysisError, analyze_reference
from .youtube_captions import CaptionsError, download_caption, list_captions
from .youtube_client import YouTubeApiError, YouTubeClient


database = Database(DB_PATH)

# Running out of a subscription is a normal weekly event here, not a bug, and
# it used to vanish into a job's error column while the orchestrator quietly
# fell back to another agent. The bridges sit below this layer, so they are
# handed somewhere to write what they notice.
usage_limits.set_sink(
    database.record_provider_usage_limit,
    database.clear_provider_usage_limit,
)
youtube = YouTubeClient(YOUTUBE_API_KEY)
service = SyncService(database, youtube, YOUTUBE_MAX_INITIAL_VIDEOS)
metadata_queue = AnalysisQueue(database)
transcript_queue = TranscriptQueue(database)
openmontage_adapter = OpenMontageAdapter(
    settings.OPENMONTAGE_ROOT,
    settings.OPENMONTAGE_PYTHON,
    settings.OPENMONTAGE_RENDER_RUNTIME,
    FFMPEG_BINARY,
    settings.OPENMONTAGE_TIMEOUT_SECONDS,
)
production_worker = ProductionWorker(
    database,
    PRODUCTION_ARTIFACT_DIR,
    pyvideotrans_command=PYVIDEOTRANS_COMMAND,
    edge_tts_command=EDGE_TTS_COMMAND,
    ffmpeg_command=FFMPEG_RENDER_COMMAND,
    ffmpeg_binary=FFMPEG_BINARY,
    pyvideotrans_workdir=PYVIDEOTRANS_WORKDIR,
    pyvideotrans_voice_role=PYVIDEOTRANS_VOICE_ROLE,
    pyvideotrans_tts_type=PYVIDEOTRANS_TTS_TYPE,
    voxcpm_python=str(VOXCPM_PYTHON),
    voxcpm_runner=str(VOXCPM_RUNNER),
    voxcpm_model=VOXCPM_MODEL,
    voxcpm_device=VOXCPM_DEVICE,
    voxcpm_reference_audio=VOXCPM_REFERENCE_AUDIO,
    voxcpm_prompt_text=VOXCPM_PROMPT_TEXT,
    openmontage_adapter=openmontage_adapter,
)
publisher_worker = PublisherWorker(database)
scene_generation_worker = SceneGenerationWorker(database, PRODUCTION_ARTIFACT_DIR)
template_path = Path(__file__).resolve().parent / "templates" / "index.html"

# Tracks the last time each external-sidecar provider (Antigravity/Flow/Meta
# AI) actually polled for work, so the UI can tell "queued, waiting for a
# sidecar that isn't running" apart from "queued, sidecar will pick it up in
# a few seconds" instead of just sitting at an unmoving progress bar. Reset
# on every app restart by design — a fresh process has no sidecar sightings
# yet, which is the correct "unknown" state until one polls in.
_sidecar_last_seen: dict[str, datetime] = {}
_SIDECAR_STALE_AFTER_SECONDS = 30  # polls happen every 5-10s when idle


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class BrowserLeaseMonitor:
    """Tự dừng server local khi không còn tab giao diện nào giữ heartbeat."""

    def __init__(self) -> None:
        self.enabled = _env_bool("YOUTUBE_AUTO_CLOSE_ON_BROWSER_EXIT", False)
        self.idle_seconds = max(15.0, float(os.getenv("YOUTUBE_BROWSER_IDLE_SECONDS", "45")))
        self.close_grace_seconds = max(5.0, float(os.getenv("YOUTUBE_BROWSER_CLOSE_GRACE_SECONDS", "10")))
        self._leases: dict[str, float] = {}
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._browser_seen = False
        self._empty_since: float | None = None
        self._closing = False

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="browser-lease-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def heartbeat(self, client_id: str, status: Literal["online", "offline"]) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        with self._lock:
            self._browser_seen = True
            if status == "offline":
                self._leases.pop(client_id, None)
            else:
                self._leases[client_id] = now
            self._empty_since = None if self._leases else (self._empty_since or now)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "browser_seen": self._browser_seen,
                "active_clients": len(self._leases),
                "idle_seconds": self.idle_seconds,
                "close_grace_seconds": self.close_grace_seconds,
            }

    def _run(self) -> None:
        while not self._stop_event.wait(5.0):
            now = time.monotonic()
            should_close = False
            with self._lock:
                stale = [client_id for client_id, last_seen in self._leases.items() if now - last_seen > self.idle_seconds]
                for client_id in stale:
                    self._leases.pop(client_id, None)
                if self._browser_seen and not self._leases:
                    self._empty_since = self._empty_since or now
                    should_close = now - self._empty_since >= self.close_grace_seconds
                else:
                    self._empty_since = None
            if should_close:
                self._shutdown_process()
                return

    def _shutdown_process(self) -> None:
        with self._lock:
            if self._closing:
                return
            self._closing = True
        _stop_runtime_workers()
        os._exit(0)


_runtime_stop_lock = threading.Lock()
_runtime_workers_stopped = False


def _stop_runtime_workers() -> None:
    global _runtime_workers_stopped
    with _runtime_stop_lock:
        if _runtime_workers_stopped:
            return
        _runtime_workers_stopped = True
        scene_generation_worker.stop()
        publisher_worker.stop()
        production_worker.stop()
        metadata_queue.stop()
        transcript_queue.stop()


browser_lease_monitor = BrowserLeaseMonitor()


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    metadata_queue.start()
    transcript_queue.start()
    production_worker.start()
    publisher_worker.start()
    scene_generation_worker.start()
    browser_lease_monitor.start()
    try:
        yield
    finally:
        browser_lease_monitor.stop()
        _stop_runtime_workers()


app = FastAPI(title="YouTube AI Factory - Monitor", version="0.1.0", lifespan=lifespan)


class AddChannelRequest(BaseModel):
    reference: str = Field(min_length=1, max_length=500)
    group_name: str = Field(default="", max_length=100)
    max_videos: int | None = Field(default=None, ge=1, le=5000)


class ImportVideoRequest(BaseModel):
    reference: str = Field(min_length=1, max_length=500)
    group_name: str = Field(default="", max_length=100)


class TrackingRequest(BaseModel):
    enabled: bool


class ChannelGroupRequest(BaseModel):
    group_name: str = Field(default="", max_length=100)


class ManagedChannelRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    channel_url: str = Field(min_length=1, max_length=500)
    youtube_channel_id: str = Field(default="", max_length=200)
    group_name: str = Field(default="", max_length=100)
    workflow_reference_channel_id: str = Field(default="", max_length=200)
    output_profile: Literal["youtube_landscape", "youtube_shorts", "instagram_reels", "tiktok"] = "youtube_landscape"
    language: str = Field(default="vi", max_length=20)
    default_voice_provider: Literal["edge_tts", "pyvideotrans", "voxcpm"] = "edge_tts"
    default_voice_model: str = Field(default="vi-VN-HoaiMyNeural", min_length=1, max_length=120)
    default_subtitle_provider: Literal["timeline_text", "faster_whisper_local"] = "timeline_text"
    default_subtitle_model: str = Field(default="timeline", min_length=1, max_length=120)
    default_transition_style: Literal["none", "fade"] = "fade"
    notes: str = Field(default="", max_length=5000)
    enabled: bool = True
    schedule_enabled: bool = False
    schedule_frequency: Literal["daily", "weekdays", "weekly", "monthly"] = "weekly"
    schedule_time: str = Field(default="19:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    schedule_timezone: str = Field(default="Asia/Bangkok", max_length=60)
    schedule_days: str = Field(default="mon", max_length=50)
    default_privacy: Literal["private", "unlisted", "public"] = "private"
    auto_upload: bool = False


class ManagedChannelUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    channel_url: str | None = Field(default=None, min_length=1, max_length=500)
    youtube_channel_id: str | None = Field(default=None, max_length=200)
    group_name: str | None = Field(default=None, max_length=100)
    workflow_reference_channel_id: str | None = Field(default=None, max_length=200)
    output_profile: Literal["youtube_landscape", "youtube_shorts", "instagram_reels", "tiktok"] | None = None
    language: str | None = Field(default=None, max_length=20)
    default_voice_provider: Literal["edge_tts", "pyvideotrans", "voxcpm"] | None = None
    default_voice_model: str | None = Field(default=None, min_length=1, max_length=120)
    default_subtitle_provider: Literal["timeline_text", "faster_whisper_local"] | None = None
    default_subtitle_model: str | None = Field(default=None, min_length=1, max_length=120)
    default_transition_style: Literal["none", "fade"] | None = None
    notes: str | None = Field(default=None, max_length=5000)
    enabled: bool | None = None
    schedule_enabled: bool | None = None
    schedule_frequency: Literal["daily", "weekdays", "weekly", "monthly"] | None = None
    schedule_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    schedule_timezone: str | None = Field(default=None, max_length=60)
    schedule_days: str | None = Field(default=None, max_length=50)
    default_privacy: Literal["private", "unlisted", "public"] | None = None
    auto_upload: bool | None = None


class QueueAnalysisRequest(BaseModel):
    channel_id: str | None = None
    limit: int = Field(default=100, ge=1, le=500)
    force: bool = False
    provider: str | None = None
    video_ids: list[str] | None = Field(default=None, max_length=200)


class QueuePauseRequest(BaseModel):
    paused: bool


class TranscriptRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    source_type: Literal["manual", "authorized_caption", "uploaded_file"] = "manual"
    language: str = Field(default="", max_length=20)
    transcript_format: Literal["txt", "srt", "vtt"] = "txt"


class AutoTranscriptRequest(BaseModel):
    language: str = Field(default="", max_length=20)
    confirmed: bool = False


class QueueTranscriptRequest(BaseModel):
    channel_id: str | None = None
    limit: int = Field(default=10, ge=1, le=200)
    force: bool = False
    video_ids: list[str] | None = Field(default=None, max_length=200)
    confirmed: bool = False


class WriterRequest(BaseModel):
    provider: str | None = None
    managed_channel_id: int | None = Field(default=None, ge=1)
    creative_direction: str = Field(default="", max_length=4000)
    remake_mode: Literal["new_story_same_feeling", "new_angle_same_topic", "style_only", "faithful_retell"] = "new_angle_same_topic"
    output_language: str = Field(default=languages.DEFAULT_LANGUAGE, max_length=12)
    target_duration_seconds: int | None = Field(default=None, ge=30, le=1800)
    target_duration_text: str = Field(default="", max_length=40)
    use_web_research: bool = True


class ScriptChatRequest(BaseModel):
    provider: str | None = None
    message: str = Field(min_length=1, max_length=10_000)


class CaptionImportRequest(BaseModel):
    caption_id: str = Field(min_length=1, max_length=200)
    language: str = Field(default="", max_length=20)


ProjectStatus = Literal["draft", "script", "review", "approved", "archived"]
ScriptStatus = Literal["draft", "review", "approved"]
ShotStatus = Literal["planned", "ready", "done"]
TimelineStatus = Literal["planned", "voice_ready", "asset_ready", "ready", "done"]


class CreateProjectRequest(BaseModel):
    title: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=5000)
    managed_channel_id: int | None = Field(default=None, ge=1)


class UpdateProjectRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    status: ProjectStatus | None = None
    notes: str | None = Field(default=None, max_length=5000)
    managed_channel_id: int | None = Field(default=None, ge=1)


class UpdateScriptRequest(BaseModel):
    script_title: str | None = Field(default=None, max_length=300)
    hook: str | None = Field(default=None, max_length=5000)
    intro: str | None = Field(default=None, max_length=20_000)
    main_content: str | None = Field(default=None, max_length=200_000)
    cta: str | None = Field(default=None, max_length=5000)
    status: ScriptStatus | None = None


class GenerateShotsRequest(BaseModel):
    force: bool = False


class UpdateShotRequest(BaseModel):
    narration: str | None = Field(default=None, max_length=20_000)
    visual_prompt: str | None = Field(default=None, max_length=20_000)
    asset_type: str | None = Field(default=None, max_length=50)
    duration_seconds: int | None = Field(default=None, ge=1, le=3600)
    status: ShotStatus | None = None


class CreateShotRequest(BaseModel):
    section: str = Field(default="main", max_length=60)
    narration: str = Field(default="", max_length=20_000)
    visual_prompt: str = Field(default="", max_length=20_000)
    asset_type: str = Field(default="broll", max_length=50)
    duration_seconds: int = Field(default=8, ge=1, le=3600)
    status: ShotStatus = "planned"


class ReorderShotsRequest(BaseModel):
    shot_ids: list[int] = Field(min_length=1, max_length=500)


class GenerateTimelineRequest(BaseModel):
    force: bool = False


class UpdateTimelineRequest(BaseModel):
    voice_text: str | None = Field(default=None, max_length=20_000)
    subtitle_text: str | None = Field(default=None, max_length=20_000)
    visual_prompt: str | None = Field(default=None, max_length=20_000)
    asset_type: str | None = Field(default=None, max_length=50)
    duration_seconds: int | None = Field(default=None, ge=1, le=3600)
    audio_path: str | None = Field(default=None, max_length=1000)
    visual_path: str | None = Field(default=None, max_length=1000)
    status: TimelineStatus | None = None


class RenderSettingsRequest(BaseModel):
    music_asset_id: int | None = Field(default=None, ge=1)
    music_volume: float = Field(default=0.12, ge=0.0, le=0.5)
    transition_style: Literal["none", "fade"] = "fade"
    output_profile: Literal["youtube_landscape", "youtube_shorts", "instagram_reels", "tiktok"] = "youtube_landscape"
    voice_provider: Literal["edge_tts", "pyvideotrans", "voxcpm"] = "edge_tts"
    voice_model: str = Field(default="vi-VN-HoaiMyNeural", min_length=1, max_length=120)
    voice_rate: Literal["-25%", "-15%", "-8%", "+0%", "+8%", "+15%", "+25%"] = "+0%"
    voice_reference_asset_id: int | None = Field(default=None, ge=1)
    voice_prompt_text: str = Field(default="", max_length=5000)
    subtitle_provider: Literal["timeline_text", "faster_whisper_local"] = "timeline_text"
    subtitle_model: str = Field(default="timeline", min_length=1, max_length=120)
    publish_language: Literal["vi", "en", "th", "pt-BR", "es", "fr", "de", "ja", "ko", "zh-CN", "id"] = "vi"


class GenerateThumbnailsRequest(BaseModel):
    prompt: str = Field(default="", max_length=5_000)
    seed: int | None = None
    variants: int = Field(default=3, ge=1, le=6)


ProductionJobType = Literal["voiceover", "voiceover_segment", "source_visuals", "render", "premiere_draft", "director_production"]


class CreateProductionJobRequest(BaseModel):
    job_type: ProductionJobType
    provider: str = Field(default="dry_run", min_length=1, max_length=50)
    force: bool = False
    confirmed: bool = False
    segment_id: int | None = Field(default=None, ge=1)


class CreatePublicationRequest(BaseModel):
    managed_channel_id: int | None = Field(default=None, ge=1)
    thumbnail_asset_id: int | None = Field(default=None, ge=1)
    title: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=500)
    category_id: str = Field(default="27", min_length=1, max_length=10)
    privacy_status: Literal["private", "unlisted", "public"] | None = None
    scheduled_at: str | None = Field(default=None, max_length=80)
    confirmed: bool = False


DirectorProvider = Literal["codex_cli", "openai_gpt", "anthropic_claude", "claude_code_cli", "antigravity"]


class DirectorDraftRequest(BaseModel):
    provider: DirectorProvider = "codex_cli"
    creative_direction: str = Field(default="", max_length=4000)
    remake_mode: Literal["new_story_same_feeling", "new_angle_same_topic", "style_only", "faithful_retell"] = "new_angle_same_topic"
    output_language: str = Field(default=languages.DEFAULT_LANGUAGE, max_length=12)
    target_duration_seconds: int | None = Field(default=None, ge=30, le=1800)
    target_duration_text: str = Field(default="", max_length=40)
    use_web_research: bool = True
    auto_produce: bool = False
    confirmed: bool = False


class PauseProductionQueueRequest(BaseModel):
    paused: bool


class PremiereExportRequest(BaseModel):
    force: bool = False


AssetType = Literal["video", "audio", "image"]


class AttachAssetRequest(BaseModel):
    asset_id: int = Field(ge=1)


class CreateSceneGenerationRequest(BaseModel):
    timeline_segment_id: int = Field(ge=1)
    provider: Literal["openai_image", "gemini_image", "gemini_veo", "runway", "antigravity_image", "gflow_cli", "gflow_image", "flow_veo", "flow_image", "meta_ai_video", "gemini_web_image", "chatgpt_web_image"] = "gemini_image"
    prompt: str = Field(min_length=3, max_length=20_000)
    duration_seconds: int = Field(default=5, ge=1, le=30)
    ratio: Literal["1280:720", "720:1280", "1024:1024"] = "1280:720"
    reference_asset_id: int | None = Field(default=None, ge=1)
    requires_reference_image: bool = False
    motion_as_gif: bool = False
    confirmed: bool = False


SceneProvider = Literal[
    "openai_image", "gemini_image", "gemini_veo", "runway", "antigravity_image",
    "gflow_cli", "gflow_image", "flow_veo", "flow_image", "meta_ai_video", "gemini_web_image", "chatgpt_web_image",
]


class BatchSceneGenerationRequest(BaseModel):
    provider: SceneProvider = "gemini_image"
    # Spreading a batch over several providers is what makes it run in
    # parallel: the extension already handles concurrent jobs, but every
    # scene going to the same site queues behind one tab.
    providers: list[SceneProvider] = Field(default_factory=list)
    # Honour each scene's planned visual_kind (see plan-visuals), routing
    # still scenes to image tools and moving ones to video tools, instead of
    # sending every scene to the same kind of provider.
    respect_plan: bool = False
    # Replace every planned GIF/video scene with an image-provider job that
    # creates a 2x2 animation sheet. The app cuts its four AI-created frames
    # into a GIF locally. No video provider is called.
    motion_as_gif: bool = False
    # Useful for orchestrated smoke tests: exercise a few providers without
    # accidentally queueing an entire long project.
    limit: int | None = Field(default=None, ge=1, le=500)
    # When true, every video job must consume a real image asset. Segments
    # without one first receive an image job and the video waits for it.
    requires_reference_image: bool = False
    reference_image_provider: SceneProvider = "flow_image"
    duration_seconds: int = Field(default=5, ge=1, le=30)
    ratio: Literal["1280:720", "720:1280", "1024:1024"] = "1280:720"
    confirmed: bool = False


class AnalyzeAssetRequest(BaseModel):
    language: str = Field(default="", max_length=20)
    confirmed: bool = False


class RenameAssetRequest(BaseModel):
    original_name: str = Field(min_length=1, max_length=180)


def _api_error(exc: Exception) -> HTTPException:
    if isinstance(exc, operations.OperationCancelled):
        # 499 is nginx's "client closed request"; the nearest honest code for
        # work that was deliberately stopped rather than failing.
        return HTTPException(status_code=499, detail="Đã dừng theo yêu cầu")
    if isinstance(exc, YouTubeApiError):
        status = exc.status_code if exc.status_code and 400 <= exc.status_code < 500 else 502
        return HTTPException(status_code=status, detail=str(exc))
    if isinstance(exc, TranscriptionError):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, LlmAnalysisError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, DirectorError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, (OAuthError, CaptionsError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, VideoDownloadError):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, ProductionJobError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, SceneGenerationError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, ThumbnailGenerationError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _write_project_document(project_id: int, filename: str, content: str) -> Path:
    """Keep the human-readable production plan beside each project."""
    path = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["script"] / filename
    path.write_text(content, encoding="utf-8")
    return path


def _current_final_video_path(project_id: int, script_id: int | None = None) -> Path | None:
    """Return final.mp4 only when it was rendered from the current script."""
    script = database.get_latest_project_script(project_id)
    active_script_id = int(script_id or (script or {}).get("id") or 0)
    if not active_script_id:
        return None
    final_path = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["exports"] / "final.mp4"
    if not final_path.is_file():
        return None
    for job in database.list_project_jobs(project_id, limit=100):
        if (
            int(job.get("script_id") or 0) == active_script_id
            and job.get("job_type") in {"render", "director_production"}
            and job.get("status") == "completed"
            and Path(str(job.get("output_path") or "")).resolve() == final_path.resolve()
        ):
            return final_path
    return None


# Split out of this file (see api/routes_system.py, api/routes_oauth.py) so
# main.py doesn't have to grow forever as a single router file. Imported here,
# after `_api_error` and the singletons above are defined, since both routers
# import them back from this module.
from .api.routes_system import router as _system_router  # noqa: E402
from .api.routes_oauth import router as _oauth_router  # noqa: E402

app.include_router(_system_router)
app.include_router(_oauth_router)


@app.get("/api/channels")
def list_channels() -> list[dict[str, Any]]:
    return database.list_channels()


@app.post("/api/channels")
def add_channel(payload: AddChannelRequest) -> dict[str, Any]:
    try:
        return service.add_channel(
            payload.reference,
            group_name=payload.group_name,
            max_videos=payload.max_videos,
        )
    except Exception as exc:
        raise _api_error(exc) from exc


@app.post("/api/videos/import")
def import_reference_video(payload: ImportVideoRequest) -> dict[str, Any]:
    try:
        return service.add_video(payload.reference, group_name=payload.group_name)
    except Exception as exc:
        raise _api_error(exc) from exc


@app.get("/api/managed-channels")
def list_managed_channels() -> list[dict[str, Any]]:
    return database.list_managed_channels()


@app.post("/api/managed-channels")
def add_managed_channel(payload: ManagedChannelRequest) -> dict[str, Any]:
    try:
        channel = database.create_managed_channel(
            name=payload.name,
            channel_url=payload.channel_url,
            youtube_channel_id=payload.youtube_channel_id,
            group_name=payload.group_name,
            workflow_reference_channel_id=payload.workflow_reference_channel_id,
            output_profile=payload.output_profile,
            language=payload.language,
            default_voice_provider=payload.default_voice_provider,
            default_voice_model=payload.default_voice_model,
            default_subtitle_provider=payload.default_subtitle_provider,
            default_subtitle_model=payload.default_subtitle_model,
            default_transition_style=payload.default_transition_style,
            notes=payload.notes,
            schedule_enabled=payload.schedule_enabled,
            schedule_frequency=payload.schedule_frequency,
            schedule_time=payload.schedule_time,
            schedule_timezone=payload.schedule_timezone,
            schedule_days=payload.schedule_days,
            default_privacy=payload.default_privacy,
            auto_upload=payload.auto_upload,
        )
        return {"status": "saved", "channel": channel}
    except Exception as exc:
        raise _api_error(exc) from exc


@app.patch("/api/managed-channels/{channel_id}")
def update_managed_channel(channel_id: int, payload: ManagedChannelUpdateRequest) -> dict[str, Any]:
    try:
        channel = database.update_managed_channel(channel_id, **payload.model_dump(exclude_unset=True))
    except Exception as exc:
        raise _api_error(exc) from exc
    if not channel:
        raise HTTPException(status_code=404, detail="Không tìm thấy kênh của tôi")
    return {"status": "saved", "channel": channel}


@app.get("/api/workflow-reference-channels")
def list_workflow_reference_channels() -> list[dict[str, Any]]:
    return [
        {
            "youtube_channel_id": channel["youtube_channel_id"],
            "title": channel.get("title") or channel["youtube_channel_id"],
            "channel_url": channel.get("channel_url") or "",
            "group_name": channel.get("group_name") or "",
            "thumbnail_url": channel.get("thumbnail_url") or "",
        }
        for channel in database.list_channels()
    ]


@app.patch("/api/channels/{channel_id}/tracking")
def set_tracking(channel_id: str, payload: TrackingRequest) -> dict[str, Any]:
    channel = database.set_tracking_enabled(channel_id, payload.enabled)
    if not channel:
        raise HTTPException(status_code=404, detail="Không tìm thấy kênh")
    return channel


@app.patch("/api/channels/{channel_id}/group")
def set_channel_group(channel_id: str, payload: ChannelGroupRequest) -> dict[str, Any]:
    channel = database.set_channel_group(channel_id, payload.group_name)
    if not channel:
        raise HTTPException(status_code=404, detail="Không tìm thấy kênh")
    return channel


@app.post("/api/channels/{channel_id}/sync")
def sync_channel(
    channel_id: str,
    max_videos: int | None = Query(default=None, ge=1, le=5000),
) -> dict[str, Any]:
    try:
        return service.sync_channel(channel_id, max_videos=max_videos, trigger="manual")
    except Exception as exc:
        raise _api_error(exc) from exc


@app.get("/api/videos")
def list_videos(
    channel_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    return database.list_videos(channel_id, limit)


@app.get("/api/projects")
def list_projects(limit: int = Query(default=100, ge=1, le=200)) -> list[dict[str, Any]]:
    return database.list_production_projects(limit)


@app.get("/api/projects/{project_id}")
def get_project(project_id: int) -> dict[str, Any]:
    bundle = database.get_production_project_bundle(project_id, transcript_text_limit=2_000)
    if not bundle:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    final_path = _current_final_video_path(project_id, int((bundle.get("latest_script") or {}).get("id") or 0))
    bundle["final_video"] = {
        "available": bool(final_path),
        "url": f"/api/projects/{project_id}/final-video" if final_path else None,
        "size_bytes": final_path.stat().st_size if final_path else None,
    }
    return bundle


@app.get("/api/projects/{project_id}/final-video")
def stream_project_final_video(project_id: int) -> FileResponse:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    final_path = _current_final_video_path(project_id)
    if not final_path:
        raise HTTPException(status_code=404, detail="Dự án chưa có video hoàn chỉnh cho phiên kịch bản hiện tại; hãy tạo cảnh AI và render lại")
    return FileResponse(final_path, media_type="video/mp4")


@app.get("/api/projects/{project_id}/handoff")
def get_project_handoff(
    project_id: int,
    transcript_chars: int = Query(default=50_000, ge=0, le=200_000),
) -> dict[str, Any]:
    limit = None if transcript_chars == 0 else transcript_chars
    bundle = database.get_production_project_bundle(project_id, transcript_text_limit=limit)
    if not bundle:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return {
        "handoff_version": "youtube_ai_factory.project.v1",
        "intended_consumer": "OpenClaw",
        **bundle,
    }


@app.get("/api/projects/{project_id}/script")
def get_latest_project_script(project_id: int) -> dict[str, Any]:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id)
    return script or {"project_id": project_id, "status": "missing"}


@app.get("/api/projects/{project_id}/scripts")
def list_project_scripts(project_id: int) -> list[dict[str, Any]]:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return database.list_project_scripts(project_id)


@app.post("/api/projects/{project_id}/script/draft")
def create_project_script_draft(project_id: int) -> dict[str, Any]:
    bundle = database.get_production_project_bundle(project_id, transcript_text_limit=50_000)
    if not bundle:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    draft = build_script_draft(bundle)
    script = database.create_project_script(project_id, **draft)
    if not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    _write_project_document(project_id, "kich-ban.md", script_to_markdown(script, bundle["project"]))
    return {"status": "saved", "script": script}


@app.post("/api/projects/{project_id}/director-draft")
def create_director_draft(
    project_id: int,
    payload: DirectorDraftRequest = DirectorDraftRequest(),
) -> dict[str, Any]:
    """Create an original, user-directed script and AI-scene blueprint.

    Rendering is intentionally a separate phase: an actual video must have a
    real scene clip/image for every shot, not placeholder title cards.
    """
    bundle = database.get_production_project_bundle(project_id, transcript_text_limit=50_000)
    if not bundle:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    direction = payload.creative_direction.strip()
    if not direction:
        raise HTTPException(
            status_code=400,
            detail="AI Đạo diễn cần ý tưởng video mới của bạn (nhân vật, bối cảnh, diễn biến hoặc thông điệp) trước khi viết.",
        )
    try:
        active_writer = resolve_writer(payload.provider)
        video = bundle.get("source_video") or database.get_video(str(bundle["project"]["youtube_video_id"]))
        transcript_text = (bundle.get("latest_transcript") or {}).get("content_text") or None
        reference_analysis = (bundle.get("reference_analysis") or {}).get("result") or None
        workflow_context = {
            "managed_channel_name": bundle["project"].get("managed_channel_name", ""),
            "output_profile": bundle["project"].get("managed_channel_output_profile", "youtube_landscape"),
            "workflow_reference_title": bundle["project"].get("workflow_reference_title", ""),
            "workflow_notes": bundle["project"].get("managed_channel_notes", ""),
        }
        target_duration = resolve_target_duration_seconds(payload.target_duration_seconds, direction, payload.target_duration_text, (video or {}).get("duration_seconds"))
        research_context = research_folklore_remake(str((video or {}).get("title") or ""), direction) if payload.use_web_research else None
        with operations.track("writer", f"AI Đạo diễn · dự án {project_id}", project_id):
            creative = active_writer.generate(
                video or {},
                transcript_text,
                workflow_context=workflow_context,
                creative_direction=direction,
                remake_mode=payload.remake_mode,
                target_duration_seconds=target_duration,
                source_duration_seconds=(video or {}).get("duration_seconds"),
                research_context=research_context,
                reference_analysis=reference_analysis,
                output_language=payload.output_language,
            )
        if research_context:
            creative["research_context"] = research_context
        creative["target_duration_seconds"] = target_duration
        creative["output_language"] = payload.output_language
        creative["quality_warnings"] = validate_voiceover_plan(creative, target_duration, payload.output_language)
        database.save_video_analysis(
            str(bundle["project"]["youtube_video_id"]), creative, analysis_type="writer",
            provider=active_writer.provider, source_type=creative["source_type"],
        )
        script = database.create_project_script(project_id, **dict(creative.get("new_script") or {}))
        if not script:
            raise HTTPException(status_code=404, detail="Không thể lưu kịch bản AI Đạo diễn")
        shots = database.create_project_shots(
            project_id,
            int(script["id"]),
            build_shot_plan(bundle["project"], script, writer_content=creative),
            force=True,
        )
        if shots is None:
            raise HTTPException(status_code=404, detail="Không thể lưu shot list AI Đạo diễn")
        timeline = database.create_project_timeline(
            project_id,
            int(script["id"]),
            build_timeline(bundle["project"], script, shots),
            force=True,
        )
        if timeline is None:
            raise HTTPException(status_code=404, detail="Không thể lưu timeline AI Đạo diễn")
        _write_project_document(
            project_id,
            "ai-dao-dien.md",
            "# AI Đạo diễn · brief sáng tạo\n\n"
            f"- Ý tưởng của bạn: {direction}\n"
            f"- Chế độ remake: {payload.remake_mode}\n\n"
            "## Concept mới\n\n"
            f"{creative.get('new_story_concept', '')}\n\n"
            "## Áp dụng phong cách\n\n"
            + "\n".join(f"- {item}" for item in creative.get("style_application", [])) + "\n",
        )
        _write_project_document(project_id, "kich-ban.md", script_to_markdown(script, bundle["project"]))
        _write_project_document(project_id, "shot-list.md", shots_to_markdown(bundle["project"], script, shots))
        _write_project_document(project_id, "timeline.md", timeline_to_markdown(bundle["project"], script, timeline))
    except HTTPException:
        raise
    except Exception as exc:
        raise _api_error(exc) from exc

    return {
        "status": "saved",
        "director": creative,
        "script": script,
        "shots": shots,
        "timeline": timeline,
        "next_step": "Tạo video AI cho từng cảnh trong storyboard, xem/duyệt cảnh, rồi mới tạo voice và render.",
    }


@app.patch("/api/scripts/{script_id}")
def update_script(script_id: int, payload: UpdateScriptRequest) -> dict[str, Any]:
    script = database.update_project_script(
        script_id,
        script_title=payload.script_title,
        hook=payload.hook,
        intro=payload.intro,
        main_content=payload.main_content,
        cta=payload.cta,
        status=payload.status,
    )
    if not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy kịch bản")
    # Editing the words invalidates any earlier verdict about them: a checked
    # script that is then changed must not keep walking through the gate.
    if str(script.get("fidelity_status") or "unchecked") != "unchecked":
        script = database.set_script_fidelity_status(script_id, "unchecked") or script
    project = database.get_production_project(int(script["project_id"]))
    if project:
        _write_project_document(int(script["project_id"]), "kich-ban.md", script_to_markdown(script, project))
    return {"status": "saved", "script": script}


@app.post("/api/scripts/{script_id}/approve")
def approve_script(script_id: int) -> dict[str, Any]:
    script = database.approve_project_script(script_id)
    if not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy kịch bản")
    project = database.get_production_project(int(script["project_id"]))
    if project:
        _write_project_document(int(script["project_id"]), "kich-ban.md", script_to_markdown(script, project))
    return {"status": "approved", "script": script}


@app.post("/api/projects/{project_id}/script/chat")
def revise_project_script_from_chat(
    project_id: int,
    payload: ScriptChatRequest,
) -> dict[str, Any]:
    """Revise the latest saved script through the selected AI writer provider."""
    project = database.get_production_project(project_id)
    script = database.get_latest_project_script(project_id)
    if not project or not script:
        raise HTTPException(status_code=404, detail="Project chưa có kịch bản để chỉnh sửa")
    video = database.get_video(str(project["youtube_video_id"]))
    if not video:
        raise HTTPException(status_code=404, detail="Không tìm thấy video nguồn của project")
    transcript = database.get_transcript(str(project["youtube_video_id"]), transcript_format="txt")
    workflow_context = {
        "managed_channel_name": project.get("managed_channel_name", ""),
        "output_profile": project.get("managed_channel_output_profile", "youtube_landscape"),
        "workflow_reference_title": project.get("workflow_reference_title", ""),
        "workflow_notes": "",
    } if project.get("managed_channel_id") else None
    try:
        revised = revise_script(
            payload.provider,
            video,
            script,
            payload.message,
            transcript_text=transcript.get("content_text") if transcript else None,
            workflow_context=workflow_context,
        )
        saved = database.create_project_script(
            project_id,
            script_title=revised["script_title"],
            hook=revised["hook"],
            intro=revised["intro"],
            main_content=revised["main_content"],
            cta=revised["cta"],
        )
        if not saved:
            raise HTTPException(status_code=404, detail="Không thể lưu phiên bản kịch bản mới")
        _write_project_document(project_id, "kich-ban.md", script_to_markdown(saved, project))
        return {"status": "saved", "provider": revised["provider"], "script": saved}
    except HTTPException:
        raise
    except WriterError as exc:
        raise _api_error(exc) from exc
    except Exception as exc:
        raise _api_error(exc) from exc


@app.get("/api/scripts/{script_id}/markdown")
def export_script_markdown(script_id: int) -> PlainTextResponse:
    script = database.get_project_script(script_id)
    if not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy kịch bản")
    project = database.get_production_project(int(script["project_id"]))
    return PlainTextResponse(
        script_to_markdown(script, project),
        media_type="text/markdown; charset=utf-8",
    )


@app.get("/api/projects/{project_id}/shots")
def list_project_shots(project_id: int) -> list[dict[str, Any]]:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id)
    if not script:
        return []
    return database.list_project_shots(project_id, script_id=int(script["id"]))


@app.post("/api/projects/{project_id}/shots/generate")
def generate_project_shots(
    project_id: int,
    payload: GenerateShotsRequest = GenerateShotsRequest(),
) -> dict[str, Any]:
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id)
    if not script:
        raise HTTPException(status_code=400, detail="Project chưa có kịch bản để tạo shot list")
    writer_analysis = database.get_video_analysis(str(project["youtube_video_id"]), analysis_type="writer")
    writer_content = writer_analysis.get("result") if writer_analysis else None
    planned = build_shot_plan(project, script, writer_content=writer_content)
    shots = database.create_project_shots(
        project_id,
        int(script["id"]),
        planned,
        force=payload.force,
    )
    if shots is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án hoặc kịch bản")
    _write_project_document(project_id, "shot-list.md", shots_to_markdown(project, script, shots))
    return {"status": "saved", "script_id": script["id"], "shots": shots}


@app.patch("/api/shots/{shot_id}")
def update_shot(shot_id: int, payload: UpdateShotRequest) -> dict[str, Any]:
    shot = database.update_project_shot(
        shot_id,
        narration=payload.narration,
        visual_prompt=payload.visual_prompt,
        asset_type=payload.asset_type,
        duration_seconds=payload.duration_seconds,
        status=payload.status,
    )
    if not shot:
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh")
    project = database.get_production_project(int(shot["project_id"]))
    script = database.get_project_script(int(shot["script_id"]))
    if project and script:
        shots = database.list_project_shots(int(project["id"]), script_id=int(script["id"]))
        _write_project_document(int(project["id"]), "shot-list.md", shots_to_markdown(project, script, shots))
    return {"status": "saved", "shot": shot}


@app.post("/api/projects/{project_id}/shots")
def create_project_shot(project_id: int, payload: CreateShotRequest) -> dict[str, Any]:
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id)
    if not script:
        raise HTTPException(status_code=400, detail="Project chưa có kịch bản để thêm cảnh")
    shot = database.create_project_shot(
        project_id,
        int(script["id"]),
        section=payload.section,
        narration=payload.narration,
        visual_prompt=payload.visual_prompt,
        asset_type=payload.asset_type,
        duration_seconds=payload.duration_seconds,
        status=payload.status,
    )
    if not shot:
        raise HTTPException(status_code=404, detail="Không thể tạo cảnh")
    shots = database.list_project_shots(project_id, script_id=int(script["id"]))
    _write_project_document(project_id, "shot-list.md", shots_to_markdown(project, script, shots))
    return {"status": "created", "shot": shot, "shots": shots}


@app.post("/api/shots/{shot_id}/duplicate")
def duplicate_project_shot(shot_id: int) -> dict[str, Any]:
    source = database.get_project_shot(shot_id)
    if not source:
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh")
    shot = database.duplicate_project_shot(shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="Không thể nhân bản cảnh")
    project = database.get_production_project(int(source["project_id"]))
    script = database.get_project_script(int(source["script_id"]))
    if project and script:
        shots = database.list_project_shots(int(project["id"]), script_id=int(script["id"]))
        _write_project_document(int(project["id"]), "shot-list.md", shots_to_markdown(project, script, shots))
    else:
        shots = []
    return {"status": "created", "source_shot_id": shot_id, "shot": shot, "shots": shots}


@app.post("/api/projects/{project_id}/shots/reorder")
def reorder_shots(project_id: int, payload: ReorderShotsRequest) -> dict[str, Any]:
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id)
    if not script:
        raise HTTPException(status_code=400, detail="Project chưa có kịch bản để sắp xếp cảnh")
    try:
        shots = database.reorder_project_shots(project_id, payload.shot_ids, script_id=int(script["id"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _write_project_document(project_id, "shot-list.md", shots_to_markdown(project, script, shots))
    return {"status": "saved", "shots": shots}


@app.delete("/api/shots/{shot_id}")
def delete_shot(shot_id: int) -> dict[str, Any]:
    shot = database.get_project_shot(shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh")
    if not database.delete_project_shot(shot_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh")
    project = database.get_production_project(int(shot["project_id"]))
    script = database.get_project_script(int(shot["script_id"]))
    if project and script:
        shots = database.list_project_shots(int(project["id"]), script_id=int(script["id"]))
        _write_project_document(int(project["id"]), "shot-list.md", shots_to_markdown(project, script, shots))
    return {"status": "deleted", "shot_id": shot_id}


@app.get("/api/projects/{project_id}/shots/markdown")
def export_project_shots_markdown(project_id: int) -> PlainTextResponse:
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id)
    shots = database.list_project_shots(project_id, script_id=int(script["id"])) if script else []
    return PlainTextResponse(
        shots_to_markdown(project, script, shots),
        media_type="text/markdown; charset=utf-8",
    )


@app.get("/api/projects/{project_id}/timeline")
def list_project_timeline(project_id: int) -> list[dict[str, Any]]:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id)
    if not script:
        return []
    return database.list_project_timeline(project_id, script_id=int(script["id"]))


@app.post("/api/projects/{project_id}/timeline/generate")
def generate_project_timeline(
    project_id: int,
    payload: GenerateTimelineRequest = GenerateTimelineRequest(),
) -> dict[str, Any]:
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id)
    if not script:
        raise HTTPException(status_code=400, detail="Project chưa có kịch bản để tạo timeline")
    shots = database.list_project_shots(project_id, script_id=int(script["id"]))
    if not shots:
        raise HTTPException(status_code=400, detail="Project chưa có shot list để tạo timeline")
    planned = build_timeline(project, script, shots)
    timeline = database.create_project_timeline(
        project_id,
        int(script["id"]),
        planned,
        force=payload.force,
    )
    if timeline is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án hoặc kịch bản")
    _write_project_document(project_id, "timeline.md", timeline_to_markdown(project, script, timeline))
    return {
        "status": "saved",
        "script_id": script["id"],
        "total_duration_seconds": sum(int(item["duration_seconds"]) for item in timeline),
        "timeline": timeline,
    }


@app.patch("/api/timeline/{segment_id}")
def update_timeline_segment(
    segment_id: int,
    payload: UpdateTimelineRequest,
) -> dict[str, Any]:
    segment = database.update_project_timeline_segment(
        segment_id,
        voice_text=payload.voice_text,
        subtitle_text=payload.subtitle_text,
        visual_prompt=payload.visual_prompt,
        asset_type=payload.asset_type,
        duration_seconds=payload.duration_seconds,
        audio_path=payload.audio_path,
        visual_path=payload.visual_path,
        status=payload.status,
    )
    if not segment:
        raise HTTPException(status_code=404, detail="Không tìm thấy segment timeline")
    return {"status": "saved", "segment": segment}


class UpdateProjectWorkflowRequest(BaseModel):
    """Which production workflow this project follows."""

    workflow: Literal["content", "reup"] = "content"


@app.patch("/api/projects/{project_id}/workflow")
def update_project_workflow(project_id: int, payload: UpdateProjectWorkflowRequest) -> dict[str, Any]:
    """Remember the workflow so reopening a project restores the right steps.

    The choice lives on the project, not the browser: the same project opened
    on another machine has to come back as the workflow it was built with, or
    the wizard would offer steps that do not match what is already there.
    """
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return {"status": "saved", "project": database.set_project_workflow(project_id, payload.workflow)}


class UpdateScenePlanRequest(BaseModel):
    """A person overriding what the orchestrator decided for one scene."""

    visual_kind: Literal["image", "gif", "video"] | None = None
    visual_fps: int | None = Field(default=None, ge=0, le=24)
    transition: Literal["cut", "fade"] | None = None
    effect: Literal["zoom_in", "zoom_out", "static"] | None = None
    note: str | None = Field(default=None, max_length=400)


@app.patch("/api/timeline/{segment_id}/plan")
def update_timeline_segment_plan(segment_id: int, payload: UpdateScenePlanRequest) -> dict[str, Any]:
    """Change one scene's planned kind or its place in the edit.

    Both plans are written by an AI reading the script, which is right more
    often than a blanket setting but not always right. Being able to correct
    a single scene is what makes it safe to run the planners at all — the
    alternative was re-running the whole plan to fix one row.
    """
    segment = database.get_project_timeline_segment(segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Không tìm thấy segment timeline")
    if payload.visual_kind is not None:
        fps = payload.visual_fps if payload.visual_fps is not None else int(segment.get("visual_fps") or 0)
        segment = database.set_segment_visual_kind(
            segment_id,
            payload.visual_kind,
            fps=fps if payload.visual_kind in {"gif", "video"} else 0,
            reason="Người dùng chọn tay",
        ) or segment
    elif payload.visual_fps is not None:
        segment = database.set_segment_visual_kind(
            segment_id,
            str(segment.get("visual_kind") or "image"),
            fps=payload.visual_fps,
            reason=str(segment.get("visual_kind_reason") or ""),
        ) or segment
    if payload.transition is not None or payload.effect is not None or payload.note is not None:
        database.save_segment_edit(
            segment_id,
            payload.transition if payload.transition is not None else str(segment.get("edit_transition") or "fade"),
            payload.effect if payload.effect is not None else str(segment.get("edit_effect") or "zoom_in"),
            payload.note if payload.note is not None else str(segment.get("edit_note") or ""),
        )
        segment = database.get_project_timeline_segment(segment_id) or segment
    return {"status": "saved", "segment": segment}


@app.get("/api/projects/{project_id}/timeline/manifest")
def export_project_timeline_manifest(project_id: int) -> dict[str, Any]:
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id)
    timeline = database.list_project_timeline(
        project_id,
        script_id=int(script["id"]) if script else None,
    ) if script else []
    return timeline_to_manifest(project, script, timeline)


@app.get("/api/projects/{project_id}/timeline/markdown")
def export_project_timeline_markdown(project_id: int) -> PlainTextResponse:
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id)
    timeline = database.list_project_timeline(
        project_id,
        script_id=int(script["id"]) if script else None,
    ) if script else []
    return PlainTextResponse(
        timeline_to_markdown(project, script, timeline),
        media_type="text/markdown; charset=utf-8",
    )


@app.get("/api/projects/{project_id}/render-settings")
def get_project_render_settings(project_id: int) -> dict[str, Any]:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return database.get_project_render_settings(project_id)


@app.patch("/api/projects/{project_id}/render-settings")
def update_project_render_settings(
    project_id: int,
    payload: RenderSettingsRequest,
) -> dict[str, Any]:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    try:
        settings = database.update_project_render_settings(
            project_id,
            music_asset_id=payload.music_asset_id,
            music_volume=payload.music_volume,
            transition_style=payload.transition_style,
            output_profile=payload.output_profile,
            voice_provider=payload.voice_provider,
            voice_model=payload.voice_model,
            voice_rate=payload.voice_rate,
            voice_reference_asset_id=payload.voice_reference_asset_id,
            voice_prompt_text=payload.voice_prompt_text,
            subtitle_provider=payload.subtitle_provider,
            subtitle_model=payload.subtitle_model,
            publish_language=payload.publish_language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "saved", "settings": settings}


@app.post("/api/projects/{project_id}/apply-channel-preset")
def apply_channel_preset(project_id: int) -> dict[str, Any]:
    try:
        render_settings = database.apply_managed_channel_preset(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if render_settings is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return {"status": "applied", "settings": render_settings}


_ASSET_EXTENSIONS = {
    "video": {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"},
    "audio": {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"},
    "image": {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"},
}

# The user's three reference recordings are kept in the shared documentation
# folder.  Expose them as a small local library so they remain available when
# the user switches projects.  Selecting one copies it into the project as a
# normal editable audio asset; it never moves or changes the original file.
_VOICE_LIBRARY_DIR = PRODUCTION_ARTIFACT_DIR.parent / "03_TAI_LIEU"
_VOICE_LIBRARY = (
    {
        "key": "voice-sample-1",
        "label": "Giọng mẫu 1",
        "filename": "co_hang_chuc_mo_hinh_nen_khac_nhau_vay_phai_ghi_6547dcf8-c299-4d92-98e6-91436a06b912.mp3",
    },
    {
        "key": "voice-sample-2",
        "label": "Giọng mẫu 2",
        "filename": "co_hang_chuc_mo_hinh_nen_khac_nhau_vay_phai_ghi_91710c44-a39b-4639-9a7c-5a66a35ce00f.mp3",
    },
    {
        "key": "voice-sample-3",
        "label": "Giọng mẫu 3",
        "filename": "co_hang_chuc_mo_hinh_nen_khac_nhau_vay_phai_ghi_bc41f313-ba98-462c-a87d-1940164feb60.mp3",
    },
)
_EDGE_TTS_VOICES = {
    "vi-VN-HoaiMyNeural",
    "vi-VN-NamMinhNeural",
    "en-US-AriaNeural",
    "en-US-GuyNeural",
    "th-TH-PremwadeeNeural",
    "pt-BR-FranciscaNeural",
    "pt-BR-AntonioNeural",
}
_EDGE_PREVIEW_RATES = {"-25%", "-15%", "-8%", "+0%", "+8%", "+15%", "+25%"}
_EDGE_PREVIEW_TEXT = "Đây là bản nghe thử giọng đọc. Câu chuyện sẽ được kể rõ ràng, tự nhiên và giàu cảm xúc."


def _voice_library_entry(key: str) -> dict[str, str]:
    entry = next((item for item in _VOICE_LIBRARY if item["key"] == key), None)
    if not entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy giọng mẫu")
    return entry


def _voice_library_path(key: str) -> Path:
    entry = _voice_library_entry(key)
    return _VOICE_LIBRARY_DIR / entry["filename"]


def _select_voxcpm_reference_asset(
    project_id: int,
    asset: dict[str, Any],
    label: str,
    voice_model: str = "voxcpm-default",
) -> dict[str, Any]:
    current = database.get_project_render_settings(project_id)
    try:
        return database.update_project_render_settings(
            project_id,
            music_asset_id=current.get("music_asset_id"),
            music_volume=float(current.get("music_volume") or 0.12),
            transition_style=str(current.get("transition_style") or "fade"),
            output_profile=str(current.get("output_profile") or "youtube_landscape"),
            voice_provider="voxcpm",
            voice_model=voice_model,
            voice_rate=str(current.get("voice_rate") or "+0%"),
            voice_reference_asset_id=int(asset["id"]),
            voice_prompt_text=str(current.get("voice_prompt_text") or f"Giọng kể chuyện tiếng Việt tự nhiên, dùng mẫu {label}."),
            subtitle_provider=str(current.get("subtitle_provider") or "timeline_text"),
            subtitle_model=str(current.get("subtitle_model") or "timeline"),
            publish_language=str(current.get("publish_language") or "vi"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _edge_voice_preview_path(voice: str, rate: str) -> Path:
    safe_rate = rate.replace("+", "plus").replace("-", "minus").replace("%", "")
    return PRODUCTION_ARTIFACT_DIR / "_voice_previews" / f"edge-{voice}-{safe_rate}.mp3"


def _safe_asset_stem(filename: str) -> str:
    stem = Path(filename).stem
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in stem)
    return (cleaned[:80] or "asset").strip("._") or "asset"


@app.get("/api/voice-previews/edge/{voice}")
def stream_edge_voice_preview(voice: str, rate: str = Query(default="+0%")) -> FileResponse:
    """Generate/cache a short real Edge TTS audition for the selected voice."""
    if voice not in _EDGE_TTS_VOICES:
        raise HTTPException(status_code=404, detail="Giọng Edge TTS không được hỗ trợ để nghe thử")
    if rate not in _EDGE_PREVIEW_RATES:
        raise HTTPException(status_code=400, detail="Tốc độ nghe thử không hợp lệ")
    if not EDGE_TTS_RUNTIME_READY:
        raise HTTPException(status_code=400, detail="Edge TTS chưa sẵn sàng để tạo bản nghe thử")
    output = _edge_voice_preview_path(voice, rate)
    if not output.is_file() or output.stat().st_size == 0:
        output.parent.mkdir(parents=True, exist_ok=True)
        text_file = output.with_suffix(".txt")
        text_file.write_text(_EDGE_PREVIEW_TEXT, encoding="utf-8")
        values = {
            "text_file": text_file,
            "output_file": output,
            "voice_role": voice,
            "voice_rate": rate,
            "srt_file": text_file.with_suffix(".srt"),
            "output_dir": output.parent,
            "language": "vi",
        }
        try:
            rendered = EDGE_TTS_COMMAND.format(**{key: str(value) for key, value in values.items()})
            args = [item.strip('"') for item in shlex.split(rendered, posix=False)]
            result = subprocess.run(
                args,
                cwd=str(output.parent),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=90,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError) as exc:
            raise HTTPException(status_code=502, detail=f"Không tạo được bản nghe thử Edge TTS: {exc}") from exc
        if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            detail = (result.stderr or result.stdout or "Edge TTS không trả về audio").strip()[-1000:]
            raise HTTPException(status_code=502, detail=f"Không tạo được bản nghe thử Edge TTS: {detail}")
    return FileResponse(output, media_type="audio/mpeg")


@app.get("/api/voice-library")
def list_voice_library() -> list[dict[str, Any]]:
    """List the user's shared local voice samples without coupling to a project."""
    return [
        {
            "key": item["key"],
            "label": item["label"],
            "ready": _voice_library_path(item["key"]).is_file(),
            "url": f"/api/voice-library/{item['key']}/audio",
        }
        for item in _VOICE_LIBRARY
    ]


@app.get("/api/voice-library/{key}/audio")
def stream_voice_library_audio(key: str) -> FileResponse:
    path = _voice_library_path(key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy file giọng mẫu trên máy")
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "audio/mpeg")


@app.post("/api/projects/{project_id}/voice-library/{key}/select")
def select_voice_library_sample(project_id: int, key: str) -> dict[str, Any]:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    entry = _voice_library_entry(key)
    source = _voice_library_path(key)
    if not source.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy file giọng mẫu trên máy")

    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assets = database.list_project_assets(project_id)
    asset = next(
        (
            item for item in assets
            if item.get("asset_type") == "audio" and str(item.get("sha256") or "") == digest
            and Path(str(item.get("file_path") or "")).is_file()
        ),
        None,
    )
    if not asset:
        asset_dir = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["assets"] / "audio"
        asset_dir.mkdir(parents=True, exist_ok=True)
        target = asset_dir / f"voice-library-{entry['key']}{source.suffix.lower()}"
        try:
            shutil.copy2(source, target)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Không thể sao chép giọng mẫu vào dự án: {exc}") from exc
        asset = database.create_project_asset(
            project_id,
            "audio",
            entry["label"],
            str(target),
            mime_type=mimetypes.guess_type(source.name)[0] or "audio/mpeg",
            file_size=target.stat().st_size,
            sha256=digest,
        )
    if not asset:
        raise HTTPException(status_code=500, detail="Không thể lưu giọng mẫu vào dự án")
    settings = _select_voxcpm_reference_asset(project_id, asset, entry["label"], f"library:{key}")
    return {"status": "selected", "asset": asset, "settings": settings, "label": entry["label"]}


@app.get("/api/projects/{project_id}/assets")
def list_project_assets(project_id: int) -> list[dict[str, Any]]:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return database.list_project_assets(project_id)


LOCAL_UPLOAD_CHANNEL_ID = "LOCAL-UPLOADS-0000000000"
_SOURCE_UPLOAD_EXTENSIONS = _ASSET_EXTENSIONS["video"] | _ASSET_EXTENSIONS["audio"]


def _ensure_local_upload_channel() -> None:
    """One synthetic channel so uploads sit alongside the tracked ones.

    Everything downstream - projects, transcripts, analyses, timelines - is
    keyed to a row in `videos`, which in turn needs a channel. Giving uploads
    their own channel rather than a nullable column means none of that had to
    learn about a second kind of source.
    """
    database.upsert_channel({
        "youtube_channel_id": LOCAL_UPLOAD_CHANNEL_ID,
        "channel_url": "local://uploads",
        "title": "Tệp tải lên từ máy",
        "uploads_playlist_id": "LOCAL-UPLOADS",
        "group_name": "Tệp tải lên",
    })


@app.post("/api/uploads/source")
def upload_local_source(
    file: UploadFile = File(...),
    title: str = Form(default=""),
) -> dict[str, Any]:
    """Take a video or audio file from the user's machine as a project source.

    Until now a project could only start from a video the app had discovered
    on YouTube, which left no way to work on footage the user already had.
    The uploaded file is registered as an ordinary video row carrying
    local_media_path, so transcription, analysis and - for the reup workflow -
    cutting scenes out of it all work without a download step.
    """
    filename = Path(file.filename or "").name
    extension = Path(filename).suffix.lower()
    if not filename or extension not in _SOURCE_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Chỉ nhận video hoặc audio. Đuôi nhận được: {extension or 'không có'}",
        )

    upload_dir = Path(PRODUCTION_ARTIFACT_DIR) / "_tai_len"
    upload_dir.mkdir(parents=True, exist_ok=True)
    video_id = f"local-{uuid.uuid4().hex[:16]}"
    target = upload_dir / f"{video_id}{extension}"
    digest = hashlib.sha256()
    total = 0
    try:
        with target.open("wb") as output:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > LOCAL_ASSET_MAX_BYTES:
                    raise HTTPException(status_code=413, detail="File vượt quá giới hạn upload local")
                digest.update(chunk)
                output.write(chunk)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Không lưu được file: {exc}") from exc
    if not total:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="File rỗng")

    _ensure_local_upload_channel()
    duration = media_duration_seconds(target, FFMPEG_BINARY) or 0
    database.upsert_video({
        "youtube_video_id": video_id,
        "youtube_channel_id": LOCAL_UPLOAD_CHANNEL_ID,
        "video_url": target.as_uri(),
        "title": (title.strip() or Path(filename).stem)[:200],
        "description": f"Tệp tải lên từ máy: {filename}",
        "duration_seconds": int(duration),
        "metadata_hash": digest.hexdigest(),
        "raw_payload": {"uploaded_filename": filename, "file_size": total},
    })
    # upsert_video does not write local_media_path - the column was added later
    # for downloads - so the file is registered the same way a download is.
    database.mark_video_downloaded(video_id, str(target))
    return {
        "status": "uploaded",
        "video": database.get_video(video_id),
        "file_size": total,
        "duration_seconds": int(duration),
    }


def _contact_sheet_for_review(images: list[Path], project_id: int) -> Path:
    """Tile several reference images into one, so a model sees them together.

    Showing them one at a time costs a CLI round trip each and, worse, invites
    a description of each picture rather than of what they have in common -
    which is the whole point of handing over a folder.
    """
    if len(images) == 1:
        return images[0]
    workspace = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["work"] / "reference"
    workspace.mkdir(parents=True, exist_ok=True)
    sheet_path = workspace / "reference-contact-sheet.png"
    columns = 2 if len(images) <= 4 else 3
    command = [FFMPEG_BINARY, "-y", "-hide_banner", "-loglevel", "error"]
    for image in images:
        command.extend(["-i", str(image)])
    scaled = "".join(
        f"[{index}:v]scale=640:640:force_original_aspect_ratio=decrease,"
        f"pad=640:640:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[t{index}];"
        for index in range(len(images))
    )
    inputs = "".join(f"[t{index}]" for index in range(len(images)))
    command.extend([
        "-filter_complex",
        f"{scaled}{inputs}xstack=inputs={len(images)}:"
        f"layout={_xstack_layout(len(images), columns)}:fill=black[out]",
        "-map", "[out]", "-frames:v", "1", str(sheet_path),
    ])
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    if result.returncode != 0 or not sheet_path.is_file():
        # One picture the model can actually see beats a sheet it cannot.
        return images[0]
    return sheet_path


def _xstack_layout(count: int, columns: int) -> str:
    """Grid positions for xstack, in the cell units FFmpeg expects."""
    cells = []
    for index in range(count):
        column, row = index % columns, index // columns
        cells.append(
            f"{'0' if column == 0 else '+'.join(['w0'] * column)}_"
            f"{'0' if row == 0 else '+'.join(['h0'] * row)}"
        )
    return "|".join(cells)


_REFERENCE_IMAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "visual_style": {"type": "string"},
        "palette": {"type": "array", "items": {"type": "string"}},
        "subjects": {"type": "array", "items": {"type": "string"}},
        "composition": {"type": "string"},
        "reusable_prompt": {"type": "string"},
    },
    "required": ["summary", "visual_style"],
}


@app.post("/api/projects/{project_id}/assets/analyze-images")
def analyze_reference_images(
    project_id: int,
    limit: int = Query(default=6, ge=1, le=12),
) -> dict[str, Any]:
    """Have a vision AI look at the images the user uploaded as reference.

    Whisper covers uploaded audio and video; images had no analysis at all,
    so a folder of reference art could be attached and then never read. The
    files are shown to the model directly rather than described from their
    names, and the result includes a prompt fragment the scene writer can
    reuse so the style actually reaches the images it generates.
    """
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    images = [
        asset for asset in database.list_project_assets(project_id)
        if str(asset.get("asset_type")) == "image"
        and Path(str(asset.get("file_path") or "")).is_file()
    ]
    if not images:
        raise HTTPException(status_code=400, detail="Dự án chưa có ảnh tham khảo nào được tải lên")

    chosen = images[:limit]
    sheet = _contact_sheet_for_review(
        [Path(str(asset["file_path"])) for asset in chosen], project_id
    )
    system_prompt = (
        "Ban XEM anh tham khao cua nguoi dung roi mo ta phong cach hinh anh cua chung.\n"
        "- 'summary': anh noi ve cai gi, dung mot doan ngan.\n"
        "- 'visual_style': phong cach ve/chup, chat lieu, do tuong phan, anh sang.\n"
        "- 'palette': cac mau chu dao.\n"
        "- 'subjects': nhung thu xuat hien nhieu lan.\n"
        "- 'composition': cach bo cuc va goc may.\n"
        "- 'reusable_prompt': mot doan tieng Anh ngan de gan vao prompt tao anh sau nay, "
        "dien ta dung phong cach nay.\n"
        "Chi mo ta nhung gi BAN THUC SU NHIN THAY. Neu khong xem duoc file, hay noi ro, TUYET DOI khong bia. "
        "Viet bang tieng Viet tru 'reusable_prompt'."
    )
    user_prompt = (
        f"Day la {len(chosen)} anh tham khao nguoi dung tai len cho du an nay"
        + (f" (ghep thanh mot bang de xem cung luc)." if len(chosen) > 1 else ".")
    )
    assignment = settings.agent_assignment("storyboard")
    executor = str(assignment.get("executor") or settings.orchestrator_provider())
    errors: list[str] = []
    for agent in dict.fromkeys([executor, "claude_code_cli", "codex_cli"]):
        if agent not in {"codex_cli", "claude_code_cli"}:
            continue
        try:
            if agent == "codex_cli":
                result = call_codex_vision_json(
                    system_prompt, user_prompt, _REFERENCE_IMAGE_SCHEMA, image_path=sheet
                )
            else:
                result = call_claude_code_cli_json(
                    system_prompt, user_prompt, _REFERENCE_IMAGE_SCHEMA, image_path=str(sheet)
                )
            break
        except (LlmError, CodexBridgeError) as exc:
            errors.append(f"{agent}: {exc}")
    else:
        raise HTTPException(
            status_code=502,
            detail="Không AI vision nào đọc được ảnh tham khảo. " + " | ".join(errors),
        )

    for asset in chosen:
        database.update_project_asset_analysis(int(asset["id"]), "completed")
    return {
        "status": "analyzed",
        "images_seen": len(chosen),
        "images_total": len(images),
        "result": result,
    }

@app.post("/api/projects/{project_id}/assets/upload")
def upload_project_asset(
    project_id: int,
    asset_type: AssetType = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    filename = Path(file.filename or "").name
    extension = Path(filename).suffix.lower()
    if not filename or extension not in _ASSET_EXTENSIONS[asset_type]:
        raise HTTPException(
            status_code=400,
            detail=f"Định dạng file không hợp lệ cho {asset_type}. Đuôi nhận được: {extension or 'không có'}",
        )

    asset_dir = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["assets"] / asset_type
    asset_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex[:12]}-{_safe_asset_stem(filename)}{extension}"
    target = asset_dir / stored_name
    digest = hashlib.sha256()
    total = 0
    try:
        with target.open("wb") as output:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > LOCAL_ASSET_MAX_BYTES:
                    raise HTTPException(status_code=413, detail="File vượt quá giới hạn upload local")
                digest.update(chunk)
                output.write(chunk)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Không thể lưu file local: {exc}") from exc

    asset = database.create_project_asset(
        project_id,
        asset_type,
        filename,
        str(target),
        mime_type=file.content_type or mimetypes.guess_type(filename)[0] or "",
        file_size=total,
        sha256=digest.hexdigest(),
    )
    if not asset:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return {"status": "uploaded", "asset": asset}


class ImportLocalAssetRequest(BaseModel):
    path: str = Field(min_length=3, max_length=1000)
    asset_type: AssetType = "video"


@app.post("/api/projects/{project_id}/assets/import-local")
def import_local_project_asset(project_id: int, payload: ImportLocalAssetRequest) -> dict[str, Any]:
    """Copy a file the browser already downloaded into the project's assets.

    Meta AI plays generated videos through MediaSource, so the <video> src is
    a blob: URL backed by streamed segments — not fetchable, which stranded
    every video job at "Failed to fetch" even with CDN host permissions. The
    workable route is to let the site's own Download button write the file to
    disk and import it from there, which this endpoint does.

    Reads a caller-supplied path, so it is deliberately fenced: the server
    only listens on 127.0.0.1, and the path must resolve inside the user's
    home directory (where every browser download lands) with an extension
    already allowed for that asset type.
    """
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    source = Path(payload.path).expanduser()
    try:
        source = source.resolve(strict=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Không đọc được file: {exc}") from exc
    if not source.is_file():
        raise HTTPException(status_code=400, detail="Đường dẫn không phải file")
    home = Path.home().resolve()
    if not source.is_relative_to(home):
        raise HTTPException(status_code=400, detail="Chỉ nhận file nằm trong thư mục người dùng")
    extension = source.suffix.lower()
    if extension not in _ASSET_EXTENSIONS[payload.asset_type]:
        raise HTTPException(
            status_code=400,
            detail=f"Định dạng file không hợp lệ cho {payload.asset_type}. Đuôi nhận được: {extension or 'không có'}",
        )
    size = source.stat().st_size
    if size > LOCAL_ASSET_MAX_BYTES:
        raise HTTPException(status_code=413, detail="File vượt quá giới hạn upload local")

    asset_dir = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["assets"] / payload.asset_type
    asset_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex[:12]}-{_safe_asset_stem(source.name)}{extension}"
    target = asset_dir / stored_name
    digest = hashlib.sha256()
    try:
        with source.open("rb") as src, target.open("wb") as output:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                output.write(chunk)
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Không thể sao chép file: {exc}") from exc

    asset = database.create_project_asset(
        project_id,
        payload.asset_type,
        source.name,
        str(target),
        mime_type=mimetypes.guess_type(source.name)[0] or "",
        file_size=size,
        sha256=digest.hexdigest(),
    )
    if not asset:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return {"status": "imported", "asset": asset}


@app.get("/api/assets/{asset_id}/download")
def download_project_asset(asset_id: int) -> FileResponse:
    asset = database.get_project_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Không tìm thấy asset")
    path = Path(str(asset["file_path"]))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File asset không còn tồn tại trên máy")
    return FileResponse(path, media_type=asset.get("mime_type") or "application/octet-stream", filename=asset["original_name"])


@app.patch("/api/assets/{asset_id}")
def rename_project_asset(asset_id: int, payload: RenameAssetRequest) -> dict[str, Any]:
    try:
        asset = database.rename_project_asset(asset_id, payload.original_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not asset:
        raise HTTPException(status_code=404, detail="Không tìm thấy asset")
    return {"status": "renamed", "asset": asset}


@app.get("/api/projects/{project_id}/thumbnails")
def list_project_thumbnails(project_id: int) -> list[dict[str, Any]]:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return database.list_project_thumbnails(project_id)


@app.post("/api/projects/{project_id}/thumbnails/generate")
def generate_project_thumbnails(
    project_id: int,
    payload: GenerateThumbnailsRequest = GenerateThumbnailsRequest(),
) -> dict[str, Any]:
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    final_path = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["exports"] / "final.mp4"
    script = database.get_latest_project_script(project_id)
    prompt = payload.prompt.strip() or str((script or {}).get("script_title") or project.get("title") or "")
    output_dir = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["assets"] / "thumbnails" / uuid.uuid4().hex[:10]
    try:
        files = generate_frame_thumbnails(final_path, output_dir, FFMPEG_BINARY, payload.variants)
    except ThumbnailGenerationError as exc:
        raise _api_error(exc) from exc
    thumbnails: list[dict[str, Any]] = []
    for index, path in enumerate(files, start=1):
        asset = database.create_project_asset(
            project_id,
            "image",
            f"thumbnail-{index:02d}.jpg",
            str(path),
            mime_type="image/jpeg",
            file_size=path.stat().st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        if not asset:
            raise HTTPException(status_code=500, detail="Không thể lưu thumbnail vào thư viện dự án")
        thumbnail = database.create_project_thumbnail(
            project_id,
            int(asset["id"]),
            provider="ffmpeg_frame",
            model="ffmpeg",
            prompt=prompt,
            seed=(payload.seed + index - 1) if payload.seed is not None else None,
        )
        if thumbnail:
            thumbnails.append(thumbnail)
    return {"status": "generated", "thumbnails": thumbnails}


@app.post("/api/thumbnails/{thumbnail_id}/select")
def select_project_thumbnail(thumbnail_id: int) -> dict[str, Any]:
    thumbnail = database.select_project_thumbnail(thumbnail_id)
    if not thumbnail:
        raise HTTPException(status_code=404, detail="Không tìm thấy thumbnail")
    return {"status": "selected", "thumbnail": thumbnail}


@app.post("/api/assets/{asset_id}/analyze")
def analyze_local_asset(asset_id: int, payload: AnalyzeAssetRequest) -> dict[str, Any]:
    asset = database.get_project_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Không tìm thấy asset")
    if asset["asset_type"] not in {"audio", "video"}:
        raise HTTPException(status_code=400, detail="Whisper hiện chỉ phân tích asset audio/video")
    if not payload.confirmed:
        raise HTTPException(status_code=400, detail="Phân tích local cần confirmed=true vì sẽ dùng CPU/GPU")
    database.update_project_asset_analysis(asset_id, "running")
    try:
        result = transcribe_local_file(asset["file_path"], f"asset-{asset_id}", language=payload.language or None)
        if not result["text"]:
            raise TranscriptionError("Whisper không nhận diện được lời thoại trong asset")
        transcript = save_asset_transcript_result(database, asset_id, result)
        database.update_project_asset_analysis(asset_id, "completed")
    except Exception as exc:
        database.update_project_asset_analysis(asset_id, "error", str(exc))
        raise _api_error(exc) from exc
    return {"status": "completed", "asset": database.get_project_asset(asset_id), "transcript": transcript}


@app.post("/api/timeline/{segment_id}/attach-asset")
def attach_asset_to_timeline(segment_id: int, payload: AttachAssetRequest) -> dict[str, Any]:
    result = database.attach_asset_to_timeline_segment(segment_id, payload.asset_id)
    if not result:
        raise HTTPException(status_code=400, detail="Asset không hợp lệ hoặc không cùng project với timeline segment")
    return {"status": "attached", **result}


@app.get("/api/projects/{project_id}/scene-jobs")
def list_scene_generation_jobs(project_id: int) -> list[dict[str, Any]]:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return database.list_scene_generation_jobs(project_id)



# Chat-style image providers where the raw storyboard visual_prompt (often
# written as a multi-step animation brief: "sau do...", "tiep theo...")
# reliably triggers the model to ask a clarifying question instead of
# generating directly — confirmed live across both Gemini and ChatGPT.
_CHAT_IMAGE_PROVIDERS = {"gemini_web_image", "chatgpt_web_image", "flow_image"}
# These produce video, not a still — the "collapse to one static frame"
# instruction _craft_image_prompt gives would be actively wrong here, so they
# get motion-oriented crafting (_craft_video_prompt) instead.
_CHAT_VIDEO_PROVIDERS = {"meta_ai_video", "flow_veo", "gflow_cli"}

_CRAFT_IMAGE_PROMPT_SCHEMA = {
    "type": "object",
    "properties": {"prompt": {"type": "string"}},
    "required": ["prompt"],
}
_CRAFT_VIDEO_PROMPT_SCHEMA = {
    "type": "object",
    "properties": {"prompt": {"type": "string"}},
    "required": ["prompt"],
}

_STAGE_AGENT_PREFERENCES = {
    "orchestration": ["codex_cli", "claude_code_cli", "antigravity"],
    "script": ["claude_code_cli", "codex_cli", "antigravity"],
    "storyboard": ["codex_cli", "claude_code_cli", "antigravity"],
    "image_generation": ["antigravity", "codex_cli", "claude_code_cli"],
    "video_generation": ["codex_cli", "claude_code_cli", "antigravity"],
}


def _auto_agent_order(stage: str, executor: str, allowed: list[str]) -> list[str]:
    """Rank allowed subscription agents by readiness and stage fit."""
    status_calls = {
        "codex_cli": codex_cli_status,
        "claude_code_cli": claude_code_cli_status,
        "antigravity": antigravity_cli_status,
    }
    readiness: dict[str, bool] = {}
    for agent in allowed:
        try:
            state = status_calls[agent]()
            readiness[agent] = bool(state.get("logged_in") or state.get("ready"))
        except Exception:
            readiness[agent] = False
    preferred = _STAGE_AGENT_PREFERENCES.get(stage, _STAGE_AGENT_PREFERENCES["orchestration"])
    preference_score = {agent: len(preferred) - index for index, agent in enumerate(preferred)}
    return sorted(
        allowed,
        key=lambda agent: (
            -int(readiness.get(agent, False)),
            -(preference_score.get(agent, 0) * 10 + (8 if agent == executor else 0)),
            agent,
        ),
    )


def _call_orchestrator_json(
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    *,
    stage: str = "orchestration",
) -> dict[str, Any]:
    """Route a structured task through the user's per-stage agent policy."""
    calls = {
        "codex_cli": call_codex_json,
        "claude_code_cli": call_claude_code_cli_json,
        "antigravity": call_antigravity_json,
    }
    assignment = settings.agent_assignment(stage)
    executor = str(assignment.get("executor") or settings.orchestrator_provider())
    mode = str(assignment.get("mode") or "auto")
    allowed = [str(item) for item in assignment.get("allowed_agents", []) if str(item) in calls]
    fallbacks = [
        str(item) for item in assignment.get("fallback_agents", [])
        if str(item) in calls and str(item) != executor
    ]
    if mode == "fixed":
        order = [executor]
    elif mode == "fallback":
        order = [executor, *fallbacks]
    else:
        auto_candidates = list(dict.fromkeys([*allowed, executor, *fallbacks]))
        order = _auto_agent_order(
            stage,
            executor,
            [agent for agent in auto_candidates if agent in calls],
        )
    order = list(dict.fromkeys(agent for agent in order if agent in calls and (not allowed or agent in allowed)))
    if not order:
        raise LlmError(f"Không có AI được phép thực hiện công đoạn {stage}")
    errors: list[str] = []
    first_error: LlmError | None = None
    for agent in order:
        try:
            return calls[agent](system_prompt, user_prompt, schema)
        except LlmError as exc:
            first_error = first_error or exc
            errors.append(f"{agent}: {exc}")
    raise LlmError(
        f"Các AI được gán cho công đoạn {stage} đều thất bại. " + " | ".join(errors)
    ) from first_error


def _scene_prompt_context(timeline: list[dict[str, Any]], position: int) -> str:
    """Narration and neighbouring shots for the scene at `position`.

    A scene's visual_prompt read on its own says nothing about who the
    characters are or what the shot before it established, so each image came
    back styled independently and the sequence did not look like one film.
    """
    if position < 0 or position >= len(timeline):
        return ""
    segment = timeline[position]
    parts = [f"Canh {segment.get('segment_index')} trong tong so {len(timeline)} canh."]
    narration = str(segment.get("voice_text") or "").strip()
    if narration:
        parts.append(f"Loi thoai canh nay: {narration[:400]}")
    if position > 0:
        previous = str(timeline[position - 1].get("visual_prompt") or "").strip()
        if previous:
            parts.append(f"Canh LIEN TRUOC: {previous[:220]}")
    if position + 1 < len(timeline):
        following = str(timeline[position + 1].get("visual_prompt") or "").strip()
        if following:
            parts.append(f"Canh LIEN SAU: {following[:220]}")
    return "\n".join(parts)


def _craft_image_prompt(raw_prompt: str, context: str = "") -> str:
    """Rewrites a storyboard's raw visual_prompt into a standalone
    single-image prompt via the app's configured orchestrator CLI (the
    user's own logged-in Claude/Codex subscription — not a metered API
    key), so a chat-based image AI can act on it immediately instead of
    asking what to draw. Falls back to the raw prompt untouched if the
    orchestrator call fails — an awkward prompt beats no job at all."""
    system_prompt = (
        "Ban la chuyen gia viet prompt cho AI tao anh (Gemini/ChatGPT/DALL-E). Nguoi dung se dua mo ta "
        "mot canh hoat hinh, co the co nhieu buoc chuyen dong theo thoi gian ('sau do', 'tiep theo', ...). "
        "Hay viet lai thanh MOT prompt tao MOT anh tinh duy nhat: cu the, ro rang, khong con yeu to trinh "
        "tu thoi gian — chi giu lai bo cuc/khoanh khac tinh dep nhat de minh hoa dung y chinh cua canh. "
        "Tra loi bang tieng Anh, ngan gon, khong hoi lai, khong giai thich them."
    )
    user_prompt = raw_prompt
    if context:
        # The scenes are shots of one film, so the prompt is written knowing
        # what surrounds it: same characters, same drawing style, no
        # contradiction with the shot before or after.
        system_prompt += (
            " Ban duoc cho biet loi thoai va cac canh lien ke. Hay giu NHAT QUAN nhan vat, trang phuc, "
            "boi canh va phong cach ve voi cac canh do — day la cac canh cua CUNG mot video. "
            "Khong mo ta lai noi dung canh khac, chi ve canh duoc yeu cau."
        )
        user_prompt = f"NGU CANH:\n{context}\n\nMO TA CANH CAN VE:\n{raw_prompt}"
    try:
        result = _call_orchestrator_json(system_prompt, user_prompt, _CRAFT_IMAGE_PROMPT_SCHEMA, stage="image_generation")
        crafted = str(result.get("prompt") or "").strip()
        return crafted or raw_prompt
    except LlmError:
        return raw_prompt


def _craft_gif_sheet_prompt(raw_prompt: str, context: str = "") -> str:
    """Ask the orchestrator to write the request for an animated scene.

    This used to wrap everything in a fixed "2x2 sprite sheet" instruction,
    on the premise that image sites cannot return an animated GIF. That
    premise is wrong — asked directly, ChatGPT and Gemini do produce one —
    and the workaround produced poor results: the four panels came back
    nearly identical, so the assembled loop barely moved and reviews scored
    it 4-5/10. The orchestrator now writes the actual request, and may ask
    for a real GIF or for successive frames, whichever suits the scene.
    """
    system_prompt = (
        "Ban la animation director, dang viet YEU CAU gui cho mot AI web (ChatGPT/Gemini) de co mot canh "
        "CO CHUYEN DONG cho video.\n"
        "Muc tieu: mot vong lap ngan, muot, lap lai duoc (khoang 3-6 giay).\n"
        "Ban duoc TU CHON cach dat van de, vi du:\n"
        "- Yeu cau thang mot file GIF dong (cac trang nay lam duoc, hay noi ro muon file .gif tai ve duoc)\n"
        "- Hoac yeu cau mot bang 2x2 gom bon khung hinh lien tiep de app tu ghep thanh GIF\n"
        "Dieu QUAN TRONG NHAT: chuyen dong phai THAY DOI RO RET giua cac khoanh khac. Loi thuong gap la "
        "bon khung gan nhu giong het nhau khien vong lap nhu dung yen — hay mo ta cu the vat the nao di "
        "chuyen tu dau den dau, thay doi bao nhieu, de khac biet nhin thay duoc ngay.\n"
        "Giu nhat quan nhan vat, trang phuc, boi canh, phong cach ve va goc camera. "
        "Tra ve prompt tieng Anh, ro rang, khong giai thich them."
    )
    user_prompt = raw_prompt
    if context:
        # Same reason as _craft_image_prompt: these are shots of one film, so
        # the loop must match the characters and style around it.
        system_prompt += (
            " Ban duoc cho biet loi thoai va cac canh lien ke — hay giu nhat quan nhan vat, trang phuc, "
            "boi canh va phong cach ve voi chung."
        )
        user_prompt = f"NGU CANH:\n{context}\n\nMO TA CANH CAN VE:\n{raw_prompt}"
    try:
        result = _call_orchestrator_json(system_prompt, user_prompt, _CRAFT_IMAGE_PROMPT_SCHEMA, stage="image_generation")
        motion_prompt = str(result.get("prompt") or "").strip() or raw_prompt
    except LlmError:
        # Only when the orchestrator itself failed: fall back to the fixed
        # sheet request rather than sending a plain still-image prompt to a
        # job that must come back with motion.
        return (
            "Create ONE 16:9 image as a clean 2x2 animation sprite sheet with FOUR equal 16:9 frames "
            "showing successive phases of a seamless short animation, reading top-left, top-right, "
            "bottom-left, bottom-right. Keep the same character design, clothing, background, lighting "
            "and camera in every panel; only the action changes, and it must change VISIBLY between "
            "panels. Each quadrant is a complete edge-to-edge frame. No captions, panel numbers, "
            "borders or watermark.\n\nAnimation to depict:\n"
            f"{raw_prompt}"
        )
    return motion_prompt


def _craft_video_prompt(raw_prompt: str, has_reference_image: bool) -> str:
    """Rewrites a storyboard's raw visual_prompt into a prompt for a
    chat-based video AI (Meta AI) — the mirror of _craft_image_prompt, but
    motion language is exactly what's wanted here rather than something to
    strip out. When the scene already has a generated still (image-to-video,
    the usual case once Storyboard images exist), the prompt only needs to
    describe how that frame should animate, not re-describe the composition
    from scratch."""
    context = (
        "Nguoi dung da co san MOT anh tinh se duoc dinh kem lam khung hinh dau (image-to-video) — "
        "prompt chi can mo ta CHUYEN DONG/HANH DONG xay ra tu khung hinh do, khong can mo ta lai bo cuc anh."
        if has_reference_image else
        "Nguoi dung chua co anh nao — AI se tao video hoan toan tu prompt (text-to-video), can mo ta ca "
        "bo cuc lan chuyen dong."
    )
    system_prompt = (
        f"Ban la chuyen gia viet prompt cho AI tao video ngan. {context} "
        "Hay viet lai mo ta canh duoi day thanh MOT prompt video ngan gon, cu the, ro rang ve chuyen dong "
        "xay ra trong video, phu hop de AI tao video hieu va tao ngay khong hoi lai. "
        # A chat surface that can do both stills and clips will answer with a
        # still unless the request names the medium — that happened live on
        # Meta AI, which returned an image for a video job.
        "Prompt PHAI bat dau bang mot cau yeu cau ro rang tao VIDEO (vi du 'Create a short animated video ...'), "
        "de AI khong hieu nham thanh tao anh tinh. "
        "Tra loi bang tieng Anh, ngan gon, khong hoi lai, khong giai thich them."
    )
    try:
        result = _call_orchestrator_json(system_prompt, raw_prompt, _CRAFT_VIDEO_PROMPT_SCHEMA, stage="video_generation")
        crafted = str(result.get("prompt") or "").strip()
        return crafted or raw_prompt
    except LlmError:
        return raw_prompt


class AnswerPromptQuestionRequest(BaseModel):
    original_prompt: str = Field(min_length=1, max_length=20_000)
    page_text: str = Field(default="", max_length=4000)
    kind: Literal["image", "video"] = "image"


_ANSWER_QUESTION_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


@app.post("/api/orchestrator/answer-prompt-question")
def answer_prompt_question(payload: AnswerPromptQuestionRequest) -> dict[str, Any]:
    """When a chat-based image AI asks a clarifying question instead of
    generating directly (confirmed live with both Gemini and ChatGPT), the
    browser extension sends the tail of the page's visible text here
    instead of guessing with one canned reply. The orchestrator CLI reads
    it and writes a short, natural confirmation so the chat can proceed
    without a human — same account/subscription used everywhere else in
    this app, not a metered API key."""
    # The answer has to name the right output type. While this was hardcoded
    # to "anh", video jobs got a reply asking the chat to produce a still —
    # observed live: Meta AI returned an image for a video job because the
    # auto-reply ended with "va tao hinh luon giup minh nhe".
    if payload.kind == "video":
        target = (
            "AI tao VIDEO. AI do vua hoi lai mot cau truoc khi tao video, thay vi tao ngay. "
        )
        instruction = (
            "xac nhan/chon phuong an hop ly nhat de AI tao VIDEO CO CHUYEN DONG ngay, khong hoi them. "
            "Cau tra loi phai noi ro la muon VIDEO (video clip co chuyen dong), tuyet doi khong duoc "
            "yeu cau tao anh tinh."
        )
    else:
        target = "AI tao anh. AI do vua hoi lai mot cau ve bo cuc/phong cach truoc khi tao anh, thay vi tao ngay. "
        instruction = "xac nhan/chon phuong an hop ly nhat de AI tiep tuc tao anh ngay, khong hoi them."
    system_prompt = (
        f"Ban dang giup tra loi thay nguoi dung trong mot cuoc chat voi {target}"
        "Duoi day la mo ta canh goc nguoi dung muon tao, roi den doan cuoi trang chat hien tai "
        "(co the lan lon voi noi dung khac ngoai cau hoi). "
        f"Hay viet MOT cau tra loi ngan gon, tu nhien, cung ngon ngu voi doan chat, {instruction}"
    )
    user_prompt = f"Mo ta canh goc:\n{payload.original_prompt}\n\nDuoi trang chat hien tai:\n{payload.page_text}"
    try:
        result = _call_orchestrator_json(system_prompt, user_prompt, _ANSWER_QUESTION_SCHEMA)
    except LlmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    answer = str(result.get("answer") or "").strip()
    if not answer:
        raise HTTPException(status_code=502, detail="Orchestrator khong tra ve cau tra loi")
    return {"answer": answer}


class BrowserPageElement(BaseModel):
    i: int
    tag: str = ""
    role: str = ""
    label: str = ""
    text: str = ""
    disabled: bool = False
    # Icon-only controls carry no label or text at all — position, size,
    # class/id hints and neighbouring text are the only things that make them
    # identifiable, and without them the orchestrator saw a bare "<button>".
    id: str = ""
    testid: str = ""
    cls: str = ""
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    ctx: str = ""


class BrowserViewport(BaseModel):
    w: int = 0
    h: int = 0


class BrowserActionRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    url: str = Field(default="", max_length=500)
    viewport: BrowserViewport = Field(default_factory=BrowserViewport)
    elements: list[BrowserPageElement] = Field(default_factory=list)
    page_text: str = Field(default="", max_length=3000)
    history: list[str] = Field(default_factory=list)
    step: int = 0


_BROWSER_ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["type", "click", "attach_image", "wait", "reload", "done", "fail"],
        },
        "index": {"type": "integer"},
        "text": {"type": "string"},
        # Optional follow-up steps to run without another round trip. One
        # decision costs ~11s of CLI time, so a 30-step run spent most of its
        # wall clock waiting on the orchestrator rather than on the page.
        "then": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["type", "click", "attach_image", "wait"]},
                    "index": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["action"],
            },
        },
        "reason": {"type": "string"},
    },
    "required": ["action", "reason"],
}


@app.post("/api/orchestrator/browser-action")
def decide_browser_action(payload: BrowserActionRequest) -> dict[str, Any]:
    """Picks the next UI action for the browser extension to perform.

    The extension used to hardcode which selector to click and in what order,
    which broke on every layout, language, and state difference the live site
    presented — most of a working session went into guessing selectors. This
    inverts that: the extension reports what is actually on the page and the
    orchestrator (the user's own CLI subscription, same as everywhere else in
    this app) decides one action at a time, so it can react to whatever the
    site actually shows instead of following a fixed script.
    """
    lines = []
    for element in payload.elements[:80]:
        parts = [f"[{element.i}] <{element.tag}>"]
        if element.role:
            parts.append(f"role={element.role}")
        if element.label:
            parts.append(f'label="{element.label[:80]}"')
        if element.text:
            parts.append(f'text="{element.text[:80]}"')
        if element.testid:
            parts.append(f'testid="{element.testid}"')
        if element.id:
            parts.append(f'id="{element.id}"')
        if element.cls:
            parts.append(f'class="{element.cls}"')
        if element.w or element.h:
            parts.append(f"tai=({element.x},{element.y}) kichthuoc={element.w}x{element.h}")
        if element.ctx:
            parts.append(f'canh="{element.ctx[:80]}"')
        if element.disabled:
            parts.append("DISABLED")
        lines.append(" ".join(parts))
    element_block = "\n".join(lines) or "(khong co phan tu nao)"
    viewport_note = (
        f"Kich thuoc man hinh: {payload.viewport.w}x{payload.viewport.h} "
        "(toa do 'tai=(x,y)' tinh tu goc TREN-TRAI; y cang lon la cang gan DAY man hinh, "
        "x cang lon la cang gan MEP PHAI)."
        if payload.viewport.w else ""
    )
    history_block = "\n".join(payload.history[-12:]) or "(chua lam gi)"

    system_prompt = (
        "Ban dang dieu khien mot trang web AI (Meta AI / Gemini / ChatGPT) thong qua mot extension trinh duyet, "
        "de hoan thanh MUC TIEU duoc giao. Moi luot ban chi chon DUNG MOT hanh dong tiep theo dua tren danh sach "
        "phan tu dang co tren trang.\n"
        "Cac hanh dong hop le:\n"
        "- type: go van ban vao phan tu (can 'index' va 'text')\n"
        "- click: bam vao phan tu (can 'index')\n"
        "- attach_image: dinh kem anh tham chieu vao o dinh kem file (can 'index'); "
        "chi dung khi MUC TIEU noi rang co san anh tham chieu\n"
        "- wait: cho trang xu ly (dung khi vua gui xong hoac AI dang tao noi dung)\n"
        "- reload: tai lai trang, dung khi trang bi loi/sap (vi du 'Application error') hoac giao dien "
        "bien mat het; sau khi tai lai se quay ve trang goc ban dau\n"
        "- done: muc tieu da hoan thanh (vi du video/anh ket qua da xuat hien)\n"
        "- fail: khong the hoan thanh, giai thich ly do trong 'reason'\n\n"
        "GOP NHIEU BUOC: moi lan hoi ban ton khoang 11 giay, nen neu ban CHAC CHAN ve chuoi thao tac tiep "
        "theo ma khong can nhin lai trang giua chung (vi du: go prompt vao o nhap ROI bam nut gui), hay dua "
        "them cac buoc do vao mang 'then' (toi da 4 buoc). Chi gop khi cac phan tu can thao tac DEU da co "
        "trong danh sach hien tai va ban tin chung khong bien mat sau buoc dau. Neu khong chac, cu tra ve "
        "mot hanh dong va se duoc nhin lai trang o luot sau.\n"
        "NHAN DIEN NUT KHONG CO CHU: nhieu nut chi co icon nen khong co label lan text. Hay dua vao "
        "toa do/kich thuoc, ten class/id, va chu o khoi ben canh ('canh=...') de suy ra chuc nang. "
        "Vi du nut gui/tao thuong la nut vuong nho nam o goc PHAI-DUOI cua khung soan prompt.\n"
        "QUY TAC CHONG LAP: xem ky phan CAC HANH DONG DA LAM. Neu ban da lam mot hanh dong ma trang "
        "khong tien trien theo huong mong muon, TUYET DOI khong lam lai hanh dong do lan nua — hay thu "
        "cach khac. Neu da thu 3 cach khac nhau ma van khong dung huong, hay tra ve 'fail' va noi ro ly do. "
        "Moi lan bam nham nut tao co the tieu ton luot tra phi cua nguoi dung, nen tha dung lai con hon lap lai. "
        "KIEM TRA LOAI KET QUA: neu MUC TIEU la tao video ma ket qua hien ra lai la anh tinh, thi day la SAI "
        "— dung tao them, hay tim dung chuc nang tao video hoac tra ve 'fail'.\n"
        "Nguyen tac: phan tu DISABLED thi khong bam duoc, hay 'wait' cho no mo khoa. "
        "Neu trang hoi lai mot cau de xac nhan, hay 'type' cau tra loi phu hop roi bam gui. "
        "Neu da gui prompt va dang cho ket qua, hay 'wait'. "
        "Neu trang chua o dung man hinh can thiet, hay 'click' de dieu huong den do truoc. "
        "Truong 'reason' viet ngan gon bang tieng Viet."
    )
    user_prompt = (
        f"MUC TIEU:\n{payload.goal}\n\n"
        f"URL hien tai: {payload.url}\n"
        f"{viewport_note}\n\n"
        f"CAC HANH DONG DA LAM (buoc {payload.step}):\n{history_block}\n\n"
        f"PHAN TU TREN TRANG:\n{element_block}\n\n"
        f"NOI DUNG CUOI TRANG:\n{payload.page_text}"
    )
    try:
        result = _call_orchestrator_json(system_prompt, user_prompt, _BROWSER_ACTION_SCHEMA)
    except LlmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    action = str(result.get("action") or "").strip()
    if action not in {"type", "click", "attach_image", "wait", "reload", "done", "fail"}:
        raise HTTPException(status_code=502, detail=f"Orchestrator tra ve hanh dong khong hop le: {action}")
    return {
        "action": action,
        "index": result.get("index"),
        "text": str(result.get("text") or ""),
        "reason": str(result.get("reason") or ""),
    }


_REVIEW_SCENE_SCHEMA = {
    "type": "object",
    "properties": {
        "saw": {"type": "string"},
        "matches": {"type": "boolean"},
        "score": {"type": "integer"},
        "issues": {"type": "string"},
        "should_regenerate": {"type": "boolean"},
    },
    "required": ["saw", "matches", "score", "issues", "should_regenerate"],
    "additionalProperties": False,
}

# A scene the model simply cannot get right would otherwise regenerate
# forever, spending paid quota on every attempt.
_MAX_AUTO_REGENERATE = 1
_REVIEW_PASS_SCORE = 6


def _review_scene_asset(file_path: Path, scene_prompt: str, kind: str) -> dict[str, Any]:
    """Has the orchestrator look at a generated file and judge it.

    Vision must follow the configured app orchestrator too. Both Codex and
    Claude receive the real local image, rather than being asked to infer its
    contents from a path or prompt.
    """
    system_prompt = (
        f"Ban la nguoi kiem tra chat luong {'video' if kind == 'video' else 'anh'} minh hoa cho video YouTube. "
        "Hay XEM ky file duoc cung cap, roi doi chieu voi mo ta canh mong muon.\n"
        "- 'saw': mo ta ngan gon nhung gi BAN THUC SU NHIN THAY. Neu khong xem duoc file, hay noi ro la "
        "khong xem duoc, TUYET DOI khong bia.\n"
        "- 'matches': noi dung co dung y mo ta canh khong.\n"
        "- 'score': 1-10 (do khop y + chat luong hinh anh: bo cuc, chu viet, chi tiet loi).\n"
        "- 'issues': cac loi cu the neu co (chu sai chinh ta, tay/chan bien dang, vat the thua...).\n"
        "- 'should_regenerate': chi dat true khi loi du nghiem trong de khong dung duoc cho video."
    )
    user_prompt = f"Mo ta canh mong muon:\n{scene_prompt}"
    temporary: tempfile.TemporaryDirectory[str] | None = None
    vision_path = file_path
    try:
        if file_path.suffix.lower() in {".gif", ".mp4", ".webm", ".mov", ".mkv"}:
            temporary = tempfile.TemporaryDirectory(prefix="youtube-ai-factory-motion-review-")
            frame_path = Path(temporary.name) / "motion-contact-sheet.png"
            duration = media_duration_seconds(file_path, FFMPEG_BINARY) or 4.0
            review_fps = max(0.1, 4.0 / max(0.25, duration))
            result = subprocess.run(
                [
                    FFMPEG_BINARY,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(file_path),
                    "-vf",
                    f"fps={review_fps:.6f},scale=480:-2,tile=2x2:padding=4:margin=4",
                    "-frames:v", "1",
                    str(frame_path),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if result.returncode == 0 and frame_path.is_file():
                vision_path = frame_path
                user_prompt += (
                    "\nFile đính kèm là contact sheet 2x2 gồm bốn thời điểm trải đều trong chuyển động. "
                    "Hãy kiểm tra cả tính nhất quán giữa bốn ô, không chỉ ô đầu tiên."
                )
        assignment = settings.agent_assignment("quality_review")
        reviewer = str(assignment.get("reviewer") or "auto")
        executor = str(assignment.get("executor") or settings.orchestrator_provider())
        vision_agents = ["codex_cli", "claude_code_cli"]
        if reviewer in vision_agents:
            order = [reviewer, *[agent for agent in vision_agents if agent != reviewer]]
        else:
            order = [agent for agent in vision_agents if agent != executor] + [executor]
        errors: list[str] = []
        for agent in dict.fromkeys(agent for agent in order if agent in vision_agents):
            try:
                if agent == "codex_cli":
                    return call_codex_vision_json(
                        system_prompt,
                        user_prompt,
                        _REVIEW_SCENE_SCHEMA,
                        image_path=vision_path,
                    )
                return call_claude_code_cli_json(
                    system_prompt, user_prompt, _REVIEW_SCENE_SCHEMA, image_path=str(vision_path)
                )
            except (LlmError, CodexBridgeError) as exc:
                errors.append(f"{agent}: {exc}")
        raise LlmError("Không AI vision nào nghiệm thu được cảnh. " + " | ".join(errors))
    finally:
        if temporary is not None:
            temporary.cleanup()


def _run_scene_review(job_id: int) -> dict[str, Any] | None:
    """Reviews a finished job and regenerates it once if the result is poor."""
    job = database.get_scene_generation_job(job_id)
    if not job or str(job.get("status")) != "completed":
        return None
    path = Path(str(job.get("timeline_visual_path") or job.get("output_path") or ""))
    if not path.is_file():
        return None
    segment = database.get_project_timeline_segment(int(job["timeline_segment_id"]))
    # A GIF job's provider prompt describes the 2x2 transport format. Review
    # the finished animation against the storyboard intent instead, otherwise
    # the vision model would incorrectly expect to see the whole sheet in one
    # extracted GIF frame.
    segment_prompt = str((segment or {}).get("visual_prompt") or job.get("prompt") or "")
    kind = "video" if path.suffix.lower() in {".mp4", ".webm", ".mov"} else "image"
    try:
        verdict = _review_scene_asset(path, segment_prompt, kind)
    except (LlmError, CodexBridgeError) as exc:
        database.save_scene_job_review(job_id, "skipped", 0, f"Khong cham duoc: {exc}")
        return None

    score = int(verdict.get("score") or 0)
    passed = bool(verdict.get("matches")) and score >= _REVIEW_PASS_SCORE
    note_parts = [str(verdict.get("saw") or "").strip()]
    if verdict.get("issues"):
        note_parts.append(f"Loi: {verdict['issues']}")
    note = " | ".join(part for part in note_parts if part)
    database.save_scene_job_review(job_id, "pass" if passed else "fail", score, note)

    if passed or not verdict.get("should_regenerate"):
        return verdict
    if int(job.get("auto_retry_count") or 0) >= _MAX_AUTO_REGENERATE:
        return verdict
    database.bump_scene_job_auto_retry(job_id)
    provider = str(job.get("provider") or "")
    if provider in database.EXTERNAL_SIDECAR_PROVIDERS:
        database.retry_scene_generation_job(job_id)
    else:
        scene_generation_worker.retry(job_id)
    return verdict


def _review_scene_in_background(job_id: int) -> None:
    """Reviewing takes ~15-30s of CLI time; the caller must not wait on it."""
    def review_then_release() -> None:
        try:
            _run_scene_review(job_id)
        except Exception as exc:
            database.save_scene_job_review(job_id, "skipped", 0, f"Không chấm được ảnh: {exc}")
        finally:
            # Image-to-video children remain in `waiting` while the image is
            # being judged. A rejected image may be regenerated once; only
            # the accepted/final image is allowed to become a start frame.
            # An unavailable reviewer must not strand the pipeline forever.
            database.release_scene_generation_dependents(job_id)

    threading.Thread(target=review_then_release, daemon=True).start()


# Internal providers (including gflow-cli) use the same cross-review gate as
# browser/Antigravity sidecars before dependent stages are released.
scene_generation_worker.set_completion_callback(_review_scene_in_background)


_PLAN_VISUALS_SCHEMA = {
    "type": "object",
    "properties": {
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_index": {"type": "integer"},
                    "kind": {"type": "string", "enum": ["image", "gif", "video"]},
                    "fps": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["segment_index", "kind", "reason"],
            },
        },
    },
    "required": ["scenes"],
}

# Which providers can actually produce each kind, so a plan can be honoured
# by picking from the right pool instead of sending a clip request to an
# image tool.
_IMAGE_CAPABLE_PROVIDERS = {
    "openai_image", "gemini_image", "antigravity_image",
    "flow_image", "gemini_web_image", "chatgpt_web_image",
}
_VIDEO_CAPABLE_PROVIDERS = {"gemini_veo", "runway", "gflow_cli", "flow_veo", "meta_ai_video"}


@app.post("/api/projects/{project_id}/timeline/plan-visuals")
def plan_timeline_visuals(
    project_id: int,
    motion_policy: Literal["balanced", "gif_only"] = "balanced",
) -> dict[str, Any]:
    """Decides per scene whether it wants a still, a short loop, or a clip.

    A talking point that holds one diagram on screen doesn't need a rendered
    clip, while a scene whose whole meaning is a number counting up or a bar
    growing reads as broken when frozen. Making that call per scene — rather
    than one setting for the whole project — is what keeps motion where it
    carries meaning and avoids paying for it where it doesn't.
    """
    script = database.get_latest_project_script(project_id)
    if not database.get_production_project(project_id) or not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án hoặc kịch bản")
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    if not timeline:
        raise HTTPException(status_code=400, detail="Cần tạo timeline trước")

    lines = []
    for segment in timeline:
        lines.append(
            f"[{segment.get('segment_index')}] ({segment.get('duration_seconds') or 0}s) "
            f"Loi thoai: {str(segment.get('voice_text') or '')[:180]} || "
            f"Hinh anh: {str(segment.get('visual_prompt') or '')[:260]}"
        )
    gif_policy = (
        "\nCHINH SACH BAT BUOC CUA PROJECT NAY: KHONG dung video. Moi canh can chuyen dong, ke ca canh "
        "co nhieu buoc, phai chon 'gif'. AI tao anh se lo phan chuyen dong (co the tra thang mot file GIF "
        "dong, hoac bon khung hinh lien tiep de App ghep lai). "
        "Tuyet doi khong tra ve kind='video'.\n"
        if motion_policy == "gif_only"
        else ""
    )
    system_prompt = (
        "Ban la dao dien hinh anh cho video YouTube. Voi TUNG canh duoi day, hay quyet dinh nen dung:\n"
        "- 'image': anh TINH — khi canh chi can mot hinh minh hoa giu nguyen tren man hinh\n"
        "- 'gif': vong lap ngan khong tieng — khi chi co MOT chuyen dong lap lai don gian "
        "(banh rang quay, mui ten chay, so nhay). Kem 'fps' hop ly (8-15 cho hoat hoa vector phang)\n"
        "- 'video': clip that — khi canh co nhieu buoc chuyen dong noi tiep nhau, hoac chuyen dong "
        "chinh la NOI DUNG cua canh (so dem tang dan, bieu do lon len, so sanh hai trang thai)\n\n"
        "Nguyen tac: chuyen dong ton kem, chi dung khi no MANG Y NGHIA. Canh chi giai thich mot so lieu "
        "tinh thi dung 'image'. Tra ve dung so canh, moi canh mot muc, kem 'reason' ngan bang tieng Viet."
        + gif_policy
    )
    try:
        result = _call_orchestrator_json(system_prompt, "\n".join(lines), _PLAN_VISUALS_SCHEMA, stage="storyboard")
    except LlmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    by_index = {int(segment.get("segment_index") or 0): segment for segment in timeline}
    planned: list[dict[str, Any]] = []
    for entry in result.get("scenes") or []:
        segment = by_index.get(int(entry.get("segment_index") or -1))
        if not segment:
            continue
        kind = str(entry.get("kind") or "image")
        if motion_policy == "gif_only" and kind == "video":
            kind = "gif"
        fps = int(entry.get("fps") or 0) if kind in {"gif", "video"} else 0
        updated = database.set_segment_visual_kind(
            int(segment["id"]), kind, fps=fps, reason=str(entry.get("reason") or "")
        )
        if updated:
            planned.append({
                "segment_id": updated["id"],
                "segment_index": updated["segment_index"],
                "kind": updated["visual_kind"],
                "fps": updated["visual_fps"],
                "reason": updated["visual_kind_reason"],
            })
    counts: dict[str, int] = {}
    for item in planned:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    return {"status": "planned", "scenes": planned, "by_kind": counts, "total_segments": len(timeline)}


_EDIT_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "pacing": {"type": "string"},
        "music_mood": {"type": "string"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_index": {"type": "integer"},
                    "transition": {"type": "string", "enum": ["cut", "fade"]},
                    "effect": {"type": "string", "enum": ["zoom_in", "zoom_out", "static"]},
                    "note": {"type": "string"},
                },
                "required": ["segment_index", "transition", "effect"],
            },
        },
    },
    "required": ["scenes"],
}


@app.post("/api/projects/{project_id}/edit-plan")
def plan_project_edit(project_id: int) -> dict[str, Any]:
    """Plans the cut before rendering: per-scene transition and camera move.

    The renderer applied one blanket transition and the same gentle push-in
    to every scene. Deciding this per scene is what makes a sequence read as
    edited — a hard cut where two states are being compared, a hold where the
    viewer is meant to read something, a pull-back where the frame is opening
    out.
    """
    script = database.get_latest_project_script(project_id)
    if not database.get_production_project(project_id) or not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án hoặc kịch bản")
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    if not timeline:
        raise HTTPException(status_code=400, detail="Cần tạo timeline trước")

    lines = []
    for segment in timeline:
        lines.append(
            f"[{segment.get('segment_index')}] ({segment.get('duration_seconds') or 0}s, "
            f"loai hinh: {segment.get('visual_kind') or 'chua ro'}) "
            f"Loi thoai: {str(segment.get('voice_text') or '')[:160]} || "
            f"Hinh: {str(segment.get('visual_prompt') or '')[:200]}"
        )
    system_prompt = (
        "Ban la nguoi dung phim (editor) cho video YouTube giai thich tai chinh. "
        "Voi TUNG canh, hay quyet dinh cach vao canh va chuyen dong camera:\n"
        "- 'transition': 'cut' (cat thang, dung khi doi y dot ngot hoac so sanh hai trang thai) "
        "hoac 'fade' (mem, dung khi mach y chay lien tuc)\n"
        "- 'effect': 'zoom_in' (day vao dan, tao cam giac tap trung), 'zoom_out' (keo lui, mo rong boi canh), "
        "hoac 'static' (dung yen hoan toan — dung khi nguoi xem can DOC noi dung tren man hinh)\n"
        "- 'note': ly do ngan bang tieng Viet\n\n"
        "Luu y: canh loai 'video'/'gif' da co chuyen dong san, nen thuong de 'static' de khong chong chuyen dong. "
        "Ngoai ra tra ve 'pacing' (nhip tong the) va 'music_mood' (khong khi nhac nen) cho ca video."
    )
    try:
        result = _call_orchestrator_json(system_prompt, "\n".join(lines), _EDIT_PLAN_SCHEMA, stage="storyboard")
    except LlmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    by_index = {int(segment.get("segment_index") or 0): segment for segment in timeline}
    planned: list[dict[str, Any]] = []
    for entry in result.get("scenes") or []:
        segment = by_index.get(int(entry.get("segment_index") or -1))
        if not segment:
            continue
        transition = str(entry.get("transition") or "fade")
        effect = str(entry.get("effect") or "zoom_in")
        database.save_segment_edit(int(segment["id"]), transition, effect, str(entry.get("note") or ""))
        planned.append({
            "segment_id": segment["id"],
            "segment_index": segment["segment_index"],
            "transition": transition,
            "effect": effect,
            "note": str(entry.get("note") or ""),
        })
    return {
        "status": "planned",
        "pacing": str(result.get("pacing") or ""),
        "music_mood": str(result.get("music_mood") or ""),
        "scenes": planned,
    }


class OrchestrateRequest(BaseModel):
    intent: str = Field(min_length=3, max_length=2000)
    # Costly steps stay behind an explicit confirmation: the plan is shown
    # first so nothing spends generation quota before it has been read.
    dry_run: bool = True


# The orchestrator's tools, as data rather than a hand-written enum.
#
# It used to pick from six fixed action names whose behaviour lived in an
# if/elif chain below, so the workflow was Python's and the orchestrator only
# decorated it. A goal nobody had anticipated — "redo the three worst-scoring
# scenes" — had no way to be expressed at all. Tools are registered here
# instead: adding a capability is adding an entry, and the orchestrator
# composes its own sequence with its own arguments.
#
# Cost is stated plainly because it is the fact it most needs when choosing,
# and paid quota has been spent carelessly before.
_ORCHESTRATOR_TOOLS: dict[str, dict[str, str]] = {
    "read_scenes": {
        "description": (
            "Doc chi tiet tung canh: loai hinh da lap ke hoach, da co hinh chua, ke hoach dung. "
            "Dung khi can biet ro truoc khi quyet dinh."
        ),
        "args": "khong co",
        "cost": "mien phi",
    },
    "plan_scene_kinds": {
        "description": (
            "Quyet dinh moi canh nen dung anh tinh / gif / video, kem fps va ly do. "
            "Chay TRUOC khi tao hinh."
        ),
        "args": "motion_policy (tuy chon): 'balanced' | 'gif_only'",
        "cost": "mien phi (chi goi AI dieu phoi)",
    },
    "plan_edit": {
        "description": "Lap ke hoach dung phim tung canh: cat hay mo, day vao / keo lui / dung yen.",
        "args": "khong co",
        "cost": "mien phi (chi goi AI dieu phoi)",
    },
    "create_scene_jobs": {
        "description": (
            "Xep hang tao hinh cho cac canh CON THIEU; tra ve ngay, khong cho AI ve xong. "
            "Canh video luon duoc tao anh tinh truoc roi moi dung video tu chinh anh do."
        ),
        "args": (
            "kind: 'image' | 'gif' | 'video'; providers (tuy chon): danh sach key provider "
            "('gflow_image' = Flow CLI, khong can trinh duyet, tao GIF bang chuoi khung noi tiep; "
            "'chatgpt_web_image', 'gemini_web_image' = qua Extension); "
            "limit (tuy chon): so canh toi da"
        ),
        "cost": "image/gif: theo goi thue bao. video: TON TIN DUNG",
    },
    "cancel_pending_jobs": {
        "description": "Huy moi job cua du an chua bat dau. Dung khi xep nham hoac muon dung lai.",
        "args": "khong co",
        "cost": "mien phi",
    },
    "review_scene": {
        "description": (
            "Cham lai mot canh da hoan thanh: AI mo file ra xem va cho diem. "
            "Dung khi muon kiem tra lai truoc khi quyet dinh tao lai."
        ),
        "args": "job_id: so hieu job da hoan thanh",
        "cost": "mien phi (chi goi AI cham)",
    },
    "review_script": {
        "description": (
            "Cho MOT AI KHAC doc soat kich ban: mach logic, suc giu chan cua hook, so lieu dang ngo, "
            "doan thua. Nen chay TRUOC khi dung storyboard vi loi o day lan sang moi canh."
        ),
        "args": "khong co",
        "cost": "mien phi (chi goi AI soat)",
    },
    "review_voice": {
        "description": (
            "Nghe lai giong doc va doi chieu voi loi thoai: cau bi bo, tu doc sai, so lieu doc lech. "
            "May nghe lai chay cuc bo tren PC."
        ),
        "args": "limit (tuy chon): so canh toi da can kiem tra",
        "cost": "mien phi, nhung cham vi phai nghe lai tung file",
    },
}

_ORCHESTRATE_SCHEMA = {
    "type": "object",
    "properties": {
        "understanding": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    # Generated from the registry above, so registering a tool
                    # is all it takes to make it selectable.
                    "tool": {"type": "string", "enum": sorted(_ORCHESTRATOR_TOOLS)},
                    "kind": {"type": "string"},
                    "motion_policy": {"type": "string"},
                    "job_id": {"type": "integer"},
                    "limit": {"type": "integer"},
                    "providers": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["tool", "reason"],
            },
        },
    },
    "required": ["understanding", "steps"],
}


def _run_orchestrator_tool(project_id: int, step: dict[str, Any]) -> dict[str, Any]:
    """Carry out one tool the orchestrator asked for."""
    tool = str(step.get("tool") or "")
    if tool == "read_scenes":
        script = database.get_latest_project_script(project_id)
        timeline = database.list_project_timeline(
            project_id, script_id=int(script["id"]) if script else None
        )
        return {
            "status": "ok",
            "scenes": [
                {
                    "segment_index": segment.get("segment_index"),
                    "visual_kind": segment.get("visual_kind") or "",
                    "has_visual": bool(str(segment.get("visual_path") or "").strip()),
                    "edit_transition": segment.get("edit_transition") or "",
                }
                for segment in timeline
            ],
        }
    if tool == "plan_scene_kinds":
        policy = "gif_only" if str(step.get("motion_policy") or "") == "gif_only" else "balanced"
        return plan_timeline_visuals(project_id, motion_policy=policy)
    if tool == "plan_edit":
        return plan_project_edit(project_id)
    if tool == "cancel_pending_jobs":
        return cancel_pending_scene_jobs(project_id)
    if tool == "review_scene":
        job_id = int(step.get("job_id") or 0)
        if job_id <= 0:
            return {"status": "error", "detail": "review_scene can 'job_id'"}
        return review_scene_job(job_id)
    if tool == "review_script":
        return review_project_script(project_id)
    if tool == "review_voice":
        limit = step.get("limit")
        return review_project_voice(project_id, limit=max(0, min(int(limit), 200)) if limit else 0)
    if tool == "create_scene_jobs":
        kind = str(step.get("kind") or "image")
        wants_video = kind == "video"
        providers = [str(item) for item in (step.get("providers") or [])]
        if not providers:
            providers = ["gflow_cli"] if wants_video else [
                "gflow_image", "chatgpt_web_image", "gemini_web_image",
            ]
        # The Flow browser extension is retired; anything still naming it is
        # rewritten rather than quietly routed back through it.
        providers = list(dict.fromkeys(
            "gflow_cli" if provider == "flow_veo" else provider for provider in providers
        ))
        limit = step.get("limit")
        return queue_scene_generation_batch(
            project_id,
            BatchSceneGenerationRequest(
                providers=providers,
                respect_plan=True,
                motion_as_gif=kind == "gif",
                limit=max(1, min(int(limit), 500)) if limit else None,
                requires_reference_image=wants_video,
                reference_image_provider="flow_image",
                ratio="1280:720",
                duration_seconds=5,
                confirmed=True,
            ),
        )
    return {"status": "error", "detail": f"Cong cu khong ton tai: {tool}"}


def _project_state_summary(project_id: int) -> str:
    """What the orchestrator needs to know before choosing steps."""
    script = database.get_latest_project_script(project_id)
    if not script:
        return "Du an chua co kich ban."
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    if not timeline:
        return "Du an chua co timeline."
    with_visual = sum(1 for s in timeline if str(s.get("visual_path") or "").strip())
    kinds: dict[str, int] = {}
    for segment in timeline:
        kind = str(segment.get("visual_kind") or "chua-lap-ke-hoach")
        kinds[kind] = kinds.get(kind, 0) + 1
    edited = sum(1 for s in timeline if str(s.get("edit_transition") or "").strip())
    return (
        f"Tong so canh: {len(timeline)}. Da co hinh: {with_visual}. Con thieu: {len(timeline) - with_visual}.\n"
        f"Ke hoach loai hinh (visual_kind): {kinds}.\n"
        f"So canh da co ke hoach dung phim: {edited}/{len(timeline)}.\n"
        "Trang thai AI tao canh: "
        + "; ".join(
            f"{state['provider']} failures={state.get('consecutive_failures', 0)} "
            f"last_error={str(state.get('last_error') or '')[:120]}"
            for state in database.list_scene_provider_states()
        )
    )


@app.post("/api/projects/{project_id}/orchestrate")
def orchestrate_project(project_id: int, payload: OrchestrateRequest) -> dict[str, Any]:
    """Turns a plain-language request into an ordered run of the app's tools.

    Routing every button through the orchestrator would put a ~11s CLI call
    behind each click and make the app fragile. This keeps the direct
    controls as they are and adds one place to hand over an intent: the
    orchestrator reads the project's actual state, picks which tools to run
    and in what order, and returns the plan. Nothing that spends generation
    quota runs until the plan has been seen and confirmed.
    """
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")

    catalogue = "\n".join(
        f"- {name}: {spec['description']}\n  Tham so: {spec['args']}\n  Chi phi: {spec['cost']}"
        for name, spec in sorted(_ORCHESTRATOR_TOOLS.items())
    )
    system_prompt = (
        "Ban la AI dieu phoi cua mot app san xuat video YouTube. Nguoi dung noi mong muon cua ho; "
        "ban TU quyet dinh cac buoc va thu tu dua tren tinh trang thuc te cua du an.\n\n"
        f"CAC CONG CU BAN CO THE GOI:\n{catalogue}\n\n"
        "Hay tu ghep cac cong cu tren thanh chuoi buoc phu hop voi yeu cau — khong bi rang buoc vao "
        "mot quy trinh co san. Neu can biet ro hon truoc khi quyet dinh, goi 'read_scenes' truoc.\n\n"
        "NGUYEN TAC:\n"
        "- Khong tao lai thu da co va dang dung duoc.\n"
        "- Chua co ke hoach loai hinh ma nguoi dung muon tao hang loat: goi 'plan_scene_kinds' truoc.\n"
        "- Chi tao video khi that su can vi no TON TIEN. Neu nguoi dung muon GIF thay video: "
        "'plan_scene_kinds' voi motion_policy='gif_only', roi 'create_scene_jobs' voi kind='gif'.\n"
        "- Nguoi dung noi dang TEST/THU: dat 'limit' nho (vi du 3).\n"
        "- Dong co video duy nhat la 'gflow_cli'; extension Flow ('flow_veo') da nghi.\n"
        "- Tao anh/GIF: uu tien 'gflow_image' (Flow CLI, khong can trinh duyet mo san; GIF duoc ve "
        "thanh chuoi khung noi tiep nen NOI DUNG that su chuyen dong). Them 'chatgpt_web_image' va "
        "'gemini_web_image' de chay song song khi can nhieu canh cung luc.\n"
        "- Provider vua timeout/loi thi chon provider khac, dung lap lai provider vua hong.\n"
        "- Khong can lam gi thi tra ve 'steps' rong va giai thich trong 'understanding'.\n"
        "Viet 'reason' ngan gon bang tieng Viet."
    )
    user_prompt = (
        f"MONG MUON CUA NGUOI DUNG:\n{payload.intent}\n\n"
        f"TINH TRANG DU AN:\n{_project_state_summary(project_id)}"
    )
    try:
        result = _call_orchestrator_json(system_prompt, user_prompt, _ORCHESTRATE_SCHEMA)
    except LlmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    steps = [
        {
            "tool": str(step.get("tool") or ""),
            "reason": str(step.get("reason") or ""),
            **{
                key: step[key]
                for key in ("kind", "motion_policy", "job_id", "limit", "providers")
                if step.get(key) not in (None, "", [])
            },
        }
        for step in (result.get("steps") or [])
        if str(step.get("tool") or "") in _ORCHESTRATOR_TOOLS
    ]
    if payload.dry_run:
        return {
            "status": "planned",
            "orchestrator_provider": settings.orchestrator_provider(),
            "understanding": str(result.get("understanding") or ""),
            "steps": steps,
            "note": "Chưa chạy gì. Gửi lại với dry_run=false để thực hiện.",
        }

    executed: list[dict[str, Any]] = []
    for step in steps:
        try:
            outcome = _run_orchestrator_tool(project_id, step)
        except HTTPException as exc:
            outcome = {"status": "error", "detail": str(exc.detail)}
        executed.append({**step, "result": outcome})
    return {
        "status": "done",
        "orchestrator_provider": settings.orchestrator_provider(),
        "understanding": str(result.get("understanding") or ""),
        "steps": executed,
    }


_CRAFT_GIF_FRAMES_SCHEMA = {
    "type": "object",
    "properties": {
        "frames": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["frames"],
}


def _craft_gif_frame_prompts(raw_prompt: str, context: str = "", count: int = GFLOW_GIF_FRAME_COUNT) -> list[str]:
    """Write one prompt per frame of a motion loop, as a progression.

    The sheet route asks a single drawing to hold four moments at quarter
    size, and what came back moved the wallpaper while the subject of the
    scene sat still. Flow draws each frame full size from the one before it,
    so the orchestrator is asked for the steps of the movement instead: what
    has advanced by frame two, by frame three. Each step names its own change,
    which is the part the sheet prompt could only ask for and not enforce.
    """
    system_prompt = (
        f"Ban la animation director. Hay chia MOT chuyen dong ngan thanh {count} KHUNG lien tiep.\n"
        "AI ve se ve khung 1 truoc, roi dung chinh khung do lam ANH THAM CHIEU de ve khung 2, va cu the. "
        "Vi vay:\n"
        f"- 'frames': dung {count} prompt tieng Anh, theo dung thu tu.\n"
        "- Khung 1: mo ta day du canh (nhan vat, boi canh, anh sang, goc may, phong cach ve).\n"
        "- Cac khung sau: KHONG mo ta lai toan canh. Viet dang 'same shot as the reference image, but ...' "
        "va chi noi RO DIEU GI DA THAY DOI so voi khung truoc.\n"
        "Dieu QUAN TRONG NHAT: thu thay doi phai la NOI DUNG CHINH cua canh — con so tang len, o duoc to "
        "dan, tay chi dich chuyen, cot bieu do cao them — chu KHONG phai chi co hau canh nhap nhay. "
        "Moi khung phai khac khung truoc du de nhin thay ngay.\n"
        "Chuyen dong nen di mot chieu tu khung 1 den khung cuoi (app se phat xuoi roi nguoc de tao vong lap)."
    )
    user_prompt = raw_prompt
    if context:
        system_prompt += (
            " Ban duoc cho biet loi thoai va cac canh lien ke — hay giu nhat quan nhan vat, trang phuc, "
            "boi canh va phong cach ve voi chung."
        )
        user_prompt = f"NGU CANH:\n{context}\n\nMO TA CANH CAN VE:\n{raw_prompt}"
    result = _call_orchestrator_json(
        system_prompt, user_prompt, _CRAFT_GIF_FRAMES_SCHEMA, stage="image_generation"
    )
    frames = [str(item).strip() for item in (result.get("frames") or []) if str(item).strip()]
    if len(frames) < 2:
        raise LlmError("Orchestrator khong tra ve du khung hinh cho GIF")
    return frames[:count]


def _write_job_prompt(job: dict[str, Any]) -> str:
    """Write the prompt for a job that is about to run.

    Jobs are queued carrying the storyboard's own words, so this is where the
    real prompt gets written — one CLI call per job, off the request path.
    Reads the scene's neighbours for continuity, the same as before.
    """
    raw_prompt = str(job.get("prompt") or "").strip()
    if not raw_prompt:
        return ""
    segment_id = int(job.get("timeline_segment_id") or 0)
    context = ""
    segment = database.get_project_timeline_segment(segment_id) if segment_id else None
    if segment:
        timeline = database.list_project_timeline(
            int(job["project_id"]), script_id=int(segment.get("script_id") or 0) or None
        )
        position = next(
            (index for index, item in enumerate(timeline) if int(item["id"]) == segment_id),
            -1,
        )
        context = _scene_prompt_context(timeline, position)

    kind = str(job.get("job_kind") or "")
    if kind == "gif":
        # Flow redraws each frame from the previous one, so it gets the steps
        # of the movement rather than a single sheet request. Sites reached
        # through the browser cannot chain like that and keep the sheet.
        if str(job.get("provider") or "") == "gflow_image":
            try:
                frames = _craft_gif_frame_prompts(raw_prompt, context=context)
            except LlmError:
                return _craft_gif_sheet_prompt(raw_prompt, context=context)
            return json.dumps({"frames": frames}, ensure_ascii=False)
        return _craft_gif_sheet_prompt(raw_prompt, context=context)
    if kind == "video":
        return _craft_video_prompt(
            raw_prompt, has_reference_image=bool(job.get("requires_reference_image"))
        )
    return _craft_image_prompt(raw_prompt, context=context)


# Registered here, after the definition above: the worker only calls it
# once a job actually starts, so queueing never waits on the CLI.
scene_generation_worker.set_prompt_crafter(_write_job_prompt)


def _require_scene_provider_config(provider: str) -> None:
    """Rejects a provider whose API key is missing, before any job is made."""
    if provider == "meta_ai_video":
        raise HTTPException(
            status_code=400,
            detail="Meta AI hiện không tạo được video trong luồng đã kiểm chứng; provider này tạm khóa để tránh job kẹt.",
        )
    provider_state = database.get_scene_provider_state(provider)
    if provider_state.get("circuit_open"):
        raise HTTPException(
            status_code=429,
            detail=(
                f"Provider {provider} đang tạm ngắt đến {provider_state.get('opened_until')} "
                f"sau nhiều lỗi liên tiếp. Lỗi gần nhất: {provider_state.get('last_error') or 'không rõ'}"
            ),
        )
    if provider == "runway":
        runway_key, _ = settings.runway_config()
        if not runway_key:
            raise HTTPException(status_code=400, detail="Chưa cấu hình Runway API trong Kết nối AI")
    elif provider == "openai_image":
        openai_key, _ = settings.openai_config()
        if not openai_key:
            raise HTTPException(status_code=400, detail="Chưa cấu hình OPENAI_API_KEY trong Kết nối AI")
    elif provider in {"gemini_image", "gemini_veo"}:
        gemini_key, _, _ = settings.gemini_config()
        if not gemini_key:
            raise HTTPException(status_code=400, detail="Chưa cấu hình GEMINI_API_KEY trong Kết nối AI")
    elif provider in {"gflow_cli", "gflow_image"}:
        gflow = gflow_cli_status()
        if not gflow.get("installed"):
            raise HTTPException(status_code=400, detail="Chưa cài gflow-cli; mở Kết nối AI để cài/kiểm tra lại")
        if not gflow.get("logged_in"):
            raise HTTPException(status_code=400, detail="Google Flow chưa đăng nhập; mở Kết nối AI và bấm Đăng nhập Google Flow")


_SCENE_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_SCENE_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}


def _scene_failure_kind(error: str) -> str:
    normalized = error.lower()
    if any(key in normalized for key in ("quota", "credit", "tín dụng", "resource_exhausted", "hạn mức")):
        return "quota"
    if any(key in normalized for key in ("timeout", "quá lâu", "heartbeat", "mất kết nối")):
        return "timeout"
    return "provider"


def _reference_image_asset_for_segment(project_id: int, segment: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve/register the timeline's still image as an asset for image-to-video."""
    raw_path = str(segment.get("visual_path") or "").strip()
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.suffix.lower() not in _SCENE_IMAGE_EXTENSIONS or not path.is_file():
        return None
    asset = database.find_project_asset_by_path(project_id, str(path))
    if asset and asset.get("asset_type") == "image":
        return asset
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return database.create_project_asset(
        project_id,
        "image",
        path.name,
        str(path),
        mime_type=mimetypes.guess_type(path.name)[0] or "image/png",
        file_size=path.stat().st_size,
        sha256=digest.hexdigest(),
    )


@app.post("/api/projects/{project_id}/scene-jobs")
def queue_scene_generation_job(
    project_id: int,
    payload: CreateSceneGenerationRequest,
) -> dict[str, Any]:
    if not payload.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Tao canh AI se goi dich vu cloud va phat sinh chi phi; can confirmed=true",
        )
    _require_scene_provider_config(payload.provider)
    is_video_provider = payload.provider in _VIDEO_CAPABLE_PROVIDERS
    if payload.motion_as_gif and is_video_provider:
        raise HTTPException(status_code=400, detail="GIF chỉ nhận provider tạo ảnh")
    if payload.requires_reference_image and not is_video_provider:
        raise HTTPException(status_code=400, detail="Chỉ video provider mới nhận chế độ image-to-video")
    if payload.requires_reference_image and payload.reference_asset_id is None:
        raise HTTPException(
            status_code=400,
            detail="Cảnh chưa có ảnh nguồn. Hãy tạo/chọn ảnh cho cảnh trước khi tạo video.",
        )
    if payload.reference_asset_id is not None:
        asset = database.get_project_asset(payload.reference_asset_id)
        if not asset or int(asset["project_id"]) != project_id:
            raise HTTPException(status_code=400, detail="Asset tham chieu khong thuoc project")
        if asset["asset_type"] != "image":
            raise HTTPException(status_code=400, detail="Chi co the dung anh lam asset tham chieu")
    # The prompt is written when the job runs, not here — see
    # _write_job_prompt. Queueing stays instant and callable-off.
    prompt_text = payload.prompt
    job = database.create_scene_generation_job(
        project_id,
        payload.timeline_segment_id,
        payload.provider,
        prompt_text,
        duration_seconds=payload.duration_seconds,
        ratio=payload.ratio,
        reference_asset_id=payload.reference_asset_id,
        job_kind="gif" if payload.motion_as_gif else ("video" if is_video_provider else "image"),
        requires_reference_image=payload.requires_reference_image,
        prompt_pending=True,
    )
    if not job:
        raise HTTPException(status_code=400, detail="Segment timeline khong hop le hoac khong thuoc project")
    if payload.provider not in database.EXTERNAL_SIDECAR_PROVIDERS:
        scene_generation_worker.enqueue(int(job["id"]))
    delegated = payload.provider in database.EXTERNAL_SIDECAR_PROVIDERS
    return {"status": "delegated" if delegated else "queued", "job": job}


@app.post("/api/projects/{project_id}/scene-jobs/batch")
def queue_scene_generation_batch(project_id: int, payload: BatchSceneGenerationRequest) -> dict[str, Any]:
    if not payload.confirmed:
        raise HTTPException(status_code=400, detail="Tạo toàn bộ cảnh AI có thể phát sinh chi phí; cần confirmed=true")
    # Preserve order while removing duplicates, so the round-robin below
    # doesn't hand one provider twice the share.
    providers = list(dict.fromkeys(payload.providers)) or [payload.provider]
    for provider in providers:
        _require_scene_provider_config(provider)
    if payload.motion_as_gif:
        if payload.requires_reference_image:
            raise HTTPException(status_code=400, detail="Chế độ GIF không được đồng thời gọi pipeline video")
        invalid_gif_providers = [provider for provider in providers if provider not in _IMAGE_CAPABLE_PROVIDERS]
        if invalid_gif_providers:
            raise HTTPException(
                status_code=400,
                detail=f"GIF chỉ dùng AI tạo ảnh, không nhận video provider: {', '.join(invalid_gif_providers)}",
            )
    if payload.requires_reference_image:
        invalid_video_providers = [provider for provider in providers if provider not in _VIDEO_CAPABLE_PROVIDERS]
        if invalid_video_providers:
            raise HTTPException(
                status_code=400,
                detail=f"Chế độ ảnh sang video chỉ nhận video provider: {', '.join(invalid_video_providers)}",
            )
        if payload.reference_image_provider not in _IMAGE_CAPABLE_PROVIDERS:
            raise HTTPException(status_code=400, detail="Provider chuẩn bị ảnh không hỗ trợ tạo ảnh")
        _require_scene_provider_config(payload.reference_image_provider)
    project = database.get_production_project(project_id)
    script = database.get_latest_project_script(project_id)
    if not project or not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án hoặc kịch bản")
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    if not timeline:
        raise HTTPException(status_code=400, detail="Cần tạo timeline trước khi tạo cảnh AI")
    image_pool = [p for p in providers if p in _IMAGE_CAPABLE_PROVIDERS]
    video_pool = [p for p in providers if p in _VIDEO_CAPABLE_PROVIDERS]
    active_segment_ids = {
        int(job["timeline_segment_id"])
        for job in database.list_scene_generation_jobs(project_id, limit=500)
        if str(job.get("status") or "") in {"waiting", "queued", "running"}
    }
    queued: list[dict[str, Any]] = []
    preparation_jobs: list[dict[str, Any]] = []
    counters = {"image": 0, "video": 0}
    for position, segment in enumerate(timeline):
        if payload.limit is not None and len(queued) >= payload.limit:
            break
        if int(segment["id"]) in active_segment_ids:
            continue
        visual_path = str(segment.get("visual_path") or "").strip()
        visual_suffix = Path(visual_path).suffix.lower() if visual_path else ""
        prompt = str(segment.get("visual_prompt") or "").strip()
        if not prompt:
            continue
        planned_kind = str(segment.get("visual_kind") or "")
        # A scene that is to become a video ALWAYS goes through the
        # image-first pipeline: make the still, then animate that exact
        # still. There is deliberately no text-to-video path in a batch, so
        # the rule does not depend on the caller remembering a flag — a clip
        # generated from the prompt alone would not match the storyboard
        # image the rest of the video is built around.
        wants_video_scene = (
            bool(video_pool)
            and not payload.motion_as_gif
            and (payload.requires_reference_image or planned_kind == "video")
        )
        if wants_video_scene:
            # A video already attached means this scene has completed the
            # image-to-video stage. A still image is resolved into an asset;
            # when no still exists, create it first and keep the video job in
            # `waiting` until that exact image has completed and been reviewed.
            if visual_suffix in _SCENE_VIDEO_EXTENSIONS:
                continue
            # Only scenes the plan actually calls for as video go down this
            # path. Running it over the whole timeline built an image job plus
            # a waiting video job even for scenes planned as a still or a
            # loop — paying for motion the scene was never meant to have.
            # With no plan recorded, fall back to treating every scene as
            # eligible, which is what a caller asking for video without
            # planning first is asking for.
            if planned_kind and planned_kind != "video":
                continue
            provider = video_pool[counters["video"] % len(video_pool)]
            counters["video"] += 1
            reference_asset = _reference_image_asset_for_segment(project_id, segment)
            dependency_job: dict[str, Any] | None = None
            if reference_asset is None:
                # The caller only supplies this when it asked for the video
                # pipeline explicitly; a plan-driven video scene falls back to
                # whichever image tool this batch already has.
                image_provider = payload.reference_image_provider
                if image_provider not in _IMAGE_CAPABLE_PROVIDERS:
                    image_provider = image_pool[0] if image_pool else "flow_image"
                dependency_job = database.create_scene_generation_job(
                    project_id,
                    int(segment["id"]),
                    image_provider,
                    prompt,
                    duration_seconds=5,
                    ratio=payload.ratio,
                    job_kind="image",
                    prompt_pending=True,
                )
                if not dependency_job:
                    continue
                preparation_jobs.append(dependency_job)
                if image_provider not in database.EXTERNAL_SIDECAR_PROVIDERS:
                    scene_generation_worker.enqueue(int(dependency_job["id"]))
            job = database.create_scene_generation_job(
                project_id,
                int(segment["id"]),
                provider,
                prompt,
                duration_seconds=payload.duration_seconds,
                ratio=payload.ratio,
                reference_asset_id=int(reference_asset["id"]) if reference_asset else None,
                job_kind="video",
                depends_on_job_id=int(dependency_job["id"]) if dependency_job else None,
                requires_reference_image=True,
                prompt_pending=True,
            )
            if job:
                if not dependency_job and provider not in database.EXTERNAL_SIDECAR_PROVIDERS:
                    scene_generation_worker.enqueue(int(job["id"]))
                queued.append(job)
            continue

        # Round-robin over the chosen providers so the scenes spread across
        # sites and actually run at the same time.
        #
        # Anything reaching here produces a still (or a GIF sheet, which is
        # also a still). Video scenes were handled above through the
        # image-first pipeline, so this branch never picks a video tool: doing
        # so would be a text-to-video clip, which cannot match the storyboard
        # image the rest of the video is built around.
        # Asking for GIFs means "make the scenes planned as loops", not "turn
        # every moving scene into a loop". Treating them the same silently
        # rewrote seven scenes the plan had marked as video — twice — and the
        # plan is the user's decision to change, not a side effect of a
        # generate call. Converting video scenes to loops is what
        # plan_visuals(motion_policy="gif_only") is for: it records the change
        # and its reason where it can be seen.
        wants_gif = payload.motion_as_gif and (
            planned_kind == "gif" if payload.respect_plan else True
        )
        # A GIF batch is about the loops only. A scene planned as video
        # belongs to the video pipeline, so leave it for that call rather than
        # quietly producing a still for it here.
        if payload.motion_as_gif and payload.respect_plan and planned_kind == "video":
            continue
        # "Has a visual" is not the same as "matches the plan". A scene
        # planned as a loop but still holding the earlier still was treated as
        # finished and silently skipped, so a GIF batch over a fully
        # illustrated project queued nothing at all.
        if visual_path and not (wants_gif and visual_suffix != ".gif"):
            continue
        pool = image_pool
        if not pool:
            fallback = payload.reference_image_provider
            pool = [fallback if fallback in _IMAGE_CAPABLE_PROVIDERS else "flow_image"]
        provider = pool[counters["image"] % len(pool)]
        counters["image"] += 1
        if wants_gif and not payload.respect_plan and planned_kind != "gif":
            # Only when the caller deliberately opted out of the plan. While
            # this also ran under respect_plan it quietly rewrote the recorded
            # decision for scenes the user had planned as video.
            database.set_segment_visual_kind(
                int(segment["id"]),
                "gif",
                fps=int(segment.get("visual_fps") or 8),
                reason=(str(segment.get("visual_kind_reason") or "") + " | Dùng GIF thay video theo chính sách project").strip(" |"),
            )
        job = database.create_scene_generation_job(
            project_id, int(segment["id"]), provider, prompt,
            duration_seconds=payload.duration_seconds, ratio=payload.ratio,
            job_kind="gif" if wants_gif else "image",
            prompt_pending=True,
        )
        if job:
            active_segment_ids.add(int(segment["id"]))
            if provider not in database.EXTERNAL_SIDECAR_PROVIDERS:
                scene_generation_worker.enqueue(int(job["id"]))
            queued.append(job)
    by_provider: dict[str, int] = {}
    for job in queued:
        key = str(job.get("provider") or "")
        by_provider[key] = by_provider.get(key, 0) + 1
    return {
        "status": "queued",
        "jobs": queued,
        "preparation_jobs": preparation_jobs,
        "queued_count": len(queued),
        "preparation_count": len(preparation_jobs),
        "total_segments": len(timeline),
        "motion_as_gif": payload.motion_as_gif,
        "limit": payload.limit,
        "by_provider": by_provider,
    }


@app.get("/api/antigravity/next-scene-job")
def claim_antigravity_scene_job() -> dict[str, Any]:
    """Sidecar-only handoff: one queued image job becomes an Antigravity task."""
    _sidecar_last_seen["antigravity_image"] = datetime.now(timezone.utc)
    job = database.claim_next_antigravity_scene_job()
    return {"job": job}


def _materialize_scene_job_asset(job: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    """Convert an AI key frame into the job's final local artifact when needed."""
    try:
        return materialize_gif_asset(
            database,
            job,
            asset,
            ffmpeg_binary=FFMPEG_BINARY,
        )
    except GifGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/antigravity/scene-jobs/{job_id}/complete")
def complete_antigravity_scene_job(job_id: int, asset_id: int) -> dict[str, Any]:
    job = database.get_scene_generation_job(job_id)
    asset = database.get_project_asset(asset_id)
    if not job or str(job.get("provider")) != "antigravity_image":
        raise HTTPException(status_code=404, detail="Không tìm thấy job Antigravity")
    if not asset or int(asset["project_id"]) != int(job["project_id"]):
        raise HTTPException(status_code=400, detail="Asset không thuộc dự án của job")
    asset = _materialize_scene_job_asset(job, asset)
    asset_id = int(asset["id"])
    attached = database.attach_asset_to_timeline_segment(int(job["timeline_segment_id"]), asset_id)
    if not attached:
        raise HTTPException(status_code=400, detail="Không thể gắn asset vào cảnh")
    finished = database.finish_scene_generation_job(
        job_id,
        "completed",
        output_path=str(asset["file_path"]),
        output_asset_id=asset_id,
        release_dependents=False,
    )
    # Judge the result and regenerate a poor one, without making the caller
    # wait out a ~20s CLI call before it can pick up the next job.
    _review_scene_in_background(job_id)
    return {"status": "completed", "job": finished, "asset": asset}


@app.post("/api/antigravity/scene-jobs/{job_id}/fail")
def fail_antigravity_scene_job(job_id: int, error: str = "") -> dict[str, Any]:
    job = database.get_scene_generation_job(job_id)
    if not job or str(job.get("provider")) != "antigravity_image":
        raise HTTPException(status_code=404, detail="Không tìm thấy job Antigravity")
    message = error.strip() or "Sidecar báo lỗi, không có chi tiết"
    finished = database.finish_scene_generation_job(
        job_id,
        "error",
        error=message,
        failure_kind=_scene_failure_kind(message),
    )
    return {"status": "error", "job": finished}


@app.get("/api/browser-scene-jobs/next")
def claim_browser_scene_job(provider: str) -> dict[str, Any]:
    """Sidecar-only handoff: one queued job becomes a browser-automation task.

    Generic version of /api/antigravity/next-scene-job for any web-app
    provider driven by web_video_sidecar.py (Flow/Veo 3, Meta AI Vibes, ...
    see database.BROWSER_SIDECAR_PROVIDERS for the current allow-list). The
    sidecar drives the site with the caller's own logged-in account/
    subscription, then completes the job via
    POST /api/browser-scene-jobs/{job_id}/complete once the clip is uploaded.
    """
    if provider not in database.BROWSER_SIDECAR_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Provider không hợp lệ: {provider}")
    _sidecar_last_seen[provider] = datetime.now(timezone.utc)
    if provider == "meta_ai_video":
        return {
            "job": None,
            "disabled_reason": "Meta AI không tạo được video trong luồng đã kiểm chứng; provider đang bị khóa.",
        }
    provider_state = database.get_scene_provider_state(provider)
    if provider_state.get("circuit_open"):
        return {"job": None, "circuit": provider_state}
    job = database.claim_next_scene_job_for_provider(provider)
    if job and not job.get("prompt_written"):
        # These jobs never pass through SceneGenerationWorker, so this is
        # their equivalent of _ensure_prompt_written: the prompt is written
        # now, on the claim, rather than when the batch was queued.
        try:
            written = _write_job_prompt(job)
        except LlmError:
            written = ""
        if written.strip():
            job = database.save_scene_job_prompt(int(job["id"]), written) or job
        else:
            database.touch_scene_generation_job(int(job["id"]), "prompt_ready")
    return {"job": job}


@app.get("/api/scene-sidecar-status")
def scene_sidecar_status() -> dict[str, Any]:
    """Whether each external-sidecar provider has polled recently enough to
    be considered alive — lets the UI say "no sidecar is running" instead of
    silently sitting at an unmoving progress bar when jobs stay queued."""
    now = datetime.now(timezone.utc)
    result: dict[str, Any] = {}
    for provider in database.EXTERNAL_SIDECAR_PROVIDERS:
        last_seen = _sidecar_last_seen.get(provider)
        seconds_ago = (now - last_seen).total_seconds() if last_seen else None
        result[provider] = {
            "last_seen_at": last_seen.isoformat() if last_seen else None,
            "seconds_ago": seconds_ago,
            "alive": seconds_ago is not None and seconds_ago <= _SIDECAR_STALE_AFTER_SECONDS,
            "circuit": database.get_scene_provider_state(provider),
        }
    return result


@app.post("/api/browser-scene-jobs/{job_id}/complete")
def complete_browser_scene_job(job_id: int, asset_id: int, claim_token: str = "") -> dict[str, Any]:
    job = database.get_scene_generation_job(job_id)
    asset = database.get_project_asset(asset_id)
    if not job or str(job.get("provider")) not in database.BROWSER_SIDECAR_PROVIDERS:
        raise HTTPException(status_code=404, detail="Không tìm thấy job trình duyệt")
    if job.get("status") != "running" or not claim_token or claim_token != str(job.get("claim_token") or ""):
        raise HTTPException(status_code=409, detail="Lượt chạy này đã hết hạn hoặc không còn sở hữu job")
    if not asset or int(asset["project_id"]) != int(job["project_id"]):
        raise HTTPException(status_code=400, detail="Asset không thuộc dự án của job")
    asset = _materialize_scene_job_asset(job, asset)
    asset_id = int(asset["id"])
    attached = database.attach_asset_to_timeline_segment(int(job["timeline_segment_id"]), asset_id)
    if not attached:
        raise HTTPException(status_code=400, detail="Không thể gắn asset vào cảnh")
    finished = database.finish_scene_generation_job(
        job_id,
        "completed",
        output_path=str(asset["file_path"]),
        output_asset_id=asset_id,
        release_dependents=False,
    )
    # Judge the result and regenerate a poor one, without making the caller
    # wait out a ~20s CLI call before it can pick up the next job.
    _review_scene_in_background(job_id)
    return {"status": "completed", "job": finished, "asset": asset}


@app.post("/api/projects/{project_id}/scene-jobs/cancel-pending")
def cancel_pending_scene_jobs(project_id: int) -> dict[str, Any]:
    """Call off every scene job of this project that has not started yet.

    A batch that turns out to be wrong needs one action to undo, not one per
    job: cancelling them individually is slow enough that more get claimed
    while you work down the list. Running jobs are left to finish and report.
    """
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Khong tim thay du an")
    cancelled = database.cancel_pending_scene_generation_jobs(project_id)
    return {"status": "cancelled", "cancelled_count": cancelled}


_SCRIPT_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "hook_verdict": {"type": "string"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "suggestions": {"type": "array", "items": {"type": "string"}},
        "should_rewrite": {"type": "boolean"},
    },
    "required": ["score", "issues", "should_rewrite"],
}


@app.post("/api/projects/{project_id}/script/review")
def review_project_script(project_id: int) -> dict[str, Any]:
    """Have a second AI read the script before anything is built from it.

    The `script` stage has been selectable in the agent settings all along and
    nothing ever called it, so a script went from written to storyboarded
    without another pair of eyes — while a generated image, far cheaper to
    redo, was reviewed. Errors here propagate into every scene, the narration
    and the render.
    """
    script = database.get_latest_project_script(project_id)
    if not database.get_production_project(project_id) or not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án hoặc kịch bản")

    body = "\n\n".join(
        part for part in (
            f"TIEU DE: {script.get('script_title') or ''}",
            f"HOOK:\n{script.get('hook') or ''}",
            f"MO DAU:\n{script.get('intro') or ''}",
            f"NOI DUNG:\n{script.get('main_content') or ''}",
            f"KEU GOI CUOI:\n{script.get('cta') or ''}",
        ) if part.strip()
    )
    system_prompt = (
        "Ban la bien tap vien soat kich ban video YouTube do MOT AI KHAC viet. Hay doc ky va cham that, "
        "khong khen xa giao.\n"
        "- 'score': 1-10 cho tong the (mach logic, suc giu chan nguoi xem, do chinh xac).\n"
        "- 'hook_verdict': 15 giay dau co du suc giu nguoi xem khong, vi sao.\n"
        "- 'issues': liet ke loi CU THE — so lieu dang ngo hoac mau thuan, doan lap y, doan thua co the cat, "
        "cho chuyen y bi hut, tuyen bo qua manh ma khong co can cu.\n"
        "- 'suggestions': cach sua ngan gon cho tung loi quan trong.\n"
        "- 'should_rewrite': true chi khi kich ban co loi du nang de khong nen dung.\n"
        "Viet bang tieng Viet."
    )
    try:
        verdict = _call_orchestrator_json(system_prompt, body, _SCRIPT_REVIEW_SCHEMA, stage="script")
    except LlmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    issues = [str(item) for item in (verdict.get("issues") or [])]
    suggestions = [str(item) for item in (verdict.get("suggestions") or [])]
    note_parts = [str(verdict.get("hook_verdict") or "").strip()]
    if issues:
        note_parts.append("Vấn đề: " + " | ".join(issues))
    if suggestions:
        note_parts.append("Đề xuất: " + " | ".join(suggestions))
    updated = database.save_script_review(
        int(script["id"]),
        int(verdict.get("score") or 0),
        " || ".join(part for part in note_parts if part),
        settings.agent_assignment("script").get("executor") or "",
    )
    return {"status": "reviewed", "review": verdict, "script": updated}


_SOURCE_CUE_SCHEMA = {
    "type": "object",
    "properties": {
        "cues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_index": {"type": "integer"},
                    "source_start_seconds": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["segment_index", "source_start_seconds"],
            },
        },
    },
    "required": ["cues"],
}


def _condense_transcript(segments: list[dict[str, Any]], block_seconds: float = 20.0) -> str:
    """Fold a word-level transcript into readable time blocks.

    Whisper returns a line every few seconds — 495 of them for a 20 minute
    video — which is both too long to send and too fine to choose from. Blocks
    of roughly this length are what a person would actually cut on.
    """
    blocks: list[tuple[float, list[str]]] = []
    for item in segments:
        try:
            start = float(item.get("start") or 0)
        except (TypeError, ValueError):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        if not blocks or start - blocks[-1][0] >= block_seconds:
            blocks.append((start, [text]))
        else:
            blocks[-1][1].append(text)
    lines = []
    for start, texts in blocks:
        minutes, seconds = divmod(int(start), 60)
        lines.append(f"[{start:.0f}s = {minutes}:{seconds:02d}] " + " ".join(texts)[:400])
    return "\n".join(lines)


@app.post("/api/projects/{project_id}/timeline/plan-source-cues")
def plan_timeline_source_cues(project_id: int) -> dict[str, Any]:
    """Decide which moment of the source video each scene should show.

    Until now the cut point came from a keyword table written for one
    particular video, and it only ran at all when the source description
    carried chapters. Without them every scene was cut from the first second
    of the source. The transcript is already stored with its timestamps, so
    the AI reads what is being said when, and matches it to the narration.
    """
    project = database.get_production_project(project_id)
    script = database.get_latest_project_script(project_id)
    if not project or not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án hoặc kịch bản")
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    if not timeline:
        raise HTTPException(status_code=400, detail="Dự án chưa có timeline")

    video_id = str(project.get("youtube_video_id") or "")
    transcript = database.get_transcript(video_id, transcript_format="json")
    if not transcript:
        raise HTTPException(
            status_code=400,
            detail="Video nguồn chưa có transcript dạng json. Chạy Whisper cho video này trước.",
        )
    try:
        segments = json.loads(str(transcript.get("content_text") or "[]"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Transcript json hỏng: {exc}") from exc
    if not isinstance(segments, list) or not segments:
        raise HTTPException(status_code=400, detail="Transcript json rỗng")

    video = database.get_video(video_id) or {}
    source_duration = float(video.get("duration_seconds") or 0)
    if not source_duration:
        try:
            source_duration = float(segments[-1].get("end") or 0)
        except (AttributeError, TypeError, ValueError):
            source_duration = 0.0

    scenes = "\n".join(
        f"[{int(item.get('segment_index') or 0)}] ({int(item.get('duration_seconds') or 0)}s) "
        f"{str(item.get('voice_text') or '').strip()[:300]}"
        for item in timeline
    )
    system_prompt = (
        "Ban chon doan HINH cua video goc de minh hoa cho tung cau binh luan moi.\n"
        "Dau vao: ban ghi loi noi cua video goc kem moc giay, va danh sach cac canh binh luan moi.\n"
        "- 'cues': moi canh mot phan tu, gom 'segment_index', 'source_start_seconds' (giay trong "
        "video goc) va 'reason' ngan bang tieng Viet.\n"
        "- Chon doan ma HINH ANH luc do khop voi dieu cau binh luan dang noi toi.\n"
        "- Cac canh nen di THEO MACH cua video goc (moc giay tang dan), tru khi noi dung doi hoi quay lai.\n"
        "- KHONG dat nhieu canh vao cung mot moc; moi canh mot doan khac nhau.\n"
        "- Tranh vai giay dau video (thuong la intro/title card).\n"
        f"- Video goc dai khoang {int(source_duration)} giay; moc chon phai nho hon so nay."
    )
    body = (
        f"BAN GHI VIDEO GOC:\n{_condense_transcript(segments)}\n\n"
        f"CAC CANH BINH LUAN MOI:\n{scenes}"
    )
    try:
        result = _call_orchestrator_json(system_prompt, body, _SOURCE_CUE_SCHEMA, stage="storyboard")
    except LlmError as exc:
        raise HTTPException(status_code=502, detail=f"AI không chọn được đoạn nguồn: {exc}") from exc

    by_index = {int(item.get("segment_index") or 0): item for item in timeline}
    planned: list[dict[str, Any]] = []
    for entry in result.get("cues") or []:
        segment = by_index.get(int(entry.get("segment_index") or -1))
        if not segment:
            continue
        start = max(0.0, float(entry.get("source_start_seconds") or 0))
        if source_duration:
            # A cue past the end would silently become a black clip.
            start = min(start, max(0.0, source_duration - 1.0))
        updated = database.save_segment_source_cue(
            int(segment["id"]), start, str(entry.get("reason") or "")
        )
        planned.append({
            "segment_id": segment["id"],
            "segment_index": segment.get("segment_index"),
            "source_start_seconds": (updated or {}).get("source_start_seconds", start),
            "reason": (updated or {}).get("source_cue_reason", ""),
        })
    if not planned:
        raise HTTPException(status_code=502, detail="AI không trả về đoạn nguồn nào dùng được")
    distinct = len({round(float(item["source_start_seconds"]), 1) for item in planned})
    return {
        "status": "planned",
        "scenes": planned,
        "planned": len(planned),
        "total_segments": len(timeline),
        "distinct_cues": distinct,
        "source_duration_seconds": source_duration,
    }


_FIDELITY_SCHEMA = {
    "type": "object",
    "properties": {
        "faithful": {"type": "boolean"},
        "score": {"type": "integer"},
        "invented": {"type": "array", "items": {"type": "string"}},
        "altered": {"type": "array", "items": {"type": "string"}},
        "missing": {"type": "array", "items": {"type": "string"}},
        "ending_verdict": {"type": "string"},
    },
    "required": ["faithful", "score"],
}


# Provider keys are internal; a banner has to name the thing the user pays for.
_PROVIDER_LABELS = {
    "codex_cli": "Codex CLI (ChatGPT)",
    "claude_code_cli": "Claude Code CLI",
    "antigravity": "Google Antigravity",
    "gflow_cli": "Google Flow (video)",
    "gflow_image": "Google Flow (ảnh)",
    "gemini_image": "Google Gemini API",
    "gemini_veo": "Google Veo API",
    "openai_image": "OpenAI Image API",
    "runway": "Runway",
    "chatgpt_web_image": "ChatGPT web",
    "gemini_web_image": "Gemini web",
    "antigravity_image": "Antigravity (ảnh)",
}


@app.get("/api/languages")
def list_output_languages() -> dict[str, Any]:
    """Languages the analysis and the script can be written in."""
    return {
        "default": languages.DEFAULT_LANGUAGE,
        "languages": [
            {"code": code, "label": record["label"], "tokens_per_second": record["tokens_per_second"]}
            for code, record in languages.LANGUAGES.items()
        ],
    }


@app.get("/api/operations")
def list_operations() -> dict[str, Any]:
    """Long-running work in progress, with what each one is doing."""
    return {"operations": operations.active()}


@app.post("/api/operations/{operation_id}/cancel")
def cancel_operation(operation_id: str) -> dict[str, Any]:
    """Stop one operation and kill whatever CLI it is currently waiting on."""
    if not operations.cancel(operation_id):
        raise HTTPException(status_code=404, detail="Tiến trình đã kết thúc hoặc không tồn tại")
    return {"status": "cancelling", "operation_id": operation_id}


@app.post("/api/operations/cancel-all")
def cancel_all_operations() -> dict[str, Any]:
    """Stop everything that is running."""
    return {"status": "cancelling", "cancelled": operations.cancel_all()}


@app.get("/api/usage-limits")
def list_usage_limits() -> dict[str, Any]:
    """Which models are out of quota right now, and when they come back."""
    limits = database.list_active_usage_limits()
    now = datetime.now(timezone.utc)
    active: list[dict[str, Any]] = []
    for item in limits:
        resets_at = str(item.get("resets_at") or "")
        if resets_at:
            try:
                # A provider that said when it would return, and has, is no
                # longer worth warning about; the next successful call clears
                # the row properly.
                if datetime.fromisoformat(resets_at) <= now:
                    continue
            except ValueError:
                pass
        active.append({
            "provider": item.get("provider"),
            "label": _PROVIDER_LABELS.get(str(item.get("provider")), str(item.get("provider"))),
            "message": item.get("message"),
            "detected_at": item.get("detected_at"),
            "resets_at": resets_at or None,
        })
    return {"limits": active, "count": len(active)}


@app.post("/api/projects/{project_id}/script/fidelity-check")
def check_script_fidelity(project_id: int) -> dict[str, Any]:
    """Check a retelling against the source it is supposed to be retelling.

    The re-narration workflow exists for material that has to be right: a folk
    tale people grew up with, a piece of history someone can look up. Telling
    it a different way is the point; changing a name, a number or the ending
    is the failure, and it is the kind of failure that reads perfectly well
    and so survives every other check in the app.

    Deliberately one-directional. A retelling is shorter than its source, so
    what the source has and the retelling omits is usually just compression.
    What the retelling asserts and the source never said is the real fault,
    and that is what this weighs.
    """
    project = database.get_production_project(project_id)
    script = database.get_latest_project_script(project_id)
    if not project or not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án hoặc kịch bản")

    video_id = str(project.get("youtube_video_id") or "")
    source = (
        database.get_transcript(video_id, transcript_format="txt")
        or database.get_transcript(video_id)
    )
    source_text = str((source or {}).get("content_text") or "").strip()
    if not source_text:
        raise HTTPException(
            status_code=400,
            detail="Video nguồn chưa có transcript để đối chiếu. Chạy Whisper cho video này trước.",
        )

    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    narration = "\n".join(
        str(item.get("voice_text") or "").strip()
        for item in timeline
        if str(item.get("voice_text") or "").strip()
    )
    if not narration:
        narration = "\n".join(
            str(script.get(field) or "").strip()
            for field in ("hook", "intro", "main_content", "cta")
        ).strip()
    if not narration:
        raise HTTPException(status_code=400, detail="Chưa có lời dẫn để đối chiếu")

    system_prompt = (
        "Ban doi chieu mot BAN KE LAI voi NOI DUNG GOC ma no phai ke lai.\n"
        "Muc dich: ban ke lai duoc phep doi CACH KE, nhung KHONG duoc doi NOI DUNG.\n"
        "- 'invented': dieu ban ke lai KHANG DINH ma nguon khong he noi — ten, so lieu, tinh tiet, "
        "nhan vat, bai hoc tu nghi ra. Day la loi NANG NHAT.\n"
        "- 'altered': dieu co trong ca hai nhung DA BI DOI — sai ten, sai so, sai dia danh, sai thu tu "
        "su viec, sai quan he nhan vat, sai ket cuc.\n"
        "- 'missing': su viec quan trong cua nguon bi bo hoan toan.\n"
        "- 'ending_verdict': ket cuc ban ke lai co dung ket cuc cua nguon khong.\n"
        "- 'score': 1-10 theo do trung thanh ve NOI DUNG. Dien dat khac di thi KHONG tru diem; "
        "chi tru diem khi SU THAT khac di.\n"
        "- 'faithful': false neu co bat ky muc 'invented' hoac 'altered' nao dang ke.\n"
        "Luu y: ban ke lai thuong NGAN HON nguon, nen viec rut gon la binh thuong — dung coi moi cho "
        "rut gon la loi. Viet bang tieng Viet."
    )
    body = f"NOI DUNG GOC:\n{source_text[:40000]}\n\nBAN KE LAI:\n{narration[:20000]}"
    try:
        verdict = _call_orchestrator_json(
            system_prompt, body, _FIDELITY_SCHEMA, stage="quality_review"
        )
    except LlmError as exc:
        raise HTTPException(status_code=502, detail=f"Không soát được độ chính xác: {exc}") from exc

    invented = [str(item) for item in (verdict.get("invented") or [])]
    altered = [str(item) for item in (verdict.get("altered") or [])]
    missing = [str(item) for item in (verdict.get("missing") or [])]
    # The reviewer is the same kind of system that wrote the text, so its
    # opinion is not the last word. Names and numbers are compared by machine,
    # and anything the retelling states that the source never did fails the
    # check whatever the reviewer concluded.
    mechanical = unsourced_details(source_text, narration)
    faithful = bool(verdict.get("faithful")) and not mechanical["names"] and not mechanical["numbers"]
    note_parts = [f"Kết cục: {verdict.get('ending_verdict') or ''}".strip()]
    if invented:
        note_parts.append("Tự nghĩ ra: " + " | ".join(invented))
    if altered:
        note_parts.append("Bị đổi: " + " | ".join(altered))
    if missing:
        note_parts.append("Thiếu: " + " | ".join(missing))
    if mechanical["names"]:
        note_parts.append("Tên không có trong nguồn: " + " | ".join(mechanical["names"]))
    if mechanical["numbers"]:
        note_parts.append("Số không có trong nguồn: " + " | ".join(mechanical["numbers"]))
    database.save_script_review(
        int(script["id"]),
        int(verdict.get("score") or 0),
        " || ".join(part for part in note_parts if part and part != "Kết cục:"),
        settings.agent_assignment("quality_review").get("reviewer") or "",
    )
    updated = database.set_script_fidelity_status(
        int(script["id"]), "passed" if faithful else "failed"
    )
    return {
        "status": "checked",
        "faithful": faithful,
        "unsourced_names": mechanical["names"],
        "unsourced_numbers": mechanical["numbers"],
        "score": int(verdict.get("score") or 0),
        "invented": invented,
        "altered": altered,
        "missing": missing,
        "ending_verdict": str(verdict.get("ending_verdict") or ""),
        "script": updated,
    }


_TRANSLATE_SOURCE_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "source_language": {"type": "string"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["text"],
}


@app.post("/api/videos/{video_id}/transcript/translate")
def translate_source_transcript(
    video_id: str,
    target_language: str = Query(default=languages.DEFAULT_LANGUAGE, max_length=12),
    chunk_chars: int = Query(default=6000, ge=1000, le=20000),
) -> dict[str, Any]:
    """Translate the source's own transcript, before anything is written from it.

    Analysis and scripting both read the transcript, and a model reading a
    foreign-language source translates it silently in its head - differently
    each time, with names and numbers drifting. Doing it once, on purpose, and
    storing the result means every later step reads the same Vietnamese text,
    and a person can check that text against the original.

    Stored as its own transcript row rather than replacing the original: the
    source's own words stay available as the thing a retelling is judged
    against.
    """
    video = database.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    source = database.get_transcript(video_id, transcript_format="txt") or database.get_transcript(video_id)
    original = str((source or {}).get("content_text") or "").strip()
    if not original:
        raise HTTPException(
            status_code=400,
            detail="Video chưa có transcript để dịch. Chạy Whisper cho video này trước.",
        )
    record = languages.resolve(target_language)
    if str((source or {}).get("language") or "").lower().startswith(str(target_language).lower()):
        return {
            "status": "skipped",
            "detail": f"Transcript đã ở {record['label']}, không cần dịch.",
            "target_language": target_language,
        }

    system_prompt = (
        f"Ban dich BAN GHI LOI NOI cua mot video sang {record['name']} ({record['english_name']}).\n"
        "- Dich DAY DU, khong tom tat, khong bo doan nao, khong them loi binh cua ban.\n"
        "- LOI THOAI NHAN VAT dich thanh loi thoai, giu dung giong dieu cua tung nhan vat.\n"
        "- GIU NGUYEN ten rieng, ten dia danh, con so, don vi, ngay thang.\n"
        "- Ban ghi do may nghe lai nen co the sai chinh ta hoac dinh cac tu; hay dich theo Y "
        "cua cau, va neu mot cho that su khong doan duoc thi ghi [khong ro] thay vi bia ra.\n"
        "- 'source_language': ngon ngu cua ban goc.\n"
        "- 'notes': nhung cho ban khong chac, neu co.\n"
        "Chi tra ve ban dich trong 'text'."
    )

    pieces: list[str] = []
    notes: list[str] = []
    detected = ""
    # Split on blank lines first so a paragraph is not cut mid-sentence.
    paragraphs = [part for part in re.split(r"\n\s*\n", original) if part.strip()] or [original]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) > chunk_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)

    for index, chunk in enumerate(chunks, start=1):
        try:
            result = _call_orchestrator_json(
                system_prompt,
                f"PHAN {index}/{len(chunks)} CUA BAN GHI:\n{chunk}",
                _TRANSLATE_SOURCE_SCHEMA,
                stage="script",
            )
        except LlmError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Dịch transcript thất bại ở phần {index}/{len(chunks)}: {exc}",
            ) from exc
        pieces.append(str(result.get("text") or "").strip())
        notes.extend(str(item) for item in (result.get("notes") or []))
        detected = detected or str(result.get("source_language") or "")

    translated = "\n\n".join(part for part in pieces if part)
    if not translated:
        raise HTTPException(status_code=502, detail="AI không trả về nội dung dịch")
    stored = database.save_transcript(
        video_id,
        translated,
        source_type=f"translated_{target_language}",
        language=target_language,
        transcript_format="txt",
    )
    return {
        "status": "translated",
        "target_language": target_language,
        "source_language": detected,
        "chunks": len(chunks),
        "original_chars": len(original),
        "translated_chars": len(translated),
        "notes": notes[:20],
        "transcript": stored,
    }


_TRANSLATE_SEGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_index": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["segment_index", "text"],
            },
        },
    },
    "required": ["lines"],
}

_LANGUAGE_NAMES = {
    "vi": "tieng Viet",
    "en": "tieng Anh",
    "zh": "tieng Trung",
    "ja": "tieng Nhat",
    "ko": "tieng Han",
    "th": "tieng Thai",
    "es": "tieng Tay Ban Nha",
    "fr": "tieng Phap",
}


@app.post("/api/projects/{project_id}/script/translate")
def translate_project_narration(
    project_id: int,
    target_language: str = Query(default="vi", max_length=12),
    batch_size: int = Query(default=8, ge=1, le=30),
) -> dict[str, Any]:
    """Translate each scene's narration in place, scene by scene.

    Translating the script as one block would come back as prose that no
    longer divides where the timeline divides, and every scene's timing is
    already pinned to its own line. Going scene by scene keeps the count and
    the boundaries fixed; only the words change. The pre-translation wording
    is kept so a translated line can still be checked against what was said.
    """
    script = database.get_latest_project_script(project_id)
    if not database.get_production_project(project_id) or not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án hoặc kịch bản")
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    pending = [item for item in timeline if str(item.get("voice_text") or "").strip()]
    if not pending:
        raise HTTPException(status_code=400, detail="Timeline chưa có lời đọc để dịch")

    language = str(target_language or "vi").strip().lower()
    language_name = _LANGUAGE_NAMES.get(language, language)
    system_prompt = (
        f"Ban dich loi BINH LUAN cho video sang {language_name}.\n"
        "- Tra ve 'lines': moi phan tu gom 'segment_index' dung nhu dau vao va 'text' da dich.\n"
        "- Tra ve DUNG SO DONG nhu dau vao, khong gop, khong tach, khong bo dong nao.\n"
        "- Day la loi DE DOC THANH TIENG: uu tien tu nhien khi noi hon la sat tung chu. "
        "Tranh cau qua dai, tranh cau bi dong nang ne.\n"
        "- GIU NGUYEN moi con so, don vi, ngay thang, ten rieng, ten thuong hieu.\n"
        "- Do dai moi dong nen tuong duong ban goc, vi thoi luong doc da duoc tinh theo dong do.\n"
        "- Khong them loi binh cua ban, khong giai thich."
    )

    translated: list[dict[str, Any]] = []
    failed: list[int] = []
    errors: list[str] = []
    for start in range(0, len(pending), batch_size):
        chunk = pending[start:start + batch_size]
        body = "\n".join(
            f"[{int(item.get('segment_index') or 0)}] {str(item['voice_text']).strip()}"
            for item in chunk
        )
        try:
            result = _call_orchestrator_json(
                system_prompt, body, _TRANSLATE_SEGMENT_SCHEMA, stage="script"
            )
        except LlmError as exc:
            # One bad batch must not lose the batches that did translate, but
            # it must not vanish either: the reason travels back in the reply.
            failed.extend(int(item.get("segment_index") or 0) for item in chunk)
            errors.append(str(exc)[:200])
            continue
        by_index = {int(item.get("segment_index") or 0): item for item in chunk}
        for line in result.get("lines") or []:
            segment = by_index.get(int(line.get("segment_index") or -1))
            text = str(line.get("text") or "").strip()
            if not segment or not text:
                continue
            updated = database.save_segment_translation(
                int(segment["id"]), text, str(segment.get("voice_text") or "")
            )
            translated.append({
                "segment_index": segment.get("segment_index"),
                "source_voice_text": (updated or {}).get("source_voice_text", ""),
                "voice_text": (updated or {}).get("voice_text", text),
            })

    # Translation can rewrite a proper noun as easily as any other word, so a
    # translated script has to be checked again before it may be produced.
    database.set_script_fidelity_status(int(script["id"]), "unchecked")

    if not translated:
        detail = "Không dịch được đoạn nào; kiểm tra AI điều phối"
        if errors:
            detail += f". Lỗi đầu tiên: {errors[0]}"
        raise HTTPException(status_code=502, detail=detail)
    missing = sorted({int(item.get("segment_index") or 0) for item in pending}
                     - {int(item["segment_index"]) for item in translated})
    return {
        "status": "translated",
        "target_language": language,
        "total": len(pending),
        "translated": len(translated),
        "missing_segments": missing,
        "failed_segments": sorted(set(failed)),
        "errors": errors,
        "segments": translated,
    }


_VOICE_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "matches": {"type": "boolean"},
        "issues": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "matches"],
}


@app.post("/api/projects/{project_id}/voice/review")
def review_project_voice(project_id: int, limit: int = Query(default=0, ge=0, le=200)) -> dict[str, Any]:
    """Check that each scene's narration actually says what the script asked.

    Nothing listened back before: the app could tell you a scene had audio and
    how loud it was, but not whether a sentence had been dropped or a number
    misread. Faster-Whisper is already used for source transcripts, so the
    audio is transcribed locally and an AI compares it against voice_text —
    a mismatch here would otherwise only surface once the video is rendered.
    """
    script = database.get_latest_project_script(project_id)
    if not database.get_production_project(project_id) or not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án hoặc kịch bản")
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    pending = [
        segment for segment in timeline
        if str(segment.get("audio_path") or "").strip()
        and Path(str(segment["audio_path"])).is_file()
        and str(segment.get("voice_text") or "").strip()
    ]
    if not pending:
        raise HTTPException(status_code=400, detail="Chưa có cảnh nào có sẵn file giọng đọc để kiểm tra")
    if limit:
        pending = pending[:limit]

    reviewed: list[dict[str, Any]] = []
    for segment in pending:
        expected = str(segment["voice_text"]).strip()
        try:
            heard = str(
                transcribe_local_file(
                    str(segment["audio_path"]), f"segment-{segment['id']}", language="vi"
                ).get("text") or ""
            ).strip()
        except Exception as exc:  # noqa: BLE001 - one bad clip must not end the run
            reviewed.append({
                "segment_index": segment.get("segment_index"),
                "status": "skipped",
                "detail": str(exc)[:200],
            })
            continue
        system_prompt = (
            "Ban doi chieu LOI DOC THUC TE (do may nghe lai tu file am thanh) voi LOI THOAI MONG MUON.\n"
            "- 'score': 1-10 theo do khop.\n"
            "- 'matches': co doc dung va du y khong.\n"
            "- 'issues': liet ke cu the — cau bi bo, tu doc sai, so lieu doc lech, thu tu dao.\n"
            "Luu y: may nghe lai co the sai chinh ta hoac dau cau; chi bao loi khi Y NGHIA khac nhau, "
            "khong bat be tung dau phay. Viet bang tieng Viet."
        )
        user_prompt = f"LOI THOAI MONG MUON:\n{expected}\n\nLOI DOC THUC TE:\n{heard}"
        try:
            verdict = _call_orchestrator_json(
                system_prompt, user_prompt, _VOICE_REVIEW_SCHEMA, stage="quality_review"
            )
        except LlmError as exc:
            reviewed.append({
                "segment_index": segment.get("segment_index"),
                "status": "skipped",
                "detail": str(exc)[:200],
            })
            continue
        issues = [str(item) for item in (verdict.get("issues") or [])]
        database.save_segment_voice_review(
            int(segment["id"]), int(verdict.get("score") or 0), " | ".join(issues)
        )
        reviewed.append({
            "segment_index": segment.get("segment_index"),
            "status": "ok",
            "score": int(verdict.get("score") or 0),
            "matches": bool(verdict.get("matches")),
            "issues": issues,
        })
    failed = [item for item in reviewed if item.get("status") == "ok" and not item.get("matches")]
    return {
        "status": "reviewed",
        "checked": len(reviewed),
        "mismatched": len(failed),
        "segments": reviewed,
    }


@app.post("/api/scene-jobs/{job_id}/review")
def review_scene_job(job_id: int) -> dict[str, Any]:
    """Judge a finished scene on demand (the same check that runs automatically)."""
    job = database.get_scene_generation_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy job tạo cảnh")
    if str(job.get("status")) != "completed":
        raise HTTPException(status_code=409, detail="Chỉ chấm được job đã hoàn thành")
    verdict = _run_scene_review(job_id)
    if verdict is None:
        raise HTTPException(status_code=502, detail="Không chấm được (thiếu file hoặc orchestrator lỗi)")
    return {"review": verdict, "job": database.get_scene_generation_job(job_id)}


@app.get("/api/browser/trace")
def browser_trace(job: int = 0, stage: str = "", claim_token: str = "") -> dict[str, Any]:
    """Breadcrumb endpoint for the extension's job pipeline.

    A stalled run is otherwise invisible from here: the job sits at
    'running' with no error and no requests, and the only place the reason
    exists is the extension's own service-worker console. Each stage hits
    this so the server access log shows exactly how far a job got.
    """
    if job > 0:
        scene_job = database.get_scene_generation_job(job)
        if (
            scene_job
            and scene_job.get("status") == "running"
            and claim_token
            and claim_token == str(scene_job.get("claim_token") or "")
        ):
            database.touch_scene_generation_job(job, stage)
    return {"ok": True, "job": job, "stage": stage[:120]}


@app.post("/api/browser-scene-jobs/{job_id}/fail")
def fail_browser_scene_job(job_id: int, error: str = "", claim_token: str = "") -> dict[str, Any]:
    job = database.get_scene_generation_job(job_id)
    if not job or str(job.get("provider")) not in database.BROWSER_SIDECAR_PROVIDERS:
        raise HTTPException(status_code=404, detail="Không tìm thấy job trình duyệt")
    if job.get("status") != "running" or not claim_token or claim_token != str(job.get("claim_token") or ""):
        raise HTTPException(status_code=409, detail="Lượt chạy này đã hết hạn hoặc không còn sở hữu job")
    message = error.strip() or "Sidecar báo lỗi, không có chi tiết"
    finished = database.finish_scene_generation_job(
        job_id,
        "error",
        error=message,
        failure_kind=_scene_failure_kind(message),
    )
    return {"status": "error", "job": finished}


@app.websocket("/ws/browser-scene-jobs")
async def browser_scene_jobs_ws(websocket: WebSocket) -> None:
    """Push side of the browser-sidecar queue, for clients (the browser
    extension bridge) that want to sit idle instead of polling on a timer.
    The client does nothing but hold this connection open; a message here
    is just "go check /api/browser-scene-jobs/next for <provider>" — the
    actual atomic claim still goes through that existing endpoint, so two
    connected clients racing on the same push is still safe.

    Implemented as a cheap in-process DB check every 2s, done here on the
    server rather than by the client, because that's the actual point:
    server-side, in-process polling of its own SQLite file is negligible
    load; a browser extension re-hitting this API in a tight client loop
    just to ask "anything new?" is not.
    """
    await websocket.accept()
    last_queued: dict[str, int] = {}
    try:
        while True:
            for provider in database.BROWSER_SIDECAR_PROVIDERS:
                count = database.count_queued_scene_generation_jobs(provider)
                if count > 0 and count != last_queued.get(provider):
                    await websocket.send_json({"provider": provider, "queued": count})
                last_queued[provider] = count
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass


@app.get("/api/projects/{project_id}/timeline/{segment_id}/visual-preview")
def stream_timeline_visual_preview(project_id: int, segment_id: int) -> FileResponse:
    segment = database.get_project_timeline_segment(segment_id)
    if not segment or int(segment["project_id"]) != project_id:
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh trong dự án")
    path = Path(str(segment.get("visual_path") or ""))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Cảnh này chưa có file video hoặc ảnh để preview")
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")


@app.get("/api/projects/{project_id}/timeline/{segment_id}/audio-preview")
def stream_timeline_audio_preview(project_id: int, segment_id: int) -> FileResponse:
    segment = database.get_project_timeline_segment(segment_id)
    if not segment or int(segment["project_id"]) != project_id:
        raise HTTPException(status_code=404, detail="Không tìm thấy giọng đọc trong dự án")
    path = Path(str(segment.get("audio_path") or ""))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Cảnh này chưa có file giọng đọc để nghe")
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "audio/wav")


def _voxcpm_preview_definition(key: str) -> dict[str, Any]:
    for preset in VOXCPM_VOICE_PRESETS:
        if str(preset["key"]) == key:
            return preset
    raise HTTPException(status_code=404, detail="Không tìm thấy preset giọng VoxCPM")


def _voxcpm_preview_path(project_id: int, key: str) -> Path:
    _voxcpm_preview_definition(key)
    return ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["audio"] / "voice-previews" / f"{key}.wav"


@app.post("/api/projects/{project_id}/voice-previews")
def queue_voxcpm_voice_previews(project_id: int) -> dict[str, Any]:
    if not VOXCPM_RUNTIME_READY:
        raise HTTPException(status_code=400, detail="VoxCPM chưa sẵn sàng: kiểm tra CUDA và môi trường local")
    script = database.get_latest_project_script(project_id)
    if not database.get_production_project(project_id) or not script:
        raise HTTPException(status_code=400, detail="Hãy tạo project và kịch bản trước khi nghe thử giọng")
    try:
        job = production_worker.enqueue(project_id, int(script["id"]), "voice_preview", "voxcpm", force=False)
    except ProductionJobError as exc:
        raise _api_error(exc) from exc
    return {"status": "queued" if job["status"] == "queued" else job["status"], "job": job}


@app.get("/api/projects/{project_id}/voice-previews")
def list_voxcpm_voice_previews(project_id: int) -> list[dict[str, Any]]:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return [
        {
            "key": preset["key"],
            "label": preset["label"],
            "style": preset["style"],
            "ready": _voxcpm_preview_path(project_id, str(preset["key"])).is_file(),
            "url": f"/api/projects/{project_id}/voice-previews/{preset['key']}/audio",
        }
        for preset in VOXCPM_VOICE_PRESETS
    ]


@app.get("/api/projects/{project_id}/voice-previews/{key}/audio")
def stream_voxcpm_voice_preview(project_id: int, key: str) -> FileResponse:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    path = _voxcpm_preview_path(project_id, key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Giọng thử chưa được tạo")
    return FileResponse(path, media_type="audio/wav")


@app.post("/api/projects/{project_id}/voice-previews/{key}/select")
def select_voxcpm_voice_preview(project_id: int, key: str) -> dict[str, Any]:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    preset = _voxcpm_preview_definition(key)
    path = _voxcpm_preview_path(project_id, key)
    if not path.is_file():
        raise HTTPException(status_code=400, detail="Hãy tạo và nghe thử preset này trước")
    assets = database.list_project_assets(project_id)
    asset = next((item for item in assets if Path(str(item.get("file_path") or "")) == path), None)
    if not asset:
        asset = database.create_project_asset(
            project_id, "audio", f"VoxCPM preset · {preset['label']}.wav", str(path),
            mime_type="audio/wav", file_size=path.stat().st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    if not asset:
        raise HTTPException(status_code=500, detail="Không lưu được preset giọng vào dự án")
    current = database.get_project_render_settings(project_id)
    try:
        render_settings = database.update_project_render_settings(
            project_id,
            music_asset_id=current.get("music_asset_id"),
            music_volume=float(current.get("music_volume") or 0.12),
            transition_style=str(current.get("transition_style") or "fade"),
            output_profile=str(current.get("output_profile") or "youtube_landscape"),
            voice_provider="voxcpm",
            voice_model=f"design:{preset['style']}",
            voice_rate=str(current.get("voice_rate") or "+0%"),
            voice_reference_asset_id=int(asset["id"]),
            voice_prompt_text=VOXCPM_PREVIEW_TEXT,
            subtitle_provider=str(current.get("subtitle_provider") or "timeline_text"),
            subtitle_model=str(current.get("subtitle_model") or "timeline"),
            publish_language=str(current.get("publish_language") or "vi"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "selected", "preset": preset, "asset": asset, "settings": render_settings}


@app.get("/api/scene-jobs/{job_id}")
def get_scene_generation_job(job_id: int) -> dict[str, Any]:
    job = database.get_scene_generation_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy job tạo cảnh")
    return job


@app.post("/api/scene-jobs/{job_id}/cancel")
def cancel_scene_job(job_id: int) -> dict[str, Any]:
    job = database.get_scene_generation_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy job tạo cảnh")
    if job["status"] != "queued":
        raise HTTPException(
            status_code=409,
            detail="Chỉ có thể hủy job đang chờ; job đang chạy sẽ hoàn tất an toàn.",
        )
    return {"job": scene_generation_worker.cancel_queued(job_id)}


@app.post("/api/scene-jobs/{job_id}/retry")
def retry_scene_job(job_id: int) -> dict[str, Any]:
    job = database.get_scene_generation_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy job tạo cảnh")
    if job["status"] not in {"error", "cancelled"}:
        raise HTTPException(status_code=409, detail="Chỉ có thể chạy lại job lỗi hoặc đã hủy")
    provider = str(job.get("provider") or "")
    if provider in database.EXTERNAL_SIDECAR_PROVIDERS:
        # Not consumed by scene_generation_worker's in-process queue — the
        # external sidecar (antigravity/web_video_sidecar.py) picks queued
        # jobs up by polling, so resetting the DB row is enough.
        retried = database.retry_scene_generation_job(job_id)
    else:
        retried = scene_generation_worker.retry(job_id)
    return {"job": retried}


@app.get("/api/scene-generation-queue")
def scene_generation_queue_status() -> dict[str, Any]:
    return scene_generation_worker.status()


@app.get("/api/projects/{project_id}/jobs")
def list_project_jobs(project_id: int) -> list[dict[str, Any]]:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return database.list_project_jobs(project_id)


@app.post("/api/projects/{project_id}/jobs")
def queue_project_job(
    project_id: int,
    payload: CreateProductionJobRequest,
) -> dict[str, Any]:
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id)
    if not script:
        raise HTTPException(status_code=400, detail="Project chưa có kịch bản")
    if not database.list_project_timeline(project_id, script_id=int(script["id"])):
        raise HTTPException(status_code=400, detail="Project chưa có timeline")

    provider = payload.provider.strip().lower()
    allowed = {
        "voiceover": {"dry_run", "preview", "mock", "pyvideotrans", "py_video_trans", "edge_tts", "voxcpm"},
        "voiceover_segment": {"dry_run", "preview", "mock", "pyvideotrans", "py_video_trans", "edge_tts", "voxcpm"},
        "source_visuals": {"dry_run", "preview", "mock", "source_video", "source", "local_source"},
        "render": {
            "dry_run",
            "preview",
            "mock",
            "ffmpeg",
            "ffmpeg_command",
            "ffmpeg_builtin",
            "openmontage",
            "openmontage_ffmpeg",
            "openmontage_remotion",
            "openmontage_hyperframes",
        },
        "premiere_draft": {"dry_run", "preview", "mock", "pyvideotrans", "py_video_trans", "edge_tts", "voxcpm"},
        "director_production": {"edge_tts", "pyvideotrans", "voxcpm"},
    }[payload.job_type]
    if provider not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Provider không hợp lệ cho {payload.job_type}: {payload.provider}",
        )
    if provider not in {"dry_run", "preview", "mock"} and not payload.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Job production thật cần confirmed=true vì có thể gọi TTS hoặc render tốn tài nguyên",
        )
    if provider in {"pyvideotrans", "py_video_trans"} and not PYVIDEOTRANS_COMMAND:
        raise HTTPException(status_code=400, detail="Chưa cấu hình PYVIDEOTRANS_COMMAND trong .env")
    if provider in {"pyvideotrans", "py_video_trans"} and not PYVIDEOTRANS_RUNTIME_READY:
        raise HTTPException(status_code=400, detail="Môi trường pyVideoTrans chưa hoàn tất dependency")
    if provider == "voxcpm" and not VOXCPM_RUNTIME_READY:
        raise HTTPException(status_code=400, detail="VoxCPM chưa sẵn sàng: kiểm tra voxcpm và CUDA")
    if provider == "edge_tts" and not EDGE_TTS_RUNTIME_READY:
        raise HTTPException(status_code=400, detail="Edge TTS chưa sẵn sàng trong môi trường local")
    if provider in {"ffmpeg", "ffmpeg_command"} and not FFMPEG_RENDER_COMMAND:
        raise HTTPException(status_code=400, detail="Chưa cấu hình FFMPEG_RENDER_COMMAND trong .env")
    if payload.job_type == "source_visuals" and provider not in {"dry_run", "preview", "mock"} and not ffmpeg_available(FFMPEG_BINARY):
        raise HTTPException(status_code=400, detail=f"Không tìm thấy FFmpeg ({FFMPEG_BINARY}) trên máy")
    if provider == "ffmpeg_builtin" and not ffmpeg_available(FFMPEG_BINARY):
        raise HTTPException(status_code=400, detail=f"Không tìm thấy FFmpeg ({FFMPEG_BINARY}) trên máy")
    if settings.GPU_ONLY and payload.job_type in {"source_visuals", "render", "director_production"} and provider not in {"dry_run", "preview", "mock"} and not nvenc_available(FFMPEG_BINARY):
        raise HTTPException(
            status_code=400,
            detail="GPU-only mode đang bật nhưng FFmpeg/NVENC chưa sẵn sàng; job không được phép chạy bằng CPU",
        )
    if settings.GPU_ONLY and payload.job_type == "render" and provider not in {"dry_run", "preview", "mock", "ffmpeg_builtin"}:
        raise HTTPException(
            status_code=400,
            detail="GPU-only mode chỉ cho phép Render FFmpeg built-in với h264_nvenc",
        )
    if provider.startswith("openmontage"):
        try:
            runtime = runtime_for_provider(provider, openmontage_adapter.configured_runtime)
        except OpenMontageError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        openmontage_status = openmontage_adapter.status()
        if not openmontage_status["runtimes"].get(runtime):
            raise HTTPException(
                status_code=400,
                detail=f"OpenMontage runtime '{runtime}' chưa sẵn sàng: {openmontage_status['runtime_details'].get(runtime)}",
            )
    if payload.job_type == "director_production" and not ffmpeg_available(FFMPEG_BINARY):
        raise HTTPException(status_code=400, detail=f"Không tìm thấy FFmpeg ({FFMPEG_BINARY}) trên máy")
    if payload.job_type == "voiceover_segment":
        if not payload.segment_id:
            raise HTTPException(status_code=400, detail="Cần chọn đúng đoạn timeline để tạo lại giọng đọc")
        segment = database.get_project_timeline_segment(int(payload.segment_id))
        if not segment or int(segment.get("project_id") or 0) != project_id:
            raise HTTPException(status_code=400, detail="Đoạn timeline không thuộc dự án này")
    try:
        job = production_worker.enqueue(
            project_id,
            int(script["id"]),
            payload.job_type,
            provider,
            force=payload.force,
            segment_id=payload.segment_id,
        )
    except ProductionJobError as exc:
        raise _api_error(exc) from exc
    return {"status": "queued" if job["status"] == "queued" else job["status"], "job": job}


def _publication_payload(project: dict[str, Any], script: dict[str, Any], payload: CreatePublicationRequest) -> dict[str, Any]:
    writer = database.get_video_analysis(str(project["youtube_video_id"]), analysis_type="writer")
    writer_result = (writer or {}).get("result") or {}
    writer_tags = [str(item).lstrip("#").strip() for item in (writer_result.get("hashtags") or [])]
    title = payload.title.strip() or str(script.get("script_title") or project.get("title") or "YouTube video")
    description = payload.description.strip() or str(writer_result.get("new_description") or "")
    if not description:
        description = "\n\n".join(
            part for part in (str(script.get("hook") or ""), str(script.get("cta") or "")) if part.strip()
        )
    tags = [str(tag).lstrip("#").strip() for tag in payload.tags if str(tag).strip()] or writer_tags
    return {
        "title": title,
        "description": description,
        "tags": list(dict.fromkeys(tags)),
        "category_id": payload.category_id.strip() or "27",
    }


@app.get("/api/publisher/status")
def publisher_status() -> dict[str, Any]:
    return publisher_worker.status()


@app.get("/api/publisher/queue")
def publisher_queue(project_id: int | None = Query(default=None, ge=1)) -> dict[str, Any]:
    return {
        "status": publisher_worker.status(),
        "publications": database.list_project_publications(project_id=project_id),
    }


@app.post("/api/projects/{project_id}/publish")
def queue_project_publication(
    project_id: int,
    payload: CreatePublicationRequest,
) -> dict[str, Any]:
    if not payload.confirmed:
        raise HTTPException(status_code=400, detail="Publish cần confirmed=true sau khi người dùng đã duyệt video")
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id)
    if not script or script.get("status") != "approved":
        raise HTTPException(status_code=400, detail="Kích bản chưa được duyệt; hãy duyệt trước khi đưa vào Publisher")
    final_path = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["exports"] / "final.mp4"
    if not final_path.is_file():
        raise HTTPException(status_code=400, detail="Project chưa có final.mp4; hãy render và Quality Check trước")

    selected_thumbnail = next(
        (item for item in database.list_project_thumbnails(project_id) if item.get("selected")),
        None,
    )
    thumbnail_path = str((selected_thumbnail or {}).get("file_path") or "")
    if payload.thumbnail_asset_id:
        thumbnail_asset = database.get_project_asset(int(payload.thumbnail_asset_id))
        if not thumbnail_asset or int(thumbnail_asset.get("project_id") or 0) != project_id:
            raise HTTPException(status_code=400, detail="Thumbnail asset không thuộc project này")
        if thumbnail_asset.get("asset_type") != "image":
            raise HTTPException(status_code=400, detail="Asset thumbnail phải là file ảnh")
        thumbnail_file = Path(str(thumbnail_asset.get("file_path") or "")).expanduser()
        if not thumbnail_file.is_file():
            raise HTTPException(status_code=400, detail="Không tìm thấy file thumbnail trên máy")
        if thumbnail_file.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            raise HTTPException(status_code=400, detail="Thumbnail YouTube phải là JPG hoặc PNG")
        thumbnail_path = str(thumbnail_file)

    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    report = build_quality_report(timeline, str(final_path), FFMPEG_BINARY, thumbnail_path)
    if report["status"] != "pass":
        failed = ", ".join(key for key, passed in report["checks"].items() if not passed)
        raise HTTPException(
            status_code=400,
            detail=f"Quality Check chưa đạt: {failed}. Sửa lỗi hoặc tạo/chọn thumbnail trước khi xuất bản.",
        )

    managed_id = payload.managed_channel_id or project.get("managed_channel_id")
    channel = database.get_managed_channel(int(managed_id)) if managed_id else None
    if managed_id and not channel:
        raise HTTPException(status_code=400, detail="Không tìm thấy kênh của tôi")
    privacy = payload.privacy_status or str((channel or {}).get("default_privacy") or "private")
    scheduled_at = payload.scheduled_at.strip() if payload.scheduled_at else ""
    if scheduled_at:
        try:
            parsed = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            scheduled_at = parsed.astimezone(timezone.utc).isoformat()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="scheduled_at phải là ISO datetime hợp lệ") from exc
    elif channel and channel.get("schedule_enabled"):
        scheduled_at = next_channel_schedule(channel) or ""
    if not scheduled_at:
        scheduled_at = None

    try:
        publication = database.create_project_publication(
            project_id,
            str(final_path),
            **_publication_payload(project, script, payload),
            privacy_status=privacy,
            scheduled_at=scheduled_at,
            managed_channel_id=int(managed_id) if managed_id else None,
            thumbnail_path=thumbnail_path,
        )
    except (ValueError, PublisherError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "queued",
        "publication": publication,
        "publisher": publisher_worker.status(),
    }


@app.post("/api/publications/{publication_id}/cancel")
def cancel_publication(publication_id: int) -> dict[str, Any]:
    publication = database.get_project_publication(publication_id)
    if not publication:
        raise HTTPException(status_code=404, detail="Không tìm thấy publication")
    if publication.get("status") != "queued":
        raise HTTPException(status_code=400, detail="Chỉ có thể hủy publication đang xếp hàng")
    return {"status": "cancelled", "publication": database.finish_project_publication(publication_id, "cancelled")}


@app.post("/api/publications/{publication_id}/retry")
def retry_publication(publication_id: int) -> dict[str, Any]:
    publication = database.get_project_publication(publication_id)
    if not publication:
        raise HTTPException(status_code=404, detail="Không tìm thấy publication")
    if publication.get("status") not in {"error", "cancelled"}:
        raise HTTPException(status_code=400, detail="Chỉ có thể chạy lại publication lỗi hoặc đã hủy")
    retried = database.retry_project_publication(publication_id)
    return {"status": "queued", "publication": retried, "publisher": publisher_worker.status()}


@app.get("/api/projects/{project_id}/quality-check")
def get_project_quality_check(project_id: int) -> dict[str, Any]:
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id)
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"])) if script else []
    final_path = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["exports"] / "final.mp4"
    selected_thumbnail = next(
        (item for item in database.list_project_thumbnails(project_id) if item.get("selected")),
        None,
    )
    return build_quality_report(
        timeline,
        str(final_path),
        FFMPEG_BINARY,
        str((selected_thumbnail or {}).get("file_path") or ""),
    )


@app.get("/api/jobs/{job_id}")
def get_project_job(job_id: int) -> dict[str, Any]:
    job = database.get_project_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy production job")
    return job


@app.post("/api/jobs/{job_id}/cancel")
def cancel_project_job(job_id: int) -> dict[str, Any]:
    job = database.get_project_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy production job")
    if job["status"] != "queued":
        raise HTTPException(
            status_code=409,
            detail="Chỉ có thể hủy job đang chờ; job đang chạy sẽ hoàn tất an toàn.",
        )
    cancelled = database.cancel_queued_project_job(job_id)
    return {"job": cancelled}


@app.post("/api/jobs/{job_id}/retry")
def retry_project_job(job_id: int) -> dict[str, Any]:
    job = database.get_project_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy production job")
    if job["status"] not in {"error", "cancelled"}:
        raise HTTPException(status_code=409, detail="Chỉ có thể chạy lại job lỗi hoặc đã hủy")
    retry_job = production_worker.enqueue(
        int(job["project_id"]),
        int(job["script_id"]),
        str(job["job_type"]),
        str(job["provider"]),
        force=True,
    )
    return {"job": retry_job, "retried_from_job_id": job_id}


@app.get("/api/production-queue")
def production_queue_status() -> dict[str, Any]:
    return {
        **production_worker.status(),
        "gpu_only": settings.GPU_ONLY,
        "nvenc_available": nvenc_available(FFMPEG_BINARY),
        "pyvideotrans_configured": bool(PYVIDEOTRANS_COMMAND),
        "pyvideotrans_cuda_ready": settings.PYVIDEOTRANS_CUDA_READY,
        "pyvideotrans_runtime_ready": PYVIDEOTRANS_RUNTIME_READY,
        "pyvideotrans_workdir_configured": bool(PYVIDEOTRANS_WORKDIR),
        "pyvideotrans_voice_role": PYVIDEOTRANS_VOICE_ROLE,
        "voxcpm_runtime_ready": VOXCPM_RUNTIME_READY,
        "voxcpm_model": VOXCPM_MODEL,
        "voxcpm_device": VOXCPM_DEVICE,
        "edge_tts_runtime_ready": EDGE_TTS_RUNTIME_READY,
        "ffmpeg_configured": bool(FFMPEG_RENDER_COMMAND),
        "ffmpeg_builtin_available": ffmpeg_available(FFMPEG_BINARY),
        "openmontage_runtime_ready": bool(openmontage_adapter.status()["ready"]),
        "openmontage": openmontage_adapter.status(),
        "artifact_dir": str(PRODUCTION_ARTIFACT_DIR),
    }


@app.patch("/api/production-queue")
def toggle_production_queue(payload: PauseProductionQueueRequest) -> dict[str, Any]:
    return production_worker.set_paused(payload.paused)


@app.post("/api/projects/{project_id}/premiere-export")
def export_premiere_package(
    project_id: int,
    payload: PremiereExportRequest = PremiereExportRequest(),
) -> dict[str, Any]:
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id)
    if not script:
        raise HTTPException(status_code=400, detail="Project chưa có kịch bản")
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    if not timeline:
        raise HTTPException(status_code=400, detail="Project chưa có timeline")
    try:
        package = build_premiere_export_package(
            project,
            script,
            timeline,
            database.get_video(str(project["youtube_video_id"])),
            PRODUCTION_ARTIFACT_DIR,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "exported",
        **package,
        "download_url": f"/api/projects/{project_id}/premiere-export/download",
    }


@app.get("/api/projects/{project_id}/premiere-export/download")
def download_premiere_package(project_id: int) -> FileResponse:
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    zip_path = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["exports"] / "premiere-package.zip"
    if not zip_path.is_file():
        raise HTTPException(status_code=404, detail="Project chưa có gói Premiere")
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"premiere-export-{project_id}.zip",
    )


@app.post("/api/videos/{video_id}/project")
def create_project_from_video(
    video_id: str,
    payload: CreateProjectRequest = CreateProjectRequest(),
) -> dict[str, Any]:
    try:
        project = database.create_production_project(
            video_id,
            title=payload.title,
            notes=payload.notes,
            managed_channel_id=payload.managed_channel_id,
        )
    except Exception as exc:
        raise _api_error(exc) from exc
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    return {"status": "saved", "project": project}


@app.patch("/api/projects/{project_id}")
def update_project(project_id: int, payload: UpdateProjectRequest) -> dict[str, Any]:
    project = database.update_production_project(
        project_id,
        title=payload.title,
        status=payload.status,
        notes=payload.notes,
        managed_channel_id=payload.managed_channel_id,
    )
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return {"status": "saved", "project": project}


@app.get("/api/videos/{video_id}/transcript")
def get_video_transcript(
    video_id: str,
    transcript_format: str | None = Query(default=None, alias="format"),
) -> dict[str, Any]:
    if not database.get_video(video_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    transcript = database.get_transcript(video_id, transcript_format)
    return transcript or {
        "youtube_video_id": video_id,
        "status": "missing",
        "content_text": "",
    }


@app.get("/api/videos/{video_id}/transcripts")
def list_video_transcripts(video_id: str) -> list[dict[str, Any]]:
    if not database.get_video(video_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    return database.list_transcripts(video_id)


@app.post("/api/videos/{video_id}/transcript")
def save_video_transcript(video_id: str, payload: TranscriptRequest) -> dict[str, Any]:
    if not database.get_video(video_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    content = normalize_transcript(payload.text, payload.transcript_format)
    if not content:
        raise HTTPException(status_code=422, detail="Transcript không có nội dung sau khi làm sạch")
    transcript = database.save_transcript(
        video_id,
        content,
        source_type=payload.source_type,
        language=payload.language,
        transcript_format=payload.transcript_format,
    )
    return {"status": "saved", "youtube_video_id": video_id, "transcript": transcript}


@app.post("/api/videos/{video_id}/transcript/auto")
def auto_transcribe_video(
    video_id: str,
    payload: AutoTranscriptRequest = AutoTranscriptRequest(),
) -> dict[str, Any]:
    """Extract temporary audio and run Faster-Whisper locally to produce a transcript.

    Audio is discarded right after transcription; only the resulting text is stored,
    tagged with source_type='whisper_auto' so it stays distinguishable from
    manually-attested/authorized transcripts.
    """
    video = database.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    if not payload.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Whisper sẽ trích xuất audio tạm thời. Cần xác nhận rõ ràng trước khi chạy.",
        )

    job_id = database.start_analysis_job(video_id, "transcript", "faster_whisper")
    # An uploaded file has no URL to pull audio from, and a YouTube video that
    # was already downloaded should not be fetched a second time. Either way
    # the copy on disk is the better source.
    local_media = Path(str(video.get("local_media_path") or ""))
    try:
        if local_media.is_file():
            result = transcribe_local_file(str(local_media), video_id, language=payload.language or None)
        else:
            result = transcribe_video(video["video_url"], video_id, language=payload.language or None)
        if not result["text"]:
            raise TranscriptionError("Whisper không nhận diện được nội dung thoại nào trong audio")

        transcript = save_transcript_result(database, video_id, result)
        database.finish_analysis_job(job_id, "completed")
        return {
            "job_id": job_id,
            "video_id": video_id,
            "status": "completed",
            "provider": "faster_whisper",
            "language": result["language"],
            "transcript": transcript,
        }
    except Exception as exc:
        database.finish_analysis_job(job_id, "error", str(exc))
        raise _api_error(exc) from exc


@app.get("/api/videos/{video_id}/captions")
def list_video_captions(video_id: str) -> list[dict[str, Any]]:
    """List official YouTube caption tracks for a video (requires OAuth to be connected)."""
    if not database.get_video(video_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    try:
        return list_captions(video_id)
    except Exception as exc:
        raise _api_error(exc) from exc


@app.post("/api/videos/{video_id}/transcript/from-caption")
def import_caption_transcript(video_id: str, payload: CaptionImportRequest) -> dict[str, Any]:
    """Download an official caption track via OAuth and save it as the video's transcript.

    Only succeeds for videos the connected OAuth account owns/manages — YouTube rejects
    caption downloads for other channels' videos regardless of scope.
    """
    if not database.get_video(video_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    try:
        raw_srt = download_caption(payload.caption_id)
    except Exception as exc:
        raise _api_error(exc) from exc

    content = normalize_transcript(raw_srt, "srt")
    if not content:
        raise HTTPException(status_code=422, detail="Caption không có nội dung sau khi làm sạch")
    transcript = database.save_transcript(
        video_id,
        content,
        source_type="authorized_caption",
        language=payload.language,
        transcript_format="txt",
    )
    return {"status": "saved", "youtube_video_id": video_id, "transcript": transcript}


@app.post("/api/videos/{video_id}/download")
def download_video_for_editing(
    video_id: str,
    media_type: str = Query(default="video", pattern="^(video|audio)$"),
    confirmed: bool = Query(default=False),
    browser_session: str = Query(default="", pattern="^(|coccoc)$"),
) -> dict[str, Any]:
    """Download a video's source file for local re-editing (reaction/commentary use).

    Deliberately single-video and manual — no automatic or batch pipeline downloads video.
    The file is kept on disk until explicitly deleted; publishing decisions and copyright
    compliance for the resulting edited video remain the user's responsibility.
    """
    video = database.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    if not confirmed:
        raise HTTPException(
            status_code=400,
            detail="Tải media về máy cần xác nhận rõ ràng từ giao diện.",
        )
    try:
        path = download_video(
            video["video_url"],
            video_id,
            media_type=media_type,
            browser_session=browser_session,
        )
    except Exception as exc:
        raise _api_error(exc) from exc
    database.mark_video_downloaded(video_id, str(path))
    return {"video_id": video_id, "status": "downloaded", "path": str(path), "media_type": media_type}


@app.post("/api/videos/{video_id}/download-with-cookie-file")
async def download_video_with_cookie_file(
    video_id: str,
    media_type: str = Query(default="video", pattern="^(video|audio)$"),
    confirmed: bool = Query(default=False),
    cookie_file: UploadFile = File(...),
) -> dict[str, Any]:
    """Use a user-selected Netscape cookies.txt file only for one local download."""
    video = database.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    if not confirmed:
        raise HTTPException(status_code=400, detail="Tải media cần xác nhận rõ ràng")
    if Path(cookie_file.filename or "").suffix.lower() not in {".txt", ".cookies"}:
        raise HTTPException(status_code=400, detail="Hãy chọn file cookies.txt")
    content = await cookie_file.read()
    if not content or len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File cookies.txt rỗng hoặc vượt quá 5 MB")
    temporary_path = Path(tempfile.gettempdir()) / f"youtube-ai-cookie-{uuid.uuid4().hex}.txt"
    try:
        temporary_path.write_bytes(content)
        path = download_video(
            video["video_url"],
            video_id,
            media_type=media_type,
            cookie_file=temporary_path,
        )
    except Exception as exc:
        raise _api_error(exc) from exc
    finally:
        temporary_path.unlink(missing_ok=True)
    database.mark_video_downloaded(video_id, str(path))
    return {"video_id": video_id, "status": "downloaded", "path": str(path), "media_type": media_type}


@app.delete("/api/videos/{video_id}/download")
def delete_video_download(video_id: str) -> dict[str, Any]:
    if not database.get_video(video_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    delete_downloaded_video(video_id)
    database.mark_video_media_deleted(video_id)
    return {"video_id": video_id, "status": "deleted"}


@app.get("/api/videos/{video_id}/analysis")
def get_video_analysis(video_id: str) -> dict[str, Any]:
    if not database.get_video(video_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    analysis = database.get_video_analysis(video_id, analysis_type="metadata")
    return analysis or {"youtube_video_id": video_id, "status": "pending"}


@app.get("/api/videos/{video_id}/reference-analysis")
def get_reference_analysis(video_id: str) -> dict[str, Any]:
    if not database.get_video(video_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    analysis = database.get_video_analysis(video_id, analysis_type="reference")
    if not analysis:
        return {"youtube_video_id": video_id, "status": "pending"}
    # The stored row carries no status of its own, and the studio only redraws
    # an analysis it can see is finished. Without this a completed analysis
    # came back statusless, was ignored on reload, and the wizard dropped back
    # to step one as though the video had never been read.
    return {"status": "completed", **analysis}


def _analysis_transcript(video_id: str) -> str:
    """Give the analysis one utterance per line, with its timestamp.

    The plain-text transcript is every fragment run together into a wall with
    no punctuation, which throws away the one clue an automatic transcript
    does carry: where each utterance ended. In a drama that boundary is
    usually a change of speaker, so reading the timed version is the
    difference between being able to attribute dialogue and not.
    """
    timed = database.get_transcript(video_id, transcript_format="json")
    if timed:
        try:
            segments = json.loads(str(timed.get("content_text") or "[]"))
        except (TypeError, ValueError):
            segments = []
        lines = [
            f"[{float(item.get('start') or 0):.0f}s] {str(item.get('text') or '').strip()}"
            for item in segments
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]
        if lines:
            return "\n".join(lines)
    subtitles = database.get_transcript(video_id, transcript_format="srt")
    if subtitles:
        body = str(subtitles.get("content_text") or "")
        lines = [
            line.strip() for line in body.splitlines()
            if line.strip() and not line.strip().isdigit() and "-->" not in line
        ]
        if lines:
            return "\n".join(lines)
    plain = database.get_transcript(video_id, transcript_format="txt") or database.get_transcript(video_id)
    return str((plain or {}).get("content_text") or "").strip()


@app.post("/api/videos/{video_id}/reference-analysis")
def create_reference_analysis(
    video_id: str,
    provider: str = Query(default="codex_cli"),
    output_language: str = Query(default=languages.DEFAULT_LANGUAGE, max_length=12),
) -> dict[str, Any]:
    """Analyse structure and style as a remake reference, not a viewer-facing recap."""
    video = database.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    transcript_text = _analysis_transcript(video_id)
    job_id = database.start_analysis_job(video_id, "reference", provider)
    try:
        # Do not rely solely on the browser to enforce this workflow.  Reference
        # analysis is also called from project actions and API clients; in all
        # cases it needs spoken content before judging story beats and scenes.
        # Existing transcripts are reused, so this never downloads audio twice.
        transcript_generated = False
        if not transcript_text:
            whisper_result = transcribe_video(video["video_url"], video_id)
            if not whisper_result["text"]:
                raise TranscriptionError("Whisper không nhận diện được nội dung thoại nào trong audio")
            transcript = save_transcript_result(database, video_id, whisper_result)
            transcript_text = str(transcript.get("content_text") or "").strip()
            transcript_generated = True
        with operations.track("reference", f"Phân tích nguồn: {str(video.get('title') or video_id)[:50]}"):
            result = analyze_reference(video, transcript_text, provider, output_language=output_language)
        database.save_video_analysis(
            video_id, result, analysis_type="reference", provider=result["provider"], source_type=result["source_type"],
        )
        database.finish_analysis_job(job_id, "completed")
        return {
            "job_id": job_id,
            "video_id": video_id,
            "status": "completed",
            "provider": result["provider"],
            "transcript_generated": transcript_generated,
            "result": result,
        }
    except ReferenceAnalysisError as exc:
        database.finish_analysis_job(job_id, "error", str(exc))
        raise _api_error(exc) from exc
    except Exception as exc:
        database.finish_analysis_job(job_id, "error", str(exc))
        raise _api_error(exc) from exc


@app.post("/api/videos/{video_id}/analyze")
def analyze_video(
    video_id: str,
    provider: str | None = Query(default=None),
) -> dict[str, Any]:
    video = database.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    try:
        active_analyzer = resolve_analyzer(provider)
    except LlmAnalysisError as exc:
        raise _api_error(exc) from exc

    job_id = database.start_analysis_job(video_id, "metadata", active_analyzer.provider)
    try:
        # Metadata analysis may be launched outside the wizard too.  Keep the
        # same promise as reference analysis: analysing a video also creates a
        # reusable Whisper transcript when the video does not already have one.
        transcript = database.get_transcript(video_id, transcript_format="txt")
        transcript_generated = False
        if not transcript or not str(transcript.get("content_text") or "").strip():
            whisper_result = transcribe_video(video["video_url"], video_id)
            if not whisper_result["text"]:
                raise TranscriptionError("Whisper không nhận diện được nội dung thoại nào trong audio")
            save_transcript_result(database, video_id, whisper_result)
            transcript_generated = True
        result = active_analyzer.analyze(video)
        database.save_video_analysis(
            video_id,
            result,
            analysis_type="metadata",
            provider=active_analyzer.provider,
            source_type="metadata",
        )
        database.finish_analysis_job(job_id, "completed")
        return {
            "job_id": job_id,
            "video_id": video_id,
            "status": "completed",
            "provider": active_analyzer.provider,
            "transcript_generated": transcript_generated,
            "result": result,
        }
    except Exception as exc:
        database.mark_video_analysis_error(video_id)
        database.finish_analysis_job(job_id, "error", str(exc))
        raise _api_error(exc) from exc


@app.get("/api/videos/{video_id}/writer")
def get_video_writer_content(video_id: str) -> dict[str, Any]:
    if not database.get_video(video_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    result = database.get_video_analysis(video_id, analysis_type="writer")
    return result or {"youtube_video_id": video_id, "status": "pending"}


@app.post("/api/videos/{video_id}/writer")
def generate_video_writer_content(
    video_id: str,
    payload: WriterRequest = WriterRequest(),
) -> dict[str, Any]:
    """Generate new titles/description/hashtags/CTA/script outline via an LLM.

    Uses the saved Whisper transcript when one exists, metadata only otherwise.
    Unlike metadata analysis, there is no free local fallback here — creative
    writing genuinely needs an LLM, so this always requires Claude or GPT.
    """
    video = database.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    try:
        active_writer = resolve_writer(payload.provider)
    except WriterError as exc:
        raise _api_error(exc) from exc

    transcript = database.get_transcript(video_id, transcript_format="txt")
    transcript_text = transcript["content_text"] if transcript else None
    saved_reference = database.get_video_analysis(video_id, analysis_type="reference")
    reference_analysis = saved_reference.get("result") if saved_reference else None
    workflow_context = None
    if payload.managed_channel_id is not None:
        managed_channel = database.get_managed_channel(payload.managed_channel_id)
        if not managed_channel:
            raise HTTPException(status_code=404, detail="Không tìm thấy kênh xuất bản đã chọn")
        workflow_context = {
            "managed_channel_name": managed_channel.get("name", ""),
            "output_profile": managed_channel.get("output_profile", "youtube_landscape"),
            "workflow_reference_title": managed_channel.get("workflow_reference_title", ""),
            "workflow_reference_description": managed_channel.get("workflow_reference_description", ""),
            "workflow_notes": managed_channel.get("notes", ""),
        }

    job_id = database.start_analysis_job(video_id, "writer", active_writer.provider)
    try:
        target_duration = resolve_target_duration_seconds(payload.target_duration_seconds, payload.creative_direction, payload.target_duration_text, video.get("duration_seconds"))
        research_context = research_folklore_remake(str(video.get("title") or ""), payload.creative_direction) if payload.use_web_research else None
        with operations.track("writer", f"Viết kịch bản: {str(video.get('title') or video_id)[:50]}"):
            result = active_writer.generate(
                video,
                transcript_text,
                workflow_context=workflow_context,
                creative_direction=payload.creative_direction,
                remake_mode=payload.remake_mode,
                target_duration_seconds=target_duration,
                source_duration_seconds=video.get("duration_seconds"),
                research_context=research_context,
                reference_analysis=reference_analysis,
                output_language=payload.output_language,
            )
        if research_context:
            result["research_context"] = research_context
        result["target_duration_seconds"] = target_duration
        result["output_language"] = payload.output_language
        result["quality_warnings"] = validate_voiceover_plan(result, target_duration, payload.output_language)
        database.save_video_analysis(
            video_id,
            result,
            analysis_type="writer",
            provider=active_writer.provider,
            source_type=result["source_type"],
        )
        database.finish_analysis_job(job_id, "completed")
        return {
            "job_id": job_id,
            "video_id": video_id,
            "status": "completed",
            "provider": active_writer.provider,
            "result": result,
        }
    except Exception as exc:
        database.finish_analysis_job(job_id, "error", str(exc))
        raise _api_error(exc) from exc


@app.get("/api/analysis-providers")
def list_analysis_providers() -> list[dict[str, Any]]:
    anthropic_key, anthropic_model = settings.anthropic_config()
    openai_key, openai_model = settings.openai_config()
    codex = codex_cli_status()
    claude_code = claude_code_cli_status()
    antigravity = antigravity_cli_status()
    return [
        {"provider": "local_metadata", "label": "Local (không cần API key)", "available": True},
        {
            "provider": "anthropic_claude",
            "label": f"Claude ({anthropic_model})",
            "available": bool(anthropic_key),
        },
        {
            "provider": "openai_gpt",
            "label": f"GPT ({openai_model})",
            "available": bool(openai_key),
        },
        {
            "provider": "codex_cli",
            "label": "Codex CLI (tai khoan dang nhap)",
            "available": bool(codex["logged_in"]),
        },
        {
            "provider": "claude_code_cli",
            "label": "Claude Code CLI (tai khoan dang nhap)",
            "available": bool(claude_code["logged_in"]),
        },
        {
            "provider": "antigravity",
            "label": "Antigravity CLI (tai khoan dang nhap)",
            "available": bool(antigravity["logged_in"]),
        },
    ]


@app.get("/api/analysis-jobs")
def list_analysis_jobs(limit: int = Query(default=30, ge=1, le=100)) -> list[dict[str, Any]]:
    return database.list_analysis_jobs(limit)


@app.post("/api/analysis-jobs/{job_id}/cancel")
def cancel_analysis_job(job_id: int) -> dict[str, Any]:
    """Covers both metadata analysis and Whisper transcript jobs (shared analysis_jobs table)."""
    job = database.get_analysis_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy job")
    if job["status"] != "queued":
        raise HTTPException(
            status_code=409,
            detail="Chỉ có thể hủy job đang chờ; job đang chạy sẽ hoàn tất an toàn.",
        )
    queue = transcript_queue if job.get("analysis_type") == "transcript" else metadata_queue
    return {"job": queue.cancel_queued(job_id)}


@app.post("/api/analysis-jobs/{job_id}/retry")
def retry_analysis_job(job_id: int) -> dict[str, Any]:
    job = database.get_analysis_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy job")
    if job["status"] not in {"error", "cancelled"}:
        raise HTTPException(status_code=409, detail="Chỉ có thể chạy lại job lỗi hoặc đã hủy")
    queue = transcript_queue if job.get("analysis_type") == "transcript" else metadata_queue
    return {"job": queue.retry(job_id)}


@app.get("/api/analysis-queue")
def analysis_queue_status() -> dict[str, Any]:
    return metadata_queue.status()


@app.post("/api/analysis-queue")
def enqueue_analysis(payload: QueueAnalysisRequest) -> dict[str, Any]:
    provider = payload.provider or "local_metadata"
    anthropic_key, _ = settings.anthropic_config()
    openai_key, _ = settings.openai_config()
    codex = codex_cli_status()
    claude_code = claude_code_cli_status()
    antigravity = antigravity_cli_status()
    if provider == "anthropic_claude" and not anthropic_key:
        raise HTTPException(status_code=400, detail="Thiếu ANTHROPIC_API_KEY trong .env")
    if provider == "openai_gpt" and not openai_key:
        raise HTTPException(status_code=400, detail="Thiếu OPENAI_API_KEY trong .env")
    if provider == "codex_cli" and not codex["logged_in"]:
        raise HTTPException(status_code=400, detail="Codex CLI chua dang nhap")
    if provider == "claude_code_cli" and not claude_code["logged_in"]:
        raise HTTPException(status_code=400, detail="Claude Code CLI chua dang nhap")
    if provider == "antigravity" and not antigravity["logged_in"]:
        raise HTTPException(status_code=400, detail="Antigravity CLI chua dang nhap")
    try:
        resolve_analyzer(provider)
    except LlmAnalysisError as exc:
        raise _api_error(exc) from exc
    result = metadata_queue.enqueue_pending(
        channel_id=payload.channel_id,
        limit=payload.limit,
        force=payload.force,
        provider=payload.provider,
        video_ids=payload.video_ids,
    )
    return {**result, "queue": metadata_queue.status()}


@app.patch("/api/analysis-queue")
def pause_analysis_queue(payload: QueuePauseRequest) -> dict[str, Any]:
    return metadata_queue.set_paused(payload.paused)


@app.get("/api/transcript-queue")
def transcript_queue_status() -> dict[str, Any]:
    return transcript_queue.status()


@app.post("/api/transcript-queue")
def enqueue_transcripts(payload: QueueTranscriptRequest) -> dict[str, Any]:
    if not payload.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Hàng đợi Whisper sẽ trích xuất audio tạm thời cho nhiều video. Cần xác nhận trước khi chạy.",
        )
    result = transcript_queue.enqueue_pending(
        channel_id=payload.channel_id,
        limit=payload.limit,
        force=payload.force,
        video_ids=payload.video_ids,
    )
    return {**result, "queue": transcript_queue.status()}


@app.patch("/api/transcript-queue")
def pause_transcript_queue(payload: QueuePauseRequest) -> dict[str, Any]:
    return transcript_queue.set_paused(payload.paused)


@app.get("/api/sync-runs")
def list_sync_runs(limit: int = Query(default=30, ge=1, le=100)) -> list[dict[str, Any]]:
    return database.list_sync_runs(limit)


@app.get("/webhooks/youtube")
def youtube_push_verification(
    mode: str | None = Query(default=None, alias="hub.mode"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
    verify_token: str | None = Query(default=None, alias="hub.verify_token"),
) -> PlainTextResponse:
    if YOUTUBE_PUSH_VERIFY_TOKEN and verify_token != YOUTUBE_PUSH_VERIFY_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid verification token")
    if mode == "subscribe" and challenge:
        return PlainTextResponse(challenge)
    return PlainTextResponse("ok")


@app.post("/webhooks/youtube")
async def youtube_push_event(request: Request) -> dict[str, Any]:
    try:
        events = parse_push_feed(await request.body())
        result = service.handle_push_events(events)
        return {"ok": True, "events": len(events), **result}
    except Exception as exc:
        raise _api_error(exc) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("youtube_monitor.main:app", host="127.0.0.1", port=8787, reload=False)
