"""Claude Code CLI as the orchestrating agent - not as the structured worker.

claude_code_bridge.call_claude_code_json stays exactly as it is (`--tools ""`,
one answer). This runs the same CLI, same login, with one set of hands only:
the app's MCP server. Everything else is closed off:

- `--restricted`: no command-running tools, no WebFetch, user/project settings
  ignored, bypassPermissions refused;
- `--tools ""`: no built-in tools at all;
- `--strict-mcp-config`: only the app's server, not whatever else is configured;
- `--permission-mode dontAsk` + `--allowedTools mcp__youtube_ai_factory`:
  the app's tools run without a prompt nobody is there to answer, anything
  else is refused.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from . import operations
from .agent_runtime import (
    MCP_SERVER_NAME,
    REPORT_SCHEMA,
    AgentRun,
    AgentRunError,
    coerce_report,
    mcp_server_spec,
    redact,
)
from .claude_code_bridge import _local_claude_environment, claude_code_cli_status

RUNTIME = "claude_code_cli"
TOOL_TIMEOUT_MS = 1_500_000


def build_command(
    executable: str,
    *,
    mcp_config_path: Path,
    instructions: str,
    max_turns: int,
    model: str = "",
) -> list[str]:
    command = [
        executable,
        "-p",
        "--output-format", "json",
        "--restricted",
        "--tools", "",
        "--strict-mcp-config",
        "--mcp-config", str(mcp_config_path),
        "--permission-mode", "dontAsk",
        "--allowedTools", f"mcp__{MCP_SERVER_NAME}",
        "--json-schema", json.dumps(REPORT_SCHEMA, ensure_ascii=False),
        "--max-turns", str(int(max_turns)),
    ]
    if instructions:
        command += ["--append-system-prompt", instructions]
    if model:
        command += ["--model", model]
    return command


def parse_output(stdout: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(report, meta) from `claude -p --output-format json`."""
    try:
        envelope = json.loads(stdout.strip() or "{}")
    except json.JSONDecodeError:
        return coerce_report(stdout, fallback_text=stdout), {}
    if not isinstance(envelope, dict):
        return coerce_report(None, fallback_text=stdout), {}
    meta = {
        key: envelope.get(key)
        for key in ("subtype", "is_error", "num_turns", "total_cost_usd", "duration_ms")
        if key in envelope
    }
    usage = envelope.get("modelUsage")
    if isinstance(usage, dict) and usage:
        # Which model actually answered, as Claude Code reports it.
        meta["model"] = ", ".join(sorted(str(name) for name in usage))
    structured = envelope.get("structured_output")
    if isinstance(structured, dict):
        return coerce_report(structured), meta
    return coerce_report(envelope.get("result"), fallback_text=str(envelope.get("result") or "")), meta


def run(
    prompt: str,
    mcp_env: dict[str, str],
    *,
    instructions: str = "",
    timeout_seconds: int = 3600,
    max_turns: int = 60,
    model: str = "",
) -> AgentRun:
    status = claude_code_cli_status()
    if not status.get("logged_in"):
        raise AgentRunError(RUNTIME, str(status.get("detail") or "Claude Code CLI chưa đăng nhập"))
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="yt-claude-agent-") as directory:
        workdir = Path(directory)
        config_path = workdir / "mcp.json"
        config_path.write_text(
            json.dumps({"mcpServers": {MCP_SERVER_NAME: mcp_server_spec(mcp_env)}}, ensure_ascii=False),
            encoding="utf-8",
        )
        command = build_command(
            str(status["path"]), mcp_config_path=config_path, instructions=instructions,
            max_turns=max_turns, model=model,
        )
        environment = _local_claude_environment()
        environment["MCP_TOOL_TIMEOUT"] = str(TOOL_TIMEOUT_MS)
        environment["MCP_TIMEOUT"] = "60000"
        try:
            process = operations.run_cancellable(
                command, timeout=timeout_seconds, cwd=str(workdir), env=environment, input_text=prompt,
            )
        except Exception as exc:
            raise AgentRunError(RUNTIME, f"Claude agent không chạy xong: {exc}") from exc
    stdout = process.stdout or ""
    report, meta = parse_output(stdout)
    tail = redact(((process.stderr or "") + stdout)[-3000:])
    if process.returncode != 0 and not meta:
        raise AgentRunError(RUNTIME, f"Claude agent thoát mã {process.returncode}: {tail[-1200:]}")
    if meta.get("is_error") and meta.get("subtype") not in {"error_max_turns"}:
        # A run that hit its turn limit still did work worth reading; any
        # other error means the brain itself failed (quota, auth, crash).
        raise AgentRunError(RUNTIME, f"Claude agent báo lỗi ({meta.get('subtype')}): {tail[-1200:]}")
    return AgentRun(
        runtime=RUNTIME,
        report=report,
        seconds=round(time.monotonic() - started, 1),
        turns=meta.get("num_turns"),
        cost_usd=meta.get("total_cost_usd"),
        raw_tail=tail[-1500:],
        meta=meta,
    )
