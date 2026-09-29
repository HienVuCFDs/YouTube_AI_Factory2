"""Connections to the marketplaces, and the bridge to the person's own browser.

Two ways to be connected, chosen per platform by what the platform tolerates:

  bridge   The person's own browser (Cốc Cốc, Chrome) through the YT Factory
           extension - the Browser Bridge. The person signs in there as they
           always do; the app never launches a browser for it. On request the
           extension reads one page and hands back what it shows. Shopee is
           connected this way: measured 29/09, it answers any automated
           browser with /verify/captcha?anti_bot, signed in or not.
  profile  A browser profile the app keeps on disk for the platform
           (%LOCALAPPDATA%\\YouTubeAIFactory\\profiles\\<platform>). "Kết nối"
           opens it in a window and the person signs in there. TikTok Shop,
           Lazada, Tiki and Sendo, which serve their listings to it.

The product reader asks this module which way to read a listing:

    structured (plain HTTP, done by page_source)
    → Shopee: the person's browser via the bridge, then the app profile only
      as a fallback that has not already been turned away
    → others: the platform's own profile, then the bridge
    → NEED_LOGIN / NEED_HUMAN_VERIFY

A captcha is answered with NEED_HUMAN_VERIFY at once: it is not retried,
not solved and not hidden from. The bridge has no heartbeat: an idle
extension sleeps, and a request waits in the queue until it reconnects on its
own. Nothing here types a password or reads a cookie; what leaves this module
is a status, a label and what a page showed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from . import page_source

# What one read found.
OK = "OK"
NEED_LOGIN = "NEED_LOGIN"
NEED_HUMAN_VERIFY = "NEED_HUMAN_VERIFY"
UNAVAILABLE = "UNAVAILABLE"
FAILED = "FAILED"
SKIPPED = "SKIPPED"

# What a platform connection is, as the Connection Manager shows it.
CONNECTED = "CONNECTED"
DISCONNECTED = "DISCONNECTED"
STATUS_NEED_LOGIN = "NEED_LOGIN"
EXPIRED = "EXPIRED"
STATUS_NEED_VERIFY = "NEED_HUMAN_VERIFY"  # the platform wants a person to pass a check
ERROR = "ERROR"

# What one Browser Bridge (one browser with the extension) is.
BRIDGE_CONNECTED = "connected"
BRIDGE_STANDBY = "standby"  # asleep; reconnects on its own and then takes the request
BRIDGE_OFFLINE = "offline"
BRIDGE_OUTDATED = "outdated"  # connected, but a build that cannot read pages yet

EXTENSION_ID = "extension:browser"  # whichever browser has the extension


@dataclass(frozen=True)
class Platform:
    key: str
    label: str
    site: str
    login_url: str
    home_url: str
    # Measured 29/09: TikTok Shop answers a headless browser with "Security
    # Check" and serves a window.
    visible: bool
    # Shopee hides the listing from a visitor who is not signed in; the
    # others show it to anyone, so their profile reads without a sign-in.
    login_to_read: bool
    # Connected through the person's own browser first, the app profile after.
    via_bridge: bool = False
    # Whether the app's own profile is a usable way in at all. Shopee sends it
    # to /verify/captcha whatever it does, so it is not offered there.
    profile_usable: bool = True
    # After the app profile met a captcha or a sign-in wall, how long before it
    # is tried again unasked. None: not until a person acts. TikTok's check
    # comes and goes (the same profile passed and failed within the hour).
    profile_retry_seconds: float | None = None


PLATFORMS: tuple[Platform, ...] = (
    Platform("shopee", "Shopee", "shopee.vn", "https://shopee.vn/buyer/login", "https://shopee.vn/",
             True, True, via_bridge=True, profile_usable=False),
    Platform("tiktok", "TikTok Shop", "shop.tiktok.com", "https://shop.tiktok.com/vn", "https://shop.tiktok.com/vn",
             True, False, via_bridge=True, profile_retry_seconds=30 * 60),
    Platform("lazada", "Lazada", "lazada.vn", "https://member.lazada.vn/user/login", "https://www.lazada.vn/",
             False, False),
    Platform("tiki", "Tiki", "tiki.vn", "https://tiki.vn/", "https://tiki.vn/", False, False),
    Platform("sendo", "Sendo", "sendo.vn", "https://www.sendo.vn/", "https://www.sendo.vn/", False, False),
)
BY_KEY = {platform.key: platform for platform in PLATFORMS}
SITES = tuple(platform.site for platform in PLATFORMS)

# On these sites being redirected away from the listing is the sign-in wall.
REDIRECT_MEANS_LOGIN = frozenset({"shopee.vn"})
LOGIN_PATHS = ("/buyer/login", "/user/login", "/login", "/signin", "/sign-in", "/passport")
LOGIN_TEXT = ("cần đăng nhập", "vui lòng đăng nhập", "please log in", "please sign in")
# What a site's header says to someone who is not signed in.
SIGNED_OUT_HEADER = ("đăng nhập", "log in", "login", "sign in")

RENDER_TIMEOUT_MS = 45_000
SETTLE_MIN_MS = 2_000
SETTLE_MAX_MS = 10_000
LOGIN_WINDOW_SECONDS = 15 * 60
BRIDGE_WAKE_SECONDS = 75  # the extension reconnects at least once a minute
BRIDGE_WORK_SECONDS = 90
BRIDGE_OPEN_SECONDS = 20
BRIDGE_STANDBY_SECONDS = 180

_LOCAL = Path(os.getenv("LOCALAPPDATA", str(Path.home())))
# On the C: drive on purpose: Chrome's sandbox fails to set up a profile
# directory on the F: data volume ("Access is denied"), see web_video_sidecar.
PROFILES_ROOT = Path(os.getenv("YOUTUBE_PROFILES_DIR", str(_LOCAL / "YouTubeAIFactory" / "profiles")))
STORE_PATH = Path(os.getenv("YOUTUBE_CONNECTIONS_STORE", str(PROFILES_ROOT / "connections.json")))

# Run inside the page. Returns what the page shows - its text, its structured
# data, the prices on screen - and nothing the browser holds for the site.
# The extension carries a copy of this function (background.js probePage);
# the two must stay the same.
PROBE_JS = r"""() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const text = clean(document.body ? document.body.innerText : '').slice(0, 40000);
  const ld = Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
    .map((node) => (node.textContent || '').slice(0, 100000)).filter(Boolean).slice(0, 20);
  const meta = {};
  for (const node of document.querySelectorAll('meta')) {
    const key = (node.getAttribute('property') || node.getAttribute('name') || node.getAttribute('itemprop') || '').toLowerCase();
    if (!key || key in meta) continue;
    if (/^(og:|product:|twitter:)/.test(key) || ['description', 'title', 'price', 'pricecurrency'].includes(key)) {
      meta[key] = clean(node.getAttribute('content')).slice(0, 500);
    }
  }
  const money = /(₫\s?\d{1,3}(?:[.,]\d{3})+|\d{1,3}(?:[.,]\d{3})+\s?(?:₫|đ|vnđ|vnd)(?![a-z]))/i;
  const prices = [];
  for (const el of document.querySelectorAll('body *')) {
    if (prices.length >= 80) break;
    if (el.childElementCount > 3) continue;
    const raw = el.textContent || '';
    if (!raw || raw.length > 80) continue;
    const own = clean(el.innerText);
    if (!own || own.length > 40) continue;
    const found = own.match(money);
    if (!found) continue;
    if (Array.from(el.children).some((child) => clean(child.innerText) === own)) continue;
    const box = el.getBoundingClientRect();
    if (!box.width || !box.height) continue;
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    // A price is often a small wrapper around large digits: measure the largest
    // type inside it, and count it struck if any part of it is.
    const parts = [el, ...Array.from(el.querySelectorAll('*'))].map((node) => getComputedStyle(node));
    const size = Math.max(...parts.map((part) => parseFloat(part.fontSize) || 0));
    const struck = parts.some((part) => String(part.textDecorationLine || '').includes('line-through')) || !!el.closest('del, s, strike');
    const context = clean(el.parentElement ? el.parentElement.innerText : '').slice(0, 120);
    prices.push({ text: found[0], size, top: Math.round(box.top + window.scrollY), struck, context });
  }
  const images = Array.from(document.images)
    .filter((img) => (img.naturalWidth || img.width) >= 300 && (img.naturalHeight || img.height) >= 300)
    .map((img) => img.currentSrc || img.src)
    .filter((src) => /^https?:/.test(src));
  return { url: location.href, title: document.title || '', text, ld, meta, prices, images: Array.from(new Set(images)).slice(0, 12) };
}"""

# A listing loads its price after the page itself; this is what "loaded" means.
READY_JS = r"""() => /(₫\s?\d|\d[.,]\d{3}\s?(₫|đ))/i.test(document.body ? document.body.innerText : '')"""

# Enough of a page to tell whether its header greets someone signed in.
HEADER_JS = r"""() => ({
  url: location.href,
  title: document.title || '',
  ready: document.readyState === 'complete',
  text: String(document.body ? document.body.innerText : '').replace(/\s+/g, ' ').trim().slice(0, 1500),
})"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _host(target: str) -> str:
    text = str(target or "").strip()
    parsed = urlparse(text if "//" in text else f"https://{text}")
    return (parsed.hostname or "").lower()


def platform_of(target: str) -> Platform | None:
    """The platform a link, a domain, a key ("shopee") or a session id names."""
    text = str(target or "").strip().lower()
    if text.startswith("profile:"):
        text = text.split(":", 1)[1]
    if text in BY_KEY:
        return BY_KEY[text]
    host = _host(text)
    for platform in PLATFORMS:
        if host == platform.site or host.endswith("." + platform.site):
            return platform
    return None


def site_of(target: str) -> str:
    platform = platform_of(target)
    return platform.site if platform else ""


def bridge_slug(browser: str) -> str:
    """"Cốc Cốc" -> "coccoc": the browser's name as it appears in an id."""
    plain = unicodedata.normalize("NFKD", str(browser or "").replace("đ", "d").replace("Đ", "D"))
    return re.sub(r"[^a-z0-9]+", "", plain.encode("ascii", "ignore").decode().lower()) or "browser"


# Where each browser installs itself. Cốc Cốc tells a page it is "Google
# Chrome" (its client hints say so, measured 29/09), so the name an extension
# reports cannot be trusted; the program holding the socket can.
_BROWSER_PROGRAMS = (
    ("coccoc", "Cốc Cốc"),
    ("microsoft\\edge", "Edge"),
    ("bravesoftware", "Brave"),
    ("google\\chrome", "Chrome"),
)


def browser_of_peer(port: int) -> str:
    """The browser whose socket is on this local port, or "" if unknown.

    Only the program's install path is looked at - which browser it is, not
    anything the browser holds.
    """
    try:
        import psutil
    except ImportError:
        return ""
    try:
        pid = next(
            (conn.pid for conn in psutil.net_connections(kind="tcp")
             if conn.pid and conn.laddr and conn.laddr.port == int(port)),
            None,
        )
        path = psutil.Process(pid).exe().lower() if pid else ""
    except Exception:
        return ""
    return next((name for marker, name in _BROWSER_PROGRAMS if marker in path), "")


def bridge_target(session_id: str) -> str:
    """The browser an "extension:<browser>" id names; "" for any browser."""
    text = str(session_id or "").strip().lower()
    if not text.startswith("extension:") or text == EXTENSION_ID:
        return ""
    return bridge_slug(text.split(":", 1)[1])


def _legacy_profile(platform: Platform) -> Path:
    from .web_video_sidecar import STATE_DIR

    return Path(STATE_DIR) / f"profile_shop_{re.sub(r'[^a-z0-9]+', '_', platform.site).strip('_')}"


def profile_dir(platform: Platform) -> Path:
    """The platform's own profile: the same directory every time.

    A profile left by the earlier per-site layout is moved here once, so a
    sign-in already made there is not lost.
    """
    directory = PROFILES_ROOT / platform.key
    legacy = _legacy_profile(platform)
    if not directory.exists() and legacy.is_dir():
        try:
            directory.parent.mkdir(parents=True, exist_ok=True)
            legacy.rename(directory)
        except OSError:
            pass
    return directory


def has_profile(platform: Platform) -> bool:
    return (profile_dir(platform) / "Default").is_dir()


def classify(requested_url: str, probe: dict[str, Any]) -> tuple[str, str]:
    """Whether what came back is the listing, a sign-in wall, or a challenge."""
    final = str(probe.get("url") or requested_url)
    path = urlparse(final).path.lower()
    title = str(probe.get("title") or "")
    head = str(probe.get("text") or "")[:1500]
    blob = f"{title} {head}".lower()
    if "captcha" in path or "anti_bot" in final.lower():
        # Measured 29/09: Shopee sends an automated browser to
        # /verify/captcha?anti_bot... Reported for a person, never retried.
        return NEED_HUMAN_VERIFY, f"Sàn đòi người xác minh (captcha: {path})"
    if any(path.startswith(marker) or f"{marker}/" in path for marker in LOGIN_PATHS):
        return NEED_LOGIN, f"Trang chuyển sang đăng nhập ({path})"
    if "/verify/" in path:
        if any(marker in blob for marker in LOGIN_TEXT):
            return NEED_LOGIN, f"Sàn đòi đăng nhập trước khi cho xem ({path})"
        return NEED_HUMAN_VERIFY, f"Sàn đòi người xác minh ({path})"
    said = next((marker for marker in LOGIN_TEXT if marker in blob), "")
    if said:
        start = blob.find(said)
        return NEED_LOGIN, f"Trang ghi cần đăng nhập: \"{blob[max(0, start - 60):start + 60].strip()}\""
    if page_source.looks_like_bot_wall(title, head[:600]):
        return NEED_HUMAN_VERIFY, f"Trang là tường chặn bot: {title[:80] or head[:80]}"
    if page_source.landed_elsewhere(requested_url, final):
        if site_of(requested_url) in REDIRECT_MEANS_LOGIN:
            return NEED_LOGIN, f"Bị chuyển khỏi trang sản phẩm ({path or '/'})"
        return FAILED, f"Bị chuyển sang trang khác ({path or '/'})"
    return OK, ""


def signed_in(platform: Platform, page: dict[str, Any]) -> tuple[bool, str]:
    """Whether a page of the platform greets someone signed in.

    Read off the header, the way a person would tell: a signed-out visitor is
    offered "Đăng nhập" at the top of every one of these sites (measured on
    Shopee, Lazada and TikTok Shop 29/09); a signed-in one sees their name.
    """
    url = str(page.get("url") or "")
    host = _host(url)
    if not (host == platform.site or host.endswith("." + platform.site)):
        return False, f"Đang ở trang khác ({host or 'trống'})"
    path = urlparse(url).path.lower()
    if any(path.startswith(marker) for marker in LOGIN_PATHS) or "/verify" in path or "captcha" in path:
        return False, f"Đang ở trang đăng nhập/xác minh ({path})"
    header = str(page.get("text") or "")[:600].lower()
    if len(header) < 80:
        return False, "Trang chưa tải xong"
    shown = next((marker for marker in SIGNED_OUT_HEADER if marker in header), "")
    if shown:
        return False, f"Đầu trang vẫn mời \"{shown}\""
    return True, ""


class _Store:
    """Last known state of each connection. Machine state, like the profiles
    themselves, so it lives beside them and not in a project database."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, key: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._load().get(key) or {})

    def put(self, key: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            entry = dict(data.get(key) or {})
            entry.update(fields)
            data[key] = entry
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
            return entry


class BrowserBridge:
    """Requests to the YT Factory extension, in whichever browser runs it.

    Event-driven, no heartbeat: a request is queued with the browser it is
    for (or none, for any); the app's WebSocket endpoint hands it over through
    `outbox` as soon as a matching extension is connected - now, or when it
    next wakes and reconnects - and the answer comes back through `resolve`.
    An extension that never said hello is an older build: connected, and
    unable to read pages until it is reloaded.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: dict[str, dict[str, Any]] = {}
        self._seen: dict[str, dict[str, Any]] = {}
        self._pending: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _info(info: dict[str, Any] | None) -> dict[str, Any]:
        info = dict(info or {"capabilities": []})
        info["slug"] = bridge_slug(info.get("browser") or "") if info.get("browser") else "browser"
        return info

    def register(self, connection_id: str, info: dict[str, Any] | None = None) -> None:
        with self._lock:
            client = self._info(info)
            self._clients[connection_id] = client
            if "page_read" in (client.get("capabilities") or []):
                self._seen[client["slug"]] = {"at": time.monotonic(), "info": client}

    def unregister(self, connection_id: str) -> None:
        with self._lock:
            client = self._clients.pop(connection_id, None) or {}
            if "page_read" in (client.get("capabilities") or []):
                self._seen[client["slug"]] = {"at": time.monotonic(), "info": client}
            for request in self._pending.values():
                if request.get("delivered_to") == connection_id and not request["answered"].is_set():
                    request["answer"] = {"ok": False, "error": "Extension mất kết nối giữa chừng"}
                    request["answered"].set()

    def bridges(self) -> list[dict[str, Any]]:
        """Every browser the extension has been seen in, and its state."""
        with self._lock:
            clients = list(self._clients.values())
            seen = {slug: dict(entry) for slug, entry in self._seen.items()}
        rows: dict[str, dict[str, Any]] = {}
        for client in clients:
            capable = "page_read" in (client.get("capabilities") or [])
            status = BRIDGE_CONNECTED if capable else BRIDGE_OUTDATED
            if rows.get(client["slug"], {}).get("status") == BRIDGE_CONNECTED:
                continue
            rows[client["slug"]] = {"status": status, "info": client}
        for slug, entry in seen.items():
            if slug in rows:
                continue
            fresh = time.monotonic() - entry["at"] <= BRIDGE_STANDBY_SECONDS
            rows[slug] = {"status": BRIDGE_STANDBY if fresh else BRIDGE_OFFLINE, "info": entry["info"]}
        return [
            {
                "id": f"extension:{slug}",
                "browser": str(row["info"].get("browser") or "trình duyệt"),
                "version": str(row["info"].get("version") or ""),
                "status": row["status"],
                "can_read": row["status"] in {BRIDGE_CONNECTED, BRIDGE_STANDBY},
                "can_open": "open_tab" in (row["info"].get("capabilities") or []),
                "sites": list(row["info"].get("sites") or []),
            }
            for slug, row in rows.items()
        ]

    def find(self, target: str = "") -> dict[str, Any] | None:
        """The bridge a target names, or the best one when none is named."""
        rows = self.bridges()
        if target:
            return next((row for row in rows if row["id"] == f"extension:{target}"), None)
        order = {BRIDGE_CONNECTED: 0, BRIDGE_STANDBY: 1, BRIDGE_OUTDATED: 2, BRIDGE_OFFLINE: 3}
        return min(rows, key=lambda row: order[row["status"]]) if rows else None

    def state(self) -> dict[str, Any]:
        best = self.find() or {}
        status = best.get("status") or BRIDGE_OFFLINE
        return {
            "status": status,
            "can_read": status in {BRIDGE_CONNECTED, BRIDGE_STANDBY},
            "version": best.get("version") or "",
            "browser": best.get("browser") or "",
            "sites": best.get("sites") or [],
        }

    def outbox(self, connection_id: str) -> list[dict[str, Any]]:
        with self._lock:
            client = self._clients.get(connection_id) or {}
            capabilities = client.get("capabilities") or []
            if "page_read" not in capabilities:
                return []
            messages = []
            for request_id, request in self._pending.items():
                if request.get("delivered_to") or request["kind"] not in capabilities:
                    continue
                if request["target"] and request["target"] != client.get("slug"):
                    continue
                request["delivered_to"] = connection_id
                request["delivered_slug"] = client.get("slug") or ""
                request["delivered"].set()
                messages.append({"type": request["kind"], "request_id": request_id, "url": request["url"]})
            return messages

    def resolve(self, request_id: str, answer: dict[str, Any]) -> None:
        with self._lock:
            request = self._pending.get(str(request_id))
        if request is not None:
            request["answer"] = dict(answer or {})
            request["answered"].set()

    def request(
        self, kind: str, url: str, *, target: str = "",
        wake_seconds: float = BRIDGE_WAKE_SECONDS, work_seconds: float = BRIDGE_WORK_SECONDS,
    ) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        request = {"kind": kind, "url": url, "target": target, "delivered": threading.Event(),
                   "answered": threading.Event(), "answer": None, "delivered_to": "", "delivered_slug": ""}
        with self._lock:
            self._pending[request_id] = request
        try:
            if not request["delivered"].wait(wake_seconds):
                return {"ok": False, "error": f"Extension không thức dậy nhận việc trong {int(wake_seconds)} giây"}
            if not request["answered"].wait(work_seconds):
                return {"ok": False, "error": f"Extension không trả lời sau {int(work_seconds)} giây",
                        "bridge": request["delivered_slug"]}
            return {**dict(request["answer"] or {}), "bridge": request["delivered_slug"]}
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def read(self, url: str, *, target: str = "", wake_seconds: float = BRIDGE_WAKE_SECONDS,
             work_seconds: float = BRIDGE_WORK_SECONDS) -> dict[str, Any]:
        return self.request("page_read", url, target=target, wake_seconds=wake_seconds, work_seconds=work_seconds)

    def open_tab(self, url: str, *, target: str = "") -> dict[str, Any]:
        """Show a page to the person in their own browser, as a normal tab."""
        return self.request("open_tab", url, target=target, work_seconds=BRIDGE_OPEN_SECONDS)


BRIDGE = BrowserBridge()

_PROFILE_LOCKS: dict[str, threading.Lock] = {}
_PROFILE_LOCKS_GUARD = threading.Lock()


def _profile_lock(platform: Platform) -> threading.Lock:
    with _PROFILE_LOCKS_GUARD:
        return _PROFILE_LOCKS.setdefault(platform.key, threading.Lock())


def _launch(playwright: Any, platform: Platform, *, headless: bool) -> Any:
    """The platform's own persistent profile - never a fresh context."""
    directory = profile_dir(platform)
    directory.mkdir(parents=True, exist_ok=True)
    options: dict[str, Any] = {
        "headless": headless,
        "locale": "vi-VN",
        "args": ["--disable-features=NetworkServiceSandbox"],
    }
    if headless:
        # Headless Chrome names itself in its user agent.
        options["user_agent"] = page_source.BROWSER_HEADERS["User-Agent"]
    try:
        return playwright.chromium.launch_persistent_context(str(directory), channel="chrome", **options)
    except Exception as exc:  # no installed Chrome: the bundled browser still keeps the profile
        if "chrome" in str(exc).lower() and ("install" in str(exc).lower() or "channel" in str(exc).lower()):
            return playwright.chromium.launch_persistent_context(str(directory), **options)
        raise


def _settle(page: Any) -> None:
    page.wait_for_timeout(SETTLE_MIN_MS)
    waited = SETTLE_MIN_MS
    while waited < SETTLE_MAX_MS:
        if "captcha" in str(page.url or "").lower() or "/verify/" in str(page.url or "").lower():
            return  # a challenge will not turn into the listing by waiting
        try:
            if page.evaluate(READY_JS):
                return
        except Exception:
            pass
        page.wait_for_timeout(1_000)
        waited += 1_000


def _open_and_run(platform: Platform, url: str, script: str) -> tuple[str, dict[str, Any]]:
    """Open the platform's profile on one page and run one script there."""
    lock = _profile_lock(platform)
    if not lock.acquire(timeout=2):
        return UNAVAILABLE, {"error": "Profile đang mở ở cửa sổ khác (đang đăng nhập?)"}
    try:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return UNAVAILABLE, {"error": "Chưa cài Playwright"}
        with sync_playwright() as playwright:
            context = _launch(playwright, platform, headless=not platform.visible)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(url, timeout=RENDER_TIMEOUT_MS, wait_until="domcontentloaded")
                _settle(page)
                return OK, dict(page.evaluate(script) or {})
            finally:
                context.close()
    except Exception as exc:
        text = str(exc)
        if "user data directory is already in use" in text.lower() or "processsingleton" in text.lower():
            return UNAVAILABLE, {"error": "Profile đang được một cửa sổ Chrome khác dùng"}
        return FAILED, {"error": f"Không mở được trang: {text[:200]}"}
    finally:
        lock.release()


def _read_with_profile(url: str, platform: Platform) -> tuple[str, str, dict[str, Any]]:
    status, probe = _open_and_run(platform, url, PROBE_JS)
    if status != OK:
        return status, str(probe.get("error") or ""), {}
    status, detail = classify(url, probe)
    return status, detail, probe


def _check_with_profile(platform: Platform) -> tuple[str, dict[str, Any]]:
    return _open_and_run(platform, platform.home_url, HEADER_JS)


def _read_with_bridge(url: str, bridge: BrowserBridge, target: str) -> tuple[str, str, dict[str, Any], str]:
    answer = bridge.read(url, target=target)
    responder = f"extension:{answer['bridge']}" if answer.get("bridge") else ""
    if not answer.get("ok"):
        return FAILED, str(answer.get("error") or "Extension không đọc được trang")[:300], {}, responder
    probe = answer.get("result") if isinstance(answer.get("result"), dict) else {}
    status, detail = classify(url, probe)
    return status, detail, probe, responder


_NEXT_ACTION = {
    DISCONNECTED: "Người dùng bấm Kết nối {label} trong tab Công cụ & kết nối",
    STATUS_NEED_LOGIN: "Người dùng bấm Kết nối {label} trong tab Công cụ & kết nối rồi tự đăng nhập",
    EXPIRED: "Người dùng bấm Đăng nhập lại {label} trong tab Công cụ & kết nối",
    ERROR: "Bấm Kiểm tra {label}; nếu sàn đòi xác minh thì người dùng tự xác minh trong trình duyệt",
}
_NEXT_ACTION[STATUS_NEED_VERIFY] = "Người dùng bấm Kết nối {label} và tự xác minh trong cửa sổ đó"
_NEXT_ACTION_BRIDGE = {
    DISCONNECTED: "Người dùng bấm Kết nối {label} trong tab Công cụ & kết nối và chọn trình duyệt",
    STATUS_NEED_LOGIN: "Người dùng đăng nhập {label} trong {browser}, rồi bấm Kiểm tra {label}",
    EXPIRED: "Phiên {label} trong {browser} đã hết: người dùng đăng nhập lại ở đó, rồi bấm Kiểm tra",
    STATUS_NEED_VERIFY: "Người dùng mở {label} trong {browser} và tự xác minh, rồi bấm Kiểm tra {label}",
    ERROR: "Bấm Kiểm tra {label}; nếu vẫn lỗi, mở {label} trong {browser} xem trang có hiện không",
}


class ConnectionManager:
    def __init__(
        self,
        *,
        store: _Store | None = None,
        bridge: BrowserBridge | None = None,
        profile_reader: Callable[[str, Platform], tuple[str, str, dict[str, Any]]] | None = None,
        profile_checker: Callable[[Platform], tuple[str, dict[str, Any]]] | None = None,
        profile_exists: Callable[[Platform], bool] | None = None,
    ) -> None:
        self.store = store or _Store(STORE_PATH)
        self.bridge = bridge or BRIDGE
        self._profile_reader = profile_reader or _read_with_profile
        self._profile_checker = profile_checker or _check_with_profile
        self._profile_exists = profile_exists or has_profile

    # -- what there is --------------------------------------------------------

    def connection(self, platform: Platform) -> dict[str, Any]:
        """One platform, as the Connection Manager shows it. No secrets."""
        stored = self.store.get(platform.key)
        status = str(stored.get("status") or DISCONNECTED)
        via = str(stored.get("via") or "")
        busy = _profile_lock(platform).locked()
        entry: dict[str, Any] = {
            "platform": platform.key,
            "label": platform.label,
            "site": platform.site,
            "mode": "bridge" if platform.via_bridge else "profile",
            "status": status,
            "via": via,
            "detail": str(stored.get("detail") or ""),
            "checked_at": stored.get("checked_at") or None,
            "connected_at": stored.get("connected_at") or None,
            "last_read_at": stored.get("last_read_at") or None,
            "last_read_status": stored.get("last_read_status") or None,
            "busy": busy,
            "login_window_open": bool(stored.get("login_window_open")) and busy,
            "login_to_read": platform.login_to_read,
        }
        if platform.via_bridge:
            # The session lives in the person's browser; there is nothing of
            # the app's to be missing, so the stored state stands.
            entry["profile"] = bool(self._profile_exists(platform))
            entry["can_read"] = status == CONNECTED or (
                not platform.login_to_read and status not in {STATUS_NEED_VERIFY, STATUS_NEED_LOGIN, EXPIRED}
            )
            entry["profile_option"] = platform.profile_usable
            via_browser = "trình duyệt riêng của app" if via.startswith("profile:") else ""
            browser = via_browser or (self.bridge.find(bridge_target(via)) or {}).get("browser") \
                or "trình duyệt có extension"
            if status in _NEXT_ACTION_BRIDGE:
                entry["next_action"] = _NEXT_ACTION_BRIDGE[status].format(label=platform.label, browser=browser)
        else:
            exists = bool(self._profile_exists(platform))
            if not exists and status != ERROR:
                entry["status"] = status = DISCONNECTED
            entry["profile"] = exists
            entry["can_read"] = status == CONNECTED or not platform.login_to_read
            if status in _NEXT_ACTION:
                entry["next_action"] = _NEXT_ACTION[status].format(label=platform.label)
        entry["summary"] = f"{platform.key}: {status}" + (f" via {via}" if via and status == CONNECTED else "")
        return entry

    def bridge_view(self) -> dict[str, Any]:
        state = self.bridge.state()
        notes = {
            BRIDGE_CONNECTED: "Đang kết nối, nhận việc ngay.",
            BRIDGE_STANDBY: "Extension đang ngủ; có việc thì nhận khi nó tự nối lại (tối đa khoảng 1 phút).",
            BRIDGE_OFFLINE: "Chưa thấy extension YT Factory (trình duyệt tắt, hoặc chưa cài).",
            BRIDGE_OUTDATED: "Extension đang chạy bản cũ chưa biết đọc trang: mở chrome://extensions và bấm Tải lại.",
        }
        return {"id": EXTENSION_ID, **state, "detail": notes[state["status"]], "bridges": self.bridge.bridges()}

    def overview(self) -> dict[str, Any]:
        return {
            "platforms": [self.connection(platform) for platform in PLATFORMS],
            "browser_bridge": self.bridge_view(),
        }

    def capabilities(self) -> dict[str, Any]:
        """What an AI is shown: which platform can be read, and through what."""
        rows = []
        for platform in PLATFORMS:
            entry = self.connection(platform)
            rows.append({key: entry[key] for key in (
                "platform", "label", "status", "via", "can_read", "summary", "detail", "next_action",
            ) if entry.get(key) not in (None, "")})
        return {
            "platforms": rows,
            "browser_bridges": [{key: row[key] for key in ("id", "browser", "status", "can_read")}
                                for row in self.bridge.bridges()],
            "read_with": "options.browser_session = profile:<nền tảng> hoặc extension:<trình duyệt>",
        }

    def routes(self, platform: Platform) -> list[dict[str, Any]]:
        """The ways this platform's pages could be read right now."""
        entry = self.connection(platform)
        rows = [{"id": row["id"], "status": row["status"], "can_read": row["can_read"]}
                for row in self.bridge.bridges()]
        profile_state = self.store.get(f"{platform.key}|profile") if platform.via_bridge else {}
        profile_status = (profile_state.get("last_status") or "chưa thử") if platform.via_bridge else entry["status"]
        rows.append({"id": f"profile:{platform.key}", "status": profile_status,
                     "can_read": bool(entry["can_read"]) if not platform.via_bridge else self._profile_fallback_ok(platform)})
        return rows

    # -- actions ----------------------------------------------------------------

    def connect(self, key: str, use: str = "") -> dict[str, Any]:
        """Kết nối / Đăng nhập lại.

        A platform connected through the person's browser launches nothing:
        the answer lists the browsers with the extension, for the person to
        choose one, open the platform there and sign in as usual. A platform
        with its own profile gets that profile in a window instead; the person
        signs in, the app watches the header and marks it CONNECTED.
        """
        platform = self._platform(key)
        if platform.via_bridge and not (use == "profile" and platform.profile_usable):
            bridges = self.bridge.bridges()
            usable = [row for row in bridges if row["can_read"]]
            if usable:
                message = (f"Chọn trình duyệt để dùng cho {platform.label}, đăng nhập {platform.label} ở đó như bình "
                           "thường, rồi bấm Kiểm tra.")
            else:
                message = ("Chưa thấy trình duyệt nào có extension YT Factory. Mở Cốc Cốc (có cài extension), "
                           "đợi khoảng 1 phút rồi bấm Làm mới.")
            if platform.profile_usable:
                message += " Hoặc dùng trình duyệt riêng của app (cửa sổ hiện, tự xác minh nếu sàn hỏi)."
            return {**self.connection(platform), "action": "choose_bridge", "bridges": bridges,
                    "profile_option": platform.profile_usable,
                    "login_url": platform.login_url, "message": message}
        lock = _profile_lock(platform)
        if not lock.acquire(blocking=False):
            return {**self.connection(platform), "action": "already_open",
                    "message": "Cửa sổ của nền tảng này đang mở. Đăng nhập xong app sẽ tự nhận ra."}
        self.store.put(platform.key, login_window_open=True, checked_at=_now())
        threading.Thread(
            target=self._login_window, args=(platform, lock), daemon=True, name=f"connect-{platform.key}",
        ).start()
        return {**self.connection(platform), "action": "opened",
                "message": f"Đã mở cửa sổ {platform.label}. Tự đăng nhập (mật khẩu, OTP, captcha) trong cửa sổ đó."}

    def open_in_browser(self, key: str, bridge: str = "") -> dict[str, Any]:
        """Open the platform's sign-in page as a normal tab of the person's browser."""
        platform = self._platform(key)
        target = bridge_slug(bridge) if bridge else ""
        answer = self.bridge.open_tab(platform.login_url, target=target)
        if not answer.get("ok"):
            raise RuntimeError(str(answer.get("error") or "Extension không mở được tab"))
        via = f"extension:{answer.get('bridge') or target or 'browser'}"
        self.store.put(platform.key, via=via, checked_at=_now(),
                       detail=f"Đã mở {platform.label} trong trình duyệt; đăng nhập xong bấm Kiểm tra")
        return {**self.connection(platform), "action": "opened_in_browser",
                "message": f"Đã mở {platform.label} trong trình duyệt của bạn. Đăng nhập xong bấm Kiểm tra."}

    def check(self, key: str, bridge: str = "") -> dict[str, Any]:
        """Kiểm tra: is the platform's session signed in?

        Through the bridge, the extension reads the platform's home page once
        in the person's browser; with a profile, the app opens it once.
        """
        platform = self._platform(key)
        if platform.via_bridge and bridge != "profile":
            return self._check_via_bridge(platform, bridge)
        if not self._profile_exists(platform):
            self.store.put(platform.key, status=DISCONNECTED, detail="Chưa có profile", checked_at=_now())
            return self.connection(platform)
        where = self._check_url(platform) if platform.via_bridge else platform.home_url
        status, page = self._profile_checker(platform) if where == platform.home_url \
            else _open_and_run(platform, where, HEADER_JS)
        if status != OK:
            self.store.put(platform.key, status=ERROR, detail=str(page.get("error") or status), checked_at=_now())
            return self.connection(platform)
        wall, wall_detail = classify(where, page)
        via = f"profile:{platform.key}" if platform.via_bridge else None
        if wall == NEED_HUMAN_VERIFY:
            self.store.put(platform.key, status=STATUS_NEED_VERIFY, checked_at=_now(),
                           detail=f"{wall_detail}. Bấm Kết nối và tự xác minh trong cửa sổ.",
                           **({"via": via} if via else {}))
            return self.connection(platform)
        works = self._session_works if platform.via_bridge else signed_in
        ok, why = works(platform, page) if wall == OK else (False, wall_detail)
        self._set_signed_in(platform, ok, why, via=via)
        return self.connection(platform)

    def _check_via_bridge(self, platform: Platform, bridge: str) -> dict[str, Any]:
        stored = self.store.get(platform.key)
        target = bridge_slug(bridge) if bridge else bridge_target(str(stored.get("via") or ""))
        found = self.bridge.find(target)
        if found is None and not target:
            self.store.put(platform.key, status=DISCONNECTED, checked_at=_now(),
                           detail="Chưa thấy trình duyệt nào có extension YT Factory")
            return self.connection(platform)
        if found is not None and found["status"] == BRIDGE_OUTDATED:
            self.store.put(platform.key, status=ERROR, checked_at=_now(),
                           detail="Extension bản cũ chưa biết đọc trang: mở chrome://extensions và bấm Tải lại")
            return self.connection(platform)
        where = self._check_url(platform)
        answer = self.bridge.read(where, target=target)
        via = f"extension:{answer.get('bridge') or target or 'browser'}"
        if not answer.get("ok"):
            self.store.put(platform.key, status=ERROR, via=via, checked_at=_now(),
                           detail=str(answer.get("error") or "Extension không đọc được trang")[:300])
            return self.connection(platform)
        page = answer.get("result") if isinstance(answer.get("result"), dict) else {}
        wall, wall_detail = classify(where, page)
        if wall == NEED_HUMAN_VERIFY:
            self.store.put(platform.key, status=STATUS_NEED_VERIFY, via=via, checked_at=_now(),
                           detail=f"{wall_detail}. Mở {platform.label} trong trình duyệt và tự xác minh.")
            return self.connection(platform)
        ok, why = self._session_works(platform, page) if wall == OK else (False, wall_detail)
        self._set_signed_in(platform, ok, why, via=via)
        return self.connection(platform)

    def _check_url(self, platform: Platform) -> str:
        """TikTok Shop puts "Security Check" on its home page more often than on a
        listing (measured 29/09: home walled, listing served, same browser, same
        minute), so a platform that needs no sign-in is checked on the last
        listing it served. Shopee is checked on its home page, where the header
        says who is signed in."""
        if platform.login_to_read:
            return platform.home_url
        return str(self.store.get(platform.key).get("last_ok_url") or platform.home_url)

    @staticmethod
    def _session_works(platform: Platform, page: dict[str, Any]) -> tuple[bool, str]:
        """Signed in, where the platform hides listings otherwise; served, elsewhere.

        TikTok Shop shows a listing and its price to anyone, so a session that
        is served its pages is a working connection, signed in or not.
        """
        ok, why = signed_in(platform, page)
        if ok or platform.login_to_read:
            return ok, why
        host = _host(str(page.get("url") or ""))
        if not (host == platform.site or host.endswith("." + platform.site)):
            return False, why
        return True, "" if ok else "Đọc được trang (chưa đăng nhập tài khoản trên sàn - không bắt buộc)"

    def disconnect(self, key: str) -> dict[str, Any]:
        """Stop using this platform's session.

        For a platform with its own profile the profile directory is the
        session, so it is deleted - only that directory, and only inside the
        app's profiles folder. A session in the person's own browser is
        theirs: the app forgets it and signs nobody out.
        """
        platform = self._platform(key)
        lock = _profile_lock(platform)
        if not lock.acquire(blocking=False):
            raise RuntimeError(f"Cửa sổ {platform.label} đang mở; đóng nó trước khi ngắt kết nối")
        try:
            directory = profile_dir(platform).resolve()
            if directory.parent != PROFILES_ROOT.resolve():
                raise RuntimeError("Profile không nằm trong thư mục profiles của app; không xoá")
            if directory.exists():
                shutil.rmtree(directory)
        finally:
            lock.release()
        self.store.put(platform.key, status=DISCONNECTED, detail="Đã ngắt kết nối", checked_at=_now(),
                       connected_at=None, via="", login_window_open=False)
        self.store.put(f"{platform.key}|profile", last_status=None)
        return self.connection(platform)

    def _platform(self, key: str) -> Platform:
        platform = platform_of(key)
        if platform is None:
            raise ValueError(f"Không có nền tảng {key}. Có: {', '.join(BY_KEY)}")
        return platform

    def _set_signed_in(self, platform: Platform, ok: bool, why: str, *, via: str | None = None) -> None:
        previous = self.store.get(platform.key)
        extra = {} if via is None else {"via": via}
        if ok:
            self.store.put(platform.key, status=CONNECTED, detail=why if not platform.login_to_read else "",
                           checked_at=_now(), connected_at=_now(), **extra)
        else:
            status = EXPIRED if previous.get("status") in {CONNECTED, EXPIRED} else STATUS_NEED_LOGIN
            self.store.put(platform.key, status=status, detail=why, checked_at=_now(), **extra)

    def _login_window(self, platform: Platform, lock: threading.Lock) -> None:
        connected = False
        problem = ""
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright

            with sync_playwright() as playwright:
                context = _launch(playwright, platform, headless=False)
                closed = threading.Event()
                context.on("close", lambda *_: closed.set())
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(platform.login_url, wait_until="domcontentloaded", timeout=RENDER_TIMEOUT_MS)
                seen_in_a_row = 0
                deadline = time.monotonic() + LOGIN_WINDOW_SECONDS
                while not closed.is_set() and time.monotonic() < deadline:
                    try:
                        context.wait_for_event("close", timeout=3_000)
                        break
                    except PlaywrightTimeout:
                        pass
                    except Exception:
                        break
                    # Looked at inside the window, not asked of any server.
                    seen = False
                    for tab in list(context.pages):
                        try:
                            ok, _why = signed_in(platform, dict(tab.evaluate(HEADER_JS) or {}))
                        except Exception:
                            continue
                        seen = seen or ok
                    seen_in_a_row = seen_in_a_row + 1 if seen else 0
                    if seen_in_a_row >= 2:
                        self._set_signed_in(platform, True, "",
                                            via=f"profile:{platform.key}" if platform.via_bridge else None)
                        connected = True
                        # Let the browser write the new session to disk.
                        page.wait_for_timeout(2_000)
                        break
                if not closed.is_set():
                    context.close()
        except Exception as exc:
            problem = f"Cửa sổ đăng nhập lỗi: {str(exc)[:200]}"
        finally:
            lock.release()
            self.store.put(platform.key, login_window_open=False)
        if problem:
            self.store.put(platform.key, status=ERROR, detail=problem, checked_at=_now())
        elif not connected:
            # Closed by hand, or timed out: see what the profile holds now.
            self.check(platform.key, "profile" if platform.via_bridge else "")

    # -- reading ----------------------------------------------------------------

    def _profile_fallback_ok(self, platform: Platform) -> bool:
        """For a bridge platform, whether the app profile is still worth a try.

        Tried once; after a captcha or a sign-in wall it is not tried again
        automatically - a loop of automated visits is what anti-bot systems
        punish, and the answer would not change.
        """
        state = self.store.get(f"{platform.key}|profile")
        if str(state.get("last_status") or "") not in {NEED_HUMAN_VERIFY, NEED_LOGIN}:
            return True
        if platform.profile_retry_seconds is None:
            return False
        try:
            since = datetime.fromisoformat(str(state.get("at") or ""))
        except ValueError:
            return True
        return (datetime.now(timezone.utc) - since).total_seconds() >= platform.profile_retry_seconds

    def _note_profile_read(self, platform: Platform, status: str, detail: str, url: str = "") -> None:
        if platform.via_bridge:
            self.store.put(f"{platform.key}|profile", last_status=status, last_detail=detail[:300], at=_now())
            if status == OK and url:
                self.store.put(platform.key, last_ok_url=url)
            current = self.store.get(platform.key)
            if status == OK and not platform.login_to_read and current.get("status") != CONNECTED:
                # Nothing better is connected and the app's own window was
                # served the listing: that is the connection now.
                self._set_signed_in(platform, True, "", via=f"profile:{platform.key}")
            return
        self.store.put(platform.key, last_read_at=_now(), last_read_status=status)
        previous = str(self.store.get(platform.key).get("status") or "")
        if status == OK and platform.login_to_read:
            # The listing is only served signed in, so being served it is proof.
            self._set_signed_in(platform, True, "")
        elif status == NEED_LOGIN and previous == CONNECTED:
            self.store.put(platform.key, status=EXPIRED, detail=detail[:300], checked_at=_now())

    def _note_bridge_read(self, platform: Platform, via: str, status: str, detail: str, url: str = "") -> None:
        self.store.put(f"extension|{platform.key}", last_read_at=_now(), last_read_status=status)
        if not platform.via_bridge:
            return
        self.store.put(platform.key, last_read_at=_now(), last_read_status=status,
                       **({"last_ok_url": url} if status == OK and url else {}))
        if status == OK:
            # A listing read in the person's browser: the connection works.
            self._set_signed_in(platform, True, "", via=via)
        elif status == NEED_LOGIN:
            self._set_signed_in(platform, False, detail[:300], via=via)
        elif status == NEED_HUMAN_VERIFY:
            self.store.put(platform.key, status=STATUS_NEED_VERIFY, via=via, checked_at=_now(),
                           detail=f"{detail[:250]}. Người dùng mở {platform.label} trong trình duyệt và tự xác minh.")

    def _candidates(self, platform: Platform, session_id: str) -> list[str]:
        profile_id = f"profile:{platform.key}"
        if session_id:
            return [session_id]
        if platform.via_bridge:
            via = str(self.store.get(platform.key).get("via") or "")
            chosen = via if via.startswith(("extension:", "profile:")) else EXTENSION_ID
            return list(dict.fromkeys([chosen, EXTENSION_ID, profile_id]))
        return [profile_id, EXTENSION_ID]

    def read(self, url: str, *, session_id: str = "") -> dict[str, Any]:
        """Read one listing through the platform's connection.

        Named, only that route is used: "profile:<platform>",
        "extension:<browser>" or "extension:browser" (any browser).
        """
        platform = platform_of(url)
        if platform is None:
            return {"status": UNAVAILABLE, "session": "", "site": "", "probe": {}, "attempts": [],
                    "detail": f"Chỉ đọc qua kết nối cho các sàn: {', '.join(SITES)}"}
        session_id = str(session_id or "").strip().lower()
        profile_id = f"profile:{platform.key}"
        if session_id and not session_id.startswith("extension:") and platform_of(session_id) != platform:
            return {"status": UNAVAILABLE, "session": session_id, "site": platform.site, "probe": {}, "attempts": [],
                    "detail": f"{session_id} không phải kết nối của {platform.label}"}
        if session_id.startswith("profile:"):
            session_id = profile_id
        stored_via = str(self.store.get(platform.key).get("via") or "")
        attempts: list[dict[str, Any]] = []
        tried_bridge = False
        for candidate in self._candidates(platform, session_id):
            started = time.monotonic()
            if candidate == profile_id:
                entry = self.connection(platform)
                if entry["busy"]:
                    attempts.append({"session": candidate, "status": UNAVAILABLE, "seconds": 0,
                                     "detail": "Profile đang mở (đang đăng nhập hoặc đang đọc)"})
                    continue
                connected_here = platform.via_bridge and stored_via == profile_id
                allowed = (connected_here or self._profile_fallback_ok(platform)) if platform.via_bridge \
                    else entry["can_read"]
                if not session_id and not allowed:
                    why = (f"profile của app chỉ là dự phòng và vừa bị {platform.label} chặn; chưa thử lại"
                           if platform.via_bridge else f"{entry['status']}: {platform.label} cần đăng nhập mới xem được")
                    attempts.append({"session": candidate, "status": SKIPPED, "seconds": 0, "detail": why})
                    continue
                status, detail, probe = self._profile_reader(url, platform)
                self._note_profile_read(platform, status, detail, url)
                used = candidate
            else:
                if tried_bridge and candidate == EXTENSION_ID:
                    continue  # the named browser was already asked; "any" would ask it again
                target = bridge_target(candidate)
                found = self.bridge.find(target)
                remembered = bool(target) and candidate == stored_via
                usable = found is not None and found["can_read"]
                if found is not None and found["status"] == BRIDGE_OUTDATED:
                    attempts.append({"session": candidate, "status": UNAVAILABLE, "seconds": 0,
                                     "detail": f"Extension trong {found['browser']} là bản cũ: tải lại extension"})
                    continue
                if not usable and not remembered and not (session_id and found is not None):
                    attempts.append({"session": candidate, "status": UNAVAILABLE, "seconds": 0,
                                     "detail": "Chưa thấy trình duyệt nào có extension YT Factory"})
                    continue
                if found is not None and found["sites"] and platform.site not in found["sites"]:
                    attempts.append({"session": candidate, "status": UNAVAILABLE, "seconds": 0,
                                     "detail": f"Extension không được phép đọc {platform.site}"})
                    continue
                # Asleep, or not back yet since the app restarted: the request
                # waits for the extension to reconnect rather than being dropped.
                tried_bridge = True
                status, detail, probe, responder = _read_with_bridge(url, self.bridge, target)
                used = responder or candidate
                self._note_bridge_read(platform, used, status, detail, url)
            # Where the browser ended up and what the page called itself: the
            # two things that tell a sign-in wall from a misreading.
            attempts.append({"session": used, "status": status, "detail": detail,
                             "seconds": round(time.monotonic() - started, 1),
                             "final_url": str(probe.get("url") or "")[:200],
                             "title": str(probe.get("title") or "")[:120]})
            if status == OK:
                return {"status": OK, "session": used, "site": platform.site, "probe": probe,
                        "attempts": attempts, "detail": ""}
            if status == NEED_HUMAN_VERIFY and candidate == profile_id:
                break  # a captcha is for a person; the next route would not change it
        status = _overall(attempts)
        # A named route failing is about that route; general advice ("nothing
        # can read this") would be wrong while others still can.
        named = f"{session_id}: {attempts[-1]['detail']}" if session_id and attempts else ""
        return {
            "status": status, "session": "", "site": platform.site, "probe": {}, "attempts": attempts,
            "detail": named or _failure_advice(status, platform),
            "sessions": self.routes(platform),
        }


def _overall(attempts: list[dict[str, Any]]) -> str:
    """The one status a caller acts on when nothing was served the page."""
    seen = [str(item.get("status") or "") for item in attempts]
    if NEED_LOGIN in seen:
        return NEED_LOGIN
    if NEED_HUMAN_VERIFY in seen:
        return NEED_HUMAN_VERIFY
    if SKIPPED in seen:
        return NEED_LOGIN
    if FAILED in seen:
        return FAILED
    return UNAVAILABLE


def _failure_advice(status: str, platform: Platform) -> str:
    if platform.via_bridge and not platform.login_to_read:
        if status == NEED_HUMAN_VERIFY:
            return (f"{platform.label} đòi người xác minh (captcha/Security Check). App không tự giải; người dùng "
                    f"bấm Kết nối {platform.label} và tự xác minh trong trình duyệt đã chọn, rồi bấm Kiểm tra.")
        return (f"Chưa đường nào đọc được {platform.label}: mở trình duyệt có extension YT Factory (vd Cốc Cốc) "
                f"hoặc bấm Kết nối {platform.label} để dùng trình duyệt riêng của app.")
    if platform.via_bridge:
        if status == NEED_HUMAN_VERIFY:
            return (f"{platform.label} đòi người xác minh (captcha). App không tự giải; người dùng mở "
                    f"{platform.label} trong trình duyệt có extension và tự xác minh.")
        return (f"{platform.label} cần đăng nhập trong trình duyệt có extension YT Factory (vd Cốc Cốc). "
                f"Người dùng đăng nhập ở đó rồi bấm Kiểm tra {platform.label} trong tab Công cụ & kết nối.")
    if status == NEED_LOGIN:
        return (
            f"{platform.label} cần một phiên đã đăng nhập. Người dùng bấm Kết nối {platform.label} trong tab "
            "Công cụ & kết nối và tự đăng nhập."
        )
    if status == NEED_HUMAN_VERIFY:
        return (
            f"{platform.label} đòi người xác minh (captcha). App không tự giải; người dùng bấm Kết nối "
            f"{platform.label} và tự xác minh trong cửa sổ đó."
        )
    if status == FAILED:
        return "Các đường đã thử đều không mở được trang."
    return "Không có kết nối nào dùng được lúc này."


_MANAGER: ConnectionManager | None = None
_MANAGER_GUARD = threading.Lock()


def manager() -> ConnectionManager:
    global _MANAGER
    with _MANAGER_GUARD:
        if _MANAGER is None:
            _MANAGER = ConnectionManager()
        return _MANAGER


def public_view(outcome: dict[str, Any], *, text_chars: int = 4000) -> dict[str, Any]:
    """A read result fit to hand to an AI: what the page shows, trimmed."""
    probe = outcome.get("probe") or {}
    view = {key: value for key, value in outcome.items() if key != "probe"}
    if probe:
        found = page_source.product_from_probe(probe)
        view["page"] = {
            "final_url": probe.get("url") or "",
            "title": probe.get("title") or "",
            "product": {key: found.get(key) for key in (
                "name", "price", "price_text", "currency", "original_price", "original_price_text", "discount",
                "brand", "seller", "rating", "review_count", "sold_count", "category", "sku", "canonical_url", "images",
            ) if found.get(key)},
            "text": str(probe.get("text") or "")[:text_chars],
            # The figures the page showed, so a missing or odd price can be
            # traced to what was on screen.
            "price_candidates": [
                {key: item.get(key) for key in ("text", "size", "top", "struck", "context")}
                for item in (probe.get("prices") or [])[:8]
            ],
        }
    return view
