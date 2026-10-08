"""Bước 5.3 · T3 · applying an EditDocument to the timeline.

    current EditDocument ─→ effective_edit() per scene ─→ apply_edit_document_rows() ─→ timeline rows + edit beats + edit_apply

Only a scene whose edit was made for it and still holds is applied (ready,
or kept for a visual review); a scene with no edit or a stale one is left as
it is. A picture is written only when the edit names one - otherwise the
row keeps the one it has, a legacy one included, and no file is deleted.
Before a row is written, what it holds is checked against what the
EditDocument last knew: the latest apply, else the legacy orphan of that very
row, else nothing ever written. A row written since by another path is a
conflict: skipped, while the other scenes are still applied, in one
transaction that a real error rolls back whole. Every test runs on the
suite's temporary database.
"""

from __future__ import annotations

import copy
from pathlib import Path
from unittest import mock

from tests.test_edit_store import _StoreCase
from youtube_monitor import edit_apply as ea, edit_document as ed, edit_store as es, main
from youtube_monitor.database import EDIT_APPLY_KIND, EDIT_OWNED_COLUMNS

# What of a row an apply never writes.
_NOT_OWNED = ("voice_text", "subtitle_text", "speaker", "audio_path", "subtitle_path", "duration_seconds", "status",
              "segment_index", "shot_id")


class _ApplyCase(_StoreCase):
    def setUp(self) -> None:
        super().setUp()
        self._hold_scene_worker()
        self.project_id, self.script_id = self._project()
        self.bootstrap = self._sync(self.project_id, self.script_id)

    def _hold_scene_worker(self) -> None:
        """The app's scene worker runs for as long as the class's TestClient: idle, it takes queued jobs from the
        database every 2 s. A job a test made to hold a beat must stay as the test left it, not be run (and fail)."""
        idle = mock.patch.object(self.database, "list_queued_scene_generation_job_ids", return_value=[])
        idle.start()
        self.addCleanup(idle.stop)

    # --- helpers ---------------------------------------------------------------------

    def _row(self, segment_id: int) -> dict:
        return self.database.get_project_timeline_segment(segment_id)

    def _beats(self, segment_id: int) -> list[dict]:
        return self.database.list_timeline_edit_beats(segment_id)

    def _doc(self) -> dict:
        return es.current(self.database, self.project_id, self.script_id, self._board_row(self.project_id, self.script_id))["document"]

    def _scene(self, n: int) -> dict:
        return self._doc()["scenes"][n]

    def _edit(self, n: int, *, picture: str | None = None, beats: bool = True, transition: str = "fade") -> dict:
        """An edit made for scene n at its length: a text overlay over its first half, a cue, two beats."""
        seconds = float(self._scene(n)["voice"]["duration_seconds"])
        visual = {"edit_transition": transition}
        if picture is not None:
            visual.update(visual_path=str(self.tmp / picture), asset_type="ai_scene")
        return ed.edit(visual,
                       overlays=[{"kind": "text", "text": f"scene {n}", "start_seconds": 0.0, "end_seconds": round(seconds / 2, 3)}],
                       sound_cues=[{"cue": "whoosh", "start_seconds": 0.0, "end_seconds": 0.5}],
                       beats=[{"visual_path": f"b{n}a.png", "start_seconds": 0.0, "duration_seconds": round(seconds / 2, 3)},
                              {"visual_path": f"b{n}b.png", "start_seconds": round(seconds / 2, 3),
                               "duration_seconds": round(seconds / 2, 3)}] if beats else [])

    def _plan(self, n: int, edit: dict) -> dict:
        key = self._scene(n)["scene_key"]
        return es.plan_scene(self.database, self.project_id, self.script_id, self._board_row(self.project_id, self.script_id),
                             key, edit)

    def _apply(self, **options) -> dict:
        return ea.apply_scenes(self.database, self.project_id, self.script_id,
                               self._board_row(self.project_id, self.script_id), **options)

    def _records(self) -> int:
        with self.database._connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM project_director_artifacts WHERE project_id = ? AND kind = ?",
                                      (self.project_id, EDIT_APPLY_KIND)).fetchone()[0]

    def _not_owned(self) -> list:
        return [{key: row.get(key) for key in _NOT_OWNED} for row in self._timeline(self.project_id, self.script_id)]


# ===========================================================================
# 1. A ready scene is applied: its effective edit, its beats, its record
# ===========================================================================

class ApplyTests(_ApplyCase):
    def test_a_ready_scene_is_applied_with_its_beats_and_recorded(self) -> None:
        edit = self._edit(0, picture="new0.png")
        self._plan(0, edit)
        segment_id = self._scene(0)["segment_id"]
        before = self._not_owned()
        done = self._apply()
        self.assertEqual([item["segment_id"] for item in done["applied"]], [segment_id])
        self.assertEqual(done["conflicts"], [])
        row = self._row(segment_id)
        self.assertEqual((row["visual_path"], row["asset_type"], row["edit_transition"]),
                         (str(self.tmp / "new0.png"), "ai_scene", "fade"))
        self.assertEqual(main.json.loads(row["overlays"]), edit["layers"]["overlays"])
        self.assertEqual(main.json.loads(row["sound_cues"]), edit["layers"]["sound_cues"])
        self.assertEqual([(beat["beat_index"], beat["visual_path"], beat["start_seconds"], beat["duration_seconds"])
                          for beat in self._beats(segment_id)],
                         [(1, "b0a.png", 0.0, edit["beats"][0]["duration_seconds"]),
                          (2, "b0b.png", edit["beats"][1]["start_seconds"], edit["beats"][1]["duration_seconds"])])
        self.assertEqual(self._not_owned(), before, "voice, subtitles, length and status are never written")
        record = self.database.list_edit_applies(self.project_id, self.script_id)[0]["payload"]
        self.assertEqual((record["document_hash"], record["written"]), (done["document_hash"], [segment_id]))
        self.assertEqual(record["rows"][0]["layer_hash"], ed.edit_hash(ed.effective_edit(self._scene(0))))
        self.assertEqual(record["rows"][0]["state_hash"], ea.state_hash(self._row(segment_id), self._beats(segment_id)))
        self.assertEqual(self._edit_plan_rows(self.project_id), 0)

    def test_the_edit_is_applied_as_it_plays_now_retimed_to_the_voice(self) -> None:
        edit = self._edit(0, beats=False)
        self._plan(0, edit)
        segment_id = self._scene(0)["segment_id"]
        old = float(self._scene(0)["voice"]["duration_seconds"])
        self.database.update_project_timeline_segment(segment_id, duration_seconds=int(old * 2))
        self._sync(self.project_id, self.script_id)
        scene = self._scene(0)
        self.assertEqual((scene["status"], scene["timing"]["state"]), (ed.READY, ed.TIMING_RETIMED))
        self._apply()
        overlay = main.json.loads(self._row(segment_id)["overlays"])[0]
        self.assertAlmostEqual(overlay["end_seconds"], edit["layers"]["overlays"][0]["end_seconds"] * scene["timing"]["ratio"], 3)

    def test_the_owned_columns_are_the_ones_an_edit_document_reads_back(self) -> None:
        self.assertEqual(set(es._VISUAL_COLUMNS) | {"asset_type", "overlays", "sound_cues", "edit_direction"}, EDIT_OWNED_COLUMNS)


# ===========================================================================
# 2. No edit, no write: legacy pictures stay - bootstrap and carried over
# ===========================================================================

class NothingToApplyTests(_ApplyCase):
    def test_scenes_with_no_edit_write_nothing_and_the_legacy_pictures_stay(self) -> None:
        before = self._timeline_edit(self.project_id, self.script_id)
        done = self._apply()
        self.assertEqual((done["applied"], done["conflicts"], done["artifact_id"]), ([], [], None))
        self.assertEqual({item["reason"] for item in done["skipped"]}, {ea.NEEDS_PLAN})
        self.assertEqual(self._timeline_edit(self.project_id, self.script_id), before)
        self.assertTrue(all(Path(row["visual_path"]).is_file() for row in before[0]))
        self.assertEqual(self._records(), 0)

    def test_a_carried_over_row_is_never_wiped_nor_overwritten(self) -> None:
        self._plan(0, self._edit(0, picture="mine.png"))
        old = self._script(self.project_id)
        lines = old["main_content"].split("\n")
        at = self._first_of_section(self.project_id, 1)
        lines[at] = lines[at].replace(" ", " mỗi ", 1).rsplit(" ", 1)[0] + "."
        main.run_project_step(self.project_id, "script", {"revision": {"base_script_id": old["id"],
                                                                       "fields": {"main_content": "\n".join(lines)}, "source": "t"}})
        # The library alone (T3): rows no EditDocument knows of. With the production caller (T4) the reconcile's
        # carried rows are known and applied - tests/test_edit_integration.py.
        with mock.patch.object(main, "_apply_edit_document", return_value={"status": "deferred"}):
            self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={})
        self.script_id = int(self.database.get_latest_project_script(self.project_id)["id"])
        self.assertEqual(self._sync(self.project_id, self.script_id)["mode"], "carried_over")
        before = self._timeline_edit(self.project_id, self.script_id)
        self.assertTrue(all(row["visual_path"] for row in before[0]), "the reconcile copied every picture over")
        done = self._apply()
        self.assertEqual(done["applied"], [])
        self.assertEqual([(item["scene_key"], item["expected_from"]) for item in done["conflicts"]],
                         [(self._scene(0)["scene_key"], "default")], "a copied picture no apply knows of is not overwritten")
        self.assertEqual(self._timeline_edit(self.project_id, self.script_id), before)


# ===========================================================================
# 3. The picture: owned only when the edit names one
# ===========================================================================

class PictureOwnershipTests(_ApplyCase):
    def test_an_edit_without_a_picture_keeps_the_legacy_one(self) -> None:
        segment_id = self._scene(0)["segment_id"]
        legacy = self._row(segment_id)["visual_path"]
        self._plan(0, self._edit(0, picture=None, transition="cut"))
        done = self._apply()
        self.assertEqual(done["applied"][0]["visual_owned"], False)
        row = self._row(segment_id)
        self.assertEqual((row["visual_path"], row["edit_transition"]), (legacy, "cut"))
        self.assertTrue(main.json.loads(row["overlays"]))
        self.assertTrue(Path(legacy).is_file())

    def test_an_edit_with_a_picture_owns_the_row_and_no_file_is_deleted(self) -> None:
        segment_id = self._scene(0)["segment_id"]
        legacy = self._row(segment_id)["visual_path"]
        self._plan(0, self._edit(0, picture="mine.png"))
        done = self._apply()
        self.assertEqual(done["applied"][0]["visual_owned"], True)
        self.assertEqual(self._row(segment_id)["visual_path"], str(self.tmp / "mine.png"))
        self.assertTrue(Path(legacy).is_file(), "the legacy picture's file stays")
        orphans = [item for item in self._doc()["orphans"] if item["segment_id"] == segment_id]
        self.assertEqual(orphans[0]["edit"]["visual"]["visual_path"], legacy, "and so does its orphan")

    def test_the_orphan_is_found_by_its_row_never_by_its_candidate(self) -> None:
        document = self._doc()
        first, second = document["scenes"][0], document["scenes"][1]
        moved = copy.deepcopy(document)
        for orphan in moved["orphans"]:
            if orphan["segment_id"] == first["segment_id"]:
                orphan["candidate"] = second["scene_key"]
            elif orphan["segment_id"] == second["segment_id"]:
                orphan["candidate"] = first["scene_key"]
        planned = ed.plan_scene(moved, self._doc_board(), first["scene_key"], self._edit(0))
        rows, _ = ea.plan(planned)
        legacy = {item["segment_id"]: item["edit"] for item in document["orphans"]}
        self.assertEqual(rows[0]["legacy_hash"], ed.edit_hash(legacy[first["segment_id"]]))

    def _doc_board(self) -> dict:
        return es._storyboard(self._board_row(self.project_id, self.script_id), project_id=self.project_id,
                              script_id=self.script_id)


# ===========================================================================
# 4. A row written since by another path is a conflict; the others still go
# ===========================================================================

class ConflictTests(_ApplyCase):
    def test_a_row_changed_after_the_apply_is_not_overwritten_and_the_rest_still_apply(self) -> None:
        self._plan(0, self._edit(0, picture="one.png"))
        self._plan(1, self._edit(1, picture="two.png"))
        self._apply()
        first, second = self._scene(0)["segment_id"], self._scene(1)["segment_id"]
        self.database.update_project_timeline_segment(first, visual_path=str(self.tmp / "by-hand.png"))
        self._plan(0, self._edit(0, picture="one-again.png"))
        self._plan(1, self._edit(1, picture="two-again.png"))
        done = self._apply()
        self.assertEqual([(item["segment_id"], item["reason"], item["expected_from"]) for item in done["conflicts"]],
                         [(first, "timeline_changed", "applied")])
        self.assertEqual([item["segment_id"] for item in done["applied"]], [second])
        self.assertEqual(self._row(first)["visual_path"], str(self.tmp / "by-hand.png"))
        self.assertEqual(self._row(second)["visual_path"], str(self.tmp / "two-again.png"))
        record = self.database.list_edit_applies(self.project_id, self.script_id)[0]["payload"]
        self.assertEqual((record["written"], [item["segment_id"] for item in record["conflicts"]]), ([second], [first]))

    def test_a_finished_scene_job_and_a_legacy_layer_write_are_conflicts(self) -> None:
        first, second = self._scene(0)["segment_id"], self._scene(1)["segment_id"]
        job = self.database.create_scene_generation_job(self.project_id, first, "dry_run", "p")
        self.database.finish_scene_generation_job(int(job["id"]), "completed", output_path=str(self.tmp / "job.png"))
        self.database.save_segment_edit_layers(second, overlays=[{"kind": "text", "text": "x", "start_seconds": 0, "end_seconds": 1}])
        self._plan(0, self._edit(0, picture="a.png"))
        self._plan(1, self._edit(1))
        done = self._apply()
        self.assertEqual(sorted((item["segment_id"], item["expected_from"]) for item in done["conflicts"]),
                         sorted([(first, "legacy"), (second, "legacy")]))
        self.assertEqual(self._row(first)["visual_path"], str(self.tmp / "job.png"))
        self.assertEqual(self._records(), 0)

    def test_a_row_the_apply_left_alone_still_expects_its_legacy_layers(self) -> None:
        segment_id = self._scene(0)["segment_id"]
        self._plan(0, self._edit(0))
        done = self._apply()
        self.assertEqual((done["applied"][0]["segment_id"], done["conflicts"]), (segment_id, []), "legacy as expected")


# ===========================================================================
# 5. Stale and unplanned scenes are not applied
# ===========================================================================

class StatusTests(_ApplyCase):
    @staticmethod
    def _document(*statuses: list[str]) -> dict:
        scenes = []
        for n, found in enumerate(statuses, start=1):
            value = ed.edit({"edit_transition": "fade"}, overlays=[{"kind": "text", "start_seconds": 0, "end_seconds": 1}])
            scenes.append({"scene_key": f"k{n}", "segment_id": 100 + n, "statuses": found, "edit": value,
                           "timing": {"state": ed.TIMING_KEPT}})
        return {"scenes": scenes, "orphans": []}

    def test_only_ready_and_visual_review_scenes_are_planned(self) -> None:
        rows, skipped = ea.plan(self._document([], [ed.VISUAL_REVIEW], [ed.NEEDS_PLAN], [ed.STALE_CONTENT, ed.VISUAL_REVIEW],
                                               [ed.STALE_OVERLAYS], [ed.STALE_TIMING]))
        self.assertEqual([item["scene_key"] for item in rows], ["k1", "k2"])
        self.assertEqual([(item["scene_key"], item["reason"]) for item in skipped],
                         [("k3", ea.NEEDS_PLAN), ("k4", ea.STALE), ("k5", ea.STALE), ("k6", ea.STALE)])

    def test_a_scene_whose_words_changed_is_left_as_it_is(self) -> None:
        for n in range(len(self._doc()["scenes"])):
            self._plan(n, self._edit(n, picture=f"p{n}.png"))
        at = self._first_of_section(self.project_id, 1)
        self._patch_lines(self.project_id, lambda lines: lines.__setitem__(at, lines[at].replace(" ", " mỗi ", 1).rsplit(" ", 1)[0] + "."))
        self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={"force": True})
        self._sync(self.project_id, self.script_id)
        stale = [item for item in self._doc()["scenes"] if ed.STALE_CONTENT in item["statuses"]]
        self.assertEqual(len(stale), 1, "the one scene whose words changed")
        self.assertIn(ed.VISUAL_REVIEW, stale[0]["statuses"])
        before = self._row(stale[0]["segment_id"])
        done = self._apply()
        self.assertIn((stale[0]["scene_key"], ea.STALE), {(item["scene_key"], item["reason"]) for item in done["skipped"]})
        after = self._row(stale[0]["segment_id"])
        self.assertEqual({key: after[key] for key in EDIT_OWNED_COLUMNS}, {key: before[key] for key in EDIT_OWNED_COLUMNS})


# ===========================================================================
# 6. Only the current document, on the rows it was built for
# ===========================================================================

class PreconditionTests(_ApplyCase):
    def test_a_document_behind_the_timeline_or_voices_is_refused(self) -> None:
        self._plan(0, self._edit(0, picture="a.png"))
        segment_id = self._scene(0)["segment_id"]
        self.database.update_project_timeline_segment(segment_id, duration_seconds=99)
        before = self._timeline_edit(self.project_id, self.script_id)
        with self.assertRaises(es.EditStoreError):
            self._apply()
        self.assertEqual((self._timeline_edit(self.project_id, self.script_id), self._records()), (before, 0))

    def test_no_current_document_is_refused(self) -> None:
        other = {**self._board_row(self.project_id, self.script_id), "document_hash": "another-cut"}
        with self.assertRaises(es.EditStoreError):
            ea.apply_scenes(self.database, self.project_id, self.script_id, other)

    def test_an_unknown_scene_is_refused(self) -> None:
        with self.assertRaises(es.EditStoreError) as refused:
            self._apply(scene_keys=["sk-nope"])
        self.assertEqual(refused.exception.status_code, 422)

    def test_a_row_of_another_script_is_never_written(self) -> None:
        other_project, other_script = self._project()
        foreign = self._timeline(other_project, other_script)[0]
        updates, beats, _ = ea.row_writes(self._edit(0, picture="x.png"))
        done = self.database.apply_edit_document_rows(
            self.project_id, self.script_id,
            [{"segment_id": int(foreign["id"]), "scene_key": "k", "layer_hash": "h", "legacy_hash": None,
              "default_hash": ea.DEFAULT_HASH, "updates": updates, "beats": beats, "visual_owned": True}],
            state_hash=ea.state_hash, record={})
        self.assertEqual([item["reason"] for item in done["skipped"]], ["missing_row"])
        self.assertEqual(self._row(int(foreign["id"]))["visual_path"], foreign["visual_path"])

    def test_only_owned_columns_can_be_written(self) -> None:
        segment_id = self._scene(0)["segment_id"]
        with self.assertRaises(ValueError):
            self.database.apply_edit_document_rows(
                self.project_id, self.script_id,
                [{"segment_id": segment_id, "scene_key": "k", "layer_hash": "h", "legacy_hash": None,
                  "default_hash": ea.DEFAULT_HASH, "updates": {"audio_path": ""}, "beats": [], "visual_owned": False}],
                state_hash=ea.state_hash, record={})
        self.assertTrue(self._row(segment_id)["audio_path"])


# ===========================================================================
# 7. One transaction: a real error rolls the whole apply back
# ===========================================================================

class TransactionTests(_ApplyCase):
    def test_an_error_half_way_leaves_every_row_and_no_record(self) -> None:
        self._plan(0, self._edit(0, picture="a.png"))
        self._plan(1, self._edit(1, picture="b.png"))
        before = self._timeline_edit(self.project_id, self.script_id)
        calls = {"n": 0}
        real = ea.state_hash

        def failing(segment, beats):
            calls["n"] += 1
            if calls["n"] == 4:   # both rows read and written; reading the second back, the system fails
                raise RuntimeError("disk gone")
            return real(segment, beats)

        with mock.patch.object(ea, "state_hash", failing), self.assertRaises(RuntimeError):
            self._apply()
        self.assertEqual(calls["n"], 4)
        self.assertNotEqual(self._row(self._scene(0)["segment_id"])["visual_path"], str(self.tmp / "a.png"),
                            "the first row was written before the error, and rolled back with the rest")
        self.assertEqual(self._timeline_edit(self.project_id, self.script_id), before)
        self.assertEqual(self._records(), 0)


# ===========================================================================
# 8. Applying the same document again writes nothing
# ===========================================================================

class IdempotenceTests(_ApplyCase):
    def test_the_same_document_twice_writes_and_records_nothing_the_second_time(self) -> None:
        self._plan(0, self._edit(0, picture="a.png"))
        first = self._apply()
        segment_id = first["applied"][0]["segment_id"]
        stamp = self._row(segment_id)["updated_at"]
        again = self._apply()
        self.assertEqual((again["applied"], again["artifact_id"], [item["segment_id"] for item in again["unchanged"]]),
                         ([], None, [segment_id]))
        self.assertEqual((self._records(), self._row(segment_id)["updated_at"]), (1, stamp))

    def test_a_new_edit_for_an_applied_row_is_written(self) -> None:
        self._plan(0, self._edit(0, picture="a.png"))
        self._apply()
        self._plan(0, self._edit(0, picture="b.png"))
        done = self._apply()
        self.assertEqual(done["applied"][0]["segment_id"], self._scene(0)["segment_id"])
        self.assertEqual(self._row(self._scene(0)["segment_id"])["visual_path"], str(self.tmp / "b.png"))
        self.assertEqual(self._records(), 2)


# ===========================================================================
# 9. Beats a job made, and rows a job is still making
# ===========================================================================

class BeatTests(_ApplyCase):
    def test_a_beat_given_a_generated_asset_is_not_replaced_unseen(self) -> None:
        self._plan(0, self._edit(0, picture="a.png"))
        segment_id = self._apply()["applied"][0]["segment_id"]
        asset = self.database.create_project_asset(self.project_id, "image", "gen.png", str(self.tmp / "gen.png"))
        beat = self._beats(segment_id)[0]
        self.database.attach_asset_to_edit_beat(int(beat["id"]), int(asset["id"]))
        self._plan(0, self._edit(0, picture="b.png"))
        done = self._apply()
        self.assertEqual([item["segment_id"] for item in done["conflicts"]], [segment_id])
        self.assertEqual(self._beats(segment_id)[0]["asset_id"], int(asset["id"]))

    def test_a_row_with_a_scene_job_still_running_is_skipped(self) -> None:
        segment_id = self._scene(0)["segment_id"]
        self.database.create_scene_generation_job(self.project_id, segment_id, "dry_run", "p")
        self._plan(0, self._edit(0, picture="a.png"))
        done = self._apply()
        self.assertEqual([(item["segment_id"], item["reason"]) for item in done["skipped"] if item["segment_id"] == segment_id],
                         [(segment_id, "scene_job_running")])
        self.assertNotEqual(self._row(segment_id)["visual_path"], str(self.tmp / "a.png"))

    def test_a_beat_naming_an_asset_of_another_project_is_skipped(self) -> None:
        other_project, _ = self._project()
        foreign = self.database.create_project_asset(other_project, "image", "x.png", str(self.tmp / "x.png"))
        seconds = float(self._scene(0)["voice"]["duration_seconds"])
        self._plan(0, ed.edit({"edit_transition": "fade"},
                              beats=[{"asset_id": int(foreign["id"]), "visual_path": "x.png", "start_seconds": 0.0,
                                      "duration_seconds": seconds}]))
        done = self._apply()
        self.assertEqual([item["reason"] for item in done["skipped"] if item["scene_key"] == self._scene(0)["scene_key"]],
                         ["unknown_asset"])


# ===========================================================================
# 10. Apart from the legacy Edit Plan, and from the generic artifact calls
# ===========================================================================

class SeparationTests(_ApplyCase):
    def test_an_apply_never_touches_the_legacy_edit_plan_and_its_record_is_its_own(self) -> None:
        self.database.save_project_edit_plan(self.project_id, self.script_id, "rev", {"scenes": []})
        self._plan(0, self._edit(0, picture="a.png"))
        self._apply()
        self.assertEqual(self._edit_plan_rows(self.project_id), 1)
        self.assertEqual(self.database.get_project_edit_plan(self.project_id, self.script_id)["plan"], {"scenes": []})
        with self.assertRaises(ValueError):
            self.database.save_director_artifact(self.project_id, EDIT_APPLY_KIND, {"rows": []})
        with self.assertRaises(ValueError):
            self.database.get_director_artifact(self.project_id, EDIT_APPLY_KIND)

    def test_a_broken_apply_record_is_refused_not_skipped(self) -> None:
        self._plan(0, self._edit(0, picture="a.png"))
        record = self._apply()["artifact_id"]
        self._overwrite(record, "{broken")
        self._plan(0, self._edit(0, picture="b.png"))
        with self.assertRaises(es.EditStoreError):
            self._apply()


# ===========================================================================
# B1. Naming no beats is not asking for none: the row's beats stay
# ===========================================================================

class _LegacyBeatCase(_ApplyCase):
    """A row that had an inserted beat before the first EditDocument."""

    def setUp(self) -> None:
        _StoreCase.setUp(self)
        self._hold_scene_worker()
        self.project_id, self.script_id = self._project()
        first = self._timeline(self.project_id, self.script_id)[0]
        self.database.replace_timeline_edit_beats(int(first["id"]), [
            {"visual_path": str(self.tmp / "legacy-insert.png"), "source_kind": "ai_image", "duration_seconds": 1.0}])
        self.legacy_beats = self._beats(int(first["id"]))
        self.legacy_picture = first["visual_path"]
        self.bootstrap = self._sync(self.project_id, self.script_id)

    def _beat_rows(self, segment_id: int) -> list[tuple]:
        return [(beat["id"], beat["visual_path"], beat["start_seconds"], beat["duration_seconds"]) for beat in self._beats(segment_id)]


class LegacyBeatTests(_LegacyBeatCase):
    def test_an_edit_without_beats_leaves_the_legacy_beats_as_they_are(self) -> None:
        segment_id = self._scene(0)["segment_id"]
        before = self._beat_rows(segment_id)
        self._plan(0, self._edit(0, beats=False))
        done = self._apply()
        self.assertEqual((done["applied"][0]["segment_id"], done["applied"][0]["beats_written"]), (segment_id, None))
        self.assertEqual(self._beat_rows(segment_id), before, "same beats, same ids: nothing deleted")
        self.assertTrue(main.json.loads(self._row(segment_id)["overlays"]), "the layers it names are written")

    def test_the_legacy_picture_and_beats_both_stay(self) -> None:
        segment_id = self._scene(0)["segment_id"]
        self._plan(0, self._edit(0, picture=None, beats=False, transition="cut"))
        self._apply()
        row = self._row(segment_id)
        self.assertEqual((row["visual_path"], row["edit_transition"]), (self.legacy_picture, "cut"))
        self.assertEqual([beat["visual_path"] for beat in self._beats(segment_id)], [str(self.tmp / "legacy-insert.png")])
        self.assertTrue(Path(self.legacy_picture).is_file())

    def test_an_edit_that_names_beats_replaces_them(self) -> None:
        segment_id = self._scene(0)["segment_id"]
        edit = self._edit(0)
        self._plan(0, edit)
        done = self._apply()
        self.assertEqual(done["applied"][0]["beats_written"], 2)
        self.assertEqual([(beat["beat_index"], beat["visual_path"], beat["duration_seconds"]) for beat in self._beats(segment_id)],
                         [(1, "b0a.png", edit["beats"][0]["duration_seconds"]), (2, "b0b.png", edit["beats"][1]["duration_seconds"])])

    def test_applying_the_same_document_again_leaves_the_beats_alone(self) -> None:
        segment_id = self._scene(0)["segment_id"]
        self._plan(0, self._edit(0))
        self._apply()
        before = self._beat_rows(segment_id)
        again = self._apply()
        self.assertEqual(([item["segment_id"] for item in again["unchanged"]], again["applied"]), ([segment_id], []))
        self.assertEqual(self._beat_rows(segment_id), before)

    def test_beats_written_since_by_another_path_are_a_conflict_not_deleted(self) -> None:
        segment_id = self._scene(0)["segment_id"]
        self._plan(0, self._edit(0))
        self._apply()
        self.database.replace_timeline_edit_beats(segment_id, [{"visual_path": "outside.png", "duration_seconds": 2.0}])
        outside = self._beat_rows(segment_id)
        self._plan(0, self._edit(0, picture="next.png"))
        done = self._apply()
        self.assertEqual([item["segment_id"] for item in done["conflicts"]], [segment_id])
        self.assertEqual(self._beat_rows(segment_id), outside)

    def test_an_edit_without_beats_after_one_with_beats_keeps_them(self) -> None:
        segment_id = self._scene(0)["segment_id"]
        self._plan(0, self._edit(0))
        self._apply()
        before = self._beat_rows(segment_id)
        self._plan(0, self._edit(0, beats=False, transition="cut"))
        done = self._apply()
        self.assertEqual((done["applied"][0]["segment_id"], self._row(segment_id)["edit_transition"]), (segment_id, "cut"))
        self.assertEqual(self._beat_rows(segment_id), before)


# ===========================================================================
# B2. Beats a scene job points at are never deleted, whatever the job's status
# ===========================================================================

class BeatJobTests(_ApplyCase):
    def _held(self, status: str) -> tuple[int, dict, list, str]:
        """Scene 0 applied with beats, then a scene job made for its first beat, left in `status`."""
        self._plan(0, self._edit(0, picture="mine.png"))
        segment_id = self._apply()["applied"][0]["segment_id"]
        beats = self._beats(segment_id)
        job = self.database.create_scene_generation_job(self.project_id, segment_id, "dry_run", "p",
                                                        edit_beat_id=int(beats[0]["id"]))
        with self.database._connect() as connection:
            connection.execute("UPDATE scene_generation_jobs SET status = ? WHERE id = ?", (status, int(job["id"])))
        return segment_id, job, beats, self._row(segment_id)["visual_path"]

    def _assert_held(self, status: str) -> None:
        segment_id, job, beats, picture = self._held(status)
        self._plan(0, self._edit(0, picture="other.png"))
        done = self._apply()
        self.assertEqual([(item["segment_id"], item["reason"]) for item in done["skipped"] if item["segment_id"] == segment_id],
                         [(segment_id, "beat_has_jobs")], status)
        self.assertEqual(done["applied"], [], status)
        self.assertEqual(self._row(segment_id)["visual_path"], picture, status)
        self.assertEqual([beat["id"] for beat in self._beats(segment_id)], [beat["id"] for beat in beats], status)
        self.assertEqual(self.database.get_scene_generation_job(int(job["id"]))["edit_beat_id"], int(beats[0]["id"]), status)

    def test_a_running_job_holds_its_beat(self) -> None:
        self._assert_held("running")

    def test_a_queued_job_holds_its_beat(self) -> None:
        self._assert_held("queued")

    def test_a_failed_job_holds_its_beat(self) -> None:
        self._assert_held("error")

    def test_a_cancelled_job_holds_its_beat(self) -> None:
        self._assert_held("cancelled")

    def test_a_finished_job_holds_its_beat_too(self) -> None:
        self._assert_held("completed")

    def test_a_job_retried_after_the_apply_never_writes_over_the_scene(self) -> None:
        segment_id, job, beats, picture = self._held("cancelled")
        self._plan(0, self._edit(0, picture="other.png"))
        self._apply()
        self.assertTrue(self.database.retry_scene_generation_job(int(job["id"])))
        self.database.finish_scene_generation_job(int(job["id"]), "completed", output_path=str(self.tmp / "retried.png"))
        self.assertEqual(self._row(segment_id)["visual_path"], picture, "the scene keeps its picture")
        self.assertEqual(self._beats(segment_id)[0]["visual_path"], str(self.tmp / "retried.png"), "the job lands in its beat")
        self.assertEqual(self.database.get_scene_generation_job(int(job["id"]))["edit_beat_id"], int(beats[0]["id"]))

    def test_beats_no_job_points_at_can_be_replaced(self) -> None:
        segment_id, job, _, _ = self._held("cancelled")
        other = self._scene(1)["segment_id"]
        self._plan(1, self._edit(1, picture="b.png"))
        done = self._apply()
        self.assertIn(other, [item["segment_id"] for item in done["applied"]], "a job on another row's beat holds only that row")
        self.assertEqual([beat["visual_path"] for beat in self._beats(other)], ["b1a.png", "b1b.png"])


# ===========================================================================
# B3. An edit the timeline cannot hold is skipped; only a system error rolls back
# ===========================================================================

class InvalidEditTests(_ApplyCase):
    def _bad(self, n: int, visual: dict | None = None, beats: list | None = None) -> None:
        seconds = float(self._scene(n)["voice"]["duration_seconds"])
        self._plan(n, ed.edit(visual or {"edit_transition": "fade"},
                              overlays=[{"kind": "text", "start_seconds": 0.0, "end_seconds": round(seconds / 2, 3)}], beats=beats))

    def test_an_empty_value_where_one_is_needed_is_skipped_and_the_valid_scene_still_applies(self) -> None:
        self._plan(0, self._edit(0, picture="ok.png"))
        self._bad(1, {"edit_transition": None})
        first, second = self._scene(0)["segment_id"], self._scene(1)["segment_id"]
        before = self._row(second)
        done = self._apply()
        self.assertEqual([item["segment_id"] for item in done["applied"]], [first])
        self.assertEqual([(item["segment_id"], item["reason"]) for item in done["skipped"] if item["segment_id"] == second],
                         [(second, ea.INVALID_EDIT)])
        self.assertIsNotNone(done["artifact_id"])
        self.assertEqual(self._row(first)["visual_path"], str(self.tmp / "ok.png"), "committed")
        self.assertEqual({key: self._row(second)[key] for key in EDIT_OWNED_COLUMNS}, {key: before[key] for key in EDIT_OWNED_COLUMNS})

    def test_an_asset_id_that_is_not_a_number_is_an_invalid_edit(self) -> None:
        seconds = float(self._scene(0)["voice"]["duration_seconds"])
        self._bad(0, beats=[{"asset_id": "abc", "visual_path": "x.png", "start_seconds": 0.0, "duration_seconds": seconds}])
        done = self._apply()
        found = [item for item in done["skipped"] if item["scene_key"] == self._scene(0)["scene_key"]]
        self.assertEqual(found[0]["reason"], ea.INVALID_EDIT)
        self.assertIn("asset_id", found[0]["detail"])

    def test_a_bad_last_scene_never_costs_the_scenes_before_it(self) -> None:
        count = len(self._doc()["scenes"])
        for n in range(count - 1):
            self._plan(n, self._edit(n, picture=f"p{n}.png"))
        self._bad(count - 1, {"visual_fps": "eight"})
        done = self._apply()
        self.assertEqual(len(done["applied"]), count - 1)
        self.assertEqual([item["reason"] for item in done["skipped"] if item["scene_key"] == self._scene(count - 1)["scene_key"]],
                         [ea.INVALID_EDIT])
        self.assertTrue(all(self._row(self._scene(n)["segment_id"])["visual_path"] == str(self.tmp / f"p{n}.png")
                            for n in range(count - 1)))

    def test_the_database_names_a_bad_value_before_writing_never_by_an_integrity_error(self) -> None:
        first, second = self._scene(0)["segment_id"], self._scene(1)["segment_id"]
        good, _, _ = ea.row_writes(self._edit(0, picture="db.png", beats=False))
        done = self.database.apply_edit_document_rows(
            self.project_id, self.script_id,
            [{"segment_id": second, "scene_key": "k2", "layer_hash": "h2", "legacy_hash": self._legacy(second),
              "default_hash": ea.DEFAULT_HASH, "updates": {"edit_transition": None}, "beats": None, "visual_owned": False},
             {"segment_id": first, "scene_key": "k1", "layer_hash": "h1", "legacy_hash": self._legacy(first),
              "default_hash": ea.DEFAULT_HASH, "updates": good, "beats": None, "visual_owned": True}],
            state_hash=ea.state_hash, record={})
        self.assertEqual([(item["segment_id"], item["reason"]) for item in done["skipped"]], [(second, "invalid_edit")])
        self.assertEqual([item["segment_id"] for item in done["written"]], [first])

    def test_an_edit_of_the_wrong_shape_is_named_by_the_engine(self) -> None:
        for bad in (ed.edit({"content_dna": [1]}), ed.edit({"content_dna": "[1]"}), ed.edit({"edit_cleanups": "{not json"}),
                    ed.edit({}, overlays=["text"]), ed.edit({}, beats=[{"visual_path": "a", "colour": "red"}]),
                    ed.edit({}, beats=["a"]), ed.edit({"edit_note": {"a": 1}})):
            with self.assertRaises(ea.InvalidEditError, msg=str(bad)):
                ea.row_writes(bad)

    def test_an_edit_the_engine_cannot_shape_is_skipped_and_the_valid_scene_still_applies(self) -> None:
        self._plan(0, self._edit(0, picture="ok.png"))
        self._bad(1, {"content_dna": "[1]"})
        done = self._apply()
        self.assertEqual([item["segment_id"] for item in done["applied"]], [self._scene(0)["segment_id"]])
        found = [item for item in done["skipped"] if item["scene_key"] == self._scene(1)["scene_key"]]
        self.assertEqual((found[0]["reason"], "content_dna" in found[0]["detail"]), (ea.INVALID_EDIT, True))

    def _legacy(self, segment_id: int) -> str | None:
        return next((ed.edit_hash(item["edit"]) for item in self._doc()["orphans"] if item["segment_id"] == segment_id), None)


# ===========================================================================
# B4. What each row was given is in the record
# ===========================================================================

class RecordTests(_ApplyCase):
    def test_the_record_names_the_columns_and_beats_written(self) -> None:
        self._plan(0, self._edit(0, picture="a.png"))
        self._plan(1, self._edit(1, beats=False))
        rows, _ = ea.plan(self._doc())
        self._apply()
        record = {item["segment_id"]: item for item in self.database.list_edit_applies(self.project_id, self.script_id)[0]["payload"]["rows"]}
        for planned in rows:
            item = record[planned["segment_id"]]
            self.assertEqual(item["columns_written"], sorted(planned["updates"]))
            self.assertEqual(item["beats_written"], None if planned["beats"] is None else len(planned["beats"]))
            self.assertEqual(set(item), {"segment_id", "scene_key", "layer_hash", "state_hash", "visual_owned",
                                         "columns_written", "beats_written"})
        self.assertIn("visual_path", record[self._scene(0)["segment_id"]]["columns_written"])
        self.assertNotIn("visual_path", record[self._scene(1)["segment_id"]]["columns_written"])
