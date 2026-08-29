"""Motion-graphics scenes: charts, stat cards and kinetic titles as clips.

Every other scene provider either generates imagery or fetches it. None of
them can draw an animated bar chart, a counting statistic or a kinetic title
— FFmpeg composes footage, it does not author motion. This provider fills
that gap by rendering React compositions to an MP4.

The compositions live in ``_HE_THONG/app/motion_composer`` and were copied
from OpenMontage under AGPL-3.0; see ``motion_composer/NGUON_GOC.md`` for
what that means before publishing the app. Everything in this file is our
own code and talks to them only through the ``remotion render`` command line
and a props JSON file.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from .database import Database
from .ffmpeg_renderer import _encoding_arguments, nvenc_available, resolve_ffmpeg
from .project_layout import ensure_project_layout


class MotionGraphicsError(RuntimeError):
    pass


COMPOSER_ROOT = Path(__file__).resolve().parent.parent / "motion_composer"
COMPOSITION_ID = "Explainer"

# Cut types the Explainer composition dispatches on. Kept in step with
# motion_composer/SCENE_TYPES.md, which is the upstream contract.
MOTION_CUT_TYPES = frozenset(
    {
        "text_card",
        "hero_title",
        "stat_card",
        "callout",
        "comparison",
        "bar_chart",
        "line_chart",
        "pie_chart",
        "kpi_grid",
        "progress_bar",
        "terminal_scene",
    }
)

MOTION_THEMES = ("flat-motion-graphics", "clean-professional", "minimalist-diagram", "anime-ghibli")
DEFAULT_THEME = "flat-motion-graphics"

# The composition adds one second of padding after the last cut so it can
# fade out. The scene needs its exact length, so that padding is trimmed off.
_TAIL_PADDING_SECONDS = 1

_RENDER_TIMEOUT_SECONDS = int(os.getenv("MOTION_RENDER_TIMEOUT_SECONDS", "900"))

SpecBuilder = Callable[[dict[str, Any]], dict[str, Any]]
_spec_builder: SpecBuilder | None = None


def set_spec_builder(callback: SpecBuilder | None) -> None:
    """Let the app turn a prose storyboard prompt into a cut spec.

    A storyboard prompt describes a picture; this provider needs structured
    data — the bars, the number, the steps. Converting between them takes a
    model, which lives in the app rather than here, so it is injected the way
    the scene worker already injects its prompt crafter.
    """
    global _spec_builder
    _spec_builder = callback


def composer_ready() -> tuple[bool, str]:
    """Report whether the composer can render, and why not when it cannot."""
    if not COMPOSER_ROOT.is_dir():
        return False, f"Khong tim thay motion_composer: {COMPOSER_ROOT}"
    if not (COMPOSER_ROOT / "src" / "index.tsx").is_file():
        return False, "motion_composer thieu src/index.tsx"
    if not (COMPOSER_ROOT / "node_modules").is_dir():
        return False, "Chua cai dependency: chay `npm ci` trong motion_composer"
    if not shutil.which("npx"):
        return False, "Khong tim thay Node/npx tren may"
    return True, ""


def _coerce_spec(candidate: Any) -> dict[str, Any] | None:
    """Accept a cut spec only when it names a type the composition knows."""
    if not isinstance(candidate, dict):
        return None
    cut_type = str(candidate.get("type") or "").strip()
    if cut_type not in MOTION_CUT_TYPES:
        return None
    return dict(candidate)


def build_cut_spec(job: dict[str, Any]) -> dict[str, Any]:
    """Decide what this scene should draw.

    A caller that already knows (the Director agent, or an MCP client) passes
    the spec as JSON in the prompt. Otherwise the app's model is asked. If
    neither is available the scene still renders, as a typographic card, so a
    missing model degrades the scene rather than failing the job.
    """
    raw = str(job.get("prompt") or "").strip()
    if not raw:
        raise MotionGraphicsError("Prompt cho canh motion graphics dang trong")
    if raw.startswith("{"):
        try:
            direct = _coerce_spec(json.loads(raw))
        except json.JSONDecodeError:
            direct = None
        if direct:
            return direct
    if _spec_builder is not None:
        try:
            built = _coerce_spec(_spec_builder(job))
        except Exception as exc:
            raise MotionGraphicsError(f"Khong dung duoc spec motion graphics: {exc}") from exc
        if built:
            return built
    return {"type": "text_card", "text": raw[:400]}


def build_props(job: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Wrap one cut spec in the props the Explainer composition expects."""
    duration = max(1, int(job.get("duration_seconds") or 5))
    theme = str(spec.get("theme") or DEFAULT_THEME)
    if theme not in MOTION_THEMES:
        theme = DEFAULT_THEME
    cut = {key: value for key, value in spec.items() if key != "theme"}
    cut.update(
        {
            "id": f"scene-{int(job.get('timeline_segment_id') or 0)}",
            "source": "",
            "in_seconds": 0,
            "out_seconds": duration,
        }
    )
    return {"theme": theme, "cuts": [cut], "overlays": [], "captions": [], "audio": {}}


def _target_size(ratio: str) -> tuple[int, int]:
    parts = str(ratio or "").replace("x", ":").split(":")
    try:
        width, height = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return 1280, 720
    if width <= 0 or height <= 0:
        return 1280, 720
    return width - width % 2, height - height % 2


def _render_composition(props: dict[str, Any], destination: Path) -> None:
    """Run one `remotion render` at the composition's native 1920x1080."""
    ready, detail = composer_ready()
    if not ready:
        raise MotionGraphicsError(detail)
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8", dir=str(destination.parent)
    )
    try:
        json.dump(props, handle, ensure_ascii=False)
        handle.close()
        completed = subprocess.run(
            [
                "npx", "remotion", "render",
                "src/index.tsx", COMPOSITION_ID, str(destination),
                f"--props={handle.name}",
                "--log=error",
            ],
            cwd=str(COMPOSER_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_RENDER_TIMEOUT_SECONDS,
            shell=os.name == "nt",
        )
    except subprocess.TimeoutExpired as exc:
        raise MotionGraphicsError(
            f"Remotion render qua {_RENDER_TIMEOUT_SECONDS}s"
        ) from exc
    except OSError as exc:
        raise MotionGraphicsError(f"Khong chay duoc Remotion: {exc}") from exc
    finally:
        Path(handle.name).unlink(missing_ok=True)
    if completed.returncode != 0 or not destination.is_file() or destination.stat().st_size == 0:
        detail = ((completed.stderr or "") + "\n" + (completed.stdout or "")).strip()[-1500:]
        raise MotionGraphicsError(f"Remotion render that bai: {detail or '(khong co output)'}")


def _normalise_clip(
    source_path: Path,
    output_path: Path,
    *,
    duration_seconds: int,
    ratio: str,
    ffmpeg_binary: str,
) -> None:
    """Trim the composition's fade padding and fit the project's frame."""
    executable = resolve_ffmpeg(ffmpeg_binary)
    if not executable:
        raise MotionGraphicsError(f"Khong tim thay FFmpeg ({ffmpeg_binary}) tren may")
    width, height = _target_size(ratio)
    codec = "h264_nvenc" if nvenc_available(ffmpeg_binary) else "libx264"
    completed = subprocess.run(
        [
            executable, "-y",
            "-t", f"{max(1, int(duration_seconds))}",
            "-i", str(source_path),
            "-vf",
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
            # Narration is mixed in by the timeline; the composition's silent
            # audio track would only add an empty stream to reconcile later.
            "-an",
            *_encoding_arguments(codec),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if completed.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-1200:]
        raise MotionGraphicsError(f"FFmpeg khong chuan hoa duoc clip motion: {detail}")


def generate_motion_graphics_scene(
    database: Database,
    job: dict[str, Any],
    artifact_root: Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
) -> str:
    """Render one scene as motion graphics and return the clip path."""
    del database  # The provider contract passes it; this renderer needs none.
    spec = build_cut_spec(dict(job))
    props = build_props(dict(job), spec)
    output_dir = ensure_project_layout(artifact_root, job["project_id"])["assets"] / "generated_scenes"
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"motion-segment-{int(job['timeline_segment_id'])}-job-{int(job['id'])}"
    output_path = output_dir / f"{stem}.mp4"
    raw_path = output_dir / f"{stem}.raw.mp4"
    try:
        _render_composition(props, raw_path)
        _normalise_clip(
            raw_path,
            output_path,
            duration_seconds=int(job.get("duration_seconds") or 5),
            ratio=str(job.get("ratio") or ""),
            ffmpeg_binary=ffmpeg_binary,
        )
    finally:
        raw_path.unlink(missing_ok=True)
    return str(output_path)
