"""A signed-in browser profile per marketplace, saved once and reused.

Shopee and TikTok Shop do not refuse an automated fetch outright. Shopee sends
a headless browser to its home page - the page loads, publishes a real
og:title, and the title belongs to the home page. TikTok answers with a puzzle.
Either way the listing is never served, and the price was never readable even
on Lazada, whose own JSON-LD carries no price field at all.

What changes that is the same thing the app already does for ChatGPT and Meta
AI: the real installed Chrome rather than Playwright's bundled Chromium, a
visible window rather than headless, and a profile that has been signed in
once by hand. A signed-in shopper is served the page.

One profile per site, not one shared profile: signing into Shopee should not
require a TikTok account, and a site that flags one profile does not reach the
others.

    python -m youtube_monitor.shop_login shopee.vn

opens a window, waits while you sign in, and saves the session. Nothing is
typed for you and no credentials are stored by the app - the session lives in
Chrome's own profile directory, exactly as it would if you had opened Chrome
yourself.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from .web_video_sidecar import STATE_DIR

LOGIN_PAGES = {
    "shopee.vn": "https://shopee.vn/buyer/login",
    "shop.tiktok.com": "https://shop.tiktok.com/vn",
    "www.lazada.vn": "https://member.lazada.vn/user/login",
    "lazada.vn": "https://member.lazada.vn/user/login",
    "tiki.vn": "https://tiki.vn/",
}


def host_of(target: str) -> str:
    """The host, whether given a bare domain or a full product link."""
    text = str(target or "").strip()
    if not text:
        return ""
    parsed = urlparse(text if "//" in text else f"https://{text}")
    return (parsed.hostname or "").lower()


def profile_dir(target: str) -> Path:
    """Where one site's signed-in session lives."""
    host = host_of(target)
    slug = re.sub(r"[^a-z0-9]+", "_", host).strip("_") or "unknown"
    return Path(STATE_DIR) / f"profile_shop_{slug}"


def has_profile(target: str) -> bool:
    """Whether there is a browser profile for this site worth using.

    Deliberately not "whether you are signed in", because that cannot be told
    from outside: merely opening a login page writes three hundred files and
    sets cookies for the domain, so neither the folder nor the cookie store
    distinguishes a signed-in session from a browser that visited once.

    The honest test is the read itself - the page either renders or the site
    sends you to its home page - and that check already runs every time. What
    this answers is the cheaper question: is there a profile here at all, so
    the reader should use it rather than starting from a blank browser.
    """
    store = profile_dir(target) / "Default" / "Network" / "Cookies"
    return store.is_file() and store.stat().st_size > 0


def login(target: str) -> Path:
    """Open a window on the site, wait for you to sign in, then check it worked.

    Given a full product link the window returns to that exact page once you
    are signed in and reports what it can now see. Saving a session and only
    finding out days later that the site still will not serve the listing is
    the failure worth avoiding: the check costs one page load.
    """
    from playwright.sync_api import sync_playwright

    host = host_of(target)
    if not host:
        raise SystemExit("Hãy đưa tên miền hoặc link, ví dụ: shopee.vn")
    directory = profile_dir(host)
    directory.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(target if "//" in target else f"https://{target}")
    product_url = target if parsed.path.strip("/") else ""
    start = LOGIN_PAGES.get(host, f"https://{host}")

    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                str(directory), channel="chrome", headless=False,
                args=["--disable-features=NetworkServiceSandbox"],
            )
        except Exception:
            # Machines without Chrome installed fall back to the bundled
            # browser; the session still saves, the fingerprint is just worse.
            context = playwright.chromium.launch_persistent_context(
                str(directory), headless=False,
                args=["--disable-features=NetworkServiceSandbox"],
            )
        page = context.new_page()
        page.goto(start, wait_until="domcontentloaded")
        input(f"Đăng nhập {host} trong cửa sổ vừa mở, đợi trang tải xong rồi bấm Enter ở đây... ")
        if product_url:
            print("\nĐang mở lại link sản phẩm để kiểm tra...")
            try:
                page.goto(product_url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(4_000)
                _report(page, product_url)
            except Exception as exc:
                print(f"  Không mở lại được link: {str(exc)[:160]}")
        context.close()
    print(f"\nĐã lưu phiên tại {directory}")
    return directory


def _report(page: object, product_url: str) -> None:
    """Say plainly whether the listing is now readable."""
    from . import page_source

    html = page.content()
    title = page_source.page_title(html)
    landed = page_source.landed_elsewhere(product_url, str(page.url or ""))
    product = page_source.product_from_ld(html)

    print(f"  Tiêu đề trang:  {title[:90] or '(trống)'}")
    if landed:
        print(f"  ⚠ Bị chuyển sang trang khác: {str(page.url)[:90]}")
        print("    → Phiên chưa đủ; sàn vẫn coi đây là truy cập tự động.")
        return
    if page_source.looks_like_bot_wall(title, html[:4000]):
        print("  ⚠ Trang vẫn là tường chặn / đòi đăng nhập.")
        return
    price = str(product.get("price") or "")
    images = len(product.get("images") or [])
    print(f"  Đọc được:       giá={price or '(không có)'} | ảnh={images}")
    print("  → Đọc được trang. App sẽ tự dùng phiên này." if title else "  → Vẫn chưa đọc được.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Cách dùng: python -m youtube_monitor.shop_login shopee.vn")
    login(sys.argv[1])
