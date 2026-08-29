from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Queue
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any, Callable, Mapping

from .database import Database


AGENT_ROLES = ("research", "script", "director", "media", "qc")
ROLE_STAGE = {
    "research": "orchestration",
    "script": "script",
    "director": "storyboard",
    "media": "image_generation",
    "qc": "quality_review",
}


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    role: str
    display_name: str
    responsibility: str
    stage: str


DEFAULT_AGENTS = (
    AgentDefinition("research", "Research Agent", "Research chủ đề, cơ hội và audience", "orchestration"),
    AgentDefinition("script", "Script Agent", "Viết hook, outline, narration và CTA", "script"),
    AgentDefinition("director", "Director Agent", "Chia scene, camera, motion và thời lượng", "storyboard"),
    AgentDefinition("media", "Media Agent", "Chọn loại media và provider cho từng scene", "image_generation"),
    AgentDefinition("qc", "QC Agent", "Nghiệm thu chéo asset, voice, subtitle và render", "quality_review"),
)


AgentExecutor = Callable[[dict[str, Any], str], dict[str, Any]]
AgentReviewer = Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]]
AssignmentResolver = Callable[[str], Mapping[str, Any]]
AvailabilityResolver = Callable[[str], bool]
CompletionHandler = Callable[[dict[str, Any]], None]
PolicyResolver = Callable[[], Mapping[str, Any]]


class AgentTaskWorker:
    """Persistent worker executing role tasks with cross-agent review."""

    def __init__(
        self,
        database: Database,
        *,
        assignment_resolver: AssignmentResolver,
        availability_resolver: AvailabilityResolver,
        policy_resolver: PolicyResolver | None = None,
    ):
        self.database = database
        self.assignment_resolver = assignment_resolver
        self.availability_resolver = availability_resolver
        self.policy_resolver = policy_resolver or (lambda: {})
        self._executor: AgentExecutor | None = None
        self._reviewer: AgentReviewer | None = None
        self._completion_handler: CompletionHandler | None = None
        self._jobs: Queue[str | None] = Queue()
        self._stop = Event()
        self._lock = Lock()
        self._thread: Thread | None = None
        self._last_review_scan = 0.0
        self.review_scan_seconds = 30.0

    def configure(
        self,
        *,
        executor: AgentExecutor,
        reviewer: AgentReviewer,
        completion_handler: CompletionHandler | None = None,
    ) -> None:
        self._executor = executor
        self._reviewer = reviewer
        self._completion_handler = completion_handler

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            if self._executor is None or self._reviewer is None:
                raise RuntimeError("AgentTaskWorker chưa được cấu hình executor/reviewer")
            self._stop.clear()
            self.database.requeue_interrupted_agent_tasks()
            for task_id in self.database.list_queued_agent_task_ids():
                self._jobs.put(task_id)
            self._thread = Thread(target=self._run, name="agent-task-worker", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._jobs.put(None)
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
        self._thread = None

    def enqueue(self, task_id: str) -> None:
        self._jobs.put(task_id)

    def status(self) -> dict[str, Any]:
        tasks = self.database.list_agent_tasks(limit=1000)
        counts: dict[str, int] = {}
        for task in tasks:
            key = str(task.get("status") or "unknown")
            counts[key] = counts.get(key, 0) + 1
        return {
            **counts,
            "worker_running": bool(self._thread and self._thread.is_alive()),
            "configured": self._executor is not None and self._reviewer is not None,
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                task_id = self._jobs.get(timeout=2.0)
            except Empty:
                queued = self.database.list_queued_agent_task_ids(limit=1)
                task_id = queued[0] if queued else None
                if task_id is None and monotonic() - self._last_review_scan >= self.review_scan_seconds:
                    self._last_review_scan = monotonic()
                    waiting_reviews = self.database.list_review_required_agent_task_ids(limit=1)
                    task_id = waiting_reviews[0] if waiting_reviews else None
            if task_id is None:
                if self._stop.is_set():
                    return
                continue
            self._process(task_id)

    def _agent_order(self, task: dict[str, Any]) -> list[str]:
        stage = ROLE_STAGE.get(str(task.get("role") or ""), "orchestration")
        assignment = dict(self.assignment_resolver(stage) or {})
        executor = str(task.get("assigned_agent") or assignment.get("executor") or "")
        allowed = [str(item) for item in assignment.get("allowed_agents", []) if str(item)]
        fallbacks = [str(item) for item in assignment.get("fallback_agents", []) if str(item)]
        mode = str(assignment.get("mode") or "auto")
        if mode == "fixed":
            order = [executor]
        elif mode == "fallback":
            order = [executor, *fallbacks]
        else:
            order = [executor, *allowed, *fallbacks]
            order.sort(key=lambda agent: (not self.availability_resolver(agent), agent != executor, agent))
        return list(dict.fromkeys(agent for agent in order if agent))

    def _reviewer_order(self, task: dict[str, Any], executor: str, order: list[str]) -> list[str]:
        stage = ROLE_STAGE.get(str(task.get("role") or ""), "orchestration")
        assignment = dict(self.assignment_resolver(stage) or {})
        configured = str(task.get("reviewer_agent") or assignment.get("reviewer") or "auto")
        candidates = [] if configured == "auto" else [configured]
        # A fixed executor policy only locks who performs the task. It must
        # not collapse cross-review to the same agent when another allowed AI
        # is online.
        candidates.extend(str(item) for item in assignment.get("fallback_agents", []) if str(item))
        candidates.extend(str(item) for item in assignment.get("allowed_agents", []) if str(item))
        candidates.extend(order)
        return [
            candidate
            for candidate in dict.fromkeys(candidates)
            if candidate and candidate != executor and self.availability_resolver(candidate)
        ]

    def _perform_review(
        self,
        task: dict[str, Any],
        executor_agent: str,
        output: dict[str, Any],
        order: list[str],
    ) -> tuple[str, dict[str, Any]]:
        reviewer_call = self._reviewer
        assert reviewer_call is not None
        reviewer_agents = self._reviewer_order(task, executor_agent, order)
        review_errors: list[str] = []
        for candidate in reviewer_agents:
            self.database.append_agent_message(
                project_id=task.get("project_id"),
                task_id=str(task["id"]),
                sender_agent=executor_agent,
                recipient_agent=candidate,
                message_type="review_request",
                correlation_id=str(task.get("correlation_id") or ""),
                payload={"output": output},
            )
            self.database.emit_domain_event(
                "review.requested",
                project_id=task.get("project_id"),
                aggregate_type="agent_task",
                aggregate_id=str(task["id"]),
                source=executor_agent,
                correlation_id=str(task.get("correlation_id") or ""),
                payload={"reviewer_agent": candidate, "role": task["role"]},
            )
            try:
                review = reviewer_call(task, candidate, output)
            except Exception as exc:
                review_errors.append(f"{candidate}: {exc}")
                self.database.append_agent_message(
                    project_id=task.get("project_id"),
                    task_id=str(task["id"]),
                    sender_agent=candidate,
                    recipient_agent="orchestrator",
                    message_type="review_error",
                    correlation_id=str(task.get("correlation_id") or ""),
                    payload={"error": str(exc)[:4000], "role": task["role"]},
                )
                self.database.emit_domain_event(
                    "review.failed",
                    project_id=task.get("project_id"),
                    aggregate_type="agent_task",
                    aggregate_id=str(task["id"]),
                    source=candidate,
                    correlation_id=str(task.get("correlation_id") or ""),
                    payload={"error": str(exc)[:4000], "role": task["role"]},
                )
                continue
            review = dict(review or {})
            try:
                minimum_score = max(0, min(int(self.policy_resolver().get("min_review_score", 0)), 10))
            except (TypeError, ValueError):
                minimum_score = 0
            try:
                score = int(review.get("score", 0))
            except (TypeError, ValueError):
                score = 0
            review["policy_min_score"] = minimum_score
            if bool(review.get("approved", True)) and score < minimum_score:
                review["approved"] = False
                review["note"] = (
                    f"Điểm nghiệm thu {score}/10 thấp hơn ngưỡng policy {minimum_score}/10. "
                    f"{str(review.get('note') or '').strip()}"
                ).strip()
            self.database.append_agent_message(
                project_id=task.get("project_id"),
                task_id=str(task["id"]),
                sender_agent=candidate,
                recipient_agent="orchestrator",
                message_type="review_result",
                correlation_id=str(task.get("correlation_id") or ""),
                payload=review,
            )
            self.database.emit_domain_event(
                "review.completed",
                project_id=task.get("project_id"),
                aggregate_type="agent_task",
                aggregate_id=str(task["id"]),
                source=candidate,
                correlation_id=str(task.get("correlation_id") or ""),
                payload=review,
            )
            return candidate, review
        return "", {
            "approved": False,
            "score": 0,
            "note": " | ".join(review_errors)[:4000] or "Không có reviewer khác đang sẵn sàng",
        }

    def _process(self, task_id: str) -> None:
        pending = self.database.get_agent_task(task_id)
        if not pending:
            return
        if pending.get("status") == "review_required":
            self._process_pending_review(pending)
            return
        if pending.get("status") != "queued":
            return
        order = self._agent_order(pending)
        if not order:
            self.database.finish_agent_task(task_id, "failed", error="Không có AI được phép nhận task")
            return
        claimed = self.database.claim_agent_task(task_id, order[0])
        if not claimed:
            return
        executor = self._executor
        reviewer_call = self._reviewer
        assert executor is not None and reviewer_call is not None
        errors: list[str] = []
        output: dict[str, Any] | None = None
        used_agent = ""
        for agent in order:
            if not self.availability_resolver(agent):
                errors.append(f"{agent}: unavailable")
                continue
            try:
                self.database.append_agent_message(
                    project_id=claimed.get("project_id"),
                    task_id=task_id,
                    sender_agent="orchestrator",
                    recipient_agent=agent,
                    message_type="assignment",
                    correlation_id=str(claimed.get("correlation_id") or ""),
                    payload={"role": claimed["role"], "task_type": claimed["task_type"]},
                )
                output = executor(claimed, agent)
                used_agent = agent
                break
            except Exception as exc:
                errors.append(f"{agent}: {exc}")
                self.database.append_agent_message(
                    project_id=claimed.get("project_id"),
                    task_id=task_id,
                    sender_agent=agent,
                    recipient_agent="orchestrator",
                    message_type="execution_error",
                    correlation_id=str(claimed.get("correlation_id") or ""),
                    payload={"error": str(exc)[:4000], "role": claimed["role"]},
                )
                self.database.emit_domain_event(
                    "agent.execution_failed",
                    project_id=claimed.get("project_id"),
                    aggregate_type="agent_task",
                    aggregate_id=task_id,
                    source=agent,
                    correlation_id=str(claimed.get("correlation_id") or ""),
                    payload={"error": str(exc)[:4000], "role": claimed["role"]},
                )
        if output is None:
            message = " | ".join(errors)[:4000]
            if self.database.requeue_agent_task(task_id, message):
                self._jobs.put(task_id)
            else:
                self.database.finish_agent_task(task_id, "failed", error=message)
            return

        reviewer_agent, review = self._perform_review(claimed, used_agent, output, order)

        combined = {**output, "_execution": {"executor": used_agent, "reviewer": reviewer_agent, "review": review}}
        if not reviewer_agent:
            self.database.finish_agent_task(
                task_id,
                "review_required",
                output=combined,
                error=str(review.get("note") or "Đang chờ một AI khác nghiệm thu")[:4000],
            )
            return
        if not bool(review.get("approved", True)):
            message = str(review.get("note") or "Reviewer không duyệt")
            if self.database.requeue_agent_task(task_id, message):
                self._jobs.put(task_id)
            else:
                self.database.finish_agent_task(task_id, "failed", output=combined, error=message)
            return
        completed = self.database.finish_agent_task(task_id, "completed", output=combined)
        if completed and self._completion_handler is not None:
            try:
                self._completion_handler(completed)
            except Exception:
                # The task remains complete; the pipeline can be resumed from
                # its durable output by an API/MCP caller.
                pass

    def _process_pending_review(self, task: dict[str, Any]) -> None:
        output = dict(task.get("output") or {})
        execution = dict(output.get("_execution") or {})
        executor_agent = str(execution.get("executor") or task.get("assigned_agent") or "")
        if not executor_agent:
            return
        review_input = {key: value for key, value in output.items() if key != "_execution"}
        order = self._agent_order(task)
        reviewer_agent, review = self._perform_review(task, executor_agent, review_input, order)
        if not reviewer_agent:
            return
        combined = {
            **review_input,
            "_execution": {
                "executor": executor_agent,
                "reviewer": reviewer_agent,
                "review": review,
            },
        }
        task_id = str(task["id"])
        if not bool(review.get("approved", True)):
            message = str(review.get("note") or "Reviewer không duyệt")
            requeued = self.database.requeue_agent_task(task_id, message)
            if requeued:
                self._jobs.put(task_id)
            else:
                self.database.finish_agent_task(task_id, "failed", output=combined, error=message)
            return
        completed = self.database.finish_agent_task(task_id, "completed", output=combined)
        if completed and self._completion_handler is not None:
            try:
                self._completion_handler(completed)
            except Exception:
                pass


class AgentPipeline:
    """Creates the A2A hand-off chain without coupling agents to each other."""

    sequence = AGENT_ROLES

    def __init__(
        self,
        database: Database,
        worker: AgentTaskWorker,
        policy_resolver: PolicyResolver | None = None,
    ):
        self.database = database
        self.worker = worker
        self.policy_resolver = policy_resolver or (lambda: {})

    def _max_attempts(self) -> int:
        try:
            return max(1, min(int(self.policy_resolver().get("max_attempts", 2)), 10))
        except (TypeError, ValueError):
            return 2

    def start(
        self,
        project_id: int,
        goal: str,
        *,
        auto_generate_media: bool = False,
        auto_render: bool = False,
    ) -> dict[str, Any]:
        task = self.database.create_agent_task(
            project_id,
            "research",
            "pipeline.research",
            {
                "goal": goal.strip(),
                "pipeline": {
                    "auto_generate_media": bool(auto_generate_media),
                    "auto_render": bool(auto_render),
                },
            },
            requested_by="orchestrator",
            max_attempts=self._max_attempts(),
        )
        self.worker.enqueue(str(task["id"]))
        return task

    def advance(self, completed: dict[str, Any]) -> dict[str, Any] | None:
        role = str(completed.get("role") or "")
        if role not in self.sequence:
            return None
        position = self.sequence.index(role)
        if position >= len(self.sequence) - 1:
            return None
        next_role = self.sequence[position + 1]
        output = dict(completed.get("output") or {})
        original_input = dict(completed.get("input") or {})
        task = self.database.create_agent_task(
            completed.get("project_id"),
            next_role,
            f"pipeline.{next_role}",
            {
                "goal": original_input.get("goal") or output.get("goal") or "",
                "pipeline": original_input.get("pipeline") or output.get("pipeline") or {},
                "previous_role": role,
                "previous_result": output,
            },
            requested_by="orchestrator",
            parent_task_id=str(completed["id"]),
            correlation_id=str(completed.get("correlation_id") or ""),
            max_attempts=self._max_attempts(),
        )
        self.database.append_agent_message(
            project_id=completed.get("project_id"),
            task_id=str(task["id"]),
            sender_agent=f"{role}_agent",
            recipient_agent=f"{next_role}_agent",
            message_type="handoff",
            correlation_id=str(completed.get("correlation_id") or ""),
            payload={"from_task_id": completed["id"], "result": output},
        )
        self.worker.enqueue(str(task["id"]))
        return task
