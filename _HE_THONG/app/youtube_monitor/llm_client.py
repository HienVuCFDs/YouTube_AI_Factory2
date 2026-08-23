from __future__ import annotations

import json
from typing import Any

from . import settings
from .antigravity_bridge import AntigravityBridgeError, call_antigravity_json as _call_antigravity_json
from .claude_code_bridge import ClaudeCodeBridgeError, call_claude_code_json as _call_claude_code_json
from .codex_bridge import CodexBridgeError, call_codex_json as _call_codex_json
from . import usage_limits


class LlmError(RuntimeError):
    pass


def call_codex_json(
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    max_tokens: int = 2000,
) -> dict[str, Any]:
    """Use the locally logged-in Codex CLI without an OpenAI API key."""
    del max_tokens  # Codex CLI owns its model token budget.
    try:
        result = _call_codex_json(system_prompt, user_prompt, schema)
    except CodexBridgeError as exc:
        usage_limits.note_failure("codex_cli", str(exc))
        raise LlmError(str(exc)) from exc
    usage_limits.note_success("codex_cli")
    return result


def call_claude_code_cli_json(
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    max_tokens: int = 2000,
    image_path: str | None = None,
) -> dict[str, Any]:
    """Use the locally logged-in Claude Code CLI (claude.ai subscription)
    without an ANTHROPIC_API_KEY.

    Passing image_path lets the CLI open exactly that one file — the only way
    it can judge a generated image, since every tool is otherwise denied and
    it will (correctly) refuse to describe a file it cannot see.
    """
    del max_tokens  # Claude Code CLI owns its model token budget.
    try:
        result = _call_claude_code_json(system_prompt, user_prompt, schema, image_path=image_path)
    except ClaudeCodeBridgeError as exc:
        usage_limits.note_failure("claude_code_cli", str(exc))
        raise LlmError(str(exc)) from exc
    usage_limits.note_success("claude_code_cli")
    return result


def call_antigravity_json(
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    max_tokens: int = 2000,
) -> dict[str, Any]:
    """Use the locally logged-in Antigravity CLI (Google account) without an API key."""
    del max_tokens  # Antigravity CLI owns its model token budget.
    try:
        result = _call_antigravity_json(system_prompt, user_prompt, schema)
    except AntigravityBridgeError as exc:
        usage_limits.note_failure("antigravity", str(exc))
        raise LlmError(str(exc)) from exc
    usage_limits.note_success("antigravity")
    return result


def call_claude_json(
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    max_tokens: int = 2000,
) -> dict[str, Any]:
    api_key, model = settings.anthropic_config()
    if not api_key:
        raise LlmError("Thiếu ANTHROPIC_API_KEY. Hãy thêm vào .env để dùng Claude.")
    try:
        import anthropic
    except ImportError as exc:
        raise LlmError("Thiếu thư viện anthropic. Cài đặt bằng: pip install anthropic") from exc

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:
        raise LlmError(f"Claude API lỗi: {exc}") from exc

    text = next((block.text for block in response.content if block.type == "text"), "")
    try:
        return json.loads(text)
    except ValueError as exc:
        raise LlmError(f"Claude trả về JSON không hợp lệ: {exc}") from exc


def call_openai_json(
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    max_tokens: int = 2000,
) -> dict[str, Any]:
    api_key, model = settings.openai_config()
    if not api_key:
        raise LlmError("Thiếu OPENAI_API_KEY. Hãy thêm vào .env để dùng GPT.")
    import httpx

    schema_hint = json.dumps(schema, ensure_ascii=False)
    try:
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "response_format": {"type": "json_object"},
                "max_tokens": max_tokens,
                "messages": [
                    {
                        "role": "system",
                        "content": f"{system_prompt} Schema JSON bắt buộc: {schema_hint}",
                    },
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=90.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LlmError(f"OpenAI API lỗi: {exc}") from exc

    payload = response.json()
    try:
        text = payload["choices"][0]["message"]["content"]
        return json.loads(text)
    except (KeyError, IndexError, ValueError) as exc:
        raise LlmError(f"OpenAI trả về dữ liệu không hợp lệ: {exc}") from exc
