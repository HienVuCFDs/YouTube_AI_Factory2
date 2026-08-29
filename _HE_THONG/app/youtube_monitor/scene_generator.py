from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import random
import time
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Any, Callable

import httpx

from . import settings, usage_limits
from .database import Database
from .gif_generator import (
    GFLOW_GIF_FRAME_COUNT,
    create_gif_from_frames,
    materialize_gif_asset,
)
from .gflow_bridge import (
    GFlowCliError,
    create_gflow_project,
    generate_gflow_image,
    generate_gflow_video,
)
from .project_layout import ensure_project_layout
from .providers import (
    EXECUTION_EXTERNAL_SIDECAR,
    SCENE_ANIMATED_IMAGE,
    SCENE_IMAGE,
    SCENE_VIDEO,
    FunctionSceneProviderAdapter,
    ProviderDescriptor,
    ProviderGateway,
    SidecarSceneProviderAdapter,
)


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
            database.touch_scene_generation_job(int(job["id"]), "provider_poll")
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
    instance: dict[str, Any] = {"prompt": prompt}
    reference_asset_id = job.get("reference_asset_id")
    if reference_asset_id:
        # Image-to-video: reuse the scene's existing still as Veo's starting
        # frame instead of generating a fresh clip from text alone, per
        # Google's documented Veo image field (bytesBase64Encoded + mimeType).
        asset = database.get_project_asset(int(reference_asset_id))
        if not asset:
            raise SceneGenerationError("Khong tim thay anh tham chieu")
        image_path = Path(str(asset["file_path"]))
        if not image_path.is_file():
            raise SceneGenerationError("Anh tham chieu khong ton tai tren dia")
        mime_type = str(asset.get("mime_type") or mimetypes.guess_type(image_path.name)[0] or "image/png")
        if not mime_type.startswith("image/"):
            raise SceneGenerationError("Chi ho tro anh lam khung hinh dau cho Veo (image-to-video)")
        instance["image"] = {
            "bytesBase64Encoded": base64.b64encode(image_path.read_bytes()).decode("ascii"),
            "mimeType": mime_type,
        }
    payload = {"instances": [instance], "parameters": {"aspectRatio": _gemini_aspect_ratio(str(job.get("ratio") or "")), "durationSeconds": 8}}
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
            database.touch_scene_generation_job(int(job["id"]), "provider_poll")
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


def generate_gflow_cli_scene(database: Database, job: dict[str, Any], artifact_root: Path) -> str:
    """Generate one Flow/Veo clip through the user's logged-in gflow profile."""
    project = database.get_production_project(int(job["project_id"]))
    if not project:
        raise GFlowCliError("Không tìm thấy production project", kind="input")
    profile = str(settings.gflow_config().get("profile") or "default")
    gflow_project_id = str(project.get("gflow_project_id") or "").strip()
    if not gflow_project_id or str(project.get("gflow_profile") or "") != profile:
        gflow_project_id = create_gflow_project(
            f"YTAF {int(project['id'])} - {project.get('title') or project.get('source_title') or 'Video'}",
            heartbeat=lambda: database.touch_scene_generation_job(int(job["id"]), "gflow_project_create"),
        )
        database.update_production_project_gflow(int(project["id"]), gflow_project_id, profile)
    reference_path: Path | None = None
    reference_asset_id = job.get("reference_asset_id")
    if reference_asset_id:
        asset = database.get_project_asset(int(reference_asset_id))
        if not asset:
            raise GFlowCliError("Không tìm thấy ảnh nguồn trong project", kind="input")
        reference_path = Path(str(asset.get("file_path") or ""))
        mime_type = str(asset.get("mime_type") or mimetypes.guess_type(reference_path.name)[0] or "")
        if not reference_path.is_file():
            raise GFlowCliError("Ảnh nguồn không còn tồn tại trên máy", kind="input")
        if not mime_type.startswith("image/"):
            raise GFlowCliError("gflow I2V chỉ nhận ảnh làm khung hình đầu", kind="input")
    output_dir = ensure_project_layout(artifact_root, job["project_id"])["assets"] / "generated_scenes"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / (
        f"gflow-segment-{int(job['timeline_segment_id'])}-job-{int(job['id'])}.mp4"
    )
    return generate_gflow_video(
        job,
        reference_path,
        output_path,
        gflow_project_id=gflow_project_id,
        heartbeat=lambda: database.touch_scene_generation_job(int(job["id"]), "gflow_rendering"),
    )


def _gflow_frame_prompts(job: dict[str, Any]) -> list[str]:
    """Read the per-frame prompts main.py wrote for a chained GIF job."""
    raw = str(job.get("prompt") or "").strip()
    if not raw:
        raise GFlowCliError("Prompt tao GIF dang trong", kind="input")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        payload = None
    frames = payload.get("frames") if isinstance(payload, dict) else None
    if isinstance(frames, list):
        cleaned = [str(item).strip() for item in frames if str(item).strip()]
        if len(cleaned) >= 2:
            return cleaned
    # The orchestrator was unreachable when the prompt was written, so the job
    # carries one plain description. Rather than fail, ask for the same shot
    # advanced a step at a time — weaker than authored steps, but still motion.
    return [
        raw if index == 0 else
        f"Same shot, same characters, same style as the reference image. "
        f"Advance the motion to stage {index + 1} of {GFLOW_GIF_FRAME_COUNT}: {raw}"
        for index in range(GFLOW_GIF_FRAME_COUNT)
    ]


def generate_gflow_image_scene(database: Database, job: dict[str, Any], artifact_root: Path) -> str:
    """Draw a scene's still — or the frames of its loop — through Flow's CLI.

    Flow's image side still works while its video side is out of credit, and
    it needs no browser tab held open. For a GIF the frames are drawn one
    after another, each passed the previous frame as reference, which is what
    keeps the subject of the scene moving instead of only the background.
    """
    project = database.get_production_project(int(job["project_id"]))
    if not project:
        raise GFlowCliError("Không tìm thấy production project", kind="input")
    profile = str(settings.gflow_config().get("profile") or "default")
    gflow_project_id = str(project.get("gflow_project_id") or "").strip()
    if not gflow_project_id or str(project.get("gflow_profile") or "") != profile:
        gflow_project_id = create_gflow_project(
            f"YTAF {int(project['id'])} - {project.get('title') or project.get('source_title') or 'Video'}",
            heartbeat=lambda: database.touch_scene_generation_job(int(job["id"]), "gflow_project_create"),
        )
        database.update_production_project_gflow(int(project["id"]), gflow_project_id, profile)
    reference_path: Path | None = None
    reference_asset_id = job.get("reference_asset_id")
    if reference_asset_id:
        asset = database.get_project_asset(int(reference_asset_id))
        if asset:
            candidate = Path(str(asset.get("file_path") or ""))
            if candidate.is_file():
                reference_path = candidate
    output_dir = ensure_project_layout(artifact_root, job["project_id"])["assets"] / "generated_scenes"
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"gflow-image-segment-{int(job['timeline_segment_id'])}-job-{int(job['id'])}"

    def beat(stage: str) -> Callable[[], None]:
        return lambda: database.touch_scene_generation_job(int(job["id"]), stage)

    if str(job.get("job_kind") or "") != "gif":
        return generate_gflow_image(
            job,
            reference_path,
            output_dir / f"{stem}.png",
            gflow_project_id=gflow_project_id,
            heartbeat=beat("gflow_image"),
        )
    prompts = _gflow_frame_prompts(job)
    frames: list[Path] = []
    previous = reference_path
    for index, frame_prompt in enumerate(prompts):
        drawn = generate_gflow_image(
            {**job, "prompt": frame_prompt},
            previous,
            output_dir / f"{stem}-frame{index + 1}.png",
            gflow_project_id=gflow_project_id,
            heartbeat=beat(f"gflow_gif_frame_{index + 1}"),
        )
        frames.append(Path(drawn))
        previous = frames[-1]
    return create_gif_from_frames(
        list(frames),
        output_dir / f"{stem}.gif",
        duration_seconds=float(job.get("duration_seconds") or 5),
        fps=int(job.get("visual_fps") or job.get("gif_fps") or 8),
        ffmpeg_binary=settings.FFMPEG_BINARY,
    )


# Rough per-scene cost estimates in USD, used only to enforce the spending
# ceilings in Automation Policy and to rank providers. They are not billing
# figures: providers change prices, and a clip's real cost depends on its
# length and resolution. Each value is deliberately on the high side, so a
# ceiling stops work slightly early rather than slightly late.
ESTIMATED_SCENE_COST_USD = {
    "runway": 0.50,
    "openai_image": 0.04,
    "gemini_image": 0.04,
    "gemini_veo": 1.60,
}
# Work covered by a subscription the user already pays for, or run locally,
# adds nothing to a money ceiling. Stating 0 rather than leaving it unknown is
# what lets the ceiling skip these providers instead of guessing.
SUBSCRIPTION_SCENE_COST_USD = 0.0


def build_scene_provider_gateway() -> ProviderGateway:
    """Build the provider catalog used by scene workers and future routing.

    The lambdas intentionally resolve the module functions at execution time.
    Existing tests and local extensions can therefore still monkeypatch a
    provider implementation without rebuilding the whole app.
    """
    gateway = ProviderGateway(
        (
            FunctionSceneProviderAdapter(
                ProviderDescriptor(
                    "runway", "Runway", frozenset({SCENE_VIDEO}),
                    priority=90, quality_score=88, billing_mode="api",
                    estimated_unit_cost=ESTIMATED_SCENE_COST_USD["runway"],
                    fallback_keys=("gflow_cli", "gemini_veo"),
                ),
                lambda database, job, root: generate_runway_scene(database, job, root),
            ),
            FunctionSceneProviderAdapter(
                ProviderDescriptor(
                    "openai_image", "OpenAI Image API", frozenset({SCENE_IMAGE, SCENE_ANIMATED_IMAGE}),
                    priority=80, quality_score=87, billing_mode="api",
                    estimated_unit_cost=ESTIMATED_SCENE_COST_USD["openai_image"],
                    fallback_keys=("gflow_image", "chatgpt_web_image"),
                ),
                lambda database, job, root: generate_openai_image_scene(database, job, root),
            ),
            FunctionSceneProviderAdapter(
                ProviderDescriptor(
                    "gemini_image", "Google Gemini Image API", frozenset({SCENE_IMAGE, SCENE_ANIMATED_IMAGE}),
                    priority=85, quality_score=85, billing_mode="api",
                    estimated_unit_cost=ESTIMATED_SCENE_COST_USD["gemini_image"],
                    fallback_keys=("gflow_image", "gemini_web_image"),
                ),
                lambda database, job, root: generate_gemini_image_scene(database, job, root),
            ),
            FunctionSceneProviderAdapter(
                ProviderDescriptor(
                    "gemini_veo", "Google Veo API", frozenset({SCENE_VIDEO}),
                    priority=80, quality_score=92, billing_mode="api",
                    estimated_unit_cost=ESTIMATED_SCENE_COST_USD["gemini_veo"],
                    fallback_keys=("gflow_cli",),
                ),
                lambda database, job, root: generate_gemini_veo_scene(database, job, root),
            ),
            FunctionSceneProviderAdapter(
                ProviderDescriptor(
                    "gflow_cli", "Google Flow CLI (video)", frozenset({SCENE_VIDEO}),
                    priority=10, quality_score=92, billing_mode="subscription",
                    estimated_unit_cost=SUBSCRIPTION_SCENE_COST_USD,
                    fallback_keys=("gemini_veo", "runway"),
                ),
                lambda database, job, root: generate_gflow_cli_scene(database, job, root),
            ),
            FunctionSceneProviderAdapter(
                ProviderDescriptor(
                    "gflow_image",
                    "Google Flow CLI (image/GIF)",
                    frozenset({SCENE_IMAGE, SCENE_ANIMATED_IMAGE}),
                    priority=10,
                    quality_score=86,
                    billing_mode="subscription",
                    estimated_unit_cost=SUBSCRIPTION_SCENE_COST_USD,
                    fallback_keys=("chatgpt_web_image", "gemini_web_image", "flow_image"),
                ),
                lambda database, job, root: generate_gflow_image_scene(database, job, root),
            ),
        )
    )
    external_providers = {
        "antigravity_image": ("Google Antigravity (image)", {SCENE_IMAGE, SCENE_ANIMATED_IMAGE}, 25, 84, True),
        "flow_veo": ("Google Flow web (video, legacy)", {SCENE_VIDEO}, 95, 88, True),
        "flow_image": ("Google Flow web (image)", {SCENE_IMAGE, SCENE_ANIMATED_IMAGE}, 35, 84, True),
        "meta_ai_video": ("Meta AI web (video)", {SCENE_VIDEO}, 100, 70, False),
        "gemini_web_image": ("Google Gemini web (image)", {SCENE_IMAGE, SCENE_ANIMATED_IMAGE}, 30, 84, True),
        "chatgpt_web_image": ("ChatGPT web (image)", {SCENE_IMAGE, SCENE_ANIMATED_IMAGE}, 20, 87, True),
    }
    for key in Database.EXTERNAL_SIDECAR_PROVIDERS:
        display_name, capabilities, priority, quality, enabled = external_providers[key]
        gateway.register(
            SidecarSceneProviderAdapter(
                ProviderDescriptor(
                    key,
                    display_name,
                    frozenset(capabilities),
                    execution_mode=EXECUTION_EXTERNAL_SIDECAR,
                    priority=priority,
                    quality_score=quality,
                    billing_mode="subscription",
                    estimated_unit_cost=SUBSCRIPTION_SCENE_COST_USD,
                    enabled=enabled,
                )
            )
        )
    return gateway


class SceneGenerationWorker:
    """Persistent local worker for paid cloud scene-generation jobs."""

    def __init__(
        self,
        database: Database,
        artifact_root: Path,
        provider_gateway: ProviderGateway | None = None,
    ):
        self.database = database
        self.artifact_root = Path(artifact_root)
        self.provider_gateway = provider_gateway or build_scene_provider_gateway()
        self._jobs: Queue[int | None] = Queue()
        self._stop = Event()
        self._lock = Lock()
        self._paused = False
        self._thread: Thread | None = None
        self._watchdog_thread: Thread | None = None
        self._completion_callback: Callable[[int], None] | None = None
        self._failure_router: Callable[[dict[str, Any], str, str], str | None] | None = None
        # Writing a scene's prompt takes a CLI round trip, so it happens when
        # the job runs rather than when it is queued — otherwise queueing a
        # batch of 30 scenes held the HTTP request for minutes and could not
        # be called off once started. Injected from main.py, which owns the
        # orchestrator, so this module needn't import back into it.
        self._prompt_crafter: Callable[[dict[str, Any]], str] | None = None
        self.stale_seconds = max(60, int(os.getenv("SCENE_JOB_STALE_SECONDS", "900")))
        self.watchdog_interval_seconds = max(5, int(os.getenv("SCENE_WATCHDOG_INTERVAL_SECONDS", "30")))

    def set_completion_callback(self, callback: Callable[[int], None] | None) -> None:
        """Run app-level review after an internal provider creates its asset."""
        self._completion_callback = callback

    def set_prompt_crafter(self, callback: Callable[[dict[str, Any]], str] | None) -> None:
        """Let the app write a job's prompt just before the job runs."""
        self._prompt_crafter = callback

    def set_failure_router(
        self,
        callback: Callable[[dict[str, Any], str, str], str | None] | None,
    ) -> None:
        """Choose another adapter after a bounded provider failure."""
        self._failure_router = callback

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
            self._watchdog_thread = Thread(
                target=self._watchdog_loop,
                name="scene-generation-watchdog",
                daemon=True,
            )
            self._watchdog_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._jobs.put(None)
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
        watchdog = self._watchdog_thread
        if watchdog and watchdog.is_alive():
            watchdog.join(timeout=5)
        self._thread = None
        self._watchdog_thread = None

    def enqueue(self, job_id: int) -> None:
        self._jobs.put(job_id)

    def cancel_queued(self, job_id: int) -> dict[str, Any] | None:
        return self.database.cancel_queued_scene_generation_job(job_id)

    def retry(self, job_id: int) -> dict[str, Any] | None:
        job = self.database.retry_scene_generation_job(job_id)
        if job:
            self._jobs.put(job_id)
        return job

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
            "watchdog_running": bool(self._watchdog_thread and self._watchdog_thread.is_alive()),
            "stale_seconds": self.stale_seconds,
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = self._jobs.get(timeout=2.0)
            except Empty:
                queued = self.database.list_queued_scene_generation_job_ids(limit=1)
                job_id = queued[0] if queued else None
            if job_id is None:
                if self._stop.is_set():
                    return
                continue
            while True:
                with self._lock:
                    paused = self._paused
                if not paused or self._stop.wait(0.25):
                    break
            if self._stop.is_set():
                return
            self._process(job_id)

    def _watchdog_loop(self) -> None:
        while not self._stop.wait(self.watchdog_interval_seconds):
            recovered = self.database.recover_stale_scene_generation_jobs(self.stale_seconds)
            for item in recovered:
                if item.get("requeued") and item.get("provider") not in self.database.EXTERNAL_SIDECAR_PROVIDERS:
                    self._jobs.put(int(item["id"]))

    def _register_output_asset(self, job: dict[str, Any], output_path: str) -> dict[str, Any] | None:
        path = Path(output_path)
        if not path.is_file():
            return None
        existing = self.database.find_project_asset_by_path(int(job["project_id"]), str(path))
        if existing:
            return existing
        suffix = path.suffix.lower()
        asset_type = "video" if suffix in {".mp4", ".mov", ".webm", ".mkv"} else "image"
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        return self.database.create_project_asset(
            int(job["project_id"]),
            asset_type,
            path.name,
            str(path),
            mime_type=mimetypes.guess_type(path.name)[0] or "",
            file_size=path.stat().st_size,
            sha256=digest,
        )

    def _ensure_prompt_written(self, job: dict[str, Any]) -> dict[str, Any]:
        """Have the orchestrator write this job's prompt, if it hasn't yet.

        Touches the heartbeat around the call: writing a prompt takes tens of
        seconds, which is long enough for the watchdog to decide the job had
        stalled and hand it to someone else.
        """
        if job.get("prompt_written") or self._prompt_crafter is None:
            return job
        job_id = int(job["id"])
        self.database.touch_scene_generation_job(job_id, "writing_prompt")
        try:
            prompt = self._prompt_crafter(job)
        except Exception:
            # A prompt the orchestrator could not improve is still the
            # storyboard's own description — good enough to generate from.
            self.database.touch_scene_generation_job(job_id, "prompt_ready")
            return job
        if not prompt.strip():
            return job
        return self.database.save_scene_job_prompt(job_id, prompt) or job

    def _process(self, job_id: int) -> None:
        job = self.database.claim_scene_generation_job(job_id)
        if not job:
            return
        capability = ""
        try:
            job = self._ensure_prompt_written(job)
            provider = str(job.get("provider") or "").strip().lower()
            capability = {
                "image": SCENE_IMAGE,
                "gif": SCENE_ANIMATED_IMAGE,
                "video": SCENE_VIDEO,
            }.get(str(job.get("job_kind") or "").strip().lower(), "")
            output_path = self.provider_gateway.execute_scene(
                provider,
                self.database,
                job,
                self.artifact_root,
                capability=capability,
            )
            asset = self._register_output_asset(job, output_path)
            if asset and str(job.get("job_kind") or "") == "gif":
                asset = materialize_gif_asset(
                    self.database,
                    job,
                    asset,
                    ffmpeg_binary=settings.FFMPEG_BINARY,
                )
                output_path = str(asset["file_path"])
            self.database.finish_scene_generation_job(
                job_id,
                "completed",
                output_path=output_path,
                output_asset_id=int(asset["id"]) if asset else None,
                release_dependents=self._completion_callback is None,
            )
            self.database.finalize_scene_provider_usage(
                job_id,
                "completed",
                metadata={"output_path": output_path},
            )
            if self._completion_callback is not None:
                try:
                    self._completion_callback(job_id)
                except Exception:
                    # Review is a quality gate, not a reason to strand the
                    # downstream I2V dependency forever.
                    self.database.release_scene_generation_dependents(job_id)
            for queued_id in self.database.list_queued_scene_generation_job_ids(limit=20):
                self._jobs.put(queued_id)
        except Exception as exc:
            message = str(exc)
            normalized = message.lower()
            # Read from the job rather than the local: a failure before the
            # provider is chosen would leave that name unbound.
            failed_provider = str((job or {}).get("provider") or "").strip().lower()
            failure_kind = (
                exc.kind if isinstance(exc, GFlowCliError) else
                "quota" if usage_limits.note_failure(failed_provider, message)
                or any(key in normalized for key in ("quota", "credit", "tín dụng", "resource_exhausted")) else
                "provider"
            )
            self.database.finalize_scene_provider_usage(
                job_id,
                "failed",
                metadata={"failure_kind": failure_kind, "error": message[:2000]},
            )
            fallback_provider = ""
            if self._failure_router is not None and failure_kind not in {"input", "dependency"}:
                try:
                    fallback_provider = str(
                        self._failure_router(job, message, failure_kind) or ""
                    ).strip().lower()
                except Exception:
                    fallback_provider = ""
            if fallback_provider and fallback_provider != failed_provider:
                self.database.record_scene_provider_failure(failed_provider, message)
                rerouted = self.database.reroute_scene_generation_job(
                    job_id,
                    fallback_provider,
                    previous_error=message,
                    failure_kind=failure_kind,
                )
                if rerouted:
                    descriptor = self.provider_gateway.require(fallback_provider).descriptor
                    self.database.record_provider_usage(
                        project_id=int(rerouted["project_id"]),
                        scene_job_id=job_id,
                        provider=fallback_provider,
                        capability=capability or f"scene.{rerouted.get('job_kind') or 'image'}",
                        status="estimated",
                        estimated_cost=descriptor.estimated_unit_cost or 0,
                        metadata={
                            "billing_mode": descriptor.billing_mode,
                            "fallback_from": failed_provider,
                        },
                    )
                    if fallback_provider not in self.database.EXTERNAL_SIDECAR_PROVIDERS:
                        self._jobs.put(job_id)
                    return
            self.database.finish_scene_generation_job(
                job_id,
                "error",
                error=message,
                failure_kind=failure_kind,
            )
