from __future__ import annotations

import re


_TIMESTAMP_LINE = re.compile(
    r"^(?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{3}\s+-->\s+(?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{3}"
)
_SRT_INDEX = re.compile(r"^\d+$")
_HTML_TAG = re.compile(r"<[^>]+>")


def normalize_transcript(text: str, transcript_format: str = "txt") -> str:
    """Convert TXT/SRT/VTT input into clean text for later AI processing."""
    value = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if transcript_format not in {"srt", "vtt"}:
        return value

    lines: list[str] = []
    for line in value.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.upper() == "WEBVTT":
            continue
        if _TIMESTAMP_LINE.match(stripped) or _SRT_INDEX.fullmatch(stripped):
            continue
        if stripped.startswith(("NOTE", "STYLE", "REGION")):
            continue
        cleaned = _HTML_TAG.sub("", stripped)
        if cleaned:
            lines.append(cleaned)
    return " ".join(lines).strip()
