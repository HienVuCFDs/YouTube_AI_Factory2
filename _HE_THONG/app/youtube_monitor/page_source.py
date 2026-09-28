"""Reading a web page that is not a video: an article, or a product listing.

Measured on the three Vietnamese marketplaces the user actually sells from,
because they fail in three different ways and one route does not cover them:

  Lazada      plain HTTP, JSON-LD `Product`  - name, six images, brand, price
  TikTok Shop needs a browser, then the rendered text
  Shopee      needs a browser AND a signed-in profile; without one the page
              renders "Cần đăng nhập" and carries only `WebSite` and
              `BreadcrumbList` - no product block, no images, no price

So there are three tiers, tried cheapest first, and the result records which
one answered. A caller that gets tier 3 knows it is holding a page that was
rendered but not signed in, which on Shopee means the price is simply absent -
and an absent price is the thing a writer is most likely to invent.

Prices are stamped with the moment they were read. A price is only true on the
day it was taken, and a video made next month from today's number is wrong in
a way nothing downstream could otherwise notice.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

TIMEOUT_SECONDS = 25.0
RENDER_TIMEOUT_MS = 45_000
RENDER_SETTLE_MS = 4_000
MAX_IMAGES = 8

# Saying who we are gets 403 from Wikipedia and a captcha from some shops;
# these pages are read the way a browser reads them.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}

# Hosts whose pages are a thing for sale rather than something to read.
SHOP_HOSTS = (
    "shopee.vn", "lazada.vn", "shop.tiktok.com", "tiki.vn", "sendo.vn",
    "amazon.", "aliexpress.", "taobao.com", "shein.com", "temu.com",
)

_JSON_LD = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I
)
_META = re.compile(
    r'<meta[^>]+(?:property|name)=["\']([^"\']+)["\'][^>]+content=["\']([^"\']*)["\']', re.I
)
_TAGS = re.compile(r"(?is)<(script|style|nav|footer|header|form|svg)[^>]*>.*?</\1>")


# What a site says instead of its content when it decides you are a robot.
# Importing one of these as a source is worse than failing: the project is
# created, named "Security Check", and looks like it worked.
BOT_WALL_MARKERS = (
    "security check",
    "verify to continue",
    "drag the puzzle",
    "please enable javascript",
    "enable javascript",
    "access denied",
    "captcha",
    "are you a robot",
    "unusual traffic",
    "cần đăng nhập",
    "just a moment",
    "attention required",
)


class PageSourceError(RuntimeError):
    pass


def landed_elsewhere(requested: str, final: str) -> bool:
    """True when the browser ended up on a different page than it asked for.

    Query strings and trailing slashes are ignored; what counts is being sent
    to a different path, which is how a marketplace refuses without refusing.
    """
    from urllib.parse import urlparse as _parse

    asked = _parse(str(requested or ""))
    got = _parse(str(final or ""))
    if not got.path:
        return False
    return asked.path.rstrip("/").lower() != got.path.rstrip("/").lower()


def looks_like_bot_wall(*parts: str) -> bool:
    """True when what came back is a challenge rather than the page."""
    blob = " ".join(str(part or "") for part in parts).lower()
    return any(marker in blob for marker in BOT_WALL_MARKERS)


def page_title(html: str) -> str:
    """The page's own name: og:title first, then <title>."""
    tags = meta_tags(html)
    title = str(tags.get("og:title") or tags.get("title") or "").strip()
    if title:
        return title
    match = re.search(r"<title[^>]*>(.*?)</title>", str(html or ""), re.S | re.I)
    return _clean(match.group(1)) if match else ""


def name_from_url(url: str) -> str:
    """The product name a marketplace writes into its own URL, or "".

    Shopee puts the listing's title in the path - "Tai-Nghe-S10-Mau-Den-Mini-
    Khong-Day-Bluetooth-...-i.196261835.29134843988" - so a page that refuses
    to load still tells us what it is selling. Not the price, but a source
    named after the product beats one named after a URL.

    A path that is only digits, as TikTok Shop's is, carries nothing and is
    reported as nothing rather than as a name made of numbers.
    """
    path = unquote(urlparse(str(url or "")).path).strip("/")
    if not path:
        return ""
    slug = path.split("/")[-1]
    # Shopee appends "-i.<shop>.<item>"; everything before it is the title.
    if "-i." in slug:
        slug = slug.rsplit("-i.", 1)[0]
    slug = re.sub(r"\.html?$", "", slug)
    words = _clean(slug.replace("-", " ").replace("_", " "))
    # Two real words at least. Lazada's path is "pdp-i204631671-s254952397",
    # which is a product identifier wearing the shape of a title; returning it
    # as a name would put a row called "pdp i204631671" in the library.
    letters = [
        token for token in words.split()
        if len(token) >= 2 and re.fullmatch(r"[^\W\d_]+", token, re.UNICODE)
    ]
    return words[:300] if len(letters) >= 2 else ""


def looks_like_shop(url: str) -> bool:
    lowered = str(url or "").lower()
    return any(host in lowered for host in SHOP_HOSTS)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def strip_markup(html: str, *, max_chars: int = 24_000) -> str:
    body = _TAGS.sub(" ", str(html or ""))
    return _clean(re.sub(r"<[^>]+>", " ", body))[:max_chars]


def meta_tags(html: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for match in _META.finditer(str(html or "")):
        key = match.group(1).lower()
        if key.startswith(("og:", "product:", "twitter:")) or key in {"description", "title"}:
            found.setdefault(key, _clean(match.group(2))[:500])
    return found


def _ld_blocks(html: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for match in _JSON_LD.finditer(str(html or "")):
        try:
            data = json.loads(match.group(1).strip())
        except (ValueError, TypeError):
            continue
        for item in (data if isinstance(data, list) else [data]):
            if isinstance(item, dict):
                blocks.append(item)
                graph = item.get("@graph")
                if isinstance(graph, list):
                    blocks.extend(node for node in graph if isinstance(node, dict))
    return blocks


def _absolute(url: str) -> str:
    text = str(url or "").strip()
    return f"https:{text}" if text.startswith("//") else text


def product_from_ld(html: str) -> dict[str, Any]:
    """The `Product` block a well-behaved listing publishes, or {}."""
    for block in _ld_blocks(html):
        if str(block.get("@type") or "") != "Product":
            continue
        offers = block.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        offers = offers if isinstance(offers, dict) else {}
        images = block.get("image")
        images = images if isinstance(images, list) else ([images] if images else [])
        brand = block.get("brand")
        brand_name = brand.get("name") if isinstance(brand, dict) else brand
        return {
            "name": _clean(block.get("name"))[:300],
            "description": _clean(block.get("description"))[:4000],
            "brand": _clean(brand_name)[:120],
            "category": _clean(block.get("category"))[:200],
            "sku": _clean(block.get("sku"))[:120],
            "price": _clean(offers.get("price"))[:40],
            "currency": _clean(offers.get("priceCurrency"))[:10],
            "availability": _clean(offers.get("availability"))[:80],
            "images": [_absolute(item) for item in images if str(item or "").strip()][:MAX_IMAGES],
        }
    return {}


def product_from_meta(html: str) -> dict[str, Any]:
    """What a link preview would show. Thinner, but it survives rendering."""
    tags = meta_tags(html)
    image = tags.get("og:image") or tags.get("twitter:image") or ""
    return {
        "name": _clean(tags.get("og:title") or tags.get("title"))[:300],
        "description": _clean(tags.get("og:description") or tags.get("description"))[:4000],
        "brand": "",
        "category": "",
        "sku": "",
        "price": _clean(tags.get("product:price:amount"))[:40],
        "currency": _clean(tags.get("product:price:currency"))[:10],
        "availability": "",
        "images": [_absolute(image)] if image else [],
    }


def fetch_static(url: str) -> str:
    try:
        response = httpx.get(
            url, headers=BROWSER_HEADERS, timeout=TIMEOUT_SECONDS, follow_redirects=True,
        )
        response.raise_for_status()
        return response.text
    except (httpx.HTTPError, ValueError) as exc:
        raise PageSourceError(f"Không tải được trang: {exc}") from exc


def fetch_rendered(url: str, *, profile_dir: str = "") -> tuple[str, str, str]:
    """Load the page in a real browser. Returns (html, visible text, final url).

    The final url matters: a site that has decided you are a robot may answer
    by sending you to its home page rather than by saying no. The page then
    loads perfectly, publishes a real og:title, and the title belongs to the
    home page - which is how a product import came back named "Shopee Việt
    Nam | Mua và Bán Trên Ứng Dụng Di Động".

    With `profile_dir` the browser reuses a signed-in profile, which is the
    only way Shopee shows a price at all.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PageSourceError("Chưa cài Playwright nên không mở được trang bằng trình duyệt") from exc
    try:
        with sync_playwright() as playwright:
            if profile_dir:
                context = playwright.chromium.launch_persistent_context(
                    profile_dir, channel="chrome", headless=False,
                    locale="vi-VN", user_agent=BROWSER_HEADERS["User-Agent"],
                )
                browser = None
            else:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(
                    locale="vi-VN", user_agent=BROWSER_HEADERS["User-Agent"],
                )
            try:
                page = context.new_page()
                page.goto(url, timeout=RENDER_TIMEOUT_MS, wait_until="domcontentloaded")
                page.wait_for_timeout(RENDER_SETTLE_MS)
                html = page.content()
                try:
                    text = _clean(page.inner_text("body"))
                except Exception:
                    text = ""
                return html, text, str(page.url or url)
            finally:
                context.close()
                if browser is not None:
                    browser.close()
    except PageSourceError:
        raise
    except Exception as exc:
        raise PageSourceError(f"Không mở được trang bằng trình duyệt: {str(exc)[:200]}") from exc


AI_READER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "readable": {"type": "boolean"},
        "name": {"type": "string"},
        "price": {"type": "string"},
        "currency": {"type": "string"},
        "brand": {"type": "string"},
        "category": {"type": "string"},
        "rating": {"type": "string"},
        "review_count": {"type": "string"},
        "sold_count": {"type": "string"},
        "description": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": [
        "readable", "name", "price", "currency", "brand", "category",
        "rating", "review_count", "sold_count", "description", "note",
    ],
    "additionalProperties": False,
}

_AI_READER_SYSTEM = (
    "Ban doc mot trang ban hang va ghi lai DUNG nhung gi trang do ghi. "
    "Khong suy doan, khong lam tron, khong doi don vi. Truong nao trang khong ghi thi de chuoi rong - "
    "de trong la cau tra loi dung, bia mot con so la sai. Neu trang chan bot, doi dang nhap, hoac "
    "chuyen huong di noi khac thi dat readable=false va noi ro trong note."
)

AI_READER_TIMEOUT_SECONDS = 300


def read_with_ai(url: str) -> dict[str, Any]:
    """Have the local Claude Code CLI read the listing, or return {}.

    The app cannot fetch these pages itself: Lazada publishes a JSON-LD block
    with no price field in it, Shopee answers a script-only shell, TikTok a
    captcha. The CLI's own reader gets the page - measured on Lazada, it
    returned the price, the rating and the review count in 24 seconds, none of
    which exist anywhere in the HTML the app can reach.

    Never raises: a reader that is not installed, not signed in or simply
    blocked leaves the caller with whatever the markup gave, which is still
    better than nothing.
    """
    try:
        from .claude_code_bridge import call_claude_code_json
    except ImportError:
        return {}
    try:
        answer = call_claude_code_json(
            _AI_READER_SYSTEM,
            f"Link: {url}",
            AI_READER_SCHEMA,
            timeout_seconds=AI_READER_TIMEOUT_SECONDS,
            allow_web=True,
        )
    except Exception:
        return {}
    if not isinstance(answer, dict) or not answer.get("readable"):
        return {}
    return {key: _clean(value)[:4000] for key, value in answer.items() if isinstance(value, str)}


def _merge_reader(product: dict[str, Any], read: dict[str, Any]) -> dict[str, Any]:
    """Markup wins on what it states; the reader fills what it cannot see.

    The two disagree in a useful way. JSON-LD carries the pictures, the SKU
    and the brand exactly, with no model in the loop. The reader carries the
    price and the rating, which the markup does not have at all. Neither
    overwrites a field the other established.
    """
    if not read:
        return product
    merged = dict(product)
    for key in ("name", "brand", "category", "description"):
        if not str(merged.get(key) or "").strip() and read.get(key):
            merged[key] = read[key]
    for key in ("price", "currency", "rating", "review_count", "sold_count"):
        if read.get(key):
            merged.setdefault(key, "")
            merged[key] = merged[key] or read[key]
    if read.get("note"):
        merged["reader_note"] = read["note"]
    return merged


def _usable(product: dict[str, Any]) -> bool:
    """Enough to be worth stopping at: a name plus a price or a picture.

    A name on its own is what Shopee gives a signed-out visitor, and stopping
    there would hide that the price was never read.
    """
    return bool(product.get("name")) and bool(product.get("price") or product.get("images"))


def saved_profile(url: str) -> str:
    """A browser profile saved for this site, or "".

    Not a promise that it is signed in - that cannot be told from outside, and
    the read itself is what finds out. Looked up rather than asked for, so a
    caller need not know which sites have one. Imported lazily to keep this
    module usable without Playwright installed.
    """
    try:
        from .shop_login import has_profile, profile_dir as shop_profile_dir
    except ImportError:
        return ""
    return str(shop_profile_dir(url)) if has_profile(url) else ""


# Kept as the old name for callers that read as though it meant signed in.
signed_in_profile = saved_profile


def read_product(url: str, *, profile_dir: str = "", use_ai: bool = True) -> dict[str, Any]:
    """Name, price, pictures and specs for a listing, by whichever route works.

    The markup is read first because it is free and instant, and because it
    carries the pictures. The AI reader is then asked for the fields the
    markup does not have - on every marketplace measured, that includes the
    price, which is the one field a writer is most likely to invent.
    """
    attempts: list[str] = []
    if not profile_dir:
        # A signed-in shopper is served the listing; a signed-out robot is
        # sent to the home page. Use the profile when there is one.
        profile_dir = saved_profile(url)
    read = read_with_ai(url) if use_ai else {}
    if read:
        attempts.append("ai_reader: đọc được trang")
    elif use_ai:
        attempts.append("ai_reader: không đọc được")

    try:
        html = fetch_static(url)
    except PageSourceError as exc:
        attempts.append(f"http: {exc}")
        html = ""
    if html:
        product = _merge_reader(product_from_ld(html), read)
        if _usable(product):
            return _finish(product, url, "http_jsonld", attempts, strip_markup(html))
        attempts.append("http: không có khối Product dùng được")
    if read:
        # The markup gave nothing usable but the reader did - which is exactly
        # what Shopee and TikTok look like. No browser needed.
        return _finish(_merge_reader({}, read), url, "ai_reader", attempts, "")

    try:
        rendered_html, rendered_text, final_url = fetch_rendered(url, profile_dir=profile_dir)
        if landed_elsewhere(url, final_url):
            # The listing was not served; the home page was. Its title is real
            # and belongs to the home page, so using it would name the source
            # "Shopee Việt Nam | Mua và Bán Trên Ứng Dụng Di Động".
            attempts.append("browser: bị chuyển sang trang khác")
            rendered_html, rendered_text = "", ""
    except PageSourceError as exc:
        attempts.append(str(exc))
        if html:
            fallback = product_from_meta(html)
            return _finish(fallback, url, "http_meta", attempts, strip_markup(html))
        raise

    tier = "browser_profile" if profile_dir else "browser"
    product = _merge_reader(product_from_ld(rendered_html), read)
    if _usable(product):
        return _finish(product, url, f"{tier}_jsonld", attempts, rendered_text)
    attempts.append(f"{tier}: không có khối Product dùng được")

    product = _merge_reader(product_from_meta(rendered_html) if rendered_html else {}, read)
    if not product.get("name") and rendered_text:
        product["name"] = rendered_text[:200]
    if not product.get("name"):
        # The marketplace writes the listing's title into its own URL.
        product["name"] = name_from_url(url)
    return _finish(
        product, url, f"{tier}_text" if rendered_html else "url_slug",
        attempts, rendered_text or (strip_markup(rendered_html) if rendered_html else ""),
    )


def _finish(
    product: dict[str, Any], url: str, route: str, attempts: list[str], text: str,
) -> dict[str, Any]:
    return {
        **product,
        "url": url,
        "route": route,
        # A price is only true on the day it was read.
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "attempts": attempts,
        "page_text": text[:24_000],
    }


def describe(product: dict[str, Any]) -> str:
    """The listing written out for a model to read, facts first."""
    rows = [
        ("Ten san pham", product.get("name")),
        ("Thuong hieu", product.get("brand")),
        ("Danh muc", product.get("category")),
        ("Ma SKU", product.get("sku")),
        ("Gia", " ".join(part for part in (product.get("price"), product.get("currency")) if part)),
        ("Danh gia", product.get("rating")),
        ("So luot danh gia", product.get("review_count")),
        ("So da ban", product.get("sold_count")),
        ("Tinh trang", product.get("availability")),
        ("Mo ta", product.get("description")),
        ("Ghi chu cua nguoi doc trang", product.get("reader_note")),
    ]
    lines = [f"{label}: {value}" for label, value in rows if str(value or "").strip()]
    if product.get("captured_at"):
        lines.append(f"Thoi diem doc trang: {product['captured_at']}")
    if not str(product.get("price") or "").strip():
        # Said out loud, because an absent price is the single field a writer
        # is most likely to fill in from nowhere.
        lines.append(
            "KHONG doc duoc gia tu trang nay. TUYET DOI khong tu dien gia vao kich ban."
        )
    body = str(product.get("page_text") or "").strip()
    if body:
        lines.append(f"\nNoi dung trang:\n{body[:8000]}")
    return "\n".join(lines)


def article_images(html: str, *, limit: int = MAX_IMAGES) -> list[str]:
    """Pictures an article publishes about itself, best first.

    An article with photographs was being analysed as though it had none, so
    its visual style came back empty and the scene planner had nothing to work
    from.
    """
    found: list[str] = []
    for block in _ld_blocks(html):
        image = block.get("image")
        for item in (image if isinstance(image, list) else [image]):
            if isinstance(item, dict):
                item = item.get("url")
            if str(item or "").strip():
                found.append(_absolute(str(item)))
    tags = meta_tags(html)
    for key in ("og:image", "twitter:image"):
        if tags.get(key):
            found.append(_absolute(tags[key]))
    seen: list[str] = []
    for item in found:
        if item not in seen and item.startswith("http"):
            seen.append(item)
    return seen[:limit]
