"""One video, but not one caption.

The same words do not work in every feed. A YouTube title is read in a search
result and can carry a full clause; a TikTok caption is read over the video
while it plays and has to be short; Reels lives on hashtags. Posting one
video everywhere with one set of metadata is the commonest reason a reup does
well on one platform and disappears on the others.

These are shaping rules, not writing: the words still come from the writer.
What differs is length, where the hashtags go, and which call to action makes
sense where - subscribing is a YouTube idea, following is a TikTok one.
"""

from __future__ import annotations

import re
from typing import Any

# What each destination can actually show before it truncates.
PLATFORM_LIMITS: dict[str, dict[str, int]] = {
    "youtube": {"title": 100, "description": 5000, "tags": 15},
    "tiktok": {"title": 90, "description": 2200, "tags": 8},
    "facebook": {"title": 120, "description": 2000, "tags": 10},
    "instagram": {"title": 120, "description": 2200, "tags": 12},
}

# A call to action names the thing that platform actually does.
PLATFORM_CTA: dict[str, str] = {
    "youtube": "Đăng ký kênh để xem phần tiếp theo.",
    "tiktok": "Theo dõi để xem phần sau.",
    "facebook": "Theo dõi trang để xem phần sau.",
    "instagram": "Theo dõi để xem phần sau.",
}

# Where the hashtags belong. On YouTube they are a tags field and clutter the
# description; in the short-form feeds they are the description.
HASHTAGS_IN_BODY = {"tiktok", "instagram", "facebook"}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _trim(text: str, limit: int) -> str:
    """Cut at a word, not mid-word, and only when it actually overruns."""
    text = _clean(text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:-") + "…"


def _first_sentences(text: str, limit: int) -> str:
    """As many whole sentences as fit - a caption cut mid-clause reads badly."""
    sentences = re.split(r"(?<=[.!?…])\s+", _clean(text))
    kept: list[str] = []
    used = 0
    for sentence in sentences:
        if kept and used + len(sentence) + 1 > limit:
            break
        kept.append(sentence)
        used += len(sentence) + 1
    return " ".join(kept) if kept else _trim(text, limit)


def normalise_tags(tags: list[str] | None) -> list[str]:
    """Bare words for a tags field, and the same list is hashtagged later."""
    seen: list[str] = []
    for raw in tags or []:
        tag = _clean(raw).lstrip("#")
        if tag and tag.lower() not in {item.lower() for item in seen}:
            seen.append(tag)
    return seen


def build(
    platform: str,
    *,
    title: str,
    description: str,
    tags: list[str] | None = None,
    cta: str = "",
    is_short: bool = False,
) -> dict[str, Any]:
    """The copy for one destination, shaped to what it shows."""
    key = str(platform or "youtube").strip().lower()
    limits = PLATFORM_LIMITS.get(key, PLATFORM_LIMITS["youtube"])
    clean_tags = normalise_tags(tags)[: limits["tags"]]
    call = _clean(cta) or PLATFORM_CTA.get(key, PLATFORM_CTA["youtube"])

    headline = _trim(title, limits["title"])

    if key in HASHTAGS_IN_BODY:
        # The feed reads the caption over the video, so it opens with the
        # hook and closes with the hashtags; nobody scrolls a caption.
        body_limit = max(80, limits["description"] - len(call) - 2 - sum(len(t) + 2 for t in clean_tags))
        body = _first_sentences(description or title, min(body_limit, 400 if is_short else body_limit))
        parts = [body, call, " ".join(f"#{tag.replace(' ', '')}" for tag in clean_tags)]
        caption = "\n\n".join(part for part in parts if part.strip())
    else:
        # YouTube has a real description field and a separate tags field.
        body = _first_sentences(description or title, limits["description"] - len(call) - 4)
        caption = "\n\n".join(part for part in (body, call) if part.strip())

    return {
        "platform": key,
        "title": headline,
        "description": _trim(caption, limits["description"]) if len(caption) > limits["description"] else caption,
        "tags": clean_tags,
        "cta": call,
        "hashtags_in_description": key in HASHTAGS_IN_BODY,
        "limits": dict(limits),
    }


def build_all(
    platforms: list[str],
    *,
    title: str,
    description: str,
    tags: list[str] | None = None,
    cta: str = "",
    is_short: bool = False,
) -> dict[str, dict[str, Any]]:
    return {
        str(platform).strip().lower(): build(
            platform, title=title, description=description,
            tags=tags, cta=cta, is_short=is_short,
        )
        for platform in platforms
        if str(platform).strip()
    }
