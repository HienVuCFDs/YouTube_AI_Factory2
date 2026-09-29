"""Local MCP bridge between a desktop chat app and YouTube AI Factory.

This is intentionally dependency-free: the desktop app (GPT Work, or Claude
Desktop/Cowork with YOUTUBE_CHAT_AGENT=claude_chat) starts this process over
stdio.  The process never reads browser
profiles, application tokens, or cloud credentials.  It talks only to the local
YouTube AI Factory HTTP server and only imports media from a project drop folder.

Run by an MCP client, not by the user directly::

    C:\\Program Files\\Python313\\python.exe ai_desktop_mcp.py
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

try:
    from . import steps as step_catalog
    from .agent_runtime import redact
    from .tool_layer.registry import astra_mcp_tool_definitions, astra_tool_names
except ImportError:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from youtube_monitor import steps as step_catalog
    from youtube_monitor.agent_runtime import redact
    from youtube_monitor.tool_layer.registry import astra_mcp_tool_definitions, astra_tool_names


FACTORY_URL = os.getenv("YOUTUBE_FACTORY_URL", "http://127.0.0.1:8787").rstrip("/")
CHAT_AGENT = os.getenv("YOUTUBE_CHAT_AGENT", "chatgpt_app").strip().lower()
if CHAT_AGENT not in {"chatgpt_app", "claude_chat"}:
    raise ValueError("YOUTUBE_CHAT_AGENT phải là chatgpt_app hoặc claude_chat")
CHAT_AGENT_LABEL = "Claude Chat" if CHAT_AGENT == "claude_chat" else "ChatGPT Chat"

# A step such as writing a script or planning scenes runs inside one call and
# takes minutes; 45 seconds cut the caller off while the app kept working.
REQUEST_TIMEOUT_SECONDS = 45
STEP_TIMEOUT_SECONDS = int(os.getenv("YOUTUBE_FACTORY_STEP_TIMEOUT", "1500") or 1500)

# Agent-run mode. Set only by the app when it starts its own orchestrating
# agent (codex_agent_bridge / claude_agent_bridge); a desktop chat app never
# sets it, so for GPT Work and Claude Cowork nothing below changes.
AGENT_RUN_LOG = os.getenv("YOUTUBE_AGENT_RUN_LOG", "").strip()
AGENT_ROUND = int(os.getenv("YOUTUBE_AGENT_ROUND", "1") or 1)
AGENT_PROJECT_ID = int(os.getenv("YOUTUBE_AGENT_PROJECT_ID", "0") or 0)
AGENT_ALLOW_SPEND = os.getenv("YOUTUBE_AGENT_ALLOW_SPEND", "0") == "1"
AGENT_ALLOW_OVERWRITE = os.getenv("YOUTUBE_AGENT_ALLOW_OVERWRITE", "0") == "1"
AGENT_TOOL_BUDGET = max(1, int(os.getenv("YOUTUBE_AGENT_TOOL_BUDGET", "40") or 40))

# The chat apps' own task queue. An agent the app started has no business
# claiming work queued for GPT Work or Claude Cowork, or queueing more.
_CHAT_QUEUE_TOOLS = {
    "youtube_factory_get_next_task",
    "youtube_factory_complete_task",
    "youtube_factory_fail_task",
    "youtube_factory_create_project",
    "youtube_factory_start_pipeline",
    "youtube_factory_create_agent_task",
}

SERVER_INSTRUCTIONS = (
    "Đây là cổng điều khiển trực tiếp YouTube AI Factory. Làm việc với app bằng các tool youtube_factory_*, "
    "KHÔNG bằng cách bấm giao diện: gọi youtube_factory_list_steps để xem dự án đang ở đâu, "
    "youtube_factory_run_step để chạy một bước (cùng đường với nút bấm). Tool trả lỗi thì đọc lỗi rồi chọn "
    "cách khác (bước tiên quyết, provider khác). Chỉ dùng giao diện hoặc điều khiển máy khi không có tool nào "
    "làm được việc đó, và nói rõ vì sao."
)


def _agent_mode() -> bool:
    return bool(AGENT_RUN_LOG)
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
PROJECTS_ROOT = WORKSPACE_ROOT / "01_DU_AN"
MAX_IMPORT_BYTES = 2 * 1024 * 1024 * 1024

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def _json_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _json_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _factory_request(
    path: str,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> Any:
    request = urllib.request.Request(
        f"{FACTORY_URL}{path}", data=data, method=method, headers=headers or {}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            detail = str(parsed.get("detail") or detail)
        except json.JSONDecodeError:
            pass
        raise RuntimeError(f"YT Factory báo lỗi HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Không kết nối được YT Factory tại {FACTORY_URL}. Hãy mở YT Factory trước."
        ) from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("YT Factory trả về dữ liệu không hợp lệ") from exc


def _json_factory(
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    method: str = "POST",
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> Any:
    return _factory_request(
        path,
        method=method,
        data=json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if method != "GET" else None,
        headers={"Content-Type": "application/json"} if method != "GET" else None,
        timeout=timeout,
    )


def _report_chat_contact() -> None:
    """Best-effort liveness signal; tool discovery must remain responsive offline."""
    if _agent_mode():
        # An agent the app started is not GPT Work or Claude Cowork; saying
        # otherwise would make the app believe a chat app is attached.
        return
    request = urllib.request.Request(
        f"{FACTORY_URL}/api/chat-agents/{CHAT_AGENT}/heartbeat",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=2):
            pass
    except (OSError, urllib.error.URLError):
        pass


def _drop_folder(project_id: int) -> Path:
    folder = PROJECTS_ROOT / str(project_id) / "03_TAI_NGUYEN" / "ai_desktop_import"
    folder.mkdir(parents=True, exist_ok=True)
    return folder.resolve()


def _asset_type(path: Path) -> str:
    extension = path.suffix.lower()
    if extension in _IMAGE_EXTENSIONS:
        return "image"
    if extension in _VIDEO_EXTENSIONS:
        return "video"
    if extension in _AUDIO_EXTENSIONS:
        return "audio"
    raise ValueError("Chỉ nhận ảnh PNG/JPG/WEBP, video MP4/MOV/WEBM/MKV/AVI hoặc audio MP3/WAV/M4A/AAC/FLAC/OGG")


def _safe_generated_file(project_id: int, raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    allowed = _drop_folder(project_id)
    try:
        path.relative_to(allowed)
    except ValueError as exc:
        raise ValueError(
            f"File phải nằm trong thư mục import của dự án: {allowed}"
        ) from exc
    if not path.is_file():
        raise ValueError("Không tìm thấy file media cần import")
    if path.stat().st_size > MAX_IMPORT_BYTES:
        raise ValueError("File lớn hơn giới hạn 2 GB của YT Factory")
    return path


def _multipart_upload(project_id: int, path: Path, asset_type: str) -> dict[str, Any]:
    boundary = f"----YouTubeFactory{uuid.uuid4().hex}"
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="asset_type"\r\n\r\n'
        f"{asset_type}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8")
    suffix = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = prefix + path.read_bytes() + suffix
    result = _factory_request(
        f"/api/projects/{project_id}/assets/upload",
        method="POST",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    if not isinstance(result, dict) or not isinstance(result.get("asset"), dict):
        raise RuntimeError("YT Factory không xác nhận asset vừa upload")
    return result


def _automation_tool_definitions() -> list[dict[str, Any]]:
    project_id = {"type": "integer", "description": "ID du an YouTube AI Factory"}
    confirmed = {
        "type": "boolean",
        "description": "Xac nhan cho phep goi trinh tao media hoac render ton tai nguyen",
    }
    return [
        {
            "name": "youtube_factory_get_next_task",
            "description": f"Nhận hoặc tiếp tục task kế tiếp mà YouTube AI Factory giao cho {CHAT_AGENT_LABEL}.",
            "inputSchema": {"type": "object", "properties": {}},
            "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
        },
        {
            "name": "youtube_factory_complete_task",
            "description": f"Đánh dấu task {CHAT_AGENT_LABEL} đã hoàn tất và chuyển pipeline sang công đoạn tiếp theo.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "output": {"type": "object", "description": "Kết quả có cấu trúc và ID artifact đã lưu vào app"},
                },
                "required": ["task_id", "output"],
            },
            "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
        },
        {
            "name": "youtube_factory_fail_task",
            "description": f"Báo task {CHAT_AGENT_LABEL} không thể hoàn tất, kèm lý do rõ ràng.",
            "inputSchema": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}, "error": {"type": "string", "minLength": 1}},
                "required": ["task_id", "error"],
            },
            "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
        },
        {
            "name": "youtube_factory_create_project",
            "description": f"Tạo dự án và hàng đợi Research -> Script -> Director -> Media -> QC để {CHAT_AGENT_LABEL} xử lý.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "minLength": 10},
                    "title": {"type": "string"},
                    "language": {"type": "string", "default": "vi"},
                    "auto_generate_media": {"type": "boolean", "default": False},
                    "auto_render": {"type": "boolean", "default": False},
                },
                "required": ["goal"],
            },
        },
        {
            "name": "youtube_factory_start_pipeline",
            "description": f"Khởi động chuỗi task {CHAT_AGENT_LABEL} cho một dự án đã có.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": project_id,
                    "goal": {"type": "string", "minLength": 10},
                    "auto_generate_media": {"type": "boolean", "default": False},
                    "auto_render": {"type": "boolean", "default": False},
                },
                "required": ["project_id", "goal"],
            },
        },
        {
            "name": "youtube_factory_get_pipeline_status",
            "description": "Lay task, message A2A, event va chi phi provider cua du an.",
            "inputSchema": {"type": "object", "properties": {"project_id": project_id}, "required": ["project_id"]},
        },
        {
            "name": "youtube_factory_create_agent_task",
            "description": "Giao mot task ben vung cho Research/Script/Director/Media/QC Agent va bat nghiem thu cheo.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": project_id,
                    "role": {"type": "string", "enum": ["research", "script", "director", "media", "qc"]},
                    "task_type": {"type": "string"},
                    "input": {"type": "object"},
                    "assigned_agent": {"type": "string"},
                    "reviewer_agent": {"type": "string"},
                },
                "required": ["role", "task_type", "input"],
            },
        },
        {
            "name": "youtube_factory_list_agent_tasks",
            "description": "Liet ke task cua cac AI va trang thai hien tai.",
            "inputSchema": {
                "type": "object",
                "properties": {"project_id": project_id, "status": {"type": "string"}, "role": {"type": "string"}},
            },
        },
        {
            "name": "youtube_factory_list_events",
            "description": "Doc event bus ben vung de theo doi task, scene, review, render va loi.",
            "inputSchema": {
                "type": "object",
                "properties": {"project_id": project_id, "after_id": {"type": "integer", "default": 0}},
            },
        },
        {
            "name": "youtube_factory_list_providers",
            "description": "Lay catalog provider, kha nang, tinh san sang, chi phi uoc tinh va fallback.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "youtube_factory_route_provider",
            "description": "De Provider Gateway tu chon provider theo kha nang, san sang, goi dang ky va chi phi.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": project_id,
                    "capability": {"type": "string", "enum": ["scene.image", "scene.animated_image", "scene.video"]},
                },
                "required": ["capability"],
            },
        },
        *[
            {
                "name": f"youtube_factory_generate_{kind}",
                "description": f"Tao {kind} cho mot scene qua Provider Gateway; co the de provider rong de tu dinh tuyen.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": project_id,
                        "segment_id": {"type": "integer"},
                        "prompt": {"type": "string", "minLength": 3},
                        "provider": {"type": "string"},
                        "duration_seconds": {"type": "integer", "minimum": 1, "maximum": 30, "default": 5},
                        "reference_asset_id": {"type": "integer"},
                        "confirmed": confirmed,
                    },
                    "required": ["project_id", "segment_id", "prompt", "confirmed"],
                },
            }
            for kind in ("image", "gif", "video")
        ],
        {
            "name": "youtube_factory_get_job_status",
            "description": "Lay trang thai cua mot scene generation job.",
            "inputSchema": {"type": "object", "properties": {"job_id": {"type": "integer"}}, "required": ["job_id"]},
        },
        {
            "name": "youtube_factory_approve_scene",
            "description": "Yeu cau AI QC cham lai scene da hoan thanh; chi tra approved khi asset khop prompt.",
            "inputSchema": {"type": "object", "properties": {"job_id": {"type": "integer"}}, "required": ["job_id"]},
        },
        {
            "name": "youtube_factory_build_timeline",
            "description": "Tao timeline tu script va shot plan cua du an.",
            "inputSchema": {
                "type": "object",
                "properties": {"project_id": project_id, "force": {"type": "boolean", "default": False}},
                "required": ["project_id"],
            },
        },
        {
            "name": "youtube_factory_generate_voice",
            "description": "Tao voiceover bat dong bo cho timeline.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": project_id,
                    "provider": {"type": "string", "default": "edge_tts"},
                    "confirmed": confirmed,
                },
                "required": ["project_id", "confirmed"],
            },
        },
        {
            "name": "youtube_factory_render_video",
            "description": "Xep render video bat dong bo; chi nen goi sau khi QC duyet ready_to_render.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": project_id,
                    "provider": {"type": "string", "default": "ffmpeg_builtin"},
                    "force": {"type": "boolean", "default": False},
                    "confirmed": confirmed,
                },
                "required": ["project_id", "confirmed"],
            },
        },
        {
            "name": "youtube_factory_get_render_status",
            "description": "Lay cac production job va render status cua du an.",
            "inputSchema": {"type": "object", "properties": {"project_id": project_id}, "required": ["project_id"]},
        },
    ]


def _tool_definitions() -> list[dict[str, Any]]:
    return astra_mcp_tool_definitions() + _automation_tool_definitions() + [
        {
            "name": "youtube_factory_save_script",
            "description": f"Lưu nguyên văn kịch bản do {CHAT_AGENT_LABEL} vừa viết vào dự án; nếu chưa có project_id thì tạo dự án mới.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "text": {"type": "string", "minLength": 1},
                    "language": {"type": "string", "default": "vi"},
                    "variant": {"type": "string", "enum": ["long", "short"], "default": "long"},
                },
                "required": ["text"],
            },
            "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
        },
        {
            "name": "youtube_factory_update_shot",
            "description": "Sửa lời đọc, prompt hình, loại asset hoặc thời lượng của một cảnh storyboard.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "shot_id": {"type": "integer"},
                    "narration": {"type": "string"},
                    "visual_prompt": {"type": "string"},
                    "asset_type": {"type": "string"},
                    "duration_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
                    "status": {"type": "string", "enum": ["planned", "ready", "done"]},
                },
                "required": ["shot_id"],
            },
            "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
        },
        {
            "name": "youtube_factory_list_projects",
            "description": "Liệt kê các dự án YT Factory đang có để chọn dự án cần sản xuất.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "youtube_factory_get_storyboard",
            "description": "Lấy storyboard, lời đọc và prompt cảnh của một dự án. Trả về thư mục import; hãy lưu ảnh/video đã tạo vào chính thư mục này.",
            "inputSchema": {
                "type": "object",
                "properties": {"project_id": {"type": "integer", "description": "ID dự án YT Factory"}},
                "required": ["project_id"],
            },
        },
        {
            "name": "youtube_factory_import_asset",
            "description": "Upload một asset đã tạo từ thư mục import của dự án và gắn nó vào cảnh storyboard chỉ định.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer"},
                    "segment_id": {"type": "integer", "description": "ID cảnh/timeline segment"},
                    "file_path": {"type": "string", "description": "Đường dẫn tuyệt đối của file trong thư mục import"},
                },
                "required": ["project_id", "segment_id", "file_path"],
            },
        },
        {
            "name": "youtube_factory_import_assets_batch",
            "description": "Upload và gắn nhiều asset vào nhiều cảnh. Mỗi item gồm segment_id và file_path, các file phải nằm trong thư mục import.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"segment_id": {"type": "integer"}, "file_path": {"type": "string"}},
                            "required": ["segment_id", "file_path"],
                        },
                    },
                },
                "required": ["project_id", "items"],
            },
        },
        {
            "name": "youtube_factory_complete_antigravity_scene",
            "description": "Đánh dấu một job ảnh Antigravity hoàn tất. Chỉ gọi sau khi ảnh đã được import; truyền job_id và asset_id mà tool import vừa trả về.",
            "inputSchema": {"type": "object", "properties": {"job_id": {"type": "integer"}, "asset_id": {"type": "integer"}}, "required": ["job_id", "asset_id"]},
        },
    ]


def _text_result(value: Any, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}],
        "isError": is_error,
    }


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name in astra_tool_names():
        # Readiness is the one Astra question that is not about a project:
        # it asks which AI can run at all before a run is started.
        if name == "youtube_factory_get_ai_runtimes":
            return _text_result(_factory_request("/api/orchestrator/runtimes"))
        # Connections belong to the machine, not to a project. What comes back
        # is a status per platform and what a page shows - never a cookie.
        if name == "youtube_factory_list_connections":
            return _text_result(_factory_request("/api/connections?view=capabilities"))
        if name == "youtube_factory_get_connection_status":
            platform = urllib.parse.quote(str(arguments.get("platform") or "").strip(), safe="")
            return _text_result(_factory_request(f"/api/connections/{platform}"))
        if name == "youtube_factory_read_product":
            return _text_result(_json_factory(
                "/api/connections/read",
                {"url": str(arguments.get("url") or "").strip(),
                 "session_id": str(arguments.get("session_id") or "").strip()},
                timeout=240,
            ))
        # Research is not about a project either: it is how a project starts.
        if name == "youtube_factory_search_web":
            query = urllib.parse.quote(str(arguments.get("query") or "").strip(), safe="")
            limit = max(1, min(int(arguments.get("limit") or 5), 10))
            return _text_result(_factory_request(f"/api/research/search?query={query}&limit={limit}"))
        project_id = int(arguments.get("project_id"))
        if name == "youtube_factory_get_project_context":
            return _text_result(_factory_request(f"/api/projects/{project_id}/astra-context"))
        if name == "youtube_factory_get_source_package":
            return _text_result(_factory_request(f"/api/projects/{project_id}/source-package"))
        if name == "youtube_factory_get_project_edit_plan":
            return _text_result(_factory_request(f"/api/projects/{project_id}/edit-plan"))
        if name == "youtube_factory_plan_project_edit":
            motion_policy = urllib.parse.quote(str(arguments.get("motion_policy") or "balanced"), safe="")
            return _text_result(_factory_request(f"/api/projects/{project_id}/edit-plan?motion_policy={motion_policy}", method="POST"))
        if name == "youtube_factory_update_project_edit_scene":
            segment_id = int(arguments.get("segment_id"))
            changes = arguments.get("changes") if isinstance(arguments.get("changes"), dict) else {}
            return _text_result(_json_factory(f"/api/projects/{project_id}/edit-plan/scenes/{segment_id}", changes, method="PATCH"))
        if name == "youtube_factory_approve_project_edit_plan":
            return _text_result(_factory_request(f"/api/projects/{project_id}/edit-plan/approve", method="POST"))
        if name == "youtube_factory_apply_project_edit_plan":
            return _text_result(_factory_request(f"/api/projects/{project_id}/edit-plan/apply", method="POST"))
        if name == "youtube_factory_get_storyboard_required_jobs":
            return _text_result(_factory_request(f"/api/projects/{project_id}/storyboard/required-jobs"))
        if name == "youtube_factory_plan_scene_edit_beats":
            segment_id = int(arguments.get("segment_id"))
            return _text_result(_json_factory(
                f"/api/timeline/{segment_id}/edit-beats/plan",
                {"max_beats": int(arguments.get("max_beats") or 4)},
            ))
        if name == "youtube_factory_apply_scene_edit_beats":
            segment_id = int(arguments.get("segment_id"))
            provider = str(arguments.get("image_provider") or "auto").strip()
            if provider == "auto":
                route = _json_factory(
                    "/api/providers/route",
                    {"project_id": project_id, "capability": "scene.image"},
                )
                provider = str(route.get("selected_provider") or "")
            return _text_result(_json_factory(
                f"/api/timeline/{segment_id}/edit-beats/apply",
                {
                    "image_provider": provider,
                    "ratio": str(arguments.get("ratio") or "1280:720"),
                    "confirmed": bool(arguments.get("confirmed", False)),
                },
            ))
        if name == "youtube_factory_get_scene_speech_timing":
            segment_id = int(arguments.get("segment_id"))
            return _text_result(_factory_request(f"/api/timeline/{segment_id}/speech-timing"))
        if name == "youtube_factory_get_contact_sheet":
            tiles = max(1, min(int(arguments.get("tiles") or 12), 24))
            return _text_result(_factory_request(f"/api/projects/{project_id}/contact-sheet?tiles={tiles}"))
        if name == "youtube_factory_list_steps":
            return _text_result(_factory_request(f"/api/projects/{project_id}/steps"))
        if name == "youtube_factory_run_step":
            step = urllib.parse.quote(str(arguments.get("step") or "").strip(), safe="")
            options = arguments.get("options") if isinstance(arguments.get("options"), dict) else {}
            return _text_result(_json_factory(
                f"/api/projects/{project_id}/steps/{step}", {"options": options},
                timeout=STEP_TIMEOUT_SECONDS,
            ))
        if name == "youtube_factory_get_render_readiness":
            return _text_result(_factory_request(f"/api/projects/{project_id}/render-readiness"))
        if name == "youtube_factory_get_orchestrator_report":
            limit = max(1, min(int(arguments.get("limit") or 200), 1000))
            return _text_result(_factory_request(f"/api/projects/{project_id}/orchestrator-report?limit={limit}"))

    if name == "youtube_factory_get_next_task":
        return _text_result(_json_factory(f"/api/chat-agents/{CHAT_AGENT}/tasks/next", {}))

    if name in {"youtube_factory_complete_task", "youtube_factory_fail_task"}:
        task_id = urllib.parse.quote(str(arguments.get("task_id") or ""), safe="")
        if not task_id:
            raise ValueError("Thiếu task_id")
        if name == "youtube_factory_complete_task":
            payload = {"output": arguments.get("output") if isinstance(arguments.get("output"), dict) else {}}
            action = "complete"
        else:
            payload = {"error": str(arguments.get("error") or "").strip()}
            action = "fail"
        return _text_result(_json_factory(f"/api/chat-agents/{CHAT_AGENT}/tasks/{task_id}/{action}", payload))

    if name in {"youtube_factory_create_project", "youtube_factory_start_pipeline"}:
        payload = {
            "goal": str(arguments.get("goal") or "").strip(),
            "title": str(arguments.get("title") or "").strip(),
            "language": str(arguments.get("language") or "vi").strip(),
            "auto_generate_media": bool(arguments.get("auto_generate_media", False)),
            "auto_render": bool(arguments.get("auto_render", False)),
            "chat_agent": CHAT_AGENT,
        }
        if name == "youtube_factory_start_pipeline":
            payload["project_id"] = int(arguments.get("project_id"))
        return _text_result(_json_factory("/api/automation/pipelines", payload))

    if name == "youtube_factory_get_pipeline_status":
        project_id = int(arguments.get("project_id"))
        return _text_result(_factory_request(f"/api/automation/projects/{project_id}"))

    if name == "youtube_factory_create_agent_task":
        payload = {
            "project_id": int(arguments["project_id"]) if arguments.get("project_id") is not None else None,
            "role": str(arguments.get("role") or ""),
            "task_type": str(arguments.get("task_type") or "manual"),
            "input": arguments.get("input") if isinstance(arguments.get("input"), dict) else {},
            "assigned_agent": str(arguments.get("assigned_agent") or ""),
            "reviewer_agent": str(arguments.get("reviewer_agent") or ""),
        }
        return _text_result(_json_factory("/api/agent-tasks", payload))

    if name == "youtube_factory_list_agent_tasks":
        query = {
            key: value for key, value in {
                "project_id": arguments.get("project_id"),
                "status": arguments.get("status"),
                "role": arguments.get("role"),
            }.items() if value not in (None, "")
        }
        suffix = f"?{urllib.parse.urlencode(query)}" if query else ""
        return _text_result({"tasks": _factory_request(f"/api/agent-tasks{suffix}")})

    if name == "youtube_factory_list_events":
        query = {
            key: value for key, value in {
                "project_id": arguments.get("project_id"),
                "after_id": arguments.get("after_id", 0),
            }.items() if value is not None
        }
        return _text_result({"events": _factory_request(f"/api/events?{urllib.parse.urlencode(query)}")})

    if name == "youtube_factory_list_providers":
        return _text_result(_factory_request("/api/providers/catalog"))

    if name == "youtube_factory_route_provider":
        payload = {"capability": str(arguments.get("capability") or "")}
        if arguments.get("project_id") is not None:
            payload["project_id"] = int(arguments["project_id"])
        return _text_result(_json_factory("/api/providers/route", payload))

    if name in {
        "youtube_factory_generate_image",
        "youtube_factory_generate_gif",
        "youtube_factory_generate_video",
    }:
        kind = name.rsplit("_", 1)[-1]
        capability = {
            "image": "scene.image",
            "gif": "scene.animated_image",
            "video": "scene.video",
        }[kind]
        project_id = int(arguments.get("project_id"))
        provider = str(arguments.get("provider") or "").strip()
        if not provider:
            route = _json_factory(
                "/api/providers/route",
                {"project_id": project_id, "capability": capability},
            )
            provider = str(route.get("selected_provider") or "")
        reference_asset_id = arguments.get("reference_asset_id")
        if kind == "video" and reference_asset_id is None:
            raise ValueError("Tao video bat buoc co reference_asset_id cua anh scene da duoc duyet")
        payload = {
            "timeline_segment_id": int(arguments.get("segment_id")),
            "provider": provider,
            "prompt": str(arguments.get("prompt") or ""),
            "duration_seconds": int(arguments.get("duration_seconds") or 5),
            "reference_asset_id": int(reference_asset_id) if reference_asset_id is not None else None,
            "requires_reference_image": kind == "video",
            "motion_as_gif": kind == "gif",
            "confirmed": bool(arguments.get("confirmed", False)),
        }
        return _text_result(_json_factory(f"/api/projects/{project_id}/scene-jobs", payload))

    if name == "youtube_factory_get_job_status":
        return _text_result(_factory_request(f"/api/scene-jobs/{int(arguments.get('job_id'))}"))

    if name == "youtube_factory_approve_scene":
        result = _json_factory(f"/api/scene-jobs/{int(arguments.get('job_id'))}/review", {})
        review = result.get("review") if isinstance(result, dict) else {}
        return _text_result({**result, "approved": bool((review or {}).get("matches"))})

    if name == "youtube_factory_build_timeline":
        project_id = int(arguments.get("project_id"))
        return _text_result(
            _json_factory(
                f"/api/projects/{project_id}/timeline/generate",
                {"force": bool(arguments.get("force", False))},
            )
        )

    if name in {"youtube_factory_generate_voice", "youtube_factory_render_video"}:
        project_id = int(arguments.get("project_id"))
        is_render = name == "youtube_factory_render_video"
        payload = {
            "job_type": "render" if is_render else "voiceover",
            "provider": str(arguments.get("provider") or ("ffmpeg_builtin" if is_render else "edge_tts")),
            "confirmed": bool(arguments.get("confirmed", False)),
            "force": bool(arguments.get("force", False)),
        }
        return _text_result(_json_factory(f"/api/projects/{project_id}/jobs", payload))

    if name == "youtube_factory_get_render_status":
        project_id = int(arguments.get("project_id"))
        jobs = _factory_request(f"/api/projects/{project_id}/jobs")
        render_jobs = [job for job in jobs if isinstance(job, dict) and job.get("job_type") == "render"]
        return _text_result({"project_id": project_id, "render_jobs": render_jobs, "all_jobs": jobs})

    if name == "youtube_factory_save_script":
        payload = {
            "project_id": int(arguments["project_id"]) if arguments.get("project_id") is not None else None,
            "title": str(arguments.get("title") or "").strip(),
            "text": str(arguments.get("text") or "").strip(),
            "language": str(arguments.get("language") or "vi").strip(),
            "variant": str(arguments.get("variant") or "long").strip(),
            "workflow": "content",
        }
        return _text_result(_json_factory("/api/scripts/import", payload))

    if name == "youtube_factory_update_shot":
        shot_id = int(arguments.get("shot_id"))
        payload = {
            key: arguments[key]
            for key in ("narration", "visual_prompt", "asset_type", "duration_seconds", "status")
            if key in arguments
        }
        return _text_result(_json_factory(f"/api/shots/{shot_id}", payload, method="PATCH"))

    if name == "youtube_factory_list_projects":
        projects = _factory_request("/api/projects")
        compact = [
            {key: project.get(key) for key in ("id", "title", "status", "updated_at")}
            for project in projects
            if isinstance(project, dict)
        ]
        return _text_result({"projects": compact})

    if name == "youtube_factory_complete_antigravity_scene":
        job_id = int(arguments.get("job_id"))
        asset_id = int(arguments.get("asset_id"))
        completed = _factory_request(f"/api/antigravity/scene-jobs/{job_id}/complete?asset_id={asset_id}", method="POST")
        return _text_result(completed)

    project_id = int(arguments.get("project_id"))
    if name == "youtube_factory_get_storyboard":
        project = _factory_request(f"/api/projects/{project_id}")
        timeline = _factory_request(f"/api/projects/{project_id}/timeline")
        script = _factory_request(f"/api/projects/{project_id}/script")
        return _text_result(
            {
                "project": project,
                "script": script,
                "timeline": timeline,
                "import_folder": str(_drop_folder(project_id)),
                "instruction": "Tạo media theo prompt của từng cảnh, lưu file vào import_folder, rồi gọi youtube_factory_import_asset với segment_id tương ứng.",
            }
        )

    if name in {"youtube_factory_import_asset", "youtube_factory_import_assets_batch"}:
        raw_items = (
            [{"segment_id": arguments.get("segment_id"), "file_path": arguments.get("file_path")}]
            if name == "youtube_factory_import_asset"
            else arguments.get("items")
        )
        if not isinstance(raw_items, list) or not raw_items:
            raise ValueError("Cần ít nhất một asset để import")
        imported: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                raise ValueError("Mỗi item import phải là object")
            segment_id = int(item.get("segment_id"))
            source = _safe_generated_file(project_id, str(item.get("file_path") or ""))
            upload = _multipart_upload(project_id, source, _asset_type(source))
            asset = upload["asset"]
            attached = _factory_request(
                f"/api/timeline/{segment_id}/attach-asset",
                method="POST",
                data=json.dumps({"asset_id": asset["id"]}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            imported.append({"segment_id": segment_id, "asset": asset, "attached": attached})
        return _text_result({"status": "imported", "items": imported})

    raise ValueError(f"Không có tool MCP: {name}")


def _call_key(name: str, arguments: dict[str, Any]) -> str:
    return json.dumps({"tool": name, "arguments": arguments}, sort_keys=True, ensure_ascii=False)


def _read_agent_log() -> list[dict[str, Any]]:
    path = Path(AGENT_RUN_LOG)
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            entries.append(item)
    return entries


def _append_agent_log(entry: dict[str, Any]) -> None:
    path = Path(AGENT_RUN_LOG)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"round": AGENT_ROUND, "at": time.time(), **entry}, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        # The log is read after a failed run; it must never hold a credential.
        handle.write(redact(line) + "\n")


def _state_fingerprint(project_id: int) -> str:
    """What the project has actually got, reduced to a comparable token.

    "The conditions have not changed" is decided on this: the steps that are
    done and the state of every step, read from the app.
    """
    if not project_id:
        return ""
    try:
        state = _factory_request(f"/api/projects/{project_id}/steps")
    except RuntimeError:
        return ""
    shape = [state.get("done"), [(row.get("key"), row.get("state")) for row in state.get("steps") or []]]
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _refuse_guarded(name: str, arguments: dict[str, Any]) -> None:
    """The actions an agent run may not take on its own.

    Nothing in the tool set deletes; what can undo someone's work is `force`,
    which rebuilds a script, scene list, timeline or render over what is there -
    possibly after a person edited it. Spending and publishing are the other
    two. Ordinary steps need none of these, so they are not slowed down.
    """
    options = arguments.get("options") if isinstance(arguments.get("options"), dict) else {}
    if (arguments.get("force") or options.get("force")) and not AGENT_ALLOW_OVERWRITE:
        raise ValueError(
            "force ghi đè dữ liệu đã có (kịch bản/cảnh/timeline/bản dựng có thể đã được người dùng sửa), "
            "và lượt chạy này không được phép ghi đè. Nếu bước bị từ chối vì dữ liệu cũ, báo blocked và nói rõ."
        )
    _refuse_spending(name, arguments)


def _refuse_spending(name: str, arguments: dict[str, Any]) -> None:
    if name == "youtube_factory_run_step":
        options = arguments.get("options") if isinstance(arguments.get("options"), dict) else {}
        if options.get("confirmed_publish"):
            raise ValueError("Lượt chạy tự động không được đăng video: đăng lên kênh luôn cần người dùng duyệt.")
        step = step_catalog.get(str(arguments.get("step") or ""))
        if step is not None and step.spends and step.key != "publish" and not AGENT_ALLOW_SPEND:
            raise ValueError(
                f"Bước '{step.label}' tiêu lượt tạo/quota, và lượt chạy này không được phép tiêu. "
                "Báo blocked kèm lý do; đừng tìm đường vòng."
            )
        return
    if arguments.get("confirmed") and not AGENT_ALLOW_SPEND:
        raise ValueError("Tool này tiêu lượt tạo/quota, và lượt chạy này không được phép tiêu. Báo blocked kèm lý do.")


def _agent_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """One tool call on behalf of an agent the app started, with its guards.

    The guards are here rather than in the prompt because a prompt can be
    ignored: the budget of a round, the one project the run is about, no
    spending unless allowed, and no identical retry of a call that already
    failed while the project is exactly as it was.
    """
    if name in _CHAT_QUEUE_TOOLS:
        raise ValueError("Tool này thuộc hàng đợi của app chat; lượt chạy của app không dùng nó.")
    log = _read_agent_log()
    used = sum(1 for entry in log if entry.get("round") == AGENT_ROUND)
    if used >= AGENT_TOOL_BUDGET:
        raise ValueError(
            f"Đã dùng hết {AGENT_TOOL_BUDGET} lần gọi tool của vòng này. Dừng lại và trả báo cáo: "
            "đã làm gì, còn thiếu gì."
        )
    raw_project = arguments.get("project_id")
    if AGENT_PROJECT_ID and raw_project not in (None, "") and int(raw_project) != AGENT_PROJECT_ID:
        raise ValueError(f"Lượt chạy này chỉ làm việc trên dự án {AGENT_PROJECT_ID}.")
    project_id = AGENT_PROJECT_ID or int(raw_project or 0)
    key = _call_key(name, arguments)
    try:
        _refuse_guarded(name, arguments)
    except ValueError as exc:
        _append_agent_log({"tool": name, "arguments": arguments, "key": key, "ok": False,
                           "refused": "guard", "error": str(exc)})
        raise
    # Only calls that actually ran and failed count. A call refused by policy
    # never reached the app, so it says nothing about whether it would work.
    failures = [
        entry for entry in log
        if entry.get("key") == key and not entry.get("ok") and not entry.get("refused")
    ]
    if failures:
        previous = failures[-1]
        now = _state_fingerprint(project_id)
        if now == str(previous.get("fingerprint") or ""):
            message = (
                f"Lệnh này đã được gọi y hệt và thất bại: {str(previous.get('error') or '')[:500]}. "
                "Trạng thái dự án chưa đổi kể từ đó, nên gọi lại y hệt sẽ ra cùng kết quả. "
                "Chọn cách khác: chạy bước tiên quyết, đổi tham số hoặc provider, hoặc báo blocked."
            )
            _append_agent_log({"tool": name, "arguments": arguments, "key": key, "ok": False,
                               "refused": "identical_retry", "error": message, "fingerprint": now})
            raise ValueError(message)
    try:
        result = _call_tool(name, arguments)
    except (RuntimeError, ValueError, TypeError) as exc:
        _append_agent_log({"tool": name, "arguments": arguments, "key": key, "ok": False,
                           "error": str(exc)[:2000], "fingerprint": _state_fingerprint(project_id)})
        raise
    text = "".join(str(part.get("text") or "") for part in result.get("content") or [])
    _append_agent_log({"tool": name, "arguments": arguments, "key": key, "ok": not result.get("isError"),
                       "result": text[:800]})
    return result


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        # Announced here as well as on tools/list. A client that connects and
        # then sits idle was reported as "not connected" until it happened to
        # touch a tool, so the one screen that says whether the desktop app is
        # reachable answered no while it was plainly attached.
        _report_chat_contact()
        requested_version = str((message.get("params") or {}).get("protocolVersion") or "2025-03-26")
        return _json_response(
            request_id,
            {
                "protocolVersion": requested_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "youtube-ai-factory", "version": "1.0.0"},
                "instructions": SERVER_INSTRUCTIONS,
            },
        )
    if method == "tools/list":
        _report_chat_contact()
        tools = _tool_definitions()
        if _agent_mode():
            tools = [tool for tool in tools if tool["name"] not in _CHAT_QUEUE_TOOLS]
        return _json_response(request_id, {"tools": tools})
    if method == "tools/call":
        _report_chat_contact()
        params = message.get("params") or {}
        call = _agent_call if _agent_mode() else _call_tool
        try:
            result = call(str(params.get("name") or ""), params.get("arguments") or {})
        except (RuntimeError, ValueError, TypeError) as exc:
            result = _text_result({"error": str(exc)}, is_error=True)
        return _json_response(request_id, result)
    if request_id is not None:
        return _json_error(request_id, -32601, f"Method not found: {method}")
    return None


def main() -> int:
    # MCP clients communicate using UTF-8.  Windows PowerShell may otherwise
    # inherit cp1252 and fail when a Vietnamese tool description is returned.
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("JSON-RPC request phải là object")
            response = _handle(message)
        except (ValueError, json.JSONDecodeError) as exc:
            response = _json_error(None, -32700, str(exc))
        except Exception as exc:  # never let a client request terminate the bridge
            response = _json_error(None, -32603, f"Lỗi bridge: {exc}")
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
