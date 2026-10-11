"""Bước 05 · P2-4 · chỉnh sửa tay trước EditDocument: chốt hành vi bằng test (giai đoạn 1, F2, F1, F3).

    Sửa cảnh (PATCH /api/timeline/{id}, …/plan, …/edit-beats) ─→ hàng timeline
    "Áp dụng vào timeline…" (POST …/steps/edit_plan, confirmed_apply) ─→ sync ─→ (AI giả) ─→ apply ─→ hàng timeline
    Tạo lại storyboard / kịch bản mới ─→ reconcile ─→ sync(refresh) ─→ apply

Lệnh áp chỉ so những cột nó sẽ ghi (F1) với điều EditDocument biết lần cuối;
cột nó không ghi được để nguyên và không gây xung đột.

1. Sửa riêng visual_prompt trước khi áp: mô tả tay được giữ, cảnh vẫn được
   áp kế hoạch (kế hoạch không ghi visual_prompt nên không xung đột).
2. Sửa riêng visual_prompt sau khi đã áp: mô tả tay được giữ, cảnh lập lại và
   áp tiếp được; bản ghi áp vẫn nhớ mô tả cũ (state_edit), không nhận mô tả tay.
3. Kế hoạch do AI lập không có visual_prompt / visual_path; lệnh áp không ghi
   hai cột đó, và không ghi project_shots. Trường lớp dựng kế hoạch sẽ ghi bị
   sửa tay: xung đột, không ghi đè; nhịp dựng tay mà kế hoạch không ghi: không
   xung đột, giữ nguyên.
4. Lớp dựng sửa tay (chuyển cảnh, hiệu ứng, chữ, âm thanh, hướng dựng, nhịp)
   trên hàng chưa áp: luôn giữ nguyên và báo xung đột - không có reconcile,
   sau kịch bản mới (kể cả lần tự áp khi tạo lại storyboard), sau đổi lời
   cảnh, và sau timeline của agent. Từ F2, hàng đang giữ chỉnh sửa tay không
   bao giờ được nhận làm mốc "legacy" mới (refresh) để kế hoạch ghi đè.
   Reconcile nhận hàng đó theo từng phần (edit_apply.held_edits): phần sửa
   tay giữ mốc cũ, phần còn lại (lớp legacy nó chép/căn lại) là đã biết.
7. Chỉ sửa tay mô tả hình rồi reconcile (kịch bản mới, đổi lời cảnh): lớp
   dựng legacy được chép/căn lại không gây xung đột, kế hoạch được áp, mô tả
   tay giữ nguyên và vẫn chưa được nhận là đã biết.
5. GET …/edit-document sau khi đổi thời lượng (F3): trả đúng điều lần sync kế
   tiếp sẽ lưu (edit_store.preview) - timing "retimed", cảnh đó "older",
   `fresh` False, `document_hash` là bản sync sẽ lưu - mà không ghi gì vào DB.
6. Reflow (updated_at, start/end của mọi hàng) không gây xung đột giả. Bản ghi
   áp cũ (trước F1, không có state_edit): đọc lại được từng cột thì gỡ kẹt,
   không đọc được thì so cả hàng như trước.

Mọi test chạy trên DB tạm của bộ test (tests/conftest.py); mô hình AI là giả
(tests/test_edit_planner.Director); không gọi AI thật, không tạo job thật.
"""

from __future__ import annotations

import json
import os
from unittest import mock

from tests.test_edit_planner import _PlannerCase
from youtube_monitor import edit_apply as ea, edit_document as ed, edit_planner as ep, edit_store as es, main

# Những cột lớp dựng mà kế hoạch AI ghi (và người dùng có thể sửa tay qua …/plan).
_LAYER_COLUMNS = ("edit_transition", "edit_effect", "edit_note", "overlays", "sound_cues", "edit_direction", "visual_kind")
MANUAL_PROMPT = "P24 tay: đồi phong lúc hoàng hôn"
MANUAL_OVERLAYS = [{"kind": "text", "text": "Chữ tay P24", "start_seconds": 0.0, "end_seconds": 1.0}]


class _ManualCase(_PlannerCase):
    def setUp(self) -> None:
        super().setUp()
        self._fresh()

    # --- đọc / ghi qua đúng các cửa của ứng dụng --------------------------------------

    def _segments(self) -> list[dict]:
        return self._timeline(self.project_id, self.script_id)

    def _seg(self, segment_id: int) -> dict:
        return self.database.get_project_timeline_segment(segment_id)

    def _beats(self, segment_id: int) -> list[dict]:
        return self.database.list_timeline_edit_beats(segment_id)

    def _patch(self, segment_id: int, **body) -> dict:
        """Ô "Sửa cảnh" của Bước 5: PATCH /api/timeline/{id}."""
        response = self.client.patch(f"/api/timeline/{segment_id}", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["segment"]

    def _patch_plan(self, segment_id: int, **body) -> dict:
        """Sửa tay lớp dựng của một cảnh: PATCH /api/timeline/{id}/plan."""
        response = self.client.patch(f"/api/timeline/{segment_id}/plan", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["segment"]

    def _step(self, **options) -> dict:
        """Nút "Lập kế hoạch dựng" (không options) và "Áp dụng vào timeline…" (confirmed_apply)."""
        response = self.client.post(f"/api/projects/{self.project_id}/steps/edit_plan", json={"options": options})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["result"]

    def _edit_document(self) -> dict:
        response = self.client.get(f"/api/projects/{self.project_id}/edit-document")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _scene_of(self, segment_id: int, answer: dict | None = None) -> dict:
        answer = answer or self._edit_document()
        return next(item for item in answer["scenes"] if item["segment_id"] == segment_id)

    def _layers(self, row: dict) -> dict:
        found = {column: row.get(column) for column in _LAYER_COLUMNS}
        for column in ("overlays", "sound_cues", "edit_direction"):
            try:
                found[column] = json.loads(found[column] or "null")
            except ValueError:
                pass
        return found

    def _conflicts(self, applied: dict) -> list[tuple]:
        return [(item["segment_id"], item["reason"], item["expected_from"]) for item in applied["conflicts"]]

    def _db_state(self) -> dict:
        """Mọi thứ một lần GET có thể đã ghi: các hàng timeline, nhịp dựng, shots và artifact của dự án."""
        with self.database._connect() as connection:
            tables = {
                "timeline": [dict(row) for row in connection.execute(
                    "SELECT * FROM project_timeline_segments WHERE project_id = ? ORDER BY id", (self.project_id,))],
                "shots": [dict(row) for row in connection.execute(
                    "SELECT * FROM project_shots WHERE project_id = ? ORDER BY id", (self.project_id,))],
                "beats": [dict(row) for row in connection.execute(
                    "SELECT b.* FROM project_timeline_edit_beats b JOIN project_timeline_segments s "
                    "ON s.id = b.timeline_segment_id WHERE s.project_id = ? ORDER BY b.id", (self.project_id,))],
                "artifacts": [dict(row) for row in connection.execute(
                    "SELECT id, kind, payload_json FROM project_director_artifacts WHERE project_id = ? ORDER BY id",
                    (self.project_id,))],
            }
        return tables

    def _note(self, name: str, **data) -> None:
        """Ghi giá trị trước/sau ra file khi đặt P24_EVIDENCE (chỉ để báo cáo); không đổi kết quả test."""
        target = os.environ.get("P24_EVIDENCE")
        if target:
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"test": name, **data}, ensure_ascii=False, default=str) + "\n")

    # --- kịch bản thay đổi (như tests/test_edit_integration._FlowCase) ------------------

    def _revise(self, line_of_section: int = 2) -> None:
        """Kịch bản mới (script id mới): một dòng của một mục được đổi lời, phần còn lại giữ nguyên."""
        old = self._script(self.project_id)
        lines = old["main_content"].split("\n")
        at = self._first_of_section(self.project_id, line_of_section)
        lines[at] = lines[at].replace(" ", " mỗi ", 1).rsplit(" ", 1)[0] + "."
        main.run_project_step(self.project_id, "script", {"revision": {"base_script_id": old["id"],
                                                                       "fields": {"main_content": "\n".join(lines)}, "source": "t"}})

    def _first_scene_of_section(self, section: int) -> int:
        """The row of the first scene of a section (0-based) - the scene _reword_in_place(section) changes."""
        return int(list(self._by_section(self.project_id).values())[section][0][0])

    def _reword_in_place(self, section: int = 1) -> None:
        at = self._first_of_section(self.project_id, section)
        self._patch_lines(self.project_id, lambda lines: lines.__setitem__(at, lines[at].replace(" ", " mỗi ", 1).rsplit(" ", 1)[0] + "."))


# ===========================================================================
# 1-2. visual_prompt sửa tay: giữ nguyên, và không làm cảnh kẹt xung đột (F1)
# ===========================================================================

class VisualPromptTests(_ManualCase):
    def test_1_visual_prompt_edited_after_plan_before_apply_is_kept_and_the_scene_is_applied(self) -> None:
        planned = self._step()
        self.assertEqual(planned["status"], ep.PLANNED)
        rows = self._segments()
        target = int(rows[0]["id"])
        before = self._seg(target)
        self.assertTrue(before["visual_path"], "the row was illustrated before any EditDocument (a legacy picture)")

        self._patch(target, visual_prompt=MANUAL_PROMPT)
        first = self._step(confirmed_apply=True)["applied"]
        after_first = self._seg(target)
        self._note("1", target=target, prompt_before=before["visual_prompt"], prompt_after=after_first["visual_prompt"],
                   layers_before=self._layers(before), layers_after=self._layers(after_first),
                   apply_status=first["status"], counts=first["counts"], conflicts=first["conflicts"],
                   scene=self._scene_of(target))

        self.assertEqual((first["status"], self._conflicts(first)), ("applied", []))
        self.assertEqual(sorted(item["segment_id"] for item in first["applied"]), sorted(int(row["id"]) for row in rows))
        self.assertEqual(after_first["visual_prompt"], MANUAL_PROMPT, "the manual description is kept")
        self.assertEqual((after_first["visual_path"], after_first["edit_transition"]), (before["visual_path"], "cut"),
                         "the legacy picture stays, the plan's layers are written")
        self.assertEqual(self._scene_of(target)["applied"], "applied")

        second = self._step(confirmed_apply=True)["applied"]
        self.assertEqual((second["status"], self._conflicts(second), second["counts"]["unchanged"]), ("unchanged", [], len(rows)))
        self.assertEqual(self._seg(target)["visual_prompt"], MANUAL_PROMPT)

    def test_2_visual_prompt_edited_after_apply_is_kept_and_the_scene_can_be_planned_and_applied_again(self) -> None:
        done = self._step(confirmed_apply=True)
        self.assertEqual(done["applied"]["status"], "applied")
        rows = self._segments()
        target = int(rows[0]["id"])
        before = self._seg(target)

        self._patch(target, visual_prompt=MANUAL_PROMPT)
        again = self._step(confirmed_apply=True)
        self.assertEqual(again["status"], ep.UNCHANGED, "nothing to plan")
        self.assertEqual((again["applied"]["status"], self._conflicts(again["applied"])), ("unchanged", []))
        self.assertEqual(again["applied"]["counts"]["unchanged"], len(rows))

        key = self._scene_of(target)["scene_key"]
        self.director.overlay_text = "Ý mới sau khi lập lại"
        replanned = self._step(confirmed_apply=True, scene_keys=[key], replan=True)
        after_replan = self._seg(target)
        self.assertEqual(replanned["planned"], [key])
        self.assertEqual((replanned["applied"]["status"], self._conflicts(replanned["applied"])), ("applied", []))
        self.assertEqual([item["segment_id"] for item in replanned["applied"]["applied"]], [target], "only the replanned scene")
        self.assertEqual(after_replan["visual_prompt"], MANUAL_PROMPT, "the manual description is kept")
        self.assertEqual(self._layers(after_replan)["overlays"][0]["text"], "Ý mới sau khi lập lại", "the new plan landed")
        self.assertEqual(self._scene_of(target)["applied"], "applied")

        third = self._step(confirmed_apply=True)["applied"]
        self.assertEqual((third["status"], self._conflicts(third)), ("unchanged", []))
        self._note("2", target=target, prompt_before=before["visual_prompt"], prompt_after=after_replan["visual_prompt"],
                   overlays_before=self._layers(before)["overlays"], overlays_after=self._layers(after_replan)["overlays"],
                   again=again["applied"]["counts"], after_replan=replanned["applied"]["counts"], third=third["counts"])

    def test_2b_the_record_keeps_what_the_plan_last_knew_not_the_hand_edit(self) -> None:
        """The hand's description is accepted because no plan writes it - not taken as known: the next apply's record
        still expects the description the row had before, so an edit that would write it still sees the hand edit."""
        self._step(confirmed_apply=True)
        target = int(self._segments()[0]["id"])
        original = self._seg(target)["visual_prompt"]
        self._patch(target, visual_prompt=MANUAL_PROMPT)
        self.director.overlay_text = "Ý khác"
        self._step(confirmed_apply=True, scene_keys=[self._scene_of(target)["scene_key"]], replan=True)
        record = next(item for item in self.database.list_edit_applies(self.project_id, self.script_id)[0]["payload"]["rows"]
                      if item["segment_id"] == target)
        self.assertEqual(record["state_edit"]["visual"].get("visual_prompt") or "", original)
        self.assertNotEqual(record["state_hash"], ea.edit_document.edit_hash(record["state_edit"]),
                            "the row (state_hash) holds the hand edit; what the plan knows (state_edit) does not")


# ===========================================================================
# 3b. Lớp dựng sửa tay sau khi áp: trường kế hoạch sẽ ghi thì xung đột, trường kế hoạch không ghi thì không
# ===========================================================================

class LayerScopeTests(_ManualCase):
    def test_3b_a_layer_the_plan_writes_edited_by_hand_after_apply_is_a_conflict_and_kept(self) -> None:
        self._step(confirmed_apply=True)
        rows = self._segments()
        target = int(rows[0]["id"])
        self._patch_plan(target, transition="fade", overlays=MANUAL_OVERLAYS)
        hand = self._layers(self._seg(target))
        self.director.overlay_text = "Ý khác"
        result = self._step(confirmed_apply=True, replan=True)
        applied = result["applied"]
        self._note("3b", target=target, hand=hand, after=self._layers(self._seg(target)), conflicts=applied["conflicts"],
                   counts=applied["counts"])
        self.assertEqual(self._conflicts(applied), [(target, "timeline_changed", "applied")])
        self.assertEqual(sorted(applied["conflicts"][0]["columns"]), ["edit_transition", "overlays"])
        self.assertEqual(self._layers(self._seg(target)), hand, "the hand's layers are not written over")
        self.assertEqual((applied["status"], applied["counts"]["applied"]), ("partial", len(rows) - 1),
                         "every other scene took the new plan")

    def test_3c_hand_beats_the_plan_never_writes_are_no_conflict_and_are_kept(self) -> None:
        self._step()
        target = int(self._segments()[0]["id"])
        seconds = float(self._seg(target)["duration_seconds"])
        response = self.client.put(f"/api/timeline/{target}/edit-beats", json={"beats": [
            {"visual_path": "tay-a.png", "duration_seconds": round(seconds / 2, 3), "prompt": "nhịp tay A"},
            {"visual_path": "tay-b.png", "duration_seconds": round(seconds / 2, 3), "prompt": "nhịp tay B"}]})
        self.assertEqual(response.status_code, 200, response.text)
        hand_beats = [(beat["visual_path"], beat["prompt"]) for beat in self._beats(target)]
        self.assertIsNone(next(row for row in ea.plan(self._doc())[0] if row["segment_id"] == target)["beats"],
                          "the plan names no beats for this scene")
        applied = self._step(confirmed_apply=True)["applied"]
        self.assertEqual((applied["status"], self._conflicts(applied)), ("applied", []))
        self.assertEqual([(beat["visual_path"], beat["prompt"]) for beat in self._beats(target)], hand_beats)
        self.assertEqual(self._seg(target)["edit_transition"], "cut", "and the plan's layers are written")

        # Đối chứng: một trường kế hoạch có ghi (chuyển cảnh) bị sửa tay thì vẫn xung đột.
        self._patch_plan(target, transition="fade")
        self.director.overlay_text = "Ý khác"
        again = self._step(confirmed_apply=True, replan=True)["applied"]
        self.assertEqual(self._conflicts(again), [(target, "timeline_changed", "applied")])
        self.assertEqual(again["conflicts"][0]["columns"], ["edit_transition"])
        self.assertEqual(self._seg(target)["edit_transition"], "fade")


# ===========================================================================
# 6. Bản ghi áp cũ (trước F1, không có state_edit)
# ===========================================================================

class OldRecordTests(_ManualCase):
    def _as_old_records(self, **change) -> None:
        """Every apply record of the project as an apply before F1 wrote it: no state_edit (and `change` on its rows)."""
        with self.database._connect() as connection:
            for row in connection.execute("SELECT id, payload_json FROM project_director_artifacts WHERE project_id = ? "
                                          "AND kind = 'edit_apply'", (self.project_id,)).fetchall():
                payload = json.loads(row["payload_json"])
                for item in payload["rows"]:
                    item.pop("state_edit", None)
                    item.update(change)
                connection.execute("UPDATE project_director_artifacts SET payload_json = ? WHERE id = ?",
                                   (json.dumps(payload, ensure_ascii=False), row["id"]))

    def test_6a_a_scene_stuck_by_a_hand_description_before_f1_is_freed_and_keeps_it(self) -> None:
        self._step(confirmed_apply=True)
        rows = self._segments()
        target = int(rows[0]["id"])
        self._as_old_records()
        self._patch(target, visual_prompt=MANUAL_PROMPT)
        self.director.overlay_text = "Ý mới"
        applied = self._step(confirmed_apply=True, replan=True)["applied"]
        self._note("6a", target=target, status=applied["status"], conflicts=applied["conflicts"], counts=applied["counts"])
        self.assertEqual((applied["status"], self._conflicts(applied)), ("applied", []))
        self.assertEqual(applied["counts"]["applied"], len(rows))
        self.assertEqual(self._seg(target)["visual_prompt"], MANUAL_PROMPT)
        self.assertEqual(self._layers(self._seg(target))["overlays"][0]["text"], "Ý mới")
        record = self.database.list_edit_applies(self.project_id, self.script_id)[0]["payload"]["rows"]
        self.assertTrue(all("state_edit" in item for item in record), "the new record is in the new form")

    def test_6b_an_old_record_still_protects_a_hand_edited_layer(self) -> None:
        self._step(confirmed_apply=True)
        target = int(self._segments()[0]["id"])
        self._as_old_records()
        self._patch_plan(target, transition="fade")
        self.director.overlay_text = "Ý mới"
        applied = self._step(confirmed_apply=True, replan=True)["applied"]
        self.assertEqual(self._conflicts(applied), [(target, "timeline_changed", "applied")])
        self.assertEqual(self._seg(target)["edit_transition"], "fade")

    def test_6c_an_old_record_that_cannot_be_read_column_by_column_falls_back_to_the_whole_row(self) -> None:
        self._step(confirmed_apply=True)
        target = int(self._segments()[0]["id"])
        before = self._layers(self._seg(target))
        self._as_old_records(layer_hash="not-a-known-edit")
        self._patch(target, visual_prompt=MANUAL_PROMPT)
        self.director.overlay_text = "Ý mới"
        applied = self._step(confirmed_apply=True, replan=True)["applied"]
        self.assertEqual(self._conflicts(applied), [(target, "timeline_changed", "applied")], "conservative, as before F1")
        self.assertEqual(applied["conflicts"][0]["columns"], ["*"])
        self.assertEqual((self._seg(target)["visual_prompt"], self._layers(self._seg(target))), (MANUAL_PROMPT, before))


# ===========================================================================
# 3. Lệnh áp kế hoạch AI không ghi visual_prompt
# ===========================================================================

class PlannerNeverWritesThePromptTests(_ManualCase):
    def test_3_a_planner_edit_names_no_prompt_nor_picture_and_the_apply_writes_neither(self) -> None:
        prompts = {int(row["id"]): (row["visual_prompt"], row["visual_path"]) for row in self._segments()}
        shots = {int(shot["id"]): shot["visual_prompt"] for shot in self.database.list_project_shots(self.project_id,
                                                                                                      script_id=self.script_id)}
        done = self._step(confirmed_apply=True)
        self.assertEqual(done["applied"]["status"], "applied")
        document = self._doc()
        for scene in document["scenes"]:
            self.assertFalse({"visual_prompt", "visual_path"} & set(scene["edit"]["visual"]), scene["scene_key"])
        record = self.database.list_edit_applies(self.project_id, self.script_id)[0]["payload"]
        written = {column for item in record["rows"] for column in item["columns_written"]}
        self.assertFalse({"visual_prompt", "visual_path", "asset_type"} & written, sorted(written))
        self.assertEqual({int(row["id"]): (row["visual_prompt"], row["visual_path"]) for row in self._segments()}, prompts)
        self.assertEqual({int(shot["id"]): shot["visual_prompt"]
                          for shot in self.database.list_project_shots(self.project_id, script_id=self.script_id)}, shots)
        # The same from the planner's own function: what it builds names no prompt, so row_writes() writes none.
        planned = ep.scene_edit(kind="image", fps=0, reason="r", transform={}, transition="cut", effect="zoom_in", note="n",
                                trim_head=0, trim_tail=0, cleanups=[], sound_cues=[], beats=[])
        updates, beats, owned = ea.row_writes(planned)
        self.assertFalse({"visual_prompt", "visual_path"} & set(updates))
        self.assertFalse(owned)
        self._note("3", columns_written=sorted(written), edit_visual_keys=sorted(document["scenes"][0]["edit"]["visual"]),
                   row_writes_columns=sorted(updates))


# ===========================================================================
# 4. Lớp dựng sửa tay trên hàng chưa áp, rồi reconcile
# ===========================================================================

class ManualLayersThenReconcileTests(_ManualCase):
    """F2: lớp dựng sửa tay trên hàng chưa áp không bao giờ thành mốc legacy mới, kể cả qua reconcile."""

    def _manual_layers(self, segment_id: int) -> dict:
        seconds = float(self._seg(segment_id)["duration_seconds"])
        self._patch_plan(segment_id, transition="fade", effect="static", note="P24 tay", overlays=MANUAL_OVERLAYS,
                         sound_cues=[{"cue": "whoosh", "start_seconds": 0.0, "end_seconds": 0.5}],
                         direction={"camera": "slow_push"})
        response = self.client.put(f"/api/timeline/{segment_id}/edit-beats", json={"beats": [
            {"visual_path": "tay-a.png", "duration_seconds": round(seconds / 2, 3), "prompt": "nhịp tay A"},
            {"visual_path": "tay-b.png", "duration_seconds": round(seconds / 2, 3), "prompt": "nhịp tay B"}]})
        self.assertEqual(response.status_code, 200, response.text)
        return self._hand(segment_id)

    def _hand(self, segment_id: int) -> dict:
        """Mọi thứ người dùng sửa tay ở lớp dựng: các cột lớp dựng và nhịp dựng (không kể id, thời điểm ghi)."""
        beats = [{key: beat[key] for key in ("beat_index", "visual_path", "source_kind", "start_seconds", "duration_seconds",
                                              "effect", "transition", "prompt", "status")}
                 for beat in self._beats(segment_id)]
        return {**self._layers(self._seg(segment_id)), "beats": beats}

    @staticmethod
    def _scaled(hand: dict, ratio: float) -> dict:
        """Lớp dựng tay sau khi reconcile căn lại theo độ dài mới - chữ, kiểu, thứ tự giữ nguyên, chỉ thời điểm co giãn."""
        scale = lambda items, keys: [{**item, **{key: round(float(item[key]) * ratio, 3) for key in keys}}  # noqa: E731
                                     for item in items]
        return {**hand, "overlays": scale(hand["overlays"], ("start_seconds", "end_seconds")),
                "sound_cues": scale(hand["sound_cues"], ("start_seconds", "end_seconds")),
                "beats": [{**beat, "start_seconds": round(float(beat["start_seconds"]) * ratio, 3),
                           "duration_seconds": round(float(beat["duration_seconds"]) * ratio, 3)} for beat in hand["beats"]]}

    def test_4a_without_a_reconcile_manual_layers_are_a_conflict_and_kept(self) -> None:
        self._step()
        target = int(self._segments()[0]["id"])
        manual = self._manual_layers(target)
        applied = self._step(confirmed_apply=True)["applied"]
        self.assertEqual(self._conflicts(applied), [(target, "timeline_changed", "legacy")])
        self.assertEqual(self._hand(target), manual)
        self._note("4a", target=target, manual=manual, conflicts=applied["conflicts"], status=applied["status"])

    def test_4b_a_new_script_carries_the_manual_layers_and_neither_the_rebuild_nor_an_apply_overwrites_them(self) -> None:
        self._step()
        old_script = self.script_id
        old_rows = self._segments()
        target = int(old_rows[0]["id"])
        manual = self._manual_layers(target)

        # Tạo lại storyboard cho kịch bản mới: reconcile chép hàng sang, rồi TỰ ÁP kế hoạch (người dùng chưa bấm "Áp dụng").
        self._revise(line_of_section=2)
        answer = self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={}).json()
        self.script_id = int(self.database.get_latest_project_script(self.project_id)["id"])
        self.assertNotEqual(self.script_id, old_script)
        new_rows = self._segments()
        new_target = int(new_rows[0]["id"])
        self.assertEqual(new_rows[0]["voice_text"], old_rows[0]["voice_text"], "the scene's words did not change")
        after_rebuild = self._hand(new_target)
        rebuilt = answer["edit_document"]

        applied = self._step(confirmed_apply=True)["applied"]   # rồi "Áp dụng vào timeline…"
        after_apply = self._hand(new_target)
        self._note("4b", old_row=target, new_row=new_target, manual=manual, after_rebuild=after_rebuild,
                   after_apply=after_apply, old_row_now=self._hand(target), reconcile_mode=answer["reconcile"]["mode"],
                   edit_refresh=answer["edit_refresh"], rebuild_status=rebuilt["status"], rebuild_counts=rebuilt["counts"],
                   rebuild_conflicts=rebuilt["conflicts"], apply_status=applied["status"], apply_conflicts=applied["conflicts"])

        self.assertEqual(answer["reconcile"]["mode"], "carried_over")
        self.assertNotIn(new_target, answer["edit_refresh"], "a row holding hand edits is never taken as legacy")
        # The new row is known part by part (its carried picture), its hand-edited layers as the document knew them.
        self.assertEqual(self._conflicts(rebuilt), [(new_target, "timeline_changed", "legacy")])
        self.assertEqual(rebuilt["status"], "partial", "the other scenes were still applied")
        self.assertEqual(after_rebuild, manual, "the rebuild kept every hand edit")
        self.assertEqual(self._conflicts(applied), [(new_target, "timeline_changed", "legacy")])
        self.assertEqual(after_apply, manual, "and so did the apply")
        self.assertEqual(self._hand(target), manual, "the old script's row still holds them")

    def test_4c_a_reworded_scene_keeps_the_manual_layers_through_the_reconcile_and_the_apply(self) -> None:
        self._step()
        target = self._first_scene_of_section(1)
        manual = self._manual_layers(target)
        doubled = int(self._seg(target)["duration_seconds"]) * 2
        self._patch(target, duration_seconds=doubled)   # also by hand: the scene's length, so the reconcile retimes it

        self._reword_in_place(1)
        answer = self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={"force": True}).json()
        after_reconcile = self._hand(target)
        ratio = float(self._seg(target)["duration_seconds"]) / doubled
        self.assertEqual(answer["reconcile"]["mode"], "in_place")
        self.assertNotIn(target, answer["edit_refresh"], "a row holding hand edits is never taken as legacy")
        self.assertEqual(answer["edit_document"]["counts"]["skipped"].get(ea.STALE), 1, "its words changed: stale, skipped")
        self.assertEqual(after_reconcile, self._scaled(manual, ratio),
                         "the reconcile only retimed the hand's layers to the new length, as it does any legacy layer")

        applied = self._step(confirmed_apply=True)   # "Áp dụng vào timeline…": the stale scene is planned again, then applied
        after = self._hand(target)
        self._note("4c", target=target, manual=manual, after_reconcile=after_reconcile, after_apply=after,
                   duration_set=doubled, ratio=ratio, edit_refresh=answer["edit_refresh"], planned=applied["planned"],
                   apply_status=applied["applied"]["status"], conflicts=applied["applied"]["conflicts"])
        self.assertEqual(applied["planned"], [self._scene_of(target)["scene_key"]], "the scene was planned again")
        self.assertEqual(self._conflicts(applied["applied"]), [(target, "timeline_changed", "legacy")])
        self.assertEqual(after, after_reconcile, "the new plan did not reach the row")

    def test_4d_an_agents_timeline_never_makes_hand_edits_the_new_legacy(self) -> None:
        self._step()
        rows = self._segments()
        target = int(rows[0]["id"])
        manual = self._manual_layers(target)
        segments = [{"voice_text": row["voice_text"], "subtitle_text": row["voice_text"], "visual_prompt": f"agent {n}"}
                    for n, row in enumerate(rows)]
        result = main.run_project_step(self.project_id, "timeline", {"segments": segments})["result"]
        applied = result["edit_document"]
        self._note("4d", target=target, manual=manual, after=self._hand(target), status=applied["status"],
                   conflicts=applied["conflicts"], applied=[item["segment_id"] for item in applied["applied"]])
        self.assertEqual(self._seg(target)["visual_prompt"], "agent 0", "the agent's own field is written, as before")
        self.assertEqual(self._conflicts(applied), [(target, "timeline_changed", "legacy")])
        self.assertEqual(self._hand(target), manual, "the hand's layers are kept")
        self.assertEqual(sorted(item["segment_id"] for item in applied["applied"]), sorted(int(row["id"]) for row in rows[1:]))


class HandPromptThenReconcileTests(_ManualCase):
    """F1 × F2: chỉ sửa tay mô tả hình (cột kế hoạch không ghi) không được làm kẹt các lớp dựng đã biết.

    Reconcile ghi nhận theo từng phần (edit_apply.held_edits): lớp dựng legacy nó chép/căn lại được nhận là đã
    biết; riêng mô tả tay giữ mốc cũ. Kế hoạch được áp, mô tả tay giữ nguyên và vẫn chưa được nhận là đã biết.
    """

    def _legacy_overlays(self, segment_id: int) -> None:
        """Lớp dựng có trên hàng trước mọi EditDocument: lần lập kế hoạch đầu giữ nó làm orphan legacy (đã biết)."""
        self.database.save_segment_edit_layers(segment_id, overlays=[
            {"kind": "text", "text": "Chữ cũ", "start_seconds": 0.0, "end_seconds": 1.0}])

    def test_7a_a_new_script_makes_the_carried_legacy_layers_known_but_never_the_hand_description(self) -> None:
        target = int(self._segments()[0]["id"])
        self._legacy_overlays(target)
        self._step()
        self._patch(target, visual_prompt=MANUAL_PROMPT)

        self._revise(line_of_section=2)
        answer = self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={}).json()
        self.script_id = int(self.database.get_latest_project_script(self.project_id)["id"])
        rows = self._segments()
        new_target = int(rows[0]["id"])
        rebuilt = answer["edit_document"]
        self._note("7a", target=target, new_target=new_target, edit_refresh=answer["edit_refresh"],
                   rebuild_status=rebuilt["status"], rebuild_conflicts=rebuilt["conflicts"], row=self._seg(new_target))

        self.assertEqual(answer["reconcile"]["mode"], "carried_over")
        self.assertNotIn(new_target, answer["edit_refresh"], "the row holds a hand edit: never taken as it is")
        self.assertEqual(self._conflicts(rebuilt), [], "the carried legacy layers are known: no conflict")
        self.assertIn(new_target, [item["segment_id"] for item in rebuilt["applied"]], "the plan reached the row")
        row = self._seg(new_target)
        self.assertEqual(row["visual_prompt"], MANUAL_PROMPT, "the hand description is kept")
        self.assertEqual(row["edit_transition"], "cut", "the plan's layers are written")
        self.assertIn(new_target, ea.unknown_rows(self.database, self.project_id, self.script_id, rows),
                      "the hand description is still not known to the document")

    def test_7b_a_reworded_scene_takes_its_new_plan_over_retimed_legacy_layers_and_keeps_the_hand_description(self) -> None:
        target = self._first_scene_of_section(1)
        self._legacy_overlays(target)
        self._step()
        self._patch(target, visual_prompt=MANUAL_PROMPT)
        self._patch(target, duration_seconds=int(self._seg(target)["duration_seconds"]) * 2)   # so the reconcile retimes

        self._reword_in_place(1)
        answer = self.client.post(f"/api/projects/{self.project_id}/shots/generate", json={"force": True}).json()
        self.assertEqual(answer["reconcile"]["mode"], "in_place")
        self.assertNotIn(target, answer["edit_refresh"], "the row holds a hand edit: never taken as it is")
        self.assertNotEqual(json.loads(self._seg(target)["overlays"])[0]["end_seconds"], 1.0,
                            "the reconcile retimed the legacy layers")

        applied = self._step(confirmed_apply=True)   # the reworded (stale) scene is planned again, then applied
        self._note("7b", target=target, edit_refresh=answer["edit_refresh"], planned=applied["planned"],
                   apply_status=applied["applied"]["status"], conflicts=applied["applied"]["conflicts"], row=self._seg(target))
        self.assertEqual(self._conflicts(applied["applied"]), [], "the retimed legacy layers are known: no conflict")
        self.assertIn(target, [item["segment_id"] for item in applied["applied"]["applied"]], "the new plan reached the row")
        self.assertEqual(self._seg(target)["visual_prompt"], MANUAL_PROMPT, "the hand description is kept")


# ===========================================================================
# 5. GET …/edit-document sau khi đổi thời lượng
# ===========================================================================

class ReadAfterLengthChangeTests(_ManualCase):
    def test_5_after_a_length_change_the_read_says_what_the_next_sync_will_and_writes_nothing(self) -> None:
        """F3: the read follows the timeline as it is now (edit_store.preview), never the stored timing of before."""
        self._step(confirmed_apply=True)
        target = int(self._segments()[0]["id"])
        before = self._edit_document()
        self.assertEqual((before["fresh"], before["stored_document_hash"]), (True, before["document_hash"]))
        old = int(self._seg(target)["duration_seconds"])
        self._patch(target, duration_seconds=old * 2)

        state = self._db_state()
        read = self._edit_document()
        self.assertEqual(self._db_state(), state, "the read wrote nothing")
        self.assertEqual(self._edit_document(), read, "reading twice answers the same")
        scene = self._scene_of(target, read)
        self.assertEqual((read["state"], read["fresh"], read["stored_document_hash"]),
                         ("current", False, before["document_hash"]))
        self.assertNotEqual(read["document_hash"], before["document_hash"])
        self.assertEqual((scene["timing"], scene["applied"], scene["status"]), (ed.TIMING_RETIMED, "older", ed.READY))
        self.assertEqual(read["counts"], {**before["counts"], "applied": before["counts"]["applied"] - 1})
        others = [item for item in read["scenes"] if item["segment_id"] != target]
        self.assertTrue(all((item["timing"], item["applied"]) == (ed.TIMING_KEPT, "applied") for item in others),
                        "only the scene whose length changed moves")

        # The next sync (a plan or an apply runs one first) keeps exactly what the read said.
        synced = es.sync(self.database, self.project_id, self.script_id,
                         self.database.get_latest_project_storyboard(self.project_id, script_id=self.script_id))
        item = next(s for s in synced["document"]["scenes"] if s["segment_id"] == target)
        reread = self._edit_document()
        self._note("5", target=target, duration=[old, old * 2], hash_before=before["document_hash"],
                   hash_read=read["document_hash"], scene_read=scene, sync_created=synced["created"],
                   hash_after_sync=synced["document_hash"], timing_after_sync=item["timing"],
                   scene_reread=self._scene_of(target, reread))
        self.assertTrue(synced["created"])
        self.assertEqual(synced["document_hash"], read["document_hash"], "the read named the version the sync keeps")
        self.assertEqual((item["timing"]["state"], item["timing"]["ratio"]), (ed.TIMING_RETIMED, 2.0))
        self.assertEqual((reread["fresh"], reread["document_hash"], reread["stored_document_hash"]),
                         (True, read["document_hash"], read["document_hash"]))
        self.assertEqual(reread["scenes"], read["scenes"])

        # Applied again, the row holds the retimed edit: read as applied, still fresh.
        self._step(confirmed_apply=True)
        final = self._edit_document()
        self.assertEqual((final["fresh"], self._scene_of(target, final)["applied"]), (True, "applied"))

    def test_5b_a_length_the_edit_cannot_follow_reads_stale_timing_with_nothing_to_apply(self) -> None:
        self._step(confirmed_apply=True)
        target = int(self._segments()[0]["id"])
        self._patch(target, duration_seconds=1)
        read = self._edit_document()
        scene = self._scene_of(target, read)
        self._note("5b", target=target, scene=scene, fresh=read["fresh"])
        self.assertFalse(read["fresh"])
        if scene["timing"] == ed.TIMING_STALE:
            self.assertEqual((scene["status"], scene["applied"]), (ed.STALE_TIMING, None))
            self.assertEqual(read["counts"]["stale"], 1)
        else:   # a short enough edit still follows one second: then it is retimed, as in test 5
            self.assertEqual((scene["timing"], scene["applied"]), (ed.TIMING_RETIMED, "older"))

    def test_5c_a_read_that_cannot_work_out_the_timeline_answers_the_stored_document_and_says_why(self) -> None:
        self._step(confirmed_apply=True)
        before = self._edit_document()
        with mock.patch.object(es, "snapshot", side_effect=es.EditStoreError("Timeline chưa khớp Storyboard hiện hành")):
            read = self._edit_document()
        self.assertEqual((read["state"], read["fresh"], read["document_hash"]), ("current", None, before["document_hash"]))
        self.assertIn("Timeline chưa khớp", read["fresh_detail"])
        self.assertEqual(read["scenes"], before["scenes"])


# ===========================================================================
# 6. Reflow không gây xung đột giả
# ===========================================================================

class ReflowTests(_ManualCase):
    def test_6_a_length_change_rewrites_every_row_yet_the_next_apply_has_no_conflict(self) -> None:
        self._step(confirmed_apply=True)
        rows = self._segments()
        target = int(rows[0]["id"])
        before = {int(row["id"]): (row["updated_at"], row["start_seconds"], row["end_seconds"]) for row in rows}
        overlays_before = self._layers(self._seg(target))["overlays"]
        old = int(rows[0]["duration_seconds"])
        self._patch(target, duration_seconds=old + 2)
        mid = {int(row["id"]): (row["updated_at"], row["start_seconds"], row["end_seconds"]) for row in self._segments()}
        self.assertTrue(all(mid[key][0] != before[key][0] for key in before), "the reflow rewrote updated_at of every row")
        self.assertTrue(all(mid[key][1] == before[key][1] + 2 for key in list(before)[1:]), "and moved the later rows")

        applied = self._step(confirmed_apply=True)["applied"]
        overlays_after = self._layers(self._seg(target))["overlays"]
        self._note("6", target=target, duration=[old, old + 2], status=applied["status"], counts=applied["counts"],
                   conflicts=applied["conflicts"], overlays_before=overlays_before, overlays_after=overlays_after)
        self.assertEqual(self._conflicts(applied), [])
        self.assertEqual(applied["status"], "applied")
        self.assertEqual([item["segment_id"] for item in applied["applied"]], [target], "only the retimed scene is written")
        self.assertEqual(applied["counts"]["unchanged"], len(rows) - 1)
        self.assertAlmostEqual(overlays_after[0]["end_seconds"], round(overlays_before[0]["end_seconds"] * (old + 2) / old, 3),
                               places=3)
