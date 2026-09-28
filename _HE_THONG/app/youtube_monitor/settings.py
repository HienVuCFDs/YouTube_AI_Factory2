from __future__ import annotations

import json
import os
import shutil
import site
import subprocess
import sys
import time
import threading
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
    "AI_ORCHESTRATOR_FALLBACK_PROVIDER",
    "AI_STAGE_ASSIGNMENTS_JSON",
    "AUTOMATION_POLICY_JSON",
    "ASTRA_MCP_TUNNEL_ID",
    "CHATGPT_MCP_TUNNEL_ID",
    "GFLOW_CLI_PATH",
    "GFLOW_PROFILE",
    "GFLOW_VIDEO_MODEL",
    "PHANTOM_CANVAS_URL",
    "GOOGLE_TTS_API_KEY",
    "GOOGLE_TTS_VOICE",
    "PIPER_BINARY",
    "PIPER_MODEL",
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


def google_tts_config() -> tuple[str, str]:
    """The Google TTS key and voice. The key is returned only to the caller
    about to speak with it, never through the settings API."""
    return integration_value("GOOGLE_TTS_API_KEY"), (
        integration_value("GOOGLE_TTS_VOICE") or GOOGLE_TTS_VOICE
    )


def piper_config() -> tuple[str, str]:
    """The piper binary and the .onnx model to speak with."""
    return (
        integration_value("PIPER_BINARY") or PIPER_BINARY,
        integration_value("PIPER_MODEL") or PIPER_MODEL,
    )


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

# `base` is the second smallest model, and on Vietnamese it mishears enough to
# change the meaning: "vu tru" came back as "vu chup", "he mat troi" as "he mat
# cho", "nguyen to hoa hoc" as "vinh tuu khoa hoc". The transcript is the raw
# material for every step after it, and a writer handed that repairs it by
# guessing - which reads perfectly well and is sometimes wrong. large-v3 costs
# about four extra seconds on a minute of audio and fixes all of the above.
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "large-v3").strip() or "large-v3"
# Tried in turn when the chosen model will not load, which on a small card
# means running out of memory. A smaller transcript is worth more than none.
WHISPER_MODEL_FALLBACKS: tuple[str, ...] = ("medium", "small", "base", "tiny")
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
        "image_model": integration_value("GFLOW_IMAGE_MODEL"),
    }


# The runtime has one active Orchestrator: the AI that directs a run, deciding
# which step comes next. Astra is the default when nothing is chosen.
ORCHESTRATOR_IDS = ("astra", "antigravity", "chatgpt_app", "claude_chat", "claude")
ORCHESTRATOR_FALLBACK_IDS = ("claude", "antigravity", "claude_chat", "chatgpt_app", "astra")

# The desktop chat apps (GPT Work, Claude Cowork). They reach the app over MCP
# and pull their own work; nothing here can call one and wait for an answer.
# So they can direct a run, but they cannot be the AI a step calls mid-way.
CHAT_AGENT_IDS = ("chatgpt_app", "claude_chat")

# Agent assignments are the user-facing routing policy for orchestration and
# specialist tasks. A concrete integration can still be unavailable at runtime;
# API routes expose readiness and the app enforces policy before execution.
AGENT_IDS = ("astra", "antigravity", "chatgpt_app", "claude_chat", "claude")
AGENT_STAGE_IDS = (
    "orchestration",
    "script",
    "storyboard",
    "image_generation",
    "video_generation",
    "quality_review",
)


# The agents were once named after the CLI that ran them. A saved assignment
# still speaks the old names, and dropping an unknown name as malformed left a
# stage allowed to use exactly one AI - usually not the one the user picked.
LEGACY_AGENT_IDS: dict[str, str] = {
    "codex_cli": "astra",
    "codex": "astra",
    "claude_code_cli": "claude",
    "claude_code": "claude",
    "claude_cli": "claude",
    "antigravity_cli": "antigravity",
    "chatgpt": "chatgpt_app",
}

# The one table from an agent (what the user assigns) to the runtime that
# executes it. Everything that needs "which CLI is Astra" asks runtime_for()
# (re-exported as orchestrator_runtime.runtime_id); no module keeps its own copy.
# Chat apps have no runtime here: they pull their own work over MCP.
AGENT_RUNTIME: dict[str, str] = {
    "astra": "codex_cli",
    "claude": "claude_code_cli",
    "antigravity": "antigravity",
}


def canonical_agent_id(agent: object) -> str:
    """Return the current id for an agent name, or "" if there is none."""
    name = str(agent or "").strip()
    name = LEGACY_AGENT_IDS.get(name, name)
    return name if name in AGENT_IDS else ""


def runtime_for(name: object) -> str:
    """The runtime behind an agent name; any other name comes back unchanged.

    Unknown names (openai_gpt, anthropic_claude, gflow_cli...) are returned as
    given so the caller can refuse them by name instead of having them quietly
    rewritten into a runtime nobody picked.
    """
    raw = str(name or "").strip().lower()
    agent = canonical_agent_id(raw)
    return AGENT_RUNTIME.get(agent, agent) if agent else raw


def default_agent_assignments() -> dict[str, dict[str, object]]:
    # A stage is the thinking a step does while it runs, which the app calls
    # and waits on. A chat app directing the run cannot be called that way, so
    # choosing one to direct must not also make it every stage's executor.
    primary = orchestrator_provider()
    fallback = orchestrator_fallback_provider()
    if primary in CHAT_AGENT_IDS:
        primary = "astra"
    if fallback in CHAT_AGENT_IDS:
        fallback = "claude"
    return {
        stage: {
            "mode": "auto",
            "executor": primary,
            "allowed_agents": list(AGENT_IDS),
            "fallback_agents": [fallback] if fallback != primary else [],
            "reviewer": "auto",
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
        executor = canonical_agent_id(configured.get("executor")) or str(defaults[stage]["executor"])
        allowed = [
            name for name in (canonical_agent_id(item) for item in configured.get("allowed_agents", []))
            if name
        ]
        if not allowed:
            allowed = list(AGENT_IDS)
        fallbacks = [
            name for name in (canonical_agent_id(item) for item in configured.get("fallback_agents", []))
            if name and name != executor
        ]
        reviewer = configured.get("reviewer") or defaults[stage]["reviewer"]
        reviewer = "auto" if str(reviewer) == "auto" else canonical_agent_id(reviewer) or "auto"
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


def default_automation_policy() -> dict[str, object]:
    """Safe defaults for unattended work.

    Paid API providers stay locked until the user explicitly enables them;
    subscriptions already paid for may be used. Publishing always remains a
    human decision even when every AI review passes.
    """
    return {
        "global_rules": "",
        "max_attempts": 2,
        "min_review_score": 8,
        "min_scene_qc_score": 7,
        "allow_paid_apis": False,
        "allow_subscription_media": True,
        "auto_generate_media": False,
        "auto_render": False,
        "require_final_approval": True,
        "pause_on_provider_exhaustion": True,
        "max_project_cost": 0.0,
        "max_daily_cost": 0.0,
    }


def automation_policy() -> dict[str, object]:
    """Return the validated dashboard-managed automation policy."""
    policy = default_automation_policy()
    raw = integration_value("AUTOMATION_POLICY_JSON")
    if not raw:
        return policy
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return policy
    if not isinstance(parsed, dict):
        return policy
    policy["global_rules"] = str(parsed.get("global_rules") or "")[:10_000]
    for key, minimum, maximum in (
        ("max_attempts", 1, 10),
        ("min_review_score", 0, 10),
        ("min_scene_qc_score", 0, 10),
    ):
        try:
            policy[key] = max(minimum, min(int(parsed.get(key, policy[key])), maximum))
        except (TypeError, ValueError):
            pass
    for key in ("max_project_cost", "max_daily_cost"):
        try:
            # 0 means "no ceiling". A negative ceiling would silently block
            # every provider, so it is rejected rather than clamped to zero.
            amount = float(parsed.get(key, policy[key]))
        except (TypeError, ValueError):
            continue
        if amount >= 0:
            policy[key] = round(min(amount, 1_000_000.0), 4)
    for key in (
        "allow_paid_apis",
        "allow_subscription_media",
        "auto_generate_media",
        "auto_render",
        "require_final_approval",
        "pause_on_provider_exhaustion",
    ):
        if key in parsed:
            policy[key] = bool(parsed[key])
    return policy


def orchestrator_provider() -> str:
    """Return the selected primary Orchestrator."""
    configured = integration_value("AI_ORCHESTRATOR_PROVIDER", "astra") or "astra"
    return configured if configured in ORCHESTRATOR_IDS else "astra"


def orchestrator_fallback_provider() -> str:
    """Return the configured fallback Orchestrator."""
    configured = integration_value("AI_ORCHESTRATOR_FALLBACK_PROVIDER", "claude") or "claude"
    return configured if configured in ORCHESTRATOR_FALLBACK_IDS else "claude"


def orchestrator_chat_agents() -> list[str]:
    """The desktop chat apps chosen to direct runs, primary first.

    Empty when the primary is a CLI: runs then stay with the in-app worker, as
    they did before a chat app could be picked. A CLI fallback behind a chat
    primary is left out too - a chat app that has been quiet for a while is
    usually idle, not gone, and handing its run to a CLI would put the CLI
    back in the director's seat without anyone choosing that.
    """
    primary = orchestrator_provider()
    if primary not in CHAT_AGENT_IDS:
        return []
    chosen = (primary, orchestrator_fallback_provider())
    return [agent for agent in dict.fromkeys(chosen) if agent in CHAT_AGENT_IDS]

GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
GOOGLE_OAUTH_REDIRECT_URI = (
    os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://127.0.0.1:8787/oauth/youtube/callback").strip()
)
OAUTH_TOKEN_PATH = DATA_DIR / "oauth_token.json"

# Deliberate, single-video, manual download for re-editing (reaction/commentary videos
# with the user's own added footage and voiceover) — never used by any automatic/batch
# pipeline. See _HE_THONG/tai_lieu/KE_HOACH_DU_AN.md (muc 19) for the policy this changes.
# Source footage belongs with the projects it feeds, not in a third
# top-level folder of its own.
VIDEO_DOWNLOAD_DIR = Path(os.getenv(
    "VIDEO_DOWNLOAD_DIR", str(PROJECT_ROOT / "01_DU_AN" / "_nguyen_lieu" / "tai_ve")
))

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
            text=True, encoding="utf-8", errors="replace",
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


# Do not import torch in a subprocess while importing the web server. Cold
# CUDA startup can take 20 seconds and is unrelated to opening the library.
PYVIDEOTRANS_CUDA_READY = False
PYVIDEOTRANS_RUNTIME_READY = False
_pyvideotrans_probe_at = 0.0
_pyvideotrans_probe_lock = threading.Lock()
_pyvideotrans_probe_thread_lock = threading.Lock()
_pyvideotrans_probe_thread: threading.Thread | None = None


def pyvideotrans_runtime_status(wait: bool = True) -> tuple[bool, bool]:
    global PYVIDEOTRANS_CUDA_READY, PYVIDEOTRANS_RUNTIME_READY
    global _pyvideotrans_probe_at, _pyvideotrans_probe_thread
    if _pyvideotrans_probe_at and (PYVIDEOTRANS_RUNTIME_READY or time.monotonic() - _pyvideotrans_probe_at < 60):
        return PYVIDEOTRANS_CUDA_READY, PYVIDEOTRANS_RUNTIME_READY
    if not wait:
        with _pyvideotrans_probe_thread_lock:
            if _pyvideotrans_probe_thread is None or not _pyvideotrans_probe_thread.is_alive():
                _pyvideotrans_probe_thread = threading.Thread(target=pyvideotrans_runtime_status, daemon=True)
                _pyvideotrans_probe_thread.start()
        return PYVIDEOTRANS_CUDA_READY, PYVIDEOTRANS_RUNTIME_READY
    with _pyvideotrans_probe_lock:
        if not _pyvideotrans_probe_at or (not PYVIDEOTRANS_RUNTIME_READY and time.monotonic() - _pyvideotrans_probe_at >= 60):
            PYVIDEOTRANS_CUDA_READY = _pyvideotrans_cuda_ready()
            PYVIDEOTRANS_RUNTIME_READY = bool(PYVIDEOTRANS_COMMAND and PYVIDEOTRANS_CUDA_READY
                and (not PYVIDEOTRANS_WORKDIR or (PYVIDEOTRANS_ROOT / ".venv" / "Lib" / "site-packages" / "edge_tts").is_dir()))
            _pyvideotrans_probe_at = time.monotonic()
    return PYVIDEOTRANS_CUDA_READY, PYVIDEOTRANS_RUNTIME_READY

VOXCPM_PYTHON = Path(
    os.getenv("VOXCPM_PYTHON", str(_pyvideotrans_venv_python))
).expanduser()
VOXCPM_RUNNER = Path(
    os.getenv("VOXCPM_RUNNER", str(Path(__file__).with_name("voxcpm_runner.py")))
).expanduser()
# Edge ships exactly two Vietnamese voices, so every video a Vietnamese
# channel makes is narrated by one of the same two. These are the ways out.
GOOGLE_TTS_VOICE = os.getenv("GOOGLE_TTS_VOICE", "vi-VN-Neural2-A").strip() or "vi-VN-Neural2-A"
PIPER_BINARY = os.getenv("PIPER_BINARY", "piper").strip() or "piper"
PIPER_MODEL = os.getenv("PIPER_MODEL", "").strip()

VOXCPM_MODEL = os.getenv("VOXCPM_MODEL", "openbmb/VoxCPM2").strip() or "openbmb/VoxCPM2"
VOXCPM_DEVICE = os.getenv("VOXCPM_DEVICE", "cuda").strip() or "cuda"
VOXCPM_REFERENCE_AUDIO = os.getenv("VOXCPM_REFERENCE_AUDIO", "").strip()
VOXCPM_PROMPT_TEXT = os.getenv("VOXCPM_PROMPT_TEXT", "").strip()


# Loading torch and waking CUDA takes about five seconds once the files are in
# the page cache, and far longer on a cold disk - which is exactly the state
# the machine is in when the app is started from its .bat right after boot.
_VOXCPM_PROBE_TIMEOUT_SECONDS = 180
# A failure is worth asking about again: the usual cause is a slow first
# import, not a missing install, and freezing that answer for the life of the
# process meant the only cure was restarting the app.
_VOXCPM_RETRY_AFTER_SECONDS = 60

_voxcpm_probe: tuple[float, bool, str] | None = None
_voxcpm_probe_lock = threading.Lock()
_voxcpm_probe_thread_lock = threading.Lock()
_voxcpm_probe_thread: threading.Thread | None = None


def _run_voxcpm_probe() -> tuple[bool, str]:
    """Whether VoxCPM can run here, and if not, what actually stopped it."""
    for label, path in (("Python cua pyVideoTrans", VOXCPM_PYTHON), ("voxcpm_runner.py", VOXCPM_RUNNER)):
        if not path.is_file():
            return False, f"Không tìm thấy {label}: {path}"
    if not VOXCPM_DEVICE.startswith("cuda"):
        return False, f"VOXCPM_DEVICE đang là '{VOXCPM_DEVICE}'; VoxCPM ở đây chỉ chạy trên CUDA"
    try:
        probe = subprocess.run(
            [
                str(VOXCPM_PYTHON),
                "-c",
                "import soundfile as sf; sf.SoundFileRuntimeError = getattr(sf, 'SoundFileRuntimeError', RuntimeError); import torch, voxcpm; assert torch.cuda.is_available()",
            ],
            cwd=str(PYVIDEOTRANS_ROOT),
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=_VOXCPM_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, (
            f"Phép thử VoxCPM quá {_VOXCPM_PROBE_TIMEOUT_SECONDS}s. "
            "Thường là lần nạp torch/CUDA đầu tiên sau khi bật máy; thử lại sau một phút."
        )
    except OSError as exc:
        return False, f"Không chạy được phép thử VoxCPM: {exc}"
    if probe.returncode == 0:
        return True, ""
    detail = (probe.stderr or probe.stdout or "").strip().splitlines()
    return False, detail[-1] if detail else f"Phép thử VoxCPM thoát với mã {probe.returncode}"


def voxcpm_runtime_status(force: bool = False, *, wait: bool = True) -> tuple[bool, str]:
    """Cached answer to "can VoxCPM run", with the reason when it cannot."""
    global _voxcpm_probe, _voxcpm_probe_thread
    now = time.monotonic()
    if not force and _voxcpm_probe is not None:
        checked_at, ready, detail = _voxcpm_probe
        if ready or now - checked_at < _VOXCPM_RETRY_AFTER_SECONDS:
            return ready, detail
    if not wait:
        with _voxcpm_probe_thread_lock:
            if _voxcpm_probe_thread is None or not _voxcpm_probe_thread.is_alive():
                _voxcpm_probe_thread = threading.Thread(target=voxcpm_runtime_status, daemon=True)
                _voxcpm_probe_thread.start()
        return (_voxcpm_probe[1], _voxcpm_probe[2]) if _voxcpm_probe else (False, "Đang kiểm tra VoxCPM/CUDA trong nền")
    with _voxcpm_probe_lock:
        if not force and _voxcpm_probe is not None:
            checked_at, ready, detail = _voxcpm_probe
            if ready or time.monotonic() - checked_at < _VOXCPM_RETRY_AFTER_SECONDS:
                return ready, detail
        ready, detail = _run_voxcpm_probe()
        _voxcpm_probe = (time.monotonic(), ready, detail)
        return ready, detail


def voxcpm_runtime_ready() -> bool:
    return voxcpm_runtime_status()[0]
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
