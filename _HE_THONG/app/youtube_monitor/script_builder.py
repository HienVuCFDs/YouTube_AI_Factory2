from __future__ import annotations

from typing import Any


def _items(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def _blueprint_script(writer: dict[str, Any], project: dict[str, Any]) -> dict[str, str] | None:
    """Make the visible script equal the narration that storyboard/TTS will use."""
    raw_scenes = writer.get("scene_blueprints") if isinstance(writer, dict) else None
    if not isinstance(raw_scenes, list):
        return None
    scenes = [item for item in raw_scenes if isinstance(item, dict) and str(item.get("narration") or "").strip()]
    if not scenes:
        return None
    scenes.sort(key=lambda item: int(item.get("order") or 0))
    narration = [str(item.get("narration") or "").strip() for item in scenes]
    generated = writer.get("new_script") if isinstance(writer.get("new_script"), dict) else {}
    titles = _items(writer.get("new_titles"))
    title = str(generated.get("script_title") or (titles[0] if titles else "") or project.get("title") or "Kịch bản AI").strip()
    hook = narration[0]
    if len(narration) == 1:
        return {"script_title": title, "hook": hook, "intro": "", "main_content": "", "cta": ""}
    intro = narration[1] if len(narration) > 2 else ""
    cta = narration[-1]
    middle_start = 2 if len(narration) > 3 else 1
    middle_end = -1 if len(narration) > 2 else len(narration)
    body_lines: list[str] = []
    for index, item in enumerate(scenes[middle_start:middle_end], start=middle_start + 1):
        section = str(item.get("section") or "Diễn biến").strip()
        body_lines.append(f"Cảnh {index} · {section}\n{str(item.get('narration') or '').strip()}")
    return {
        "script_title": title,
        "hook": hook,
        "intro": intro,
        "main_content": "\n\n".join(body_lines),
        "cta": cta,
    }


def build_script_draft(bundle: dict[str, Any]) -> dict[str, str]:
    project = bundle.get("project") or {}
    video = bundle.get("source_video") or {}
    metadata = (bundle.get("metadata_analysis") or {}).get("result") or {}
    writer = (bundle.get("writer_content") or {}).get("result") or {}

    production_script = _blueprint_script(writer, project)
    if production_script:
        return production_script

    generated_script = writer.get("new_script") if isinstance(writer.get("new_script"), dict) else {}
    if generated_script and any(str(generated_script.get(key) or "").strip() for key in ("hook", "intro", "main_content", "cta")):
        return {
            "script_title": str(generated_script.get("script_title") or project.get("title") or "Video mới do AI tạo").strip(),
            "hook": str(generated_script.get("hook") or "").strip(),
            "intro": str(generated_script.get("intro") or "").strip(),
            "main_content": str(generated_script.get("main_content") or "").strip(),
            "cta": str(generated_script.get("cta") or "").strip(),
        }

    titles = _items(writer.get("new_titles"))
    ideas = _items(writer.get("key_ideas"))
    outline = _items(writer.get("script_outline"))
    recommendations = _items(metadata.get("recommendations"))

    source_title = str(video.get("title") or project.get("title") or "").strip()
    script_title = titles[0] if titles else f"Góc nhìn mới: {source_title}".strip()
    hook = str(metadata.get("hook") or "").strip()
    if not hook and titles:
        hook = f"Vì sao {titles[0].rstrip('?')}?"
    if not hook:
        hook = "Mở đầu bằng một câu hỏi hoặc tình huống khiến người xem muốn ở lại."

    summary = str(writer.get("summary") or metadata.get("description_opening") or "").strip()
    intro = summary or (
        "Giới thiệu chủ đề chính, nêu lý do người xem nên quan tâm và đặt kỳ vọng rằng video mới "
        "sẽ bổ sung góc nhìn riêng thay vì lặp lại nguồn tham khảo."
    )

    body_lines: list[str] = []
    source_points = outline or ideas or recommendations
    for index, item in enumerate(source_points, start=1):
        body_lines.append(f"{index}. {item}")
    if not body_lines:
        body_lines = [
            "1. Trình bày bối cảnh của chủ đề bằng ngôn ngữ riêng.",
            "2. Chọn 2-3 luận điểm chính và bổ sung ví dụ hoặc quan sát cá nhân.",
            "3. Kết lại bằng bài học, cảnh báo hoặc đề xuất hành động cụ thể cho người xem.",
        ]

    cta = str(writer.get("cta") or "").strip() or (
        "Nếu bạn muốn mình đào sâu chủ đề này ở video tiếp theo, hãy để lại bình luận bên dưới."
    )

    return {
        "script_title": script_title,
        "hook": hook,
        "intro": intro,
        "main_content": "\n".join(body_lines),
        "cta": cta,
    }


def script_to_markdown(script: dict[str, Any], project: dict[str, Any] | None = None) -> str:
    title = str(script.get("script_title") or (project or {}).get("title") or "").strip()
    if not title:
        title = "Kịch bản sản xuất"
    parts = [
        f"# {title}",
        "",
        f"- Project ID: {script.get('project_id', '')}",
        f"- Script ID: {script.get('id', '')}",
        f"- Version: {script.get('version', '')}",
        f"- Status: {script.get('status', '')}",
        "",
        "## Hook",
        str(script.get("hook") or "").strip(),
        "",
        "## Intro",
        str(script.get("intro") or "").strip(),
        "",
        "## Nội dung chính",
        str(script.get("main_content") or "").strip(),
        "",
        "## CTA",
        str(script.get("cta") or "").strip(),
        "",
    ]
    return "\n".join(parts).strip() + "\n"
