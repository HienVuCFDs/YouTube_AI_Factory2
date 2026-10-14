"""Bước 05 · T7 hardening · một job tạo hình và một lần thay nhịp dựng của cùng cảnh không bao giờ đan xen.

Cả hai lấy khoá ghi của SQLite (BEGIN IMMEDIATE) trước lần đọc đầu tiên rồi kiểm và ghi trong cùng giao dịch:

* job trước: lần thay nhịp đợi khoá, rồi thấy job đang trỏ vào nhịp - từ chối, không ghi gì;
* thay nhịp trước: lần tạo job đợi khoá, rồi thấy nhịp nó định tạo hình đã đổi hoặc đã bị xoá - từ chối, không có job.

Thứ tự được ép bằng sự kiện, không bằng thời gian. Luồng thứ nhất dừng ngay trước lần ghi đầu tiên của nó - đã đọc và
kiểm, chưa ghi: khe mà một luồng khác chen vào nếu không có khoá. Ở đó một kết nối thử với timeout=0 phải thấy khoá ghi
đang bị giữ; rồi luồng thứ hai chạy cho tới khi đứng ngay trước BEGIN IMMEDIATE của nó (hoặc xong hẳn, nếu nó không
lấy khoá), và chỉ khi đó luồng thứ nhất mới ghi và commit.
Mọi test chạy trên DB tạm của bộ test (tests/conftest.py); không gọi AI, không chạy app hay worker.
"""

from __future__ import annotations

import contextlib
import sqlite3
import tempfile
import threading
from pathlib import Path
from unittest import mock

from tests.test_legacy_timeline_writes import _LegacyCase
from youtube_monitor import main
from youtube_monitor.database import SceneJobConflict

WAIT = 30   # a safety net against a hang only: every wait below is released by an event, never by the clock
_WRITES = ("INSERT", "UPDATE", "DELETE")


class _Race:
    """Two DB calls: the first held just before its first write until the second is at its BEGIN IMMEDIATE (or done)."""

    def __init__(self, database) -> None:
        self.database = database
        self.local = threading.local()
        self.log: list[str] = []
        self.guard = threading.Lock()
        self.first_paused = threading.Event()
        self.second_at_lock = threading.Event()

    def note(self, what: str) -> None:
        with self.guard:
            self.log.append(what)

    @contextlib.contextmanager
    def connect(self):
        # Database._connect, line for line, with a note just before a write transaction commits.
        connection = sqlite3.connect(self.database.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        held = _Held(connection, self)
        try:
            yield held
            if held.locked or held.wrote:
                self.note(f"{held.role} commits")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def run(self, first, second) -> dict:
        outcome: dict = {}

        def play(role, call):
            self.local.role = role
            try:
                outcome[role] = call()
            except Exception as exc:          # noqa: BLE001 - what each side ended with is the result
                outcome[role] = exc
            finally:
                if role == "second":
                    self.note("second done")
                    self.second_at_lock.set()     # a second call that never takes the lock releases the first too

        with mock.patch.object(self.database, "_connect", self.connect):
            one = threading.Thread(target=play, args=("first", first))
            one.start()
            assert self.first_paused.wait(WAIT), "the first call never reached its first write"
            probe = sqlite3.connect(self.database.path, timeout=0)
            try:
                probe.execute("BEGIN IMMEDIATE")
                outcome["probe"] = "got the lock"
                probe.rollback()
            except sqlite3.OperationalError as exc:
                outcome["probe"] = str(exc)
            finally:
                probe.close()
            two = threading.Thread(target=play, args=("second", second))
            two.start()
            one.join(WAIT)
            two.join(WAIT)
            assert not one.is_alive() and not two.is_alive(), "a call never finished"
        return outcome


class _Held:
    """A connection that tells _Race where its call stands: at its BEGIN IMMEDIATE, holding it, at its first write."""

    def __init__(self, connection, race: _Race) -> None:
        self.connection, self.race = connection, race
        self.role = getattr(race.local, "role", "")
        self.locked = self.wrote = False

    def execute(self, sql, *args):
        statement = str(sql).lstrip().upper()
        if self.role and statement.startswith("BEGIN IMMEDIATE"):
            if self.role == "second":
                self.race.note("second at the lock")
                self.race.second_at_lock.set()
            result = self.connection.execute(sql, *args)
            self.locked = True
            self.race.note(f"{self.role} locked")
            return result
        if self.role == "first" and statement.startswith(_WRITES) and not self.race.first_paused.is_set():
            self.race.note("first read, about to write")
            self.race.first_paused.set()
            assert self.race.second_at_lock.wait(WAIT), "the second call never reached the lock"
        if self.role and statement.startswith(_WRITES):
            self.wrote = True
        return self.connection.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self.connection, name)


class _RaceCase(_LegacyCase):
    def setUp(self) -> None:
        super().setUp()
        seconds = self._seconds()
        response = self.client.put(f"/api/timeline/{self.target}/edit-beats", json={"beats": [
            {"duration_seconds": round(seconds / 2, 3), "source_kind": "ai_image", "prompt": "nhịp A"},
            {"duration_seconds": round(seconds - round(seconds / 2, 3), 3), "source_kind": "ai_image", "prompt": "nhịp B"}]})
        self.assertEqual(response.status_code, 200, response.text)
        self.beats = self._beats(self.target)

    def _new_job(self, beat: dict | None, seen: dict | None = None):
        options = {"edit_beat_id": int(beat["id"]), "edit_beat_seen": seen or beat} if beat else {}
        return lambda: self.database.create_scene_generation_job(self.project_id, self.target, "dry_run", "p",
                                                                 job_kind="image", **options)

    def _replace(self, beats: list[dict]):
        return lambda: self.database.replace_timeline_edit_beats(self.target, beats, refuse_if_held=True)

    def _one_beat(self, prompt: str = "thay") -> list[dict]:
        return [{"duration_seconds": self._seconds(), "source_kind": "ai_image", "prompt": prompt}]

    def _jobs(self) -> list[dict]:
        with self.database._connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM scene_generation_jobs WHERE timeline_segment_id = ? ORDER BY id", (self.target,))]

    def _sound(self) -> None:
        """No job without its beat, no job pointing at another scene's beat, no beat of a job deleted."""
        with self.database._connect() as connection:
            orphans = connection.execute(
                "SELECT j.id FROM scene_generation_jobs j LEFT JOIN project_timeline_edit_beats b ON b.id = j.edit_beat_id "
                "WHERE j.edit_beat_id IS NOT NULL AND (b.id IS NULL OR b.timeline_segment_id != j.timeline_segment_id)").fetchall()
        self.assertEqual(orphans, [])

    def _ordered(self, race: _Race, outcome: dict) -> None:
        self.assertIn("locked", outcome["probe"], "between the first call's check and its write, nobody else can write")
        log = race.log
        self.assertLess(log.index("second at the lock"), log.index("first commits"), log)
        if "second locked" in log:
            self.assertGreater(log.index("second locked"), log.index("first commits"), log)


class JobFirstTests(_RaceCase):
    def test_a_job_made_first_holds_its_beat_against_a_replace_waiting_for_the_lock(self) -> None:
        beat = self.beats[1]
        race = _Race(self.database)
        outcome = race.run(self._new_job(beat), self._replace(self._one_beat()))
        self._ordered(race, outcome)
        job = outcome["first"]
        self.assertEqual(int(job["edit_beat_id"]), int(beat["id"]))
        self.assertIsInstance(outcome["second"], SceneJobConflict)
        self.assertEqual(outcome["second"].reason, "scene_job_running", "the new job is queued: not finished")
        self.assertEqual(self._beats(self.target), self.beats, "the replace wrote nothing")
        # Cancelled, it still points at its beat (it can be retried): the beats stay held.
        self.database.cancel_queued_scene_generation_job(int(job["id"]))
        with self.assertRaises(SceneJobConflict) as held:
            self._replace(self._one_beat())()
        self.assertEqual(held.exception.reason, "beat_has_jobs")
        self.assertEqual(self._beats(self.target), self.beats)
        self.assertEqual(int(self.database.get_scene_generation_job(int(job["id"]))["edit_beat_id"]), int(beat["id"]))
        self._sound()

    def test_a_scene_job_made_first_holds_the_beats_against_a_replace_waiting_for_the_lock(self) -> None:
        race = _Race(self.database)
        outcome = race.run(self._new_job(None), self._replace(self._one_beat()))
        self._ordered(race, outcome)
        self.assertIsInstance(outcome["second"], SceneJobConflict)
        self.assertEqual(outcome["second"].reason, "scene_job_running")
        self.assertEqual(self._beats(self.target), self.beats)
        self._sound()


class ReplaceFirstTests(_RaceCase):
    def test_a_job_waiting_for_the_lock_finds_its_beat_deleted_and_is_never_made(self) -> None:
        beat = self.beats[1]                              # beat 2: a one-beat replace deletes it
        race = _Race(self.database)
        outcome = race.run(self._replace(self._one_beat()), self._new_job(beat))
        self._ordered(race, outcome)
        self.assertEqual([item["prompt"] for item in outcome["first"]], ["thay"])
        self.assertIsInstance(outcome["second"], SceneJobConflict)
        self.assertEqual(outcome["second"].reason, "beat_gone")
        self.assertEqual(self._jobs(), [])
        self._sound()

    def test_a_job_waiting_for_the_lock_finds_its_beat_changed_and_is_never_made(self) -> None:
        beat = self.beats[0]                              # beat 1: kept by id, its prompt replaced
        race = _Race(self.database)
        outcome = race.run(self._replace(self._one_beat("nhịp mới")), self._new_job(beat))
        self._ordered(race, outcome)
        self.assertEqual([(item["id"], item["prompt"]) for item in outcome["first"]], [(beat["id"], "nhịp mới")])
        self.assertIsInstance(outcome["second"], SceneJobConflict)
        self.assertEqual(outcome["second"].reason, "beat_changed")
        self.assertEqual(self._jobs(), [])
        self._sound()

    def test_a_job_on_a_beat_the_replace_left_as_it_was_is_made_after_it(self) -> None:
        # The replace rewrote beat 1 with what it already held: the job sees it as it was and is made.
        beat = self.beats[0]
        same = [{key: beat[key] for key in ("duration_seconds", "source_kind", "prompt")},
                {key: self.beats[1][key] for key in ("duration_seconds", "source_kind", "prompt")}]
        race = _Race(self.database)
        outcome = race.run(self._replace(same), self._new_job(beat))
        self._ordered(race, outcome)
        self.assertEqual(int(outcome["second"]["edit_beat_id"]), int(beat["id"]))
        self._sound()


class WithoutAJobTests(_RaceCase):
    def test_a_replace_with_no_job_and_a_job_made_without_a_seen_beat_behave_as_before(self) -> None:
        replaced = self.database.replace_timeline_edit_beats(self.target, self._one_beat(), refuse_if_held=True)
        self.assertEqual([item["prompt"] for item in replaced], ["thay"])
        # A caller that names no beat it saw keeps the old check only (the beat is the scene's).
        job = self.database.create_scene_generation_job(self.project_id, self.target, "dry_run", "p",
                                                        edit_beat_id=int(replaced[0]["id"]))
        self.assertEqual(int(job["edit_beat_id"]), int(replaced[0]["id"]))
        self.assertIsNone(self.database.create_scene_generation_job(self.project_id, self.target, "dry_run", "p",
                                                                    edit_beat_id=int(self.beats[1]["id"])))
        # Without refuse_if_held (the internal callers that make a scene's first beat) nothing is checked, as before.
        again = self.database.replace_timeline_edit_beats(self.target, self._one_beat("lại"))
        self.assertEqual([item["prompt"] for item in again], ["lại"])
        self._sound()


class RouteTests(_RaceCase):
    def test_a_beat_changed_since_the_route_read_it_is_a_409_and_no_job(self) -> None:
        beat = self.beats[0]
        original = main._queue_edit_beat_image

        def queue_after_a_replace(segment, seen, provider, ratio):
            self.database.replace_timeline_edit_beats(self.target, self._one_beat("đổi giữa chừng"), refuse_if_held=True)
            return original(segment, seen, provider, ratio)

        with mock.patch.object(main, "_queue_edit_beat_image", side_effect=queue_after_a_replace), \
                mock.patch.object(main, "_require_scene_provider_config"), \
                mock.patch.object(main, "_enforce_provider_billing_policy"):
            response = self.client.post(f"/api/timeline/{self.target}/edit-beats/1/generate",
                                        json={"image_provider": "gemini_web_image", "confirmed": True})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self._jobs(), [])
        self.assertEqual(self._beats(self.target)[0]["status"], "needs_asset", "never marked generating")
        self._sound()

    def test_a_job_the_route_did_not_see_is_still_a_409_from_the_database(self) -> None:
        # The route's own early check passes (no job yet); a job made just before the replace holds the beats.
        job_made = []
        original = main._refuse_scene_jobs_holding

        def check_then_a_job_arrives(segment_id, **options):
            original(segment_id, **options)
            job_made.append(self._new_job(self.beats[0])())

        with mock.patch.object(main, "_refuse_scene_jobs_holding", side_effect=check_then_a_job_arrives):
            response = self.client.put(f"/api/timeline/{self.target}/edit-beats", json={"beats": self._one_beat()})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(len(job_made), 1)
        self.assertEqual(self._beats(self.target), self.beats)
        self._sound()

    def _approved_edit_plan(self) -> dict:
        """A legacy Edit Plan, approved, for this script as it is now: applying it replaces every scene's beats."""
        script = self.database.get_latest_project_script(self.project_id)
        timeline = self.database.list_project_timeline(self.project_id, script_id=int(script["id"]))
        return self.database.save_project_edit_plan(
            self.project_id, int(script["id"]), main._edit_plan_source_revision(script, timeline),
            {"scenes": [{"segment_id": self.target, "kind": "image", "transition": "cut", "effect": "static"}]},
            status="approved")

    def test_the_legacy_edit_plan_never_deletes_beats_a_job_points_at(self) -> None:
        job = self._new_job(self.beats[0])()
        self.database.cancel_queued_scene_generation_job(int(job["id"]))    # finished, still pointing at its beat
        plan = self._approved_edit_plan()
        state = self._state()
        response = self.client.post(f"/api/projects/{self.project_id}/edit-plan/apply")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self._state(), state, "refused before anything, the plan's status included")
        self.assertEqual(self.database.get_project_edit_plan(self.project_id)["status"], plan["status"])
        self._sound()

    def test_a_job_made_after_the_early_answer_still_holds_the_beats_in_the_legacy_edit_plan(self) -> None:
        self._approved_edit_plan()
        original = main._refuse_scene_jobs_holding
        made = []

        def check_then_a_job_arrives(segment_id, **options):
            original(segment_id, **options)
            made.append(self._new_job(self.beats[0])())

        with mock.patch.object(main, "_refuse_scene_jobs_holding", side_effect=check_then_a_job_arrives):
            response = self.client.post(f"/api/projects/{self.project_id}/edit-plan/apply")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(len(made), 1)
        self.assertEqual(self._beats(self.target), self.beats, "the whole apply rolled back")
        self.assertEqual(self.database.get_project_edit_plan(self.project_id)["status"], "approved")
        self._sound()

    def test_the_legacy_edit_plan_applies_as_before_with_no_job(self) -> None:
        self._approved_edit_plan()
        response = self.client.post(f"/api/projects/{self.project_id}/edit-plan/apply")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.database.get_project_edit_plan(self.project_id)["status"], "ready")

    def test_the_worker_still_finishes_a_beats_job(self) -> None:
        beat = self.beats[0]
        job = self._new_job(beat)()
        folder = tempfile.TemporaryDirectory(prefix="t7_race_")
        self.addCleanup(folder.cleanup)
        picture = Path(folder.name) / "race-done.png"
        picture.write_bytes(b"\x89PNG\r\n\x1a\n")
        done = self.database.finish_scene_generation_job(int(job["id"]), "completed", str(picture))
        self.assertEqual(done["status"], "completed")
        finished = next(item for item in self._beats(self.target) if item["id"] == beat["id"])
        self.assertEqual((finished["visual_path"], finished["status"]), (str(picture), "ready"))
        # The beat is still held: the job could be marked failed in review and retried.
        response = self.client.put(f"/api/timeline/{self.target}/edit-beats", json={"beats": self._one_beat()})
        self.assertEqual(response.status_code, 409, response.text)
        self._sound()
