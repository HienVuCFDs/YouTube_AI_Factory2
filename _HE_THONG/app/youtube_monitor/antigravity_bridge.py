from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from . import operations, settings


class AntigravityBridgeError(RuntimeError):
    pass


def _antigravity_environment() -> dict[str, str]:
    return os.environ.copy()


# `agy models` (used only to check login status) takes up to 20s and is
# invoked from ~6 endpoints the frontend polls every 3s. Uncached, that
# stacked into 4-5+ concurrent `agy.exe` processes at all times, real enough
# resource contention that it was starving the actual sidecar's own agy
# calls. A short TTL keeps the status reasonably fresh without re-spawning a
# process on every poll.
_status_cache: dict[str, Any] | None = None
_status_cache_at = 0.0
_STATUS_CACHE_TTL_SECONDS = 20.0


def antigravity_cli_status() -> dict[str, Any]:
    global _status_cache, _status_cache_at
    now = time.monotonic()
    if _status_cache is not None and (now - _status_cache_at) < _STATUS_CACHE_TTL_SECONDS:
        return _status_cache
    result = _antigravity_cli_status_uncached()
    _status_cache, _status_cache_at = result, now
    return result


def _antigravity_cli_status_uncached() -> dict[str, Any]:
    executable = settings.ANTIGRAVITY_CLI_PATH
    if not executable or not Path(executable).is_file():
        return {
            "installed": False,
            "logged_in": False,
            "path": "",
            "detail": "Khong tim thay Antigravity CLI (agy.exe) tren may",
        }
    try:
        # `agy models` lists the account's available models — succeeds only
        # when logged in, and doesn't run a prompt (no cost, no side effect).
        result = subprocess.run(
            [executable, "models"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
            env=_antigravity_environment(),
        )
    except OSError as exc:
        return {
            "installed": False,
            "logged_in": False,
            "path": executable,
            "detail": f"Khong chay duoc Antigravity CLI: {exc}",
        }
    logged_in = result.returncode == 0 and bool(result.stdout.strip())
    detail = "Antigravity CLI da dang nhap" if logged_in else "Antigravity CLI chua dang nhap hoac loi"
    return {"installed": True, "logged_in": logged_in, "path": executable, "detail": detail}


def _unwrap_double_encoded(payload: dict[str, Any]) -> dict[str, Any]:
    """Undo the CLI wrapping a whole JSON answer inside one of its own fields.

    Observed live: asked for {"answer": "ok"} it returns
    structured_output = {"answer": "{\"answer\": \"ok\"}"} - the object encoded
    again as the value of its own key. Left alone, every field reads as a
    string of JSON rather than the value it names.
    """
    if len(payload) == 1:
        only = next(iter(payload.values()))
        if isinstance(only, str):
            try:
                inner = json.loads(only)
            except (TypeError, ValueError):
                inner = None
            if isinstance(inner, dict):
                return inner
    return payload


def _first_json_object(text: str) -> dict[str, Any] | None:
    """Pull the first complete JSON object out of a model's free text."""
    body = text or ""
    start = body.find("{")
    while start != -1:
        depth, in_string, escaped = 0, False, False
        for index in range(start, len(body)):
            char = body[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(body[start:index + 1])
                    except ValueError:
                        break
                    if isinstance(parsed, dict):
                        return parsed
                    break
        start = body.find("{", start + 1)
    return None


def _parse_json_output(text: str) -> dict[str, Any]:
    """Read the answer out of Antigravity's envelope.

    The envelope was previously guessed at rather than checked against a live
    run, and the guess was wrong: it looks for "result", which Antigravity does
    not use. Finding nothing, the old code returned the envelope itself, so
    every schema field was missing and an empty analysis was stored as a
    success. A live call returns conversation_id, status, response,
    structured_output and usage.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        raise AntigravityBridgeError("Antigravity khong tra ve gi")
    try:
        envelope = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        # Some invocations print the answer directly rather than an envelope.
        direct = _first_json_object(cleaned)
        if direct is not None:
            return direct
        raise AntigravityBridgeError("Antigravity khong tra ve JSON hop le") from exc
    if not isinstance(envelope, dict):
        raise AntigravityBridgeError("Antigravity phai tra ve mot JSON object")

    # Not every invocation wraps the answer. If none of the envelope's own keys
    # are present, this object is the answer.
    envelope_keys = ("status", "response", "structured_output", "conversation_id", "result")
    if not any(key in envelope for key in envelope_keys):
        return envelope

    status = str(envelope.get("status") or "").upper()
    if status and status != "SUCCESS":
        detail = str(envelope.get("response") or envelope.get("error") or status)
        raise AntigravityBridgeError(f"Antigravity bao that bai ({status}): {detail[:400]}")

    # The model's own words come first: structured_output is the CLI's
    # extraction of them, and it is the half that double-encodes.
    spoken = _first_json_object(str(envelope.get("response") or ""))
    if spoken:
        return _unwrap_double_encoded(spoken)
    structured = envelope.get("structured_output")
    if isinstance(structured, dict) and structured:
        return _unwrap_double_encoded(structured)
    for key in ("result", "output", "data"):
        value = envelope.get(key)
        if isinstance(value, dict) and value:
            return value
        if isinstance(value, str):
            inner = _first_json_object(value)
            if inner:
                return inner
    raise AntigravityBridgeError(
        "Antigravity chay xong nhung khong tim thay ket qua JSON trong phan hoi"
    )


def call_antigravity_json(
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    # A full script for a fifteen minute video is a large generation:
    # forty-odd scenes, each with narration and an image prompt. Ten
    # minutes was not enough and the run was thrown away at the end.
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    """Run the user's local Antigravity CLI as a sandboxed structured-output agent.

    Uses the CLI's existing login (Google account) rather than an API key,
    same pattern as call_codex_json / call_claude_code_json.
    """
    status = antigravity_cli_status()
    if not status["installed"]:
        raise AntigravityBridgeError("Khong tim thay Antigravity CLI; hay cai Antigravity")
    if not status["logged_in"]:
        raise AntigravityBridgeError("Antigravity CLI chua dang nhap. Hay mo Antigravity va dang nhap mot lan")

    instruction = (
        f"{system_prompt}\n\n"
        "Quy tac bat buoc: chi phan tich noi dung duoc cung cap; khong doc file, khong chay lenh, "
        "khong sua project va khong truy cap mang. Tra ve dung JSON theo schema.\n\n"
        f"Du lieu can xu ly:\n{user_prompt}"
    )
    executable = str(status["path"])
    command = [
        executable,
        "-p", instruction,
        "--output-format", "json",
        "--json-schema", json.dumps(schema, ensure_ascii=False),
        "--sandbox",
        "--dangerously-skip-permissions",
        "--print-timeout", f"{max(1, timeout_seconds // 60)}m",
    ]
    try:
        process = operations.run_cancellable(
            command,
            timeout=timeout_seconds,
            cwd=str(settings.PROJECT_ROOT),
            env=_antigravity_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AntigravityBridgeError(f"Khong chay duoc Antigravity CLI: {exc}") from exc
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip()[-2000:]
        raise AntigravityBridgeError(f"Antigravity CLI that bai: {detail or process.returncode}")
    return _parse_json_output(process.stdout)
