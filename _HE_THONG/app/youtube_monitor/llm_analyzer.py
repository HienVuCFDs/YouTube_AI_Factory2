from __future__ import annotations

from typing import Any

from .analyzer import MetadataAnalyzer
from .llm_client import LlmError, call_antigravity_json, call_claude_code_cli_json, call_claude_json, call_codex_json, call_openai_json


LlmAnalysisError = LlmError


RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "language": {"type": "string"},
        "content_type": {"type": "string"},
        "topic": {"type": "string"},
        "keywords": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "count": {"type": "integer"},
                },
                "required": ["keyword", "count"],
                "additionalProperties": False,
            },
        },
        "hook": {"type": "string"},
        "description_opening": {"type": "string"},
        "recommendations": {"type": "array", "items": {"type": "string"}},
        "next_step": {"type": "string"},
    },
    "required": [
        "language", "content_type", "topic", "keywords",
        "hook", "description_opening", "recommendations", "next_step",
    ],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "Bạn là chuyên gia phân tích nội dung YouTube. Dựa trên metadata video "
    "(tiêu đề, mô tả, tags), hãy phân tích và trả về đúng schema JSON được yêu cầu. "
    "Không thêm giải thích ngoài JSON."
)


def _build_user_prompt(video: dict[str, Any]) -> str:
    title = str(video.get("title") or "").strip()
    description = str(video.get("description") or "").strip()
    tags = ", ".join(str(tag) for tag in (video.get("tags") or []))
    return (
        f"Tiêu đề: {title}\n"
        f"Mô tả: {description[:2000]}\n"
        f"Tags: {tags}\n\n"
        "Hãy trả về: language (mã ngôn ngữ, vd 'vi'/'en'), content_type "
        "(vd tutorial/news/review/finance/technology/entertainment/general), "
        "topic (chủ đề chính, 1-3 từ), keywords (5-12 từ khóa quan trọng kèm mức độ liên quan "
        "dưới dạng count 1-10), hook (câu mở đầu hấp dẫn gợi ý cho video mới), "
        "description_opening (câu mở đầu mô tả gợi ý), recommendations (2-4 đề xuất cải thiện "
        "SEO/nội dung), next_step (bước tiếp theo nên làm: 'transcript', 'script_writing' hoặc "
        "'manual_review')."
    )


def _finalize_result(video: dict[str, Any], provider: str, parsed: dict[str, Any]) -> dict[str, Any]:
    title = str(video.get("title") or "").strip()
    return {
        "provider": provider,
        "source_type": "metadata",
        "title": title,
        "language": parsed.get("language", ""),
        "content_type": parsed.get("content_type", "general"),
        "topic": parsed.get("topic", ""),
        "keywords": parsed.get("keywords", []),
        "hook": parsed.get("hook", title),
        "description_opening": parsed.get("description_opening", ""),
        "metrics": {
            "title_length": len(title),
            "description_length": len(str(video.get("description") or "")),
            "tag_count": len(video.get("tags") or []),
            "has_thumbnail": bool(video.get("thumbnail_url")),
            "caption_available": bool(video.get("caption_available")),
        },
        "recommendations": parsed.get("recommendations", []),
        "next_step": parsed.get("next_step", "manual_review"),
    }


class ClaudeAnalyzer:
    """Phân tích metadata bằng Claude API (cần ANTHROPIC_API_KEY)."""

    provider = "anthropic_claude"

    def analyze(self, video: dict[str, Any]) -> dict[str, Any]:
        parsed = call_claude_json(_SYSTEM_PROMPT, _build_user_prompt(video), RESULT_SCHEMA)
        return _finalize_result(video, self.provider, parsed)


class OpenAiAnalyzer:
    """Phân tích metadata bằng OpenAI API (cần OPENAI_API_KEY)."""

    provider = "openai_gpt"

    def analyze(self, video: dict[str, Any]) -> dict[str, Any]:
        parsed = call_openai_json(_SYSTEM_PROMPT, _build_user_prompt(video), RESULT_SCHEMA)
        return _finalize_result(video, self.provider, parsed)


class CodexAnalyzer:
    """Phan tich metadata bang Codex CLI da dang nhap tren may local."""

    provider = "codex_cli"

    def analyze(self, video: dict[str, Any]) -> dict[str, Any]:
        parsed = call_codex_json(_SYSTEM_PROMPT, _build_user_prompt(video), RESULT_SCHEMA)
        return _finalize_result(video, self.provider, parsed)


class ClaudeCodeCliAnalyzer:
    """Phan tich metadata bang Claude Code CLI da dang nhap, khong can ANTHROPIC_API_KEY."""

    provider = "claude_code_cli"

    def analyze(self, video: dict[str, Any]) -> dict[str, Any]:
        parsed = call_claude_code_cli_json(_SYSTEM_PROMPT, _build_user_prompt(video), RESULT_SCHEMA)
        return _finalize_result(video, self.provider, parsed)


class AntigravityAnalyzer:
    """Phan tich metadata bang Antigravity CLI da dang nhap, khong can API key."""

    provider = "antigravity"

    def analyze(self, video: dict[str, Any]) -> dict[str, Any]:
        parsed = call_antigravity_json(_SYSTEM_PROMPT, _build_user_prompt(video), RESULT_SCHEMA)
        return _finalize_result(video, self.provider, parsed)


_LOCAL_ANALYZER = MetadataAnalyzer()
_LLM_ANALYZERS: dict[str, Any] = {}

AVAILABLE_PROVIDERS = [
    _LOCAL_ANALYZER.provider,
    ClaudeAnalyzer.provider,
    OpenAiAnalyzer.provider,
    CodexAnalyzer.provider,
    ClaudeCodeCliAnalyzer.provider,
    AntigravityAnalyzer.provider,
]


def resolve_analyzer(provider: str | None):
    """Return an analyzer instance for the given provider name.

    Falls back to the free local_metadata analyzer when provider is empty.
    """
    name = provider or _LOCAL_ANALYZER.provider
    if name == _LOCAL_ANALYZER.provider:
        return _LOCAL_ANALYZER
    if name not in _LLM_ANALYZERS:
        if name == ClaudeAnalyzer.provider:
            _LLM_ANALYZERS[name] = ClaudeAnalyzer()
        elif name == OpenAiAnalyzer.provider:
            _LLM_ANALYZERS[name] = OpenAiAnalyzer()
        elif name == CodexAnalyzer.provider:
            _LLM_ANALYZERS[name] = CodexAnalyzer()
        elif name == ClaudeCodeCliAnalyzer.provider:
            _LLM_ANALYZERS[name] = ClaudeCodeCliAnalyzer()
        elif name == AntigravityAnalyzer.provider:
            _LLM_ANALYZERS[name] = AntigravityAnalyzer()
        else:
            raise LlmAnalysisError(f"Provider không được hỗ trợ: {name}")
    return _LLM_ANALYZERS[name]
