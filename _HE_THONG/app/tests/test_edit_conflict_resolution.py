"""Bước 05 · T6b · xung đột EditDocument bị kẹt: thấy được, và người dùng quyết định.

    GET  /api/projects/{id}/edit-document                       mỗi cảnh: conflict {columns, expected_from, state_hash, layer_hash}
    POST /api/projects/{id}/edit-document/scenes/{key}/resolve  {choice: keep_timeline | use_plan, columns, state_hash, layer_hash}

5A · phần nào của hàng đã đúng giá trị lần áp sẽ ghi thì không còn là xung đột (ghi không đổi gì).
keep_timeline · kế hoạch dựng nhận đúng các phần đó như trên timeline; timeline không bị ghi.
use_plan · kế hoạch được ghi đè lên đúng cảnh đó, đúng các phần đó - chỉ khi hàng và kế hoạch vẫn là
đúng bản người dùng đã thấy (state_hash, layer_hash), kiểm trong transaction của lần áp; lệch: 409.

Mọi test chạy trên DB tạm của bộ test (tests/conftest.py), mô hình AI giả; không gọi AI thật, không chạy app.
"""

from __future__ import annotations

import json
from unittest import mock

from tests.test_edit_manual_conflicts import MANUAL_OVERLAYS
from tests.test_edit_manual_document import HAND_OVERLAYS, _SceneEditCase
from youtube_monitor import edit_apply as ea, edit_document as ed, edit_store as es, main
from youtube_monitor.database import EDIT_APPLY_KIND, EDIT_DOCUMENT_KIND


class _ConflictCase(_SceneEditCase):
    def setUp(self) -> None:
        super().setUp()
        self._step(confirmed_apply=True)                      # every scene planned and applied
        rows = self._segments()
        self.target, self.other = int(rows[0]["id"]), int(rows[1]["id"])
        self.key = self._scene(self.target)["scene_key"]
        self.plan_texts = self._texts(self._scene(self.target)["edit"]["layers"]["overlays"])

    @staticmethod
    def _texts(overlays: list) -> list:
        return [item.get("text") for item in overlays]

    def _hand_overlays(self, segment_id: int | None = None, overlays: list | None = None) -> None:
        """Chữ động sửa tay qua route timeline cũ: ngoài EditDocument."""
        self._patch_plan(segment_id or self.target, overlays=overlays or HAND_OVERLAYS)

    def _conflict(self, segment_id: int | None = None) -> dict | None:
        return self._scene_of(segment_id or self.target)["conflict"]

    def _decision(self, choice: str, segment_id: int | None = None) -> dict:
        found = self._conflict(segment_id)
        self.assertIsNotNone(found, "there is a conflict to decide")
        return {"choice": choice, "columns": found["columns"], "state_hash": found["state_hash"],
                "layer_hash": found["layer_hash"]}

    def _resolve(self, body: dict, expect: int = 200, key: str | None = None) -> dict:
        response = self.client.post(f"/api/projects/{self.project_id}/edit-document/scenes/{key or self.key}/resolve", json=body)
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def _timeline_state(self) -> dict:
        """The timeline as it is stored, byte for byte: rows, beats and shots (updated_at included)."""
        state = self._db_state()
        return {table: state[table] for table in ("timeline", "shots", "beats")}

    def _row_overlay_texts(self, segment_id: int | None = None) -> list:
        return self._texts(self._overlays(segment_id or self.target))

    def _unknown(self) -> set:
        return ea.unknown_rows(self.database, self.project_id, self.script_id, self._segments())


# ===========================================================================
# 5A · a part already holding what the apply writes is no conflict
# ===========================================================================

class AlreadyThereTests(_ConflictCase):
    def test_a_part_already_holding_the_value_the_plan_writes_is_no_conflict(self) -> None:
        self._hand_overlays()
        answer = self._put(self.key, {"overlays": json.loads(self._seg(self.target)["overlays"])})   # the row's own overlays
        self.assertEqual((answer["status"], answer["conflicts"]), ("applied", []))
        self.assertEqual(self._row_overlay_texts(), self._texts(HAND_OVERLAYS))
        self.assertIsNone(self._conflict())
        self.assertNotIn(self.target, self._unknown(), "the part is known now: no false conflict later")
        self.assertEqual(self._conflicts(self._step(confirmed_apply=True)["applied"]), [])

    def test_only_the_parts_that_differ_from_what_the_plan_writes_stay_in_conflict(self) -> None:
        self._patch_plan(self.target, overlays=HAND_OVERLAYS, transition="fade")
        before = self._timeline_state()
        answer = self._put(self.key, {"overlays": json.loads(self._seg(self.target)["overlays"])})
        self.assertEqual(answer["status"], "blocked")
        self.assertEqual([item["columns"] for item in answer["conflicts"]], [["edit_transition"]],
                         "the overlays already hold the plan's; the transition does not")
        self.assertEqual(self._timeline_state(), before, "the row is left as it is")

    def test_beats_already_holding_the_planned_beats_are_no_conflict(self) -> None:
        seconds = float(self._scene(self.target)["voice"]["duration_seconds"])
        first = round(seconds / 2, 3)
        beats = [{"source_kind": "primary", "duration_seconds": first, "effect": "zoom_in", "prompt": "nhịp A"},
                 {"source_kind": "primary", "duration_seconds": round(seconds - first, 3), "transition": "fade", "prompt": "nhịp B"}]
        self._put(self.key, {"beats": beats})
        hand = [{**beats[0], "prompt": "nhịp tay A"}, beats[1]]
        with self._outside():
            response = self.client.put(f"/api/timeline/{self.target}/edit-beats", json={"beats": hand})   # outside the document
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._conflict()["columns"], ["beats"])
        answer = self._put(self.key, {"beats": hand})        # the very beats the row holds (beat_index 1, 2)
        self.assertEqual((answer["status"], answer["conflicts"]), ("applied", []))
        self.assertEqual([beat["prompt"] for beat in self._beats(self.target)], ["nhịp tay A", "nhịp B"])
        self.assertIsNone(self._conflict())


# ===========================================================================
# The read names each conflict, and writes nothing
# ===========================================================================

class ReadTests(_ConflictCase):
    def test_the_read_names_each_conflict_and_writes_nothing(self) -> None:
        self._hand_overlays()
        state = self._db_state()
        read = self._edit_document()
        self.assertEqual(self._db_state(), state, "the read wrote nothing")
        self.assertEqual(self._edit_document(), read, "reading twice answers the same")
        found = self._scene_of(self.target, read)["conflict"]
        row = self._seg(self.target)
        self.assertEqual(found, {"columns": ["overlays"], "expected_from": "applied",
                                 "state_hash": ea.state_hash(row, self._beats(self.target)),
                                 "layer_hash": ed.edit_hash(ed.effective_edit(self._scene(self.target)))})
        self.assertIsNone(self._scene_of(self.other, read)["conflict"])
        self.assertEqual(sum(1 for item in read["scenes"] if item["conflict"]), 1)

    def test_a_scene_without_a_conflict_says_none(self) -> None:
        read = self._edit_document()
        self.assertTrue(all(item["conflict"] is None for item in read["scenes"]))


# ===========================================================================
# keep_timeline · the plan takes the row's parts; the timeline is never written
# ===========================================================================

class KeepTimelineTests(_ConflictCase):
    def test_the_plan_takes_the_rows_parts_and_the_timeline_is_never_written(self) -> None:
        self._hand_overlays()
        decision = self._decision("keep_timeline")
        before = self._timeline_state()
        versions, applies = self._count(EDIT_DOCUMENT_KIND), self._count(EDIT_APPLY_KIND)

        answer = self._resolve(decision)

        self.assertEqual((answer["status"], answer["resolved"]), ("unchanged", "keep_timeline"))
        self.assertIsNone(answer["conflict"])
        self.assertEqual(self._timeline_state(), before, "the timeline is not written, not even its updated_at")
        self.assertEqual(self._count(EDIT_APPLY_KIND), applies, "no apply")
        self.assertEqual(self._count(EDIT_DOCUMENT_KIND), versions + 1, "one new version of the plan")
        self.assertEqual(self._texts(self._scene(self.target)["edit"]["layers"]["overlays"]), self._texts(HAND_OVERLAYS))
        self.assertIsNone(self._conflict(), "nothing left to decide")
        applied = self._step(confirmed_apply=True)["applied"]
        self.assertEqual(self._conflicts(applied), [], "the next apply makes no false conflict")
        self.assertEqual(self._row_overlay_texts(), self._texts(HAND_OVERLAYS), "and keeps the hand's overlays")
        self.assertNotIn(self.target, self._unknown(), "what the plan knows is the row now")

    def test_sent_again_it_changes_nothing(self) -> None:
        self._hand_overlays()
        decision = self._decision("keep_timeline")
        self._resolve(decision)
        versions, state = self._count(EDIT_DOCUMENT_KIND), self._db_state()
        again = self._resolve(decision)
        self.assertEqual(again["status"], "unchanged")
        self.assertEqual((self._count(EDIT_DOCUMENT_KIND), self._db_state()), (versions, state))

    def test_a_timeline_changed_since_it_was_seen_is_409_and_nothing_is_kept(self) -> None:
        self._hand_overlays()
        decision = self._decision("keep_timeline")
        self._hand_overlays(overlays=MANUAL_OVERLAYS)          # edited again after the user looked
        state = self._db_state()
        answer = self._resolve(decision, expect=409)
        self.assertIn("đã đổi", answer["detail"])
        self.assertEqual(self._db_state(), state)


# ===========================================================================
# use_plan · the plan is written over that scene only, only as it was seen
# ===========================================================================

class UsePlanTests(_ConflictCase):
    def test_the_plan_is_written_over_the_hand_edit_of_that_scene_only(self) -> None:
        self._hand_overlays()
        self._hand_overlays(self.other, overlays=MANUAL_OVERLAYS)   # another scene in conflict, left to decide
        other_before = self._layers(self._seg(self.other))
        decision = self._decision("use_plan")
        applies = self._count(EDIT_APPLY_KIND)

        answer = self._resolve(decision)

        self.assertEqual((answer["status"], answer["resolved"]), ("applied", "use_plan"))
        self.assertEqual([item["segment_id"] for item in answer["applied"]], [self.target])
        self.assertEqual(self._row_overlay_texts(), self.plan_texts, "the plan's overlays are on the row")
        self.assertEqual(self._layers(self._seg(self.other)), other_before, "the other scene is not touched")
        self.assertEqual(self._count(EDIT_APPLY_KIND), applies + 1)
        record = self.database.list_edit_applies(self.project_id, self.script_id)[0]["payload"]
        self.assertEqual(record["written"], [self.target])
        self.assertIsNone(self._conflict())
        self.assertIsNotNone(self._conflict(self.other), "its conflict is still there, not decided for it")
        self.assertNotIn(self.target, self._unknown())

    def test_a_timeline_changed_since_it_was_seen_is_409_and_nothing_is_written(self) -> None:
        self._hand_overlays()
        decision = self._decision("use_plan")
        self._hand_overlays(overlays=MANUAL_OVERLAYS)
        state = self._db_state()
        answer = self._resolve(decision, expect=409)
        self.assertIn("đã đổi", answer["detail"])
        self.assertEqual(self._db_state(), state)
        self.assertEqual(self._row_overlay_texts(), self._texts(MANUAL_OVERLAYS), "the newer hand edit is kept")

    def test_a_plan_changed_since_it_was_seen_is_409_and_nothing_is_written(self) -> None:
        self._hand_overlays()
        decision = self._decision("use_plan")
        self._put(self.key, {"note": "kế hoạch đổi sau lúc xem"})   # a new version of the plan (its apply is blocked)
        state = self._db_state()
        self._resolve(decision, expect=409)
        self.assertEqual(self._db_state(), state)

    def test_columns_other_than_the_conflict_seen_are_409(self) -> None:
        self._hand_overlays()
        decision = {**self._decision("use_plan"), "columns": ["overlays", "edit_transition"]}
        state = self._db_state()
        self._resolve(decision, expect=409)
        self.assertEqual(self._db_state(), state)

    def test_sent_again_it_changes_nothing(self) -> None:
        self._hand_overlays()
        decision = self._decision("use_plan")
        self._resolve(decision)
        state = self._db_state()
        again = self._resolve(decision)
        self.assertEqual(again["status"], "unchanged")
        self.assertEqual(self._db_state(), state, "no second write, no new record")

    def test_beats_decided_for_the_plan_are_written_again_on_the_row(self) -> None:
        seconds = float(self._scene(self.target)["voice"]["duration_seconds"])
        first = round(seconds / 2, 3)
        planned = [{"source_kind": "primary", "duration_seconds": first, "prompt": "nhịp kế hoạch A"},
                   {"source_kind": "primary", "duration_seconds": round(seconds - first, 3), "prompt": "nhịp kế hoạch B"}]
        self._put(self.key, {"beats": planned})                  # applied: the last apply wrote this very plan
        with self._outside():
            response = self.client.put(f"/api/timeline/{self.target}/edit-beats", json={"beats": [
                {**planned[0], "prompt": "nhịp tay"}, planned[1]]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._conflict()["columns"], ["beats"])
        answer = self._resolve(self._decision("use_plan"))
        self.assertEqual(answer["status"], "applied")
        self.assertEqual([(beat["beat_index"], beat["prompt"]) for beat in self._beats(self.target)],
                         [(1, "nhịp kế hoạch A"), (2, "nhịp kế hoạch B")], "the row's beats really changed")
        self.assertIsNone(self._conflict())

    def test_a_conflict_comes_back_when_the_row_is_edited_by_hand_again(self) -> None:
        self._hand_overlays()
        self._resolve(self._decision("use_plan"))
        self.assertIsNone(self._conflict())
        self._hand_overlays(overlays=MANUAL_OVERLAYS)
        self.assertEqual(self._conflict()["columns"], ["overlays"])


class RewriteScopeTests(_ConflictCase):
    """ScopedCheck.verdict on the rows as stored: a decision rewrites only its own parts of its own row."""

    def _parts(self) -> tuple[dict, dict, list, dict]:
        rows, _ = ea.plan(self._doc())
        row = next(item for item in rows if item["segment_id"] == self.target)
        segment = self._seg(self.target)
        beats = self.database.list_project_edit_beats(self.project_id, script_id=self.script_id).get(self.target, [])
        applied = next(item for entry in self.database.list_edit_applies(self.project_id)
                       for item in entry["payload"]["rows"] if item["segment_id"] == self.target)
        return row, segment, beats, applied

    def _accept(self, row: dict, segment: dict, beats: list, columns: list) -> dict:
        return {self.target: {"columns": columns, "state_hash": ea.state_hash(segment, beats), "layer_hash": row["layer_hash"]}}

    def test_a_decision_rewrites_only_when_every_other_part_already_holds_the_plan(self) -> None:
        self._hand_overlays()
        row, segment, beats, applied = self._parts()
        verdict = ea.ScopedCheck(accept=self._accept(row, segment, beats, ["overlays"])).verdict(row, segment, beats, applied)
        self.assertEqual((verdict["conflict"], verdict["rewrite"]), (False, True))
        # The same decision on a row whose transition was also edited by hand: the transition is outside it.
        self._patch_plan(self.target, transition="fade")
        row, segment, beats, applied = self._parts()
        outside = ea.ScopedCheck(accept=self._accept(row, segment, beats, ["overlays"])).verdict(row, segment, beats, applied)
        self.assertTrue(outside["conflict"], "the transition is still a conflict: not decided")
        self.assertFalse(outside.get("rewrite"))

    def test_no_decision_never_rewrites_and_a_decision_never_reaches_another_row(self) -> None:
        self._hand_overlays()
        row, segment, beats, applied = self._parts()
        self.assertFalse(ea.ScopedCheck().verdict(row, segment, beats, applied).get("rewrite"))
        other = {self.other: {"columns": ["overlays"], "state_hash": ea.state_hash(segment, beats), "layer_hash": row["layer_hash"]}}
        verdict = ea.ScopedCheck(accept=other).verdict(row, segment, beats, applied)
        self.assertEqual((verdict["conflict"], verdict["columns"], verdict.get("rewrite")), (True, ["overlays"], False))

    def test_a_decision_never_rewrites_a_row_whose_other_parts_do_not_hold_the_plan(self) -> None:
        self._hand_overlays()
        self._put(self.key, {"note": "ghi chú mới của kế hoạch"})   # the plan moved on: its note is not on the row
        row, segment, beats, applied = self._parts()
        verdict = ea.ScopedCheck(accept=self._accept(row, segment, beats, ["overlays"])).verdict(row, segment, beats, applied)
        self.assertFalse(verdict["conflict"], "the note is no conflict: the row holds what the plan last knew")
        self.assertFalse(verdict["rewrite"], "the note is outside the decision: not a rewrite of the decided parts only")

    def test_a_row_the_apply_took_as_unchanged_is_never_called_done(self) -> None:
        # Defence in depth: were the apply to take the row as unchanged (the plan it last wrote), the decision is
        # reported as not done - the row still holds the hand edit.
        self._hand_overlays()
        decision = self._decision("use_plan")
        with mock.patch.object(ea.ScopedCheck, "_rewrite", return_value=False):
            answer = self._resolve(decision)
        self.assertEqual(answer["status"], "blocked")
        self.assertEqual(self._row_overlay_texts(), self._texts(HAND_OVERLAYS))

    def test_a_decision_on_a_row_moved_on_since_is_outdated(self) -> None:
        self._hand_overlays()
        row, segment, beats, applied = self._parts()
        decision = self._accept(row, segment, beats, ["overlays"])
        self._hand_overlays(overlays=MANUAL_OVERLAYS)
        row, segment, beats, applied = self._parts()
        verdict = ea.ScopedCheck(accept=decision).verdict(row, segment, beats, applied)
        self.assertEqual((verdict["conflict"], verdict["source"]), (True, ea.DECISION_OUTDATED))


# ===========================================================================
# A record from before F1 (the row as a whole) and a conflict a reconcile carried
# ===========================================================================

class WholeRowTests(_ConflictCase):
    def _old_records(self) -> None:
        """Apply records as before F1, whose edit cannot be found again: only the whole row can be compared."""
        with self.database._connect() as connection:
            for row in connection.execute("SELECT id, payload_json FROM project_director_artifacts WHERE project_id = ? "
                                          "AND kind = 'edit_apply'", (self.project_id,)).fetchall():
                payload = json.loads(row["payload_json"])
                for item in payload["rows"]:
                    item.pop("state_edit", None)
                    item["layer_hash"] = "not-a-known-edit"
                connection.execute("UPDATE project_director_artifacts SET payload_json = ? WHERE id = ?",
                                   (json.dumps(payload, ensure_ascii=False), row["id"]))

    def test_use_plan_over_the_whole_row(self) -> None:
        self._old_records()
        self._patch_plan(self.target, transition="fade")
        self.assertEqual(self._conflict()["columns"], ["*"])
        answer = self._resolve(self._decision("use_plan"))
        self.assertEqual(answer["status"], "applied")
        self.assertEqual(self._seg(self.target)["edit_transition"], "cut", "the plan's transition is on the row")
        self.assertIsNone(self._conflict())

    def test_keep_timeline_for_the_whole_row(self) -> None:
        self._old_records()
        self._patch_plan(self.target, transition="fade")
        before = self._timeline_state()
        answer = self._resolve(self._decision("keep_timeline"))
        self.assertEqual(answer["status"], "unchanged")
        self.assertEqual(self._timeline_state(), before)
        self.assertEqual(self._scene(self.target)["edit"]["visual"]["edit_transition"], "fade")
        self.assertIsNone(self._conflict())
        self.assertEqual(self._conflicts(self._step(confirmed_apply=True)["applied"]), [])
        self.assertEqual(self._seg(self.target)["edit_transition"], "fade")


class ReconcileTests(_SceneEditCase):
    def test_a_conflict_a_new_script_carried_is_kept_on_the_timeline_when_asked(self) -> None:
        self._step()                                             # planned, never applied
        target = int(self._segments()[0]["id"])
        self._patch_plan(target, overlays=HAND_OVERLAYS, transition="fade")
        self._revise(line_of_section=2)
        answer = self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={}).json()
        self.assertEqual(answer["reconcile"]["mode"], "carried_over")
        self.script_id = int(self.database.get_latest_project_script(self.project_id)["id"])
        new_target = int(self._segments()[0]["id"])
        found = self._scene_of(new_target)["conflict"]
        self.assertIsNotNone(found)
        self.assertEqual(found["expected_from"], "legacy")
        key = self._scene_of(new_target)["scene_key"]
        response = self.client.post(f"/api/projects/{self.project_id}/edit-document/scenes/{key}/resolve", json={
            "choice": "keep_timeline", "columns": found["columns"], "state_hash": found["state_hash"],
            "layer_hash": found["layer_hash"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "unchanged")
        self.assertIsNone(self._scene_of(new_target)["conflict"])
        applied = self._step(confirmed_apply=True)["applied"]
        self.assertEqual(self._conflicts(applied), [])
        row = self._seg(new_target)
        self.assertEqual((self._texts_of(row), row["edit_transition"]), (["Chữ sửa tay T6a"], "fade"), "the hand's layers stay")

    @staticmethod
    def _texts_of(row: dict) -> list:
        return [item.get("text") for item in json.loads(row["overlays"] or "[]")]


# ===========================================================================
# Two decisions at once, and the doors that refuse
# ===========================================================================

class ConcurrentDecisionTests(_ConflictCase):
    def test_two_use_plan_decisions_at_once_write_once(self) -> None:
        self._hand_overlays()
        decision = self._decision("use_plan")
        real_apply = ea.apply_scenes
        first: dict = {}

        def apply_after_another_decision(*args, **kwargs):
            if "inner" not in first:
                first["inner"] = None
                first["inner"] = self._resolve(decision)          # the same decision lands first
            return real_apply(*args, **kwargs)

        applies = self._count(EDIT_APPLY_KIND)
        with mock.patch.object(ea, "apply_scenes", side_effect=apply_after_another_decision):
            response = self.client.post(f"/api/projects/{self.project_id}/edit-document/scenes/{self.key}/resolve",
                                        json=decision)
        self.assertEqual(first["inner"]["status"], "applied")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self._count(EDIT_APPLY_KIND), applies + 1, "written once")
        self.assertEqual(self._row_overlay_texts(), self.plan_texts)

    def test_a_keep_decision_made_on_an_older_plan_never_writes_over_a_newer_one(self) -> None:
        self._hand_overlays()
        decision = self._decision("keep_timeline")
        real_sync = es.sync
        first: dict = {}

        def sync_then_another_edit(*args, **kwargs):
            synced = real_sync(*args, **kwargs)
            if "inner" not in first:
                first["inner"] = None
                # Another plan is kept after this decision checked its version, before it saves.
                first["inner"] = self._put(self.key, {"note": "kế hoạch mới hơn"})
            return synced

        versions = self._count(EDIT_DOCUMENT_KIND)
        with mock.patch.object(es, "sync", side_effect=sync_then_another_edit):
            response = self.client.post(f"/api/projects/{self.project_id}/edit-document/scenes/{self.key}/resolve",
                                        json=decision)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self._count(EDIT_DOCUMENT_KIND), versions + 1, "the newer plan only")
        edit = self._scene(self.target)["edit"]
        self.assertEqual(edit["visual"]["edit_note"], "kế hoạch mới hơn", "the newer plan is kept")
        self.assertEqual(self._texts(edit["layers"]["overlays"]), self.plan_texts, "the old decision wrote nothing over it")

    def test_two_identical_keep_decisions_at_once_keep_one_version(self) -> None:
        # The same decision twice makes the very same version: kept once, nothing written over, both fine.
        self._hand_overlays()
        decision = self._decision("keep_timeline")
        real_sync = es.sync
        first: dict = {}

        def sync_then_the_same_decision(*args, **kwargs):
            synced = real_sync(*args, **kwargs)
            if "inner" not in first:
                first["inner"] = None
                first["inner"] = self._resolve(decision)
            return synced

        versions = self._count(EDIT_DOCUMENT_KIND)
        with mock.patch.object(es, "sync", side_effect=sync_then_the_same_decision):
            outer = self._resolve(decision)
        self.assertEqual((first["inner"]["status"], outer["status"]), ("unchanged", "unchanged"))
        self.assertEqual(self._count(EDIT_DOCUMENT_KIND), versions + 1, "one version kept")
        self.assertEqual(self._texts(self._scene(self.target)["edit"]["layers"]["overlays"]), self._texts(HAND_OVERLAYS))


class RefusalTests(_ConflictCase):
    def test_a_project_outside_the_plan_workflow_is_409(self) -> None:
        self._hand_overlays()
        decision = self._decision("use_plan")
        state = self._db_state()
        with mock.patch.object(main, "_storyboard_gate", return_value=({"mode": "legacy", "state": "not_applicable"}, None)):
            self._resolve(decision, expect=409)
        self.assertEqual(self._db_state(), state)

    def test_a_wrong_choice_or_missing_hashes_is_422(self) -> None:
        self._hand_overlays()
        decision = self._decision("use_plan")
        state = self._db_state()
        self._resolve({**decision, "choice": "merge"}, expect=422)
        self._resolve({"choice": "use_plan", "columns": ["overlays"]}, expect=422)
        self._resolve({**decision, "columns": []}, expect=422)
        self.assertEqual(self._db_state(), state)

    def test_an_unknown_scene_is_404(self) -> None:
        self._hand_overlays()
        self._resolve(self._decision("use_plan"), expect=404, key="sk-khong-co")
