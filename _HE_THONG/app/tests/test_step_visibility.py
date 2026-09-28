"""Looking at the work, and saying out loud that it is happening.

Two gaps that only show up from outside the app. A task that needs eyes was
routed like any other, so a text-only runtime could take it and answer
confidently about a picture it never saw. And a step wrote its progress to a
table only this app reads, so anything watching from elsewhere - the page, and
later a chat channel relaying a request - saw nothing for the three minutes the
planner takes and could not tell work from a hang.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from youtube_monitor import main as main_module


class OnlyRuntimesWithEyesTakeALookingTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.sheet = Path(self._dir.name) / "sheet.jpg"
        self.sheet.write_bytes(b"jpeg")

    def test_a_task_with_a_picture_never_reaches_a_text_only_runtime(self) -> None:
        """Antigravity cannot be shown an image. Falling back to it would not
        fail - it would describe a picture it was never given."""
        seen: list[str] = []

        def vision(system, user, schema, image_path=None, **kwargs):
            seen.append("vision")
            return {"topic": "ok"}

        with mock.patch.object(main_module, "call_codex_vision_json", side_effect=vision), \
                mock.patch.object(main_module, "call_antigravity_json") as blind, \
                mock.patch.object(main_module.settings, "agent_assignment", return_value={
                    "mode": "fixed", "executor": "antigravity",
                    "allowed_agents": ["antigravity", "astra"], "fallback_agents": [], "reviewer": "auto",
                }):
            with self.assertRaises(Exception):
                main_module._call_orchestrator_json(
                    "s", "u", {"type": "object"}, image_path=self.sheet,
                )

        blind.assert_not_called()

    def test_without_a_picture_every_runtime_is_still_eligible(self) -> None:
        with mock.patch.object(main_module, "call_antigravity_json", return_value={"topic": "ok"}) as blind, \
                mock.patch.object(main_module.settings, "agent_assignment", return_value={
                    "mode": "fixed", "executor": "antigravity",
                    "allowed_agents": ["antigravity"], "fallback_agents": [], "reviewer": "auto",
                }):
            result = main_module._call_orchestrator_json("s", "u", {"type": "object"})

        blind.assert_called_once()
        self.assertEqual(result["topic"], "ok")

    def test_a_path_that_is_not_on_disk_is_not_treated_as_a_picture(self) -> None:
        with mock.patch.object(main_module, "call_antigravity_json", return_value={"topic": "ok"}) as blind, \
                mock.patch.object(main_module.settings, "agent_assignment", return_value={
                    "mode": "fixed", "executor": "antigravity",
                    "allowed_agents": ["antigravity"], "fallback_agents": [], "reviewer": "auto",
                }):
            main_module._call_orchestrator_json(
                "s", "u", {"type": "object"}, image_path=Path(self._dir.name) / "gone.jpg",
            )

        blind.assert_called_once()


class AStepSaysWhatItIsDoingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        project = main_module.database.create_idea_project("Chu de", title="Events")
        cls.project_id = int(project["id"])

    def _events(self, calls) -> list[str]:
        return [call.args[0] for call in calls.call_args_list]

    def test_the_announcement_actually_reaches_the_event_log(self) -> None:
        """Mocking the emitter proves the call was made, not that anything
        listens. The bus takes a fixed set of keyword arguments and rejects
        the rest, so loose keywords raised a TypeError this code caught and
        discarded - the app looked like it was announcing and was not."""
        before = main_module.event_bus.history(project_id=self.project_id, limit=200)

        with mock.patch.dict(main_module._STEP_RUNNERS, {"research": lambda *a, **k: {"ok": True}}):
            main_module.run_project_step(self.project_id, "research", {})

        after = main_module.event_bus.history(project_id=self.project_id, limit=200)
        fresh = [event.as_dict() for event in after[len(before):]]
        kinds = [event["event_type"] for event in fresh]

        self.assertIn("step.started", kinds)
        self.assertIn("step.finished", kinds)
        finished = next(event for event in fresh if event["event_type"] == "step.finished")
        self.assertEqual(finished["payload"]["step"], "research")
        self.assertIn("seconds", finished["payload"])

    def test_starting_and_finishing_are_both_announced(self) -> None:
        with mock.patch.dict(main_module._STEP_RUNNERS, {"research": lambda *a, **k: {"ok": True}}), \
                mock.patch.object(main_module.database, "emit_domain_event") as announced:
            main_module.run_project_step(self.project_id, "research", {})

        self.assertEqual(self._events(announced), ["step.started", "step.finished"])

    def test_a_failure_is_announced_too(self) -> None:
        """Otherwise a watcher cannot tell a failure from a step still running."""
        from fastapi import HTTPException

        def explode(*args, **kwargs):
            raise HTTPException(status_code=400, detail="hỏng")

        with mock.patch.dict(main_module._STEP_RUNNERS, {"research": explode}), \
                mock.patch.object(main_module.database, "emit_domain_event") as announced:
            with self.assertRaises(HTTPException):
                main_module.run_project_step(self.project_id, "research", {})

        self.assertEqual(self._events(announced), ["step.started", "step.failed"])

    def test_a_refusal_is_announced_without_pretending_the_step_ran(self) -> None:
        with mock.patch.object(main_module.database, "emit_domain_event") as announced:
            with self.assertRaises(Exception):
                main_module.run_project_step(self.project_id, "render", {"confirmed": False})

        self.assertEqual(self._events(announced), ["step.refused"])

    def test_announcing_never_costs_the_step_its_result(self) -> None:
        with mock.patch.dict(main_module._STEP_RUNNERS, {"research": lambda *a, **k: {"ok": True}}), \
                mock.patch.object(
                    main_module.database, "emit_domain_event", side_effect=RuntimeError("event log down"),
                ):
            body = main_module.run_project_step(self.project_id, "research", {})

        self.assertTrue(body["result"]["ok"])


class TheTranscriberFallsBackRatherThanStopsTests(unittest.TestCase):
    def test_a_model_that_will_not_load_is_followed_by_a_smaller_one(self) -> None:
        """On a card with little free memory the accurate model fails to
        allocate. A rougher transcript is worth more than a run that stops."""
        from youtube_monitor import transcriber

        tried: list[str] = []

        class Loader:
            def __init__(self, name, device=None, compute_type=None):
                tried.append(name)
                if name != "small":
                    raise RuntimeError("out of memory")

        transcriber._model_cache.clear()
        with mock.patch.dict("sys.modules", {"faster_whisper": mock.MagicMock(WhisperModel=Loader)}), \
                mock.patch.object(transcriber, "resolve_whisper_runtime", return_value=("cuda", "float16")):
            transcriber._get_model("large-v3")

        self.assertEqual(tried[0], "large-v3")
        self.assertEqual(tried[-1], "small")
        transcriber._model_cache.clear()

    def test_nothing_loading_at_all_is_reported_plainly(self) -> None:
        from youtube_monitor import transcriber

        class Loader:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("out of memory")

        transcriber._model_cache.clear()
        with mock.patch.dict("sys.modules", {"faster_whisper": mock.MagicMock(WhisperModel=Loader)}), \
                mock.patch.object(transcriber, "resolve_whisper_runtime", return_value=("cuda", "float16")):
            with self.assertRaises(transcriber.TranscriptionError):
                transcriber._get_model("large-v3")
        transcriber._model_cache.clear()


if __name__ == "__main__":
    unittest.main()
