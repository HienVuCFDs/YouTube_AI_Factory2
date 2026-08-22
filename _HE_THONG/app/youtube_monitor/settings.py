from __future__ import annotations

import json
import os
import shutil
import site
import subprocess
import sys
from pathlib import Path


# The visible factory root stays clean for the user. Runtime code and secrets
# live under _HE_THONG/app and _HE_THONG/config after the folder migration.
APP_ROOT = Path(__file__).resolve().parent.parent
SYSTEM_ROOT = APP_ROOT.parent
PROJECT_ROOT = SYSTEM_ROOT.parent
ENV_PATH = SYSTEM_ROOT / "config" / ".env"

# Only these values may be changed from the local dashboard.  Keeping the
# allow-list here prevents the UI from becoming a generic editor for the
# machine's environment.
EDITABLE_INTEGRATION_KEYS = {
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "GEMINI_API_KEY",
    "GEMINI_IMAGE_MODEL",
    "GEMINI_VIDEO_MODEL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "RUNWAYML_API_SECRET",
    "RUNWAY_MODEL",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_OAUTH_REDIRECT_URI",
    "AI_ORCHESTRATOR_PROVIDER",
    "AI_STAGE_ASSIGNMENTS_JSON",
    "GFLOW_CLI_PATH",
    "GFLOW_PROFILE",
    "GFLOW_VIDEO_MODEL",
}


def _load_dotenv() -> None:
    """Load the local .env without adding another dependency for the MVP."""
    if not ENV_PATH.exists():
        return

    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


def integration_value(key: str, default: str = "") -> str:
    """Read a dashboard-managed integration value without exposing secrets."""
    return os.getenv(key, default).strip()


def save_integration_values(values: dict[str, str]) -> None:
    """Persist selected provider settings to the project-local .env file.

    The app is intended to run locally. Values are never returned by the API,
    and only the keys in ``EDITABLE_INTEGRATION_KEYS`` can be written.
    """
    if not values:
        return
    invalid = set(values) - EDITABLE_INTEGRATION_KEYS
    if invalid:
        raise ValueError(f"Không được phép thay đổi: {', '.join(sorted(invalid))}")
    normalized: dict[str, str] = {}
    for key, raw_value in values.items():
        value = str(raw_value).strip()
        if "\n" in value or "\r" in value:
            raise ValueError(f"Giá trị {key} không được chứa xuống dòng")
        normalized[key] = value

    existing_lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    remaining = dict(normalized)
    updated_lines: list[str] = []
    for raw_line in existing_lines:
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#") and "=" in raw_line:
            name = raw_line.split("=", 1)[0].strip()
            if name in remaining:
                updated_lines.append(f"{name}={remaining.pop(name)}")
                continue
        updated_lines.append(raw_line)
    if remaining:
        if updated_lines and updated_lines[-1].strip():
            updated_lines.append("")
        header = "# Local integrations (managed from dashboard)"
        if header not in updated_lines:
            updated_lines.append(header)
        updated_lines.extend(f"{key}={value}" for key, value in remaining.items())
    ENV_PATH.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    for key, value in normalized.items():
        os.environ[key] = value


def openai_config() -> tuple[str, str]:
    return integration_value("OPENAI_API_KEY"), integration_value("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini"


def gemini_config() -> tuple[str, str, str]:
    return (
        integration_value("GEMINI_API_KEY"),
        integration_value("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image") or "gemini-3.1-flash-image",
        integration_value("GEMINI_VIDEO_MODEL", "veo-3.1-lite-generate-preview") or "veo-3.1-lite-generate-preview",
    )


def anthropic_config() -> tuple[str, str]:
    return integration_value("ANTHROPIC_API_KEY"), integration_value("ANTHROPIC_MODEL", "claude-opus-5") or "claude-opus-5"


def runway_config() -> tuple[str, str]:
    return integration_value("RUNWAYML_API_SECRET"), integration_value("RUNWAY_MODEL", "gen4.5") or "gen4.5"


def _detect_codex_cli() -> str:
    configured = integration_value("CODEX_CLI_PATH")
    if configured and Path(configured).is_file():
        return configured
    on_path = shutil.which("codex")
    if on_path:
        return on_path
    vscode_extensions = Path(os.getenv("USERPROFILE", "")) / ".vscode" / "extensions"
    candidates = sorted(
        vscode_extensions.glob("openai.chatgpt-*/bin/windows-x86_64/codex.exe"),
        key=lambda path: str(path),
        reverse=True,
    ) if vscode_extensions.is_dir() else []
    return str(candidates[0]) if candidates else ""


def _detect_claude_code_cli() -> str:
    configured = integration_value("CLAUDE_CODE_CLI_PATH")
    if configured and Path(configured).is_file():
        return configured
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    vscode_extensions = Path(os.getenv("USERPROFILE", "")) / ".vscode" / "extensions"
    candidates = sorted(
        vscode_extensions.glob("anthropic.claude-code-*/resources/native-binary/claude.exe"),
        key=lambda path: str(path),
        reverse=True,
    ) if vscode_extensions.is_dir() else []
    return str(candidates[0]) if candidates else ""


def _detect_antigravity_cli() -> str:
    configured = integration_value("ANTIGRAVITY_CLI_PATH")
    if configured and Path(configured).is_file():
        return configured
    on_path = shutil.which("agy")
    if on_path:
        return on_path
    default = Path(os.getenv("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"
    return str(default) if default.is_file() else ""


def _detect_gflow_cli() -> str:
    """Find the isolated Google Flow CLI without requiring it on PATH."""
    configured = integration_value("GFLOW_CLI_PATH")
    if configured and Path(configured).is_file():
        return configured
    on_path = shutil.which("gflow")
    if on_path:
        return on_path
    executable = "gflow.exe" if os.name == "nt" else "gflow"
    candidates = (
        PROJECT_ROOT / "_THU_NGHIEM" / "gflow-cli" / ".venv" / "Scripts" / executable,
        Path(site.getuserbase()) / "Scripts" / executable,
        Path(sys.executable).parent / "Scripts" / executable,
    )
    return str(next((path for path in candidates if path.is_file()), ""))

DATA_DIR = Path(os.getenv("YOUTUBE_DATA_DIR", str(SYSTEM_ROOT / "data")))
DB_PATH = Path(os.getenv("YOUTUBE_DB_PATH", str(DATA_DIR / "youtube_monitor.db")))
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
YOUTUBE_MAX_INITIAL_VIDEOS = int(os.getenv("YOUTUBE_MAX_INITIAL_VIDEOS", "100"))
YOUTUBE_PUSH_VERIFY_TOKEN = os.getenv("YOUTUBE_PUSH_VERIFY_TOKEN", "").strip()

WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base").strip() or "base"
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto").strip().lower() or "auto"
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "auto").strip().lower() or "auto"

# GPU-only applies to the heavy local AI/video stages. The web server, SQLite
# and process orchestration still use CPU because they are not GPU workloads.
# A production job must not silently fall back to a CPU implementation.
GPU_ONLY = os.getenv("YOUTUBE_GPU_ONLY", "1").strip().lower() in {"1", "true", "yes", "on"}
GPU_DEVICE_INDEX = os.getenv("CUDA_DEVICE", "0").strip() or "0"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5").strip() or "claude-opus-5"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image").strip() or "gemini-3.1-flash-image"
GEMINI_VIDEO_MODEL = os.getenv("GEMINI_VIDEO_MODEL", "veo-3.1-lite-generate-preview").strip() or "veo-3.1-lite-generate-preview"

# Runway is the first cloud video generator adapter. Other providers can use
# the same scene-job contract without changing the project timeline schema.
RUNWAYML_API_SECRET = os.getenv("RUNWAYML_API_SECRET", "").strip()
RUNWAY_MODEL = os.getenv("RUNWAY_MODEL", "gen4.5").strip() or "gen4.5"
CODEX_CLI_PATH = _detect_codex_cli()
CODEX_BRIDGE_HOME = Path(
    os.getenv("LOCALAPPDATA", str(DATA_DIR / "local-app-data"))
) / "YouTubeAIFactory" / "codex_cli_profile"

CLAUDE_CODE_CLI_PATH = _detect_claude_code_cli()

ANTIGRAVITY_CLI_PATH = _detect_antigravity_cli()


def gflow_config() -> dict[str, str]:
    """Live Google Flow CLI settings managed from the local dashboard."""
    return {
        "path": _detect_gflow_cli(),
        "profile": integration_value("GFLOW_PROFILE", "default") or "default",
        # Empty means let gflow choose the safest/default model for the mode.
        "video_model": integration_value("GFLOW_VIDEO_MODEL"),
    }


AGENT_IDS = ("codex_cli", "claude_code_cli", "antigravity")
AGENT_STAGE_IDS = (
    "orchestration",
    "script",
    "storyboard",
    "image_generation",
    "video_generation",
    "quality_review",
)


def default_agent_assignments() -> dict[str, dict[str, object]]:
    primary = orchestrator_provider()
    fallback = [agent for agent in AGENT_IDS if agent != primary]
    return {
        stage: {
            "mode": "auto" if stage not in {"orchestration"} else "fixed",
            "executor": primary,
            "allowed_agents": list(AGENT_IDS),
            "fallback_agents": fallback,
            "reviewer": "auto" if stage != "quality_review" else fallback[0],
        }
        for stage in AGENT_STAGE_IDS
    }


def agent_assignments() -> dict[str, dict[str, object]]:
    """Return validated per-stage agent routing; malformed config is ignored."""
    defaults = default_agent_assignments()
    raw = integration_value("AI_STAGE_ASSIGNMENTS_JSON")
    if not raw:
        return defaults
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return defaults
    if not isinstance(parsed, dict):
        return defaults
    for stage in AGENT_STAGE_IDS:
        configured = parsed.get(stage)
        if not isinstance(configured, dict):
            continue
        mode = str(configured.get("mode") or defaults[stage]["mode"])
        if mode not in {"fixed", "auto", "fallback"}:
            mode = str(defaults[stage]["mode"])
        executor = str(configured.get("executor") or defaults[stage]["executor"])
        if executor not in AGENT_IDS:
            executor = str(defaults[stage]["executor"])
        allowed = [str(item) for item in configured.get("allowed_agents", []) if str(item) in AGENT_IDS]
        if not allowed:
            allowed = list(AGENT_IDS)
        fallbacks = [
            str(item) for item in configured.get("fallback_agents", [])
            if str(item) in AGENT_IDS and str(item) != executor
        ]
        reviewer = str(configured.get("reviewer") or defaults[stage]["reviewer"])
        if reviewer not in {*AGENT_IDS, "auto"}:
            reviewer = "auto"
        defaults[stage] = {
            "mode": mode,
            "executor": executor,
            "allowed_agents": list(dict.fromkeys(allowed)),
            "fallback_agents": list(dict.fromkeys(fallbacks)),
            "reviewer": reviewer,
        }
    return defaults


def agent_assignment(stage: str) -> dict[str, object]:
    assignments = agent_assignments()
    return assignments.get(stage, assignments["orchestration"])


def orchestrator_provider() -> str:
    """Return the selected cloud agent reached through its logged-in local client.

    This is a function, rather than an import-time constant, so switching among
    Codex CLI, Claude Code CLI, and Antigravity takes effect without restarting
    the app.
    """
    return integration_value("AI_ORCHESTRATOR_PROVIDER", "codex_cli") or "codex_cli"

GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
GOOGLE_OAUTH_REDIRECT_URI = (
    os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://127.0.0.1:8787/oauth/youtube/callback").strip()
)
OAUTH_TOKEN_PATH = DATA_DIR / "oauth_token.json"

# Deliberate, single-video, manual download for re-editing (reaction/commentary videos
# with the user's own added footage and voiceover) — never used by any automatic/batch
# pipeline. See 03_TAI_LIEU/KE_HOACH_DU_AN.md (muc 19) for the policy this changes.
VIDEO_DOWNLOAD_DIR = Path(os.getenv("VIDEO_DOWNLOAD_DIR", str(PROJECT_ROOT / "02_NGUYEN_LIEU" / "tai_ve")))

# Production adapters. Empty commands keep the workflow in safe dry-run mode;
# configure command templates only after the local tools are installed.
PRODUCTION_ARTIFACT_DIR = Path(os.getenv("PRODUCTION_ARTIFACT_DIR", str(PROJECT_ROOT / "01_DU_AN")))
OPENMONTAGE_ROOT = Path(
    os.getenv(
        "OPENMONTAGE_ROOT",
        str(PROJECT_ROOT / "_THU_NGHIEM" / "OpenMontage"),
    )
).expanduser()
_openmontage_default_python = OPENMONTAGE_ROOT / ".venv" / "Scripts" / "python.exe"
OPENMONTAGE_PYTHON = os.getenv(
    "OPENMONTAGE_PYTHON",
    str(_openmontage_default_python),
).strip()
OPENMONTAGE_RENDER_RUNTIME = (
    os.getenv("OPENMONTAGE_RENDER_RUNTIME", "ffmpeg").strip().lower() or "ffmpeg"
)
OPENMONTAGE_TIMEOUT_SECONDS = int(os.getenv("OPENMONTAGE_TIMEOUT_SECONDS", "3600"))
PYVIDEOTRANS_ROOT = Path(os.getenv("PYVIDEOTRANS_ROOT", str(PROJECT_ROOT.parent / "pyVideoTrans")))
_uv_default = shutil.which("uv") or str(
    Path(site.getuserbase()) / "Scripts" / ("uv.exe" if os.name == "nt" else "uv")
)
_pyvideotrans_detected = (PYVIDEOTRANS_ROOT / "cli.py").is_file()
_pyvideotrans_venv_python = PYVIDEOTRANS_ROOT / ".venv" / "Scripts" / "python.exe"
_uv_available = Path(_uv_default).is_file()
PYVIDEOTRANS_WORKDIR = os.getenv(
    "PYVIDEOTRANS_WORKDIR",
    str(PYVIDEOTRANS_ROOT) if _pyvideotrans_detected else "",
).strip()
_pyvideotrans_default_command = (
    f'"{_uv_default}" run cli.py --task tts --name "{{srt_file}}" --cuda '
    '--tts_type {tts_type} --voice_role "{voice_role}" '
    '--target_language_code {language} --output-dir "{output_dir}"'
    if _pyvideotrans_detected and _uv_available
    else (
        f'"{_pyvideotrans_venv_python}" cli.py --task tts --name "{{srt_file}}" --cuda '
        '--tts_type {tts_type} --voice_role "{voice_role}" '
        '--target_language_code {language} --output-dir "{output_dir}"'
        if _pyvideotrans_detected and _pyvideotrans_venv_python.is_file()
        else ""
    )
)
PYVIDEOTRANS_COMMAND = os.getenv("PYVIDEOTRANS_COMMAND", _pyvideotrans_default_command).strip()
PYVIDEOTRANS_VOICE_ROLE = os.getenv("PYVIDEOTRANS_VOICE_ROLE", "vi-VN-HoaiMyNeural").strip() or "vi-VN-HoaiMyNeural"
PYVIDEOTRANS_TTS_TYPE = os.getenv("PYVIDEOTRANS_TTS_TYPE", "0").strip() or "0"


def _pyvideotrans_cuda_ready() -> bool:
    if not _pyvideotrans_venv_python.is_file():
        return False
    try:
        probe = subprocess.run(
            [
                str(_pyvideotrans_venv_python),
                "-c",
                "import torch; assert hasattr(torch, 'cuda'); assert torch.cuda.is_available()",
            ],
            cwd=str(PYVIDEOTRANS_ROOT),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


PYVIDEOTRANS_CUDA_READY = _pyvideotrans_cuda_ready()
PYVIDEOTRANS_RUNTIME_READY = bool(
    PYVIDEOTRANS_COMMAND
    and (not PYVIDEOTRANS_WORKDIR or (PYVIDEOTRANS_ROOT / ".venv" / "Scripts" / "python.exe").is_file())
    and (not PYVIDEOTRANS_WORKDIR or (PYVIDEOTRANS_ROOT / ".venv" / "Lib" / "site-packages" / "edge_tts").is_dir())
    and PYVIDEOTRANS_CUDA_READY
)

VOXCPM_PYTHON = Path(
    os.getenv("VOXCPM_PYTHON", str(_pyvideotrans_venv_python))
).expanduser()
VOXCPM_RUNNER = Path(
    os.getenv("VOXCPM_RUNNER", str(Path(__file__).with_name("voxcpm_runner.py")))
).expanduser()
VOXCPM_MODEL = os.getenv("VOXCPM_MODEL", "openbmb/VoxCPM2").strip() or "openbmb/VoxCPM2"
VOXCPM_DEVICE = os.getenv("VOXCPM_DEVICE", "cuda").strip() or "cuda"
VOXCPM_REFERENCE_AUDIO = os.getenv("VOXCPM_REFERENCE_AUDIO", "").strip()
VOXCPM_PROMPT_TEXT = os.getenv("VOXCPM_PROMPT_TEXT", "").strip()


def _voxcpm_runtime_ready() -> bool:
    if not VOXCPM_PYTHON.is_file() or not VOXCPM_RUNNER.is_file() or not VOXCPM_DEVICE.startswith("cuda"):
        return False
    try:
        probe = subprocess.run(
            [
                str(VOXCPM_PYTHON),
                "-c",
                "import soundfile as sf; sf.SoundFileRuntimeError = getattr(sf, 'SoundFileRuntimeError', RuntimeError); import torch, voxcpm; assert torch.cuda.is_available()",
            ],
            cwd=str(PYVIDEOTRANS_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


VOXCPM_RUNTIME_READY = _voxcpm_runtime_ready()
# Edge TTS is a lightweight fallback for voiceover. It is shipped inside the
# pyVideoTrans virtual environment but does not import pyVideoTrans/PyTorch.
EDGE_TTS_PYTHON = Path(os.getenv("EDGE_TTS_PYTHON", str(_pyvideotrans_venv_python)))
_edge_tts_default_command = (
    f'"{EDGE_TTS_PYTHON}" -m edge_tts --file "{{text_file}}" '
    '--voice "{voice_role}" --rate "{voice_rate}" --write-media "{output_file}"'
    if EDGE_TTS_PYTHON.is_file()
    else ""
)
EDGE_TTS_COMMAND = os.getenv("EDGE_TTS_COMMAND", _edge_tts_default_command).strip()
EDGE_TTS_RUNTIME_READY = bool(EDGE_TTS_COMMAND and EDGE_TTS_PYTHON.is_file())
FFMPEG_RENDER_COMMAND = os.getenv("FFMPEG_RENDER_COMMAND", "").strip()
FFMPEG_BINARY = os.getenv("FFMPEG_BINARY", "ffmpeg").strip() or "ffmpeg"
LOCAL_ASSET_MAX_BYTES = int(os.getenv("LOCAL_ASSET_MAX_BYTES", str(2 * 1024 * 1024 * 1024)))

DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
PRODUCTION_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
