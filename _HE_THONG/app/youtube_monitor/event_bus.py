from __future__ import annotations

import re
from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable, Iterable

from .database import Database


TASK_CREATED = "task.created"
TASK_STARTED = "task.started"
TASK_COMPLETED = "task.completed"
TASK_FAILED = "task.failed"
REVIEW_REQUESTED = "review.requested"
REVIEW_COMPLETED = "review.completed"
SCRIPT_COMPLETED = "script.completed"
SCENE_CREATED = "scene.created"
SCENE_APPROVED = "scene.approved"
SCENE_QC_FAILED = "scene.qc_failed"
VOICE_COMPLETED = "voice.completed"
PROJECT_READY_TO_RENDER = "project.ready_to_render"
RENDER_COMPLETED = "render.completed"

_EVENT_NAME = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


@dataclass(frozen=True, slots=True)
class DomainEvent:
    id: int
    event_type: str
    project_id: int | None
    aggregate_type: str
    aggregate_id: str
    source: str
    correlation_id: str
    causation_id: str
    payload: dict[str, Any]
    created_at: str

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "DomainEvent":
        return cls(
            id=int(record["id"]),
            event_type=str(record["event_type"]),
            project_id=int(record["project_id"]) if record.get("project_id") is not None else None,
            aggregate_type=str(record.get("aggregate_type") or ""),
            aggregate_id=str(record.get("aggregate_id") or ""),
            source=str(record.get("source") or "app"),
            correlation_id=str(record.get("correlation_id") or ""),
            causation_id=str(record.get("causation_id") or ""),
            payload=dict(record.get("payload") or {}),
            created_at=str(record.get("created_at") or ""),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "project_id": self.project_id,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "source": self.source,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "payload": self.payload,
            "created_at": self.created_at,
        }


EventHandler = Callable[[DomainEvent], None]


class EventBus:
    """Durable event bus with optional in-process subscribers.

    Persisting before dispatch means an MCP client or agent can resume from an
    event id even if the app was restarted between producer and consumer.
    """

    def __init__(self, database: Database):
        self.database = database
        self._lock = RLock()
        self._subscribers: dict[str, list[EventHandler]] = {}

    @staticmethod
    def validate_event_type(event_type: str) -> str:
        normalized = event_type.strip().lower()
        if not _EVENT_NAME.fullmatch(normalized):
            raise ValueError(
                "Event type phải có dạng namespace.action, ví dụ task.completed"
            )
        return normalized

    def subscribe(self, event_type: str, handler: EventHandler) -> Callable[[], None]:
        key = "*" if event_type.strip() == "*" else self.validate_event_type(event_type)
        with self._lock:
            self._subscribers.setdefault(key, []).append(handler)

        def unsubscribe() -> None:
            with self._lock:
                handlers = self._subscribers.get(key, [])
                if handler in handlers:
                    handlers.remove(handler)

        return unsubscribe

    def publish(
        self,
        event_type: str,
        *,
        project_id: int | None = None,
        aggregate_type: str = "",
        aggregate_id: str | int = "",
        source: str = "app",
        correlation_id: str = "",
        causation_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> DomainEvent:
        normalized = self.validate_event_type(event_type)
        event = DomainEvent.from_record(
            self.database.append_domain_event(
                normalized,
                project_id=project_id,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                source=source,
                correlation_id=correlation_id,
                causation_id=causation_id,
                payload=payload,
            )
        )
        with self._lock:
            handlers = tuple(self._subscribers.get(normalized, ())) + tuple(
                self._subscribers.get("*", ())
            )
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                # A consumer cannot roll back a durable event or break the
                # producer. It can resume from the event id and retry later.
                continue
        return event

    def history(
        self,
        *,
        after_id: int = 0,
        project_id: int | None = None,
        event_types: Iterable[str] = (),
        limit: int = 200,
    ) -> list[DomainEvent]:
        normalized = [self.validate_event_type(item) for item in event_types]
        return [
            DomainEvent.from_record(record)
            for record in self.database.list_domain_events(
                after_id=after_id,
                project_id=project_id,
                event_types=normalized,
                limit=limit,
            )
        ]
