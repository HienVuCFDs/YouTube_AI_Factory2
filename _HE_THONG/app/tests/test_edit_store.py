"""Bước 5.3 · T2 · keeping a planned project's EditDocument (edit_store + Database).

    timeline + voices + StoryboardDocument ─→ edit_document.build() ─→ save() ─→ project_director_artifacts
    stored artifact ─→ load(): its storyboard by hash ─→ validate() ─→ the document, or a refusal

One row per version, after the latest one; read back only through validate()
against the storyboard it names; the first document of a timeline that already
has layers holds them as legacy orphans; nothing is written to the timeline.
All on the test database.
"""

from __future__ import annotations

import json
from tests.test_edit_document import _edit
from tests.test_storyboard_gate import _AppCase
from youtube_monitor import edit_document as ed, edit_store as es, main, production_worker as worker_module
from youtube_monitor import storyboard_engine as sb
from youtube_monitor.database import EDIT_DOCUMENT_KIND, EditDocumentConflict


class _StoreCase(_AppCase):
    def _script_id(self, project_id: int) -> int:
        return int(self.database.get_latest_project_script(project_id)["id"])

    def _board_row(self, project_id: int, script_id: int | None = None) -> dict:
        script_id = script_id or self._script_id(project_id)
        row = self.database.get_latest_project_storyboard(project_id, script_id)
        self.assertIsNotNone(row)
        return row

    def _sync(self, project_id: int, script_id: int | None = None) -> dict:
        script_id = script_id or self._script_id(project_id)
        return es.sync(self.database, project_id, script_id, self._board_row(project_id, script_id))

    def _rows(self, project_id: int) -> int:
        with self.database._connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM project_director_artifacts WHERE project_id = ? AND kind = ?",
                                      (project_id, EDIT_DOCUMENT_KIND)).fetchone()[0]

    def _tamper(self, artifact_id: int, change) -> None:
        with self.database._connect() as connection:
            payload = json.loads(connection.execute("SELECT payload_json FROM project_director_artifacts WHERE id = ?",
                                                    (artifact_id,)).fetchone()[0])
            change(payload)
            connection.execute("UPDATE project_director_artifacts SET payload_json = ? WHERE id = ?",
                               (json.dumps(payload, ensure_ascii=False), artifact_id))

    def _timeline_data(self, project_id: int, script_id: int | None = None) -> list[dict]:
        skip = {"status", "updated_at"}  # resync_timeline_segment_states moves these on its own
        return [{key: value for key, value in row.items() if key not in skip} for row in self._timeline(project_id, script_id)]

    def _clear_layers(self, project_id: int) -> None:
        for segment in self._timeline(project_id):
            self.database.update_project_timeline_segment(int(segment["id"]), visual_path="")

    def _overlays(self, segment_id: int, overlays: list) -> None:
        """A layer written straight onto a row, as the legacy Edit Plan routes do."""
        with self.database._connect() as connection:
            connection.execute("UPDATE project_timeline_segments SET overlays = ? WHERE id = ?", (json.dumps(overlays), segment_id))


class BootstrapTests(_StoreCase):
    def test_a_timeline_without_layers_starts_a_document_that_needs_a_plan_everywhere(self) -> None:
        project_id = self._ready()
        self._clear_layers(project_id)
        before = self._timeline_data(project_id)
        first = self._sync(project_id)
        document = first["document"]
        self.assertEqual((first["mode"], first["created"], first["parent_hash"]), ("bootstrap", True, None))
        self.assertEqual({item["status"] for item in document["scenes"]}, {"needs_plan"})
        self.assertEqual(document["orphans"], [])
        self.assertEqual([item["segment_id"] for item in document["scenes"]], [row["id"] for row in self._timeline(project_id)],
                         "each scene names the timeline row it is now")
        self.assertTrue(all(item["voice"]["audio_signature"] for item in document["scenes"]), "the voices on the timeline are read")
        self.assertEqual(document["provenance"]["storyboard_id"], self._board_row(project_id)["id"])
        # Nothing moved: the same version, no new row.
        again = self._sync(project_id)
        self.assertEqual((again["mode"], again["created"], again["document_hash"]), ("unchanged", False, first["document_hash"]))
        self.assertEqual(self._rows(project_id), 1)
        self.assertEqual(self._timeline_data(project_id), before, "nothing is written to the timeline")

    def test_layers_already_on_the_timeline_are_held_as_legacy_never_taken_as_ready(self) -> None:
        project_id = self._ready()  # every row has a picture, from before any EditDocument
        timeline = self._timeline(project_id)
        overlay = [{"kind": "text", "text": "cũ", "start_seconds": 0.5, "end_seconds": 1.5}]
        self._overlays(int(timeline[0]["id"]), overlay)
        document = self._sync(project_id)["document"]
        self.assertTrue(all(item["status"] == "needs_plan" and not item["ready"] for item in document["scenes"]))
        self.assertTrue(all(item["review"] == ["unverified"] for item in document["scenes"]))
        self.assertEqual([(orphan["reason"], orphan["candidate"], orphan["segment_id"], orphan["ready"])
                          for orphan in document["orphans"]],
                         [("legacy", item["scene_key"], item["segment_id"], False) for item in document["scenes"]])
        first = document["orphans"][0]["edit"]
        self.assertEqual((first["visual"]["visual_path"], first["layers"]["overlays"]), (timeline[0]["visual_path"], overlay))
        self.assertEqual(document["counts"]["orphan"], len(timeline))
        # Once there is a document, the timeline is not read as a source again: a new layer there is not adopted.
        self._overlays(int(timeline[1]["id"]), overlay)
        self.assertEqual(self._sync(project_id)["mode"], "unchanged")


class VersionTests(_StoreCase):
    def test_planning_a_scene_keeps_the_next_version_after_the_latest(self) -> None:
        project_id = self._ready()
        self._clear_layers(project_id)
        script_id = self._script_id(project_id)
        first = self._sync(project_id)
        key = first["document"]["scenes"][0]["scene_key"]
        seconds = first["document"]["scenes"][0]["voice"]["duration_seconds"]
        before = self._timeline_data(project_id)
        planned = es.plan_scene(self.database, project_id, script_id, self._board_row(project_id), key, _edit("a", seconds=seconds))
        self.assertEqual((planned["created"], planned["parent_hash"]), (True, first["document_hash"]))
        self.assertEqual(planned["document"]["scenes"][0]["status"], "ready")
        loaded = es.load(self.database, project_id, script_id)
        self.assertEqual((loaded["document_hash"], loaded["parent_hash"], loaded["artifact_id"]),
                         (planned["document_hash"], first["document_hash"], planned["artifact_id"]))
        self.assertEqual(loaded["document"], planned["document"])
        found = es.current(self.database, project_id, script_id, self._board_row(project_id))
        self.assertEqual((found["state"], found["document_hash"]), ("current", planned["document_hash"]))
        self.assertEqual([item["document_hash"] for item in es.history(self.database, project_id, script_id)],
                         [planned["document_hash"], first["document_hash"]])
        self.assertEqual(self._timeline_data(project_id), before, "planned, not applied (T3)")

    def test_a_save_that_does_not_follow_the_latest_version_writes_nothing(self) -> None:
        project_id = self._ready()
        self._clear_layers(project_id)
        script_id, row = self._script_id(project_id), self._board_row(project_id)
        first = self._sync(project_id)
        board = sb.decode(row)
        key = first["document"]["scenes"][0]["scene_key"]
        seconds = first["document"]["scenes"][0]["voice"]["duration_seconds"]
        es.plan_scene(self.database, project_id, script_id, row, key, _edit("a", seconds=seconds))
        # Built on the first version while another was kept since.
        late = ed.plan_scene(first["document"], board, key, _edit("b", seconds=seconds))
        with self.assertRaises(es.EditStoreError) as refused:
            es.save(self.database, project_id, script_id, late, storyboard_row=row, expected_parent=first["document_hash"])
        self.assertEqual(refused.exception.status_code, 409)
        # A version already in the history is not kept again either.
        with self.assertRaises(EditDocumentConflict):
            self.database.save_edit_document(project_id, script_id, first["document"], storyboard_id=row["id"],
                                             expected_parent=es.load(self.database, project_id, script_id)["document_hash"])
        self.assertEqual(self._rows(project_id), 2)

    def test_only_a_document_valid_for_its_storyboard_is_kept(self) -> None:
        project_id = self._ready()
        self._clear_layers(project_id)
        script_id, row = self._script_id(project_id), self._board_row(project_id)
        document = self._sync(project_id)["document"]
        forged = json.loads(json.dumps(document))
        forged["scenes"][0].update(statuses=[], status="ready", ready=True)
        forged["document_hash"] = ed.document_hash(forged)
        with self.assertRaises(es.EditStoreError) as refused:
            es.save(self.database, project_id, script_id, forged, storyboard_row=row, expected_parent=document["document_hash"])
        self.assertIn("không hợp lệ", str(refused.exception))
        with self.assertRaises(es.EditStoreError):
            es.save(self.database, project_id, script_id + 999, document, storyboard_row=row, expected_parent=None)
        self.assertEqual(self._rows(project_id), 1)


class ReadTests(_StoreCase):
    def _kept(self) -> tuple[int, int, dict]:
        project_id = self._ready()
        self._clear_layers(project_id)
        return project_id, self._script_id(project_id), self._sync(project_id)

    def test_a_tampered_or_broken_version_is_refused_never_read_as_empty(self) -> None:
        cases = {
            "lớp dựng sửa ngoài basis": lambda payload: payload["document"]["scenes"][0]["edit"]["visual"].update(visual_path="x.png"),
            "document_hash không khớp": lambda payload: payload["document"]["scenes"][0].update(status="ready"),
            "schema": lambda payload: payload.update(schema=2),
            "storyboard khác": lambda payload: payload.update(storyboard_hash="khac"),
        }
        for name, change in cases.items():
            with self.subTest(name):
                project_id, script_id, kept = self._kept()
                self._tamper(kept["artifact_id"], change)
                with self.assertRaises(es.EditStoreError):
                    es.load(self.database, project_id, script_id)
                with self.assertRaises(es.EditStoreError, msg="a broken latest version is not built over"):
                    self._sync(project_id)

    def test_broken_json_is_refused_even_for_another_script(self) -> None:
        project_id, script_id, kept = self._kept()
        with self.database._connect() as connection:
            connection.execute("UPDATE project_director_artifacts SET payload_json = '{' WHERE id = ?", (kept["artifact_id"],))
        with self.assertRaises(es.EditStoreError):
            es.load(self.database, project_id, script_id + 1)

    def test_a_storyboard_that_is_gone_or_changed_makes_the_version_unreadable(self) -> None:
        project_id, script_id, kept = self._kept()
        with self.database._connect() as connection:
            connection.execute("UPDATE project_storyboards SET document_hash = 'khac' WHERE id = ?", (kept["document"]["provenance"]["storyboard_id"],))
        with self.assertRaises(es.EditStoreError) as refused:
            es.load(self.database, project_id, script_id)
        self.assertIn("Không tìm thấy storyboard", str(refused.exception))


class FollowTests(_StoreCase):
    def _planned(self) -> tuple[int, dict]:
        project_id = self._ready()
        self._clear_layers(project_id)
        script_id = self._script_id(project_id)
        document = self._sync(project_id)["document"]
        for item in document["scenes"]:
            document = es.plan_scene(self.database, project_id, script_id, self._board_row(project_id), item["scene_key"],
                                     _edit(item["scene_key"], seconds=item["voice"]["duration_seconds"]))["document"]
        self.assertTrue(all(item["ready"] for item in document["scenes"]))
        return project_id, document

    def test_new_voice_settings_make_a_new_version_even_when_the_audio_is_the_same(self) -> None:
        project_id, before = self._planned()
        now = main._current_voice_fingerprint(project_id)
        for segment in self._timeline(project_id):
            worker_module.write_voice_record(segment["audio_path"], voice_text=segment["voice_text"], speaker=segment["speaker"],
                                             fingerprint=now, config={}, segment_id=int(segment["id"]))
        self.assertEqual(self._sync(project_id)["mode"], "unchanged", "the record says what the voice already was")
        self.database.update_project_render_settings(project_id, voice_model="vi-VN-NamMinhNeural")
        after = self._sync(project_id)
        self.assertEqual((after["mode"], after["created"], after["parent_hash"]), ("follow", True, before["document_hash"]))
        self.assertTrue(all(item["voice"]["fits"] is False for item in after["document"]["scenes"]))
        self.assertTrue(all(item["timing"]["state"] == "retimed" for item in after["document"]["scenes"]),
                        "the voice it was timed against no longer fits: times follow, never kept as they were")

    def test_a_record_written_later_with_other_settings_is_seen(self) -> None:
        # The audio file, its length and the project's settings stay the same; only whether the voice fits changes.
        project_id, before = self._planned()
        for segment in self._timeline(project_id)[:1]:
            worker_module.write_voice_record(segment["audio_path"], voice_text=segment["voice_text"], speaker=segment["speaker"],
                                             fingerprint="khac", config={}, segment_id=int(segment["id"]))
        after = self._sync(project_id)
        self.assertEqual(after["mode"], "follow")
        self.assertEqual(after["document"]["provenance"], {**before["provenance"], "storyboard_id": after["document"]["provenance"]["storyboard_id"]})
        self.assertFalse(after["document"]["scenes"][0]["voice"]["fits"])

    def test_new_words_make_the_scene_stale_on_the_new_storyboard_and_keep_the_others(self) -> None:
        project_id, before = self._planned()
        script_id = self._script_id(project_id)
        old_row = self._board_row(project_id)
        at = self._first_of_section(project_id, 1)
        self._patch_lines(project_id, lambda lines: lines.__setitem__(at, lines[at].replace(" ", " mỗi ", 1).rsplit(" ", 1)[0] + "."))
        self.client.post(f"/api/projects/{project_id}/shots/generate", json={"force": True})
        new_row = self._board_row(project_id)
        self.assertNotEqual(new_row["document_hash"], old_row["document_hash"])
        self.assertEqual(es.current(self.database, project_id, script_id, new_row)["state"], "outdated")
        self.assertEqual(es.current(self.database, project_id, script_id, old_row)["state"], "current")
        after = self._sync(project_id)
        self.assertEqual((after["mode"], after["parent_hash"]), ("follow", before["document_hash"]))
        statuses = [item["statuses"] for item in after["document"]["scenes"]]
        self.assertEqual(sum(1 for item in statuses if "stale_content" in item), 1, statuses)
        self.assertEqual(sum(1 for item in statuses if not item), len(statuses) - 1, "every other scene keeps its edit")
        self.assertEqual(after["document"]["provenance"]["storyboard_hash"], new_row["document_hash"])
        self.assertEqual(es.current(self.database, project_id, script_id, new_row)["state"], "current")

    def test_a_revised_script_carries_the_edit_over_from_the_old_one(self) -> None:
        project_id, before = self._planned()
        old = self._script(project_id)
        lines = old["main_content"].split("\n")
        at = self._first_of_section(project_id, 1)
        lines[at] = lines[at].replace(" ", " mỗi ", 1).rsplit(" ", 1)[0] + "."
        main.run_project_step(project_id, "script", {"revision": {"base_script_id": old["id"],
                                                                  "fields": {"main_content": "\n".join(lines)}, "source": "test"}})
        self.client.post(f"/api/projects/{project_id}/shots/generate", json={})
        new_id = self._script_id(project_id)
        self.assertNotEqual(new_id, old["id"])
        self.assertIsNone(es.load(self.database, project_id, new_id))
        after = self._sync(project_id, new_id)
        self.assertEqual(after["mode"], "carried_over")
        kept = es.load(self.database, project_id, new_id)
        self.assertEqual((kept["carried_from"], kept["parent_hash"]), (before["document_hash"], None))
        statuses = [item["statuses"] for item in after["document"]["scenes"]]
        self.assertEqual(sum(1 for item in statuses if not item), len(statuses) - 1, statuses)
        self.assertEqual(es.load(self.database, project_id, old["id"])["document_hash"], before["document_hash"],
                         "the old script's document is untouched")


if __name__ == "__main__":
    import unittest

    unittest.main()
