from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from . import settings


class AntigravityBridgeError(RuntimeError):
    pass


def _antigravity_environment() -> dict[str, str]:
    return os.environ.copy()


def antigravity_cli_status() -> dict[str, Any]:
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


def _parse_json_output(text: str) -> dict[str, Any]:
    """Same defensive multi-shape parsing as claude_code_bridge._parse_json_output
    (see that module for why) — Antigravity's exact --output-format json envelope
    for --json-schema results wasn't verified against a live run either."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3].rstrip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AntigravityBridgeError("Antigravity khong tra ve JSON hop le") from exc
    if not isinstance(parsed, dict):
        raise AntigravityBridgeError("Antigravity phai tra ve mot JSON object")
    if "result" in parsed:
        result = parsed["result"]
        if isinstance(result, dict):
            return result
        if isinstance(result, str):
            try:
                inner = json.loads(result)
            except json.JSONDecodeError:
                inner = None
            if isinstance(inner, dict):
                return inner
    return parsed


def call_antigravity_json(
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    timeout_seconds: int = 600,
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
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            cwd=str(settings.PROJECT_ROOT),
            env=_antigravity_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AntigravityBridgeError(f"Khong chay duoc Antigravity CLI: {exc}") from exc
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip()[-2000:]
        raise AntigravityBridgeError(f"Antigravity CLI that bai: {detail or process.returncode}")
    return _parse_json_output(process.stdout)
