"""Bước 5.3 · T4 · the EditDocument in the production flow.

    reconcile (Storyboard) ─→ edit_store.sync(refresh) ─→ edit_apply.apply_scenes() ─→ timeline
          three transactions in a row, never one: each later one checks what the earlier ones left

Every door to a planned project's scenes (shots/generate, timeline/generate,
run_step shots/timeline, a pasted script) goes through _sync_storyboard, and
from there through _apply_edit_document - the one production call of T3.
What an EditDocument has applied to a row is its own: the reconcile neither
carries it to a new row nor retimes it in place; the next apply writes it.
Legacy content the reconcile does carry or retime is made known to the
EditDocument (a legacy orphan of that row), so an apply expects it instead of
refusing it. A project without an EditDocument is left as it was. Every test
runs on the suite's temporary database.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from tests.test_edit_apply import _ApplyCase
from tests.test_edit_store import _StoreCase
from youtube_monitor import edit_apply as ea, edit_document as ed, edit_store as es, main, storyboard_engine as sb
from youtube_monitor.database import EDIT_APPLY_KIND, EDIT_DOCUMENT_KIND


class _FlowCase(_ApplyCase):
    def _timeline_generate(self) -> dict:
        response = self.client.post(f"/api/projects/{self.project_id}/timeline/generate", json={})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _count(self, kind: str) -> int:
        with self.database._connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM project_director_artifacts WHERE project_id = ? AND kind = ?",
                                      (self.project_id, kind)).fetchone()[0]

    def _revise(self, line_of_section: int = 1) -> None:
        """A revised script (a new script id): one line of a section reworded, the rest the same."""
        old = self._script(self.project_id)
        lines = old["main_content"].split("\n")
        at = self._first_of_section(self.project_id, line_of_section)
        lines[at] = lines[at].replace(" ", " mỗi ", 1).rsplit(" ", 1)[0] + "."
        main.run_project_step(self.project_id, "script", {"revision": {"base_script_id": old["id"],
                                                                       "fields": {"main_content": "\n".join(lines)}, "source": "t"}})

    def _reword_in_place(self) -> None:
        at = self._first_of_section(self.project_id, 1)
        self._patch_lines(self.project_id, lambda lines: lines.__setitem__(at, lines[at].replace(" ", " mỗi ", 1).rsplit(" ", 1)[0] + "."))

    def _plan_all(self, picture: bool = True) -> None:
        for n in range(len(self._doc()["scenes"])):
            self._plan(n, self._edit(n, picture=f"p{n}.png" if picture else None, beats=False))

    def _orphan_hash(self, segment_id: int) -> str | None:
        """What the current EditDocument expects a row it never wrote to hold - the latest legacy orphan of that row."""
        found = [item for item in self._doc()["orphans"] if item.get("reason") == ed.LEGACY and item["segment_id"] == segment_id]
        return ed.edit_hash(found[-1]["edit"]) if found else None


# ===========================================================================
# The production caller
# ===========================================================================

class CallerTests(_FlowCase):
    def test_timeline_generate_applies_the_current_edit_document(self) -> None:
        self._plan(0, self._edit(0, picture="mine.png"))
        answer = self._timeline_generate()["edit_document"]
        segment_id = self._scene(0)["segment_id"]
        self.assertEqual((answer["status"], answer["counts"]["applied"]), ("applied", 1))
        self.assertEqual(self._row(segment_id)["visual_path"], str(self.tmp / "mine.png"))
        self.assertEqual(self._count(EDIT_APPLY_KIND), 1)

    def test_shots_generate_and_run_step_go_through_the_same_caller(self) -> None:
        self._plan(0, self._edit(0, picture="a.png"))
        answer = self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={}).json()["edit_document"]
        self.assertEqual(answer["status"], "applied")
        self._plan(0, self._edit(0, picture="b.png"))
        ran = main.run_project_step(self.project_id, "timeline", {})
        self.assertEqual(ran["result"]["edit_document"]["status"], "applied")
        self.assertEqual(self._row(self._scene(0)["segment_id"])["visual_path"], str(self.tmp / "b.png"))

    def test_a_project_without_an_edit_document_is_left_as_it_was(self) -> None:
        other, script_id = self._project()
        before = self._timeline_edit(other, script_id)
        response = self.client.post(f"/api/projects/{other}/timeline/generate", json={}).json()
        self.assertEqual(response["edit_document"], {"status": "no_document"})
        self.assertEqual(self._timeline_edit(other, script_id), before)
        with self.database._connect() as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM project_director_artifacts WHERE project_id = ? AND kind IN (?, ?)",
                (other, EDIT_DOCUMENT_KIND, EDIT_APPLY_KIND)).fetchone()[0], 0)

    def test_the_same_state_twice_writes_nothing_and_keeps_every_version(self) -> None:
        self._plan(0, self._edit(0, picture="a.png"))
        self._timeline_generate()
        documents, applies = self._count(EDIT_DOCUMENT_KIND), self._count(EDIT_APPLY_KIND)
        stamp = self._row(self._scene(0)["segment_id"])["updated_at"]
        answer = self._timeline_generate()["edit_document"]
        self.assertEqual((answer["status"], answer["document_mode"], answer["artifact_id"]), ("unchanged", "unchanged", None))
        self.assertEqual((self._count(EDIT_DOCUMENT_KIND), self._count(EDIT_APPLY_KIND)), (documents, applies))
        self.assertEqual(self._row(self._scene(0)["segment_id"])["updated_at"], stamp)


# ===========================================================================
# Only the current storyboard of the current script
# ===========================================================================

class CurrentTests(_FlowCase):
    def test_a_storyboard_the_gate_does_not_hold_current_is_not_applied(self) -> None:
        self._plan(0, self._edit(0, picture="a.png"))
        before = self._timeline_edit(self.project_id, self.script_id)
        stale = ({"state": sb.STALE}, self._board_row(self.project_id, self.script_id))
        with mock.patch.object(main, "_storyboard_gate", return_value=stale):
            answer = main._apply_edit_document(self.project_id, self._script(self.project_id))
        self.assertEqual((answer["status"], answer["gate"]), ("not_current", sb.STALE))
        self.assertEqual(self._timeline_edit(self.project_id, self.script_id), before)
        self.assertEqual(self._count(EDIT_APPLY_KIND), 0)

    def test_an_older_script_is_never_applied(self) -> None:
        old = self.database.get_project_script(self.script_id)
        self._revise()
        self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={})
        before = self._timeline_edit(self.project_id, self.script_id)
        answer = main._apply_edit_document(self.project_id, old)
        self.assertEqual(answer["status"], "not_current")
        self.assertEqual(self._timeline_edit(self.project_id, self.script_id), before)

    def test_a_stored_edit_document_that_cannot_be_read_is_an_error_not_none(self) -> None:
        latest = self.database.get_latest_edit_document(self.project_id, self.script_id)
        self._overwrite(latest["id"], "{broken")
        answer = self._timeline_generate()["edit_document"]
        self.assertEqual(answer["status"], "error")


# ===========================================================================
# Reconcile and _retime: what the EditDocument owns is left to it
# ===========================================================================

class ReconcileTests(_FlowCase):
    def _legacy_layers(self, overlays: list) -> None:
        """Layers written by another path after the document began, and a voice measured longer than the estimate:
        a reworded scene loses its voice, so its length goes back to the estimate and the reconcile scales its layers."""
        for row in self._timeline(self.project_id, self.script_id):
            self.database.save_segment_edit_layers(int(row["id"]), overlays=overlays)
            self.database.update_project_timeline_segment(int(row["id"]), duration_seconds=int(row["duration_seconds"]) * 2)
        self._sync(self.project_id, self.script_id)   # the document follows the voices; the layers stay unknown to it

    def test_a_reworded_scene_the_document_owns_is_neither_retimed_nor_rewritten(self) -> None:
        self._plan_all()
        self._timeline_generate()
        applied = {row["id"]: json.loads(row["overlays"]) for row in self._timeline(self.project_id, self.script_id)}
        self._reword_in_place()
        answer = self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={"force": True}).json()
        owned = [scene for scene in answer["reconcile"]["scenes"] if scene.get("edit_owned")]
        self.assertEqual(len(owned), 1, "the one reworded scene was owned")
        self.assertIsNone(owned[0]["retimed"], "never retimed by the reconcile")
        segment_id = owned[0]["new_segment_id"]
        self.assertEqual(json.loads(self._row(segment_id)["overlays"]), applied[segment_id], "its layers as the apply left them")
        self.assertEqual(answer["edit_document"]["counts"]["skipped"].get(ea.STALE), 1)
        self.assertEqual(answer["edit_document"]["counts"]["conflicts"], 0)

    def test_a_reworded_legacy_scene_is_retimed_as_before_and_made_known(self) -> None:
        legacy_overlay = [{"kind": "text", "text": "old", "start_seconds": 0.0, "end_seconds": 1.0}]
        self._legacy_layers(legacy_overlay)   # the document follows, the layers are another path's - unknown to it
        self._reword_in_place()
        answer = self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={"force": True}).json()
        retimed = [scene for scene in answer["reconcile"]["scenes"] if scene.get("retimed")]
        self.assertEqual(len(retimed), 1)
        segment_id = retimed[0]["new_segment_id"]
        self.assertIn(segment_id, answer["edit_refresh"])
        row = self._row(segment_id)
        self.assertNotEqual(json.loads(row["overlays"]), legacy_overlay, "legacy layers still follow the new length")
        self.assertEqual(self._orphan_hash(segment_id), ea.state_hash(row, self._beats(segment_id)),
                         "and the document now knows what the row holds")

    def test_a_retimed_legacy_scene_can_then_be_planned_and_applied(self) -> None:
        self._legacy_layers([{"kind": "text", "start_seconds": 0, "end_seconds": 1}])
        self._reword_in_place()
        answer = self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={"force": True}).json()
        segment_id = next(scene["new_segment_id"] for scene in answer["reconcile"]["scenes"] if scene.get("retimed"))
        n = next(n for n, scene in enumerate(self._doc()["scenes"]) if scene["segment_id"] == segment_id)
        legacy_picture = self._row(segment_id)["visual_path"]
        self._plan(n, self._edit(n, beats=False, transition="cut"))
        applied = self._timeline_generate()["edit_document"]
        self.assertEqual((applied["status"], applied["counts"]["conflicts"]), ("applied", 0))
        self.assertEqual((self._row(segment_id)["edit_transition"], self._row(segment_id)["visual_path"]), ("cut", legacy_picture))


# ===========================================================================
# A revised script: new rows, the EditDocument carried by lineage
# ===========================================================================

class CarriedOverTests(_FlowCase):
    def test_owned_edits_are_written_by_the_apply_and_legacy_pictures_carried(self) -> None:
        self._plan(0, self._edit(0, picture="owned.png"))
        self._plan(1, self._edit(1, beats=False, transition="cut"))   # layers only: the legacy picture stays the row's
        self._timeline_generate()
        old_rows = self._timeline(self.project_id, self.script_id)
        self._revise(line_of_section=2)
        answer = self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={}).json()
        self.script_id = int(self.database.get_latest_project_script(self.project_id)["id"])
        new_rows = self._timeline(self.project_id, self.script_id)
        self.assertEqual(answer["reconcile"]["mode"], "carried_over")
        self.assertEqual(answer["edit_document"]["document_mode"], "carried_over")
        self.assertEqual(answer["edit_document"]["counts"]["conflicts"], 0, answer["edit_document"]["conflicts"])
        self.assertEqual(new_rows[0]["visual_path"], str(self.tmp / "owned.png"), "written by the apply, not copied")
        self.assertEqual((new_rows[1]["visual_path"], new_rows[1]["edit_transition"]), (old_rows[1]["visual_path"], "cut"))
        self.assertTrue(all(row["visual_path"] == old["visual_path"] for row, old in zip(new_rows[2:], old_rows[2:])
                            if row["voice_text"] == old["voice_text"]), "legacy pictures carried as before")
        self.assertEqual({item["segment_id"] for item in answer["edit_document"]["applied"]},
                         {new_rows[0]["id"], new_rows[1]["id"]})

    def test_owned_columns_are_never_copied_to_the_new_row(self) -> None:
        self._plan(0, self._edit(0, picture="owned.png"))
        self._timeline_generate()
        with mock.patch.object(main, "_apply_edit_document", return_value={"status": "deferred"}):
            self._revise(line_of_section=2)
            self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={})
        new_id = int(self.database.get_latest_project_script(self.project_id)["id"])
        first = self._timeline(self.project_id, new_id)[0]
        self.assertEqual((first["visual_path"], json.loads(first["overlays"])), ("", []),
                         "left for the apply: the reconcile copies only what no EditDocument wrote")
        self.assertEqual(self.database.list_timeline_edit_beats(int(first["id"])), [])


# ===========================================================================
# Partial success, and a real failure
# ===========================================================================

class OutcomeTests(_FlowCase):
    def test_a_conflict_beside_a_valid_scene_is_partial_never_success(self) -> None:
        self._plan(0, self._edit(0, picture="a.png"))
        self._plan(1, self._edit(1, picture="b.png"))
        self._timeline_generate()
        first, second = self._scene(0)["segment_id"], self._scene(1)["segment_id"]
        self.database.update_project_timeline_segment(first, visual_path=str(self.tmp / "by-hand.png"))
        self._plan(0, self._edit(0, picture="a2.png"))
        self._plan(1, self._edit(1, picture="b2.png"))
        answer = self._timeline_generate()["edit_document"]
        self.assertEqual((answer["status"], answer["counts"]["applied"], answer["counts"]["conflicts"]), ("partial", 1, 1))
        self.assertEqual(self._row(first)["visual_path"], str(self.tmp / "by-hand.png"))
        self.assertEqual(self._row(second)["visual_path"], str(self.tmp / "b2.png"))

    def test_nothing_written_and_a_conflict_is_blocked(self) -> None:
        self._plan(0, self._edit(0, picture="a.png"))
        self._timeline_generate()
        first = self._scene(0)["segment_id"]
        self.database.update_project_timeline_segment(first, visual_path=str(self.tmp / "by-hand.png"))
        self._plan(0, self._edit(0, picture="a2.png"))
        self.assertEqual(self._timeline_generate()["edit_document"]["status"], "blocked")

    def test_an_invalid_edit_is_reported_and_the_rest_applied(self) -> None:
        self._plan(0, self._edit(0, picture="ok.png"))
        seconds = float(self._scene(1)["voice"]["duration_seconds"])
        self._plan(1, ed.edit({"edit_transition": None}, overlays=[{"kind": "text", "start_seconds": 0, "end_seconds": seconds / 2}]))
        answer = self._timeline_generate()["edit_document"]
        self.assertEqual((answer["status"], answer["counts"]["skipped"].get(ea.INVALID_EDIT)), ("partial", 1))
        self.assertEqual(self._row(self._scene(0)["segment_id"])["visual_path"], str(self.tmp / "ok.png"))

    def test_a_system_error_in_the_apply_rolls_the_apply_back_and_surfaces(self) -> None:
        self._plan(0, self._edit(0, picture="a.png"))
        self._plan(1, self._edit(1, picture="b.png"))
        before = self._timeline_edit(self.project_id, self.script_id)
        calls, real = {"n": 0}, ea.state_hash

        def failing(segment, beats):
            calls["n"] += 1
            if calls["n"] == 4:
                raise RuntimeError("disk gone")
            return real(segment, beats)

        with mock.patch.object(ea, "state_hash", failing), self.assertRaises(RuntimeError):
            self.client.post(f"/api/projects/{self.project_id}/timeline/generate", json={})
        self.assertEqual(self._timeline_edit(self.project_id, self.script_id), before, "both rows the apply wrote, rolled back")
        self.assertEqual(self._count(EDIT_APPLY_KIND), 0)


# ===========================================================================
# One writer per flow: an agent's timeline does not write over the EditDocument
# ===========================================================================

class SingleWriterTests(_FlowCase):
    def test_an_agents_fields_never_land_on_a_row_the_document_owns(self) -> None:
        self._plan(0, self._edit(0, picture="owned.png"))
        self._timeline_generate()
        rows = self._timeline(self.project_id, self.script_id)
        owned_prompt = rows[0]["visual_prompt"]
        segments = [{"voice_text": row["voice_text"], "subtitle_text": row["voice_text"], "visual_prompt": f"agent {n}"}
                    for n, row in enumerate(rows)]
        result = main.run_project_step(self.project_id, "timeline", {"segments": segments})["result"]
        self.assertEqual(result["edit_owned_rows_kept"], [rows[0]["id"]])
        self.assertEqual(self._row(rows[0]["id"])["visual_prompt"], owned_prompt, "the owned row keeps the document's")
        self.assertEqual(self._row(rows[1]["id"])["visual_prompt"], "agent 1", "the others take the agent's, as before")
        self.assertEqual(result["edit_document"]["counts"]["conflicts"], 0, "and the document knows what they now hold")
        self.assertEqual(self._orphan_hash(rows[1]["id"]), ea.state_hash(self._row(rows[1]["id"]), self._beats(rows[1]["id"])))

    def test_a_flow_writes_an_owned_row_once(self) -> None:
        self._plan(0, self._edit(0, picture="a.png"))
        segment_id = self._scene(0)["segment_id"]
        writes = []
        real = self.database.apply_edit_document_rows

        def counting(*args, **kwargs):
            done = real(*args, **kwargs)
            writes.extend(item["segment_id"] for item in done["written"])
            return done

        with mock.patch.object(self.database, "apply_edit_document_rows", side_effect=counting), \
                mock.patch.object(self.database, "update_project_timeline_segment",
                                  side_effect=AssertionError("no legacy writer in this flow")) as legacy:
            self._timeline_generate()
        self.assertEqual(writes, [segment_id])
        legacy.assert_not_called()
