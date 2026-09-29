"""An analysis that takes minutes is the server's to report, not the page's.

Reloading the page dropped the request but not the work, and the page forgot
the work was going on: the button came back, and a second click started the
same analysis again. The run is now kept where it happens and read from there.
"""

from __future__ import annotations

import threading
import unittest
from unittest import mock

from fastapi import HTTPException


class AnAnalysisInProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient
        from youtube_monitor import main

        cls.main = main
        cls._client_cm = TestClient(main.app)
        cls.client = cls._client_cm.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)

    def setUp(self) -> None:
        project = self.main.database.create_idea_project("Thu nghiem phan tich dang chay", title="Step runs")
        self.project_id = int(project["id"])
        self.release = threading.Event()
        self.entered = threading.Event()

    def _analyze_row(self) -> dict:
        body = self.client.get(f"/api/projects/{self.project_id}/steps").json()
        return next(row for row in body["steps"] if row["key"] == "analyze")

    def _start(self, runner) -> threading.Thread:
        patcher = mock.patch.dict(self.main._STEP_RUNNERS, {"analyze": runner})
        patcher.start()
        self.addCleanup(patcher.stop)
        errors: list[BaseException] = []

        def work() -> None:
            try:
                self.main.run_project_step(self.project_id, "analyze", {})
            except HTTPException as exc:
                errors.append(exc)

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        self.assertTrue(self.entered.wait(5))
        self.addCleanup(self.release.set)
        return thread

    def _blocking(self, then=None):
        def runner(project_id, project, options):
            self.entered.set()
            self.release.wait(10)
            if then:
                then()
            return {"status": "analyzed", "result": {"content_summary": "x"}}
        return runner

    def test_the_run_is_readable_while_it_goes_on(self) -> None:
        thread = self._start(self._blocking())

        row = self._analyze_row()
        self.assertEqual(row["state"], "running")
        self.assertTrue(row["run"]["run_id"])
        self.assertTrue(row["run"]["started_at"])

        self.release.set()
        thread.join(5)
        row = self._analyze_row()
        self.assertNotEqual(row["state"], "running")
        self.assertIsNone(row["run"])
        self.assertEqual(row["last_run"]["status"], "success")
        self.assertTrue(row["last_run"]["finished_at"])

    def test_a_second_analysis_of_the_same_project_is_refused_while_one_runs(self) -> None:
        calls: list[int] = []
        runner = self._blocking()

        def counting(project_id, project, options):
            calls.append(project_id)
            return runner(project_id, project, options)

        thread = self._start(counting)

        response = self.client.post(f"/api/projects/{self.project_id}/steps/analyze", json={"options": {}})
        self.assertEqual(response.status_code, 409)
        self.assertIn("đang chạy", response.json()["detail"])
        self.assertEqual(calls, [self.project_id])

        self.release.set()
        thread.join(5)
        # Once it is over, analysing again is allowed.
        self.release.set()
        again = self.client.post(f"/api/projects/{self.project_id}/steps/analyze", json={"options": {}})
        self.assertEqual(again.status_code, 200)

    def test_a_failure_is_kept_with_its_reason_for_a_page_that_was_away(self) -> None:
        def fail() -> None:
            raise HTTPException(status_code=502, detail="Phân tích nguồn không chạy được: hết lượt")

        thread = self._start(self._blocking(then=fail))
        self.release.set()
        thread.join(5)

        row = self._analyze_row()
        self.assertIsNone(row["run"])
        self.assertEqual(row["last_run"]["status"], "failed")
        self.assertEqual(row["last_run"]["status_code"], 502)
        self.assertIn("hết lượt", row["last_run"]["error"])

    def test_other_projects_are_not_held_up(self) -> None:
        thread = self._start(self._blocking())
        other = int(self.main.database.create_idea_project("Du an khac", title="Other")["id"])

        body = self.client.get(f"/api/projects/{other}/steps").json()
        row = next(item for item in body["steps"] if item["key"] == "analyze")
        self.assertNotEqual(row["state"], "running")
        self.assertIsNone(row["run"])

        self.release.set()
        thread.join(5)


if __name__ == "__main__":
    unittest.main()
