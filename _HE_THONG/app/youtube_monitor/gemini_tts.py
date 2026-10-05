"""Gemini 3.8 TTS through the Gemini API, for a narrator that can be told how to read.

Edge reads a line the one way it knows. Gemini 3.8 Flash TTS and Flash-Lite
TTS take an instruction about the delivery - warm, unhurried, stressing the
key words - and keep it apart from what is said: the words go in as the
transcript, the way of saying them goes in `speech_metadata`, and the only
things allowed inline are momentary vocal events (<laugh>, <short pause>).
Nothing here adds a word to the transcript.

The contract, from the Gemini API documentation for the 3.8 TTS models
(generally available 22 September 2026):

    POST {API}/interactions                      header x-goog-api-key
    {"model": "gemini-3.8-flash-tts",
     "input": [{"type": "user_input", "content": [
         {"type": "text", "text": <transcript>,
          "annotations": [{"type": "speech_metadata", "style": ..., "speaker": ...}]}]}],
     "response_format": {"type": "audio", "mime_type": "audio/wav"},
     "generation_config": {"speech_config": [{"voice": "Kore", "language": "vi"}]}}
                     two speakers: {"speech_config": {"mode": "conversational",
                                    "speakers": [{"speaker": ..., "voice": ...}, ...]}}
    answer: steps[type=model_output].content[type=audio].data - base64 WAV with
            its RIFF header (24 kHz, mono, 16-bit) for a unary request
    voices: GET {API}/voices?type=prebuilt&language_code=vi-VN

Spoken to over plain HTTP like the app's other Gemini calls. The key travels
in a header - never in a URL, a log line, an error, the ledger or a file.
"""

from __future__ import annotations

import base64
import io
import json
import re
import time
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import httpx

from . import usage_limits

API = "https://generativelanguage.googleapis.com/v1beta"
VENDOR = "google"


@dataclass(frozen=True)
class GeminiTtsModel:
    key: str      # the app's provider key: what a job, the settings and the ledger name
    model: str    # Gemini's model code
    label: str


# Two models, two keys: which one read a video is never a guess afterwards.
MODELS: dict[str, GeminiTtsModel] = {
    item.key: item
    for item in (
        GeminiTtsModel("google_gemini_3_8_flash_tts", "gemini-3.8-flash-tts", "Gemini 3.8 Flash TTS"),
        GeminiTtsModel("google_gemini_3_8_flash_lite_tts", "gemini-3.8-flash-lite-tts", "Gemini 3.8 Flash-Lite TTS"),
    )
}

# The prebuilt voices the documentation lists. The catalog (GET /voices) is
# asked first; these are what is offered when it cannot be, and what a stored
# voice is checked against before a request is sent.
PREBUILT_VOICES: tuple[str, ...] = (
    "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede", "Callirrhoe", "Autonoe",
    "Enceladus", "Iapetus", "Umbriel", "Algieba", "Despina", "Erinome", "Algenib", "Rasalgethi",
    "Laomedeia", "Achernar", "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
    "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
)
DEFAULT_VOICE = "Kore"
# One unary request speaks for at most two speakers with prebuilt voices.
MAX_SPEAKERS = 2
SAMPLE_RATE = 24_000
MAX_STYLE_CHARS = 1000

# Technical retry, the same shape as the Edge path: three attempts in all.
# A rate limit is waited out for as long as Google says, up to a ceiling.
RETRY_WAITS: tuple[float, ...] = (2.0, 5.0)
MAX_RATE_LIMIT_WAIT = 30.0
TIMEOUT = httpx.Timeout(120.0, connect=20.0)
VOICE_CACHE_SECONDS = 3600.0
# A catalog that could not be read is not asked again for this long (refresh asks anyway).
VOICE_FAILURE_SECONDS = 300.0

# The app's language codes as BCP-47 with a region, for the voice catalog's filter.
_CATALOG_LANGUAGES = {
    "vi": "vi-VN", "en": "en-US", "th": "th-TH", "es": "es-ES", "fr": "fr-FR", "de": "de-DE",
    "ja": "ja-JP", "ko": "ko-KR", "id": "id-ID", "zh": "zh-CN",
}


class GeminiTtsError(RuntimeError):
    """A failure, and what kind: input, auth, quota, rate_limit, transient or response.

    Only "transient" and "rate_limit" are tried again; only "quota" is
    recorded as the account being out.
    """

    def __init__(self, message: str, *, kind: str, status_code: int | None = None,
                 retry_after: float | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass(frozen=True)
class Turn:
    """One stretch of transcript, who says it, and how - the how never joins the words."""

    text: str
    speaker: str = ""
    style: str = ""


# Seams for the tests: the HTTP client and the wait between attempts.
def _new_client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, follow_redirects=True)


_client_factory: Callable[[], httpx.Client] = _new_client
_sleep: Callable[[float], None] = time.sleep

# The last failure each model met, for the readiness shown in Bước 4; cleared by a success.
_last_failure: dict[str, dict[str, Any]] = {}
_voice_cache: dict[str, dict[str, Any]] = {}
_voice_failures: dict[str, dict[str, Any]] = {}


def model_for(provider: str) -> GeminiTtsModel:
    try:
        return MODELS[provider]
    except KeyError:
        raise GeminiTtsError(f"Không phải model Gemini TTS: {provider}", kind="input") from None


# ---------------------------------------------------------------------------
# The request
# ---------------------------------------------------------------------------

def _catalog_voices() -> dict[str, dict[str, Any]]:
    """The voices the catalog has listed so far, by lowercased id."""
    found: dict[str, dict[str, Any]] = {}
    for cached in _voice_cache.values():
        for item in cached.get("voices") or []:
            found.setdefault(str(item.get("id") or "").lower(), item)
    return found


def is_known_voice(voice: str) -> bool:
    wanted = str(voice or "").strip().lower()
    return bool(wanted) and (wanted in {name.lower() for name in PREBUILT_VOICES} or wanted in _catalog_voices())


def resolve_voice(voice: str, known: Sequence[str] = ()) -> tuple[str, str]:
    """(the voice to send, the stored name it replaced - empty when none was replaced).

    A voice picked for another engine ("vi-VN-HoaiMyNeural") means nothing to
    Gemini and would fail every scene of a job, so anything Gemini does not
    list is replaced by the default voice - and the replacement is recorded.
    "Does not list" means the catalog read in this process; the callers go
    through voice_for, which refuses rather than replaces when it was not read.
    """
    wanted = str(voice or "").strip()
    names = {name.lower(): name for name in (*PREBUILT_VOICES, *known) if name}
    for key, item in _catalog_voices().items():
        names.setdefault(key, str(item.get("id") or ""))
    if wanted and wanted.lower() in names:
        return names[wanted.lower()], ""
    return DEFAULT_VOICE, wanted


def voice_for(api_key: str, voice: str, language: str) -> tuple[str, str]:
    """resolve_voice, once the catalog has been asked about a voice it does not know yet.

    A voice picked from the catalog is known only once the catalog has been
    read in this process. When it cannot be read (an app just restarted, the
    catalog down), a stored voice cannot be told apart from a foreign one -
    so it is not replaced by Kore: the request is refused, transiently, and
    nothing is spoken in a voice nobody chose. A voice the catalog was read
    and does not list is replaced, as resolve_voice says.
    """
    wanted = str(voice or "").strip()
    if wanted and not is_known_voice(wanted):
        found = list_voices(api_key, language)
        if found.get("source") != "api" and not is_known_voice(wanted):
            reason = str(found.get("error") or "").strip()
            raise GeminiTtsError(
                f"Chưa đọc được danh mục giọng Gemini nên chưa xác nhận được giọng “{wanted}”; "
                "giọng đã chọn không bị thay bằng giọng khác. Thử lại sau." + (f" ({reason})" if reason else ""),
                kind="transient")
    return resolve_voice(wanted)


def voice_language(voice: str, language: str) -> str:
    """The language to name beside `voice` in speech_config.

    Google looks a voice up by its name and language together: a catalog
    voice ("vi-vn-advisor-6") is found only under the code the catalog lists
    it with ("vi-VN"), not under the app's "vi". A prebuilt voice keeps the
    language as given.
    """
    listed = _catalog_voices().get(str(voice or "").strip().lower())
    return str(listed.get("language_code") or "").strip() if listed and listed.get("language_code") else language


def _clean(text: Any, limit: int) -> str:
    return str(text or "").strip()[:limit]


def request_body(model: str, turns: Sequence[Turn], *, voices: Mapping[str, str] | str,
                 language: str = "") -> dict[str, Any]:
    """The Interactions request for these turns. The transcript is each turn's text, as given."""
    spoken = [turn for turn in turns if str(turn.text or "").strip()]
    if not spoken:
        raise GeminiTtsError("Không có lời để đọc", kind="input")
    speakers: list[str] = []
    for turn in spoken:
        name = _clean(turn.speaker, 80)
        if name and name not in speakers:
            speakers.append(name)
    if len(speakers) > MAX_SPEAKERS:
        raise GeminiTtsError(
            f"Gemini TTS đọc tối đa {MAX_SPEAKERS} người nói trong một lượt; đoạn này có {len(speakers)}: "
            + ", ".join(speakers), kind="input")

    def voice_of(name: str) -> str:
        return voices if isinstance(voices, str) else str(voices.get(name) or voices.get("") or DEFAULT_VOICE)

    conversational = len(speakers) == MAX_SPEAKERS
    if conversational and any(not _clean(turn.speaker, 80) for turn in spoken):
        raise GeminiTtsError("Khi có hai người nói, mỗi lượt lời cần ghi rõ ai nói", kind="input")
    content = []
    for turn in spoken:
        annotation: dict[str, Any] = {"type": "speech_metadata"}
        if conversational:
            annotation["speaker"] = _clean(turn.speaker, 80)
        style = _clean(turn.style, MAX_STYLE_CHARS)
        if style:
            annotation["style"] = style
        item: dict[str, Any] = {"type": "text", "text": str(turn.text).strip()}
        if len(annotation) > 1:
            item["annotations"] = [annotation]
        content.append(item)
    language = _clean(language, 20)

    def voice_entry(name: str) -> dict[str, Any]:
        voice = voice_of(name)
        spoken_in = _clean(voice_language(voice, language), 20)
        return {"voice": voice, **({"language": spoken_in} if spoken_in else {})}

    if conversational:
        speech_config: Any = {
            "mode": "conversational",
            "speakers": [{"speaker": name, **voice_entry(name)} for name in speakers],
        }
    else:
        speech_config = [voice_entry(speakers[0] if speakers else "")]
    return {
        "model": model,
        "input": [{"type": "user_input", "content": content}],
        "response_format": {"type": "audio", "mime_type": "audio/wav"},
        "generation_config": {"speech_config": speech_config},
    }


# ---------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------

def _is_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def as_wav(data: bytes, mime_type: str, *, sample_rate: int = SAMPLE_RATE, channels: int = 1) -> bytes:
    """WAV bytes ready to write. A complete WAV is kept as it came - its header is never added twice.

    Only headerless 16-bit PCM (audio/l16, which streaming returns) is given a
    header, here and nowhere else.
    """
    if _is_wav(data):
        return data
    mime = str(mime_type or "").lower()
    if mime.startswith("audio/l16") or mime.startswith("audio/pcm"):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setnchannels(max(1, int(channels or 1)))
            writer.setsampwidth(2)
            writer.setframerate(int(sample_rate or SAMPLE_RATE))
            writer.writeframes(data)
        return buffer.getvalue()
    raise GeminiTtsError(f"Gemini TTS trả về audio không đọc được ({mime or 'không rõ định dạng'})", kind="response")


def audio_from(payload: Any) -> tuple[bytes, dict[str, Any]]:
    """The WAV in an Interactions answer, and what came with it."""
    steps = payload.get("steps") if isinstance(payload, dict) else None
    parts = [
        part
        for step in (steps or []) if isinstance(step, dict) and step.get("type") == "model_output"
        for part in (step.get("content") or []) if isinstance(part, dict) and part.get("type") == "audio" and part.get("data")
    ]
    if not parts:
        raise GeminiTtsError("Gemini TTS không trả về audio", kind="response")
    last = parts[-1]
    try:
        raw = base64.b64decode(str(last["data"]), validate=True)
    except (ValueError, TypeError) as exc:
        raise GeminiTtsError("Gemini TTS trả audio hỏng", kind="response") from exc
    if not raw:
        raise GeminiTtsError("Gemini TTS trả audio rỗng", kind="response")
    mime = str(last.get("mime_type") or "audio/wav")
    try:
        rate = int(last.get("sample_rate") or SAMPLE_RATE)
        channels = int(last.get("channels") or 1)
    except (TypeError, ValueError) as exc:
        raise GeminiTtsError("Gemini TTS trả thông số audio không đọc được", kind="response") from exc
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return as_wav(raw, mime, sample_rate=rate, channels=channels), {
        "mime_type": "audio/wav", "sample_rate": rate, "channels": channels,
        "usage": {key: usage[key] for key in ("total_input_tokens", "total_output_tokens", "total_tokens") if key in usage},
    }


# ---------------------------------------------------------------------------
# Errors: what Google said, in which kind, with no key in it
# ---------------------------------------------------------------------------

def _scrub(text: str, api_key: str) -> str:
    text = str(text or "")
    return text.replace(api_key, "***") if api_key else text


def _seconds(value: Any) -> float | None:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s\s*", str(value or ""))
    return float(match.group(1)) if match else None


def classify(status_code: int, body: Any, api_key: str = "") -> GeminiTtsError:
    """One HTTP failure as a GeminiTtsError of the right kind."""
    error = body.get("error") if isinstance(body, dict) else None
    error = error if isinstance(error, dict) else {}
    message = _scrub(str(error.get("message") or "").strip()[:500], api_key)
    status = str(error.get("status") or "")
    details = [item for item in (error.get("details") or []) if isinstance(item, dict)]
    retry_after = next((_seconds(item.get("retryDelay")) for item in details if item.get("retryDelay")), None)
    quota_ids = " ".join(
        f"{violation.get('quotaId') or ''} {violation.get('quotaMetric') or ''}"
        for item in details for violation in (item.get("violations") or []) if isinstance(violation, dict)
    )
    said = f" (HTTP {status_code}{' ' + status if status else ''}): {message}" if message else f" (HTTP {status_code})"
    if status_code in (401, 403) or "API_KEY_INVALID" in json.dumps(error) or "api key not valid" in message.lower():
        return GeminiTtsError("Gemini API từ chối khóa GEMINI_API_KEY" + said, kind="auth", status_code=status_code)
    if status_code == 429:
        if re.search(r"per ?day|daily", quota_ids, re.IGNORECASE):
            # The account is out for the day: "hết hạn mức" is what usage_limits records.
            return GeminiTtsError("Gemini TTS hết hạn mức trong ngày" + said, kind="quota", status_code=429,
                                  retry_after=retry_after)
        return GeminiTtsError("Gemini TTS đang giới hạn số lượt gọi mỗi phút" + said, kind="rate_limit",
                              status_code=429, retry_after=retry_after)
    if status_code >= 500:
        return GeminiTtsError("Gemini TTS tạm thời không trả lời được" + said, kind="transient", status_code=status_code)
    return GeminiTtsError("Gemini TTS từ chối yêu cầu" + said, kind="input", status_code=status_code)


def _post(body: dict[str, Any], api_key: str) -> dict[str, Any]:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json; charset=utf-8"}
    try:
        with _client_factory() as client:
            response = client.post(f"{API}/interactions", headers=headers, content=payload)
    except httpx.TimeoutException as exc:
        raise GeminiTtsError("Gemini TTS quá thời gian chờ", kind="transient") from exc
    except httpx.HTTPError as exc:
        raise GeminiTtsError(f"Không kết nối được Gemini TTS: {_scrub(type(exc).__name__, api_key)}", kind="transient") from exc
    if response.status_code >= 400:
        try:
            parsed = response.json()
        except ValueError:
            parsed = {}
        raise classify(response.status_code, parsed, api_key)
    try:
        return response.json()
    except ValueError as exc:
        raise GeminiTtsError("Gemini TTS trả về nội dung không đọc được", kind="response") from exc


# ---------------------------------------------------------------------------
# Speaking
# ---------------------------------------------------------------------------

def synthesize_turns(
    turns: Sequence[Turn],
    output_path: Path,
    *,
    provider: str,
    api_key: str,
    voices: Mapping[str, str] | str = DEFAULT_VOICE,
    language: str = "",
) -> dict[str, Any]:
    """Speak these turns into `output_path` as WAV; what was used comes back for the record.

    Raises GeminiTtsError. Transient failures and rate limits are tried again
    (technical retry); a daily quota is recorded as the account being out; an
    auth or input error is final at once.
    """
    chosen = model_for(provider)
    if not str(api_key or "").strip():
        raise GeminiTtsError("Chưa có GEMINI_API_KEY. Điền khóa Gemini API trong Kết nối AI.", kind="auth")
    # A stored voice is judged only against a catalog that could be read (voice_for).
    if isinstance(voices, str):
        voice, replaced = voice_for(api_key, voices, language)
        sent_voices: Mapping[str, str] | str = voice
        replaced_voices = {"": replaced} if replaced else {}
    else:
        resolved = {name: voice_for(api_key, value, language) for name, value in voices.items()}
        sent_voices = {name: pair[0] for name, pair in resolved.items()}
        replaced_voices = {name: pair[1] for name, pair in resolved.items() if pair[1]}
    body = request_body(chosen.model, turns, voices=sent_voices, language=language)
    attempts = 0
    while True:
        attempts += 1
        try:
            payload = _post(body, api_key)
            audio, info = audio_from(payload)
            break
        except GeminiTtsError as exc:
            retryable = exc.kind in {"transient", "rate_limit"} and attempts <= len(RETRY_WAITS)
            if not retryable:
                # A request refused for what it asked (a voice, a text) says nothing
                # about whether the model can be reached; it does not mark the model.
                if exc.kind != "input":
                    _last_failure[provider] = {"kind": exc.kind, "message": str(exc)[:300],
                                               "at": datetime.now(timezone.utc).isoformat()}
                if exc.kind == "quota":
                    usage_limits.note_failure(provider, str(exc))
                raise
            wait = RETRY_WAITS[attempts - 1]
            if exc.kind == "rate_limit" and exc.retry_after:
                wait = min(MAX_RATE_LIMIT_WAIT, max(wait, exc.retry_after))
            _sleep(wait)
    _last_failure.pop(provider, None)
    usage_limits.note_success(provider)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio)
    speech = body["generation_config"]["speech_config"]
    return {
        "path": str(output_path),
        "vendor": VENDOR,
        "provider": chosen.key,
        "model": chosen.model,
        "voice": sent_voices if isinstance(sent_voices, str) else dict(sent_voices),
        "voice_fallback_from": replaced_voices.get("", "") if isinstance(sent_voices, str) else replaced_voices,
        "language": language,
        "voice_language": ({item["speaker"]: item.get("language", "") for item in speech["speakers"]}
                           if isinstance(speech, dict) else speech[0].get("language", "")),
        "speakers": [item["speaker"] for item in speech["speakers"]] if isinstance(speech, dict) else [],
        "attempts": attempts,
        "bytes": len(audio),
        **info,
    }


def synthesize(
    text: str,
    output_path: Path,
    *,
    provider: str,
    api_key: str,
    voice: str = DEFAULT_VOICE,
    language: str = "",
    style: str = "",
    speaker: str = "",
) -> dict[str, Any]:
    """One stretch of narration - one scene - in one voice, read in `style`.

    The same contract as the app's other TTS adapters: the words in, a file
    out at `output_path`, an error of the adapter's own type on failure. The
    speaker is kept for the record; one voice reads it.
    """
    result = synthesize_turns([Turn(text=text, style=style)], output_path, provider=provider, api_key=api_key,
                              voices=voice, language=language)
    return {**result, "speaker": str(speaker or ""), "style": _clean(style, MAX_STYLE_CHARS)}


# ---------------------------------------------------------------------------
# The voices, and whether a model is ready
# ---------------------------------------------------------------------------

def catalog_language(code: str) -> str:
    text = str(code or "").strip()
    return text if "-" in text else _CATALOG_LANGUAGES.get(text.lower(), text)


def _builtin_voices() -> list[dict[str, Any]]:
    return [{"id": name, "name": name, "language_code": "", "gender": "", "type": "prebuilt"} for name in PREBUILT_VOICES]


def list_voices(api_key: str, language: str = "vi", *, refresh: bool = False) -> dict[str, Any]:
    """Google's prebuilt voices for a language, from GET /voices, cached for an hour.

    Without a key, or when the catalog cannot be read, the documented
    prebuilt voices are returned instead and the reason is said - unless the
    catalog was read before: that list, older than an hour, is still the
    better answer (the voice a project already chose is in it), so it is
    returned with the reason and marked stale.
    """
    wanted = catalog_language(language)
    cached = _voice_cache.get(wanted)
    if cached and not refresh and time.monotonic() - float(cached["fetched_at"]) < VOICE_CACHE_SECONDS:
        return {"voices": cached["voices"], "source": "api", "language_code": wanted, "error": ""}
    if not str(api_key or "").strip():
        return {"voices": _builtin_voices(), "source": "builtin", "language_code": wanted,
                "error": "Chưa có GEMINI_API_KEY nên chưa hỏi được danh mục giọng."}

    def unavailable(reason: str) -> dict[str, Any]:
        if cached:
            return {"voices": cached["voices"], "source": "api", "language_code": wanted, "error": reason, "stale": True}
        return {"voices": _builtin_voices(), "source": "builtin", "language_code": wanted, "error": reason}

    failed = _voice_failures.get(wanted)
    if failed and not refresh and time.monotonic() - float(failed["at"]) < VOICE_FAILURE_SECONDS:
        return unavailable(failed["error"])

    def fallback(reason: str) -> dict[str, Any]:
        _voice_failures[wanted] = {"at": time.monotonic(), "error": reason}
        return unavailable(reason)

    def ask(language_code: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        token = ""
        with _client_factory() as client:
            for _ in range(5):
                params: dict[str, Any] = {"type": "prebuilt", "page_size": 1000}
                if language_code:
                    params["language_code"] = language_code
                if token:
                    params["page_token"] = token
                response = client.get(f"{API}/voices", headers={"x-goog-api-key": api_key}, params=params)
                if response.status_code >= 400:
                    try:
                        parsed = response.json()
                    except ValueError:
                        parsed = {}
                    raise classify(response.status_code, parsed, api_key)
                body = response.json()
                if not isinstance(body, dict):
                    raise GeminiTtsError("Danh mục giọng Gemini trả về nội dung không đọc được", kind="response")
                found.extend(item for item in (body.get("voices") or []) if isinstance(item, dict) and item.get("id"))
                token = str(body.get("next_page_token") or "")
                if not token:
                    break
        return found

    try:
        voices = ask(wanted) or ask("")
    except GeminiTtsError as exc:
        return fallback(str(exc)[:300])
    except (httpx.HTTPError, ValueError) as exc:
        return fallback(f"Không đọc được danh mục giọng Gemini: {_scrub(type(exc).__name__, api_key)}")
    if not voices:
        return fallback("Danh mục giọng Gemini trả về rỗng.")
    _voice_failures.pop(wanted, None)
    shaped = [
        {"id": str(item["id"]), "name": str(item.get("display_name") or item["id"]),
         "language_code": str(item.get("language_code") or ""), "gender": str(item.get("gender") or ""),
         "description": str(item.get("description") or "")[:200], "persona": str(item.get("persona") or "")[:120],
         "type": str(item.get("type") or "prebuilt")}
        for item in voices
    ]
    _voice_cache[wanted] = {"fetched_at": time.monotonic(), "voices": shaped}
    return {"voices": shaped, "source": "api", "language_code": wanted, "error": ""}


def status(provider: str, *, api_key: str, usage_limit: dict[str, Any] | None) -> dict[str, Any]:
    """Whether a Gemini TTS model can be chosen now: ready, not_configured, quota or error."""
    chosen = model_for(provider)
    base = {"key": chosen.key, "vendor": VENDOR, "model": chosen.model, "label": chosen.label}
    if not str(api_key or "").strip():
        return {**base, "status": "not_configured", "status_label": "Chưa cấu hình",
                "detail": "Chưa có GEMINI_API_KEY trong Kết nối AI."}
    quota = usage_limits.limit_state(usage_limit)
    if quota["blocking"]:
        return {**base, "status": "quota", "status_label": "Hết quota",
                "detail": str((usage_limit or {}).get("message") or ""), "retry_at": quota["retry_at"]}
    failure = _last_failure.get(provider)
    if failure:
        return {**base, "status": "error", "status_label": "Lỗi kết nối", "detail": failure["message"]}
    return {**base, "status": "ready", "status_label": "Sẵn sàng", "detail": ""}
