from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import settings, usage_limits


class GFlowCliError(RuntimeError):
    def __init__(self, message: str, *, kind: str = "provider", retryable: bool = False, exit_code: int = 1):
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.exit_code = exit_code


_status_cache: dict[str, Any] | None = None
_status_cache_at = 0.0
_STATUS_CACHE_SECONDS = 20.0
_generation_lock = threading.Lock()
_auth_process: subprocess.Popen[str] | None = None


def _command() -> tuple[list[str], dict[str, str]]:
    config = settings.gflow_config()
    executable = str(config.get("path") or "")
    if not executable or not Path(executable).is_file():
        raise GFlowCliError(
            "Chưa cài gflow-cli trong _THU_NGHIEM/gflow-cli hoặc chưa cấu hình GFLOW_CLI_PATH",
            kind="not_installed",
            retryable=False,
        )
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # Google rejects the bundled/headless browser for authenticated Flow.
    env["GFLOW_CLI_HEADLESS"] = "false"
    return [executable], env


def _profile_args() -> list[str]:
    profile = str(settings.gflow_config().get("profile") or "").strip()
    return ["--profile", profile] if profile else []


def gflow_cli_status(*, force: bool = False) -> dict[str, Any]:
    global _status_cache, _status_cache_at
    now = time.monotonic()
    if not force and _status_cache is not None and now - _status_cache_at < _STATUS_CACHE_SECONDS:
        return _status_cache
    config = settings.gflow_config()
    path = str(config.get("path") or "")
    if not path or not Path(path).is_file():
        result = {
            "installed": False,
            "logged_in": False,
            "ready": False,
            "path": "",
            "profile": str(config.get("profile") or "default"),
            "version": "",
            "detail": "Chưa cài gflow-cli",
        }
        _status_cache, _status_cache_at = result, now
        return result
    try:
        version_process = subprocess.run(
            [path, "--version"], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=15, check=False,
        )
        auth_process = subprocess.run(
            [path, "auth", "status", *_profile_args()], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result = {
            "installed": True,
            "logged_in": False,
            "ready": False,
            "path": path,
            "profile": str(config.get("profile") or "default"),
            "version": "",
            "detail": f"Không chạy được gflow-cli: {exc}",
        }
    else:
        version = (version_process.stdout or version_process.stderr or "").strip().splitlines()
        logged_in = auth_process.returncode == 0
        detail_text = (auth_process.stdout or auth_process.stderr or "").strip()
        result = {
            "installed": True,
            "logged_in": logged_in,
            "ready": logged_in,
            "path": path,
            "profile": str(config.get("profile") or "default"),
            "version": version[-1] if version else "",
            "detail": "gflow-cli đã đăng nhập Google Flow" if logged_in else (
                detail_text[-500:] or "gflow-cli chưa đăng nhập; chạy gflow auth login --browser chrome"
            ),
        }
    _status_cache, _status_cache_at = result, now
    return result


def launch_gflow_login() -> dict[str, Any]:
    """Open gflow's passive authentication flow in real Chrome."""
    global _auth_process, _status_cache, _status_cache_at
    current = gflow_cli_status(force=True)
    if current.get("logged_in"):
        return {**current, "started": False, "detail": "Google Flow đã đăng nhập"}
    if _auth_process is not None and _auth_process.poll() is None:
        return {
            **current,
            "started": False,
            "pid": _auth_process.pid,
            "detail": "Cửa sổ đăng nhập Google Flow đang mở trong Chrome",
        }
    base, env = _command()
    env["GFLOW_CLI_AUTH_LOGIN_TIMEOUT"] = os.getenv("GFLOW_CLI_AUTH_LOGIN_TIMEOUT", "1800")
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    _auth_process = subprocess.Popen(
        [*base, "auth", "login", *_profile_args(), "--browser", "chrome"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        text=True, encoding="utf-8", errors="replace",
        creationflags=creation_flags,
    )
    _status_cache = None
    _status_cache_at = 0.0
    return {
        **current,
        "started": True,
        "pid": _auth_process.pid,
        "detail": "Chrome đã mở. Vào được trình biên tập Flow rồi đóng cửa sổ Chrome để hoàn tất.",
    }


def _parse_json_output(stdout: str) -> dict[str, Any]:
    cleaned = stdout.strip()
    if not cleaned:
        raise GFlowCliError("gflow-cli không trả về JSON", kind="invalid_output", retryable=False)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        # Be defensive around wrappers that accidentally prefix one log line.
        parsed = None
        for line in reversed(cleaned.splitlines()):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                parsed = candidate
                break
        if parsed is None:
            raise GFlowCliError(
                f"gflow-cli trả về dữ liệu không hợp lệ: {cleaned[-800:]}",
                kind="invalid_output",
                retryable=False,
            ) from exc
    if not isinstance(parsed, dict):
        raise GFlowCliError("gflow-cli phải trả về một JSON object", kind="invalid_output")
    return parsed


def _classify_failure(exit_code: int, payload: dict[str, Any], stderr: str) -> GFlowCliError:
    detail = str(
        payload.get("detail") or payload.get("error_message") or payload.get("title")
        or payload.get("failure_reasons") or stderr or f"gflow-cli thoát mã {exit_code}"
    ).strip()
    normalized = detail.lower()
    retryable = bool(payload.get("retryable")) or exit_code in {4, 6}
    if exit_code == 3 or any(key in normalized for key in ("auth", "login", "cookie expired")):
        kind = "auth"
        retryable = False
    elif exit_code == 23 or "selector" in normalized or "ui drift" in normalized:
        kind = "selector_drift"
    elif any(key in normalized for key in ("quota", "credit", "tín dụng", "insufficient")):
        kind = "quota"
        usage_limits.note_failure("gflow_cli", detail or normalized)
        retryable = False
    elif exit_code in {9, 27} or "initial frame" in normalized or "upload" in normalized:
        kind = "input"
        retryable = False
    elif "timeout" in normalized or "timed out" in normalized:
        kind = "timeout"
        retryable = True
    else:
        kind = "provider"
    return GFlowCliError(detail[-2000:], kind=kind, retryable=retryable, exit_code=exit_code)


def run_gflow_json(
    args: list[str],
    *,
    timeout_seconds: int,
    heartbeat: Callable[[], None] | None = None,
    heartbeat_seconds: float = 10.0,
) -> dict[str, Any]:
    base, env = _command()
    command = [*base, *args]
    with _generation_lock, tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stdout_file, tempfile.TemporaryFile(
        mode="w+", encoding="utf-8"
    ) as stderr_file:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                command,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=creation_flags,
            )
        except OSError as exc:
            raise GFlowCliError(f"Không khởi động được gflow-cli: {exc}", kind="not_installed") from exc
        deadline = time.monotonic() + max(30, timeout_seconds)
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise GFlowCliError(
                    "gflow-cli tạo video quá thời gian cho phép",
                    kind="timeout",
                    retryable=True,
                )
            try:
                process.wait(timeout=min(max(1.0, heartbeat_seconds), remaining))
            except subprocess.TimeoutExpired:
                if heartbeat:
                    heartbeat()
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read()
        stderr = stderr_file.read()
    payload: dict[str, Any] = {}
    if stdout.strip():
        try:
            payload = _parse_json_output(stdout)
        except GFlowCliError:
            if process.returncode == 0:
                raise
    if process.returncode != 0:
        raise _classify_failure(int(process.returncode or 1), payload, stderr)
    if not payload:
        raise GFlowCliError(
            f"gflow-cli hoàn tất nhưng không có kết quả JSON: {stderr[-800:]}",
            kind="invalid_output",
        )
    return payload


def create_gflow_project(
    title: str,
    *,
    heartbeat: Callable[[], None] | None = None,
) -> str:
    """Create one durable Flow project and return its cloud project id."""
    safe_title = " ".join(title.split()).strip()[:120] or "YouTube AI Factory"
    result = run_gflow_json(
        ["project", "create", "--name", safe_title, "--json", *_profile_args()],
        timeout_seconds=180,
        heartbeat=heartbeat,
    )
    project_id = str(result.get("project_id") or "").strip()
    if not project_id:
        raise GFlowCliError(
            "Flow đã tạo project nhưng không trả về project_id",
            kind="invalid_output",
        )
    return project_id


def generate_gflow_image(
    job: dict[str, Any],
    reference_path: Path | None,
    output_path: Path,
    *,
    gflow_project_id: str = "",
    heartbeat: Callable[[], None] | None = None,
) -> str:
    """Draw one still through the signed-in Flow profile instead of a browser.

    Flow's Imagen still generates while its video side is out of credit, and
    the CLI reaches it without the extension - no tab to keep open, no page
    layout to break. With a reference image it runs ``image i2i``, which is
    what lets a GIF's later frames inherit the earlier one instead of each
    frame being drawn from scratch.
    """
    prompt = str(job.get("prompt") or "").strip()
    if not prompt:
        raise GFlowCliError("Prompt tạo ảnh đang trống", kind="input")
    aspect = {
        "1280:720": "16:9",
        "720:1280": "9:16",
        "1024:1024": "1:1",
    }.get(str(job.get("ratio") or ""), "16:9")
    args = ["image", "i2i" if reference_path is not None else "t2i", prompt]
    if reference_path is not None:
        if not reference_path.is_file():
            raise GFlowCliError("Ảnh tham chiếu không còn tồn tại trên máy", kind="input")
        args.extend(["--ref", str(reference_path)])
    args.extend(["--aspect", aspect, "-o", str(output_path), "--json"])
    model = str(settings.gflow_config().get("image_model") or "").strip()
    if model:
        args.extend(["--model", model])
    if gflow_project_id.strip():
        args.extend(["--project", gflow_project_id.strip()])
    args.extend(_profile_args())
    result = run_gflow_json(
        args,
        timeout_seconds=max(60, int(os.getenv("GFLOW_IMAGE_TIMEOUT_SECONDS", "600"))),
        heartbeat=heartbeat,
    )
    if result.get("succeeded") is False or str(result.get("status") or "").lower() in {"failed", "error"}:
        raise _classify_failure(1, result, "")
    result_path = Path(str(result.get("local_path") or output_path))
    if not result_path.is_file() or result_path.stat().st_size == 0:
        raise GFlowCliError("Flow báo thành công nhưng không tìm thấy ảnh đã tải", kind="download", retryable=True)
    return str(result_path)


def generate_gflow_video(
    job: dict[str, Any],
    reference_path: Path | None,
    output_path: Path,
    *,
    gflow_project_id: str = "",
    heartbeat: Callable[[], None] | None = None,
) -> str:
    prompt = str(job.get("prompt") or "").strip()
    if not prompt:
        raise GFlowCliError("Prompt tạo video đang trống", kind="input")
    if bool(job.get("requires_reference_image")) and reference_path is None:
        raise GFlowCliError("Job I2V bắt buộc có ảnh nguồn", kind="input")
    aspect = {
        "1280:720": "16:9",
        "720:1280": "9:16",
    }.get(str(job.get("ratio") or ""), "16:9")
    mode = "i2v" if reference_path is not None else "t2v"
    args = ["video", mode]
    if reference_path is not None:
        args.extend(["--initial-frame", str(reference_path)])
    args.extend([prompt, "--aspect", aspect, "-o", str(output_path), "--json"])
    model = str(settings.gflow_config().get("video_model") or "").strip()
    if model:
        args.extend(["--model", model])
        # gflow 0.59 only exposes duration control for omni-flash.
        if model == "omni-flash":
            requested = max(1, min(int(job.get("duration_seconds") or 8), 10))
            duration = min((4, 6, 8, 10), key=lambda value: (abs(value - requested), -value))
            args.extend(["--duration", str(duration)])
    if gflow_project_id.strip():
        args.extend(["--project", gflow_project_id.strip()])
    args.extend(_profile_args())
    result = run_gflow_json(
        args,
        timeout_seconds=max(60, int(os.getenv("GFLOW_GENERATION_TIMEOUT_SECONDS", "1800"))),
        heartbeat=heartbeat,
    )
    if result.get("succeeded") is False or str(result.get("status") or "").lower() in {"failed", "error"}:
        raise _classify_failure(1, result, "")
    result_path = Path(str(result.get("local_path") or output_path))
    if not result_path.is_file() or result_path.stat().st_size == 0:
        raise GFlowCliError("Flow báo thành công nhưng không tìm thấy MP4 đã tải", kind="download", retryable=True)
    return str(result_path)
