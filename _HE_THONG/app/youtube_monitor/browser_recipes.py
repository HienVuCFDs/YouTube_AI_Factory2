"""Driving a known chat page without asking a model what to click next.

The browser extension runs an observe → decide → act loop and asks the
orchestrator for every single step, up to thirty of them. That was written so
the agent could cope with whatever the live site actually shows, and it does -
but it made drawing one picture cost thirty model calls, and it made the whole
provider stop dead when no text model was available at all. The recorded
failures say exactly that: ten consecutive refusals on ChatGPT web, three on
Gemini web, every one of them `502 Không có AI được phép thực hiện công đoạn
orchestration`.

For a chat site the steps are not a puzzle. Type the prompt, press send, wait,
take the picture that appears. This module answers those steps from the page
snapshot alone, and returns None the moment it sees anything it does not
recognise - then the model-driven loop runs exactly as before.

Two limits are deliberate:

- only the chat sites are handled here. Flow and Meta AI put image mode and
  video mode behind tabs in the same composer, and a wrong click there spends
  the user's paid generations; that judgement stays with the model.
- "done" is only ever claimed for media that was not on the page when the run
  started. A chat page is full of earlier pictures, and returning one of those
  would hand back a picture from a different scene.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


PROMPT_MARKER = "PROMPT CAN GUI:"

# A page that has been told to draw and has not drawn yet is simply slow:
# images take upwards of a minute. After this many waits the run is handed to
# the model, which can read a refusal or a rate-limit notice that this module
# cannot.
MAX_WAITS = 14

# Media smaller than this is an avatar or an icon, not a generated picture.
# The snapshot already filters below 120px; this is the second gate, applied
# to what the site draws inline.
MIN_RESULT_PIXELS = 200


@dataclass(frozen=True)
class SiteRecipe:
    key: str
    hosts: tuple[str, ...]
    # Ordered strongest-first. An id or a test id is a contract the site keeps
    # across redesigns far more often than a class name or a label does.
    prompt_ids: tuple[str, ...] = ()
    prompt_testids: tuple[str, ...] = ()
    prompt_classes: tuple[str, ...] = ()
    send_testids: tuple[str, ...] = ()
    send_labels: tuple[str, ...] = ()


RECIPES: tuple[SiteRecipe, ...] = (
    SiteRecipe(
        key="chatgpt_web",
        hosts=("chatgpt.com", "chat.openai.com"),
        prompt_ids=("prompt-textarea",),
        prompt_testids=("prompt-textarea",),
        prompt_classes=("prosemirror",),
        send_testids=("send-button", "composer-submit-button"),
        send_labels=("send", "gửi", "gui", "submit"),
    ),
    SiteRecipe(
        key="gemini_web",
        hosts=("gemini.google.com",),
        prompt_classes=("ql-editor", "textarea-wrapper", "text-input"),
        send_labels=("send", "gửi", "gui", "submit", "run"),
    ),
)

# One entry per run, holding the media already on the page before the prompt
# was sent. Keyed by the prompt itself, which is what makes a run unique.
_BASELINES: dict[str, dict[str, Any]] = {}
_BASELINE_TTL_SECONDS = 3600.0
_BASELINE_MAX = 200


def _host(url: str) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


def recipe_for(url: str) -> SiteRecipe | None:
    host = _host(url)
    if not host:
        return None
    for recipe in RECIPES:
        if any(host == known or host.endswith("." + known) for known in recipe.hosts):
            return recipe
    return None


def prompt_from_goal(goal: str) -> str:
    """The text to type, which the extension appends under a fixed marker."""
    text = str(goal or "")
    if PROMPT_MARKER not in text:
        return ""
    return text.split(PROMPT_MARKER, 1)[1].strip()


def _wants_reference_image(goal: str) -> bool:
    return "anh tham chieu" in str(goal or "").lower()


def _actions_taken(history: list[str]) -> list[str]:
    """Every action already performed, main steps and follow-ups alike.

    The loop writes a main step as "3. type(5) — why" and a follow-up as
    "   + click(7)"; a follow-up that fails is written as "   + click(7):
    dung lai - ...", and reading that as a completed click would leave the
    prompt typed and never sent.
    """
    done: list[str] = []
    for line in history or []:
        main = re.match(r"^\d+\.\s*([a-z_]+)", str(line))
        if main:
            done.append(main.group(1))
            continue
        follow = re.match(r"^\s+\+\s*([a-z_]+)(\([0-9]+\))?\s*$", str(line))
        if follow:
            done.append(follow.group(1))
    return done


def _text_of(element: dict[str, Any], *keys: str) -> str:
    return " ".join(str(element.get(key) or "") for key in keys).lower()


def _is_media(element: dict[str, Any]) -> bool:
    return str(element.get("tag") or "").lower() in {"img", "video"}


def _media_source(element: dict[str, Any]) -> str:
    """The snapshot reports media as text="src=…", truncated to 60 chars."""
    text = str(element.get("text") or "")
    return text[4:] if text.startswith("src=") else ""


def _media_on_page(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in elements if _is_media(item) and _media_source(item)]


def _find_prompt_box(elements: list[dict[str, Any]], recipe: SiteRecipe) -> dict[str, Any] | None:
    for element in elements:
        if str(element.get("id") or "").lower() in recipe.prompt_ids:
            return element
    for element in elements:
        if str(element.get("testid") or "").lower() in recipe.prompt_testids:
            return element
    for element in elements:
        classes = str(element.get("cls") or "").lower()
        if any(hint in classes for hint in recipe.prompt_classes):
            return element
    # Last resort within a recognised site: the one obvious writing surface.
    candidates = [
        element for element in elements
        if str(element.get("tag") or "").lower() == "textarea"
        or str(element.get("role") or "").lower() == "textbox"
    ]
    return candidates[0] if len(candidates) == 1 else None


def _find_send_button(elements: list[dict[str, Any]], recipe: SiteRecipe) -> dict[str, Any] | None:
    for element in elements:
        if str(element.get("testid") or "").lower() in recipe.send_testids:
            return element
    for element in elements:
        if str(element.get("tag") or "").lower() not in {"button"} and str(element.get("role") or "").lower() != "button":
            continue
        haystack = _text_of(element, "label", "text")
        if any(word in haystack for word in recipe.send_labels):
            return element
    return None


def _find_file_input(elements: list[dict[str, Any]]) -> dict[str, Any] | None:
    for element in elements:
        if "O DINH KEM FILE" in str(element.get("text") or ""):
            return element
    return None


def _run_key(goal: str, url: str) -> str:
    seed = f"{_host(url)}|{prompt_from_goal(goal)[:400]}"
    return hashlib.sha1(seed.encode("utf-8", "replace")).hexdigest()[:20]


def _baseline(key: str, elements: list[dict[str, Any]], step: int) -> set[str]:
    """Media already on the page when this run began.

    Recorded on the first step and then left alone: taking it again later
    would quietly adopt the picture the run itself produced, and the run
    would never finish.
    """
    now = time.monotonic()
    stale = [item for item, value in _BASELINES.items() if now - value["at"] > _BASELINE_TTL_SECONDS]
    for item in stale:
        _BASELINES.pop(item, None)
    if len(_BASELINES) > _BASELINE_MAX:
        for item in sorted(_BASELINES, key=lambda name: _BASELINES[name]["at"])[: len(_BASELINES) - _BASELINE_MAX]:
            _BASELINES.pop(item, None)
    existing = _BASELINES.get(key)
    if existing is None or step <= 1:
        sources = {_media_source(item) for item in _media_on_page(elements)}
        _BASELINES[key] = {"at": now, "sources": sources}
        return sources
    return set(existing["sources"])


def forget_run(goal: str, url: str) -> None:
    _BASELINES.pop(_run_key(goal, url), None)


def next_action(
    *,
    goal: str,
    url: str,
    elements: list[dict[str, Any]],
    history: list[str] | None = None,
    step: int = 0,
) -> dict[str, Any] | None:
    """The next action for a known chat page, or None to ask the model.

    None is the honest answer for anything unrecognised: an unknown site, a
    page whose composer is not on screen, a run that has waited long enough
    that something is probably wrong. The caller falls back to the model.
    """
    recipe = recipe_for(url)
    if recipe is None:
        return None
    prompt = prompt_from_goal(goal)
    if not prompt:
        return None

    history = list(history or [])
    taken = _actions_taken(history)
    baseline = _baseline(_run_key(goal, url), elements, step)

    # Anything drawn since the run began is this run's own output.
    fresh = [
        item for item in _media_on_page(elements)
        if _media_source(item) not in baseline
        and int(item.get("w") or 0) >= MIN_RESULT_PIXELS
        and int(item.get("h") or 0) >= MIN_RESULT_PIXELS
    ]
    if fresh and "type" in taken:
        best = max(fresh, key=lambda item: int(item.get("w") or 0) * int(item.get("h") or 0))
        return {
            "action": "done",
            "index": int(best["i"]),
            "reason": f"Ảnh mới xuất hiện sau khi gửi prompt ({best.get('w')}x{best.get('h')}).",
            "decided_by": "recipe",
        }

    if "type" not in taken:
        if _wants_reference_image(goal) and "attach_image" not in taken:
            file_input = _find_file_input(elements)
            if file_input is not None:
                return {
                    "action": "attach_image",
                    "index": int(file_input["i"]),
                    "reason": "Đính kèm ảnh tham chiếu trước khi gửi prompt.",
                    "decided_by": "recipe",
                }
        box = _find_prompt_box(elements, recipe)
        if box is None:
            return None
        action: dict[str, Any] = {
            "action": "type",
            "index": int(box["i"]),
            "text": prompt,
            "reason": f"Gõ prompt vào ô nhập của {recipe.key}.",
            "decided_by": "recipe",
        }
        send = _find_send_button(elements, recipe)
        if send is not None and not send.get("disabled"):
            action["then"] = [{"action": "click", "index": int(send["i"])}, {"action": "wait"}]
        return action

    if "click" not in taken:
        send = _find_send_button(elements, recipe)
        if send is None:
            return None
        if send.get("disabled"):
            return {"action": "wait", "reason": "Nút gửi đang khoá, chờ trang sẵn sàng.", "decided_by": "recipe"}
        return {
            "action": "click",
            "index": int(send["i"]),
            "reason": "Bấm gửi prompt.",
            "decided_by": "recipe",
        }

    if taken.count("wait") >= MAX_WAITS:
        # Long enough that this is not simply a slow drawing. Whatever the
        # page is showing now - a refusal, a limit notice, a login wall -
        # needs reading, and reading is what the model is for.
        return None
    return {
        "action": "wait",
        "reason": "Đã gửi prompt, chờ ảnh được tạo.",
        "decided_by": "recipe",
    }
