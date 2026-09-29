"""Reading a web page that is not a video: an article, or a product listing.

Measured on the three Vietnamese marketplaces the user actually sells from,
because they fail in three different ways and one route does not cover them:

  Lazada      plain HTTP, JSON-LD `Product` - name, six images, brand, but an
              Offer with no price in it; the price exists only on screen
  TikTok Shop needs a browser, and then renames the page's URL around the
              product id it was asked for
  Shopee      needs a browser AND a signed-in session; without one it sends
              the visitor to /verify/traffic/error "Cần đăng nhập"

So the product reader goes cheapest first - plain HTTP and the page's own
structured data - and then asks `platform_connections` for a browser that
is served the listing: the platform's own persistent profile, then the
person's own signed-in browser through the Browser Bridge. When none is, the answer says why (NEED_LOGIN,
NEED_HUMAN_VERIFY, ...) instead of looking like a thin success.

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


# Where each marketplace writes the listing's own id into its URLs.
_PRODUCT_IDS = (
    re.compile(r"/pdp/(?:[^/]+/)?(\d{8,})"),  # TikTok Shop, with or without the name
    re.compile(r"-i\.(\d+)\.(\d+)"),  # Shopee, name in the path
    re.compile(r"/product/(\d+)/(\d+)"),  # Shopee, short form
    re.compile(r"-i(\d+)(?:-s(\d+))?"),  # Lazada
    re.compile(r"-p(\d{5,})\.html"),  # Tiki
)


def product_id(url: str) -> str:
    """The listing's id as its marketplace writes it into the URL, or ""."""
    path = unquote(urlparse(str(url or "")).path)
    for pattern in _PRODUCT_IDS:
        match = pattern.search(path)
        if match:
            return ":".join(group for group in match.groups() if group)
    return ""


def landed_elsewhere(requested: str, final: str) -> bool:
    """True when the browser ended up on a different page than it asked for.

    Query strings and trailing slashes are ignored; what counts is being sent
    to a different path, which is how a marketplace refuses without refusing.
    A different path that still carries the same listing id is the same
    page: TikTok Shop answers /vn/pdp/<id> from /vn/pdp/<product-name>/<id>,
    and treating that as a refusal threw away a page that had been served.
    """
    asked = urlparse(str(requested or ""))
    got = urlparse(str(final or ""))
    if not got.path:
        return False
    if asked.path.rstrip("/").lower() == got.path.rstrip("/").lower():
        return False
    wanted = product_id(requested)
    return not (wanted and wanted == product_id(final))


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
    return _ld_from_texts(match.group(1) for match in _JSON_LD.finditer(str(html or "")))


def _ld_from_texts(texts: Any) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for text in texts:
        try:
            data = json.loads(str(text or "").strip())
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
    return _product_block(_ld_blocks(html))


def _product_block(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    for block in blocks:
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
        seller = offers.get("seller")
        seller_name = seller.get("name") if isinstance(seller, dict) else seller
        return {
            "name": _clean(block.get("name"))[:300],
            "seller": _clean(seller_name)[:120],
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
    return _product_from_tags(meta_tags(html))


def _product_from_tags(tags: dict[str, str]) -> dict[str, Any]:
    image = tags.get("og:image") or tags.get("twitter:image") or ""
    return {
        "name": _clean(tags.get("og:title") or tags.get("title"))[:300],
        "description": _clean(tags.get("og:description") or tags.get("description"))[:4000],
        "brand": "",
        "category": "",
        "sku": "",
        "price": _clean(tags.get("product:price:amount") or tags.get("price"))[:40],
        "currency": _clean(tags.get("product:price:currency") or tags.get("pricecurrency"))[:10],
        "availability": "",
        "images": [_absolute(image)] if image else [],
    }


_MONEY = re.compile(r"\d{1,3}(?:[.,]\d{3})+")

# A figure inside one of these sentences is a threshold or a fee, not what the
# listing costs. Measured on Lazada: "Nhận ngay Quà tặng khi mua từ 299.000 ₫"
# sat just under a flash-sale price of 267.000₫.
_NOT_THE_PRICE = (
    "khi mua", "mua từ", "đơn từ", "đơn tối thiểu", "phí vận chuyển", "phí giao", "vận chuyển",
    "giảm tối đa", "tiết kiệm", "voucher", "freeship", "miễn phí", "hoàn tiền",
)


def pick_display_price(prices: list[dict[str, Any]]) -> tuple[str, str]:
    """The price a listing shows as its own: (as shown, digits only).

    Measured on a page's visible money figures: the selling price is the
    largest one near the top that is not struck through. The struck one is
    the old price, the ones inside a promotion sentence are thresholds, and
    the small ones further down belong to other listings.
    """
    best: dict[str, Any] | None = None
    for item in prices or []:
        if item.get("struck") or float(item.get("top") or 0) > 2500:
            continue
        context = str(item.get("context") or "").lower()
        if any(marker in context for marker in _NOT_THE_PRICE):
            continue
        found = _MONEY.search(str(item.get("text") or ""))
        digits = found.group(0).replace(".", "").replace(",", "") if found else ""
        if not digits or int(digits) <= 0:
            continue
        key = (float(item.get("size") or 0), -float(item.get("top") or 0))
        if best is None or key > best["key"]:
            best = {"key": key, "text": _clean(item.get("text")), "digits": digits}
    return (best["text"], best["digits"]) if best else ("", "")


_DISCOUNT = re.compile(r"-\s?\d{1,2}\s?%")


def _amount(text: str) -> int:
    found = _MONEY.search(str(text or ""))
    return int(found.group(0).replace(".", "").replace(",", "")) if found else 0


def price_details(prices: list[dict[str, Any]]) -> dict[str, str]:
    """The selling price, and the old price and discount shown beside it.

    The old price is the struck figure in the same block that is higher than
    the selling price - measured on TikTok Shop "-62% ₫ 9.999 26.000₫", on
    Lazada "267.000₫ 326.000 ₫-18%", on Shopee "229.000₫ 450.000₫ -49%". A
    discount is taken as the page writes it, never worked out.
    """
    shown, digits = pick_display_price(prices)
    if not digits:
        return {}
    selling = int(digits)
    details = {"price": digits, "price_text": shown}
    home = next((item for item in prices or [] if not item.get("struck") and _amount(item.get("text")) == selling), {})
    block = str(home.get("context") or "")
    older = [
        item for item in prices or []
        if item.get("struck") and _amount(item.get("text")) > selling
        and (str(item.get("context") or "") == block or shown in str(item.get("context") or "")
             or abs(float(item.get("top") or 0) - float(home.get("top") or 0)) <= 80)
    ]
    if older:
        best = max(older, key=lambda item: (float(item.get("size") or 0), -abs(float(item.get("top") or 0) - float(home.get("top") or 0))))
        details["original_price"] = str(_amount(best.get("text")))
        details["original_price_text"] = _clean(best.get("text"))
    for text in [block] + [str(item.get("context") or "") for item in older]:
        found = _DISCOUNT.search(text)
        if found:
            details["discount"] = found.group(0).replace(" ", "")
            break
    return details


# How a listing names its seller and its standing in its own words, measured on
# TikTok Shop 29/09: "... Do Shop Gia Dụng Tú Anh bán 4.7 (1.1K) 19.8K đã được bán".
_SOLD_BY = re.compile(r"\bDo (.{2,60}?) bán\b|\bSold by (.{2,60}?)(?=\s\d|\s·|$)")
_STANDING = re.compile(r"(\d(?:[.,]\d)?)\s*\(([\d.,]+[KkMm]?)\)\s*([\d.,]+[KkMm]?\+?)\s*(?:đã (?:được )?bán|sold)")


def listing_facts_from_text(text: str) -> dict[str, str]:
    """Seller, rating, review count and sold count, where the page writes them."""
    facts: dict[str, str] = {}
    body = _clean(text)
    sold_by = _SOLD_BY.search(body)
    if sold_by:
        facts["seller"] = _clean(sold_by.group(1) or sold_by.group(2))[:120]
    standing = _STANDING.search(body[sold_by.end():] if sold_by else body)
    if standing:
        facts.update(rating=standing.group(1), review_count=standing.group(2), sold_count=standing.group(3))
    return facts


def canonical_url(tags: dict[str, str], fallback: str) -> str:
    """The listing's own address, without the tracking a visit adds to it."""
    return (str(tags.get("og:url") or "").strip() or str(fallback or "")).split("?", 1)[0].split("#", 1)[0]


def product_from_probe(probe: dict[str, Any]) -> dict[str, Any]:
    """The listing as a browser session saw it (see platform_connections.PROBE_JS).

    Structured data first, exactly as with plain HTTP; the price shown on
    screen fills in when the structured data has none, which on Lazada is
    always. Where the price came from is recorded next to it.
    """
    tags = {str(key).lower(): str(value) for key, value in (probe.get("meta") or {}).items()}
    product = _product_from_tags(tags)
    stated = _product_block(_ld_from_texts(probe.get("ld") or []))
    product.update({key: value for key, value in stated.items() if value})
    if not product.get("name"):
        product["name"] = _clean(probe.get("title"))[:300]
    if not product.get("images"):
        product["images"] = [
            _absolute(item) for item in (probe.get("images") or []) if str(item or "").startswith("http")
        ][:MAX_IMAGES]
    shown = price_details(probe.get("prices") or [])
    if product.get("price"):
        product["price_source"] = "jsonld" if stated.get("price") else "meta"
    elif shown:
        product.update(price=shown["price"], currency="VND", price_text=shown["price_text"], price_source="dom")
    # What the screen shows beside the price, whichever source gave the price.
    for key in ("original_price", "original_price_text", "discount"):
        if shown.get(key):
            product[key] = shown[key]
    product["canonical_url"] = canonical_url(tags, str(probe.get("url") or ""))
    for key, value in listing_facts_from_text(str(probe.get("text") or "")).items():
        if not product.get(key):
            product[key] = value
    return product


def fetch_static(url: str) -> str:
    try:
        response = httpx.get(
            url, headers=BROWSER_HEADERS, timeout=TIMEOUT_SECONDS, follow_redirects=True,
        )
        response.raise_for_status()
        return response.text
    except (httpx.HTTPError, ValueError) as exc:
        raise PageSourceError(f"Không tải được trang: {exc}") from exc


def fetch_rendered(url: str) -> tuple[str, str, str]:
    """Load an ordinary page in a headless browser: (html, visible text, final url).

    For pages that only exist once their script has run - a news site, a blog.
    Marketplaces do not come through here: they are read through
    `platform_connections`, which keeps a persistent profile per platform instead of
    the throwaway context used here.

    The final url matters: a site that has decided you are a robot may answer
    by sending you to its home page rather than by saying no.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PageSourceError("Chưa cài Playwright nên không mở được trang bằng trình duyệt") from exc
    try:
        with sync_playwright() as playwright:
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


def _merge_seen(markup: dict[str, Any], seen: dict[str, Any]) -> dict[str, Any]:
    """What plain HTTP stated wins; what the browser saw fills the gaps.

    The structured block fetched over HTTP carries the name, the SKU and the
    pictures exactly. The browser adds what only exists on screen - on Lazada
    that is the price.
    """
    merged = dict(seen)
    merged.update({key: value for key, value in markup.items() if value})
    return merged


def read_product(
    url: str, *, session_id: str = "", use_ai: bool = False, sessions: Any = None,
) -> dict[str, Any]:
    """Name, price, pictures and specs for a listing, cheapest route first.

    1. Plain HTTP and the page's own JSON-LD: free, instant, and it carries
       the pictures. Enough on its own when it states a price.
    2. A connection from `platform_connections`: the platform's own persistent
       profile, then the person's browser through the Browser Bridge. With
       `session_id` only that session is used.
    3. Otherwise a structured failure: whatever the markup and the URL said,
       with `read_status` saying why the listing itself was not read.

    `use_ai` adds the Claude CLI web reader as a last resort. It is off by
    default: measured on the three marketplaces it never returned a price.
    """
    from . import platform_connections

    attempts: list[str] = []
    html = ""
    try:
        html = fetch_static(url)
    except PageSourceError as exc:
        attempts.append(f"http: {exc}")
    walled = bool(html) and looks_like_bot_wall(page_title(html))
    if walled:
        attempts.append(f"http: tường chặn bot ({page_title(html)[:60]})")
    markup = product_from_ld(html) if html and not walled else {}
    if markup.get("price") and not session_id:
        return _finish(markup, url, "http_jsonld", attempts, strip_markup(html), read_status="OK")
    if markup:
        attempts.append("http: có khối Product nhưng không có giá")
    elif html and not walled:
        attempts.append("http: không có khối Product")

    outcome = (sessions or platform_connections.manager()).read(url, session_id=session_id)
    for item in outcome.get("attempts") or []:
        attempts.append(
            f"{item.get('session')}: {item.get('status')}"
            + (f" - {item.get('detail')}" if item.get("detail") else "")
        )
    if outcome.get("status") == "OK":
        probe = outcome.get("probe") or {}
        product = _merge_seen(markup, product_from_probe(probe))
        if not product.get("name"):
            product["name"] = name_from_url(url)
        return _finish(
            product, url, f"session:{outcome.get('session')}", attempts, str(probe.get("text") or ""),
            read_status="OK", session=str(outcome.get("session") or ""),
        )
    if not outcome.get("site") and outcome.get("detail"):
        attempts.append(str(outcome["detail"]))

    status = str(outcome.get("status") or "UNAVAILABLE")
    product = dict(markup)
    route = "http_jsonld" if markup else ""
    if use_ai:
        read = read_with_ai(url)
        attempts.append("ai_reader: đọc được trang" if read else "ai_reader: không đọc được")
        if read:
            product = _merge_reader(product, read)
            route, status = route or "ai_reader", "OK"
    if not product and html and not walled:
        product = product_from_meta(html)
        route = "http_meta" if _usable(product) else ""
        if not route:
            product = {}
    if not product.get("name"):
        # The marketplace writes the listing's title into its own URL.
        product["name"] = name_from_url(url)
    return _finish(
        product, url, route or "url_slug", attempts,
        strip_markup(html) if html and not walled else "",
        read_status=status, read_detail=str(outcome.get("detail") or ""),
        sessions=[
            {key: item.get(key) for key in ("id", "status", "detail", "can_read", "next_action") if item.get(key)}
            for item in outcome.get("sessions") or []
        ],
    )


def _finish(
    product: dict[str, Any], url: str, route: str, attempts: list[str], text: str, **extra: Any,
) -> dict[str, Any]:
    return {
        **product,
        "url": url,
        "product_id": product_id(url),
        "canonical_url": product.get("canonical_url") or url.split("?", 1)[0],
        "route": route,
        # A price is only true on the day it was read - and on TikTok Shop only
        # for the session that read it (measured 29/09: ₫9.999 in the person's
        # browser, ₫11.546 in the app's own profile, same listing, same hour).
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "attempts": attempts,
        "page_text": text[:24_000],
        **extra,
    }


def describe(product: dict[str, Any]) -> str:
    """The listing written out for a model to read, facts first."""
    rows = [
        ("Ten san pham", product.get("name")),
        ("Thuong hieu", product.get("brand")),
        ("Danh muc", product.get("category")),
        ("Ma SKU", product.get("sku")),
        ("Gia", " ".join(part for part in (product.get("price"), product.get("currency")) if part)),
        ("Gia nhu trang hien thi", product.get("price_text")),
        ("Gia goc (gach ngang tren trang)", product.get("original_price_text") or product.get("original_price")),
        ("Giam gia (trang ghi)", product.get("discount")),
        ("Nguoi ban / shop", product.get("seller")),
        ("Ma san pham", product.get("product_id")),
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
    status = str(product.get("read_status") or "OK")
    if status != "OK":
        # Everything above came from the URL or the markup around the page,
        # not from the listing a shopper sees.
        lines.append(
            f"TRANG SAN PHAM CHUA DOC DUOC ({status}). Cac thong tin tren chi lay tu duong dan/"
            "du lieu cau truc; khong co gi ve gia, danh gia hay mo ta that cua trang."
        )
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
