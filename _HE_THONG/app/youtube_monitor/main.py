from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import math
import mimetypes
import os
import random
import re
import shlex
import shutil
import subprocess
import threading
import tempfile

import httpx
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Literal
from urllib.parse import urlparse

from fastapi import File, Form, FastAPI, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from .analysis_queue import AnalysisQueue
from .agent_system import ORCHESTRATOR_ROLE, AgentPipeline, AgentTaskWorker, DEFAULT_AGENTS
from . import settings
from .antigravity_bridge import antigravity_cli_status
from .claude_code_bridge import claude_code_cli_status
from .codex_bridge import CodexBridgeError, call_codex_vision_json, codex_cli_status, launch_codex_login
from .database import Database
from .event_bus import EventBus
from .director import DirectorError, director_to_markdown, director_to_script, director_to_shots, generate_director_draft
from .ffmpeg_renderer import ffmpeg_available, media_duration_seconds, nvenc_available, render_timeline_with_ffmpeg
from .ffmpeg_renderer import video_frame_size
from . import operations, usage_limits, workflows
from . import languages
from .fidelity_guard import unsourced_details
from .graphic_overlays import normalize_graphic_overlays
from .scene_direction import DIRECTION_SCHEMA, DIRECTOR_INSTRUCTIONS, normalize_direction, resolve_direction
from .speech_timing import scene_speech_timing, audio_signature
from .gif_generator import GFLOW_GIF_FRAME_COUNT, GifGenerationError, materialize_gif_asset
from .gflow_bridge import cached_status as gflow_cached_status
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
from . import agent_loop, agent_runtime, claude_agent_bridge, codex_agent_bridge, platform_connections
from . import browser_recipes, contact_sheet, orchestrator_runtime, page_source, source_brief, steps, web_research
from . import plan_engine, project_planner, research_collectors, source_detector, source_identity, source_kinds
from .channel_research import ChannelResearchError, ChannelResearchService
from .youtube_quota import YouTubeQuota
from .run_registry import RunRegistry
from .production_worker import (
    ProductionJobError,
    ProductionWorker,
    VOXCPM_PREVIEW_TEXT,
    VOXCPM_VOICE_PRESETS,
)
from .publisher import PublisherError, PublisherWorker, next_channel_schedule
from .project_layout import ensure_project_layout
from .project_context import build_project_context, build_source_package
from .quality_check import build_quality_report
from .scene_generator import SceneGenerationError, SceneGenerationWorker, build_scene_provider_gateway
from .motion_graphics import (
    MOTION_CUT_TYPES,
    composer_ready as motion_composer_ready,
    set_spec_builder as motion_graphics_set_spec_builder,
)
from .source_visuals import mismatched_source_clips
from .source_links import (
    SourceLinkError,
    is_http_url,
    platform_of as source_links_platform,
    probe_url as probe_source_link,
)
from .short_script import (
    DEFAULT_SHORT_SCRIPT_SECONDS,
    MAX_SHORT_SCRIPT_SECONDS,
    MIN_SHORT_SCRIPT_SECONDS,
    RESULT_SCHEMA as SHORT_SCRIPT_SCHEMA,
    ShortScriptError,
    build_short_script,
    estimated_seconds as estimated_short_seconds,
    set_script_writer as short_script_set_writer,
)
from .shorts import (
    frame_matches_profile,
    profile_label,
    MAX_SHORT_SECONDS,
    ShortPlan,
    ShortsPlanError,
    build_plan as build_short_plan,
    plan_duration_seconds,
    set_plan_builder as shorts_set_plan_builder,
)
from .providers import (
    ProviderGatewayError,
    ProviderRoutePolicy,
    SCENE_ANIMATED_IMAGE,
    SCENE_IMAGE,
    SCENE_VIDEO,
)
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
    PYVIDEOTRANS_TTS_TYPE,
    PYVIDEOTRANS_VOICE_ROLE,
    PYVIDEOTRANS_WORKDIR,
    VOXCPM_DEVICE,
    VOXCPM_MODEL,
    VOXCPM_PROMPT_TEXT,
    VOXCPM_PYTHON,
    VOXCPM_REFERENCE_AUDIO,
    VOXCPM_RUNNER,
    voxcpm_runtime_status,
    SYSTEM_ROOT,
    YOUTUBE_API_KEY,
    YOUTUBE_MAX_INITIAL_VIDEOS,
    YOUTUBE_PUSH_VERIFY_TOKEN,
)
from .script_builder import build_script_draft, script_to_markdown
from .burned_in_marks import MarkDetectionError, detect_burned_in_marks
from .ffmpeg_renderer import resolve_ffmpeg
from .source_visuals import SourceVisualError, prepare_source_visuals
from .media_probe import MediaProbeError, describe, probe_media, reject_reason
from . import publish_gate
from . import platform_copy
from . import project_log
from . import voice_library
from . import thumbnail_prompt
from . import chat_agent_presence
from . import phantom_canvas_bridge
from .providers import EXECUTION_EXTERNAL_SIDECAR
from . import oauth as youtube_oauth
from .publisher import oauth_status
from .reuse_check import measure_reuse, narration_overlap, rule_findings, rule_verdict
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
from .video_downloader import VideoDownloadError, delete_downloaded_video, download_preview_video, download_video
from .writer import WriterError, resolve_target_duration_seconds, resolve_writer, revise_script, validate_voiceover_plan
from .folklore_research import research_folklore_remake
from .youtube_captions import CaptionsError, download_caption, list_captions
from .youtube_client import YouTubeApiError, YouTubeClient, parse_video_reference
from .youtube_client import parse_duration as parse_youtube_duration


database = Database(DB_PATH)
event_bus = EventBus(database)
database.set_event_publisher(event_bus.publish)


def _agent_runtime_available(agent: str) -> bool:
    """Whether the in-app worker can run this agent right now.

    A chat app (GPT Work, Claude Cowork) is never run by this worker - it pulls
    its own tasks over MCP - so for the worker it is not available. Saying yes
    here once made chat apps look like executors and reviewers, and every such
    "attempt" ended "Agent không được hỗ trợ".
    """
    if agent in settings.CHAT_AGENT_IDS:
        return False
    # Assignments speak agent names (astra, claude); quota rows and status
    # probes speak runtimes (codex_cli, claude_code_cli). Without this every
    # pipeline task died "astra: unavailable | claude: unavailable" while both
    # CLIs were signed in and ready.
    agent = orchestrator_runtime.runtime_id(agent)
    # The same reading of a stored outage as readiness and the catalog use: a
    # stale one is tried again after the cooldown instead of blocking forever.
    quota = usage_limits.limit_state(database.get_provider_usage_limit(agent))
    if quota["state"] == "reset_passed":
        database.clear_provider_usage_limit(agent)
    if quota["blocking"]:
        return False
    status_calls = {
        "codex_cli": codex_cli_status,
        "claude_code_cli": claude_code_cli_status,
        "antigravity": antigravity_cli_status,
    }
    status_call = status_calls.get(agent)
    if status_call is None:
        return False
    try:
        state = status_call()
    except Exception:
        return False
    return bool(state.get("logged_in") or state.get("ready"))


agent_task_worker = AgentTaskWorker(
    database,
    assignment_resolver=settings.agent_assignment,
    availability_resolver=_agent_runtime_available,
    policy_resolver=settings.automation_policy,
)
agent_pipeline = AgentPipeline(
    database,
    agent_task_worker,
    settings.automation_policy,
    external_agent="",
)

# Running out of a subscription is a normal weekly event here, not a bug, and
# it used to vanish into a job's error column while the orchestrator quietly
# fell back to another agent. The bridges sit below this layer, so they are
# handed somewhere to write what they notice.
usage_limits.set_sink(
    database.record_provider_usage_limit,
    database.clear_provider_usage_limit,
)
# Every Data API call is priced and written to the usage ledger, the monitor's
# included: research searches cost 100 units each and must not be able to
# spend the allowance the channel sync depends on without anyone seeing it.
youtube_quota = YouTubeQuota(database)
youtube = YouTubeClient(YOUTUBE_API_KEY, quota=youtube_quota)
service = SyncService(database, youtube, YOUTUBE_MAX_INITIAL_VIDEOS)
# One Channel Intelligence engine: the channel manager's button and the plan
# step both go through it, so they read and update the same profiles.
channel_research_service = ChannelResearchService(database, youtube)
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
scene_provider_gateway = build_scene_provider_gateway()
scene_generation_worker = SceneGenerationWorker(
    database,
    PRODUCTION_ARTIFACT_DIR,
    provider_gateway=scene_provider_gateway,
)
template_path = Path(__file__).resolve().parent / "templates" / "index.html"


def _source_fingerprint() -> float:
    """The newest modification time across the app's own Python files."""
    root = Path(__file__).resolve().parent
    newest = 0.0
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return newest


# Recorded once, at import: this is the code the running process actually has.
_IMPORTED_SOURCE_MTIME = _source_fingerprint()


def running_build_is_stale() -> bool:
    """Whether the files on disk have moved on since this process started.

    The interface is served from disk and updates without a restart, so it
    can show controls the running Python has never heard of. Saying so is the
    difference between "this feature is broken" and "restart the app".
    """
    return _source_fingerprint() > _IMPORTED_SOURCE_MTIME + 1.0

# Tracks the last time each external-sidecar provider (Antigravity/Flow/Meta
# AI) actually polled for work, so the UI can tell "queued, waiting for a
# sidecar that isn't running" apart from "queued, sidecar will pick it up in
# a few seconds" instead of just sitting at an unmoving progress bar. Reset
# on every app restart by design — a fresh process has no sidecar sightings
# yet, which is the correct "unknown" state until one polls in.
_sidecar_last_seen: dict[str, datetime] = {}
_SIDECAR_STALE_AFTER_SECONDS = 30  # polls happen every 5-10s when idle
# Browser-extension clients wait on the WebSocket instead of polling while
# idle. Track those connections separately, otherwise the status endpoint says
# every Cốc Cốc provider is offline even while the bridge is connected.
_browser_extension_connections = 0


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
        agent_task_worker.stop()


browser_lease_monitor = BrowserLeaseMonitor()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # TestClient and desktop relaunches can enter the same app lifespan more
    # than once in a process.  The shutdown guard belongs to one lifespan,
    # not to the whole Python process; leaving it set meant every later
    # lifespan restarted the workers but skipped stopping them.  Those daemon
    # threads then touched a temporary SQLite database after it had been
    # deleted.  Re-arm the guard before starting a new worker generation.
    global _runtime_workers_stopped
    with _runtime_stop_lock:
        _runtime_workers_stopped = False
    database.initialize()
    # Scenes whose status named only half of what they hold. Cheap and
    # idempotent: it touches only rows whose label disagrees with their files.
    database.resync_timeline_segment_states()
    metadata_queue.start()
    transcript_queue.start()
    production_worker.start()
    publisher_worker.start()
    scene_generation_worker.start()
    agent_task_worker.start()
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
    platform: Literal["youtube", "tiktok", "facebook", "instagram"] = "youtube"
    youtube_channel_id: str = Field(default="", max_length=200)
    group_name: str = Field(default="", max_length=100)
    workflow_reference_channel_id: str = Field(default="", max_length=200)
    output_profile: Literal["youtube_landscape", "youtube_shorts", "instagram_reels", "tiktok", "facebook_reels", "facebook_feed"] = "youtube_landscape"
    language: str = Field(default="vi", max_length=20)
    default_voice_provider: Literal["edge_tts", "google_tts", "piper", "pyvideotrans", "voxcpm"] = "edge_tts"
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
    platform: Literal["youtube", "tiktok", "facebook", "instagram"] | None = None
    youtube_channel_id: str | None = Field(default=None, max_length=200)
    group_name: str | None = Field(default=None, max_length=100)
    workflow_reference_channel_id: str | None = Field(default=None, max_length=200)
    output_profile: Literal["youtube_landscape", "youtube_shorts", "instagram_reels", "tiktok", "facebook_reels", "facebook_feed"] | None = None
    language: str | None = Field(default=None, max_length=20)
    default_voice_provider: Literal["edge_tts", "google_tts", "piper", "pyvideotrans", "voxcpm"] | None = None
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
    # The standalone Short has its own script and storyboard. Keep the
    # existing default, while allowing this endpoint to build its timeline.
    variant: Literal["long", "short"] = "long"


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
    output_profile: Literal["youtube_landscape", "youtube_shorts", "instagram_reels", "tiktok", "facebook_reels", "facebook_feed"] = "youtube_landscape"
    voice_provider: Literal["edge_tts", "google_tts", "piper", "pyvideotrans", "voxcpm"] = "edge_tts"
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
    # A frame lifted out of the video is whatever the camera was doing that
    # second; a thumbnail is composed. Both are useful, so both are offered.
    mode: Literal["frame", "ai", "designed"] = "frame"
    title_text: str = Field(default="", max_length=120)
    provider: str = Field(default="gemini_image", max_length=50)
    video_variant: Literal["long", "short"] = "long"


ProductionJobType = Literal["voiceover", "voiceover_segment", "source_visuals", "render", "render_short", "premiere_draft", "director_production"]


class CreateProductionJobRequest(BaseModel):
    job_type: ProductionJobType
    provider: str = Field(default="dry_run", min_length=1, max_length=50)
    force: bool = False
    confirmed: bool = False
    segment_id: int | None = Field(default=None, ge=1)
    # Which of the project's two videos this job is for. The long one unless
    # asked, so every caller written before the standalone short keeps
    # meaning what it meant.
    variant: Literal["long", "short"] = "long"


class ScriptDraftRequest(BaseModel):
    """Create the long script and, optionally, a standalone Short from one brief."""

    create_standalone_short: bool = False
    short_seconds: int = Field(
        default=DEFAULT_SHORT_SCRIPT_SECONDS,
        ge=MIN_SHORT_SCRIPT_SECONDS,
        le=MAX_SHORT_SCRIPT_SECONDS,
    )
    short_direction: str = Field(default="", max_length=4000)


class CreatePublicationRequest(BaseModel):
    managed_channel_id: int | None = Field(default=None, ge=1)
    platform: Literal["youtube", "tiktok", "facebook", "instagram"] | None = None
    output_profile: Literal["youtube_landscape", "youtube_shorts", "instagram_reels", "tiktok", "facebook_reels", "facebook_feed"] | None = None
    video_variant: Literal["long", "short"] = "long"
    thumbnail_asset_id: int | None = Field(default=None, ge=1)
    title: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=500)
    category_id: str = Field(default="27", min_length=1, max_length=10)
    privacy_status: Literal["private", "unlisted", "public"] | None = None
    scheduled_at: str | None = Field(default=None, max_length=80)
    confirmed: bool = False
    # The verdict the user has already been shown, so the gate need not
    # re-measure the whole source on every publish.
    reuse_verdict: str = Field(default="", max_length=16)
    # A deliberate override, sent only after the page has listed what is
    # missing. Default false: skipping the gate has to be a decision rather
    # than the path of least resistance.
    override_checklist: bool = False


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
    provider: str = Field(default="gemini_image", min_length=2, max_length=80)
    prompt: str = Field(min_length=3, max_length=20_000)
    duration_seconds: int = Field(default=5, ge=1, le=30)
    ratio: Literal["1280:720", "720:1280", "1024:1024"] = "1280:720"
    reference_asset_id: int | None = Field(default=None, ge=1)
    requires_reference_image: bool = False
    motion_as_gif: bool = False
    confirmed: bool = False


SceneProvider = str


class BatchSceneGenerationRequest(BaseModel):
    provider: SceneProvider = "gemini_image"
    # A batch must name the timeline it reads: long video and standalone Short
    # have separate scripts and scene rows.
    variant: Literal["long", "short"] = "long"
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
    active_script_id = int(
        script_id
        or (database.get_latest_project_script(project_id) or {}).get("id")
        or 0
    )
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
    """Tracked channels, each with its research status - read from the DB only."""
    channels = database.list_channels()
    for channel in channels:
        try:
            identity = channel_research_service.resolve(channel["youtube_channel_id"])
            summary = channel_research_service.summary(identity)
        except Exception:
            identity, summary = {}, {"state": "none", "label": "Chưa nghiên cứu", "coverage": {}}
        channel["research"] = {key: summary.get(key) for key in ("state", "label", "updated_at", "coverage")}
        channel["identity"] = {
            "platform": _channel_platform(channel, identity),
            "native_channel_id": identity.get("native_channel_id") or "",
            "resolved": bool(identity.get("resolved")),
            "ref": identity.get("ref") or "",
        }
        # A synthetic row has no picture of its own; the real channel it
        # resolves to may.
        native_row = database.get_channel(identity["native_channel_id"]) if identity.get("native_channel_id") else None
        channel["avatar_url"] = channel.get("thumbnail_url") or (native_row or {}).get("thumbnail_url") or ""
    _group_channel_rows(channels)
    return channels


def _group_channel_rows(channels: list[dict[str, Any]]) -> None:
    """One card per real channel, while every row stays in the list.

    An older link import filed a channel under "WEB-YOUTUBE-…"; the same
    channel may also have its real "UC…" row. Both rows are kept - videos,
    projects and the studio's source picker still point at the old one - but
    only one is shown as the channel: the native row when there is one.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for channel in channels:
        ref = channel["identity"]["ref"]
        groups.setdefault(ref or f"row:{channel['youtube_channel_id']}", []).append(channel)
    for members in groups.values():
        native = members[0]["identity"]["native_channel_id"]
        primary = next((item for item in members if item["youtube_channel_id"] == native), None) or min(
            members,
            key=lambda item: (
                not item.get("thumbnail_url"), not item.get("tracking_enabled"), str(item.get("created_at") or ""),
            ),
        )
        keys = [item["youtube_channel_id"] for item in members]
        for item in members:
            item["display"] = {
                "primary": item is primary,
                "primary_key": primary["youtube_channel_id"],
                "group_keys": keys,
            }


_YOUTUBE_CHANNEL_KEY = re.compile(r"UC[\w-]{22}")


def _channel_platform(channel: dict[str, Any], identity: dict[str, Any]) -> str:
    """The platform a channels row stands for, from what the row already says."""
    if identity.get("platform"):
        return str(identity["platform"])
    key = str(channel.get("youtube_channel_id") or "")
    if key.startswith("site-"):
        return "shop" if str(channel.get("group_name") or "").lower() == "shop" or page_source.looks_like_shop(f"https://{key[5:]}/") else "web"
    if key.startswith("LOCAL-"):
        return "upload"
    if key == "UC_YOUTUBE_AI_FACTORY_IDEAS":
        return "idea"
    if key.startswith("WEB-"):
        extractor = key.split("-")[1] if key.count("-") >= 2 else ""
        return "web" if extractor.startswith(("HTML5", "GENERIC")) else source_links_platform(extractor)
    return "youtube" if _YOUTUBE_CHANNEL_KEY.fullmatch(key) else "web"


def _plain_failure(item: dict[str, Any]) -> dict[str, str]:
    """A collector failure in words for the page: what, where, why - no codes, no collector names."""
    collector = str(item.get("collector") or "")
    source = str(item.get("source") or "")
    reason = str(item.get("reason") or "").lower()
    what = next((label for prefix, label in (
        ("web", "Trang web"), ("youtube.comments", "Comment"), ("youtube.captions", "Phụ đề"),
        ("youtube.similar", "Video tương tự"), ("youtube.reviews", "Video review"), ("channel_research", "Hồ sơ kênh"),
    ) if collector.startswith(prefix)), "Nguồn")
    if source.startswith("search: "):
        where = f"tìm “{source[8:60]}”"
    else:
        where = urlparse(source).hostname or source[:80]
    if any(code in reason for code in ("403", "401", "forbidden", "captcha")):
        why = "trang chặn truy cập tự động"
    elif "timeout" in reason or "timed out" in reason or "quá lâu" in reason:
        why = "phản hồi quá lâu"
    elif "tắt comment" in reason:
        why = "video tắt comment"
    elif "chưa có comment" in reason:
        why = "video chưa có comment"
    elif "phụ đề" in reason:
        why = "không có phụ đề công khai"
    elif "api key" in reason:
        why = "chưa cấu hình YouTube API"
    elif "không có kết quả" in reason:
        why = "tìm không ra kết quả"
    else:
        why = "chưa đọc được"
    return {"what": what, "where": where, "why": why}


def _latest_channel_report(identity: dict[str, Any]) -> dict[str, Any] | None:
    """The newest ResearchReport that researched this channel, summed up for the page."""
    if not identity.get("resolved"):
        return None
    for row in database.list_recent_research_reports(200):
        report = row.get("report") or {}
        source = report.get("source_channel") or {}
        if source.get("native_channel_id") != identity.get("native_channel_id") or source.get("platform") != identity.get("platform"):
            continue
        evidence = report.get("evidence") or []
        kinds: dict[str, int] = {}
        for item in evidence:
            kinds[item.get("source_kind", "")] = kinds.get(item.get("source_kind", ""), 0) + 1
        failures = [_plain_failure(item) for item in report.get("failed_sources") or []]
        return {
            "report_id": row.get("id"), "project_id": row.get("project_id"), "version": row.get("version"),
            "status": row.get("status"), "captured_at": row.get("captured_at"),
            "similar_videos": len(report.get("similar_content") or []),
            "transcripts": kinds.get("transcript", 0),
            "comment_samples": kinds.get("comment_sample", 0),
            "comments_sampled": sum(int(item.get("sample_size") or 0) for item in evidence if item.get("source_kind") == "comment_sample"),
            "web_read": kinds.get("article", 0) + kinds.get("official", 0),
            "web_snippets": kinds.get("search_result", 0),
            "unread_sources": failures,
            "limitations": [str(item) for item in report.get("limitations") or []][:10],
            "channel_status": source.get("status"), "channel_profile_version": source.get("profile_version"),
        }
    return None


def _channel_videos(identity: dict[str, Any], recent: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The channel's videos the app knows: its library rows, then the research window."""
    merged: dict[str, dict[str, Any]] = {}
    for key in identity.get("row_keys") or []:
        for video in database.list_videos(channel_id=key, limit=200):
            row_key = str(video.get("youtube_video_id") or "")
            native = str(video.get("native_video_id") or ("" if row_key.startswith(("web-", "local-", "idea-")) else row_key))
            merged[native or row_key] = {
                "video_id": native or row_key, "row_key": row_key, "in_library": True,
                "title": video.get("title"), "published_at": video.get("published_at"),
                "duration_seconds": video.get("duration_seconds"), "view_count": video.get("view_count"),
                "comment_count": video.get("comment_count"), "thumbnail_url": video.get("thumbnail_url") or "",
                "url": video.get("video_url") or "",
            }
    youtube = identity.get("platform") == "youtube"
    for video in recent:
        native = str(video.get("video_id") or "")
        if not native:
            continue
        if native in merged:
            # The library row wins, but a figure it lacks is taken from research.
            kept = merged[native]
            for field in ("title", "published_at", "duration_seconds", "view_count", "comment_count"):
                if kept.get(field) in (None, "", 0) and video.get(field) not in (None, ""):
                    kept[field] = video[field]
            continue
        merged[native] = {
            "video_id": native, "row_key": "", "in_library": False,
            "title": video.get("title"), "published_at": video.get("published_at"),
            "duration_seconds": video.get("duration_seconds"), "view_count": video.get("view_count"),
            "comment_count": video.get("comment_count"),
            # YouTube serves every video's thumbnail at this address.
            "thumbnail_url": f"https://i.ytimg.com/vi/{native}/mqdefault.jpg" if youtube else "",
            "url": f"https://www.youtube.com/watch?v={native}" if youtube else "",
        }
    return sorted(merged.values(), key=lambda item: str(item.get("published_at") or ""), reverse=True)


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
    # A YouTube reference keeps its own path: the Data API gives channel
    # membership and view counts that yt-dlp does not, and the tracked-channel
    # features depend on them. Anything else is a plain link.
    if is_http_url(payload.reference) and not _looks_like_youtube(payload.reference):
        return _add_link_source(payload.reference, group_name=payload.group_name, allow_channel=False)
    # A YouTube video already stored - under its own id or an older link
    # import's key - is that video: reused through the same helper, never
    # written a second time under another key.
    try:
        native = parse_video_reference(payload.reference)
    except ValueError:
        native = ""
    if native and database.find_videos_by_native_id("youtube", native):
        return _add_link_source(
            f"https://www.youtube.com/watch?v={native}", group_name=payload.group_name, allow_channel=False,
        )
    try:
        return service.add_video(payload.reference, group_name=payload.group_name)
    except Exception as exc:
        raise _api_error(exc) from exc


_YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")


def _looks_like_youtube(reference: str) -> bool:
    lowered = str(reference or "").lower()
    return any(host in lowered for host in _YOUTUBE_HOSTS)


class ImportVideoLinkRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    group_name: str = Field(default="", max_length=120)


def _page_identity(html: str, *, strict: bool) -> str:
    """A title the page states about *itself*, or "".

    `strict` is for marketplaces. Their script-only shell still carries a
    <title>, and it is the site's own slogan - trusting it named the source
    "Shopee Việt Nam | Mua và Bán Trên Ứng Dụng Di Động" instead of the
    product. A listing that means to be understood publishes og:title or a
    JSON-LD name; the shell does not, so a bare <title> there sends the caller
    to the browser.

    Ordinary sites are not held to that. A <title> is how most of the web
    names a page, and refusing it turned a news section that imported fine
    into a failure.
    """
    if not html:
        return ""
    named = str(page_source.product_from_ld(html).get("name") or "").strip()
    stated = str(page_source.meta_tags(html).get("og:title") or "").strip()
    title = named or stated or ("" if strict else page_source.page_title(html))
    return "" if page_source.looks_like_bot_wall(title) else title


def _probe_page_link(url: str, *, known: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Describe a page the way a video probe describes a video, or None.

    Enough of the same shape that the row, the project and every later step
    need no knowledge of which one it was; the analysis step works the kind
    out from the URL and the row's own emptiness.

    `known` is a listing the Product Reader was served a moment ago (the
    preview in "Thêm nguồn"): used instead of opening the marketplace again.
    """
    strict = page_source.looks_like_shop(url)
    try:
        html = page_source.fetch_static(url)
    except page_source.PageSourceError:
        html = ""
    title = _page_identity(html, strict=strict)
    seen: dict[str, Any] = {}

    if not title and platform_connections.site_of(url):
        # A marketplace is read through a browser session - the site's own
        # persistent profile, then the person's signed-in browser - and never
        # through a throwaway browser, which is what these sites refuse.
        if known:
            seen = dict(known)
        else:
            outcome = platform_connections.manager().read(url)
            if outcome.get("status") == platform_connections.OK:
                seen = page_source.product_from_probe(outcome.get("probe") or {})
        named = str(seen.get("name") or "").strip()
        title = "" if page_source.looks_like_bot_wall(named) else named
    elif not title:
        # Either the shell or a challenge came back. The browser is the next
        # thing to try, not a refusal.
        rendered = ""
        try:
            rendered, _text, final_url = page_source.fetch_rendered(url)
            # Being sent to the home page is how a marketplace refuses without
            # refusing: the page loads, names itself honestly, and is not the
            # page that was asked for.
            if page_source.landed_elsewhere(url, final_url):
                rendered = ""
        except page_source.PageSourceError:
            rendered = ""
        title = _page_identity(rendered, strict=strict) if rendered else ""
        html = rendered if title else html

    if not title:
        # Last resort, and a good one: a marketplace writes the listing's
        # title into its own URL, so a page that will not load still says what
        # it is selling. The source is created named after the product and the
        # numbers are left to whoever can actually open the page - which, as
        # the user demonstrated, the orchestrator can.
        title = page_source.name_from_url(url)
        html = ""
    if not title:
        return None

    tags = page_source.meta_tags(html)
    product = page_source.product_from_ld(html) or seen
    host = (urlparse(url).hostname or "page").lower()
    return {
        "video_id": f"web-{hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]}",
        "channel_id": f"site-{host}",
        "uploader": host,
        "uploader_url": f"https://{host}",
        "webpage_url": url,
        "platform": "shop" if page_source.looks_like_shop(url) else "web",
        "native_id": url,
        "title": title[:300],
        "description": str(
            product.get("description") or tags.get("og:description") or tags.get("description") or ""
        )[:5000],
        # No running time is what later marks this as a page rather than a film.
        "duration_seconds": 0,
        "thumbnail": (
            page_source.article_images(html)[:1] and page_source.article_images(html)[0]
            or next(iter(seen.get("images") or []), "")
        ),
        "is_live": False,
    }


def _unreadable_link_detail(url: str, detail: str) -> str:
    """Why a link could not be imported, in words the person can act on."""
    # yt-dlp's "Unsupported URL" says nothing useful about a shop
    # link, which was never going to be a video in the first place.
    if page_source.looks_like_shop(url):
        # Nothing reads this page: not an HTTP client, not a headless
        # browser, and not the CLI's own web reader either. Measured on
        # Shopee and TikTok Shop, all three come back with a shell, a
        # redirect or a captcha. Telling someone to sign in does not
        # help - viewing a listing never required an account - so the
        # message says the one thing that does.
        host = (urlparse(url).hostname or "").lower()
        return (
            f"{host} chặn mọi cách đọc tự động, kể cả trình đọc web của AI. "
            "Hãy mở trang trong trình duyệt của bạn rồi tạo dự án ý tưởng và dán "
            "tên sản phẩm, giá và mô tả vào đó — app sẽ dùng đúng những gì bạn dán "
            "và không tự nghĩ ra con số nào."
        )
    return detail


def _import_video_from_link(
    url: str, *, group_name: str = "", as_page: str = "", page_fallback: bool = True,
) -> dict[str, Any]:
    """Register a source video from any site yt-dlp can read.

    The row looks exactly like a tracked or uploaded one, so transcript,
    analysis and the reup workflow need no knowledge of where it came from.
    Nothing is downloaded here: that stays an explicit, confirmed action.

    The row's source_kind is stated here, from what was actually read:
    `as_page` ("article", "product" or "web") is for a link already known to
    be a page - yt-dlp is not asked, so an article with a clip embedded in it
    is not stored as that clip, and a listing is read as a listing; a link
    yt-dlp reads is a video. `page_fallback=False` is for a link already
    known to be a video: if yt-dlp cannot read it now, that is the answer,
    not a page stored in its place.
    """
    stated_kind = source_kinds.valid(as_page)
    if as_page:
        known = source_detector.recent_product(url) if as_page == "product" else None
        page = _probe_page_link(url, known=known)
        if page is None:
            raise HTTPException(status_code=400, detail=_unreadable_link_detail(url, "Không đọc được trang từ link này."))
        details = page
    else:
        try:
            details = probe_source_link(url)
            stated_kind = source_kinds.VIDEO
        except SourceLinkError as exc:
            if not page_fallback:
                raise HTTPException(
                    status_code=400, detail="Không đọc được video từ link này lúc này. Thử lại sau ít phút.",
                ) from exc
            # yt-dlp is asked first because a link is usually a video. When it is
            # not - an article, a listing - the old behaviour was to refuse, so
            # those sources could not be brought into the app at all even though
            # the analysis step knows how to read them.
            page = _probe_page_link(url)
            if page is None:
                raise HTTPException(status_code=400, detail=_unreadable_link_detail(url, str(exc))) from exc
            details = page
            # A page nobody identified beyond "not a video": a listing on a
            # known shop, otherwise a web page - the kind that claims nothing.
            stated_kind = source_kinds.PRODUCT if page_source.looks_like_shop(url) else source_kinds.WEB
    if details["is_live"]:
        raise HTTPException(
            status_code=400,
            detail="Đây là buổi phát trực tiếp đang diễn ra; hãy nhập lại khi đã có bản lưu.",
        )
    platform = str(details.get("platform_slug") or source_links_platform(details["platform"]))
    metrics_source = "yt_dlp" if details.get("view_count") is not None else ""
    if platform == "youtube":
        # The Data API is the authority on a YouTube video's channel and
        # counts; yt-dlp's reading stands only when the API cannot be asked.
        official = _official_youtube_details(str(details.get("native_id") or ""))
        if official:
            details = {**details, **{key: value for key, value in official.items() if value not in (None, "")}}
            metrics_source = "youtube_data_api"
            if official.get("native_channel_id"):
                details["channel_id"] = official["native_channel_id"]
    if platform == "youtube" and details.get("native_id"):
        # One YouTube video, one row: the monitor, "Một video" and a pasted
        # link all land on the same key, and an older link import keeps its own.
        details["video_id"] = _canonical_youtube_row(str(details["native_id"]))
        if database.get_video_raw_payload(details["video_id"]).get("kind") == "youtube#video":
            return _refresh_monitored_row(details, platform, metrics_source)
    previous = database.get_video(details["video_id"]) or {}
    # A row that exists stays on the channel it is filed under, whatever this
    # read found. Its real channel is recorded beside it (native_channel_id),
    # which is what groups the two in KÊNH; moving the row emptied the older
    # channel row and split one channel into two cards (30/09). It also means
    # a second read that did not get the real channel cannot lose it.
    channel_key = str(previous.get("youtube_channel_id") or "") or details["channel_id"]
    real_youtube_channel = platform == "youtube" and channel_key.startswith("UC")
    existing_channel = database.get_channel(channel_key)
    # A real channel may already be tracked by the monitor, with its own
    # title, counts and uploads playlist; a link import must not overwrite it.
    # Nor does it rewrite the channel row of a video it already has.
    if not previous and not (real_youtube_channel and existing_channel):
        database.upsert_channel({
            "youtube_channel_id": channel_key,
            "channel_url": details["uploader_url"] or details["webpage_url"],
            "title": f"{details['uploader']} · {details['platform']}"[:200],
            "uploads_playlist_id": ("UU" + channel_key[2:]) if real_youtube_channel else channel_key,
            "group_name": group_name or details["platform"],
        })
    fields = _keep_known_metadata(previous, {
        # yt-dlp names a video after its URL when it found no title.
        "title": "" if details["title"] == details["webpage_url"] else details["title"],
        "description": details["description"],
        "published_at": details.get("published_at"),
        "duration_seconds": details["duration_seconds"],
        "thumbnail_url": details["thumbnail"],
    })
    counts = {key: details.get(key) for key in ("view_count", "like_count", "comment_count")}
    if all(value is None for value in counts.values()) and previous.get("metrics_captured_at"):
        # Nothing was counted this time: keep the last counts, with the time
        # they were really read, rather than blanking them.
        counts = {key: previous.get(key) for key in counts}
        counts["metrics_captured_at"] = previous["metrics_captured_at"]
        metrics_source = str(previous.get("metrics_source") or "")
    database.upsert_video({
        "youtube_video_id": details["video_id"],
        "youtube_channel_id": channel_key,
        "video_url": details["webpage_url"],
        **fields,
        "title": fields["title"] or details["webpage_url"],
        **counts,
        "metadata_hash": details["video_id"],
        # What was read - stated here, once; everything after reads it.
        "source_kind": stated_kind,
        "raw_payload": {
            "source": "link_import",
            "platform": details["platform"],
            "native_id": details["native_id"],
            "native_channel_id": details.get("native_channel_id", ""),
            "channel_name": details.get("channel_name", ""),
        },
    })
    database.set_video_source_identity(
        details["video_id"],
        source_platform=platform,
        source_extractor=details["platform"],
        # A page has no video id of its own; for one read by a catch-all
        # extractor the "id" is a piece of its URL.
        native_video_id="" if platform in {"web", "shop"} else details["native_id"],
        native_channel_id=details.get("native_channel_id", ""),
        native_channel_name=details.get("channel_name", ""),
        metrics_source=metrics_source,
    )
    return {
        "status": "imported",
        "import_mode": "link",
        "platform": details["platform"],
        "video": database.get_video(details["video_id"]),
        "channel": database.get_channel(channel_key),
        "identity": source_identity.of(database, details["video_id"]),
    }


def _canonical_youtube_row(native_id: str) -> str:
    """The row a YouTube video already has, or its native id for a new one."""
    rows = database.find_videos_by_native_id("youtube", native_id)
    keys = [str(row["youtube_video_id"]) for row in rows]
    if native_id in keys:
        return native_id
    return keys[0] if keys else native_id


def _refresh_monitored_row(details: dict[str, Any], platform: str, metrics_source: str) -> dict[str, Any]:
    """A link to a video the monitor already stores: add what was read, change nothing it owns.

    The monitor's row holds the API payload, the real channel and the stats
    history; a link import rewriting it would take those away.
    """
    video_id = details["video_id"]
    if any(details.get(key) is not None for key in ("view_count", "like_count", "comment_count")):
        database.update_video_metrics(
            video_id,
            view_count=details.get("view_count"),
            like_count=details.get("like_count"),
            comment_count=details.get("comment_count"),
        )
    database.set_video_source_identity(
        video_id,
        source_platform=platform,
        native_video_id=details["native_id"],
        native_channel_id=details.get("native_channel_id", ""),
        native_channel_name=details.get("channel_name", ""),
        metrics_source=metrics_source,
    )
    video = database.get_video(video_id) or {}
    return {
        "status": "imported",
        "import_mode": "link",
        "platform": details["platform"],
        "video": video,
        "channel": database.get_channel(str(video.get("youtube_channel_id") or "")),
        "identity": source_identity.of(database, video_id),
        "reused_row": True,
    }


def _keep_known_metadata(previous: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    """The fresh values, except where the fresh read came back empty.

    An empty title, a zero duration or a missing date says the read failed,
    not that the video changed, so the value already on the row stands.
    """
    kept: dict[str, Any] = {}
    for key, value in fresh.items():
        empty = value is None or (isinstance(value, str) and not value.strip()) or (key == "duration_seconds" and not value)
        kept[key] = previous.get(key) if empty and previous.get(key) not in (None, "", 0) else value
    return kept


def _official_youtube_details(native_id: str) -> dict[str, Any] | None:
    """What the YouTube Data API says about one video, or None when it cannot say.

    One quota unit. A missing key, a spent quota or an unreachable API leaves
    the import to yt-dlp's reading rather than failing it.
    """
    if not native_id or not youtube.api_key:
        return None
    try:
        items = youtube.get_videos([native_id])
    except YouTubeApiError:
        return None
    if not items:
        return None
    snippet = items[0].get("snippet") or {}
    statistics = items[0].get("statistics") or {}
    content = items[0].get("contentDetails") or {}

    def count(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    return {
        "native_channel_id": str(snippet.get("channelId") or ""),
        "channel_name": str(snippet.get("channelTitle") or ""),
        "view_count": count(statistics.get("viewCount")),
        "like_count": count(statistics.get("likeCount")),
        "comment_count": count(statistics.get("commentCount")),
        "published_at": snippet.get("publishedAt"),
        "duration_seconds": parse_youtube_duration(content.get("duration")),
    }


def _source_media_kind(path: Path) -> str:
    """What was actually downloaded, so the workflow can refuse the wrong one.

    A link can hand back a podcast episode or a music track as readily as a
    film, and the reup workflow cuts pictures out of whatever it is given.
    Recording the kind here is what lets the app say "this has no picture"
    instead of failing inside FFmpeg several steps later.
    """
    try:
        return str(probe_media(Path(path), FFMPEG_BINARY).get("kind") or "")
    except (MediaProbeError, OSError):
        return ""


@app.post("/api/videos/import-link")
def import_video_from_link(payload: ImportVideoLinkRequest) -> dict[str, Any]:
    """Import a source from a link. Kept for older callers; the page uses /api/sources/import.

    Only the request shape differs: the same helper resolves the link to what
    is stored and imports only what is new. This endpoint used to call the
    importer directly, and re-importing an older YouTube link import moved its
    row onto the real channel, leaving the old channel row empty.
    """
    return _add_link_source(payload.url, group_name=payload.group_name, allow_channel=False)


@app.get("/api/videos/probe-link")
def probe_video_link(url: str = Query(min_length=8, max_length=2000)) -> dict[str, Any]:
    """Show what a link is before anything is written or downloaded."""
    try:
        return {"video": probe_source_link(url)}
    except SourceLinkError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---- Nguồn tham khảo · NGUỒN: one box for a link or files -----------------
# source_detector decides what was given; the importers above (and the
# channel sync, the upload, the project assets) do the importing.

class SourceDetectRequest(BaseModel):
    text: str = Field(default="", max_length=2000)
    probe: bool = True


class SourceFileDescriptor(BaseModel):
    index: int = 0
    name: str = Field(default="", max_length=500)
    type: str = Field(default="", max_length=200)
    size: int = Field(default=0, ge=0)
    path: str = Field(default="", max_length=1000)


class SourceFilesDetectRequest(BaseModel):
    files: list[SourceFileDescriptor] = Field(default_factory=list, max_length=2000)


class SourceImportRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    group_name: str = Field(default="", max_length=120)


class ImageCollectionRequest(BaseModel):
    title: str = Field(default="", max_length=200)


# ---- Import Router ----------------------------------------------------------
# Which importer takes what the detector found. The detector only names the
# kind; every importer below existed before "Thêm nguồn" and is used as it was.
SOURCE_ROUTES = {
    source_detector.YOUTUBE_CHANNEL: "channel_sync",  # service.add_channel: follow and sync
    source_detector.VIDEO: "link_import",  # _import_video_from_link: YouTube Data API, yt-dlp
    source_detector.PRODUCT: "page_import",  # _probe_page_link, with the Product Reader's read
    source_detector.ARTICLE: "page_import",
    source_detector.WEB: "page_import",
}
# Files never reach the server before the person confirms, so the page does
# the sending - to the route named here.
FILE_ROUTES = {
    source_detector.IMAGE: "image_collection",  # /api/sources/image-collection, then the project asset upload
    source_detector.IMAGE_COLLECTION: "image_collection",
    source_detector.VIDEO: "upload",  # /api/uploads/source
    source_detector.AUDIO: "upload",
}


def _source_route(detected: dict[str, Any]) -> str:
    """The importer a detection goes to, or "" when there is nothing to import."""
    if detected.get("status") not in (source_detector.DETECTED, source_detector.NEED_CONNECTION):
        return ""
    routes = FILE_ROUTES if detected.get("origin") == "file" else SOURCE_ROUTES
    return routes.get(str(detected.get("kind") or ""), "")


@app.post("/api/sources/detect")
def detect_source(payload: SourceDetectRequest) -> dict[str, Any]:
    """What a pasted link is, and the importer it would go to. Saves nothing.

    `probe=false` answers from the link's shape alone, at once; the page asks
    that first, then again with `probe=true` for what the source says.
    """
    detected = source_detector.detect(
        payload.text, probe=payload.probe, database=database, youtube=youtube, probe_video=probe_source_link,
    )
    return {**detected, "route": _source_route(detected)}


@app.post("/api/sources/detect-files")
def detect_source_files(payload: SourceFilesDetectRequest) -> dict[str, Any]:
    """Group picked or dropped files into sources, from their names and types only."""
    found = source_detector.detect_files(
        [item.model_dump() for item in payload.files],
        extensions=_ASSET_EXTENSIONS, max_bytes=LOCAL_ASSET_MAX_BYTES,
    )
    return {"sources": [{**item, "route": _source_route(item)} for item in found]}


# yt-dlp and httpx word their failures for developers.
_TECHNICAL_ERROR = re.compile(r"ERROR:|HTTP Error|Traceback|Unsupported URL|\[[\w:]+\]|errno", re.I)


def _plain_import_error(detail: str) -> str:
    if _TECHNICAL_ERROR.search(detail):
        return "Không đọc được nguồn từ link này. Có thể trang riêng tư, đã bị xoá, hoặc không cho đọc tự động."
    return detail


def _source_snapshot(detected: dict[str, Any]) -> dict[str, Any]:
    """What the preview showed that the row itself does not keep."""
    metadata = detected.get("metadata") or {}
    snapshot: dict[str, Any] = {"site_name": metadata.get("site_name"), "is_short": metadata.get("is_short") or None}
    if detected.get("kind") == source_detector.PRODUCT and metadata.get("price_text"):
        snapshot.update(
            price_text=metadata["price_text"], price_captured_at=metadata.get("captured_at"),
            seller=metadata.get("seller"),
        )
    return snapshot


def _stored_source(detected: dict[str, Any], url: str) -> dict[str, Any] | None:
    """The row this link already has, if any. Reads the database only.

    By what the preview found; then by the platform's own video id (a video
    is one identity however its row is keyed or filed); then by the exact
    link. An older link import of a YouTube video sits under a "web-..." key
    on a synthetic channel - found here, it is reused where it is.
    """
    known = str((detected.get("existing") or {}).get("video_id") or "")
    stored = database.get_video(known) if known else None
    native = str(detected.get("native_id") or "")
    if stored is None and detected.get("kind") == source_detector.VIDEO and native:
        rows = database.find_videos_by_native_id(str(detected.get("platform") or ""), native)
        stored = database.get_video(str(rows[0]["youtube_video_id"])) if rows else None
    if stored is None:
        stored = database.find_video_by_url(url)
    return stored


def _add_link_source(text: str, *, group_name: str = "", allow_channel: bool = True) -> dict[str, Any]:
    """The one way a link becomes a source - "Thêm nguồn" and the older link endpoints alike.

    1. What the link is: the detection it got a moment ago or, failing that,
       its shape (source_detector). No network here.
    2. Whether it is stored already (_stored_source). If so the row is reused
       exactly where it is - same key, same channel, its project, transcript
       and analysis untouched - and nothing is fetched.
    3. Otherwise the importer SOURCE_ROUTES names takes it, and states the
       row's source_kind.
    A channel goes to the channel sync and is never stored as a source row.
    """
    shape = source_detector.classify(text)
    if shape["status"] != source_detector.DETECTED:
        raise HTTPException(status_code=400, detail=shape["message"])
    url = shape["url"]
    seen = source_detector.recalled(url)
    detected = shape
    # A page's own tags may have said what the URL could not (an article,
    # a listing, a video); a YouTube link is what its shape says it is.
    if seen and (seen.get("kind") == shape["kind"] or shape["kind"] in (source_detector.WEB, source_detector.ARTICLE)):
        detected = seen
    route = _source_route(detected)
    if route == "channel_sync":
        if not allow_channel:
            raise HTTPException(
                status_code=400,
                detail="Đây là link của một kênh, không phải một video. Thêm kênh ở Nguồn tham khảo › NGUỒN.",
            )
        return _import_source_channel(detected, group_name)
    if route not in ("link_import", "page_import"):
        raise HTTPException(status_code=400, detail=detected.get("message") or "Nguồn này chưa thêm được.")
    snapshot = _source_snapshot(detected)
    by = str(detected.get("detected_by") or "")
    stored = _stored_source(detected, url)
    if stored:
        # Already stored: marked as a source, not read or stored again. What
        # this preview found is the kind - fresher evidence than whatever an
        # older row was given - so the chain holds: detected product, stored
        # product, analysed product. A bare link shape (no preview) is weaker
        # and only fills in a row that has no kind.
        # One thing more is corrected: a page stored before the app could tell
        # a check page from a listing is named after it ("Security Check"),
        # and the preview has just read the real name.
        video_id = str(stored["youtube_video_id"])
        named = str(detected.get("title") or "").strip()
        if page_source.looks_like_bot_wall(str(stored.get("title") or "")) and named \
                and not page_source.looks_like_bot_wall(named):
            database.set_video_title(video_id, named)
        probed = bool(seen) or not stored.get("source_kind")
        item = database.record_source_item(
            video_id, kind=str(detected.get("source_kind") or "") if probed else "",
            platform=str(detected.get("platform") or ""), detected_by=by, snapshot=snapshot,
        )
        stored = database.get_video(video_id) or stored
        return {
            "status": "exists", "import_mode": "link", "reused_row": True, "route": "existing",
            "platform": str(stored.get("source_extractor") or stored.get("source_platform") or detected.get("platform") or ""),
            "video": stored, "channel": database.get_channel(str(stored.get("youtube_channel_id") or "")),
            "identity": source_identity.of(database, video_id),
            "kind": item["source_kind"], "source": item,
        }
    as_page = str(detected.get("source_kind") or "") if route == "page_import" else ""
    try:
        # The importer states exactly the kind the detector found: a page as
        # that page, a video as a video - never a page stored in its place.
        result = _import_video_from_link(
            url, group_name=group_name, as_page=as_page, page_fallback=route != "link_import",
        )
    except HTTPException as exc:
        raise HTTPException(status_code=exc.status_code, detail=_plain_import_error(str(exc.detail))) from exc
    video = result.get("video") or {}
    video_id = str(video.get("youtube_video_id") or "")
    if not video_id:
        return {**result, "kind": "", "route": route}
    platform = str(detected.get("platform") or "")
    if platform in ("", "web") and video.get("source_kind") == source_kinds.VIDEO:
        platform = str(video.get("source_platform") or platform)
    # The importer stated the kind (a page asked for, or a video yt-dlp read).
    item = database.record_source_item(video_id, kind="", platform=platform, detected_by=by, snapshot=snapshot)
    return {**result, "kind": item.get("source_kind", ""), "route": route, "source": item}


@app.post("/api/sources/import")
def import_source(payload: SourceImportRequest) -> dict[str, Any]:
    """Add what "Thêm nguồn" detected. The page sends only the link; _add_link_source does the rest."""
    return _add_link_source(payload.text, group_name=payload.group_name)


def _import_source_channel(detected: dict[str, Any], group_name: str) -> dict[str, Any]:
    native = str(detected.get("native_id") or "")
    handle = str((detected.get("metadata") or {}).get("handle") or "")
    row = database.get_channel(native) if native else database.find_channel_by_handle(handle) if handle else None
    if row:
        # Already followed: nothing is synced again, the page opens it.
        return {"status": "exists", "kind": source_detector.YOUTUBE_CHANNEL, "route": "channel_sync",
                "channel_id": row["youtube_channel_id"], "channel": row}
    try:
        result = service.add_channel(native or str(detected.get("url") or ""), group_name=group_name)
    except Exception as exc:
        raise _api_error(exc) from exc
    channel_id = str(result.get("channel_id") or "")
    return {**result, "status": "imported", "kind": source_detector.YOUTUBE_CHANNEL, "route": "channel_sync",
            "channel_id": channel_id, "channel": database.get_channel(channel_id)}


@app.post("/api/sources/image-collection")
def create_image_collection(payload: ImageCollectionRequest) -> dict[str, Any]:
    """A set of pictures as one source: an idea project the images are uploaded into.

    The pictures go through the project's own asset upload; the row says
    image_collection, which the analysis step reads as images.
    """
    title = payload.title.strip() or "Bộ ảnh tham khảo"
    project = database.create_idea_project(f"Bộ ảnh tham khảo: {title}", title=title, source="image_collection")
    video_id = str(project["youtube_video_id"])
    item = database.record_source_item(
        video_id, kind=source_kinds.IMAGE_COLLECTION, platform="local", detected_by="file_type",
    )
    return {"status": "created", "project": project, "video_id": video_id, "source": item}


def _source_view(row: dict[str, Any]) -> dict[str, Any] | None:
    """One saved source as the list shows it."""
    video_id = str(row["youtube_video_id"])
    snapshot = row.get("snapshot") or {}
    local = video_id.startswith(("local-", "idea-"))
    kind = source_kinds.valid(row.get("source_kind"))
    image_count = int(row.get("image_count") or 0)
    if not kind or (kind == source_kinds.IMAGE_COLLECTION and not image_count):
        return None  # not a source, or its pictures never arrived
    url = "" if local else str(row.get("video_url") or "")
    platform = str(row.get("source_item_platform") or "") or ("local" if local else str(row.get("source_platform") or ""))
    if kind == source_kinds.PRODUCT and platform in ("", "shop", "web"):
        market = platform_connections.platform_of(url)
        platform = source_detector.MARKETPLACES.get(market.key, market.key) if market else "shop"
    domain = (urlparse(url).hostname or "").lower().removeprefix("www.")
    channel = str(row.get("native_channel_name") or "")
    if not channel and not str(row.get("youtube_channel_id") or "").startswith(("site-", "LOCAL-", "UC_YOUTUBE_AI")):
        channel = str(row.get("channel_title") or "").rsplit(" · ", 1)[0]
    if kind in (source_kinds.VIDEO, source_kinds.AUDIO) and not local:
        site = channel or domain
    else:
        site = str(snapshot.get("site_name") or "") or ("" if local else domain)
    thumbnail = str(row.get("thumbnail_url") or "")
    if kind == source_kinds.IMAGE_COLLECTION and row.get("first_image_id"):
        thumbnail = f"/api/assets/{int(row['first_image_id'])}/download"
    project_id = int(row["project_id"]) if row.get("project_id") else None
    running = bool(project_id) and _step_runs(project_id, "analyze")[0] is not None
    return {
        "video_id": video_id, "kind": kind,
        "group": "file" if local else source_kinds.GROUPS[kind],
        "title": str(row.get("title") or "") or domain or video_id,
        "thumbnail_url": thumbnail, "platform": platform, "site": site, "url": url,
        "added_at": row.get("source_added_at") or row.get("first_seen_at"),
        "analyzed": bool(row.get("analyzed")), "analyzing": running, "project_id": project_id,
        "duration_seconds": row.get("duration_seconds"),
        "is_short": bool(snapshot.get("is_short")),
        "price_text": str(snapshot.get("price_text") or ""),
        "price_captured_at": str(snapshot.get("price_captured_at") or ""),
        "image_count": image_count,
    }


@app.get("/api/sources")
def list_sources(
    group: Literal["all", "video", "article", "product", "file"] = "all",
    limit: int = Query(default=300, ge=1, le=1000),
) -> dict[str, Any]:
    """The sources added so far, with a count per filter. Reads only."""
    items = [view for view in (_source_view(row) for row in database.list_source_rows()) if view]
    counts = {"all": len(items), "video": 0, "article": 0, "product": 0, "file": 0}
    for item in items:
        counts[item["group"]] = counts.get(item["group"], 0) + 1
    shown = [item for item in items if group == "all" or item["group"] == group][:limit]
    return {"counts": counts, "items": shown}


@app.get("/api/managed-channels")
def list_managed_channels() -> list[dict[str, Any]]:
    return database.list_managed_channels()


@app.post("/api/managed-channels")
def add_managed_channel(payload: ManagedChannelRequest) -> dict[str, Any]:
    try:
        channel = database.create_managed_channel(
            name=payload.name,
            channel_url=payload.channel_url,
            platform=payload.platform,
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


@app.get("/api/channels/{channel_id}/research")
def get_channel_research(channel_id: str) -> dict[str, Any]:
    """Channel Intelligence for one channel, assembled for the page.

    Opening a channel only reads: freshness is computed from what is stored,
    and nothing is fetched. `channel_id` may be a channels row key (a real
    "UC…" or an older synthetic one), "youtube:UC…", or a video id.
    """
    bundle = channel_research_service.bundle(channel_id)
    identity = bundle["identity"]
    if not identity["resolved"] and not identity["row_keys"]:
        raise HTTPException(status_code=404, detail="Không tìm thấy kênh")
    # What the page needs beyond the profile, still read from the database only.
    profile = (
        channel_research_service.store.get(identity["platform"], identity["native_channel_id"])
        if identity["resolved"] else None
    ) or {}
    recent = list(((profile.get("profile") or {}).get("recent_videos")) or [])
    row = database.get_channel(channel_id) or next(
        (database.get_channel(key) for key in identity["row_keys"] if database.get_channel(key)), None,
    ) or {}
    identity["platform"] = identity.get("platform") or _channel_platform(row, identity)
    bundle["avatar_url"] = row.get("thumbnail_url") or ((profile.get("profile") or {}).get("channel") or {}).get("thumbnail_url") or ""
    bundle["recent_videos"] = recent
    bundle["videos"] = _channel_videos(identity, recent)
    bundle["latest_report"] = _latest_channel_report(identity)
    return bundle


class ChannelResearchRefreshRequest(BaseModel):
    mode: Literal["auto", "full"] = "auto"


@app.post("/api/channels/{channel_id}/research/refresh")
def refresh_channel_research(
    channel_id: str, payload: ChannelResearchRefreshRequest = ChannelResearchRefreshRequest(),
) -> dict[str, Any]:
    """Bring a channel's research up to date - the same engine the plan step uses.

    "auto" reuses, updates incrementally or redoes in full as freshness
    requires; "full" redoes it. A second request for the same channel while
    one runs is refused with 409.
    """
    try:
        result = channel_research_service.refresh(
            channel_id, mode=payload.mode,
            identify=lambda video_id: source_identity.refresh(database, video_id, youtube=youtube, probe=probe_source_link),
        )
    except ChannelResearchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    return {"result": result, "research": channel_research_service.bundle(channel_id)["research"]}


@app.get("/api/videos")
def list_videos(
    channel_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    return database.list_videos(channel_id, limit)


@app.get("/api/projects")
def list_projects(limit: int = Query(default=100, ge=1, le=200)) -> list[dict[str, Any]]:
    return database.list_production_projects(limit)


def _narration_source(bundle: dict[str, Any]) -> dict[str, Any]:
    """Whose words the storyboard is actually going to read aloud.

    A written script and the source's own transcript are both plausible
    narrations, and one button replaces the first with the second - so a
    project can sit with an English script and a Vietnamese storyboard and
    nothing on screen says which one the voice will use. Measured by overlap
    rather than by language, because the two are just as easily confused
    within one language.
    """
    timeline = bundle.get("latest_timeline") or []
    narration = " ".join(str(item.get("voice_text") or "") for item in timeline)
    if not narration.strip():
        return {"source": "unknown", "script_overlap": 0.0, "transcript_overlap": 0.0}
    script = bundle.get("latest_script") or {}
    script_text = " ".join(
        str(script.get(field) or "") for field in ("hook", "intro", "main_content", "cta")
    )
    transcript = str((bundle.get("latest_transcript") or {}).get("content_text") or "")
    from_script = narration_overlap(narration, script_text)
    from_transcript = narration_overlap(narration, transcript)

    if from_script >= 0.55:
        source = "script"
    elif from_transcript >= 0.55 and from_transcript > from_script:
        source = "transcript"
    else:
        source = "unknown"
    return {
        "source": source,
        "script_overlap": from_script,
        "transcript_overlap": from_transcript,
        "scene_count": len(timeline),
    }


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
    bundle["narration_source"] = _narration_source(bundle)
    return bundle


@app.get("/api/projects/{project_id}/source-package")
def get_project_source_package(project_id: int) -> dict[str, Any]:
    package = build_source_package(database, project_id)
    if not package:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return package


@app.get("/api/projects/{project_id}/astra-context")
def get_project_astra_context(project_id: int) -> dict[str, Any]:
    context = build_project_context(database, project_id)
    if not context:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return context


# ---------------------------------------------------------------------------
# One implementation per step
#
# The buttons, the automatic run and an AI orchestrator all come through here,
# so a fix lands once instead of in two copies that drifted apart. Each runner
# calls the same handler the endpoint calls - this layer adds the shared parts
# the automatic run used to skip: the prerequisite check, the audit row, and
# the rule that anything spending a paid generation needs confirming.
# ---------------------------------------------------------------------------


def _project_source_video_id(project: dict[str, Any]) -> str:
    return str(project.get("youtube_video_id") or "").strip()


def _steps_done(project_id: int) -> set[str]:
    """Which steps this project has already got through.

    Read from what actually exists - a script row, audio files on segments, a
    final mp4 - rather than from a status column, so a step redone by hand
    outside the app is still seen.
    """
    done: set[str] = set()
    project = database.get_production_project(project_id)
    if not project:
        return done
    video_id = _project_source_video_id(project)
    analysis = database.get_video_analysis(video_id, analysis_type="reference") if video_id else None
    if analysis:
        done.add("analyze")
        # Bước 2 is done only when its plan is `completed`: feasibility ok or
        # adjusted, and nothing under it changed since. A plan waiting on a
        # person's decision, a blocked one and a stale one are all not done.
        outcome = project_planner.step_outcome(
            project_planner.current_plan(database, project_id, str(analysis.get("created_at") or "")))
        if outcome and outcome["completed"]:
            done.add("plan")
    script = database.get_latest_project_script(project_id)
    if script:
        done.add("script")
        script_id = int(script["id"])
        if database.list_project_shots(project_id, script_id=script_id):
            done.add("shots")
        timeline = database.list_project_timeline(project_id, script_id=script_id)
        if timeline:
            done.add("timeline")
            if any(str(item.get("audio_path") or "").strip() for item in timeline):
                done.add("voice")
            if any(str(item.get("visual_path") or "").strip() for item in timeline):
                done.add("media")
    plan = _current_project_edit_plan(project_id)
    if plan and str(plan.get("status") or "") in {"approved", "ready", "applied"}:
        done.add("edit_plan")
    if _current_final_video_path(project_id):
        done.add("render")
    if database.list_project_publications(project_id):
        done.add("publish")
    return done


def analysis_is_about_the_source(result: dict[str, Any], video: dict[str, Any], transcript: str) -> bool:
    """Whether the topic named describes the video that was analysed.

    An analysis once came back with the topic "com" - a fragment of the source
    URL - and every later step believed it: the research, the script and nine
    scenes of pictures were all made about nothing. A topic that shares no
    word with the video's own title or its spoken words is not about it, and
    catching that here costs seconds instead of a whole run.
    """
    topic = str(result.get("topic") or "").strip()
    if len(topic) < 3:
        return False
    source_words = set(re.findall(
        r"\w+", f"{video.get('title') or ''} {video.get('description') or ''} {transcript}".lower(),
        flags=re.UNICODE,
    ))
    topic_words = {word for word in re.findall(r"\w+", topic.lower(), flags=re.UNICODE) if len(word) > 1}
    return bool(topic_words & source_words)


def _source_contact_sheet(video: dict[str, Any], project_id: int) -> Path | None:
    """A sheet of frames from the source, so the analyst can see it.

    Nothing about the source was ever looked at: the analysis was made from a
    title and a description while the app held a transcript it had paid for
    and no frames at all. A small temporary copy is fetched purely for this,
    and deleted; downloading the real thing stays the explicit act it was.
    """
    if not contact_sheet.ffmpeg_available(FFMPEG_BINARY):
        return None
    local = Path(str(video.get("local_media_path") or ""))
    workspace = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["work"] / "source-view"
    workspace.mkdir(parents=True, exist_ok=True)
    sheet = workspace / "source-sheet.jpg"
    if sheet.is_file() and sheet.stat().st_size > 0:
        # The source does not change, so neither does the sheet. Re-running
        # the step should not re-download the video to make the same picture.
        return sheet
    preview: Path | None = None
    try:
        if not local.is_file():
            preview = download_preview_video(
                str(video.get("video_url") or ""), workspace,
                max_height=source_brief.preview_height(video.get("duration_seconds") or 0),
            )
            local = preview
        return contact_sheet.from_video(
            local, sheet, ffmpeg=FFMPEG_BINARY, tiles=source_brief.SHEET_TILES,
        )
    except (VideoDownloadError, contact_sheet.ContactSheetError, OSError):
        # Being unable to see the source is a limitation to report, not a
        # reason to refuse to analyse it.
        return None
    finally:
        if preview is not None and preview.is_file():
            preview.unlink(missing_ok=True)


def _sheet_from_remote_images(urls: list[str], project_id: int, folder: str) -> tuple[Path | None, int]:
    """Download a page's own pictures and tile them into one sheet.

    A listing's photographs and an article's photographs are the only thing
    saying what the subject looks like. Analysing either as though it had no
    pictures is how visual_style came back empty and the scene planner was
    left with nothing to work from.
    """
    if not urls or not contact_sheet.ffmpeg_available(FFMPEG_BINARY):
        return None, 0
    workspace = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["work"] / folder
    workspace.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for index, url in enumerate(urls[: source_brief.SHEET_TILES], start=1):
        try:
            response = httpx.get(
                url, headers=page_source.BROWSER_HEADERS, timeout=20.0, follow_redirects=True,
            )
            response.raise_for_status()
            if not response.content:
                continue
            suffix = Path(str(url).split("?", 1)[0]).suffix.lower()
            target = workspace / f"img-{index:02d}{suffix if suffix in {'.jpg', '.jpeg', '.png', '.webp'} else '.jpg'}"
            target.write_bytes(response.content)
            saved.append(target)
        except (httpx.HTTPError, OSError, ValueError):
            continue
    if not saved:
        return None, 0
    try:
        return _contact_sheet_for_review(saved, project_id), len(saved)
    except Exception:
        return None, 0


ORCHESTRATOR_READ_TASK = "doc_trang_ban_hang"


def ask_orchestrator_to_read(project_id: int, url: str, missing: list[str]) -> str:
    """Queue the page for whoever can actually open it, and say it was queued.

    Every reader the app can drive itself is refused by Shopee and TikTok
    Shop, but the orchestrator reads them: asked in its own window, GPT Work
    returned the listing's name, its price, the shop and its rating. So a page
    the app cannot read is not the end of the road - it is work for the one
    party that can, handed over through the queue it already pulls from.

    One task per link: re-running the step must not pile up duplicates of a
    job nobody has done yet.
    """
    pending = _open_read_tasks(url)
    if pending:
        return str(pending[0].get("id") or "")
    task = database.create_agent_task(
        project_id,
        "research",
        ORCHESTRATOR_READ_TASK,
        {
            "url": url,
            "missing": missing,
            "huong_dan": (
                "Mo link nay bang cong cu duyet web cua ban va ghi lai DUNG nhung gi trang hien ra: "
                "ten san pham, gia dang ban, gia goc neu co, so sao, so danh gia, so da ban, ten shop, "
                "danh muc. Khong suy doan, khong lam tron. Truong nao trang khong hien thi de trong. "
                "Neu bi chan thi noi ro bi chan kieu gi. Tra ket qua qua youtube_factory_complete_task."
            ),
        },
        # A chat agent, never a runtime the in-app worker executes. Assigning
        # this to `astra` handed it straight back to the CLI that had already
        # failed to read the page, and the task died with "astra: unavailable
        # | claude: unavailable | antigravity: unavailable". What can open a
        # marketplace is the desktop app, and the desktop app pulls its own
        # work through MCP.
        assigned_agent=_reading_chat_agent(),
    )
    return str((task or {}).get("id") or "")


def _directing_chat_agent() -> str:
    """The desktop chat app that should take the next run, or "" for none.

    Both apps pull their own work, so a fallback cannot be "try the next one
    when the first fails" - nothing here ever calls them. What it can mean is
    handing the run to whichever chosen app is attached right now. With
    neither attached, the run waits for the primary.
    """
    chosen = settings.orchestrator_chat_agents()
    for agent in chosen:
        if chat_agent_presence.connected(agent):
            return agent
    return chosen[0] if chosen else ""


def _open_read_tasks(url: str) -> list[dict[str, Any]]:
    """Requests still waiting for someone to read this listing.

    Filtered by status in the query, not by scanning the newest rows: once two
    hundred other tasks had been created since, an open request for this link
    fell out of view and a duplicate was queued.
    """
    return [
        task
        for status in ("queued", "running")
        for task in database.list_agent_tasks(status=status, limit=1000)
        if str(task.get("task_type") or "") == ORCHESTRATOR_READ_TASK
        and _same_listing(str(((task.get("input") or {}).get("url") or "")), url)
    ]


def _withdraw_read_tasks(url: str, route: str) -> list[str]:
    """Cancel requests to read a listing the app has now read itself.

    Left open, they send GPT Work to repeat a read that is already done.
    """
    withdrawn = []
    for task in _open_read_tasks(url):
        task_id = str(task.get("id") or "")
        try:
            database.finish_agent_task(
                task_id, "cancelled", output={"reason": f"App đã tự đọc được trang qua {route}"},
            )
            withdrawn.append(task_id)
        except Exception:
            continue
    return withdrawn


def _same_listing(first: str, second: str) -> bool:
    """Two links to the same listing, ignoring tracking queries and slashes."""
    if not first or not second:
        return False
    first_id, second_id = page_source.product_id(first), page_source.product_id(second)
    if first_id and second_id:
        return first_id == second_id and urlparse(first).hostname == urlparse(second).hostname
    return first.split("?", 1)[0].rstrip("/") == second.split("?", 1)[0].rstrip("/")


def _reading_chat_agent() -> str:
    """Which desktop assistant to hand a page to: a connected one if there is."""
    for agent in ("chatgpt_app", "claude_chat"):
        if chat_agent_presence.connected(agent):
            return agent
    # Nobody attached right now. Queue it for the one measured reading these
    # pages, so the work is waiting when its app is next opened.
    return "chatgpt_app"


def extract_source(project_id: int, project: dict[str, Any], options: dict[str, Any]) -> source_brief.Extraction:
    """Gather what there is to analyse. Mechanical: no model is called here.

    What the source is comes from its row (videos.source_kind, stated when it
    was added); `options.source_kind` overrides it, in either vocabulary.
    """
    video_id = _project_source_video_id(project)
    video = (database.get_video(video_id) or {}) if video_id else {}
    images = [
        asset for asset in database.list_project_assets(project_id)
        if str(asset.get("asset_type")) == "image" and Path(str(asset.get("file_path") or "")).is_file()
    ]
    asked = str(options.get("source_kind") or "").strip().lower()
    kind = source_kinds.ANALYSIS_KIND.get(asked, asked) or source_brief.detect_kind(project, video, images)
    metadata = {
        "title": video.get("title") or project.get("title") or "",
        "description": video.get("description") or "",
        "duration_seconds": video.get("duration_seconds") or "",
        "url": video.get("video_url") or "",
    }
    notes = [note for note in [str(project.get("notes") or "").strip()] if note]

    if kind in ("video", "audio"):
        what = "video nguồn" if kind == "video" else "file âm thanh"
        text = str((database.get_transcript(video_id, transcript_format="txt") or {}).get("content_text") or "").strip()
        silent = ""
        if not text:
            try:
                whisper_result = _transcribe_video_source(video, video_id)
            except Exception as exc:
                whisper_result = {"text": ""}
                silent = f"Không lấy được tiếng của {what}: {str(exc)[:200]}"
            if whisper_result["text"]:
                text = str(save_transcript_result(database, video_id, whisper_result).get("content_text") or "")
            else:
                # A music video, a timelapse, gameplay or plain b-roll has
                # pictures and no words - the same situation as a folder of
                # images, not a failure. Refusing here stopped the whole run
                # on a source the frames alone could have carried.
                silent = silent or f"{what[0].upper()}{what[1:]} không có lời nói nào nhận ra được."
        # The timed version when there is one: handed the flat text, the
        # analyst can only report the whole thing as a single unattributed
        # turn, and the workflow that cuts scenes where a line is spoken then
        # has nothing to cut on.
        timed = str((database.get_transcript(video_id, transcript_format="srt") or {}).get("content_text") or "").strip()
        # Only a video has pictures; an audio file has no frames to take.
        sheet = _source_contact_sheet(video, project_id) if kind == "video" else None
        if not text and sheet is None:
            # Neither words nor pictures got through - the video may be
            # geo-blocked, removed, or behind a sign-in. What is left is the
            # title and the description, which is exactly what an idea project
            # has, so it is analysed as one rather than refused. Everything
            # downstream then sees has_story false and a limitation saying the
            # content itself was never reached.
            return source_brief.Extraction(
                kind="idea",
                text=str(metadata.get("description") or "").strip(),
                text_label="Mo ta cua nguon (khong lay duoc noi dung that)",
                metadata=metadata,
                notes=notes + [silent or f"Không lấy được lời nói của {what}."] + (
                    ["Không lấy được khung hình nào của video nguồn."] if kind == "video" else []
                ),
            )
        return source_brief.Extraction(
            kind=kind,
            text=timed or text,
            text_label="Loi thoai da phien am (co moc thoi gian)" if timed else "Loi thoai da phien am",
            image_sheet=sheet, image_count=source_brief.SHEET_TILES if sheet else 0,
            metadata=metadata, notes=notes + ([silent] if silent else []),
        )

    if kind == "product":
        session_id = str(options.get("browser_session") or "").strip()
        try:
            product = page_source.read_product(
                str(metadata["url"]), session_id=session_id, use_ai=bool(options.get("ai_reader")),
            )
        except page_source.PageSourceError as exc:
            return source_brief.Extraction(
                kind="idea", text=str(metadata.get("title") or "").strip(),
                text_label="Tieu de trang ban hang (khong doc duoc noi dung)",
                metadata=metadata, notes=notes + [f"Không đọc được trang bán hàng: {str(exc)[:200]}"],
            )
        read_status = str(product.get("read_status") or "")
        if session_id and read_status != platform_connections.OK:
            # The caller chose this session, so its failure is the answer -
            # reported with what else there is, not papered over.
            others = [
                f"{item.get('id')} ({item.get('status')})"
                for item in product.get("sessions") or [] if item.get("id") != session_id
            ]
            raise HTTPException(
                status_code=424,
                detail=(
                    f"{read_status}: phiên {session_id} không đọc được trang sản phẩm. "
                    f"{product.get('read_detail') or ''} Các phiên khác: {', '.join(others) or 'không có'}. "
                    "Chạy lại với options.browser_session là một phiên khác, hoặc bỏ trống để app tự chọn."
                ).strip(),
            )
        # Anything the caller supplies wins: the marketplaces do not hand over
        # a price to an automated fetch, and a figure typed in by the person
        # who can see the page is worth more than one nobody could read.
        for field in ("price", "currency", "name", "brand", "description"):
            supplied = str(options.get(field) or "").strip()
            if supplied:
                product[field] = supplied
        warnings: list[str] = []
        if read_status and read_status != platform_connections.OK:
            warnings.append(
                f"Chưa đọc được trang sản phẩm ({read_status}). {product.get('read_detail') or ''}".strip()
            )
        if not str(product.get("price") or "").strip():
            warnings.append(
                "Không đọc được giá từ trang bán hàng này. Kịch bản không được nêu bất kỳ con số "
                "giá nào; nếu cần giá, hãy nhập tay qua options.price."
            )
            # Handed to the orchestrator, which can open what the app cannot.
            task_id = ask_orchestrator_to_read(
                project_id, str(metadata["url"]),
                [key for key in ("price", "rating", "review_count", "sold_count")
                 if not str(product.get(key) or "").strip()],
            )
            if task_id:
                warnings.append(
                    f"Đã giao cho AI điều phối đọc trang này (task {task_id[:18]}). "
                    "Bảo nó lấy việc tiếp theo, rồi chạy lại bước phân tích."
                )
        elif read_status == platform_connections.OK:
            _withdraw_read_tasks(str(metadata["url"]), str(product.get("route") or ""))
        sheet, count = _sheet_from_remote_images(
            list(product.get("images") or []), project_id, "product-view",
        )
        return source_brief.Extraction(
            kind="product",
            text=page_source.describe(product),
            text_label="Du lieu trang ban hang",
            image_sheet=sheet, image_count=count,
            metadata={**metadata, "title": product.get("name") or metadata.get("title") or ""},
            notes=notes + [f"Đọc trang qua đường: {product.get('route')}"],
            warnings=warnings,
            # Read off the page with where and when: a TikTok price differs by
            # session and by the hour, so it is only a fact with both attached.
            facts={key: product.get(key) for key in (
                "name", "brand", "category", "sku", "seller", "price", "currency", "price_text", "price_source",
                "original_price", "original_price_text", "discount", "rating", "review_count", "sold_count",
                "availability", "images",
                "product_id", "canonical_url", "url", "route", "captured_at", "read_status", "read_detail", "session",
            ) if product.get(key)},
        )

    if kind in ("article", "web"):
        # The page itself first. Its description is the one-line summary a
        # link preview shows, and taking it whenever it existed meant a
        # 9,000-character page was analysed from 151 characters.
        body = source_brief.article_text(str(options.get("text") or ""))
        if not body and metadata["url"]:
            body = source_brief.article_text(web_research.read_page(str(metadata["url"]), max_chars=24_000))
        if not body:
            body = source_brief.article_text(str(video.get("description") or ""))
            if body:
                notes = notes + ["Không mở được trang; chỉ đọc được phần mô tả ngắn của nó."]
        if not body:
            # The page would not open, or it had nothing readable in it. The
            # title is still a subject, so the run continues on that footing
            # with the gap stated rather than stopping here.
            return source_brief.Extraction(
                kind="idea",
                text=str(metadata.get("title") or "").strip(),
                text_label="Tieu de bai viet (khong doc duoc noi dung)",
                metadata=metadata,
                notes=notes + ["Không đọc được nội dung bài viết từ đường dẫn này."],
            )
        picture_urls: list[str] = []
        if metadata["url"]:
            try:
                picture_urls = page_source.article_images(page_source.fetch_static(str(metadata["url"])))
            except page_source.PageSourceError:
                picture_urls = []
        sheet, count = _sheet_from_remote_images(picture_urls, project_id, "article-view")
        return source_brief.Extraction(
            kind=kind, text=body, text_label="Noi dung bai viet" if kind == "article" else "Noi dung trang web",
            image_sheet=sheet, image_count=count,
            metadata=metadata, notes=notes,
        )

    if kind == "images":
        chosen = images[: source_brief.SHEET_TILES]
        if not chosen:
            raise HTTPException(status_code=422, detail="Dự án chưa có ảnh nào để phân tích")
        try:
            sheet = _contact_sheet_for_review([Path(str(item["file_path"])) for item in chosen], project_id)
        except Exception as exc:
            # The pictures exist but could not be assembled - a broken file, or
            # no ffmpeg. Their names and the project's own notes still say
            # something, so that is analysed instead of refusing outright.
            return source_brief.Extraction(
                kind="idea",
                text=" ".join(str(item.get("original_name") or "") for item in chosen).strip(),
                text_label="Ten cac file anh (khong xem duoc noi dung anh)",
                metadata=metadata,
                notes=notes + [f"Không ghép được ảnh để xem: {str(exc)[:200]}"],
            )
        extra = (
            [f"Chỉ xem {len(chosen)} trên {len(images)} ảnh của dự án."]
            if len(images) > len(chosen) else []
        )
        return source_brief.Extraction(
            kind="images", image_sheet=sheet, image_count=len(chosen),
            metadata=metadata, notes=notes + extra,
        )

    goal = str(options.get("text") or project.get("notes") or project.get("title") or "").strip()
    return source_brief.Extraction(
        kind="idea", text=goal, text_label="Y tuong cua nguoi dung", metadata=metadata, notes=notes,
    )


def _step_analyze(project_id: int, project: dict[str, Any], options: dict[str, Any]) -> Any:
    """Read the source once, with eyes, and write the brief everything else uses.

    This used to be two analyses that never met: one asked a model for SEO
    notes from the title alone, and a second - the one that actually reads the
    spoken content - was not part of the flow and had never run. Now there is
    one call, it is given the transcript and the frames, and its answer is the
    brief the writer and the director both read.
    """
    extraction = extract_source(project_id, project, options)
    video_id = _project_source_video_id(project)
    video = (database.get_video(video_id) or {}) if video_id else {}

    report: dict[str, Any] = {}
    try:
        parsed = _call_orchestrator_json(
            source_brief.SYSTEM_PROMPT,
            source_brief.build_prompt(extraction),
            source_brief.BRIEF_SCHEMA,
            stage="orchestration",
            project_id=project_id,
            step="Phan tich nguon",
            image_path=extraction.image_sheet,
            provider=str(options.get("provider") or "").strip().lower(),
            report=report,
        )
    except ProviderNotSupported as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LlmError as exc:
        raise HTTPException(status_code=502, detail=f"Phân tích nguồn không chạy được: {exc}") from exc
    # Which runtime answered, as the call recorded it. The model's own JSON
    # has no provider field, so reading it from there left every brief
    # unattributed.
    brief = source_brief.finalise(parsed, extraction, str(report.get("runtime") or ""))

    if extraction.kind == "product" and not str(brief.get("topic") or "").strip():
        # The page gave little more than its name, so the model had little to
        # name. The name is a fact the app holds; using it beats refusing the
        # step over a field the source never supplied.
        brief["topic"] = str(extraction.facts.get("name") or extraction.metadata.get("title") or "")
    if extraction.has_story and not analysis_is_about_the_source(brief, video, extraction.text):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Ket qua phan tich khong khop voi nguon (chu de: "
                f"{str(brief.get('topic') or '(trong)')[:60]!r}). Hay chay lai buoc nay va "
                f"chi dinh mot AI cu the qua options.provider."
            ),
        )

    if video_id:
        title = str(video.get("title") or project.get("title") or "")
        database.save_video_analysis(
            video_id, brief, analysis_type="reference",
            provider=str(brief.get("provider") or ""), source_type=extraction.kind,
        )
        database.save_video_analysis(
            video_id, source_brief.metadata_row(brief, title),
            analysis_type="metadata", provider=str(brief.get("provider") or ""), source_type="metadata",
        )
    return {"status": "analyzed", "source": extraction.as_dict(), "result": brief}


def _step_plan(project_id: int, project: dict[str, Any], options: dict[str, Any]) -> Any:
    """Bước 2 · Kế hoạch: from the analysed source, what video to make and how.

    Research (collectors, no model) saves a ResearchReport; then two model
    calls - what the evidence means (InsightReport), and the plan - with the
    validators in insight_engine and plan_engine deciding what a model may
    not. It reads nothing from the legacy research paths.

    options
      mode      auto | full | reason | replan (see project_planner.run)
      settings  {output_profile, target_duration_seconds, video_type} to plan for
      primary_angle_id  plan for this angle among the stored candidates (replan: no research, no insight call)
      provider  one runtime instead of the stage's policy
      collect   false: no collectors, no network beyond the identity lookup
      reason    false: stop at research and a skeleton plan (defaults to `collect`)
    """
    video_id = _project_source_video_id(project)
    video = (database.get_video(video_id) or {}) if video_id else {}
    analysis = database.get_video_analysis(video_id, analysis_type="reference") if video_id else None
    if not video or not (analysis or {}).get("result"):
        raise HTTPException(status_code=409, detail="Chưa có kết quả phân tích nguồn để lập kế hoạch")

    def identify() -> dict[str, Any]:
        if not bool(options.get("refresh_identity", True)):
            return source_identity.of(database, video_id)
        return source_identity.refresh(database, video_id, youtube=youtube, probe=probe_source_link)

    collect = bool(options.get("collect", True))
    reason = bool(options.get("reason", collect))

    def progress(key: str, label: str) -> None:
        # Read back by GET …/steps while the step runs, and after a reload.
        _step_registry.update((project_id, "plan"), stage=key, stage_label=label,
                              stages=[{"key": name, "label": text} for name, text in project_planner.STAGES])

    try:
        return project_planner.run(
            database, project, video, analysis, identify=identify,
            channel_service=channel_research_service if collect else None,
            collectors=_research_collectors() if collect else None,
            quota_used=youtube_quota.used_today,
            reasoner=_plan_reasoner(project_id, str(options.get("provider") or "").strip().lower()) if reason else None,
            options=options, progress=progress,
        )
    except project_planner.PlanError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _plan_reasoner(project_id: int, provider: str) -> Callable[..., tuple[Any, dict[str, Any]]]:
    """The plan step's model calls, through the one orchestrator call every step uses.

    So the runtime is chosen by the stage's policy, a runtime that fails falls
    back to the next one allowed, and each attempt lands in the audit log.
    """
    def ask(system: str, prompt: str, schema: dict[str, Any], label: str) -> tuple[Any, dict[str, Any]]:
        info: dict[str, Any] = {}
        try:
            parsed = _call_orchestrator_json(
                system, prompt, schema, stage="orchestration", project_id=project_id, step=label,
                provider=provider, report=info,
            )
        except ProviderNotSupported as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except LlmError as exc:
            raise project_planner.ReasonerFailed(str(exc)) from exc
        return parsed, info

    return ask


def _research_collectors() -> research_collectors.Collectors:
    return research_collectors.Collectors(database, youtube)


def _project_analysis_time(project_id: int) -> str:
    project = database.get_production_project(project_id)
    video_id = _project_source_video_id(project) if project else ""
    analysis = database.get_video_analysis(video_id, analysis_type="reference") if video_id else None
    return str((analysis or {}).get("created_at") or "")


def _current_project_plan(project_id: int) -> dict[str, Any] | None:
    return project_planner.current_plan(database, project_id, _project_analysis_time(project_id))


def _current_project_insight(project_id: int) -> dict[str, Any] | None:
    return project_planner.current_insight(database, project_id, _project_analysis_time(project_id))


def _describe_steps(project_id: int, done: set[str], running: Iterable[str] = ()) -> list[dict[str, Any]]:
    """The step rows, with Bước 2 saying where its plan stands rather than only done / not done.

    A plan that exists but is not `completed` shows as needs_user_decision,
    blocked or stale, and carries the reason and the choices in `outcome`.
    """
    rows = steps.describe(done, running)
    outcome = project_planner.step_outcome(_current_project_plan(project_id))
    for row in rows:
        if row["key"] != "plan" or not outcome:
            continue
        row["outcome"] = outcome
        if row["state"] == "ready" and outcome["status"] in (
                plan_engine.NEEDS_USER_DECISION, plan_engine.BLOCKED, plan_engine.STALE):
            row["state"] = outcome["status"]
    return rows


def _step_research(project_id: int, project: dict[str, Any], options: dict[str, Any]) -> Any:
    """LEGACY - kept running so nothing that calls it breaks; do not build on it.

    Searches the web for the project's title and stores the hits as a
    director artifact that no other step reads. Bước 2 · Kế hoạch
    (`_step_plan`) replaces it and deliberately does not read its output.

    Original intent: stored rather than returned and forgotten, so the writer
    two steps later could see what was actually found.
    """
    queries = options.get("queries")
    if isinstance(queries, str):
        queries = [queries]
    if not isinstance(queries, list) or not queries:
        subject = str(
            options.get("query")
            or project.get("title")
            or project.get("source_title")
            or project.get("notes")
            or ""
        ).strip()
        if not subject:
            raise HTTPException(status_code=400, detail="Chưa có chủ đề để nghiên cứu")
        queries = [subject]

    limit = max(1, min(int(options.get("limit") or 5), 10))
    # The top few results are opened and read, not just listed. Titles and
    # snippets are a table of contents: a writer handed only those still has
    # to invent the substance, which is the thing this step exists to prevent.
    read_pages = max(0, min(int(options.get("read_pages") or 3), limit))
    findings = [
        web_research.summarise(
            str(query), web_research.search(str(query), limit=limit, read_pages=read_pages),
        )
        for query in queries[:5]
    ]
    total = sum(int(item["count"]) for item in findings)
    artifact = database.save_director_artifact(project_id, "research", {"findings": findings})
    return {
        "queries": [item["query"] for item in findings],
        "result_count": total,
        "findings": findings,
        "artifact_id": (artifact or {}).get("id"),
        # An empty lookup is reported as empty. A step that quietly passed
        # would let the writer present its own memory as researched fact.
        "researched": bool(total),
    }


def _step_media(project_id: int, project: dict[str, Any], options: dict[str, Any]) -> Any:
    """Queue the pictures for every scene that still needs one."""
    return queue_scene_generation_batch(
        project_id,
        BatchSceneGenerationRequest(
            provider=str(options.get("provider") or "auto"),
            variant=str(options.get("variant") or "long"),
            confirmed=True,
        ),
    )


def _step_publish(project_id: int, project: dict[str, Any], options: dict[str, Any]) -> Any:
    """Run the pre-publish checks, and publish only when told to in words.

    Publishing is the one step that cannot be undone from inside the app, so
    the default is to check and stop. `confirmed_publish` is deliberately not
    the same flag the other steps use: nothing should reach a channel because
    a caller passed the confirmation that unlocks spending.
    """
    checklist = project_publish_checklist(
        project_id,
        PublishChecklistRequest(
            video_variant=str(options.get("variant") or "long"),
            managed_channel_id=options.get("managed_channel_id"),
            platform=str(options.get("platform") or "youtube"),
            output_profile=str(options.get("output_profile") or "youtube_landscape"),
        ),
    )
    if not bool(options.get("confirmed_publish")):
        return {"status": "checked", "published": False, "checklist": checklist}
    publication = queue_project_publication(
        project_id,
        CreatePublicationRequest(
            confirmed=True,
            video_variant=str(options.get("variant") or "long"),
            **{key: value for key, value in options.items() if key in {"title", "description", "tags"}},
        ),
    )
    return {"status": "queued", "published": True, "checklist": checklist, "publication": publication}


def _step_script(project_id: int, project: dict[str, Any], options: dict[str, Any]) -> Any:
    """Save the project's script, whoever wrote it.

    An agent that has already written one passes it in `draft`; anything else
    goes through the writer the buttons use. Either way the row is created
    here, so there is one place that decides what a saved script looks like.
    """
    draft = options.get("draft")
    if isinstance(draft, dict) and str(draft.get("main_content") or "").strip():
        script = database.create_project_script(
            project_id,
            script_title=str(draft.get("script_title") or draft.get("title") or project.get("title") or ""),
            hook=str(draft.get("hook") or ""),
            intro=str(draft.get("intro") or ""),
            main_content=str(draft.get("main_content") or ""),
            cta=str(draft.get("cta") or ""),
            status=str(draft.get("status") or "review"),
        )
        if not script:
            raise HTTPException(status_code=404, detail="Không lưu được kịch bản")
        return {"script_id": int(script["id"]), "script": script}

    # Nobody handed one over, so it has to be written. The draft endpoint only
    # assembles what the writer already produced: called on its own it returns
    # in no time at all, having quietly turned the analysis notes into
    # "narration" - SEO advice where the spoken words should be.
    video_id = _project_source_video_id(project)
    if video_id and not (database.get_video_analysis(video_id, analysis_type="writer") or {}).get("result"):
        generate_video_writer_content(
            video_id,
            WriterRequest(
                provider=str(options.get("provider") or "") or None,
                creative_direction=str(options.get("creative_direction") or ""),
                remake_mode=str(options.get("remake_mode") or "new_angle_same_topic"),
                output_language=str(options.get("language") or languages.DEFAULT_LANGUAGE),
                target_duration_text=str(options.get("target_duration") or ""),
            ),
        )
    return create_project_script_draft(
        project_id,
        ScriptDraftRequest(
            create_standalone_short=bool(options.get("create_standalone_short", False)),
            short_direction=str(options.get("short_direction") or ""),
        ),
    )


def _step_script_review(project_id: int, project: dict[str, Any], options: dict[str, Any]) -> Any:
    return review_project_script(project_id)


def _step_shots(project_id: int, project: dict[str, Any], options: dict[str, Any]) -> Any:
    """Save the scene list, whether an agent wrote it or the planner did."""
    supplied = options.get("shots")
    if isinstance(supplied, list) and supplied:
        script = database.get_latest_project_script(project_id)
        if not script:
            raise HTTPException(status_code=400, detail="Chưa có kịch bản để chia cảnh")
        saved = database.create_project_shots(
            project_id, int(script["id"]), supplied, force=bool(options.get("force", True)),
        ) or []
        return {"status": "saved", "script_id": int(script["id"]), "shots": saved}
    return generate_project_shots(project_id, GenerateShotsRequest(force=bool(options.get("force", False))))


def _step_timeline(project_id: int, project: dict[str, Any], options: dict[str, Any]) -> Any:
    supplied = options.get("segments")
    if isinstance(supplied, list) and supplied:
        script = database.get_latest_project_script(project_id)
        if not script:
            raise HTTPException(status_code=400, detail="Chưa có kịch bản để dựng timeline")
        timeline = database.create_project_timeline(
            project_id, int(script["id"]), supplied, force=bool(options.get("force", True)),
        ) or []
        return {"status": "saved", "script_id": int(script["id"]), "timeline": timeline}
    return generate_project_timeline(
        project_id,
        GenerateTimelineRequest(
            force=bool(options.get("force", False)),
            variant=str(options.get("variant") or "long"),
        ),
    )


def _step_voice(project_id: int, project: dict[str, Any], options: dict[str, Any]) -> Any:
    return queue_project_job(
        project_id,
        CreateProductionJobRequest(
            job_type="voiceover",
            provider=str(options.get("provider") or "edge_tts"),
            confirmed=True,
            variant=str(options.get("variant") or "long"),
        ),
    )


def _step_voice_review(project_id: int, project: dict[str, Any], options: dict[str, Any]) -> Any:
    return review_project_voice(project_id)


def _refuse_a_script_that_failed_review(project_id: int) -> None:
    """A score that blocks nothing is a note.

    The reviewer gives the script a mark and the policy carries a minimum, but
    nothing read them: a script the app had itself judged unfit went on to be
    voiced, illustrated and rendered. The one place worth stopping is before
    the spending starts. A script nobody reviewed is allowed through - review
    is not compulsory - but one that was reviewed and failed is not.
    """
    script = database.get_latest_project_script(project_id)
    # An unreviewed script carries a score of 0, which is not a failing mark -
    # it is the absence of one. Reading it as failure would block every normal
    # run, so what counts is whether a reviewer is named.
    if not script or not str(script.get("review_agent") or "").strip():
        return
    minimum = max(0, min(int(settings.automation_policy().get("min_review_score") or 0), 10))
    score = int(script.get("review_score") or 0)
    if minimum and score < minimum:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Kịch bản bị chấm {score}/10, dưới mức tối thiểu {minimum}. "
                f"Sửa kịch bản rồi duyệt lại, hoặc hạ min_review_score trong Automation Policy. "
                f"Nhận xét: {str(script.get('review_note') or '')[:200]}"
            ),
        )


def _step_edit_plan(project_id: int, project: dict[str, Any], options: dict[str, Any]) -> Any:
    _refuse_a_script_that_failed_review(project_id)
    planned = plan_project_edit(project_id, motion_policy=str(options.get("motion_policy") or "balanced"))
    if not options.get("apply", True):
        return planned
    approve_project_edit_plan(project_id)
    return {**planned, "applied": apply_project_edit_plan(project_id)}


def _step_render(project_id: int, project: dict[str, Any], options: dict[str, Any]) -> Any:
    return queue_project_job(
        project_id,
        CreateProductionJobRequest(
            job_type="render",
            provider=str(options.get("provider") or "ffmpeg_builtin"),
            confirmed=True,
            variant=str(options.get("variant") or "long"),
        ),
    )


_STEP_RUNNERS: dict[str, Any] = {
    "analyze": _step_analyze,
    "plan": _step_plan,
    "research": _step_research,
    "media": _step_media,
    "publish": _step_publish,
    "script": _step_script,
    "script_review": _step_script_review,
    "shots": _step_shots,
    "timeline": _step_timeline,
    "voice": _step_voice,
    "voice_review": _step_voice_review,
    "edit_plan": _step_edit_plan,
    "render": _step_render,
}


# Analysing a source takes minutes and outlives the request that started it:
# reloading the page drops the request, not the work. What is running is kept
# here, in the process doing it, so a page asks instead of remembering - and
# a second click, a second tab or an orchestrator cannot start the same work
# twice. It goes with a restart, together with the work it describes.
_SINGLE_RUN_STEPS = frozenset({"analyze", "plan"})
_step_registry = RunRegistry()


def _step_runs(project_id: int, step: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The run of this step going on now, and the one that last finished."""
    return _step_registry.state((project_id, step))


def run_project_step(project_id: int, step: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Perform one step, for whoever asked - a button, a run, an orchestrator."""
    options = dict(options or {})
    definition = steps.get(step)
    if definition is None or definition.key not in _STEP_RUNNERS:
        known = ", ".join(sorted(_STEP_RUNNERS))
        raise HTTPException(status_code=400, detail=f"Bước không chạy được: {step}. Đang có: {known}")
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")

    def refuse(status_code: int, detail: str) -> HTTPException:
        # A refusal belongs in the log as much as a failure does: an
        # orchestrator reads it to learn what to do first, and a person reads
        # it to see why the run stopped where it did.
        _record_orchestrator_step(
            project_id=project_id, stage=definition.stage or "pipeline", step=definition.label,
            status="refused", why=f"run_step({definition.key})", error=detail[:1500],
        )
        _announce_step(
            "step.refused", project_id, definition.key, definition.label, error=detail[:500],
        )
        return HTTPException(status_code=status_code, detail=detail)

    missing = steps.unmet_requirements(definition.key, _steps_done(project_id))
    if missing and not options.get("force"):
        labels = ", ".join((steps.get(name).label if steps.get(name) else name) for name in missing)
        raise refuse(409, f"Chưa làm xong bước trước: {labels}")

    # Spending is exactly what the automatic run used to do without asking,
    # because it wrote to the database instead of calling the endpoint that
    # enforces this.
    if definition.spends and not bool(options.get("confirmed", True)):
        raise refuse(400, f"Bước {definition.label} tiêu lượt, cần xác nhận")

    run_key = (project_id, definition.key)
    single = definition.key in _SINGLE_RUN_STEPS
    if single and _step_registry.claim(run_key) is None:
        raise refuse(409, f"Bước {definition.label} đang chạy cho dự án này. Chờ lượt đó xong rồi hãy chạy lại.")

    started = time.monotonic()
    outcome: dict[str, Any] = {"status": "failed", "status_code": 500, "error": "Bước dừng giữa chừng."}
    try:
        _announce_step("step.started", project_id, definition.key, definition.label)
        try:
            result = _STEP_RUNNERS[definition.key](project_id, project, options)
        except HTTPException as exc:
            outcome = {"status": "failed", "status_code": exc.status_code, "error": str(exc.detail)[:500]}
            _record_orchestrator_step(
                project_id=project_id, stage=definition.stage or "pipeline", step=definition.label,
                status="failed", why=f"run_step({definition.key})", error=str(exc.detail)[:1500],
            )
            _announce_step(
                "step.failed", project_id, definition.key, definition.label,
                seconds=round(time.monotonic() - started, 1), error=str(exc.detail)[:500],
            )
            raise
        _record_orchestrator_step(
            project_id=project_id, stage=definition.stage or "pipeline", step=definition.label,
            status="success", why=f"run_step({definition.key})",
            output_ref=f"{time.monotonic() - started:.1f}s",
        )
        _announce_step(
            "step.finished", project_id, definition.key, definition.label,
            seconds=round(time.monotonic() - started, 1),
        )
        outcome = {"status": "success"}
        return {"step": definition.key, "label": definition.label, "result": result}
    finally:
        if single:
            _step_registry.finish(run_key, outcome)


@app.get("/api/research/search")
def search_the_web(
    query: str = Query(min_length=2, max_length=300),
    limit: int = Query(default=5, ge=1, le=10),
) -> dict[str, Any]:
    """Look something up, for whoever is directing.

    Of the tools an orchestrator could reach, none searched for anything: it
    was expected to research from memory and then asked not to invent. This
    returns pointers only - titles, snippets, links - and says so plainly when
    it finds nothing, because an empty result quietly filled from memory is
    the failure worth preventing.
    """
    results = web_research.search(query, limit=limit)
    return web_research.summarise(query, results)


@app.get("/api/timeline/{segment_id}/speech-timing")
def get_segment_speech_timing(segment_id: int) -> dict[str, Any]:
    """Where each word falls inside a scene's narration.

    The app already measures this with Whisper to size scenes, but kept it to
    itself, so a director could not cut on a stressed word or hold through a
    pause - the thing that separates an edit from a slideshow.
    """
    segment = database.get_project_timeline_segment(segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh")
    timing = scene_speech_timing(segment)
    words = timing.get("words") or []
    return {
        "segment_id": segment_id,
        "segment_index": segment.get("segment_index"),
        "duration_seconds": timing.get("duration_seconds"),
        "timing_basis": timing.get("timing_basis"),
        "warning": timing.get("warning"),
        "word_count": len(words),
        "words": words,
        # Gaps are where a cut can land without stepping on a word.
        "pauses": [
            {
                "after_word": str(words[index].get("word") or ""),
                "start": round(float(words[index].get("end") or 0), 3),
                "end": round(float(words[index + 1].get("start") or 0), 3),
                "seconds": round(float(words[index + 1].get("start") or 0) - float(words[index].get("end") or 0), 3),
            }
            for index in range(len(words) - 1)
            if float(words[index + 1].get("start") or 0) - float(words[index].get("end") or 0) >= 0.25
        ][:40],
    }


@app.get("/api/projects/{project_id}/contact-sheet")
def get_project_contact_sheet(
    project_id: int, tiles: int = Query(default=12, ge=1, le=24)
) -> dict[str, Any]:
    """One image of what this project looks like right now.

    An orchestrator could queue every step and approve a plan without ever
    seeing a frame. This is the cheapest way to let it look: frames sampled
    across the finished video when there is one, otherwise the scenes as they
    currently stand. The path is returned rather than the bytes, because the
    readers of this - Claude Code, the ChatGPT app - open local files.
    """
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    if not contact_sheet.ffmpeg_available(FFMPEG_BINARY):
        raise HTTPException(status_code=400, detail="Chưa có FFmpeg để tạo ảnh tổng hợp")

    layout = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)
    output = Path(layout["work"]) / "contact-sheet.jpg"
    final_video = _current_final_video_path(project_id)
    try:
        if final_video:
            source = Path(final_video)
            seconds = media_duration_seconds(source) or 0.0
            contact_sheet.from_video(
                source, output, ffmpeg=FFMPEG_BINARY, tiles=tiles, duration_seconds=float(seconds),
            )
            kind, origin = "render", str(source)
        else:
            script = database.get_latest_project_script(project_id)
            timeline = database.list_project_timeline(
                project_id, script_id=int(script["id"]) if script else None,
            )
            visuals = [Path(str(item.get("visual_path") or "")) for item in timeline]
            contact_sheet.from_scene_visuals(visuals, output, ffmpeg=FFMPEG_BINARY)
            kind, origin = "storyboard", f"{len(timeline)} cảnh"
    except contact_sheet.ContactSheetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "project_id": project_id,
        "kind": kind,
        "source": origin,
        "path": str(output),
        "bytes": output.stat().st_size,
    }


@app.get("/api/projects/{project_id}/steps")
def list_project_steps(project_id: int) -> dict[str, Any]:
    """Where this project stands, one row per step."""
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    done = _steps_done(project_id)
    runs = {key: _step_runs(project_id, key) for key in _SINGLE_RUN_STEPS}
    rows = _describe_steps(project_id, done, [key for key, (running, _) in runs.items() if running])
    for row in rows:
        row["runnable"] = row["key"] in _STEP_RUNNERS
        if row["key"] in runs:
            row["run"], row["last_run"] = runs[row["key"]]
    return {"project_id": project_id, "done": sorted(done), "steps": rows}


@app.get("/api/projects/{project_id}/plan")
def get_project_plan(project_id: int) -> dict[str, Any]:
    """The latest ProjectPlan and the ResearchReport it was built from.

    Kept apart on purpose: research can be reused or redone without the plan,
    and a plan names the report version it relied on. `resources` is the
    plan's assets as a reader sees them - what the project has, what the app
    will make, what is missing, what is only a suggestion - decided by
    plan_engine so no page has to work it out again.
    """
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    plan = _current_project_plan(project_id)
    report_id = (plan or {}).get("research_report_id")
    report = database.get_research_report(int(report_id)) if report_id else database.get_latest_research_report(project_id)
    # The insights the plan was reasoned from; with no plan yet, the latest ones.
    insight_id = (plan or {}).get("insight_report_id")
    insight = database.get_insight_report(int(insight_id)) if insight_id else _current_project_insight(project_id)
    video_id = _project_source_video_id(project)
    video = (database.get_video(video_id) or {}) if video_id else {}
    analysis = database.get_video_analysis(video_id, analysis_type="reference") if video_id else None
    return {"project_id": project_id, "plan": plan, "research_report": report, "insight_report": insight,
            "resources": project_planner.plan_resources(database, project, video, analysis, plan, report),
            "stages": [{"key": key, "label": label} for key, label in project_planner.STAGES]}


@app.get("/api/youtube/quota")
def get_youtube_quota() -> dict[str, Any]:
    """How much of today's YouTube Data API allowance the app has used."""
    return {**youtube_quota.status(), "api_key_configured": bool(youtube.api_key)}


class RunStepRequest(BaseModel):
    options: dict[str, Any] = Field(default_factory=dict)


@app.post("/api/projects/{project_id}/steps/{step}")
def run_project_step_endpoint(
    project_id: int, step: str, payload: RunStepRequest = RunStepRequest()
) -> dict[str, Any]:
    return run_project_step(project_id, step, payload.options)


@app.get("/api/projects/{project_id}/orchestrator-report")
def get_project_orchestrator_report(
    project_id: int, limit: int = Query(default=200, ge=1, le=1000)
) -> dict[str, Any]:
    """What the AI actually did on this project, step by step.

    The plan calls this the audit a run has to be able to produce: which model
    was chosen for each step and why, what it returned, and where a template
    stood in for it. A run that cannot fill this table did not happen the way
    the finished video suggests.
    """
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    steps = database.list_orchestrator_steps(project_id, limit=limit)
    return {
        "project_id": project_id,
        "steps": steps,
        "summary": orchestrator_runtime.report_summary(steps),
        "markdown": orchestrator_runtime.report_markdown(steps),
    }


@app.get("/api/projects/{project_id}/final-video")
def stream_project_final_video(project_id: int) -> FileResponse:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    final_path = _current_final_video_path(project_id)
    if not final_path:
        raise HTTPException(status_code=404, detail="Dự án chưa có video hoàn chỉnh cho phiên kịch bản hiện tại; hãy tạo cảnh AI và render lại")
    return FileResponse(final_path, media_type="video/mp4")


@app.get("/api/videos/{video_id}/source-preview")
def stream_source_video_preview(video_id: str) -> FileResponse:
    """Serve the local source media so the wizard can preview it in-app.

    YouTube videos can be embedded directly by the browser.  This endpoint is
    for files the app already has on disk: downloaded sources and local uploads.
    """
    video = database.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Không tìm thấy video nguồn")
    source_path = Path(str(video.get("local_media_path") or ""))
    if not source_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Video nguồn chưa có file trên máy. Hãy tải video nguồn hoặc dùng khung YouTube nhúng.",
        )
    media_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
    return FileResponse(source_path, media_type=media_type, filename=source_path.name)


@app.get("/api/projects/{project_id}/short-video")
def stream_project_short_video(project_id: int) -> FileResponse:
    """Serve only the completed render that belongs to the standalone Short."""
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id, variant="short")
    if not script:
        raise HTTPException(status_code=404, detail="Dự án chưa có kịch bản short riêng")
    for job in database.list_project_jobs(project_id, limit=100):
        if (
            int(job.get("script_id") or 0) == int(script["id"])
            and job.get("job_type") == "render_short"
            and job.get("status") == "completed"
        ):
            path = Path(str(job.get("output_path") or ""))
            if path.is_file():
                return FileResponse(path, media_type="video/mp4")
    raise HTTPException(status_code=404, detail="Short riêng chưa được dựng xong")


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


def _short_direction_from_bundle(bundle: dict[str, Any], direction: str = "") -> str:
    """Keep the standalone Short anchored to the same creative brief."""
    if direction.strip():
        return direction.strip()
    writer = dict(bundle.get("writer_content") or {})
    result = dict(writer.get("result") or writer)
    return str(
        result.get("creative_direction")
        or result.get("new_story_concept")
        or ""
    ).strip()[:4000]


def _create_standalone_short(
    project_id: int,
    bundle: dict[str, Any],
    long_script: dict[str, Any],
    *,
    seconds: int = DEFAULT_SHORT_SCRIPT_SECONDS,
    direction: str = "",
    use_model: bool = True,
) -> dict[str, Any]:
    """Create the Short's script, shots and timeline beside the long video's.

    This is called during script creation, not after the long render. Both
    videos therefore start from the same creative brief while keeping their
    own script IDs and downstream production assets.
    """
    draft = build_short_script(
        bundle["project"],
        long_script,
        seconds=seconds,
        direction=_short_direction_from_bundle(bundle, direction),
        use_model=use_model,
    )
    script = database.create_project_script(project_id, **draft, variant="short")
    if not script:
        raise ShortScriptError("Không lưu được kịch bản short")
    shots = database.create_project_shots(
        project_id,
        int(script["id"]),
        build_shot_plan(bundle["project"], script),
        force=True,
    )
    timeline = database.create_project_timeline(
        project_id,
        int(script["id"]),
        build_timeline(bundle["project"], script, shots or []),
        force=True,
    )
    if shots is None or timeline is None:
        raise ShortScriptError("Không tạo được storyboard hoặc timeline cho bản short")
    _write_project_document(project_id, "kich-ban-short.md", script_to_markdown(script, bundle["project"]))
    return {
        "script": script,
        "shots": shots,
        "timeline": timeline,
        "estimated_seconds": estimated_short_seconds(script),
    }


@app.post("/api/projects/{project_id}/script/draft")
def create_project_script_draft(
    project_id: int,
    payload: ScriptDraftRequest = ScriptDraftRequest(),
) -> dict[str, Any]:
    """Save both scripts at the writing step, before either video is built."""
    bundle = database.get_production_project_bundle(project_id, transcript_text_limit=50_000)
    if not bundle:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    draft = build_script_draft(bundle)
    script = database.create_project_script(project_id, **draft)
    if not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    _write_project_document(project_id, "kich-ban.md", script_to_markdown(script, bundle["project"]))
    short: dict[str, Any] | None = None
    short_error = ""
    if payload.create_standalone_short:
        try:
            short = _create_standalone_short(
                project_id,
                bundle,
                script,
                seconds=payload.short_seconds,
                direction=payload.short_direction,
            )
        except Exception as exc:
            # The long script is still usable if its companion Short cannot be
            # planned. Return the failure explicitly so the UI never claims it
            # was written when it was not.
            short_error = str(exc)
    return {
        "status": "saved",
        "script": script,
        "short": short,
        "short_error": short_error,
    }


class ImportScriptRequest(BaseModel):
    project_id: int | None = Field(default=None, ge=1)
    video_id: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=300)
    text: str = Field(min_length=1, max_length=200_000)
    variant: Literal["long", "short"] = "long"
    language: str = Field(default="vi", max_length=12)
    workflow: Literal["content", "reup"] = "content"


@app.post("/api/scripts/import")
def import_pasted_script(payload: ImportScriptRequest) -> dict[str, Any]:
    """Save pasted narration as a new version, without rewriting it with AI."""
    narration = payload.text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not narration:
        raise HTTPException(status_code=400, detail="Hãy dán nội dung kịch bản trước khi lưu")
    if payload.language not in languages.LANGUAGES:
        raise HTTPException(status_code=400, detail="Ngôn ngữ kịch bản không hợp lệ")
    if payload.project_id:
        project = database.get_production_project(payload.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    elif payload.video_id:
        project = database.create_production_project(payload.video_id, title=payload.title)
        if not project:
            raise HTTPException(status_code=404, detail="Không tìm thấy video nguồn")
        project = database.set_project_workflow(int(project["id"]), payload.workflow) or project
    else:
        project = database.create_idea_project(
            "Kịch bản nhập thủ công", title=payload.title.strip() or "Kịch bản đã dán", language=payload.language,
        )
    project_id = int(project["id"])
    script = database.create_project_script(
        project_id, script_title=payload.title.strip() or str(project.get("title") or "Kịch bản đã dán"),
        hook="", intro="", main_content=narration, cta="", variant=payload.variant,
    )
    if not script:
        raise HTTPException(status_code=500, detail="Không lưu được kịch bản")
    # New rows belong only to this script version; previous audio and visuals
    # remain attached to their original script, never to the pasted words.
    shots = database.create_project_shots(project_id, int(script["id"]), build_shot_plan(project, script)) or []
    timeline = database.create_project_timeline(project_id, int(script["id"]), build_timeline(project, script, shots)) or []
    _write_project_document(project_id, "kich-ban-short.md" if payload.variant == "short" else "kich-ban.md", script_to_markdown(script, project))
    return {"status": "saved", "project": project, "script": script, "shots": shots, "timeline": timeline}


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
            # `creative` is the response that just produced this very script,
            # so its scene list is this script's by construction.
            build_shot_plan(bundle["project"], script, writer_content=creative, blueprints_verified=True),
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
    # Scene blueprints are only valid for the exact writer response that made
    # this script.  Saving/translating a script in place keeps version 1, but
    # its updated timestamp moves past the analysis; reusing blueprints then
    # rebuilt the former (often Vietnamese) storyboard over the new English
    # script.  The saved script is authoritative after that point.
    #
    # That "the script moved past the analysis" test used to compare against
    # the moment the analysis was recorded. Writing a script records the
    # analysis and then the script, milliseconds apart, so a brand new script
    # always looked newer than its own blueprints and they were thrown away
    # every single time - the app asked an AI to break the piece into scenes,
    # discarded the answer, and chopped the prose by line instead. What marks
    # an edit is the script changing after it was created, so that is what is
    # compared now.
    writer_content = None
    blueprints_verified = False
    if writer_analysis:
        script_created = str(script.get("created_at") or "")
        script_updated = str(script.get("updated_at") or "")
        analysed_at = str(writer_analysis.get("created_at") or "")
        untouched_since_written = script_updated <= script_created
        analysis_came_first = analysed_at <= script_created
        if untouched_since_written and analysis_came_first:
            writer_content = writer_analysis.get("result")
    if isinstance(writer_content, dict):
        blueprints = writer_content.get("scene_blueprints")
        if isinstance(blueprints, list):
            script_words = set(re.findall(
                r"\w+",
                " ".join(str(script.get(field) or "") for field in ("hook", "intro", "main_content", "cta")).lower(),
                flags=re.UNICODE,
            ))
            blueprint_words = set(re.findall(
                r"\w+",
                " ".join(str(item.get("narration") or "") for item in blueprints if isinstance(item, dict)).lower(),
                flags=re.UNICODE,
            ))
            overlap = len(script_words & blueprint_words) / min(len(script_words), len(blueprint_words)) if script_words and blueprint_words else 0.0
            if overlap < 0.45:
                # Different-language or manually rewritten blueprints are not
                # a plan for this script.  Rebuild from the visible script.
                writer_content = None
            else:
                blueprints_verified = True
    existing = database.list_project_shots(project_id, script_id=int(script["id"]))
    # Editing a script in place leaves its old storyboard attached to the same
    # script ID.  Reusing it would make the voice job read yesterday's words.
    # Never silently regenerate (it can discard reviewed media); tell callers
    # exactly when they need to explicitly rebuild instead.
    script_updated = str(script.get("updated_at") or "")
    expected = build_shot_plan(
        project, script, writer_content=writer_content, blueprints_verified=blueprints_verified,
    )
    narration_mismatch = len(existing) != len(expected) or any(
        str(shot.get("narration") or "").strip() != str(planned.get("narration") or "").strip()
        for shot, planned in zip(existing, expected)
    )
    storyboard_stale = bool(existing and (
        narration_mismatch
        or (script_updated and script_updated > max(str(item.get("updated_at") or "") for item in existing))
    ))
    if storyboard_stale and not payload.force:
        return {
            "status": "stale",
            "script_id": script["id"],
            "stale": True,
            "shots": existing,
        }
    shots = database.create_project_shots(
        project_id,
        int(script["id"]),
        expected,
        force=payload.force,
    )
    if shots is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án hoặc kịch bản")
    _write_project_document(project_id, "shot-list.md", shots_to_markdown(project, script, shots))
    return {"status": "saved", "script_id": script["id"], "stale": False, "shots": shots}


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
    script = database.get_latest_project_script(project_id, variant=payload.variant)
    if not script:
        raise HTTPException(status_code=400, detail="Project chưa có kịch bản để tạo timeline")
    shots = database.list_project_shots(project_id, script_id=int(script["id"]))
    if not shots:
        raise HTTPException(status_code=400, detail="Project chưa có shot list để tạo timeline")
    previous_timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    previous_count = len(previous_timeline)
    planned = build_timeline(project, script, shots)
    timeline = database.create_project_timeline(
        project_id,
        int(script["id"]),
        planned,
        force=payload.force,
    )
    if timeline is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án hoặc kịch bản")
    document_name = "timeline-short.md" if payload.variant == "short" else "timeline.md"
    _write_project_document(project_id, document_name, timeline_to_markdown(project, script, timeline))
    # Without `force` an existing timeline is returned untouched, so pressing
    # the button after rewriting the script looked like it had worked while
    # the old scenes stayed. Say which happened, and whether the timeline
    # still matches the shot list it should have been built from.
    rebuilt = bool(payload.force) or previous_count == 0
    newest_shot_update = max((str(item.get("updated_at") or "") for item in shots), default="")
    newest_timeline_update = max((str(item.get("updated_at") or "") for item in previous_timeline), default="")
    # SQLite timestamps have second precision, so a script edit, shot update
    # and voice retry in one second can look fresh even when their words are
    # in different languages.  A voice job reads timeline.voice_text, so the
    # actual narration is the only reliable freshness check.
    narration_mismatch = len(previous_timeline) != len(shots) or any(
        str(segment.get("voice_text") or "").strip() != str(shot.get("narration") or "").strip()
        for segment, shot in zip(previous_timeline, shots)
    )
    stale = not rebuilt and (
        narration_mismatch
        or bool(newest_shot_update and newest_timeline_update and newest_shot_update > newest_timeline_update)
    )
    return {
        "status": "saved",
        "script_id": script["id"],
        "variant": payload.variant,
        "rebuilt": rebuilt,
        "stale": stale,
        "shot_count": len(shots),
        "total_duration_seconds": sum(int(item["duration_seconds"]) for item in timeline),
        "timeline": timeline,
    }


@app.get("/api/projects/{project_id}/timeline/{segment_id}/waveform")
def timeline_segment_waveform(project_id: int, segment_id: int) -> Response:
    """A picture of the scene's audio, so silence and clipping are visible.

    Reviewing a voiceover by pressing play on every scene in turn is how a
    dead scene or a truncated line gets missed. The shape of the audio shows
    both at a glance, which is what a review pass actually needs.
    """
    segment = database.get_project_timeline_segment(segment_id)
    if not segment or int(segment.get("project_id") or 0) != project_id:
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh")
    audio = Path(str(segment.get("audio_path") or ""))
    if not audio.is_file():
        raise HTTPException(status_code=404, detail="Cảnh này chưa có giọng đọc")
    executable = resolve_ffmpeg(FFMPEG_BINARY)
    if not executable:
        raise HTTPException(status_code=400, detail=f"Không tìm thấy FFmpeg ({FFMPEG_BINARY})")
    try:
        result = subprocess.run(
            [
                executable, "-v", "error", "-i", str(audio),
                "-filter_complex",
                "aformat=channel_layouts=mono,compand,showwavespic=s=640x80:colors=#f59e0b",
                "-frames:v", "1", "-f", "image2", "-c:v", "png", "-",
            ],
            capture_output=True, timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=500, detail=f"Không vẽ được dạng sóng: {exc}") from exc
    if result.returncode != 0 or not result.stdout:
        raise HTTPException(status_code=500, detail="FFmpeg không vẽ được dạng sóng cho cảnh này")
    return Response(content=result.stdout, media_type="image/png")


class SegmentCutRequest(BaseModel):
    """Where in the source this scene's picture is taken from."""

    # -1 is how the column says "never set"; refusing it made a scene
    # impossible to put back the way it was found.
    source_start_seconds: float | None = Field(default=None, ge=-1, le=86_400)
    edit_trim_head: float | None = Field(default=None, ge=0, le=600)
    edit_trim_tail: float | None = Field(default=None, ge=0, le=600)
    recut: bool = True


@app.patch("/api/timeline/{segment_id}/cut")
def update_timeline_segment_cut(segment_id: int, payload: SegmentCutRequest) -> dict[str, Any]:
    """Move a scene's cut point and, by default, re-cut just that clip.

    Saving the number alone would leave the storyboard showing the old
    picture, so the change could only be judged after a full render - which
    is exactly the review this is meant to make possible beforehand.
    """
    segment = database.get_project_timeline_segment(segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh")
    project_id = int(segment.get("project_id") or 0)
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")

    if payload.source_start_seconds is not None:
        database.save_segment_source_cue(
            segment_id,
            float(payload.source_start_seconds),
            str(segment.get("source_cue_reason") or "Chỉnh tay ở storyboard"),
        )
    if payload.edit_trim_head is not None or payload.edit_trim_tail is not None:
        database.save_segment_edit(
            segment_id,
            str(segment.get("edit_transition") or ""),
            str(segment.get("edit_effect") or ""),
            str(segment.get("edit_note") or ""),
            trim_head_seconds=float(
                payload.edit_trim_head
                if payload.edit_trim_head is not None
                else segment.get("edit_trim_head") or 0
            ),
            trim_tail_seconds=float(
                payload.edit_trim_tail
                if payload.edit_trim_tail is not None
                else segment.get("edit_trim_tail") or 0
            ),
            cleanups=json.loads(str(segment.get("edit_cleanups") or "[]") or "[]"),
        )

    recut_error = ""
    if payload.recut:
        video = database.get_video(str(project.get("youtube_video_id") or "")) or {}
        source_path = Path(str(video.get("local_media_path") or ""))
        if not source_path.is_file():
            recut_error = "Chưa có video nguồn trên máy để cắt lại cảnh này."
        else:
            fresh = database.get_project_timeline_segment(segment_id) or segment
            try:
                prepare_source_visuals(
                    [fresh],
                    source_path,
                    ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["assets"] / "source_clips",
                    description=str(video.get("description") or ""),
                    ffmpeg_binary=FFMPEG_BINARY,
                )
            except SourceVisualError as exc:
                recut_error = str(exc)

    return {
        "status": "saved",
        "segment": database.get_project_timeline_segment(segment_id),
        "recut_error": recut_error,
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

    workflow: str = Field(default=workflows.DEFAULT_KEY, max_length=32)


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
    visual_strategy: str | None = Field(default=None, max_length=80)
    visual_provider: str | None = Field(default=None, max_length=80)
    source_dependency: Literal["none", "low", "medium", "high"] | None = None
    risk_level: Literal["low", "medium", "high"] | None = None
    content_dna: dict[str, Any] | None = None
    transform_actions: list[dict[str, Any]] | None = Field(default=None, max_length=12)
    required_assets: list[dict[str, Any]] | None = Field(default=None, max_length=12)
    overlays: list[dict[str, Any]] | None = Field(default=None, max_length=12)
    sound_cues: list[dict[str, Any]] | None = Field(default=None, max_length=8)
    direction: dict[str, Any] | None = None
    transition: Literal["cut", "fade"] | None = None
    effect: Literal["zoom_in", "zoom_out", "static"] | None = None
    note: str | None = Field(default=None, max_length=400)


class ApplyVisualFallbackRequest(BaseModel):
    confirmed: bool = False


class EditBeatRequest(BaseModel):
    """One visual beat inside a narrated storyboard scene."""

    asset_id: int | None = Field(default=None, ge=1)
    visual_path: str = Field(default="", max_length=1000)
    source_kind: Literal["primary", "source_frame", "asset", "ai_image", "ai_video"] = "primary"
    duration_seconds: float = Field(default=1.0, ge=0.15, le=120.0)
    effect: Literal["zoom_in", "zoom_out", "static"] = "static"
    transition: Literal["cut", "fade"] = "cut"
    prompt: str = Field(default="", max_length=5000)
    status: Literal["ready", "needs_asset", "generating", "error"] = "ready"


class ReplaceEditBeatsRequest(BaseModel):
    beats: list[EditBeatRequest] = Field(default_factory=list, max_length=24)


class PlanEditBeatsRequest(BaseModel):
    max_beats: int = Field(default=4, ge=1, le=8)


class ApplyEditBeatsRequest(BaseModel):
    image_provider: str = Field(default="gemini_web_image", min_length=2, max_length=80)
    ratio: Literal["1280:720", "720:1280", "1024:1024"] = "1280:720"
    confirmed: bool = False


class GenerateEditBeatRequest(BaseModel):
    image_provider: str = Field(default="gemini_web_image", min_length=2, max_length=80)
    ratio: Literal["1280:720", "720:1280", "1024:1024"] = "1280:720"
    confirmed: bool = False


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
    if payload.overlays is not None or payload.sound_cues is not None or payload.direction is not None:
        duration = max(0.1, float(segment.get("duration_seconds") or 1))
        try:
            overlays = normalize_graphic_overlays(payload.overlays, duration) if payload.overlays is not None else None
            sound_cues = _normalise_sound_cues(payload.sound_cues, duration) if payload.sound_cues is not None else None
            direction = normalize_direction(payload.direction, duration) if payload.direction is not None else None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Kế hoạch lớp dựng không hợp lệ: {exc}") from exc
        segment = database.save_segment_edit_layers(
            segment_id,
            overlays=overlays,
            sound_cues=sound_cues,
            direction=direction,
        ) or segment
    return {"status": "saved", "segment": segment}


@app.get("/api/timeline/{segment_id}/edit-beats")
def get_timeline_edit_beats(segment_id: int) -> dict[str, Any]:
    segment = database.get_project_timeline_segment(segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Không tìm thấy segment timeline")
    return {"segment": segment, "beats": database.list_timeline_edit_beats(segment_id)}


@app.put("/api/timeline/{segment_id}/edit-beats")
def replace_timeline_edit_beats(segment_id: int, payload: ReplaceEditBeatsRequest) -> dict[str, Any]:
    segment = database.get_project_timeline_segment(segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Không tìm thấy segment timeline")
    total = sum(float(item.duration_seconds) for item in payload.beats)
    duration = float(segment.get("duration_seconds") or 0)
    if payload.beats and abs(total - duration) > 0.35:
        raise HTTPException(
            status_code=400,
            detail=f"Tổng nhịp dựng ({total:.1f}s) phải khớp lời đọc của cảnh ({duration:.1f}s)",
        )
    beats = database.replace_timeline_edit_beats(
        segment_id, [item.model_dump() for item in payload.beats]
    )
    return {"status": "saved", "beats": beats}


@app.post("/api/timeline/{segment_id}/edit-beats/{beat_index}/extract-frame")
def extract_edit_beat_frame(segment_id: int, beat_index: int) -> dict[str, Any]:
    """Materialise a source-frame insert as a reusable project asset."""
    return _extract_edit_beat_frame(segment_id, beat_index)


def _extract_edit_beat_frame(segment_id: int, beat_index: int) -> dict[str, Any]:
    segment = database.get_project_timeline_segment(segment_id)
    beats = database.list_timeline_edit_beats(segment_id)
    beat = next((item for item in beats if int(item.get("beat_index") or 0) == beat_index), None)
    if not segment or not beat:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhịp dựng")
    source = Path(str(beat.get("visual_path") or segment.get("visual_path") or ""))
    if not source.is_file():
        raise HTTPException(status_code=400, detail="Nhịp này chưa có clip nguồn để trích frame")
    executable = resolve_ffmpeg(FFMPEG_BINARY)
    if not executable:
        raise HTTPException(status_code=400, detail="Không tìm thấy FFmpeg")
    project_id = int(segment["project_id"])
    output_dir = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["assets"] / "edit_frames"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"segment-{segment_id}-beat-{beat_index}.png"
    seek = max(0.0, float(beat.get("start_seconds") or 0) + float(beat.get("duration_seconds") or 1) / 2)
    result = subprocess.run([executable, "-y", "-ss", f"{seek:.3f}", "-i", str(source), "-frames:v", "1", str(output)], capture_output=True, timeout=60, check=False)
    if result.returncode != 0 or not output.is_file():
        raise HTTPException(status_code=500, detail="Không trích được frame từ clip nguồn")
    asset = database.create_project_asset(project_id, "image", output.name, str(output), "image/png", output.stat().st_size)
    attached = database.attach_asset_to_edit_beat(
        int(beat["id"]), int(asset["id"]), source_kind="source_frame"
    )
    if not attached:
        raise HTTPException(status_code=500, detail="Không gắn được frame vào nhịp dựng")
    saved = database.list_timeline_edit_beats(segment_id)
    return {"status": "extracted", "asset": asset, "beats": saved}


@app.get("/api/timeline/{segment_id}/edit-beats/{beat_index}/preview")
def preview_edit_beat(segment_id: int, beat_index: int) -> FileResponse:
    segment = database.get_project_timeline_segment(segment_id)
    beat = next(
        (item for item in database.list_timeline_edit_beats(segment_id)
         if int(item.get("beat_index") or 0) == beat_index),
        None,
    )
    if not segment or not beat:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhịp dựng")
    path = Path(str(beat.get("visual_path") or ""))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Nhịp dựng chưa có media")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name)


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
    if script:
        timeline = database.attach_edit_beats_to_timeline(
            project_id,
            timeline,
            script_id=int(script["id"]),
        )
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
    if script:
        timeline = database.attach_edit_beats_to_timeline(
            project_id,
            timeline,
            script_id=int(script["id"]),
        )
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
# Reference recordings are system material, so they live under the system
# folder rather than beside the user's projects.
_VOICE_LIBRARY_DIR = settings.SYSTEM_ROOT / "tai_lieu"
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
    "de-DE-KatjaNeural", "de-DE-ConradNeural", "de-DE-AmalaNeural", "de-DE-KillianNeural",
    "de-DE-FlorianMultilingualNeural", "de-DE-SeraphinaMultilingualNeural",
    "es-ES-ElviraNeural", "es-ES-AlvaroNeural", "es-ES-XimenaNeural",
}
_EDGE_PREVIEW_RATES = {"-25%", "-15%", "-8%", "+0%", "+8%", "+15%", "+25%"}
_EDGE_PREVIEW_TEXT = "Đây là bản nghe thử giọng đọc. Câu chuyện sẽ được kể rõ ràng, tự nhiên và giàu cảm xúc."
_EDGE_PREVIEW_TEXTS = {
    "de": "Dies ist eine Hörprobe. Die Geschichte wird klar, natürlich und mit Gefühl erzählt.",
    "es": "Esta es una muestra de voz. La historia se contará con claridad, naturalidad y emoción.",
    "en": "This is a voice preview. The story will be told clearly, naturally, and with feeling.",
}


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
        preview_language = voice.split("-")[0]
        text_file.write_text(_EDGE_PREVIEW_TEXTS.get(preview_language, _EDGE_PREVIEW_TEXT), encoding="utf-8")
        values = {
            "text_file": text_file,
            "output_file": output,
            "voice_role": voice,
            "voice_rate": rate,
            "srt_file": text_file.with_suffix(".srt"),
            "output_dir": output.parent,
            "language": preview_language,
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
                errors="replace",
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
    local_media_path, so transcription and analysis work without a download
    step. A video can also be cut into source scenes by the reup workflow;
    an audio-only upload is deliberately kept out of that visual-cut path.
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

    # The same file added twice is one source: the earlier row is returned
    # and the second copy is not kept.
    previous = database.find_local_upload(LOCAL_UPLOAD_CHANNEL_ID, digest.hexdigest())
    if previous:
        target.unlink(missing_ok=True)
        return {
            "status": "duplicate",
            "video": previous,
            "file_size": total,
            "duration_seconds": int(previous.get("duration_seconds") or 0),
            "media_kind": str(database.get_video_raw_payload(str(previous["youtube_video_id"])).get("media_kind") or ""),
            "reused_row": True,
        }

    # A permitted suffix is only a first-pass guard. Probe the bytes before
    # registering a source so renamed or corrupt files cannot create projects
    # which fail later in analysis or rendering.
    duration = media_duration_seconds(target, FFMPEG_BINARY)
    if not duration:
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail="Không đọc được file media hợp lệ. Hãy kiểm tra lại file video/audio.",
        )

    media_kind = "audio" if extension in _ASSET_EXTENSIONS["audio"] else "video"
    # What the bytes hold decides it: a .webm or .mp4 with no picture is sound.
    probed = _source_media_kind(target)
    _ensure_local_upload_channel()
    database.upsert_video({
        "youtube_video_id": video_id,
        "youtube_channel_id": LOCAL_UPLOAD_CHANNEL_ID,
        "video_url": target.as_uri(),
        "title": (title.strip() or Path(filename).stem)[:200],
        "description": f"Tệp tải lên từ máy: {filename}",
        "duration_seconds": int(duration),
        "metadata_hash": digest.hexdigest(),
        "source_kind": source_kinds.AUDIO if "audio" in (media_kind, probed) else source_kinds.VIDEO,
        "raw_payload": {
            "uploaded_filename": filename,
            "file_size": total,
            "media_kind": media_kind,
        },
    })
    # upsert_video does not write local_media_path - the column was added later
    # for downloads - so the file is registered the same way a download is.
    database.mark_video_downloaded(video_id, str(target), probed)
    return {
        "status": "uploaded",
        "video": database.get_video(video_id),
        "file_size": total,
        "duration_seconds": int(duration),
        "media_kind": media_kind,
    }


def _contact_sheet_for_review(images: list[Path], project_id: int) -> Path:
    """Tile several reference images into one, so a model sees them together.

    Showing them one at a time costs a CLI round trip each and, worse, invites
    a description of each picture rather than of what they have in common -
    which is the whole point of handing over a folder.
    """
    if len(images) == 1:
        return _viewable_image(images[0])
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
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False)
    if result.returncode != 0 or not sheet_path.is_file():
        # One picture the model can actually see beats a sheet it cannot.
        return _viewable_image(images[0])
    return sheet_path


_VIEWABLE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def _viewable_image(image: Path) -> Path:
    """The picture in a format every vision reader opens, or as it was.

    Marketplaces serve WebP. Handed one on its own - a listing with a single
    photograph, which is not tiled - the Codex CLI hung until its timeout
    (measured 30/09 on a TikTok Shop listing; the Shopee one, a JPEG, read
    fine). Two or more pictures are tiled into a PNG already.
    """
    if image.suffix.lower() in _VIEWABLE_SUFFIXES:
        return image
    target = image.with_suffix(".jpg")
    try:
        result = subprocess.run(
            [FFMPEG_BINARY, "-y", "-hide_banner", "-loglevel", "error", "-i", str(image), "-frames:v", "1", str(target)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return image
    return target if result.returncode == 0 and target.is_file() and target.stat().st_size else image


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
    # The assignment says "astra"/"claude"; compared against runtime names as
    # it was, the user's choice never matched and was skipped without a word.
    executor = orchestrator_runtime.runtime_id(str(assignment.get("executor") or settings.orchestrator_provider()))
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

    checksum = digest.hexdigest()

    # The same file uploaded twice is the commonest way an assets folder
    # fills up, and the second copy is indistinguishable from the first
    # except by name. Matching on content rather than filename catches it.
    duplicate = next(
        (
            item for item in database.list_project_assets(project_id)
            if str(item.get("sha256") or "") == checksum
            and Path(str(item.get("file_path") or "")).is_file()
        ),
        None,
    )
    if duplicate:
        target.unlink(missing_ok=True)
        return {
            "status": "duplicate",
            "asset": duplicate,
            "detail": f"File này đã có sẵn trong dự án: {duplicate.get('original_name') or ''}",
        }

    # An extension is a promise. A .mp4 that is really an .m4a, or a download
    # that stopped halfway, passes every suffix check and then fails inside a
    # render with an error nobody can act on. Reading the actual streams turns
    # that into one refusal at the point it can still be fixed.
    media: dict[str, Any] = {}
    if asset_type in {"video", "audio", "image"}:
        try:
            media = probe_media(target, FFMPEG_BINARY)
        except MediaProbeError:
            media = {}
        if media:
            reason = reject_reason(media, asset_type)
            if reason:
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail=reason)

    asset = database.create_project_asset(
        project_id,
        asset_type,
        filename,
        str(target),
        mime_type=file.content_type or mimetypes.guess_type(filename)[0] or "",
        file_size=total,
        sha256=checksum,
    )
    if not asset:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return {
        "status": "uploaded",
        "asset": asset,
        "media": media,
        "detail": describe(media) if media else "",
    }


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


def _generate_ai_thumbnails(
    project_id: int,
    project: dict[str, Any],
    script: dict[str, Any] | None,
    payload: "GenerateThumbnailsRequest",
    output_dir: Path,
) -> list[Path]:
    """Draw thumbnails from the project's own story, not from its footage.

    The image providers already in the app are reused rather than reached for
    directly: they take a job with a prompt and return a file, and a thumbnail
    is that with a different brief. Each variant is given a different framing,
    because three renders of one prompt is not a choice.
    """
    reference = (database.get_video_analysis(
        str(project.get("youtube_video_id") or ""), analysis_type="reference"
    ) or {}).get("result", {})
    base = thumbnail_prompt.build(
        script,
        project,
        vertical=payload.video_variant == "short",
        visual_style=str(reference.get("visual_style") or ""),
        direction=payload.prompt.strip(),
    )
    prompts = thumbnail_prompt.variant_prompts(base, payload.variants)
    output_dir.mkdir(parents=True, exist_ok=True)

    made: list[Path] = []
    failures: list[str] = []
    chain = _image_provider_chain(payload.provider)
    drew_with = ""
    for index, text in enumerate(prompts, start=1):
        # Every image provider builds its output filename with int(job["id"]),
        # so a readable string id raised ValueError before a single provider
        # was reached - the drawn thumbnail could not have worked with any
        # model, not only the one out of quota. A negative id converts, keeps
        # each variant's file distinct, and can never match a real job row:
        # ids are positive, so the heartbeat UPDATE stays a no-op.
        job = {
            "id": -random.randrange(1_000_000, 1_000_000_000),
            "project_id": project_id,
            "timeline_segment_id": 0,
            "prompt": text,
            "provider": payload.provider,
            "ratio": "720:1280" if payload.video_variant == "short" else "1280:720",
            "seed": payload.seed,
        }
        # Once one model has drawn, the rest of the set stays with it: three
        # variants from three different models is not a set to choose between.
        produced = None
        used = ""
        for key in ([drew_with] if drew_with else chain):
            job["provider"] = key
            try:
                produced = scene_provider_gateway.execute_scene(
                    key, database, job, PRODUCTION_ARTIFACT_DIR,
                    capability=SCENE_IMAGE,
                )
            except Exception as exc:  # noqa: BLE001 - the next model may still draw
                failures.append(f"{index}/{key}: {str(exc)[:140]}")
                produced = None
                continue
            used = key
            break
        if produced is None:
            continue
        source = Path(str(produced))
        if not source.is_file():
            failures.append(f"{index}/{used}: provider không trả về file")
            continue
        drew_with = used
        target = output_dir / f"ai-thumbnail-{index:02d}{source.suffix or '.png'}"
        shutil.copy2(source, target)
        made.append(target)

    if not made:
        # Naming the state of every provider, not only the one that failed:
        # "generation failed" sends the user back to the same button, while
        # "this key has no image quota, these two are ready" is something to
        # act on. A picture cannot be drawn without a model that will draw it.
        raise SceneGenerationError(
            "Không tạo được thumbnail AI nào.\n"
            + ("Lỗi: " + " · ".join(failures) + "\n" if failures else "")
            + _image_provider_advice(payload.provider)
        )
    return made


def _image_provider_blocked(key: str, *, probe: bool = True) -> str:
    """Why this model cannot draw right now, or "" if it is worth trying.

    Saying "not configured" is not enough to act on. A signed-out Flow is one
    click from working and an empty quota is not, so they are different
    answers even though both come back as a failure to draw.
    """
    try:
        adapter = scene_provider_gateway.get(key)
    except Exception:  # noqa: BLE001 - an unknown key is simply not a candidate
        return "không có trong danh sách provider"
    if not adapter.supports(SCENE_IMAGE):
        return "không vẽ được ảnh"
    if adapter.descriptor.execution_mode == EXECUTION_EXTERNAL_SIDECAR:
        return "cần sidecar/trình duyệt đang chạy"
    if key == "openai_image" and not OPENAI_API_KEY:
        return "chưa có OPENAI_API_KEY"
    if key in {"phantom_canvas_image", "phantom_canvas_video"}:
        result = phantom_canvas_bridge.status()
        return "" if result.get("ready") else str(result.get("detail") or "Phantom Canvas chưa chạy")
    if key in {"gflow_image", "gflow_cli"}:
        # Rendering a list must not wait on a network probe. Unknown is
        # offered rather than hidden: trying it returns the real answer.
        status = gflow_cli_status() if probe else gflow_cached_status()
        if status is None:
            return ""
        if not status.get("installed"):
            return "chưa cài gflow-cli"
        # A sign-in helps only when the session is actually dead. When the
        # probe could not look, asking for one leaves another browser window
        # holding the profile - which is the reason it could not look.
        state = str(status.get("session_state") or "")
        if state == "unverified":
            return "chưa kiểm tra được phiên Flow — đóng cửa sổ Chrome đang mở profile gflow rồi thử lại"
        if not status.get("logged_in"):
            return "gflow-cli chưa đăng nhập — bấm “Đăng nhập Flow” ở tab Tích hợp"
    return ""


def _image_provider_chain(attempted: str) -> list[str]:
    """The models worth trying for one drawn image, best first.

    The provider the user picked comes first, then what its descriptor says
    to fall back to, then anything else that can draw. A thumbnail does not
    care which model made it; being told "no" by one of them is not a reason
    to stop.
    """
    order: list[str] = []

    def offer(key: str) -> None:
        if key and key not in order and not _image_provider_blocked(key):
            order.append(key)

    offer(attempted)
    try:
        declared = scene_provider_gateway.get(attempted).descriptor.fallback_keys
    except Exception:  # noqa: BLE001 - an unknown provider still gets the rest
        declared = ()
    for key in declared:
        offer(key)
    for key in scene_provider_gateway.provider_keys(capability=SCENE_IMAGE):
        offer(key)
    return order


def _image_provider_advice(attempted: str) -> str:
    """What the user can actually switch to, given what is configured here."""
    ready: list[str] = []
    blocked: list[str] = []
    for key in scene_provider_gateway.provider_keys(capability=SCENE_IMAGE):
        reason = _image_provider_blocked(key)
        if reason:
            blocked.append(f"{key} ({reason})")
        elif key == attempted:
            continue
        else:
            ready.append(key)
    parts = []
    if ready:
        parts.append("Có thể thử model khác: " + ", ".join(ready) + ".")
    if blocked:
        parts.append("Chưa dùng được: " + "; ".join(blocked) + ".")
    parts.append(
        "Hoặc dùng “Cắt khung từ video” — app sẽ chọn khung nét và đủ sáng nhất, "
        "nhưng đó là khung phim chứ không phải ảnh bìa được dựng."
    )
    return " ".join(parts)


@app.get("/api/image-providers")
def list_image_providers() -> dict[str, Any]:
    """Every model that can draw, and for the ones that cannot, why not.

    Both thumbnail panels used to carry their own hand-written list: one had
    three entries, the other none at all, and neither matched what the app
    can actually reach. A model missing from a list looks like a model the
    app does not have.
    """
    providers: list[dict[str, Any]] = []
    for key in scene_provider_gateway.provider_keys(capability=SCENE_IMAGE):
        reason = _image_provider_blocked(key, probe=False)
        providers.append({
            "key": key,
            "label": scene_provider_gateway.get(key).descriptor.display_name,
            "ready": not reason,
            "reason": reason,
        })
    # Usable first; within each group the same order every time, so the
    # selection does not move under the pointer between renders.
    providers.sort(key=lambda item: (not item["ready"], item["key"]))
    return {"providers": providers}


@app.post("/api/projects/{project_id}/thumbnails/generate")
def generate_project_thumbnails(
    project_id: int,
    payload: GenerateThumbnailsRequest = GenerateThumbnailsRequest(),
) -> dict[str, Any]:
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id, variant=payload.video_variant)
    if not script:
        raise HTTPException(status_code=400, detail="Chưa có kịch bản cho bản video đã chọn")
    prompt = payload.prompt.strip() or str((script or {}).get("script_title") or project.get("title") or "")
    output_dir = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["assets"] / "thumbnails" / uuid.uuid4().hex[:10]
    if payload.mode == "ai":
        try:
            files = _generate_ai_thumbnails(
                project_id, project, script, payload, output_dir,
            )
        except SceneGenerationError as exc:
            raise _api_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        if payload.video_variant == "short":
            final_path = Path(_short_lane_progress(project_id).get("output_path") or "")
        else:
            final_path = _current_final_video_path(project_id, int(script["id"])) or Path()
        try:
            files = generate_frame_thumbnails(final_path, output_dir, FFMPEG_BINARY, payload.variants,
                vertical=payload.video_variant == "short")
        except ThumbnailGenerationError as exc:
            raise _api_error(exc) from exc
    thumbnails: list[dict[str, Any]] = []
    for index, path in enumerate(files, start=1):
        from .thumbnail_generator import compose_thumbnail
        title_text = payload.title_text.strip()
        if payload.mode == "designed" and not title_text:
            title_text = str(script.get("script_title") or "")[:120]
        path = compose_thumbnail(path, output_dir / f"cover-{index:02d}.jpg",
            vertical=payload.video_variant == "short", title=title_text)
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
            provider=payload.provider if payload.mode == "ai" else "ffmpeg_frame",
            model=payload.provider if payload.mode == "ai" else ("cover_design" if payload.mode == "designed" else "ffmpeg"),
            prompt=prompt,
            seed=(payload.seed + index - 1) if payload.seed is not None else None,
            video_variant=payload.video_variant,
        )
        if thumbnail:
            thumbnails.append(thumbnail)
    return {"status": "generated", "thumbnails": thumbnails}


@app.delete("/api/thumbnails/{thumbnail_id}")
def delete_project_thumbnail(thumbnail_id: int) -> dict[str, Any]:
    """Throw away one thumbnail, and the file it points at."""
    removed = database.delete_project_thumbnail(thumbnail_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Không tìm thấy thumbnail")
    path = Path(str(removed.get("file_path") or ""))
    # Best effort: the row is already gone, and a leftover file is a smaller
    # problem than an endpoint that fails after half the work.
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return {"status": "deleted", "thumbnail_id": thumbnail_id}


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
    # An asset is attached directly to a timeline row.  Recompute the row's
    # combined state now, otherwise a manually restored voice can still look
    # unavailable to storyboard/render checks until some unrelated job runs.
    project_id = int(result["segment"]["project_id"])
    database.resync_timeline_segment_states(project_id)
    result["segment"] = database.get_project_timeline_segment(segment_id)
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
    executor = _orchestrator_runtime_id(executor)
    allowed = [_orchestrator_runtime_id(agent) for agent in allowed]
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


class ProviderNotSupported(LlmError):
    """The runtime a caller named cannot do this kind of task at all."""


def _orchestrator_runtime_id(agent: str) -> str:
    """Map the product-level coordinator choice to the local callable runtime.

    The UI stores the user's intent as Astra / ChatGPT app / Claude; only
    orchestrator_runtime knows which concrete runtime executes each of those.
    """
    return orchestrator_runtime.runtime_id(agent)


def _record_orchestrator_step(**values: Any) -> None:
    """Write one audit row, never at the cost of the call it describes."""
    try:
        database.record_orchestrator_step(**values)
    except Exception:
        pass


def _announce_step(event_type: str, project_id: int, step: str, label: str, **values: Any) -> None:
    """Say out loud that a step started or finished.

    The audit row goes to a table only this app reads. Anything watching from
    outside - the page itself, and later a chat channel relaying a request -
    polls the event log, and step progress was not in it. A run driven from
    elsewhere went silent for the three minutes the planner takes, with no way
    to tell work from a hang.

    The app deliberately knows nothing about who is listening; it only says
    what it is doing.
    """
    try:
        database.emit_domain_event(
            event_type,
            project_id=project_id,
            aggregate_type="project_step",
            aggregate_id=step,
            # Everything a reader needs travels in the payload: the bus takes
            # a fixed set of keyword arguments and rejects anything else, and
            # passing details as loose keywords raised a TypeError that this
            # function's own catch then swallowed - so the announcement went
            # nowhere while the app looked like it was announcing.
            payload={"step": step, "label": label, **values},
        )
    except Exception:
        # Never at the cost of the step it describes.
        pass


def _call_orchestrator_json(
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    *,
    stage: str = "orchestration",
    project_id: int | None = None,
    step: str = "",
    image_path: Path | None = None,
    provider: str = "",
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Route a structured task through the user's per-stage agent policy.

    `provider` names one runtime and overrides the policy: only that runtime
    is tried, because a person or an orchestrator who picked it asked for it.
    `report`, when given, receives which runtime answered - the model's JSON
    does not say, and a result that cannot name its author is unauditable.

    With `image_path` the task is one the model must look at, and only the
    runtimes that accept an image can take it. Falling back to a text-only
    runtime there would not fail - it would answer confidently about a picture
    it never saw, which is worse than having no answer.

    Readiness is measured, not assumed: a runtime that cannot execute right
    now is tried last rather than first, and if nothing runs the error names
    the missing sign-in instead of saying no AI was allowed. Every attempt is
    recorded, because the only way to know an AI really made a decision is to
    be able to read back which one did and what it answered.
    """
    looking = image_path is not None and Path(image_path).is_file()
    calls: dict[str, Any] = (
        {
            "codex_cli": lambda system, user, sch: call_codex_vision_json(
                system, user, sch, image_path=str(image_path),
            ),
            "claude_code_cli": lambda system, user, sch: call_claude_code_cli_json(
                system, user, sch, image_path=str(image_path),
            ),
        }
        if looking
        else {
            "codex_cli": call_codex_json,
            "claude_code_cli": call_claude_code_cli_json,
            "antigravity": call_antigravity_json,
        }
    )
    assignment = settings.agent_assignment(stage)
    executor = _orchestrator_runtime_id(str(assignment.get("executor") or settings.orchestrator_provider()))
    mode = str(assignment.get("mode") or "auto")
    allowed = [
        _orchestrator_runtime_id(str(item))
        for item in assignment.get("allowed_agents", [])
        if _orchestrator_runtime_id(str(item)) in calls
    ]
    fallbacks = [
        _orchestrator_runtime_id(str(item)) for item in assignment.get("fallback_agents", [])
        if _orchestrator_runtime_id(str(item)) in calls and _orchestrator_runtime_id(str(item)) != executor
    ]
    forced = _orchestrator_runtime_id(provider) if provider and provider != "auto" else ""
    if forced:
        if forced not in calls:
            raise ProviderNotSupported(
                f"{provider} không làm được việc này"
                + (" (việc này cần xem ảnh)" if looking else "")
                + f". Chọn một trong: {', '.join(calls)} hoặc auto."
            )
        order = [forced]
    elif mode == "fixed":
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
    if not forced:
        order = list(dict.fromkeys(agent for agent in order if agent in calls and (not allowed or agent in allowed)))
    label = step or stage
    if not order:
        detail = f"Không có AI được phép thực hiện công đoạn {stage}"
        _record_orchestrator_step(
            project_id=project_id, stage=stage, step=label, status="failed",
            why="Chính sách công đoạn không cho phép runtime nào chạy được", error=detail,
        )
        raise LlmError(detail)

    readiness = orchestrator_runtime.runtime_readiness(
        database,
        statuses={
            "codex_cli": codex_cli_status,
            "claude_code_cli": claude_code_cli_status,
            "antigravity": antigravity_cli_status,
        },
    )
    gated = orchestrator_runtime.gate(readiness, order)
    blocked_detail = {str(item["runtime"]): str(item.get("detail") or "") for item in gated["blocked"]}
    # A blocked runtime is still attempted, last: a probe can be wrong in both
    # directions, and refusing to try would turn a stale status into an
    # outage. What changes is the order, and that the reason is on the record.
    attempt_order = [*gated["ready"], *[item["runtime"] for item in gated["blocked"]]]

    attempts: list[dict[str, Any]] = []
    errors: list[str] = []
    first_error: LlmError | None = None
    for agent in attempt_order:
        why = (
            "Được gán làm executor của công đoạn" if agent == executor
            else "Fallback theo chính sách" if agent in fallbacks
            else "Auto: hợp công đoạn và được phép"
        )
        if agent in blocked_detail:
            why += f" (thử cuối vì kiểm tra sẵn sàng báo: {blocked_detail[agent]})"
        try:
            result = calls[agent](system_prompt, user_prompt, schema)
        except (LlmError, CodexBridgeError) as exc:
            first_error = first_error or (exc if isinstance(exc, LlmError) else LlmError(str(exc)))
            errors.append(f"{agent}: {exc}")
            attempts.append({"runtime": agent, "status": "failed", "error": str(exc)[:600]})
            continue
        attempts.append({"runtime": agent, "status": "success", "error": ""})
        if report is not None:
            report.update(runtime=agent, attempts=list(attempts))
        if forced:
            why = "Người gọi chỉ định runtime này (options.provider)"
        _record_orchestrator_step(
            project_id=project_id, stage=stage, step=label, status="success",
            runtime=agent, agent=agent, why=why,
            input_summary=" ".join(user_prompt.split())[:400],
            output_ref=", ".join(sorted(str(key) for key in result)) if isinstance(result, dict) else "",
            attempts=attempts,
        )
        return result

    summary = " | ".join(errors)
    if gated["blocked"]:
        summary += (
            (" | " if summary else "")
            + "Chưa sẵn sàng: "
            + orchestrator_runtime.blocked_summary(gated["blocked"])
        )
    detail = f"Các AI được gán cho công đoạn {stage} đều thất bại. {summary}"
    _record_orchestrator_step(
        project_id=project_id, stage=stage, step=label, status="failed",
        runtime=attempt_order[0] if attempt_order else "",
        why="Đã thử toàn bộ runtime được phép",
        input_summary=" ".join(user_prompt.split())[:400],
        error=detail, attempts=attempts,
    )
    raise LlmError(detail) from first_error


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
    # Typing a prompt into a chat box and pressing send is the same every
    # time, so a model is not asked to work it out. It is asked only when the
    # page shows something this does not recognise - which is also what kept
    # happening when no model was reachable at all: ten runs on ChatGPT web
    # died on "Không có AI được phép thực hiện công đoạn orchestration".
    planned = browser_recipes.next_action(
        goal=payload.goal,
        url=payload.url,
        elements=[element.model_dump() for element in payload.elements],
        history=payload.history,
        step=payload.step,
    )
    if planned is not None:
        return _browser_action_response(planned)

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
    return _browser_action_response(result)


_BROWSER_ACTIONS = {"type", "click", "attach_image", "wait", "reload", "done", "fail"}
_BROWSER_FOLLOW_UP_ACTIONS = {"type", "click", "attach_image", "wait"}


def _browser_action_response(result: dict[str, Any]) -> dict[str, Any]:
    """One shape for the extension, whichever side decided the step.

    `then` used to be dropped here although both the schema and the extension
    carry it, so the batching that exists to save a round trip per step never
    reached the browser at all.
    """
    action = str(result.get("action") or "").strip()
    if action not in _BROWSER_ACTIONS:
        raise HTTPException(status_code=502, detail=f"Orchestrator tra ve hanh dong khong hop le: {action}")
    follow_ups: list[dict[str, Any]] = []
    for item in (result.get("then") or [])[:4]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("action") or "").strip()
        if name not in _BROWSER_FOLLOW_UP_ACTIONS:
            continue
        follow_ups.append({
            "action": name,
            "index": item.get("index"),
            "text": str(item.get("text") or ""),
        })
    return {
        "action": action,
        "index": result.get("index"),
        "text": str(result.get("text") or ""),
        "reason": str(result.get("reason") or ""),
        "then": follow_ups,
        # Which side answered, so a run can be read back without guessing.
        "decided_by": str(result.get("decided_by") or "model"),
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


def _scene_review_pass_score() -> int:
    """The score a generated scene must reach, as set in Automation Policy."""
    try:
        configured = settings.automation_policy().get("min_scene_qc_score", _REVIEW_PASS_SCORE)
        return max(0, min(int(configured), 10))
    except (TypeError, ValueError):
        return _REVIEW_PASS_SCORE


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
                text=True, encoding="utf-8", errors="replace",
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
        # Agent names from the assignment, runtime names below: map at the
        # boundary or the chosen reviewer is silently never first.
        reviewer = str(assignment.get("reviewer") or "auto")
        reviewer = reviewer if reviewer == "auto" else orchestrator_runtime.runtime_id(reviewer)
        executor = orchestrator_runtime.runtime_id(str(assignment.get("executor") or settings.orchestrator_provider()))
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
    minimum = _scene_review_pass_score()
    passed = bool(verdict.get("matches")) and score >= minimum
    note_parts = [str(verdict.get("saw") or "").strip()]
    if verdict.get("issues"):
        note_parts.append(f"Loi: {verdict['issues']}")
    if not passed:
        # The user has to be able to tell a genuinely bad image from one that
        # only fell short of the threshold they themselves raised.
        note_parts.append(f"Diem {score}/10, nguong policy {minimum}/10")
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
_IMAGE_CAPABLE_PROVIDERS = set(scene_provider_gateway.provider_keys(capability=SCENE_IMAGE)) | set(
    scene_provider_gateway.provider_keys(capability=SCENE_ANIMATED_IMAGE)
)
_VIDEO_CAPABLE_PROVIDERS = set(scene_provider_gateway.provider_keys(capability=SCENE_VIDEO))


@app.post("/api/projects/{project_id}/timeline/plan-visuals")
def plan_timeline_visuals(
    project_id: int,
    motion_policy: Literal["balanced", "gif_only"] = "balanced",
) -> dict[str, Any]:
    """Compatibility endpoint backed by the single unified edit plan."""
    unified = plan_project_edit(project_id, motion_policy=motion_policy)
    planned = unified.get("scenes") or []
    counts: dict[str, int] = {}
    for item in planned:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    return {
        **unified,
        "by_kind": counts,
        "total_segments": len(planned),
    }


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
                    "kind": {"type": "string", "enum": ["image", "gif", "video"]},
                    "fps": {"type": "integer"},
                    "reason": {"type": "string"},
                    "content_dna": {
                        "type": "object",
                        "properties": {
                            "core_point": {"type": "string"},
                            "must_keep": {"type": "array", "items": {"type": "string"}},
                            "characters": {"type": "array", "items": {"type": "string"}},
                            "facts": {"type": "array", "items": {"type": "string"}},
                            "emotion": {"type": "string"},
                            "source_cue": {"type": "string"},
                        },
                    },
                    "visual_strategy": {
                        "type": "string",
                        "enum": [
                            "source_clip_short", "source_freeze_frame", "ai_image",
                            "ai_video_from_image", "stock_footage", "motion_graphics",
                            "text_card", "map_chart", "manual_asset", "fallback_draft",
                        ],
                    },
                    "provider": {"type": "string"},
                    "source_dependency": {"type": "string", "enum": ["none", "low", "medium", "high"]},
                    "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
                    "transform_actions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["type", "description"],
                        },
                    },
                    "required_assets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string"},
                                "provider": {"type": "string"},
                                "prompt": {"type": "string"},
                                "reason": {"type": "string"},
                            },
                            "required": ["kind", "prompt"],
                        },
                    },
                    "overlays": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string", "enum": ["title", "callout", "label", "text"]},
                                "text": {"type": "string"},
                                "position": {"type": "string", "enum": ["top_left", "top_center", "top_right", "center"]},
                                "style": {"type": "string", "enum": ["clean", "neon", "card"]},
                                "animation": {"type": "string", "enum": ["fade", "pop", "slide_up"]},
                                "start_seconds": {"type": "number"},
                                "end_seconds": {"type": "number"},
                                "reason": {"type": "string"},
                            },
                            "required": ["kind", "text", "position", "style", "animation", "start_seconds", "end_seconds"],
                        },
                    },
                    "sound_cues": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["whoosh", "pop", "hit", "ambient", "music_duck"]},
                                "start_seconds": {"type": "number"},
                                "end_seconds": {"type": "number"},
                                "intensity": {"type": "string", "enum": ["low", "medium", "high"]},
                                "asset_id": {"type": "integer"},
                                "asset_path": {"type": "string"},
                                "reason": {"type": "string"}
                            },
                            "required": ["type", "start_seconds", "end_seconds"],
                        },
                    },
                    "transition": {"type": "string", "enum": ["cut", "fade"]},
                    "effect": {"type": "string", "enum": ["zoom_in", "zoom_out", "static"]},
                    # Dead air and a redundant lead-in are the commonest reason
                    # a retold clip feels slack, and how much to take off
                    "trim_head_seconds": {"type": "number"},
                    "trim_tail_seconds": {"type": "number"},
                    # Anything on screen that belongs to the source rather than
                    # to this video: its channel logo, its watermark, and its
                    # burned-in subtitles, which are in a language this
                    # audience is not being given.
                    "cleanups": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string", "enum": ["logo", "watermark", "subtitle", "other"]},
                                "position": {
                                    "type": "string",
                                    "enum": [
                                        "top_left", "top_right", "top_center",
                                        "bottom_left", "bottom_right", "bottom_center",
                                        "center", "full",
                                    ],
                                },
                                "method": {"type": "string", "enum": ["blur", "delogo", "crop"]},
                                "note": {"type": "string"},
                            },
                            "required": ["kind", "position", "method"],
                        },
                    },
                    "needs_extra_visual": {"type": "boolean"},
                    "extra_visual_note": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["segment_index", "kind", "transition", "effect"],
            },
        },
    },
    "required": ["scenes"],
}


_EDIT_PLAN_SCHEMA["properties"]["scenes"]["items"]["properties"]["direction"] = DIRECTION_SCHEMA

_SOUND_CUE_TYPES = {"whoosh", "pop", "hit", "ambient", "music_duck"}


def _normalise_sound_cues(raw: Any, duration: float) -> list[dict[str, Any]]:
    from .sound_effects import normalize_sound_cues
    return normalize_sound_cues(raw, duration)


_VISUAL_STRATEGIES = {
    "source_clip_short", "source_freeze_frame", "ai_image", "ai_video_from_image",
    "stock_footage", "motion_graphics", "text_card", "map_chart", "manual_asset",
    "fallback_draft",
}
_SOURCE_DEPENDENCY_LEVELS = {"none", "low", "medium", "high"}
_RISK_LEVELS = {"low", "medium", "high"}


def _workflow_for_edit_plan(project: dict[str, Any], timeline: list[dict[str, Any]]) -> str:
    if any(str(item.get("asset_type") or "") == "source_clip" for item in timeline):
        return "reup"
    key = str(project.get("workflow") or "").strip()
    if key in set(workflows.keys()):
        return key
    return workflows.DEFAULT_KEY


def _plan_list_of_objects(value: Any, limit: int = 12) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value[:limit] if isinstance(item, dict)]


def _normalise_visual_transform_fields(entry: dict[str, Any], segment: dict[str, Any]) -> dict[str, Any]:
    timing = segment.get("_speech_timing") or {}
    duration = max(.15, float(timing.get("duration_seconds") or segment.get("duration_seconds") or 1))
    direction = normalize_direction(entry.get("direction"), duration)
    if direction:
        direction["audio_signature"] = timing.get("audio_signature", "")
        direction["timing_basis"] = timing.get("timing_basis", "estimated")
        if timing.get("warning"):
            direction["warnings"].append(timing["warning"])
        direction = resolve_direction(direction, duration, timing.get("words"))
    asset_type = str(segment.get("asset_type") or "")
    strategy = str(entry.get("visual_strategy") or "").strip()
    if strategy not in _VISUAL_STRATEGIES:
        if asset_type == "source_clip":
            strategy = "source_clip_short"
        else:
            strategy = "ai_video_from_image" if str(entry.get("kind") or "") == "video" else "ai_image"
    dependency = str(entry.get("source_dependency") or "").strip()
    if dependency not in _SOURCE_DEPENDENCY_LEVELS:
        dependency = "medium" if strategy.startswith("source_") else "low"
    risk = str(entry.get("risk_level") or "").strip()
    if risk not in _RISK_LEVELS:
        duration = float(segment.get("duration_seconds") or 0)
        risk = "high" if dependency == "high" or (strategy == "source_clip_short" and duration >= 12) else "low"
    content_dna = entry.get("content_dna") if isinstance(entry.get("content_dna"), dict) else {}
    if not content_dna:
        content_dna = {
            "core_point": str(segment.get("voice_text") or "").strip()[:500],
            "must_keep": [],
            "characters": [],
            "facts": [],
            "emotion": "",
            "source_cue": str(segment.get("visual_prompt") or "").strip()[:300],
        }
    return {
        "content_dna": content_dna,
        "visual_strategy": strategy,
        "provider": str(entry.get("provider") or entry.get("visual_provider") or "").strip()[:80],
        "source_dependency": dependency,
        "risk_level": risk,
        "transform_actions": _plan_list_of_objects(entry.get("transform_actions")),
        "required_assets": _plan_list_of_objects(entry.get("required_assets")),
        "direction": direction,
        "overlays": normalize_graphic_overlays(
            entry.get("overlays") or [], max(0.1, float(segment.get("duration_seconds") or 1))
        ),
        "sound_cues": _normalise_sound_cues(
            entry.get("sound_cues") or [], max(0.1, float(segment.get("duration_seconds") or 1))
        ),
    }


def _edit_plan_input_lines(
    project: dict[str, Any],
    source_video: dict[str, Any],
    source_analysis: dict[str, Any],
    render_settings: dict[str, Any],
    timeline: list[dict[str, Any]],
    workflow_key: str,
) -> list[str]:
    flow = workflows.get(workflow_key)
    if workflow_key == "reup" or any(str(item.get("asset_type") or "") == "source_clip" for item in timeline):
        header = [
            "WORKFLOW: WF Reup - ke lai noi dung nguon bang loi binh moi.",
            "NGUON: cac canh asset_type=source_clip co the cat tu MOT video goc, nhung ke hoach dung "
            "khong duoc mac dinh dung clip goc cho moi canh.",
            f"- Tieu de goc: {str(source_video.get('title') or 'khong ro')[:200]}",
            f"- Hinh anh video goc: {str(source_analysis.get('visual_style') or 'chua mo ta')[:600]}",
            f"- Ngon ngu se xuat ban: {render_settings.get('publish_language') or 'vi'}",
            "- Muc tieu: giu ADN noi dung, nhan vat, su kien, thu tu va cam xuc; tao them visual moi "
            "khi co the de video tong khac dang ke so voi nguon.",
            "",
            "CAC CANH:",
        ]
    else:
        header = [
            f"WORKFLOW: {flow.label} - {flow.summary}",
            "NGUON: canh co the la AI scene, stock, motion graphics, anh/file local hoac asset thu cong; "
            "khong gia dinh moi canh cat tu video goc.",
            f"- Tieu de tham chieu: {str(source_video.get('title') or project.get('title') or 'khong ro')[:200]}",
            f"- Goi y phong cach/tham chieu: {str(source_analysis.get('visual_style') or 'chua mo ta')[:600]}",
            f"- Ngon ngu se xuat ban: {render_settings.get('publish_language') or 'vi'}",
            "- Muc tieu: chon hinh thuc visual phu hop voi tung y - AI image/video, stock footage, "
            "motion graphics, text card hoac asset thu cong.",
            "",
            "CAC CANH:",
        ]
    for segment in timeline:
        header.append(
            f"[{segment.get('segment_index')}] ({segment.get('duration_seconds') or 0}s, "
            f"asset_type: {segment.get('asset_type') or 'chua ro'}, "
            f"loai hinh: {segment.get('visual_kind') or 'chua ro'}) "
            f"Loi thoai: {str(segment.get('voice_text') or '')} || "
            f"Hinh: {str(segment.get('visual_prompt') or '')[:220]}"
        )
        timing = segment.get("_speech_timing") or {}
        header.append(f"TIMING BASIS: {timing.get('timing_basis', 'estimated')}")
        if timing.get("words"):
            header.append("WORD TIMING: " + json.dumps(timing["words"], ensure_ascii=False))
    return header


def _edit_plan_workflow_instructions(workflow_key: str, motion_policy: str) -> str:
    shared = (
        DIRECTOR_INSTRUCTIONS + "\n" +
        "Ban la dao dien hinh anh va nguoi dung phim cho video YouTube. "
        "Tra ve MOT ke hoach thong nhat cho TUNG canh. Chon 'kind': image cho hinh tinh, "
        "gif cho mot chuyen dong lap ngan, video khi chuyen dong la noi dung chinh; kem fps va reason. "
        + (
            "Project nay cam dung video: neu can chuyen dong phai chon gif. "
            if motion_policy == "gif_only" else ""
        )
        + "Sau do quyet dinh cach vao canh va chuyen dong camera:\n"
        "- 'transition': 'cut' hoac 'fade'.\n"
        "- 'effect': 'zoom_in', 'zoom_out', hoac 'static'.\n"
        "- 'note': ly do ngan bang tieng Viet.\n\n"
        "MOI CANH BAT BUOC CO KE HOACH BIEN DOI VISUAL:\n"
        "- 'content_dna': ADN noi dung phai giu gom core_point, must_keep, characters, facts, emotion, source_cue.\n"
        "- 'visual_strategy': mot trong source_clip_short, source_freeze_frame, ai_image, ai_video_from_image, "
        "stock_footage, motion_graphics, text_card, map_chart, manual_asset, fallback_draft.\n"
        "- 'provider': provider goi y cho asset can tao, co the de rong neu chua can.\n"
        "- 'source_dependency': none/low/medium/high.\n"
        "- 'risk_level': low/medium/high.\n"
        "- 'transform_actions': cac thao tac lam video moi khac nguon.\n"
        "- 'required_assets': asset can tao them de apply ke hoach; neu khong can thi mang rong.\n"
        "- 'overlays': toi da 2 lop chu ngan moi canh, chi khi loi binh can nhan manh y/chuyen buoc. "
        "Moi lop co kind title/callout/label/text, text ngan, position top_left/top_center/top_right/center, "
        "style clean/neon/card, animation fade/pop/slide_up, start_seconds/end_seconds theo thoi luong canh, "
        "reason. Dong bo moc xuat hien voi cau doc; de khoang thoang cho mat nguoi va phu de. "
        "Phong cach canh quyet dinh preset, khong lap lai mot kieu cho moi canh. "
        "Khong che noi dung trong chu tu video nguon khi chua xac minh.\n"
        "- 'sound_cues': cue am thanh ngan cho whoosh/pop/hit/ambient/music_duck, chi lap khi can nhan nhip overlay, chuyen y hoac CTA; moi cue co start_seconds/end_seconds, intensity va reason. Neu can file SFX rieng, them required_assets kind=sound_effect.\n\n"
    )
    if workflow_key == "reup":
        return shared + (
            "LUAT RIENG WF REUP:\n"
            "- Giu ADN cau chuyen: nhan vat, su kien, so lieu, thu tu va cam xuc khong duoc bi thay doi.\n"
            "- Khong mac dinh moi canh la source_clip. Chi dung source_clip_short khi can thay khoanh khac that "
            "hoac hanh dong/nhan vat quan trong cua nguon.\n"
            "- Khi loi binh noi ve y niem, nguyen nhan, bai hoc, so sanh, chu thich, hay uu tien motion_graphics, "
            "text_card, stock_footage, source_freeze_frame + overlay, hoac ai_image/ai_video_from_image.\n"
            "- Neu dung source_clip_short tren 10 giay, risk_level thuong la high tru khi co overlay/commentary/cleanup "
            "lam bien doi ro.\n"
            "- Lap required_assets cho moi canh can tao them anh/clip/frame/graphics.\n"
            "- Cleanups chi dua vao bang chung ve video goc; neu co logo/phu de/watermark trong NGUON thi ap dung "
            "cho MOI canh source_clip.\n\n"
            "Ngoai ra tra ve 'pacing' va 'music_mood'."
        )
    return shared + (
        "LUAT RIENG WF CONTENT/WORKFLOW KHONG PHAI REUP:\n"
        "- Khong coi canh la clip nguon neu asset_type khong phai source_clip.\n"
        "- Canh co so lieu/quy trinh/so sanh/khai niem uu tien motion_graphics hoac text_card.\n"
        "- Canh doi song/thuc dia uu tien stock_footage neu khop, neu khong dung ai_image/ai_video_from_image.\n"
        "- Canh minh hoa nhan vat/boi canh tuong tuong uu tien ai_image/ai_video_from_image.\n"
        "- source_dependency thuong la none hoac low.\n\n"
        "Ngoai ra tra ve 'pacing' va 'music_mood'."
    )


def _fallback_scene_transform(segment: dict[str, Any], workflow_key: str, motion_policy: str) -> dict[str, Any]:
    index = int(segment.get("segment_index") or 1)
    duration = float(segment.get("duration_seconds") or 0)
    voice = " ".join(str(segment.get("voice_text") or "").split())
    prompt = str(segment.get("visual_prompt") or "").strip()
    content_dna = {
        "core_point": voice[:500],
        "must_keep": [voice[:160]] if voice else [],
        "characters": [],
        "facts": [],
        "emotion": "",
        "source_cue": prompt[:300],
    }
    if workflow_key == "reup":
        if index % 3 == 1:
            strategy = "source_clip_short"
            kind = "gif" if motion_policy == "gif_only" else "video"
            provider = ""
            dependency = "medium"
            risk = "high" if duration >= 10 else "medium"
            actions = [
                {"type": "shorten_source_clip", "description": "Chỉ dùng khoảnh khắc gốc thật cần thiết."},
                {"type": "add_overlay", "description": "Thêm callout/subtitle mới để làm rõ góc kể lại."},
            ]
            required_assets: list[dict[str, Any]] = [{"kind": "sound_effect", "provider": "manual_sfx", "prompt": "soft whoosh accent for text overlay", "reason": "Nhấn nhịp chữ xuất hiện"}]
            overlays = [{"kind": "callout", "text": voice[:80], "position": "top_center", "style": "card", "animation": "pop", "start_seconds": 0.2, "end_seconds": min(duration, 2.4), "reason": "Thêm lớp bình luận mới"}] if voice else []
        elif index % 3 == 2:
            strategy = "source_freeze_frame"
            kind = "image"
            provider = ""
            dependency = "low"
            risk = "medium"
            actions = [
                {"type": "freeze_frame", "description": "Lấy một frame đại diện thay vì phát lại clip dài."},
                {"type": "pan_zoom", "description": "Tạo chuyển động nhẹ trên frame và thêm overlay."},
            ]
            required_assets = [{"kind": "source_frame", "prompt": prompt or voice[:160], "reason": "Cần frame đại diện từ nguồn"}]
            overlays = [{"kind": "label", "text": (voice or "Điểm chính")[:80], "position": "top_center", "style": "clean", "animation": "slide_up", "start_seconds": 0.3, "end_seconds": min(duration, 2.8), "reason": "Dẫn mắt vào ý chính"}]
        else:
            strategy = "motion_graphics"
            kind = "gif" if motion_policy == "gif_only" else "video"
            provider = "motion_graphics"
            dependency = "none"
            risk = "low"
            actions = [{"type": "replace_with_graphics", "description": "Biến ý chính thành thẻ chữ/biểu đồ động thay cho hình nguồn."}]
            required_assets = [{"kind": "motion_graphics", "provider": "motion_graphics", "prompt": prompt or voice[:220], "reason": "Tạo visual mới giữ ý nhưng không dùng lại khung hình gốc"}]
            overlays = []
    else:
        if index % 3 == 1:
            strategy = "motion_graphics"
            kind = "image"
            provider = "motion_graphics"
            visual_label = "MYTH / FACT"
        elif index % 3 == 2:
            strategy = "text_card"
            kind = "image"
            provider = "motion_graphics"
            visual_label = "ĐIỂM MẤU CHỐT"
        else:
            strategy = "ai_image"
            kind = "image"
            provider = "auto_parallel"
            visual_label = "HÌNH MINH HOẠ"
        dependency = "none"
        risk = "low"
        actions = [
            {"type": "replace_or_cover_source", "description": "Không phát lại nguyên cảnh nguồn; dùng thẻ chữ/graphic/ảnh minh hoạ làm lớp dựng mới."},
            {"type": "add_kinetic_text", "description": "Thêm chữ động ngắn để tạo nhịp và góc kể mới."},
        ]
        required_assets = [{
            "kind": "motion_graphics" if provider == "motion_graphics" else kind,
            "provider": provider,
            "prompt": prompt or voice[:220],
            "reason": "Cần visual khác nguồn để WF Content không trở thành reup.",
        }]
        headline = (voice or prompt or visual_label).strip()[:52]
        overlays = [
            {
                "kind": "title",
                "text": visual_label,
                "position": "top_center",
                "style": "neon" if index % 2 else "card",
                "animation": "pop",
                "start_seconds": 0.15,
                "end_seconds": min(duration, 1.6),
                "reason": "Mở cảnh bằng nhãn đồ họa rõ như Reels/TikTok.",
            },
            {
                "kind": "callout",
                "text": headline,
                "position": "center",
                "style": "card",
                "animation": "slide_up",
                "start_seconds": min(duration, 1.0),
                "end_seconds": min(duration, 3.6),
                "reason": "Nhấn ý chính thay vì chỉ nghe voice.",
            },
        ]
    return {
        "segment_index": index,
        "kind": kind,
        "fps": 12 if kind == "gif" else (24 if kind == "video" else 0),
        "reason": "Kế hoạch dự phòng khi AI lập kế hoạch không phản hồi.",
        "content_dna": content_dna,
        "visual_strategy": strategy,
        "provider": provider,
        "source_dependency": dependency,
        "risk_level": risk,
        "transform_actions": actions,
        "required_assets": required_assets,
        "overlays": overlays,
        "sound_cues": [
            {"type": "whoosh", "start_seconds": 0.15, "end_seconds": min(duration, 0.7), "intensity": "medium", "reason": "Nhấn nhịp chữ mở cảnh"},
            {"type": "pop", "start_seconds": min(duration, 1.0), "end_seconds": min(duration, 1.35), "intensity": "low", "reason": "Nhấn callout chính"},
        ] if overlays else [],
        "transition": "cut" if index % 2 else "fade",
        "effect": ["zoom_in", "zoom_out", "static", "zoom_in"][index % 4],
        "trim_head_seconds": 0,
        "trim_tail_seconds": 0,
        "cleanups": [],
        "needs_extra_visual": bool(required_assets),
        "extra_visual_note": prompt or voice[:220],
        "note": "Fallback deterministic: đủ dữ liệu để sửa tay và tạo asset thiếu.",
    }


def _json_list_field(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [dict(item) for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _storyboard_required_jobs_from_timeline(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Describe the next media work without spending quota or queueing it."""
    jobs: list[dict[str, Any]] = []
    for segment in timeline:
        segment_id = int(segment.get("id") or 0)
        segment_index = int(segment.get("segment_index") or 0)
        visual_path = Path(str(segment.get("visual_path") or ""))
        has_visual = visual_path.is_file()
        strategy = str(segment.get("visual_strategy") or "").strip()
        provider = str(segment.get("visual_provider") or "").strip()
        prompt = str(segment.get("visual_prompt") or segment.get("voice_text") or "").strip()
        required_assets = _json_list_field(segment.get("required_assets"))
        if required_assets:
            for index, asset in enumerate(required_assets, start=1):
                kind = str(asset.get("kind") or "").strip() or "image"
                jobs.append({
                    "segment_id": segment_id,
                    "segment_index": segment_index,
                    "asset_index": index,
                    "job_kind": kind,
                    "provider": str(asset.get("provider") or provider or _default_provider_for_required_kind(kind)).strip(),
                    "prompt": str(asset.get("prompt") or prompt).strip(),
                    "reason": str(asset.get("reason") or segment.get("visual_kind_reason") or "").strip(),
                    "visual_strategy": strategy,
                    "status": "needed",
                    "spends_quota": kind in {"image", "video", "gif"} and str(asset.get("provider") or provider) not in {"", "motion_graphics", "stock_footage"},
                })
            continue
        if not has_visual:
            kind = _job_kind_for_visual_strategy(strategy, str(segment.get("visual_kind") or ""))
            jobs.append({
                "segment_id": segment_id,
                "segment_index": segment_index,
                "asset_index": 1,
                "job_kind": kind,
                "provider": provider or _default_provider_for_required_kind(kind),
                "prompt": prompt,
                "reason": "Cảnh chưa có visual sau khi áp dụng kế hoạch.",
                "visual_strategy": strategy or "fallback_draft",
                "status": "needed",
                "spends_quota": kind in {"image", "video", "gif"} and (provider or _default_provider_for_required_kind(kind)) not in {"motion_graphics", "stock_footage"},
            })
    return jobs


def _job_kind_for_visual_strategy(strategy: str, visual_kind: str) -> str:
    if strategy == "source_freeze_frame":
        return "source_frame"
    if strategy == "source_clip_short":
        return "source_visuals"
    if strategy == "motion_graphics":
        return "motion_graphics"
    if strategy == "stock_footage":
        return "stock_footage"
    if strategy == "fallback_draft":
        return "fallback"
    if strategy == "ai_video_from_image":
        return "video"
    return visual_kind if visual_kind in {"image", "gif", "video"} else "image"


def _default_provider_for_required_kind(kind: str) -> str:
    if kind in {"source_frame", "source_visuals"}:
        return "ffmpeg_builtin"
    if kind == "motion_graphics":
        return "motion_graphics"
    if kind == "stock_footage":
        return "stock_footage"
    if kind == "sound_effect":
        return "manual_sfx"
    if kind == "video":
        return "gflow_cli"
    if kind == "fallback":
        return "ffmpeg_builtin"
    return "auto_parallel"


def _scene_plan_effect_sequence(effect: str) -> list[str]:
    base = str(effect or "static").strip()
    if base == "zoom_in":
        return ["zoom_in", "static", "zoom_out", "zoom_in"]
    if base == "zoom_out":
        return ["zoom_out", "static", "zoom_in", "zoom_out"]
    return ["static", "zoom_in", "zoom_out", "static"]


def _scene_plan_to_edit_beats(segment: dict[str, Any], scene: dict[str, Any]) -> list[dict[str, Any]]:
    """Compile semantic beats only. No duration-based cuts or forced zooms."""
    visual_path = str(segment.get("visual_path") or "").strip()
    direction = scene.get("direction") or {}
    beats = []
    for beat in direction.get("visual_beats") or []:
        asset_id = int(beat.get("asset_id") or 0)
        path = visual_path
        if beat["source_kind"] == "asset":
            asset = database.get_project_asset(asset_id)
            if not asset or int(asset["project_id"]) != int(segment["project_id"]):
                raise ValueError(f"Asset {asset_id} không thuộc dự án của cảnh")
            path = str(asset.get("file_path") or "")
            if not Path(path).is_file():
                raise ValueError(f"Asset {asset_id} chưa có file để dựng")
        beats.append({"source_kind": beat["source_kind"], "asset_id": asset_id or None,
                      "visual_path": path, "start_seconds": beat["start_seconds"],
                      "duration_seconds": beat["end_seconds"] - beat["start_seconds"],
                      "effect": beat["effect"], "transition": "cut", "prompt": beat["reason"],
                      "status": "ready" if path else "needs_asset"})
    return beats


def _edit_plan_source_revision(
    script: dict[str, Any],
    timeline: list[dict[str, Any]],
) -> str:
    """Fingerprint only inputs whose change can make an edit proposal wrong."""
    source = {
        "script": {
            "id": script.get("id"),
            "updated_at": script.get("updated_at"),
            "title": script.get("script_title"),
            "hook": script.get("hook"),
            "intro": script.get("intro"),
            "main_content": script.get("main_content"),
            "cta": script.get("cta"),
        },
        "timeline": [
            {
                "id": item.get("id"),
                "shot_id": item.get("shot_id"),
                "segment_index": item.get("segment_index"),
                "voice_text": item.get("voice_text"),
                "visual_prompt": item.get("visual_prompt"),
                "asset_type": item.get("asset_type"),
                "duration_seconds": item.get("duration_seconds"),
                "visual_kind": item.get("visual_kind"),
                "content_dna": item.get("content_dna"),
                "visual_strategy": item.get("visual_strategy"),
                "visual_provider": item.get("visual_provider"),
                "source_dependency": item.get("source_dependency"),
                "risk_level": item.get("risk_level"),
                "transform_actions": item.get("transform_actions"),
                "required_assets": item.get("required_assets"),
                "overlays": item.get("overlays"),
            "sound_cues": item.get("sound_cues"),
            "edit_direction": item.get("edit_direction"),
                "scene_direction": item.get("scene_direction"),
                "audio_path": item.get("audio_path"),
                "audio_signature": audio_signature(Path(item["audio_path"]))
                if item.get("audio_path") and Path(item["audio_path"]).is_file() else "",
                "visual_path": item.get("visual_path"),
                "edit_transition": item.get("edit_transition"),
                "edit_effect": item.get("edit_effect"),
                "edit_trim_head": item.get("edit_trim_head"),
                "edit_trim_tail": item.get("edit_trim_tail"),
                "edit_cleanups": item.get("edit_cleanups"),
            }
            for item in timeline
        ],
    }
    payload = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _current_project_edit_plan(project_id: int) -> dict[str, Any] | None:
    script = database.get_latest_project_script(project_id)
    if not script:
        return None
    plan = database.get_project_edit_plan(project_id, int(script["id"]))
    if not plan:
        return None
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    current_revision = _edit_plan_source_revision(script, timeline)
    if (
        plan.get("source_revision") != current_revision
        and plan.get("status") in {"draft", "approved", "ready"}
    ):
        plan = database.set_project_edit_plan_status(int(plan["id"]), "stale") or plan
    plan["current_source_revision"] = current_revision
    plan["stale"] = plan.get("status") == "stale"
    return plan


@app.get("/api/projects/{project_id}/edit-plan")
def get_project_edit_plan(project_id: int) -> dict[str, Any]:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    plan = _current_project_edit_plan(project_id)
    return {"status": "missing", "plan": None} if not plan else {"status": plan["status"], "plan": plan}


# A scene shorter than this is allowed to simply sit there; past it, a still
# frame with nothing happening reads as a slideshow rather than an edit.
FLAT_SCENE_SECONDS = 10.0


def plan_is_flat(scenes: list[dict[str, Any]], timeline: list[dict[str, Any]]) -> bool:
    """True when a plan asks for no movement and no graphics anywhere.

    The planner has everything it needs - the picture's description, the kind
    of scene, word timing measured from the voice - and still returns a plan
    of nothing but static frames on some runs, while producing a fully worked
    one on others. That is the model varying, not data going missing, and the
    app's job is to not accept the empty answer in silence.
    """
    durations = {
        int(segment.get("segment_index") or 0): float(segment.get("duration_seconds") or 0)
        for segment in timeline
    }
    long_enough = False
    for entry in scenes:
        if not isinstance(entry, dict):
            continue
        if durations.get(int(entry.get("segment_index") or -1), 0.0) >= FLAT_SCENE_SECONDS:
            long_enough = True
        if str(entry.get("effect") or "").strip() not in {"", "static"}:
            return False
        if entry.get("overlays") or entry.get("transform_actions"):
            return False
    return long_enough


_ASK_FOR_AN_EDIT = (
    "\n\nLUU Y: ban ke hoach truoc do khong co bat ky chuyen dong hay do hoa nao - "
    "moi canh deu la khung hinh tinh. Day la mot video giai thich, khong phai trinh chieu anh. "
    "Voi moi canh tu 10 giay tro len, hay chon mot chuyen dong may (effect) phu hop voi y cua canh, "
    "va dat it nhat mot moc do hoa bam theo word timing da do. Neu mot canh that su nen dung yen, "
    "hay noi ro ly do trong truong 'reason'."
)


@app.post("/api/projects/{project_id}/edit-plan")
def plan_project_edit(
    project_id: int,
    motion_policy: Literal["balanced", "gif_only"] = "balanced",
) -> dict[str, Any]:
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
    project = database.get_production_project(project_id) or {}

    # What is on screen is a fact about the source video, not about any one
    # scene: every clip here is cut from the same film, so a channel logo or a
    # burned-in subtitle is on all of them or none. Without this the planner
    # was being asked what a scene looks like while holding only its dialogue
    # and the words "cut from the source at 9s" - so it correctly answered that
    # it had no evidence of any mark, and nothing was ever cleaned.
    source_video = database.get_video(str(project.get("youtube_video_id") or "")) or {}
    source_analysis = (database.get_video_analysis(
        str(project.get("youtube_video_id") or ""), analysis_type="reference"
    ) or {}).get("result", {})
    render_settings = database.get_project_render_settings(project_id) or {}
    workflow_key = _workflow_for_edit_plan(project, timeline)
    # The model receives the whole spoken content and actual voice timing.
    # These enriched rows are not written to the live timeline until Apply.
    timeline = [{**segment, "_speech_timing": scene_speech_timing(segment)} for segment in timeline]
    for segment in timeline:
        segment["duration_seconds"] = segment["_speech_timing"]["duration_seconds"]
    lines = _edit_plan_input_lines(
        project, source_video, source_analysis, render_settings, timeline, workflow_key
    )
    available_assets = database.list_project_assets(project_id)
    lines.append("ASSETS CO SAN: " + json.dumps([
        {"asset_id": item["id"], "name": Path(str(item.get("file_path") or "")).name,
         "kind": item.get("asset_type", "")}
        for item in available_assets if Path(str(item.get("file_path") or "")).is_file()
    ], ensure_ascii=False))
    system_prompt = _edit_plan_workflow_instructions(workflow_key, motion_policy)
    try:
        result = _call_orchestrator_json(
            system_prompt, "\n".join(lines), _EDIT_PLAN_SCHEMA,
            stage="storyboard", project_id=project_id, step="Kế hoạch dựng (AI Đạo diễn)",
        )
        planner_error = ""
        # Which side made this plan is the difference between an AI-directed
        # edit and a template, and only this function can still tell them
        # apart - by the time it is saved, both are the same shape.
        planned_by = "ai"
        if plan_is_flat(result.get("scenes") or [], timeline):
            # Asked once more, saying plainly what was missing. One retry, not
            # a loop: this call costs minutes, and a planner that answers flat
            # twice is answering, not failing.
            retried = _call_orchestrator_json(
                system_prompt, "\n".join(lines) + _ASK_FOR_AN_EDIT, _EDIT_PLAN_SCHEMA,
                stage="storyboard", project_id=project_id,
                step="Kế hoạch dựng (hỏi lại vì không có nhịp)",
            )
            if not plan_is_flat(retried.get("scenes") or [], timeline):
                result = retried
    except LlmError as exc:
        result = {
            "pacing": "fallback",
            "music_mood": "",
            "scenes": [
                _fallback_scene_transform(segment, workflow_key, motion_policy)
                for segment in timeline
            ],
        }
        planner_error = str(exc)
        planned_by = "fallback"

    # The planner is asked about the source's own marks, but it is asked in
    # words - it holds the scene's dialogue and a sentence of style, never a
    # frame. It answers, correctly, that it has seen no logo and no burned-in
    # subtitle, which is why running the plan never cleaned anything. So the
    # picture is measured instead, and what is measured outranks what was
    # guessed: measurement also gives the rectangle, which a guess cannot.
    measured: list[dict[str, Any]] = []
    source_media = Path(str((source_video or {}).get("local_media_path") or ""))
    if source_media.is_file():
        try:
            measured = detect_burned_in_marks(source_media, ffmpeg_binary=FFMPEG_BINARY)
        except (MarkDetectionError, OSError, ValueError):
            measured = []

    by_index = {int(segment.get("segment_index") or 0): segment for segment in timeline}
    planned: list[dict[str, Any]] = []
    for entry in result.get("scenes") or []:
        segment = by_index.get(int(entry.get("segment_index") or -1))
        if not segment:
            continue
        if (
            (workflow_key == "reup" or str(segment.get("asset_type") or "") == "source_clip")
            and str(entry.get("visual_strategy") or "").strip() not in _VISUAL_STRATEGIES
        ):
            fallback = _fallback_scene_transform(segment, workflow_key, motion_policy)
            entry = {**fallback, **entry}
        transition = str(entry.get("transition") or "fade")
        effect = str(entry.get("effect") or "zoom_in")
        kind = str(entry.get("kind") or "image")
        if motion_policy == "gif_only" and kind == "video":
            kind = "gif"
        fps = int(entry.get("fps") or 0) if kind in {"gif", "video"} else 0
        uses_source_visual = str(entry.get("visual_strategy") or "").strip() in {"source_clip_short", "source_freeze_frame"}
        cleanups = (measured if (workflow_key == "reup" or uses_source_visual) else []) or [
            item for item in (entry.get("cleanups") or []) if isinstance(item, dict)
        ]
        needs_visual = bool(entry.get("needs_extra_visual"))
        extra_note = str(entry.get("extra_visual_note") or "").strip()
        try:
            transform = _normalise_visual_transform_fields(entry, segment)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Kế hoạch đồ họa cảnh {segment['segment_index']} không hợp lệ: {exc}",
            ) from exc
        planned.append({
            "segment_id": segment["id"],
            "shot_id": segment.get("shot_id"),
            "segment_index": segment["segment_index"],
            "kind": kind,
            "fps": max(0, min(fps, 60)),
            "reason": str(entry.get("reason") or ""),
            **transform,
            "transition": transition,
            "effect": effect,
            "note": str(entry.get("note") or ""),
            "trim_head_seconds": float(entry.get("trim_head_seconds") or 0),
            "trim_tail_seconds": float(entry.get("trim_tail_seconds") or 0),
            "cleanups": cleanups,
            "needs_extra_visual": needs_visual,
            "extra_visual_note": extra_note,
        })
    proposal = {
        "motion_policy": motion_policy,
        "workflow": workflow_key,
        "pacing": str(result.get("pacing") or ""),
        "music_mood": str(result.get("music_mood") or ""),
        "planner_error": planner_error,
        "planned_by": planned_by,
        "is_fallback": planned_by == "fallback",
        "scenes": planned,
    }
    if planned_by == "fallback":
        _record_orchestrator_step(
            project_id=project_id, stage="storyboard", step="Kế hoạch dựng (bản dự phòng)",
            status="fallback", runtime="app_template", fallback_used=True,
            why="AI lập kế hoạch thất bại nên app dùng mẫu dựng sẵn",
            output_ref=f"{len(planned)} cảnh theo mẫu", error=planner_error,
        )
    saved = database.save_project_edit_plan(
        project_id,
        int(script["id"]),
        _edit_plan_source_revision(script, database.list_project_timeline(project_id, script_id=int(script["id"]))),
        proposal,
        status="draft",
    )
    return {
        **proposal,
        "id": saved["id"] if saved else None,
        "status": "draft",
        "source_revision": saved["source_revision"] if saved else "",
        "stale": False,
    }


@app.post("/api/projects/{project_id}/edit-plan/approve")
def approve_project_edit_plan(project_id: int) -> dict[str, Any]:
    plan = _current_project_edit_plan(project_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Chưa có kế hoạch dựng để duyệt")
    if plan.get("status") == "stale":
        raise HTTPException(status_code=409, detail="Kế hoạch đã lỗi thời; hãy lập lại trước khi duyệt")
    if plan.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Chỉ có thể duyệt kế hoạch đang ở trạng thái bản nháp")
    timeline = database.list_project_timeline(project_id, script_id=int(plan["script_id"]))
    durations = {int(item["id"]): max(0.1, float(item.get("duration_seconds") or 1)) for item in timeline}
    for scene in (plan.get("plan") or {}).get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        duration = durations.get(int(scene.get("segment_id") or 0))
        if duration is None:
            continue
        try:
            normalize_graphic_overlays(scene.get("overlays") or [], duration)
            direction = scene.get("direction") or {}
            normalize_direction(direction, float(direction.get("duration_seconds") or duration))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Overlay cảnh {scene.get('segment_index')} không hợp lệ: {exc}") from exc
    approved = database.set_project_edit_plan_status(int(plan["id"]), "approved")
    return {"status": "approved", "plan": approved}


@app.patch("/api/projects/{project_id}/edit-plan/scenes/{segment_id}")
def update_project_edit_plan_scene(
    project_id: int,
    segment_id: int,
    payload: UpdateScenePlanRequest,
) -> dict[str, Any]:
    plan = _current_project_edit_plan(project_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Chưa có kế hoạch dựng")
    if plan.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Chỉ sửa được kế hoạch đang ở trạng thái bản nháp")
    proposal = dict(plan.get("plan") or {})
    scenes = [dict(item) for item in (proposal.get("scenes") or []) if isinstance(item, dict)]
    scene = next((item for item in scenes if int(item.get("segment_id") or 0) == segment_id), None)
    if not scene:
        raise HTTPException(status_code=404, detail="Cảnh không nằm trong kế hoạch dựng")
    changes = payload.model_dump(exclude_none=True)
    if "overlays" in changes or "direction" in changes or "sound_cues" in changes:
        timeline = database.list_project_timeline(project_id, script_id=int(plan["script_id"]))
        segment = next((item for item in timeline if int(item["id"]) == segment_id), None)
        if not segment:
            raise HTTPException(status_code=404, detail="Không tìm thấy cảnh trong timeline")
        duration = max(0.1, float(segment.get("duration_seconds") or 1))
        try:
            if "overlays" in changes:
                changes["overlays"] = normalize_graphic_overlays(changes["overlays"], duration)
            if "direction" in changes:
                measured = scene.get("direction", {}).get("duration_seconds") or duration
                changes["direction"] = normalize_direction(changes["direction"], measured)
            if "sound_cues" in changes:
                changes["sound_cues"] = _normalise_sound_cues(changes["sound_cues"], duration)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Overlay không hợp lệ: {exc}") from exc
    if "visual_kind" in changes:
        scene["kind"] = changes.pop("visual_kind")
    if "visual_fps" in changes:
        scene["fps"] = changes.pop("visual_fps")
    if "visual_provider" in changes:
        scene["provider"] = changes.pop("visual_provider")
    scene.update(changes)
    proposal["scenes"] = scenes
    saved = database.save_project_edit_plan(
        project_id,
        int(plan["script_id"]),
        str(plan["source_revision"]),
        proposal,
        status="draft",
    )
    return {"status": "draft", "plan": saved}


@app.post("/api/projects/{project_id}/edit-plan/apply")
def apply_project_edit_plan(project_id: int) -> dict[str, Any]:
    plan = _current_project_edit_plan(project_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Chưa có kế hoạch dựng để áp dụng")
    if plan.get("status") == "stale":
        raise HTTPException(status_code=409, detail="Kế hoạch đã lỗi thời; hãy lập lại trước khi áp dụng")
    if plan.get("status") != "approved":
        raise HTTPException(status_code=409, detail="Kế hoạch phải được duyệt trước khi áp dụng")

    script = database.get_project_script(int(plan["script_id"]))
    if not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy kịch bản của kế hoạch")
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    try:
        scenes = [item for item in (plan.get("plan") or {}).get("scenes") or [] if isinstance(item, dict)]
        segments_by_id = {int(item["id"]): item for item in timeline}
        for scene in scenes:
            segment = segments_by_id[int(scene["segment_id"])]
            direction = scene.get("direction") or {}
            scene["direction"] = normalize_direction(direction, float(direction.get("duration_seconds") or segment["duration_seconds"]))
            from .sound_effects import resolve_sound_assets
            try:
                scene["sound_cues"] = resolve_sound_assets(
                    database, project_id, scene.get("sound_cues") or [], float(segment["duration_seconds"]),
                    ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["audio"] / "sfx")
            except ValueError as exc:
                # A cue the library cannot supply - the planner is free to ask
                # for an ambient bed nobody has imported - used to take the
                # whole apply down with it, losing the transitions, camera
                # moves and overlays that were perfectly usable. The cut is
                # worth more than the sound it could not find.
                scene["sound_cues"] = []
                scene["sound_cue_warning"] = str(exc)[:300]
            scene["compiled_beats"] = _scene_plan_to_edit_beats(segment, scene)
        database.set_project_edit_plan_status(int(plan["id"]), "applying")
        applied = database.apply_project_edit_plan_scenes(
            project_id,
            int(script["id"]),
            scenes,
        )
    except Exception as exc:
        database.set_project_edit_plan_status(int(plan["id"]), "error", error=str(exc))
        raise

    refreshed_timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    edit_beats_created = sum(len(scene["compiled_beats"]) for scene in scenes)
    refreshed_timeline = database.attach_edit_beats_to_timeline(
        project_id, refreshed_timeline, script_id=int(script["id"])
    )
    ready = database.set_project_edit_plan_status(
        int(plan["id"]),
        "ready",
        source_revision=_edit_plan_source_revision(script, refreshed_timeline),
    )
    required_jobs = _storyboard_required_jobs_from_timeline(refreshed_timeline)
    return {
        "status": "ready",
        "applied_scenes": applied,
        "edit_beats_created": edit_beats_created,
        "plan": ready,
        "required_jobs": required_jobs,
        "required_jobs_count": len(required_jobs),
    }


def _render_readiness(project_id: int) -> dict[str, Any]:
    """Report only facts that determine whether the current timeline renders.

    This deliberately has no dependency on the retired edit-plan workflow:
    readiness is derived from the files actually attached to each scene.
    """
    project = database.get_production_project(project_id)
    script = database.get_latest_project_script(project_id)
    if not project or not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án hoặc kịch bản")
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    scenes: list[dict[str, Any]] = []
    for segment in timeline:
        visual_path = Path(str(segment.get("visual_path") or ""))
        audio_path = Path(str(segment.get("audio_path") or ""))
        has_visual = visual_path.is_file()
        has_audio = audio_path.is_file()
        is_fallback = str(segment.get("asset_type") or "") == "fallback"
        is_draft = "director_draft_visuals" in str(visual_path).replace("\\", "/").lower()
        scenes.append({
            "segment_id": segment["id"],
            "segment_index": segment["segment_index"],
            "has_visual": has_visual,
            "has_audio": has_audio,
            "fallback": is_fallback,
            "draft_visual": is_draft,
            "ready": has_visual and has_audio and not is_draft,
        })
    missing_visual = sum(not item["has_visual"] for item in scenes)
    missing_audio = sum(not item["has_audio"] for item in scenes)
    draft_visual = sum(item["draft_visual"] for item in scenes)
    fallback = sum(item["fallback"] for item in scenes)
    creative_scenes = []
    for segment in timeline:
        overlays = _json_list_field(segment.get("overlays"))
        sound_cues = _json_list_field(segment.get("sound_cues"))
        effect = str(segment.get("edit_effect") or "").strip()
        transition = str(segment.get("edit_transition") or "").strip()
        required_assets = _json_list_field(segment.get("required_assets"))
        visual_strategy = str(segment.get("visual_strategy") or "").strip()
        has_creative_layers = bool(overlays or sound_cues or effect or transition or required_assets or visual_strategy)
        creative_scenes.append({
            "segment_id": segment["id"],
            "segment_index": segment["segment_index"],
            "overlays": len(overlays),
            "sound_cues": len(sound_cues),
            "effect": effect,
            "transition": transition,
            "visual_strategy": visual_strategy,
            "required_assets": len(required_assets),
            "creative_ready": has_creative_layers,
        })
    creative_ready_count = sum(item["creative_ready"] for item in creative_scenes)
    missing_creative = len(creative_scenes) - creative_ready_count
    issues = []
    if missing_visual:
        issues.append(f"{missing_visual} cảnh thiếu hình")
    if missing_audio:
        issues.append(f"{missing_audio} cảnh thiếu tiếng")
    if draft_visual:
        issues.append(f"{draft_visual} cảnh còn dùng visual nháp")
    creative_issues = []
    if missing_creative:
        creative_issues.append(f"{missing_creative} cảnh chưa có kế hoạch dựng sáng tạo")
    return {
        "status": "ready" if not issues else "needs_attention",
        "total": len(scenes),
        "ready": sum(item["ready"] for item in scenes),
        "missing_visual": missing_visual,
        "missing_audio": missing_audio,
        "draft_visual": draft_visual,
        "fallback": fallback,
        "can_render": bool(scenes) and not missing_visual and not missing_audio and not draft_visual,
        "creative_status": "ready" if creative_scenes and not missing_creative else "needs_edit_plan",
        "creative_ready": bool(creative_scenes) and not missing_creative,
        "creative_ready_count": creative_ready_count,
        "missing_creative": missing_creative,
        "creative_issues": creative_issues,
        "issues": issues,
        "required_jobs": _storyboard_required_jobs_from_timeline(timeline),
        "scenes": scenes,
        "creative_scenes": creative_scenes,
    }


def _edit_preflight(project_id: int) -> dict[str, Any]:
    """Compatibility alias for integrations using the former function name."""
    return _render_readiness(project_id)


@app.get("/api/projects/{project_id}/render-readiness")
def get_project_render_readiness(project_id: int) -> dict[str, Any]:
    return _render_readiness(project_id)


@app.get("/api/projects/{project_id}/edit-plan/preflight")
def get_project_edit_preflight(project_id: int) -> dict[str, Any]:
    """Backward-compatible route; the active app uses render-readiness."""
    return _render_readiness(project_id)


@app.get("/api/projects/{project_id}/storyboard/required-jobs")
def list_project_storyboard_required_jobs(project_id: int) -> dict[str, Any]:
    project = database.get_production_project(project_id)
    script = database.get_latest_project_script(project_id)
    if not project or not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án hoặc kịch bản")
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    jobs = _storyboard_required_jobs_from_timeline(timeline)
    return {"status": "ok", "total": len(jobs), "required_jobs": jobs}


@app.post("/api/projects/{project_id}/edit-plan/fallback")
def apply_project_visual_fallbacks(
    project_id: int,
    payload: ApplyVisualFallbackRequest,
) -> dict[str, Any]:
    if not payload.confirmed:
        raise HTTPException(status_code=400, detail="Cần confirmed=true để tạo hình dự phòng")
    if not ffmpeg_available(FFMPEG_BINARY):
        raise HTTPException(status_code=400, detail="Không tìm thấy FFmpeg để tạo hình dự phòng")
    script = database.get_latest_project_script(project_id)
    if not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy kịch bản")
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    missing = [item for item in timeline if not Path(str(item.get("visual_path") or "")).is_file()]
    if not missing:
        return {"status": "unchanged", "applied": 0, "preflight": _edit_preflight(project_id)}
    output = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["assets"] / "fallback-background.png"
    if not output.is_file():
        result = subprocess.run(
            [
                FFMPEG_BINARY, "-y", "-f", "lavfi", "-i",
                "color=c=0x111827:s=1280x720", "-frames:v", "1", str(output),
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0 or not output.is_file():
            raise HTTPException(status_code=500, detail="Không tạo được hình dự phòng bằng FFmpeg")
    for segment in missing:
        database.update_project_timeline_segment(
            int(segment["id"]),
            visual_path=str(output),
            asset_type="fallback",
        )
    plan = database.get_project_edit_plan(project_id, int(script["id"]))
    if plan and plan.get("status") == "ready":
        refreshed = database.list_project_timeline(project_id, script_id=int(script["id"]))
        database.set_project_edit_plan_status(
            int(plan["id"]),
            "ready",
            source_revision=_edit_plan_source_revision(script, refreshed),
        )
    return {"status": "applied", "applied": len(missing), "preflight": _edit_preflight(project_id)}


@app.post("/api/projects/{project_id}/timeline/{segment_id}/edit-preview")
def render_timeline_segment_preview(project_id: int, segment_id: int) -> FileResponse:
    segment = database.get_project_timeline_segment(segment_id)
    if not segment or int(segment.get("project_id") or 0) != project_id:
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh")
    if not Path(str(segment.get("visual_path") or "")).is_file():
        raise HTTPException(status_code=400, detail="Cảnh chưa có hình để preview")
    work = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["work"] / "edit-previews" / str(segment_id)
    try:
        output = render_timeline_with_ffmpeg(
            database.attach_edit_beats_to_timeline(project_id, [segment]),
            work,
            output_filename="preview.mp4",
            binary=FFMPEG_BINARY,
            width=640,
            height=360,
            fit="cover",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Không dựng được preview: {exc}") from exc
    return FileResponse(output, media_type="video/mp4", filename=f"scene-{segment.get('segment_index')}-preview.mp4")


class OrchestrateRequest(BaseModel):
    intent: str = Field(min_length=3, max_length=2000)
    # Costly steps stay behind an explicit confirmation: the plan is shown
    # first so nothing spends generation quota before it has been read.
    dry_run: bool = True
    # "plan": one model call proposes a tool list, run once (the page's
    # button). "agent": an agent works the goal over the app's tools, reads
    # every result, changes approach when something fails, and the app checks
    # the project before calling it done.
    mode: Literal["plan", "agent"] = "plan"
    target_steps: list[str] = Field(default_factory=list, max_length=12)
    allow_spend: bool = False
    # `force` rebuilds over what exists, possibly after a person edited it.
    allow_overwrite: bool = False
    # Which AI directs first: "auto" follows the orchestration assignment; an
    # agent or runtime name (astra, claude, codex_cli, claude_code_cli) puts
    # that one first. The others stay behind it as the fallback.
    runtime: str = Field(default="auto", max_length=40)
    max_rounds: int = Field(default=4, ge=1, le=8)
    tool_budget: int = Field(default=40, ge=5, le=120)


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
    "plan_scene_edits": {
        "description": (
            "Lap ke hoach dung CHI TIET cho tung scene: visual beats, chu dong hien/an, "
            "graphic overlay va sound cues. Day la buoc chinh de edit chuyen nghiep truoc render."
        ),
        "args": "limit (tuy chon): so canh toi da; max_beats (tuy chon): 1-8",
        "cost": "mien phi (chi goi AI dieu phoi), chua tao asset AI",
    },
    "apply_scene_edits": {
        "description": (
            "Ap dung ke hoach dung chi tiet da lap: trich frame, tao preset SFX, "
            "queue anh AI phu neu co beat ai_image."
        ),
        "args": "limit (tuy chon): so canh toi da; image_provider (tuy chon, mac dinh auto)",
        "cost": "co the ton quota neu can tao anh AI phu",
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
                    "max_beats": {"type": "integer"},
                    "image_provider": {"type": "string"},
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
        timeline = database.attach_edit_beats_to_timeline(project_id, timeline)
        return {
            "status": "ok",
            "scenes": [
                {
                    "segment_index": segment.get("segment_index"),
                    "visual_kind": segment.get("visual_kind") or "",
                    "has_visual": bool(str(segment.get("visual_path") or "").strip()),
                    "edit_transition": segment.get("edit_transition") or "",
                    "edit_beats": len(segment.get("edit_beats") or []),
                    "overlays": len(_json_list_field(segment.get("overlays"))),
                    "sound_cues": len(_json_list_field(segment.get("sound_cues"))),
                }
                for segment in timeline
            ],
        }
    if tool == "plan_scene_kinds":
        policy = "gif_only" if str(step.get("motion_policy") or "") == "gif_only" else "balanced"
        return plan_timeline_visuals(project_id, motion_policy=policy)
    if tool == "plan_edit":
        return plan_project_edit(project_id)
    if tool == "plan_scene_edits":
        script = database.get_latest_project_script(project_id)
        timeline = database.list_project_timeline(
            project_id, script_id=int(script["id"]) if script else None
        )
        limit = max(0, min(int(step.get("limit") or 0), 500))
        max_beats = max(1, min(int(step.get("max_beats") or 4), 8))
        selected = timeline[:limit] if limit else timeline
        results: list[dict[str, Any]] = []
        for segment in selected:
            try:
                results.append(plan_timeline_edit_beats(
                    int(segment["id"]),
                    PlanEditBeatsRequest(max_beats=max_beats),
                ))
            except HTTPException as exc:
                results.append({
                    "status": "error",
                    "segment_id": int(segment["id"]),
                    "detail": str(exc.detail),
                })
        return {
            "status": "planned",
            "planned": sum(1 for item in results if item.get("status") == "planned"),
            "failed": sum(1 for item in results if item.get("status") == "error"),
            "results": results,
        }
    if tool == "apply_scene_edits":
        script = database.get_latest_project_script(project_id)
        timeline = database.list_project_timeline(
            project_id, script_id=int(script["id"]) if script else None
        )
        limit = max(0, min(int(step.get("limit") or 0), 500))
        selected = timeline[:limit] if limit else timeline
        provider = str(step.get("image_provider") or "auto").strip()
        if provider == "auto":
            try:
                route = scene_provider_gateway.route(
                    SCENE_IMAGE,
                    provider_states=_provider_runtime_states(),
                    policy=_billing_route_policy(),
                )
                provider = route.selected.key
            except Exception as exc:
                return {"status": "error", "detail": f"Auto không chọn được image provider: {exc}"}
        results = []
        for segment in selected:
            try:
                results.append(apply_timeline_edit_beats(
                    int(segment["id"]),
                    ApplyEditBeatsRequest(image_provider=provider, confirmed=True),
                ))
            except HTTPException as exc:
                results.append({
                    "status": "error",
                    "segment_id": int(segment["id"]),
                    "detail": str(exc.detail),
                })
        return {
            "status": "applied",
            "provider": provider,
            "applied": sum(1 for item in results if item.get("status") in {"ready", "generating"}),
            "failed": sum(1 for item in results if item.get("status") == "error"),
            "results": results,
        }
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


def _queue_orchestrator_goal(project_id: int, payload: OrchestrateRequest) -> dict[str, Any]:
    """Hand a goal to an orchestrating agent through the existing task queue.

    It can take many minutes, so it runs on the agent worker rather than inside
    this request; the caller follows the task and the step log.
    """
    targets = [str(name).strip().lower() for name in payload.target_steps if str(name).strip()]
    unknown = [name for name in targets if steps.get(name) is None]
    if not targets or unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                "Chế độ agent cần target_steps: các bước phải đạt để coi là xong, "
                f"chọn trong {', '.join(steps.STEP_KEYS)}"
                + (f". Không có bước: {', '.join(unknown)}" if unknown else "")
            ),
        )
    preferred = str(payload.runtime or "auto").strip().lower()
    first_agent = ""
    if preferred != "auto":
        if orchestrator_runtime.runtime_id(preferred) not in _AGENT_RUNNERS:
            raise HTTPException(
                status_code=400,
                detail=f"runtime phải là auto hoặc một AI điều phối được: {', '.join(sorted(_AGENT_RUNNERS))}",
            )
        # Assigned to the agent, so the worker claims it with that one and
        # the run log names the AI that actually directed.
        first_agent = settings.canonical_agent_id(orchestrator_runtime.runtime_id(preferred))
    task = database.create_agent_task(
        project_id,
        ORCHESTRATOR_ROLE,
        "orchestrate.goal",
        {
            "goal": payload.intent.strip(),
            "target_steps": targets,
            "allow_spend": bool(payload.allow_spend),
            "allow_overwrite": bool(payload.allow_overwrite),
            "max_rounds": int(payload.max_rounds),
            "tool_budget": int(payload.tool_budget),
            "runtime": preferred,
        },
        requested_by="user",
        assigned_agent=first_agent,
        max_attempts=1,
    )
    agent_task_worker.enqueue(str(task["id"]))
    return {
        "status": "queued",
        "mode": "agent",
        "task": task,
        "follow": {
            "task": f"/api/agent-tasks/{task['id']}",
            "steps": f"/api/projects/{project_id}/steps",
            "log": f"/api/projects/{project_id}/orchestrator-report",
        },
    }


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
    if payload.mode == "agent":
        return _queue_orchestrator_goal(project_id, payload)

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
        "- Neu nguoi dung muon edit chuyen nghiep, chu dong hien/an, hieu ung do hoa hoac SFX: "
        "goi 'plan_scene_edits' truoc; sau khi da xem/chap nhan thi goi 'apply_scene_edits'.\n"
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
        result = _call_orchestrator_json(
            system_prompt, user_prompt, _ORCHESTRATE_SCHEMA,
            project_id=project_id, step="Điều phối theo yêu cầu người dùng",
        )
    except LlmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    steps = [
        {
            "tool": str(step.get("tool") or ""),
            "reason": str(step.get("reason") or ""),
            **{
                key: step[key]
                for key in ("kind", "motion_policy", "max_beats", "image_provider", "job_id", "limit", "providers")
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
        if str(job.get("provider") or "") == "motion_graphics":
            # Motion graphics draws data, not a picture. Rewriting the scene
            # into a camera prompt here would throw away the numbers the
            # chart needs; the spec builder below reads the storyboard line.
            return raw_prompt
        return _craft_video_prompt(
            raw_prompt, has_reference_image=bool(job.get("requires_reference_image"))
        )
    return _craft_image_prompt(raw_prompt, context=context)


_MOTION_SPEC_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": sorted(MOTION_CUT_TYPES)},
        "title": {"type": "string"},
        "text": {"type": "string"},
        "stat": {"type": "string"},
        "subtitle": {"type": "string"},
        "chartData": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    # A string here renders as NaN: the count-up animation
                    # parses it as a number. Currency belongs in `prefix`.
                    "value": {"type": "number"},
                    "prefix": {"type": "string"},
                    "suffix": {"type": "string"},
                },
                "required": ["label", "value", "prefix", "suffix"],
            },
        },
    },
    "required": ["type", "title", "text", "stat", "subtitle", "chartData"],
}


def _build_motion_cut_spec(job: dict[str, Any]) -> dict[str, Any]:
    """Turn one storyboard line into a motion-graphics cut spec."""
    verdict = _call_orchestrator_json(
        (
            "Bạn chuyển một câu mô tả cảnh storyboard thành đặc tả đồ hoạ chuyển động. "
            "Chọn 'type' hợp nội dung: có số liệu so sánh thì bar_chart/pie_chart, "
            "nhiều chỉ số thì kpi_grid, một con số lớn thì stat_card, "
            "chỉ có chữ thì text_card hoặc hero_title. "
            "chartData chỉ dùng cho bar_chart, pie_chart, kpi_grid. "
            "'value' phải là số; ký hiệu tiền tệ đặt ở 'prefix'. "
            "Không bịa số liệu không có trong mô tả: khi không có số, dùng text_card. "
            "Trường không dùng thì để chuỗi rỗng hoặc mảng rỗng."
        ),
        str(job.get("prompt") or "")[:8000],
        _MOTION_SPEC_SCHEMA,
        stage="storyboard",
    )
    # Empty fields are how the strict schema says "not used"; passing them on
    # would draw a blank title over the chart.
    return {
        key: value
        for key, value in dict(verdict).items()
        if value not in ("", [], None)
    }


motion_graphics_set_spec_builder(_build_motion_cut_spec)


# Registered here, after the definition above: the worker only calls it
# once a job actually starts, so queueing never waits on the CLI.
scene_generation_worker.set_prompt_crafter(_write_job_prompt)


def _require_scene_provider_config(provider: str) -> None:
    """Rejects a provider whose API key is missing, before any job is made."""
    adapter = scene_provider_gateway.get(provider)
    if adapter is None:
        raise HTTPException(status_code=400, detail=f"Provider chưa được đăng ký: {provider}")
    if not adapter.descriptor.enabled:
        raise HTTPException(status_code=400, detail=f"Provider đang tạm khóa: {provider}")
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
    elif provider in {"phantom_canvas_image", "phantom_canvas_video"}:
        phantom = phantom_canvas_bridge.status()
        if not phantom.get("ready"):
            raise HTTPException(
                status_code=400,
                detail=(str(phantom.get("detail") or "Phantom Canvas chưa chạy")
                        + " Mở Kết nối AI và bấm ‘Chạy Phantom Canvas’, rồi thử lại."),
            )


_SCENE_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_SCENE_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}


def _scene_failure_kind(error: str) -> str:
    normalized = error.lower()
    if any(key in normalized for key in ("quota", "credit", "tín dụng", "resource_exhausted", "hạn mức")):
        return "quota"
    if any(key in normalized for key in ("timeout", "quá lâu", "heartbeat", "mất kết nối")):
        return "timeout"
    return "provider"


def _finish_or_fallback_external_scene_job(
    job: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    """Apply the same bounded Provider Gateway fallback to sidecar failures."""
    job_id = int(job["id"])
    failed_provider = str(job.get("provider") or "").strip().lower()
    failure_kind = _scene_failure_kind(message)
    database.finalize_scene_provider_usage(
        job_id,
        "failed",
        metadata={"failure_kind": failure_kind, "error": message[:2000]},
    )
    fallback_provider = _route_scene_failure(job, message, failure_kind)
    if fallback_provider and fallback_provider != failed_provider:
        database.record_scene_provider_failure(failed_provider, message)
        rerouted = database.reroute_scene_generation_job(
            job_id,
            fallback_provider,
            previous_error=message,
            failure_kind=failure_kind,
        )
        if rerouted:
            descriptor = scene_provider_gateway.require(fallback_provider).descriptor
            kind = str(rerouted.get("job_kind") or "image").strip().lower()
            capability = {
                "image": SCENE_IMAGE,
                "gif": SCENE_ANIMATED_IMAGE,
                "video": SCENE_VIDEO,
            }.get(kind, f"scene.{kind}")
            database.record_provider_usage(
                project_id=int(rerouted["project_id"]),
                scene_job_id=job_id,
                provider=fallback_provider,
                capability=capability,
                status="estimated",
                estimated_cost=descriptor.estimated_unit_cost or 0,
                metadata={
                    "billing_mode": descriptor.billing_mode,
                    "fallback_from": failed_provider,
                },
            )
            if fallback_provider not in database.EXTERNAL_SIDECAR_PROVIDERS:
                scene_generation_worker.enqueue(job_id)
            return {"status": "fallback", "job": rerouted, "from_provider": failed_provider}
    finished = database.finish_scene_generation_job(
        job_id,
        "error",
        error=message,
        failure_kind=failure_kind,
    )
    return {"status": "error", "job": finished}


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


def _record_scene_job_estimate(job: dict[str, Any] | None, *, reason: str = "queued") -> None:
    if not job:
        return
    provider = str(job.get("provider") or "").strip().lower()
    try:
        descriptor = scene_provider_gateway.require(provider).descriptor
    except Exception:
        return
    kind = str(job.get("job_kind") or "image").strip().lower()
    capability = {
        "image": SCENE_IMAGE,
        "gif": SCENE_ANIMATED_IMAGE,
        "video": SCENE_VIDEO,
    }.get(kind, f"scene.{kind}")
    database.record_provider_usage(
        project_id=int(job["project_id"]),
        scene_job_id=int(job["id"]),
        provider=provider,
        capability=capability,
        status="estimated",
        estimated_cost=descriptor.estimated_unit_cost or 0,
        metadata={"billing_mode": descriptor.billing_mode, "reason": reason},
    )


_EDIT_BEATS_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_kind": {"type": "string", "enum": ["primary", "source_frame", "ai_image"]},
                    "duration_seconds": {"type": "number"},
                    "effect": {"type": "string", "enum": ["static", "zoom_in", "zoom_out"]},
                    "sound_cues": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["whoosh", "pop", "hit", "ambient", "music_duck"]},
                                "start_seconds": {"type": "number"},
                                "end_seconds": {"type": "number"},
                                "intensity": {"type": "string", "enum": ["low", "medium", "high"]},
                                "asset_id": {"type": "integer"},
                                "asset_path": {"type": "string"},
                                "reason": {"type": "string"}
                            },
                            "required": ["type", "start_seconds", "end_seconds"],
                        },
                    },
                    "transition": {"type": "string", "enum": ["cut", "fade"]},
                    "prompt": {"type": "string"},
                },
                "required": ["source_kind", "duration_seconds", "effect", "transition", "prompt"],
            },
        },
        "overlays": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["title", "callout", "label", "text"]},
                    "text": {"type": "string"},
                    "position": {"type": "string", "enum": ["top_left", "top_center", "top_right", "center"]},
                    "style": {"type": "string", "enum": ["clean", "neon", "card"]},
                    "animation": {"type": "string", "enum": ["fade", "pop", "slide_up"]},
                    "start_seconds": {"type": "number"},
                    "end_seconds": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["kind", "text", "position", "style", "animation", "start_seconds", "end_seconds"],
            },
        },
        "sound_cues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["whoosh", "pop", "hit", "ambient", "music_duck"]},
                    "start_seconds": {"type": "number"},
                    "end_seconds": {"type": "number"},
                    "intensity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "asset_id": {"type": "integer"},
                    "asset_path": {"type": "string"},
                    "reason": {"type": "string"}
                },
                "required": ["type", "start_seconds", "end_seconds"],
            },
        },
        "reason": {"type": "string"},
    },
    "required": ["beats", "reason"],
}


def _normalise_scene_edit_beats(
    segment: dict[str, Any], raw_beats: list[dict[str, Any]], max_beats: int
) -> list[dict[str, Any]]:
    duration = max(0.15, float(segment.get("duration_seconds") or 1))
    visual_path = str(segment.get("visual_path") or "").strip()
    cleaned: list[dict[str, Any]] = []
    for raw in raw_beats[:max_beats]:
        kind = str(raw.get("source_kind") or "primary")
        if kind not in {"primary", "source_frame", "ai_image"}:
            kind = "primary"
        effect = str(raw.get("effect") or "static")
        transition = str(raw.get("transition") or "cut")
        cleaned.append({
            "source_kind": kind,
            "visual_path": visual_path if kind in {"primary", "source_frame"} else "",
            "duration_seconds": max(0.15, float(raw.get("duration_seconds") or 1)),
            "effect": effect if effect in {"static", "zoom_in", "zoom_out"} else "static",
            "transition": transition if transition in {"cut", "fade"} else "cut",
            "prompt": str(raw.get("prompt") or "").strip()[:5000],
            "status": "ready" if kind == "primary" and visual_path else "needs_asset",
        })
    if not cleaned:
        cleaned = [{
            "source_kind": "primary",
            "visual_path": visual_path,
            "duration_seconds": duration,
            "effect": "static",
            "transition": "cut",
            "prompt": "",
            "status": "ready" if visual_path else "needs_asset",
        }]
    total_weight = sum(float(item["duration_seconds"]) for item in cleaned) or 1.0
    elapsed = 0.0
    for index, item in enumerate(cleaned):
        if index == len(cleaned) - 1:
            item["duration_seconds"] = round(max(0.15, duration - elapsed), 3)
        else:
            value = round(max(0.15, duration * float(item["duration_seconds"]) / total_weight), 3)
            remaining_minimum = 0.15 * (len(cleaned) - index - 1)
            value = min(value, max(0.15, duration - elapsed - remaining_minimum))
            item["duration_seconds"] = value
            elapsed += value
    # The renderer expects one exact timeline, including very short scenes.
    delta = duration - sum(float(item["duration_seconds"]) for item in cleaned)
    cleaned[-1]["duration_seconds"] = round(float(cleaned[-1]["duration_seconds"]) + delta, 3)
    return cleaned


def _short_overlay_text(segment: dict[str, Any], limit: int = 72) -> str:
    text = " ".join(str(segment.get("voice_text") or segment.get("visual_prompt") or "").split())
    if not text:
        return ""
    text = text.strip(" .,:;!?-")
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].strip(" .,:;!?-") or text[:limit].strip()


def _fallback_storyboard_edit_layers(segment: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    duration = max(0.15, float(segment.get("duration_seconds") or 1))
    text = _short_overlay_text(segment)
    if not text or duration < 1.2:
        return [], []
    overlay = {
        "kind": "callout",
        "text": text,
        "position": "top_center",
        "style": "card",
        "animation": "pop",
        "start_seconds": 0.2,
        "end_seconds": round(min(duration, max(1.2, min(2.8, duration * 0.55))), 3),
        "reason": "Nhấn ý chính của cảnh bằng chữ động.",
    }
    cue = {
        "type": "whoosh",
        "start_seconds": 0.2,
        "end_seconds": round(min(duration, 0.75), 3),
        "intensity": "low",
        "reason": "Đệm nhẹ cho chữ xuất hiện.",
    }
    return [overlay], [cue]


def _normalise_storyboard_edit_layers(
    segment: dict[str, Any],
    plan_result: dict[str, Any],
    *,
    force_fallback: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    duration = max(0.15, float(segment.get("duration_seconds") or 1))
    raw_overlays = plan_result.get("overlays") if isinstance(plan_result, dict) else []
    raw_sound_cues = plan_result.get("sound_cues") if isinstance(plan_result, dict) else []
    if force_fallback:
        raw_overlays, raw_sound_cues = _fallback_storyboard_edit_layers(segment)
    warning = ""
    try:
        overlays = normalize_graphic_overlays(raw_overlays or [], duration)
    except ValueError as exc:
        overlays = []
        warning = f"Overlay AI không hợp lệ: {exc}"
    try:
        sound_cues = _normalise_sound_cues(raw_sound_cues or [], duration)
    except ValueError as exc:
        sound_cues = []
        warning = f"{warning}; " if warning else ""
        warning += f"SFX AI không hợp lệ: {exc}"
    return overlays, sound_cues, warning


@app.post("/api/timeline/{segment_id}/edit-beats/plan")
def plan_timeline_edit_beats(segment_id: int, payload: PlanEditBeatsRequest) -> dict[str, Any]:
    """Use the storyboard AI to design the edit inside one narrated scene."""
    segment = database.get_project_timeline_segment(segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh storyboard")
    duration = float(segment.get("duration_seconds") or 1)
    system_prompt = (
        "Ban la editor video. Hay chia MOT canh storyboard thanh cac nhip hinh lien tuc de minh hoa loi doc. "
        "Dung primary cho clip goc, source_frame khi can dong bang mot khoanh khac, ai_image chi khi clip goc "
        "khong du minh hoa. Tong duration_seconds phai bang dung thoi luong canh. Toi da mot nhip AI image de "
        "tranh cat vu qua day. Prompt ai_image viet bang tieng Anh, cu the, khong chen chu. "
        "Ngoai beats, lap them overlays va sound_cues cap canh neu can tao cam giac dung chuyen nghiep: "
        "overlays la 0-2 lop chu ngan nhu title/callout/label/text, co style clean/neon/card, "
        "animation fade/pop/slide_up, thoi diem start/end nam trong canh. "
        "sound_cues la whoosh/pop/hit/music_duck ngan de nhan nhip chu, chuyen canh hoac CTA; dung tiet che. "
        "Khong giai thich ngoai JSON."
    )
    user_prompt = (
        f"Thoi luong: {duration:.3f} giay; toi da {payload.max_beats} nhip.\n"
        f"Loi AI doc: {str(segment.get('voice_text') or '')[:3000]}\n"
        f"Mo ta hinh: {str(segment.get('visual_prompt') or '')[:3000]}\n"
        f"Clip goc hien co: {'co' if str(segment.get('visual_path') or '').strip() else 'khong'}."
    )
    ai_error = ""
    result: dict[str, Any] = {}
    force_layer_fallback = False
    try:
        result = _call_orchestrator_json(
            system_prompt, user_prompt, _EDIT_BEATS_PLAN_SCHEMA, stage="storyboard",
            project_id=int(segment.get("project_id") or 0) or None,
            step=f"Nhịp dựng cảnh {segment.get('segment_index')}",
        )
        raw_beats = [dict(item) for item in (result.get("beats") or []) if isinstance(item, dict)]
        reason = str(result.get("reason") or "AI đã lập kế hoạch cho cảnh.")
        planned_by = "ai"
    except LlmError as exc:
        ai_error = str(exc)
        force_layer_fallback = True
        planned_by = "fallback"
        raw_beats = [{
            "source_kind": "primary",
            "duration_seconds": duration,
            "effect": "zoom_in",
            "transition": "cut",
            "prompt": "",
        }]
        reason = "AI lập kế hoạch tạm thời không phản hồi; đã giữ clip gốc an toàn để bạn vẫn tiếp tục dựng."
    cleaned_beats = _normalise_scene_edit_beats(segment, raw_beats, payload.max_beats)
    overlays, sound_cues, layer_warning = _normalise_storyboard_edit_layers(
        segment, result, force_fallback=force_layer_fallback,
    )
    first = cleaned_beats[0] if cleaned_beats else {}
    database.save_segment_edit(
        segment_id,
        str(first.get("transition") or "cut"),
        str(first.get("effect") or "static"),
        reason[:400],
    )
    database.save_segment_edit_layers(segment_id, overlays=overlays, sound_cues=sound_cues)
    beats = database.replace_timeline_edit_beats(
        segment_id, cleaned_beats
    )
    if layer_warning:
        ai_error = f"{ai_error}; {layer_warning}" if ai_error else layer_warning
    if planned_by == "fallback":
        _record_orchestrator_step(
            project_id=int(segment.get("project_id") or 0) or None, stage="storyboard",
            step=f"Nhịp dựng cảnh {segment.get('segment_index')} (bản dự phòng)",
            status="fallback", runtime="app_template", fallback_used=True,
            why="AI lập nhịp dựng thất bại nên app giữ nguyên clip gốc",
            output_ref=f"{len(beats)} nhịp", error=ai_error,
        )
    segment = database.get_project_timeline_segment(segment_id) or segment
    return {
        "status": "planned",
        "segment": segment,
        "beats": beats,
        "overlays": overlays,
        "sound_cues": sound_cues,
        "reason": reason,
        "ai_error": ai_error,
        "planned_by": planned_by,
        "is_fallback": planned_by == "fallback",
    }


def _queue_edit_beat_image(
    segment: dict[str, Any], beat: dict[str, Any], provider: str, ratio: str
) -> dict[str, Any]:
    project_id = int(segment["project_id"])
    for active in database.list_scene_generation_jobs(project_id, limit=500):
        if int(active.get("edit_beat_id") or 0) == int(beat["id"]) and str(active.get("status") or "") in {"waiting", "queued", "running"}:
            return active
    prompt = str(beat.get("prompt") or segment.get("visual_prompt") or segment.get("voice_text") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail=f"Nhịp {beat.get('beat_index')} chưa có prompt tạo ảnh")
    job = database.create_scene_generation_job(
        project_id,
        int(segment["id"]),
        provider,
        prompt,
        duration_seconds=max(1, min(30, int(math.ceil(float(beat.get("duration_seconds") or 1))))),
        ratio=ratio,
        job_kind="image",
        prompt_pending=False,
        edit_beat_id=int(beat["id"]),
    )
    if not job:
        raise HTTPException(status_code=400, detail="Không tạo được job cho nhịp dựng")
    database.set_timeline_edit_beat_status(int(beat["id"]), "generating")
    _record_scene_job_estimate(job, reason="storyboard_edit_beat")
    if provider not in database.EXTERNAL_SIDECAR_PROVIDERS:
        scene_generation_worker.enqueue(int(job["id"]))
    return database.get_scene_generation_job(int(job["id"])) or job


@app.post("/api/timeline/{segment_id}/edit-beats/{beat_index}/generate")
def generate_edit_beat_image(segment_id: int, beat_index: int, payload: GenerateEditBeatRequest) -> dict[str, Any]:
    if not payload.confirmed:
        raise HTTPException(status_code=400, detail="Tạo ảnh AI có thể dùng hạn mức; cần confirmed=true")
    if payload.image_provider not in _IMAGE_CAPABLE_PROVIDERS:
        raise HTTPException(status_code=400, detail="Provider này không tạo ảnh")
    _require_scene_provider_config(payload.image_provider)
    segment = database.get_project_timeline_segment(segment_id)
    beat = next((item for item in database.list_timeline_edit_beats(segment_id) if int(item.get("beat_index") or 0) == beat_index), None)
    if not segment or not beat:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhịp dựng")
    _enforce_provider_billing_policy(payload.image_provider, int(segment["project_id"]))
    job = _queue_edit_beat_image(segment, beat, payload.image_provider, payload.ratio)
    return {"status": "delegated" if payload.image_provider in database.EXTERNAL_SIDECAR_PROVIDERS else "queued", "job": job}


@app.post("/api/timeline/{segment_id}/edit-beats/apply")
def apply_timeline_edit_beats(segment_id: int, payload: ApplyEditBeatsRequest) -> dict[str, Any]:
    segment = database.get_project_timeline_segment(segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh storyboard")
    beats = database.list_timeline_edit_beats(segment_id)
    if not beats:
        beats = database.replace_timeline_edit_beats(
            segment_id, _normalise_scene_edit_beats(segment, [], 1)
        )
    needs_ai = [item for item in beats if str(item.get("source_kind") or "") == "ai_image" and not Path(str(item.get("visual_path") or "")).is_file()]
    if needs_ai:
        if not payload.confirmed:
            raise HTTPException(status_code=400, detail="Kế hoạch có ảnh AI; cần confirmed=true")
        if payload.image_provider not in _IMAGE_CAPABLE_PROVIDERS:
            raise HTTPException(status_code=400, detail="Provider này không tạo ảnh")
        _require_scene_provider_config(payload.image_provider)
        _enforce_provider_billing_policy(payload.image_provider, int(segment["project_id"]))
    extracted: list[dict[str, Any]] = []
    queued: list[dict[str, Any]] = []
    resolved_sound_cues: list[dict[str, Any]] = []
    raw_sound_cues = segment.get("sound_cues") or []
    try:
        if isinstance(raw_sound_cues, str):
            raw_sound_cues = json.loads(raw_sound_cues)
        if raw_sound_cues:
            from .sound_effects import resolve_sound_assets
            resolved_sound_cues = resolve_sound_assets(
                database,
                int(segment["project_id"]),
                raw_sound_cues,
                max(0.15, float(segment.get("duration_seconds") or 1)),
                ensure_project_layout(PRODUCTION_ARTIFACT_DIR, int(segment["project_id"]))["audio"] / "sfx",
            )
            database.save_segment_edit_layers(segment_id, sound_cues=resolved_sound_cues)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"Sound cue của cảnh không hợp lệ: {exc}") from exc
    for beat in beats:
        kind = str(beat.get("source_kind") or "primary")
        if kind == "source_frame" and not beat.get("asset_id"):
            extracted.append(_extract_edit_beat_frame(segment_id, int(beat["beat_index"])))
        elif kind == "ai_image" and not Path(str(beat.get("visual_path") or "")).is_file():
            queued.append(_queue_edit_beat_image(segment, beat, payload.image_provider, payload.ratio))
    return {
        "status": "generating" if queued else "ready",
        "extracted_count": len(extracted),
        "queued_jobs": queued,
        "beats": database.list_timeline_edit_beats(segment_id),
        "sound_cues": resolved_sound_cues,
    }


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
    _enforce_provider_billing_policy(payload.provider, project_id)
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
    _record_scene_job_estimate(job)
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
        _enforce_provider_billing_policy(provider, project_id)
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
        _enforce_provider_billing_policy(payload.reference_image_provider, project_id)
    project = database.get_production_project(project_id)
    script = database.get_latest_project_script(project_id, variant=payload.variant)
    if not project or not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án hoặc kịch bản")
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    if not timeline:
        raise HTTPException(status_code=400, detail="Cần tạo timeline trước khi tạo cảnh AI")
    image_pool = [p for p in providers if p in _IMAGE_CAPABLE_PROVIDERS]
    video_pool = [p for p in providers if p in _VIDEO_CAPABLE_PROVIDERS]
    if not video_pool and not payload.motion_as_gif:
        # Scenes the plan calls for as video used to fall through to a still
        # without a word, because the branch that makes video is entered only
        # when a video provider is present. The whole film came back as
        # stills - matching nothing the director had planned - and the first
        # sign of it was watching the result.
        wanted_motion = [
            segment for segment in database.list_project_timeline(project_id, script_id=int(script["id"]))
            if str(segment.get("visual_kind") or "") == "video"
            and Path(str(segment.get("visual_path") or "")).suffix.lower() not in _SCENE_VIDEO_EXTENSIONS
        ]
        if wanted_motion:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{len(wanted_motion)} cảnh được lên kế hoạch là video, nhưng provider đang chọn "
                    f"({', '.join(providers)}) chỉ tạo được ảnh tĩnh. Hãy thêm một provider video "
                    f"(ví dụ gflow_cli) hoặc đổi kế hoạch các cảnh này sang ảnh."
                ),
            )
    active_segment_ids = {
        int(job["timeline_segment_id"])
        for job in database.list_scene_generation_jobs(project_id, limit=500)
        if str(job.get("status") or "") in {"waiting", "queued", "running"}
    }
    queued: list[dict[str, Any]] = []
    preparation_jobs: list[dict[str, Any]] = []
    counters = {"image": 0, "video": 0}
    budget_stop = ""

    def _budget_stops(candidate: str) -> bool:
        """Stop the batch at the ceiling instead of at the first scene.

        Each queued job writes its estimate to the ledger straight away, so
        this sees the batch's own running total and cuts it off at the exact
        scene that would cross the line.
        """
        nonlocal budget_stop
        if budget_stop:
            return True
        budget_stop = _cost_budget_breach(project_id, candidate)
        return bool(budget_stop)
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
            if _budget_stops(provider):
                break
            reference_asset = _reference_image_asset_for_segment(project_id, segment)
            dependency_job: dict[str, Any] | None = None
            if reference_asset is None:
                # The caller only supplies this when it asked for the video
                # pipeline explicitly; a plan-driven video scene falls back to
                # whichever image tool this batch already has.
                image_provider = payload.reference_image_provider
                if image_provider not in _IMAGE_CAPABLE_PROVIDERS:
                    image_provider = image_pool[0] if image_pool else "flow_image"
                if _budget_stops(image_provider):
                    break
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
                _record_scene_job_estimate(dependency_job, reason="image_to_video_dependency")
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
                _record_scene_job_estimate(job, reason="image_to_video")
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
        if _budget_stops(provider):
            break
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
            _record_scene_job_estimate(job, reason="batch")
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
        "variant": payload.variant,
        "motion_as_gif": payload.motion_as_gif,
        "limit": payload.limit,
        "by_provider": by_provider,
        "budget_stop": budget_stop,
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


def _attach_scene_job_asset(job: dict[str, Any], asset_id: int) -> dict[str, Any] | None:
    """Keep storyboard inserts inside their beat; ordinary jobs still replace a scene visual."""
    beat_id = int(job.get("edit_beat_id") or 0)
    if beat_id:
        return database.attach_asset_to_edit_beat(beat_id, asset_id)
    return database.attach_asset_to_timeline_segment(int(job["timeline_segment_id"]), asset_id)


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
    attached = _attach_scene_job_asset(job, asset_id)
    if not attached:
        raise HTTPException(status_code=400, detail="Không thể gắn asset vào cảnh")
    finished = database.finish_scene_generation_job(
        job_id,
        "completed",
        output_path=str(asset["file_path"]),
        output_asset_id=asset_id,
        release_dependents=False,
    )
    database.finalize_scene_provider_usage(
        job_id,
        "completed",
        metadata={"output_path": str(asset["file_path"])},
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
    return _finish_or_fallback_external_scene_job(job, message)


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


# Sites web_video_sidecar.py can drive with Playwright, needing no browser
# extension — only a session saved once with `--login`. flow_image is absent
# on purpose: it has no Playwright entry, so it is the one provider that
# really does require the extension.
PLAYWRIGHT_SIDECAR_PROVIDERS = frozenset(
    {"flow_veo", "meta_ai_video", "meta_ai_image", "gemini_web_image", "chatgpt_web_image"}
)


@app.get("/api/scene-sidecar-status")
def _sidecar_recently_polled(provider: str) -> bool:
    """Whether an external sidecar has asked for work recently enough."""
    last_seen = _sidecar_last_seen.get(provider)
    if last_seen is None:
        return False
    age = (datetime.now(timezone.utc) - last_seen).total_seconds()
    return age <= _SIDECAR_STALE_AFTER_SECONDS


def scene_sidecar_status() -> dict[str, Any]:
    """Whether each external-sidecar provider has polled recently enough to
    be considered alive — lets the UI say "no sidecar is running" instead of
    silently sitting at an unmoving progress bar when jobs stay queued."""
    now = datetime.now(timezone.utc)
    result: dict[str, Any] = {}
    for provider in database.EXTERNAL_SIDECAR_PROVIDERS:
        last_seen = _sidecar_last_seen.get(provider)
        seconds_ago = (now - last_seen).total_seconds() if last_seen else None
        extension_connected = (
            provider in database.BROWSER_SIDECAR_PROVIDERS
            and _browser_extension_connections > 0
        )
        result[provider] = {
            "last_seen_at": last_seen.isoformat() if last_seen else None,
            "seconds_ago": seconds_ago,
            "alive": seconds_ago is not None and seconds_ago <= _SIDECAR_STALE_AFTER_SECONDS,
            "extension_connected": extension_connected,
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
    attached = _attach_scene_job_asset(job, asset_id)
    if not attached:
        raise HTTPException(status_code=400, detail="Không thể gắn asset vào cảnh")
    finished = database.finish_scene_generation_job(
        job_id,
        "completed",
        output_path=str(asset["file_path"]),
        output_asset_id=asset_id,
        release_dependents=False,
    )
    database.finalize_scene_provider_usage(
        job_id,
        "completed",
        metadata={"output_path": str(asset["file_path"])},
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
        verdict = _call_orchestrator_json(
            system_prompt, body, _SCRIPT_REVIEW_SCHEMA, stage="script",
            project_id=project_id, step="Soát kịch bản",
        )
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


@app.post("/api/projects/{project_id}/timeline/from-dialogue")
def build_timeline_from_dialogue(
    project_id: int,
    min_seconds: float = Query(default=1.2, ge=0.3, le=10.0),
    force: bool = Query(default=False),
    replace_existing: bool = Query(default=False),
) -> dict[str, Any]:
    """Cut the timeline on the source's own dialogue turns.

    The reup workflow does not draw its pictures, it takes them from the video
    it is retelling. Its scenes should therefore fall exactly where the speech
    falls - one scene per spoken turn, running from that line's first second to
    its last - rather than on the even 15-25 second blocks a writer invents for
    a storyboard that will be illustrated.

    Each segment carries the speaker, so the line stays attached to whoever
    says it, and source_start_seconds, so the cut is made at that exact moment
    instead of being guessed at later.
    """
    project = database.get_production_project(project_id)
    script = database.get_latest_project_script(project_id)
    if not project or not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án hoặc kịch bản")

    # This replaces every scene, so anything attached to the current ones is
    # gone. A confirm in the page is not enough: a browser left open still
    # shows the old wording, and one user lost a twenty-minute voiceover to
    # it three times. Refusing here protects the work whatever page asks.
    # `force=true` used to be sent by an old, cached browser page and erased
    # the storyboard silently.  Replacing it is now an explicit destructive
    # operation, never the default action behind a storyboard button.
    if not (force and replace_existing):
        existing = database.list_project_timeline(project_id, script_id=int(script["id"]))
        attached = [item for item in existing if str(item.get("audio_path") or "").strip()]
        # Losing a voiceover is not the only damage, and it was the only one
        # this guard used to look for. Cutting by dialogue fills every scene
        # with the SOURCE's transcript, so a project whose script was written
        # in another language silently ends up narrating the original - in the
        # original language, transcription errors and all - with nothing said
        # about it. That happens whether or not any voice was attached.
        if existing:
            losses = [f"{len(existing)} cảnh hiện có sẽ bị thay hết"]
            if attached:
                losses.append(f"{len(attached)} cảnh đã có giọng đọc sẽ mất")
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{'; '.join(losses)}. Cắt theo lời thoại lấy lời từ transcript của video gốc, "
                    "không phải từ kịch bản bạn đã viết — sau đó phải bấm “Dịch lời bình” mới "
                    "chuyển được sang ngôn ngữ xuất bản. Nếu vẫn muốn, chạy lại với force=true."
                ),
            )
    analysis = database.get_video_analysis(
        str(project.get("youtube_video_id") or ""), analysis_type="reference"
    )
    turns = list((analysis or {}).get("result", {}).get("dialogue") or [])
    if not turns:
        raise HTTPException(
            status_code=400,
            detail="Chưa có bản phân tích lời thoại. Hãy chạy bước Phân tích trước.",
        )
    video = database.get_video(str(project.get("youtube_video_id") or "")) or {}
    source_duration = float(video.get("duration_seconds") or 0)

    planned: list[dict[str, Any]] = []
    missing_times = 0
    for index, turn in enumerate(turns):
        line = str(turn.get("line") or "").strip()
        if not line:
            continue
        start = float(turn.get("start_seconds") or 0)
        end = float(turn.get("end_seconds") or 0)
        if end <= start:
            # An analysis from before turns carried times, or a turn the model
            # could not place: fall back to the next turn's start so the cut is
            # still made somewhere sensible rather than at second zero.
            following = turns[index + 1] if index + 1 < len(turns) else {}
            end = float(following.get("start_seconds") or 0) or start + min_seconds
            missing_times += 1
        duration = max(min_seconds, end - start)
        if source_duration:
            start = min(start, max(0.0, source_duration - min_seconds))
        planned.append({
            "segment_index": len(planned) + 1,
            "start_seconds": int(round(sum(item["duration_seconds"] for item in planned))),
            "duration_seconds": max(1, int(round(duration))),
            "voice_text": line,
            "subtitle_text": line,
            "speaker": str(turn.get("speaker") or "").strip(),
            "visual_prompt": f"Cắt từ video gốc tại {int(start)}s",
            "asset_type": "source_clip",
        })
        planned[-1]["_source_start"] = start

    if not planned:
        raise HTTPException(status_code=400, detail="Bản phân tích không có lượt thoại nào dùng được")

    cuts = [item.pop("_source_start") for item in planned]

    # The storyboard grid is drawn from project_shots, and pairs a card to its
    # segment through segment.shot_id. Cutting the timeline without rewriting
    # the shots left the old, AI-invented storyboard on screen next to a
    # timeline it no longer described - every card reported "no picture yet"
    # even though each segment already had its clip from the source. One shot
    # per spoken turn, and the link between them, keeps the two in step.
    shots = database.create_project_shots(
        project_id,
        int(script["id"]),
        [
            {
                "shot_index": item["segment_index"],
                "section": "main",
                "narration": item["voice_text"],
                "speaker": item["speaker"],
                "visual_prompt": item["visual_prompt"],
                "asset_type": "source_clip",
                "duration_seconds": item["duration_seconds"],
                "status": "planned",
            }
            for item in planned
        ],
        force=True,
    ) or []
    for item, shot in zip(planned, shots):
        item["shot_id"] = int(shot["id"])

    timeline = database.create_project_timeline(project_id, int(script["id"]), planned, force=True)
    # Rebuilding replaced the rows the voice hung off. The files are
    # still there, so the scenes whose words are unchanged get theirs
    # back rather than being generated again.
    _reattach_project_voice(project_id)
    if timeline is None:
        raise HTTPException(status_code=404, detail="Không lưu được timeline")
    for segment, start in zip(timeline, cuts):
        database.save_segment_source_cue(
            int(segment["id"]), start, "Cắt đúng lúc câu thoại này được nói"
        )

    speakers = sorted({str(item.get("speaker") or "").strip() for item in planned if item.get("speaker")})
    return {
        "status": "built",
        "segments": len(planned),
        "speakers": speakers,
        "turns_without_timing": missing_times,
        "total_duration_seconds": sum(int(item["duration_seconds"]) for item in planned),
        "timeline": database.list_project_timeline(project_id, script_id=int(script["id"])),
    }


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
        result = _call_orchestrator_json(
            system_prompt, body, _SOURCE_CUE_SCHEMA, stage="storyboard",
            project_id=project_id, step="Chọn đoạn nguồn cho từng cảnh",
        )
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


_EDGE_VOICE_CACHE: dict[str, Any] = {"fetched_at": 0.0, "voices": []}
_EDGE_VOICE_TTL_SECONDS = 3600.0


@app.get("/api/tts/voices")
def list_tts_voices(refresh: bool = Query(default=False)) -> dict[str, Any]:
    """Ask Edge TTS what voices it actually has, rather than guessing.

    The picker listed seven voices written into the page by hand. Microsoft
    publishes 322, so most were simply unreachable - and the two Vietnamese
    ones shown were not the app being stingy, they are the entire Vietnamese
    catalogue, which is worth being able to see for oneself.

    Cached for an hour: the list changes rarely and the call goes over the
    network, while the voice picker is drawn on every project open.
    """
    now = time.monotonic()
    cached = _EDGE_VOICE_CACHE["voices"]
    if cached and not refresh and now - float(_EDGE_VOICE_CACHE["fetched_at"]) < _EDGE_VOICE_TTL_SECONDS:
        voices = cached
    else:
        if not EDGE_TTS_RUNTIME_READY:
            raise HTTPException(status_code=400, detail="Edge TTS chưa sẵn sàng trong môi trường local")
        script = (
            "import asyncio, json, edge_tts;"
            "print(json.dumps([{'short_name': v['ShortName'], 'locale': v['Locale'],"
            " 'gender': v['Gender'], 'friendly': v.get('FriendlyName', '')}"
            " for v in asyncio.run(edge_tts.list_voices())]))"
        )
        try:
            result = operations.run_cancellable(
                [str(settings.EDGE_TTS_PYTHON), "-c", script], timeout=90
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HTTPException(status_code=502, detail=f"Không hỏi được danh sách giọng: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-300:]
            raise HTTPException(status_code=502, detail=f"edge-tts lỗi: {detail}")
        try:
            voices = json.loads(result.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError) as exc:
            raise HTTPException(status_code=502, detail="edge-tts trả về dữ liệu không đọc được") from exc
        _EDGE_VOICE_CACHE["voices"] = voices
        _EDGE_VOICE_CACHE["fetched_at"] = now

    by_locale: dict[str, list[dict[str, Any]]] = {}
    for voice in voices:
        by_locale.setdefault(str(voice.get("locale") or "?"), []).append(voice)
    return {
        "provider": "edge_tts",
        "total": len(voices),
        "locales": len(by_locale),
        # Vietnamese first: it is what this app is for, and seeing that the
        # language really does have only two voices answers the question
        # better than any note could.
        "voices": sorted(
            voices,
            key=lambda item: (
                not str(item.get("locale") or "").startswith("vi-"),
                str(item.get("locale") or ""),
                str(item.get("short_name") or ""),
            ),
        ),
    }


@app.get("/api/workflows")
def list_workflows() -> dict[str, Any]:
    """The workflows, each read from its own file.

    The browser builds its wizard from this rather than keeping a second copy
    of the same descriptions, which is how a workflow came to mean one thing
    on screen and another in the writer.
    """
    return {
        "default": workflows.DEFAULT_KEY,
        "workflows": [item.as_dict() for item in workflows.all_workflows()],
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
    """Which models are out of quota right now, and when they come back.

    `limits` is only what blocks now. An outage past its reset time, or old
    enough to be tried again, is history: listed under `history` so it can be
    shown for what it is, never as a warning that a working model is down.
    """
    active: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    for item in database.list_active_usage_limits():
        quota = usage_limits.limit_state(item)
        row = {
            "provider": item.get("provider"),
            "label": _PROVIDER_LABELS.get(str(item.get("provider")), str(item.get("provider"))),
            "message": item.get("message"),
            "detected_at": item.get("detected_at"),
            "resets_at": str(item.get("resets_at") or "") or None,
            "state": quota["state"],
            "retry_at": quota["retry_at"],
        }
        (active if quota["blocking"] else history).append(row)
    return {"limits": active, "count": len(active), "history": history}


@app.post("/api/usage-limits/{provider}/clear")
def clear_usage_limit(provider: str) -> dict[str, Any]:
    """Let a recovered account be probed immediately.

    This clears only the app's local outage marker. If the account is still
    limited, the next real call records the warning again and starts a fresh
    six-hour probe cooldown; no credential or provider state is changed.
    """
    if provider not in _PROVIDER_LABELS:
        raise HTTPException(status_code=404, detail="Không nhận ra model/provider")
    database.clear_provider_usage_limit(provider)
    event_bus.publish(
        "provider.usage_limit_cleared",
        source="user",
        payload={"provider": provider, "reason": "manual_retry"},
    )
    return {
        "status": "retry_enabled",
        "provider": provider,
        "label": _PROVIDER_LABELS[provider],
    }


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
            system_prompt, body, _FIDELITY_SCHEMA, stage="quality_review",
            project_id=project_id, step="Soát độ trung thành với nguồn",
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
    "de": "tieng Duc",
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
            # The timeline is the production source for the voice, while the
            # matching shot supplies the storyboard card. Keep both records
            # in the same language so reopening the project cannot show an
            # old Vietnamese card beside newly generated English audio.
            shot_id = (updated or {}).get("shot_id") or segment.get("shot_id")
            if shot_id:
                database.update_project_shot(int(shot_id), narration=text)
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
    return _finish_or_fallback_external_scene_job(job, message)


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

    The same socket is the Browser Bridge for page reads. There is no
    heartbeat on it: the browser puts an idle extension to sleep and the
    socket closes; a page read asked for meanwhile waits in the bridge's
    queue and is sent the moment the extension reconnects.
    """
    global _browser_extension_connections
    await websocket.accept()
    _browser_extension_connections += 1
    connection_id = uuid.uuid4().hex
    bridge = platform_connections.BRIDGE
    # An extension that never says hello is an older build: connected, and
    # unable to read pages until it is reloaded.
    bridge.register(connection_id)

    async def listen() -> None:
        # The extension speaks twice: a hello saying what it can do, and the
        # answer to a page it was asked to read.
        while True:
            try:
                message = await websocket.receive_json()
            except ValueError:
                continue
            except (WebSocketDisconnect, RuntimeError):
                return
            if not isinstance(message, dict):
                continue
            if message.get("type") == "hello":
                reported = str(message.get("browser") or "")[:40]
                # Named by the program holding the socket: Cốc Cốc reports
                # itself as "Google Chrome".
                peer = await asyncio.to_thread(
                    platform_connections.browser_of_peer, websocket.client.port if websocket.client else 0,
                )
                bridge.register(connection_id, {
                    "capabilities": [str(item) for item in message.get("capabilities") or []][:10],
                    "version": str(message.get("version") or "")[:20],
                    "browser": peer or reported,
                    "reported_browser": reported,
                    "sites": [str(item) for item in message.get("sites") or []][:20],
                })
            elif message.get("type") in {"page_read_result", "open_tab_result"}:
                bridge.resolve(str(message.get("request_id") or ""), {
                    "ok": bool(message.get("ok")),
                    "error": str(message.get("error") or "")[:500],
                    "result": message.get("result") if isinstance(message.get("result"), dict) else {},
                })

    listener = asyncio.create_task(listen())
    last_queued: dict[str, int] = {}
    last_checked = 0.0
    try:
        while not listener.done():
            if time.monotonic() - last_checked >= 2:
                last_checked = time.monotonic()
                for provider in database.BROWSER_SIDECAR_PROVIDERS:
                    count = database.count_queued_scene_generation_jobs(provider)
                    if count > 0 and count != last_queued.get(provider):
                        await websocket.send_json({"provider": provider, "queued": count})
                    last_queued[provider] = count
            for message in bridge.outbox(connection_id):
                await websocket.send_json(message)
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass
    finally:
        listener.cancel()
        bridge.unregister(connection_id)
        _browser_extension_connections = max(0, _browser_extension_connections - 1)


class ConnectionReadRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    session_id: str = Field(default="", max_length=120)


def _connection_action(action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return action()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/connections")
def list_platform_connections(view: Literal["full", "capabilities"] = "full") -> dict[str, Any]:
    """The Connection Manager: every marketplace, its status, and the bridge.

    `view=capabilities` is what an AI is shown - which platform can be read
    and how, with no paths, cookies or timestamps.
    """
    manager = platform_connections.manager()
    return manager.capabilities() if view == "capabilities" else manager.overview()


@app.post("/api/connections/read")
def read_product_page(payload: ConnectionReadRequest) -> dict[str, Any]:
    """ProductReader over the connections: read one listing, save nothing.

    Returns what the page shows - product fields and a slice of its text - or
    NEED_LOGIN / NEED_HUMAN_VERIFY / UNAVAILABLE with each platform's status.
    """
    if not platform_connections.site_of(payload.url):
        raise HTTPException(
            status_code=400,
            detail=f"Chỉ đọc qua kết nối cho các sàn: {', '.join(platform_connections.SITES)}",
        )
    outcome = platform_connections.manager().read(payload.url, session_id=payload.session_id.strip())
    return platform_connections.public_view(outcome)


@app.get("/api/connections/{platform}")
def get_platform_connection(platform: str) -> dict[str, Any]:
    manager = platform_connections.manager()
    return _connection_action(lambda: manager.connection(manager._platform(platform)))


@app.post("/api/connections/{platform}/connect")
def connect_platform(platform: str, use: str = Query(default="", max_length=20)) -> dict[str, Any]:
    """Kết nối / Đăng nhập lại.

    Shopee and TikTok Shop launch nothing: the answer lists the browsers that
    have the extension, for the person to choose one and sign in or pass a
    check there. `use=profile` opens the app's own profile instead, in a
    visible window, where the platform allows it (TikTok Shop). The others get
    their own profile in a window; the person signs in themselves - password,
    OTP, captcha - and the profile keeps that session across restarts.
    """
    return _connection_action(lambda: platform_connections.manager().connect(platform, use))


@app.post("/api/connections/{platform}/open")
def open_platform_in_browser(platform: str, bridge: str = Query(default="", max_length=40)) -> dict[str, Any]:
    """Open the platform's sign-in page as a normal tab of the person's browser.

    Sent to the YT Factory extension in the browser the person chose; nothing
    is launched by the app. The person signs in there as they always do.
    """
    return _connection_action(lambda: platform_connections.manager().open_in_browser(platform, bridge))


@app.post("/api/connections/{platform}/check")
def check_platform_connection(platform: str, bridge: str = Query(default="", max_length=40)) -> dict[str, Any]:
    """Kiểm tra: is the platform's session signed in?

    Shopee is checked through the person's browser (the extension reads its
    home page once); the others by opening their own profile once.
    """
    return _connection_action(lambda: platform_connections.manager().check(platform, bridge))


@app.post("/api/connections/{platform}/disconnect")
def disconnect_platform(platform: str) -> dict[str, Any]:
    """Ngắt kết nối: delete that platform's session from this machine."""
    return _connection_action(lambda: platform_connections.manager().disconnect(platform))


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
    voxcpm_ready, voxcpm_detail = voxcpm_runtime_status()
    if not voxcpm_ready:
        raise HTTPException(status_code=400, detail=f"VoxCPM chưa sẵn sàng: {voxcpm_detail}")
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
    script = database.get_latest_project_script(project_id, variant=payload.variant)
    if not script:
        raise HTTPException(
            status_code=400,
            detail=(
                "Dự án chưa có kịch bản bản short — hãy viết nó ở mục Video ngắn."
                if payload.variant == "short" else "Project chưa có kịch bản"
            ),
        )
    if not database.list_project_timeline(project_id, script_id=int(script["id"])):
        raise HTTPException(status_code=400, detail="Project chưa có timeline")

    provider = payload.provider.strip().lower()
    allowed = {
        "voiceover": {"dry_run", "preview", "mock", "pyvideotrans", "py_video_trans", "edge_tts", "voxcpm"},
        "voiceover_segment": {"dry_run", "preview", "mock", "pyvideotrans", "py_video_trans", "edge_tts", "voxcpm"},
        "source_visuals": {"dry_run", "preview", "mock", "source_video", "source", "local_source"},
        "render_short": {"ffmpeg_builtin"},
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
    if payload.job_type == "render_short":
        readiness = _short_lane_progress(project_id)
        if not readiness.get("can_render"):
            detail = " · ".join(readiness.get("issues") or []) or "chưa đủ hình và voice"
            raise HTTPException(status_code=400, detail=f"Short chưa thể dựng: {detail}")
    if payload.job_type == "render" and provider not in {"dry_run", "preview", "mock"}:
        readiness = _render_readiness(project_id)
        if not readiness.get("can_render"):
            detail = " · ".join(readiness.get("issues") or []) or "timeline chưa hoàn chỉnh"
            raise HTTPException(status_code=400, detail=f"Video chưa thể dựng: {detail}")
    if provider in {"pyvideotrans", "py_video_trans"} and not PYVIDEOTRANS_COMMAND:
        raise HTTPException(status_code=400, detail="Chưa cấu hình PYVIDEOTRANS_COMMAND trong .env")
    if provider in {"pyvideotrans", "py_video_trans"} and not settings.pyvideotrans_runtime_status()[1]:
        raise HTTPException(status_code=400, detail="Môi trường pyVideoTrans chưa hoàn tất dependency")
    if provider == "voxcpm":
        ready, detail = voxcpm_runtime_status()
        if not ready:
            raise HTTPException(status_code=400, detail=f"VoxCPM chưa sẵn sàng: {detail}")
    if provider == "edge_tts" and not EDGE_TTS_RUNTIME_READY:
        raise HTTPException(status_code=400, detail="Edge TTS chưa sẵn sàng trong môi trường local")
    if provider in {"ffmpeg", "ffmpeg_command"} and not FFMPEG_RENDER_COMMAND:
        raise HTTPException(status_code=400, detail="Chưa cấu hình FFMPEG_RENDER_COMMAND trong .env")
    if payload.job_type == "source_visuals" and provider not in {"dry_run", "preview", "mock"}:
        # Refused before the job is created, so an audio-only project never
        # collects a queue of jobs that cannot succeed.
        source_kind = str(
            (database.get_video(str(project.get("youtube_video_id") or "")) or {}).get("media_kind") or ""
        ).strip().lower()
        if source_kind and source_kind != "video":
            raise HTTPException(
                status_code=400,
                detail=(
                    "Nguồn của dự án này chỉ có tiếng, không có hình — không cắt cảnh được. "
                    "Hãy dùng luồng lời bình: tạo giọng đọc rồi gắn hình của bạn cho từng cảnh."
                ),
            )
    if payload.job_type == "source_visuals" and provider not in {"dry_run", "preview", "mock"} and not ffmpeg_available(FFMPEG_BINARY):
        raise HTTPException(status_code=400, detail=f"Không tìm thấy FFmpeg ({FFMPEG_BINARY}) trên máy")
    if provider == "ffmpeg_builtin" and not ffmpeg_available(FFMPEG_BINARY):
        raise HTTPException(status_code=400, detail=f"Không tìm thấy FFmpeg ({FFMPEG_BINARY}) trên máy")
    if settings.GPU_ONLY and payload.job_type in {"source_visuals", "render", "render_short", "director_production"} and provider not in {"dry_run", "preview", "mock"} and not nvenc_available(FFMPEG_BINARY):
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


def _publish_checklist(
    project_id: int,
    variant: str,
    *,
    output_profile: str,
    platform: str,
    title: str = "",
    description: str = "",
    tags: list[str] | None = None,
    reuse_verdict: str = "",
    managed_channel_id: int | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Gather every fact that decides whether this video may go out.

    Each of these was already knowable somewhere; none of them was gathered,
    so each was discovered separately and usually after the upload.
    """
    project = database.get_production_project(project_id) or {}
    script = database.get_latest_project_script(project_id, variant=variant)
    timeline = (
        database.list_project_timeline(project_id, script_id=int(script["id"]))
        if script else []
    )
    try:
        _, video_path = _publication_video_path(project_id, variant)
    except HTTPException:
        video_path = None
    frame = video_frame_size(video_path, FFMPEG_BINARY) if video_path else None
    selected = next(
        (item for item in database.list_project_thumbnails(project_id) if item.get("selected") and item.get("video_variant", "long") == variant),
        None,
    )
    source_video = database.get_video(str(project.get("youtube_video_id") or "")) or {}
    checks = publish_gate.evaluate(
        timeline=timeline,
        script=script,
        video_path=video_path,
        frame_size=frame,
        output_profile=output_profile,
        title=title or str((script or {}).get("script_title") or ""),
        description=description,
        tags=tags or [],
        thumbnail_path=str((selected or {}).get("file_path") or ""),
        platform=platform,
        reuse_verdict=reuse_verdict,
        source_title=str(source_video.get("title") or ""),
        youtube_configured=youtube_oauth.is_configured(),
        # This channel's account, not the app's: with several channels linked
        # to different Google accounts, "someone is signed in" says nothing
        # about whether this one is.
        youtube_connected=bool(oauth_status(managed_channel_id).get("connected")),
    )
    return checks, {
        "scene_count": len(timeline),
        "frame_size": list(frame) if frame else [],
        "video_path": str(video_path or ""),
    }


class PublishChecklistRequest(BaseModel):
    video_variant: Literal["long", "short"] = "long"
    managed_channel_id: int | None = Field(default=None, ge=1)
    platform: Literal["youtube", "tiktok", "facebook", "instagram"] = "youtube"
    output_profile: Literal[
        "youtube_landscape", "youtube_shorts", "instagram_reels",
        "tiktok", "facebook_reels", "facebook_feed",
    ] = "youtube_landscape"
    title: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list)
    reuse_verdict: str = Field(default="", max_length=16)


class PlatformCopyRequest(BaseModel):
    video_variant: Literal["long", "short"] = "long"
    platforms: list[Literal["youtube", "tiktok", "facebook", "instagram"]] = Field(
        default_factory=lambda: ["youtube", "tiktok", "facebook", "instagram"]
    )
    title: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list)


def _reattach_project_voice(project_id: int, variant: str = "long") -> dict[str, Any]:
    """Give a rebuilt timeline back the voice this project already made.

    Audio hangs off a timeline row, so replacing the rows loses it even
    though the files are still there. They are matched back by the words they
    were spoken from - never by scene number, which a rebuild renumbers.
    """
    script = database.get_latest_project_script(project_id, variant=variant)
    if not script:
        return {"attached": 0, "matched": [], "missing": []}
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    layout = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)
    library = voice_library.index_voices(layout["work"] / "voiceover", layout["audio"])
    matched, missing = voice_library.match_timeline(timeline, library)
    for item in matched:
        duration = media_duration_seconds(Path(item["audio_path"]), FFMPEG_BINARY)
        database.update_project_timeline_segment(
            item["segment_id"],
            audio_path=item["audio_path"],
            duration_seconds=max(1, int(math.ceil(duration))) if duration else None,
        )
    if matched:
        database.resync_timeline_segment_states(project_id)
    return {
        "attached": len(matched),
        "matched": matched,
        "missing": missing,
        "library_size": len(library),
    }


class ReattachVoiceRequest(BaseModel):
    video_variant: Literal["long", "short"] = "long"


class AttachGeneratedVoiceRequest(BaseModel):
    voice_key: str = Field(min_length=1, max_length=20_000)


@app.post("/api/projects/{project_id}/timeline/reattach-voice")
def reattach_project_voice(
    project_id: int, payload: ReattachVoiceRequest = ReattachVoiceRequest()
) -> dict[str, Any]:
    """Attach voice this project has already generated to the scenes that need it."""
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return _reattach_project_voice(project_id, payload.video_variant)


@app.get("/api/projects/{project_id}/voice-library")
def list_project_voice_library(project_id: int) -> dict[str, Any]:
    """List only the generated audio files belonging to this project."""
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    layout = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)
    library = voice_library.index_voices(layout["work"] / "voiceover", layout["audio"])
    return {
        "voices": [
            {
                "key": key,
                "text": str(item.get("text") or ""),
                "filename": Path(str(item.get("audio_path") or "")).name,
            }
            for key, item in library.items()
        ]
    }


@app.post("/api/timeline/{segment_id}/attach-generated-voice")
def attach_generated_voice_to_timeline(
    segment_id: int, payload: AttachGeneratedVoiceRequest
) -> dict[str, Any]:
    """Manually attach one voice from this project's generated voice library."""
    segment = database.get_project_timeline_segment(segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Không tìm thấy segment timeline")
    project_id = int(segment["project_id"])
    layout = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)
    library = voice_library.index_voices(layout["work"] / "voiceover", layout["audio"])
    selected = library.get(payload.voice_key)
    if not selected:
        raise HTTPException(status_code=404, detail="Không tìm thấy file voice đã tạo trong project")
    database.update_project_timeline_segment(segment_id, audio_path=str(selected["audio_path"]))
    database.resync_timeline_segment_states(project_id)
    return {"status": "attached", "segment": database.get_project_timeline_segment(segment_id)}


@app.get("/api/projects/{project_id}/log")
def project_operations_log(project_id: int) -> dict[str, Any]:
    """Everything that happened to this project, in order.

    Assembled from rows that already existed - jobs, scripts, publications,
    the cost ledger - rather than stored separately, which is also why it is
    still there after the app is reopened.
    """
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    log = project_log.build(
        project=project,
        source_video=database.get_video(str(project.get("youtube_video_id") or "")),
        scripts=database.list_project_scripts(project_id, variant=None),
        jobs=database.list_project_jobs(project_id, limit=400),
        publications=database.list_project_publications(project_id=project_id),
        cost_usd=database.project_provider_cost(project_id),
    )
    return {**log, "stage_status": project_log.stage_status(log)}


@app.post("/api/projects/{project_id}/platform-copy")
def project_platform_copy(project_id: int, payload: PlatformCopyRequest) -> dict[str, Any]:
    """One video's words, shaped for each place it is going.

    Same substance everywhere; what changes is length, where the hashtags sit
    and which call to action that platform actually has. Posting one caption
    to all of them is why a reup lands on one and vanishes on the rest.
    """
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id, variant=payload.video_variant)
    bundle_writer = (database.get_video_analysis(
        str((database.get_production_project(project_id) or {}).get("youtube_video_id") or ""),
        analysis_type="writer",
    ) or {}).get("result", {})

    title = payload.title or str((script or {}).get("script_title") or "")
    description = payload.description or str(bundle_writer.get("new_description") or "")
    tags = payload.tags or list(bundle_writer.get("hashtags") or [])
    return {
        "variants": platform_copy.build_all(
            list(payload.platforms),
            title=title,
            description=description,
            tags=tags,
            # Not the script's cta: that is the closing line of the story
            # ("Night settled over the forest..."), not a call to action.
            # Each platform has its own, and they are not interchangeable.
            cta="",
            is_short=payload.video_variant == "short",
        ),
    }


@app.post("/api/projects/{project_id}/publish-checklist")
def project_publish_checklist(
    project_id: int, payload: PublishChecklistRequest
) -> dict[str, Any]:
    """What is still missing before this video may be published."""
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    checks, facts = _publish_checklist(
        project_id, payload.video_variant,
        output_profile=payload.output_profile,
        platform=payload.platform,
        title=payload.title,
        description=payload.description,
        tags=payload.tags,
        reuse_verdict=payload.reuse_verdict,
        managed_channel_id=payload.managed_channel_id,
    )
    return {
        "ready": publish_gate.is_ready(checks),
        "checks": checks,
        "blockers": publish_gate.blockers(checks),
        "warnings": publish_gate.warnings(checks),
        **facts,
    }


def _publication_video_path(project_id: int, variant: str) -> tuple[dict[str, Any], Path]:
    """Return the approved script and its rendered file for this destination."""
    script = database.get_latest_project_script(project_id, variant=variant)
    if not script or script.get("status") != "approved":
        label = "Short" if variant == "short" else "Kịch bản"
        raise HTTPException(status_code=400, detail=f"{label} chưa được duyệt; hãy duyệt trước khi xuất bản")
    if variant == "long":
        return script, ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["exports"] / "final.mp4"
    for job in database.list_project_jobs(project_id, limit=100):
        if (
            int(job.get("script_id") or 0) == int(script["id"])
            and job.get("job_type") == "render_short"
            and job.get("status") == "completed"
        ):
            path = Path(str(job.get("output_path") or ""))
            if path.is_file():
                return script, path
    raise HTTPException(status_code=400, detail="Short chưa được dựng xong; hãy dựng Short trước khi xuất bản")


def _build_manual_publication_package(
    publication: dict[str, Any],
    channel: dict[str, Any] | None,
) -> Path:
    """Create a self-contained handoff zip for platforms without an API link."""
    source = Path(str(publication.get("local_file_path") or "")).expanduser()
    if not source.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy MP4 của gói đăng")
    project_id = int(publication["project_id"])
    platform = str(publication.get("platform") or "manual").strip().lower()
    package_dir = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["exports"] / "manual_publish"
    package_dir.mkdir(parents=True, exist_ok=True)
    archive = package_dir / f"publication-{int(publication['id'])}-{platform}.zip"
    tags = [str(item).lstrip("#").strip() for item in (publication.get("tags") or []) if str(item).strip()]
    hashtags = " ".join(f"#{item}" for item in tags)
    destination = {
        "platform": platform,
        "channel_name": str((channel or {}).get("name") or ""),
        "channel_url": str((channel or {}).get("channel_url") or ""),
        "output_profile": str(publication.get("output_profile") or ""),
        "video_variant": str(publication.get("video_variant") or "long"),
        "scheduled_at": publication.get("scheduled_at"),
    }
    caption = "\n".join((
        str(publication.get("title") or "").strip(),
        "",
        str(publication.get("description") or "").strip(),
        "",
        hashtags,
    )).strip() + "\n"
    instructions = "\n".join((
        f"Nền tảng: {platform}",
        f"Kênh đích: {destination['channel_name'] or '(chưa đặt tên)'}",
        f"Định dạng: {destination['output_profile']}",
        f"Loại video: {destination['video_variant']}",
        "",
        "1. Tải file video MP4 trong gói lên đúng kênh đích.",
        "2. Sao chép tiêu đề, mô tả và hashtag từ caption.txt.",
        "3. Dùng thumbnail trong gói nếu nền tảng cho phép.",
        "4. Kiểm tra lại quyền riêng tư và lịch đăng trước khi xác nhận.",
    )) + "\n"
    thumbnail = Path(str(publication.get("thumbnail_path") or "")).expanduser()
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
            package.write(source, arcname=f"video{source.suffix.lower() or '.mp4'}")
            package.writestr("caption.txt", caption)
            package.writestr("metadata.json", json.dumps({
                "publication_id": int(publication["id"]),
                "title": publication.get("title") or "",
                "description": publication.get("description") or "",
                "tags": tags,
                "destination": destination,
            }, ensure_ascii=False, indent=2))
            package.writestr("README.txt", instructions)
            if thumbnail.is_file():
                package.write(thumbnail, arcname=f"thumbnail{thumbnail.suffix.lower()}")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Không tạo được gói đăng: {exc}") from exc
    return archive


@app.get("/api/publisher/status")
def publisher_status() -> dict[str, Any]:
    return publisher_worker.status()


@app.get("/api/publisher/queue")
def publisher_queue(project_id: int | None = Query(default=None, ge=1)) -> dict[str, Any]:
    return {
        "status": publisher_worker.status(),
        "publications": database.list_project_publications(project_id=project_id),
    }


@app.get("/api/publications/{publication_id}/manual-package")
def download_manual_publication_package(publication_id: int) -> FileResponse:
    """Download the MP4 and final copy for a ready-to-post social destination."""
    publication = database.get_project_publication(publication_id)
    if not publication:
        raise HTTPException(status_code=404, detail="Không tìm thấy publication")
    platform = str(publication.get("platform") or "youtube").strip().lower()
    if platform == "youtube":
        raise HTTPException(status_code=400, detail="YouTube dùng hàng đợi upload, không cần gói đăng thủ công")
    if publication.get("status") not in {"ready_manual", "completed"}:
        raise HTTPException(status_code=409, detail="Gói chỉ sẵn sàng sau khi publication được chuẩn bị")
    channel_id = publication.get("managed_channel_id")
    channel = database.get_managed_channel(int(channel_id)) if channel_id else None
    archive = _build_manual_publication_package(publication, channel)
    return FileResponse(
        archive,
        media_type="application/zip",
        filename=f"{platform}-publication-{publication_id}.zip",
    )


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

    managed_id = payload.managed_channel_id or project.get("managed_channel_id")
    channel = database.get_managed_channel(int(managed_id)) if managed_id else None
    if managed_id and not channel:
        raise HTTPException(status_code=400, detail="Selected publication channel does not exist")
    platform = payload.platform or str((channel or {}).get("platform") or "youtube")
    if channel and payload.platform and platform != str(channel.get("platform") or "youtube"):
        raise HTTPException(status_code=400, detail="Selected channel belongs to another platform")
    output_profile = payload.output_profile or str((channel or {}).get("output_profile") or "")
    if not output_profile:
        output_profile = "youtube_shorts" if payload.video_variant == "short" else "youtube_landscape"

    selected_thumbnail = next(
        (item for item in database.list_project_thumbnails(project_id) if item.get("selected") and item.get("video_variant", "long") == payload.video_variant),
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

    # Publishing is the one step that cannot be taken back, so every
    # precondition is checked together here rather than being discovered one
    # at a time after the upload. The shape of the file is only one of them.
    checks, _ = _publish_checklist(
        project_id,
        payload.video_variant,
        output_profile=output_profile,
        platform=platform,
        title=payload.title,
        description=payload.description,
        tags=list(payload.tags or []),
        reuse_verdict=payload.reuse_verdict,
        managed_channel_id=int(managed_id) if managed_id else None,
    )
    stopped = publish_gate.blockers(checks)
    if stopped and not payload.override_checklist:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Chưa đủ điều kiện để đăng.",
                "blockers": stopped,
                "checks": checks,
            },
        )

    # Only now, once the whole list has been reported, do the individual
    # guards run - they would otherwise fire first and hide the rest.
    script, final_path = _publication_video_path(project_id, payload.video_variant)
    if not final_path.is_file():
        raise HTTPException(status_code=400, detail="Project chưa có final.mp4; hãy render và Quality Check trước")

    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    report = build_quality_report(timeline, str(final_path), FFMPEG_BINARY, thumbnail_path)
    if report["status"] != "pass" and (
        platform == "youtube"
        or any(key != "has_thumbnail" for key, passed in report["checks"].items() if not passed)
    ):
        failed = ", ".join(key for key, passed in report["checks"].items() if not passed)
        raise HTTPException(
            status_code=400,
            detail=f"Quality Check chưa đạt: {failed}. Sửa lỗi hoặc tạo/chọn thumbnail trước khi xuất bản.",
        )

    # A valid Google token is not sufficient when the workspace contains more
    # than one channel.  Verify the identity now, before a row enters the
    # worker queue, so an upload can never quietly land on another channel.
    if platform == "youtube":
        if not managed_id or not channel:
            raise HTTPException(status_code=400, detail="Hãy chọn một kênh YouTube để đăng tự động.")
        account = oauth_status(int(managed_id))
        if not account.get("configured"):
            raise HTTPException(status_code=400, detail="Chưa cấu hình YouTube OAuth trong Cài đặt · Kết nối.")
        if not account.get("connected"):
            raise HTTPException(
                status_code=400,
                detail=f"Kênh “{channel.get('name') or managed_id}” chưa đăng nhập YouTube. Bấm “Đăng nhập kênh này” rồi thử lại.",
            )
        expected_id = str(channel.get("youtube_channel_id") or "").strip()
        try:
            authorized = publisher_worker.publisher.list_authorized_channels(int(managed_id))
        except (OAuthError, PublisherError) as exc:
            raise _api_error(exc) from exc
        actual_ids = {str(item.get("id") or "").strip() for item in authorized}
        if expected_id and expected_id not in actual_ids:
            raise HTTPException(
                status_code=400,
                detail=(f"Tài khoản đang đăng nhập không phải kênh “{channel.get('name') or managed_id}”. "
                        "Bấm “Đăng nhập kênh này”, chọn đúng tài khoản/kênh Google, rồi đăng lại."),
            )
        if not actual_ids:
            raise HTTPException(status_code=400, detail="Google không trả về kênh YouTube nào cho tài khoản đã đăng nhập.")

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
            platform=platform,
            output_profile=output_profile,
            video_variant=payload.video_variant,
            status="queued" if platform == "youtube" else "ready_manual",
        )
    except (ValueError, PublisherError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "queued" if platform == "youtube" else "ready_manual",
        "publication": publication,
        "publisher": publisher_worker.status(),
    }


@app.post("/api/publications/{publication_id}/cancel")
def cancel_publication(publication_id: int) -> dict[str, Any]:
    publication = database.get_project_publication(publication_id)
    if not publication:
        raise HTTPException(status_code=404, detail="Không tìm thấy publication")
    if publication.get("status") not in {"queued", "ready_manual"}:
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
    return {"status": str((retried or {}).get("status") or "queued"), "publication": retried, "publisher": publisher_worker.status()}


_REUSE_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["low", "medium", "high"]},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "policy": {"type": "string"},
                    "detail": {"type": "string"},
                    "fix": {"type": "string"},
                },
                "required": ["severity", "policy", "detail", "fix"],
            },
        },
    },
    "required": ["verdict", "summary", "findings"],
}


class CopyrightCheckRequest(BaseModel):
    video_variant: Literal["long", "short"] = "long"
    use_model: bool = True
    publish_title: str = Field(default="", max_length=300)


@app.post("/api/projects/{project_id}/copyright-check")
def check_project_copyright(
    project_id: int,
    payload: CopyrightCheckRequest = CopyrightCheckRequest(),
) -> dict[str, Any]:
    """Weigh what is left of the source against the platform's reuse policy.

    Measured first, judged second. The numbers - how many seconds of picture
    came straight from the source, whether its audio came with them, whether
    the narration is its transcript in other words - decide most of this on
    their own, and a model asked without them could only guess.
    """
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id, variant=payload.video_variant)
    if not script:
        raise HTTPException(status_code=400, detail="Dự án chưa có kịch bản cho bản này")
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    if not timeline:
        raise HTTPException(status_code=400, detail="Dự án chưa có timeline để kiểm tra")

    source_video = database.get_video(str(project.get("youtube_video_id") or "")) or {}
    transcript = database.get_transcript(str(project.get("youtube_video_id") or "")) or {}
    settings_row = database.get_project_render_settings(project_id) or {}
    facts = measure_reuse(
        timeline,
        source_video=source_video,
        # content_text, not text: reading the wrong key made the narration
        # comparison silently vacuous, reporting 0% overlap for everything.
        transcript_text=str(transcript.get("content_text") or ""),
        publish_title=payload.publish_title or str(script.get("script_title") or ""),
        publish_language=str(settings_row.get("publish_language") or ""),
        ffmpeg_binary=FFMPEG_BINARY,
    )
    findings = rule_findings(facts)
    verdict = rule_verdict(findings)

    model_review: dict[str, Any] = {}
    if payload.use_model:
        try:
            model_review = _call_orchestrator_json(
                (
                    "Ban la nguoi soat chinh sach cua kenh YouTube. Duoc cung cap SO DO thuc te cua "
                    "mot video lam lai tu video cua nguoi khac, hay danh gia rui ro theo chinh sach "
                    "'noi dung dung lai' (reused content), ban quyen va Content ID cua YouTube.\n"
                    "Khong bia them so lieu: chi dua tren so da do. Neu so lieu chua du de ket luan "
                    "mot diem nao, hay noi ro la chua du.\n"
                    "'verdict': 'high' neu co kha nang bi tu choi kiem tien hoac go, 'medium' neu can "
                    "sua truoc khi dang, 'low' neu dang duoc.\n"
                    "Moi 'findings' phai neu ro dieu khoan lien quan va cach sua cu the. "
                    "Viet bang tieng Viet."
                ),
                json.dumps(facts, ensure_ascii=False),
                _REUSE_REVIEW_SCHEMA,
                stage="quality",
            )
        except Exception as exc:  # noqa: BLE001 - the measured verdict still stands
            model_review = {"error": str(exc)[:300]}

    # The model may raise the verdict but never lower it: the measurements are
    # facts about the files, and a reassuring answer cannot make reused
    # footage stop being reused footage.
    order = {"low": 0, "medium": 1, "high": 2}
    model_verdict = str(model_review.get("verdict") or "")
    if order.get(model_verdict, -1) > order[verdict]:
        verdict = model_verdict

    return {
        "verdict": verdict,
        "facts": facts,
        "findings": findings,
        "model_review": model_review,
        "checked_variant": payload.video_variant,
    }


@app.get("/api/projects/{project_id}/quality-check")
def get_project_quality_check(project_id: int) -> dict[str, Any]:
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id)
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"])) if script else []
    final_path = ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["exports"] / "final.mp4"
    selected_thumbnail = next(
        (item for item in database.list_project_thumbnails(project_id) if item.get("selected") and item.get("video_variant", "long") == "long"),
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
        "pyvideotrans_cuda_ready": settings.pyvideotrans_runtime_status(wait=False)[0],
        "pyvideotrans_runtime_ready": settings.pyvideotrans_runtime_status(wait=False)[1],
        "pyvideotrans_workdir_configured": bool(PYVIDEOTRANS_WORKDIR),
        "pyvideotrans_voice_role": PYVIDEOTRANS_VOICE_ROLE,
        "voxcpm_runtime_ready": voxcpm_runtime_status(wait=False)[0],
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


def _transcribe_video_source(
    video: dict[str, Any], video_id: str, *, language: str | None = None,
) -> dict[str, Any]:
    """Prefer a source file already attached to the video over another download."""
    local_media = Path(str(video.get("local_media_path") or ""))
    if local_media.is_file():
        return transcribe_local_file(str(local_media), video_id, language=language)
    return transcribe_video(str(video["video_url"]), video_id, language=language)


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
    try:
        result = _transcribe_video_source(video, video_id, language=payload.language or None)
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
    database.mark_video_downloaded(video_id, str(path), _source_media_kind(path))
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
    database.mark_video_downloaded(video_id, str(path), _source_media_kind(path))
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


def _available_text_providers(*, include_local: bool = False) -> list[str]:
    """Provider order used when a step-level selector is set to Auto."""
    anthropic_key, _ = settings.anthropic_config()
    openai_key, _ = settings.openai_config()
    codex = codex_cli_status()
    claude_code = claude_code_cli_status()
    antigravity = antigravity_cli_status()
    candidates: list[tuple[str, bool]] = [
        ("codex_cli", bool(codex.get("logged_in"))),
        ("claude_code_cli", bool(claude_code.get("logged_in"))),
        ("antigravity", bool(antigravity.get("logged_in"))),
        ("anthropic_claude", bool(anthropic_key)),
        ("openai_gpt", bool(openai_key)),
    ]
    if include_local:
        candidates.insert(0, ("local_metadata", True))
    return [provider for provider, available in candidates if available]


def _resolve_auto_text_provider(provider: str | None, *, include_local: bool = False) -> str:
    name = str(provider or "").strip().lower()
    if name and name != "auto":
        # An agent name ("astra", "claude") is as valid a choice as a runtime
        # name; resolved here once so no resolver downstream has to guess.
        return orchestrator_runtime.runtime_id(name)
    available = _available_text_providers(include_local=include_local)
    if available:
        return available[0]
    if include_local:
        return "local_metadata"
    raise HTTPException(
        status_code=400,
        detail="Chưa có AI text nào sẵn sàng cho chế độ Auto. Hãy đăng nhập Astra/ChatGPT/Claude hoặc cấu hình API key.",
    )


@app.post("/api/videos/{video_id}/analyze")
def analyze_video(
    video_id: str,
    provider: str | None = Query(default=None),
) -> dict[str, Any]:
    video = database.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    try:
        selected_provider = _resolve_auto_text_provider(provider, include_local=True)
        active_analyzer = resolve_analyzer(selected_provider)
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
            whisper_result = _transcribe_video_source(video, video_id)
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
        selected_provider = _resolve_auto_text_provider(payload.provider, include_local=False)
        active_writer = resolve_writer(selected_provider)
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
    """The model list every step selector offers.

    Built from the same readiness gate the router uses, so a model that is
    signed in but out of quota is offered as unavailable with the reason
    attached, instead of being picked and failing a minute later.
    """
    providers: list[dict[str, Any]] = [
        {
            "provider": "auto",
            "label": "Auto · AI điều phối tự chọn",
            "available": bool(_available_text_providers(include_local=True)),
            "detail": "App chọn AI còn chạy được theo chính sách của công đoạn.",
            "blocked_reason": "",
        },
        {
            "provider": "local_metadata",
            "label": "Local · không cần API key",
            "available": True,
            "detail": "Chạy trong máy, không gọi AI nào.",
            "blocked_reason": "",
        },
    ]
    providers.extend(orchestrator_runtime.text_providers(
        database,
        statuses={
            "codex_cli": codex_cli_status,
            "claude_code_cli": claude_code_cli_status,
            "antigravity": antigravity_cli_status,
        },
    ))
    return providers


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
    provider = _resolve_auto_text_provider(payload.provider or "local_metadata", include_local=True)
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
        provider=provider,
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


# ---------------------------------------------------------------------------
# Durable multi-agent automation (WORK BRIEF phases 3-7)
# ---------------------------------------------------------------------------

# LEGACY: the scores below are asked of a model with no data behind them.
# New research uses research_evidence (Evidence → Insight, numbers by rule).
_AGENT_RESEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"},
        "summary": {"type": "string"},
        "target_audience": {"type": "string"},
        "angle": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "trend_score": {"type": "integer"},
        "competition_score": {"type": "integer"},
        "opportunity_score": {"type": "integer"},
        "facts_to_verify": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["topic", "summary", "target_audience", "angle", "keywords", "facts_to_verify"],
}
_AGENT_SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "hook": {"type": "string"},
        "intro": {"type": "string"},
        "main_content": {"type": "string"},
        "cta": {"type": "string"},
    },
    "required": ["title", "hook", "intro", "main_content", "cta"],
}
_AGENT_DIRECTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "scene_index": {"type": "integer"},
                    "section": {"type": "string"},
                    "narration": {"type": "string"},
                    "visual_prompt": {"type": "string"},
                    "duration": {"type": "integer"},
                    "camera": {"type": "string"},
                    "motion": {"type": "string"},
                    "media_type": {"type": "string", "enum": ["image", "gif", "video"]},
                },
                "required": ["scene_index", "narration", "visual_prompt", "duration", "media_type"],
            },
        }
    },
    "required": ["scenes"],
}
_AGENT_MEDIA_SCHEMA = {
    "type": "object",
    "properties": {
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "integer"},
                    "kind": {"type": "string", "enum": ["image", "gif", "video"]},
                    "treatment": {
                        "type": "string",
                        "enum": ["real_world", "data_graphics", "illustration"],
                    },
                    "reason": {"type": "string"},
                },
                "required": ["segment_id", "kind", "treatment", "reason"],
            },
        }
    },
    "required": ["scenes"],
}
_AGENT_QC_SCHEMA = {
    "type": "object",
    "properties": {
        "approved": {"type": "boolean"},
        "score": {"type": "integer", "minimum": 0, "maximum": 10},
        "issues": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"},
    },
    "required": ["approved", "score", "issues", "note"],
}
_AGENT_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "approved": {"type": "boolean"},
        "score": {"type": "integer", "minimum": 0, "maximum": 10},
        "note": {"type": "string"},
        "issues": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["approved", "score", "note", "issues"],
}


def _call_specific_agent_json(
    agent: str,
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    calls = {
        "codex_cli": call_codex_json,
        "claude_code_cli": call_claude_code_cli_json,
        "antigravity": call_antigravity_json,
    }
    runtime = orchestrator_runtime.runtime_id(agent)
    if runtime not in calls:
        raise LlmError(f"Agent không được hỗ trợ: {agent}")
    return calls[runtime](system_prompt, user_prompt, schema)


def _latest_scene_jobs_by_segment(scene_jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the newest attempt for each timeline segment without erasing history.

    A failed scene remains useful audit evidence, but it must stop blocking QC
    after a newer replacement has passed. Database callers normally return
    newest-first; comparing ids keeps this helper correct for injected/test
    data in any order.
    """
    latest: dict[int, dict[str, Any]] = {}
    for job in scene_jobs:
        segment_id = int(job.get("timeline_segment_id") or 0)
        if not segment_id:
            continue
        current = latest.get(segment_id)
        if current is None or int(job.get("id") or 0) > int(current.get("id") or 0):
            latest[segment_id] = job
    return list(latest.values())


def _provider_runtime_states() -> dict[str, dict[str, Any]]:
    gflow = gflow_cli_status()
    antigravity = antigravity_cli_status()
    runway_key, _ = settings.runway_config()
    openai_key, _ = settings.openai_config()
    gemini_key, _, _ = settings.gemini_config()
    states: dict[str, dict[str, Any]] = {}
    for descriptor in scene_provider_gateway.descriptors():
        state = dict(database.get_scene_provider_state(descriptor.key))
        available = not bool(state.get("circuit_open"))
        reason = str(state.get("last_error") or "")
        usage_limit = database.get_provider_usage_limit(descriptor.key)
        if usage_limits.limit_state(usage_limit)["blocking"]:
            available = False
            reason = str(usage_limit.get("message") or "usage_limit")
        if descriptor.key == "runway" and not runway_key:
            available, reason = False, "missing_api_key"
        elif descriptor.key == "openai_image" and not openai_key:
            available, reason = False, "missing_api_key"
        elif descriptor.key in {"gemini_image", "gemini_veo"} and not gemini_key:
            available, reason = False, "missing_api_key"
        elif descriptor.key in {"gflow_cli", "gflow_image"} and not gflow.get("logged_in"):
            available, reason = False, "gflow_not_logged_in"
        elif descriptor.key == "antigravity_image":
            if not (antigravity.get("logged_in") or antigravity.get("ready")):
                available, reason = False, "antigravity_not_ready"
            elif not _sidecar_recently_polled(descriptor.key):
                # A logged-in CLI is not a running worker. Jobs for this
                # provider are pulled by a sidecar; with none polling, they
                # sit queued forever and the pipeline stalls with no error.
                available, reason = False, "antigravity_sidecar_not_running"
        elif descriptor.key == "motion_graphics":
            composer_ok, composer_detail = motion_composer_ready()
            if not composer_ok:
                available, reason = False, composer_detail
            elif not ffmpeg_available(FFMPEG_BINARY):
                available, reason = False, "ffmpeg_not_available"
        elif descriptor.key == "stock_footage" and not ffmpeg_available(FFMPEG_BINARY):
            # The archives hand over a whole film; FFmpeg is what turns it
            # into one scene-length clip, so without it there is no output.
            available, reason = False, "ffmpeg_not_available"
        elif descriptor.key in database.BROWSER_SIDECAR_PROVIDERS and not (
            _browser_extension_connections > 0 or _sidecar_recently_polled(descriptor.key)
        ):
            # There are two ways to drive a logged-in site, and only one of
            # them is the browser extension. web_video_sidecar.py drives the
            # same sites with Playwright and its own saved session, and it
            # pulls jobs from the same queue — asking only about the extension
            # declared those providers dead while their sidecar was working.
            available, reason = (
                False,
                "browser_extension_not_connected"
                if descriptor.key not in PLAYWRIGHT_SIDECAR_PROVIDERS
                else "no_browser_worker",
            )
        state.update({"available": available, "reason": reason})
        states[descriptor.key] = state
    return states


def _paid_api_allowed() -> bool:
    return bool(settings.automation_policy().get("allow_paid_apis", False))


def _subscription_media_allowed() -> bool:
    return bool(settings.automation_policy().get("allow_subscription_media", True))


def _billing_route_policy(**overrides: Any) -> ProviderRoutePolicy:
    """Turn the saved automation policy into routing rules, in one place.

    Every caller that routes a capability goes through here, so a policy the
    user saved cannot be honoured on one code path and ignored on another.
    """
    return ProviderRoutePolicy(
        allow_api_billing=_paid_api_allowed(),
        allow_subscription_billing=_subscription_media_allowed(),
        **overrides,
    )


PROVIDER_EXHAUSTED_APPROVAL = "provider_exhausted"
BUDGET_EXCEEDED_APPROVAL = "budget_exceeded"


def _cost_ceilings() -> tuple[float, float]:
    """Return (per-project, per-day) ceilings in USD. 0 means no ceiling."""
    policy = settings.automation_policy()
    try:
        project_ceiling = max(0.0, float(policy.get("max_project_cost", 0) or 0))
    except (TypeError, ValueError):
        project_ceiling = 0.0
    try:
        daily_ceiling = max(0.0, float(policy.get("max_daily_cost", 0) or 0))
    except (TypeError, ValueError):
        daily_ceiling = 0.0
    return project_ceiling, daily_ceiling


def _cost_budget_breach(project_id: int, provider: str) -> str:
    """Say why one more call would break a saved spending ceiling.

    A ceiling limits money, so a provider that costs nothing extra (a paid
    subscription already billed, or a local model) is never blocked by it.
    Blocking those would stop free work because unrelated paid work overspent.
    """
    project_ceiling, daily_ceiling = _cost_ceilings()
    if not project_ceiling and not daily_ceiling:
        return ""
    try:
        descriptor = scene_provider_gateway.require(provider).descriptor
    except Exception:
        return ""
    upcoming = float(descriptor.estimated_unit_cost or 0)
    if upcoming <= 0:
        return ""
    if project_ceiling and project_id:
        spent = database.project_provider_cost(int(project_id))
        if spent + upcoming > project_ceiling:
            return (
                f"Dự án đã dùng ${spent:.2f}; thêm ${upcoming:.2f} của "
                f"{descriptor.display_name} sẽ vượt hạn mức ${project_ceiling:.2f} mỗi dự án."
            )
    if daily_ceiling:
        spent_today = database.today_provider_cost()
        if spent_today + upcoming > daily_ceiling:
            return (
                f"Hôm nay đã dùng ${spent_today:.2f}; thêm ${upcoming:.2f} của "
                f"{descriptor.display_name} sẽ vượt hạn mức ${daily_ceiling:.2f} mỗi ngày."
            )
    return ""


def _pause_for_automation_block(
    project_id: int | None,
    approval_type: str,
    title: str,
    payload: dict[str, Any],
) -> bool:
    """Park the pipeline on a pending decision instead of failing silently.

    Returns whether the pipeline is now paused. The approval row de-duplicates
    itself, so repeated failures raise one question, not a queue of them.
    """
    if not project_id:
        return False
    try:
        database.create_automation_approval(
            int(project_id), approval_type, title=title, payload=payload
        )
    except ValueError:
        return False
    database.emit_domain_event(
        "pipeline.paused",
        project_id=int(project_id),
        aggregate_type="project",
        aggregate_id=str(project_id),
        source="orchestrator",
        payload={"approval_type": approval_type, **payload},
    )
    return True


def _automation_pause_active(project_id: int | None) -> str:
    """Return the pending block type holding this project, if any."""
    if not project_id:
        return ""
    for approval in database.list_automation_approvals(
        project_id=int(project_id), status="pending", limit=200
    ):
        approval_type = str(approval.get("approval_type") or "")
        if approval_type in {PROVIDER_EXHAUSTED_APPROVAL, BUDGET_EXCEEDED_APPROVAL}:
            return approval_type
    return ""


def _enforce_provider_billing_policy(provider: str, project_id: int | None = None) -> None:
    try:
        descriptor = scene_provider_gateway.require(provider).descriptor
    except Exception:
        return
    if descriptor.billing_mode == "api" and not _paid_api_allowed():
        raise HTTPException(
            status_code=403,
            detail=(
                f"Provider {descriptor.display_name} dùng API trả phí và đang bị khóa bởi Automation Policy. "
                "Hãy bật 'Cho phép API trả phí' trong Điều phối AI nếu thật sự muốn dùng."
            ),
        )
    if descriptor.billing_mode == "subscription" and not _subscription_media_allowed():
        raise HTTPException(
            status_code=403,
            detail=(
                f"Provider {descriptor.display_name} dùng gói thuê bao và đang bị khóa bởi Automation Policy. "
                "Hãy bật 'Cho phép media qua gói thuê bao' trong Điều phối AI nếu muốn dùng."
            ),
        )
    breach = _cost_budget_breach(int(project_id or 0), provider)
    if breach:
        raise HTTPException(status_code=403, detail=f"Vượt hạn mức chi phí. {breach}")


def _route_scene_failure(job: dict[str, Any], error: str, failure_kind: str) -> str | None:
    """Select and audit one bounded fallback for an existing scene job."""
    if failure_kind in {"input", "dependency", "cancelled"}:
        return None
    current = str(job.get("provider") or "").strip().lower()
    kind = str(job.get("job_kind") or "image").strip().lower()
    capability = {
        "image": SCENE_IMAGE,
        "gif": SCENE_ANIMATED_IMAGE,
        "video": SCENE_VIDEO,
    }.get(kind)
    if not capability:
        return None
    project_id = int(job.get("project_id") or 0)
    try:
        descriptor = scene_provider_gateway.require(current).descriptor
        route = scene_provider_gateway.route(
            capability,
            provider_states=_provider_runtime_states(),
            policy=_billing_route_policy(
                preferred=descriptor.fallback_keys,
                excluded=frozenset({current}),
                prefer_subscription=True,
            ),
        )
    except ProviderGatewayError as exc:
        # Nothing is left to try for this capability. Silently failing the job
        # would let the pipeline grind through every remaining scene against
        # providers that are equally exhausted.
        if settings.automation_policy().get("pause_on_provider_exhaustion", True):
            _pause_for_automation_block(
                project_id,
                PROVIDER_EXHAUSTED_APPROVAL,
                "Hết provider khả dụng — pipeline tạm dừng chờ quyết định",
                {
                    "capability": capability,
                    "scene_job_id": int(job["id"]),
                    "failed_provider": current,
                    "error": str(error)[:500],
                    "detail": str(exc)[:1000],
                },
            )
        return None
    except Exception:
        return None
    breach = _cost_budget_breach(project_id, route.selected.key)
    if breach:
        _pause_for_automation_block(
            project_id,
            BUDGET_EXCEEDED_APPROVAL,
            "Chi phí chạm hạn mức — pipeline tạm dừng chờ quyết định",
            {
                "capability": capability,
                "scene_job_id": int(job["id"]),
                "blocked_provider": route.selected.key,
                "detail": breach,
            },
        )
        return None
    database.record_provider_route(
        project_id=project_id,
        scene_job_id=int(job["id"]),
        capability=capability,
        selected_provider=route.selected.key,
        candidates=list(route.candidates),
        reason=f"Fallback sau {failure_kind}: {route.reason}; error={error[:500]}",
        estimated_cost=route.selected.estimated_unit_cost or 0,
    )
    return route.selected.key


_FACTORY_URL = os.getenv("YOUTUBE_FACTORY_URL", "http://127.0.0.1:8787").rstrip("/")


def _verify_goal(project_id: int, target_steps: Iterable[str], claimed: Iterable[str] = ()) -> dict[str, Any]:
    """Whether a goal is reached, read from the project and not from anyone's report.

    A tool answering "ok" and an agent answering "done" are both claims; this
    looks for the things the steps leave behind - the script row, the scenes,
    the timeline, the audio, the mp4 that actually plays. Anything the agent
    said it finished that is not there comes back as a false claim.
    """
    done = _steps_done(project_id)
    targets = [str(name) for name in target_steps]
    missing = [name for name in targets if name not in done]
    evidence: dict[str, Any] = {}
    script = database.get_latest_project_script(project_id)
    if script:
        script_id = int(script["id"])
        evidence["script"] = {"script_id": script_id, "version": script.get("version")}
        if "shots" in done:
            evidence["shots"] = {"count": len(database.list_project_shots(project_id, script_id=script_id))}
        if "timeline" in done:
            timeline = database.list_project_timeline(project_id, script_id=script_id)
            evidence["timeline"] = {
                "segments": len(timeline),
                "with_voice": sum(1 for item in timeline if str(item.get("audio_path") or "").strip()),
                "with_visual": sum(1 for item in timeline if str(item.get("visual_path") or "").strip()),
            }
    if "render" in done:
        final = _current_final_video_path(project_id)
        seconds = media_duration_seconds(Path(final)) if final else None
        evidence["render"] = {"path": str(final or ""), "seconds": seconds}
        # An mp4 that exists but will not play is not a finished video.
        if "render" in targets and not seconds and "render" not in missing:
            missing.append("render")
    reasons: dict[str, str] = {}
    if "analyze" in targets and "analyze" in done:
        # A product analysis written from the URL alone exists as a row, and
        # is not an analysis of the listing: the listing was never read.
        gap = _unread_listing(project_id)
        if gap:
            missing.append("analyze")
            reasons["analyze"] = gap
            evidence["analyze"] = {"listing_read": False}
    false_claims = sorted({str(name) for name in claimed if steps.get(str(name)) and str(name) not in done})
    return {
        "passed": not missing,
        "missing": missing,
        "reasons": reasons,
        "done": sorted(done),
        "false_claims": false_claims,
        "evidence": evidence,
    }


def _unread_listing(project_id: int) -> str:
    """Why a product source's brief does not count yet, or "" when it does."""
    project = database.get_production_project(project_id) or {}
    video_id = _project_source_video_id(project)
    saved = database.get_video_analysis(video_id, analysis_type="reference") if video_id else None
    brief = (saved or {}).get("result") or {}
    if str(brief.get("source_type") or "") != "product":
        return ""
    facts = brief.get("source_facts") or {}
    status = str(facts.get("read_status") or "")
    if status == platform_connections.OK:
        return ""
    return (
        f"Trang sản phẩm chưa đọc được ({status or 'không rõ'}); bản phân tích hiện chỉ dựa trên đường dẫn. "
        "Gọi youtube_factory_list_connections, chọn kết nối can_read (profile:<nền tảng> hoặc "
        "extension:browser), rồi chạy lại analyze với options.browser_session=<id>. Không kết nối nào đọc "
        "được thì báo blocked kèm việc người dùng cần làm (bấm Kết nối / tự xác minh)."
    )


def _goal_state(project_id: int) -> dict[str, Any]:
    done = _steps_done(project_id)
    return {"done": sorted(done), "steps": _describe_steps(project_id, done)}


def _run_codex_agent(prompt: str, mcp_env: dict[str, str]) -> agent_runtime.AgentRun:
    return codex_agent_bridge.run(prompt, mcp_env, instructions=agent_loop.INSTRUCTIONS)


def _run_claude_agent(prompt: str, mcp_env: dict[str, str]) -> agent_runtime.AgentRun:
    return claude_agent_bridge.run(prompt, mcp_env, instructions=agent_loop.INSTRUCTIONS)


# The runtimes that can direct a goal with the app's tools. Antigravity has no
# agent runtime here; it stays a structured worker.
_AGENT_RUNNERS: dict[str, Any] = {
    "codex_cli": _run_codex_agent,
    "claude_code_cli": _run_claude_agent,
}


def _agent_runtime_order(agent: str) -> tuple[str, ...]:
    """Which runtimes may direct, the one the worker picked first, policy order after."""
    assignment = settings.agent_assignment("orchestration")
    names = [
        agent,
        assignment.get("executor"),
        *(assignment.get("fallback_agents") or []),
        *(assignment.get("allowed_agents") or []),
    ]
    order: list[str] = []
    for name in names:
        runtime = orchestrator_runtime.runtime_id(str(name or ""))
        if runtime in _AGENT_RUNNERS and runtime not in order:
            order.append(runtime)
    return tuple(order)


def _record_agent_round(project_id: int, goal: str, event: dict[str, Any]) -> None:
    kind = str(event.get("event") or "")
    status = {
        "round.started": "running",
        "round.runtime_failed": "failed",
        "round.finished": "success" if event.get("passed") else "partial",
        "run.finished": "success" if event.get("verified") else "failed",
    }.get(kind, "info")
    details = {key: value for key, value in event.items() if key != "event"}
    step = "Agent kết thúc" if kind == "run.finished" else f"Agent vòng {event.get('round')}"
    _record_orchestrator_step(
        project_id=project_id, stage="orchestration", step=step,
        status=status, runtime=str(event.get("runtime") or ""), agent=str(event.get("model") or event.get("runtime") or ""),
        why=goal[:300], output_ref=json.dumps(details, ensure_ascii=False, default=str)[:500],
        # A skipped runtime is a fallback decision; the row says so.
        fallback_used=bool((event.get("decision") or {}).get("skipped")),
        error=str(event.get("error") or event.get("reason") or "")[:1500],
    )
    _announce_step(f"agent.{kind}", project_id, "orchestrate", "Điều phối bằng agent", **details)


def _run_orchestrator_goal(task: dict[str, Any], agent: str) -> dict[str, Any]:
    """One goal, driven by an agent over the app's tools until verified or blocked."""
    payload = dict(task.get("input") or {})
    project_id = int(task.get("project_id") or 0)
    runtimes = _agent_runtime_order(agent)
    if not runtimes:
        raise ValueError("Chính sách công đoạn điều phối không cho phép runtime agent nào (codex_cli, claude_code_cli)")
    spec = agent_loop.GoalSpec(
        project_id=project_id,
        goal=str(payload.get("goal") or "").strip(),
        target_steps=tuple(str(name) for name in payload.get("target_steps") or ()),
        allow_spend=bool(payload.get("allow_spend", False)),
        allow_overwrite=bool(payload.get("allow_overwrite", False)),
        max_rounds=max(1, min(int(payload.get("max_rounds") or 4), 8)),
        tool_budget=max(5, min(int(payload.get("tool_budget") or 40), 120)),
        runtimes=runtimes,
    )
    log_path = Path(ensure_project_layout(PRODUCTION_ARTIFACT_DIR, project_id)["work"]) / "agent_runs" / f"{task['id']}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    result = agent_loop.run_goal(
        spec,
        runners=_AGENT_RUNNERS,
        read_state=_goal_state,
        verify=lambda goal, claimed: _verify_goal(goal.project_id, goal.target_steps, claimed),
        mcp_env=lambda round_number: agent_runtime.mcp_environment(
            run_log=log_path, round_number=round_number, project_id=project_id,
            allow_spend=spec.allow_spend, tool_budget=spec.tool_budget, factory_url=_FACTORY_URL,
            allow_overwrite=spec.allow_overwrite,
        ),
        log_path=log_path,
        available=_agent_runtime_available,
        record=lambda event: _record_agent_round(project_id, spec.goal, event),
    )
    result["run_log"] = str(log_path)
    return result


def _execute_agent_task(task: dict[str, Any], agent: str) -> dict[str, Any]:
    role = str(task.get("role") or "")
    project_id = int(task.get("project_id") or 0)
    payload = dict(task.get("input") or {})
    project = database.get_production_project(project_id)
    if not project:
        raise ValueError("Project của agent task không còn tồn tại")
    if role == ORCHESTRATOR_ROLE:
        return _run_orchestrator_goal(task, agent)
    goal = str(payload.get("goal") or project.get("notes") or project.get("title") or "").strip()
    # A retry is told why the last attempt was turned back; asked the same
    # thing again it returned the same fault (media, project 72, twice).
    feedback = str(task.get("previous_error") or "").strip()

    def ask(system_prompt: str, user_prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        if feedback:
            user_prompt = (
                f"{user_prompt}\n\nLẦN THỬ TRƯỚC BỊ NGHIỆM THU TRẢ VỀ VÌ:\n{feedback[:3000]}\n"
                "Sửa đúng những điểm bị chê; phần không bị chê thì giữ."
            )
        return _call_specific_agent_json(agent, system_prompt, user_prompt, schema)
    previous = dict(payload.get("previous_result") or {})

    if role == "research":
        # LEGACY Research Agent of the five-role pipeline: a model answering
        # from the goal text alone, with no tools, whose trend/competition/
        # opportunity scores rest on nothing it read. Kept so the automation
        # tab keeps working; Bước 2 · Kế hoạch (`_step_plan`) does not read it.
        return ask(
            (
                "Bạn là Research Agent cho video YouTube. Phân tích chủ đề, audience, góc nội dung, "
                "keyword và khoảng trống nội dung. Không bịa dữ liệu thời gian thực: mọi số liệu hoặc "
                "xu hướng chưa kiểm chứng phải liệt kê trong facts_to_verify. Trả JSON đúng schema."
            ),
            f"Yêu cầu cấp cao:\n{goal}",
            _AGENT_RESEARCH_SCHEMA,
        )

    if role == "script":
        result = ask(
            (
                "Bạn là Script Agent. Viết một kịch bản YouTube nguyên bản, hook rõ, mạch logic, "
                "giữ chân tốt, không sao chép. main_content phải là lời kể hoàn chỉnh, không chỉ outline. "
                "Không đưa thông tin chưa kiểm chứng thành sự thật. Trả JSON đúng schema."
            ),
            f"Yêu cầu:\n{goal}\n\nKết quả Research Agent:\n{json.dumps(previous, ensure_ascii=False)[:50000]}",
            _AGENT_SCRIPT_SCHEMA,
        )
        # The agent wrote it; the shared step saves it, so a script created by
        # the automatic run is the same row, with the same checks, as one
        # created by the button.
        saved = run_project_step(project_id, "script", {"draft": {
            "script_title": str(result.get("title") or project.get("title") or ""),
            "hook": str(result.get("hook") or ""),
            "intro": str(result.get("intro") or ""),
            "main_content": str(result.get("main_content") or ""),
            "cta": str(result.get("cta") or ""),
            "status": "review",
        }})
        script_id = int((saved.get("result") or {}).get("script_id") or 0)
        if not script_id:
            raise RuntimeError("Script Agent không lưu được kịch bản")
        return {**result, "script_id": script_id, "goal": goal, "pipeline": payload.get("pipeline") or {}}

    if role == "director":
        script = database.get_latest_project_script(project_id)
        if not script:
            raise ValueError("Director Agent cần kịch bản trước")
        result = ask(
            (
                "Bạn là Director Agent. Chia kịch bản thành scene độc lập. Mỗi scene phải có lời đọc, "
                "visual prompt cụ thể, camera, motion, duration và media_type. Dùng image cho cảnh tĩnh, "
                "gif khi chuyển động ngắn mang ý nghĩa, video chỉ khi chuyển động thật sự cần thiết. "
                "Trả JSON đúng schema."
            ),
            json.dumps({"goal": goal, "script": script}, ensure_ascii=False)[:60000],
            _AGENT_DIRECTOR_SCHEMA,
        )
        raw_scenes = [item for item in result.get("scenes", []) if isinstance(item, dict)]
        if not raw_scenes:
            raise ValueError("Director Agent không trả scene")
        shots = []
        for index, scene in enumerate(raw_scenes, start=1):
            shots.append({
                "shot_index": index,
                "section": str(scene.get("section") or "main"),
                "narration": str(scene.get("narration") or ""),
                "visual_prompt": " ".join(
                    item for item in (
                        str(scene.get("visual_prompt") or ""),
                        f"Camera: {scene.get('camera')}" if scene.get("camera") else "",
                        f"Motion: {scene.get('motion')}" if scene.get("motion") else "",
                    ) if item
                ),
                "asset_type": "ai_scene",
                "duration_seconds": max(2, min(int(scene.get("duration") or 8), 30)),
            })
        saved_shots = (run_project_step(project_id, "shots", {"shots": shots, "force": True})
                       .get("result") or {}).get("shots") or []
        segments = [
            {
                "shot_id": saved_shots[index - 1]["id"] if index <= len(saved_shots) else None,
                "segment_index": index,
                "section": shot["section"],
                "voice_text": shot["narration"],
                "subtitle_text": shot["narration"],
                "visual_prompt": shot["visual_prompt"],
                "asset_type": "ai_scene",
                "duration_seconds": shot["duration_seconds"],
            }
            for index, shot in enumerate(shots, start=1)
        ]
        timeline = (run_project_step(project_id, "timeline", {"segments": segments, "force": True})
                    .get("result") or {}).get("timeline") or []
        # Rebuilding replaced the rows the voice hung off. The files are
        # still there, so the scenes whose words are unchanged get theirs
        # back rather than being generated again.
        _reattach_project_voice(project_id, "short")
        for segment, raw_scene in zip(timeline, raw_scenes):
            database.set_segment_visual_kind(
                int(segment["id"]),
                str(raw_scene.get("media_type") or "image"),
                fps=8 if str(raw_scene.get("media_type")) == "gif" else 0,
                reason="Director Agent chọn theo nội dung và chuyển động của scene",
            )
        database.emit_domain_event(
            "script.completed",
            project_id=project_id,
            aggregate_type="project_script",
            aggregate_id=int(script["id"]),
            source="director_agent",
            correlation_id=str(task.get("correlation_id") or ""),
            payload={"scene_count": len(timeline)},
        )
        return {
            "scene_count": len(timeline),
            "script_id": int(script["id"]),
            "scenes": raw_scenes,
            "goal": goal,
            "pipeline": payload.get("pipeline") or {},
        }

    if role == "media":
        script = database.get_latest_project_script(project_id)
        timeline = database.list_project_timeline(project_id, script_id=int(script["id"]) if script else None)
        if not timeline:
            raise ValueError("Media Agent cần timeline trước")
        decision = ask(
            (
                "Bạn là Media Agent. Với từng scene, chọn 'kind' (image/gif/video) và 'treatment'. "
                "Video tốn credit nên chỉ dùng khi chuyển động là phần thiết yếu; infographic hoặc thay đổi ngắn dùng gif; còn lại dùng image. "
                "'treatment' quyết định cảnh được lấy từ đâu: "
                "- 'data_graphics': cảnh trình bày số liệu, so sánh, quy trình, khái niệm trừu tượng (bảo mật, sao lưu, hiệu suất). App sẽ VẼ biểu đồ và thẻ số động. Không kho tư liệu nào quay được một khái niệm, còn AI tạo ảnh thì bịa ra số liệu sai. "
                "- 'real_world': cảnh có thật quay được — địa danh, vũ trụ, tư liệu lịch sử, đời sống thường ngày. "
                "- 'illustration': cảnh cần hình vẽ minh hoạ nhân vật hoặc bối cảnh tưởng tượng. "
                "Giữ nguyên segment_id và trả JSON đúng schema."
            ),
            json.dumps(
                {"goal": goal, "scenes": [
                    {"segment_id": item["id"], "narration": item["voice_text"], "visual_prompt": item["visual_prompt"]}
                    for item in timeline
                ]},
                ensure_ascii=False,
            )[:60000],
            _AGENT_MEDIA_SCHEMA,
        )
        by_id = {int(item["id"]): item for item in timeline}
        states = _provider_runtime_states()
        assignments: list[dict[str, Any]] = []
        for item in decision.get("scenes", []):
            if not isinstance(item, dict) or int(item.get("segment_id") or 0) not in by_id:
                continue
            segment_id = int(item["segment_id"])
            kind = str(item.get("kind") or "image")
            treatment = str(item.get("treatment") or "illustration")
            if treatment == "data_graphics":
                # Only a renderer can draw a chart that is actually correct.
                # An image model asked for one returns a picture of a chart
                # with invented numbers, and an archive has no footage of a
                # concept at all — a real run scored one such scene 1/10.
                kind = "video"
            capability = {"image": SCENE_IMAGE, "gif": SCENE_ANIMATED_IMAGE, "video": SCENE_VIDEO}[kind]
            preferred = {
                "data_graphics": ("motion_graphics",),
                "real_world": ("stock_footage", "gflow_cli"),
            }.get(treatment, ())
            database.set_segment_visual_kind(
                segment_id,
                kind,
                fps=8 if kind == "gif" else 0,
                reason=f"{item.get('reason') or 'Media Agent routing'} [{treatment}]",
            )
            try:
                route = scene_provider_gateway.route(
                    capability,
                    provider_states=states,
                    policy=_billing_route_policy(preferred=preferred),
                )
                provider = route.selected.key
                route_record = database.record_provider_route(
                    project_id=project_id,
                    capability=capability,
                    selected_provider=provider,
                    candidates=list(route.candidates),
                    reason=route.reason,
                    estimated_cost=route.selected.estimated_unit_cost or 0,
                )
                assignments.append({
                    "segment_id": segment_id,
                    "kind": kind,
                    "treatment": treatment,
                    "provider": provider,
                    "route_id": route_record["id"],
                    "reason": str(item.get("reason") or ""),
                })
            except Exception as exc:
                assignments.append({
                    "segment_id": segment_id, "kind": kind, "treatment": treatment,
                    "provider": "", "error": str(exc),
                })

        pipeline_options = dict(payload.get("pipeline") or {})
        queued_jobs: list[int] = []
        unroutable = [item for item in assignments if not item.get("provider")]
        if unroutable and settings.automation_policy().get("pause_on_provider_exhaustion", True):
            _pause_for_automation_block(
                project_id,
                PROVIDER_EXHAUSTED_APPROVAL,
                "Hết provider khả dụng — pipeline tạm dừng chờ quyết định",
                {
                    "unroutable_segments": [int(item["segment_id"]) for item in unroutable],
                    "detail": str(unroutable[0].get("error") or "")[:1000],
                },
            )
        blocked = _automation_pause_active(project_id)
        if pipeline_options.get("auto_generate_media") and not blocked:
            for assignment in assignments:
                provider = str(assignment.get("provider") or "")
                if not provider:
                    continue
                breach = _cost_budget_breach(project_id, provider)
                if breach:
                    # Stop the whole batch, not just this scene: the next one
                    # would breach the same ceiling by the same amount.
                    blocked = BUDGET_EXCEEDED_APPROVAL
                    _pause_for_automation_block(
                        project_id,
                        BUDGET_EXCEEDED_APPROVAL,
                        "Chi phí chạm hạn mức — pipeline tạm dừng chờ quyết định",
                        {
                            "segment_id": int(assignment["segment_id"]),
                            "blocked_provider": provider,
                            "detail": breach,
                        },
                    )
                    break
                segment = by_id[int(assignment["segment_id"])]
                if str(segment.get("visual_path") or "").strip():
                    continue
                kind = str(assignment["kind"])
                reference_asset = _reference_image_asset_for_segment(project_id, segment) if kind == "video" else None
                dependency = None
                if kind == "video" and reference_asset is None:
                    image_route = scene_provider_gateway.route(
                        SCENE_IMAGE,
                        provider_states=states,
                        policy=_billing_route_policy(),
                    )
                    dependency = database.create_scene_generation_job(
                        project_id,
                        int(segment["id"]),
                        image_route.selected.key,
                        str(segment.get("visual_prompt") or ""),
                        job_kind="image",
                        prompt_pending=True,
                    )
                    _record_scene_job_estimate(dependency, reason="agent_image_to_video_dependency")
                    if dependency and image_route.selected.key not in database.EXTERNAL_SIDECAR_PROVIDERS:
                        scene_generation_worker.enqueue(int(dependency["id"]))
                job = database.create_scene_generation_job(
                    project_id,
                    int(segment["id"]),
                    provider,
                    str(segment.get("visual_prompt") or ""),
                    duration_seconds=max(2, min(int(segment.get("duration_seconds") or 5), 30)),
                    reference_asset_id=int(reference_asset["id"]) if reference_asset else None,
                    job_kind=kind,
                    depends_on_job_id=int(dependency["id"]) if dependency else None,
                    requires_reference_image=kind == "video",
                    prompt_pending=True,
                )
                if dependency:
                    queued_jobs.append(int(dependency["id"]))
                if job:
                    queued_jobs.append(int(job["id"]))
                    _record_scene_job_estimate(job, reason="media_agent")
                    if not dependency and provider not in database.EXTERNAL_SIDECAR_PROVIDERS:
                        scene_generation_worker.enqueue(int(job["id"]))
            if script and not blocked:
                render_settings = database.get_project_render_settings(project_id)
                voice_provider = str(render_settings.get("voice_provider") or "edge_tts")
                try:
                    production_worker.enqueue(project_id, int(script["id"]), "voiceover", voice_provider)
                except ProductionJobError:
                    pass
        return {
            "assignments": assignments,
            "queued_job_ids": queued_jobs,
            "auto_generate_media": bool(pipeline_options.get("auto_generate_media")),
            "paused_by": blocked,
            "goal": goal,
            "pipeline": pipeline_options,
        }

    if role == "qc":
        script = database.get_latest_project_script(project_id)
        timeline = database.list_project_timeline(project_id, script_id=int(script["id"]) if script else None)
        scene_jobs = database.list_scene_generation_jobs(project_id, limit=500)
        latest_scene_jobs = _latest_scene_jobs_by_segment(scene_jobs)
        project_jobs = database.list_project_jobs(project_id, limit=100)
        active = [job for job in [*scene_jobs, *project_jobs] if job.get("status") in {"waiting", "queued", "running"}]
        # The measurable checks the manual Quality Check panel already runs.
        # Reading the database column only proves a path was written down;
        # this proves the file is on disk, and measures the audio besides.
        report = build_quality_report(timeline, "", FFMPEG_BINARY)
        # Only the checks that mean anything before a render exists. The rest
        # of the report is about final.mp4, its loudness and its thumbnail —
        # all of them necessarily failing at the point QC decides whether a
        # render should be attempted at all.
        all_checks = dict(report.get("checks") or {})
        pre_render_faults = {
            "has_all_visuals": "Có cảnh chưa có file hình trên đĩa",
            "has_all_voice": "Có cảnh chưa có file giọng đọc trên đĩa",
            "subtitle_ready": "Có cảnh chưa có phụ đề",
            "no_abnormal_voice_silence": "Giọng đọc có khoảng lặng bất thường trên 1,5 giây",
        }
        # Only these travel to the agent. Handing it the whole report made it
        # dutifully list "no final.mp4", "no thumbnail" and "not GPU encoded"
        # as faults — all of them true, none of them actionable, at the moment
        # QC is deciding whether a render should happen at all. The reviewer
        # rejected that report as untrustworthy, and was right to.
        checks = {key: all_checks.get(key, True) for key in pre_render_faults}
        issues = [
            message for key, message in pre_render_faults.items() if not checks.get(key, True)
        ]
        issues += [
            issue
            for issue in report.get("issues", [])
            if issue.startswith(("Thiếu cảnh hình ảnh", "Thiếu voice", "Voice có khoảng lặng"))
        ]
        for stale in mismatched_source_clips(timeline, FFMPEG_BINARY):
            issues.append(
                f"Cảnh {stale['segment_index']}: clip nguồn dài {stale['clip_seconds']}s "
                f"nhưng giọng đọc {stale['voice_seconds']}s — cắt lại clip từ video gốc"
            )
        failed_reviews = [
            job for job in latest_scene_jobs if str(job.get("review_status") or "") == "fail"
        ]
        for job in sorted(failed_reviews, key=lambda item: int(item.get("segment_index") or 0)):
            scene_label = int(job.get("segment_index") or 0) or int(job.get("timeline_segment_id") or 0)
            score = int(job.get("review_score") or 0)
            issues.append(
                f"Cảnh {scene_label} (job #{int(job.get('id') or 0)}) bị AI chấm {score}/10 — cần tạo lại"
            )
        if active:
            active_ids = ", ".join(
                f"#{int(job.get('id') or 0)}:{job.get('status')}" for job in active[:12]
            )
            issues.append(f"Còn {len(active)} job đang xử lý ({active_ids})")
        timeline_snapshot = [
            {
                "segment_id": int(segment.get("id") or 0),
                "scene": int(segment.get("segment_index") or 0),
                "duration_seconds": int(segment.get("duration_seconds") or 0),
                "has_visual": bool(str(segment.get("visual_path") or "").strip()),
                "has_voice": bool(str(segment.get("audio_path") or "").strip()),
                "has_subtitle": bool(
                    str(segment.get("subtitle_path") or segment.get("subtitle_text") or "").strip()
                ),
            }
            for segment in timeline
        ]
        result = ask(
            (
                "Bạn là QC Agent độc lập. Kiểm tra snapshot dự án, chỉ duyệt khi không thiếu visual/voice/subtitle, "
                "không còn job chạy và không có scene review fail. Không được che giấu lỗi. Trả JSON đúng schema."
            ),
            json.dumps(
                {
                    "project_id": project_id,
                    "issues_detected": issues,
                    "scene_count": len(timeline),
                    "total_duration_seconds": sum(
                        int(segment.get("duration_seconds") or 0) for segment in timeline
                    ),
                    "timeline": timeline_snapshot,
                    "quality_checks": checks,
                },
                ensure_ascii=False,
                default=str,
            )[:60000],
            _AGENT_QC_SCHEMA,
        )
        approved = bool(result.get("approved")) and not issues
        result = {**result, "approved": approved, "detected_issues": issues, "ready_for_render": approved}
        if approved:
            database.emit_domain_event(
                "project.ready_to_render",
                project_id=project_id,
                aggregate_type="production_project",
                aggregate_id=project_id,
                source="qc_agent",
                correlation_id=str(task.get("correlation_id") or ""),
                payload={"score": result.get("score"), "scene_count": len(timeline)},
            )
        return {**result, "goal": goal, "pipeline": payload.get("pipeline") or {}}

    raise ValueError(f"Agent role không được hỗ trợ: {role}")


def _review_agent_task(
    task: dict[str, Any],
    reviewer_agent: str,
    output: dict[str, Any],
) -> dict[str, Any]:
    return _call_specific_agent_json(
        reviewer_agent,
        (
            "Bạn là AI nghiệm thu chéo. Executor và reviewer phải độc lập. Kiểm tra output có đúng nhiệm vụ, "
            "đủ dữ liệu, tự nhất quán và không bịa hay không. Với QC task, được phép duyệt chất lượng của báo cáo "
            "dù báo cáo kết luận project chưa sẵn sàng; approved ở đây nghĩa là output đáng tin, không phải video đã đạt. "
            "Trả JSON đúng schema."
        ),
        json.dumps(
            {"role": task.get("role"), "task_type": task.get("task_type"), "input": task.get("input"), "output": output},
            ensure_ascii=False,
        )[:80000],
        _AGENT_REVIEW_SCHEMA,
    )


def _pipeline_has_active_media(project_id: int) -> bool:
    return any(
        job.get("status") in {"waiting", "queued", "running"}
        for job in [
            *database.list_scene_generation_jobs(project_id, limit=500),
            *database.list_project_jobs(project_id, limit=100),
        ]
    )


def _resume_media_pipeline(project_id: int) -> None:
    if _pipeline_has_active_media(project_id):
        return
    tasks = database.list_agent_tasks(project_id=project_id, limit=500)
    children = {str(task.get("parent_task_id") or "") for task in tasks}
    for task in tasks:
        if task.get("role") == "media" and task.get("status") == "completed" and str(task["id"]) not in children:
            agent_pipeline.advance(task)
            return


def _agent_pipeline_completed(task: dict[str, Any]) -> None:
    role = str(task.get("role") or "")
    project_id = int(task.get("project_id") or 0)
    if role == "script":
        script_id = int((task.get("output") or {}).get("script_id") or 0)
        if script_id:
            database.approve_project_script(script_id)
    if role == "media" and _pipeline_has_active_media(project_id):
        return
    if role == "qc":
        output = dict(task.get("output") or {})
        options = dict((task.get("input") or {}).get("pipeline") or output.get("pipeline") or {})
        if output.get("ready_for_render") and options.get("auto_render"):
            script = database.get_latest_project_script(project_id)
            if script:
                production_worker.enqueue(project_id, int(script["id"]), "render", "ffmpeg_builtin")
        policy = settings.automation_policy()
        if policy.get("require_final_approval"):
            if output.get("ready_for_render"):
                database.create_automation_approval(
                    project_id,
                    "final_publish",
                    title="Video đã qua QC — chờ người dùng duyệt cuối",
                    payload={
                        "qc_task_id": task.get("id"),
                        "score": output.get("score"),
                        "issues": output.get("detected_issues") or output.get("issues") or [],
                        "ready_for_render": True,
                    },
                )
            elif options.get("auto_generate_media"):
                database.create_automation_approval(
                    project_id,
                    "pipeline_exception",
                    title="Pipeline tự động chưa thể hoàn tất — cần quyết định",
                    payload={
                        "qc_task_id": task.get("id"),
                        "score": output.get("score"),
                        "issues": output.get("detected_issues") or output.get("issues") or [],
                        "ready_for_render": False,
                    },
                )
        return
    agent_pipeline.advance(task)


def _resume_pipeline_from_event(event) -> None:
    if event.project_id is not None:
        _resume_media_pipeline(int(event.project_id))


agent_task_worker.configure(
    executor=_execute_agent_task,
    reviewer=_review_agent_task,
    completion_handler=_agent_pipeline_completed,
)
scene_generation_worker.set_failure_router(_route_scene_failure)
event_bus.subscribe("scene.created", _resume_pipeline_from_event)
event_bus.subscribe("voice.completed", _resume_pipeline_from_event)
event_bus.subscribe("task.failed", _resume_pipeline_from_event)


class AutomationPipelineRequest(BaseModel):
    goal: str = Field(min_length=10, max_length=10_000)
    project_id: int | None = Field(default=None, ge=1)
    title: str = Field(default="", max_length=200)
    language: str = Field(default="vi", max_length=20)
    auto_generate_media: bool = False
    auto_render: bool = False
    chat_agent: Literal["chatgpt_app", "claude_chat"] | None = None


class AutomationApprovalDecisionRequest(BaseModel):
    decision: Literal["approved", "changes_requested", "dismissed"]
    note: str = Field(default="", max_length=4000)
    resume_role: Literal["research", "script", "director", "media", "qc"] = "media"


class CreateAgentTaskRequest(BaseModel):
    project_id: int | None = Field(default=None, ge=1)
    role: Literal["research", "script", "director", "media", "qc"]
    task_type: str = Field(default="manual", min_length=2, max_length=120)
    input: dict[str, Any] = Field(default_factory=dict)
    assigned_agent: str = Field(default="", max_length=80)
    reviewer_agent: str = Field(default="", max_length=80)
    max_attempts: int = Field(default=2, ge=1, le=10)


class ChatGPTTaskCompleteRequest(BaseModel):
    output: dict[str, Any] = Field(default_factory=dict)


class ChatGPTTaskFailRequest(BaseModel):
    error: str = Field(min_length=1, max_length=4000)


class AgentMessageRequest(BaseModel):
    project_id: int | None = Field(default=None, ge=1)
    task_id: str | None = Field(default=None, max_length=80)
    sender_agent: str = Field(min_length=2, max_length=80)
    recipient_agent: str = Field(min_length=2, max_length=80)
    message_type: str = Field(default="message", max_length=80)
    correlation_id: str = Field(default="", max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)


class ProviderRouteRequest(BaseModel):
    capability: Literal["scene.image", "scene.animated_image", "scene.video"]
    project_id: int | None = Field(default=None, ge=1)


_SHORT_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "hook": {"type": "string"},
        "reason": {"type": "string"},
        "segment_ids": {"type": "array", "items": {"type": "integer"}},
        "captions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["segment_id", "text"],
            },
        },
    },
    "required": ["title", "hook", "reason", "segment_ids", "captions"],
}


def _write_short_plan(request: dict[str, Any]) -> dict[str, Any]:
    """Choose the moments that carry the story, and write the hook."""
    return _call_orchestrator_json(
        (
            "Bạn dựng một video Short dọc từ timeline của một video dài đã hoàn tất. "
            f"Chọn các cảnh cộng lại KHÔNG quá {MAX_SHORT_SECONDS} giây. "
            "Giữ nguyên thứ tự thời gian của video dài; short là bản cô đọng, không phải bản dựng lại. "
            "Chọn cảnh mang trọn một ý hoàn chỉnh, bỏ cảnh dẫn nhập hoặc chuyển tiếp. "
            "'hook' là câu chữ hiện lên ngay giây đầu để giữ người xem, viết ngắn và cụ thể. "
            "'captions' là chữ hiện trên từng cảnh, chỉ thêm khi thật sự giúp hiểu. "
            "Chỉ dùng segment_id có trong dữ liệu, không bịa."
        ),
        json.dumps(request, ensure_ascii=False)[:60000],
        _SHORT_PLAN_SCHEMA,
        stage="storyboard",
    )


shorts_set_plan_builder(_write_short_plan)


def _write_short_script(request: dict[str, Any]) -> dict[str, Any]:
    """Write a standalone short - its own hook, its own ending."""
    return _call_orchestrator_json(
        (
            "Ban viet kich ban cho MOT video ngan doc (Short/Reels/TikTok), doc trong "
            f"khoang {request.get('seconds', 45)} giay. "
            f"Toan bo loi doc KHONG duoc vuot qua {request.get('word_budget', 144)} tu. "
            "Day KHONG phai ban rut gon cua video dai: no la mot video rieng, co mo dau, "
            "dien bien va ket thuc tron ven trong thoi luong do. "
            "'hook' la cau dau tien, phai chan nguoi xem lai ngay giay dau - noi thang vao "
            "dieu bat thuong nhat, khong dan nhap, khong chao hoi. "
            "'main_content' la loi doc lien mach, cau ngan, khong tieu de muc, khong ky hieu. "
            "'cta' la mot cau ket ngan. Viet bang cung ngon ngu voi kich ban dai."
        ),
        json.dumps(request, ensure_ascii=False)[:60000],
        SHORT_SCRIPT_SCHEMA,
        stage="script",
    )


short_script_set_writer(_write_short_script)


class ShortScriptRequest(BaseModel):
    seconds: int = Field(default=DEFAULT_SHORT_SCRIPT_SECONDS, ge=MIN_SHORT_SCRIPT_SECONDS, le=MAX_SHORT_SCRIPT_SECONDS)
    direction: str = Field(default="", max_length=4000)
    use_model: bool = True


def _short_lane_progress(project_id: int) -> dict[str, Any]:
    """Where the short's own production has got to, step by step.

    The lane mirrors the long video's, so it needs the same thing the long
    wizard has: which steps are done. Derived from what is actually on disk
    and in the timeline rather than from a status column, because a status
    column is what goes stale when a job is re-run.
    """
    script = database.get_latest_project_script(project_id, variant="short")
    if not script:
        return {
            "script": None, "shots": [], "timeline": [], "estimated_seconds": 0,
            "steps": {"script": False, "voice": False, "visuals": False, "render": False},
            "scenes": 0, "voiced": 0, "with_visuals": 0, "missing_audio": 0,
            "missing_visual": 0, "draft_visual": 0, "can_render": False,
            "issues": ["chưa có kịch bản Short"], "output_path": "",
        }
    # The shots too, not only the timeline: a storyboard card is a shot joined
    # to its segment, so without them the short could only be shown as a list
    # of lines - no picture, no player, no per-scene controls - which is not
    # the storyboard the rest of the app has.
    shots = database.list_project_shots(project_id, script_id=int(script["id"]))
    timeline = database.list_project_timeline(project_id, script_id=int(script["id"]))
    has_audio = [Path(str(item.get("audio_path") or "")).is_file() for item in timeline]
    has_visual = [Path(str(item.get("visual_path") or "")).is_file() for item in timeline]
    draft_visual = sum(
        1 for item, exists in zip(timeline, has_visual)
        if exists and "director_draft_visuals" in str(item.get("visual_path") or "").replace("\\", "/").lower()
    )
    voiced = sum(has_audio)
    with_visuals = sum(has_visual)
    missing_audio = len(timeline) - voiced
    missing_visual = len(timeline) - with_visuals
    can_render = bool(timeline) and not missing_audio and not missing_visual and not draft_visual
    issues: list[str] = []
    if missing_visual:
        issues.append(f"{missing_visual} cảnh thiếu hình")
    if missing_audio:
        issues.append(f"{missing_audio} cảnh thiếu tiếng")
    if draft_visual:
        issues.append(f"{draft_visual} cảnh còn dùng visual nháp")
    output_path = ""
    render_version = ""
    for job in database.list_project_jobs(project_id, limit=100):
        if (
            int(job.get("script_id") or 0) == int(script["id"])
            and job.get("job_type") == "render_short"
            and job.get("status") == "completed"
            and Path(str(job.get("output_path") or "")).is_file()
        ):
            output_path = str(job.get("output_path") or "")
            render_version = f"{job['id']}-{Path(output_path).stat().st_mtime_ns}"
            break
    return {
        "script": script,
        "shots": shots,
        "timeline": timeline,
        "estimated_seconds": estimated_short_seconds(script),
        "scenes": len(timeline),
        "voiced": voiced,
        "with_visuals": with_visuals,
        "missing_audio": missing_audio,
        "missing_visual": missing_visual,
        "draft_visual": draft_visual,
        "can_render": can_render,
        "issues": issues,
        "output_path": output_path,
        "render_version": render_version,
        "steps": {
            "script": bool(timeline),
            # Every scene, not any: a lane that says "done" with half its
            # scenes silent is how a short gets rendered with gaps in it.
            "voice": bool(timeline) and not missing_audio,
            "visuals": bool(timeline) and not missing_visual and not draft_visual,
            "render": bool(output_path),
        },
    }


@app.get("/api/projects/{project_id}/short-lane")
def get_project_short_lane(project_id: int) -> dict[str, Any]:
    """The short lane's own progress, for its own wizard."""
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    return _short_lane_progress(project_id)


@app.get("/api/projects/{project_id}/short-script")
def get_project_short_script(project_id: int) -> dict[str, Any]:
    """The project's standalone short, if one has been written."""
    script = database.get_latest_project_script(project_id, variant="short")
    timeline = (
        database.list_project_timeline(project_id, script_id=int(script["id"]))
        if script else []
    )
    return {
        "script": script,
        "timeline": timeline,
        "estimated_seconds": estimated_short_seconds(script) if script else 0,
    }


@app.post("/api/projects/{project_id}/short-script")
def write_project_short_script(project_id: int, payload: ShortScriptRequest) -> dict[str, Any]:
    """Rewrite a standalone Short after the initial script-pair was created."""
    bundle = database.get_production_project_bundle(project_id, transcript_text_limit=50_000)
    if not bundle:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    # The short is written from the brief, not from the long video, so it does
    # not have to wait for one. Requiring the long script first made the two a
    # single queue wearing the name of a parallel one: nothing about a short
    # written for its own sake depends on the long video existing, and a
    # project may only ever want the short.
    brief = database.get_latest_project_script(project_id) or build_script_draft(bundle)
    try:
        short = _create_standalone_short(
            project_id,
            bundle,
            brief,
            seconds=payload.seconds,
            direction=payload.direction,
            use_model=payload.use_model,
        )
    except ShortScriptError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise _api_error(exc) from exc

    return {
        "status": "saved",
        **short,
        "next_step": "Tạo giọng đọc cho bản short, cắt cảnh, rồi dựng video ngắn.",
    }


class ShortPlanRequest(BaseModel):
    goal: str = Field(default="", max_length=4000)
    profile: Literal["youtube_shorts", "instagram_reels", "tiktok"] = "youtube_shorts"
    use_model: bool = True


@app.post("/api/projects/{project_id}/short/plan")
def plan_project_short(project_id: int, payload: ShortPlanRequest) -> dict[str, Any]:
    """Write the short's script and pick its cuts from the finished long video."""
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id)
    timeline = database.list_project_timeline(
        project_id, script_id=int(script["id"]) if script else None
    )
    if not timeline:
        raise HTTPException(status_code=400, detail="Dự án chưa có timeline để cắt short")
    try:
        if payload.use_model:
            plan = build_short_plan(
                timeline,
                title=str(project.get("title") or ""),
                goal=payload.goal,
                profile=payload.profile,
            )
        else:
            from .shorts import default_plan

            base = default_plan(timeline, title=str(project.get("title") or ""))
            plan = ShortPlan(
                title=base.title, hook=base.hook, segment_ids=base.segment_ids,
                captions=base.captions, profile=payload.profile, reason=base.reason,
            )
    except ShortsPlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    seconds = plan_duration_seconds(timeline, plan.segment_ids)
    record = database.save_project_short(project_id, plan.as_dict(), duration_seconds=seconds)
    database.emit_domain_event(
        "short.planned",
        project_id=project_id,
        aggregate_type="production_project",
        aggregate_id=project_id,
        source="app",
        payload={"segments": len(plan.segment_ids), "seconds": seconds},
    )
    return {"short": record, "duration_seconds": seconds, "scene_count": len(plan.segment_ids)}


class TimelineCleanupRequest(BaseModel):
    position: Literal[
        "top_left", "top_right", "top_center",
        "bottom_left", "bottom_right", "bottom_center", "center",
    ] = "bottom_center"
    method: Literal["blur", "crop"] = "blur"
    clear: bool = False
    # Measuring the source beats naming a preset: a subtitle burned higher
    # than usual falls outside every preset box.
    detect: bool = False


@app.post("/api/projects/{project_id}/timeline/cleanups")
def set_timeline_cleanups(project_id: int, payload: TimelineCleanupRequest) -> dict[str, Any]:
    """Cover the source's own subtitles or logo on every scene at once."""
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")
    script = database.get_latest_project_script(project_id)
    script_id = int(script["id"]) if script else None

    if payload.clear:
        # Not an empty list: a render with nothing marked now measures the
        # source and covers what it finds, and an empty list is exactly the
        # state it reads as "nobody has decided yet". Turning covering off has
        # to say so, or the next render would quietly turn it back on.
        cleanups: list[dict[str, Any]] = [{"kind": "none", "source": "user_cleared"}]
        status = "cleared"
    elif payload.detect:
        video = database.get_video(str(project.get("youtube_video_id") or "")) or {}
        source_path = Path(str(video.get("local_media_path") or ""))
        if not source_path.is_file():
            raise HTTPException(
                status_code=400,
                detail="Chưa có video nguồn trên máy để dò. Hãy tải video nguồn trước.",
            )
        try:
            cleanups = detect_burned_in_marks(source_path, ffmpeg_binary=FFMPEG_BINARY)
        except MarkDetectionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not cleanups:
            return {"status": "nothing_found", "segments": 0, "cleanups": []}
        status = "detected"
    else:
        cleanups = [{"position": payload.position, "method": payload.method}]
        status = "saved"

    changed = database.set_timeline_cleanups(project_id, cleanups, script_id=script_id)
    return {"status": status, "segments": changed, "cleanups": cleanups}


@app.get("/api/projects/{project_id}/short")
def get_project_short(project_id: int) -> dict[str, Any]:
    record = database.get_project_short(project_id)
    return {"short": record, "max_seconds": MAX_SHORT_SECONDS}


@app.get("/api/agent-system/status")
def agent_system_status() -> dict[str, Any]:
    return {
        "worker": agent_task_worker.status(),
        "agents": [
            {
                "role": item.role,
                "display_name": item.display_name,
                "responsibility": item.responsibility,
                "stage": item.stage,
            }
            for item in DEFAULT_AGENTS
        ],
        "runtimes": {
            # Chat apps are reachable when they are attached, not when this
            # worker could run them (it never can).
            agent: {
                "available": chat_agent_presence.connected(agent)
                if agent in settings.CHAT_AGENT_IDS else _agent_runtime_available(agent),
                "runtime": orchestrator_runtime.runtime_id(agent),
            }
            for agent in settings.AGENT_IDS
        },
    }


@app.post("/api/automation/pipelines")
def start_automation_pipeline(payload: AutomationPipelineRequest) -> dict[str, Any]:
    policy = settings.automation_policy()
    global_rules = str(policy.get("global_rules") or "").strip()
    effective_goal = payload.goal.strip()
    if global_rules:
        effective_goal = f"{effective_goal}\n\nQUY TẮC HỆ THỐNG BẮT BUỘC:\n{global_rules}"
    project = database.get_production_project(payload.project_id) if payload.project_id else None
    if payload.project_id and not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy project")
    if project is None:
        project = database.create_idea_project(
            effective_goal,
            title=payload.title,
            language=payload.language,
        )
    selected_chat = payload.chat_agent or _directing_chat_agent()
    task = agent_pipeline.start(
        int(project["id"]),
        effective_goal,
        auto_generate_media=payload.auto_generate_media,
        auto_render=payload.auto_render,
        external_agent=selected_chat,
    )
    return {"status": "queued", "project": project, "task": task, "chat_agent": selected_chat or None}


@app.get("/api/automation/projects")
def list_automation_projects(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for project in database.list_production_projects(limit=limit):
        tasks = database.list_agent_tasks(project_id=int(project["id"]), limit=200)
        if not tasks:
            continue
        latest = tasks[0]
        pending_approvals = database.list_automation_approvals(
            project_id=int(project["id"]), status="pending", limit=20
        )
        items.append({
            "project": project,
            "latest_task": latest,
            "task_counts": {
                status: sum(1 for task in tasks if task.get("status") == status)
                for status in {str(task.get("status") or "unknown") for task in tasks}
            },
            "pending_approvals": len(pending_approvals),
        })
    return {"projects": items, "count": len(items)}


@app.get("/api/automation/projects/{project_id}")
def automation_project_status(project_id: int) -> dict[str, Any]:
    project = database.get_production_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy project")
    script = database.get_latest_project_script(project_id)
    return {
        "project": project,
        "agent_tasks": database.list_agent_tasks(project_id=project_id, limit=500),
        "agent_messages": database.list_agent_messages(project_id=project_id, limit=1000),
        "events": [event.as_dict() for event in event_bus.history(project_id=project_id, limit=1000)],
        "provider_usage": database.list_provider_usage(project_id, limit=500),
        "timeline": database.list_project_timeline(
            project_id, script_id=int(script["id"]) if script else None
        ),
        "scene_jobs": database.list_scene_generation_jobs(project_id, limit=500),
        "production_jobs": database.list_project_jobs(project_id, limit=200),
        "approvals": database.list_automation_approvals(project_id=project_id, limit=200),
        "policy": settings.automation_policy(),
        "agent_worker": agent_task_worker.status(),
    }


@app.get("/api/automation/approvals")
def list_automation_approvals(
    project_id: int | None = Query(default=None, ge=1),
    status: str = "pending",
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    approvals = database.list_automation_approvals(
        project_id=project_id, status=status, limit=limit
    )
    projects = {
        int(item["id"]): item for item in database.list_production_projects(limit=200)
    }
    return {
        "approvals": [
            {**item, "project": projects.get(int(item["project_id"]))}
            for item in approvals
        ],
        "count": len(approvals),
    }


@app.post("/api/automation/approvals/{approval_id}/decision")
def decide_automation_approval(
    approval_id: int,
    payload: AutomationApprovalDecisionRequest,
) -> dict[str, Any]:
    approval = database.get_automation_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu phê duyệt")
    decided = database.decide_automation_approval(
        approval_id, payload.decision, payload.note
    )
    if not decided:
        raise HTTPException(status_code=409, detail="Yêu cầu này đã được xử lý")
    project_id = int(approval["project_id"])
    task = None
    if payload.decision == "approved":
        database.update_production_project(project_id, status="approved")
    elif payload.decision == "changes_requested":
        project = database.get_production_project(project_id) or {}
        policy = settings.automation_policy()
        # Carried in the input as well: the hand-off to the next role reads it
        # from there, and without it the rest of the rework went to the CLI.
        chat_agent = _directing_chat_agent()
        task = database.create_agent_task(
            project_id,
            payload.resume_role,
            "user.change_request",
            {
                "goal": payload.note.strip() or f"Sửa project {project.get('title') or project_id} theo báo cáo QC",
                "pipeline": {
                    "auto_generate_media": bool(policy.get("auto_generate_media")),
                    "auto_render": bool(policy.get("auto_render")),
                },
                "approval_id": approval_id,
                "chat_agent": chat_agent,
            },
            requested_by="user",
            assigned_agent=chat_agent,
            max_attempts=int(policy.get("max_attempts") or 2),
        )
        if not chat_agent:
            agent_task_worker.enqueue(str(task["id"]))
        database.update_production_project(project_id, status="review")
    event_bus.publish(
        "approval.decided",
        project_id=project_id,
        aggregate_type="automation_approval",
        aggregate_id=approval_id,
        source="user",
        payload={
            "decision": payload.decision,
            "note": payload.note,
            "resume_role": payload.resume_role if task else "",
            "task_id": str((task or {}).get("id") or ""),
        },
    )
    return {"status": payload.decision, "approval": decided, "task": task}


@app.get("/api/agent-tasks")
def list_agent_tasks(
    project_id: int | None = Query(default=None, ge=1),
    status: str = "",
    role: str = "",
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return database.list_agent_tasks(project_id=project_id, status=status, role=role, limit=limit)


@app.post("/api/agent-tasks")
def create_agent_task(payload: CreateAgentTaskRequest) -> dict[str, Any]:
    if payload.project_id and not database.get_production_project(payload.project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy project")
    task = database.create_agent_task(
        payload.project_id,
        payload.role,
        payload.task_type,
        payload.input,
        assigned_agent=payload.assigned_agent or _directing_chat_agent(),
        reviewer_agent=payload.reviewer_agent,
        max_attempts=payload.max_attempts,
    )
    if str(task.get("assigned_agent") or "") not in {"chatgpt_app", "claude_chat"}:
        agent_task_worker.enqueue(str(task["id"]))
    return {"status": "queued", "task": task}


_CHAT_ROLE_INSTRUCTIONS = {
    "research": (
        "Nghiên cứu brief và trả về các insight, nguồn/tham chiếu cần thiết. "
        "Sau đó hoàn tất task với output có goal, findings và recommendations."
    ),
    "script": (
        "Viết kịch bản trong chính cuộc trò chuyện này. Gọi youtube_factory_save_script để lưu; "
        "sau đó hoàn tất task với output chứa project_id và script_id vừa nhận."
    ),
    "director": (
        "Gọi youtube_factory_get_storyboard, kiểm tra từng cảnh và dùng youtube_factory_update_shot "
        "khi cần. Hoàn tất task với tóm tắt storyboard và các shot đã sửa."
    ),
    "media": (
        "Tạo hoặc điều phối media cho từng cảnh bằng các tool generate/import. Không render nếu chưa "
        "được người dùng xác nhận. Hoàn tất task với danh sách job/asset."
    ),
    "qc": (
        "Đọc project, storyboard, job và render hiện có; kiểm tra tính đầy đủ. Hoàn tất task với score, "
        "detected_issues và ready_for_render."
    ),
}


_CHAT_AGENT_LABELS = {"chatgpt_app": "ChatGPT Chat", "claude_chat": "Claude Chat"}


@app.post("/api/chat-agents/{chat_agent}/heartbeat")
def chat_agent_heartbeat(chat_agent: str) -> dict[str, Any]:
    chat_agent_presence.record_contact(_require_chat_agent(chat_agent))
    return {"status": "connected", "chat_agent": chat_agent}


def _chat_task_envelope(task: dict[str, Any], chat_agent: str) -> dict[str, Any]:
    project_id = int(task.get("project_id") or 0)
    project = database.get_production_project(project_id) if project_id else None
    script = database.get_latest_project_script(project_id) if project_id else None
    return {
        "task": task,
        "instruction": _CHAT_ROLE_INSTRUCTIONS.get(str(task.get("role") or ""), "Hoàn tất task bằng các tool của YouTube AI Factory."),
        "project": project,
        "latest_script": script,
        "note": f"{_CHAT_AGENT_LABELS[chat_agent]} là executor của task này; không thay bằng Codex CLI, Claude Code CLI hoặc API.",
        # The role instruction says what this hand-off wants; this says how
        # the app is driven, so the chat directs through the same steps the
        # buttons run instead of rebuilding them from lower-level tools.
        "how_to_direct": (
            "Bạn là AI điều phối của dự án này. Làm việc với app bằng tool youtube_factory_*, không bằng "
            "cách bấm giao diện: xem bước nào đã xong, bước nào còn thiếu điều kiện bằng "
            "youtube_factory_list_steps; chạy bước bằng youtube_factory_run_step - cùng đường với nút bấm. "
            "Tool lỗi thì đọc lỗi rồi đổi cách (bước tiên quyết, provider khác); chỉ dùng giao diện hay "
            "điều khiển máy khi không có tool nào làm được, và nói rõ vì sao. Bước tiêu lượt tạo media "
            "hoặc render phải có xác nhận của người dùng; không bao giờ tự đăng video."
        ),
    }


def _require_chat_agent(chat_agent: str) -> str:
    if chat_agent not in _CHAT_AGENT_LABELS:
        raise HTTPException(status_code=400, detail="Chat agent không hợp lệ")
    return chat_agent


@app.post("/api/chat-agents/{chat_agent}/tasks/next")
def claim_next_chat_task(chat_agent: str) -> dict[str, Any]:
    """Claim or resume the oldest durable task owned by one chat client."""
    chat_agent = _require_chat_agent(chat_agent)
    running = [
        task for task in database.list_agent_tasks(status="running", limit=1000)
        if str(task.get("assigned_agent") or "") == chat_agent
    ]
    if running:
        return {"status": "resumed", **_chat_task_envelope(list(reversed(running))[0], chat_agent)}
    queued = [
        task for task in database.list_agent_tasks(status="queued", limit=1000)
        if str(task.get("assigned_agent") or "") == chat_agent
    ]
    for pending in reversed(queued):
        claimed = database.claim_agent_task(str(pending["id"]), chat_agent)
        if claimed:
            return {"status": "claimed", **_chat_task_envelope(claimed, chat_agent)}
    return {"status": "idle", "task": None, "message": f"Không có task {_CHAT_AGENT_LABELS[chat_agent]} đang chờ."}


@app.post("/api/chatgpt/tasks/next")
def claim_next_chatgpt_task() -> dict[str, Any]:
    return claim_next_chat_task("chatgpt_app")


@app.post("/api/chat-agents/{chat_agent}/tasks/{task_id}/complete")
def complete_chat_task(chat_agent: str, task_id: str, payload: ChatGPTTaskCompleteRequest) -> dict[str, Any]:
    chat_agent = _require_chat_agent(chat_agent)
    task = database.get_agent_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Không tìm thấy task")
    if str(task.get("assigned_agent") or "") != chat_agent:
        raise HTTPException(status_code=409, detail=f"Task này không thuộc {_CHAT_AGENT_LABELS[chat_agent]}")
    if str(task.get("status") or "") not in {"running", "queued"}:
        raise HTTPException(status_code=409, detail=f"Task đang ở trạng thái {task.get('status')}")
    if str(task.get("status") or "") == "queued":
        task = database.claim_agent_task(task_id, chat_agent) or task
    completed = database.finish_agent_task(task_id, "completed", output=payload.output)
    if completed:
        _agent_pipeline_completed(completed)
    return {"status": "completed", "task": completed}


@app.post("/api/chatgpt/tasks/{task_id}/complete")
def complete_chatgpt_task(task_id: str, payload: ChatGPTTaskCompleteRequest) -> dict[str, Any]:
    return complete_chat_task("chatgpt_app", task_id, payload)


@app.post("/api/chat-agents/{chat_agent}/tasks/{task_id}/fail")
def fail_chat_task(chat_agent: str, task_id: str, payload: ChatGPTTaskFailRequest) -> dict[str, Any]:
    chat_agent = _require_chat_agent(chat_agent)
    task = database.get_agent_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Không tìm thấy task")
    if str(task.get("assigned_agent") or "") != chat_agent:
        raise HTTPException(status_code=409, detail=f"Task này không thuộc {_CHAT_AGENT_LABELS[chat_agent]}")
    failed = database.finish_agent_task(task_id, "failed", error=payload.error)
    return {"status": "failed", "task": failed}


@app.post("/api/chatgpt/tasks/{task_id}/fail")
def fail_chatgpt_task(task_id: str, payload: ChatGPTTaskFailRequest) -> dict[str, Any]:
    return fail_chat_task("chatgpt_app", task_id, payload)


@app.get("/api/agent-tasks/{task_id}")
def get_agent_task(task_id: str) -> dict[str, Any]:
    task = database.get_agent_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Không tìm thấy agent task")
    return {"task": task, "messages": database.list_agent_messages(task_id=task_id)}


@app.post("/api/agent-messages")
def create_agent_message(payload: AgentMessageRequest) -> dict[str, Any]:
    message = database.append_agent_message(
        project_id=payload.project_id,
        task_id=payload.task_id,
        sender_agent=payload.sender_agent,
        recipient_agent=payload.recipient_agent,
        message_type=payload.message_type,
        correlation_id=payload.correlation_id,
        payload=payload.payload,
    )
    return {"status": "sent", "message": message}


@app.get("/api/events")
def list_domain_events(
    after_id: int = Query(default=0, ge=0),
    project_id: int | None = Query(default=None, ge=1),
    event_type: list[str] = Query(default=[]),
    limit: int = Query(default=200, ge=1, le=2000),
) -> list[dict[str, Any]]:
    try:
        return [
            event.as_dict()
            for event in event_bus.history(
                after_id=after_id,
                project_id=project_id,
                event_types=event_type,
                limit=limit,
            )
        ]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/providers/catalog")
def provider_catalog() -> dict[str, Any]:
    states = _provider_runtime_states()
    return {
        "providers": [
            {
                "key": item.key,
                "display_name": item.display_name,
                "capabilities": sorted(item.capabilities),
                "execution_mode": item.execution_mode,
                "priority": item.priority,
                "quality_score": item.quality_score,
                "billing_mode": item.billing_mode,
                "estimated_unit_cost": item.estimated_unit_cost,
                "enabled": item.enabled,
                "max_attempts": item.max_attempts,
                "fallback_keys": list(item.fallback_keys),
                "runtime": states.get(item.key) or {},
            }
            for item in scene_provider_gateway.descriptors()
        ]
    }


@app.post("/api/providers/route")
def route_provider(payload: ProviderRouteRequest) -> dict[str, Any]:
    try:
        route = scene_provider_gateway.route(
            payload.capability,
            provider_states=_provider_runtime_states(),
            policy=_billing_route_policy(),
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    recorded = database.record_provider_route(
        project_id=payload.project_id,
        capability=payload.capability,
        selected_provider=route.selected.key,
        candidates=list(route.candidates),
        reason=route.reason,
        estimated_cost=route.selected.estimated_unit_cost or 0,
    )
    return {"selected_provider": route.selected.key, "candidates": route.candidates, "reason": route.reason, "decision": recorded}


@app.get("/api/projects/{project_id}/provider-usage")
def project_provider_usage(project_id: int) -> list[dict[str, Any]]:
    if not database.get_production_project(project_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy project")
    return database.list_provider_usage(project_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("youtube_monitor.main:app", host="127.0.0.1", port=8787, reload=False)
