from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from . import operations, settings


class CodexBridgeError(RuntimeError):
    pass


def _local_codex_environment() -> dict[str, str]:
    """Use this app's dedicated Codex profile, never an inherited session."""
    environment = os.environ.copy()
    settings.CODEX_BRIDGE_HOME.mkdir(parents=True, exist_ok=True)
    # A bridge launched by a development tool must not inherit a temporary
    # bearer token belonging to that tool's own session.
    environment["CODEX_HOME"] = str(settings.CODEX_BRIDGE_HOME)
    environment.pop("CODEX_ACCESS_TOKEN", None)
    return environment


# See antigravity_bridge.py's _status_cache for why: this status check is
# invoked from ~6 endpoints the frontend polls every 3s, and uncached that
# stacks up concurrent CLI subprocesses for no reason (the login state
# barely changes second to second).
_status_cache: dict[str, Any] | None = None
_status_cache_at = 0.0
_STATUS_CACHE_TTL_SECONDS = 20.0


def codex_cli_status() -> dict[str, Any]:
    global _status_cache, _status_cache_at
    now = time.monotonic()
    if _status_cache is not None and (now - _status_cache_at) < _STATUS_CACHE_TTL_SECONDS:
        return _status_cache
    result = _codex_cli_status_uncached()
    _status_cache, _status_cache_at = result, now
    return result


def _codex_cli_status_uncached() -> dict[str, Any]:
    executable = settings.CODEX_CLI_PATH
    if not executable or not Path(executable).is_file():
        return {
            "installed": False,
            "logged_in": False,
            "path": "",
            "detail": "Khong tim thay Codex CLI tren may",
        }
    try:
        result = subprocess.run(
            [executable, "login", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            env=_local_codex_environment(),
        )
    except OSError as exc:
        return {
            "installed": False,
            "logged_in": False,
            "path": executable,
            "detail": f"Khong chay duoc Codex CLI: {exc}",
        }
    message = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
    logged_in = result.returncode == 0 and "not logged in" not in message.lower()
    return {
        "installed": True,
        "logged_in": logged_in,
        "path": executable,
        "detail": "Codex CLI da dang nhap" if logged_in else "Codex CLI chua dang nhap",
    }


def launch_codex_login() -> dict[str, Any]:
    """Open the official Codex CLI login in a visible local console."""
    status = codex_cli_status()
    if not status["installed"]:
        raise CodexBridgeError("Khong tim thay Codex CLI tren may")
    if status["logged_in"]:
        return status
    try:
        subprocess.Popen(
            [str(status["path"]), "login"],
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            env=_local_codex_environment(),
        )
    except OSError as exc:
        raise CodexBridgeError(f"Khong mo duoc Codex login: {exc}") from exc
    return {
        **status,
        "detail": "Da mo cua so Codex login; hay hoan tat dang nhap roi quay lai Lam moi.",
    }


def _parse_json_output(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3].rstrip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise CodexBridgeError("Codex khong tra ve JSON hop le") from exc
    if not isinstance(parsed, dict):
        raise CodexBridgeError("Codex phai tra ve mot JSON object")
    return parsed


def call_codex_json(
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    """Run the user's local Codex CLI as a read-only structured-output agent.

    This uses the CLI's existing login rather than an OPENAI_API_KEY. The
    worker is restricted to a read-only sandbox and receives no write task.
    """
    status = codex_cli_status()
    if not status["installed"]:
        raise CodexBridgeError("Khong tim thay Codex CLI; hay cai hoac cau hinh CODEX_CLI_PATH")
    if not status["logged_in"]:
        raise CodexBridgeError("Codex CLI chua dang nhap. Hay chay DANG_NHAP_CODEX.bat mot lan")

    instruction = (
        f"{system_prompt}\n\n"
        "Quy tac bat buoc: chi phan tich noi dung duoc cung cap; khong doc file, khong chay lenh, "
        "khong sua project va khong truy cap mang. Tra ve dung JSON theo schema.\n\n"
        f"Du lieu can xu ly:\n{user_prompt}"
    )
    executable = str(status["path"])
    with tempfile.TemporaryDirectory(prefix="youtube-ai-factory-codex-") as directory:
        workdir = Path(directory)
        schema_path = workdir / "schema.json"
        result_path = workdir / "result.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
        command = [
            executable,
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-user-config",
            "--sandbox",
            "read-only",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(result_path),
            "--color",
            "never",
            "-C",
            str(settings.PROJECT_ROOT),
            "-",
        ]
        try:
            process = operations.run_cancellable(
                command,
                timeout=timeout_seconds,
                cwd=str(settings.PROJECT_ROOT),
                env=_local_codex_environment(),
                input_text=instruction,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CodexBridgeError(f"Khong chay duoc Codex CLI: {exc}") from exc
        if process.returncode != 0:
            detail = (process.stderr or process.stdout or "").strip()[-2000:]
            raise CodexBridgeError(f"Codex CLI that bai: {detail or process.returncode}")
        if not result_path.is_file():
            raise CodexBridgeError("Codex CLI khong tao ket qua cuoi cung")
        return _parse_json_output(result_path.read_text(encoding="utf-8"))


def call_codex_vision_json(
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    image_path: str | Path,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    """Like call_codex_json, but attaches one image via Codex's native `-i/--image`
    flag (verified via `codex exec --help` on this machine) instead of asking the
    model to read a file — so the read-only, no-file-access posture of
    call_codex_json can stay unchanged for its existing callers (writer.py).

    Used by /api/orchestrator/locate-element (web_video_sidecar.py's vision
    fallback): "here is a screenshot, where do I click".
    """
    status = codex_cli_status()
    if not status["installed"]:
        raise CodexBridgeError("Khong tim thay Codex CLI; hay cai hoac cau hinh CODEX_CLI_PATH")
    if not status["logged_in"]:
        raise CodexBridgeError("Codex CLI chua dang nhap. Hay chay DANG_NHAP_CODEX.bat mot lan")

    instruction = (
        f"{system_prompt}\n\n"
        "Quy tac bat buoc: chi phan tich anh da dinh kem va noi dung duoc cung cap; "
        "khong chay lenh, khong sua project va khong truy cap mang. Tra ve dung JSON theo schema.\n\n"
        f"Yeu cau:\n{user_prompt}"
    )
    executable = str(status["path"])
    with tempfile.TemporaryDirectory(prefix="youtube-ai-factory-codex-vision-") as directory:
        workdir = Path(directory)
        schema_path = workdir / "schema.json"
        result_path = workdir / "result.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
        command = [
            executable,
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-user-config",
            "--sandbox",
            "read-only",
            "--image",
            str(Path(image_path).resolve()),
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(result_path),
            "--color",
            "never",
            "-C",
            str(settings.PROJECT_ROOT),
            "-",
        ]
        try:
            process = subprocess.run(
                command,
                input=instruction,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
                env=_local_codex_environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CodexBridgeError(f"Khong chay duoc Codex CLI: {exc}") from exc
        if process.returncode != 0:
            detail = (process.stderr or process.stdout or "").strip()[-2000:]
            raise CodexBridgeError(f"Codex CLI that bai: {detail or process.returncode}")
        if not result_path.is_file():
            raise CodexBridgeError("Codex CLI khong tao ket qua cuoi cung")
        return _parse_json_output(result_path.read_text(encoding="utf-8"))
