"""Local MCP bridge for desktop AI tools and YouTube AI Factory.

This is intentionally dependency-free: Claude Desktop, MiniMax Design or another
MCP client starts this process over stdio.  The process never reads browser
profiles, application tokens, or cloud credentials.  It talks only to the local
YouTube AI Factory HTTP server and only imports media from a project drop folder.

Run by an MCP client, not by the user directly::

    C:\\Program Files\\Python313\\python.exe ai_desktop_mcp.py
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


FACTORY_URL = os.getenv("YOUTUBE_FACTORY_URL", "http://127.0.0.1:8787").rstrip("/")
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


def _factory_request(path: str, method: str = "GET", data: bytes | None = None, headers: dict[str, str] | None = None) -> Any:
    request = urllib.request.Request(
        f"{FACTORY_URL}{path}", data=data, method=method, headers=headers or {}
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
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


def _tool_definitions() -> list[dict[str, Any]]:
    return [
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


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        requested_version = str((message.get("params") or {}).get("protocolVersion") or "2025-03-26")
        return _json_response(
            request_id,
            {
                "protocolVersion": requested_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "youtube-ai-factory", "version": "1.0.0"},
            },
        )
    if method == "tools/list":
        return _json_response(request_id, {"tools": _tool_definitions()})
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            result = _call_tool(str(params.get("name") or ""), params.get("arguments") or {})
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
