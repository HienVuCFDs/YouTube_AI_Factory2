from __future__ import annotations

import re
from pathlib import Path


def _timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"


def subtitle_chunks(text: str, maximum_words: int = 11) -> list[str]:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?…])\s+", " ".join(str(text or "").split())) if part.strip()]
    chunks: list[str] = []
    for sentence in sentences:
        words = sentence.split()
        while len(words) > maximum_words:
            chunks.append(" ".join(words[:maximum_words]))
            words = words[maximum_words:]
        if words:
            chunks.append(" ".join(words))
    return chunks or ([str(text).strip()] if str(text).strip() else [])


def write_segment_srt(path: Path, text: str, duration_seconds: float) -> Path:
    chunks = subtitle_chunks(text)
    duration = max(0.1, float(duration_seconds))
    weighted = [max(1, len(chunk.split())) for chunk in chunks]
    total_weight = sum(weighted) or 1
    cursor = 0.0
    lines: list[str] = []
    for index, (chunk, weight) in enumerate(zip(chunks, weighted), start=1):
        next_cursor = duration if index == len(chunks) else cursor + duration * weight / total_weight
        lines.extend([str(index), f"{_timestamp(cursor)} --> {_timestamp(next_cursor)}", chunk, ""])
        cursor = next_cursor
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
