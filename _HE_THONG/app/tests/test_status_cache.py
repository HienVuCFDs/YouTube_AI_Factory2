"""A status check must not make the page wait for a subprocess.

Asking whether a CLI is logged in means launching it, which costs one to
twenty seconds. Six polled endpoints ask for those statuses, so a plain TTL
still made whichever request landed on the expiry pay the whole probe —
several at once, each holding a worker thread. Health took seven to eleven
seconds and changing one dropdown took longer than the work it configured.
"""

from __future__ import annotations

import subprocess
import threading
import time
import unittest
from unittest import mock

from youtube_monitor import antigravity_bridge
from youtube_monitor.status_cache import BackgroundStatus


class BackgroundStatusTests(unittest.TestCase):
    def test_the_first_caller_waits_because_there_is_nothing_to_serve(self) -> None:
        probe = mock.Mock(return_value={"ok": True})
        cache = BackgroundStatus(probe, ttl_seconds=10)
        self.assertEqual(cache.get(), {"ok": True})
        probe.assert_called_once()

    def test_a_fresh_value_is_served_without_probing_again(self) -> None:
        probe = mock.Mock(return_value={"ok": True})
        cache = BackgroundStatus(probe, ttl_seconds=10)
        cache.get()
        cache.get()
        cache.get()
        probe.assert_called_once()

    def test_an_expired_value_is_still_returned_at_once(self) -> None:
        """This is the whole point: staleness must not cost the caller time."""
        started = threading.Event()
        release = threading.Event()

        def slow_probe():
            started.set()
            release.wait(timeout=5)
            return {"generation": 2}

        cache = BackgroundStatus(slow_probe, ttl_seconds=0.01)
        cache._value = {"generation": 1}
        cache._fetched_at = time.monotonic() - 10
        begin = time.monotonic()
        served = cache.get()
        elapsed = time.monotonic() - begin
        self.assertEqual(served, {"generation": 1})
        self.assertLess(elapsed, 0.5)
        self.assertTrue(started.wait(timeout=5))
        release.set()

    def test_only_one_refresh_runs_at_a_time(self) -> None:
        release = threading.Event()
        calls: list[int] = []

        def slow_probe():
            calls.append(1)
            release.wait(timeout=5)
            return {"n": len(calls)}

        cache = BackgroundStatus(slow_probe, ttl_seconds=0.01)
        cache._value = {"n": 0}
        cache._fetched_at = time.monotonic() - 10
        for _ in range(5):
            cache.get()
        release.set()
        time.sleep(0.2)
        self.assertEqual(len(calls), 1)

    def test_force_waits_for_the_truth(self) -> None:
        probe = mock.Mock(side_effect=[{"n": 1}, {"n": 2}])
        cache = BackgroundStatus(probe, ttl_seconds=100)
        self.assertEqual(cache.get(), {"n": 1})
        self.assertEqual(cache.get(force=True), {"n": 2})

    def test_a_failing_refresh_keeps_serving_the_last_good_answer(self) -> None:
        cache = BackgroundStatus(mock.Mock(side_effect=RuntimeError("het gio")), ttl_seconds=0.01)
        cache._value = {"n": 1}
        cache._fetched_at = time.monotonic() - 10
        self.assertEqual(cache.get(), {"n": 1})
        time.sleep(0.2)
        self.assertEqual(cache.get(), {"n": 1})
        self.assertFalse(cache._refreshing)


class AntigravityProbeTests(unittest.TestCase):
    def test_a_cli_that_never_answers_is_reported_not_raised(self) -> None:
        """It reached the page as a 500 on what is only a status check."""
        with mock.patch.object(antigravity_bridge.settings, "ANTIGRAVITY_CLI_PATH", __file__):
            with mock.patch.object(
                antigravity_bridge.subprocess, "run",
                side_effect=subprocess.TimeoutExpired(cmd="agy", timeout=20),
            ):
                status = antigravity_bridge._antigravity_cli_status_uncached()
        self.assertFalse(status["logged_in"])
        self.assertIn("khong tra loi", status["detail"])

    def test_the_status_is_served_through_the_background_cache(self) -> None:
        self.assertIsInstance(antigravity_bridge._status, BackgroundStatus)


if __name__ == "__main__":
    unittest.main()
