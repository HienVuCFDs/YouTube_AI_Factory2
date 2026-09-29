"""Connect a marketplace from the command line.

The app does this from the Connection Manager (tab "Công cụ & kết nối"): each
platform has its own persistent profile, the person signs in there themselves,
and the profile is the session. This is the same thing without the page:

    python -m youtube_monitor.shop_login shopee.vn

opens the platform's window and waits until the person has signed in or has
closed it. Nothing is typed for you and no credential is stored by the app -
the session lives in Chrome's own profile directory.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

from . import platform_connections as connections


def host_of(target: str) -> str:
    """The host, whether given a bare domain or a full product link."""
    text = str(target or "").strip()
    if not text:
        return ""
    parsed = urlparse(text if "//" in text else f"https://{text}")
    return (parsed.hostname or "").lower()


def _platform(target: str) -> connections.Platform:
    platform = connections.platform_of(target)
    if platform is None:
        raise SystemExit(f"Không có nền tảng cho {target!r}. Có: {', '.join(connections.SITES)}")
    return platform


def profile_dir(target: str) -> Path:
    """Where one platform's session lives."""
    return connections.profile_dir(_platform(target))


def has_profile(target: str) -> bool:
    platform = connections.platform_of(target)
    return bool(platform) and connections.has_profile(platform)


def login(target: str) -> dict:
    """Open the platform's window and wait for the person to finish."""
    platform = _platform(target)
    manager = connections.manager()
    lock = connections._profile_lock(platform)
    if not lock.acquire(blocking=False):
        raise SystemExit(f"Cửa sổ {platform.label} đang mở ở nơi khác.")
    print(f"Đang mở cửa sổ {platform.label}. Tự đăng nhập trong đó; app sẽ tự nhận ra, hoặc đóng cửa sổ khi xong.")
    manager._login_window(platform, lock)
    result = manager.connection(platform)
    print(f"{platform.label}: {result['status']} {result.get('detail') or ''}".strip())
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Cách dùng: python -m youtube_monitor.shop_login shopee.vn")
    login(sys.argv[1])
