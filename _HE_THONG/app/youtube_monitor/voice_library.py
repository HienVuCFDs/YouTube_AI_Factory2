"""The voice a project has already made, findable again after a rebuild.

Audio is attached to a timeline row, not to the words it was spoken from, so
anything that replaces the rows loses it - cutting scenes by dialogue,
rebuilding the storyboard, rewriting the script. The files are still on disk,
minutes of generated speech, and the app's answer was to generate them again.

They do not have to be. The voiceover writes the text it spoke beside each
file, so a scene whose narration matches one of those can be given its voice
back. Matching is on the words, never on the scene number: a rebuild renumbers
everything, and scene 3 after a rebuild is rarely scene 3 before it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

AUDIO_SUFFIXES = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")


def normalise(text: str) -> str:
    """Compare on words alone, so punctuation and spacing cannot miss a match."""
    return re.sub(r"\W+", "", str(text or "").lower(), flags=re.UNICODE)


def index_voices(work_dir: Path, audio_dir: Path) -> dict[str, dict[str, Any]]:
    """Every generated voice file this project still has, keyed by its words.

    The sidecar the voiceover already writes is what makes this possible: it
    records what was spoken, which the filename does not.
    """
    work_dir, audio_dir = Path(work_dir), Path(audio_dir)
    library: dict[str, dict[str, Any]] = {}
    if not work_dir.is_dir() or not audio_dir.is_dir():
        return library
    # segment-NNN: voices made before Bước 5.2; voice-s<row>-<content>: since.
    for sidecar in sorted([*work_dir.glob("segment-*.txt"), *work_dir.glob("voice-*.txt")]):
        spoken = sidecar.read_text(encoding="utf-8", errors="replace").strip()
        key = normalise(spoken)
        if not key:
            continue
        for suffix in AUDIO_SUFFIXES:
            candidate = audio_dir / f"{sidecar.stem}{suffix}"
            if candidate.is_file() and candidate.stat().st_size > 0:
                # A later regeneration of the same words wins: it is the one
                # the user last chose to make.
                previous = library.get(key)
                if not previous or candidate.stat().st_mtime > previous["mtime"]:
                    library[key] = {
                        "audio_path": str(candidate),
                        "text": spoken,
                        "mtime": candidate.stat().st_mtime,
                    }
                break
    return library


def match_timeline(
    timeline: list[dict[str, Any]], library: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a timeline into scenes whose voice can be restored, and the rest.

    A scene that already has a playable file is left alone: re-attaching would
    be a no-op at best and, if the user had replaced one by hand, a loss.
    """
    matched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for item in timeline:
        existing = str(item.get("audio_path") or "").strip()
        if existing and Path(existing).is_file():
            continue
        found = library.get(normalise(item.get("voice_text")))
        if found:
            matched.append({
                "segment_id": int(item["id"]),
                "segment_index": int(item.get("segment_index") or 0),
                "audio_path": found["audio_path"],
            })
        else:
            missing.append({
                "segment_index": int(item.get("segment_index") or 0),
                "voice_text": str(item.get("voice_text") or "")[:160],
            })
    return matched, missing
