from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from typing import Any

from . import workflows
from .database import Database


PROJECT_CONTEXT_VERSION = "youtube_ai_factory.project_context.v1"
SOURCE_PACKAGE_VERSION = "youtube_ai_factory.source_package.v1"


def _text(value: Any, limit: int = 240) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "…"


def _words(value: Any) -> int:
    return len(re.findall(r"\w+", str(value or ""), flags=re.UNICODE))


def _counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counter = Counter(str(item.get(key) or "unknown") for item in items)
    return dict(sorted(counter.items()))


def _file_exists(value: Any) -> bool:
    path = str(value or "").strip()
    return bool(path and Path(path).is_file())


def _source_kind(video: dict[str, Any], raw: dict[str, Any]) -> str:
    """Where the source came from, for Astra. What it *is* is videos.source_kind."""
    url = str(video.get("video_url") or "")
    video_id = str(video.get("youtube_video_id") or "")
    if video_id.startswith("idea-") or raw.get("source") == "high_level_request":
        return "prompt_text"
    if url.startswith("file://") or str(video.get("media_kind") or "").strip():
        return "local_media"
    if video_id.startswith("web-"):
        return "web_video_url"
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube_video"
    if url.startswith(("http://", "https://")):
        return "url_video"
    return "unknown"


def build_source_package(
    database: Database,
    project_id: int,
    *,
    transcript_preview_chars: int = 600,
) -> dict[str, Any] | None:
    """Return a compact source package for Astra without moving heavy media."""
    project = database.get_production_project(project_id)
    if not project:
        return None
    video = database.get_video(str(project.get("youtube_video_id") or ""))
    if not video:
        return None
    transcript = database.get_transcript(str(video.get("youtube_video_id") or ""), transcript_format="txt") or database.get_transcript(str(video.get("youtube_video_id") or ""))
    assets = database.list_project_assets(project_id)
    analyses = {
        "metadata": bool(database.get_video_analysis(str(video.get("youtube_video_id") or ""), analysis_type="metadata")),
        "reference": bool(database.get_video_analysis(str(video.get("youtube_video_id") or ""), analysis_type="reference")),
        "writer": bool(database.get_video_analysis(str(video.get("youtube_video_id") or ""), analysis_type="writer")),
    }
    content = str((transcript or {}).get("content_text") or "")
    return {
        "source_package_version": SOURCE_PACKAGE_VERSION,
        "project_id": int(project_id),
        "source": {
            # get_video leaves the payload out; it is read on its own.
            "kind": _source_kind(video, database.get_video_raw_payload(str(video.get("youtube_video_id") or ""))),
            "source_kind": str(video.get("source_kind") or ""),
            "video_id": str(video.get("youtube_video_id") or ""),
            "title": str(video.get("title") or project.get("title") or ""),
            "url": str(video.get("video_url") or ""),
            "duration_seconds": video.get("duration_seconds"),
            "thumbnail_url": str(video.get("thumbnail_url") or ""),
            "language": str(video.get("default_language") or ""),
            "media_status": str(video.get("media_status") or ""),
            "local_media_path": str(video.get("local_media_path") or ""),
            "local_media_exists": _file_exists(video.get("local_media_path")),
        },
        "transcript": {
            "available": bool(transcript),
            "id": (transcript or {}).get("id"),
            "source_type": str((transcript or {}).get("source_type") or ""),
            "format": str((transcript or {}).get("transcript_format") or ""),
            "word_count": int((transcript or {}).get("word_count") or 0),
            "preview": content[: max(0, transcript_preview_chars)],
            "truncated": len(content) > transcript_preview_chars,
        },
        "analyses": analyses,
        "assets": {
            "total": len(assets),
            "by_type": _counts(assets, "asset_type"),
        },
        "supported_inputs": [
            "youtube_video",
            "web_video_url",
            "local_media",
            "project_asset",
            "prompt_text",
        ],
        "not_first_class_yet": [
            "article_url",
            "product_url",
            "folder_footage_as_source_package",
        ],
    }


def _json_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [dict(item) for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _compact_edit_plan(plan: dict[str, Any] | None) -> dict[str, Any]:
    if not plan:
        return {"available": False, "status": "missing"}
    payload = plan.get("plan") if isinstance(plan.get("plan"), dict) else {}
    scenes = [item for item in (payload.get("scenes") or []) if isinstance(item, dict)]
    return {
        "available": True,
        "id": plan.get("id"),
        "status": str(plan.get("status") or ""),
        "stale": bool(plan.get("stale")),
        "workflow": str(payload.get("workflow") or ""),
        "motion_policy": str(payload.get("motion_policy") or ""),
        "pacing": str(payload.get("pacing") or ""),
        "music_mood": str(payload.get("music_mood") or ""),
        "scenes": len(scenes),
        "visual_strategy_counts": _counts(scenes, "visual_strategy"),
        "transition_counts": _counts(scenes, "transition"),
        "effect_counts": _counts(scenes, "effect"),
        "overlay_count": sum(len(item.get("overlays") or []) for item in scenes),
        "sound_cue_count": sum(len(item.get("sound_cues") or []) for item in scenes),
        "required_asset_count": sum(len(item.get("required_assets") or []) for item in scenes),
        "updated_at": plan.get("updated_at"),
        "applied_at": plan.get("applied_at"),
        "error": _text(plan.get("error"), 240),
    }


def _compact_script(script: dict[str, Any] | None) -> dict[str, Any] | None:
    if not script:
        return None
    sections = {
        key: bool(str(script.get(key) or "").strip())
        for key in ("hook", "intro", "main_content", "cta")
    }
    body = "\n".join(str(script.get(key) or "") for key in ("hook", "intro", "main_content", "cta"))
    return {
        "id": script.get("id"),
        "version": script.get("version"),
        "variant": str(script.get("variant") or "long"),
        "status": str(script.get("status") or ""),
        "title": str(script.get("script_title") or ""),
        "word_count": _words(body),
        "sections_present": sections,
        "preview": _text(body, 500),
        "updated_at": script.get("updated_at"),
        "approved_at": script.get("approved_at"),
    }


def _compact_timeline(timeline: list[dict[str, Any]]) -> dict[str, Any]:
    total_duration = sum(float(item.get("duration_seconds") or 0) for item in timeline)
    missing_audio = [int(item.get("segment_index") or 0) for item in timeline if not _file_exists(item.get("audio_path"))]
    missing_visual = [int(item.get("segment_index") or 0) for item in timeline if not _file_exists(item.get("visual_path"))]
    edit_beats = sum(len(item.get("edit_beats") or []) for item in timeline)
    overlays = sum(len(_json_list(item.get("overlays"))) for item in timeline)
    sound_cues = sum(len(_json_list(item.get("sound_cues"))) for item in timeline)
    edited_segments = sum(1 for item in timeline if str(item.get("edit_transition") or item.get("edit_effect") or "").strip())
    return {
        "segments": len(timeline),
        "duration_seconds": round(total_duration, 3),
        "with_audio": len(timeline) - len(missing_audio),
        "with_visual": len(timeline) - len(missing_visual),
        "missing_audio_segments": missing_audio[:12],
        "missing_visual_segments": missing_visual[:12],
        "status_counts": _counts(timeline, "status"),
        "asset_type_counts": _counts(timeline, "asset_type"),
        "edit_beats": edit_beats,
        "edited_segments": edited_segments,
        "graphic_overlays": overlays,
        "sound_cues": sound_cues,
        "sample": [
            {
                "id": item.get("id"),
                "segment_index": item.get("segment_index"),
                "section": str(item.get("section") or ""),
                "asset_type": str(item.get("asset_type") or ""),
                "duration_seconds": item.get("duration_seconds"),
                "voice_preview": _text(item.get("voice_text"), 180),
                "visual_prompt_preview": _text(item.get("visual_prompt"), 180),
                "has_audio": _file_exists(item.get("audio_path")),
                "has_visual": _file_exists(item.get("visual_path")),
                "edit_transition": str(item.get("edit_transition") or ""),
                "edit_effect": str(item.get("edit_effect") or ""),
                "overlay_count": len(_json_list(item.get("overlays"))),
                "sound_cue_count": len(_json_list(item.get("sound_cues"))),
            }
            for item in timeline[:8]
        ],
    }


def _current_step(readiness: dict[str, Any]) -> dict[str, Any]:
    steps = [
        (1, "Video nguồn"),
        (2, "Phân tích"),
        (3, "Kịch bản"),
        (4, "Tạo giọng"),
        (5, "Storyboard"),
        (6, "Dựng"),
        (7, "Xuất bản"),
    ]
    if readiness.get("has_render"):
        index = 7
    elif readiness.get("has_timeline") and readiness.get("has_voiceover"):
        index = 6
    elif readiness.get("has_shot_plan") or readiness.get("has_timeline"):
        index = 5
    elif readiness.get("has_script"):
        index = 4
    elif not readiness.get("has_metadata_analysis") and not readiness.get("has_transcript"):
        index = 2
    else:
        index = 3
    return {"index": index, "name": dict(steps)[index]}


def build_project_context(database: Database, project_id: int) -> dict[str, Any] | None:
    """Build the compact state Astra should read before deciding what to do."""
    bundle = database.get_production_project_bundle(project_id, transcript_text_limit=600)
    if not bundle:
        return None
    project = dict(bundle.get("project") or {})
    workflow_key = str(project.get("workflow") or "content")
    workflow = workflows.get(workflow_key).as_dict()
    timeline = list(bundle.get("latest_timeline") or [])
    shots = list(bundle.get("latest_shots") or [])
    jobs = list(bundle.get("production_jobs") or [])
    scene_jobs = list(bundle.get("scene_generation_jobs") or [])
    publications = list(bundle.get("publications") or [])
    assets = list(bundle.get("project_assets") or [])
    readiness = dict(bundle.get("readiness") or {})
    source_package = build_source_package(database, project_id, transcript_preview_chars=600)
    edit_plan = database.get_project_edit_plan(project_id, int(bundle["latest_script"]["id"])) if bundle.get("latest_script") else None
    return {
        "context_version": PROJECT_CONTEXT_VERSION,
        "project": {
            "id": project.get("id"),
            "title": str(project.get("title") or ""),
            "status": str(project.get("status") or ""),
            "workflow": workflow_key,
            "managed_channel_id": project.get("managed_channel_id"),
            "managed_channel_name": str(project.get("managed_channel_name") or ""),
            "updated_at": project.get("updated_at"),
        },
        "workflow": workflow,
        "current_step": _current_step(readiness),
        "source_package": source_package,
        "script": _compact_script(bundle.get("latest_script")),
        "storyboard": {
            "shots": len(shots),
            "status_counts": _counts(shots, "status"),
            "asset_type_counts": _counts(shots, "asset_type"),
            "sample": [
                {
                    "id": item.get("id"),
                    "shot_index": item.get("shot_index"),
                    "section": str(item.get("section") or ""),
                    "asset_type": str(item.get("asset_type") or ""),
                    "duration_seconds": item.get("duration_seconds"),
                    "narration_preview": _text(item.get("narration"), 180),
                    "visual_prompt_preview": _text(item.get("visual_prompt"), 180),
                }
                for item in shots[:8]
            ],
        },
        "timeline": _compact_timeline(timeline),
        "edit_plan": _compact_edit_plan(edit_plan),
        "assets": {
            "total": len(assets),
            "by_type": _counts(assets, "asset_type"),
            "recent": [
                {
                    "id": item.get("id"),
                    "asset_type": str(item.get("asset_type") or ""),
                    "name": str(item.get("original_name") or ""),
                    "file_exists": _file_exists(item.get("file_path")),
                }
                for item in assets[:10]
            ],
        },
        "jobs": {
            "production_by_status": _counts(jobs, "status"),
            "production_by_type": _counts(jobs, "job_type"),
            "scene_by_status": _counts(scene_jobs, "status"),
            "scene_by_provider": _counts(scene_jobs, "provider"),
            "active": [
                {
                    "id": item.get("id"),
                    "kind": "scene" if "timeline_segment_id" in item else "production",
                    "status": str(item.get("status") or ""),
                    "type": str(item.get("job_type") or item.get("job_kind") or ""),
                    "provider": str(item.get("provider") or ""),
                    "error": _text(item.get("error"), 240),
                }
                for item in [*jobs, *scene_jobs]
                if str(item.get("status") or "") in {"waiting", "queued", "running", "review_required"}
            ][:12],
        },
        "publish": {
            "publications": len(publications),
            "latest": publications[0] if publications else None,
            "has_selected_thumbnail": bool(readiness.get("has_thumbnail")),
        },
        "readiness": readiness,
        "next_actions": list(bundle.get("next_actions") or [])[:10],
    }
