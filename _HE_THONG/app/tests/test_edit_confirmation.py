"""Bước 05 · T4 phương án B: an EditDocument reaches the timeline only as the version a person confirmed.

* A new plan (or a plan changed since) is kept, never applied - by planning, by a sync, a reconcile or a rebuild.
* "Áp dụng vào timeline…" confirms the very version shown (its document_hash): it plans nothing; a version that
  changed since it was shown is not applied; the confirmed one is, under the rules of any apply (T6b conflicts).
* A person's own edit (T6a, a resolve, the cleanups) on a confirmed version is that person's word for the new one.
  T6a still applies its own scene at once, as it always did.

Every test runs on the test suite's temporary database (tests/conftest.py), fake models, no app, no worker.
"""

from __future__ import annotations

import json

from tests.test_edit_manual_document import _SceneEditCase
from youtube_monitor import main
from youtube_monitor.database import EDIT_APPLY_KIND


class _ConfirmCase(_SceneEditCase):
    def setUp(self) -> None:
        super().setUp()
        self.target = int(self._segments()[0]["id"])

    def _layers_now(self) -> list:
        return [(row["id"], row["edit_transition"], row["edit_note"], row["overlays"]) for row in self._segments()]

    def _plan_only(self, **options) -> dict:
        response = self.client.post(f"/api/projects/{self.project_id}/steps/edit_plan", json={"options": options})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["result"]


class UnconfirmedTests(_ConfirmCase):
    def test_a_new_plan_is_kept_and_nothing_applies_it_until_it_is_confirmed(self) -> None:
        before = self._layers_now()
        self._plan_only()
        read = self._edit_document()
        self.assertFalse(read["confirmed"])
        for door in (lambda: self.client.post(f"/api/projects/{self.project_id}/timeline/generate", json={}).json(),
                     lambda: self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={}).json(),
                     lambda: main.run_project_step(self.project_id, "timeline", {})["result"]):
            answer = door()
            self.assertEqual(answer["edit_document"]["status"], main.NEEDS_CONFIRMATION)
        self.assertEqual(self._layers_now(), before)
        self.assertEqual(self._count(EDIT_APPLY_KIND), 0)
        self.assertIn("edit_not_applied", {item["code"] for item in main._render_blockers(self.project_id, self.script_id)})

    def test_a_confirmation_without_a_version_or_with_another_applies_nothing(self) -> None:
        self._plan_only()
        before = self._layers_now()
        for shown in (None, "khong-phai-phien-ban-nay"):
            with self.subTest(shown=shown):
                applied = self._plan_only(confirmed_apply=True, **({"document_hash": shown} if shown else {}))["applied"]
                self.assertEqual(applied["status"], main.NEEDS_CONFIRMATION)
        self.assertEqual(self._layers_now(), before)
        self.assertFalse(self._edit_document()["confirmed"])


class ConfirmedTests(_ConfirmCase):
    def test_the_version_shown_is_confirmed_and_applied_and_a_sync_of_it_applies_it(self) -> None:
        self._plan_only()
        shown = self._edit_document()["document_hash"]
        applied = self._confirm(shown)["applied"]
        self.assertEqual(applied["status"], "applied")
        self.assertTrue(self._edit_document()["confirmed"])
        again = self.client.post(f"/api/projects/{self.project_id}/timeline/generate", json={}).json()["edit_document"]
        self.assertEqual(again["status"], "unchanged")
        edit_codes = {"edit_not_applied", "conflict", "stale_layers", "edit_document_outdated"}
        self.assertEqual([item for item in main._render_blockers(self.project_id, self.script_id) if item["code"] in edit_codes],
                         [], "the confirmed plan is on the rows")

    def test_a_confirmation_plans_nothing_the_person_has_not_seen(self) -> None:
        self._sync(self.project_id, self.script_id)                                 # an EditDocument, nothing planned
        self._plan_only(scene_keys=[self._scene_of(self.target)["scene_key"]])     # one scene planned, others not
        calls = len(self.director.calls)
        result = self._confirm()
        self.assertEqual(len(self.director.calls), calls, "no model call")
        self.assertEqual(result["planned"], [])
        self.assertEqual(result["applied"]["status"], "applied")
        planned = {scene["segment_id"] for scene in self._edit_document()["scenes"] if scene["applied"] == "applied"}
        self.assertEqual(planned, {self.target}, "only what was planned and shown")

    def test_a_version_changed_after_the_confirmation_waits_for_its_own(self) -> None:
        self._plan_only()
        first = self._edit_document()["document_hash"]
        self._confirm(first)
        applied_now = self._layers_now()
        self._plan_only(scene_keys=[self._scene_of(self.target)["scene_key"]], replan=True)   # a new version
        second = self._edit_document()["document_hash"]
        self.assertNotEqual(second, first)
        self.assertFalse(self._edit_document()["confirmed"], "the old confirmation is not the new version's")
        sync = self.client.post(f"/api/projects/{self.project_id}/timeline/generate", json={}).json()["edit_document"]
        self.assertEqual(sync["status"], main.NEEDS_CONFIRMATION)
        self.assertEqual(self._confirm(first)["applied"]["status"], main.NEEDS_CONFIRMATION, "the old version is not the one now")
        self.assertEqual(self._layers_now(), applied_now, "nothing of the new version reached the rows")
        self.assertIn(self._confirm(second)["applied"]["status"], ("applied", "unchanged"))
        self.assertTrue(self._edit_document()["confirmed"])

    def test_a_confirmed_plan_never_writes_over_a_hand_edit(self) -> None:
        self._plan_only()
        with self._outside():
            self._patch_plan(self.target, overlays=[{"kind": "text", "text": "Chữ sửa tay", "start_seconds": 0.0, "end_seconds": 1.0}])
        held = self._overlays(self.target)
        applied = self._confirm()["applied"]
        self.assertEqual(applied["status"], "partial")
        self.assertIn(self.target, [item["segment_id"] for item in applied["conflicts"]])
        self.assertEqual(self._overlays(self.target), held)


class PersonsOwnEditTests(_ConfirmCase):
    def test_t6a_still_applies_its_scene_only_and_never_the_unconfirmed_others(self) -> None:
        self._plan_only()
        before = {row["id"]: row for row in self._segments()}
        answer = self._put(self._scene_of(self.target)["scene_key"], {"transition": "fade"})
        self.assertEqual(answer["status"], "applied")
        self.assertEqual(self._seg(self.target)["edit_transition"], "fade")
        for row in self._segments():
            if int(row["id"]) != self.target:
                self.assertEqual((row["edit_note"], row["overlays"]), (before[row["id"]]["edit_note"], before[row["id"]]["overlays"]),
                                 "the AI's plan of the other scenes was never confirmed: not applied")
        self.assertFalse(self._edit_document()["confirmed"], "a base nobody confirmed stays unconfirmed")

    def test_a_hand_edit_on_a_confirmed_version_keeps_it_confirmed(self) -> None:
        self._plan_only()
        self._confirm()
        self._put(self._scene_of(self.target)["scene_key"], {"note": "sửa tay sau khi xác nhận"})
        self.assertTrue(self._edit_document()["confirmed"], "the person's own edit on a confirmed plan")
        sync = self.client.post(f"/api/projects/{self.project_id}/timeline/generate", json={}).json()["edit_document"]
        self.assertEqual(sync["status"], "unchanged")

    def test_cleanups_wait_on_an_unconfirmed_plan_and_apply_on_a_confirmed_one(self) -> None:
        self._plan_only()
        before = [row["edit_cleanups"] for row in self._segments()]
        waiting = self.client.post(f"/api/projects/{self.project_id}/timeline/cleanups",
                                   json={"position": "top_right", "method": "blur"}).json()
        self.assertEqual((waiting["status"], waiting["segments"]), (main.NEEDS_CONFIRMATION, 0))
        self.assertEqual([row["edit_cleanups"] for row in self._segments()], before)
        self._confirm()                                         # the plan, with the cleanups kept in it, confirmed
        self.assertTrue(all(json.loads(row["edit_cleanups"]) == [{"position": "top_right", "method": "blur"}]
                            for row in self._segments()))
        cleared = self.client.post(f"/api/projects/{self.project_id}/timeline/cleanups", json={"clear": True}).json()
        self.assertEqual(cleared["status"], "cleared", "on a confirmed version they apply at once")
        self.assertTrue(self._edit_document()["confirmed"])


class StaleSceneTests(_ConfirmCase):
    def _scene_number(self, segment_id: int) -> int:
        # The scenes are read in the storyboard's order: "Cảnh N" is the N-th.
        return 1 + [item["segment_id"] for item in self._edit_document()["scenes"]].index(segment_id)

    def test_a_change_of_many_scenes_never_makes_a_stale_scene_current(self) -> None:
        # Bước 05 · T9 (found in the browser): the cleanups kept on a scene whose layers were made for other words
        # gave it a new basis - "ready" - without anybody planning it again.
        self._plan_only()
        self._confirm()
        target = self._first_scene_of_section(1)
        self._reword_in_place(1)
        rebuilt = self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={"force": True})
        self.assertEqual(rebuilt.status_code, 200, rebuilt.text)
        stale = {"stale_content", "stale_overlays", "stale_timing"}
        self.assertTrue(stale & set(self._scene_of(target)["statuses"]), "its words changed: stale")
        answer = self.client.post(f"/api/projects/{self.project_id}/timeline/cleanups",
                                  json={"position": "top_right", "method": "blur"}).json()
        held = [item for item in answer["not_applied"] if item["segment_id"] == target]
        self.assertEqual(len(held), 1)
        self.assertIn("lớp dựng cũ", held[0]["reason"])
        self.assertEqual((held[0]["code"], held[0]["scene_index"]), ("stale_layers", self._scene_number(target)))
        self.assertTrue(stale & set(self._scene_of(target)["statuses"]), "still stale: nobody planned it again")

    def test_on_an_unconfirmed_plan_the_stale_scene_is_named_among_those_waiting(self) -> None:
        # Bước 05 · T9: the message of cleanups waiting for a confirmation names the stale scenes they skip.
        self._plan_only()
        target = self._first_scene_of_section(1)
        self._reword_in_place(1)
        rebuilt = self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={"force": True})
        self.assertEqual(rebuilt.status_code, 200, rebuilt.text)
        answer = self.client.post(f"/api/projects/{self.project_id}/timeline/cleanups",
                                  json={"position": "top_right", "method": "blur"}).json()
        self.assertEqual(answer["status"], main.NEEDS_CONFIRMATION)
        stale = [item for item in answer["not_applied"] if item.get("code") == "stale_layers"]
        self.assertEqual([(item["segment_id"], item["scene_index"]) for item in stale],
                         [(target, self._scene_number(target))])
