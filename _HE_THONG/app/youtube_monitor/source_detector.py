"""What a pasted link or a dropped file is, worked out before anything is saved.

The "Thêm nguồn" box takes a link or files and nothing else - nobody picks a
type first. This module decides what it was given and which of the importers
that already exist should take it; it imports nothing itself.

Cheapest first, stopping as soon as it is sure:

  1. the address or the file itself - YouTube's own URL shapes, the
     marketplaces the Product Reader knows, TikTok videos, news sites; a
     file's MIME type and extension. No network.
  2. yt-dlp's table of ~1800 sites, asked offline which one claims the URL.
  3. a metadata probe - the database or the YouTube Data API for YouTube,
     yt-dlp for any other video, the page's own tags for an article.
  4. the Product Reader for a listing, which may go through a browser session.

No model is asked. A link none of these recognise stays "web" with low
confidence and is imported the way a link always was.

Nothing here writes to the database. What it returns is shown to a person:
no session, route, cookie or raw error text is put into it.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import PurePosixPath
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from . import page_source, platform_connections, source_kinds
from .source_links import SourceLinkError, is_http_url, platform_of as extractor_platform
from .youtube_client import (
    YouTubeApiError,
    parse_channel_reference,
    parse_duration,
    parse_video_reference,
    thumbnail_url,
)

# What a detection can end in.
YOUTUBE_CHANNEL = "youtube_channel"
CHANNEL = "channel"  # a profile or a list on another platform: not followed
VIDEO = "video"
AUDIO = "audio"
PRODUCT = "product"
ARTICLE = "article"
WEB = "web"
IMAGE = "image"
IMAGE_COLLECTION = "image_collection"
INVALID = "invalid"
UNSUPPORTED = "unsupported"

# The filter a kind is counted under in the list of sources.
GROUPS = {
    VIDEO: "video", ARTICLE: "article", WEB: "article", PRODUCT: "product",
    AUDIO: "file", IMAGE: "file", IMAGE_COLLECTION: "file",
}
# What a detection is stored as once added (videos.source_kind, see
# source_kinds). A channel, a refused link or file is not stored as a source.
STORED_AS = {
    VIDEO: source_kinds.VIDEO, AUDIO: source_kinds.AUDIO, PRODUCT: source_kinds.PRODUCT,
    ARTICLE: source_kinds.ARTICLE, WEB: source_kinds.WEB,
    IMAGE: source_kinds.IMAGE_COLLECTION, IMAGE_COLLECTION: source_kinds.IMAGE_COLLECTION,
}

# How far the detection got, as the page words it.
DETECTED = "detected"
NEED_CONNECTION = "need_connection"
UNREADABLE = "unreadable"

# What the page offers to do next.
ADD_CHANNEL = "add_channel"
OPEN_CHANNEL = "open_channel"
ADD_SOURCE = "add_source"
UPLOAD = "upload"
CONNECT = "connect_platform"
NONE = "none"

# Product Reader platform key -> the name used here. "tiktok" there is the
# shop; here "tiktok" is the video platform.
MARKETPLACES = {"shopee": "shopee", "tiktok": "tiktok_shop", "lazada": "lazada", "tiki": "tiki", "sendo": "sendo"}
MARKETPLACE_LABELS = {
    "shopee": "Shopee", "tiktok_shop": "TikTok Shop", "lazada": "Lazada", "tiki": "Tiki", "sendo": "Sendo",
    "amazon": "Amazon", "aliexpress": "AliExpress", "taobao": "Taobao", "shein": "Shein", "temu": "Temu",
}
# Shops page_source knows are shops but the Product Reader has no connection for.
_OTHER_SHOPS = (("amazon.", "amazon"), ("aliexpress.", "aliexpress"), ("taobao.com", "taobao"),
                ("shein.com", "shein"), ("temu.com", "temu"))

# Sites whose pages are articles. A section or the home page is still a page
# to read, just not an article, so the path decides between the two.
NEWS_HOSTS = (
    "vnexpress.net", "tuoitre.vn", "thanhnien.vn", "dantri.com.vn", "vietnamnet.vn", "znews.vn",
    "zingnews.vn", "kenh14.vn", "cafef.vn", "cafebiz.vn", "vtv.vn", "nld.com.vn", "laodong.vn",
    "tienphong.vn", "baomoi.com", "genk.vn", "vietnamplus.vn", "soha.vn", "24h.com.vn", "vov.vn",
    "plo.vn", "vneconomy.vn", "medium.com", "substack.com", "wikipedia.org", "bbc.com", "bbc.co.uk",
    "cnn.com", "nytimes.com", "theguardian.com", "reuters.com", "apnews.com", "forbes.com",
)
_ARTICLE_SEGMENTS = {
    "tin-tuc", "news", "blog", "blogs", "article", "articles", "bai-viet", "post", "posts",
    "story", "stories", "wiki", "p",
}
_YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")
_TIKTOK_VIDEO = re.compile(r"^/@([^/]+)/(video|photo)/(\d+)")
_TIKTOK_PROFILE = re.compile(r"^/@([^/]+)/?$")
_TIKTOK_PRODUCT = re.compile(r"^/view/product/(\d+)")
_TIKTOK_SHORT_HOSTS = ("vm.tiktok.com", "vt.tiktok.com")
_HANDLE = re.compile(r"@[\w.\-]{3,100}")
_CHANNEL_ID = re.compile(r"UC[\w-]{22}")
_BARE_DOMAIN = re.compile(r"^[\w-]+(\.[\w-]+)+(:\d+)?(/|$)")
# A yt-dlp extractor for a whole profile or list rather than one video.
_COLLECTION_EXTRACTOR = re.compile(r"(User|Playlist|Channel|Tab|Search|Profile|Album|Collection|Series|Feed)")
_ARTICLE_LD_TYPES = {"article", "newsarticle", "blogposting", "report", "liveblogposting", "scholarlyarticle"}

RECALL_SECONDS = 15 * 60


def _result(
    kind: str, *, platform: str = "", url: str = "", native_id: str = "", title: str = "",
    thumbnail: str = "", metadata: dict[str, Any] | None = None, confidence: str = "high",
    action: str = ADD_SOURCE, status: str = DETECTED, message: str = "", detected_by: str = "url_rule",
    existing: dict[str, Any] | None = None, origin: str = "link",
) -> dict[str, Any]:
    return {
        "kind": kind, "group": GROUPS.get(kind, ""), "source_kind": STORED_AS.get(kind, ""),
        "platform": platform, "native_id": native_id,
        "url": url, "title": title, "thumbnail": thumbnail, "metadata": metadata or {},
        "confidence": confidence, "suggested_action": action, "status": status, "message": message,
        "detected_by": detected_by, "existing": existing or {}, "origin": origin,
    }


def _refused(kind: str, message: str, *, url: str = "", platform: str = "") -> dict[str, Any]:
    return _result(kind, url=url, platform=platform, confidence="high", action=NONE,
                   status=UNREADABLE if kind != INVALID else INVALID, message=message)


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for prefix in ("www.", "m."):
        host = host.removeprefix(prefix)
    return host


def _on(host: str, sites: tuple[str, ...]) -> bool:
    return any(host == site or host.endswith("." + site) for site in sites)


def _looks_like_article_path(path: str) -> bool:
    """A path that names one piece of writing rather than a section."""
    segments = [segment for segment in path.lower().split("/") if segment]
    if not segments:
        return False
    last = segments[-1]
    stem = re.sub(r"\.(s?html?|php|aspx?)$", "", last)
    words = [word for word in re.split(r"[-_]", stem) if word]
    return (
        (stem != last and len(words) >= 2)
        or len(words) >= 4
        or any(segment in _ARTICLE_SEGMENTS for segment in segments[:-1])
    )


# ---- 1 and 2: no network ---------------------------------------------------

def classify(text: str, *, extractor_of: Callable[[str], str] | None = None) -> dict[str, Any]:
    """What a pasted text is, from its shape alone. Never touches the network."""
    raw = str(text or "").strip().strip("<>\"' ")
    if not raw:
        return _refused(INVALID, "Dán một link, hoặc thả file vào đây.")
    if _CHANNEL_ID.fullmatch(raw):
        return _result(YOUTUBE_CHANNEL, platform="youtube", url=f"https://www.youtube.com/channel/{raw}",
                       native_id=raw, action=ADD_CHANNEL)
    if _HANDLE.fullmatch(raw):
        return _result(YOUTUBE_CHANNEL, platform="youtube", url=f"https://www.youtube.com/{raw}",
                       metadata={"handle": raw}, action=ADD_CHANNEL)
    url = raw
    if "://" not in url and " " not in url and _BARE_DOMAIN.match(url):
        url = f"https://{url}"
    if " " in url or not is_http_url(url):
        return _refused(INVALID, "Đây không phải một link. Link bắt đầu bằng http:// hoặc https://.")
    host = _host(url)
    path = unquote(urlparse(url).path or "/")

    if _on(host, _YOUTUBE_HOSTS):
        return _classify_youtube(url, path)
    market = platform_connections.platform_of(url)
    if market is not None:
        return _product(url, MARKETPLACES.get(market.key, market.key))
    if _on(host, ("tiktok.com",)) or host in _TIKTOK_SHORT_HOSTS:
        return _classify_tiktok(url, host, path)
    for marker, name in _OTHER_SHOPS:
        if marker in host:
            return _product(url, name)
    if _on(host, NEWS_HOSTS):
        if _looks_like_article_path(path):
            return _result(ARTICLE, platform="web", url=url, metadata={"domain": host})
        return _result(WEB, platform="web", url=url, metadata={"domain": host}, confidence="medium")

    extractor = (extractor_of or ytdlp_extractor)(url)
    if extractor:
        platform = extractor_platform(extractor)
        if _COLLECTION_EXTRACTOR.search(extractor):
            return _result(
                CHANNEL, platform=platform, url=url, action=NONE, detected_by="platform_detector",
                message="Đây là trang kênh hoặc danh sách, chưa thêm được như một nguồn. Hãy dán link một video.",
            )
        return _result(VIDEO, platform=platform, url=url, confidence="medium", detected_by="platform_detector")
    if _looks_like_article_path(path):
        return _result(ARTICLE, platform="web", url=url, metadata={"domain": host}, confidence="medium")
    return _result(WEB, platform="web", url=url, metadata={"domain": host}, confidence="low")


def _classify_youtube(url: str, path: str) -> dict[str, Any]:
    try:
        video_id = parse_video_reference(url)
    except ValueError:
        video_id = ""
    if video_id:
        short = path.startswith("/shorts/")
        return _result(
            VIDEO, platform="youtube", native_id=video_id, metadata={"is_short": short},
            url=f"https://www.youtube.com/shorts/{video_id}" if short else f"https://www.youtube.com/watch?v={video_id}",
        )
    if path.rstrip("/") == "/playlist" or "list" in parse_qs(urlparse(url).query):
        return _refused(UNSUPPORTED, "Danh sách phát chưa thêm được như một nguồn. Hãy dán link từng video, "
                                     "hoặc link của kênh.", url=url, platform="youtube")
    try:
        selector, value = parse_channel_reference(url)
    except ValueError:
        return _refused(UNSUPPORTED, "Link YouTube này không trỏ tới một video hay một kênh.",
                        url=url, platform="youtube")
    if selector == "id":
        return _result(YOUTUBE_CHANNEL, platform="youtube", url=f"https://www.youtube.com/channel/{value}",
                       native_id=value, action=ADD_CHANNEL)
    handle = value if value.startswith("@") or selector == "forUsername" else f"@{value}"
    return _result(
        YOUTUBE_CHANNEL, platform="youtube", url=url, action=ADD_CHANNEL,
        metadata={"username": value} if selector == "forUsername" else {"handle": handle},
    )


def _classify_tiktok(url: str, host: str, path: str) -> dict[str, Any]:
    match = _TIKTOK_VIDEO.match(path)
    if match:
        return _result(VIDEO, platform="tiktok", url=url.split("?", 1)[0], native_id=match.group(3),
                       metadata={"author": f"@{match.group(1)}", "is_photo": match.group(2) == "photo"})
    product = _TIKTOK_PRODUCT.match(path)
    if product:
        return _product(url, "tiktok_shop", native_id=product.group(1))
    if host in _TIKTOK_SHORT_HOSTS or path.startswith("/t/"):
        # A share link: it redirects to a video (usually), which the probe follows.
        return _result(VIDEO, platform="tiktok", url=url, confidence="medium", metadata={"short_link": True})
    if _TIKTOK_PROFILE.match(path):
        return _result(CHANNEL, platform="tiktok", url=url, action=NONE,
                       message="Chưa theo dõi được kênh TikTok. Hãy dán link một video của kênh.")
    return _refused(UNSUPPORTED, "Link TikTok này không trỏ tới một video.", url=url, platform="tiktok")


def _product(url: str, platform: str, *, native_id: str = "") -> dict[str, Any]:
    native_id = native_id or page_source.product_id(url)
    return _result(
        PRODUCT, platform=platform, url=url, native_id=native_id, title=name_from_url(url),
        metadata={"marketplace": MARKETPLACE_LABELS.get(platform, platform)},
        confidence="high" if native_id else "medium",
    )


def name_from_url(url: str) -> str:
    """The title a site writes into its own URL, without the id many put after it.

    A marketplace or a news site names the page in its path ("gia-vang-hom-
    nay-4800000.html", Tiki's "-p123456"); page_source reads the words.
    """
    return re.sub(r"\s+[a-z]?\d{5,}$", "", page_source.name_from_url(url), flags=re.I)


_EXTRACTORS: list[Any] | None = None
_EXTRACTORS_GUARD = threading.Lock()


def ytdlp_extractor(url: str) -> str:
    """The yt-dlp extractor that claims this URL, or "". Offline: regexes only."""
    global _EXTRACTORS
    with _EXTRACTORS_GUARD:
        if _EXTRACTORS is None:
            try:
                from yt_dlp.extractor import gen_extractor_classes

                # The catch-all claims everything and would say nothing.
                _EXTRACTORS = [item for item in gen_extractor_classes() if item.ie_key() != "Generic"]
            except Exception:  # pragma: no cover - a declared dependency
                _EXTRACTORS = []
    for extractor in _EXTRACTORS:
        try:
            if extractor.suitable(url):
                return str(extractor.ie_key())
        except Exception:
            continue
    return ""


# ---- 3 and 4: reading what the source says about itself -------------------

class _Recall:
    """The last detection per link, so adding it does not read the page again.

    A marketplace read may go through a browser session and take seconds;
    the add a moment later reuses it. Kept in memory for a short while only.
    """

    def __init__(self) -> None:
        self._items: dict[str, tuple[float, dict[str, Any], dict[str, Any]]] = {}
        self._guard = threading.Lock()

    def keep(self, url: str, detected: dict[str, Any], product: dict[str, Any] | None = None) -> None:
        with self._guard:
            now = time.monotonic()
            self._items = {key: item for key, item in self._items.items() if now - item[0] < RECALL_SECONDS}
            self._items[url] = (now, detected, product or {})

    def get(self, url: str) -> tuple[dict[str, Any], dict[str, Any]]:
        with self._guard:
            item = self._items.get(url)
        if not item or time.monotonic() - item[0] >= RECALL_SECONDS:
            return {}, {}
        return item[1], item[2]


RECALL = _Recall()


def recalled(url: str) -> dict[str, Any]:
    """The detection made for this link a moment ago, or {}."""
    return RECALL.get(url)[0]


def recent_product(url: str) -> dict[str, Any]:
    """The listing the Product Reader read for this link a moment ago, if it was served."""
    product = RECALL.get(url)[1]
    served = str(product.get("read_status") or "") == platform_connections.OK and _product_name(product)
    return product if served else {}


def _product_name(product: dict[str, Any]) -> str:
    name = str(product.get("name") or "").strip()
    return "" if page_source.looks_like_bot_wall(name) else name


def detect(
    text: str, *, probe: bool = True, database: Any = None, youtube: Any = None,
    probe_video: Callable[[str], dict[str, Any]] | None = None,
    fetch_page: Callable[[str], str] | None = None,
    read_product: Callable[[str], dict[str, Any]] | None = None,
    extractor_of: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """classify(), then - with `probe` - what the source says about itself."""
    detected = classify(text, extractor_of=extractor_of)
    if not probe or detected["status"] != DETECTED:
        return detected
    detected = dict(detected)
    kind = detected["kind"]
    try:
        if kind == YOUTUBE_CHANNEL:
            detected = _probe_youtube_channel(detected, database, youtube)
        elif kind == VIDEO and detected["platform"] == "youtube":
            detected = _probe_youtube_video(detected, database, youtube, probe_video)
        elif kind == VIDEO:
            detected = _probe_other_video(detected, database, probe_video)
        elif kind == PRODUCT:
            detected = _probe_product(detected, database, read_product or page_source.read_product)
        elif kind in (ARTICLE, WEB):
            detected = _probe_page(detected, database, fetch_page or page_source.fetch_static, probe_video)
    except Exception:  # a probe must never turn a detection into a crash
        detected = {**detected, "message": "Chưa đọc được thông tin của nguồn này lúc này."}
    # A page's own tags may have changed the kind; what it is stored as follows it.
    detected["group"] = GROUPS.get(detected["kind"], "")
    detected["source_kind"] = STORED_AS.get(detected["kind"], "")
    # The reader's own account (routes, sessions, attempts) stays in here.
    product = detected.pop("_product", None)
    if detected["url"]:
        RECALL.keep(detected["url"], detected, product)
    return detected


def _existing_video(database: Any, keys: list[str]) -> dict[str, Any]:
    for key in keys:
        row = database.get_video(key) if key else None
        if row:
            return {"video_id": str(row["youtube_video_id"]), "is_source": bool(database.is_source_item(key))}
    return {}


def _existing_page(database: Any, url: str) -> dict[str, Any]:
    """A page already stored from this link: under today's key, or any older one."""
    if database is None:
        return {}
    found = _existing_video(database, [page_link_key(url)])
    if not found:
        row = database.find_video_by_url(url)
        found = _existing_video(database, [str(row["youtube_video_id"])]) if row else {}
    return found


def _price_label(product: dict[str, Any]) -> str:
    """The price as the page showed it, or its structured value written the Vietnamese way."""
    shown = str(product.get("price_text") or "").strip()
    if shown or not product.get("price"):
        return shown
    currency = str(product.get("currency") or "").upper()
    try:
        amount = float(str(product["price"]).replace(",", ""))
    except ValueError:
        return f"{product['price']} {currency}".strip()
    if currency in ("VND", "₫", ""):
        return f"{amount:,.0f}".replace(",", ".") + "₫"
    return f"{amount:,.2f} {currency}"


def _probe_youtube_video(detected: dict[str, Any], database: Any, youtube: Any, probe_video: Any) -> dict[str, Any]:
    native = detected["native_id"]
    rows = database.find_videos_by_native_id("youtube", native) if database is not None else []
    key = next((str(row["youtube_video_id"]) for row in rows if row["youtube_video_id"] == native), "")
    key = key or (str(rows[0]["youtube_video_id"]) if rows else "")
    if key:
        # Already stored: its row says everything, and nothing is fetched.
        row = database.get_video(key) or {}
        channel = database.get_channel(str(row.get("youtube_channel_id") or "")) or {}
        return {
            **detected, "title": str(row.get("title") or ""), "detected_by": "database",
            "thumbnail": str(row.get("thumbnail_url") or f"https://i.ytimg.com/vi/{native}/mqdefault.jpg"),
            "metadata": {
                **detected["metadata"],
                "channel_name": str(row.get("native_channel_name") or channel.get("title") or ""),
                "duration_seconds": row.get("duration_seconds"), "published_at": row.get("published_at"),
                "view_count": row.get("view_count"),
            },
            "existing": _existing_video(database, [key]),
        }
    if youtube is not None and getattr(youtube, "api_key", ""):
        try:
            items = youtube.get_videos([native])
        except YouTubeApiError:
            items = None  # quota spent, or no network: yt-dlp may still read it
        if items == []:
            return {**detected, "status": UNREADABLE, "suggested_action": NONE, "detected_by": "metadata_probe",
                    "message": "Không tìm thấy video này. Có thể video đã bị xoá hoặc để riêng tư."}
        if items:
            snippet = items[0].get("snippet") or {}
            statistics = items[0].get("statistics") or {}
            return {
                **detected, "title": str(snippet.get("title") or ""), "detected_by": "metadata_probe",
                "thumbnail": thumbnail_url(snippet.get("thumbnails")),
                "metadata": {
                    **detected["metadata"], "channel_name": str(snippet.get("channelTitle") or ""),
                    "channel_id": str(snippet.get("channelId") or ""),
                    "duration_seconds": parse_duration((items[0].get("contentDetails") or {}).get("duration")),
                    "published_at": snippet.get("publishedAt"),
                    "view_count": _int(statistics.get("viewCount")),
                },
            }
    return _probe_other_video(detected, database, probe_video)


def _probe_other_video(detected: dict[str, Any], database: Any, probe_video: Any) -> dict[str, Any]:
    if probe_video is None:
        return detected
    try:
        details = probe_video(detected["url"])
    except SourceLinkError:
        return {**detected, "status": UNREADABLE, "suggested_action": NONE, "detected_by": "metadata_probe",
                "message": "Không đọc được video từ link này. Có thể video riêng tư, đã bị xoá, "
                           "hoặc trang không cho đọc tự động."}
    title = str(details.get("title") or "")
    return {
        **detected,
        "title": "" if title == details.get("webpage_url") else title,
        "thumbnail": str(details.get("thumbnail") or ""),
        "native_id": detected["native_id"] or str(details.get("native_id") or ""),
        "platform": detected["platform"] if detected["platform"] not in ("", "web")
        else str(details.get("platform_slug") or detected["platform"]),
        "detected_by": "metadata_probe",
        "metadata": {
            **detected["metadata"],
            "channel_name": str(details.get("channel_name") or details.get("uploader") or ""),
            "duration_seconds": details.get("duration_seconds") or None,
            "published_at": details.get("published_at"), "view_count": details.get("view_count"),
        },
        "existing": _existing_video(database, [str(details.get("video_id") or "")]) if database is not None else {},
    }


def _probe_youtube_channel(detected: dict[str, Any], database: Any, youtube: Any) -> dict[str, Any]:
    native = detected["native_id"]
    handle = str(detected["metadata"].get("handle") or "")
    row = None
    if database is not None:
        row = database.get_channel(native) if native else database.find_channel_by_handle(handle) if handle else None
    found: dict[str, Any] = dict(row) if row else {}
    by = "database" if row else "metadata_probe"
    if not found:
        if youtube is None or not getattr(youtube, "api_key", ""):
            return {**detected, "suggested_action": NONE,
                    "message": "Chưa đọc được thông tin kênh: app chưa có khóa YouTube API, nên chưa thêm được kênh."}
        try:
            found = youtube.get_channel(native or handle or detected["url"])
        except YouTubeApiError as exc:
            if exc.status_code == 404:
                return {**detected, "status": UNREADABLE, "suggested_action": NONE, "detected_by": by,
                        "message": "Không tìm thấy kênh YouTube này."}
            return {**detected, "message": "Chưa đọc được thông tin kênh lúc này. Thử lại sau."}
        row = database.get_channel(found["youtube_channel_id"]) if database is not None else None
    channel_id = str(found.get("youtube_channel_id") or native)
    return {
        **detected, "native_id": channel_id, "title": str(found.get("title") or ""),
        "thumbnail": str(found.get("thumbnail_url") or ""), "detected_by": by,
        "metadata": {
            **detected["metadata"], "handle": str(found.get("handle") or handle),
            "subscriber_count": found.get("subscriber_count"), "video_count": found.get("video_count"),
        },
        # Already followed: the page opens it in KÊNH instead of adding it again.
        "suggested_action": OPEN_CHANNEL if row else ADD_CHANNEL,
        "existing": {"channel_id": channel_id} if row else {},
    }


def _probe_product(detected: dict[str, Any], database: Any, read_product: Any) -> dict[str, Any]:
    url = detected["url"]
    product = read_product(url) or {}
    name = _product_name(product)
    read = str(product.get("read_status") or "")
    label = MARKETPLACE_LABELS.get(detected["platform"], detected["platform"])
    wrong_page = read == platform_connections.OK and not name
    if wrong_page:
        # Served a page, but not one naming this listing - a check page or
        # the shop's front page (measured 30/09 on TikTok Shop: a price and a
        # seller that belonged to neither). Nothing from it is shown.
        product = {}
    title = name or detected["title"]
    price_text = _price_label(product)
    metadata = {
        **detected["metadata"],
        "seller": str(product.get("seller") or product.get("brand") or ""),
        "price_text": price_text,
        # A price is only true when and where it was read.
        "captured_at": str(product.get("captured_at") or "") if price_text else "",
        "rating": str(product.get("rating") or ""), "sold_count": str(product.get("sold_count") or ""),
    }
    images = [str(item) for item in (product.get("images") or []) if str(item).startswith("http")]
    status, message = DETECTED, ""
    if wrong_page:
        status = NEED_CONNECTION
        message = (f"Chưa đọc được thông tin sản phẩm: {label} không mở ra trang của sản phẩm này. "
                   f"Hãy kiểm tra kết nối {label} trong Công cụ & kết nối rồi thử lại.")
    elif read in (platform_connections.NEED_LOGIN, platform_connections.NEED_HUMAN_VERIFY,
                  platform_connections.UNAVAILABLE, platform_connections.SKIPPED):
        status = NEED_CONNECTION
        message = (f"Chưa đọc được thông tin sản phẩm: {label} đang yêu cầu xác minh. Hãy tự xác minh trong "
                   "Công cụ & kết nối rồi thử lại." if read == platform_connections.NEED_HUMAN_VERIFY
                   else f"Chưa đọc được thông tin sản phẩm: cần kết nối {label} trong Công cụ & kết nối.")
    elif read and read != platform_connections.OK:
        status, message = UNREADABLE, "Chưa đọc được thông tin sản phẩm."
    elif not price_text:
        message = "Đã đọc được sản phẩm nhưng chưa thấy giá."
    existing = _existing_page(database, url)
    return {
        **detected, "title": title, "thumbnail": images[0] if images else "", "metadata": metadata,
        "status": status, "message": message, "detected_by": "product_reader", "existing": existing,
        # Without even a name there is nothing to add yet; connecting comes first.
        "suggested_action": ADD_SOURCE if title else CONNECT,
        "_product": product,
    }


def _ld_types(html: str) -> set[str]:
    types: set[str] = set()
    for block in page_source._ld_blocks(html):
        stack = [block]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                kind = item.get("@type")
                for value in kind if isinstance(kind, list) else [kind]:
                    if isinstance(value, str):
                        types.add(value.lower())
                stack.extend(value for value in item.values() if isinstance(value, (dict, list)))
    return types


def _probe_page(detected: dict[str, Any], database: Any, fetch_page: Any, probe_video: Any) -> dict[str, Any]:
    url = detected["url"]
    try:
        html = fetch_page(url)
    except page_source.PageSourceError:
        html = ""
    title = page_source.page_title(html) if html else ""
    if page_source.looks_like_bot_wall(title):
        html, title = "", ""
    tags = page_source.meta_tags(html) if html else {}
    kind = detected["kind"]
    unsure = kind == WEB or detected["confidence"] != "high"
    product = page_source.product_from_ld(html) if html and unsure else {}
    types = _ld_types(html) if html and unsure else set()
    if product.get("name"):
        # A listing on a shop the URL rules do not know.
        return {
            **detected, "kind": PRODUCT, "group": GROUPS[PRODUCT], "title": str(product["name"])[:300],
            "thumbnail": next(iter(product.get("images") or []), "") or str(tags.get("og:image") or ""),
            "detected_by": "metadata_probe", "confidence": "medium",
            "metadata": {**detected["metadata"], "site_name": str(tags.get("og:site_name") or ""),
                         "price_text": _price_label(product), "seller": str(product.get("brand") or "")},
            "existing": _existing_page(database, url),
        }
    og_type = str(tags.get("og:type") or "").lower()
    if unsure and (og_type.startswith("video") or "videoobject" in types) and probe_video is not None:
        video = _probe_other_video({**detected, "kind": VIDEO, "group": GROUPS[VIDEO]}, database, probe_video)
        if video["status"] == DETECTED:
            return video
    if kind == WEB and (og_type == "article" or types & _ARTICLE_LD_TYPES):
        kind = ARTICLE
    metadata = {
        **detected["metadata"],
        "site_name": str(tags.get("og:site_name") or ""),
        "description": str(tags.get("og:description") or tags.get("description") or "")[:300],
        "published_at": str(tags.get("article:published_time") or ""),
    }
    result = {
        **detected, "kind": kind, "group": GROUPS[kind], "detected_by": "metadata_probe" if html else detected["detected_by"],
        "title": title[:300] or name_from_url(url),
        "thumbnail": str(tags.get("og:image") or ""), "metadata": metadata,
        "existing": _existing_page(database, url),
    }
    if not html:
        result["message"] = "Chưa mở được trang lúc này. Khi thêm, app sẽ thử đọc lại bằng trình duyệt."
    return result


def page_link_key(url: str) -> str:
    """The row key a page imported from this link is stored under (see main._probe_page_link)."""
    import hashlib

    return f"web-{hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]}"


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---- files -------------------------------------------------------------------

def _file_kind(mime: str, extension: str, extensions: dict[str, set[str]]) -> str:
    by_type = next((kind for kind in ("image", "video", "audio") if mime.startswith(kind + "/")), "")
    by_name = next((kind for kind in ("image", "video", "audio") if extension in extensions.get(kind, set())), "")
    if by_type and by_name and by_type != by_name:
        # .webm is both: the browser read the header, so its answer stands
        # where the importer takes that extension for it.
        return by_type if extension in extensions.get(by_type, set()) else by_name
    kind = by_type or by_name
    return kind if kind and extension in extensions.get(kind, set()) else ""


def detect_files(
    files: list[dict[str, Any]], *, extensions: dict[str, set[str]], max_bytes: int,
) -> list[dict[str, Any]]:
    """Group dropped or picked files into sources: every image together, each video or audio alone.

    Only the name, the browser's MIME type, the size and a folder path are
    looked at; the bytes stay in the browser until the person confirms.
    """
    images: list[dict[str, Any]] = []
    folders: set[str] = set()
    results: list[dict[str, Any]] = []
    for index, item in enumerate(files):
        name = PurePosixPath(str(item.get("name") or "").replace("\\", "/")).name
        extension = PurePosixPath(name).suffix.lower()
        mime = str(item.get("type") or "").lower()
        size = int(item.get("size") or 0)
        entry = {"index": int(item.get("index", index)), "name": name, "size": size, "type": mime}
        kind = _file_kind(mime, extension, extensions)
        problem = ""
        if not kind:
            problem = f"Chưa hỗ trợ loại file này ({extension or mime or 'không rõ'})."
        elif size <= 0:
            problem = "File rỗng."
        elif size > max_bytes:
            problem = "File quá lớn để tải lên."
        if problem:
            results.append(_file_result(UNSUPPORTED, [entry], name, action=NONE, status=UNREADABLE, message=problem))
            continue
        if kind == "image":
            images.append(entry)
            parts = [part for part in str(item.get("path") or "").replace("\\", "/").split("/") if part]
            folders.add(parts[0] if len(parts) > 1 else "")
        else:
            results.append(_file_result(VIDEO if kind == "video" else AUDIO, [entry], PurePosixPath(name).stem))
    if images:
        folder = next(iter(folders)) if len(folders) == 1 else ""
        title = folder or (PurePosixPath(images[0]["name"]).stem if len(images) == 1 else f"Bộ ảnh ({len(images)} ảnh)")
        results.insert(0, _file_result(IMAGE if len(images) == 1 else IMAGE_COLLECTION, images, title))
    return results


def _file_result(
    kind: str, entries: list[dict[str, Any]], title: str, *, action: str = UPLOAD,
    status: str = DETECTED, message: str = "",
) -> dict[str, Any]:
    return _result(
        kind, platform="local", title=title[:200], action=action, status=status, message=message,
        detected_by="file_type", origin="file",
        metadata={"files": entries, "file_count": len(entries), "total_size": sum(item["size"] for item in entries)},
    )
