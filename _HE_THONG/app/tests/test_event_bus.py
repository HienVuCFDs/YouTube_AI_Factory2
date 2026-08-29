from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from youtube_monitor.database import Database
from youtube_monitor.event_bus import EventBus, TASK_COMPLETED, TASK_CREATED


def test_event_bus_persists_and_replays_events():
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "events.db")
        bus = EventBus(database)

        created = bus.publish(
            TASK_CREATED,
            aggregate_type="agent_task",
            aggregate_id="agt_1",
            source="orchestrator",
            correlation_id="corr-1",
            payload={"role": "research"},
        )
        completed = bus.publish(
            TASK_COMPLETED,
            aggregate_type="agent_task",
            aggregate_id="agt_1",
            source="research_agent",
            correlation_id="corr-1",
            causation_id=str(created.id),
            payload={"score": 91},
        )

        replayed = EventBus(Database(Path(directory) / "events.db")).history(
            after_id=created.id,
            event_types=[TASK_COMPLETED],
        )
        assert [event.id for event in replayed] == [completed.id]
        assert replayed[0].payload == {"score": 91}
        assert replayed[0].correlation_id == "corr-1"


def test_event_bus_dispatches_exact_and_wildcard_subscribers_without_rollback():
    with tempfile.TemporaryDirectory() as directory:
        bus = EventBus(Database(Path(directory) / "events.db"))
        received = []
        bus.subscribe(TASK_CREATED, received.append)
        bus.subscribe("*", lambda event: received.append(event))
        bus.subscribe(TASK_CREATED, lambda event: (_ for _ in ()).throw(RuntimeError("consumer failed")))

        event = bus.publish(TASK_CREATED, payload={"ok": True})

        assert [item.id for item in received] == [event.id, event.id]
        assert bus.history()[0].payload == {"ok": True}


def test_event_bus_rejects_unscoped_event_names():
    with tempfile.TemporaryDirectory() as directory:
        bus = EventBus(Database(Path(directory) / "events.db"))
        with pytest.raises(ValueError, match="namespace.action"):
            bus.publish("TASK_COMPLETED")
