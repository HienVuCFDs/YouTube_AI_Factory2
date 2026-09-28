"""Local HTTP adapter for Phantom Canvas' persistent Gemini-Web service.

The service owns Chrome and its cookies.  Factory only submits a scene and
downloads the completed local result, so restarting the Factory never loses a
web login or leaves an automation browser attached to an application request.
"""
from __future__ import annotations

import mimetypes
import shutil
import subprocess
import os
import time
from pathlib import Path
from typing import Any

import httpx

from . import settings
from .project_layout import ensure_project_layout


class PhantomCanvasError(RuntimeError):
    pass


def base_url() -> str:
    return settings.integration_value("PHANTOM_CANVAS_URL", "http://127.0.0.1:8420").rstrip("/")


def status() -> dict[str, Any]:
    installed = bool(shutil.which("phantom-canvas.cmd" if os.name == "nt" else "phantom-canvas"))
    if not installed:
        return {"ready": False, "installed": False, "detail": "Chưa cài Phantom Canvas trên máy.", "health": {}}
    try:
        response = httpx.get(f"{base_url()}/health", timeout=2.5)
        response.raise_for_status()
        payload = response.json() if response.content else {}
        return {"ready": True, "installed": True, "detail": "Phantom Canvas đang chạy. Mở Gemini để đăng nhập nếu đây là lần đầu; phiên sẽ được lưu trong profile riêng.", "health": payload}
    except (httpx.HTTPError, ValueError) as exc:
        return {"ready": False, "installed": True, "detail": f"Đã cài nhưng service chưa chạy tại {base_url()}.", "health": {}}


def _detached(command: list[str]) -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    if os.name == "nt":
        executable = shutil.which("phantom-canvas.cmd")
        if not executable:
            raise PhantomCanvasError("Không tìm thấy lệnh phantom-canvas.cmd sau khi cài đặt")
        command = [executable, *command[1:]]
    env = os.environ.copy()
    # Phantom Canvas 2.0 resolves `chrome.exe` from PATH on Windows rather
    # than the normal Program Files location.  Preserve the user's PATH and
    # add Chrome only for this child process.
    for chrome in (Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application",
                   Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Google/Chrome/Application"):
        if (chrome / "chrome.exe").is_file():
            env["PATH"] = f"{chrome}{os.pathsep}{env.get('PATH', '')}"
            break
    # Keep a small local startup log.  A web session can fail before its HTTP
    # port opens; discarding stderr made that indistinguishable from a missing
    # service in the Factory UI.
    log_path = settings.DATA_DIR / "phantom_canvas.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_file:
        subprocess.Popen(
            command,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=flags,
            env=env,
        )


def start_service() -> dict[str, Any]:
    current = status()
    if current["ready"]:
        return current
    if not current.get("installed"):
        raise PhantomCanvasError("Chưa cài Phantom Canvas. Hãy cài lại từ Cài đặt.")
    _detached(["phantom-canvas", "serve"])
    return {"ready": False, "installed": True, "detail": "Đã khởi động service. Đợi vài giây rồi bấm kiểm tra lại.", "health": {}}


def open_login() -> dict[str, Any]:
    current = status()
    if not current.get("installed"):
        raise PhantomCanvasError("Chưa cài Phantom Canvas trên máy.")
    # This launches only the service-owned persistent Chrome profile.  It is
    # deliberately a user action; Factory never opens a Google login itself.
    _detached(["phantom-canvas", "chrome"])
    return {"detail": "Đã mở Chrome profile của Phantom Canvas. Đăng nhập Gemini một lần, rồi quay lại app và bấm kiểm tra."}


def generate_scene(database: Any, job: dict[str, Any], artifact_root: Path) -> str:
    prompt = str(job.get("prompt") or "").strip()
    if not prompt:
        raise PhantomCanvasError("Prompt tạo cảnh đang trống")
    kind = "video" if str(job.get("job_kind") or "") == "video" else "image"
    timeout_seconds = 420 if kind == "video" else 240
    reference_images: list[str] = []
    reference_id = job.get("reference_asset_id")
    if reference_id:
        asset = database.get_project_asset(int(reference_id))
        path = Path(str((asset or {}).get("file_path") or ""))
        if path.is_file() and (mimetypes.guess_type(path.name)[0] or "").startswith("image/"):
            reference_images.append(str(path))
    payload: dict[str, Any] = {"prompt": prompt[:30_000], "type": kind, "timeout_secs": timeout_seconds}
    if reference_images:
        payload["reference_images"] = reference_images
    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0), follow_redirects=True) as client:
            response = client.post(f"{base_url()}/generate", json=payload)
            response.raise_for_status()
            task_id = str(response.json().get("task_id") or "")
            if not task_id:
                raise PhantomCanvasError("Phantom Canvas không trả về mã tác vụ")
            database.update_scene_generation_task(int(job["id"]), task_id)
            deadline = time.monotonic() + timeout_seconds + 30
            task: dict[str, Any] = {}
            while time.monotonic() < deadline:
                time.sleep(3)
                database.touch_scene_generation_job(int(job["id"]), "phantom_canvas_poll")
                task_response = client.get(f"{base_url()}/task/{task_id}")
                task_response.raise_for_status()
                task = task_response.json()
                state = str(task.get("status") or "").lower()
                if state == "completed":
                    break
                if state in {"failed", "error", "cancelled"}:
                    raise PhantomCanvasError(str(task.get("error") or "Gemini Web từ chối hoặc thất bại"))
            else:
                raise PhantomCanvasError("Phantom Canvas quá thời gian chờ tạo cảnh")
            outputs = task.get("images") or task.get("outputs") or []
            item = outputs[0] if outputs else {}
            relative_url = str((item or {}).get("url") or "")
            if not relative_url:
                raise PhantomCanvasError("Tác vụ hoàn tất nhưng không có file kết quả")
            file_response = client.get(relative_url if relative_url.startswith("http") else f"{base_url()}{relative_url}")
            file_response.raise_for_status()
            content = file_response.content
            mime = file_response.headers.get("content-type", "").split(";", 1)[0]
    except httpx.HTTPError as exc:
        raise PhantomCanvasError(f"Không gọi được Phantom Canvas: {exc}") from exc
    if not content:
        raise PhantomCanvasError("Phantom Canvas trả về file rỗng")
    suffix = ".mp4" if kind == "video" else (".jpg" if mime == "image/jpeg" else ".png")
    folder_name = "generated_videos" if kind == "video" else "generated_images"
    output_dir = ensure_project_layout(artifact_root, int(job["project_id"]))["assets"] / folder_name
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"phantom-canvas-{kind}-segment-{int(job['timeline_segment_id'])}-job-{int(job['id'])}{suffix}"
    output.write_bytes(content)
    return str(output)
