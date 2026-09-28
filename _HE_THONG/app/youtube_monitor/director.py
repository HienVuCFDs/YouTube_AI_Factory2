from __future__ import annotations

import re
from typing import Any

from . import orchestrator_runtime
from .codex_bridge import CodexBridgeError, call_codex_json
from .llm_client import LlmError, call_antigravity_json, call_claude_code_cli_json, call_claude_json, call_openai_json


class DirectorError(RuntimeError):
    pass


DIRECTOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "script_title": {"type": "string"},
        "hook": {"type": "string"},
        "intro": {"type": "string"},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string"},
                    "narration": {"type": "string"},
                    "visual_intent": {"type": "string"},
                    "source_cue": {"type": "string"},
                    "asset_type": {"type": "string"},
                },
                "required": ["section", "narration", "visual_intent", "source_cue", "asset_type"],
                "additionalProperties": False,
            },
        },
        "cta": {"type": "string"},
    },
    "required": ["script_title", "hook", "intro", "segments", "cta"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = """Bạn là AI Đạo diễn và biên tập viên YouTube bằng tiếng Việt.
Hãy tạo một kịch bản BÌNH LUẬN MỚI, mạch lạc, có giá trị phân tích riêng; không chép lại câu chữ
hay cấu trúc trình bày của video tham khảo. Mỗi segment phải nối ý segment trước, ngắn gọn và có
hình minh họa cụ thể. source_cue là 2-5 từ khóa tiếng Anh để tìm cảnh cùng chủ đề trong video
nguồn (ví dụ: directional bias, data, location, confirmation, point of interest, trade). asset_type
chỉ nhận: talking_head, source_clip, broll, ai_scene. Tránh lời khuyên tài chính trực tiếp; ưu tiên
giải thích quy trình, rủi ro và kiểm chứng. Trả về đúng JSON theo schema, không kèm markdown."""


def _text(value: Any, maximum: int = 3000) -> str:
    return " ".join(str(value or "").split())[:maximum].strip()


def _list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item, 500) for item in value if _text(item, 500)][:limit]


def _director_prompt(bundle: dict[str, Any]) -> str:
    project = bundle.get("project") or {}
    video = bundle.get("source_video") or {}
    writer = (bundle.get("writer_content") or {}).get("result") or {}
    existing = bundle.get("latest_script") or {}
    transcript = (bundle.get("latest_transcript") or {}).get("content_text") or ""
    workflow = (
        f"Destination channel: {project.get('managed_channel_name', '')}; "
        f"style reference: {project.get('workflow_reference_title', '')}; "
        f"output format: {project.get('managed_channel_output_profile', '')}"
        if project.get("managed_channel_id") else ""
    )
    parts = [
        f"Tên project: {_text(project.get('title'), 200)}",
        f"Video tham khảo: {_text(video.get('title'), 500)}",
        f"Mô tả nguồn: {_text(video.get('description'), 1800)}",
        f"Ý chính đã phân tích: {' | '.join(_list(writer.get('key_ideas'), 6))}",
        f"Tóm tắt AI Writer: {_text(writer.get('summary'), 1600)}",
        f"Kịch bản đang có: Hook={_text(existing.get('hook'), 600)}; Intro={_text(existing.get('intro'), 1000)}; Nội dung={_text(existing.get('main_content'), 3000)}; CTA={_text(existing.get('cta'), 600)}",
    ]
    if workflow:
        parts.append(
            f"Workflow style reference (use pacing/tone only, never copy content): {workflow}"
        )
    if transcript:
        parts.append(f"Transcript tham khảo (chỉ lấy ý, không sao chép):\n{_text(transcript, 9000)}")
    parts.append(
        "Yêu cầu đầu ra: 7-10 segments cho video 90-150 giây. Hook 1 câu gây tò mò; intro đặt vấn đề; "
        "các segment thân bài giải thích liên tiếp theo logic; CTA tự nhiên. Mỗi narration 1-3 câu, tối đa 55 từ. "
        "Đề xuất visual_intent chi tiết để editor biết nên lấy chart, người nói, dashboard hay cảnh minh họa nào."
    )
    return "\n\n".join(parts)


def _call(provider: str, prompt: str) -> dict[str, Any]:
    # An agent name (astra, claude) arrives here as readily as a runtime name.
    name = orchestrator_runtime.runtime_id(str(provider or "codex_cli"))
    try:
        if name == "codex_cli":
            return call_codex_json(_SYSTEM_PROMPT, prompt, DIRECTOR_SCHEMA, timeout_seconds=600)
        if name == "openai_gpt":
            return call_openai_json(_SYSTEM_PROMPT, prompt, DIRECTOR_SCHEMA, max_tokens=4500)
        if name == "anthropic_claude":
            return call_claude_json(_SYSTEM_PROMPT, prompt, DIRECTOR_SCHEMA, max_tokens=4500)
        if name == "claude_code_cli":
            return call_claude_code_cli_json(_SYSTEM_PROMPT, prompt, DIRECTOR_SCHEMA, max_tokens=4500)
        if name == "antigravity":
            return call_antigravity_json(_SYSTEM_PROMPT, prompt, DIRECTOR_SCHEMA, max_tokens=4500)
    except (CodexBridgeError, LlmError) as exc:
        raise DirectorError(str(exc)) from exc
    raise DirectorError(f"Director provider không được hỗ trợ: {provider}")


def _duration(text: str) -> int:
    words = len(re.findall(r"\w+", text, flags=re.UNICODE))
    return max(5, min(28, round(words / 2.45) + 2))


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    valid_sections = {"hook", "intro", "main", "cta"}
    valid_assets = {"talking_head", "source_clip", "broll", "ai_scene"}
    segments: list[dict[str, str]] = []
    for index, item in enumerate(raw.get("segments") if isinstance(raw.get("segments"), list) else [], start=1):
        if not isinstance(item, dict):
            continue
        narration = _text(item.get("narration"), 650)
        if not narration:
            continue
        section = _text(item.get("section"), 30).lower() or "main"
        if section not in valid_sections:
            section = "main"
        asset_type = _text(item.get("asset_type"), 30).lower() or "source_clip"
        if asset_type not in valid_assets:
            asset_type = "source_clip"
        segments.append(
            {
                "section": section,
                "narration": narration,
                "visual_intent": _text(item.get("visual_intent"), 500) or "Cảnh nguồn liên quan trực tiếp tới ý đang nói.",
                "source_cue": _text(item.get("source_cue"), 100) or "general explanation",
                "asset_type": asset_type,
            }
        )
    if not segments:
        raise DirectorError("AI Đạo diễn không tạo được segment có lời dẫn")
    if len(segments) > 12:
        segments = segments[:12]
    return {
        "script_title": _text(raw.get("script_title"), 250) or "Bản dựng do AI Đạo diễn tạo",
        "hook": _text(raw.get("hook"), 600) or segments[0]["narration"],
        "intro": _text(raw.get("intro"), 1600),
        "segments": segments,
        "cta": _text(raw.get("cta"), 600) or "Hãy để lại góc nhìn của bạn sau khi tự kiểm chứng quy trình này.",
    }


def generate_director_draft(bundle: dict[str, Any], provider: str = "codex_cli") -> dict[str, Any]:
    return {"provider": provider, **_normalize(_call(provider, _director_prompt(bundle)))}


def director_to_script(director: dict[str, Any]) -> dict[str, str]:
    main = [item["narration"] for item in director["segments"] if item["section"] == "main"]
    intro = director["intro"] or " ".join(
        item["narration"] for item in director["segments"] if item["section"] == "intro"
    )
    return {
        "script_title": director["script_title"],
        "hook": director["hook"],
        "intro": intro,
        "main_content": "\n".join(main),
        "cta": director["cta"],
    }


def director_to_shots(project: dict[str, Any], director: dict[str, Any]) -> list[dict[str, Any]]:
    shots: list[dict[str, Any]] = []
    for index, item in enumerate(director["segments"], start=1):
        narration = item["narration"]
        visual_prompt = (
            f"[SOURCE_CUE: {item['source_cue']}] {item['visual_intent']} "
            f"Narration context: {narration}"
        )
        shots.append(
            {
                "shot_index": index,
                "section": item["section"],
                "narration": narration,
                "visual_prompt": visual_prompt,
                "asset_type": item["asset_type"],
                "duration_seconds": _duration(narration),
                "status": "planned",
            }
        )
    return shots


def director_to_markdown(director: dict[str, Any]) -> str:
    lines = [f"# AI Đạo diễn: {director['script_title']}", "", f"- Provider: {director['provider']}", ""]
    for index, item in enumerate(director["segments"], start=1):
        lines.extend(
            [
                f"## Cảnh {index} · {item['section']}",
                "",
                f"- Source cue: {item['source_cue']}",
                f"- Asset type: {item['asset_type']}",
                f"- Visual: {item['visual_intent']}",
                "",
                item["narration"],
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"
