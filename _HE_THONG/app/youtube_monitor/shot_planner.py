"""The legacy shot planner: one scene per line of the old four script columns.

Compatibility boundary (Bước 5.1): a project in the plan workflow whose script
is a ScriptDocument is cut by storyboard_engine, never here. This planner is
kept for what has no ScriptDocument - a project outside the plan workflow
(pasted words alone, the old writer's scene list) and the Short.
"""

from __future__ import annotations

import re
from typing import Any


# The writer lays its script out with headings — "Cảnh 5 · main_content" —
# and every line here becomes a scene. Half of one script was headings, so
# half its scenes were the narrator reading a section label aloud: 26 scenes
# and 102 seconds of "Cảnh 5 · main_content" inside a fourteen minute video.
_SECTION_WORD = r"(?:cảnh|canh|scene|phần|phan|part|đoạn|doan)"
_SECTION_HEADING = re.compile(
    rf"^{_SECTION_WORD}\s*\d+\s*[·:.\-–—]?\s*"
    r"(?:hook|intro|main_content|main|body|cta|outro|kết|ket)?\s*$",
    re.IGNORECASE,
)
# A writer naming its own scenes - "Cảnh 3 · Các ngôi sao và nguyên tố" - is
# writing a heading too, and that form got past a pattern that only knew the
# section keywords. The narrator read the table of contents out loud.
_TITLED_HEADING = re.compile(rf"^{_SECTION_WORD}\s*\d+\s*[·:\-–—]\s*(?P<title>\S.*)$", re.IGNORECASE)
_HEADING_TITLE_WORDS = 12


def is_section_heading(line: str) -> bool:
    """A line that only names a section is a label, not something to say."""
    text = str(line or "").strip()
    if _SECTION_HEADING.match(text):
        return True
    titled = _TITLED_HEADING.match(text)
    if not titled:
        return False
    # A heading is a short name. A sentence that happens to open with
    # "Cảnh 3 - " and then runs on, or ends in a full stop, is narration and
    # is left alone: reading a label aloud is a smaller loss than dropping a
    # line the writer meant to be heard.
    title = titled.group("title").strip()
    if title.endswith((".", "!", "?", "…")) or re.search(r"[.!?…]\s+\S", title):
        return False
    # A second separator means the label was written on the same line as the
    # speech - "Cảnh 5 · main_content: Yvan bắt đầu đào" - and the speech is
    # the part that matters.
    if re.search(r":\s*\S", title):
        return False
    return len(re.findall(r"\S+", title)) <= _HEADING_TITLE_WORDS


def _clean_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^\s*(?:[-*•]|\d+[\.)])\s*", "", line).strip()
        if line and not is_section_heading(line):
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


def build_shot_plan(
    project: dict[str, Any],
    script: dict[str, Any],
    writer_content: dict[str, Any] | None = None,
    *,
    blueprints_verified: bool = False,
) -> list[dict[str, Any]]:
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
    # The version number is a stand-in for "this script was rewritten", used
    # because this function cannot tell on its own. A caller that has checked
    # the blueprints really do belong to this script - same words, recorded as
    # the script was written, untouched since - knows better, and says so.
    # Without that, a second script row was enough to discard a scene list the
    # AI had already written, and the prose got chopped by line instead.
    if not blueprints_verified and script_version > 1 and has_own_words:
        blueprints = None
    if isinstance(blueprints, list):
        usable = [
            item for item in blueprints
            if isinstance(item, dict) and str(item.get("narration") or "").strip()
            # The filter below guarded only the fallback path, so a writer that
            # returned its own scene list - the path actually taken - still got
            # its headings read aloud, each as a scene of its own.
            and not is_section_heading(item.get("narration"))
        ]
        ai_shots: list[dict[str, Any]] = []
        for index, item in enumerate(usable, start=1):
            narration = str(item.get("narration") or "").strip()
            section = str(item.get("section") or "").strip().lower()
            if section not in {"hook", "intro", "main", "cta"}:
                # A writer naming its own sections - "Mở vấn đề", "Sự sống và
                # tổng kết" - had every one of them flattened to "main", and
                # with it the opening and closing treatment those names exist
                # to select. Position says what the name no longer can.
                if index == 1:
                    section = "hook"
                elif index == len(usable):
                    section = "cta"
                else:
                    section = "main"
            # The writer's own estimate is a guess made before a word was
            # spoken, and it came back as a flat ten seconds for scenes whose
            # lines take seventeen to read. A scene is never given less time
            # than its own sentence needs; asking for more than that is a
            # pacing choice and is honoured.
            spoken = _duration(narration)
            wanted = int(item.get("duration_seconds") or 0) or spoken
            ai_shots.append({
                "shot_index": int(item.get("order") or index), "section": section, "narration": narration,
                "speaker": str(item.get("speaker") or "").strip(),
                "visual_prompt": str(item.get("visual_prompt") or _visual_prompt(section, narration, project_title)).strip(),
                # Honour the asset type the writer chose. Forcing ai_scene here
                # sent the reup workflow - whose pictures are cut from its own
                # source - into the image generators anyway.
                "asset_type": str(item.get("asset_type") or "ai_scene").strip() or "ai_scene",
                "duration_seconds": max(3, min(30, max(wanted, spoken))),
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
