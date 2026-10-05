"""The one list of things making a video consists of.

The app grew two separate implementations of the same pipeline: the endpoints
the buttons call, and a second copy inside the automatic agent run that wrote
to the database directly - with `force=True`, so it also skipped the checks
the manual path has to pass. Fixing a step in one never fixed the other, and
the two produced different results on the same project.

This module is the shared description: what the steps are, what each one needs
before it can run, and which of them spend the user's paid generations. It is
deliberately data only - no imports from `main`, so the order and the rules can
be read and tested without starting the app. `main` supplies the function that
performs each step, and every way of driving the app - a button, the automatic
run, an AI orchestrator over MCP - goes through that one implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class StepDefinition:
    key: str
    label: str
    # Which per-stage agent policy decides this step, "" when the step is
    # deterministic and asks no model at all.
    stage: str = ""
    # Steps that must be done first. A step whose needs are unmet is refused
    # with the reason rather than run into a failure further down.
    requires: tuple[str, ...] = ()
    # True when running it consumes a paid generation or a subscription quota.
    # Anything true here stays behind the confirmation policy.
    spends: bool = False
    note: str = ""
    # Kept running so nothing that calls it breaks, but superseded: new work
    # must not build on it.
    legacy: bool = False


STEPS: tuple[StepDefinition, ...] = (
    StepDefinition(
        key="analyze",
        label="Phân tích nguồn",
        stage="orchestration",
        note="Đọc video/nguồn và rút ra chủ đề, phong cách, nhịp dựng.",
    ),
    StepDefinition(
        key="plan",
        label="Lập kế hoạch",
        stage="orchestration",
        requires=("analyze",),
        note="Từ nguồn đã phân tích: nên làm video gì và làm thế nào. Lưu ResearchReport và ProjectPlan.",
    ),
    StepDefinition(
        key="research",
        label="Nghiên cứu (cũ)",
        stage="orchestration",
        legacy=True,
        note=(
            "Đường cũ: tra web theo tên dự án, lưu artifact mà không bước nào đọc. "
            "Giữ để không gãy lời gọi cũ; Kế hoạch mới không dùng kết quả này."
        ),
    ),
    StepDefinition(
        key="script",
        label="Viết kịch bản",
        stage="script",
        # The script is written from the plan, and only a completed plan
        # counts as done: one that waits on a decision, is blocked or is
        # stale does not. A project started from an idea is analysed and
        # planned like any other before it is written.
        requires=("plan",),
        spends=True,
        note="Viết lời cho video từ Kế hoạch đã sẵn sàng: đúng góc, thời lượng và cấu trúc. Không nghiên cứu lại.",
    ),
    StepDefinition(
        key="script_review",
        label="Soát kịch bản",
        stage="quality_review",
        requires=("script",),
    ),
    StepDefinition(
        key="shots",
        label="Chia cảnh",
        stage="storyboard",
        requires=("script",),
    ),
    StepDefinition(
        key="timeline",
        label="Dựng timeline",
        requires=("shots",),
        note="Tất định: ghép cảnh thành dòng thời gian, không gọi AI.",
    ),
    StepDefinition(
        key="voice",
        label="Tạo giọng đọc",
        requires=("timeline",),
        spends=True,
    ),
    StepDefinition(
        key="voice_review",
        label="Soát giọng đọc",
        stage="quality_review",
        requires=("voice",),
    ),
    StepDefinition(
        key="media",
        label="Tạo hình cho cảnh",
        stage="image_generation",
        requires=("timeline",),
        spends=True,
    ),
    StepDefinition(
        key="edit_plan",
        label="Lập kế hoạch dựng",
        stage="storyboard",
        # After the voice, so overlay and SFX timing is planned against the
        # real length of each scene instead of an estimate that the voice
        # then overwrites.
        requires=("voice",),
    ),
    StepDefinition(
        key="render",
        label="Dựng video",
        requires=("timeline",),
        spends=True,
    ),
    StepDefinition(
        key="publish",
        label="Xuất bản",
        stage="quality_review",
        requires=("render",),
        spends=True,
    ),
)

STEP_KEYS: tuple[str, ...] = tuple(step.key for step in STEPS)
_BY_KEY: dict[str, StepDefinition] = {step.key: step for step in STEPS}


def get(key: str) -> StepDefinition | None:
    return _BY_KEY.get(str(key or "").strip().lower())


def unmet_requirements(key: str, done: Iterable[str]) -> list[str]:
    """Which prerequisites of this step have not been done yet."""
    step = get(key)
    if step is None:
        return []
    finished = {str(item) for item in done}
    return [name for name in step.requires if name not in finished]


def upstream(key: str) -> set[str]:
    """Every step this one waits on, directly or through another."""
    found: set[str] = set()
    pending = list((get(key).requires if get(key) else ()))
    while pending:
        name = pending.pop()
        if name in found:
            continue
        found.add(name)
        pending.extend(get(name).requires if get(name) else ())
    return found


def plan_for(key: str, done: Iterable[str]) -> list[str]:
    """Every step needed to reach `key`, in order, skipping what is done.

    A caller that asks for the render on an empty project gets the whole
    chain rather than a refusal: that is what "làm video từ link này" means
    in one sentence.
    """
    finished = {str(item) for item in done}
    ordered: list[str] = []

    def walk(name: str) -> None:
        step = get(name)
        if step is None or name in ordered or name in finished:
            return
        for need in step.requires:
            walk(need)
        ordered.append(name)

    walk(str(key or "").strip().lower())
    return ordered


def describe(done: Iterable[str], running: Iterable[str] = ()) -> list[dict[str, Any]]:
    """The state of every step, for a progress strip or an orchestrator."""
    finished = {str(item) for item in done}
    active = {str(item) for item in running}
    rows: list[dict[str, Any]] = []
    for step in STEPS:
        missing = [name for name in step.requires if name not in finished]
        if step.key in active:
            state = "running"
        elif step.key in finished:
            state = "done"
        elif missing:
            state = "blocked"
        else:
            state = "ready"
        rows.append({
            "key": step.key,
            "label": step.label,
            "stage": step.stage,
            "requires": list(step.requires),
            "spends": step.spends,
            "note": step.note,
            "legacy": step.legacy,
            "state": state,
            "missing": missing,
        })
    return rows
