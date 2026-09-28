"""Cached local word timestamps for scene direction; no application workers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def audio_signature(path: Path) -> str:
    stat = path.stat()
    return hashlib.sha256(f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()


def scene_speech_timing(segment: dict[str, Any]) -> dict[str, Any]:
    """Measure the voice used by the renderer, never the reference's old narration.

    A missing/unavailable recognizer leaves an explicit estimated timing status.
    The render remains available. Cached results are invalidated on audio changes.
    """
    path = Path(str(segment.get("audio_path") or ""))
    duration = max(.15, float(segment.get("duration_seconds") or 1))
    if not path.is_file():
        return {"duration_seconds": duration, "words": [], "timing_basis": "estimated",
                "audio_signature": "", "warning": "Chưa có voice: thời điểm đang ước lượng"}
    from .ffmpeg_renderer import media_duration_seconds
    duration = media_duration_seconds(path) or duration
    signature = audio_signature(path)
    cache = path.with_suffix(path.suffix + ".words.json")
    try:
        stored = json.loads(cache.read_text(encoding="utf-8"))
        if stored.get("audio_signature") == signature and stored.get("words"):
            return stored
    except (OSError, ValueError):
        pass
    try:
        from .transcriber import _get_model
        model = _get_model()
        iterator, _info = model.transcribe(str(path), word_timestamps=True, vad_filter=True)
        words = [{"word": word.word.strip(), "start": round(float(word.start), 3),
                  "end": round(float(word.end), 3)}
                 for utterance in iterator for word in (utterance.words or [])]
        result = {"duration_seconds": duration, "words": words, "audio_signature": signature,
                  "timing_basis": "word_timestamps" if words else "estimated",
                  "warning": "" if words else "Không đo được từ trong voice"}
        try:
            cache.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # Read-only imported media can still be used.
        return result
    except Exception as exc:
        return {"duration_seconds": duration, "words": [], "audio_signature": signature,
                "timing_basis": "estimated", "warning": f"Chưa căn được lời thoại: {str(exc)[:240]}"}
