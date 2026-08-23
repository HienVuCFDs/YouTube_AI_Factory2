from __future__ import annotations

"""Turn a source video into a *reference brief*, never a script to copy."""

from typing import Any

from . import languages
from .llm_client import LlmError, call_antigravity_json, call_claude_code_cli_json, call_claude_json, call_codex_json, call_openai_json


ReferenceAnalysisError = LlmError

REFERENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "content_summary": {"type": "string"},
        "narrative_formula": {"type": "array", "items": {"type": "string"}},
        "scene_map": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "order": {"type": "integer"},
                    "story_beat": {"type": "string"},
                    "what_happens": {"type": "string"},
                    "visual_direction": {"type": "string"},
                    "editing_pacing": {"type": "string"},
                },
                "required": ["order", "story_beat", "what_happens", "visual_direction", "editing_pacing"],
                "additionalProperties": False,
            },
        },
        "visual_style": {
            "type": "object",
            "properties": {
                "art_direction": {"type": "string"},
                "subjects_and_setting": {"type": "string"},
                "lighting_palette": {"type": "string"},
                "camera_composition": {"type": "string"},
                "motion_editing": {"type": "string"},
                "text_graphics": {"type": "string"},
                "style_recipe": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["art_direction", "subjects_and_setting", "lighting_palette", "camera_composition", "motion_editing", "text_graphics", "style_recipe"],
            "additionalProperties": False,
        },
        "pacing": {"type": "string"},
        "remake_guardrails": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["content_summary", "narrative_formula", "scene_map", "visual_style", "pacing", "remake_guardrails", "limitations"],
    "additionalProperties": False,
}

FAITHFUL_MODE = "faithful"

_FAITHFUL_SYSTEM_PROMPT = """You are analysing a source video that will be RETOLD, not remade.
The new video keeps this content: the same events, people, numbers, order and ending, said a
different way. So report what the source actually contains, accurately and in order, and state
plainly what you could not determine. Do not propose changing anything, do not suggest a new
setting or new characters, and do not invent detail the source did not give. Return only the
requested JSON."""

_SYSTEM_PROMPT = """You are a YouTube creative director. Analyse a source only as a reference.
Identify its abstract storytelling structure, scene progression, pacing and visual language,
then make the result useful for producing an ORIGINAL new video. Never recap it scene by
scene for viewers, never reproduce dialogue, and never instruct copying distinctive protected
characters, logos or footage. State uncertainty frankly when no transcript or visual frames
were supplied. Return only the requested JSON."""


def _prompt(
    video: dict[str, Any],
    transcript_text: str | None,
    output_language: str = languages.DEFAULT_LANGUAGE,
    mode: str = "remake",
) -> str:
    parts = [
        f"Source title: {str(video.get('title') or '').strip()}",
        f"Source description: {str(video.get('description') or '').strip()[:2400]}",
        f"Tags: {', '.join(str(x) for x in (video.get('tags') or []))}",
    ]
    if transcript_text:
        parts.append(f"Transcript for story/scene inference (possibly shortened):\n{transcript_text[:12000]}")
        parts.append("Visual note: transcript confirms spoken content and sequence, not exact image details. Infer visual direction conservatively.")
    else:
        parts.append("No transcript or sampled frames are available. Do not pretend to have watched the video; mark visual claims as hypotheses in limitations.")
    if mode == FAITHFUL_MODE:
        # The remake brief below tells the writer to change the setting, the
        # characters and the motives. A retelling is judged on keeping all of
        # them, so the same fields are asked for with the opposite meaning
        # rather than handing the next step instructions that contradict it.
        parts.append(
            "Return a FAITHFUL content brief for retelling this source:\n"
            "- content_summary: what the source actually says or shows, accurately.\n"
            "- narrative_formula: the real sequence of events in order, not an abstract pattern.\n"
            "- scene_map: the actual scenes in order - what happens, who is in it, what is on screen.\n"
            "- visual_style: how the source looks, so the retelling can match it.\n"
            "- pacing: how fast the source moves.\n"
            "- remake_guardrails: the details that MUST BE KEPT EXACTLY when retelling - names, "
            "numbers, dates, places, who does what, the ending. Write each as a fact to preserve, "
            "never as a change to make.\n"
            "- limitations: what you could not determine and must not be guessed at."
        )
    else:
        parts.append(
            "Return a production reference brief: content_summary; narrative_formula (5-8 abstract beats); "
            "scene_map (6-12 scene units with story beat, action, visual direction and edit pacing); "
            "visual_style (a reusable, non-identical style recipe); pacing; remake_guardrails that enforce "
            "an original story; limitations."
        )
    parts.append(languages.instruction(output_language))
    return "\n\n".join(parts)


def analyze_reference(
    video: dict[str, Any],
    transcript_text: str | None,
    provider: str,
    output_language: str = languages.DEFAULT_LANGUAGE,
    mode: str = "remake",
) -> dict[str, Any]:
    name = str(provider or "codex_cli").strip().lower()
    user_prompt = _prompt(video, transcript_text, output_language, mode)
    system_prompt = _FAITHFUL_SYSTEM_PROMPT if mode == FAITHFUL_MODE else _SYSTEM_PROMPT
    if name == "codex_cli":
        result = call_codex_json(system_prompt, user_prompt, REFERENCE_SCHEMA, max_tokens=5000)
    elif name == "openai_gpt":
        result = call_openai_json(system_prompt, user_prompt, REFERENCE_SCHEMA, max_tokens=5000)
    elif name == "anthropic_claude":
        result = call_claude_json(system_prompt, user_prompt, REFERENCE_SCHEMA, max_tokens=5000)
    elif name == "claude_code_cli":
        result = call_claude_code_cli_json(system_prompt, user_prompt, REFERENCE_SCHEMA, max_tokens=5000)
    elif name == "antigravity":
        result = call_antigravity_json(system_prompt, user_prompt, REFERENCE_SCHEMA, max_tokens=5000)
    else:
        raise ReferenceAnalysisError(f"Provider không được hỗ trợ cho phân tích tham chiếu: {provider}")
    return {
        "provider": name,
        "mode": mode,
        "source_type": "transcript" if transcript_text else "metadata",
        "visual_evidence": "transcript-guided" if transcript_text else "metadata-only",
        **result,
    }
