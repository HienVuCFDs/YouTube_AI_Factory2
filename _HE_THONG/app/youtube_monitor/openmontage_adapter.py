from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .subtitle_builder import subtitle_chunks


class OpenMontageError(RuntimeError):
    pass


_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
_RUNTIME_BY_PROVIDER = {
    "openmontage": None,
    "openmontage_ffmpeg": "ffmpeg",
    "openmontage_remotion": "remotion",
    "openmontage_hyperframes": "hyperframes",
}


def runtime_for_provider(provider: str, configured_runtime: str = "ffmpeg") -> str:
    name = str(provider or "").strip().lower()
    override = _RUNTIME_BY_PROVIDER.get(name)
    runtime = override or configured_runtime
    if runtime not in {"ffmpeg", "remotion", "hyperframes"}:
        raise OpenMontageError(f"OpenMontage runtime không hợp lệ: {runtime}")
    return runtime


class OpenMontageAdapter:
    def __init__(
        self,
        root: str | Path,
        python: str | Path = "",
        configured_runtime: str = "ffmpeg",
        ffmpeg_binary: str = "ffmpeg",
        timeout_seconds: int = 3600,
    ) -> None:
        self.root = Path(root).expanduser()
        self.python = Path(python).expanduser() if str(python).strip() else self._detect_python()
        self.configured_runtime = str(configured_runtime or "ffmpeg").strip().lower()
        self.ffmpeg_binary = ffmpeg_binary or "ffmpeg"
        self.timeout_seconds = max(60, int(timeout_seconds))
        self.bridge_path = Path(__file__).resolve().with_name("openmontage_bridge.py")

    def _detect_python(self) -> Path:
        candidates = [
            self.root / ".venv" / "Scripts" / "python.exe",
            self.root / ".venv" / "bin" / "python",
        ]
        on_path = shutil.which("python")
        if on_path:
            candidates.append(Path(on_path))
        return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])

    def _runtime_status(self, runtime: str) -> tuple[bool, str]:
        if runtime == "ffmpeg":
            ready = bool(shutil.which(self.ffmpeg_binary))
            return ready, "FFmpeg" if ready else f"Không tìm thấy {self.ffmpeg_binary}"
        if runtime == "remotion":
            composer = self.root / "remotion-composer"
            ready = bool(
                shutil.which("node")
                and shutil.which("npx")
                and (composer / "package.json").is_file()
                and (composer / "node_modules").is_dir()
            )
            return ready, "Remotion" if ready else "Remotion chưa đủ Node/npm hoặc node_modules"
        ready = bool(shutil.which("node") and shutil.which("npx") and shutil.which(self.ffmpeg_binary))
        return ready, "HyperFrames floor" if ready else "HyperFrames thiếu Node/npx/FFmpeg"

    def status(self) -> dict[str, Any]:
        root_ready = self.root.is_dir()
        python_ready = self.python.is_file()
        runtimes: dict[str, bool] = {}
        runtime_details: dict[str, str] = {}
        for runtime in ("ffmpeg", "remotion", "hyperframes"):
            ready, detail = self._runtime_status(runtime)
            runtimes[runtime] = bool(root_ready and python_ready and ready)
            runtime_details[runtime] = detail
        configured_ready = runtimes.get(self.configured_runtime, False)
        return {
            "enabled": root_ready,
            "ready": configured_ready,
            "root": str(self.root),
            "python": str(self.python),
            "configured_runtime": self.configured_runtime,
            "runtimes": runtimes,
            "runtime_details": runtime_details,
            "bridge": str(self.bridge_path),
            "detail": (
                f"OpenMontage sẵn sàng với {self.configured_runtime}"
                if configured_ready
                else "OpenMontage chưa sẵn sàng; kiểm tra root/.venv và runtime"
            ),
        }

    def _write_subtitles(
        self,
        path: Path,
        timeline: list[dict[str, Any]],
        maximum_words: int = 10,
    ) -> None:
        def timestamp(seconds: float) -> str:
            millis = max(0, int(round(seconds * 1000)))
            hours, millis = divmod(millis, 3_600_000)
            minutes, millis = divmod(millis, 60_000)
            secs, millis = divmod(millis, 1000)
            return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

        rows: list[str] = []
        cue_index = 1
        for item in timeline:
            text = str(item.get("subtitle_text") or item.get("voice_text") or "").strip()
            if not text:
                continue
            start = float(item.get("start_seconds") or 0)
            end = float(item.get("end_seconds") or start + float(item.get("duration_seconds") or 1))
            chunks = subtitle_chunks(text, maximum_words=max(1, int(maximum_words)))
            duration = max(0.1, end - start)
            weights = [max(1, len(chunk.split())) for chunk in chunks]
            total_weight = sum(weights) or 1
            cursor = start
            for chunk_index, (chunk, weight) in enumerate(zip(chunks, weights)):
                next_cursor = end if chunk_index == len(chunks) - 1 else cursor + duration * weight / total_weight
                rows.extend([
                    str(cue_index),
                    f"{timestamp(cursor)} --> {timestamp(next_cursor)}",
                    chunk,
                    "",
                ])
                cue_index += 1
                cursor = next_cursor
        path.write_text("\n".join(rows), encoding="utf-8")

    def _mix_voiceover(
        self,
        timeline: list[dict[str, Any]],
        output_path: Path,
        background_music: Path | None = None,
        music_volume: float = 0.12,
    ) -> Path | None:
        audio_paths = [Path(str(item.get("audio_path") or "")) for item in timeline]
        existing = [path for path in audio_paths if str(path) and path.is_file()]
        if not existing and not background_music:
            return None
        if existing and len(existing) != len(audio_paths):
            missing = [str(path) for path in audio_paths if not path.is_file()]
            raise OpenMontageError("Thiếu audio voiceover: " + ", ".join(missing[:8]))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        inputs: list[str] = []
        labels: list[str] = []
        if existing:
            for index, path in enumerate(existing):
                inputs.extend(["-i", str(path)])
                labels.append(f"[{index}:a]")
            voice_label = "[voice]"
            filter_parts = ["".join(labels) + f"concat=n={len(labels)}:v=0:a=1[voice]"]
        else:
            voice_label = ""
            filter_parts = []
        if background_music and background_music.is_file():
            music_index = len(existing)
            inputs.extend(["-stream_loop", "-1", "-i", str(background_music)])
            music_label = f"[{music_index}:a]"
            if voice_label:
                filter_parts.extend(
                    [
                        f"{voice_label}volume=1[voice_main]",
                        f"{music_label}volume={max(0.0, min(0.5, float(music_volume)))}[music]",
                        "[voice_main][music]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                    ]
                )
            else:
                filter_parts.extend(
                    [
                        f"{music_label}volume={max(0.0, min(0.5, float(music_volume)))}[aout]",
                    ]
                )
        else:
            if voice_label:
                filter_parts.append(f"{voice_label}anull[aout]")
        filter_graph = ";".join(filter_parts)
        duration_args = []
        if not existing:
            duration_args = [
                "-t",
                str(sum(max(0.1, float(item.get("duration_seconds") or 1)) for item in timeline)),
            ]
        command = [
            self.ffmpeg_binary,
            "-y",
            *inputs,
            "-filter_complex",
            filter_graph,
            "-map",
            "[aout]",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            *duration_args,
            str(output_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=600)
        if result.returncode != 0 or not output_path.is_file():
            detail = (result.stderr or result.stdout or "").strip()[-2000:]
            raise OpenMontageError(f"Không trộn được voiceover: {detail}")
        return output_path

    def render_timeline(
        self,
        project: dict[str, Any],
        script: dict[str, Any] | None,
        timeline: list[dict[str, Any]],
        output_path: str | Path,
        work_dir: str | Path,
        provider: str = "openmontage",
        background_music: str | Path | None = None,
        music_volume: float = 0.12,
        profile: str = "youtube_landscape",
    ) -> str:
        runtime = runtime_for_provider(provider, self.configured_runtime)
        status = self.status()
        if not status["enabled"] or not status["python"] or not self.python.is_file():
            raise OpenMontageError(f"OpenMontage chưa có Python environment: {status['python']}")
        if not status["runtimes"].get(runtime):
            raise OpenMontageError(
                f"OpenMontage runtime '{runtime}' chưa sẵn sàng: {status['runtime_details'].get(runtime)}"
            )
        if not self.bridge_path.is_file():
            raise OpenMontageError(f"Không tìm thấy bridge: {self.bridge_path}")
        if not timeline:
            raise OpenMontageError("Timeline trống")

        output = Path(output_path).resolve()
        work = Path(work_dir).resolve()
        work.mkdir(parents=True, exist_ok=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        subtitle_path = work / "subtitles.srt"
        vertical_profiles = {"youtube_shorts", "instagram_reels", "tiktok"}
        self._write_subtitles(
            subtitle_path,
            timeline,
            maximum_words=6 if str(profile or "").strip().lower() in vertical_profiles else 10,
        )
        music_path = Path(str(background_music)).expanduser() if background_music else None
        audio_path = self._mix_voiceover(
            timeline,
            work / "voiceover-mix.m4a",
            background_music=music_path if music_path and music_path.is_file() else None,
            music_volume=music_volume,
        )

        assets: list[dict[str, Any]] = []
        cuts: list[dict[str, Any]] = []
        script_text = "\n".join(str(item.get("voice_text") or "").strip() for item in timeline).strip()
        for index, item in enumerate(timeline, start=1):
            visual = Path(str(item.get("visual_path") or "")).expanduser()
            if not visual.is_file():
                raise OpenMontageError(f"Không tìm thấy visual segment {index}: {visual}")
            asset_id = f"youtube-ai-segment-{index:03d}"
            duration = max(0.1, float(item.get("duration_seconds") or 1))
            is_image = visual.suffix.lower() in _IMAGE_EXTENSIONS
            assets.append(
                {
                    "id": asset_id,
                    "path": str(visual.resolve()),
                    "type": "image" if is_image else "video",
                    "duration_seconds": duration,
                    "source": "youtube_ai_factory",
                }
            )
            cuts.append(
                {
                    "id": asset_id,
                    "source": asset_id,
                    "in_seconds": 0,
                    "out_seconds": duration,
                    "type": "image" if is_image else "video",
                    "transition_in": "fade" if runtime != "ffmpeg" else None,
                }
            )

        edit_decisions = {
            "version": "1.0",
            "render_runtime": runtime,
            "renderer_family": "documentary-montage",
            "composition_mode": "templated",
            "cuts": cuts,
            "subtitles": {"enabled": True, "source": str(subtitle_path)},
            "metadata": {
                "project_id": project.get("id"),
                "project_title": project.get("title") or script and script.get("script_title") or "",
                "proposal_render_runtime": runtime,
                "compose_target": {"width": 1920, "height": 1080, "fit": "cover"},
                "delivery_promise": "video-led documentary montage with narration and subtitles",
            },
        }
        payload = {
            "operation": "render",
            "output_path": str(output),
            "edit_decisions": edit_decisions,
            "asset_manifest": {"version": "1.0", "assets": assets},
            "subtitle_path": str(subtitle_path),
            "audio_path": str(audio_path) if audio_path else "",
            "profile": str(profile or "youtube_landscape").strip().lower(),
            "options": {"subtitle_burn": True},
            "script_text": script_text,
            "remotion_timeout_ms": 120000,
        }
        input_path = work / "openmontage-input.json"
        result_path = work / "openmontage-result.json"
        input_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        command = [
            str(self.python),
            "-u",
            str(self.bridge_path),
            "--root",
            str(self.root.resolve()),
            "--input",
            str(input_path),
            "--result",
            str(result_path),
        ]
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        try:
            result = subprocess.run(
                command,
                cwd=str(self.root),
                env=environment,
                capture_output=True,
                text=True, encoding="utf-8", errors="replace",
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise OpenMontageError(f"OpenMontage render quá thời gian {self.timeout_seconds}s") from exc
        except OSError as exc:
            raise OpenMontageError(f"Không chạy được OpenMontage: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-3000:]
            raise OpenMontageError(f"OpenMontage render thất bại ({result.returncode}): {detail}")
        if not output.is_file():
            raise OpenMontageError("OpenMontage chạy xong nhưng không tạo được final.mp4")
        return str(output)
