from __future__ import annotations

import hmac
import json
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from .settings import OAUTH_TOKEN_PATH


AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"


class OAuthError(RuntimeError):
    pass


def _oauth_config() -> tuple[str, str, str]:
    return (
        os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip(),
        os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip(),
        os.getenv(
            "GOOGLE_OAUTH_REDIRECT_URI",
            "http://127.0.0.1:8787/oauth/youtube/callback",
        ).strip(),
    )


def _state_path():
    return OAUTH_TOKEN_PATH.with_name("oauth_state.json")


def _save_state(state: str) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"state": state, "created_at": time.time()}), encoding="utf-8")


def _consume_state(state: str | None) -> bool:
    path = _state_path()
    if not state or not path.exists():
        return False
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        expected = str(saved.get("state") or "")
        created_at = float(saved.get("created_at") or 0)
    except (ValueError, TypeError):
        expected = ""
        created_at = 0
    try:
        path.unlink()
    except OSError:
        pass
    return bool(expected and time.time() - created_at <= 600 and hmac.compare_digest(expected, state))


def is_configured() -> bool:
    client_id, client_secret, _ = _oauth_config()
    return bool(client_id and client_secret)


def build_authorize_url() -> str:
    if not is_configured():
        raise OAuthError(
            "Thiếu GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET. Hãy tạo OAuth Client ID "
            "(loại Desktop app) trên Google Cloud Console rồi thêm vào .env."
        )
    client_id, _, redirect_uri = _oauth_config()
    state = secrets.token_urlsafe(32)
    _save_state(state)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def _load_token() -> dict[str, Any] | None:
    if not OAUTH_TOKEN_PATH.exists():
        return None
    try:
        return json.loads(OAUTH_TOKEN_PATH.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _save_token(token: dict[str, Any]) -> None:
    OAUTH_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    OAUTH_TOKEN_PATH.write_text(json.dumps(token, ensure_ascii=False, indent=2), encoding="utf-8")


def disconnect() -> None:
    if OAUTH_TOKEN_PATH.exists():
        OAUTH_TOKEN_PATH.unlink()
    state_path = _state_path()
    if state_path.exists():
        state_path.unlink()


def exchange_code(code: str, state: str | None = None) -> None:
    if not is_configured():
        raise OAuthError("Thiếu cấu hình OAuth trong .env")
    if not _consume_state(state):
        raise OAuthError("OAuth state không hợp lệ hoặc đã hết hạn. Hãy bắt đầu kết nối lại.")
    client_id, client_secret, redirect_uri = _oauth_config()
    try:
        response = httpx.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=30.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise OAuthError(f"Đổi mã xác thực thất bại: {exc}") from exc

    payload = response.json()
    token: dict[str, Any] = {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token"),
        "expires_at": time.time() + payload.get("expires_in", 3600) - 60,
        "scope": payload.get("scope", ""),
    }
    existing = _load_token()
    if not token["refresh_token"] and existing and existing.get("refresh_token"):
        # Google only returns a refresh_token on the very first consent grant.
        token["refresh_token"] = existing["refresh_token"]
    _save_token(token)


def _refresh(token: dict[str, Any]) -> dict[str, Any]:
    if not token.get("refresh_token"):
        raise OAuthError("Không có refresh_token đã lưu. Hãy kết nối lại YouTube OAuth.")
    client_id, client_secret, _ = _oauth_config()
    try:
        response = httpx.post(
            TOKEN_ENDPOINT,
            data={
                "refresh_token": token["refresh_token"],
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
            timeout=30.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise OAuthError(f"Làm mới access token thất bại: {exc}") from exc

    payload = response.json()
    token["access_token"] = payload["access_token"]
    token["expires_at"] = time.time() + payload.get("expires_in", 3600) - 60
    _save_token(token)
    return token


def get_access_token() -> str:
    token = _load_token()
    if not token:
        raise OAuthError("Chưa kết nối YouTube OAuth.")
    if time.time() >= token.get("expires_at", 0):
        token = _refresh(token)
    return str(token["access_token"])


def status() -> dict[str, Any]:
    token = _load_token()
    client_id, client_secret, redirect_uri = _oauth_config()
    return {
        "configured": bool(client_id and client_secret),
        "connected": bool(token and token.get("refresh_token")),
        "client_id_configured": bool(client_id),
        "client_id_hint": f"{client_id[:8]}..." if client_id else "",
        "redirect_uri": redirect_uri,
    }
