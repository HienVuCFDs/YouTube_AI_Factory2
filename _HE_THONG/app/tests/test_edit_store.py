"""Bước 5.3 · T2 · keeping a planned project's EditDocument.

    timeline + voices + StoryboardDocument ─→ edit_document.build() ─→ edit_store.save()
    stored artifact ─→ edit_store.load(): its storyboard by hash ─→ validate() ─→ the document, or a refusal

An EditDocument is a director artifact of kind "edit_document", one row per
version, never a row of project_edit_plans: the legacy Edit Plan and the
EditDocument neither read nor write each other. A save follows the latest
version it was built on - checked in the same transaction as the write - and
the same document is the row already there. The first document of a timeline
that already has edit layers keeps them as `legacy` orphans: never ready,
never taken as a scene's edit, the timeline left as it is. Every test runs on
the suite's temporary database.
"""

from __future__ import annotations

import json
import sqlite3
from unittest import mock

from tests.test_storyboard_gate import _AppCase
from youtube_monitor import edit_document as ed, edit_store as es, main
from youtube_monitor.database import EDIT_DOCUMENT_KIND, Database, EditDocumentConflict

# What of a timeline row is its edit: a sync must leave every one of these as it found it.
_EDIT_COLUMNS = ("id", "voice_text", "audio_path", "visual_path", "visual_prompt", "asset_type", "overlays", "sound_cues",
                 "edit_direction", "edit_transition", "edit_effect", "edit_trim_head", "edit_trim_tail")


class _StoreCase(_AppCase):
    def _project(self) -> tuple[int, int]:
        """A planned project cut, voiced and illustrated - its pictures made before any EditDocument."""
        project_id = self._ready()
        return project_id, int(self.database.get_latest_project_script(project_id)["id"])

    def _board_row(self, project_id: int, script_id: int) -> dict:
        return self.database.get_latest_project_storyboard(project_id, script_id=script_id)

    def _sync(self, project_id: int, script_id: int) -> dict:
        return es.sync(self.database, project_id, script_id, self._board_row(project_id, script_id))

    def _rows(self, project_id: int) -> int:
        with self.database._connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM project_director_artifacts WHERE project_id = ? AND kind = ?",
                                      (project_id, EDIT_DOCUMENT_KIND)).fetchone()[0]

    def _edit_plan_rows(self, project_id: int) -> int:
        with self.database._connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM project_edit_plans WHERE project_id = ?", (project_id,)).fetchone()[0]

    def _timeline_edit(self, project_id: int, script_id: int) -> tuple[list, dict]:
        rows = [{key: row.get(key) for key in _EDIT_COLUMNS} for row in self._timeline(project_id, script_id)]
        return rows, self.database.list_project_edit_beats(project_id, script_id=script_id)

    def _overwrite(self, artifact_id: int, payload_json: str) -> None:
        with self.database._connect() as connection:
            connection.execute("UPDATE project_director_artifacts SET payload_json = ? WHERE id = ?", (payload_json, artifact_id))

    def _planned(self, project_id: int, script_id: int, tag: str) -> dict:
        """The current document with its first scene's edit made for it (`tag` names the picture), kept."""
        document = es.current(self.database, project_id, script_id, self._board_row(project_id, script_id))["document"]
        scene = document["scenes"][0]
        made = ed.edit({"visual_path": f"{tag}.png", "asset_type": "ai_scene"},
                       overlays=[{"kind": "text", "text": tag, "start_seconds": 0.0,
                                  "end_seconds": round(scene["voice"]["duration_seconds"] / 2, 3)}])
        return es.plan_scene(self.database, project_id, script_id, self._board_row(project_id, script_id), scene["scene_key"], made)


# ===========================================================================
# Storage: a director artifact, never the legacy Edit Plan
# ===========================================================================

class StorageTests(_StoreCase):
    def test_the_document_is_a_director_artifact_and_never_an_edit_plan(self) -> None:
        project_id, script_id = self._project()
        done = self._sync(project_id, script_id)
        self.assertEqual((done["created"], done["mode"], self._rows(project_id)), (True, "bootstrap", 1))
        self.assertEqual(self._edit_plan_rows(project_id), 0, "project_edit_plans is the legacy Edit Plan's")
        self.assertIsNone(self.database.get_project_edit_plan(project_id, script_id))
        stored = self.database.get_latest_edit_document(project_id, script_id)
        self.assertEqual((stored["id"], stored["payload"]["schema"], stored["payload"]["script_id"]),
                         (done["artifact_id"], es.SCHEMA, script_id))
        self.assertEqual(stored["payload"]["document"], done["document"])
        self.assertEqual(stored["payload"]["storyboard_hash"], self._board_row(project_id, script_id)["document_hash"])

    def test_a_legacy_edit_plan_is_never_read_as_an_edit_document_nor_the_other_way(self) -> None:
        project_id, script_id = self._project()
        self.database.save_project_edit_plan(project_id, script_id, "rev", {"kind": "edit_document", "scenes": []})
        self.assertEqual(self.database.list_edit_documents(project_id), [])
        self.assertIsNone(es.load(self.database, project_id, script_id))
        done = self._sync(project_id, script_id)
        self.assertEqual(done["mode"], "bootstrap", "the legacy plan is not a previous EditDocument")
        legacy_plan = self.database.get_project_edit_plan(project_id, script_id)
        self.assertEqual(legacy_plan["plan"], {"kind": "edit_document", "scenes": []}, "and the sync left it as it was")
        self.assertEqual(self._edit_plan_rows(project_id), 1)

    def test_the_generic_director_artifact_calls_cannot_reach_an_edit_document(self) -> None:
        project_id, script_id = self._project()
        self._sync(project_id, script_id)
        with self.assertRaises(ValueError):
            self.database.save_director_artifact(project_id, EDIT_DOCUMENT_KIND, {"document": {}})
        with self.assertRaises(ValueError):
            self.database.get_director_artifact(project_id, EDIT_DOCUMENT_KIND)
        self.assertEqual(self._rows(project_id), 1)


# ===========================================================================
# Versions: one row each, after the latest, checked in the write's transaction
# ===========================================================================

class VersionTests(_StoreCase):
    def test_the_same_document_is_the_row_already_there(self) -> None:
        project_id, script_id = self._project()
        first = self._sync(project_id, script_id)
        again = es.save(self.database, project_id, script_id, first["document"], storyboard_row=self._board_row(project_id, script_id),
                        expected_parent=None)
        self.assertEqual((again["created"], again["artifact_id"], self._rows(project_id)), (False, first["artifact_id"], 1))
        later = self._sync(project_id, script_id)
        self.assertEqual((later["created"], later["mode"], later["artifact_id"], self._rows(project_id)),
                         (False, "unchanged", first["artifact_id"], 1))

    def test_a_save_that_no_longer_follows_the_latest_version_writes_nothing(self) -> None:
        project_id, script_id = self._project()
        first = self._sync(project_id, script_id)
        board_row = self._board_row(project_id, script_id)
        scene = first["document"]["scenes"][0]
        made = lambda tag: ed.plan_scene(first["document"], es._storyboard(board_row, project_id=project_id, script_id=script_id),  # noqa: E731
                                         scene["scene_key"], ed.edit({"visual_path": f"{tag}.png"}))
        winner = es.save(self.database, project_id, script_id, made("a"), storyboard_row=board_row,
                         expected_parent=first["document_hash"])
        self.assertEqual((winner["created"], winner["parent_hash"]), (True, first["document_hash"]))
        with self.assertRaises(es.EditStoreError) as refused:
            es.save(self.database, project_id, script_id, made("b"), storyboard_row=board_row, expected_parent=first["document_hash"])
        self.assertEqual(refused.exception.status_code, 409)
        self.assertEqual(self._rows(project_id), 2)
        self.assertEqual(es.load(self.database, project_id, script_id)["document_hash"], winner["document_hash"])
        with self.assertRaises(EditDocumentConflict):
            self.database.save_edit_document(project_id, script_id, made("c"), storyboard_id=int(board_row["id"]),
                                             expected_parent=None)

    def test_the_latest_version_is_read_under_the_write_lock(self) -> None:
        project_id, script_id = self._project()
        first = self._sync(project_id, script_id)
        board_row = self._board_row(project_id, script_id)
        document = ed.plan_scene(first["document"], es._storyboard(board_row, project_id=project_id, script_id=script_id),
                                 first["document"]["scenes"][0]["scene_key"], ed.edit({"visual_path": "x.png"}))
        seen: list[str] = []
        read = Database._edit_document_entries

        def racing(connection, *args):
            # Another writer arriving between the read and the write is held off: the lock is already taken.
            other = sqlite3.connect(self.database.path, timeout=0.1)
            try:
                other.execute("INSERT INTO project_director_artifacts (project_id, kind, payload_json, created_at) "
                              "VALUES (?, 'other', '{}', 'now')", (project_id,))
                other.commit()
                seen.append("written")
            except sqlite3.OperationalError as exc:
                seen.append(str(exc))
            finally:
                other.close()
            return read(connection, *args)

        with mock.patch.object(Database, "_edit_document_entries", staticmethod(racing)):
            self.database.save_edit_document(project_id, script_id, document, storyboard_id=int(board_row["id"]),
                                             expected_parent=first["document_hash"])
        self.assertEqual(len(seen), 1)
        self.assertIn("locked", seen[0])

    def test_going_back_to_an_earlier_edit_is_a_new_version(self) -> None:
        project_id, script_id = self._project()
        first = self._sync(project_id, script_id)
        a = self._planned(project_id, script_id, "a")
        b = self._planned(project_id, script_id, "b")
        again = self._planned(project_id, script_id, "a")
        self.assertTrue(again["created"])
        self.assertEqual(len({first["document_hash"], a["document_hash"], b["document_hash"], again["document_hash"]}), 4)
        self.assertEqual((a["parent_hash"], b["parent_hash"], again["parent_hash"]),
                         (first["document_hash"], a["document_hash"], b["document_hash"]))
        self.assertEqual(again["document"]["based_on"], b["document_hash"])
        self.assertEqual(again["document"]["scenes"][0]["edit"], a["document"]["scenes"][0]["edit"])
        self.assertEqual([item["document_hash"] for item in es.history(self.database, project_id, script_id)],
                         [again["document_hash"], b["document_hash"], a["document_hash"], first["document_hash"]])

    def test_a_document_already_further_back_in_the_history_is_not_stored_again(self) -> None:
        project_id, script_id = self._project()
        first = self._sync(project_id, script_id)
        b = self._planned(project_id, script_id, "b")
        with self.assertRaises(es.EditStoreError):
            es.save(self.database, project_id, script_id, first["document"], storyboard_row=self._board_row(project_id, script_id),
                    expected_parent=b["document_hash"])
        self.assertEqual(self._rows(project_id), 2)


# ===========================================================================
# Reading: checked end to end, refused - never read as empty - when broken
# ===========================================================================

class ReadTests(_StoreCase):
    def test_a_row_that_cannot_be_read_is_refused_not_skipped(self) -> None:
        project_id, script_id = self._project()
        first = self._sync(project_id, script_id)
        self._planned(project_id, script_id, "a")
        latest = self.database.get_latest_edit_document(project_id, script_id)
        self._overwrite(latest["id"], "{not json")
        for read in (es.load, es.history):
            with self.assertRaises(es.EditStoreError):
                read(self.database, project_id, script_id)
        with self.assertRaises(es.EditStoreError):
            self._sync(project_id, script_id)
        self.assertNotEqual(first["artifact_id"], latest["id"], "the older version is never handed back in its place")

    def test_a_document_changed_after_it_was_kept_is_refused(self) -> None:
        project_id, script_id = self._project()
        first = self._sync(project_id, script_id)
        payload = self.database.get_latest_edit_document(project_id, script_id)["payload"]
        payload["document"]["scenes"][0]["status"] = ed.READY
        self._overwrite(first["artifact_id"], json.dumps(payload))
        with self.assertRaises(es.EditStoreError) as refused:
            es.load(self.database, project_id, script_id)
        self.assertIn("document_hash", str(refused.exception))

    def test_a_document_whose_rehashed_content_fails_validate_is_refused(self) -> None:
        project_id, script_id = self._project()
        first = self._sync(project_id, script_id)
        payload = self.database.get_latest_edit_document(project_id, script_id)["payload"]
        document = payload["document"]
        document["scenes"][0].update(status=ed.READY, ready=True, statuses=[])   # a legacy scene made ready unseen
        document["document_hash"] = payload["document_hash"] = ed.document_hash(document)
        self._overwrite(first["artifact_id"], json.dumps(payload))
        with self.assertRaises(es.EditStoreError) as refused:
            es.load(self.database, project_id, script_id)
        self.assertIn("không hợp lệ", str(refused.exception))

    def test_a_document_whose_storyboard_is_gone_or_changed_is_refused(self) -> None:
        project_id, script_id = self._project()
        self._sync(project_id, script_id)
        board_row = self._board_row(project_id, script_id)
        with self.database._connect() as connection:
            connection.execute("UPDATE project_storyboards SET document_hash = 'other' WHERE id = ?", (board_row["id"],))
        with self.assertRaises(es.EditStoreError) as refused:
            es.load(self.database, project_id, script_id)
        self.assertIn("storyboard", str(refused.exception).lower())

    def test_a_document_made_for_another_storyboard_is_outdated_not_current(self) -> None:
        project_id, script_id = self._project()
        first = self._sync(project_id, script_id)
        other = {**self._board_row(project_id, script_id), "document_hash": "another-cut"}
        found = es.current(self.database, project_id, script_id, other)
        self.assertEqual((found["state"], found["document"], found["document_hash"]), (es.OUTDATED, None, first["document_hash"]))
        self.assertEqual(es.current(self.database, project_id, script_id, self._board_row(project_id, script_id))["state"], es.CURRENT)
        self.assertEqual(es.current(self.database, project_id, script_id + 999, None)["state"], es.MISSING)
        with self.assertRaises(es.EditStoreError):
            es.plan_scene(self.database, project_id, script_id, other, first["document"]["scenes"][0]["scene_key"])


# ===========================================================================
# Bootstrap: pictures already on the timeline are kept as legacy orphans
# ===========================================================================

class BootstrapTests(_StoreCase):
    def test_every_picture_already_made_is_kept_as_a_legacy_orphan_and_no_scene_is_ready(self) -> None:
        project_id, script_id = self._project()
        timeline = self._timeline(project_id, script_id)
        self.assertTrue(all(row["visual_path"] for row in timeline))
        document = self._sync(project_id, script_id)["document"]
        self.assertTrue(all(item["status"] == ed.NEEDS_PLAN and item["ready"] is False for item in document["scenes"]))
        self.assertTrue(all(item["basis"] is None and item["edit"] == ed.normalize_edit(None) for item in document["scenes"]),
                        "no basis is made up for a picture nobody planned for this scene")
        self.assertEqual(len(document["orphans"]), len(timeline))
        by_row = {orphan["segment_id"]: orphan for orphan in document["orphans"]}
        for item, row in zip(document["scenes"], timeline):
            orphan = by_row[row["id"]]
            self.assertEqual((orphan["reason"], orphan["status"], orphan["ready"], orphan["candidate"], orphan["basis"]),
                             (ed.LEGACY, ed.ORPHAN, False, item["scene_key"], None))
            self.assertEqual(orphan["edit"]["visual"]["visual_path"], row["visual_path"], "the picture is kept as it is")
            self.assertEqual(item["segment_id"], row["id"])
            self.assertEqual((item["lineage"]["match"], item["lineage"]["previous_segment_id"]), ("segment", row["id"]))
            self.assertIn("unverified", item["review"])
        self.assertEqual(document["counts"][ed.READY], 0)

    def test_a_sync_never_writes_to_the_timeline_nor_removes_a_file(self) -> None:
        project_id, script_id = self._project()
        before = self._timeline_edit(project_id, script_id)
        files = [row["visual_path"] for row in before[0]] + [row["audio_path"] for row in before[0]]
        self._sync(project_id, script_id)
        self._planned(project_id, script_id, "a")
        self.database.update_project_render_settings(project_id, voice_model="vi-VN-NamMinhNeural")
        self._sync(project_id, script_id)
        self.assertEqual(self._timeline_edit(project_id, script_id), before)
        self.assertTrue(all(main.Path(path).is_file() for path in files))

    def test_a_row_nobody_edited_leaves_no_orphan(self) -> None:
        project_id, script_id = self._project()
        first = self._timeline(project_id, script_id)[0]
        with self.database._connect() as connection:
            connection.execute("UPDATE project_timeline_segments SET visual_path = '', visual_prompt = '' WHERE id = ?",
                               (first["id"],))
        document = self._sync(project_id, script_id)["document"]
        self.assertNotIn(first["id"], {orphan["segment_id"] for orphan in document["orphans"]})
        self.assertEqual(document["scenes"][0]["lineage"]["match"], None)
        self.assertEqual(es.timeline_edit({"visual_path": "", "overlays": "[]", "sound_cues": "[]", "edit_direction": "{}"}, []),
                         ed.normalize_edit(None))

    def test_a_layer_column_that_does_not_read_is_kept_not_dropped(self) -> None:
        held = es.timeline_edit({"visual_path": "p.png", "asset_type": "ai_scene", "overlays": "{broken", "sound_cues": "[]"}, [])
        self.assertEqual(held["visual"], {"visual_path": "p.png", "asset_type": "ai_scene", "unparsed_overlays": "{broken"})

    def test_shots_that_do_not_say_the_storyboard_are_not_read(self) -> None:
        project_id, script_id = self._project()
        with mock.patch.object(es.storyboard_engine, "shots_match", return_value=False):
            with self.assertRaises(es.EditStoreError):
                self._sync(project_id, script_id)
        self.assertEqual(self._rows(project_id), 0)


# ===========================================================================
# Following: the next version is built from the latest one, by lineage
# ===========================================================================

class FollowTests(_StoreCase):
    def test_orphans_and_planned_scenes_survive_the_next_version(self) -> None:
        project_id, script_id = self._project()
        first = self._sync(project_id, script_id)
        planned = self._planned(project_id, script_id, "a")
        self.assertTrue(planned["document"]["scenes"][0]["ready"])
        self.database.update_project_render_settings(project_id, voice_model="vi-VN-NamMinhNeural")
        done = self._sync(project_id, script_id)
        self.assertEqual((done["created"], done["mode"], done["parent_hash"]), (True, "follow", planned["document_hash"]))
        self.assertEqual(done["document"]["based_on"], planned["document_hash"])
        self.assertEqual(done["document"]["orphans"], first["document"]["orphans"], "the legacy pictures are still held")
        self.assertEqual(done["document"]["scenes"][0]["edit"], planned["document"]["scenes"][0]["edit"])
        self.assertTrue(all(item["status"] == ed.NEEDS_PLAN for item in done["document"]["scenes"][1:]))

    def test_a_new_script_carries_the_edit_over_and_keeps_the_old_history(self) -> None:
        project_id, old_id = self._project()
        self._sync(project_id, old_id)
        planned = self._planned(project_id, old_id, "a")
        old = self._script(project_id)
        lines = old["main_content"].split("\n")
        at = self._first_of_section(project_id, 1)
        lines[at] = lines[at].replace(" ", " mỗi ", 1).rsplit(" ", 1)[0] + "."
        main.run_project_step(project_id, "script", {"revision": {"base_script_id": old["id"],
                                                                  "fields": {"main_content": "\n".join(lines)}, "source": "test"}})
        self.assertEqual(self.client.post(f"/api/projects/{project_id}/shots/generate", json={}).json()["status"], "saved")
        new_id = int(self.database.get_latest_project_script(project_id)["id"])
        self.assertNotEqual(new_id, old_id)
        done = self._sync(project_id, new_id)
        self.assertEqual((done["mode"], done["parent_hash"]), ("carried_over", None))
        stored = self.database.get_latest_edit_document(project_id, new_id)["payload"]
        self.assertEqual(stored["carried_from"], planned["document_hash"])
        self.assertEqual(done["document"]["based_on"], planned["document_hash"])
        self.assertEqual(done["document"]["scenes"][0]["edit"], planned["document"]["scenes"][0]["edit"])
        self.assertEqual(len(es.history(self.database, project_id, old_id)), 2, "the old script's versions stay as they were")
        self.assertEqual(es.load(self.database, project_id, old_id)["document_hash"], planned["document_hash"])
