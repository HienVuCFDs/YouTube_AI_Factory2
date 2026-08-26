from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .. import settings
from ..antigravity_bridge import antigravity_cli_status
from ..claude_code_bridge import ClaudeCodeBridgeError, call_claude_code_json, claude_code_cli_status
from ..codex_bridge import CodexBridgeError, call_codex_vision_json, codex_cli_status, launch_codex_login
from ..ffmpeg_renderer import ffmpeg_available, nvenc_available
from ..gflow_bridge import gflow_cli_status, launch_gflow_login
from ..maintenance import list_database_backups, prune_database_backups
from ..oauth import status as oauth_status
from ..settings import (
    ANTHROPIC_API_KEY,
    DB_PATH,
    EDGE_TTS_RUNTIME_READY,
    OPENAI_API_KEY,
    FFMPEG_RENDER_COMMAND,
    FFMPEG_BINARY,
    PYVIDEOTRANS_COMMAND,
    PYVIDEOTRANS_RUNTIME_READY,
    PYVIDEOTRANS_VOICE_ROLE,
    PYVIDEOTRANS_WORKDIR,
    VOXCPM_DEVICE,
    VOXCPM_MODEL,
    voxcpm_runtime_status,
    SYSTEM_ROOT,
    YOUTUBE_API_KEY,
)
from ..transcriber import TranscriptionError, resolve_whisper_runtime

# Deferred import: `..main` defines the shared singletons (database, workers,
# template_path) and is the module that includes this router, so importing it
# here only resolves once main.py's module-level setup has already run.
from ..main import (
    browser_lease_monitor,
    database,
    openmontage_adapter,
    production_worker,
    publisher_worker,
    scene_generation_worker,
    template_path,
)

router = APIRouter()


class BrowserHeartbeatRequest(BaseModel):
    client_id: str = Field(min_length=8, max_length=128)
    status: Literal["online", "offline"] = "online"


class PruneBackupsRequest(BaseModel):
    keep: int = Field(default=14, ge=1, le=100)
    confirmed: bool = False


IntegrationProvider = Literal["openai_gpt", "google_gemini", "anthropic_claude", "runway"]


class SaveIntegrationRequest(BaseModel):
    provider: IntegrationProvider
    api_key: str | None = Field(default=None, max_length=1000)
    model: str | None = Field(default=None, max_length=120)
    clear_api_key: bool = False


@router.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(template_path.read_text(encoding="utf-8"))


@router.post("/api/browser/heartbeat")
def browser_heartbeat(payload: BrowserHeartbeatRequest) -> dict[str, Any]:
    browser_lease_monitor.heartbeat(payload.client_id, payload.status)
    return {"ok": True, "browser": browser_lease_monitor.snapshot()}


@router.get("/api/health")
def health() -> dict[str, Any]:
    try:
        whisper_device, whisper_compute_type = resolve_whisper_runtime()
    except TranscriptionError as exc:
        whisper_device, whisper_compute_type = "error", str(exc)
    anthropic_key, anthropic_model = settings.anthropic_config()
    openai_key, openai_model = settings.openai_config()
    runway_key, runway_model = settings.runway_config()
    codex = codex_cli_status()
    claude_code = claude_code_cli_status()
    antigravity = antigravity_cli_status()
    gflow = gflow_cli_status()
    oauth = oauth_status()
    openmontage_status = openmontage_adapter.status()
    return {
        "ok": True,
        "api_key_configured": bool(YOUTUBE_API_KEY),
        "database": str(DB_PATH),
        # Monitoring, analysis and transcript queues do not download video.  The
        # confirmed AI Director action may download a single source for editing.
        "auto_download_enabled": True,
        "director_download_requires_confirmation": True,
        "manual_video_download_available": True,
        "whisper_requires_explicit_confirmation": True,
        "whisper_device": whisper_device,
        "whisper_compute_type": whisper_compute_type,
        "gpu_only": settings.GPU_ONLY,
        "cuda_device": settings.GPU_DEVICE_INDEX,
        "ffmpeg_nvenc_available": nvenc_available(FFMPEG_BINARY),
        "production_worker_running": bool(
            production_worker._thread and production_worker._thread.is_alive()
        ),
        "publisher_worker_running": bool(
            publisher_worker._thread and publisher_worker._thread.is_alive()
        ),
        "youtube_oauth_connected": bool(oauth.get("connected")),
        "pyvideotrans_configured": bool(PYVIDEOTRANS_COMMAND),
        "pyvideotrans_cuda_ready": settings.PYVIDEOTRANS_CUDA_READY,
        "pyvideotrans_runtime_ready": PYVIDEOTRANS_RUNTIME_READY,
        "pyvideotrans_workdir_configured": bool(PYVIDEOTRANS_WORKDIR),
        "pyvideotrans_voice_role": PYVIDEOTRANS_VOICE_ROLE,
        "voxcpm_runtime_ready": voxcpm_runtime_status()[0],
        "voxcpm_model": VOXCPM_MODEL,
        "voxcpm_device": VOXCPM_DEVICE,
        "edge_tts_runtime_ready": EDGE_TTS_RUNTIME_READY,
        "ffmpeg_configured": bool(FFMPEG_RENDER_COMMAND),
        "ffmpeg_builtin_available": ffmpeg_available(FFMPEG_BINARY),
        "openai_configured": bool(openai_key),
        "openai_model": openai_model,
        "anthropic_configured": bool(anthropic_key),
        "anthropic_model": anthropic_model,
        "runway_configured": bool(runway_key),
        "runway_model": runway_model,
        "scene_generation_worker_running": bool(
            scene_generation_worker._thread and scene_generation_worker._thread.is_alive()
        ),
        "codex_cli_installed": bool(codex["installed"]),
        "codex_cli_logged_in": bool(codex["logged_in"]),
        "claude_code_cli_installed": bool(claude_code["installed"]),
        "claude_code_cli_logged_in": bool(claude_code["logged_in"]),
        "antigravity_cli_installed": bool(antigravity["installed"]),
        "antigravity_cli_logged_in": bool(antigravity["logged_in"]),
        "gflow_cli_installed": bool(gflow["installed"]),
        "gflow_cli_logged_in": bool(gflow["logged_in"]),
        "gflow_cli_profile": str(gflow.get("profile") or "default"),
        "ai_orchestrator_provider": settings.orchestrator_provider(),
        "openmontage": openmontage_status,
    }


@router.post("/api/maintenance/database-backup")
def create_database_backup() -> dict[str, Any]:
    backup_dir = DB_PATH.parent / "backups"
    filename = f"youtube_monitor-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.db"
    try:
        path = database.backup_to(backup_dir / filename)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "completed", "path": str(path), "bytes": path.stat().st_size}


@router.get("/api/maintenance/database-backups")
def database_backups() -> dict[str, Any]:
    backups = list_database_backups(DB_PATH.parent / "backups")
    return {"backups": backups, "count": len(backups)}


@router.post("/api/maintenance/database-backups/prune")
def prune_backups(payload: PruneBackupsRequest) -> dict[str, Any]:
    if not payload.confirmed:
        raise HTTPException(status_code=400, detail="Cần xác nhận trước khi dọn bản sao lưu cũ")
    try:
        result = prune_database_backups(DB_PATH.parent / "backups", payload.keep)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**result, "count": len(list_database_backups(DB_PATH.parent / "backups"))}


@router.get("/api/summary")
def summary() -> dict[str, int]:
    return database.summary()


def _integration_status() -> list[dict[str, Any]]:
    openai_key, openai_model = settings.openai_config()
    gemini_key, gemini_image_model, gemini_video_model = settings.gemini_config()
    anthropic_key, anthropic_model = settings.anthropic_config()
    runway_key, runway_model = settings.runway_config()
    codex = codex_cli_status()
    claude_code = claude_code_cli_status()
    antigravity = antigravity_cli_status()
    gflow = gflow_cli_status()
    oauth = oauth_status()
    return [
        {
            "key": "openai_gpt",
            "label": "OpenAI GPT + Image API",
            "category": "AI Writer / anh canh",
            "ready": bool(openai_key),
            "connection": "api_key",
            "model": openai_model,
            "detail": "Viet kich ban, phan tich va tao anh cho tung canh" if openai_key else "Can them OPENAI_API_KEY",
        },
        {
            "key": "google_gemini",
            "label": "Google Gemini Image + Veo",
            "category": "Anh canh / video canh AI",
            "ready": bool(gemini_key),
            "connection": "api_key",
            "model": gemini_image_model,
            "detail": (
                f"Anh: {gemini_image_model} · Video: {gemini_video_model} · Cần Google AI Studio Billing để tạo ảnh/video"
                if gemini_key else "Can them GEMINI_API_KEY"
            ),
        },
        {
            "key": "anthropic_claude",
            "label": "Claude API",
            "category": "AI Writer / director",
            "ready": bool(anthropic_key),
            "connection": "api_key",
            "model": anthropic_model,
            "detail": "Viet kich ban, phan tich va tao ke hoach dung" if anthropic_key else "Can them ANTHROPIC_API_KEY",
        },
        {
            "key": "runway",
            "label": "Runway Video API",
            "category": "Tao canh AI tu prompt",
            "ready": bool(runway_key),
            "connection": "api_key",
            "model": runway_model,
            "detail": "Tao video canh va gan vao timeline" if runway_key else "Can them RUNWAYML_API_SECRET",
        },
        {
            "key": "youtube_oauth",
            "label": "YouTube OAuth Publisher",
            "category": "Upload video, thumbnail và đặt lịch đăng",
            "ready": bool(oauth.get("connected")),
            "configured": bool(oauth.get("configured")),
            "connection": "youtube_oauth",
            "model": "YouTube Data API v3",
            "client_id_hint": oauth.get("client_id_hint", ""),
            "redirect_uri": oauth.get("redirect_uri", ""),
            "detail": "Đã kết nối tài khoản YouTube" if oauth.get("connected") else (
                "Đã có Client ID nhưng chưa cấp quyền" if oauth.get("configured") else "Cần cấu hình OAuth Client ID và Client Secret"
            ),
        },
        {
            "key": "codex_cli",
            "label": "Codex CLI tren may",
            "category": "AI Writer local bridge",
            "ready": bool(codex["logged_in"]),
            "connection": "codex_cli",
            "model": "Tai khoan Codex",
            "detail": str(codex["detail"]),
        },
        {
            "key": "claude_code_cli",
            "label": "Claude Code CLI tren may",
            "category": "AI Writer / dieu phoi trinh duyet local bridge",
            "ready": bool(claude_code["logged_in"]),
            "connection": "claude_code_cli",
            "model": "Tai khoan Claude",
            "detail": str(claude_code["detail"]),
        },
        {
            "key": "antigravity_cli",
            "label": "Antigravity CLI tren may",
            "category": "AI Writer / phan tich local bridge",
            "ready": bool(antigravity["logged_in"]),
            "connection": "antigravity_cli",
            "model": "Tai khoan Google",
            "detail": str(antigravity["detail"]),
        },
        {
            "key": "gflow_cli",
            "label": "Google Flow/Veo qua gflow-cli",
            "category": "Tạo video bằng gói Google Flow đã đăng ký",
            "ready": bool(gflow["logged_in"]),
            "connection": "cloud_subscription",
            "installed": bool(gflow["installed"]),
            "profile": str(gflow.get("profile") or "default"),
            "version": str(gflow.get("version") or ""),
            "model": settings.gflow_config().get("video_model") or "Flow/Veo mặc định",
            "detail": str(gflow["detail"]),
        },
        {
            "key": "openmontage",
            "label": "OpenMontage video engine",
            "category": "Dựng, chuyển cảnh và render local",
            "ready": bool(openmontage_adapter.status()["ready"]),
            "connection": "local_engine",
            "model": openmontage_adapter.configured_runtime,
            "detail": str(openmontage_adapter.status()["detail"]),
        },
        {
            "key": "claude_desktop",
            "label": "Claude Desktop",
            "category": "Handoff local",
            "ready": True,
            "connection": "handoff",
            "model": "JSON handoff",
            "detail": "Xuat goi project de dua vao Claude; dung Claude API neu can tu dong trong app",
        },
    ]


@router.get("/api/integrations")
def list_integrations() -> list[dict[str, Any]]:
    """Return provider state only; API secrets are never sent to the browser."""
    return _integration_status()


@router.post("/api/integrations")
def save_integration(payload: SaveIntegrationRequest) -> dict[str, Any]:
    mapping = {
        "openai_gpt": ("OPENAI_API_KEY", "OPENAI_MODEL"),
        "google_gemini": ("GEMINI_API_KEY", "GEMINI_IMAGE_MODEL"),
        "anthropic_claude": ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"),
        "runway": ("RUNWAYML_API_SECRET", "RUNWAY_MODEL"),
    }
    key_name, model_name = mapping[payload.provider]
    values: dict[str, str] = {}
    if payload.clear_api_key:
        values[key_name] = ""
    elif payload.api_key is not None and payload.api_key.strip():
        values[key_name] = payload.api_key.strip()
    if payload.model is not None and payload.model.strip():
        values[model_name] = payload.model.strip()
    if not values:
        raise HTTPException(status_code=400, detail="Hay nhap API key, model hoac chon xoa key")
    try:
        settings.save_integration_values(values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    item = next(item for item in _integration_status() if item["key"] == payload.provider)
    return {"status": "saved", "integration": item}


@router.post("/api/integrations/codex/login")
def begin_codex_login() -> dict[str, Any]:
    try:
        return {"status": "login_started", "integration": launch_codex_login()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/integrations/gflow/login")
def begin_gflow_login() -> dict[str, Any]:
    try:
        return {"status": "login_started", "integration": launch_gflow_login()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/integrations/gflow/status")
def refresh_gflow_status() -> dict[str, Any]:
    return {"status": "ready", "integration": gflow_cli_status(force=True)}


@router.get("/api/openmontage/status")
def openmontage_status() -> dict[str, Any]:
    return openmontage_adapter.status()


OrchestratorProvider = Literal["codex_cli", "claude_code_cli", "antigravity"]
AssignmentMode = Literal["fixed", "auto", "fallback"]
AgentProvider = Literal["codex_cli", "claude_code_cli", "antigravity"]


class OrchestratorSettingsRequest(BaseModel):
    provider: OrchestratorProvider


def _orchestrator_settings() -> dict[str, Any]:
    return {
        "provider": settings.orchestrator_provider(),
        "options": [
            {"key": "codex_cli", "label": "Codex CLI", **codex_cli_status()},
            {"key": "claude_code_cli", "label": "Claude Code CLI", **claude_code_cli_status()},
            {"key": "antigravity", "label": "Google Antigravity", **antigravity_cli_status()},
        ],
    }


@router.get("/api/settings/orchestrator")
def get_orchestrator_settings() -> dict[str, Any]:
    """Which locally-logged-in CLI agent drives tasks like web_video_sidecar.py's
    vision fallback (find an element on an unfamiliar page) — a CLI already
    logged into the user's own Claude/Codex subscription, not a metered API key."""
    return _orchestrator_settings()


@router.post("/api/settings/orchestrator")
def save_orchestrator_settings(payload: OrchestratorSettingsRequest) -> dict[str, Any]:
    assignments = settings.agent_assignments()
    assignments["orchestration"] = {
        **assignments["orchestration"],
        "mode": "fixed",
        "executor": payload.provider,
    }
    settings.save_integration_values({
        "AI_ORCHESTRATOR_PROVIDER": payload.provider,
        "AI_STAGE_ASSIGNMENTS_JSON": json.dumps(assignments, ensure_ascii=False, separators=(",", ":")),
    })
    return _orchestrator_settings()


class StageAgentAssignmentRequest(BaseModel):
    mode: AssignmentMode = "auto"
    executor: AgentProvider
    allowed_agents: list[AgentProvider] = Field(default_factory=list)
    fallback_agents: list[AgentProvider] = Field(default_factory=list)
    reviewer: Literal["auto", "codex_cli", "claude_code_cli", "antigravity"] = "auto"


class AgentAssignmentsRequest(BaseModel):
    assignments: dict[str, StageAgentAssignmentRequest]


def _agent_options() -> list[dict[str, Any]]:
    return [
        {
            "key": "codex_cli", "label": "Codex CLI", **codex_cli_status(),
            "capabilities": ["structured_json", "vision", "code", "browser_control"],
        },
        {
            "key": "claude_code_cli", "label": "Claude Code CLI", **claude_code_cli_status(),
            "capabilities": ["structured_json", "vision", "code", "browser_control"],
        },
        {
            "key": "antigravity", "label": "Google Antigravity", **antigravity_cli_status(),
            "capabilities": ["structured_json", "image_generation", "mcp_tools"],
        },
    ]


@router.get("/api/settings/agent-assignments")
def get_agent_assignments() -> dict[str, Any]:
    return {
        "stages": list(settings.AGENT_STAGE_IDS),
        "agents": _agent_options(),
        "assignments": settings.agent_assignments(),
    }


@router.post("/api/settings/agent-assignments")
def save_agent_assignments(payload: AgentAssignmentsRequest) -> dict[str, Any]:
    invalid_stages = set(payload.assignments) - set(settings.AGENT_STAGE_IDS)
    if invalid_stages:
        raise HTTPException(status_code=400, detail=f"Công đoạn không hợp lệ: {', '.join(sorted(invalid_stages))}")
    current = settings.agent_assignments()
    for stage, assignment in payload.assignments.items():
        allowed = list(dict.fromkeys(assignment.allowed_agents or list(settings.AGENT_IDS)))
        if assignment.executor not in allowed:
            allowed.insert(0, assignment.executor)
        current[stage] = {
            "mode": assignment.mode,
            "executor": assignment.executor,
            "allowed_agents": allowed,
            "fallback_agents": list(dict.fromkeys(
                agent for agent in assignment.fallback_agents if agent != assignment.executor
            )),
            "reviewer": assignment.reviewer,
        }
    settings.save_integration_values({
        "AI_STAGE_ASSIGNMENTS_JSON": json.dumps(current, ensure_ascii=False, separators=(",", ":")),
    })
    return get_agent_assignments()


class LocateElementRequest(BaseModel):
    screenshot_path: str = Field(min_length=1, max_length=1000)
    instruction: str = Field(min_length=1, max_length=2000)
    viewport_width: int = Field(ge=1, le=8000)
    viewport_height: int = Field(ge=1, le=8000)


_LOCATE_ELEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "x": {"type": "integer"},
        "y": {"type": "integer"},
        "reasoning": {"type": "string"},
    },
    "required": ["found", "x", "y"],
}


@router.post("/api/orchestrator/locate-element")
def locate_element(payload: LocateElementRequest) -> dict[str, Any]:
    """Vision fallback for web_video_sidecar.py: given a screenshot already
    saved to disk (sidecar and app run on the same machine, so a local path
    is enough — no upload needed) and a plain-language instruction, ask the
    configured orchestrator CLI (the user's own logged-in Claude/Codex
    subscription, not a metered API key) for pixel coordinates to click.
    Used only when the sidecar's hardcoded selectors fail to find something."""
    screenshot = Path(payload.screenshot_path)
    if not screenshot.is_file():
        raise HTTPException(status_code=400, detail=f"Không tìm thấy ảnh: {screenshot}")
    system_prompt = (
        f"Ban dang xem anh chup man hinh mot trang web, kich thuoc {payload.viewport_width}x{payload.viewport_height} "
        "pixel, goc toa do (0,0) o tren-trai. Tim toa do pixel can bam theo yeu cau ben duoi. "
        "Neu khong thay phan tu phu hop, tra ve found=false va x=0, y=0."
    )
    provider = settings.orchestrator_provider()
    try:
        if provider == "claude_code_cli":
            result = call_claude_code_json(
                system_prompt, payload.instruction, _LOCATE_ELEMENT_SCHEMA, image_path=screenshot,
            )
        else:
            result = call_codex_vision_json(
                system_prompt, payload.instruction, _LOCATE_ELEMENT_SCHEMA, image_path=screenshot,
            )
    except (ClaudeCodeBridgeError, CodexBridgeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result


@router.get("/api/model-catalog")
def model_catalog() -> list[dict[str, Any]]:
    """One stable catalog for the manual UI and future OpenClaw handoff."""
    anthropic_key, anthropic_model = settings.anthropic_config()
    openai_key, openai_model = settings.openai_config()
    runway_key, runway_model = settings.runway_config()
    gflow = gflow_cli_status()
    whisper_ready = bool(importlib.util.find_spec("faster_whisper")) and ffmpeg_available(FFMPEG_BINARY)
    return [
        {"stage": "LLM", "provider": "codex_cli", "model": "Codex cloud qua CLI", "mode": "cloud_account", "ready": bool(codex_cli_status()["logged_in"]), "vram": "Cloud"},
        {"stage": "LLM", "provider": "claude_code_cli", "model": "Claude cloud qua CLI", "mode": "cloud_account", "ready": bool(claude_code_cli_status()["logged_in"]), "vram": "Cloud"},
        {"stage": "LLM", "provider": "antigravity", "model": "Google cloud qua Antigravity", "mode": "cloud_account", "ready": bool(antigravity_cli_status()["logged_in"]), "vram": "Cloud"},
        {"stage": "LLM", "provider": "openai_gpt", "model": openai_model, "mode": "cloud", "ready": bool(openai_key), "vram": "Cloud"},
        {"stage": "Image AI", "provider": "openai_image", "model": "gpt-image-1", "mode": "cloud", "ready": bool(openai_key), "vram": "Cloud"},
        {"stage": "LLM", "provider": "anthropic_claude", "model": anthropic_model, "mode": "cloud", "ready": bool(anthropic_key), "vram": "Cloud"},
        {"stage": "STT", "provider": "faster_whisper", "model": settings.WHISPER_MODEL_SIZE, "mode": "local_gpu" if settings.WHISPER_DEVICE != "cpu" else "local_cpu", "ready": whisper_ready, "vram": "~1–6 GB"},
        {"stage": "TTS", "provider": "voxcpm", "model": settings.VOXCPM_MODEL, "mode": "local_gpu", "ready": voxcpm_runtime_status()[0], "vram": "~6–10 GB"},
        {"stage": "TTS", "provider": "pyvideotrans", "model": PYVIDEOTRANS_VOICE_ROLE, "mode": "local_gpu", "ready": PYVIDEOTRANS_RUNTIME_READY, "vram": "Theo engine"},
        {"stage": "TTS", "provider": "edge_tts", "model": "Neural voices", "mode": "cloud", "ready": EDGE_TTS_RUNTIME_READY, "vram": "Cloud"},
        {"stage": "Video AI", "provider": "runway", "model": runway_model, "mode": "cloud", "ready": bool(runway_key), "vram": "Cloud"},
        {"stage": "Video AI", "provider": "gflow_cli", "model": settings.gflow_config().get("video_model") or "Flow/Veo mặc định", "mode": "cloud_subscription", "ready": bool(gflow["logged_in"]), "vram": "Cloud"},
        {"stage": "Render", "provider": "ffmpeg_builtin", "model": "H.264/AAC + NVENC", "mode": "local_gpu", "ready": ffmpeg_available(FFMPEG_BINARY) and nvenc_available(FFMPEG_BINARY), "vram": "~2 GB"},
    ]


@router.get("/api/tool-status")
def tool_status() -> list[dict[str, Any]]:
    voxcpm_ready, voxcpm_detail = voxcpm_runtime_status()
    oauth = oauth_status()
    anthropic_key, _ = settings.anthropic_config()
    openai_key, _ = settings.openai_config()
    runway_key, runway_model = settings.runway_config()
    codex = codex_cli_status()
    claude_code = claude_code_cli_status()
    antigravity = antigravity_cli_status()
    gflow = gflow_cli_status()
    premiere_plugin = SYSTEM_ROOT / "premiere_plugin"
    whisper_ready = bool(importlib.util.find_spec("faster_whisper")) and ffmpeg_available(FFMPEG_BINARY)
    try:
        whisper_device, whisper_compute_type = resolve_whisper_runtime()
    except TranscriptionError as exc:
        whisper_device, whisper_compute_type = "error", str(exc)
    return [
        {
            "key": "youtube_api",
            "label": "YouTube Data API",
            "ready": bool(YOUTUBE_API_KEY),
            "phase": "ready" if YOUTUBE_API_KEY else "configure",
            "detail": "Đồng bộ metadata đa kênh" if YOUTUBE_API_KEY else "Cần YOUTUBE_API_KEY",
        },
        {
            "key": "local_whisper",
            "label": "Faster-Whisper local",
            "ready": whisper_ready,
            "phase": "ready" if whisper_ready else "configure",
            "detail": f"Trích transcript bằng GPU {whisper_compute_type}" if whisper_ready and whisper_device == "cuda" else ("Trích transcript bằng CPU" if whisper_ready else "Cần faster-whisper và FFmpeg"),
        },
        {
            "key": "ai_writer",
            "label": "AI Writer",
            "ready": bool(anthropic_key or openai_key),
            "phase": "ready" if (anthropic_key or openai_key) else "configure",
            "detail": "Claude/GPT đã cấu hình" if (ANTHROPIC_API_KEY or OPENAI_API_KEY) else "Cần OPENAI_API_KEY hoặc ANTHROPIC_API_KEY",
        },
        {
            "key": "openai_image",
            "label": "GPT Image · cảnh kể chuyện",
            "ready": bool(openai_key),
            "phase": "ready" if openai_key else "configure",
            "detail": "Tạo ảnh cho từng cảnh, FFmpeg thêm chuyển động khi dựng" if openai_key else "Cần OPENAI_API_KEY",
        },
        {
            "key": "runway_video",
            "label": "Runway Video AI",
            "ready": bool(runway_key),
            "phase": "ready" if runway_key else "configure",
            "detail": f"Tao canh tu prompt ({runway_model})" if runway_key else "Can RUNWAYML_API_SECRET",
        },
        {
            "key": "codex_cli",
            "label": "Codex CLI local",
            "ready": bool(codex["logged_in"]),
            "phase": "ready" if codex["logged_in"] else "configure",
            "detail": str(codex["detail"]),
        },
        {
            "key": "claude_code_cli",
            "label": "Claude Code CLI local",
            "ready": bool(claude_code["logged_in"]),
            "phase": "ready" if claude_code["logged_in"] else "configure",
            "detail": str(claude_code["detail"]),
        },
        {
            "key": "antigravity_cli",
            "label": "Antigravity CLI local",
            "ready": bool(antigravity["logged_in"]),
            "phase": "ready" if antigravity["logged_in"] else "configure",
            "detail": str(antigravity["detail"]),
        },
        {
            "key": "gflow_cli",
            "label": "Google Flow Video · gflow-cli",
            "ready": bool(gflow["logged_in"]),
            "phase": "ready" if gflow["logged_in"] else "configure",
            "detail": str(gflow["detail"]),
        },
        {
            "key": "pyvideotrans",
            "label": "pyVideoTrans voiceover · GPU check",
            "ready": PYVIDEOTRANS_RUNTIME_READY,
            "phase": "ready" if PYVIDEOTRANS_RUNTIME_READY else "configure",
            "detail": (
                "PyTorch CUDA sẵn sàng; F5/Qwen local sẽ dùng GPU"
                if PYVIDEOTRANS_RUNTIME_READY
                else ("Đang hoàn tất dependency pyVideoTrans" if PYVIDEOTRANS_COMMAND else "Cần cài tool và cấu hình PYVIDEOTRANS_COMMAND")
            ),
        },
        {
            "key": "voxcpm",
            "label": "VoxCPM2 voiceover · CUDA",
            "ready": voxcpm_ready,
            "phase": "ready" if voxcpm_ready else "configure",
            # The old wording told everyone to install voxcpm and enable CUDA,
            # including the many cases where both were already fine and the
            # startup probe had simply run out of time. Say what stopped it.
            "detail": (
                f"VoxCPM2 sẵn sàng trên {VOXCPM_DEVICE}; model sẽ tải ở lần chạy đầu"
                if voxcpm_ready
                else voxcpm_detail or "Cần cài voxcpm trong môi trường pyVideoTrans và bật CUDA"
            ),
        },
        {
            "key": "ffmpeg",
            "label": "FFmpeg renderer",
            "ready": ffmpeg_available(FFMPEG_BINARY),
            "phase": "ready" if ffmpeg_available(FFMPEG_BINARY) else "configure",
            "detail": "Render local không cần command template" if ffmpeg_available(FFMPEG_BINARY) else "Cần cài FFmpeg",
        },
        {
            "key": "premiere_plugin",
            "label": "Premiere UXP plugin",
            "ready": (premiere_plugin / "manifest.json").is_file(),
            "phase": "ready" if (premiere_plugin / "manifest.json").is_file() else "planned",
            "detail": "Đã có plugin, cần test trong Premiere" if (premiere_plugin / "manifest.json").is_file() else "Chưa dựng plugin",
        },
        {
            "key": "youtube_oauth",
            "label": "YouTube OAuth",
            "ready": bool(oauth.get("connected")),
            "phase": "ready" if oauth.get("connected") else "configure",
            "detail": "Caption chính chủ / quyền kênh đã kết nối" if oauth.get("connected") else "Chưa cấu hình hoặc chưa kết nối OAuth",
        },
        {
            "key": "youtube_webhook",
            "label": "YouTube Push Webhook",
            "ready": False,
            "phase": "configure",
            "detail": "Endpoint đã có, cần URL HTTPS public để đăng ký callback",
        },
        {
            "key": "comfyui",
            "label": "ComfyUI thumbnail",
            "ready": False,
            "phase": "planned",
            "detail": "Chưa tích hợp workflow thumbnail",
        },
        {
            "key": "publisher",
            "label": "YouTube Publisher",
            "ready": bool(publisher_worker._thread and publisher_worker._thread.is_alive()),
            "phase": "ready" if (publisher_worker._thread and publisher_worker._thread.is_alive()) else "configure",
            "detail": "Publisher queue đã sẵn sàng; cần kết nối YouTube OAuth để upload thật",
        },
        {
            "key": "analytics",
            "label": "Analytics Agent",
            "ready": False,
            "phase": "planned",
            "detail": "Chưa tích hợp YouTube Analytics API",
        },
    ]
