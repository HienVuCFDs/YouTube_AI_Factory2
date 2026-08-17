from __future__ import annotations

import json
import time
import urllib.request
from http.cookiejar import Cookie, MozillaCookieJar
from pathlib import Path
from typing import Any


class CocCocSessionError(RuntimeError):
    pass


_ALLOWED_COOKIE_DOMAINS = ("youtube.com", "google.com", "googleusercontent.com", "ytimg.com")


def _is_youtube_related(domain: str) -> bool:
    host = str(domain or "").lstrip(".").lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in _ALLOWED_COOKIE_DOMAINS)


def _browser_debugger_url() -> str:
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise CocCocSessionError(
            "Chưa có phiên Cốc Cốc cục bộ sẵn sàng. Hãy mở Cốc Cốc qua chế độ kết nối của app rồi thử lại."
        ) from exc
    url = str(payload.get("webSocketDebuggerUrl") or "").strip()
    if not url:
        raise CocCocSessionError("Cốc Cốc không cung cấp cổng điều khiển phiên cục bộ")
    return url


def _fetch_cookies() -> list[dict[str, Any]]:
    try:
        import websocket
    except ImportError as exc:
        raise CocCocSessionError("Thiếu websocket-client để kết nối Cốc Cốc") from exc
    try:
        connection = websocket.create_connection(_browser_debugger_url(), timeout=10, origin="http://127.0.0.1")
        try:
            next_id = 1

            def call(method: str, params: dict[str, Any] | None = None, session_id: str = "") -> dict[str, Any]:
                nonlocal next_id
                request_id = next_id
                next_id += 1
                request: dict[str, Any] = {"id": request_id, "method": method}
                if params:
                    request["params"] = params
                if session_id:
                    request["sessionId"] = session_id
                connection.send(json.dumps(request))
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    message = json.loads(connection.recv())
                    if message.get("id") == request_id:
                        if message.get("error"):
                            raise CocCocSessionError(f"Cốc Cốc từ chối {method}")
                        return dict(message.get("result", {}))
                raise CocCocSessionError(f"Cốc Cốc không phản hồi {method}")

            # Query only cookies whose URL explicitly belongs to YouTube/Google.
            # It never requests browser-wide cookie storage.
            target_id = str(call("Target.createTarget", {"url": "https://www.youtube.com"}).get("targetId") or "")
            if not target_id:
                raise CocCocSessionError("Không tạo được tab YouTube nội bộ")
            try:
                session_id = str(call("Target.attachToTarget", {"targetId": target_id, "flatten": True}).get("sessionId") or "")
                if not session_id:
                    raise CocCocSessionError("Không kết nối được tab YouTube nội bộ")
                call("Network.enable", session_id=session_id)
                response = call(
                    "Network.getCookies",
                    {
                        "urls": [
                            "https://www.youtube.com",
                            "https://accounts.google.com",
                            "https://www.google.com",
                        ]
                    },
                    session_id=session_id,
                )
                return list(response.get("cookies", []))
            finally:
                call("Target.closeTarget", {"targetId": target_id})
        finally:
            connection.close()
    except Exception as exc:
        raise CocCocSessionError("Không đọc được phiên YouTube từ Cốc Cốc cục bộ") from exc
    raise CocCocSessionError("Cốc Cốc không phản hồi danh sách cookie")


def write_youtube_cookie_file(output_path: Path) -> Path:
    """Write only YouTube/Google cookies to a temporary Netscape cookie file.

    The caller owns and deletes ``output_path`` after yt-dlp finishes.  Cookie
    values are never returned, logged, or saved inside the project.
    """
    jar = MozillaCookieJar(str(output_path))
    count = 0
    for raw in _fetch_cookies():
        domain = str(raw.get("domain") or "")
        if not _is_youtube_related(domain):
            continue
        expires = raw.get("expires")
        expires_at = int(expires) if isinstance(expires, (int, float)) and expires > 0 else None
        cookie = Cookie(
            version=0,
            name=str(raw.get("name") or ""),
            value=str(raw.get("value") or ""),
            port=None,
            port_specified=False,
            domain=domain,
            domain_specified=bool(domain),
            domain_initial_dot=domain.startswith("."),
            path=str(raw.get("path") or "/"),
            path_specified=True,
            secure=bool(raw.get("secure")),
            expires=expires_at,
            discard=expires_at is None,
            comment=None,
            comment_url=None,
            rest={"HttpOnly": None} if raw.get("httpOnly") else {},
            rfc2109=False,
        )
        if cookie.name:
            jar.set_cookie(cookie)
            count += 1
    if not count:
        raise CocCocSessionError("Không tìm thấy cookie YouTube/Google trong profile Cốc Cốc hiện tại")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    jar.save(ignore_discard=True, ignore_expires=True)
    return output_path
