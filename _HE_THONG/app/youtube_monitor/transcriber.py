from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .database import Database
from .settings import GPU_ONLY, WHISPER_COMPUTE_TYPE, WHISPER_DEVICE, WHISPER_MODEL_SIZE


class TranscriptionError(RuntimeError):
    pass


def _extract_audio(video_url: str, dest_dir: Path) -> Path:
    try:
        import yt_dlp
    except ImportError as exc:
        raise TranscriptionError(
            "Thiếu thư viện yt-dlp. Cài đặt bằng: pip install yt-dlp"
        ) from exc

    options = {
        "format": "bestaudio/best",
        "outtmpl": str(dest_dir / "audio.%(ext)s"),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "wav", "preferredquality": "192"}
        ],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "noprogress": True,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([video_url])
    except Exception as exc:
        raise TranscriptionError(f"Không trích xuất được audio: {exc}") from exc

    audio_files = sorted(dest_dir.glob("audio.*"))
    if not audio_files:
        raise TranscriptionError("Không tìm thấy file audio sau khi trích xuất")
    return audio_files[0]


_model_cache: dict[str, Any] = {}


def resolve_whisper_runtime() -> tuple[str, str]:
    configured_device = WHISPER_DEVICE
    configured_compute = WHISPER_COMPUTE_TYPE
    cuda_count = 0
    try:
        import ctranslate2

        cuda_count = int(ctranslate2.get_cuda_device_count())
    except Exception:
        cuda_count = 0

    if configured_device in {"cuda", "gpu"}:
        if cuda_count < 1:
            raise TranscriptionError(
                "WHISPER_DEVICE=cuda nhưng CTranslate2 không nhận được CUDA. "
                "Đặt WHISPER_DEVICE=auto để tự fallback CPU."
            )
        device = "cuda"
    elif configured_device in {"cpu"}:
        if GPU_ONLY:
            raise TranscriptionError(
                "GPU-only mode is enabled: Faster-Whisper is not allowed to run on CPU. "
                "Set WHISPER_DEVICE=cuda or disable YOUTUBE_GPU_ONLY explicitly."
            )
        device = "cpu"
    else:
        if cuda_count < 1 and GPU_ONLY:
            raise TranscriptionError(
                "GPU-only mode is enabled but CTranslate2 cannot detect CUDA. "
                "The app will not silently fall back to CPU."
            )
        device = "cuda" if cuda_count > 0 else "cpu"

    if configured_compute in {"", "auto", "default"}:
        compute_type = "float16" if device == "cuda" else "int8"
    else:
        compute_type = configured_compute
    return device, compute_type


def _get_model(model_size: str | None = None):
    device, compute_type = resolve_whisper_runtime()
    selected_model = str(model_size or WHISPER_MODEL_SIZE).strip() or WHISPER_MODEL_SIZE
    key = f"{selected_model}:{device}:{compute_type}"
    if key not in _model_cache:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriptionError(
                "Thiếu thư viện faster-whisper. Cài đặt bằng: pip install faster-whisper"
            ) from exc
        _model_cache[key] = WhisperModel(
            selected_model,
            device=device,
            compute_type=compute_type,
        )
    return _model_cache[key]


def _format_timestamp(seconds: float) -> str:
    millis = max(0, int(round(seconds * 1000)))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def build_srt(segments: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, segment in enumerate(segments, start=1):
        lines.append(str(index))
        lines.append(f"{_format_timestamp(segment['start'])} --> {_format_timestamp(segment['end'])}")
        lines.append(segment["text"].strip())
        lines.append("")
    return "\n".join(lines).strip()


def transcribe_video(
    video_url: str,
    video_id: str,
    language: str | None = None,
    model_size: str | None = None,
) -> dict[str, Any]:
    """Extract temporary audio, run Faster-Whisper locally, then discard the audio.

    Only the resulting text (txt/srt/segments) is returned; no media file is kept
    on disk once this function returns.
    """
    model = _get_model(model_size)
    with tempfile.TemporaryDirectory(prefix=f"whisper_{video_id}_") as tmp:
        audio_path = _extract_audio(video_url, Path(tmp))
        try:
            segments_iter, info = model.transcribe(
                str(audio_path),
                language=language or None,
                vad_filter=True,
            )
            segments = [
                {"start": float(seg.start), "end": float(seg.end), "text": seg.text.strip()}
                for seg in segments_iter
            ]
        except Exception as exc:
            raise TranscriptionError(f"Whisper transcription lỗi: {exc}") from exc

    text = " ".join(seg["text"] for seg in segments).strip()
    return {
        "language": getattr(info, "language", "") or language or "",
        "text": text,
        "srt": build_srt(segments),
        "segments": segments,
        "model": str(model_size or WHISPER_MODEL_SIZE),
    }


def transcribe_local_file(
    file_path: str | Path,
    asset_id: str,
    language: str | None = None,
    model_size: str | None = None,
) -> dict[str, Any]:
    """Run Faster-Whisper directly on a user-imported local audio/video file."""
    path = Path(file_path)
    if not path.is_file():
        raise TranscriptionError(f"Không tìm thấy file local của asset {asset_id}: {path}")
    model = _get_model(model_size)
    try:
        segments_iter, info = model.transcribe(
            str(path),
            language=language or None,
            vad_filter=True,
        )
        segments = [
            {"start": float(seg.start), "end": float(seg.end), "text": seg.text.strip()}
            for seg in segments_iter
        ]
    except Exception as exc:
        raise TranscriptionError(f"Whisper transcription asset local lỗi: {exc}") from exc

    text = " ".join(seg["text"] for seg in segments).strip()
    return {
        "language": getattr(info, "language", "") or language or "",
        "text": text,
        "srt": build_srt(segments),
        "segments": segments,
        "model": str(model_size or WHISPER_MODEL_SIZE),
    }


def save_transcript_result(database: Database, video_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Persist a transcribe_video() result as json/srt/txt rows.

    Saved in that order so the txt row ends up as the most recent one — the
    row a default (unfiltered) transcript lookup returns.
    """
    database.save_transcript(
        video_id,
        json.dumps(result["segments"], ensure_ascii=False),
        source_type="whisper_auto",
        language=result["language"],
        transcript_format="json",
    )
    if result["srt"]:
        database.save_transcript(
            video_id,
            result["srt"],
            source_type="whisper_auto",
            language=result["language"],
            transcript_format="srt",
        )
    return database.save_transcript(
        video_id,
        result["text"],
        source_type="whisper_auto",
        language=result["language"],
        transcript_format="txt",
    )


def save_asset_transcript_result(database: Database, asset_id: int, result: dict[str, Any]) -> dict[str, Any] | None:
    """Persist the text result of local-asset Whisper analysis."""
    return database.save_asset_transcript(
        asset_id,
        result["text"],
        source_type="whisper_local",
        language=result["language"],
        transcript_format="txt",
    )
