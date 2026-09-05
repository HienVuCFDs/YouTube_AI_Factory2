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


def token_path(managed_channel_id: int | None = None):
    """Where one account's token lives.

    None means the app-wide account - the file that existed before channels
    could be linked one at a time. Keeping it as the fallback is what lets an
    already-connected setup carry on unchanged.
    """
    if not managed_channel_id:
        return OAUTH_TOKEN_PATH
    return OAUTH_TOKEN_PATH.with_name(f"{OAUTH_TOKEN_PATH.stem}-channel-{int(managed_channel_id)}.json")


def _state_path():
    return OAUTH_TOKEN_PATH.with_name("oauth_state.json")


def _save_state(state: str, managed_channel_id: int | None = None) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # The channel travels with the state through Google and back, because the
    # callback has nothing else to say which account was being linked.
    path.write_text(
        json.dumps({
            "state": state,
            "created_at": time.time(),
            "managed_channel_id": int(managed_channel_id) if managed_channel_id else None,
        }),
        encoding="utf-8",
    )


def _consume_state(state: str | None) -> tuple[bool, int | None]:
    """Check the round trip, and recover which channel it was for."""
    path = _state_path()
    if not state or not path.exists():
        return False, None
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        expected = str(saved.get("state") or "")
        created_at = float(saved.get("created_at") or 0)
        channel_id = saved.get("managed_channel_id")
    except (ValueError, TypeError):
        expected = ""
        created_at = 0
        channel_id = None
    try:
        path.unlink()
    except OSError:
        pass
    valid = bool(expected and time.time() - created_at <= 600 and hmac.compare_digest(expected, state))
    return valid, (int(channel_id) if valid and channel_id else None)


def is_configured() -> bool:
    client_id, client_secret, _ = _oauth_config()
    return bool(client_id and client_secret)


def build_authorize_url(managed_channel_id: int | None = None) -> str:
    """Send the user to Google to sign in, for one channel or for the app."""
    if not is_configured():
        raise OAuthError(
            "Thiếu GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET. Hãy tạo OAuth Client ID "
            "(loại Desktop app) trên Google Cloud Console, rồi dán vào mục "
            "Cài đặt · Kết nối · Kết nối YouTube."
        )
    client_id, _, redirect_uri = _oauth_config()
    state = secrets.token_urlsafe(32)
    _save_state(state, managed_channel_id)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        # select_account as well as consent: linking a second channel has to be
        # able to pick a different Google account. With consent alone Google
        # reuses whoever the browser is signed in as, and the new channel
        # silently ends up on the previous channel's account.
        "prompt": "select_account consent",
        "state": state,
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def _load_token(managed_channel_id: int | None = None) -> dict[str, Any] | None:
    """This channel's token, falling back to the app-wide one.

    The fallback is what keeps a single-channel setup working: a channel that
    was never linked separately uses the account the app already has.
    """
    for path in _token_candidates(managed_channel_id):
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
    return None


def _token_candidates(managed_channel_id: int | None):
    if managed_channel_id:
        return [token_path(managed_channel_id), OAUTH_TOKEN_PATH]
    return [OAUTH_TOKEN_PATH]


def has_own_token(managed_channel_id: int | None) -> bool:
    """Whether this channel is signed in as itself rather than borrowing."""
    return bool(managed_channel_id) and token_path(managed_channel_id).exists()


def _save_token(token: dict[str, Any], managed_channel_id: int | None = None) -> None:
    path = token_path(managed_channel_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(token, ensure_ascii=False, indent=2), encoding="utf-8")


def disconnect(managed_channel_id: int | None = None) -> None:
    """Sign one channel out, or the app-wide account when none is named."""
    path = token_path(managed_channel_id)
    if path.exists():
        path.unlink()
    if managed_channel_id:
        return
    state_path = _state_path()
    if state_path.exists():
        state_path.unlink()


def exchange_code(code: str, state: str | None = None) -> int | None:
    """Finish the sign-in, and return the channel it was for."""
    if not is_configured():
        raise OAuthError("Thiếu cấu hình OAuth")
    valid, managed_channel_id = _consume_state(state)
    if not valid:
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
    # This channel's own previous token, never another channel's: borrowing a
    # refresh token across accounts would refresh into the wrong one.
    existing = None
    own = token_path(managed_channel_id)
    if own.exists():
        try:
            existing = json.loads(own.read_text(encoding="utf-8"))
        except ValueError:
            existing = None
    if not token["refresh_token"] and existing and existing.get("refresh_token"):
        # Google only returns a refresh_token on the very first consent grant.
        token["refresh_token"] = existing["refresh_token"]
    _save_token(token, managed_channel_id)
    return managed_channel_id


def _refresh(token: dict[str, Any], managed_channel_id: int | None = None) -> dict[str, Any]:
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
    # Written back where it was read from. Refreshing a borrowed app-wide
    # token must not create a per-channel copy that then drifts.
    _save_token(token, managed_channel_id if has_own_token(managed_channel_id) else None)
    return token


def get_access_token(managed_channel_id: int | None = None) -> str:
    """A usable access token for one channel's account.

    Naming the channel is what stops an upload meant for one account going to
    whichever account happened to be linked last.
    """
    token = _load_token(managed_channel_id)
    if not token:
        raise OAuthError(
            "Kênh này chưa đăng nhập YouTube."
            if managed_channel_id else "Chưa kết nối YouTube OAuth."
        )
    if time.time() >= token.get("expires_at", 0):
        token = _refresh(token, managed_channel_id)
    return str(token["access_token"])


def status(managed_channel_id: int | None = None) -> dict[str, Any]:
    """Whether this channel - or the app - can publish right now."""
    client_id, _, redirect_uri = _oauth_config()
    token = _load_token(managed_channel_id)
    return {
        "configured": is_configured(),
        "connected": bool(token and token.get("refresh_token")),
        "client_id_configured": bool(client_id),
        "client_id_hint": (client_id[:12] + "…") if client_id else "",
        "redirect_uri": redirect_uri,
        "managed_channel_id": int(managed_channel_id) if managed_channel_id else None,
        # A channel with no account of its own publishes through the app-wide
        # one. That is deliberate and worth showing, because it means two
        # channels can be posting to the same account without saying so.
        "own_account": has_own_token(managed_channel_id),
    }
