"""The Media Agent must say what a scene needs, not only how long it runs.

A real run routed a scene about backing up data to the open-footage
provider, which scored 1/10: no archive holds footage of a concept, and an
image model asked for a chart invents the numbers on it.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

import pytest

from youtube_monitor import main

PAGE = Path(__file__).resolve().parent.parent / "youtube_monitor" / "templates" / "index.html"


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


class MediaSchemaTests(unittest.TestCase):
    def test_the_agent_must_state_a_treatment(self) -> None:
        item = main._AGENT_MEDIA_SCHEMA["properties"]["scenes"]["items"]
        self.assertIn("treatment", item["properties"])
        self.assertIn("treatment", item["required"])

    def test_the_three_treatments_are_the_ones_routing_understands(self) -> None:
        item = main._AGENT_MEDIA_SCHEMA["properties"]["scenes"]["items"]
        self.assertEqual(
            set(item["properties"]["treatment"]["enum"]),
            {"real_world", "data_graphics", "illustration"},
        )

    def test_qc_scores_are_explicitly_on_a_ten_point_scale(self) -> None:
        for schema in (main._AGENT_QC_SCHEMA, main._AGENT_REVIEW_SCHEMA):
            score = schema["properties"]["score"]
            self.assertEqual(score["minimum"], 0)
            self.assertEqual(score["maximum"], 10)

    def test_qc_only_judges_the_latest_attempt_for_each_scene(self) -> None:
        jobs = [
            {"id": 8, "timeline_segment_id": 10, "review_status": "pass"},
            {"id": 7, "timeline_segment_id": 10, "review_status": "fail"},
            {"id": 6, "timeline_segment_id": 11, "review_status": "fail"},
        ]
        latest = main._latest_scene_jobs_by_segment(jobs)
        self.assertEqual({int(item["id"]) for item in latest}, {8, 6})
        self.assertEqual(
            [int(item["id"]) for item in latest if item["review_status"] == "fail"],
            [6],
        )


class MediaRoutingByTreatmentTests(unittest.TestCase):
    def _run_media(self, scenes: list[dict], timeline: list[dict]) -> dict:
        routes: list[dict] = []

        def fake_route(capability, provider_states=None, policy=None):
            routes.append({"capability": capability, "preferred": policy.preferred})
            selected = mock.Mock()
            selected.key = (policy.preferred or ("gflow_cli",))[0]
            selected.estimated_unit_cost = 0
            return mock.Mock(selected=selected, candidates=[], reason="test")

        task = {"project_id": 1, "role": "media", "input": {"pipeline": {}}, "correlation_id": ""}
        with mock.patch.object(main, "_call_specific_agent_json", return_value={"scenes": scenes}):
            with mock.patch.object(main.database, "get_production_project", return_value={"id": 1, "title": "T"}):
                with mock.patch.object(main.database, "get_latest_project_script", return_value={"id": 1}):
                    with mock.patch.object(main.database, "list_project_timeline", return_value=timeline):
                        with mock.patch.object(main.database, "set_segment_visual_kind"):
                            with mock.patch.object(main.database, "record_provider_route", return_value={"id": 1}):
                                with mock.patch.object(main.scene_provider_gateway, "route", side_effect=fake_route):
                                    with mock.patch.object(main, "_provider_runtime_states", return_value={}):
                                        result = main._execute_agent_task(task, "codex_cli")
        return {"result": result, "routes": routes}

    def _timeline(self) -> list[dict]:
        return [{"id": 7, "voice_text": "loi thoai", "visual_prompt": "mo ta", "duration_seconds": 6}]

    def test_a_concept_scene_is_drawn_rather_than_searched_for(self) -> None:
        scenes = [{"segment_id": 7, "kind": "image", "treatment": "data_graphics", "reason": "khai niem"}]
        outcome = self._run_media(scenes, self._timeline())
        route = outcome["routes"][0]
        # Forced to video: motion graphics is the only capability that draws.
        self.assertEqual(route["capability"], main.SCENE_VIDEO)
        self.assertEqual(route["preferred"], ("motion_graphics",))
        self.assertEqual(outcome["result"]["assignments"][0]["provider"], "motion_graphics")

    def test_a_real_world_scene_prefers_real_footage(self) -> None:
        scenes = [{"segment_id": 7, "kind": "video", "treatment": "real_world", "reason": "co that"}]
        outcome = self._run_media(scenes, self._timeline())
        self.assertEqual(outcome["routes"][0]["preferred"], ("stock_footage", "gflow_cli"))

    def test_an_illustration_scene_leaves_the_choice_to_the_gateway(self) -> None:
        scenes = [{"segment_id": 7, "kind": "image", "treatment": "illustration", "reason": "ve minh hoa"}]
        outcome = self._run_media(scenes, self._timeline())
        route = outcome["routes"][0]
        self.assertEqual(route["capability"], main.SCENE_IMAGE)
        self.assertEqual(route["preferred"], ())

    def test_the_treatment_is_recorded_so_a_bad_call_can_be_traced(self) -> None:
        scenes = [{"segment_id": 7, "kind": "video", "treatment": "real_world", "reason": "co that"}]
        outcome = self._run_media(scenes, self._timeline())
        self.assertEqual(outcome["result"]["assignments"][0]["treatment"], "real_world")

    def test_a_missing_treatment_does_not_break_the_scene(self) -> None:
        scenes = [{"segment_id": 7, "kind": "image", "reason": "khong khai"}]
        outcome = self._run_media(scenes, self._timeline())
        self.assertEqual(outcome["result"]["assignments"][0]["treatment"], "illustration")


def test_the_prompt_teaches_the_rule_the_run_discovered(page: str) -> None:
    source = (Path(__file__).resolve().parent.parent / "youtube_monitor" / "main.py").read_text(encoding="utf-8")
    assert "data_graphics" in source
    assert "bịa ra số liệu sai" in source


def test_connections_covers_the_browser_the_web_providers_run_in() -> None:
    """Four scene providers run inside the logged-in browser and Connections
    had no card for it, so there was nowhere to see why one was unusable."""
    from fastapi.testclient import TestClient
    from youtube_monitor.main import app

    with TestClient(app) as client:
        keys = {item["key"] for item in client.get("/api/integrations").json()}
    assert "browser_extension" in keys
    assert "antigravity_sidecar" in keys


def test_the_sidecar_card_is_separate_from_the_cli_login() -> None:
    """Being logged in is not the same as pulling work."""
    from fastapi.testclient import TestClient
    from youtube_monitor.main import app

    with TestClient(app) as client:
        items = {item["key"]: item for item in client.get("/api/integrations").json()}
    with mock.patch.object(main, "_sidecar_recently_polled", return_value=False):
        with TestClient(app) as client:
            fresh = {item["key"]: item for item in client.get("/api/integrations").json()}
    assert fresh["antigravity_sidecar"]["ready"] is False
    assert items["antigravity_cli"]["connection"] != fresh["antigravity_sidecar"]["connection"]


class PlaywrightSidecarCountsAsAWorkerTests(unittest.TestCase):
    """The extension is one way to drive a logged-in site, not the only way.

    web_video_sidecar.py drives the same sites with Playwright and its own
    saved session, and pulls from the same queue. Asking only whether the
    extension was connected declared four providers dead while their sidecar
    was working.
    """

    def _states(self, polled: tuple[str, ...] = ()) -> dict:
        from datetime import datetime, timezone

        seen = {name: datetime.now(timezone.utc) for name in polled}
        with mock.patch.dict(main._sidecar_last_seen, seen, clear=True):
            with mock.patch.object(main, "_browser_extension_connections", 0):
                return main._provider_runtime_states()

    def test_a_polling_playwright_sidecar_makes_its_provider_usable(self) -> None:
        states = self._states(("chatgpt_web_image",))
        self.assertTrue(states["chatgpt_web_image"]["available"])

    def test_it_does_not_vouch_for_a_provider_with_no_worker(self) -> None:
        states = self._states(("chatgpt_web_image",))
        self.assertFalse(states["gemini_web_image"]["available"])
        self.assertEqual(states["gemini_web_image"]["reason"], "no_browser_worker")

    def test_with_no_worker_flow_image_is_told_the_extension_is_its_only_route(self) -> None:
        """The poll signal is shared: the extension claims jobs through the
        same endpoint the Playwright sidecar does. So a poll for flow_image
        already means something is driving it. What differs is the advice
        when nothing is — only flow_image has no Playwright entry to fall
        back on."""
        states = self._states()
        self.assertEqual(states["flow_image"]["reason"], "browser_extension_not_connected")
        self.assertEqual(states["flow_veo"]["reason"], "no_browser_worker")

    def test_the_extension_alone_still_works(self) -> None:
        with mock.patch.dict(main._sidecar_last_seen, {}, clear=True):
            with mock.patch.object(main, "_browser_extension_connections", 1):
                states = main._provider_runtime_states()
        self.assertTrue(states["flow_image"]["available"])
        self.assertTrue(states["flow_veo"]["available"])

    def test_the_playwright_list_matches_what_the_sidecar_can_drive(self) -> None:
        source = (
            Path(__file__).resolve().parent.parent
            / "youtube_monitor" / "web_video_sidecar.py"
        ).read_text(encoding="utf-8")
        import re

        configured = set(re.findall(r'^ +"([a-z_]+)": *ProviderConfig', source, re.M))
        self.assertEqual(configured, set(main.PLAYWRIGHT_SIDECAR_PROVIDERS))


def test_the_page_offers_both_ways_to_drive_a_web_provider(page: str) -> None:
    assert "no_browser_worker" in page
    assert "web_video_sidecar.py" in page


def test_the_new_cards_have_something_to_render_them(page: str) -> None:
    assert "item.connection === 'browser_extension'" in page
    assert "item.connection === 'sidecar'" in page


def test_the_page_shows_the_event_log_and_the_a2a_handoffs(page: str) -> None:
    assert 'id="automationEvents"' in page
    assert 'id="automationMessages"' in page
    assert "renderAutomationTrace(data);" in page


def test_the_page_explains_why_a_provider_is_locked(page: str) -> None:
    assert 'id="providerCatalogPanel"' in page
    assert "/api/providers/catalog" in page
    for reason in (
        "gflow_not_logged_in",
        "browser_extension_not_connected",
        "antigravity_sidecar_not_running",
        "missing_api_key",
    ):
        assert reason in page


if __name__ == "__main__":
    unittest.main()
