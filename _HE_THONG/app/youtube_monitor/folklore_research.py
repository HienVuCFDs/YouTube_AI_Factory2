"""Small, optional web research helper for original folklore remakes.

Only search-result titles and snippets are used as idea pointers.  The writer is
explicitly told to create an original plot, never to retell or scrape a source.
Network failure is deliberately non-fatal: creative writing still works offline.
"""
from __future__ import annotations

import html
import re
from urllib.parse import quote_plus

import httpx


_ANIMAL_RE = re.compile(r"sự\s*tích\s*(?:về\s*)?(?:con\s+)?([\wÀ-ỹ]+)", re.IGNORECASE)
_FALLBACK_ANIMALS = ("mèo", "chó", "gà", "vịt", "cóc", "quạ", "thỏ")


def source_animal(title: str) -> str:
    match = _ANIMAL_RE.search(title or "")
    return match.group(1).strip().lower() if match else ""


def _clean(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def research_folklore_remake(title: str, direction: str = "") -> dict[str, object] | None:
    """Return lightweight, attribution-ready discovery hints for an animal folktale."""
    animal = source_animal(title)
    source = f"{title} {direction}".lower()
    if not animal and "sự tích" not in source and "cổ tích" not in source:
        return None
    candidates = [item for item in _FALLBACK_ANIMALS if item != animal]
    query = "truyện cổ tích Việt Nam sự tích con " + " ".join(candidates[:4])
    results: list[dict[str, str]] = []
    try:
        response = httpx.get(
            f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
            headers={"User-Agent": "Mozilla/5.0 YouTube-AI-Factory/1.0"},
            timeout=8.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        for match in re.finditer(
            r'class="result__a"[^>]*>(?P<title>.*?)</a>.*?class="result__snippet"[^>]*>(?P<snippet>.*?)</(?:a|div)>',
            response.text,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            item_title, snippet = _clean(match.group("title")), _clean(match.group("snippet"))
            if item_title:
                results.append({"title": item_title[:180], "snippet": snippet[:300]})
            if len(results) == 4:
                break
    except (httpx.HTTPError, ValueError):
        pass
    return {
        "mode": "folklore_discovery",
        "source_animal": animal,
        "suggested_target_animals": candidates[:4],
        "query": query,
        "results": results,
    }
