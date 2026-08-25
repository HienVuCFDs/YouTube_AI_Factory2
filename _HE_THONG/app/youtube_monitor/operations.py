"""A registry of work in progress, so a person can stop it.

Nothing here could be stopped. Analysis reads a long transcript in six passes
and takes about twenty minutes; writing a script for a long source can take
thirty. Both are plain blocking HTTP calls, so once started the only way out
was to close the app. Production jobs were only half better: a queued one
could be cancelled, a running one was refused outright with "it will finish
safely" - which is true, and no comfort when it is finishing the wrong thing.

An operation registers itself here, the CLI subprocesses it spawns register
against it, and cancelling sets a flag and kills them. Loops that run several
passes check between passes, so a cancel lands at the next boundary even if
the current call has already been sent.
"""

from __future__ import annotations

import contextvars
import subprocess
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator


class OperationCancelled(RuntimeError):
    """Raised inside a tracked operation once someone has cancelled it."""


@dataclass
class Operation:
    id: str
    kind: str
    label: str
    started_at: str
    project_id: int | None = None
    cancelled: bool = False
    processes: list[subprocess.Popen[Any]] = field(default_factory=list)
    step: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "started_at": self.started_at,
            "project_id": self.project_id,
            "cancelled": self.cancelled,
            "step": self.step,
        }


_lock = threading.Lock()
_running: dict[str, Operation] = {}
# Set for the duration of a tracked call, so a bridge several frames deeper can
# find the operation it belongs to without every function passing an id along.
_current: contextvars.ContextVar[str | None] = contextvars.ContextVar("operation_id", default=None)


def current_id() -> str | None:
    return _current.get()


def active() -> list[dict[str, Any]]:
    """Everything running right now, oldest first."""
    with _lock:
        return [item.as_dict() for item in sorted(_running.values(), key=lambda item: item.started_at)]


def cancel(operation_id: str) -> bool:
    """Ask an operation to stop, and kill whatever it is currently running.

    Killing the subprocess is what makes this immediate: the flag alone would
    only be noticed once the CLI call already in flight returned, which for a
    thirty minute generation is no better than waiting.
    """
    with _lock:
        operation = _running.get(operation_id)
        if operation is None:
            return False
        operation.cancelled = True
        processes = list(operation.processes)
    for process in processes:
        try:
            if process.poll() is None:
                process.terminate()
        except (OSError, ValueError):
            continue
    return True


def cancel_all() -> int:
    return sum(1 for item in active() if cancel(str(item["id"])))


def is_cancelled(operation_id: str | None = None) -> bool:
    chosen = operation_id or _current.get()
    if not chosen:
        return False
    with _lock:
        operation = _running.get(chosen)
        return bool(operation and operation.cancelled)


def check(operation_id: str | None = None) -> None:
    """Stop here if this operation has been cancelled."""
    if is_cancelled(operation_id):
        raise OperationCancelled("Người dùng đã dừng tiến trình này")


def set_step(step: str, operation_id: str | None = None) -> None:
    """Record what the operation is doing, for the list on screen."""
    chosen = operation_id or _current.get()
    if not chosen:
        return
    with _lock:
        operation = _running.get(chosen)
        if operation is not None:
            operation.step = str(step)[:200]


def register_process(process: subprocess.Popen[Any], operation_id: str | None = None) -> None:
    """Attach a subprocess so cancelling can kill it.

    Called from the CLI bridges. If the operation was cancelled between the
    check and the spawn, the process is killed immediately rather than left
    running for the length of a generation nobody is waiting for.
    """
    chosen = operation_id or _current.get()
    if not chosen:
        return
    with _lock:
        operation = _running.get(chosen)
        if operation is None:
            return
        operation.processes.append(process)
        already_cancelled = operation.cancelled
    if already_cancelled:
        try:
            process.terminate()
        except (OSError, ValueError):
            pass


def release_process(process: subprocess.Popen[Any], operation_id: str | None = None) -> None:
    chosen = operation_id or _current.get()
    if not chosen:
        return
    with _lock:
        operation = _running.get(chosen)
        if operation is not None and process in operation.processes:
            operation.processes.remove(process)


@contextmanager
def track(kind: str, label: str, project_id: int | None = None) -> Iterator[Operation]:
    """Run a block as a cancellable operation."""
    operation = Operation(
        id=uuid.uuid4().hex[:12],
        kind=kind,
        label=label,
        started_at=datetime.now(timezone.utc).isoformat(),
        project_id=project_id,
    )
    with _lock:
        _running[operation.id] = operation
    token = _current.set(operation.id)
    try:
        yield operation
    finally:
        _current.reset(token)
        with _lock:
            _running.pop(operation.id, None)


def run_cancellable(
    command: list[str],
    *,
    timeout: int,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """subprocess.run, but the process can be killed from outside.

    subprocess.run owns its child until it exits, which is why a running CLI
    call could not be stopped. Spawning it here and registering the handle lets
    cancel() terminate it, and the wait then reports the cancel rather than an
    ordinary non-zero exit.
    """
    check()
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        env=env,
        creationflags=creation_flags,
    )
    register_process(process)
    try:
        stdout, stderr = process.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    finally:
        release_process(process)
    # A terminated child looks like an ordinary failure from the outside, so
    # the flag decides which it was.
    check()
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
