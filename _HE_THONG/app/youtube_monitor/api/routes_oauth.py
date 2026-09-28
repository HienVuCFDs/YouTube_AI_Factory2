from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import shutil
from ..oauth import token_path as oauth_token_path
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
from ..main import _api_error, database, publisher_worker

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
def youtube_oauth_channels(
    managed_channel_id: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    """The YouTube channels this sign-in can post to."""
    try:
        return {
            "managed_channel_id": managed_channel_id,
            "channels": publisher_worker.publisher.list_authorized_channels(managed_channel_id),
        }
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
        managed_channel_id = oauth_exchange_code(code, state)
    except OAuthError as exc:
        return HTMLResponse(f"<p>Kết nối YouTube OAuth thất bại: {exc}</p>", status_code=400)

    # A sign-in that named no channel is one started from "add a channel":
    # the account has just told us which channel it granted, so that becomes
    # the row rather than something the user types in beforehand.
    note = ""
    if managed_channel_id is None:
        try:
            note = _adopt_signed_in_channel()
        except (OAuthError, PublisherError) as exc:
            note = f"<p>Đã đăng nhập, nhưng chưa đọc được tên kênh: {exc}</p>"
    return HTMLResponse(
        "<p>Đã kết nối YouTube thành công. Bạn có thể đóng tab này và quay lại ứng dụng.</p>"
        + note
    )


def _find_existing_channel(youtube_id: str, handle: str) -> dict[str, Any] | None:
    """The row this YouTube channel already has, however it was added.

    Rows created by hand before sign-in existed carry a URL and no id - and
    that URL almost always contains the id, because it was copied from
    YouTube. Matching on it avoids making a second row for a channel the user
    already set up, and leaving the first one borrowing the shared account.
    """
    channels = database.list_managed_channels()
    for item in channels:
        if str(item.get("youtube_channel_id") or "").strip() == youtube_id:
            return item
    if not youtube_id:
        return None
    for item in channels:
        url = str(item.get("channel_url") or "")
        if youtube_id in url:
            return item
        if handle and handle.lstrip("@") and handle.lstrip("@").lower() in url.lower():
            return item
    return None


def _adopt_signed_in_channel() -> str:
    """Turn the just-authorised YouTube channel into a channel of its own.

    One consent grants one channel, so whatever comes back is the channel the
    user picked on Google's own screen - a more reliable answer than a name
    typed from memory, and it carries the real id and URL.
    """
    found = publisher_worker.publisher.list_authorized_channels()
    if not found:
        return "<p>Tài khoản này không có kênh YouTube nào.</p>"
    channel = found[0]
    youtube_id = str(channel.get("id") or "")
    title = str(channel.get("title") or "Kênh YouTube")
    handle = str(channel.get("handle") or "")
    url = (
        f"https://www.youtube.com/{handle}" if handle.startswith("@")
        else f"https://www.youtube.com/channel/{youtube_id}"
    )

    existing = _find_existing_channel(youtube_id, handle)
    if existing:
        # Re-authorising a channel already known: keep the row, and fill in
        # the id if it was added by hand without one.
        target_id = int(existing["id"])
        if not str(existing.get("youtube_channel_id") or "").strip():
            database.update_managed_channel(target_id, youtube_channel_id=youtube_id)
        action = "cập nhật đăng nhập cho"
    else:
        created = database.create_managed_channel(
            name=title,
            channel_url=url,
            youtube_channel_id=youtube_id,
            platform="youtube",
        )
        if not created:
            return "<p>Đã đăng nhập, nhưng không tạo được kênh trong app.</p>"
        target_id = int(created["id"])
        action = "thêm"

    shutil.move(str(oauth_token_path(None)), str(oauth_token_path(target_id)))
    return f"<p>Đã {action} kênh <b>{title}</b>. Quay lại app và làm mới danh sách kênh.</p>"


@router.post("/api/oauth/youtube/disconnect")
def youtube_oauth_disconnect(
    managed_channel_id: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    """Disconnect only the account the user selected, not every channel."""
    oauth_disconnect(managed_channel_id)
    return oauth_status(managed_channel_id)
