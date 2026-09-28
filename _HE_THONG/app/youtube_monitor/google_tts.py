"""Google Cloud Text-to-Speech, for the Vietnamese voices Edge does not have.

Edge ships exactly two Vietnamese voices, HoaiMy and NamMinh, and a channel
that publishes in Vietnamese hears both of them on every video it makes. Google
has Standard, WaveNet, Neural2 and Chirp3-HD voices for vi-VN, and its free
monthly allowance covers a normal publishing schedule, so this is the cheapest
way to stop every video sounding like the same narrator.

Spoken to over plain HTTP with an API key: no SDK, no service-account file, and
nothing to install. The key is read from settings, never from the text being
spoken, and never written into a log line.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"

# Every vi-VN voice Google publishes, best first. Chirp3-HD is the current
# generation, Neural2 the previous one, Wavenet older still, Standard the
# cheapest. Nothing here is guessed at call time: an unknown name is sent
# through as given so a newly released voice works without a code change.
VIETNAMESE_VOICES: tuple[str, ...] = (
    "vi-VN-Chirp3-HD-Aoede",
    "vi-VN-Chirp3-HD-Puck",
    "vi-VN-Neural2-A",
    "vi-VN-Neural2-D",
    "vi-VN-Wavenet-A",
    "vi-VN-Wavenet-B",
    "vi-VN-Wavenet-C",
    "vi-VN-Wavenet-D",
    "vi-VN-Standard-A",
    "vi-VN-Standard-B",
    "vi-VN-Standard-C",
    "vi-VN-Standard-D",
)

DEFAULT_VOICE = "vi-VN-Neural2-A"
TIMEOUT_SECONDS = 60


class GoogleTtsError(RuntimeError):
    pass


def language_of(voice: str) -> str:
    """The language tag a voice name carries, e.g. "vi-VN-Neural2-A" -> "vi-VN"."""
    parts = str(voice or "").split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else "vi-VN"


# Edge's Vietnamese voices are named "vi-VN-HoaiMyNeural"; Google's carry the
# model family as its own part: Neural2, Chirp3-HD, Wavenet, Standard. A voice
# picked for one engine is meaningless to the other, and sending Edge's name
# here would fail every scene of a job, so the configured Google voice is used
# unless the stored one is recognisably Google's.
_GOOGLE_FAMILIES = ("-Neural2-", "-Chirp3-HD-", "-Wavenet-", "-Standard-", "-Studio-", "-Polyglot-")


def is_google_voice(name: str) -> bool:
    return any(family in str(name or "") for family in _GOOGLE_FAMILIES)


def request_body(text: str, voice: str, *, rate: float = 1.0, pitch: float = 0.0) -> dict:
    return {
        "input": {"text": text},
        "voice": {"languageCode": language_of(voice), "name": voice},
        "audioConfig": {
            "audioEncoding": "MP3",
            # Clamped to the range the API accepts, so a rate carried over from
            # another engine's scale cannot turn into a 400 halfway through a
            # job that has already spoken half its scenes.
            "speakingRate": max(0.25, min(4.0, float(rate or 1.0))),
            "pitch": max(-20.0, min(20.0, float(pitch or 0.0))),
        },
    }


def _post(body: dict, api_key: str) -> dict:
    url = f"{ENDPOINT}?{urllib.parse.urlencode({'key': api_key})}"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except (ValueError, OSError):
            detail = ""
        # The URL carries the key, so it is never repeated back in an error.
        raise GoogleTtsError(
            f"Google TTS trả lỗi {exc.code}: {detail or exc.reason}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GoogleTtsError(f"Không gọi được Google TTS: {exc}") from exc
    except ValueError as exc:
        raise GoogleTtsError("Google TTS trả về nội dung không đọc được") from exc


def synthesize(
    text: str,
    output_path: Path,
    *,
    api_key: str,
    voice: str = DEFAULT_VOICE,
    rate: float = 1.0,
    pitch: float = 0.0,
) -> Path:
    """Speak `text` into `output_path` as MP3, or raise GoogleTtsError."""
    spoken = str(text or "").strip()
    if not spoken:
        raise GoogleTtsError("Không có lời để đọc")
    if not str(api_key or "").strip():
        raise GoogleTtsError(
            "Chưa có GOOGLE_TTS_API_KEY. Tạo API key trong Google Cloud "
            "(bật Cloud Text-to-Speech API) rồi điền vào phần Tích hợp."
        )
    payload = _post(request_body(spoken, voice, rate=rate, pitch=pitch), api_key)
    encoded = payload.get("audioContent")
    if not encoded:
        raise GoogleTtsError("Google TTS không trả về audio")
    try:
        audio = base64.b64decode(encoded)
    except (ValueError, TypeError) as exc:
        raise GoogleTtsError("Google TTS trả audio hỏng") from exc
    if not audio:
        raise GoogleTtsError("Google TTS trả audio rỗng")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio)
    return output_path
