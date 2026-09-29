"""The orchestration loop: a goal, an agent with the app's tools, and a check.

`/orchestrate` used to ask a model for a plan once, run it once and stop, so the
first tool that failed decided the outcome. Here the agent works the way a
person at the controls would:

    GOAL
    → inspect the project's real state
    → choose an action (a tool), execute it, read the result or the error
    → done yet? if not: diagnose, choose something different, go again
    → verify against the real state before claiming anything
    → finish

Inside one round the agent runtime (codex_agent_bridge / claude_agent_bridge)
loops on its own over the app's MCP tools. Around it, this module keeps what a
prompt cannot guarantee:

- completion is decided by reading the project, never by the agent's report;
- a brain that fails outright (quota, not signed in, crashed) is replaced by the
  next runtime rather than asked again;
- every round sees what every earlier round tried and what came back;
- two rounds in a row that leave the project exactly as it was end the run as
  blocked, instead of trying the same thing until the round limit.

Retrying a model call that hit a 503 is a different mechanism and stays where it
is, in llm_client._with_retry. This loop changes strategy; that one repeats.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import steps
from .agent_runtime import AgentRun, AgentRunError

Runner = Callable[[str, dict[str, str]], AgentRun]


@dataclass(frozen=True)
class GoalSpec:
    project_id: int
    goal: str
    target_steps: tuple[str, ...]
    allow_spend: bool = False
    allow_overwrite: bool = False
    max_rounds: int = 4
    tool_budget: int = 40
    runtimes: tuple[str, ...] = ("codex_cli", "claude_code_cli")

    def __post_init__(self) -> None:
        unknown = [name for name in self.target_steps if steps.get(name) is None]
        if not self.target_steps or unknown:
            raise ValueError(f"target_steps phải là các bước có thật: {', '.join(unknown) or '(trống)'}")


INSTRUCTIONS = """Bạn là AI điều phối của YouTube AI Factory. Tay chân duy nhất của bạn là các tool youtube_factory_* (MCP).
Không có giao diện để bấm, không có shell: mọi việc làm qua tool.

CÁCH LÀM (bắt buộc):
1. Gọi youtube_factory_list_steps(project_id) để xem trạng thái THẬT trước khi làm gì.
2. Chọn một hành động, gọi tool, rồi ĐỌC kết quả hoặc lỗi trước khi quyết định bước tiếp.
3. Một tool lỗi KHÔNG có nghĩa mục tiêu thất bại. Đọc lỗi, chẩn đoán, chọn phương án khác:
   - bước bị từ chối vì chưa làm bước trước → chạy bước trước, rồi quay lại;
   - AI/provider lỗi hoặc hết hạn mức → chạy lại bước với options.provider khác
     (xem youtube_factory_get_ai_runtimes để biết cái nào chạy được);
   - bước cần nội dung mà AI của app không viết được → tự viết và đưa qua options
     (script: options.draft; shots: options.shots);
   - nguồn là link sản phẩm mà trang chưa đọc được (NEED_LOGIN / NEED_HUMAN_VERIFY) →
     youtube_factory_list_connections xem nền tảng nào can_read (hoặc Browser Bridge), rồi chạy lại
     analyze với options.browser_session=profile:<nền tảng> hoặc extension:<trình duyệt> (vd extension:coccoc). Không tự giải captcha,
     không đăng nhập hộ; không còn cách nào thì báo blocked và nói người dùng cần bấm Kết nối nền tảng nào.
4. Không gọi lại Y HỆT một lệnh vừa lỗi khi trạng thái dự án chưa đổi — app sẽ chặn. Đổi cách.
5. Trước khi báo "done": gọi youtube_factory_list_steps lần nữa và xác nhận các bước đích đã "done".
   App sẽ tự kiểm tra lại bằng dữ liệu thật; báo done khi chưa xong sẽ bị phát hiện.
6. Hết cách thì báo status "blocked", nói rõ lý do và các phương án đã thử. Không bịa kết quả.
7. Kết thúc bằng báo cáo đúng schema: status, summary, completed_steps, attempts (mỗi lần thử: action + outcome), blocked_reason."""


def read_calls(log_path: Path, round_number: int | None = None) -> list[dict[str, Any]]:
    if not log_path.is_file():
        return []
    calls: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and (round_number is None or entry.get("round") == round_number):
            calls.append(entry)
    return calls


def _call_line(entry: dict[str, Any]) -> str:
    args = entry.get("arguments") or {}
    shown = {key: value for key, value in args.items() if key != "project_id"}
    head = f"{entry.get('tool')}({json.dumps(shown, ensure_ascii=False)[:200]})"
    if entry.get("ok"):
        return f"  ✓ {head} → {str(entry.get('result') or '')[:220]}"
    return f"  ✗ {head} → LỖI: {str(entry.get('error') or '')[:300]}"


def build_prompt(
    spec: GoalSpec,
    state: dict[str, Any],
    check: dict[str, Any],
    rounds: list[dict[str, Any]],
    round_number: int,
    runtime: str,
    unusable: dict[str, str],
) -> str:
    done = [str(item) for item in state.get("done") or []]
    route = []
    for target in spec.target_steps:
        for name in steps.plan_for(target, done):
            if name not in route:
                route.append(name)
    lines = [
        f"MỤC TIÊU: {spec.goal}",
        f"DỰ ÁN: project_id = {spec.project_id}",
        f"ĐÍCH (app tự kiểm bằng dữ liệu thật): các bước {list(spec.target_steps)} phải ở trạng thái done.",
        f"Chuỗi bước còn phải đi theo điều kiện tiên quyết: {route or 'không còn gì'}",
        f"Hiện đã done: {done or 'chưa có bước nào'}. Còn thiếu cho đích: {check.get('missing')}",
        *[f"Vì sao {name} chưa tính là xong: {reason}" for name, reason in (check.get("reasons") or {}).items()],
        "QUYỀN: " + ("được tiêu lượt tạo/quota khi cần." if spec.allow_spend
                     else "KHÔNG được tiêu lượt tạo/quota (app sẽ chặn bước tiêu lượt).")
        + (" Được dùng force để làm lại thứ đã có." if spec.allow_overwrite
           else " KHÔNG được dùng force ghi đè thứ đã có (app sẽ chặn).")
        + " Không bao giờ đăng video.",
        f"GIỚI HẠN: tối đa {spec.tool_budget} lần gọi tool trong vòng này (vòng {round_number}/{spec.max_rounds}).",
    ]
    if unusable:
        lines.append("AI điều phối đã hỏng ở lượt này (không dùng lại): "
                     + "; ".join(f"{name}: {reason[:160]}" for name, reason in unusable.items()))
    if rounds:
        lines.append("\nNHỮNG GÌ CÁC VÒNG TRƯỚC ĐÃ LÀM (đọc kỹ, đừng lặp lại cách đã hỏng):")
        for item in rounds:
            lines.append(f"Vòng {item['round']} ({item['runtime']}):")
            if item.get("runtime_error"):
                lines.append(f"  AI điều phối không chạy được: {item['runtime_error'][:300]}")
                continue
            report = item.get("report") or {}
            lines.append(f"  Agent báo: {report.get('status')} — {str(report.get('summary') or '')[:400]}")
            lines.extend(_call_line(entry) for entry in item.get("calls") or [])
            verification = item.get("verification") or {}
            lines.append(f"  App kiểm tra sau vòng: còn thiếu {verification.get('missing')}")
            for name, reason in (verification.get("reasons") or {}).items():
                lines.append(f"    {name}: {reason[:300]}")
            if verification.get("false_claims"):
                lines.append(f"  Agent báo đã xong nhưng thực tế CHƯA: {verification['false_claims']}")
    lines.append(f"\nVòng này do {runtime} làm. Bắt đầu bằng youtube_factory_list_steps.")
    return "\n".join(lines)


def _finish(status: str, spec: GoalSpec, rounds: list[dict[str, Any]], check: dict[str, Any], reason: str = "",
            started: float = 0.0) -> dict[str, Any]:
    return {
        "status": status,
        "verified": bool(check.get("passed")),
        "goal": spec.goal,
        "project_id": spec.project_id,
        "target_steps": list(spec.target_steps),
        "missing": check.get("missing") or [],
        "evidence": check.get("evidence") or {},
        "reason": reason,
        "rounds": rounds,
        "seconds": round(time.monotonic() - started, 1) if started else 0.0,
    }


def run_goal(
    spec: GoalSpec,
    *,
    runners: dict[str, Runner],
    read_state: Callable[[int], dict[str, Any]],
    verify: Callable[[GoalSpec, list[str]], dict[str, Any]],
    mcp_env: Callable[[int], dict[str, str]],
    log_path: Path,
    available: Callable[[str], bool] = lambda runtime: True,
    record: Callable[[dict[str, Any]], None] = lambda event: None,
) -> dict[str, Any]:
    """Drive one goal to a verified finish, a clear block, or the round limit."""
    started = time.monotonic()
    rounds: list[dict[str, Any]] = []
    unusable: dict[str, str] = {}
    stalled = 0
    completed_rounds = 0

    def conclude(result: dict[str, Any]) -> dict[str, Any]:
        # One closing line per run, so a failed task says where it stopped
        # and why without replaying every round.
        record({"event": "run.finished", "status": result["status"], "verified": result["verified"],
                "missing": result["missing"], "reason": result["reason"], "rounds": len(result["rounds"])})
        return result

    while completed_rounds < spec.max_rounds:
        check = verify(spec, [])
        if check.get("passed"):
            return conclude(_finish("completed", spec, rounds, check, started=started))
        runtime, skipped = _choose_runtime(spec, runners, unusable, available)
        if runtime is None:
            reason = "Không còn AI điều phối nào chạy được: " + "; ".join(
                f"{name}: {why[:200]}" for name, why in skipped.items()
            )
            return conclude(_finish("blocked", spec, rounds, check, reason, started))
        decision = {"chosen": runtime, "skipped": skipped}

        round_number = len(rounds) + 1
        before = read_state(spec.project_id)
        prompt = build_prompt(spec, before, check, rounds, round_number, runtime, unusable)
        record({"event": "round.started", "round": round_number, "runtime": runtime, "decision": decision})
        try:
            run = runners[runtime](prompt, mcp_env(round_number))
        except AgentRunError as exc:
            # The brain itself failed; this is a change of strategy (another
            # runtime), not a retry. It does not use up a round of work.
            unusable[runtime] = str(exc)
            rounds.append({"round": round_number, "runtime": runtime, "decision": decision,
                           "runtime_error": str(exc)[:2000], "usage_limit": exc.usage_limit,
                           "calls": read_calls(log_path, round_number)})
            record({"event": "round.runtime_failed", "round": round_number, "runtime": runtime,
                    "usage_limit": exc.usage_limit, "error": str(exc)[:500]})
            continue

        completed_rounds += 1
        calls = read_calls(log_path, round_number)
        after = verify(spec, list(run.report.get("completed_steps") or []))
        rounds.append({
            "round": round_number,
            "runtime": runtime,
            "model": run.meta.get("model", ""),
            "reasoning_effort": run.meta.get("reasoning_effort", ""),
            "decision": decision,
            "report": run.report,
            "calls": calls,
            "verification": after,
            "seconds": run.seconds,
            "turns": run.turns,
            "cost_usd": run.cost_usd,
        })
        record({"event": "round.finished", "round": round_number, "runtime": runtime,
                "model": run.meta.get("model", ""), "status": run.report.get("status"),
                "passed": after.get("passed"), "missing": after.get("missing"),
                "false_claims": after.get("false_claims") or [], "calls": len(calls),
                "failed_calls": sum(1 for call in calls if not call.get("ok"))})
        if after.get("passed"):
            return conclude(_finish("completed", spec, rounds, after, started=started))

        changed = sorted(read_state(spec.project_id).get("done") or []) != sorted(before.get("done") or [])
        stalled = 0 if changed else stalled + 1
        if stalled >= 2:
            return conclude(_finish(
                "blocked", spec, rounds, after,
                "Hai vòng liền không làm thay đổi trạng thái dự án; dừng thay vì thử lại cùng một chỗ.",
                started,
            ))
    final = verify(spec, [])
    status = "completed" if final.get("passed") else "not_completed"
    return conclude(_finish(
        status, spec, rounds, final, "" if final.get("passed") else "Hết số vòng cho phép.", started,
    ))


def _choose_runtime(
    spec: GoalSpec,
    runners: dict[str, Runner],
    unusable: dict[str, str],
    available: Callable[[str], bool],
) -> tuple[str | None, dict[str, str]]:
    """The first runtime that can direct now, and why each one before it could not."""
    skipped: dict[str, str] = {}
    for name in spec.runtimes:
        if name not in runners:
            skipped[name] = "không có runtime agent"
        elif name in unusable:
            skipped[name] = f"đã hỏng ở vòng trước: {unusable[name][:200]}"
        elif not available(name):
            skipped[name] = "chưa sẵn sàng (chưa đăng nhập, hoặc đang trong thời gian chờ quota)"
        else:
            return name, skipped
    return None, skipped
