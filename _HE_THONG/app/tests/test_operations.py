"""Stopping work that is already running."""

from __future__ import annotations

import subprocess
import threading
import time

import pytest

from youtube_monitor import operations
from youtube_monitor.operations import OperationCancelled

SLOW = ["ping", "-n", "30", "127.0.0.1"]


def test_a_tracked_operation_is_listed_while_it_runs() -> None:
    with operations.track("thu", "dang chay"):
        assert [item["label"] for item in operations.active()] == ["dang chay"]
    assert operations.active() == []


def test_an_operation_is_removed_even_when_it_fails() -> None:
    """A crashed operation left in the list would offer a Stop button that
    does nothing, forever."""
    with pytest.raises(ValueError):
        with operations.track("thu", "hong"):
            raise ValueError("hong")

    assert operations.active() == []


def test_cancelling_makes_the_next_check_stop() -> None:
    with operations.track("thu", "x") as operation:
        operations.check()
        operations.cancel(operation.id)
        with pytest.raises(OperationCancelled):
            operations.check()


def test_cancelling_an_unknown_operation_reports_it() -> None:
    assert operations.cancel("khong-ton-tai") is False


def test_the_step_is_visible_while_it_runs() -> None:
    """Six passes over twenty minutes with no sign of progress is why."""
    with operations.track("reference", "phan tich"):
        operations.set_step("Đọc phần 2/6")
        assert operations.active()[0]["step"] == "Đọc phần 2/6"


def test_cancelling_kills_the_running_subprocess() -> None:
    """The flag alone would only be noticed when the call already in flight
    returned - for a thirty minute generation, no better than waiting."""
    outcome: dict[str, object] = {}

    def worker() -> None:
        try:
            with operations.track("thu", "cham"):
                outcome["id"] = operations.current_id()
                operations.run_cancellable(SLOW, timeout=90)
                outcome["result"] = "ran to completion"
        except OperationCancelled:
            outcome["result"] = "cancelled"

    thread = threading.Thread(target=worker)
    thread.start()
    for _ in range(50):
        if outcome.get("id"):
            break
        time.sleep(0.1)

    started = time.monotonic()
    assert operations.cancel(str(outcome["id"])) is True
    thread.join(timeout=20)

    assert outcome["result"] == "cancelled"
    assert time.monotonic() - started < 15, "phai dung ngay, khong doi tien trinh chay het"


def test_a_process_started_after_a_cancel_is_killed_at_once() -> None:
    """Cancel can land between the check and the spawn."""
    with operations.track("thu", "x") as operation:
        operations.cancel(operation.id)
        with pytest.raises(OperationCancelled):
            operations.run_cancellable(SLOW, timeout=60)


def test_an_untracked_call_still_runs_normally() -> None:
    """Most callers are not inside an operation and must be unaffected."""
    result = operations.run_cancellable(["cmd", "/c", "echo", "xin chao"], timeout=30)

    assert result.returncode == 0
    assert "xin chao" in result.stdout


def test_stdin_is_passed_through() -> None:
    """Codex is driven by piping the prompt to its stdin."""
    result = operations.run_cancellable(
        ["findstr", "x"], timeout=30, input_text="xxx\nyyy\n"
    )

    assert "xxx" in result.stdout


def test_a_timeout_still_raises_timeout_rather_than_cancelled() -> None:
    """The two must not be confused: one is a fault, the other is a decision."""
    with pytest.raises(subprocess.TimeoutExpired):
        operations.run_cancellable(SLOW, timeout=1)
