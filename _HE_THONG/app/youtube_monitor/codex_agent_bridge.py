"""Codex CLI as the orchestrating agent - not as the structured worker.

codex_bridge.call_codex_json stays exactly as it is: one prompt, one JSON,
read-only, no tools, no user config. This runs the same CLI, same account,
for a different job: it is handed the app's MCP server and a goal, and loops
on its own - call a tool, read the result or the error, choose the next call -
until it can report.

Its hands are only the app's tools. The sandbox stays read-only, user config
(and with it every other MCP server and plugin on this machine) stays ignored,
and the MCP server runs in agent-run mode (see agent_runtime).
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
from .codex_bridge import _local_codex_environment, _strict_output_schema, codex_cli_status

RUNTIME = "codex_cli"
# Long steps (writing a script, planning scenes) run inside one tool call.
TOOL_TIMEOUT_SECONDS = 1500


def _toml_literal(value: str) -> str:
    text = str(value)
    if "'" in text or "\n" in text:
        raise AgentRunError(RUNTIME, f"Không truyền được giá trị này vào cấu hình Codex: {text[:80]}")
    return f"'{text}'"


def _toml_inline_server(spec: dict[str, Any]) -> str:
    env = ", ".join(f"{key}={_toml_literal(value)}" for key, value in sorted(spec["env"].items()))
    args = ", ".join(_toml_literal(item) for item in spec["args"])
    return (
        "{"
        f"command={_toml_literal(spec['command'])}, args=[{args}], env={{{env}}}, "
        f"startup_timeout_sec=60, tool_timeout_sec={TOOL_TIMEOUT_SECONDS}"
        "}"
    )


def build_command(
    executable: str,
    *,
    workdir: Path,
    schema_path: Path,
    output_path: Path,
    mcp_env: dict[str, str],
    effort: str = "high",
) -> list[str]:
    server = _toml_inline_server(mcp_server_spec(mcp_env))
    return [
        executable,
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "-c",
        f'model_reasoning_effort="{effort}"',
        "-c",
        f"mcp_servers.{MCP_SERVER_NAME}={server}",
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output_path),
        # Not the repository: nothing to read there, and its AGENTS.md is
        # written for engineers, not for whoever directs a video.
        "-C",
        str(workdir),
        "-",
    ]


def run(
    prompt: str,
    mcp_env: dict[str, str],
    *,
    instructions: str = "",
    timeout_seconds: int = 3600,
    effort: str = "high",
) -> AgentRun:
    status = codex_cli_status()
    if not status.get("logged_in"):
        raise AgentRunError(RUNTIME, str(status.get("detail") or "Codex CLI chưa đăng nhập"))
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="yt-codex-agent-") as directory:
        workdir = Path(directory)
        schema_path = workdir / "report.schema.json"
        output_path = workdir / "report.json"
        schema_path.write_text(json.dumps(_strict_output_schema(REPORT_SCHEMA), ensure_ascii=False), encoding="utf-8")
        command = build_command(
            str(status["path"]), workdir=workdir, schema_path=schema_path,
            output_path=output_path, mcp_env=mcp_env, effort=effort,
        )
        text = f"{instructions}\n\n{prompt}" if instructions else prompt
        try:
            process = operations.run_cancellable(
                command, timeout=timeout_seconds, cwd=str(workdir),
                env=_local_codex_environment(), input_text=text,
            )
        except Exception as exc:  # timeout, cancel, OS error: the brain did not finish
            raise AgentRunError(RUNTIME, f"Codex agent không chạy xong: {exc}") from exc
        tail = redact(((process.stderr or "") + (process.stdout or ""))[-3000:])
        if process.returncode != 0:
            raise AgentRunError(RUNTIME, f"Codex agent thoát mã {process.returncode}: {tail[-1200:]}")
        final = output_path.read_text(encoding="utf-8").strip() if output_path.is_file() else ""
    return AgentRun(
        runtime=RUNTIME,
        report=coerce_report(final, fallback_text=tail),
        seconds=round(time.monotonic() - started, 1),
        raw_tail=tail[-1500:],
        meta=header_meta(process.stderr or ""),
    )


def header_meta(stderr: str) -> dict[str, Any]:
    """Model and reasoning effort as Codex printed them, for the run log."""
    meta: dict[str, Any] = {}
    for line in stderr.splitlines()[:40]:
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key == "model" and value.strip():
            meta["model"] = value.strip()
        elif key == "reasoning effort" and value.strip():
            meta["reasoning_effort"] = value.strip()
    return meta
