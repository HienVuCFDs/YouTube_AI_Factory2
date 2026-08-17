from __future__ import annotations

import json
import math
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from queue import Queue
from threading import Event, Lock, Thread
from typing import Any

from .database import Database
from .ffmpeg_renderer import generate_local_visual_draft, media_duration_seconds, render_timeline_with_ffmpeg
from .premiere_export import build_premiere_export_package
from .project_layout import ensure_project_layout
from .quality_check import build_quality_report, quality_report_markdown
from .openmontage_adapter import OpenMontageAdapter
from .settings import GPU_DEVICE_INDEX, GPU_ONLY
from .source_visuals import SourceVisualError, prepare_source_visuals
from .timeline_builder import timeline_to_manifest
from .transcriber import TranscriptionError, transcribe_local_file


JOB_TYPES = {"voiceover", "voice_preview", "source_visuals", "render", "premiere_draft", "director_production"}
OPENMONTAGE_RENDER_PROVIDERS = {
    "openmontage",
    "openmontage_ffmpeg",
    "openmontage_remotion",
    "openmontage_hyperframes",
}

# VoxCPM2 is a voice-design / cloning model, rather than a model shipping a
# fixed speaker-ID catalogue.  These are deterministic, app-level audition
# presets. Selecting one promotes its generated WAV to the project's reference
# voice, which then locks the chosen speaker for every storyboard scene.
VOXCPM_PREVIEW_TEXT = "Xin chào. Đây là giọng đọc thử cho câu chuyện của bạn, rõ ràng, ấm áp và tự nhiên."
VOXCPM_VOICE_PRESETS: tuple[dict[str, Any], ...] = (
    {"key": "female_warm", "label": "Nữ ấm áp · kể chuyện", "style": "Vietnamese woman narrator, warm, gentle, clear, natural storytelling pace", "seed": 11021},
    {"key": "female_bright", "label": "Nữ tươi sáng · trẻ", "style": "Young Vietnamese woman, bright, friendly, clear, lively but natural", "seed": 11022},
    {"key": "female_calm", "label": "Nữ trầm · cổ tích", "style": "Vietnamese woman, calm, soft, mature, soothing fairy tale narrator", "seed": 11023},
    {"key": "male_warm", "label": "Nam ấm · gần gũi", "style": "Vietnamese man, warm, friendly, clear and natural storyteller", "seed": 11024},
    {"key": "male_deep", "label": "Nam trầm · tài liệu", "style": "Vietnamese man, deep, steady, confident documentary narrator", "seed": 11025},
    {"key": "male_young", "label": "Nam trẻ · năng động", "style": "Young Vietnamese man, energetic, upbeat, clear, conversational", "seed": 11026},
)


class ProductionJobError(RuntimeError):
    pass


def _command_args(template: str, values: dict[str, Any]) -> list[str]:
    if not template.strip():
        raise ProductionJobError("Chưa cấu hình command cho adapter production")
    try:
        rendered = template.format(**{key: str(value) for key, value in values.items()})
    except (KeyError, ValueError) as exc:
        raise ProductionJobError(f"Command template thiếu placeholder hoặc sai cú pháp: {exc}") from exc
    try:
        tokens = shlex.split(rendered, posix=False)
    except ValueError as exc:
        raise ProductionJobError(f"Command template không hợp lệ: {exc}") from exc
    return [token.strip('"') for token in tokens]


def _run_command(template: str, values: dict[str, Any], cwd: Path, require_cuda: bool = False) -> None:
    args = _command_args(template, values)
    if require_cuda and "--cuda" not in {str(item).lower() for item in args}:
        args.append("--cuda")
    command_env = os.environ.copy()
    command_env["PYTHONIOENCODING"] = "utf-8"
    command_env["PYTHONUTF8"] = "1"
    if GPU_ONLY:
        command_env["CUDA_VISIBLE_DEVICES"] = GPU_DEVICE_INDEX
    try:
        result = subprocess.run(
            args,
            cwd=str(cwd),
            env=command_env,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProductionJobError(f"Không chạy được production command: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-2000:]
        raise ProductionJobError(f"Production command thất bại ({result.returncode}): {detail}")


def _context(database: Database, job: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    project = database.get_production_project(int(job["project_id"]))
    script = database.get_project_script(int(job["script_id"]))
    timeline = database.list_project_timeline(
        int(job["project_id"]),
        script_id=int(job["script_id"]),
    )
    if not project or not script:
        raise ProductionJobError("Project hoặc script không còn tồn tại")
    if not timeline:
        raise ProductionJobError("Project chưa có timeline để chạy production job")
    return project, script, timeline


def _write_manifest(
    artifact_dir: Path,
    project: dict[str, Any],
    script: dict[str, Any],
    timeline: list[dict[str, Any]],
    filename: str,
) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / filename
    path.write_text(
        json.dumps(timeline_to_manifest(project, script, timeline), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _srt_timestamp(seconds: float) -> str:
    millis = max(0, int(round(seconds * 1000)))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def _write_voiceover_srt(path: Path, text: str, duration: float) -> None:
    path.write_text(
        "1\n"
        f"00:00:00,000 --> {_srt_timestamp(duration)}\n"
        f"{text.strip()}\n",
        encoding="utf-8",
    )


def _find_generated_audio(output_dir: Path, requested_output: Path) -> Path | None:
    if requested_output.is_file():
        return requested_output
    candidates = [
        item
        for item in output_dir.rglob("*")
        if item.is_file() and item.suffix.lower() in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime_ns)


def _voxcpm_style_from_role(voice_role: str) -> str:
    value = str(voice_role or "").strip()
    if value.lower().startswith("design:"):
        return value.split(":", 1)[1].strip()
    return ""


def _voxcpm_ffmpeg_binary(python_executable: str) -> str:
    """Locate a decoder bundled with the local VoxCPM virtual environment."""
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    python_path = Path(python_executable).expanduser()
    venv_root = python_path.parent.parent
    bundled = venv_root / "Lib" / "site-packages" / "imageio_ffmpeg" / "binaries"
    candidates = sorted(bundled.glob("ffmpeg*.exe")) if bundled.is_dir() else []
    return str(candidates[0]) if candidates else ""


def _prepare_voxcpm_reference_audio(reference: Path, cwd: Path, python_executable: str) -> Path:
    """Decode any browser-uploaded audio into the WAV format VoxCPM expects.

    A file named ``.mp3`` is not necessarily decodable by libsndfile.  VoxCPM
    passes reference audio through librosa, so normalising it first makes the
    chosen voice sample reliable across Windows builds and keeps the original
    user file untouched.
    """
    ffmpeg = _voxcpm_ffmpeg_binary(python_executable)
    if not ffmpeg:
        raise ProductionJobError(
            "Không có bộ giải mã audio cho VoxCPM. Hãy cài FFmpeg hoặc tải file WAV 10–20 giây."
        )
    reference_dir = cwd / "voxcpm-reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    normalized = reference_dir / "reference.wav"
    result = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-y",
            "-i",
            str(reference),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "24000",
            "-c:a",
            "pcm_s16le",
            str(normalized),
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0 or not normalized.is_file() or normalized.stat().st_size < 1024:
        detail = (result.stderr or result.stdout or "FFmpeg không giải mã được file").strip()[-800:]
        raise ProductionJobError(
            "File giọng mẫu không đọc được. Hãy chọn file WAV/MP3 hợp lệ (một người nói, 10–20 giây). "
            f"Chi tiết: {detail}"
        )
    return normalized


def _run_voxcpm_batch(
    python_executable: str,
    runner_path: str,
    model: str,
    device: str,
    requests: list[dict[str, str]],
    cwd: Path,
    reference_audio: str = "",
    prompt_text: str = "",
) -> None:
    if not python_executable.strip() or not runner_path.strip():
        raise ProductionJobError("VoxCPM runtime is not configured")
    if not device.strip().lower().startswith("cuda"):
        raise ProductionJobError("VoxCPM production requires CUDA")
    reference = Path(reference_audio).expanduser() if reference_audio.strip() else None
    if reference and not reference.is_file():
        raise ProductionJobError(f"VoxCPM reference audio was not found: {reference}")
    # Force a known-good, mono WAV reference. This fixes local files encoded
    # with an MP3 variant unsupported by the installed soundfile backend.
    if reference:
        reference = _prepare_voxcpm_reference_audio(reference, cwd, python_executable)
    manifest_requests: list[dict[str, str]] = []
    for item in requests:
        payload = dict(item)
        if reference:
            # `reference_audio` alone selects VoxCPM's isolated voice-cloning
            # mode (timbre only, no transcript needed) — the right mode here,
            # since this app only has a free-text style description, not an
            # accurate transcript of the sample clip.
            #
            # VoxCPM's `prompt_text` parameter is NOT a style description: per
            # the model's own docs it must be the exact transcript of the
            # reference audio, used to align audio features with language-
            # model tokens. Sending our style text there previously broke
            # that alignment and produced garbled/wrong-language speech
            # (reported: Vietnamese input, Thai-sounding output). The style
            # text instead goes through voxcpm_runner.py's `style` field,
            # which is prepended to the narration as "(style) text" — a
            # generation hint, not an audio/text alignment.
            payload["reference_audio"] = str(reference)
            if prompt_text.strip():
                payload["style"] = prompt_text.strip()
        manifest_requests.append(payload)
    manifest_path = cwd / "voxcpm-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_requests, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    if GPU_ONLY:
        environment["CUDA_VISIBLE_DEVICES"] = GPU_DEVICE_INDEX
    command = [
        python_executable,
        runner_path,
        "--manifest",
        str(manifest_path),
        "--model",
        model,
        "--device",
        device,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            env=environment,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProductionJobError(f"VoxCPM GPU process could not start: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-3000:]
        raise ProductionJobError(f"VoxCPM GPU process failed ({result.returncode}): {detail}")


def run_voxcpm_voice_preview_job(
    database: Database,
    job: dict[str, Any],
    artifact_root: Path,
    voxcpm_python: str,
    voxcpm_runner: str,
    voxcpm_model: str = "openbmb/VoxCPM2",
    voxcpm_device: str = "cuda",
) -> str:
    """Generate the deterministic VoxCPM voice-design audition library."""
    project = database.get_production_project(int(job["project_id"]))
    if not project:
        raise ProductionJobError("Project không còn tồn tại")
    layout = ensure_project_layout(artifact_root, int(project["id"]))
    work_dir = layout["work"] / "voxcpm-voice-previews"
    preview_dir = layout["audio"] / "voice-previews"
    work_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    requests = [
        {
            "text": VOXCPM_PREVIEW_TEXT,
            "output": str(preview_dir / f"{preset['key']}.wav"),
            "style": str(preset["style"]),
            "seed": str(preset["seed"]),
        }
        for preset in VOXCPM_VOICE_PRESETS
    ]
    _run_voxcpm_batch(
        voxcpm_python,
        voxcpm_runner,
        voxcpm_model,
        voxcpm_device,
        requests,
        work_dir,
    )
    missing = [preset["key"] for preset in VOXCPM_VOICE_PRESETS if not (preview_dir / f"{preset['key']}.wav").is_file()]
    if missing:
        raise ProductionJobError(f"VoxCPM không tạo được voice preview: {', '.join(missing)}")
    return str(preview_dir)


def run_voiceover_job(
    database: Database,
    job: dict[str, Any],
    artifact_root: Path,
    pyvideotrans_command: str,
    edge_tts_command: str = "",
    language: str = "vi",
    pyvideotrans_workdir: str = "",
    voice_role: str = "vi-VN-HoaiMyNeural",
    tts_type: str = "0",
    voxcpm_python: str = "",
    voxcpm_runner: str = "",
    voxcpm_model: str = "openbmb/VoxCPM2",
    voxcpm_device: str = "cuda",
    voxcpm_reference_audio: str = "",
    voxcpm_prompt_text: str = "",
) -> str:
    project, script, timeline = _context(database, job)
    render_settings = database.get_project_render_settings(int(project["id"]))
    language = str(render_settings.get("publish_language") or language)
    voice_role = str(render_settings.get("voice_model") or voice_role)
    voice_rate = str(render_settings.get("voice_rate") or "+0%").strip()
    voxcpm_reference_audio = str(
        render_settings.get("voice_reference_file_path") or voxcpm_reference_audio
    ).strip()
    voxcpm_prompt_text = str(
        render_settings.get("voice_prompt_text") or voxcpm_prompt_text
    ).strip()
    subtitle_provider = str(render_settings.get("subtitle_provider") or "timeline_text").strip().lower()
    subtitle_model = str(render_settings.get("subtitle_model") or "").strip().lower()
    subtitle_model = subtitle_model.removeprefix("faster-whisper-") or None
    layout = ensure_project_layout(artifact_root, project["id"])
    project_dir = layout["work"] / "voiceover"
    project_dir.mkdir(parents=True, exist_ok=True)
    subtitle_dir = project_dir / "subtitles"
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = layout["audio"]
    manifest_path = _write_manifest(
        project_dir,
        project,
        script,
        timeline,
        "voiceover-plan.json",
    )
    provider = str(job["provider"]).strip().lower()
    if provider in {"dry_run", "preview", "mock"}:
        return str(manifest_path)
    if provider not in {"pyvideotrans", "py_video_trans", "edge_tts", "voxcpm"}:
        raise ProductionJobError(f"Voiceover provider không được hỗ trợ: {job['provider']}")
    if provider == "edge_tts" and not edge_tts_command.strip():
        raise ProductionJobError("Chưa cấu hình EDGE_TTS_COMMAND")

    if provider == "voxcpm" and (not voxcpm_python.strip() or not voxcpm_runner.strip()):
        raise ProductionJobError("VoxCPM runtime is not configured")
    if provider == "voxcpm" and not voxcpm_reference_audio:
        raise ProductionJobError(
            "VoxCPM cần một file giọng mẫu cố định để không đổi người đọc giữa các cảnh. "
            "Ở bước Giọng đọc, tải WAV/MP3 sạch 10–20 giây (một người nói) rồi chọn file đó trước khi tạo giọng."
        )
    if provider == "voxcpm":
        voxcpm_requests: list[dict[str, str]] = []
        for item in timeline:
            voice_text = str(item.get("voice_text") or "").strip()
            if not voice_text:
                raise ProductionJobError(f"Segment {item.get('segment_index')} has no voiceover text")
            index = int(item.get("segment_index") or 1)
            duration = max(0.1, float(item.get("duration_seconds") or 1))
            srt_path = project_dir / f"segment-{index:03d}.srt"
            _write_voiceover_srt(srt_path, voice_text, duration)
            output_path = audio_dir / f"segment-{index:03d}.wav"
            voxcpm_requests.append(
                {
                    "text": voice_text,
                    "output": str(output_path),
                    "style": _voxcpm_style_from_role(voice_role),
                }
            )
        _run_voxcpm_batch(
            voxcpm_python,
            voxcpm_runner,
            voxcpm_model,
            voxcpm_device,
            voxcpm_requests,
            project_dir,
            reference_audio=voxcpm_reference_audio,
            prompt_text=voxcpm_prompt_text,
        )

    for item in timeline:
        voice_text = str(item.get("voice_text") or "").strip()
        if not voice_text:
            raise ProductionJobError(f"Segment {item.get('segment_index')} chưa có lời voiceover")
        index = int(item.get("segment_index") or 1)
        duration = max(0.1, float(item.get("duration_seconds") or 1))
        srt_path = project_dir / f"segment-{index:03d}.srt"
        text_path = project_dir / f"segment-{index:03d}.txt"
        output_path = audio_dir / f"segment-{index:03d}.{ 'mp3' if provider == 'edge_tts' else 'wav' }"
        output_dir = project_dir / f"tts-output-{index:03d}"
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_voiceover_srt(srt_path, voice_text, duration)
        if provider == "edge_tts":
            text_path.write_text(voice_text, encoding="utf-8")
            values = {
                "text_file": text_path,
                "srt_file": srt_path,
                "output_file": output_path,
                "output_dir": output_dir,
                "language": language,
                "segment_index": index,
                "voice_role": voice_role,
                "voice_rate": voice_rate,
                "tts_type": tts_type,
            }
            last_error: ProductionJobError | None = None
            # The public Edge endpoint can occasionally return no audio after
            # several rapid requests. Retry the individual segment instead of
            # discarding all successful segments in the job.
            for attempt in range(3):
                try:
                    _run_command(edge_tts_command, values, cwd=project_dir)
                    if output_path.is_file() and output_path.stat().st_size > 0:
                        last_error = None
                        break
                    last_error = ProductionJobError(f"Edge TTS không tạo audio cho segment {index}")
                except ProductionJobError as exc:
                    last_error = exc
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
            if last_error:
                if "NoAudioReceived" in str(last_error) or "No audio was received" in str(last_error):
                    raise ProductionJobError(
                        "Edge TTS không trả audio từ dịch vục Edge trên mạng hiện tại, "
                        "không phải lỗi kịch bản. Hãy chọn VoxCPM2 local GPU ở bước Giọng đọc rồi thử lại."
                    ) from last_error
                raise last_error
        elif provider in {"pyvideotrans", "py_video_trans"}:
            command_cwd = Path(pyvideotrans_workdir).expanduser() if pyvideotrans_workdir.strip() else project_dir
            if pyvideotrans_workdir.strip() and not command_cwd.is_dir():
                raise ProductionJobError(f"Không tìm thấy PYVIDEOTRANS_WORKDIR: {command_cwd}")
            _run_command(
                pyvideotrans_command,
                {
                    "text_file": srt_path,
                    "srt_file": srt_path,
                    "output_file": output_path,
                    "output_dir": output_dir,
                    "language": language,
                    "segment_index": index,
                    "voice_role": voice_role,
                    "voice_rate": voice_rate,
                    "tts_type": tts_type,
                },
                cwd=command_cwd,
                require_cuda=GPU_ONLY,
            )
        generated = output_path if provider in {"edge_tts", "voxcpm"} and output_path.is_file() else None
        if provider in {"pyvideotrans", "py_video_trans"}:
            generated = _find_generated_audio(output_dir, output_path)
        if not generated:
            raise ProductionJobError(
                f"pyVideoTrans không tạo audio cho segment {index}; kiểm tra voice_role và output_dir"
            )
        if generated != output_path:
            normalized_output = output_path.with_suffix(generated.suffix.lower())
            shutil.copy2(generated, normalized_output)
            output_path = normalized_output
        # Planned speaking speed is only a rough estimate.  Preserve an integer
        # timeline for the UI/Premiere package, while the FFmpeg renderer reads the
        # precise duration from the voice file itself.
        actual_duration = media_duration_seconds(output_path)
        subtitle_text = None
        subtitle_path = None
        if subtitle_provider == "faster_whisper_local":
            try:
                subtitle_result = transcribe_local_file(
                    output_path,
                    f"project-{project['id']}-segment-{index}",
                    language=language.split("-", 1)[0].lower(),
                    model_size=subtitle_model,
                )
            except TranscriptionError as exc:
                raise ProductionJobError(
                    f"Không tạo được phụ đề GPU cho segment {index}: {exc}"
                ) from exc
            if not subtitle_result["segments"]:
                raise ProductionJobError(f"Faster-Whisper không nhận được lời nói ở segment {index}")
            subtitle_text = str(subtitle_result.get("text") or voice_text).strip()
            subtitle_path_obj = subtitle_dir / f"segment-{index:03d}.srt"
            subtitle_path_obj.write_text(subtitle_result["srt"], encoding="utf-8")
            subtitle_path = str(subtitle_path_obj)
        database.update_project_timeline_segment(
            int(item["id"]),
            audio_path=str(output_path),
            subtitle_text=subtitle_text,
            subtitle_path=subtitle_path,
            duration_seconds=max(1, int(math.ceil(actual_duration or duration))),
            status="voice_ready",
        )
    return str(audio_dir)


def run_source_visuals_job(
    database: Database,
    job: dict[str, Any],
    artifact_root: Path,
    ffmpeg_binary: str = "ffmpeg",
) -> str:
    """Cut meaningful muted visuals from the project's explicitly downloaded source."""
    project, script, timeline = _context(database, job)
    layout = ensure_project_layout(artifact_root, project["id"])
    work_dir = layout["work"] / "source_visuals"
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = _write_manifest(work_dir, project, script, timeline, "source-visual-plan.json")
    provider = str(job["provider"]).strip().lower()
    if provider in {"dry_run", "preview", "mock"}:
        return str(manifest_path)
    if provider not in {"source_video", "source", "local_source"}:
        raise ProductionJobError(f"Source visual provider không được hỗ trợ: {job['provider']}")
    video = database.get_video(str(project["youtube_video_id"]))
    source_path = Path(str((video or {}).get("local_media_path") or ""))
    if not source_path.is_file():
        raise ProductionJobError(
            "Chưa có video nguồn trên máy. Hãy bấm ‘Tải video nguồn’ trong thư viện, "
            "sau đó chạy ‘Chuẩn bị cảnh nguồn’."
        )
    try:
        cuts = prepare_source_visuals(
            timeline,
            source_path,
            layout["assets"] / "source_clips",
            description=str((video or {}).get("description") or ""),
            ffmpeg_binary=ffmpeg_binary,
        )
    except SourceVisualError as exc:
        raise ProductionJobError(str(exc)) from exc
    for cut in cuts:
        segment = next(item for item in timeline if int(item["id"]) == cut["segment_id"])
        database.update_project_timeline_segment(
            cut["segment_id"],
            visual_path=cut["visual_path"],
            duration_seconds=cut["duration_seconds"],
            status="ready" if str(segment.get("audio_path") or "").strip() else "asset_ready",
        )
    source_manifest = work_dir / "source-visual-cuts.json"
    source_manifest.write_text(json.dumps(cuts, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(layout["assets"] / "source_clips")


def run_render_job(
    database: Database,
    job: dict[str, Any],
    artifact_root: Path,
    ffmpeg_command: str,
    ffmpeg_binary: str = "ffmpeg",
    openmontage_adapter: OpenMontageAdapter | None = None,
) -> str:
    project, script, timeline = _context(database, job)
    provider = str(job["provider"]).strip().lower()
    layout = ensure_project_layout(artifact_root, project["id"])
    project_dir = layout["work"] / "render"
    project_dir.mkdir(parents=True, exist_ok=True)
    output_path = layout["exports"] / "final.mp4"
    manifest_path = _write_manifest(
        project_dir,
        project,
        script,
        timeline,
        "render-manifest.json",
    )
    if provider in {"dry_run", "preview", "mock"}:
        return str(manifest_path)
    if provider in OPENMONTAGE_RENDER_PROVIDERS:
        if openmontage_adapter is None:
            raise ProductionJobError("OpenMontage adapter chưa được khởi tạo")
        render_settings = database.get_project_render_settings(int(project["id"]))
        music_path = Path(str(render_settings.get("music_file_path") or ""))
        return openmontage_adapter.render_timeline(
            project,
            script,
            timeline,
            output_path,
            layout["work"] / "openmontage",
            provider=provider,
            background_music=music_path if music_path.is_file() else None,
            music_volume=float(render_settings.get("music_volume") or 0.12),
            profile=str(render_settings.get("output_profile") or "youtube_landscape"),
        )
    if provider == "ffmpeg_builtin":
        draft_segments = [
            str(item.get("segment_index") or "?")
            for item in timeline
            if "director_draft_visuals" in str(item.get("visual_path") or "").replace("\\", "/").lower()
        ]
        if draft_segments:
            raise ProductionJobError(
                "Các cảnh " + ", ".join(draft_segments)
                + " vẫn là visual draft nội bộ. Hãy thay bằng video AI hoặc ảnh/video thật trước khi render bản xuất bản."
            )
        render_settings = database.get_project_render_settings(int(project["id"]))
        music_path = Path(str(render_settings.get("music_file_path") or ""))
        return render_timeline_with_ffmpeg(
            timeline,
            project_dir,
            output_filename=str(output_path),
            binary=ffmpeg_binary,
            background_music=music_path if music_path.is_file() else None,
            music_volume=float(render_settings.get("music_volume") or 0.12),
            transition=str(render_settings.get("transition_style") or "fade"),
        )
    if provider not in {"ffmpeg", "ffmpeg_command"}:
        raise ProductionJobError(f"Render provider không được hỗ trợ: {job['provider']}")
    missing = [
        str(item.get("segment_index"))
        for item in timeline
        if not str(item.get("audio_path") or "").strip()
        or not str(item.get("visual_path") or "").strip()
    ]
    if missing:
        raise ProductionJobError(
            "Chưa đủ audio/visual path cho segment: " + ", ".join(missing)
        )
    _run_command(
        ffmpeg_command,
        {
            "manifest_file": manifest_path,
            "output_file": output_path,
            "project_id": project["id"],
        },
        cwd=project_dir,
    )
    if not output_path.exists():
        raise ProductionJobError(f"FFmpeg không tạo file output: {output_path}")
    return str(output_path)


def run_director_production_job(
    database: Database,
    job: dict[str, Any],
    artifact_root: Path,
    pyvideotrans_command: str,
    edge_tts_command: str,
    ffmpeg_command: str,
    ffmpeg_binary: str,
    language: str = "vi",
    pyvideotrans_workdir: str = "",
    voice_role: str = "vi-VN-HoaiMyNeural",
    tts_type: str = "0",
    voxcpm_python: str = "",
    voxcpm_runner: str = "",
    voxcpm_model: str = "openbmb/VoxCPM2",
    voxcpm_device: str = "cuda",
    voxcpm_reference_audio: str = "",
    voxcpm_prompt_text: str = "",
) -> str:
    """Run one coherent, reviewable local production sequence.

    The Director endpoint has already produced a fresh script, shot list and
    timeline.  This worker owns only the media work: voice, real source clips,
    subtitles/final render, then an explicit quality report beside the output.
    """
    render_settings = database.get_project_render_settings(int(job["project_id"]))
    provider = str(render_settings.get("voice_provider") or job["provider"] or "edge_tts").strip().lower()
    if provider not in {"edge_tts", "pyvideotrans", "voxcpm"}:
        raise ProductionJobError("AI Đạo diễn hiện dùng Edge TTS cho luồng dựng tự động")
    if provider == "edge_tts" and not edge_tts_command.strip():
        raise ProductionJobError("Chưa cấu hình EDGE_TTS_COMMAND")

    if provider == "pyvideotrans" and not pyvideotrans_command.strip():
        raise ProductionJobError("Chưa cấu hình PYVIDEOTRANS_COMMAND")
    if provider == "voxcpm" and (not voxcpm_python.strip() or not voxcpm_runner.strip()):
        raise ProductionJobError("VoxCPM runtime is not configured")
    run_voiceover_job(
        database,
        {**job, "provider": provider},
        artifact_root,
        pyvideotrans_command,
        edge_tts_command=edge_tts_command,
        language=language,
        pyvideotrans_workdir=pyvideotrans_workdir,
        voice_role=voice_role,
        tts_type=tts_type,
        voxcpm_python=voxcpm_python,
        voxcpm_runner=voxcpm_runner,
        voxcpm_model=voxcpm_model,
        voxcpm_device=voxcpm_device,
        voxcpm_reference_audio=voxcpm_reference_audio,
        voxcpm_prompt_text=voxcpm_prompt_text,
    )
    project, script, timeline = _context(database, job)
    try:
        visuals = generate_local_visual_draft(
            timeline,
            ensure_project_layout(artifact_root, project["id"])["assets"] / "director_draft_visuals",
            binary=ffmpeg_binary,
        )
    except Exception as exc:
        raise ProductionJobError(f"Không tạo được visual draft cho AI Đạo diễn: {exc}") from exc
    for visual in visuals:
        segment = database.get_project_timeline_segment(int(visual["segment_id"]))
        if not segment:
            raise ProductionJobError(f"Không tìm thấy timeline segment {visual['segment_id']}")
        database.update_project_timeline_segment(
            int(visual["segment_id"]),
            visual_path=str(visual["visual_path"]),
            asset_type="director_draft_visual",
            duration_seconds=int(visual["duration_seconds"]),
            status="ready" if str(segment.get("audio_path") or "").strip() else "asset_ready",
        )
    final_path = run_render_job(
        database,
        {**job, "provider": "ffmpeg_builtin"},
        artifact_root,
        ffmpeg_command,
        ffmpeg_binary,
    )
    project, _, timeline = _context(database, job)
    layout = ensure_project_layout(artifact_root, project["id"])
    report = build_quality_report(timeline, final_path, ffmpeg_binary)
    quality_path = layout["exports"] / "quality-report.md"
    quality_path.write_text(quality_report_markdown(report), encoding="utf-8")
    # Publication-only warnings (for example a thumbnail is not selected yet)
    # must not turn a valid MP4 into a failed render job. The report remains
    # beside the video and Publisher can require the missing item later.
    return final_path


def run_premiere_draft_job(
    database: Database,
    job: dict[str, Any],
    artifact_root: Path,
    pyvideotrans_command: str,
    edge_tts_command: str = "",
    language: str = "vi",
    pyvideotrans_workdir: str = "",
    voice_role: str = "vi-VN-HoaiMyNeural",
    tts_type: str = "0",
    voxcpm_python: str = "",
    voxcpm_runner: str = "",
    voxcpm_model: str = "openbmb/VoxCPM2",
    voxcpm_device: str = "cuda",
    voxcpm_reference_audio: str = "",
    voxcpm_prompt_text: str = "",
) -> str:
    """Create voiceover segments and package a Premiere-ready draft in one job."""
    provider = str(job["provider"]).strip().lower()
    if provider in {"dry_run", "preview", "mock"}:
        project, script, timeline = _context(database, job)
    else:
        if provider not in {"pyvideotrans", "py_video_trans", "edge_tts", "voxcpm"}:
            raise ProductionJobError(f"Premiere draft provider không được hỗ trợ: {job['provider']}")
        run_voiceover_job(
            database,
            job,
            artifact_root,
            pyvideotrans_command,
            edge_tts_command=edge_tts_command,
            language=language,
            pyvideotrans_workdir=pyvideotrans_workdir,
            voice_role=voice_role,
            tts_type=tts_type,
            voxcpm_python=voxcpm_python,
            voxcpm_runner=voxcpm_runner,
            voxcpm_model=voxcpm_model,
            voxcpm_device=voxcpm_device,
            voxcpm_reference_audio=voxcpm_reference_audio,
            voxcpm_prompt_text=voxcpm_prompt_text,
        )
        project, script, timeline = _context(database, job)

    package = build_premiere_export_package(
        project,
        script,
        timeline,
        database.get_video(str(project["youtube_video_id"])),
        artifact_root,
    )
    return str(package["zip_path"])


class ProductionWorker:
    """Persistent-backed worker for voiceover preparation and final rendering."""

    def __init__(
        self,
        database: Database,
        artifact_root: Path,
        pyvideotrans_command: str = "",
        edge_tts_command: str = "",
        ffmpeg_command: str = "",
        ffmpeg_binary: str = "ffmpeg",
        pyvideotrans_workdir: str = "",
        pyvideotrans_voice_role: str = "vi-VN-HoaiMyNeural",
        pyvideotrans_tts_type: str = "0",
        voxcpm_python: str = "",
        voxcpm_runner: str = "",
        voxcpm_model: str = "openbmb/VoxCPM2",
        voxcpm_device: str = "cuda",
        voxcpm_reference_audio: str = "",
        voxcpm_prompt_text: str = "",
        language: str = "vi",
        openmontage_adapter: OpenMontageAdapter | None = None,
    ):
        self.database = database
        self.artifact_root = Path(artifact_root)
        self.pyvideotrans_command = pyvideotrans_command
        self.edge_tts_command = edge_tts_command
        self.ffmpeg_command = ffmpeg_command
        self.ffmpeg_binary = ffmpeg_binary
        self.pyvideotrans_workdir = pyvideotrans_workdir
        self.pyvideotrans_voice_role = pyvideotrans_voice_role
        self.pyvideotrans_tts_type = pyvideotrans_tts_type
        self.voxcpm_python = voxcpm_python
        self.voxcpm_runner = voxcpm_runner
        self.voxcpm_model = voxcpm_model
        self.voxcpm_device = voxcpm_device
        self.voxcpm_reference_audio = voxcpm_reference_audio
        self.voxcpm_prompt_text = voxcpm_prompt_text
        self.language = language
        self.openmontage_adapter = openmontage_adapter
        self._jobs: Queue[int | None] = Queue()
        self._stop = Event()
        self._lock = Lock()
        self._paused = False
        self._thread: Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._paused = False
            self.database.requeue_interrupted_project_jobs()
            for job_id in self.database.list_queued_project_job_ids():
                self._jobs.put(job_id)
            self._thread = Thread(target=self._run, name="production-worker", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._jobs.put(None)
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
        self._thread = None

    def enqueue(
        self,
        project_id: int,
        script_id: int,
        job_type: str,
        provider: str,
        force: bool = False,
    ) -> dict[str, Any]:
        if job_type not in JOB_TYPES:
            raise ProductionJobError(f"Job type không được hỗ trợ: {job_type}")
        job = self.database.create_project_job(
            project_id,
            script_id,
            job_type,
            provider,
            force=force,
        )
        if not job:
            raise ProductionJobError("Không tìm thấy project hoặc script")
        if job["status"] == "queued":
            self._jobs.put(int(job["id"]))
        return job

    def set_paused(self, paused: bool) -> dict[str, Any]:
        with self._lock:
            self._paused = paused
        return self.status()

    def status(self, project_id: int | None = None) -> dict[str, Any]:
        with self._lock:
            paused = self._paused
        return {
            **self.database.project_job_status(project_id),
            "paused": paused,
            "worker_running": bool(self._thread and self._thread.is_alive()),
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            job_id = self._jobs.get()
            try:
                if job_id is None:
                    return
                while not self._stop.is_set():
                    with self._lock:
                        paused = self._paused
                    if not paused:
                        break
                    self._stop.wait(timeout=0.25)
                if self._stop.is_set():
                    continue
                self._process(job_id)
            finally:
                self._jobs.task_done()

    def _process(self, job_id: int) -> None:
        job = self.database.claim_project_job(job_id)
        if not job:
            return
        try:
            if job["job_type"] == "voiceover":
                output_path = run_voiceover_job(
                    self.database,
                    job,
                    self.artifact_root,
                    self.pyvideotrans_command,
                    edge_tts_command=self.edge_tts_command,
                    language=self.language,
                    pyvideotrans_workdir=self.pyvideotrans_workdir,
                    voice_role=self.pyvideotrans_voice_role,
                    tts_type=self.pyvideotrans_tts_type,
                    voxcpm_python=self.voxcpm_python,
                    voxcpm_runner=self.voxcpm_runner,
                    voxcpm_model=self.voxcpm_model,
                    voxcpm_device=self.voxcpm_device,
                    voxcpm_reference_audio=self.voxcpm_reference_audio,
                    voxcpm_prompt_text=self.voxcpm_prompt_text,
                )
            elif job["job_type"] == "voice_preview":
                output_path = run_voxcpm_voice_preview_job(
                    self.database,
                    job,
                    self.artifact_root,
                    voxcpm_python=self.voxcpm_python,
                    voxcpm_runner=self.voxcpm_runner,
                    voxcpm_model=self.voxcpm_model,
                    voxcpm_device=self.voxcpm_device,
                )
            elif job["job_type"] == "source_visuals":
                output_path = run_source_visuals_job(
                    self.database,
                    job,
                    self.artifact_root,
                    ffmpeg_binary=self.ffmpeg_binary,
                )
            elif job["job_type"] == "render":
                output_path = run_render_job(
                    self.database,
                    job,
                    self.artifact_root,
                    self.ffmpeg_command,
                    self.ffmpeg_binary,
                    self.openmontage_adapter,
                )
            elif job["job_type"] == "premiere_draft":
                output_path = run_premiere_draft_job(
                    self.database,
                    job,
                    self.artifact_root,
                    self.pyvideotrans_command,
                    edge_tts_command=self.edge_tts_command,
                    language=self.language,
                    pyvideotrans_workdir=self.pyvideotrans_workdir,
                    voice_role=self.pyvideotrans_voice_role,
                    tts_type=self.pyvideotrans_tts_type,
                    voxcpm_python=self.voxcpm_python,
                    voxcpm_runner=self.voxcpm_runner,
                    voxcpm_model=self.voxcpm_model,
                    voxcpm_device=self.voxcpm_device,
                    voxcpm_reference_audio=self.voxcpm_reference_audio,
                    voxcpm_prompt_text=self.voxcpm_prompt_text,
                )
            elif job["job_type"] == "director_production":
                output_path = run_director_production_job(
                    self.database,
                    job,
                    self.artifact_root,
                    self.pyvideotrans_command,
                    self.edge_tts_command,
                    self.ffmpeg_command,
                    self.ffmpeg_binary,
                    language=self.language,
                    pyvideotrans_workdir=self.pyvideotrans_workdir,
                    voice_role=self.pyvideotrans_voice_role,
                    tts_type=self.pyvideotrans_tts_type,
                    voxcpm_python=self.voxcpm_python,
                    voxcpm_runner=self.voxcpm_runner,
                    voxcpm_model=self.voxcpm_model,
                    voxcpm_device=self.voxcpm_device,
                    voxcpm_reference_audio=self.voxcpm_reference_audio,
                    voxcpm_prompt_text=self.voxcpm_prompt_text,
                )
            else:
                raise ProductionJobError(f"Job type không được hỗ trợ: {job['job_type']}")
            self.database.finish_project_job(job_id, "completed", output_path=output_path)
        except Exception as exc:
            self.database.finish_project_job(job_id, "error", error=str(exc))
