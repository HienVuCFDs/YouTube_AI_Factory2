from __future__ import annotations

from typing import Any


def build_timeline(
    project: dict[str, Any],
    script: dict[str, Any],
    shots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a deterministic voiceover/editing timeline from the current shot list."""
    segments: list[dict[str, Any]] = []
    cursor = 0
    for index, shot in enumerate(shots, start=1):
        duration = max(1, int(shot.get("duration_seconds") or 8))
        start = cursor
        end = start + duration
        voice_text = str(shot.get("narration") or "").strip()
        segments.append(
            {
                "segment_index": index,
                "shot_id": shot.get("id"),
                "section": str(shot.get("section") or "main").strip(),
                "voice_text": voice_text,
                "subtitle_text": voice_text,
                "speaker": str(shot.get("speaker") or "").strip(),
                "visual_prompt": str(shot.get("visual_prompt") or "").strip(),
                "asset_type": str(shot.get("asset_type") or "broll").strip(),
                "duration_seconds": duration,
                "start_seconds": start,
                "end_seconds": end,
                "audio_path": "",
                "visual_path": "",
                "status": "planned",
            }
        )
        cursor = end
    return segments


def timeline_to_manifest(
    project: dict[str, Any],
    script: dict[str, Any] | None,
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    total_duration = sum(max(0, int(item.get("duration_seconds") or 0)) for item in timeline)
    return {
        "manifest_version": "youtube_ai_factory.timeline.v1",
        "project_id": project.get("id"),
        "project_title": str(project.get("title") or "").strip(),
        "script_id": (script or {}).get("id"),
        "script_title": str((script or {}).get("script_title") or "").strip(),
        "total_duration_seconds": total_duration,
        "segments": timeline,
    }


def timeline_to_markdown(
    project: dict[str, Any],
    script: dict[str, Any] | None,
    timeline: list[dict[str, Any]],
) -> str:
    manifest = timeline_to_manifest(project, script, timeline)
    parts = [
        f"# Timeline: {manifest['project_title'] or 'Project'}",
        "",
        f"- Project ID: {manifest['project_id'] or ''}",
        f"- Script ID: {manifest['script_id'] or ''}",
        f"- Total duration: {manifest['total_duration_seconds']}s",
        f"- Total segments: {len(timeline)}",
        "",
    ]
    for item in timeline:
        parts.extend(
            [
                f"## Segment {item.get('segment_index', '')}: {item.get('section', '')}",
                "",
                f"- Shot ID: {item.get('shot_id') or ''}",
                f"- Time: {item.get('start_seconds', 0)}s - {item.get('end_seconds', 0)}s",
                f"- Duration: {item.get('duration_seconds', 0)}s",
                f"- Asset type: {item.get('asset_type', '')}",
                f"- Status: {item.get('status', '')}",
                f"- Audio path: {item.get('audio_path', '')}",
                f"- Visual path: {item.get('visual_path', '')}",
                "",
                "### Voiceover / subtitle",
                str(item.get("voice_text") or "").strip(),
                "",
                "### Visual prompt",
                str(item.get("visual_prompt") or "").strip(),
                "",
            ]
        )
    return "\n".join(parts).strip() + "\n"
