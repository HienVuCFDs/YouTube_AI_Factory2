from __future__ import annotations

import base64
import json
import mimetypes
import random
import time
from pathlib import Path
from queue import Queue
from threading import Event, Lock, Thread
from typing import Any

import httpx

from . import settings
from .database import Database
from .project_layout import ensure_project_layout


class SceneGenerationError(RuntimeError):
    pass


def _error_detail(response: httpx.Response) -> str:
    try:
        response.read()
        payload = response.json()
        if isinstance(payload, dict):
            return str(payload.get("error") or payload.get("message") or payload)
    except ValueError:
        pass
    return response.text.strip()[-1000:] or f"HTTP {response.status_code}"


def _cloud_generation_error(response: httpx.Response, service: str) -> str:
    """Turn provider quota payloads into an actionable Vietnamese error.

    Gemini returns a multi-page JSON quota diagnostic for image/video models.
    Showing it verbatim in a storyboard card hides the actual remedy: the key
    is valid, but the Google project must be on a paid billing tier.
    """
    detail = _error_detail(response)
    normalized = detail.lower()
    if response.status_code == 429 and ("quota" in normalized or "resource_exhausted" in normalized):
        return (
            f"{service} đã nhận API key nhưng quota tạo ảnh/video của project đang là 0. "
            "Các model Gemini Image và Veo cần liên kết Billing trong Google AI Studio; "
            "sau khi bật billing hãy tạo lại các cảnh lỗi."
        )
    return f"{service} không tạo được cảnh: {detail}"


def _image_data_uri(path: Path, mime_type: str = "") -> str:
    if not path.is_file():
        raise SceneGenerationError("Khong tim thay anh tham chieu local")
    if path.stat().st_size > 15 * 1024 * 1024:
        raise SceneGenerationError("Anh tham chieu vuot qua 15 MB; hay nen anh truoc khi tao canh AI")
    content_type = mime_type or mimetypes.guess_type(path.name)[0] or "image/png"
    if not content_type.startswith("image/"):
        raise SceneGenerationError("Runway image-to-video chi nhan anh tham chieu")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def generate_runway_scene(
    database: Database,
    job: dict[str, Any],
    artifact_root: Path,
    poll_interval_seconds: float = 5.0,
    timeout_seconds: int = 20 * 60,
) -> str:
    """Create, poll and download one Runway generation into the local project.

    The API key stays on the local server. The public, short-lived Runway output
    URL is immediately copied into the project's artifacts directory.
    """
    api_key, model = settings.runway_config()
    if not api_key:
        raise SceneGenerationError("Chua cau hinh RUNWAYML_API_SECRET trong Ket noi AI")

    payload: dict[str, Any] = {
        "model": model,
        "promptText": str(job.get("prompt") or "").strip(),
        "ratio": str(job.get("ratio") or "1280:720"),
        "duration": int(job.get("duration_seconds") or 5),
    }
    if not payload["promptText"]:
        raise SceneGenerationError("Prompt tao canh AI dang trong")

    reference_asset_id = job.get("reference_asset_id")
    if reference_asset_id:
        asset = database.get_project_asset(int(reference_asset_id))
        if not asset:
            raise SceneGenerationError("Khong tim thay asset tham chieu")
        payload["promptImage"] = _image_data_uri(
            Path(str(asset["file_path"])), str(asset.get("mime_type") or "")
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Runway-Version": "2024-11-06",
    }
    timeout = httpx.Timeout(60.0, connect=20.0)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.post("https://api.dev.runwayml.com/v1/image_to_video", headers=headers, json=payload)
        if response.status_code >= 400:
            raise SceneGenerationError(f"Runway khong tao duoc task: {_error_detail(response)}")
        try:
            task_id = str(response.json()["id"])
        except (ValueError, KeyError, TypeError) as exc:
            raise SceneGenerationError("Runway tra ve task khong hop le") from exc
        database.update_scene_generation_task(int(job["id"]), task_id)

        deadline = time.monotonic() + timeout_seconds
        task: dict[str, Any] = {}
        while time.monotonic() < deadline:
            time.sleep(poll_interval_seconds + random.uniform(0, 0.4))
            task_response = client.get(
                f"https://api.dev.runwayml.com/v1/tasks/{task_id}", headers=headers
            )
            if task_response.status_code >= 400:
                raise SceneGenerationError(f"Khong doc duoc trang thai Runway: {_error_detail(task_response)}")
            try:
                task = task_response.json()
            except ValueError as exc:
                raise SceneGenerationError("Runway tra ve trang thai task khong hop le") from exc
            status = str(task.get("status") or "").upper()
            if status == "SUCCEEDED":
                break
            if status in {"FAILED", "CANCELED"}:
                raise SceneGenerationError(str(task.get("failure") or task.get("error") or f"Runway task {status}"))
        else:
            raise SceneGenerationError("Runway tao canh qua lau; task van co the tiep tuc tren Runway")

        output_urls = task.get("output") or []
        if not isinstance(output_urls, list) or not output_urls or not isinstance(output_urls[0], str):
            raise SceneGenerationError("Runway task thanh cong nhung khong co URL video")
        output_url = output_urls[0]
        output_dir = ensure_project_layout(artifact_root, job["project_id"])["assets"] / "generated_scenes"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"runway-segment-{int(job['timeline_segment_id'])}-job-{int(job['id'])}.mp4"
        with client.stream("GET", output_url, timeout=httpx.Timeout(180.0, connect=20.0)) as download:
            if download.status_code >= 400:
                raise SceneGenerationError(f"Khong tai duoc video Runway: {_error_detail(download)}")
            with output_path.open("wb") as handle:
                for chunk in download.iter_bytes():
                    handle.write(chunk)
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise SceneGenerationError("Video Runway tai ve trong")
    return str(output_path)


def _openai_image_size(ratio: str) -> str:
    """Choose a supported GPT Image size that is closest to the scene ratio."""
    return {
        "1280:720": "1536x1024",
        "720:1280": "1024x1536",
        "1024:1024": "1024x1024",
    }.get(str(ratio or ""), "1536x1024")


def generate_openai_image_scene(
    database: Database,
    job: dict[str, Any],
    artifact_root: Path,
) -> str:
    """Generate one still visual with GPT Image for the local FFmpeg storyteller.

    The renderer recognises image files and turns each one into a timed,
    gently moving shot.  This is deliberately a separate provider from Runway:
    it requires only the existing OPENAI_API_KEY and does not make a video API
    call for every scene.
    """
    api_key, _ = settings.openai_config()
    if not api_key:
        raise SceneGenerationError("Chua cau hinh OPENAI_API_KEY trong Ket noi AI")
    prompt = str(job.get("prompt") or "").strip()
    if not prompt:
        raise SceneGenerationError("Prompt tao anh canh dang trong")

    # Keep generated story frames usable as visuals and prevent accidental
    # title-card-like output which was the main failure of the old draft path.
    enriched_prompt = (
        "Create one cinematic storytelling frame for a narrated video. "
        "No captions, no typography, no logos, no watermark. "
        "Keep the main character and visual style consistent with the other story scenes. "
        + prompt
    )
    payload = {
        "model": "gpt-image-1",
        "prompt": enriched_prompt[:30_000],
        "size": _openai_image_size(str(job.get("ratio") or "")),
        "quality": "medium",
        "output_format": "png",
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=20.0), follow_redirects=True) as client:
        response = client.post("https://api.openai.com/v1/images/generations", headers=headers, json=payload)
        if response.status_code >= 400:
            raise SceneGenerationError(f"OpenAI khong tao duoc anh canh: {_error_detail(response)}")
        try:
            data = response.json().get("data") or []
            image_data = data[0].get("b64_json") if data else None
        except (ValueError, AttributeError, IndexError, TypeError) as exc:
            raise SceneGenerationError("OpenAI tra ve ket qua anh khong hop le") from exc
        if not isinstance(image_data, str) or not image_data:
            raise SceneGenerationError("OpenAI khong tra ve du lieu anh cho canh nay")
        try:
            content = base64.b64decode(image_data)
        except (ValueError, TypeError) as exc:
            raise SceneGenerationError("Du lieu anh OpenAI khong hop le") from exc

    output_dir = ensure_project_layout(artifact_root, job["project_id"])["assets"] / "generated_images"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"openai-image-segment-{int(job['timeline_segment_id'])}-job-{int(job['id'])}.png"
    output_path.write_bytes(content)
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise SceneGenerationError("Anh OpenAI tai ve trong")
    return str(output_path)


def _gemini_aspect_ratio(ratio: str) -> str:
    return {"1280:720": "16:9", "720:1280": "9:16", "1024:1024": "1:1"}.get(str(ratio or ""), "16:9")


def generate_gemini_image_scene(database: Database, job: dict[str, Any], artifact_root: Path) -> str:
    """Generate one scene image through Google Gemini's native image API."""
    api_key, model, _ = settings.gemini_config()
    if not api_key:
        raise SceneGenerationError("Chua cau hinh GEMINI_API_KEY trong Ket noi AI")
    prompt = str(job.get("prompt") or "").strip()
    if not prompt:
        raise SceneGenerationError("Prompt tao anh canh dang trong")
    payload = {
        "contents": [{"parts": [{"text": "Create a cinematic storytelling frame. No captions, no typography, no logos, no watermark. " + prompt[:30_000]}]}],
        "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": _gemini_aspect_ratio(str(job.get("ratio") or "")), "imageSize": "1K"}},
    }
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=20.0), follow_redirects=True) as client:
        response = client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise SceneGenerationError(_cloud_generation_error(response, "Google Gemini"))
        try:
            parts = response.json()["candidates"][0]["content"]["parts"]
            image = next(part["inlineData"] for part in parts if isinstance(part, dict) and part.get("inlineData"))
            content = base64.b64decode(image["data"])
            mime_type = str(image.get("mimeType") or "image/png")
        except (ValueError, KeyError, IndexError, StopIteration, TypeError) as exc:
            raise SceneGenerationError("Gemini tra ve ket qua anh khong hop le") from exc
    suffix = ".jpg" if mime_type == "image/jpeg" else ".png"
    output_dir = ensure_project_layout(artifact_root, job["project_id"])["assets"] / "generated_images"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"gemini-image-segment-{int(job['timeline_segment_id'])}-job-{int(job['id'])}{suffix}"
    output_path.write_bytes(content)
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise SceneGenerationError("Anh Gemini tai ve trong")
    return str(output_path)


def generate_gemini_veo_scene(database: Database, job: dict[str, Any], artifact_root: Path, poll_interval_seconds: float = 10.0, timeout_seconds: int = 30 * 60) -> str:
    """Generate and download a real Veo scene video through Gemini's LRO API."""
    api_key, _, model = settings.gemini_config()
    if not api_key:
        raise SceneGenerationError("Chua cau hinh GEMINI_API_KEY trong Ket noi AI")
    prompt = str(job.get("prompt") or "").strip()
    if not prompt:
        raise SceneGenerationError("Prompt tao video canh dang trong")
    payload = {"instances": [{"prompt": prompt}], "parameters": {"aspectRatio": _gemini_aspect_ratio(str(job.get("ratio") or "")), "durationSeconds": 8}}
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    base_url = "https://generativelanguage.googleapis.com/v1beta"
    with httpx.Client(timeout=httpx.Timeout(90.0, connect=20.0), follow_redirects=True) as client:
        response = client.post(f"{base_url}/models/{model}:predictLongRunning", headers=headers, json=payload)
        if response.status_code >= 400:
            raise SceneGenerationError(_cloud_generation_error(response, "Google Veo"))
        try:
            operation_name = str(response.json()["name"])
        except (ValueError, KeyError, TypeError) as exc:
            raise SceneGenerationError("Veo tra ve task khong hop le") from exc
        database.update_scene_generation_task(int(job["id"]), operation_name)
        deadline = time.monotonic() + timeout_seconds
        operation: dict[str, Any] = {}
        while time.monotonic() < deadline:
            time.sleep(poll_interval_seconds + random.uniform(0, 0.4))
            status = client.get(f"{base_url}/{operation_name}", headers=headers)
            if status.status_code >= 400:
                raise SceneGenerationError(f"Khong doc duoc trang thai Veo: {_error_detail(status)}")
            operation = status.json()
            if operation.get("done"):
                break
        else:
            raise SceneGenerationError("Veo tao canh qua lau; task van co the tiep tuc tren Google")
        if operation.get("error"):
            raise SceneGenerationError(str(operation["error"].get("message") or operation["error"]))
        try:
            video_url = operation["response"]["generateVideoResponse"]["generatedSamples"][0]["video"]["uri"]
        except (KeyError, IndexError, TypeError) as exc:
            raise SceneGenerationError("Veo hoan tat nhung khong tra ve video") from exc
        output_dir = ensure_project_layout(artifact_root, job["project_id"])["assets"] / "generated_scenes"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"gemini-veo-segment-{int(job['timeline_segment_id'])}-job-{int(job['id'])}.mp4"
        with client.stream("GET", video_url, headers=headers, timeout=httpx.Timeout(300.0, connect=20.0)) as download:
            if download.status_code >= 400:
                raise SceneGenerationError(f"Khong tai duoc video Veo: {_error_detail(download)}")
            with output_path.open("wb") as handle:
                for chunk in download.iter_bytes():
                    handle.write(chunk)
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise SceneGenerationError("Video Veo tai ve trong")
    return str(output_path)


class SceneGenerationWorker:
    """Persistent local worker for paid cloud scene-generation jobs."""

    def __init__(self, database: Database, artifact_root: Path):
        self.database = database
        self.artifact_root = Path(artifact_root)
        self._jobs: Queue[int | None] = Queue()
        self._stop = Event()
        self._lock = Lock()
        self._paused = False
        self._thread: Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._paused = False
            self.database.requeue_interrupted_scene_generation_jobs()
            for job_id in self.database.list_queued_scene_generation_job_ids():
                self._jobs.put(job_id)
            self._thread = Thread(target=self._run, name="scene-generation-worker", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._jobs.put(None)
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
        self._thread = None

    def enqueue(self, job_id: int) -> None:
        self._jobs.put(job_id)

    def set_paused(self, paused: bool) -> dict[str, Any]:
        with self._lock:
            self._paused = paused
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            paused = self._paused
        return {
            **self.database.scene_generation_queue_status(),
            "paused": paused,
            "worker_running": bool(self._thread and self._thread.is_alive()),
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            job_id = self._jobs.get()
            if job_id is None:
                return
            while True:
                with self._lock:
                    paused = self._paused
                if not paused or self._stop.wait(0.25):
                    break
            if self._stop.is_set():
                return
            self._process(job_id)

    def _process(self, job_id: int) -> None:
        job = self.database.claim_scene_generation_job(job_id)
        if not job:
            return
        try:
            provider = str(job.get("provider") or "").strip().lower()
            if provider == "runway":
                output_path = generate_runway_scene(self.database, job, self.artifact_root)
            elif provider == "openai_image":
                output_path = generate_openai_image_scene(self.database, job, self.artifact_root)
            elif provider == "gemini_image":
                output_path = generate_gemini_image_scene(self.database, job, self.artifact_root)
            elif provider == "gemini_veo":
                output_path = generate_gemini_veo_scene(self.database, job, self.artifact_root)
            else:
                raise SceneGenerationError(f"Scene provider chua duoc ho tro: {provider}")
            self.database.finish_scene_generation_job(job_id, "completed", output_path=output_path)
        except Exception as exc:
            self.database.finish_scene_generation_job(job_id, "error", error=str(exc))
