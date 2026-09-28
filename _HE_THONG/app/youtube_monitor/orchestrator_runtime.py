"""Which AI can really run a step now, and what actually ran.

The app stores the user's choice by product name - Astra, ChatGPT app, Claude
Chat, Claude - while a step is executed by a concrete runtime that has to be
installed, logged in, or key-configured on this machine. Two end-to-end runs
failed on exactly that gap: the storyboard stage found none of its allowed
agents callable, quietly produced a local template plan, and that plan was
then reported as AI Orchestrator work.

So two things live here:

- a readiness gate that asks each runtime whether it can execute *now* and,
  when it cannot, says which sign-in or key is missing. A saved setting or a
  configured tunnel id is never treated as readiness;
- the shape of the audit trail, because a run is only believable if every
  step names the runtime that did it, why that one was chosen, what came out,
  and whether a fallback stood in for the AI.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from . import chat_agent_presence, settings, usage_limits
from .antigravity_bridge import antigravity_cli_status
from .claude_code_bridge import claude_code_cli_status
from .codex_bridge import codex_cli_status


# The product-level names the UI stores, mapped onto the runtime that can
# actually be called.
#
# Astra is a Codex model - `codex exec` reports `model: gpt-6-astra` - and not
# an Antigravity one: `agy models` lists Gemini, Claude and GPT-OSS, with no
# Astra among them. Mapping Astra onto Antigravity therefore sent every Astra
# step to a different vendor's model, and left the Gemini CLI with no name of
# its own in the UI at all.
#
# `chatgpt_app` means the ChatGPT desktop app, reached over MCP. It has no
# local runtime: the app cannot call a chat subscription like an API, so that
# choice stays uncallable until the MCP tunnel is live, rather than quietly
# running Codex and reporting it as ChatGPT.
# The runtimes the in-app JSON executor can call directly.
CALLABLE_RUNTIMES: tuple[str, ...] = ("codex_cli", "claude_code_cli", "antigravity")

# Derived from settings.AGENT_RUNTIME, the single table; kept for display
# (/api/orchestrator/runtimes lists it). Nothing decides from this copy.
AGENT_RUNTIMES: dict[str, str] = {
    name: settings.runtime_for(name)
    for name in (*settings.AGENT_RUNTIME, *settings.LEGACY_AGENT_IDS, *CALLABLE_RUNTIMES)
    if settings.runtime_for(name) in CALLABLE_RUNTIMES
}

# Writing the new script is the one step the plan pins an order to: a paid
# API key first when the user has configured one, then the subscriptions.
WRITER_PREFERENCE: tuple[str, ...] = (
    "openai_gpt",
    "codex_cli",
    "claude_code_cli",
    "antigravity",
    "anthropic_claude",
)

_DESCRIPTORS: tuple[dict[str, Any], ...] = (
    {
        "id": "openai_gpt",
        "label": "GPT (OpenAI API)",
        "kind": "api_key",
        "serves": ("openai_gpt",),
        "can_write": True,
        "can_orchestrate": False,
    },
    {
        "id": "antigravity",
        "label": "Antigravity CLI (Gemini)",
        "kind": "cli_subscription",
        "serves": ("antigravity",),
        "can_write": True,
        "can_orchestrate": True,
    },
    {
        "id": "claude_code_cli",
        "label": "Claude Code / API",
        "kind": "cli_subscription",
        "serves": ("claude",),
        "can_write": True,
        "can_orchestrate": True,
    },
    {
        "id": "codex_cli",
        "label": "Codex CLI (Astra · gpt-6-astra)",
        "kind": "cli_subscription",
        "serves": ("astra",),
        "can_write": True,
        "can_orchestrate": True,
    },
    {
        "id": "anthropic_claude",
        "label": "Claude (Anthropic API)",
        "kind": "api_key",
        "serves": ("claude",),
        "can_write": True,
        "can_orchestrate": False,
    },
    {
        "id": "chatgpt_app_mcp",
        "label": "ChatGPT Chat qua MCP",
        "kind": "chat_mcp",
        "serves": ("chatgpt_app",),
        "can_write": False,
        "can_orchestrate": False,
    },
    {
        "id": "claude_chat_mcp",
        "label": "Claude Chat qua MCP",
        "kind": "chat_mcp",
        "serves": ("claude_chat",),
        "can_write": False,
        "can_orchestrate": False,
    },
)


def runtime_id(agent: str) -> str:
    """Map a product-level agent choice onto the runtime that executes it.

    The boundary every module goes through (it reads settings.AGENT_RUNTIME).
    An unknown name is returned unchanged so the caller can reject it, rather
    than being silently rewritten into a runtime the user never picked.
    """
    return settings.runtime_for(agent)


def _cli_state(status: dict[str, Any], missing_detail: str) -> dict[str, Any]:
    installed = bool(status.get("installed"))
    logged_in = bool(status.get("logged_in"))
    detail = str(status.get("detail") or "").strip()
    if logged_in:
        return {"ready": True, "blocked_reason": "", "detail": detail or "Đã đăng nhập, sẵn sàng chạy."}
    if installed:
        return {
            "ready": False,
            "blocked_reason": "missing_login",
            "detail": detail or "CLI đã cài nhưng chưa đăng nhập.",
        }
    return {"ready": False, "blocked_reason": "not_installed", "detail": detail or missing_detail}


# The CLI status probes, named so a caller can hand in its own - the app
# already holds these functions and patches them in tests, and readiness has
# to agree with the routing decision made a few lines earlier, not re-measure
# it through a different door.
def default_cli_statuses() -> dict[str, Callable[[], dict[str, Any]]]:
    return {
        "antigravity": antigravity_cli_status,
        "claude_code_cli": claude_code_cli_status,
        "codex_cli": codex_cli_status,
    }


_CLI_MISSING = {
    "antigravity": "Không tìm thấy Antigravity CLI (agy) trên máy.",
    "claude_code_cli": "Không tìm thấy Claude Code CLI trên máy.",
    "codex_cli": "Không tìm thấy Codex CLI trên máy.",
}


def _probe(
    descriptor: dict[str, Any],
    statuses: dict[str, Callable[[], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Ask one runtime whether it can execute right now."""
    key = str(descriptor.get("id") or "")
    statuses = statuses or default_cli_statuses()
    if key in statuses:
        return _cli_state(statuses[key](), _CLI_MISSING.get(key, "Chưa cài runtime này."))
    if key == "openai_gpt":
        api_key, model = settings.openai_config()
        return {
            "ready": bool(api_key),
            "blocked_reason": "" if api_key else "missing_key",
            "detail": (
                f"Sẵn sàng qua OPENAI_API_KEY ({model})."
                if api_key
                else "Chưa có OPENAI_API_KEY nên không gọi được GPT API."
            ),
        }
    if key == "anthropic_claude":
        api_key, model = settings.anthropic_config()
        return {
            "ready": bool(api_key),
            "blocked_reason": "" if api_key else "missing_key",
            "detail": (
                f"Sẵn sàng qua ANTHROPIC_API_KEY ({model})."
                if api_key
                else "Chưa có ANTHROPIC_API_KEY."
            ),
        }
    if key in {"chatgpt_app_mcp", "claude_chat_mcp"}:
        agent = "chatgpt_app" if key == "chatgpt_app_mcp" else "claude_chat"
        live = chat_agent_presence.connected(agent)
        tunnel = settings.integration_value(
            "CHATGPT_MCP_TUNNEL_ID" if agent == "chatgpt_app" else "CLAUDE_MCP_TUNNEL_ID"
        )
        return {
            "ready": live,
            "blocked_reason": "" if live else "no_live_tunnel",
            "detail": (
                "Cuộc chat vừa gọi MCP nên đang nhận được việc."
                if live
                else "Đã khai báo tunnel nhưng chưa có lần gọi MCP gần đây."
                if tunnel
                else "Chưa kết nối cuộc chat với MCP bridge."
            ),
        }
    return {"ready": False, "blocked_reason": "unknown_runtime", "detail": "Runtime chưa được hỗ trợ."}


def _usage_limits(database: Any) -> dict[str, dict[str, Any]]:
    """Runtimes currently out of quota, as recorded by real failures."""
    if database is None or not hasattr(database, "list_active_usage_limits"):
        return {}
    try:
        rows = database.list_active_usage_limits()
    except Exception:
        return {}
    return {str(row.get("provider") or ""): dict(row) for row in rows}


def runtime_readiness(
    database: Any = None,
    *,
    statuses: dict[str, Callable[[], dict[str, Any]]] | None = None,
    probe: Callable[..., dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Real execution readiness for every text runtime, with the reason.

    A recorded usage limit outranks a green sign-in: the CLI is installed and
    logged in, and will still refuse the call until the quota resets, so that
    counts as an outage rather than a route worth trying.
    """
    limits = _usage_limits(database)
    report: list[dict[str, Any]] = []
    for descriptor in _DESCRIPTORS:
        try:
            state = probe(descriptor) if probe else _probe(descriptor, statuses)
        except Exception as exc:  # A probe must never take the app down.
            state = {"ready": False, "blocked_reason": "probe_failed", "detail": str(exc)[:300]}
        limit = limits.get(str(descriptor.get("id") or ""))
        quota = usage_limits.limit_state(limit)
        if quota["blocking"]:
            state = {
                "ready": False,
                "blocked_reason": "usage_limit",
                "detail": (
                    f"{str((limit or {}).get('message') or 'Tài khoản đang hết lượt dùng.')} "
                    f"(thử lại lúc {quota['retry_at']})"
                ),
            }
        elif limit and state.get("ready"):
            # History, not a verdict: the outage is old enough to be tested
            # again, and the next real call either clears it or records it anew.
            state = {
                **state,
                "detail": (
                    f"Từng hết hạn mức ({str(limit.get('detected_at') or '')[:16]}); "
                    "đã qua thời gian chờ nên được thử lại. " + str(state.get("detail") or "")
                ).strip(),
            }
        report.append({
            **descriptor,
            "serves": list(descriptor["serves"]),
            "ready": bool(state.get("ready")),
            "blocked_reason": str(state.get("blocked_reason") or ""),
            "detail": str(state.get("detail") or ""),
            "resets_at": str((limit or {}).get("resets_at") or ""),
            "quota_state": quota["state"],
            "retry_at": quota["retry_at"] or "",
        })
    return report


def text_providers(database: Any = None, **probe_kwargs: Any) -> list[dict[str, Any]]:
    """Every text AI connected to the app, for the model list of each step.

    The step selectors used to build this list themselves and ask only
    whether a CLI was signed in, so a model that was signed in and out of
    quota still offered itself as a choice. Reading the same gate the router
    reads means the list says what will actually happen.
    """
    rows = runtime_readiness(database, **probe_kwargs)
    return [
        {
            "provider": item["id"],
            "label": item["label"],
            "available": item["ready"] and item["can_write"],
            "detail": item["detail"],
            "blocked_reason": item["blocked_reason"],
            "serves": item["serves"],
        }
        for item in rows
        if item["can_write"]
    ]


def readiness_index(readiness: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id") or ""): item for item in readiness}


def writer_order(readiness: Iterable[dict[str, Any]]) -> list[str]:
    """Writer runtimes that can run now, in the order the plan asks for."""
    index = readiness_index(readiness)
    return [
        key for key in WRITER_PREFERENCE
        if index.get(key, {}).get("ready") and index.get(key, {}).get("can_write")
    ]


def gate(readiness: Iterable[dict[str, Any]], candidates: Iterable[str]) -> dict[str, Any]:
    """Split the candidates a stage policy allows into runnable and blocked.

    The blocked half is the point: when a stage ends up with nothing to call,
    the user needs to read which sign-in is missing, not "no AI is allowed".
    """
    index = readiness_index(readiness)
    ready: list[str] = []
    blocked: list[dict[str, str]] = []
    for candidate in candidates:
        state = index.get(candidate)
        if state is None:
            blocked.append({
                "runtime": candidate,
                "reason": "unknown_runtime",
                "detail": "Runtime không có trong danh sách hỗ trợ.",
            })
        elif state.get("ready"):
            ready.append(candidate)
        else:
            blocked.append({
                "runtime": candidate,
                "reason": str(state.get("blocked_reason") or "not_ready"),
                "detail": str(state.get("detail") or ""),
            })
    return {"ready": ready, "blocked": blocked}


def blocked_summary(blocked: Iterable[dict[str, Any]]) -> str:
    return " | ".join(
        f"{item.get('runtime')}: {item.get('detail') or item.get('reason')}" for item in blocked
    )


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

REPORT_COLUMNS = (
    "Bước",
    "Model/tool đã chọn",
    "Vì sao chọn",
    "Đầu vào",
    "Kết quả",
    "Trạng thái",
    "Dùng fallback",
)


def _cell(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())[:limit]
    return text.replace("|", "/") or "—"


def report_markdown(steps: Iterable[dict[str, Any]]) -> str:
    """The run report the plan requires, as a table that can be pasted back.

    A run with no rows is rendered as an explicit "no AI step recorded" line,
    because an empty table would read as a run that simply had nothing to do.
    """
    rows = list(steps)
    lines = [
        "| " + " | ".join(REPORT_COLUMNS) + " |",
        "|" + "|".join(["---"] * len(REPORT_COLUMNS)) + "|",
    ]
    if not rows:
        return "\n".join(lines + ["| _Chưa ghi nhận bước AI nào_ | — | — | — | — | — | — |"])
    for row in rows:
        lines.append("| " + " | ".join([
            _cell(row.get("step") or row.get("stage")),
            _cell(row.get("runtime")),
            _cell(row.get("why")),
            _cell(row.get("input_summary")),
            _cell(row.get("output_ref") or row.get("error")),
            _cell(row.get("status")),
            "có" if row.get("fallback_used") else "không",
        ]) + " |")
    return "\n".join(lines)


def report_summary(steps: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(steps)
    failed = [row for row in rows if str(row.get("status") or "") == "failed"]
    fallback = [row for row in rows if row.get("fallback_used")]
    runtimes = sorted({str(row.get("runtime") or "") for row in rows if row.get("runtime")})
    return {
        "steps": len(rows),
        "failed": len(failed),
        "fallback_steps": len(fallback),
        "runtimes_used": runtimes,
        # A run where any step fell back to a template is not an AI
        # Orchestrator run, however good the render looks afterwards.
        "ai_complete": bool(rows) and not failed and not fallback,
        "last_error": str((failed[-1].get("error") if failed else "") or "")[:400],
        "last_at": str((rows[-1].get("created_at") if rows else "") or ""),
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
