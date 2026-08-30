from __future__ import annotations

import re
from typing import Any


def _clean_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^\s*(?:[-*•]|\d+[\.)])\s*", "", line).strip()
        if line:
            lines.append(line)
    return lines


def _duration(text: str) -> int:
    words = len(re.findall(r"\w+", text, flags=re.UNICODE))
    return max(6, min(28, round(words / 2.4) + 3))


def _visual_prompt(section: str, narration: str, project_title: str) -> str:
    base = narration[:180].strip()
    if section == "hook":
        return f"Opening visual for '{project_title}': high contrast, clear subject, curiosity-driven scene. {base}"
    if section == "cta":
        return f"Closing frame for '{project_title}': clean end screen, room for CTA text, warm confident mood. {base}"
    if section == "intro":
        return f"Context visual for '{project_title}': simple explainer style, establish the topic clearly. {base}"
    return f"B-roll or generated visual for '{project_title}': illustrate this point with specific, useful imagery. {base}"


def build_shot_plan(project: dict[str, Any], script: dict[str, Any], writer_content: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    project_title = str(project.get("title") or script.get("script_title") or "Project").strip()
    # The blueprints belong to the script the writer produced them with, and
    # that is version 1. Returning them for every later script meant a rewrite
    # was silently ignored: the shot list, the timeline and therefore the
    # narration all stayed as the first draft, so a new script was spoken in
    # the old script's words.
    try:
        script_version = int(script.get("version") or 1)
    except (TypeError, ValueError):
        script_version = 1
    has_own_words = any(
        str(script.get(field) or "").strip()
        for field in ("hook", "intro", "main_content", "cta")
    )
    blueprints = (writer_content or {}).get("scene_blueprints") if isinstance(writer_content, dict) else None
    if script_version > 1 and has_own_words:
        blueprints = None
    if isinstance(blueprints, list):
        ai_shots: list[dict[str, Any]] = []
        for index, item in enumerate(blueprints, start=1):
            if not isinstance(item, dict) or not str(item.get("narration") or "").strip():
                continue
            section = str(item.get("section") or "main").strip().lower()
            if section not in {"hook", "intro", "main", "cta"}:
                section = "main"
            narration = str(item.get("narration") or "").strip()
            ai_shots.append({
                "shot_index": int(item.get("order") or index), "section": section, "narration": narration,
                "speaker": str(item.get("speaker") or "").strip(),
                "visual_prompt": str(item.get("visual_prompt") or _visual_prompt(section, narration, project_title)).strip(),
                # Honour the asset type the writer chose. Forcing ai_scene here
                # sent the reup workflow - whose pictures are cut from its own
                # source - into the image generators anyway.
                "asset_type": str(item.get("asset_type") or "ai_scene").strip() or "ai_scene",
                "duration_seconds": max(3, min(30, int(item.get("duration_seconds") or _duration(narration)))),
                "status": "planned",
            })
        if ai_shots:
            return ai_shots
    planned: list[tuple[str, str, str]] = []

    hook = str(script.get("hook") or "").strip()
    if hook:
        planned.append(("hook", hook, "talking_head"))

    intro = str(script.get("intro") or "").strip()
    if intro:
        planned.append(("intro", intro, "talking_head"))

    for line in _clean_lines(str(script.get("main_content") or "")):
        planned.append(("main", line, "broll"))

    cta = str(script.get("cta") or "").strip()
    if cta:
        planned.append(("cta", cta, "talking_head"))

    if not planned:
        planned.append(("main", "Bổ sung lời dẫn cho cảnh này.", "broll"))

    shots: list[dict[str, Any]] = []
    for index, (section, narration, asset_type) in enumerate(planned, start=1):
        shots.append(
            {
                "shot_index": index,
                "section": section,
                "narration": narration,
                "visual_prompt": _visual_prompt(section, narration, project_title),
                "asset_type": asset_type,
                "duration_seconds": _duration(narration),
                "status": "planned",
            }
        )
    return shots


def shots_to_markdown(project: dict[str, Any], script: dict[str, Any] | None, shots: list[dict[str, Any]]) -> str:
    title = str(project.get("title") or (script or {}).get("script_title") or "Shot list").strip()
    parts = [
        f"# Shot list: {title}",
        "",
        f"- Project ID: {project.get('id', '')}",
        f"- Script ID: {(script or {}).get('id', '')}",
        f"- Total shots: {len(shots)}",
        "",
    ]
    for shot in shots:
        parts.extend(
            [
                f"## Shot {shot.get('shot_index', '')}: {shot.get('section', '')}",
                "",
                f"- Asset type: {shot.get('asset_type', '')}",
                f"- Duration: {shot.get('duration_seconds', '')}s",
                f"- Status: {shot.get('status', '')}",
                "",
                "### Narration",
                str(shot.get("narration") or "").strip(),
                "",
                "### Visual prompt",
                str(shot.get("visual_prompt") or "").strip(),
                "",
            ]
        )
    return "\n".join(parts).strip() + "\n"
