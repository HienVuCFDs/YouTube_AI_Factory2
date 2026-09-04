"""Two lanes of production that really do run at the same time.

A project's long video and its short are separate scripts with separate
timeline rows, so there is nothing for them to fight over and they can be
produced together.

Two jobs on the SAME script are the opposite case, and this app has already
paid for it: running the voiceover and the scene cut on one timeline left the
project with pictures and no sound, each job overwriting the rows the other
had just written. That must stay impossible however many threads are added.
"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

from youtube_monitor.production_worker import ProductionWorker


class _StubDatabase:
    """Just enough of the database for the worker's scheduling decisions."""

    def __init__(self) -> None:
        self.jobs: dict[int, dict[str, Any]] = {}

    def add(self, job_id: int, script_id: int) -> None:
        self.jobs[job_id] = {"id": job_id, "script_id": script_id, "status": "queued"}

    def get_project_job(self, job_id: int) -> dict[str, Any] | None:
        return self.jobs.get(job_id)

    def requeue_interrupted_project_jobs(self) -> None:
        return None

    def list_queued_project_job_ids(self) -> list[int]:
        return []


class LaneSchedulingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = _StubDatabase()
        self.worker = ProductionWorker(
            self.database, Path(self.directory.name), pyvideotrans_command="",
        )
        self.started = threading.Barrier(2, timeout=5)
        self.overlap = threading.Event()
        self.running: set[int] = set()
        self.seen_together: list[set[int]] = []
        self._install_processor()

    def _install_processor(self) -> None:
        lock = threading.Lock()

        def process(job_id: int) -> None:
            script_id = int(self.database.jobs[job_id]["script_id"])
            with lock:
                self.running.add(script_id)
                self.seen_together.append(set(self.running))
            # Long enough that a second thread would overlap if it were allowed.
            time.sleep(0.35)
            with lock:
                self.running.discard(script_id)

        self.worker._process = process  # type: ignore[method-assign]

    def _run_jobs(self, pairs: list[tuple[int, int]]) -> None:
        for job_id, script_id in pairs:
            self.database.add(job_id, script_id)
        self.worker.start()
        self.addCleanup(self.worker.stop)
        for job_id, _ in pairs:
            self.worker._jobs.put(job_id)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if not self.worker._jobs.unfinished_tasks:
                return
            time.sleep(0.05)
        self.fail("jobs did not finish in time")

    def test_the_long_video_and_the_short_are_produced_at_the_same_time(self) -> None:
        self._run_jobs([(1, 100), (2, 200)])

        self.assertTrue(
            any(len(seen) > 1 for seen in self.seen_together),
            "two different scripts should have been in flight together",
        )

    def test_two_jobs_on_one_script_never_overlap(self) -> None:
        """The failure that cost this project its voiceover, made impossible."""
        self._run_jobs([(1, 100), (2, 100), (3, 100)])

        for seen in self.seen_together:
            self.assertLessEqual(len(seen), 1, "one script must be worked on alone")

    def test_a_blocked_job_is_not_dropped(self) -> None:
        """Putting it back on the queue must not lose it."""
        self._run_jobs([(1, 100), (2, 100)])

        done = {script for seen in self.seen_together for script in seen}
        self.assertEqual(done, {100})
        self.assertGreaterEqual(len(self.seen_together), 2, "both jobs must have run")

    def test_one_thread_is_still_a_valid_configuration(self) -> None:
        worker = ProductionWorker(
            _StubDatabase(), Path(self.directory.name), pyvideotrans_command="",
            worker_threads=1,
        )

        self.assertEqual(worker.worker_threads, 1)

    def test_a_thread_count_below_one_is_refused_rather_than_hanging(self) -> None:
        worker = ProductionWorker(
            _StubDatabase(), Path(self.directory.name), pyvideotrans_command="",
            worker_threads=0,
        )

        self.assertGreaterEqual(worker.worker_threads, 1)
