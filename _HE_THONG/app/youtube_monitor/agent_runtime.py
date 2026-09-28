"""What the two orchestrating agents share: how they reach the app, what they report.

codex_bridge / claude_code_bridge call a model as a structured worker: one
prompt, one JSON answer, no tools. That restriction is deliberate and stays.
Directing a run is a different job - look at the project, act, read what
happened, act again - so it gets its own runtime: codex_agent_bridge and
claude_agent_bridge, whose only hands are the app's own MCP server
(ai_desktop_mcp.py). No shell, no browser, no clicking the interface.

The MCP server is started by the CLI itself, with environment variables that
put it in "agent run" mode: calls are logged for the supervising loop, a call
that already failed is not repeated while the project is unchanged, spending is
refused unless the run allows it, and the tool budget of a round is enforced.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import usage_limits

MCP_SERVER_NAME = "youtube_ai_factory"
BRIDGE_SCRIPT = Path(__file__).resolve().parent / "ai_desktop_mcp.py"

# The agent's closing report. The app does not take it on trust - completion is
# decided by reading the project - but the report is what the next round and
# the person reading the log learn from.
REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["done", "blocked", "partial"]},
        "summary": {"type": "string"},
        "completed_steps": {"type": "array", "items": {"type": "string"}},
        "attempts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"action": {"type": "string"}, "outcome": {"type": "string"}},
                "required": ["action", "outcome"],
                "additionalProperties": False,
            },
        },
        "blocked_reason": {"type": "string"},
    },
    "required": ["status", "summary", "completed_steps", "attempts", "blocked_reason"],
    "additionalProperties": False,
}


class AgentRunError(RuntimeError):
    """The agent runtime itself failed: not signed in, out of quota, crashed.

    Distinct from a tool failing inside a run, which the agent sees and works
    around. This one means the brain was not available at all, so the loop
    moves on to another runtime instead of asking this one again.
    """

    def __init__(self, runtime: str, message: str):
        super().__init__(redact(message))
        self.runtime = runtime
        self.usage_limit = usage_limits.is_usage_limit(message)


@dataclass
class AgentRun:
    runtime: str
    report: dict[str, Any]
    seconds: float = 0.0
    turns: int | None = None
    cost_usd: float | None = None
    raw_tail: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


def mcp_environment(
    *,
    run_log: Path,
    round_number: int,
    project_id: int,
    allow_spend: bool,
    tool_budget: int,
    factory_url: str,
    allow_overwrite: bool = False,
) -> dict[str, str]:
    """Environment that puts the app's MCP server into agent-run mode."""
    return {
        "YOUTUBE_FACTORY_URL": factory_url,
        "YOUTUBE_AGENT_RUN_LOG": str(run_log),
        "YOUTUBE_AGENT_ROUND": str(int(round_number)),
        "YOUTUBE_AGENT_PROJECT_ID": str(int(project_id)),
        "YOUTUBE_AGENT_ALLOW_SPEND": "1" if allow_spend else "0",
        "YOUTUBE_AGENT_ALLOW_OVERWRITE": "1" if allow_overwrite else "0",
        "YOUTUBE_AGENT_TOOL_BUDGET": str(int(tool_budget)),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }


def mcp_server_spec(env: dict[str, str]) -> dict[str, Any]:
    """The stdio server entry both CLIs understand (command, args, env)."""
    return {"command": sys.executable, "args": [str(BRIDGE_SCRIPT)], "env": dict(env)}


_SECRETS = re.compile(
    r"(sk-[A-Za-z0-9_\-]{12,}"                       # OpenAI / Anthropic style keys
    r"|AIza[0-9A-Za-z_\-]{20,}"                        # Google API keys
    r"|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"  # JWTs
    r"|(?i:bearer)\s+[A-Za-z0-9._\-]{16,}"
    r"|(?i:(?:api[_-]?key|token|secret|password)\s*[=:]\s*)[^\s\"',;]{8,})"
)


def redact(text: Any) -> str:
    """The same text with anything shaped like a credential blanked out.

    Run logs keep CLI output and tool results so a failed run can be read
    afterwards; they must never become a place a key can be read from.
    """
    return _SECRETS.sub("[đã ẩn]", str(text or ""))


def coerce_report(value: Any, fallback_text: str = "") -> dict[str, Any]:
    """Whatever the agent ended with, as a report the loop can read.

    A missing or malformed report is itself information - the agent stopped
    without saying what it did - so it becomes a "partial" report carrying
    the tail of what it did say, never an invented "done".
    """
    if isinstance(value, str):
        value = _last_json_object(value)
    if not isinstance(value, dict):
        return {
            "status": "partial",
            "summary": (fallback_text or "Agent kết thúc mà không trả báo cáo.")[-1500:],
            "completed_steps": [],
            "attempts": [],
            "blocked_reason": "",
        }
    status = str(value.get("status") or "partial").strip().lower()
    return {
        "status": status if status in {"done", "blocked", "partial"} else "partial",
        "summary": str(value.get("summary") or "")[:4000],
        "completed_steps": [str(item) for item in (value.get("completed_steps") or []) if str(item).strip()],
        "attempts": [
            {"action": str(item.get("action") or ""), "outcome": str(item.get("outcome") or "")}
            for item in (value.get("attempts") or []) if isinstance(item, dict)
        ][:40],
        "blocked_reason": str(value.get("blocked_reason") or "")[:2000],
    }


def _last_json_object(text: str) -> Any:
    cleaned = str(text or "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for match in reversed(list(re.finditer(r"\{", cleaned))):
        try:
            value, _ = decoder.raw_decode(cleaned, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "status" in value:
            return value
    return None
