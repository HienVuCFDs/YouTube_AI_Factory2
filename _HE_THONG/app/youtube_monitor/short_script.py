"""A short written for its own sake, not cut out of the long video.

There are two honest ways to get a short, and this project wants both.

The one already here re-cuts the finished long video: it needs the long
video's scenes to exist and have voice, so it can only run at the end, and
what it produces is a condensed version of something the viewer may have
already seen. Cheap, fast, and it reuses every asset.

This one writes the short as its own piece from the same brief, in parallel
with the long script rather than after it. It gets its own hook, its own
through-line and its own ending, sized to the seconds a short actually has -
which is the only way a short opens on its strongest moment rather than on
whatever happened to be scene one.

It becomes a second script row for the project, so its shots, timeline,
voice and clips hang off its own script_id and the rest of the pipeline
needs to know nothing about it.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from .writer import VIETNAMESE_VOICE_TOKENS_PER_SECOND


class ShortScriptError(RuntimeError):
    """Raised when there is nothing to write a short from."""


MIN_SHORT_SCRIPT_SECONDS = 15
MAX_SHORT_SCRIPT_SECONDS = 60
DEFAULT_SHORT_SCRIPT_SECONDS = 45

# What is left for the body once the hook and the sign-off have taken theirs.
_HOOK_SHARE = 0.18
_CTA_SHARE = 0.12

ScriptWriter = Callable[[dict[str, Any]], dict[str, Any]]
_writer: ScriptWriter | None = None


def set_script_writer(callback: ScriptWriter | None) -> None:
    """Give the module the app's model. Without one it still works."""
    global _writer
    _writer = callback


RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "script_title": {"type": "string"},
        "hook": {"type": "string"},
        "main_content": {"type": "string"},
        "cta": {"type": "string"},
    },
    "required": ["script_title", "hook", "main_content", "cta"],
}


def word_budget(seconds: float) -> int:
    """How many words fit in the time, at the pace the voice actually reads.

    The long script has a target duration and is measured against it; a short
    has a hard ceiling instead. Writing to a word count keeps the finished
    clip inside the limit rather than discovering it is 80 seconds after the
    voice has been generated.
    """
    bounded = max(MIN_SHORT_SCRIPT_SECONDS, min(float(seconds), MAX_SHORT_SCRIPT_SECONDS))
    return int(bounded * VIETNAMESE_VOICE_TOKENS_PER_SECOND)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+|\n+", str(text or ""))
    return [part.strip() for part in parts if part.strip()]


def _take_words(sentences: list[str], budget: int) -> str:
    """Whole sentences up to the budget - a short cut mid-clause reads as an error."""
    kept: list[str] = []
    used = 0
    for sentence in sentences:
        length = len(sentence.split())
        if kept and used + length > budget:
            break
        kept.append(sentence)
        used += length
    return " ".join(kept)


def condense(script: dict[str, Any], seconds: float = DEFAULT_SHORT_SCRIPT_SECONDS) -> dict[str, Any]:
    """Make a short out of the long script without asking a model anything.

    Crude on purpose: it keeps the opening, because that is where a retold
    story states its premise, and stops at the budget. It exists so the
    feature works when no model is reachable, rather than failing.
    """
    budget = word_budget(seconds)
    hook = str(script.get("hook") or "").strip()
    body_source = " ".join(
        str(script.get(field) or "").strip()
        for field in ("intro", "main_content")
    ).strip()
    if not hook and not body_source:
        raise ShortScriptError("Kịch bản dài chưa có nội dung để rút thành short")

    hook_text = _take_words(_sentences(hook), max(6, int(budget * _HOOK_SHARE)))
    if not hook_text:
        hook_text = _take_words(_sentences(body_source), max(6, int(budget * _HOOK_SHARE)))
    # The sign-off is spoken too. Counting only the hook and the body let a
    # 45-second short come out at 58, and the platform - not the app - is
    # what cuts it.
    cta = _take_words(_sentences(script.get("cta")), max(4, int(budget * _CTA_SHARE)))
    remaining = max(10, budget - len(hook_text.split()) - len(cta.split()))
    body = _take_words(_sentences(body_source), remaining)
    if not body:
        body = hook_text
    return {
        "script_title": str(script.get("script_title") or "")[:200],
        "hook": hook_text,
        "intro": "",
        "main_content": body,
        "cta": cta,
    }


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def build_short_script(
    project: dict[str, Any],
    script: dict[str, Any],
    *,
    seconds: float = DEFAULT_SHORT_SCRIPT_SECONDS,
    direction: str = "",
    use_model: bool = True,
) -> dict[str, Any]:
    """Write the short's own words, falling back to condensing if it cannot."""
    if not script:
        raise ShortScriptError("Cần kịch bản dài của dự án trước khi viết bản short")
    budget = word_budget(seconds)
    if not use_model or _writer is None:
        return condense(script, seconds)

    request = {
        "seconds": int(seconds),
        "word_budget": budget,
        "direction": direction,
        "title": str(project.get("title") or script.get("script_title") or "")[:200],
        "long_script": {
            "hook": str(script.get("hook") or "")[:2000],
            "intro": str(script.get("intro") or "")[:2000],
            "main_content": str(script.get("main_content") or "")[:12000],
            "cta": str(script.get("cta") or "")[:1000],
        },
    }
    try:
        verdict = dict(_writer(request) or {})
    except Exception as exc:
        raise ShortScriptError(f"Không viết được kịch bản short: {exc}") from exc

    body = _clean(verdict.get("main_content"), 6000)
    hook = _clean(verdict.get("hook"), 600)
    if not body and not hook:
        # A model that returned nothing usable must not lose the feature.
        return condense(script, seconds)

    # The model is told the budget but is not bound by it, and a short that
    # runs long is the one failure mode that cannot be fixed later - the
    # platform cuts it. So the words are trimmed here, in whole sentences,
    # and every spoken part counts against the budget including the sign-off.
    cta = _take_words(_sentences(verdict.get("cta")), max(4, int(budget * _CTA_SHARE)))
    spent = len(hook.split()) + len(cta.split())
    body = _take_words(_sentences(body), max(10, budget - spent))
    return {
        "script_title": _clean(verdict.get("script_title") or script.get("script_title"), 200),
        "hook": hook,
        "intro": "",
        "main_content": body,
        "cta": cta,
    }


def estimated_seconds(script: dict[str, Any]) -> float:
    """How long the written short will actually take to read."""
    words = sum(
        len(str(script.get(field) or "").split())
        for field in ("hook", "intro", "main_content", "cta")
    )
    return round(words / VIETNAMESE_VOICE_TOKENS_PER_SECOND, 1)
