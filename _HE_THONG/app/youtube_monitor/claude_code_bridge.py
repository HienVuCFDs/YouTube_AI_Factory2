from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from . import settings


class ClaudeCodeBridgeError(RuntimeError):
    pass


def _local_claude_environment() -> dict[str, str]:
    """Use the user's normal, already-logged-in Claude Code profile.

    Unlike Codex CLI (CODEX_HOME fully redirects its profile, including
    credentials — verified working), Claude Code CLI does not persist login
    credentials under CLAUDE_CONFIG_DIR (verified empirically: after running
    `claude auth login` with CLAUDE_CONFIG_DIR pointed at an isolated folder,
    only a bare .claude.json appeared there — no .credentials.json; the real
    credentials stayed in the default ~/.claude). So there is no working way
    to give this bridge an isolated login the way Codex's bridge has one;
    it just uses whatever account is already logged into Claude Code on this
    machine, same as antigravity_bridge.py does for Antigravity.
    """
    return os.environ.copy()


def claude_code_cli_status() -> dict[str, Any]:
    executable = settings.CLAUDE_CODE_CLI_PATH
    if not executable or not Path(executable).is_file():
        return {
            "installed": False,
            "logged_in": False,
            "path": "",
            "detail": "Khong tim thay Claude Code CLI tren may",
        }
    try:
        # `claude auth status` prints JSON: {"loggedIn": bool, "authMethod": ...,
        # "subscriptionType": ...} — a plain read, no prompt is sent, no cost.
        result = subprocess.run(
            [executable, "auth", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
            env=_local_claude_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "installed": False,
            "logged_in": False,
            "path": executable,
            "detail": f"Khong chay duoc Claude Code CLI: {exc}",
        }
    logged_in = False
    subscription = ""
    parse_error = ""
    # Slice out just the {...} block rather than assuming the whole stdout is
    # pure JSON — some environments print an extra update-check/banner line
    # before or after the JSON that a strict json.loads() would choke on.
    stdout = result.stdout or ""
    start, end = stdout.find("{"), stdout.rfind("}")
    try:
        if start == -1 or end == -1 or end < start:
            raise ValueError("khong thay khoi JSON trong output")
        payload = json.loads(stdout[start:end + 1])
        logged_in = bool(payload.get("loggedIn"))
        subscription = str(payload.get("subscriptionType") or "")
    except (json.JSONDecodeError, ValueError, AttributeError) as exc:
        parse_error = f" (rc={result.returncode}, loi doc output: {exc}; stdout={stdout[:200]!r}; stderr={(result.stderr or '')[:200]!r})"
    detail = (
        f"Claude Code CLI da dang nhap (goi {subscription})" if logged_in and subscription
        else "Claude Code CLI da dang nhap" if logged_in
        else f"Claude Code CLI chua dang nhap{parse_error}"
    )
    return {"installed": True, "logged_in": logged_in, "path": executable, "detail": detail}


def _parse_json_output(text: str) -> dict[str, Any]:
    """Extract the structured JSON payload from `claude -p --output-format json`.

    Not fully verified against a live run (see claude_code_bridge module docs
    in web_video_sidecar.py) — tries the shapes that are plausible for
    --json-schema output and falls back gracefully rather than guessing wrong
    silently: a bare JSON object, a {"result": {...}} envelope, or a
    {"result": "...json string..."} envelope.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3].rstrip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ClaudeCodeBridgeError("Claude Code khong tra ve JSON hop le") from exc
    if not isinstance(parsed, dict):
        raise ClaudeCodeBridgeError("Claude Code phai tra ve mot JSON object")
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


def call_claude_code_json(
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    timeout_seconds: int = 600,
    image_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the user's local Claude Code CLI as a structured-output agent.

    Uses the CLI's existing claude.ai login (subscription) rather than an
    ANTHROPIC_API_KEY. When image_path is given, the Read tool is allowed so
    Claude can view exactly that one file (e.g. a Playwright screenshot for
    web_video_sidecar.py's vision fallback) — every other tool stays denied.
    """
    status = claude_code_cli_status()
    if not status["installed"]:
        raise ClaudeCodeBridgeError("Khong tim thay Claude Code CLI; hay cai hoac cau hinh CLAUDE_CODE_CLI_PATH")
    if not status["logged_in"]:
        raise ClaudeCodeBridgeError("Claude Code CLI chua dang nhap. Hay chay `claude auth login` mot lan")

    instruction = f"{system_prompt}\n\n{user_prompt}"
    if image_path:
        instruction += f"\n\nAnh can xem: {Path(image_path).resolve()}"
    executable = str(status["path"])
    command = [
        executable,
        "-p", instruction,
        "--output-format", "json",
        "--json-schema", json.dumps(schema, ensure_ascii=False),
        "--dangerously-skip-permissions",
        # --tools "" disables every tool (matches Codex's read-only, no-file,
        # no-command posture); --tools "Read" allows viewing exactly the one
        # image file referenced above and nothing else. Both forms are
        # documented by `claude --help` (verified live on this machine).
        "--tools", "Read" if image_path else "",
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
            env=_local_claude_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClaudeCodeBridgeError(f"Khong chay duoc Claude Code CLI: {exc}") from exc
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip()[-2000:]
        raise ClaudeCodeBridgeError(f"Claude Code CLI that bai: {detail or process.returncode}")
    return _parse_json_output(process.stdout)
