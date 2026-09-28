from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import workflows


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._event_publisher: Callable[..., Any] | None = None
        self.initialize()

    def set_event_publisher(self, publisher: Callable[..., Any] | None) -> None:
        """Attach the app EventBus while keeping standalone Database usable."""
        self._event_publisher = publisher

    def emit_domain_event(self, event_type: str, **values: Any) -> dict[str, Any]:
        if self._event_publisher is not None:
            published = self._event_publisher(event_type, **values)
            if hasattr(published, "as_dict"):
                return published.as_dict()
            if isinstance(published, dict):
                return published
        return self.append_domain_event(event_type, **values)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_channel_id TEXT NOT NULL UNIQUE,
                    handle TEXT NOT NULL DEFAULT '',
                    channel_url TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    thumbnail_url TEXT NOT NULL DEFAULT '',
                    uploads_playlist_id TEXT NOT NULL DEFAULT '',
                    published_at TEXT,
                    subscriber_count INTEGER,
                    video_count INTEGER,
                    group_name TEXT NOT NULL DEFAULT '',
                    tracking_enabled INTEGER NOT NULL DEFAULT 1,
                    sync_status TEXT NOT NULL DEFAULT 'never',
                    last_sync_at TEXT,
                    last_push_at TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS managed_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    channel_url TEXT NOT NULL,
                    platform TEXT NOT NULL DEFAULT 'youtube',
                    youtube_channel_id TEXT NOT NULL DEFAULT '',
                    group_name TEXT NOT NULL DEFAULT '',
                    workflow_reference_channel_id TEXT NOT NULL DEFAULT '',
                    output_profile TEXT NOT NULL DEFAULT 'youtube_landscape',
                    language TEXT NOT NULL DEFAULT 'vi',
                    default_voice_provider TEXT NOT NULL DEFAULT 'edge_tts',
                    default_voice_model TEXT NOT NULL DEFAULT 'vi-VN-HoaiMyNeural',
                    default_subtitle_provider TEXT NOT NULL DEFAULT 'timeline_text',
                    default_subtitle_model TEXT NOT NULL DEFAULT 'timeline',
                    default_transition_style TEXT NOT NULL DEFAULT 'fade',
                    notes TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    schedule_enabled INTEGER NOT NULL DEFAULT 0,
                    schedule_frequency TEXT NOT NULL DEFAULT 'weekly',
                    schedule_time TEXT NOT NULL DEFAULT '19:00',
                    schedule_timezone TEXT NOT NULL DEFAULT 'Asia/Bangkok',
                    schedule_days TEXT NOT NULL DEFAULT 'mon',
                    default_privacy TEXT NOT NULL DEFAULT 'private',
                    auto_upload INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_managed_channels_group
                    ON managed_channels(group_name, name COLLATE NOCASE);

                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_video_id TEXT NOT NULL UNIQUE,
                    youtube_channel_id TEXT NOT NULL,
                    video_url TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    published_at TEXT,
                    thumbnail_url TEXT NOT NULL DEFAULT '',
                    duration_seconds INTEGER,
                    category_id TEXT NOT NULL DEFAULT '',
                    default_language TEXT NOT NULL DEFAULT '',
                    caption_available INTEGER,
                    live_broadcast_status TEXT NOT NULL DEFAULT 'none',
                    privacy_status TEXT NOT NULL DEFAULT '',
                    license TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    view_count INTEGER,
                    like_count INTEGER,
                    comment_count INTEGER,
                    metadata_hash TEXT NOT NULL DEFAULT '',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    last_metadata_sync_at TEXT,
                    analysis_status TEXT NOT NULL DEFAULT 'pending',
                    media_status TEXT NOT NULL DEFAULT 'not_downloaded',
                    raw_payload_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (youtube_channel_id)
                        REFERENCES channels(youtube_channel_id)
                        ON UPDATE CASCADE
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_videos_channel
                    ON videos(youtube_channel_id);
                CREATE INDEX IF NOT EXISTS idx_videos_published
                    ON videos(published_at DESC);

                CREATE TABLE IF NOT EXISTS video_statistics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_video_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    view_count INTEGER,
                    like_count INTEGER,
                    comment_count INTEGER,
                    UNIQUE(youtube_video_id, captured_at),
                    FOREIGN KEY (youtube_video_id)
                        REFERENCES videos(youtube_video_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS metadata_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_video_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    thumbnail_url TEXT NOT NULL DEFAULT '',
                    metadata_hash TEXT NOT NULL,
                    FOREIGN KEY (youtube_video_id)
                        REFERENCES videos(youtube_video_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS sync_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_channel_id TEXT,
                    trigger TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    videos_seen INTEGER NOT NULL DEFAULT 0,
                    videos_new INTEGER NOT NULL DEFAULT 0,
                    videos_updated INTEGER NOT NULL DEFAULT 0,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS analysis_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_video_id TEXT NOT NULL,
                    analysis_type TEXT NOT NULL DEFAULT 'metadata',
                    provider TEXT NOT NULL DEFAULT 'local_rules',
                    status TEXT NOT NULL DEFAULT 'queued',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    error TEXT,
                    FOREIGN KEY (youtube_video_id)
                        REFERENCES videos(youtube_video_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS video_analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_video_id TEXT NOT NULL,
                    analysis_type TEXT NOT NULL DEFAULT 'metadata',
                    provider TEXT NOT NULL DEFAULT 'local_rules',
                    source_type TEXT NOT NULL DEFAULT 'metadata',
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (youtube_video_id)
                        REFERENCES videos(youtube_video_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS transcripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_video_id TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'manual',
                    language TEXT NOT NULL DEFAULT '',
                    transcript_format TEXT NOT NULL DEFAULT 'txt',
                    content_text TEXT NOT NULL,
                    word_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (youtube_video_id)
                        REFERENCES videos(youtube_video_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS production_projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_video_id TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    notes TEXT NOT NULL DEFAULT '',
                    managed_channel_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (youtube_video_id)
                        REFERENCES videos(youtube_video_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS project_scripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    version INTEGER NOT NULL,
                    script_title TEXT NOT NULL DEFAULT '',
                    hook TEXT NOT NULL DEFAULT '',
                    intro TEXT NOT NULL DEFAULT '',
                    main_content TEXT NOT NULL DEFAULT '',
                    cta TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    approved_at TEXT,
                    UNIQUE(project_id, version),
                    FOREIGN KEY (project_id)
                        REFERENCES production_projects(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS project_shots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    script_id INTEGER NOT NULL,
                    shot_index INTEGER NOT NULL,
                    section TEXT NOT NULL DEFAULT 'main',
                    narration TEXT NOT NULL DEFAULT '',
                    visual_prompt TEXT NOT NULL DEFAULT '',
                    asset_type TEXT NOT NULL DEFAULT 'broll',
                    duration_seconds INTEGER NOT NULL DEFAULT 8,
                    status TEXT NOT NULL DEFAULT 'planned',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(script_id, shot_index),
                    FOREIGN KEY (project_id)
                        REFERENCES production_projects(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (script_id)
                        REFERENCES project_scripts(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS project_timeline_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    script_id INTEGER NOT NULL,
                    shot_id INTEGER,
                    segment_index INTEGER NOT NULL,
                    section TEXT NOT NULL DEFAULT 'main',
                    voice_text TEXT NOT NULL DEFAULT '',
                    subtitle_text TEXT NOT NULL DEFAULT '',
                    visual_prompt TEXT NOT NULL DEFAULT '',
                    asset_type TEXT NOT NULL DEFAULT 'broll',
                    duration_seconds INTEGER NOT NULL DEFAULT 8,
                    start_seconds INTEGER NOT NULL DEFAULT 0,
                     end_seconds INTEGER NOT NULL DEFAULT 8,
                     audio_path TEXT NOT NULL DEFAULT '',
                     visual_path TEXT NOT NULL DEFAULT '',
                     subtitle_path TEXT NOT NULL DEFAULT '',
                     status TEXT NOT NULL DEFAULT 'planned',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(script_id, segment_index),
                    FOREIGN KEY (project_id)
                        REFERENCES production_projects(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (script_id)
                        REFERENCES project_scripts(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (shot_id)
                        REFERENCES project_shots(id)
                        ON DELETE SET NULL
                );

                -- A segment is one line of narration.  Its edit can contain
                -- several visual beats (source clip, extracted frame, or an
                -- AI/image asset) without replacing the segment's main
                -- storyboard visual.
                CREATE TABLE IF NOT EXISTS project_timeline_edit_beats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timeline_segment_id INTEGER NOT NULL,
                    beat_index INTEGER NOT NULL,
                    asset_id INTEGER,
                    visual_path TEXT NOT NULL DEFAULT '',
                    source_kind TEXT NOT NULL DEFAULT 'primary',
                    start_seconds REAL NOT NULL DEFAULT 0,
                    duration_seconds REAL NOT NULL DEFAULT 1,
                    effect TEXT NOT NULL DEFAULT 'static',
                    transition TEXT NOT NULL DEFAULT 'cut',
                    prompt TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'ready',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(timeline_segment_id, beat_index),
                    FOREIGN KEY (timeline_segment_id)
                        REFERENCES project_timeline_segments(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (asset_id)
                        REFERENCES project_assets(id)
                        ON DELETE SET NULL
                );

                -- An AI edit proposal is not the live timeline.  Keeping it
                -- separately gives the user an explicit review/apply boundary
                -- and lets us invalidate it when its source script or scenes
                -- change.
                CREATE TABLE IF NOT EXISTS project_director_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES production_projects(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_director_artifacts ON project_director_artifacts(project_id, kind, id);
                CREATE TABLE IF NOT EXISTS project_edit_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    script_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    source_revision TEXT NOT NULL,
                    plan_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    approved_at TEXT,
                    applied_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, script_id),
                    FOREIGN KEY (project_id)
                        REFERENCES production_projects(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (script_id)
                        REFERENCES project_scripts(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS project_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    script_id INTEGER NOT NULL,
                    job_type TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    output_path TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    FOREIGN KEY (project_id)
                        REFERENCES production_projects(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (script_id)
                        REFERENCES project_scripts(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS project_job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    level TEXT NOT NULL DEFAULT 'info',
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (job_id)
                        REFERENCES project_jobs(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS project_publications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    managed_channel_id INTEGER,
                    platform TEXT NOT NULL DEFAULT 'youtube',
                    output_profile TEXT NOT NULL DEFAULT 'youtube_landscape',
                    video_variant TEXT NOT NULL DEFAULT 'long',
                    local_file_path TEXT NOT NULL,
                    thumbnail_path TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    category_id TEXT NOT NULL DEFAULT '27',
                    privacy_status TEXT NOT NULL DEFAULT 'private',
                    scheduled_at TEXT,
                    status TEXT NOT NULL DEFAULT 'queued',
                    youtube_video_id TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    published_at TEXT,
                    FOREIGN KEY (project_id)
                        REFERENCES production_projects(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (managed_channel_id)
                        REFERENCES managed_channels(id)
                        ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS project_assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    asset_type TEXT NOT NULL,
                    original_name TEXT NOT NULL DEFAULT '',
                    file_path TEXT NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT '',
                    file_size INTEGER NOT NULL DEFAULT 0,
                    sha256 TEXT NOT NULL DEFAULT '',
                    analysis_status TEXT NOT NULL DEFAULT 'not_started',
                    analysis_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (project_id)
                        REFERENCES production_projects(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS project_thumbnails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    asset_id INTEGER NOT NULL UNIQUE,
                    provider TEXT NOT NULL DEFAULT 'ffmpeg_frame',
                    model TEXT NOT NULL DEFAULT 'ffmpeg',
                    prompt TEXT NOT NULL DEFAULT '',
                    seed INTEGER,
                    selected INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (project_id)
                        REFERENCES production_projects(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (asset_id)
                        REFERENCES project_assets(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS project_render_settings (
                    project_id INTEGER PRIMARY KEY,
                    music_asset_id INTEGER,
                    music_volume REAL NOT NULL DEFAULT 0.12,
                    transition_style TEXT NOT NULL DEFAULT 'fade',
                    output_profile TEXT NOT NULL DEFAULT 'youtube_landscape',
                    voice_provider TEXT NOT NULL DEFAULT 'edge_tts',
                    voice_model TEXT NOT NULL DEFAULT 'vi-VN-HoaiMyNeural',
                    voice_rate TEXT NOT NULL DEFAULT '+0%',
                    voice_reference_asset_id INTEGER,
                    voice_prompt_text TEXT NOT NULL DEFAULT '',
                    subtitle_provider TEXT NOT NULL DEFAULT 'timeline_text',
                    subtitle_model TEXT NOT NULL DEFAULT 'timeline',
                    publish_language TEXT NOT NULL DEFAULT 'vi',
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (project_id)
                        REFERENCES production_projects(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (music_asset_id)
                        REFERENCES project_assets(id)
                        ON DELETE SET NULL,
                    FOREIGN KEY (voice_reference_asset_id)
                        REFERENCES project_assets(id)
                        ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS project_asset_transcripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'whisper_local',
                    language TEXT NOT NULL DEFAULT '',
                    transcript_format TEXT NOT NULL DEFAULT 'txt',
                    content_text TEXT NOT NULL,
                    word_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (asset_id)
                        REFERENCES project_assets(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS scene_generation_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    timeline_segment_id INTEGER NOT NULL,
                    edit_beat_id INTEGER,
                    provider TEXT NOT NULL,
                    prompt TEXT NOT NULL DEFAULT '',
                    duration_seconds INTEGER NOT NULL DEFAULT 5,
                    ratio TEXT NOT NULL DEFAULT '1280:720',
                    reference_asset_id INTEGER,
                    job_kind TEXT NOT NULL DEFAULT '',
                    depends_on_job_id INTEGER,
                    requires_reference_image INTEGER NOT NULL DEFAULT 0,
                    output_asset_id INTEGER,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 2,
                    heartbeat_at TEXT,
                    claim_token TEXT NOT NULL DEFAULT '',
                    pipeline_stage TEXT NOT NULL DEFAULT 'queued',
                    failure_kind TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'queued',
                    task_id TEXT NOT NULL DEFAULT '',
                    output_path TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    FOREIGN KEY (project_id)
                        REFERENCES production_projects(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (timeline_segment_id)
                        REFERENCES project_timeline_segments(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (edit_beat_id)
                        REFERENCES project_timeline_edit_beats(id)
                        ON DELETE SET NULL,
                    FOREIGN KEY (reference_asset_id)
                        REFERENCES project_assets(id)
                        ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS scene_provider_states (
                    provider TEXT PRIMARY KEY,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    opened_until TEXT,
                    last_success_at TEXT,
                    last_failure_at TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS provider_usage_limits (
                    provider TEXT PRIMARY KEY,
                    message TEXT NOT NULL DEFAULT '',
                    detected_at TEXT NOT NULL,
                    last_failure_at TEXT,
                    resets_at TEXT,
                    cleared_at TEXT
                );

                CREATE TABLE IF NOT EXISTS domain_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    project_id INTEGER,
                    aggregate_type TEXT NOT NULL DEFAULT '',
                    aggregate_id TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'app',
                    correlation_id TEXT NOT NULL,
                    causation_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (project_id)
                        REFERENCES production_projects(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS agent_tasks (
                    id TEXT PRIMARY KEY,
                    project_id INTEGER,
                    role TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    requested_by TEXT NOT NULL DEFAULT 'orchestrator',
                    assigned_agent TEXT NOT NULL DEFAULT '',
                    reviewer_agent TEXT NOT NULL DEFAULT '',
                    parent_task_id TEXT,
                    correlation_id TEXT NOT NULL,
                    input_json TEXT NOT NULL DEFAULT '{}',
                    output_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 2,
                    estimated_cost REAL NOT NULL DEFAULT 0,
                    actual_cost REAL NOT NULL DEFAULT 0,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    FOREIGN KEY (project_id)
                        REFERENCES production_projects(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (parent_task_id)
                        REFERENCES agent_tasks(id)
                        ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS agent_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    task_id TEXT,
                    sender_agent TEXT NOT NULL,
                    recipient_agent TEXT NOT NULL,
                    message_type TEXT NOT NULL DEFAULT 'message',
                    correlation_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (project_id)
                        REFERENCES production_projects(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (task_id)
                        REFERENCES agent_tasks(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS automation_approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    approval_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    title TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    requested_at TEXT NOT NULL,
                    decided_at TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (project_id)
                        REFERENCES production_projects(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS project_shorts (
                    project_id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    hook TEXT NOT NULL DEFAULT '',
                    plan_json TEXT NOT NULL DEFAULT '{}',
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    output_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (project_id)
                        REFERENCES production_projects(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS provider_route_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    scene_job_id INTEGER,
                    capability TEXT NOT NULL,
                    selected_provider TEXT NOT NULL DEFAULT '',
                    candidates_json TEXT NOT NULL DEFAULT '[]',
                    reason TEXT NOT NULL DEFAULT '',
                    estimated_cost REAL NOT NULL DEFAULT 0,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (project_id)
                        REFERENCES production_projects(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (scene_job_id)
                        REFERENCES scene_generation_jobs(id)
                        ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS provider_usage_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    scene_job_id INTEGER,
                    provider TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'estimated',
                    units REAL NOT NULL DEFAULT 1,
                    estimated_cost REAL NOT NULL DEFAULT 0,
                    actual_cost REAL NOT NULL DEFAULT 0,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (project_id)
                        REFERENCES production_projects(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (scene_job_id)
                        REFERENCES scene_generation_jobs(id)
                        ON DELETE SET NULL
                );

                -- One row per AI step actually attempted: which runtime ran
                -- it, why that one, what came out, and whether a local
                -- fallback stood in. Without this a finished video says
                -- nothing about whether an AI ever made a decision in it.
                CREATE TABLE IF NOT EXISTS orchestrator_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    stage TEXT NOT NULL DEFAULT '',
                    step TEXT NOT NULL DEFAULT '',
                    runtime TEXT NOT NULL DEFAULT '',
                    agent TEXT NOT NULL DEFAULT '',
                    why TEXT NOT NULL DEFAULT '',
                    input_summary TEXT NOT NULL DEFAULT '',
                    output_ref TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    fallback_used INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    attempts_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (project_id)
                        REFERENCES production_projects(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_analysis_jobs_video
                    ON analysis_jobs(youtube_video_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_video_analyses_video
                    ON video_analyses(youtube_video_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_transcripts_video
                    ON transcripts(youtube_video_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_production_projects_status
                    ON production_projects(status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_project_scripts_project
                    ON project_scripts(project_id, version DESC);
                CREATE INDEX IF NOT EXISTS idx_project_shots_project
                    ON project_shots(project_id, script_id, shot_index);
                CREATE INDEX IF NOT EXISTS idx_project_timeline_project
                    ON project_timeline_segments(project_id, script_id, segment_index);
                CREATE INDEX IF NOT EXISTS idx_project_edit_plans_project
                    ON project_edit_plans(project_id, script_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_project_jobs_project
                    ON project_jobs(project_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_project_publications_due
                    ON project_publications(status, scheduled_at, id ASC);
                CREATE INDEX IF NOT EXISTS idx_project_jobs_status
                    ON project_jobs(status, id ASC);
                CREATE INDEX IF NOT EXISTS idx_project_job_events_job
                    ON project_job_events(job_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_project_assets_project
                    ON project_assets(project_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_project_thumbnails_project
                    ON project_thumbnails(project_id, selected DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_project_asset_transcripts_asset
                    ON project_asset_transcripts(asset_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_scene_generation_jobs_project
                    ON scene_generation_jobs(project_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_scene_generation_jobs_status
                    ON scene_generation_jobs(status, id ASC);
                CREATE INDEX IF NOT EXISTS idx_domain_events_project
                    ON domain_events(project_id, id ASC);
                CREATE INDEX IF NOT EXISTS idx_domain_events_type
                    ON domain_events(event_type, id ASC);
                CREATE INDEX IF NOT EXISTS idx_agent_tasks_project
                    ON agent_tasks(project_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_agent_tasks_status
                    ON agent_tasks(status, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_agent_messages_task
                    ON agent_messages(task_id, id ASC);
                CREATE INDEX IF NOT EXISTS idx_automation_approvals_status
                    ON automation_approvals(status, requested_at DESC);
                CREATE INDEX IF NOT EXISTS idx_automation_approvals_project
                    ON automation_approvals(project_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_provider_route_project
                    ON provider_route_decisions(project_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_provider_usage_project
                    ON provider_usage_ledger(project_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_orchestrator_steps_project
                    ON orchestrator_steps(project_id, id DESC);
                """
            )
            self._ensure_column(connection, "videos", "local_media_path", "TEXT")
            # What the downloaded file actually is. The reup workflow cuts
            # pictures out of it, which is impossible for a podcast or a
            # music file - and the app accepted both without noticing.
            self._ensure_column(connection, "videos", "media_kind", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "production_projects", "managed_channel_id", "INTEGER")
            self._ensure_column(connection, "production_projects", "gflow_project_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "production_projects", "gflow_profile", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "project_publications", "thumbnail_path", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "project_publications", "platform", "TEXT NOT NULL DEFAULT 'youtube'")
            self._ensure_column(connection, "project_publications", "output_profile", "TEXT NOT NULL DEFAULT 'youtube_landscape'")
            self._ensure_column(connection, "project_publications", "video_variant", "TEXT NOT NULL DEFAULT 'long'")
            self._ensure_column(connection, "project_timeline_segments", "subtitle_path", "TEXT NOT NULL DEFAULT ''")
            # A short written for its own sake, rather than cut out of the long
            # video afterwards, is a second script for the same project. Its
            # timeline, voice and clips then hang off its script_id exactly as
            # the long one's do, and nothing in the pipeline needs to know.
            self._ensure_column(connection, "project_scripts", "variant", "TEXT NOT NULL DEFAULT 'long'")
            # Orchestrator's verdict on a finished scene: what it actually saw
            # in the file, whether that matches the scene, and how many times
            # a poor result has already been regenerated (so a scene the model
            # simply cannot get right doesn't loop forever).
            # What KIND of visual a scene should get — a still, a short loop,
            # or a real clip — decided per scene rather than one setting for
            # the whole project. asset_type already means something else here
            # (where the material came from: ai_scene, broll, source_clip...).
            self._ensure_column(connection, "project_timeline_segments", "visual_kind", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "project_timeline_segments", "visual_fps", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "project_timeline_segments", "visual_kind_reason", "TEXT NOT NULL DEFAULT ''")
            # Storyboard's transform plan explains how a scene keeps the
            # source's meaning while changing what is shown on screen. These
            # fields are intentionally data-only here; media jobs and the
            # editor UI consume them later.
            self._ensure_column(connection, "project_timeline_segments", "content_dna", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(connection, "project_timeline_segments", "visual_strategy", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "project_timeline_segments", "visual_provider", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "project_timeline_segments", "source_dependency", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "project_timeline_segments", "risk_level", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "project_timeline_segments", "transform_actions", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "project_timeline_segments", "required_assets", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "project_timeline_segments", "overlays", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "project_timeline_segments", "sound_cues", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "project_timeline_segments", "edit_direction", "TEXT NOT NULL DEFAULT '{}'")
            # How the final edit should treat this scene — planned before
            # rendering rather than applying one blanket transition to all.
            self._ensure_column(connection, "project_timeline_segments", "edit_transition", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "project_timeline_segments", "edit_effect", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "project_timeline_segments", "edit_note", "TEXT NOT NULL DEFAULT ''")
            # How much of a source clip is dead air or a redundant lead-in, and
            # what on screen belongs to the source rather than to this video -
            # its logo, its watermark, its burned-in foreign subtitles.
            self._ensure_column(connection, "project_timeline_segments", "edit_trim_head", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(connection, "project_timeline_segments", "edit_trim_tail", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(connection, "project_timeline_segments", "edit_cleanups", "TEXT NOT NULL DEFAULT '[]'")
            # A second AI's verdict on the script, so the stage that was
            # declared in the agent settings but never called has somewhere to
            # record its findings. status already had draft/review/approved;
            # nothing ever moved a script into review.
            self._ensure_column(connection, "project_scripts", "review_score", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "project_thumbnails", "video_variant", "TEXT NOT NULL DEFAULT 'long'")
            self._ensure_column(connection, "project_scripts", "review_note", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "project_scripts", "review_agent", "TEXT NOT NULL DEFAULT ''")
            # Whether a retelling has been checked against the source it is
            # retelling. Editing or translating a script clears it, so the
            # badge never claims a verdict about words that have since changed.
            self._ensure_column(connection, "project_scripts", "fidelity_status", "TEXT NOT NULL DEFAULT 'unchecked'")
            # Same for the narration of a scene: whether it actually says what
            # the script asked it to say.
            self._ensure_column(connection, "project_timeline_segments", "voice_review_score", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "project_timeline_segments", "voice_review_note", "TEXT NOT NULL DEFAULT ''")
            # Which production workflow a project follows. Existing projects
            # all predate the idea, and every one of them was made the one way
            # the app used to work, so 'content' is the honest default.
            self._ensure_column(connection, "production_projects", "workflow", "TEXT NOT NULL DEFAULT 'content'")
            # Where in the downloaded source video this scene's picture comes
            # from. -1 means nobody has chosen yet; 0 is a legitimate choice
            # (the opening frames), so the two cannot share a value.
            self._ensure_column(connection, "project_timeline_segments", "source_start_seconds", "REAL NOT NULL DEFAULT -1")
            self._ensure_column(connection, "project_timeline_segments", "source_cue_reason", "TEXT NOT NULL DEFAULT ''")
            # The narration before translation, kept so a translated line can
            # be checked against what was actually said.
            self._ensure_column(connection, "project_timeline_segments", "source_voice_text", "TEXT NOT NULL DEFAULT ''")
            # Who speaks this line. Without it a retelling has nowhere to record
            # that a line belongs to a character, and every line reads as
            # narration - which is exactly how the dialogue kept disappearing.
            self._ensure_column(connection, "project_shots", "speaker", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "project_timeline_segments", "speaker", "TEXT NOT NULL DEFAULT ''")
            # Whether the orchestrator has written this job's prompt yet.
            # Cannot be inferred from pipeline_stage: claiming a job
            # overwrites that with 'running', erasing the marker.
            self._ensure_column(connection, "scene_generation_jobs", "prompt_written", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(connection, "scene_generation_jobs", "edit_beat_id", "INTEGER")
            self._ensure_column(connection, "scene_generation_jobs", "review_score", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "scene_generation_jobs", "review_note", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "scene_generation_jobs", "review_status", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "scene_generation_jobs", "auto_retry_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "scene_generation_jobs", "job_kind", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "scene_generation_jobs", "depends_on_job_id", "INTEGER")
            self._ensure_column(connection, "scene_generation_jobs", "requires_reference_image", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "scene_generation_jobs", "output_asset_id", "INTEGER")
            self._ensure_column(connection, "scene_generation_jobs", "attempt_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "scene_generation_jobs", "max_attempts", "INTEGER NOT NULL DEFAULT 2")
            self._ensure_column(connection, "scene_generation_jobs", "heartbeat_at", "TEXT")
            self._ensure_column(connection, "scene_generation_jobs", "claim_token", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "scene_generation_jobs", "pipeline_stage", "TEXT NOT NULL DEFAULT 'queued'")
            self._ensure_column(connection, "scene_generation_jobs", "failure_kind", "TEXT NOT NULL DEFAULT ''")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_scene_generation_jobs_dependency "
                "ON scene_generation_jobs(depends_on_job_id, status, id ASC)"
            )
            self._ensure_column(connection, "project_render_settings", "output_profile", "TEXT NOT NULL DEFAULT 'youtube_landscape'")
            self._ensure_column(connection, "project_render_settings", "voice_provider", "TEXT NOT NULL DEFAULT 'edge_tts'")
            self._ensure_column(connection, "project_render_settings", "voice_model", "TEXT NOT NULL DEFAULT 'vi-VN-HoaiMyNeural'")
            self._ensure_column(connection, "project_render_settings", "voice_rate", "TEXT NOT NULL DEFAULT '+0%'")
            self._ensure_column(connection, "project_render_settings", "voice_reference_asset_id", "INTEGER")
            self._ensure_column(connection, "project_render_settings", "voice_prompt_text", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "project_render_settings", "subtitle_provider", "TEXT NOT NULL DEFAULT 'timeline_text'")
            self._ensure_column(connection, "project_render_settings", "subtitle_model", "TEXT NOT NULL DEFAULT 'timeline'")
            self._ensure_column(connection, "project_render_settings", "publish_language", "TEXT NOT NULL DEFAULT 'vi'")
            self._ensure_column(connection, "project_jobs", "segment_id", "INTEGER")
            # Keep the first outage time for the activity log, but also keep
            # the most recent failed probe.  Without the latter, a provider
            # that did not state a reset time was either disabled forever or
            # retried on every worker tick after its first cooldown.
            self._ensure_column(connection, "provider_usage_limits", "last_failure_at", "TEXT")
            for column, ddl in (
                ("platform", "TEXT NOT NULL DEFAULT 'youtube'"),
                ("schedule_enabled", "INTEGER NOT NULL DEFAULT 0"),
                ("schedule_frequency", "TEXT NOT NULL DEFAULT 'weekly'"),
                ("schedule_time", "TEXT NOT NULL DEFAULT '19:00'"),
                ("schedule_timezone", "TEXT NOT NULL DEFAULT 'Asia/Bangkok'"),
                ("schedule_days", "TEXT NOT NULL DEFAULT 'mon'"),
                ("default_privacy", "TEXT NOT NULL DEFAULT 'private'"),
                ("auto_upload", "INTEGER NOT NULL DEFAULT 0"),
                ("default_voice_provider", "TEXT NOT NULL DEFAULT 'edge_tts'"),
                ("default_voice_model", "TEXT NOT NULL DEFAULT 'vi-VN-HoaiMyNeural'"),
                ("default_subtitle_provider", "TEXT NOT NULL DEFAULT 'timeline_text'"),
                ("default_subtitle_model", "TEXT NOT NULL DEFAULT 'timeline'"),
                ("default_transition_style", "TEXT NOT NULL DEFAULT 'fade'"),
            ):
                self._ensure_column(connection, "managed_channels", column, ddl)

    def backup_to(self, destination: str | Path) -> Path:
        """Create a transaction-consistent SQLite backup, including WAL state."""
        target = Path(destination).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.resolve() == Path(self.path).resolve():
            raise ValueError("Backup path must differ from the active database")
        source: sqlite3.Connection | None = None
        backup: sqlite3.Connection | None = None
        try:
            source = sqlite3.connect(self.path, timeout=30)
            backup = sqlite3.connect(str(target), timeout=30)
            source.backup(backup)
        except sqlite3.Error as exc:
            raise RuntimeError(f"Không thể sao lưu SQLite: {exc}") from exc
        finally:
            if backup is not None:
                backup.close()
            if source is not None:
                source.close()
        return target

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, column: str, ddl_type: str) -> None:
        existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")

    @staticmethod
    def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None

    def get_channel(self, channel_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM channels WHERE youtube_channel_id = ?",
                (channel_id,),
            ).fetchone()
        return self._dict(row)

    def list_channels(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM channels ORDER BY title COLLATE NOCASE, id"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_managed_channel(self, channel_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT m.*, c.title AS workflow_reference_title,
                       c.channel_url AS workflow_reference_url,
                       c.description AS workflow_reference_description
                FROM managed_channels m
                LEFT JOIN channels c
                  ON c.youtube_channel_id = m.workflow_reference_channel_id
                WHERE m.id = ?
                """,
                (channel_id,),
            ).fetchone()
        return self._dict(row)

    def list_managed_channels(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT m.*, c.title AS workflow_reference_title,
                       c.channel_url AS workflow_reference_url,
                       c.description AS workflow_reference_description
                FROM managed_channels m
                LEFT JOIN channels c
                  ON c.youtube_channel_id = m.workflow_reference_channel_id
                ORDER BY m.group_name COLLATE NOCASE, m.name COLLATE NOCASE, m.id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _validate_output_profile(value: str) -> str:
        profile = value.strip().lower()
        if profile not in {"youtube_landscape", "youtube_shorts", "instagram_reels", "tiktok", "facebook_reels", "facebook_feed"}:
            raise ValueError("Định dạng đầu ra không được hỗ trợ")
        return profile

    @staticmethod
    def _validate_platform(value: str) -> str:
        platform = value.strip().lower()
        if platform not in {"youtube", "tiktok", "facebook", "instagram"}:
            raise ValueError("Nền tảng xuất bản không được hỗ trợ")
        return platform

    def _validate_workflow_reference(self, channel_id: str) -> str:
        reference = channel_id.strip()
        if reference and not self.get_channel(reference):
            raise ValueError("Kênh workflow tham khảo chưa có trong danh sách theo dõi")
        return reference

    @staticmethod
    def _validate_schedule_frequency(value: str) -> str:
        frequency = value.strip().lower()
        if frequency not in {"daily", "weekdays", "weekly", "monthly"}:
            raise ValueError("Tần suất đăng không được hỗ trợ")
        return frequency

    @staticmethod
    def _validate_schedule_time(value: str) -> str:
        schedule_time = value.strip()
        match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", schedule_time)
        if not match:
            raise ValueError("Giờ đăng phải có dạng HH:MM")
        return schedule_time

    @staticmethod
    def _validate_privacy(value: str) -> str:
        privacy = value.strip().lower()
        if privacy not in {"private", "unlisted", "public"}:
            raise ValueError("Quyền riêng tư không được hỗ trợ")
        return privacy

    def create_managed_channel(
        self,
        name: str,
        channel_url: str,
        platform: str = "youtube",
        youtube_channel_id: str = "",
        group_name: str = "",
        workflow_reference_channel_id: str = "",
        output_profile: str = "youtube_landscape",
        language: str = "vi",
        default_voice_provider: str = "edge_tts",
        default_voice_model: str = "vi-VN-HoaiMyNeural",
        default_subtitle_provider: str = "timeline_text",
        default_subtitle_model: str = "timeline",
        default_transition_style: str = "fade",
        notes: str = "",
        schedule_enabled: bool = False,
        schedule_frequency: str = "weekly",
        schedule_time: str = "19:00",
        schedule_timezone: str = "Asia/Bangkok",
        schedule_days: str = "mon",
        default_privacy: str = "private",
        auto_upload: bool = False,
    ) -> dict[str, Any]:
        clean_name = name.strip()
        clean_url = channel_url.strip()
        if not clean_name or not clean_url:
            raise ValueError("Tên kênh và URL kênh là bắt buộc")
        reference = self._validate_workflow_reference(workflow_reference_channel_id)
        now = utc_now()
        with self._connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO managed_channels (
                        name, channel_url, platform, youtube_channel_id, group_name,
                        workflow_reference_channel_id, output_profile, language,
                        default_voice_provider, default_voice_model, default_subtitle_provider,
                        default_subtitle_model, default_transition_style, notes, schedule_enabled, schedule_frequency, schedule_time,
                        schedule_timezone, schedule_days, default_privacy, auto_upload,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_name,
                        clean_url,
                        self._validate_platform(platform),
                        youtube_channel_id.strip(),
                        group_name.strip(),
                        reference,
                        self._validate_output_profile(output_profile),
                        language.strip() or "vi",
                        default_voice_provider.strip().lower(),
                        default_voice_model.strip() or "vi-VN-HoaiMyNeural",
                        default_subtitle_provider.strip().lower(),
                        default_subtitle_model.strip() or "timeline",
                        default_transition_style.strip().lower(),
                        notes.strip(),
                        int(bool(schedule_enabled)),
                        self._validate_schedule_frequency(schedule_frequency),
                        self._validate_schedule_time(schedule_time),
                        schedule_timezone.strip() or "Asia/Bangkok",
                        schedule_days.strip() or "mon",
                        self._validate_privacy(default_privacy),
                        int(bool(auto_upload)),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Kênh này đã có trong Kênh của tôi") from exc
            channel_id = int(cursor.lastrowid)
        return self.get_managed_channel(channel_id) or {}

    def update_managed_channel(
        self,
        channel_id: int,
        name: str | None = None,
        channel_url: str | None = None,
        platform: str | None = None,
        youtube_channel_id: str | None = None,
        group_name: str | None = None,
        workflow_reference_channel_id: str | None = None,
        output_profile: str | None = None,
        language: str | None = None,
        default_voice_provider: str | None = None,
        default_voice_model: str | None = None,
        default_subtitle_provider: str | None = None,
        default_subtitle_model: str | None = None,
        default_transition_style: str | None = None,
        notes: str | None = None,
        enabled: bool | None = None,
        schedule_enabled: bool | None = None,
        schedule_frequency: str | None = None,
        schedule_time: str | None = None,
        schedule_timezone: str | None = None,
        schedule_days: str | None = None,
        default_privacy: str | None = None,
        auto_upload: bool | None = None,
    ) -> dict[str, Any] | None:
        existing = self.get_managed_channel(channel_id)
        if not existing:
            return None
        values = {
            "name": existing["name"] if name is None else name.strip(),
            "channel_url": existing["channel_url"] if channel_url is None else channel_url.strip(),
            "platform": (existing.get("platform") or "youtube") if platform is None else self._validate_platform(platform),
            "youtube_channel_id": existing["youtube_channel_id"] if youtube_channel_id is None else youtube_channel_id.strip(),
            "group_name": existing["group_name"] if group_name is None else group_name.strip(),
            "workflow_reference_channel_id": existing["workflow_reference_channel_id"] if workflow_reference_channel_id is None else self._validate_workflow_reference(workflow_reference_channel_id),
            "output_profile": existing["output_profile"] if output_profile is None else self._validate_output_profile(output_profile),
            "language": existing["language"] if language is None else language.strip() or "vi",
            "default_voice_provider": existing["default_voice_provider"] if default_voice_provider is None else default_voice_provider.strip().lower(),
            "default_voice_model": existing["default_voice_model"] if default_voice_model is None else default_voice_model.strip() or "vi-VN-HoaiMyNeural",
            "default_subtitle_provider": existing["default_subtitle_provider"] if default_subtitle_provider is None else default_subtitle_provider.strip().lower(),
            "default_subtitle_model": existing["default_subtitle_model"] if default_subtitle_model is None else default_subtitle_model.strip() or "timeline",
            "default_transition_style": existing["default_transition_style"] if default_transition_style is None else default_transition_style.strip().lower(),
            "notes": existing["notes"] if notes is None else notes.strip(),
            "enabled": existing["enabled"] if enabled is None else int(bool(enabled)),
            "schedule_enabled": existing["schedule_enabled"] if schedule_enabled is None else int(bool(schedule_enabled)),
            "schedule_frequency": existing["schedule_frequency"] if schedule_frequency is None else self._validate_schedule_frequency(schedule_frequency),
            "schedule_time": existing["schedule_time"] if schedule_time is None else self._validate_schedule_time(schedule_time),
            "schedule_timezone": existing["schedule_timezone"] if schedule_timezone is None else schedule_timezone.strip() or "Asia/Bangkok",
            "schedule_days": existing["schedule_days"] if schedule_days is None else schedule_days.strip() or "mon",
            "default_privacy": existing["default_privacy"] if default_privacy is None else self._validate_privacy(default_privacy),
            "auto_upload": existing["auto_upload"] if auto_upload is None else int(bool(auto_upload)),
        }
        if not values["name"] or not values["channel_url"]:
            raise ValueError("Tên kênh và URL kênh là bắt buộc")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE managed_channels
                SET name = ?, channel_url = ?, platform = ?, youtube_channel_id = ?, group_name = ?,
                    workflow_reference_channel_id = ?, output_profile = ?, language = ?,
                    default_voice_provider = ?, default_voice_model = ?, default_subtitle_provider = ?,
                    default_subtitle_model = ?, default_transition_style = ?, notes = ?, enabled = ?, schedule_enabled = ?, schedule_frequency = ?,
                    schedule_time = ?, schedule_timezone = ?, schedule_days = ?,
                    default_privacy = ?, auto_upload = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    values["name"], values["channel_url"], values["platform"], values["youtube_channel_id"],
                    values["group_name"], values["workflow_reference_channel_id"],
                    values["output_profile"], values["language"], values["default_voice_provider"],
                    values["default_voice_model"], values["default_subtitle_provider"],
                    values["default_subtitle_model"], values["default_transition_style"], values["notes"],
                    values["enabled"], values["schedule_enabled"], values["schedule_frequency"],
                    values["schedule_time"], values["schedule_timezone"], values["schedule_days"],
                    values["default_privacy"], values["auto_upload"], utc_now(), channel_id,
                ),
            )
        return self.get_managed_channel(channel_id)

    def apply_managed_channel_preset(self, project_id: int) -> dict[str, Any] | None:
        """Copy a managed channel's production defaults into a project explicitly."""
        project = self.get_production_project(project_id)
        if not project:
            return None
        channel_id = project.get("managed_channel_id")
        channel = self.get_managed_channel(int(channel_id)) if channel_id is not None else None
        if not channel:
            raise ValueError("Project chưa gắn kênh có workflow preset")
        current = self.get_project_render_settings(project_id)
        return self.update_project_render_settings(
            project_id,
            music_asset_id=current.get("music_asset_id"),
            music_volume=float(current.get("music_volume") or 0.12),
            transition_style=str(channel["default_transition_style"]),
            output_profile=str(channel["output_profile"]),
            voice_provider=str(channel["default_voice_provider"]),
            voice_model=str(channel["default_voice_model"]),
            voice_reference_asset_id=current.get("voice_reference_asset_id"),
            voice_prompt_text=str(current.get("voice_prompt_text") or ""),
            subtitle_provider=str(channel["default_subtitle_provider"]),
            subtitle_model=str(channel["default_subtitle_model"]),
            publish_language=str(channel["language"]),
        )

    def upsert_channel(self, channel: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        existing = self.get_channel(channel["youtube_channel_id"])
        group_name = channel.get("group_name", "")
        if existing and not group_name:
            group_name = existing.get("group_name", "")

        values = (
            channel["youtube_channel_id"],
            channel.get("handle", ""),
            channel["channel_url"],
            channel.get("title", ""),
            channel.get("description", ""),
            channel.get("thumbnail_url", ""),
            channel.get("uploads_playlist_id", ""),
            channel.get("published_at"),
            channel.get("subscriber_count"),
            channel.get("video_count"),
            group_name,
            channel.get("tracking_enabled", existing.get("tracking_enabled", 1) if existing else 1),
            existing.get("sync_status", "never") if existing else "never",
            existing.get("last_sync_at") if existing else None,
            existing.get("last_push_at") if existing else None,
            existing.get("last_error") if existing else None,
            existing.get("created_at", now) if existing else now,
            now,
        )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO channels (
                    youtube_channel_id, handle, channel_url, title, description,
                    thumbnail_url, uploads_playlist_id, published_at,
                    subscriber_count, video_count, group_name, tracking_enabled,
                    sync_status, last_sync_at, last_push_at, last_error,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(youtube_channel_id) DO UPDATE SET
                    handle = excluded.handle,
                    channel_url = excluded.channel_url,
                    title = excluded.title,
                    description = excluded.description,
                    thumbnail_url = excluded.thumbnail_url,
                    uploads_playlist_id = excluded.uploads_playlist_id,
                    published_at = excluded.published_at,
                    subscriber_count = excluded.subscriber_count,
                    video_count = excluded.video_count,
                    group_name = excluded.group_name,
                    updated_at = excluded.updated_at
                """,
                values,
            )
        return self.get_channel(channel["youtube_channel_id"]) or {}

    def set_tracking_enabled(self, channel_id: str, enabled: bool) -> dict[str, Any] | None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE channels SET tracking_enabled = ?, updated_at = ? WHERE youtube_channel_id = ?",
                (1 if enabled else 0, utc_now(), channel_id),
            )
        return self.get_channel(channel_id)

    def set_channel_group(self, channel_id: str, group_name: str) -> dict[str, Any] | None:
        """Update the user-managed label of an already tracked source channel."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE channels SET group_name = ?, updated_at = ? WHERE youtube_channel_id = ?",
                (group_name.strip()[:100], utc_now(), channel_id),
            )
        return self.get_channel(channel_id)

    def mark_channel_sync(
        self,
        channel_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE channels
                SET sync_status = ?, last_sync_at = ?, last_error = ?, updated_at = ?
                WHERE youtube_channel_id = ?
                """,
                (status, now, error, now, channel_id),
            )

    def mark_channel_push(self, channel_id: str) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE channels SET last_push_at = ?, updated_at = ? WHERE youtube_channel_id = ?",
                (now, now, channel_id),
            )

    def upsert_video(self, video: dict[str, Any]) -> dict[str, bool]:
        now = utc_now()
        video_id = video["youtube_video_id"]
        tags_json = json.dumps(video.get("tags", []), ensure_ascii=False)
        raw_payload_json = json.dumps(video.get("raw_payload", {}), ensure_ascii=False)

        with self._connect() as connection:
            existing = connection.execute(
                "SELECT metadata_hash, first_seen_at FROM videos WHERE youtube_video_id = ?",
                (video_id,),
            ).fetchone()
            is_new = existing is None
            metadata_changed = is_new or existing["metadata_hash"] != video.get("metadata_hash", "")

            connection.execute(
                """
                INSERT INTO videos (
                    youtube_video_id, youtube_channel_id, video_url, title, description,
                    published_at, thumbnail_url, duration_seconds, category_id,
                    default_language, caption_available, live_broadcast_status,
                    privacy_status, license, tags_json, view_count, like_count,
                    comment_count, metadata_hash, first_seen_at, last_seen_at,
                    last_metadata_sync_at, analysis_status, media_status, raw_payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(youtube_video_id) DO UPDATE SET
                    youtube_channel_id = excluded.youtube_channel_id,
                    video_url = excluded.video_url,
                    title = excluded.title,
                    description = excluded.description,
                    published_at = excluded.published_at,
                    thumbnail_url = excluded.thumbnail_url,
                    duration_seconds = excluded.duration_seconds,
                    category_id = excluded.category_id,
                    default_language = excluded.default_language,
                    caption_available = excluded.caption_available,
                    live_broadcast_status = excluded.live_broadcast_status,
                    privacy_status = excluded.privacy_status,
                    license = excluded.license,
                    tags_json = excluded.tags_json,
                    view_count = excluded.view_count,
                    like_count = excluded.like_count,
                    comment_count = excluded.comment_count,
                    metadata_hash = excluded.metadata_hash,
                    last_seen_at = excluded.last_seen_at,
                    last_metadata_sync_at = excluded.last_metadata_sync_at,
                    raw_payload_json = excluded.raw_payload_json
                """,
                (
                    video_id,
                    video["youtube_channel_id"],
                    video["video_url"],
                    video.get("title", ""),
                    video.get("description", ""),
                    video.get("published_at"),
                    video.get("thumbnail_url", ""),
                    video.get("duration_seconds"),
                    video.get("category_id", ""),
                    video.get("default_language", ""),
                    video.get("caption_available"),
                    video.get("live_broadcast_status", "none"),
                    video.get("privacy_status", ""),
                    video.get("license", ""),
                    tags_json,
                    video.get("view_count"),
                    video.get("like_count"),
                    video.get("comment_count"),
                    video.get("metadata_hash", ""),
                    existing["first_seen_at"] if existing and "first_seen_at" in existing.keys() else now,
                    now,
                    now,
                    video.get("analysis_status", "pending"),
                    video.get("media_status", "not_downloaded"),
                    raw_payload_json,
                ),
            )

            if metadata_changed:
                connection.execute(
                    """
                    INSERT INTO metadata_versions (
                        youtube_video_id, captured_at, title, description,
                        tags_json, thumbnail_url, metadata_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        now,
                        video.get("title", ""),
                        video.get("description", ""),
                        tags_json,
                        video.get("thumbnail_url", ""),
                        video.get("metadata_hash", ""),
                    ),
                )

            connection.execute(
                """
                INSERT OR IGNORE INTO video_statistics (
                    youtube_video_id, captured_at, view_count, like_count, comment_count
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    video_id,
                    now,
                    video.get("view_count"),
                    video.get("like_count"),
                    video.get("comment_count"),
                ),
            )

        return {"is_new": is_new, "metadata_changed": metadata_changed}

    def list_videos(self, channel_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = """
            SELECT v.*,
                   (SELECT provider FROM video_analyses a
                    WHERE a.youtube_video_id = v.youtube_video_id AND a.analysis_type = 'metadata'
                    ORDER BY a.id DESC LIMIT 1) AS analysis_provider,
                   (SELECT created_at FROM video_analyses a
                    WHERE a.youtube_video_id = v.youtube_video_id AND a.analysis_type = 'metadata'
                    ORDER BY a.id DESC LIMIT 1) AS analysis_completed_at,
                   EXISTS(
                       SELECT 1 FROM video_analyses a
                       WHERE a.youtube_video_id = v.youtube_video_id AND a.analysis_type = 'writer'
                   ) AS has_writer_content,
                   EXISTS(
                       SELECT 1 FROM transcripts t
                       WHERE t.youtube_video_id = v.youtube_video_id
                   ) AS has_transcript
            FROM videos v
        """
        params: list[Any] = []
        if channel_id:
            query += " WHERE v.youtube_channel_id = ?"
            params.append(channel_id)
        query += " ORDER BY COALESCE(v.published_at, v.first_seen_at) DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["tags"] = json.loads(item.pop("tags_json") or "[]")
            item.pop("raw_payload_json", None)
            result.append(item)
        return result

    def get_video(self, video_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT v.*,
                       EXISTS(
                           SELECT 1 FROM transcripts t
                           WHERE t.youtube_video_id = v.youtube_video_id
                       ) AS has_transcript
                FROM videos v
                WHERE v.youtube_video_id = ?
                """,
                (video_id,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["tags"] = json.loads(item.pop("tags_json") or "[]")
        item.pop("raw_payload_json", None)
        return item

    def mark_video_downloaded(
        self, video_id: str, file_path: str, media_kind: str = ""
    ) -> None:
        """Record the downloaded file and, when known, what kind it is.

        The kind decides which workflow can run at all: a source with no
        picture cannot have scenes cut out of it, however willing the rest of
        the pipeline is to try.
        """
        with self._connect() as connection:
            connection.execute(
                "UPDATE videos SET media_status = 'downloaded_for_editing', local_media_path = ?, "
                "media_kind = ? WHERE youtube_video_id = ?",
                (file_path, str(media_kind or "").strip().lower(), video_id),
            )

    def set_video_media_kind(self, video_id: str, media_kind: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE videos SET media_kind = ? WHERE youtube_video_id = ?",
                (str(media_kind or "").strip().lower(), video_id),
            )

    def mark_video_media_deleted(self, video_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE videos SET media_status = 'not_downloaded', local_media_path = NULL, "
                "media_kind = '' WHERE youtube_video_id = ?",
                (video_id,),
            )

    def create_production_project(
        self,
        video_id: str,
        title: str = "",
        notes: str = "",
        managed_channel_id: int | None = None,
    ) -> dict[str, Any] | None:
        video = self.get_video(video_id)
        if not video:
            return None
        if managed_channel_id is not None and not self.get_managed_channel(int(managed_channel_id)):
            raise ValueError("Không tìm thấy kênh xuất bản đã chọn")
        now = utc_now()
        project_title = title.strip() or str(video.get("title") or video_id).strip()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO production_projects (
                    youtube_video_id, title, status, notes, managed_channel_id, created_at, updated_at
                ) VALUES (?, ?, 'draft', ?, ?, ?, ?)
                ON CONFLICT(youtube_video_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    managed_channel_id = COALESCE(excluded.managed_channel_id, production_projects.managed_channel_id)
                """,
                (video_id, project_title, notes.strip(), managed_channel_id, now, now),
            )
            row = connection.execute(
                "SELECT id FROM production_projects WHERE youtube_video_id = ?",
                (video_id,),
            ).fetchone()
        project = self.get_production_project(int(row["id"])) if row else None
        if project and managed_channel_id is not None:
            with self._connect() as connection:
                has_render_settings = connection.execute(
                    "SELECT 1 FROM project_render_settings WHERE project_id = ?",
                    (int(project["id"]),),
                ).fetchone()
            if not has_render_settings:
                self.apply_managed_channel_preset(int(project["id"]))
                project = self.get_production_project(int(project["id"]))
        return project

    def create_idea_project(
        self,
        goal: str,
        *,
        title: str = "",
        language: str = "vi",
    ) -> dict[str, Any]:
        """Create a content project without requiring a real source video."""
        channel_id = "UC_YOUTUBE_AI_FACTORY_IDEAS"
        idea_id = f"idea-{uuid.uuid4().hex}"
        cleaned_goal = goal.strip()
        project_title = title.strip() or cleaned_goal[:160] or "AI video project"
        self.upsert_channel(
            {
                "youtube_channel_id": channel_id,
                "channel_url": "local://youtube-ai-factory/ideas",
                "title": "YouTube AI Factory Ideas",
                "description": "Internal source for high-level AI video requests",
                "uploads_playlist_id": "",
            }
        )
        self.upsert_video(
            {
                "youtube_video_id": idea_id,
                "youtube_channel_id": channel_id,
                "video_url": f"local://idea/{idea_id}",
                "title": project_title,
                "description": cleaned_goal,
                "default_language": language.strip() or "vi",
                "metadata_hash": uuid.uuid5(uuid.NAMESPACE_URL, cleaned_goal or idea_id).hex,
                "raw_payload": {"source": "high_level_request", "goal": cleaned_goal},
            }
        )
        project = self.create_production_project(
            idea_id,
            title=project_title,
            notes=cleaned_goal,
        )
        if project is None:
            raise RuntimeError("Không tạo được project từ yêu cầu cấp cao")
        self.set_project_workflow(int(project["id"]), "content")
        created = self.get_production_project(int(project["id"]))
        if created is None:
            raise RuntimeError("Project vừa tạo không còn tồn tại")
        self.emit_domain_event(
            "project.created",
            project_id=int(created["id"]),
            aggregate_type="production_project",
            aggregate_id=int(created["id"]),
            source="orchestrator",
            payload={"goal": cleaned_goal, "source": "high_level_request"},
        )
        return created

    def list_production_projects(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT p.*,
                       m.name AS managed_channel_name,
                       m.channel_url AS managed_channel_url,
                       m.workflow_reference_channel_id,
                       m.output_profile AS managed_channel_output_profile,
                       workflow.title AS workflow_reference_title,
                       v.title AS source_title,
                       v.video_url,
                       v.thumbnail_url,
                       v.youtube_channel_id,
                       v.published_at,
                       EXISTS(
                           SELECT 1 FROM transcripts t
                           WHERE t.youtube_video_id = p.youtube_video_id
                       ) AS has_transcript,
                       EXISTS(
                           SELECT 1 FROM video_analyses a
                           WHERE a.youtube_video_id = p.youtube_video_id
                             AND a.analysis_type = 'writer'
                       ) AS has_writer_content,
                       COALESCE((
                           SELECT publication.status
                           FROM project_publications publication
                           WHERE publication.project_id = p.id
                           ORDER BY publication.id DESC
                           LIMIT 1
                       ), '') AS publication_status,
                       COALESCE((
                           SELECT publication.youtube_video_id
                           FROM project_publications publication
                           WHERE publication.project_id = p.id
                           ORDER BY publication.id DESC
                           LIMIT 1
                       ), '') AS published_youtube_video_id,
                       (SELECT publication.published_at
                        FROM project_publications publication
                        WHERE publication.project_id = p.id
                        ORDER BY publication.id DESC
                        LIMIT 1) AS project_published_at,
                       EXISTS(
                           SELECT 1 FROM project_publications publication
                           WHERE publication.project_id = p.id
                             AND publication.status = 'published'
                       ) AS is_published
                FROM production_projects p
                JOIN videos v ON v.youtube_video_id = p.youtube_video_id
                LEFT JOIN managed_channels m ON m.id = p.managed_channel_id
                LEFT JOIN channels workflow ON workflow.youtube_channel_id = m.workflow_reference_channel_id
                ORDER BY p.updated_at DESC, p.id DESC
                LIMIT ?
                """,
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_production_project(self, project_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT p.*,
                       m.name AS managed_channel_name,
                       m.channel_url AS managed_channel_url,
                       m.workflow_reference_channel_id,
                       m.output_profile AS managed_channel_output_profile,
                       workflow.title AS workflow_reference_title,
                       v.title AS source_title,
                       v.video_url,
                       v.thumbnail_url,
                       v.youtube_channel_id,
                       v.published_at,
                       EXISTS(
                           SELECT 1 FROM transcripts t
                           WHERE t.youtube_video_id = p.youtube_video_id
                       ) AS has_transcript,
                       EXISTS(
                           SELECT 1 FROM video_analyses a
                           WHERE a.youtube_video_id = p.youtube_video_id
                             AND a.analysis_type = 'writer'
                       ) AS has_writer_content
                FROM production_projects p
                JOIN videos v ON v.youtube_video_id = p.youtube_video_id
                LEFT JOIN managed_channels m ON m.id = p.managed_channel_id
                LEFT JOIN channels workflow ON workflow.youtube_channel_id = m.workflow_reference_channel_id
                WHERE p.id = ?
                """,
                (project_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_production_project(
        self,
        project_id: int,
        title: str | None = None,
        status: str | None = None,
        notes: str | None = None,
        managed_channel_id: int | None = None,
    ) -> dict[str, Any] | None:
        existing = self.get_production_project(project_id)
        if not existing:
            return None
        next_title = existing["title"] if title is None else title.strip()
        next_status = existing["status"] if status is None else status
        next_notes = existing["notes"] if notes is None else notes.strip()
        next_managed_channel_id = existing.get("managed_channel_id") if managed_channel_id is None else int(managed_channel_id)
        if next_managed_channel_id is not None and not self.get_managed_channel(next_managed_channel_id):
            raise ValueError("Không tìm thấy kênh xuất bản đã chọn")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE production_projects
                SET title = ?, status = ?, notes = ?, managed_channel_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (next_title, next_status, next_notes, next_managed_channel_id, utc_now(), project_id),
            )
        return self.get_production_project(project_id)

    def update_production_project_gflow(
        self,
        project_id: int,
        gflow_project_id: str,
        gflow_profile: str,
    ) -> dict[str, Any] | None:
        """Attach one Google Flow project to one local production project."""
        if not self.get_production_project(project_id):
            return None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE production_projects
                SET gflow_project_id = ?, gflow_profile = ?, updated_at = ?
                WHERE id = ?
                """,
                (gflow_project_id.strip(), gflow_profile.strip(), utc_now(), project_id),
            )
        return self.get_production_project(project_id)

    def get_production_project_bundle(
        self,
        project_id: int,
        transcript_text_limit: int | None = 2_000,
    ) -> dict[str, Any] | None:
        project = self.get_production_project(project_id)
        if not project:
            return None

        video_id = str(project["youtube_video_id"])
        video = self.get_video(video_id)
        if not video:
            return None

        transcript = self.get_transcript(video_id, transcript_format="txt") or self.get_transcript(video_id)
        if transcript and transcript_text_limit is not None:
            content = str(transcript.get("content_text") or "")
            transcript = dict(transcript)
            transcript["content_text_truncated"] = len(content) > transcript_text_limit
            transcript["content_text"] = content[:transcript_text_limit]

        metadata_analysis = self.get_video_analysis(video_id, analysis_type="metadata")
        reference_analysis = self.get_video_analysis(video_id, analysis_type="reference")
        writer_content = self.get_video_analysis(video_id, analysis_type="writer")
        latest_script = self.get_latest_project_script(project_id)
        latest_shots = self.list_project_shots(
            project_id,
            script_id=int(latest_script["id"]) if latest_script else None,
        ) if latest_script else []
        latest_timeline = self.list_project_timeline(
            project_id,
            script_id=int(latest_script["id"]) if latest_script else None,
        ) if latest_script else []
        if latest_script and latest_timeline:
            latest_timeline = self.attach_edit_beats_to_timeline(
                project_id,
                latest_timeline,
                script_id=int(latest_script["id"]),
            )
        latest_edit_beats = {
            str(segment["id"]): segment.get("edit_beats") or []
            for segment in latest_timeline
        }
        production_jobs = self.list_project_jobs(project_id, limit=20)
        production_job_events = {
            str(job["id"]): self.list_project_job_events(int(job["id"]), limit=20)
            for job in production_jobs
        }
        publications = self.list_project_publications(project_id, limit=20)
        project_assets = self.list_project_assets(project_id)
        thumbnails = self.list_project_thumbnails(project_id)
        scene_generation_jobs = self.list_scene_generation_jobs(project_id, limit=100)
        readiness = {
            "has_metadata_analysis": bool(metadata_analysis),
            "has_transcript": bool(transcript),
            "has_writer_content": bool(writer_content),
            "has_script": bool(latest_script),
            "script_approved": bool(latest_script and latest_script.get("status") == "approved"),
            "has_shot_plan": bool(latest_shots),
            "has_timeline": bool(latest_timeline),
            "has_voiceover": any(
                job.get("job_type") in {"voiceover", "premiere_draft", "director_production"}
                and job.get("status") == "completed"
                for job in production_jobs
            ),
            "has_render": any(
                job.get("job_type") in {"render", "director_production"} and job.get("status") == "completed"
                for job in production_jobs
            ),
            "has_assets": bool(project_assets),
            "has_thumbnail": any(bool(item.get("selected")) for item in thumbnails),
            "ready_for_review": bool(latest_script),
            "approved": project.get("status") == "approved",
        }
        next_actions: list[str] = []
        if not metadata_analysis:
            next_actions.append("Chạy phân tích metadata cho video nguồn.")
        if not transcript:
            next_actions.append("Bổ sung transcript có quyền sử dụng hoặc chạy Whisper sau khi xác nhận.")
        if not writer_content:
            next_actions.append("Chạy AI Writer để tạo tiêu đề, mô tả, CTA và dàn ý kịch bản mới.")
        if writer_content and not latest_script:
            next_actions.append("Tạo bản nháp kịch bản sản xuất từ AI Writer.")
        if latest_script and latest_script.get("status") == "draft":
            next_actions.append("Sửa kịch bản và chuyển sang trạng thái chờ duyệt.")
        if latest_script and latest_script.get("status") == "review":
            next_actions.append("Kiểm duyệt kịch bản và bấm duyệt nếu đã đạt yêu cầu.")
        if latest_script and latest_script.get("status") == "approved" and not latest_shots:
            next_actions.append("Tạo shot list để chuẩn bị dựng video, B-roll và thumbnail.")
        if latest_shots:
            next_actions.append("Rà soát shot list và bổ sung prompt hình ảnh/B-roll cho từng cảnh.")
        if latest_shots and not latest_timeline:
            next_actions.append("Tạo voiceover segments và timeline để chuẩn bị TTS, phụ đề và FFmpeg.")
        if latest_timeline:
            next_actions.append("Rà soát timeline, gắn file audio/visual và chuyển các segment sang sẵn sàng.")
        if latest_timeline and not readiness["has_voiceover"]:
            next_actions.append("Chạy voiceover dry-run hoặc kết nối pyVideoTrans sau khi kiểm tra lời thoại.")
        if readiness["has_voiceover"] and not readiness["has_render"]:
            next_actions.append("Chuẩn bị asset hình ảnh/video rồi chạy render worker bằng FFmpeg.")
        if readiness["has_render"] and not readiness["has_thumbnail"]:
            next_actions.append("Tạo và chọn thumbnail trước khi xuất bản.")
        if writer_content and project.get("status") not in {"review", "approved"}:
            next_actions.append("Chuyển project sang trạng thái chờ duyệt.")
        if project.get("status") == "approved":
            next_actions.append("Có thể chuyển sang workflow dựng video/thumbnail.")

        return {
            "project": project,
            "source_video": video,
            "latest_transcript": transcript,
            "metadata_analysis": metadata_analysis,
            "reference_analysis": reference_analysis,
            "writer_content": writer_content,
            "latest_script": latest_script,
            "latest_shots": latest_shots,
            "latest_timeline": latest_timeline,
            "edit_beats": latest_edit_beats,
            "production_jobs": production_jobs,
            "production_job_events": production_job_events,
            "publications": publications,
            "project_assets": project_assets,
            "thumbnails": thumbnails,
            "render_settings": self.get_project_render_settings(project_id),
            "scene_generation_jobs": scene_generation_jobs,
            "readiness": readiness,
            "next_actions": next_actions,
        }

    def create_project_script(
        self,
        project_id: int,
        script_title: str = "",
        hook: str = "",
        intro: str = "",
        main_content: str = "",
        cta: str = "",
        status: str = "draft",
        variant: str = "long",
    ) -> dict[str, Any] | None:
        if not self.get_production_project(project_id):
            return None
        now = utc_now()
        with self._connect() as connection:
            # One counter for every script of the project, short or long: the
            # table declares UNIQUE(project_id, version), and numbering per
            # variant would collide on the short's first version. Rebuilding
            # the table to relax that constraint is not worth it - a version
            # is an ordering, and the variant already says which video it is.
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM project_scripts WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            version = int(row["next_version"])
            cursor = connection.execute(
                """
                INSERT INTO project_scripts (
                    project_id, version, script_title, hook, intro, main_content,
                    cta, status, created_at, updated_at, variant
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    version,
                    script_title.strip(),
                    hook.strip(),
                    intro.strip(),
                    main_content.strip(),
                    cta.strip(),
                    status,
                    now,
                    now,
                    variant,
                ),
            )
            connection.execute(
                "UPDATE production_projects SET status = 'script', updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            script_id = int(cursor.lastrowid)
        return self.get_project_script(script_id)

    def get_project_script(self, script_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM project_scripts WHERE id = ?",
                (script_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_latest_project_script(
        self, project_id: int, variant: str = "long"
    ) -> dict[str, Any] | None:
        """The newest script of one kind - the long video's unless asked.

        Defaulting to the long one matters: every caller that predates the
        short variant asks this question without naming a kind, and a short
        answering them would put the wrong words into the storyboard and the
        voiceover - the failure this project has already been through once.
        """
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM project_scripts
                WHERE project_id = ? AND variant = ?
                ORDER BY version DESC, id DESC
                LIMIT 1
                """,
                (project_id, variant),
            ).fetchone()
        return dict(row) if row else None

    def list_project_scripts(
        self, project_id: int, variant: str | None = "long"
    ) -> list[dict[str, Any]]:
        """Script versions of one kind; pass variant=None for every kind."""
        clauses = ["project_id = ?"]
        params: list[Any] = [project_id]
        if variant is not None:
            clauses.append("variant = ?")
            params.append(variant)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM project_scripts
                WHERE {' AND '.join(clauses)}
                ORDER BY version DESC, id DESC
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def update_project_script(
        self,
        script_id: int,
        script_title: str | None = None,
        hook: str | None = None,
        intro: str | None = None,
        main_content: str | None = None,
        cta: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        existing = self.get_project_script(script_id)
        if not existing:
            return None
        values = {
            "script_title": existing["script_title"] if script_title is None else script_title.strip(),
            "hook": existing["hook"] if hook is None else hook.strip(),
            "intro": existing["intro"] if intro is None else intro.strip(),
            "main_content": existing["main_content"] if main_content is None else main_content.strip(),
            "cta": existing["cta"] if cta is None else cta.strip(),
            "status": existing["status"] if status is None else status,
        }
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE project_scripts
                SET script_title = ?, hook = ?, intro = ?, main_content = ?,
                    cta = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    values["script_title"],
                    values["hook"],
                    values["intro"],
                    values["main_content"],
                    values["cta"],
                    values["status"],
                    utc_now(),
                    script_id,
                ),
            )
        return self.get_project_script(script_id)

    def approve_project_script(self, script_id: int) -> dict[str, Any] | None:
        existing = self.get_project_script(script_id)
        if not existing:
            return None
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE project_scripts
                SET status = 'approved', approved_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, script_id),
            )
            connection.execute(
                "UPDATE production_projects SET status = 'approved', updated_at = ? WHERE id = ?",
                (now, existing["project_id"]),
            )
        return self.get_project_script(script_id)

    def create_project_shots(
        self,
        project_id: int,
        script_id: int,
        shots: list[dict[str, Any]],
        force: bool = False,
    ) -> list[dict[str, Any]] | None:
        if not self.get_production_project(project_id) or not self.get_project_script(script_id):
            return None
        existing = self.list_project_shots(project_id, script_id=script_id)
        if existing and not force:
            return existing
        now = utc_now()
        with self._connect() as connection:
            if force:
                connection.execute(
                    "DELETE FROM project_shots WHERE project_id = ? AND script_id = ?",
                    (project_id, script_id),
                )
            for shot in shots:
                connection.execute(
                    """
                    INSERT INTO project_shots (
                        project_id, script_id, shot_index, section, narration,
                        speaker, visual_prompt, asset_type, duration_seconds, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        script_id,
                        int(shot.get("shot_index") or 1),
                        str(shot.get("section") or "main").strip(),
                        str(shot.get("narration") or "").strip(),
                        str(shot.get("speaker") or "").strip(),
                        str(shot.get("visual_prompt") or "").strip(),
                        str(shot.get("asset_type") or "broll").strip(),
                        int(shot.get("duration_seconds") or 8),
                        str(shot.get("status") or "planned").strip(),
                        now,
                        now,
                    ),
                )
            connection.execute(
                "UPDATE production_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        return self.list_project_shots(project_id, script_id=script_id)

    def list_project_shots(
        self,
        project_id: int,
        script_id: int | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM project_shots WHERE project_id = ?"
        params: list[Any] = [project_id]
        if script_id is not None:
            query += " AND script_id = ?"
            params.append(script_id)
        query += " ORDER BY shot_index ASC, id ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_project_shot(self, shot_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM project_shots WHERE id = ?",
                (shot_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_project_shot(
        self,
        shot_id: int,
        narration: str | None = None,
        visual_prompt: str | None = None,
        asset_type: str | None = None,
        duration_seconds: int | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        existing = self.get_project_shot(shot_id)
        if not existing:
            return None
        values = {
            "narration": existing["narration"] if narration is None else narration.strip(),
            "visual_prompt": existing["visual_prompt"] if visual_prompt is None else visual_prompt.strip(),
            "asset_type": existing["asset_type"] if asset_type is None else asset_type.strip(),
            "duration_seconds": existing["duration_seconds"] if duration_seconds is None else duration_seconds,
            "status": existing["status"] if status is None else status,
        }
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE project_shots
                SET narration = ?, visual_prompt = ?, asset_type = ?,
                    duration_seconds = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    values["narration"],
                    values["visual_prompt"],
                    values["asset_type"],
                    int(values["duration_seconds"]),
                    values["status"],
                    utc_now(),
                    shot_id,
                ),
            )
        return self.get_project_shot(shot_id)

    def create_project_shot(
        self,
        project_id: int,
        script_id: int,
        *,
        section: str = "main",
        narration: str = "",
        speaker: str = "",
        visual_prompt: str = "",
        asset_type: str = "broll",
        duration_seconds: int = 8,
        status: str = "planned",
        after_shot_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Create one storyboard card and insert it at a stable position.

        Shot indexes are kept contiguous inside one script version. The
        timeline is deliberately not regenerated here: its audio/assets can
        be expensive work, so the editor lets the user review the storyboard
        first and explicitly rebuild the timeline afterward.
        """
        script = self.get_project_script(script_id)
        if not self.get_production_project(project_id) or not script or int(script["project_id"]) != project_id:
            return None
        now = utc_now()
        with self._connect() as connection:
            if after_shot_id is not None:
                anchor = connection.execute(
                    """
                    SELECT shot_index FROM project_shots
                    WHERE id = ? AND project_id = ? AND script_id = ?
                    """,
                    (after_shot_id, project_id, script_id),
                ).fetchone()
                if not anchor:
                    raise ValueError("Anchor shot does not belong to this script")
                shot_index = int(anchor["shot_index"]) + 1
            else:
                row = connection.execute(
                    """
                    SELECT COALESCE(MAX(shot_index), 0) AS max_index
                    FROM project_shots WHERE project_id = ? AND script_id = ?
                    """,
                    (project_id, script_id),
                ).fetchone()
                shot_index = int(row["max_index"]) + 1

            # The UNIQUE(script_id, shot_index) constraint means a direct
            # +1 update can collide. Shift through negative values first.
            connection.execute(
                """
                UPDATE project_shots
                SET shot_index = -(shot_index + 1), updated_at = ?
                WHERE project_id = ? AND script_id = ? AND shot_index >= ?
                """,
                (now, project_id, script_id, shot_index),
            )
            connection.execute(
                """
                UPDATE project_shots SET shot_index = -shot_index
                WHERE project_id = ? AND script_id = ? AND shot_index < 0
                """,
                (project_id, script_id),
            )
            cursor = connection.execute(
                """
                INSERT INTO project_shots (
                    project_id, script_id, shot_index, section, narration,
                    speaker, visual_prompt, asset_type, duration_seconds, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    script_id,
                    shot_index,
                    section.strip() or "main",
                    narration.strip(),
                    speaker.strip(),
                    visual_prompt.strip(),
                    asset_type.strip() or "broll",
                    max(1, int(duration_seconds)),
                    status.strip() or "planned",
                    now,
                    now,
                ),
            )
            connection.execute(
                "UPDATE production_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        return self.get_project_shot(int(cursor.lastrowid))

    def duplicate_project_shot(self, shot_id: int) -> dict[str, Any] | None:
        """Duplicate a card immediately after its source card."""
        source = self.get_project_shot(shot_id)
        if not source:
            return None
        return self.create_project_shot(
            int(source["project_id"]),
            int(source["script_id"]),
            section=str(source["section"]),
            narration=str(source["narration"]),
            visual_prompt=str(source["visual_prompt"]),
            asset_type=str(source["asset_type"]),
            duration_seconds=int(source["duration_seconds"]),
            status="planned",
            after_shot_id=shot_id,
        )

    def reorder_project_shots(
        self,
        project_id: int,
        shot_ids: list[int],
        script_id: int | None = None,
    ) -> list[dict[str, Any]]:
        requested = [int(item) for item in shot_ids]
        with self._connect() as connection:
            query = "SELECT id, script_id FROM project_shots WHERE project_id = ?"
            params: list[Any] = [project_id]
            if script_id is not None:
                query += " AND script_id = ?"
                params.append(script_id)
            query += " ORDER BY shot_index ASC, id ASC"
            rows = connection.execute(query, params).fetchall()
            existing_ids = [int(row["id"]) for row in rows]
            if not requested or set(requested) != set(existing_ids) or len(requested) != len(existing_ids):
                raise ValueError("Danh sách shot reorder không đủ hoặc không thuộc project")
            script_ids = {int(row["script_id"]) for row in rows}
            if len(script_ids) != 1:
                raise ValueError("Chỉ reorder shot trong cùng một phiên bản kích bản")
            selected_script_id = next(iter(script_ids))
            now = utc_now()
            # Move to temporary negative indexes first so UNIQUE(script_id,
            # shot_index) never collides while two cards are swapped.
            connection.execute(
                "UPDATE project_shots SET shot_index = -id, updated_at = ? WHERE project_id = ? AND script_id = ?",
                (now, project_id, selected_script_id),
            )
            for index, shot_id in enumerate(requested, start=1):
                connection.execute(
                    "UPDATE project_shots SET shot_index = ?, updated_at = ? WHERE id = ? AND project_id = ?",
                    (index, now, shot_id, project_id),
                )
            connection.execute(
                "UPDATE production_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        return self.list_project_shots(project_id, script_id=selected_script_id)

    def delete_project_shot(self, shot_id: int) -> bool:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT project_id, script_id FROM project_shots WHERE id = ?", (shot_id,)
            ).fetchone()
            if not existing:
                return False
            cursor = connection.execute("DELETE FROM project_shots WHERE id = ?", (shot_id,))
            rows = connection.execute(
                """
                SELECT id FROM project_shots WHERE project_id = ? AND script_id = ?
                ORDER BY shot_index ASC, id ASC
                """,
                (existing["project_id"], existing["script_id"]),
            ).fetchall()
            now = utc_now()
            for index, row in enumerate(rows, start=1):
                connection.execute(
                    "UPDATE project_shots SET shot_index = ?, updated_at = ? WHERE id = ?",
                    (index, now, row["id"]),
                )
            connection.execute(
                "UPDATE production_projects SET updated_at = ? WHERE id = ?",
                (now, existing["project_id"]),
            )
        return cursor.rowcount == 1

    def create_project_timeline(
        self,
        project_id: int,
        script_id: int,
        segments: list[dict[str, Any]],
        force: bool = False,
    ) -> list[dict[str, Any]] | None:
        project = self.get_production_project(project_id)
        script = self.get_project_script(script_id)
        if not project or not script or int(script["project_id"]) != project_id:
            return None
        existing = self.list_project_timeline(project_id, script_id=script_id)
        if existing and not force:
            return existing
        now = utc_now()
        with self._connect() as connection:
            if force:
                connection.execute(
                    "DELETE FROM project_timeline_segments WHERE project_id = ? AND script_id = ?",
                    (project_id, script_id),
                )
            for segment in segments:
                connection.execute(
                    """
                    INSERT INTO project_timeline_segments (
                        project_id, script_id, shot_id, segment_index, section,
                        voice_text, subtitle_text, speaker, visual_prompt, asset_type,
                        duration_seconds, start_seconds, end_seconds, audio_path,
                        visual_path, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        script_id,
                        segment.get("shot_id"),
                        int(segment.get("segment_index") or 1),
                        str(segment.get("section") or "main").strip(),
                        str(segment.get("voice_text") or "").strip(),
                        str(segment.get("subtitle_text") or segment.get("voice_text") or "").strip(),
                        str(segment.get("speaker") or "").strip(),
                        str(segment.get("visual_prompt") or "").strip(),
                        str(segment.get("asset_type") or "broll").strip(),
                        max(1, int(segment.get("duration_seconds") or 8)),
                        max(0, int(segment.get("start_seconds") or 0)),
                        max(1, int(segment.get("end_seconds") or 8)),
                        str(segment.get("audio_path") or "").strip(),
                        str(segment.get("visual_path") or "").strip(),
                        str(segment.get("status") or "planned").strip(),
                        now,
                        now,
                    ),
                )
            connection.execute(
                "UPDATE production_projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            self._reflow_project_timeline(connection, project_id, script_id)
        return self.list_project_timeline(project_id, script_id=script_id)

    @staticmethod
    def _reflow_project_timeline(
        connection: sqlite3.Connection,
        project_id: int,
        script_id: int,
    ) -> None:
        rows = connection.execute(
            """
            SELECT id, duration_seconds
            FROM project_timeline_segments
            WHERE project_id = ? AND script_id = ?
            ORDER BY segment_index ASC, id ASC
            """,
            (project_id, script_id),
        ).fetchall()
        cursor = 0
        now = utc_now()
        for row in rows:
            duration = max(1, int(row["duration_seconds"] or 1))
            connection.execute(
                """
                UPDATE project_timeline_segments
                SET duration_seconds = ?, start_seconds = ?, end_seconds = ?, updated_at = ?
                WHERE id = ?
                """,
                (duration, cursor, cursor + duration, now, int(row["id"])),
            )
            cursor += duration

    def list_project_timeline(
        self,
        project_id: int,
        script_id: int | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM project_timeline_segments WHERE project_id = ?"
        params: list[Any] = [project_id]
        if script_id is not None:
            query += " AND script_id = ?"
            params.append(script_id)
        query += " ORDER BY segment_index ASC, id ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_project_timeline_segment(self, segment_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM project_timeline_segments WHERE id = ?",
                (segment_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_project_timeline_segment(
        self,
        segment_id: int,
        voice_text: str | None = None,
        subtitle_text: str | None = None,
        visual_prompt: str | None = None,
        asset_type: str | None = None,
        duration_seconds: int | None = None,
        audio_path: str | None = None,
        visual_path: str | None = None,
        subtitle_path: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        existing = self.get_project_timeline_segment(segment_id)
        if not existing:
            return None
        # Only the columns the caller actually passed are written. Rewriting
        # all nine from a read taken beforehand loses the other job's work
        # whenever two run at once: cutting the scene and generating the
        # voice each read the row before the other had written, so whichever
        # finished last put back an empty path for the half it had not seen.
        # The scene and the voice then took turns erasing each other.
        updates: list[tuple[str, Any]] = []
        if voice_text is not None:
            updates.append(("voice_text", voice_text.strip()))
        if subtitle_text is not None:
            updates.append(("subtitle_text", subtitle_text.strip()))
        if visual_prompt is not None:
            updates.append(("visual_prompt", visual_prompt.strip()))
        if asset_type is not None:
            updates.append(("asset_type", asset_type.strip()))
        if duration_seconds is not None:
            updates.append(("duration_seconds", max(1, int(duration_seconds))))
        if audio_path is not None:
            updates.append(("audio_path", audio_path.strip()))
        if visual_path is not None:
            updates.append(("visual_path", visual_path.strip()))
        if subtitle_path is not None:
            updates.append(("subtitle_path", subtitle_path.strip()))
        if status is not None:
            updates.append(("status", status))
        if not updates:
            return self.get_project_timeline_segment(segment_id)
        assignments = ", ".join(f"{column} = ?" for column, _ in updates)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE project_timeline_segments SET {assignments}, updated_at = ? WHERE id = ?",
                [*(value for _, value in updates), utc_now(), segment_id],
            )
            self._reflow_project_timeline(
                connection,
                int(existing["project_id"]),
                int(existing["script_id"]),
            )
        return self.get_project_timeline_segment(segment_id)

    def create_project_job(
        self,
        project_id: int,
        script_id: int,
        job_type: str,
        provider: str,
        force: bool = False,
        segment_id: int | None = None,
    ) -> dict[str, Any] | None:
        project = self.get_production_project(project_id)
        script = self.get_project_script(script_id)
        if not project or not script or int(script["project_id"]) != project_id:
            return None
        with self._connect() as connection:
            if not force:
                active = connection.execute(
                    """
                    SELECT * FROM project_jobs
                    WHERE project_id = ? AND script_id = ? AND job_type = ?
                      AND status IN ('queued', 'running')
                      AND segment_id IS ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (project_id, script_id, job_type, segment_id),
                ).fetchone()
                if active:
                    return dict(active)
            now = utc_now()
            cursor = connection.execute(
                """
                INSERT INTO project_jobs (
                    project_id, script_id, job_type, provider, status,
                    segment_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?)
                """,
                (project_id, script_id, job_type.strip(), provider.strip(), segment_id, now, now),
            )
            job_id = int(cursor.lastrowid)
            self._add_project_job_event(
                connection,
                job_id,
                "info",
                f"Đã vào hàng đợi: {job_type.strip()} ({provider.strip()}).",
            )
        job = self.get_project_job(job_id)
        if job:
            self.emit_domain_event(
                "task.created",
                project_id=project_id,
                aggregate_type="project_job",
                aggregate_id=job_id,
                source="job_manager",
                payload={
                    "job_type": job_type.strip(),
                    "provider": provider.strip(),
                    "segment_id": segment_id,
                },
            )
        return job

    def get_project_job(self, job_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM project_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_project_jobs(self, project_id: int, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM project_jobs
                WHERE project_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (project_id, max(1, min(limit, 100))),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _add_project_job_event(
        connection: sqlite3.Connection,
        job_id: int,
        level: str,
        message: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO project_job_events (job_id, level, message, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (job_id, level, message.strip(), utc_now()),
        )

    def list_project_job_events(self, job_id: int, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM project_job_events
                WHERE job_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (job_id, max(1, min(limit, 100))),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_queued_project_job_ids(self) -> list[int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM project_jobs WHERE status = 'queued' ORDER BY id ASC"
            ).fetchall()
        return [int(row["id"]) for row in rows]

    def requeue_interrupted_project_jobs(self) -> int:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM project_jobs WHERE status = 'running'"
            ).fetchall()
            cursor = connection.execute(
                """
                UPDATE project_jobs
                SET status = 'queued', error = 'Worker đã dừng trước khi hoàn tất.',
                    updated_at = ?, started_at = NULL
                WHERE status = 'running'
                """,
                (utc_now(),),
            )
            for row in rows:
                self._add_project_job_event(
                    connection,
                    int(row["id"]),
                    "warning",
                    "Worker đã dừng; job được đưa lại vào hàng đợi.",
                )
        return int(cursor.rowcount)

    def claim_project_job(self, job_id: int) -> dict[str, Any] | None:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE project_jobs
                SET status = 'running', started_at = ?, updated_at = ?, error = ''
                WHERE id = ? AND status = 'queued'
                """,
                (now, now, job_id),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute(
                "SELECT * FROM project_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            self._add_project_job_event(connection, job_id, "info", "Worker đã bắt đầu xử lý job.")
        job = dict(row) if row else None
        if job:
            self.emit_domain_event(
                "task.started",
                project_id=int(job["project_id"]),
                aggregate_type="project_job",
                aggregate_id=job_id,
                source="production_worker",
                payload={"job_type": job["job_type"], "provider": job["provider"]},
            )
        return job

    def cancel_queued_project_job(self, job_id: int) -> dict[str, Any] | None:
        """Cancel a job which has not been claimed by the worker yet."""
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE project_jobs
                SET status = 'cancelled', error = 'Đã hủy bởi người dùng.',
                    updated_at = ?, completed_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (now, now, job_id),
            )
            self._add_project_job_event(connection, job_id, "warning", "Job đã được hủy trước khi worker bắt đầu.")
        return self.get_project_job(job_id)

    def finish_project_job(
        self,
        job_id: int,
        status: str,
        output_path: str = "",
        error: str = "",
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE project_jobs
                SET status = ?, output_path = ?, error = ?, updated_at = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (status, output_path, error, now, now if status in {"completed", "error", "cancelled"} else None, job_id),
            )
            if status == "completed":
                message = "Job hoàn tất." + (f" Đầu ra: {output_path}" if output_path else "")
                level = "info"
            elif status == "error":
                message = f"Job lỗi: {error or 'Không xác định.'}"
                level = "error"
            else:
                message = f"Job kết thúc với trạng thái: {status}."
                level = "warning"
            self._add_project_job_event(connection, job_id, level, message)
        job = self.get_project_job(job_id)
        if job:
            event_type = "task.completed" if status == "completed" else "task.failed"
            self.emit_domain_event(
                event_type,
                project_id=int(job["project_id"]),
                aggregate_type="project_job",
                aggregate_id=job_id,
                source="production_worker",
                payload={
                    "job_type": job["job_type"],
                    "provider": job["provider"],
                    "status": status,
                    "output_path": output_path,
                    "error": error,
                },
            )
            if status == "completed" and str(job.get("job_type")) in {"voiceover", "voiceover_segment"}:
                self.emit_domain_event(
                    "voice.completed",
                    project_id=int(job["project_id"]),
                    aggregate_type="project_job",
                    aggregate_id=job_id,
                    source="production_worker",
                    payload={"output_path": output_path, "segment_id": job.get("segment_id")},
                )
            if status == "completed" and str(job.get("job_type")) in {"render", "director_production"}:
                self.emit_domain_event(
                    "render.completed",
                    project_id=int(job["project_id"]),
                    aggregate_type="project_job",
                    aggregate_id=job_id,
                    source="render_engine",
                    payload={"output_path": output_path},
                )
        return job

    def project_job_status(self, project_id: int | None = None) -> dict[str, int]:
        query = "SELECT status, COUNT(*) AS count FROM project_jobs"
        params: list[Any] = []
        if project_id is not None:
            query += " WHERE project_id = ?"
            params.append(project_id)
        query += " GROUP BY status"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        result = {"queued": 0, "running": 0, "completed": 0, "error": 0, "cancelled": 0}
        for row in rows:
            result[str(row["status"])] = int(row["count"])
        return result

    def create_project_publication(
        self,
        project_id: int,
        local_file_path: str,
        title: str,
        description: str = "",
        tags: list[str] | None = None,
        category_id: str = "27",
        privacy_status: str = "private",
        scheduled_at: str | None = None,
        managed_channel_id: int | None = None,
        thumbnail_path: str = "",
        platform: str = "youtube",
        output_profile: str = "youtube_landscape",
        video_variant: str = "long",
        status: str = "queued",
    ) -> dict[str, Any] | None:
        if not self.get_production_project(project_id):
            return None
        if managed_channel_id is not None and not self.get_managed_channel(int(managed_channel_id)):
            raise ValueError("Không tìm thấy kênh xuất bản đã chọn")
        privacy = self._validate_privacy(privacy_status)
        clean_platform = self._validate_platform(platform)
        profile = self._validate_output_profile(output_profile)
        variant = video_variant.strip().lower()
        if variant not in {"long", "short"}:
            raise ValueError("Loại video xuất bản không được hỗ trợ")
        if status not in {"queued", "ready_manual"}:
            raise ValueError("Trạng thái publication không được hỗ trợ")
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO project_publications (
                    project_id, managed_channel_id, platform, output_profile, video_variant,
                    local_file_path, thumbnail_path, title,
                    description, tags_json, category_id, privacy_status,
                    scheduled_at, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    managed_channel_id,
                    clean_platform,
                    profile,
                    variant,
                    local_file_path.strip(),
                    thumbnail_path.strip(),
                    title.strip(),
                    description.strip(),
                    json.dumps(tags or [], ensure_ascii=False),
                    str(category_id or "27").strip(),
                    privacy,
                    scheduled_at.strip() if scheduled_at else None,
                    status,
                    now,
                    now,
                ),
            )
            publication_id = int(cursor.lastrowid)
        return self.get_project_publication(publication_id)

    def get_project_publication(self, publication_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM project_publications WHERE id = ?",
                (publication_id,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            item["tags"] = json.loads(item.pop("tags_json") or "[]")
        except (TypeError, ValueError):
            item["tags"] = []
        return item

    def list_project_publications(self, project_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM project_publications"
        params: list[Any] = []
        if project_id is not None:
            query += " WHERE project_id = ?"
            params.append(project_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["tags"] = json.loads(item.pop("tags_json") or "[]")
            except (TypeError, ValueError):
                item["tags"] = []
            result.append(item)
        return result

    def list_due_project_publications(
        self,
        now_iso: str,
        limit: int = 10,
        platforms: tuple[str, ...] = ("youtube",),
    ) -> list[dict[str, Any]]:
        """Publications due now that the app can actually deliver.

        A publication records which platform it is for, but the only uploader
        that exists is YouTube's. Without this filter the queue handed a
        TikTok or Facebook publication straight to the YouTube uploader, which
        does not check either - so the video was published, to the wrong
        place, on the user's real channel. Held-back rows stay queued and are
        counted by ``publications_awaiting_platform``.
        """
        allowed = tuple(str(item).strip().lower() for item in platforms if str(item).strip())
        if not allowed:
            return []
        placeholders = ", ".join("?" for _ in allowed)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM project_publications
                WHERE status = 'queued'
                  AND LOWER(platform) IN ({placeholders})
                  AND (scheduled_at IS NULL OR scheduled_at <= ?)
                ORDER BY COALESCE(scheduled_at, created_at) ASC, id ASC
                LIMIT ?
                """,
                (*allowed, now_iso, max(1, min(int(limit), 50))),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["tags"] = json.loads(item.pop("tags_json") or "[]")
            except (TypeError, ValueError):
                item["tags"] = []
            result.append(item)
        return result

    def retry_project_publication(self, publication_id: int) -> dict[str, Any] | None:
        """Requeue a failed/cancelled publication for immediate re-upload."""
        existing = self.get_project_publication(publication_id)
        if not existing or existing.get("status") not in {"error", "cancelled"}:
            return None
        retry_status = "queued" if str(existing.get("platform") or "youtube") == "youtube" else "ready_manual"
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE project_publications
                SET status = ?, scheduled_at = NULL, error = '', updated_at = ?
                WHERE id = ? AND status IN ('error', 'cancelled')
                """,
                (retry_status, utc_now(), publication_id),
            )
            if cursor.rowcount != 1:
                return None
        return self.get_project_publication(publication_id)

    def claim_project_publication(self, publication_id: int) -> dict[str, Any] | None:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE project_publications
                SET status = 'uploading', updated_at = ?, error = ''
                WHERE id = ? AND status = 'queued'
                """,
                (now, publication_id),
            )
            if cursor.rowcount != 1:
                return None
        return self.get_project_publication(publication_id)

    def finish_project_publication(
        self,
        publication_id: int,
        status: str,
        youtube_video_id: str = "",
        error: str = "",
    ) -> dict[str, Any] | None:
        if status not in {"completed", "error", "cancelled"}:
            raise ValueError("Trạng thái publication không hợp lệ")
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE project_publications
                SET status = ?, youtube_video_id = ?, error = ?, updated_at = ?,
                    published_at = ?
                WHERE id = ?
                """,
                (status, youtube_video_id.strip(), error.strip(), now, now if status == "completed" else None, publication_id),
            )
        return self.get_project_publication(publication_id)

    def publication_status(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM project_publications GROUP BY status"
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def publications_awaiting_platform(
        self, supported: tuple[str, ...] = ("youtube",)
    ) -> dict[str, int]:
        """Queued publications for platforms this app cannot upload to yet.

        They are not an error and not lost - they simply cannot be delivered,
        and saying so is the difference between a queue that looks stuck and
        one that explains itself.
        """
        allowed = tuple(str(item).strip().lower() for item in supported if str(item).strip())
        placeholders = ", ".join("?" for _ in allowed) or "''"
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT LOWER(platform) AS platform, COUNT(*) AS count
                FROM project_publications
                WHERE status = 'queued' AND LOWER(platform) NOT IN ({placeholders})
                GROUP BY LOWER(platform)
                """,
                allowed,
            ).fetchall()
        return {str(row["platform"]): int(row["count"]) for row in rows}

    def create_project_asset(
        self,
        project_id: int,
        asset_type: str,
        original_name: str,
        file_path: str,
        mime_type: str = "",
        file_size: int = 0,
        sha256: str = "",
    ) -> dict[str, Any] | None:
        if not self.get_production_project(project_id):
            return None
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO project_assets (
                    project_id, asset_type, original_name, file_path, mime_type,
                    file_size, sha256, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    asset_type.strip(),
                    original_name.strip(),
                    file_path.strip(),
                    mime_type.strip(),
                    max(0, int(file_size)),
                    sha256.strip(),
                    now,
                    now,
                ),
            )
            asset_id = int(cursor.lastrowid)
        return self.get_project_asset(asset_id)

    def get_project_asset(self, asset_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT a.*,
                       EXISTS(
                           SELECT 1 FROM project_asset_transcripts t
                           WHERE t.asset_id = a.id
                       ) AS has_transcript
                FROM project_assets a
                WHERE a.id = ?
                """,
                (asset_id,),
            ).fetchone()
        return dict(row) if row else None

    def find_project_asset_by_path(self, project_id: int, file_path: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT a.*,
                       EXISTS(
                           SELECT 1 FROM project_asset_transcripts t
                           WHERE t.asset_id = a.id
                       ) AS has_transcript
                FROM project_assets a
                WHERE a.project_id = ? AND a.file_path = ?
                ORDER BY a.id DESC LIMIT 1
                """,
                (project_id, file_path.strip()),
            ).fetchone()
        return dict(row) if row else None

    def rename_project_asset(self, asset_id: int, original_name: str) -> dict[str, Any] | None:
        asset = self.get_project_asset(asset_id)
        if not asset:
            return None
        name = original_name.strip()
        if not name:
            raise ValueError("Tên file không được để trống")
        with self._connect() as connection:
            connection.execute(
                "UPDATE project_assets SET original_name = ?, updated_at = ? WHERE id = ?",
                (name, utc_now(), asset_id),
            )
        return self.get_project_asset(asset_id)

    def create_project_thumbnail(
        self,
        project_id: int,
        asset_id: int,
        provider: str = "ffmpeg_frame",
        model: str = "ffmpeg",
        prompt: str = "",
        seed: int | None = None,
        video_variant: str = "long",
    ) -> dict[str, Any] | None:
        if video_variant not in {"long", "short"}:
            raise ValueError("Unknown thumbnail video variant")
        asset = self.get_project_asset(asset_id)
        if not asset or int(asset["project_id"]) != project_id or asset["asset_type"] != "image":
            return None
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO project_thumbnails (project_id, asset_id, provider, model, prompt, seed, created_at, video_variant)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, asset_id, provider.strip(), model.strip(), prompt.strip(), seed, utc_now(), video_variant),
            )
        return self.get_project_thumbnail(int(cursor.lastrowid))

    def get_project_thumbnail(self, thumbnail_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT t.*, a.original_name, a.file_path, a.mime_type, a.file_size
                FROM project_thumbnails t JOIN project_assets a ON a.id = t.asset_id
                WHERE t.id = ?
                """,
                (thumbnail_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_project_thumbnails(self, project_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT t.*, a.original_name, a.file_path, a.mime_type, a.file_size
                FROM project_thumbnails t JOIN project_assets a ON a.id = t.asset_id
                WHERE t.project_id = ? ORDER BY t.selected DESC, t.id DESC
                """,
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def select_project_thumbnail(self, thumbnail_id: int) -> dict[str, Any] | None:
        thumbnail = self.get_project_thumbnail(thumbnail_id)
        if not thumbnail:
            return None
        with self._connect() as connection:
            connection.execute("UPDATE project_thumbnails SET selected = 0 WHERE project_id = ? AND video_variant = ?", (thumbnail["project_id"], thumbnail["video_variant"]))
            connection.execute("UPDATE project_thumbnails SET selected = 1 WHERE id = ?", (thumbnail_id,))
        return self.get_project_thumbnail(thumbnail_id)

    def delete_project_thumbnail(self, thumbnail_id: int) -> dict[str, Any] | None:
        """Remove a thumbnail and the asset behind it.

        Returns what was deleted so the caller can remove the file too - the
        row is the only record of where it is.
        """
        thumbnail = self.get_project_thumbnail(thumbnail_id)
        if not thumbnail:
            return None
        with self._connect() as connection:
            connection.execute("DELETE FROM project_thumbnails WHERE id = ?", (thumbnail_id,))
            asset_id = thumbnail.get("asset_id")
            if asset_id:
                connection.execute("DELETE FROM project_assets WHERE id = ?", (int(asset_id),))
        return thumbnail

    def get_project_render_settings(self, project_id: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.project_id, s.music_asset_id, s.music_volume,
                       s.transition_style, s.output_profile, s.voice_provider,
                       s.voice_model, s.voice_rate, s.voice_reference_asset_id, s.voice_prompt_text,
                       s.subtitle_provider, s.subtitle_model,
                       s.publish_language, s.updated_at,
                       a.original_name AS music_asset_name,
                       a.file_path AS music_file_path,
                       voice_asset.original_name AS voice_reference_asset_name,
                       voice_asset.file_path AS voice_reference_file_path
                FROM project_render_settings s
                LEFT JOIN project_assets a ON a.id = s.music_asset_id
                LEFT JOIN project_assets voice_asset ON voice_asset.id = s.voice_reference_asset_id
                WHERE s.project_id = ?
                """,
                (project_id,),
            ).fetchone()
        if not row:
            return {
                "project_id": project_id,
                "music_asset_id": None,
                "music_asset_name": "",
                "music_file_path": "",
                "music_volume": 0.12,
                "transition_style": "fade",
                "output_profile": "youtube_landscape",
                "voice_provider": "edge_tts",
                "voice_model": "vi-VN-HoaiMyNeural",
                "voice_rate": "+0%",
                "voice_reference_asset_id": None,
                "voice_reference_asset_name": "",
                "voice_reference_file_path": "",
                "voice_prompt_text": "",
                "subtitle_provider": "timeline_text",
                "subtitle_model": "timeline",
                "publish_language": "vi",
            }
        return dict(row)

    def update_project_render_settings(
        self,
        project_id: int,
        music_asset_id: int | None = None,
        music_volume: float = 0.12,
        transition_style: str = "fade",
        output_profile: str = "youtube_landscape",
        voice_provider: str = "edge_tts",
        voice_model: str = "vi-VN-HoaiMyNeural",
        voice_rate: str = "+0%",
        voice_reference_asset_id: int | None = None,
        voice_prompt_text: str = "",
        subtitle_provider: str = "timeline_text",
        subtitle_model: str = "timeline",
        publish_language: str = "vi",
    ) -> dict[str, Any] | None:
        if not self.get_production_project(project_id):
            return None
        if music_asset_id is not None:
            asset = self.get_project_asset(music_asset_id)
            if not asset or int(asset["project_id"]) != project_id or asset["asset_type"] != "audio":
                raise ValueError("Nhạc nền phải là asset audio thuộc cùng project")
        style = transition_style.strip().lower()
        if style not in {"none", "fade"}:
            raise ValueError("Kiểu chuyển cảnh không được hỗ trợ")
        profile = output_profile.strip().lower()
        if profile not in {"youtube_landscape", "youtube_shorts", "instagram_reels", "tiktok", "facebook_reels", "facebook_feed"}:
            raise ValueError("Định dạng đầu ra không được hỗ trợ")
        provider = voice_provider.strip().lower()
        if provider not in {"edge_tts", "pyvideotrans", "voxcpm"}:
            raise ValueError("Model lồng tiếng chưa được tích hợp")
        model = voice_model.strip()
        rate = voice_rate.strip()
        if rate not in {"-25%", "-15%", "-8%", "+0%", "+8%", "+15%", "+25%"}:
            raise ValueError("Tốc độ giọng đọc không được hỗ trợ")
        if voice_reference_asset_id is not None:
            reference_asset = self.get_project_asset(int(voice_reference_asset_id))
            if (
                not reference_asset
                or int(reference_asset["project_id"]) != int(project_id)
                or reference_asset["asset_type"] != "audio"
            ):
                raise ValueError("File gióng mẫu phải là asset audio thuộc cùng project")
            if not Path(str(reference_asset.get("file_path") or "")).is_file():
                raise ValueError("Không tìm thấy file gióng mẫu trên máy")
        prompt = voice_prompt_text.strip()
        if not model:
            raise ValueError("Hãy chọn model lồng tiếng")
        subtitle_source = subtitle_provider.strip().lower()
        if subtitle_source not in {"timeline_text", "faster_whisper_local"}:
            raise ValueError("Nguồn phụ đề chưa được tích hợp")
        subtitle_engine = subtitle_model.strip().lower()
        if not subtitle_engine:
            raise ValueError("Hãy chọn model phụ đề")
        language = publish_language.strip()
        if language not in {"vi", "en", "th", "pt-BR", "es", "fr", "de", "ja", "ko", "zh-CN", "id"}:
            raise ValueError("Ngôn ngữ xuất bản chưa được hỗ trợ")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO project_render_settings (
                    project_id, music_asset_id, music_volume, transition_style, output_profile,
                    voice_provider, voice_model, voice_rate, voice_reference_asset_id, voice_prompt_text,
                    subtitle_provider, subtitle_model, publish_language,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    music_asset_id = excluded.music_asset_id,
                    music_volume = excluded.music_volume,
                    transition_style = excluded.transition_style,
                    output_profile = excluded.output_profile,
                    voice_provider = excluded.voice_provider,
                    voice_model = excluded.voice_model,
                    voice_rate = excluded.voice_rate,
                    voice_reference_asset_id = excluded.voice_reference_asset_id,
                    voice_prompt_text = excluded.voice_prompt_text,
                    subtitle_provider = excluded.subtitle_provider,
                    subtitle_model = excluded.subtitle_model,
                    publish_language = excluded.publish_language,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    music_asset_id,
                    max(0.0, min(float(music_volume), 0.5)),
                    style,
                    profile,
                    provider,
                    model,
                    rate,
                    voice_reference_asset_id,
                    prompt,
                    subtitle_source,
                    subtitle_engine,
                    language,
                    utc_now(),
                ),
            )
        return self.get_project_render_settings(project_id)

    def list_project_assets(self, project_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT a.*,
                       EXISTS(
                           SELECT 1 FROM project_asset_transcripts t
                           WHERE t.asset_id = a.id
                       ) AS has_transcript
                FROM project_assets a
                WHERE a.project_id = ?
                ORDER BY a.id DESC
                """,
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_project_asset_analysis(
        self,
        asset_id: int,
        status: str,
        error: str = "",
    ) -> dict[str, Any] | None:
        if not self.get_project_asset(asset_id):
            return None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE project_assets
                SET analysis_status = ?, analysis_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status.strip(), error.strip(), utc_now(), asset_id),
            )
        return self.get_project_asset(asset_id)

    def save_asset_transcript(
        self,
        asset_id: int,
        content_text: str,
        source_type: str = "whisper_local",
        language: str = "",
        transcript_format: str = "txt",
    ) -> dict[str, Any] | None:
        if not self.get_project_asset(asset_id):
            return None
        cleaned = content_text.strip()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO project_asset_transcripts (
                    asset_id, source_type, language, transcript_format,
                    content_text, word_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    source_type.strip(),
                    language.strip(),
                    transcript_format.strip(),
                    cleaned,
                    len(cleaned.split()),
                    utc_now(),
                ),
            )
            transcript_id = int(cursor.lastrowid)
        return self.get_asset_transcript(transcript_id)

    def get_asset_transcript(self, transcript_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM project_asset_transcripts WHERE id = ?",
                (transcript_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_latest_asset_transcript(self, asset_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM project_asset_transcripts
                WHERE asset_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (asset_id,),
            ).fetchone()
        return dict(row) if row else None

    def attach_asset_to_timeline_segment(
        self,
        segment_id: int,
        asset_id: int,
    ) -> dict[str, Any] | None:
        segment = self.get_project_timeline_segment(segment_id)
        asset = self.get_project_asset(asset_id)
        if not segment or not asset or int(segment["project_id"]) != int(asset["project_id"]):
            return None
        asset_type = str(asset["asset_type"])
        if asset_type not in {"audio", "video", "image"}:
            return None
        column = "audio_path" if asset_type == "audio" else "visual_path"
        with self._connect() as connection:
            connection.execute(
                f"UPDATE project_timeline_segments SET {column} = ?, updated_at = ? WHERE id = ?",
                (asset["file_path"], utc_now(), segment_id),
            )
        return {
            "asset": self.get_project_asset(asset_id),
            "segment": self.get_project_timeline_segment(segment_id),
        }

    def attach_asset_to_edit_beat(
        self,
        beat_id: int,
        asset_id: int,
        *,
        source_kind: str = "",
    ) -> dict[str, Any] | None:
        """Attach generated media to one edit beat without replacing its scene clip."""
        asset = self.get_project_asset(asset_id)
        if not asset or str(asset.get("asset_type") or "") not in {"image", "video"}:
            return None
        with self._connect() as connection:
            beat = connection.execute(
                """
                SELECT b.id, b.timeline_segment_id, s.project_id
                FROM project_timeline_edit_beats b
                JOIN project_timeline_segments s ON s.id = b.timeline_segment_id
                WHERE b.id = ?
                """,
                (beat_id,),
            ).fetchone()
            if not beat or int(beat["project_id"]) != int(asset["project_id"]):
                return None
            connection.execute(
                """
                UPDATE project_timeline_edit_beats
                SET asset_id = ?, visual_path = ?, source_kind = ?, status = 'ready', updated_at = ?
                WHERE id = ?
                """,
                (
                    asset_id,
                    str(asset.get("file_path") or ""),
                    source_kind.strip() or ("ai_video" if str(asset.get("asset_type") or "") == "video" else "ai_image"),
                    utc_now(),
                    beat_id,
                ),
            )
        return {
            "asset": self.get_project_asset(asset_id),
            "beat": self.get_timeline_edit_beat(beat_id),
        }

    def set_timeline_edit_beat_status(self, beat_id: int, status: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE project_timeline_edit_beats SET status = ?, updated_at = ? WHERE id = ?",
                (status.strip()[:32], utc_now(), beat_id),
            )
        return self.get_timeline_edit_beat(beat_id)

    def get_timeline_edit_beat(self, beat_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT b.*, s.project_id, s.script_id,
                       a.original_name AS asset_name, a.mime_type AS asset_mime_type
                FROM project_timeline_edit_beats b
                JOIN project_timeline_segments s ON s.id = b.timeline_segment_id
                LEFT JOIN project_assets a ON a.id = b.asset_id
                WHERE b.id = ?
                """,
                (beat_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_timeline_edit_beats(self, segment_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT b.*, a.original_name AS asset_name, a.mime_type AS asset_mime_type
                FROM project_timeline_edit_beats b
                LEFT JOIN project_assets a ON a.id = b.asset_id
                WHERE b.timeline_segment_id = ?
                ORDER BY b.beat_index ASC, b.id ASC
                """,
                (segment_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_project_edit_beats(self, project_id: int, script_id: int | None = None) -> dict[int, list[dict[str, Any]]]:
        query = """
            SELECT b.*, s.project_id, s.script_id, a.original_name AS asset_name, a.mime_type AS asset_mime_type
            FROM project_timeline_edit_beats b
            JOIN project_timeline_segments s ON s.id = b.timeline_segment_id
            LEFT JOIN project_assets a ON a.id = b.asset_id
            WHERE s.project_id = ?
        """
        params: list[Any] = [project_id]
        if script_id is not None:
            query += " AND s.script_id = ?"
            params.append(script_id)
        query += " ORDER BY b.timeline_segment_id, b.beat_index, b.id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            item = dict(row)
            grouped.setdefault(int(item["timeline_segment_id"]), []).append(item)
        return grouped

    def attach_edit_beats_to_timeline(
        self,
        project_id: int,
        timeline: list[dict[str, Any]],
        script_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return timeline rows with approved per-scene edit beats attached.

        The renderer already knows how to turn edit beats into a real visual
        composition. Keeping this join here makes project reloads, manifests,
        previews, and production renders see the same scene data.
        """
        if not timeline:
            return []
        grouped = self.list_project_edit_beats(project_id, script_id=script_id)
        attached: list[dict[str, Any]] = []
        for segment in timeline:
            item = dict(segment)
            item["edit_beats"] = grouped.get(int(item.get("id") or 0), [])
            attached.append(item)
        return attached

    def replace_timeline_edit_beats(self, segment_id: int, beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
        segment = self.get_project_timeline_segment(segment_id)
        if not segment:
            return []
        now = utc_now()
        with self._connect() as connection:
            existing = {
                int(row["beat_index"]): int(row["id"])
                for row in connection.execute(
                    "SELECT id, beat_index FROM project_timeline_edit_beats WHERE timeline_segment_id = ?",
                    (segment_id,),
                ).fetchall()
            }
            cursor = 0.0
            retained_ids: list[int] = []
            for index, beat in enumerate(beats, start=1):
                duration = max(0.15, float(beat.get("duration_seconds") or 1))
                asset_id = beat.get("asset_id")
                visual_path = str(beat.get("visual_path") or "").strip()
                if asset_id:
                    asset = self.get_project_asset(int(asset_id))
                    if not asset or int(asset["project_id"]) != int(segment["project_id"]):
                        continue
                    visual_path = str(asset["file_path"] or "")
                values = (
                    int(asset_id) if asset_id else None, visual_path,
                    str(beat.get("source_kind") or "primary")[:32], cursor, duration,
                    str(beat.get("effect") or "static")[:32],
                    str(beat.get("transition") or "cut")[:32],
                    str(beat.get("prompt") or "")[:5000],
                    str(beat.get("status") or ("ready" if visual_path else "needs_asset"))[:32],
                )
                existing_id = existing.get(index)
                if existing_id:
                    connection.execute(
                        """
                        UPDATE project_timeline_edit_beats
                        SET asset_id = ?, visual_path = ?, source_kind = ?, start_seconds = ?,
                            duration_seconds = ?, effect = ?, transition = ?, prompt = ?, status = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (*values, now, existing_id),
                    )
                    retained_ids.append(existing_id)
                else:
                    inserted = connection.execute(
                        """
                        INSERT INTO project_timeline_edit_beats (
                            timeline_segment_id, beat_index, asset_id, visual_path, source_kind,
                            start_seconds, duration_seconds, effect, transition, prompt, status,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (segment_id, index, *values, now, now),
                    )
                    retained_ids.append(int(inserted.lastrowid))
                cursor += duration
            if retained_ids:
                placeholders = ",".join("?" for _ in retained_ids)
                connection.execute(
                    f"DELETE FROM project_timeline_edit_beats WHERE timeline_segment_id = ? AND id NOT IN ({placeholders})",
                    (segment_id, *retained_ids),
                )
            else:
                connection.execute("DELETE FROM project_timeline_edit_beats WHERE timeline_segment_id = ?", (segment_id,))
            connection.execute(
                "UPDATE project_timeline_segments SET updated_at = ? WHERE id = ?", (now, segment_id)
            )
        return self.list_timeline_edit_beats(segment_id)

    def save_transcript(
        self,
        video_id: str,
        content_text: str,
        source_type: str = "manual",
        language: str = "",
        transcript_format: str = "txt",
    ) -> dict[str, Any]:
        cleaned = content_text.strip()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO transcripts (
                    youtube_video_id, source_type, language, transcript_format,
                    content_text, word_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    video_id,
                    source_type,
                    language.strip(),
                    transcript_format,
                    cleaned,
                    len(cleaned.split()),
                    utc_now(),
                ),
            )
            transcript_id = int(cursor.lastrowid)
        return self.get_transcript(video_id) or {"id": transcript_id}

    def get_transcript(
        self,
        video_id: str,
        transcript_format: str | None = None,
    ) -> dict[str, Any] | None:
        query = "SELECT * FROM transcripts WHERE youtube_video_id = ?"
        params: list[Any] = [video_id]
        if transcript_format:
            query += " AND transcript_format = ?"
            params.append(transcript_format)
        query += " ORDER BY id DESC LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return dict(row) if row else None

    def list_transcripts(self, video_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM transcripts
                WHERE youtube_video_id = ?
                ORDER BY id DESC
                """,
                (video_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def start_analysis_job(
        self,
        video_id: str,
        analysis_type: str = "metadata",
        provider: str = "local_rules",
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO analysis_jobs (
                    youtube_video_id, analysis_type, provider, status,
                    created_at, started_at
                ) VALUES (?, ?, ?, 'running', ?, ?)
                """,
                (video_id, analysis_type, provider, utc_now(), utc_now()),
            )
            # analysis_status on videos tracks the metadata pipeline specifically;
            # other job types (e.g. transcript) must not shadow that state.
            if analysis_type == "metadata":
                connection.execute(
                    "UPDATE videos SET analysis_status = 'running' WHERE youtube_video_id = ?",
                    (video_id,),
                )
            return int(cursor.lastrowid)

    def list_pending_analysis_video_ids(
        self,
        channel_id: str | None = None,
        limit: int = 100,
    ) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT youtube_video_id
                FROM videos
                WHERE analysis_status = 'pending'
                  AND (? IS NULL OR youtube_channel_id = ?)
                ORDER BY published_at DESC, id DESC
                LIMIT ?
                """,
                (channel_id, channel_id, max(1, min(limit, 500))),
            ).fetchall()
        return [str(row["youtube_video_id"]) for row in rows]

    def list_videos_without_transcript(
        self,
        channel_id: str | None = None,
        limit: int = 100,
    ) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT v.youtube_video_id
                FROM videos v
                WHERE NOT EXISTS (
                    SELECT 1 FROM transcripts t WHERE t.youtube_video_id = v.youtube_video_id
                )
                AND (? IS NULL OR v.youtube_channel_id = ?)
                ORDER BY v.published_at DESC, v.id DESC
                LIMIT ?
                """,
                (channel_id, channel_id, max(1, min(limit, 500))),
            ).fetchall()
        return [str(row["youtube_video_id"]) for row in rows]

    def queue_analysis_jobs(
        self,
        video_ids: list[str],
        analysis_type: str = "metadata",
        provider: str = "local_metadata",
        force: bool = False,
    ) -> list[dict[str, Any]]:
        queued: list[dict[str, Any]] = []
        with self._connect() as connection:
            for video_id in dict.fromkeys(video_ids):
                video = connection.execute(
                    "SELECT analysis_status FROM videos WHERE youtube_video_id = ?",
                    (video_id,),
                ).fetchone()
                if not video:
                    continue

                active = connection.execute(
                    """
                    SELECT id FROM analysis_jobs
                    WHERE youtube_video_id = ? AND analysis_type = ?
                      AND status IN ('queued', 'running')
                    ORDER BY id DESC LIMIT 1
                    """,
                    (video_id, analysis_type),
                ).fetchone()
                if active:
                    continue

                if not force:
                    if analysis_type == "metadata" and video["analysis_status"] not in ("pending", "error"):
                        continue
                    if analysis_type == "transcript":
                        has_transcript = connection.execute(
                            "SELECT 1 FROM transcripts WHERE youtube_video_id = ? LIMIT 1",
                            (video_id,),
                        ).fetchone()
                        if has_transcript:
                            continue

                cursor = connection.execute(
                    """
                    INSERT INTO analysis_jobs (
                        youtube_video_id, analysis_type, provider, status, created_at
                    ) VALUES (?, ?, ?, 'queued', ?)
                    """,
                    (video_id, analysis_type, provider, utc_now()),
                )
                # analysis_status on videos tracks the metadata pipeline specifically.
                if analysis_type == "metadata":
                    connection.execute(
                        "UPDATE videos SET analysis_status = 'pending' WHERE youtube_video_id = ?",
                        (video_id,),
                    )
                queued.append({"job_id": int(cursor.lastrowid), "video_id": video_id})
        return queued

    def claim_analysis_job(self, job_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE analysis_jobs
                SET status = 'running', started_at = ?, error = NULL
                WHERE id = ? AND status = 'queued'
                """,
                (utc_now(), job_id),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute(
                "SELECT * FROM analysis_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row and row["analysis_type"] == "metadata":
                connection.execute(
                    "UPDATE videos SET analysis_status = 'running' WHERE youtube_video_id = ?",
                    (row["youtube_video_id"],),
                )
        return dict(row) if row else None

    def analysis_queue_status(self, analysis_type: str | None = None) -> dict[str, int]:
        query = "SELECT status, COUNT(*) AS count FROM analysis_jobs"
        params: list[Any] = []
        if analysis_type:
            query += " WHERE analysis_type = ?"
            params.append(analysis_type)
        query += " GROUP BY status"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        return {
            "queued": counts.get("queued", 0),
            "running": counts.get("running", 0),
            "completed": counts.get("completed", 0),
            "error": counts.get("error", 0),
            "cancelled": counts.get("cancelled", 0),
        }

    def list_queued_analysis_job_ids(
        self,
        analysis_type: str | None = None,
        limit: int = 5000,
    ) -> list[int]:
        query = "SELECT id FROM analysis_jobs WHERE status = 'queued'"
        params: list[Any] = []
        if analysis_type:
            query += " AND analysis_type = ?"
            params.append(analysis_type)
        query += " ORDER BY id ASC LIMIT ?"
        params.append(max(1, min(limit, 5000)))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [int(row["id"]) for row in rows]

    def requeue_interrupted_analysis_jobs(self, analysis_type: str | None = None) -> int:
        select_query = "SELECT id, youtube_video_id, analysis_type FROM analysis_jobs WHERE status = 'running'"
        update_query = """
            UPDATE analysis_jobs
            SET status = 'queued', started_at = NULL, finished_at = NULL,
                error = 'Worker được khởi động lại trước khi hoàn tất'
            WHERE status = 'running'
        """
        params: list[Any] = []
        if analysis_type:
            select_query += " AND analysis_type = ?"
            update_query += " AND analysis_type = ?"
            params.append(analysis_type)

        with self._connect() as connection:
            rows = connection.execute(select_query, params).fetchall()
            if not rows:
                return 0
            connection.execute(update_query, params)
            connection.executemany(
                "UPDATE videos SET analysis_status = 'pending' WHERE youtube_video_id = ?",
                [(row["youtube_video_id"],) for row in rows if row["analysis_type"] == "metadata"],
            )
        return len(rows)

    def save_video_analysis(
        self,
        video_id: str,
        result: dict[str, Any],
        analysis_type: str = "metadata",
        provider: str = "local_rules",
        source_type: str = "metadata",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO video_analyses (
                    youtube_video_id, analysis_type, provider, source_type,
                    result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    video_id,
                    analysis_type,
                    provider,
                    source_type,
                    json.dumps(result, ensure_ascii=False),
                    utc_now(),
                ),
            )
            # analysis_status on videos tracks the metadata pipeline specifically;
            # other analysis types (e.g. writer) must not shadow that state.
            if analysis_type == "metadata":
                connection.execute(
                    "UPDATE videos SET analysis_status = 'completed' WHERE youtube_video_id = ?",
                    (video_id,),
                )

    def finish_analysis_job(
        self,
        job_id: int,
        status: str,
        error: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE analysis_jobs SET status = ?, finished_at = ?, error = ? WHERE id = ?",
                (status, utc_now(), error, job_id),
            )

    def mark_video_analysis_error(self, video_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE videos SET analysis_status = 'error' WHERE youtube_video_id = ?",
                (video_id,),
            )

    def get_video_analysis(
        self,
        video_id: str,
        analysis_type: str | None = None,
    ) -> dict[str, Any] | None:
        query = "SELECT * FROM video_analyses WHERE youtube_video_id = ?"
        params: list[Any] = [video_id]
        if analysis_type:
            query += " AND analysis_type = ?"
            params.append(analysis_type)
        query += " ORDER BY id DESC LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        if not row:
            return None
        item = dict(row)
        item["result"] = json.loads(item.pop("result_json") or "{}")
        return item

    def list_analysis_jobs(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM analysis_jobs ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_analysis_job(self, job_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return dict(row) if row else None

    def cancel_queued_analysis_job(self, job_id: int) -> dict[str, Any] | None:
        """Cancel a metadata/transcript job which has not been claimed by the worker yet."""
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE analysis_jobs
                SET status = 'cancelled', finished_at = ?, error = 'Đã hủy bởi người dùng.'
                WHERE id = ? AND status = 'queued'
                """,
                (now, job_id),
            )
        return self.get_analysis_job(job_id)

    def retry_analysis_job(self, job_id: int) -> dict[str, Any] | None:
        """Requeue a failed/cancelled metadata or transcript job for another attempt."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE analysis_jobs
                SET status = 'queued', started_at = NULL, finished_at = NULL, error = NULL
                WHERE id = ? AND status IN ('error', 'cancelled')
                """,
                (job_id,),
            )
            if cursor.rowcount != 1:
                return None
        return self.get_analysis_job(job_id)

    def start_sync_run(self, channel_id: str, trigger: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO sync_runs (youtube_channel_id, trigger, started_at) VALUES (?, ?, ?)",
                (channel_id, trigger, utc_now()),
            )
            return int(cursor.lastrowid)

    def finish_sync_run(
        self,
        run_id: int,
        status: str,
        videos_seen: int = 0,
        videos_new: int = 0,
        videos_updated: int = 0,
        error: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE sync_runs
                SET status = ?, finished_at = ?, videos_seen = ?, videos_new = ?,
                    videos_updated = ?, error = ?
                WHERE id = ?
                """,
                (status, utc_now(), videos_seen, videos_new, videos_updated, error, run_id),
            )

    def list_sync_runs(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sync_runs ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_scene_generation_job(
        self,
        project_id: int,
        timeline_segment_id: int,
        provider: str,
        prompt: str,
        duration_seconds: int = 5,
        ratio: str = "1280:720",
        reference_asset_id: int | None = None,
        *,
        job_kind: str = "",
        depends_on_job_id: int | None = None,
        requires_reference_image: bool = False,
        max_attempts: int = 2,
        prompt_pending: bool = False,
        edit_beat_id: int | None = None,
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self._connect() as connection:
            segment = connection.execute(
                "SELECT id FROM project_timeline_segments WHERE id = ? AND project_id = ?",
                (timeline_segment_id, project_id),
            ).fetchone()
            if not segment:
                return None
            if edit_beat_id is not None:
                beat = connection.execute(
                    """
                    SELECT id FROM project_timeline_edit_beats
                    WHERE id = ? AND timeline_segment_id = ?
                    """,
                    (edit_beat_id, timeline_segment_id),
                ).fetchone()
                if not beat:
                    return None
            if reference_asset_id is not None:
                asset = connection.execute(
                    "SELECT id FROM project_assets WHERE id = ? AND project_id = ?",
                    (reference_asset_id, project_id),
                ).fetchone()
                if not asset:
                    return None
            if depends_on_job_id is not None:
                dependency = connection.execute(
                    """
                    SELECT id FROM scene_generation_jobs
                    WHERE id = ? AND project_id = ? AND timeline_segment_id = ?
                    """,
                    (depends_on_job_id, project_id, timeline_segment_id),
                ).fetchone()
                if not dependency:
                    return None
            initial_status = "waiting" if depends_on_job_id is not None else "queued"
            # "prompt_pending" means the job carries the storyboard's own
            # words and the orchestrator will write the real prompt when the
            # job starts. Queueing therefore costs no CLI time and a batch
            # stays callable-off. A job waiting on its reference image keeps
            # that stage instead; its prompt is written when it is released.
            initial_stage = (
                "waiting_for_reference" if depends_on_job_id is not None
                else ("prompt_pending" if prompt_pending else "queued")
            )
            cursor = connection.execute(
                """
                INSERT INTO scene_generation_jobs (
                    project_id, timeline_segment_id, edit_beat_id, provider, prompt,
                    duration_seconds, ratio, reference_asset_id, job_kind,
                    depends_on_job_id, requires_reference_image, max_attempts,
                    status, pipeline_stage, prompt_written, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    timeline_segment_id,
                    edit_beat_id,
                    provider.strip(),
                    prompt.strip(),
                    max(1, min(int(duration_seconds), 30)),
                    ratio.strip() or "1280:720",
                    reference_asset_id,
                    job_kind.strip()[:20],
                    depends_on_job_id,
                    1 if requires_reference_image else 0,
                    max(1, min(int(max_attempts), 5)),
                    initial_status,
                    initial_stage,
                    0 if prompt_pending else 1,
                    now,
                    now,
                ),
            )
            job_id = int(cursor.lastrowid)
        job = self.get_scene_generation_job(job_id)
        if job:
            self.emit_domain_event(
                "task.created",
                project_id=project_id,
                aggregate_type="scene_generation_job",
                aggregate_id=job_id,
                source="job_manager",
                payload={
                    "provider": provider.strip(),
                    "job_kind": job_kind.strip(),
                    "timeline_segment_id": timeline_segment_id,
                    "status": initial_status,
                },
            )
        return job

    def get_scene_generation_job(self, job_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT j.*, p.title AS project_title,
                       s.segment_index, s.visual_kind, s.visual_fps,
                       s.visual_path AS timeline_visual_path,
                       a.original_name AS reference_asset_name, a.file_path AS reference_asset_path,
                       dependency.status AS dependency_status,
                       dependency.error AS dependency_error
                FROM scene_generation_jobs j
                JOIN production_projects p ON p.id = j.project_id
                JOIN project_timeline_segments s ON s.id = j.timeline_segment_id
                LEFT JOIN project_assets a ON a.id = j.reference_asset_id
                LEFT JOIN scene_generation_jobs dependency ON dependency.id = j.depends_on_job_id
                WHERE j.id = ?
                """,
                (job_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_scene_generation_jobs(self, project_id: int, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT j.*, p.title AS project_title,
                       s.segment_index, s.visual_kind, s.visual_fps,
                       s.visual_path AS timeline_visual_path,
                       a.original_name AS reference_asset_name, a.file_path AS reference_asset_path,
                       dependency.status AS dependency_status,
                       dependency.error AS dependency_error
                FROM scene_generation_jobs j
                JOIN production_projects p ON p.id = j.project_id
                JOIN project_timeline_segments s ON s.id = j.timeline_segment_id
                LEFT JOIN project_assets a ON a.id = j.reference_asset_id
                LEFT JOIN scene_generation_jobs dependency ON dependency.id = j.depends_on_job_id
                WHERE j.project_id = ?
                ORDER BY j.id DESC
                LIMIT ?
                """,
                (project_id, max(1, min(limit, 500))),
            ).fetchall()
        return [dict(row) for row in rows]

    # Web apps driven by web_video_sidecar.py's generic Playwright automation
    # (each site gets its own "driver" in that file, but shares the same
    # queue/claim/complete/fail API surface — see /api/browser-scene-jobs/*).
    # Add a new provider here (plus its Literal entry in main.py request
    # models and its driver in web_video_sidecar.py) to support another site.
    BROWSER_SIDECAR_PROVIDERS = (
        "flow_veo",
        "flow_image",
        "meta_ai_video",
        "meta_ai_image",
        "gemini_web_image",
        "chatgpt_web_image",
    )

    # Providers handled by an external pull-queue sidecar (Antigravity's own
    # built-in tool, or any BROWSER_SIDECAR_PROVIDERS) instead of the
    # in-process SceneGenerationWorker.
    EXTERNAL_SIDECAR_PROVIDERS = ("antigravity_image", *BROWSER_SIDECAR_PROVIDERS)

    SCENE_PROVIDER_FAILURE_THRESHOLD = 3
    SCENE_PROVIDER_COOLDOWN_SECONDS = 60 * 60

    def get_scene_provider_state(self, provider: str) -> dict[str, Any]:
        provider_key = provider.strip().lower()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM scene_provider_states WHERE provider = ?",
                (provider_key,),
            ).fetchone()
        state = dict(row) if row else {
            "provider": provider_key,
            "consecutive_failures": 0,
            "opened_until": None,
            "last_success_at": None,
            "last_failure_at": None,
            "last_error": "",
            "updated_at": "",
        }
        opened_until = str(state.get("opened_until") or "")
        state["circuit_open"] = bool(opened_until and opened_until > utc_now())
        return state

    def list_scene_provider_states(self) -> list[dict[str, Any]]:
        providers = set(self.BROWSER_SIDECAR_PROVIDERS)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT provider FROM scene_provider_states ORDER BY provider"
            ).fetchall()
        providers.update(str(row["provider"]) for row in rows)
        return [self.get_scene_provider_state(provider) for provider in sorted(providers)]

    def record_scene_provider_success(self, provider: str) -> None:
        provider_key = provider.strip().lower()
        if not provider_key:
            return
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO scene_provider_states (
                    provider, consecutive_failures, opened_until,
                    last_success_at, last_failure_at, last_error, updated_at
                ) VALUES (?, 0, NULL, ?, NULL, '', ?)
                ON CONFLICT(provider) DO UPDATE SET
                    consecutive_failures = 0,
                    opened_until = NULL,
                    last_success_at = excluded.last_success_at,
                    last_error = '',
                    updated_at = excluded.updated_at
                """,
                (provider_key, now, now),
            )

    def record_scene_provider_failure(
        self,
        provider: str,
        error: str,
        *,
        threshold: int | None = None,
        cooldown_seconds: int | None = None,
    ) -> dict[str, Any]:
        provider_key = provider.strip().lower()
        failure_threshold = max(1, int(threshold or self.SCENE_PROVIDER_FAILURE_THRESHOLD))
        cooldown = max(60, int(cooldown_seconds or self.SCENE_PROVIDER_COOLDOWN_SECONDS))
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT consecutive_failures FROM scene_provider_states WHERE provider = ?",
                (provider_key,),
            ).fetchone()
            failures = int(row["consecutive_failures"] if row else 0) + 1
            opened_until = (
                (now_dt + timedelta(seconds=cooldown)).isoformat()
                if failures >= failure_threshold
                else None
            )
            connection.execute(
                """
                INSERT INTO scene_provider_states (
                    provider, consecutive_failures, opened_until,
                    last_success_at, last_failure_at, last_error, updated_at
                ) VALUES (?, ?, ?, NULL, ?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET
                    consecutive_failures = excluded.consecutive_failures,
                    opened_until = excluded.opened_until,
                    last_failure_at = excluded.last_failure_at,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (provider_key, failures, opened_until, now, error.strip()[:2000], now),
            )
        return self.get_scene_provider_state(provider_key)

    def list_queued_scene_generation_job_ids(self, limit: int = 5000) -> list[int]:
        placeholders = ",".join("?" for _ in self.EXTERNAL_SIDECAR_PROVIDERS)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT id FROM scene_generation_jobs WHERE status = 'queued' "
                f"AND provider NOT IN ({placeholders}) "
                "AND (requires_reference_image = 0 OR reference_asset_id IS NOT NULL) "
                "ORDER BY id ASC LIMIT ?",
                (*self.EXTERNAL_SIDECAR_PROVIDERS, max(1, min(limit, 5000))),
            ).fetchall()
        return [int(row["id"]) for row in rows]

    def claim_next_antigravity_scene_job(self) -> dict[str, Any] | None:
        return self.claim_next_scene_job_for_provider("antigravity_image")

    def claim_next_scene_job_for_provider(self, provider: str) -> dict[str, Any] | None:
        if self.get_scene_provider_state(provider).get("circuit_open"):
            return None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id FROM scene_generation_jobs
                WHERE status = 'queued' AND provider = ?
                  AND (requires_reference_image = 0 OR reference_asset_id IS NOT NULL)
                ORDER BY id ASC LIMIT 1
                """,
                (provider,),
            ).fetchone()
        return self.claim_scene_generation_job(int(row["id"])) if row else None

    def claim_scene_generation_job(self, job_id: int) -> dict[str, Any] | None:
        job = self.get_scene_generation_job(job_id)
        if not job or self.get_scene_provider_state(str(job.get("provider") or "")).get("circuit_open"):
            return None
        with self._connect() as connection:
            claim_token = uuid.uuid4().hex
            cursor = connection.execute(
                """
                UPDATE scene_generation_jobs
                SET status = 'running', started_at = ?, heartbeat_at = ?,
                    updated_at = ?, error = '', failure_kind = '',
                    pipeline_stage = 'running', claim_token = ?,
                    attempt_count = attempt_count + 1
                WHERE id = ? AND status = 'queued'
                  AND (requires_reference_image = 0 OR reference_asset_id IS NOT NULL)
                """,
                (utc_now(), utc_now(), utc_now(), claim_token, job_id),
            )
            if cursor.rowcount != 1:
                return None
        claimed = self.get_scene_generation_job(job_id)
        if claimed:
            self.emit_domain_event(
                "task.started",
                project_id=int(claimed["project_id"]),
                aggregate_type="scene_generation_job",
                aggregate_id=job_id,
                source="scene_worker",
                payload={
                    "provider": claimed["provider"],
                    "job_kind": claimed.get("job_kind") or "",
                    "attempt_count": claimed.get("attempt_count") or 0,
                },
            )
        return claimed

    def cancel_pending_scene_generation_jobs(self, project_id: int) -> int:
        """Call off every scene job of a project that has not started yet.

        A batch that turns out to be wrong used to have to be unpicked one job
        at a time, which is slow enough that jobs keep being claimed while you
        work through the list. Jobs already running are left alone: they hold
        a claim on a browser tab or a CLI process and will report their own
        outcome.
        """
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE scene_generation_jobs
                SET status = 'cancelled', pipeline_stage = 'cancelled',
                    updated_at = ?, completed_at = ?
                WHERE project_id = ? AND status IN ('queued', 'waiting')
                """,
                (utc_now(), utc_now(), project_id),
            )
        return int(cursor.rowcount or 0)

    def cancel_queued_scene_generation_job(self, job_id: int) -> dict[str, Any] | None:
        """Cancel a scene-generation job which has not been claimed by a worker yet."""
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE scene_generation_jobs
                SET status = 'cancelled', updated_at = ?, completed_at = ?, error = 'Đã hủy bởi người dùng.'
                WHERE id = ? AND status = 'queued'
                """,
                (now, now, job_id),
            )
        return self.get_scene_generation_job(job_id)

    @staticmethod
    def _decode_edit_plan(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        result = dict(row)
        try:
            result["plan"] = json.loads(str(result.pop("plan_json") or "{}"))
        except (TypeError, ValueError):
            result["plan"] = {}
        return result

    def save_director_artifact(self, project_id: int, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO project_director_artifacts (project_id, kind, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (project_id, kind, json.dumps(payload, ensure_ascii=False, allow_nan=False), utc_now()),
            )
            artifact_id = cursor.lastrowid
        self.emit_domain_event("director.artifact_saved", project_id=project_id,
                               aggregate_type="director_artifact", aggregate_id=artifact_id,
                               source="astra", payload={"kind": kind})
        return {"id": artifact_id, "kind": kind, "payload": payload}

    def get_director_artifact(self, project_id: int, kind: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM project_director_artifacts WHERE project_id = ? AND kind = ? ORDER BY id DESC LIMIT 1",
                (project_id, kind),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    def get_project_edit_plan(
        self,
        project_id: int,
        script_id: int | None = None,
    ) -> dict[str, Any] | None:
        clauses = ["project_id = ?"]
        params: list[Any] = [int(project_id)]
        if script_id is not None:
            clauses.append("script_id = ?")
            params.append(int(script_id))
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM project_edit_plans
                WHERE {' AND '.join(clauses)}
                ORDER BY id DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return self._decode_edit_plan(row)

    def save_project_edit_plan(
        self,
        project_id: int,
        script_id: int,
        source_revision: str,
        plan: dict[str, Any],
        status: str = "draft",
        error: str = "",
    ) -> dict[str, Any] | None:
        now = utc_now()
        selected = status if status in {"draft", "approved", "applying", "ready", "stale", "error"} else "draft"
        approved_at = now if selected == "approved" else None
        applied_at = now if selected == "ready" else None
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO project_edit_plans (
                    project_id, script_id, status, source_revision, plan_json,
                    error, approved_at, applied_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, script_id) DO UPDATE SET
                    status = excluded.status,
                    source_revision = excluded.source_revision,
                    plan_json = excluded.plan_json,
                    error = excluded.error,
                    approved_at = excluded.approved_at,
                    applied_at = excluded.applied_at,
                    updated_at = excluded.updated_at
                """,
                (
                    int(project_id),
                    int(script_id),
                    selected,
                    source_revision,
                    json.dumps(plan or {}, ensure_ascii=False),
                    error.strip()[:2000],
                    approved_at,
                    applied_at,
                    now,
                    now,
                ),
            )
        return self.get_project_edit_plan(project_id, script_id)

    def set_project_edit_plan_status(
        self,
        plan_id: int,
        status: str,
        *,
        source_revision: str | None = None,
        error: str = "",
    ) -> dict[str, Any] | None:
        selected = status if status in {"draft", "approved", "applying", "ready", "stale", "error"} else "error"
        assignments = ["status = ?", "error = ?", "updated_at = ?"]
        params: list[Any] = [selected, error.strip()[:2000], utc_now()]
        if source_revision is not None:
            assignments.append("source_revision = ?")
            params.append(source_revision)
        if selected == "approved":
            assignments.append("approved_at = ?")
            params.append(utc_now())
        if selected == "ready":
            assignments.append("applied_at = ?")
            params.append(utc_now())
        params.append(int(plan_id))
        with self._connect() as connection:
            connection.execute(
                f"UPDATE project_edit_plans SET {', '.join(assignments)} WHERE id = ?",
                params,
            )
            row = connection.execute(
                "SELECT * FROM project_edit_plans WHERE id = ?",
                (int(plan_id),),
            ).fetchone()
        return self._decode_edit_plan(row)

    def apply_project_edit_plan_scenes(
        self,
        project_id: int,
        script_id: int,
        scenes: list[dict[str, Any]],
    ) -> int:
        """Apply every proposed scene in one transaction.

        A failed row must not leave the renderer using half of the old plan
        and half of the new one.
        """
        now = utc_now()
        applied = 0
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, shot_id FROM project_timeline_segments
                WHERE project_id = ? AND script_id = ?
                """,
                (int(project_id), int(script_id)),
            ).fetchall()
            timeline = {int(row["id"]): dict(row) for row in rows}
            for entry in scenes:
                segment_id = int(entry.get("segment_id") or 0)
                segment = timeline.get(segment_id)
                if not segment:
                    raise ValueError(f"Cảnh {segment_id} không còn thuộc timeline hiện tại")
                kind = str(entry.get("kind") or "image").strip()[:20]
                fps = max(0, min(int(entry.get("fps") or 0), 60)) if kind in {"gif", "video"} else 0
                connection.execute(
                    """
                    UPDATE project_timeline_segments
                    SET visual_kind = ?, visual_fps = ?, visual_kind_reason = ?,
                        content_dna = ?, visual_strategy = ?, visual_provider = ?,
                        source_dependency = ?, risk_level = ?, transform_actions = ?,
                        required_assets = ?, overlays = ?, sound_cues = ?, edit_direction = ?,
                        edit_transition = ?, edit_effect = ?, edit_note = ?,
                        edit_trim_head = ?, edit_trim_tail = ?, edit_cleanups = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        kind,
                        fps,
                        str(entry.get("reason") or "").strip()[:500],
                        json.dumps(entry.get("content_dna") or {}, ensure_ascii=False),
                        str(entry.get("visual_strategy") or "").strip()[:80],
                        str(entry.get("provider") or entry.get("visual_provider") or "").strip()[:80],
                        str(entry.get("source_dependency") or "").strip()[:20],
                        str(entry.get("risk_level") or "").strip()[:20],
                        json.dumps(
                            [item for item in (entry.get("transform_actions") or []) if isinstance(item, dict)],
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            [item for item in (entry.get("required_assets") or []) if isinstance(item, dict)],
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            [item for item in (entry.get("overlays") or []) if isinstance(item, dict)],
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            [item for item in (entry.get("sound_cues") or []) if isinstance(item, dict)],
                            ensure_ascii=False,
                        ),
                        json.dumps(entry.get("direction") or {}, ensure_ascii=False),
                        str(entry.get("transition") or "fade").strip()[:20],
                        str(entry.get("effect") or "zoom_in").strip()[:20],
                        str(entry.get("note") or "").strip()[:400],
                        max(0.0, float(entry.get("trim_head_seconds") or 0)),
                        max(0.0, float(entry.get("trim_tail_seconds") or 0)),
                        json.dumps(
                            [item for item in (entry.get("cleanups") or []) if isinstance(item, dict)],
                            ensure_ascii=False,
                        ),
                        now,
                        segment_id,
                    ),
                )
                if "compiled_beats" in entry:
                    connection.execute("DELETE FROM project_timeline_edit_beats WHERE timeline_segment_id = ?", (segment_id,))
                    for beat_index, beat in enumerate(entry["compiled_beats"], 1):
                        connection.execute(
                            """INSERT INTO project_timeline_edit_beats
                            (timeline_segment_id, beat_index, asset_id, visual_path, source_kind,
                             start_seconds, duration_seconds, effect, transition, prompt, status, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (segment_id, beat_index, beat.get("asset_id"), beat.get("visual_path", ""),
                             beat.get("source_kind", "primary"), beat["start_seconds"], beat["duration_seconds"],
                             beat.get("effect", "static"), beat.get("transition", "cut"), beat.get("prompt", ""),
                             beat.get("status", "ready"), now, now),
                        )
                shot_id = int(segment.get("shot_id") or 0)
                if shot_id:
                    needs_visual = bool(entry.get("needs_extra_visual"))
                    extra_note = str(entry.get("extra_visual_note") or "").strip()
                    if needs_visual:
                        if extra_note:
                            connection.execute(
                                "UPDATE project_shots SET visual_prompt = ?, status = 'needs_visual', updated_at = ? WHERE id = ?",
                                (extra_note, now, shot_id),
                            )
                        else:
                            connection.execute(
                                "UPDATE project_shots SET status = 'needs_visual', updated_at = ? WHERE id = ?",
                                (now, shot_id),
                            )
                    else:
                        connection.execute(
                            "UPDATE project_shots SET status = 'planned', updated_at = ? WHERE id = ? AND status = 'needs_visual'",
                            (now, shot_id),
                        )
                applied += 1
        return applied

    def set_timeline_cleanups(
        self,
        project_id: int,
        cleanups: list[dict[str, Any]],
        script_id: int | None = None,
    ) -> int:
        """Mark what has to come off the picture, for every scene at once.

        A logo or a burned-in subtitle belongs to the source, not to a scene,
        so it sits in the same place on every clip cut from that film. Setting
        it per scene made the user mark the same rectangle dozens of times, so
        in practice nobody set it at all and it survived into the render.

        Only the cleanup list is touched: the transition, effect and trims a
        scene already carries are its own.
        """
        clauses = ["project_id = ?"]
        params: list[Any] = [int(project_id)]
        if script_id is not None:
            clauses.append("script_id = ?")
            params.append(int(script_id))
        payload = json.dumps(cleanups or [], ensure_ascii=False)
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE project_timeline_segments SET edit_cleanups = ?, updated_at = ? "
                f"WHERE {' AND '.join(clauses)}",
                [payload, utc_now(), *params],
            )
            return int(cursor.rowcount or 0)

    def save_segment_edit(
        self,
        segment_id: int,
        transition: str,
        effect: str,
        note: str = "",
        trim_head_seconds: float = 0.0,
        trim_tail_seconds: float = 0.0,
        cleanups: list[dict[str, Any]] | None = None,
    ) -> None:
        """Stores how one scene should be cut, moved and cleaned in the edit.

        Cleanups are kept as JSON rather than columns: a scene may need none,
        or a logo and a burned-in subtitle at once, and the renderer reads the
        whole list to build one filter chain.
        """
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE project_timeline_segments
                SET edit_transition = ?, edit_effect = ?, edit_note = ?,
                    edit_trim_head = ?, edit_trim_tail = ?, edit_cleanups = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    transition.strip()[:20],
                    effect.strip()[:20],
                    note.strip()[:400],
                    max(0.0, float(trim_head_seconds or 0)),
                    max(0.0, float(trim_tail_seconds or 0)),
                    json.dumps(cleanups or [], ensure_ascii=False),
                    utc_now(),
                    segment_id,
                ),
            )

    def save_segment_edit_layers(
        self,
        segment_id: int,
        *,
        overlays: list[dict[str, Any]] | None = None,
        sound_cues: list[dict[str, Any]] | None = None,
        direction: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Store renderable graphic and audio layers for one timeline scene."""
        updates: list[tuple[str, Any]] = []
        if overlays is not None:
            updates.append((
                "overlays",
                json.dumps([item for item in overlays if isinstance(item, dict)], ensure_ascii=False),
            ))
        if sound_cues is not None:
            updates.append((
                "sound_cues",
                json.dumps([item for item in sound_cues if isinstance(item, dict)], ensure_ascii=False),
            ))
        if direction is not None:
            updates.append(("edit_direction", json.dumps(direction or {}, ensure_ascii=False)))
        if not updates:
            return self.get_project_timeline_segment(segment_id)
        assignments = ", ".join(f"{column} = ?" for column, _ in updates)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE project_timeline_segments SET {assignments}, updated_at = ? WHERE id = ?",
                [*(value for _, value in updates), utc_now(), segment_id],
            )
        return self.get_project_timeline_segment(segment_id)

    def set_segment_visual_kind(
        self,
        segment_id: int,
        kind: str,
        fps: int = 0,
        reason: str = "",
    ) -> dict[str, Any] | None:
        """Records whether this scene should be a still, a loop, or a clip."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE project_timeline_segments
                SET visual_kind = ?, visual_fps = ?, visual_kind_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (kind.strip()[:20], max(0, min(int(fps), 60)), reason.strip()[:500], utc_now(), segment_id),
            )
            row = connection.execute(
                "SELECT * FROM project_timeline_segments WHERE id = ?", (segment_id,)
            ).fetchone()
        return dict(row) if row else None

    def save_script_review(
        self,
        script_id: int,
        score: int,
        note: str,
        agent: str,
        status: str = "review",
    ) -> dict[str, Any] | None:
        """Record a second AI's verdict on a script and move it into review."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE project_scripts
                SET review_score = ?, review_note = ?, review_agent = ?,
                    status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    max(0, min(int(score), 10)),
                    note.strip()[:4000],
                    agent.strip()[:40],
                    status.strip() or "review",
                    utc_now(),
                    script_id,
                ),
            )
        return self.get_project_script(script_id)

    def save_segment_voice_review(self, segment_id: int, score: int, note: str) -> None:
        """Record whether a scene's narration says what the script asked."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE project_timeline_segments
                SET voice_review_score = ?, voice_review_note = ?, updated_at = ?
                WHERE id = ?
                """,
                (max(0, min(int(score), 10)), note.strip()[:2000], utc_now(), segment_id),
            )

    def set_script_fidelity_status(self, script_id: int, status: str) -> dict[str, Any] | None:
        """Record whether this script survived the check against its source."""
        chosen = status if status in {"unchecked", "passed", "failed"} else "unchecked"
        with self._connect() as connection:
            connection.execute(
                "UPDATE project_scripts SET fidelity_status = ?, updated_at = ? WHERE id = ?",
                (chosen, utc_now(), script_id),
            )
        return self.get_project_script(script_id)

    def record_provider_usage_limit(
        self,
        provider: str,
        message: str,
        resets_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Note that a provider has run out, keeping the first time it did.

        detected_at is not refreshed on repeat failures: what the user wants
        to know is when the model stopped working, not when it was last
        retried. cleared_at is wiped so an old recovery cannot make a fresh
        outage look resolved.
        """
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO provider_usage_limits (
                    provider, message, detected_at, last_failure_at, resets_at, cleared_at
                )
                VALUES (?, ?, ?, ?, ?, NULL)
                ON CONFLICT(provider) DO UPDATE SET
                    message = excluded.message,
                    last_failure_at = excluded.last_failure_at,
                    resets_at = excluded.resets_at,
                    detected_at = CASE
                        WHEN provider_usage_limits.cleared_at IS NULL THEN provider_usage_limits.detected_at
                        ELSE excluded.detected_at
                    END,
                    cleared_at = NULL
                """,
                (provider, message.strip()[:600], now, now, resets_at),
            )
        return self.get_provider_usage_limit(provider)

    def clear_provider_usage_limit(self, provider: str) -> None:
        """Mark a provider as working again, after a call actually succeeded."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE provider_usage_limits SET cleared_at = ? WHERE provider = ? AND cleared_at IS NULL",
                (utc_now(), provider),
            )

    def get_provider_usage_limit(self, provider: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM provider_usage_limits WHERE provider = ?", (provider,)
            ).fetchone()
        return dict(row) if row else None

    def list_active_usage_limits(self) -> list[dict[str, Any]]:
        """Providers currently out, most recently hit first."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM provider_usage_limits
                WHERE cleared_at IS NULL
                ORDER BY detected_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def record_orchestrator_step(
        self,
        *,
        stage: str,
        step: str,
        status: str,
        project_id: int | None = None,
        runtime: str = "",
        agent: str = "",
        why: str = "",
        input_summary: str = "",
        output_ref: str = "",
        fallback_used: bool = False,
        error: str = "",
        attempts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Record one AI step exactly as it happened, successful or not.

        A failed step is the most valuable row here: it is the difference
        between "the AI planned this cut" and "the AI could not be reached and
        a template filled in", which the finished video cannot show.
        """
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO orchestrator_steps (
                    project_id, stage, step, runtime, agent, why, input_summary,
                    output_ref, status, fallback_used, error, attempts_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    stage.strip()[:80],
                    step.strip()[:120],
                    runtime.strip()[:80],
                    agent.strip()[:80],
                    why.strip()[:600],
                    input_summary.strip()[:600],
                    output_ref.strip()[:600],
                    status.strip()[:40],
                    1 if fallback_used else 0,
                    error.strip()[:2000],
                    json.dumps(attempts or [], ensure_ascii=False),
                    utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM orchestrator_steps WHERE id = ?", (int(cursor.lastrowid),)
            ).fetchone()
        return self._orchestrator_step(row)

    def list_orchestrator_steps(
        self,
        project_id: int | None = None,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Steps oldest first, which is the order a run report reads in."""
        clauses = ["1 = 1"]
        params: list[Any] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(int(project_id))
        params.append(max(1, min(int(limit), 1000)))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM orchestrator_steps WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [self._orchestrator_step(row) for row in reversed(rows)]

    @staticmethod
    def _orchestrator_step(row: Any) -> dict[str, Any]:
        result = dict(row)
        result["fallback_used"] = bool(result.get("fallback_used"))
        try:
            result["attempts"] = json.loads(str(result.pop("attempts_json", "") or "[]"))
        except json.JSONDecodeError:
            result["attempts"] = []
        return result

    def set_project_workflow(self, project_id: int, workflow: str) -> dict[str, Any] | None:
        """Record which production workflow this project follows.

        Resolved through the registry so an unknown key becomes the default
        rather than a value nothing later knows how to run.
        """
        chosen = workflows.get(workflow).key
        with self._connect() as connection:
            connection.execute(
                "UPDATE production_projects SET workflow = ?, updated_at = ? WHERE id = ?",
                (chosen, utc_now(), project_id),
            )
        return self.get_production_project(project_id)

    def save_segment_source_cue(
        self,
        segment_id: int,
        source_start_seconds: float,
        reason: str = "",
    ) -> dict[str, Any] | None:
        """Record which moment of the source video this scene should show."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE project_timeline_segments
                SET source_start_seconds = ?, source_cue_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (max(0.0, float(source_start_seconds)), reason.strip()[:600], utc_now(), segment_id),
            )
        return self.get_project_timeline_segment(segment_id)

    def save_segment_translation(
        self,
        segment_id: int,
        voice_text: str,
        source_voice_text: str = "",
    ) -> dict[str, Any] | None:
        """Replace a scene's narration, keeping the pre-translation wording.

        The original is only stored the first time, so translating twice does
        not overwrite it with an already-translated line.
        """
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE project_timeline_segments
                SET voice_text = ?,
                    source_voice_text = CASE
                        WHEN COALESCE(source_voice_text, '') = '' THEN ?
                        ELSE source_voice_text
                    END,
                    updated_at = ?
                WHERE id = ?
                """,
                (voice_text.strip(), source_voice_text.strip(), utc_now(), segment_id),
            )
        return self.get_project_timeline_segment(segment_id)

    def save_scene_job_prompt(self, job_id: int, prompt: str) -> dict[str, Any] | None:
        """Store the prompt written for a job once it is about to run.

        Jobs are created carrying the storyboard's raw text so that queueing a
        batch is instant and cancellable; the orchestrator writes the real
        prompt when the job starts. Keeping that write here means a job's
        prompt always reflects what was actually sent.
        """
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE scene_generation_jobs
                SET prompt = ?, prompt_written = 1, updated_at = ?, heartbeat_at = ?
                WHERE id = ?
                """,
                (prompt.strip(), utc_now(), utc_now(), job_id),
            )
        return self.get_scene_generation_job(job_id)

    def save_scene_job_review(
        self,
        job_id: int,
        status: str,
        score: int,
        note: str,
    ) -> dict[str, Any] | None:
        """Record the orchestrator's verdict on a finished scene."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE scene_generation_jobs
                SET review_status = ?, review_score = ?, review_note = ?, updated_at = ?
                WHERE id = ?
                """,
                (status.strip()[:20], max(0, min(int(score), 10)), note.strip()[:2000], utc_now(), job_id),
            )
        job = self.get_scene_generation_job(job_id)
        if job:
            review_status = status.strip()[:20]
            self.emit_domain_event(
                "review.completed",
                project_id=int(job["project_id"]),
                aggregate_type="scene_generation_job",
                aggregate_id=job_id,
                source="qc_agent",
                payload={
                    "status": review_status,
                    "score": max(0, min(int(score), 10)),
                    "note": note.strip()[:2000],
                },
            )
            self.emit_domain_event(
                "scene.approved" if review_status in {"pass", "approved"} else "scene.qc_failed",
                project_id=int(job["project_id"]),
                aggregate_type="timeline_segment",
                aggregate_id=int(job["timeline_segment_id"]),
                source="qc_agent",
                payload={"job_id": job_id, "score": max(0, min(int(score), 10))},
            )
        return job

    def bump_scene_job_auto_retry(self, job_id: int) -> int:
        """Increments and returns how many times this job was auto-regenerated."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE scene_generation_jobs SET auto_retry_count = auto_retry_count + 1, updated_at = ? WHERE id = ?",
                (utc_now(), job_id),
            )
            row = connection.execute(
                "SELECT auto_retry_count FROM scene_generation_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return int(row["auto_retry_count"]) if row else 0

    def reroute_scene_generation_job(
        self,
        job_id: int,
        provider: str,
        *,
        previous_error: str = "",
        failure_kind: str = "provider",
    ) -> dict[str, Any] | None:
        """Move a failed running attempt to another provider without losing the job."""
        target = provider.strip().lower()
        if not target:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT project_id, provider, attempt_count, max_attempts FROM scene_generation_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if not row or int(row["attempt_count"] or 0) >= int(row["max_attempts"] or 1):
                return None
            previous_provider = str(row["provider"] or "").strip().lower()
            if previous_provider == target:
                return None
            cursor = connection.execute(
                """
                UPDATE scene_generation_jobs
                SET provider = ?, status = 'queued', started_at = NULL,
                    heartbeat_at = NULL, completed_at = NULL, updated_at = ?,
                    error = ?, failure_kind = ?, pipeline_stage = 'provider_fallback',
                    claim_token = '', task_id = ''
                WHERE id = ? AND status IN ('running', 'error')
                  AND attempt_count < max_attempts
                """,
                (
                    target,
                    utc_now(),
                    previous_error.strip()[:4000],
                    failure_kind.strip()[:40],
                    job_id,
                ),
            )
            if cursor.rowcount != 1:
                return None
        job = self.get_scene_generation_job(job_id)
        if job:
            self.emit_domain_event(
                "provider.fallback",
                project_id=int(job["project_id"]),
                aggregate_type="scene_generation_job",
                aggregate_id=job_id,
                source="provider_gateway",
                payload={
                    "from_provider": previous_provider,
                    "to_provider": target,
                    "attempt_count": job.get("attempt_count") or 0,
                    "max_attempts": job.get("max_attempts") or 0,
                    "failure_kind": failure_kind,
                    "error": previous_error.strip()[:2000],
                },
            )
        return job

    def retry_scene_generation_job(self, job_id: int) -> dict[str, Any] | None:
        """Requeue a failed/cancelled scene-generation job for another attempt.

        Also allows retrying a job stuck in 'running' when it belongs to an
        external-sidecar provider (Antigravity/Flow/Meta AI): those never run
        a thread in this process, so requeueing here can't race an in-process
        worker — only the external CLI/browser session, which self-reports
        via /complete or /fail and simply targets a job id that has already
        moved on if it calls in late for a stale claim.
        """
        placeholders = ",".join("?" for _ in self.EXTERNAL_SIDECAR_PROVIDERS)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE scene_generation_jobs
                SET status = 'queued', started_at = NULL, completed_at = NULL,
                    heartbeat_at = NULL, updated_at = ?, error = '', failure_kind = '',
                    pipeline_stage = 'queued', claim_token = '', output_path = '',
                    output_asset_id = NULL
                WHERE id = ? AND (
                    status IN ('error', 'cancelled')
                    OR (status = 'completed' AND review_status = 'fail')
                    OR (status = 'running' AND provider IN ({placeholders}))
                )
                """,
                (utc_now(), job_id, *self.EXTERNAL_SIDECAR_PROVIDERS),
            )
            if cursor.rowcount != 1:
                return None
        return self.get_scene_generation_job(job_id)

    def update_scene_generation_task(self, job_id: int, task_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE scene_generation_jobs
                SET task_id = ?, heartbeat_at = ?, updated_at = ?, pipeline_stage = 'provider_running'
                WHERE id = ?
                """,
                (task_id.strip(), utc_now(), utc_now(), job_id),
            )

    def touch_scene_generation_job(self, job_id: int, pipeline_stage: str = "") -> dict[str, Any] | None:
        now = utc_now()
        stage = pipeline_stage.strip()[:120]
        with self._connect() as connection:
            if stage:
                connection.execute(
                    """
                    UPDATE scene_generation_jobs
                    SET heartbeat_at = ?, updated_at = ?, pipeline_stage = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (now, now, stage, job_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE scene_generation_jobs
                    SET heartbeat_at = ?, updated_at = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (now, now, job_id),
                )
        return self.get_scene_generation_job(job_id)

    def finish_scene_generation_job(
        self,
        job_id: int,
        status: str,
        output_path: str = "",
        error: str = "",
        *,
        output_asset_id: int | None = None,
        failure_kind: str = "",
        release_dependents: bool = True,
    ) -> dict[str, Any] | None:
        if status not in {"completed", "error", "cancelled"}:
            raise ValueError("Trạng thái scene job không hợp lệ")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT project_id, timeline_segment_id, edit_beat_id, provider, job_kind
                FROM scene_generation_jobs WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
            if not row:
                return None
            now = utc_now()
            resolved_asset_id = output_asset_id
            if status == "completed" and output_path and resolved_asset_id is None:
                asset_row = connection.execute(
                    """
                    SELECT id FROM project_assets
                    WHERE project_id = ? AND file_path = ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (row["project_id"], output_path),
                ).fetchone()
                resolved_asset_id = int(asset_row["id"]) if asset_row else None
            connection.execute(
                """
                UPDATE scene_generation_jobs
                SET status = ?, output_path = ?, output_asset_id = ?, error = ?,
                    failure_kind = ?, heartbeat_at = ?, updated_at = ?, completed_at = ?,
                    pipeline_stage = ?
                WHERE id = ?
                """,
                (
                    status,
                    output_path,
                    resolved_asset_id,
                    error,
                    failure_kind.strip()[:40],
                    now,
                    now,
                    now,
                    status,
                    job_id,
                ),
            )

            if row["edit_beat_id"] is not None and status in {"error", "cancelled"}:
                connection.execute(
                    """
                    UPDATE project_timeline_edit_beats
                    SET status = ?, updated_at = ? WHERE id = ?
                    """,
                    ("error" if status == "error" else "needs_asset", now, int(row["edit_beat_id"])),
                )
            if status == "completed" and output_path and row["edit_beat_id"] is not None:
                connection.execute(
                    """
                    UPDATE project_timeline_edit_beats
                    SET asset_id = ?, visual_path = ?, source_kind = ?, status = 'ready', updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        resolved_asset_id,
                        output_path,
                        "ai_video" if str(row["job_kind"] or "").strip().lower() == "video" else "ai_image",
                        now,
                        int(row["edit_beat_id"]),
                    ),
                )
            elif status == "completed" and output_path:
                segment = connection.execute(
                    "SELECT audio_path FROM project_timeline_segments WHERE id = ?",
                    (row["timeline_segment_id"],),
                ).fetchone()
                timeline_status = "ready" if segment and str(segment["audio_path"] or "").strip() else "asset_ready"
                connection.execute(
                    """
                    UPDATE project_timeline_segments
                    SET visual_path = ?, status = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (output_path, timeline_status, now, row["timeline_segment_id"]),
                )
            if status == "completed" and resolved_asset_id is not None and release_dependents:
                connection.execute(
                    """
                    UPDATE scene_generation_jobs
                    SET status = 'queued', reference_asset_id = ?, updated_at = ?,
                        error = '', failure_kind = '', pipeline_stage = 'queued'
                    WHERE depends_on_job_id = ?
                      AND requires_reference_image = 1
                      AND pipeline_stage IN ('waiting_for_reference', 'dependency_failed')
                    """,
                    (resolved_asset_id, now, job_id),
                )
            elif status in {"error", "cancelled"}:
                connection.execute(
                    """
                    UPDATE scene_generation_jobs
                    SET status = 'error', updated_at = ?, completed_at = ?,
                        pipeline_stage = 'dependency_failed', failure_kind = 'dependency',
                        error = ?
                    WHERE depends_on_job_id = ? AND status = 'waiting'
                    """,
                    (now, now, f"Không tạo được ảnh nguồn: {error or status}", job_id),
                )
        provider = str(row["provider"] or "")
        if status == "completed":
            self.record_scene_provider_success(provider)
        elif status == "error":
            self.record_scene_provider_failure(provider, error or "Scene job thất bại")
        job = self.get_scene_generation_job(job_id)
        if job:
            self.emit_domain_event(
                "task.completed" if status == "completed" else "task.failed",
                project_id=int(job["project_id"]),
                aggregate_type="scene_generation_job",
                aggregate_id=job_id,
                source="scene_worker",
                payload={
                    "provider": provider,
                    "job_kind": job.get("job_kind") or "",
                    "status": status,
                    "output_path": output_path,
                    "output_asset_id": output_asset_id,
                    "failure_kind": failure_kind,
                    "error": error,
                },
            )
            if status == "completed":
                self.emit_domain_event(
                    "scene.created",
                    project_id=int(job["project_id"]),
                    aggregate_type="timeline_segment",
                    aggregate_id=int(job["timeline_segment_id"]),
                    source="media_agent",
                    payload={
                        "job_id": job_id,
                        "provider": provider,
                        "output_path": output_path,
                        "output_asset_id": job.get("output_asset_id"),
                    },
                )
        return job

    def release_scene_generation_dependents(self, job_id: int) -> list[dict[str, Any]]:
        """Release image-to-video children only after their source image is accepted."""
        now = utc_now()
        with self._connect() as connection:
            parent = connection.execute(
                """
                SELECT status, output_asset_id FROM scene_generation_jobs WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
            if not parent or parent["status"] != "completed" or parent["output_asset_id"] is None:
                return []
            rows = connection.execute(
                """
                SELECT id FROM scene_generation_jobs
                WHERE depends_on_job_id = ?
                  AND requires_reference_image = 1
                  AND pipeline_stage IN ('waiting_for_reference', 'dependency_failed')
                ORDER BY id
                """,
                (job_id,),
            ).fetchall()
            connection.execute(
                """
                UPDATE scene_generation_jobs
                SET status = 'queued', reference_asset_id = ?, updated_at = ?,
                    error = '', failure_kind = '', pipeline_stage = 'queued'
                WHERE depends_on_job_id = ?
                  AND requires_reference_image = 1
                  AND pipeline_stage IN ('waiting_for_reference', 'dependency_failed')
                """,
                (parent["output_asset_id"], now, job_id),
            )
        return [self.get_scene_generation_job(int(row["id"])) for row in rows]

    def recover_stale_scene_generation_jobs(self, stale_seconds: int) -> list[dict[str, Any]]:
        """Requeue one abandoned attempt, then fail it after max_attempts.

        Browser extension service workers can disappear without delivering a
        /fail callback. heartbeat_at is refreshed by every trace step, so a
        truly active long Veo generation is not mistaken for an abandoned job.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max(30, int(stale_seconds)))).isoformat()
        now = utc_now()
        recovered: list[dict[str, Any]] = []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, provider, attempt_count, max_attempts
                FROM scene_generation_jobs
                WHERE status = 'running'
                  AND COALESCE(heartbeat_at, started_at, updated_at) < ?
                ORDER BY id
                """,
                (cutoff,),
            ).fetchall()
            for row in rows:
                should_retry = int(row["attempt_count"] or 0) < int(row["max_attempts"] or 1)
                if should_retry:
                    connection.execute(
                        """
                        UPDATE scene_generation_jobs
                        SET status = 'queued', started_at = NULL, heartbeat_at = NULL,
                            updated_at = ?, pipeline_stage = 'watchdog_retry',
                            failure_kind = 'stale', error = ?, claim_token = ''
                        WHERE id = ? AND status = 'running'
                        """,
                        (now, "Watchdog phát hiện worker mất heartbeat; tự chạy lại có giới hạn.", row["id"]),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE scene_generation_jobs
                        SET status = 'error', heartbeat_at = ?, updated_at = ?, completed_at = ?,
                            pipeline_stage = 'error', failure_kind = 'stale', error = ?, claim_token = ''
                        WHERE id = ? AND status = 'running'
                        """,
                        (now, now, now, "Job mất heartbeat và đã hết số lần chạy lại tự động.", row["id"]),
                    )
                    connection.execute(
                        """
                        UPDATE scene_generation_jobs
                        SET status = 'error', updated_at = ?, completed_at = ?,
                            pipeline_stage = 'dependency_failed', failure_kind = 'dependency',
                            error = 'Không tạo được ảnh nguồn vì job cha mất heartbeat.'
                        WHERE depends_on_job_id = ? AND status = 'waiting'
                        """,
                        (now, now, row["id"]),
                    )
                recovered.append({
                    "id": int(row["id"]),
                    "provider": str(row["provider"]),
                    "requeued": should_retry,
                })
        for item in recovered:
            self.record_scene_provider_failure(
                item["provider"],
                "Worker mất heartbeat trong khi tạo cảnh",
            )
        return recovered

    def requeue_interrupted_scene_generation_jobs(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE scene_generation_jobs
                SET status = 'queued', started_at = NULL, heartbeat_at = NULL, updated_at = ?,
                    pipeline_stage = 'queued', claim_token = '',
                    error = 'Scene worker restarted before completion'
                WHERE status = 'running'
                """,
                (utc_now(),),
            )
        return int(cursor.rowcount)

    def count_queued_scene_generation_jobs(self, provider: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM scene_generation_jobs WHERE status = 'queued' AND provider = ?",
                (provider,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def scene_generation_queue_status(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM scene_generation_jobs GROUP BY status"
            ).fetchall()
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        return {
            "waiting": counts.get("waiting", 0),
            "queued": counts.get("queued", 0),
            "running": counts.get("running", 0),
            "completed": counts.get("completed", 0),
            "error": counts.get("error", 0),
            "cancelled": counts.get("cancelled", 0),
            "providers": self.list_scene_provider_states(),
        }

    def append_domain_event(
        self,
        event_type: str,
        *,
        project_id: int | None = None,
        aggregate_type: str = "",
        aggregate_id: str | int = "",
        source: str = "app",
        correlation_id: str = "",
        causation_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        correlation = correlation_id.strip() or uuid.uuid4().hex
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO domain_events (
                    event_type, project_id, aggregate_type, aggregate_id,
                    source, correlation_id, causation_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_type.strip(),
                    project_id,
                    aggregate_type.strip(),
                    str(aggregate_id),
                    source.strip() or "app",
                    correlation,
                    causation_id.strip(),
                    json.dumps(payload or {}, ensure_ascii=False),
                    now,
                ),
            )
            event_id = int(cursor.lastrowid)
        event = self.get_domain_event(event_id)
        if event is None:
            raise RuntimeError("Không lưu được domain event")
        return event

    @staticmethod
    def _decode_json_column(row: dict[str, Any], column: str, target: str) -> None:
        try:
            row[target] = json.loads(str(row.pop(column, "") or "{}"))
        except json.JSONDecodeError:
            row[target] = {}

    def get_domain_event(self, event_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM domain_events WHERE id = ?", (event_id,)
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        self._decode_json_column(result, "payload_json", "payload")
        return result

    def list_domain_events(
        self,
        *,
        after_id: int = 0,
        project_id: int | None = None,
        event_types: list[str] | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses = ["id > ?"]
        params: list[Any] = [max(0, int(after_id))]
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(int(project_id))
        cleaned_types = [item.strip() for item in (event_types or []) if item.strip()]
        if cleaned_types:
            placeholders = ",".join("?" for _ in cleaned_types)
            clauses.append(f"event_type IN ({placeholders})")
            params.extend(cleaned_types)
        params.append(max(1, min(int(limit), 2000)))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM domain_events WHERE {' AND '.join(clauses)} ORDER BY id ASC LIMIT ?",
                params,
            ).fetchall()
        result = [dict(row) for row in rows]
        for item in result:
            self._decode_json_column(item, "payload_json", "payload")
        return result

    def create_agent_task(
        self,
        project_id: int | None,
        role: str,
        task_type: str,
        input_payload: dict[str, Any],
        *,
        requested_by: str = "orchestrator",
        assigned_agent: str = "",
        reviewer_agent: str = "",
        parent_task_id: str | None = None,
        correlation_id: str = "",
        max_attempts: int = 2,
        estimated_cost: float = 0,
        currency: str = "USD",
    ) -> dict[str, Any]:
        task_id = f"agt_{uuid.uuid4().hex}"
        correlation = correlation_id.strip() or uuid.uuid4().hex
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_tasks (
                    id, project_id, role, task_type, requested_by,
                    assigned_agent, reviewer_agent, parent_task_id,
                    correlation_id, input_json, max_attempts,
                    estimated_cost, currency, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    project_id,
                    role.strip(),
                    task_type.strip(),
                    requested_by.strip() or "orchestrator",
                    assigned_agent.strip(),
                    reviewer_agent.strip(),
                    parent_task_id,
                    correlation,
                    json.dumps(input_payload, ensure_ascii=False),
                    max(1, min(int(max_attempts), 10)),
                    max(0.0, float(estimated_cost)),
                    currency.strip().upper()[:8] or "USD",
                    now,
                    now,
                ),
            )
        task = self.get_agent_task(task_id)
        if task is None:
            raise RuntimeError("Không tạo được agent task")
        self.emit_domain_event(
            "task.created",
            project_id=project_id,
            aggregate_type="agent_task",
            aggregate_id=task_id,
            source=requested_by.strip() or "orchestrator",
            correlation_id=correlation,
            payload={
                "role": role.strip(),
                "task_type": task_type.strip(),
                "assigned_agent": assigned_agent.strip(),
                "reviewer_agent": reviewer_agent.strip(),
                "parent_task_id": parent_task_id,
            },
        )
        return task

    @staticmethod
    def _agent_task_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        result = dict(row)
        for column, target in (("input_json", "input"), ("output_json", "output")):
            try:
                result[target] = json.loads(str(result.pop(column, "") or "{}"))
            except json.JSONDecodeError:
                result[target] = {}
        return result

    def get_agent_task(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return self._agent_task_dict(row)

    def list_agent_tasks(
        self,
        *,
        project_id: int | None = None,
        status: str = "",
        role: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses = ["1 = 1"]
        params: list[Any] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(int(project_id))
        if status.strip():
            clauses.append("status = ?")
            params.append(status.strip())
        if role.strip():
            clauses.append("role = ?")
            params.append(role.strip())
        params.append(max(1, min(int(limit), 1000)))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM agent_tasks WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [item for row in rows if (item := self._agent_task_dict(row)) is not None]

    def list_queued_agent_task_ids(self, limit: int = 1000) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id FROM agent_tasks
                WHERE status = 'queued' AND attempt_count < max_attempts
                  AND assigned_agent NOT IN ('chatgpt_app', 'claude_chat')
                ORDER BY created_at ASC LIMIT ?
                """,
                (max(1, min(int(limit), 5000)),),
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def list_review_required_agent_task_ids(self, limit: int = 100) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id FROM agent_tasks
                WHERE status = 'review_required'
                ORDER BY updated_at ASC LIMIT ?
                """,
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def requeue_interrupted_agent_tasks(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE agent_tasks
                SET status = CASE WHEN attempt_count < max_attempts THEN 'queued' ELSE 'failed' END,
                    assigned_agent = '', error = 'Agent worker khởi động lại trước khi hoàn tất',
                    updated_at = ?, completed_at = CASE WHEN attempt_count < max_attempts THEN NULL ELSE ? END
                WHERE status = 'running' AND assigned_agent NOT IN ('chatgpt_app', 'claude_chat')
                """,
                (utc_now(), utc_now()),
            )
        return int(cursor.rowcount or 0)

    def claim_agent_task(self, task_id: str, agent: str) -> dict[str, Any] | None:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE agent_tasks
                SET status = 'running', assigned_agent = ?, attempt_count = attempt_count + 1,
                    started_at = COALESCE(started_at, ?), updated_at = ?, error = ''
                WHERE id = ? AND status = 'queued' AND attempt_count < max_attempts
                """,
                (agent.strip(), now, now, task_id),
            )
            if cursor.rowcount != 1:
                return None
        task = self.get_agent_task(task_id)
        if task:
            self.emit_domain_event(
                "task.started",
                project_id=task.get("project_id"),
                aggregate_type="agent_task",
                aggregate_id=task_id,
                source=agent.strip() or "agent_worker",
                correlation_id=str(task.get("correlation_id") or ""),
                payload={
                    "role": task.get("role"),
                    "task_type": task.get("task_type"),
                    "attempt_count": task.get("attempt_count"),
                },
            )
        return task

    def finish_agent_task(
        self,
        task_id: str,
        status: str,
        *,
        output: dict[str, Any] | None = None,
        error: str = "",
        actual_cost: float = 0,
    ) -> dict[str, Any] | None:
        if status not in {"completed", "failed", "cancelled", "review_required", "approved"}:
            raise ValueError("Trạng thái agent task không hợp lệ")
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE agent_tasks
                SET status = ?, output_json = ?, error = ?, actual_cost = ?,
                    updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    json.dumps(output or {}, ensure_ascii=False),
                    error.strip()[:4000],
                    max(0.0, float(actual_cost)),
                    now,
                    None if status == "review_required" else now,
                    task_id,
                ),
            )
        task = self.get_agent_task(task_id)
        if task:
            event_type = (
                "task.completed" if status in {"completed", "approved"}
                else "review.waiting" if status == "review_required"
                else "task.failed"
            )
            self.emit_domain_event(
                event_type,
                project_id=task.get("project_id"),
                aggregate_type="agent_task",
                aggregate_id=task_id,
                source=str(task.get("assigned_agent") or "agent_worker"),
                correlation_id=str(task.get("correlation_id") or ""),
                payload={
                    "role": task.get("role"),
                    "task_type": task.get("task_type"),
                    "status": status,
                    "error": error,
                },
            )
        return task

    def requeue_agent_task(self, task_id: str, error: str = "") -> dict[str, Any] | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE agent_tasks
                SET status = 'queued', assigned_agent = '', error = ?, updated_at = ?, completed_at = NULL
                WHERE id = ? AND status IN ('running', 'failed', 'review_required')
                  AND attempt_count < max_attempts
                """,
                (error.strip()[:4000], utc_now(), task_id),
            )
            if cursor.rowcount != 1:
                return None
        return self.get_agent_task(task_id)

    def append_agent_message(
        self,
        *,
        sender_agent: str,
        recipient_agent: str,
        payload: dict[str, Any],
        message_type: str = "message",
        project_id: int | None = None,
        task_id: str | None = None,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        correlation = correlation_id.strip() or uuid.uuid4().hex
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO agent_messages (
                    project_id, task_id, sender_agent, recipient_agent,
                    message_type, correlation_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    task_id,
                    sender_agent.strip(),
                    recipient_agent.strip(),
                    message_type.strip() or "message",
                    correlation,
                    json.dumps(payload, ensure_ascii=False),
                    utc_now(),
                ),
            )
            message_id = int(cursor.lastrowid)
            row = connection.execute(
                "SELECT * FROM agent_messages WHERE id = ?", (message_id,)
            ).fetchone()
        result = dict(row)
        self._decode_json_column(result, "payload_json", "payload")
        self.emit_domain_event(
            "agent.message",
            project_id=project_id,
            aggregate_type="agent_task" if task_id else "agent_conversation",
            aggregate_id=task_id or correlation,
            source=sender_agent.strip(),
            correlation_id=correlation,
            payload={
                "message_id": message_id,
                "sender_agent": sender_agent.strip(),
                "recipient_agent": recipient_agent.strip(),
                "message_type": message_type.strip() or "message",
            },
        )
        return result

    def list_agent_messages(
        self,
        *,
        task_id: str | None = None,
        project_id: int | None = None,
        after_id: int = 0,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        clauses = ["id > ?"]
        params: list[Any] = [max(0, int(after_id))]
        if task_id:
            clauses.append("task_id = ?")
            params.append(task_id)
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(int(project_id))
        params.append(max(1, min(int(limit), 2000)))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM agent_messages WHERE {' AND '.join(clauses)} ORDER BY id ASC LIMIT ?",
                params,
            ).fetchall()
        result = [dict(row) for row in rows]
        for item in result:
            self._decode_json_column(item, "payload_json", "payload")
        return result

    def create_automation_approval(
        self,
        project_id: int,
        approval_type: str,
        *,
        title: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create one pending inbox item, reusing an existing duplicate."""
        if not self.get_production_project(project_id):
            raise ValueError("Không tìm thấy project")
        cleaned_type = approval_type.strip()[:80]
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM automation_approvals
                WHERE project_id = ? AND approval_type = ? AND status = 'pending'
                ORDER BY id DESC LIMIT 1
                """,
                (project_id, cleaned_type),
            ).fetchone()
            if existing:
                result = dict(existing)
            else:
                now = utc_now()
                cursor = connection.execute(
                    """
                    INSERT INTO automation_approvals (
                        project_id, approval_type, status, title, payload_json,
                        requested_at, updated_at
                    ) VALUES (?, ?, 'pending', ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        cleaned_type,
                        title.strip()[:300],
                        json.dumps(payload or {}, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM automation_approvals WHERE id = ?",
                    (int(cursor.lastrowid),),
                ).fetchone()
                result = dict(row)
        self._decode_json_column(result, "payload_json", "payload")
        return result

    def get_automation_approval(self, approval_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM automation_approvals WHERE id = ?", (approval_id,)
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        self._decode_json_column(result, "payload_json", "payload")
        return result

    def list_automation_approvals(
        self,
        *,
        project_id: int | None = None,
        status: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses = ["1 = 1"]
        params: list[Any] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(int(project_id))
        if status.strip():
            clauses.append("status = ?")
            params.append(status.strip())
        params.append(max(1, min(int(limit), 1000)))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM automation_approvals WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        result = [dict(row) for row in rows]
        for item in result:
            self._decode_json_column(item, "payload_json", "payload")
        return result

    def decide_automation_approval(
        self,
        approval_id: int,
        status: str,
        note: str = "",
    ) -> dict[str, Any] | None:
        if status not in {"approved", "changes_requested", "dismissed"}:
            raise ValueError("Quyết định phê duyệt không hợp lệ")
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE automation_approvals
                SET status = ?, note = ?, decided_at = ?, updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (status, note.strip()[:4000], now, now, approval_id),
            )
            if cursor.rowcount != 1:
                return None
        return self.get_automation_approval(approval_id)

    def record_provider_route(
        self,
        *,
        capability: str,
        selected_provider: str,
        candidates: list[dict[str, Any]],
        reason: str,
        project_id: int | None = None,
        scene_job_id: int | None = None,
        estimated_cost: float = 0,
        currency: str = "USD",
    ) -> dict[str, Any]:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO provider_route_decisions (
                    project_id, scene_job_id, capability, selected_provider,
                    candidates_json, reason, estimated_cost, currency, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    scene_job_id,
                    capability.strip(),
                    selected_provider.strip(),
                    json.dumps(candidates, ensure_ascii=False),
                    reason.strip()[:2000],
                    max(0.0, float(estimated_cost)),
                    currency.strip().upper()[:8] or "USD",
                    utc_now(),
                ),
            )
            route_id = int(cursor.lastrowid)
            row = connection.execute(
                "SELECT * FROM provider_route_decisions WHERE id = ?", (route_id,)
            ).fetchone()
        result = dict(row)
        try:
            result["candidates"] = json.loads(str(result.pop("candidates_json", "") or "[]"))
        except json.JSONDecodeError:
            result["candidates"] = []
        return result

    def record_provider_usage(
        self,
        *,
        provider: str,
        capability: str,
        status: str,
        project_id: int | None = None,
        scene_job_id: int | None = None,
        units: float = 1,
        estimated_cost: float = 0,
        actual_cost: float = 0,
        currency: str = "USD",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO provider_usage_ledger (
                    project_id, scene_job_id, provider, capability, status,
                    units, estimated_cost, actual_cost, currency,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    scene_job_id,
                    provider.strip(),
                    capability.strip(),
                    status.strip(),
                    max(0.0, float(units)),
                    max(0.0, float(estimated_cost)),
                    max(0.0, float(actual_cost)),
                    currency.strip().upper()[:8] or "USD",
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            usage_id = int(cursor.lastrowid)
            row = connection.execute(
                "SELECT * FROM provider_usage_ledger WHERE id = ?", (usage_id,)
            ).fetchone()
        result = dict(row)
        self._decode_json_column(result, "metadata_json", "metadata")
        return result

    def finalize_scene_provider_usage(
        self,
        scene_job_id: int,
        status: str,
        *,
        actual_cost: float = 0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Finish the latest ledger entry, creating one for manually queued jobs."""
        job = self.get_scene_generation_job(scene_job_id)
        if not job:
            return None
        now = utc_now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, metadata_json FROM provider_usage_ledger
                WHERE scene_job_id = ? AND provider = ?
                ORDER BY id DESC LIMIT 1
                """,
                (scene_job_id, str(job.get("provider") or "")),
            ).fetchone()
            if row:
                try:
                    merged_metadata = json.loads(str(row["metadata_json"] or "{}"))
                except json.JSONDecodeError:
                    merged_metadata = {}
                merged_metadata.update(metadata or {})
                connection.execute(
                    """
                    UPDATE provider_usage_ledger
                    SET status = ?, actual_cost = ?, metadata_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        status.strip(),
                        max(0.0, float(actual_cost)),
                        json.dumps(merged_metadata, ensure_ascii=False),
                        now,
                        int(row["id"]),
                    ),
                )
                usage_id = int(row["id"])
            else:
                kind = str(job.get("job_kind") or "image").strip().lower()
                capability = {
                    "image": "scene.image",
                    "gif": "scene.animated_image",
                    "video": "scene.video",
                }.get(kind, f"scene.{kind or 'image'}")
                cursor = connection.execute(
                    """
                    INSERT INTO provider_usage_ledger (
                        project_id, scene_job_id, provider, capability, status,
                        units, estimated_cost, actual_cost, currency,
                        metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 1, 0, ?, 'USD', ?, ?, ?)
                    """,
                    (
                        int(job["project_id"]),
                        scene_job_id,
                        str(job.get("provider") or ""),
                        capability,
                        status.strip(),
                        max(0.0, float(actual_cost)),
                        json.dumps(metadata or {}, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                usage_id = int(cursor.lastrowid)
            result_row = connection.execute(
                "SELECT * FROM provider_usage_ledger WHERE id = ?", (usage_id,)
            ).fetchone()
        result = dict(result_row) if result_row else None
        if result is not None:
            self._decode_json_column(result, "metadata_json", "metadata")
        return result

    def list_provider_usage(self, project_id: int, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM provider_usage_ledger
                WHERE project_id = ? ORDER BY id DESC LIMIT ?
                """,
                (project_id, max(1, min(int(limit), 2000))),
            ).fetchall()
        result = [dict(row) for row in rows]
        for item in result:
            self._decode_json_column(item, "metadata_json", "metadata")
        return result

    # A cancelled request never reached the provider, so it must not eat the
    # user's budget. Every other row is counted, including failures: a failed
    # generation can still have consumed a credit on the provider's side.
    _BUDGET_COST_SQL = (
        "SELECT COALESCE(SUM(MAX(actual_cost, estimated_cost)), 0) FROM provider_usage_ledger "
        "WHERE status != 'cancelled'"
    )

    def project_provider_cost(self, project_id: int) -> float:
        """Total money already committed to one project, in USD."""
        with self._connect() as connection:
            row = connection.execute(
                f"{self._BUDGET_COST_SQL} AND project_id = ?", (int(project_id),)
            ).fetchone()
        return round(float(row[0] or 0), 6)

    def provider_cost_since(self, since: str) -> float:
        """Total money committed across all projects since an ISO timestamp."""
        with self._connect() as connection:
            row = connection.execute(
                f"{self._BUDGET_COST_SQL} AND created_at >= ?", (str(since),)
            ).fetchone()
        return round(float(row[0] or 0), 6)

    def today_provider_cost(self) -> float:
        """Total money committed since midnight UTC.

        The ledger stores timezone-aware ISO strings, so a lexicographic
        comparison against the start of the day is exact and needs no parsing.
        """
        start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        return self.provider_cost_since(start)

    def save_project_short(
        self,
        project_id: int,
        plan: dict[str, Any],
        *,
        duration_seconds: float = 0,
    ) -> dict[str, Any]:
        """Store the one current short plan for a project.

        Replanning replaces rather than accumulates: a project has one short
        in flight, and a stale plan pointing at scenes that were regenerated
        would render the wrong video.
        """
        if not self.get_production_project(project_id):
            raise ValueError("Không tìm thấy project")
        now = utc_now()
        payload = json.dumps(plan or {}, ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO project_shorts (
                    project_id, title, hook, plan_json, duration_seconds,
                    output_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, '', ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    title = excluded.title,
                    hook = excluded.hook,
                    plan_json = excluded.plan_json,
                    duration_seconds = excluded.duration_seconds,
                    output_path = '',
                    updated_at = excluded.updated_at
                """,
                (
                    int(project_id),
                    str(plan.get("title") or "")[:300],
                    str(plan.get("hook") or "")[:600],
                    payload,
                    max(0.0, float(duration_seconds)),
                    now,
                    now,
                ),
            )
        return self.get_project_short(project_id)

    def get_project_short(self, project_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM project_shorts WHERE project_id = ?", (int(project_id),)
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        self._decode_json_column(result, "plan_json", "plan")
        return result

    def save_project_short_output(self, project_id: int, output_path: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE project_shorts SET output_path = ?, updated_at = ? WHERE project_id = ?",
                (str(output_path), utc_now(), int(project_id)),
            )
        return self.get_project_short(project_id)

    def resync_timeline_segment_states(self, project_id: int | None = None) -> int:
        """Correct scenes marked as having only half of what they hold.

        The status column can hold one answer, and the voiceover and the
        source cut each wrote their own over the other's. Scenes that have
        both a picture and a voice are marked ready; the rest are named for
        whichever half they actually have.
        """
        clauses = ["status NOT IN ('done', 'skipped')"]
        params: list[Any] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(int(project_id))
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE project_timeline_segments
                SET status = CASE
                        WHEN TRIM(COALESCE(visual_path, '')) <> ''
                         AND TRIM(COALESCE(audio_path, '')) <> '' THEN 'ready'
                        WHEN TRIM(COALESCE(audio_path, '')) <> '' THEN 'voice_ready'
                        WHEN TRIM(COALESCE(visual_path, '')) <> '' THEN 'asset_ready'
                        ELSE status
                    END,
                    updated_at = ?
                WHERE {' AND '.join(clauses)}
                  AND status <> CASE
                        WHEN TRIM(COALESCE(visual_path, '')) <> ''
                         AND TRIM(COALESCE(audio_path, '')) <> '' THEN 'ready'
                        WHEN TRIM(COALESCE(audio_path, '')) <> '' THEN 'voice_ready'
                        WHEN TRIM(COALESCE(visual_path, '')) <> '' THEN 'asset_ready'
                        ELSE status
                    END
                """,
                [utc_now(), *params],
            )
            return int(cursor.rowcount or 0)

    def summary(self) -> dict[str, int]:
        with self._connect() as connection:
            channels = connection.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
            enabled = connection.execute(
                "SELECT COUNT(*) FROM channels WHERE tracking_enabled = 1"
            ).fetchone()[0]
            videos = connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
            pending = connection.execute(
                "SELECT COUNT(*) FROM videos WHERE analysis_status = 'pending'"
            ).fetchone()[0]
            completed = connection.execute(
                "SELECT COUNT(*) FROM videos WHERE analysis_status = 'completed'"
            ).fetchone()[0]
            projects = connection.execute("SELECT COUNT(*) FROM production_projects").fetchone()[0]
        return {
            "channels": int(channels),
            "enabled_channels": int(enabled),
            "videos": int(videos),
            "pending_analysis": int(pending),
            "completed_analysis": int(completed),
            "production_projects": int(projects),
        }
