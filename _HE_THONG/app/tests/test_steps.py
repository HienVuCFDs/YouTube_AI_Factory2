"""One list of steps, one implementation, whoever is driving.

The app grew a second copy of the pipeline inside the automatic run, which
wrote to the database directly with force=True and so skipped the checks the
manual path has to pass. These tests hold the shared description in place: the
order, what each step needs first, and which ones spend the user's quota.
"""

from __future__ import annotations

import unittest

from youtube_monitor import steps


class TheSharedListOfStepsTests(unittest.TestCase):
    def test_every_step_is_unique_and_named(self) -> None:
        keys = [step.key for step in steps.STEPS]
        self.assertEqual(len(keys), len(set(keys)))
        for step in steps.STEPS:
            self.assertTrue(step.label.strip(), step.key)

    def test_a_step_only_depends_on_steps_that_exist_and_come_earlier(self) -> None:
        """A requirement listed after its dependant would never be reachable."""
        seen: set[str] = set()
        for step in steps.STEPS:
            for need in step.requires:
                self.assertIn(need, seen, f"{step.key} cần {need} nhưng {need} đứng sau")
            seen.add(step.key)

    def test_the_steps_that_cost_money_are_declared(self) -> None:
        """Anything true here stays behind the confirmation policy, so the
        list is the thing that decides what may run unattended."""
        spending = {step.key for step in steps.STEPS if step.spends}

        self.assertEqual(spending, {"script", "voice", "media", "render", "publish"})

    def test_analysis_never_blocks_writing(self) -> None:
        """A project started from an idea has no source video to analyse, so
        requiring it would block that whole kind of project from being
        written at all."""
        self.assertEqual(steps.get("script").requires, ())
        self.assertEqual(steps.unmet_requirements("script", done=set()), [])

    def test_the_edit_plan_is_planned_after_the_voice_exists(self) -> None:
        """Overlay and SFX timing is planned against the length of each scene,
        and the voice overwrites that length the moment it is generated."""
        self.assertIn("voice", steps.get("edit_plan").requires)


class WhatIsStillMissingTests(unittest.TestCase):
    def test_unmet_requirements_name_what_to_do_first(self) -> None:
        missing = steps.unmet_requirements("voice", done={"analyze", "script"})

        self.assertEqual(missing, ["timeline"])

    def test_nothing_is_missing_once_the_requirement_is_done(self) -> None:
        self.assertEqual(steps.unmet_requirements("shots", done={"script"}), [])

    def test_an_unknown_step_reports_nothing_rather_than_guessing(self) -> None:
        self.assertEqual(steps.unmet_requirements("teleport", done=set()), [])


class PlanningAWholeRunTests(unittest.TestCase):
    def test_asking_for_the_render_on_an_empty_project_plans_the_whole_chain(self) -> None:
        """"Làm video từ link này" is one sentence, not a refusal."""
        plan = steps.plan_for("render", done=set())

        self.assertEqual(plan, ["script", "shots", "timeline", "render"])

    def test_work_already_done_is_not_planned_again(self) -> None:
        plan = steps.plan_for("render", done={"script", "shots", "timeline"})

        self.assertEqual(plan, ["render"])

    def test_the_plan_reaches_back_through_every_level(self) -> None:
        plan = steps.plan_for("edit_plan", done=set())

        self.assertEqual(plan, ["script", "shots", "timeline", "voice", "edit_plan"])
        self.assertLess(plan.index("voice"), plan.index("edit_plan"))


class ReadingTheStateOfAProjectTests(unittest.TestCase):
    def test_a_step_whose_turn_it_is_reads_as_ready(self) -> None:
        rows = {row["key"]: row for row in steps.describe(done={"script"})}

        self.assertEqual(rows["script"]["state"], "done")
        self.assertEqual(rows["shots"]["state"], "ready")
        self.assertEqual(rows["timeline"]["state"], "blocked")
        self.assertEqual(rows["timeline"]["missing"], ["shots"])

    def test_a_running_step_is_not_reported_as_ready_to_start(self) -> None:
        rows = {row["key"]: row for row in steps.describe(done={"analyze"}, running={"script"})}

        self.assertEqual(rows["script"]["state"], "running")

    def test_every_step_is_described_even_when_nothing_is_done(self) -> None:
        rows = steps.describe(done=set())

        self.assertEqual(len(rows), len(steps.STEPS))
        self.assertEqual(rows[0]["state"], "ready")


class TheSameDoorForEveryDriverTests(unittest.TestCase):
    """A button, the automatic run and an orchestrator all come through here."""

    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient
        from youtube_monitor.main import app, database

        cls._client_cm = TestClient(app)
        cls.client = cls._client_cm.__enter__()
        cls.database = database
        project = database.create_idea_project("Thu nghiem buoc lam video", title="Steps")
        cls.project_id = int(project["id"])

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)

    def test_the_state_of_every_step_is_readable(self) -> None:
        body = self.client.get(f"/api/projects/{self.project_id}/steps").json()

        keys = [row["key"] for row in body["steps"]]
        self.assertEqual(keys, list(steps.STEP_KEYS))
        by_key = {row["key"]: row for row in body["steps"]}
        self.assertEqual(by_key["script"]["state"], "ready")
        self.assertEqual(by_key["shots"]["state"], "blocked")
        self.assertEqual(by_key["shots"]["missing"], ["script"])

    def test_a_step_whose_turn_has_not_come_is_refused_with_the_reason(self) -> None:
        response = self.client.post(f"/api/projects/{self.project_id}/steps/voice", json={"options": {}})

        self.assertEqual(response.status_code, 409)
        self.assertIn("Chưa làm xong bước trước", response.json()["detail"])

    def test_the_refusal_is_written_into_the_one_log(self) -> None:
        """Whoever drove it, the run is on the record - that is the point of
        having one implementation."""
        before = len(self.database.list_orchestrator_steps(self.project_id))

        self.client.post(f"/api/projects/{self.project_id}/steps/render", json={"options": {}})

        rows = self.database.list_orchestrator_steps(self.project_id)
        self.assertEqual(len(rows), before + 1)
        self.assertEqual(rows[-1]["status"], "refused")
        self.assertIn("run_step(render)", rows[-1]["why"])

    def test_an_unknown_step_says_which_ones_exist(self) -> None:
        response = self.client.post(f"/api/projects/{self.project_id}/steps/teleport", json={"options": {}})

        self.assertEqual(response.status_code, 400)
        self.assertIn("timeline", response.json()["detail"])

    def test_an_unknown_project_is_a_404(self) -> None:
        self.assertEqual(self.client.get("/api/projects/99999999/steps").status_code, 404)


class EveryStepCanActuallyRunTests(unittest.TestCase):
    """A step declared but not wired reads as available and then refuses."""

    def test_no_step_is_advertised_without_something_behind_it(self) -> None:
        from youtube_monitor.main import _STEP_RUNNERS

        self.assertEqual(set(steps.STEP_KEYS), set(_STEP_RUNNERS))


class ResearchKeepsWhatItFoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from youtube_monitor.main import database

        cls.database = database
        project = database.create_idea_project("Lich su tri tue nhan tao", title="Research")
        cls.project_id = int(project["id"])

    def test_the_findings_are_stored_with_the_project(self) -> None:
        """The writer two steps later should see what was actually found,
        instead of being told to research and trusted not to invent."""
        from unittest.mock import patch

        from youtube_monitor.main import run_project_step

        found = [{"title": "AI", "snippet": "1956", "url": "https://x.test/a", "source": "x.test"}]
        with patch("youtube_monitor.main.web_research.search", return_value=found):
            body = run_project_step(self.project_id, "research", {"query": "trí tuệ nhân tạo"})

        result = body["result"]
        self.assertTrue(result["researched"])
        self.assertEqual(result["result_count"], 1)
        self.assertTrue(result["artifact_id"])

    def test_finding_nothing_is_reported_as_nothing(self) -> None:
        from unittest.mock import patch

        from youtube_monitor.main import run_project_step

        with patch("youtube_monitor.main.web_research.search", return_value=[]):
            result = run_project_step(self.project_id, "research", {"query": "abc"})["result"]

        self.assertFalse(result["researched"])
        self.assertEqual(result["result_count"], 0)

    def test_a_project_with_nothing_to_research_says_so(self) -> None:
        """Rather than searching for an empty string and reporting success."""
        from fastapi import HTTPException

        from youtube_monitor.main import _step_research

        with self.assertRaises(HTTPException) as raised:
            _step_research(self.project_id, {"id": self.project_id}, {})

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("chủ đề", str(raised.exception.detail))


class PublishingNeedsToBeAskedForTests(unittest.TestCase):
    """The one step that cannot be undone from inside the app."""

    @classmethod
    def setUpClass(cls) -> None:
        from youtube_monitor.main import database

        project = database.create_idea_project("Kiem tra xuat ban", title="Publish")
        cls.project_id = int(project["id"])

    def test_without_the_word_it_only_checks(self) -> None:
        from unittest.mock import patch

        from youtube_monitor.main import run_project_step

        with patch("youtube_monitor.main.project_publish_checklist", return_value={"ok": True}), \
                patch("youtube_monitor.main.queue_project_publication") as publish:
            result = run_project_step(self.project_id, "publish", {"force": True})["result"]

        publish.assert_not_called()
        self.assertFalse(result["published"])
        self.assertEqual(result["status"], "checked")

    def test_the_spending_confirmation_does_not_unlock_publishing(self) -> None:
        """Nothing should reach a channel because a caller passed the flag
        that unlocks paying for a render."""
        from unittest.mock import patch

        from youtube_monitor.main import run_project_step

        with patch("youtube_monitor.main.project_publish_checklist", return_value={"ok": True}), \
                patch("youtube_monitor.main.queue_project_publication") as publish:
            run_project_step(self.project_id, "publish", {"force": True, "confirmed": True})

        publish.assert_not_called()

    def test_asking_in_the_right_words_publishes(self) -> None:
        from unittest.mock import patch

        from youtube_monitor.main import run_project_step

        with patch("youtube_monitor.main.project_publish_checklist", return_value={"ok": True}), \
                patch("youtube_monitor.main.queue_project_publication", return_value={"id": 5}) as publish:
            result = run_project_step(
                self.project_id, "publish", {"force": True, "confirmed_publish": True},
            )["result"]

        publish.assert_called_once()
        self.assertTrue(result["published"])


if __name__ == "__main__":
    unittest.main()


class CatchingAWrongTurnEarlyTests(unittest.TestCase):
    """Three guards, all for the same reason: a step that accepts nonsense
    hands it to eleven steps that believe it, and each one costs more to
    undo than the check would have cost to run."""

    def test_a_topic_that_is_not_in_the_video_is_not_about_the_video(self) -> None:
        """An analysis came back with the topic "com" - a fragment of the
        source URL - and the research, the script and nine scenes of pictures
        were all made about nothing."""
        from youtube_monitor.main import analysis_is_about_the_source

        video = {"title": "Trái Đất được tạo ra như thế nào??", "description": ""}
        transcript = "hành tinh của chúng ta hình thành từ tinh vân mặt trời"

        self.assertFalse(analysis_is_about_the_source({"topic": "com"}, video, transcript))
        self.assertFalse(analysis_is_about_the_source({"topic": ""}, video, transcript))
        self.assertFalse(analysis_is_about_the_source({"topic": "Bóng đá Anh"}, video, transcript))

    def test_a_topic_drawn_from_the_video_passes(self) -> None:
        from youtube_monitor.main import analysis_is_about_the_source

        video = {"title": "Trái Đất được tạo ra như thế nào??", "description": ""}
        transcript = "hành tinh của chúng ta hình thành từ tinh vân mặt trời"

        self.assertTrue(analysis_is_about_the_source({"topic": "Trái Đất"}, video, transcript))
        self.assertTrue(
            analysis_is_about_the_source({"topic": "sự hình thành hành tinh"}, video, transcript)
        )

    def test_a_script_the_app_judged_unfit_does_not_reach_the_spending(self) -> None:
        from unittest.mock import patch

        from fastapi import HTTPException

        from youtube_monitor.main import _refuse_a_script_that_failed_review, database, settings

        project = database.create_idea_project("Chu de", title="Review gate")
        project_id = int(project["id"])
        script = database.create_project_script(project_id, script_title="Yeu", main_content="x")
        database.save_script_review(int(script["id"]), 4, "Lời dẫn rời rạc", "astra")

        with patch.object(settings, "automation_policy", return_value={"min_review_score": 8}):
            with self.assertRaises(HTTPException) as raised:
                _refuse_a_script_that_failed_review(project_id)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("4/10", raised.exception.detail)

    def test_a_script_nobody_reviewed_is_still_allowed_through(self) -> None:
        """Review is not compulsory; only failing one is disqualifying."""
        from unittest.mock import patch

        from youtube_monitor.main import _refuse_a_script_that_failed_review, database, settings

        project = database.create_idea_project("Chu de", title="Review gate 2")
        project_id = int(project["id"])
        database.create_project_script(project_id, script_title="Chua duyet", main_content="x")

        with patch.object(settings, "automation_policy", return_value={"min_review_score": 8}):
            _refuse_a_script_that_failed_review(project_id)

    def test_a_passing_score_goes_through(self) -> None:
        from unittest.mock import patch

        from youtube_monitor.main import _refuse_a_script_that_failed_review, database, settings

        project = database.create_idea_project("Chu de", title="Review gate 3")
        project_id = int(project["id"])
        script = database.create_project_script(project_id, script_title="Tot", main_content="x")
        database.save_script_review(int(script["id"]), 9, "Ổn", "astra")

        with patch.object(settings, "automation_policy", return_value={"min_review_score": 8}):
            _refuse_a_script_that_failed_review(project_id)
