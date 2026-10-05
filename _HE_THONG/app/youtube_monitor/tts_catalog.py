"""Every voice engine the app can speak with, and what to call it afterwards.

A job names its engine by a provider key; this says which vendor and which
model that key is, and what kind of file it writes - so a finished video can
always be traced to "google / gemini-3.8-flash-tts", not just "a TTS".
"""

from __future__ import annotations

from dataclasses import dataclass

from . import gemini_tts

# What the ledger files a spoken scene and an audition under.
VOICE_CAPABILITY = "voice.tts"
PREVIEW_CAPABILITY = "voice.preview"


@dataclass(frozen=True)
class VoiceEngine:
    key: str
    vendor: str
    model: str
    label: str
    suffix: str        # the file the engine writes: "mp3" or "wav"
    paid: bool = False


ENGINES: dict[str, VoiceEngine] = {
    engine.key: engine
    for engine in (
        VoiceEngine("edge_tts", "microsoft", "edge-tts", "Edge TTS", "mp3"),
        VoiceEngine("google_tts", "google", "cloud-text-to-speech", "Google Cloud Text-to-Speech", "mp3", paid=True),
        VoiceEngine("piper", "piper", "piper", "Piper", "wav"),
        VoiceEngine("voxcpm", "openbmb", "VoxCPM2", "VoxCPM2", "wav"),
        VoiceEngine("pyvideotrans", "pyvideotrans", "pyvideotrans", "pyVideoTrans", "wav"),
        VoiceEngine("py_video_trans", "pyvideotrans", "pyvideotrans", "pyVideoTrans", "wav"),
        *(VoiceEngine(item.key, gemini_tts.VENDOR, item.model, item.label, "wav", paid=True)
          for item in gemini_tts.MODELS.values()),
    )
}

# The engines Bước 4 offers, in the order it lists them.
STUDIO_ENGINES: tuple[str, ...] = ("edge_tts", *gemini_tts.MODELS, "pyvideotrans", "voxcpm")


def engine(key: str) -> VoiceEngine | None:
    return ENGINES.get(str(key or "").strip().lower())
