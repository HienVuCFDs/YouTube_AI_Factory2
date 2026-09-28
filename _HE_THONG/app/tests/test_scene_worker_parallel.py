"""Several pictures at once, but never two on the same provider.

One picture at a time meant a six scene batch took six times one provider's
round trip - about five minutes of a thirteen minute run spent waiting in a
line of one. Running them all at once is not the answer either: the web
providers each drive a single Chrome profile, and two jobs sharing a profile
fight over it. So the queue is wide and each provider is a turnstile.
"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from youtube_monitor.scene_generator import SceneGenerationWorker


class _NoDatabase:
    """Enough of a Database for the worker to start and stop."""

    EXTERNAL_SIDECAR_PROVIDERS: tuple[str, ...] = ()

    def requeue_interrupted_scene_generation_jobs(self):
        return []

    def list_queued_scene_generation_job_ids(self, limit: int = 0):
        return []

    def recover_stale_scene_generation_jobs(self, _seconds):
        return []

    def scene_generation_queue_status(self):
        return {}


class _Worker(SceneGenerationWorker):
    """A worker whose `_process` only records when it ran and for how long."""

    def __init__(self, database, root, jobs_by_provider):
        super().__init__(database, root)
        self._jobs_by_provider = jobs_by_provider
        self.spans: list[tuple[str, float, float]] = []
        self._spans_lock = threading.Lock()

    def _process(self, job_id: int) -> None:
        provider = self._jobs_by_provider[job_id]
        started = time.monotonic()
        time.sleep(0.25)
        with self._spans_lock:
            self.spans.append((provider, started, time.monotonic()))


def _overlap(left, right) -> bool:
    return left[1] < right[2] and right[1] < left[2]


class RunningSeveralAtOnceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def _run(self, jobs_by_provider: dict[int, str]) -> list[tuple[str, float, float]]:
        worker = _Worker(_NoDatabase(), self.root, jobs_by_provider)
        worker.max_workers = 3
        with mock.patch.object(
            worker.database, "get_scene_generation_job",
            side_effect=lambda job_id: {"provider": jobs_by_provider[job_id]},
            create=True,
        ):
            worker.start()
            for job_id in jobs_by_provider:
                worker.enqueue(job_id)
            deadline = time.monotonic() + 10
            while len(worker.spans) < len(jobs_by_provider) and time.monotonic() < deadline:
                time.sleep(0.02)
            worker.stop()
        return worker.spans

    def test_two_providers_are_worked_at_the_same_time(self) -> None:
        spans = self._run({1: "gflow_image", 2: "meta_ai_image"})

        self.assertEqual(len(spans), 2)
        self.assertTrue(_overlap(spans[0], spans[1]), "different providers should overlap")

    def test_two_scenes_on_one_provider_take_turns(self) -> None:
        """Both would drive the same Chrome profile, and they would fight."""
        spans = self._run({1: "gflow_image", 2: "gflow_image"})

        self.assertEqual(len(spans), 2)
        self.assertFalse(_overlap(spans[0], spans[1]), "same provider must not overlap")

    def test_stopping_does_not_leave_a_thread_behind(self) -> None:
        worker = _Worker(_NoDatabase(), self.root, {})
        worker.max_workers = 3

        worker.start()
        self.assertEqual(worker.status()["worker_count"], 3)
        worker.stop()

        self.assertFalse(worker.status()["worker_running"])

    def test_starting_twice_does_not_double_the_threads(self) -> None:
        worker = _Worker(_NoDatabase(), self.root, {})
        worker.max_workers = 2
        self.addCleanup(worker.stop)

        worker.start()
        worker.start()

        self.assertEqual(worker.status()["worker_count"], 2)


if __name__ == "__main__":
    unittest.main()
