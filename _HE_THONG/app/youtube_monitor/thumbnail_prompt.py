"""What a thumbnail has to be, written as a prompt.

A frame lifted out of the finished video is not a thumbnail. It is whatever
the camera happened to be doing at that second: a face mid-blink, a wide shot
with no subject, the moment a hand passes the lens. It costs nothing, which is
why it is worth keeping as an option, but it is not what makes anyone click.

A thumbnail is composed - one subject, large, lit, against a background that
does not compete, with room where the title will sit. That is a brief, and a
brief is what an image model needs. This turns a project's own script into
one, and deliberately forbids the things that make an AI thumbnail look
generated: text it cannot spell, logos it invents, borders and collages.
"""

from __future__ import annotations

import re
from typing import Any

# Left as an instruction rather than composited afterwards: platforms overlay
# their own duration badge and title, and a model asked for text produces
# misspelt text that then cannot be removed.
NEGATIVE = (
    "No text, no words, no letters, no captions, no watermark, no logo, "
    "no channel name, no borders, no collage, no split screen, no frame."
)

COMPOSITION = (
    "Wide 16:9 thumbnail composition. One clear subject, large in frame, "
    "sharply lit against a simple uncluttered background. Strong colour "
    "contrast between subject and background. Leave the upper-left third "
    "relatively empty so a title can be placed there later. "
    "Photographic, high detail, dramatic natural light, shallow depth of field."
)

VERTICAL_COMPOSITION = (
    "Vertical 9:16 thumbnail composition for a Short. One clear subject, "
    "large and centred, sharply lit against a simple uncluttered background. "
    "Strong colour contrast. Leave the top fifth relatively empty so a title "
    "can be placed there later. Photographic, high detail, dramatic light."
)


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _subject(script: dict[str, Any], project: dict[str, Any]) -> str:
    """The one thing the picture should be of.

    The hook is where a script says what the video is about in a sentence,
    which is closer to a thumbnail brief than the title is - a title is
    written to be read, a hook to be pictured.
    """
    for field in ("hook", "intro", "main_content"):
        text = _clean((script or {}).get(field), 400)
        if text:
            return text
    return _clean((script or {}).get("script_title") or (project or {}).get("title"), 300)


def build(
    script: dict[str, Any] | None,
    project: dict[str, Any] | None = None,
    *,
    vertical: bool = False,
    visual_style: str = "",
    direction: str = "",
) -> str:
    """A prompt for one thumbnail, built from what this project is about."""
    subject = _subject(script or {}, project or {})
    if not subject:
        raise ValueError("Chưa có kịch bản hoặc tiêu đề để mô tả thumbnail")
    parts = [
        "Create a YouTube thumbnail image.",
        f"Subject: {subject}",
    ]
    if visual_style.strip():
        parts.append(f"Visual style of the source material: {_clean(visual_style, 400)}")
    if direction.strip():
        parts.append(f"Extra direction from the user: {_clean(direction, 600)}")
    parts.append(VERTICAL_COMPOSITION if vertical else COMPOSITION)
    parts.append(NEGATIVE)
    return "\n".join(parts)


def variant_prompts(base: str, count: int = 3) -> list[str]:
    """Several briefs for the same video, different enough to choose between.

    Asking one prompt for three images gives three near-identical pictures,
    which is not a choice. Each angle changes what the picture is of rather
    than only how it is lit.
    """
    angles = [
        "Frame it as a close, intimate shot of the subject.",
        "Frame it as a wide establishing shot showing the setting around the subject.",
        "Frame it at the single most dramatic moment implied by the subject.",
        "Frame it looking down at the subject from above.",
        "Frame it low, looking up at the subject against the sky.",
        "Frame it as a before-and-after contrast within one picture.",
    ]
    return [f"{base}\n{angles[index % len(angles)]}" for index in range(max(1, count))]
