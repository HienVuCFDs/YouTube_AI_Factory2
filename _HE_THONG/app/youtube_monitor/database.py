from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.initialize()

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
                    provider TEXT NOT NULL,
                    prompt TEXT NOT NULL DEFAULT '',
                    duration_seconds INTEGER NOT NULL DEFAULT 5,
                    ratio TEXT NOT NULL DEFAULT '1280:720',
                    reference_asset_id INTEGER,
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
                    FOREIGN KEY (reference_asset_id)
                        REFERENCES project_assets(id)
                        ON DELETE SET NULL
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
                """
            )
            self._ensure_column(connection, "videos", "local_media_path", "TEXT")
            self._ensure_column(connection, "production_projects", "managed_channel_id", "INTEGER")
            self._ensure_column(connection, "project_publications", "thumbnail_path", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "project_timeline_segments", "subtitle_path", "TEXT NOT NULL DEFAULT ''")
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
            for column, ddl in (
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
        if profile not in {"youtube_landscape", "youtube_shorts", "instagram_reels", "tiktok"}:
            raise ValueError("Định dạng đầu ra không được hỗ trợ")
        return profile

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
                        name, channel_url, youtube_channel_id, group_name,
                        workflow_reference_channel_id, output_profile, language,
                        default_voice_provider, default_voice_model, default_subtitle_provider,
                        default_subtitle_model, default_transition_style, notes, schedule_enabled, schedule_frequency, schedule_time,
                        schedule_timezone, schedule_days, default_privacy, auto_upload,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_name,
                        clean_url,
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
                SET name = ?, channel_url = ?, youtube_channel_id = ?, group_name = ?,
                    workflow_reference_channel_id = ?, output_profile = ?, language = ?,
                    default_voice_provider = ?, default_voice_model = ?, default_subtitle_provider = ?,
                    default_subtitle_model = ?, default_transition_style = ?, notes = ?, enabled = ?, schedule_enabled = ?, schedule_frequency = ?,
                    schedule_time = ?, schedule_timezone = ?, schedule_days = ?,
                    default_privacy = ?, auto_upload = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    values["name"], values["channel_url"], values["youtube_channel_id"],
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

    def mark_video_downloaded(self, video_id: str, file_path: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE videos SET media_status = 'downloaded_for_editing', local_media_path = ? "
                "WHERE youtube_video_id = ?",
                (file_path, video_id),
            )

    def mark_video_media_deleted(self, video_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE videos SET media_status = 'not_downloaded', local_media_path = NULL "
                "WHERE youtube_video_id = ?",
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
    ) -> dict[str, Any] | None:
        if not self.get_production_project(project_id):
            return None
        now = utc_now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM project_scripts WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            version = int(row["next_version"])
            cursor = connection.execute(
                """
                INSERT INTO project_scripts (
                    project_id, version, script_title, hook, intro, main_content,
                    cta, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def get_latest_project_script(self, project_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM project_scripts
                WHERE project_id = ?
                ORDER BY version DESC, id DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_project_scripts(self, project_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM project_scripts
                WHERE project_id = ?
                ORDER BY version DESC, id DESC
                """,
                (project_id,),
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
                        visual_prompt, asset_type, duration_seconds, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        script_id,
                        int(shot.get("shot_index") or 1),
                        str(shot.get("section") or "main").strip(),
                        str(shot.get("narration") or "").strip(),
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
                    visual_prompt, asset_type, duration_seconds, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    script_id,
                    shot_index,
                    section.strip() or "main",
                    narration.strip(),
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
                        voice_text, subtitle_text, visual_prompt, asset_type,
                        duration_seconds, start_seconds, end_seconds, audio_path,
                        visual_path, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        script_id,
                        segment.get("shot_id"),
                        int(segment.get("segment_index") or 1),
                        str(segment.get("section") or "main").strip(),
                        str(segment.get("voice_text") or "").strip(),
                        str(segment.get("subtitle_text") or segment.get("voice_text") or "").strip(),
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
        values = {
            "voice_text": existing["voice_text"] if voice_text is None else voice_text.strip(),
            "subtitle_text": existing["subtitle_text"] if subtitle_text is None else subtitle_text.strip(),
            "visual_prompt": existing["visual_prompt"] if visual_prompt is None else visual_prompt.strip(),
            "asset_type": existing["asset_type"] if asset_type is None else asset_type.strip(),
            "duration_seconds": existing["duration_seconds"] if duration_seconds is None else duration_seconds,
            "audio_path": existing["audio_path"] if audio_path is None else audio_path.strip(),
            "visual_path": existing["visual_path"] if visual_path is None else visual_path.strip(),
            "subtitle_path": existing.get("subtitle_path", "") if subtitle_path is None else subtitle_path.strip(),
            "status": existing["status"] if status is None else status,
        }
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE project_timeline_segments
                SET voice_text = ?, subtitle_text = ?, visual_prompt = ?, asset_type = ?,
                    duration_seconds = ?, audio_path = ?, visual_path = ?, subtitle_path = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    values["voice_text"],
                    values["subtitle_text"],
                    values["visual_prompt"],
                    values["asset_type"],
                    max(1, int(values["duration_seconds"])),
                    values["audio_path"],
                    values["visual_path"],
                    values["subtitle_path"],
                    values["status"],
                    utc_now(),
                    segment_id,
                ),
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
        return self.get_project_job(job_id)

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
        return dict(row) if row else None

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
        return self.get_project_job(job_id)

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
    ) -> dict[str, Any] | None:
        if not self.get_production_project(project_id):
            return None
        if managed_channel_id is not None and not self.get_managed_channel(int(managed_channel_id)):
            raise ValueError("Không tìm thấy kênh xuất bản đã chọn")
        privacy = self._validate_privacy(privacy_status)
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO project_publications (
                    project_id, managed_channel_id, local_file_path, thumbnail_path, title,
                    description, tags_json, category_id, privacy_status,
                    scheduled_at, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (
                    project_id,
                    managed_channel_id,
                    local_file_path.strip(),
                    thumbnail_path.strip(),
                    title.strip(),
                    description.strip(),
                    json.dumps(tags or [], ensure_ascii=False),
                    str(category_id or "27").strip(),
                    privacy,
                    scheduled_at.strip() if scheduled_at else None,
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

    def list_due_project_publications(self, now_iso: str, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM project_publications
                WHERE status = 'queued'
                  AND (scheduled_at IS NULL OR scheduled_at <= ?)
                ORDER BY COALESCE(scheduled_at, created_at) ASC, id ASC
                LIMIT ?
                """,
                (now_iso, max(1, min(int(limit), 50))),
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
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE project_publications
                SET status = 'queued', scheduled_at = NULL, error = '', updated_at = ?
                WHERE id = ? AND status IN ('error', 'cancelled')
                """,
                (utc_now(), publication_id),
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
    ) -> dict[str, Any] | None:
        asset = self.get_project_asset(asset_id)
        if not asset or int(asset["project_id"]) != project_id or asset["asset_type"] != "image":
            return None
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO project_thumbnails (project_id, asset_id, provider, model, prompt, seed, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, asset_id, provider.strip(), model.strip(), prompt.strip(), seed, utc_now()),
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
            connection.execute("UPDATE project_thumbnails SET selected = 0 WHERE project_id = ?", (thumbnail["project_id"],))
            connection.execute("UPDATE project_thumbnails SET selected = 1 WHERE id = ?", (thumbnail_id,))
        return self.get_project_thumbnail(thumbnail_id)

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
        if profile not in {"youtube_landscape", "youtube_shorts", "instagram_reels", "tiktok"}:
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
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self._connect() as connection:
            segment = connection.execute(
                "SELECT id FROM project_timeline_segments WHERE id = ? AND project_id = ?",
                (timeline_segment_id, project_id),
            ).fetchone()
            if not segment:
                return None
            if reference_asset_id is not None:
                asset = connection.execute(
                    "SELECT id FROM project_assets WHERE id = ? AND project_id = ?",
                    (reference_asset_id, project_id),
                ).fetchone()
                if not asset:
                    return None
            cursor = connection.execute(
                """
                INSERT INTO scene_generation_jobs (
                    project_id, timeline_segment_id, provider, prompt,
                    duration_seconds, ratio, reference_asset_id, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (
                    project_id,
                    timeline_segment_id,
                    provider.strip(),
                    prompt.strip(),
                    max(1, min(int(duration_seconds), 30)),
                    ratio.strip() or "1280:720",
                    reference_asset_id,
                    now,
                    now,
                ),
            )
            job_id = int(cursor.lastrowid)
        return self.get_scene_generation_job(job_id)

    def get_scene_generation_job(self, job_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT j.*, s.segment_index, s.visual_path AS timeline_visual_path,
                       a.original_name AS reference_asset_name, a.file_path AS reference_asset_path
                FROM scene_generation_jobs j
                JOIN project_timeline_segments s ON s.id = j.timeline_segment_id
                LEFT JOIN project_assets a ON a.id = j.reference_asset_id
                WHERE j.id = ?
                """,
                (job_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_scene_generation_jobs(self, project_id: int, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT j.*, s.segment_index, s.visual_path AS timeline_visual_path,
                       a.original_name AS reference_asset_name, a.file_path AS reference_asset_path
                FROM scene_generation_jobs j
                JOIN project_timeline_segments s ON s.id = j.timeline_segment_id
                LEFT JOIN project_assets a ON a.id = j.reference_asset_id
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
    BROWSER_SIDECAR_PROVIDERS = ("flow_veo", "meta_ai_video")

    # Providers handled by an external pull-queue sidecar (Antigravity's own
    # built-in tool, or any BROWSER_SIDECAR_PROVIDERS) instead of the
    # in-process SceneGenerationWorker.
    EXTERNAL_SIDECAR_PROVIDERS = ("antigravity_image", *BROWSER_SIDECAR_PROVIDERS)

    def list_queued_scene_generation_job_ids(self, limit: int = 5000) -> list[int]:
        placeholders = ",".join("?" for _ in self.EXTERNAL_SIDECAR_PROVIDERS)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT id FROM scene_generation_jobs WHERE status = 'queued' "
                f"AND provider NOT IN ({placeholders}) ORDER BY id ASC LIMIT ?",
                (*self.EXTERNAL_SIDECAR_PROVIDERS, max(1, min(limit, 5000))),
            ).fetchall()
        return [int(row["id"]) for row in rows]

    def claim_next_antigravity_scene_job(self) -> dict[str, Any] | None:
        return self.claim_next_scene_job_for_provider("antigravity_image")

    def claim_next_scene_job_for_provider(self, provider: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM scene_generation_jobs WHERE status = 'queued' AND provider = ? ORDER BY id ASC LIMIT 1",
                (provider,),
            ).fetchone()
        return self.claim_scene_generation_job(int(row["id"])) if row else None

    def claim_scene_generation_job(self, job_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE scene_generation_jobs
                SET status = 'running', started_at = ?, updated_at = ?, error = ''
                WHERE id = ? AND status = 'queued'
                """,
                (utc_now(), utc_now(), job_id),
            )
            if cursor.rowcount != 1:
                return None
        return self.get_scene_generation_job(job_id)

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
                SET status = 'queued', started_at = NULL, completed_at = NULL, updated_at = ?, error = ''
                WHERE id = ? AND (status IN ('error', 'cancelled') OR (status = 'running' AND provider IN ({placeholders})))
                """,
                (utc_now(), job_id, *self.EXTERNAL_SIDECAR_PROVIDERS),
            )
            if cursor.rowcount != 1:
                return None
        return self.get_scene_generation_job(job_id)

    def update_scene_generation_task(self, job_id: int, task_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE scene_generation_jobs SET task_id = ?, updated_at = ? WHERE id = ?",
                (task_id.strip(), utc_now(), job_id),
            )

    def finish_scene_generation_job(
        self,
        job_id: int,
        status: str,
        output_path: str = "",
        error: str = "",
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT timeline_segment_id FROM scene_generation_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if not row:
                return None
            now = utc_now()
            connection.execute(
                """
                UPDATE scene_generation_jobs
                SET status = ?, output_path = ?, error = ?, updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, output_path, error, now, now, job_id),
            )
            if status == "completed" and output_path:
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
        return self.get_scene_generation_job(job_id)

    def requeue_interrupted_scene_generation_jobs(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE scene_generation_jobs
                SET status = 'queued', started_at = NULL, updated_at = ?,
                    error = 'Scene worker restarted before completion'
                WHERE status = 'running'
                """,
                (utc_now(),),
            )
        return int(cursor.rowcount)

    def scene_generation_queue_status(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM scene_generation_jobs GROUP BY status"
            ).fetchall()
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        return {
            "queued": counts.get("queued", 0),
            "running": counts.get("running", 0),
            "completed": counts.get("completed", 0),
            "error": counts.get("error", 0),
            "cancelled": counts.get("cancelled", 0),
        }

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
