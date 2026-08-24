from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

from . import settings
from .antigravity_bridge import AntigravityBridgeError, call_antigravity_json as _call_antigravity_json
from .claude_code_bridge import ClaudeCodeBridgeError, call_claude_code_json as _call_claude_code_json
from .codex_bridge import CodexBridgeError, call_codex_json as _call_codex_json
from . import usage_limits


class LlmError(RuntimeError):
    pass

# A provider being briefly overloaded is not the same as it being broken or
# out of quota, and it used to be treated as both. The reference analysis reads
# a long transcript in several sequential passes; one 529 anywhere in that run
# threw away every pass before it. These are the phrases that mean "ask again
# shortly" rather than "stop asking".
_TRANSIENT_MARKERS = (
    "529",
    "overloaded",
    "503",
    "502",
    "504",
    "service unavailable",
    "temporarily unavailable",
    "try again in a moment",
    "connection reset",
    "connection aborted",
    "read timed out",
)
_RETRY_DELAYS = (5.0, 20.0, 45.0)


def _is_transient(message: str) -> bool:
    """Whether asking again shortly is likely to work.

    A usage limit is never transient however it is worded: retrying that just
    burns minutes to be refused three more times.
    """
    if usage_limits.is_usage_limit(message):
        return False
    return any(marker in (message or "").lower() for marker in _TRANSIENT_MARKERS)


def _readable(message: str) -> str:
    """Pull the one useful sentence out of a CLI's JSON error blob.

    Claude Code reports failures as a page of session accounting with the
    actual cause in a "result" field, which is how "API Error: 529 Overloaded"
    ended up invisible behind a wall of token counts.
    """
    text = str(message or "")
    match = re.search(r'"result"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if match:
        try:
            return json.loads(f'"{match.group(1)}"')
        except ValueError:
            return match.group(1)
    return text


def _with_retry(agent: str, call: Callable[[], dict[str, Any]], errors: tuple[type[Exception], ...]):
    """Run a CLI call, giving a briefly overloaded provider another chance."""
    last = ""
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            result = call()
        except errors as exc:
            last = str(exc)
            usage_limits.note_failure(agent, last)
            if attempt >= len(_RETRY_DELAYS) or not _is_transient(last):
                raise LlmError(_readable(last)) from exc
            time.sleep(_RETRY_DELAYS[attempt])
            continue
        usage_limits.note_success(agent)
        return result
    raise LlmError(_readable(last))


def call_codex_json(
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    max_tokens: int = 2000,
) -> dict[str, Any]:
    """Use the locally logged-in Codex CLI without an OpenAI API key."""
    del max_tokens  # Codex CLI owns its model token budget.
    return _with_retry(
        "codex_cli",
        lambda: _call_codex_json(system_prompt, user_prompt, schema),
        (CodexBridgeError,),
    )


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
    return _with_retry(
        "claude_code_cli",
        lambda: _call_claude_code_json(system_prompt, user_prompt, schema, image_path=image_path),
        (ClaudeCodeBridgeError,),
    )


def call_antigravity_json(
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    max_tokens: int = 2000,
) -> dict[str, Any]:
    """Use the locally logged-in Antigravity CLI (Google account) without an API key."""
    del max_tokens  # Antigravity CLI owns its model token budget.
    return _with_retry(
        "antigravity",
        lambda: _call_antigravity_json(system_prompt, user_prompt, schema),
        (AntigravityBridgeError,),
    )


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
