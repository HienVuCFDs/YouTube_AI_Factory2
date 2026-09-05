from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from .. import settings
from ..oauth import OAuthError
from ..oauth import build_authorize_url as build_oauth_authorize_url
from ..oauth import disconnect as oauth_disconnect
from ..oauth import exchange_code as oauth_exchange_code
from ..oauth import status as oauth_status
from ..publisher import PublisherError

# Deferred import: see routes_system.py for why this is safe (main.py has
# already defined its singletons by the time this router is included).
from ..main import _api_error, publisher_worker

router = APIRouter()


class YouTubeOAuthConfigRequest(BaseModel):
    client_id: str | None = Field(default=None, max_length=500)
    client_secret: str | None = Field(default=None, max_length=500)
    redirect_uri: str | None = Field(default=None, max_length=500)
    clear: bool = False


@router.get("/api/oauth/youtube/status")
def youtube_oauth_status(managed_channel_id: int | None = Query(default=None, ge=1)) -> dict[str, Any]:
    """Whether one channel can publish; without an id, the app-wide account."""
    return oauth_status(managed_channel_id)


@router.get("/api/oauth/youtube/channels")
def youtube_oauth_channels() -> dict[str, Any]:
    try:
        return {"channels": publisher_worker.publisher.list_authorized_channels()}
    except (OAuthError, PublisherError) as exc:
        raise _api_error(exc) from exc


@router.post("/api/oauth/youtube/config")
def configure_youtube_oauth(payload: YouTubeOAuthConfigRequest) -> dict[str, Any]:
    if payload.clear:
        values = {
            "GOOGLE_OAUTH_CLIENT_ID": "",
            "GOOGLE_OAUTH_CLIENT_SECRET": "",
        }
        try:
            settings.save_integration_values(values)
            oauth_disconnect()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return oauth_status()

    values: dict[str, str] = {}
    if payload.client_id and payload.client_id.strip():
        values["GOOGLE_OAUTH_CLIENT_ID"] = payload.client_id.strip()
    if payload.client_secret and payload.client_secret.strip():
        values["GOOGLE_OAUTH_CLIENT_SECRET"] = payload.client_secret.strip()
    if payload.redirect_uri and payload.redirect_uri.strip():
        redirect_uri = payload.redirect_uri.strip()
        parsed = urlparse(redirect_uri)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise HTTPException(status_code=400, detail="Redirect URI local phai dung http://127.0.0.1 hoac http://localhost")
        values["GOOGLE_OAUTH_REDIRECT_URI"] = redirect_uri
    if not values:
        raise HTTPException(status_code=400, detail="Hay nhap Client ID, Client Secret hoac Redirect URI")
    try:
        settings.save_integration_values(values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return oauth_status()


@router.get("/oauth/youtube/authorize")
def youtube_oauth_authorize() -> RedirectResponse:
    try:
        url = build_oauth_authorize_url()
    except OAuthError as exc:
        raise _api_error(exc) from exc
    return RedirectResponse(url)


@router.get("/oauth/youtube/callback", response_class=HTMLResponse)
def youtube_oauth_callback(
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    state: str | None = Query(default=None),
) -> HTMLResponse:
    if error:
        return HTMLResponse(f"<p>Kết nối YouTube OAuth thất bại: {error}. Bạn có thể đóng tab này.</p>", status_code=400)
    if not code:
        return HTMLResponse("<p>Thiếu mã xác thực từ Google. Bạn có thể đóng tab này.</p>", status_code=400)
    try:
        oauth_exchange_code(code, state)
    except OAuthError as exc:
        return HTMLResponse(f"<p>Kết nối YouTube OAuth thất bại: {exc}</p>", status_code=400)
    return HTMLResponse(
        "<p>Đã kết nối YouTube OAuth thành công. Bạn có thể đóng tab này và quay lại ứng dụng.</p>"
    )


@router.post("/api/oauth/youtube/disconnect")
def youtube_oauth_disconnect() -> dict[str, Any]:
    oauth_disconnect(managed_channel_id)
    return oauth_status()
