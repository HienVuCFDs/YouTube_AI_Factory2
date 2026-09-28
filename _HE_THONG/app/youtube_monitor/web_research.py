"""Looking things up, for whoever is directing.

An orchestrator drove the whole pipeline with no way to check a single fact:
of the tools it could reach, none searched for anything. The one search in the
codebase was buried inside the folklore writer and served that one purpose.

This is the same transport - the site's HTML endpoint, titles and snippets
only - offered as a tool instead. It returns pointers, never a body of text to
copy: the writer is expected to read the results and write its own words, and
a failed lookup returns an empty list rather than stopping a run, because a
video does not become unmakeable because a search engine was unreachable.
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import quote_plus, unquote, urlparse

import httpx

TIMEOUT_SECONDS = 12.0
MAX_RESULTS = 10
# Wikipedia answers 403 to a generic agent, as its policy says it will, so the
# name says what this is rather than pretending to be a browser.
_HEADERS = {"User-Agent": "YouTubeAIFactory/1.0 (local video production tool)"}
_RESULT = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'.*?class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.S | re.I,
)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


def _real_url(href: str) -> str:
    """DuckDuckGo hands back its own redirect; the caller wants the site."""
    if "uddg=" in href:
        tail = href.split("uddg=", 1)[1].split("&", 1)[0]
        return unquote(tail)
    if href.startswith("//"):
        return "https:" + href
    return href


def _duckduckgo(text: str) -> str:
    response = httpx.get(
        f"https://html.duckduckgo.com/html/?q={quote_plus(text)}",
        headers=_HEADERS, timeout=TIMEOUT_SECONDS, follow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def _parse_duckduckgo(body: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for match in _RESULT.finditer(body):
        url = _real_url(match.group("href"))
        host = (urlparse(url).hostname or "").lower()
        if not host:
            continue
        found.append({
            "title": _clean(match.group("title"))[:200],
            "snippet": _clean(match.group("snippet"))[:400],
            "url": url[:600],
            "source": host,
        })
    return found


_LITE_RESULT = re.compile(
    r'<a[^>]+href="(?P<href>[^"]+)"[^>]+class=.result-link.[^>]*>(?P<title>.*?)</a>'
    r".*?class=.result-snippet.[^>]*>(?P<snippet>.*?)</td>",
    re.S | re.I,
)


def _duckduckgo_lite(text: str) -> list[dict[str, str]]:
    """The same engine's plain endpoint, whose markup is laid out differently.

    One page shape meant one point of failure: the result pattern stops
    matching and the step reports "researched nothing" while the engine is
    answering perfectly well. Tried second because it is a different page,
    not a different company - a real second opinion needs a second index, and
    the free ones reachable from here answer with a captcha.
    """
    response = httpx.get(
        f"https://lite.duckduckgo.com/lite/?q={quote_plus(text)}",
        headers=_HEADERS, timeout=TIMEOUT_SECONDS, follow_redirects=True,
    )
    response.raise_for_status()
    found: list[dict[str, str]] = []
    for match in _LITE_RESULT.finditer(response.text):
        url = _real_url(match.group("href"))
        host = (urlparse(url).hostname or "").lower()
        if not host:
            continue
        found.append({
            "title": _clean(match.group("title"))[:200],
            "snippet": _clean(match.group("snippet"))[:400],
            "url": url[:600],
            "source": host,
        })
    return found


def _wikipedia(text: str) -> list[dict[str, str]]:
    """A last resort when neither search page answers.

    Open, no key, and in the publishing language - but it refuses some
    networks outright with a 403, so it is tried after the search pages
    rather than relied on.
    """
    response = httpx.get(
        "https://vi.wikipedia.org/w/api.php",
        params={
            "action": "query", "list": "search", "srsearch": text,
            "format": "json", "srlimit": MAX_RESULTS,
        },
        headers=_HEADERS, timeout=TIMEOUT_SECONDS, follow_redirects=True,
    )
    response.raise_for_status()
    payload = response.json()
    found: list[dict[str, str]] = []
    for item in (payload.get("query") or {}).get("search") or []:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        found.append({
            "title": title[:200],
            "snippet": _clean(str(item.get("snippet") or ""))[:400],
            "url": f"https://vi.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}"[:600],
            "source": "vi.wikipedia.org",
        })
    return found


def _wikipedia_extract(title: str, *, max_chars: int = 4000) -> str:
    """The article's own plain text, through the API.

    Scraping the page for it earns a 403: Wikipedia asks tools to use the API,
    and the API hands over cleaner text than stripping tags ever would.
    """
    try:
        response = httpx.get(
            "https://vi.wikipedia.org/w/api.php",
            params={
                "action": "query", "prop": "extracts", "explaintext": "1",
                "redirects": "1", "titles": title, "format": "json",
            },
            headers=_HEADERS, timeout=TIMEOUT_SECONDS, follow_redirects=True,
        )
        response.raise_for_status()
        pages = ((response.json().get("query") or {}).get("pages") or {}).values()
    except (httpx.HTTPError, ValueError, AttributeError, KeyError, TypeError):
        return ""
    for page in pages:
        extract = " ".join(str(page.get("extract") or "").split())
        if extract:
            return extract[:max(200, int(max_chars))]
    return ""


def search(query: str, *, limit: int = 5, read_pages: int = 0) -> list[dict[str, str]]:
    """Titles, snippets and links for a query. Never raises.

    With `read_pages`, the top results are also opened and their readable text
    is attached. Titles and snippets are a table of contents, not information:
    a writer handed only those still has to invent the substance, which is the
    thing the research step exists to prevent.
    """
    text = " ".join(str(query or "").split())
    if not text:
        return []
    limit = max(1, min(int(limit or 5), MAX_RESULTS))

    found: list[dict[str, str]] = []
    attempts = (
        lambda: _parse_duckduckgo(_duckduckgo(text)),
        lambda: _duckduckgo_lite(text),
        lambda: _wikipedia(text),
    )
    for attempt in attempts:
        try:
            found = attempt()
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            found = []
        if found:
            break

    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in found:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        results.append(item)
        if len(results) >= limit:
            break

    for item in results[:max(0, int(read_pages or 0))]:
        body = (
            _wikipedia_extract(item["title"])
            if item["source"].endswith("wikipedia.org")
            else read_page(item["url"])
        )
        if body:
            item["text"] = body
    return results


def read_page(url: str, *, max_chars: int = 4000) -> str:
    """The readable text of a page, or "" when it cannot be had.

    Kept deliberately crude - strip the script and style blocks, drop the
    tags, collapse the whitespace. It is meant to give a writer something real
    to work from, not to reconstruct the page.
    """
    try:
        response = httpx.get(
            url, headers=_HEADERS, timeout=TIMEOUT_SECONDS, follow_redirects=True,
        )
        response.raise_for_status()
        if "html" not in response.headers.get("content-type", "text/html").lower():
            return ""
        body = response.text
    except (httpx.HTTPError, ValueError):
        return ""
    body = re.sub(r"(?is)<(script|style|nav|footer|header|form)[^>]*>.*?</\1>", " ", body)
    return _clean(body)[:max(200, int(max_chars))]


def summarise(query: str, results: list[dict[str, str]]) -> dict[str, Any]:
    """What a caller needs to decide whether the lookup was any use."""
    return {
        "query": " ".join(str(query or "").split()),
        "count": len(results),
        "sources": sorted({item["source"] for item in results}),
        "results": results,
        # Said plainly, because a model handed an empty list otherwise tends
        # to fill the gap from memory and present it as researched.
        "note": (
            "Đây chỉ là tiêu đề và trích đoạn để định hướng, không phải nội dung đã kiểm chứng."
            if results
            else "Không tra được kết quả nào. Đừng coi đây là đã nghiên cứu."
        ),
    }
