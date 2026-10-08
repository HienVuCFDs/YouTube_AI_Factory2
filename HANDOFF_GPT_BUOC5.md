# YOUTUBE AI FACTORY — BÀN GIAO SANG CHAT MỚI (Bước 5: T1 chờ duyệt, T2 hoàn thành, T3 hoàn thành)

Cập nhật: 2026-10-08 · Người lập: Claude (Claude Code, làm việc trực tiếp trong repo)

> **Đây là file vào đầu tiên** cho GPT và cho Claude ở chat mới. Nó mô tả trạng thái **hiện tại** của dự án.
> Thứ tự đọc khuyên dùng và bản đồ tài liệu nằm ở mục 14.
> Bản 07/10 dừng ở T1. Bản 08/10 bổ sung: trạng thái git mới (mục 1–2), **T2 hoàn thành** (mục 9b), **T3 hoàn thành, đã review và commit** (mục 9c), việc tiếp theo (mục 11).

---

## 0. Cách dùng file này

File này dành cho **hai người đọc**:

- **GPT** — reviewer và người soạn prompt.
- **Claude ở chat mới** — AI code trực tiếp trong repo.

Quy trình từ trước tới nay:

1. Người dùng gửi prompt (thường do GPT soạn) cho **Claude**.
2. Claude làm đúng phạm vi prompt, rồi gửi báo cáo.
3. Người dùng dán báo cáo cho GPT; GPT review, chỉ ra rủi ro, soạn prompt tiếp theo.

**Việc ngay bây giờ:**
- **T1 (EditDocument Engine thuần) đã xong, đang chờ duyệt** (mục 9).
- **T2 (lưu trữ EditDocument) đã hoàn thành** (mục 9b). Người dùng đã chốt:
  - storage là `project_director_artifacts`, `kind="edit_document"`;
  - bootstrap theo cách (b): lớp dựng cũ thành orphan `legacy`.
- **T3 (Apply EditDocument → timeline) hoàn thành**: đã qua final review, đã commit và push lên `claude/dreamy-gates-4qehd3` (mục 9c). Người dùng đã chốt H1–H6, B1–B4. **Chưa có caller** (H4): T3 chưa được nối vào luồng sản xuất.
- Việc kế tiếp: T4 (mục 11).

**Quy tắc bất biến (người dùng đã chốt):**
- Làm theo từng phase/task nhỏ. Hết mỗi task thì **dừng, báo cáo**, chờ duyệt. Không tự mở rộng phạm vi; gặp vấn đề kiến trúc ngoài phạm vi thì báo **BLOCKED**.
- **Không commit, không push** nếu chưa có lệnh riêng.
- **Không migrate / không ghi DB thật** nếu chưa được duyệt. Kiểm thử dùng DB tạm (`conftest.py` tự trỏ) hoặc **bản sao** DB.
- **Không chạy app** nếu prompt không yêu cầu rõ ràng. DB thật có **5 `agent_tasks` đang `queued`** và **2 `analysis_jobs` kẹt ở `running`**: chạy app trên DB thật thì worker sẽ tự nhận các việc này.
- Nếu buộc phải chạy app: START → TEST → KILL toàn bộ app/uvicorn → kiểm tra **cổng 8787 trống**. Không để app chạy nền.
- Hai test đỏ có từ trước, không sửa trừ khi chứng minh do phase mới gây ra: `test_burned_in_marks`, `test_shorts`.
- Quét secret; không in API key, token, cookie, mật khẩu.
- UI phải gọn kiểu công cụ sản xuất, ít chữ; chi tiết kỹ thuật để trong tooltip hoặc mục "Chi tiết".
- Không sửa Bước 1/2, không xoá `writer.py`. Short, UI Bước 5, Reup redesign nằm ngoài phạm vi.

**Mỗi báo cáo của Claude luôn kết thúc bằng:**
- file đã đổi;
- kết quả test (test mới + full suite);
- hash DB thật trước/sau;
- tiến trình và cổng 8787;
- xác nhận chưa commit / chưa push / chưa chạy app / chưa đụng DB thật (trừ khi được phép).

---

## 1. Dự án

- App local: FastAPI + SQLite + HTML/JS thuần, cổng 8787.
- Code ở `_HE_THONG/app/youtube_monitor/`, test ở `_HE_THONG/app/tests/`.
- DB thật: `_HE_THONG/data/youtube_monitor.db` (gitignore, chỉ có trên máy người dùng). Hash ghi nhận gần nhất **`6ece65e24917facb3b46b3ab320796c4`** (07/10), không đổi từ 06/10. Ngày 08/10 chưa đo lại: phiên Claude trên cloud không có DB.
- Git (08/10):
  - Repo **đã có remote** GitHub `HienVuCFDs/YouTube_AI_Factory2`, nhánh chính `main`.
  - Lịch sử: `08c5ed0` (Bước 2) → `98c51d2 feat: complete script engine and Gemini TTS` (Bước 3 + 4) → **`30ca9e1 Initial commit`** (08/10 01:19).
  - `30ca9e1` gom **toàn bộ** thay đổi trước đó còn nằm ngoài git: Bước 5.1, 5.2, T0, T0.5, T1, code T2, file này. Nó gom luôn các file `_tmp_*` ở thư mục gốc, kể cả `_tmp_work_brief_review/pymupdf_deps/` (thư viện pymupdf vendored).
  - Nhánh làm việc của Claude trên cloud: `claude/dreamy-gates-4qehd3`.

Pipeline:

```text
1 Phân tích ✅ → 2 Kế hoạch ✅ → 3 Kịch bản ✅ → 4 Giọng đọc ✅ (đã kiểm với API thật)
→ 5 Storyboard & Edit 🔧 (5.1 ✅ · 5.2 ✅ · 5.3: T0 ✅ T0.5 ✅ T1 ✅ chờ duyệt · T2 ✅ · T3 ✅) → 6 Xưởng dựng → 7 Render & Xuất bản
```

Kiến trúc canonical (đích của Bước 5.3):

```text
ProjectPlan → ScriptDocument → StoryboardDocument ─(lineage)→ EditDocument ─(apply, T3)→ timeline (read model) → giọng / render
```

---

## 2. Bước 5 nằm ở đâu trong git

Mọi thay đổi của Bước 5 (5.1, 5.2, T0, T0.5, T1, code T2) nằm trong commit **`30ca9e1 Initial commit`**, ngay sau `98c51d2`. Danh sách file code/test của Bước 5:

```text
 sửa  _HE_THONG/app/tests/test_production_gate.py
 sửa  _HE_THONG/app/tests/test_script_paths.py
 sửa  _HE_THONG/app/youtube_monitor/database.py          (+ storyboard, reconcile, EditDocument T2)
 sửa  _HE_THONG/app/youtube_monitor/main.py
 sửa  _HE_THONG/app/youtube_monitor/production_worker.py
 sửa  _HE_THONG/app/youtube_monitor/shot_planner.py      (chỉ docstring)
 sửa  _HE_THONG/app/youtube_monitor/voice_library.py
 mới  _HE_THONG/app/youtube_monitor/storyboard_engine.py   (5.1, T0.5)
 mới  _HE_THONG/app/youtube_monitor/storyboard_reconcile.py (5.2, T0.5, T1)
 mới  _HE_THONG/app/youtube_monitor/edit_document.py      (T1)
 mới  _HE_THONG/app/youtube_monitor/edit_store.py         (T2; chưa có caller/route – đúng phạm vi)
 mới  _HE_THONG/app/tests/test_storyboard_engine.py       (34 test)
 mới  _HE_THONG/app/tests/test_storyboard_gate.py         (47 test)
 mới  _HE_THONG/app/tests/test_storyboard_lineage.py      (28 test)
 mới  _HE_THONG/app/tests/test_edit_document.py           (25 test)
 (T2, commit ec62257) _HE_THONG/app/tests/test_edit_store.py (20 test)
 (T3, commit T3)      _HE_THONG/app/youtube_monitor/edit_apply.py, _HE_THONG/app/tests/test_edit_apply.py (46 test), database.py (+232 dòng)
 mới  HANDOFF_GPT_BUOC5.md                                (file này)
```

- Các file `_tmp_*` ở thư mục gốc là của người dùng, nhưng **đã lọt vào `30ca9e1`**: `_tmp_inspect_project56.py`, `_tmp_schema.py`, `_tmp_project56_*.json`, `_tmp_review_project56/` (ảnh contact sheet), `_tmp_work_brief_review/` (PDF/PNG của WORK BRIEF + thư viện `pymupdf_deps/`). Có gỡ khỏi git hay không là quyết định của người dùng. Claude không tự xoá.
- **Kết quả test mới nhất (sau T1, 07/10, trên máy người dùng):** 2239 đạt · 2 đỏ cũ · 9 bỏ qua · 230 subtest đạt. Kết quả T2 (Linux, 08/10) ở mục 9b.
- Phiên Claude trên cloud (08/10) **không chạy được test**: môi trường chưa cài `fastapi` / `pytest`. Số liệu test ở đây vẫn là số đo trên máy người dùng.

---

## 3. Bước 5.1 — Storyboard Engine (xong)

- `storyboard_engine.py` cắt ScriptDocument thành **StoryboardDocument**, nguồn sự thật cho lời và cách chia cảnh. `project_shots` chỉ là bản sao.
- **Chia cảnh tất định, không gọi model:**
  - một cảnh = các dòng liền nhau thuộc một phần (hook / thân / CTA) của một section, do một người nói;
  - không cắt đôi dòng, không gộp hai section;
  - độ dài mục tiêu là `edit_direction.average_shot_length_seconds` (2–30 giây, mặc định 6), đổi ra số từ bằng tốc độ đọc.
- **`scene_key`** = `"sk-" + sha256(section, role, speaker, lời)[:16]`, cộng hậu tố `-2`, `-3` cho cảnh trùng. Đây là **khoá nội dung**, không phải định danh: phải nối cảnh qua `lineage()` (mục 8), không bao giờ dựa vào key bằng nhau.
- **Provenance:** `script_id/version/fingerprint`, `plan_id/version/plan_fingerprint` (độ dài cảnh + chiến lược hình), `document_hash`, `engine_version`. Engine version hiện là **`storyboard-phase4`** (chia cảnh neo, T0.5). Storyboard phase3 vẫn dùng làm neo được.
- **Chiến lược sản xuất/dựng** đi kèm storyboard: `visual_strategy` và `plan_fingerprint`.
- **Bảng `project_storyboards`:** chỉ thêm dòng; cùng hash thì dùng lại. Migration đã có trên DB thật từ 06/10 (xem mục 12).
- **Ranh giới:**
  - dự án luồng Kế hoạch có ScriptDocument đi qua engine;
  - dự án ngoài luồng (dán tay, writer cũ) và Short giữ `shot_planner` cũ;
  - Reup "cắt theo lời thoại" là chế độ riêng.

---

## 4. Bước 5.2 — Storyboard Gate + Reconcile (xong)

**Gate trung tâm** `storyboard_engine.gate()`. `main.py` gọi qua `_storyboard_gate` / `_storyboard_block` / `_require_storyboard`.
- Mode `plan` / `reup` / `legacy`.
- State `missing` / `stale` / `invalid` / `out_of_sync` / `current`. Mode `reup`/`legacy` → `not_applicable`, không chặn.
- Gate chặn các job đọc lời (`voiceover`, `render`, `premiere_draft`, `director_production`…) ở API **và** ở worker. Áp cả cho `timeline/generate`, `run_project_step`, `_steps_done`. `force` không lách được gate.
- Chặn sửa lời ngoài kịch bản: PATCH lời shot/timeline, thêm/xoá/đổi thứ tự shot, `/script/translate` (trừ Reup), gắn giọng nói lời khác.

**Reconcile** (`storyboard_reconcile.py`, thuần) khi kịch bản đổi:
- `plan()` chọn dòng DB mà mỗi cảnh mới tiếp quản, và quyết định giữ giọng (`keeps_voice()`).
- `apply_storyboard_reconcile` (database.py) áp toàn bộ trong **một transaction**: tại chỗ (giữ id dòng) hoặc mang sang kịch bản mới.
- Dòng bị xoá được lưu snapshot vào `project_director_artifacts` (kind `storyboard_reconcile`) trước khi xoá; không xoá file.
- Tại chỗ mà làm mất giọng hoặc dòng thì cần `force`.

**Giọng:**
- Mỗi file giọng có `<audio>.voice.json` ghi lời, người nói và `fingerprint` cấu hình giọng.
- Tên file `voice-s{id_dòng}-{hash}`.
- Giọng chỉ được giữ khi đúng lời, đúng người nói, đúng cấu hình giọng hiện tại.

---

## 5. Findings sau 5.2

| # | Vấn đề | Trạng thái |
|---|---|---|
| F1 | Cảnh modified giữ lớp dựng làm cho lời/thời lượng cũ | **Phần thời gian đã sửa ở T0.5** (retime). **Phần nội dung** (overlay cũ trên lời mới) chờ T4 + T7 |
| F2 | Ghép theo vị trí vượt section | Đã sửa ở T0 |
| F3 | Timeline agent gửi bỏ qua `stale` | Đã sửa ở T0 |
| F4 | Cách gom agent gửi mặc định `force=True` | Đã sửa ở T0 |
| F5 | PATCH `subtitle_text` có thể khác lời đọc | Chờ T8 |
| F6 | Render không chặn khi các cảnh lẫn cấu hình giọng; attach giọng không kiểm cấu hình | Chờ T7/T8 |
| F7 | Gate đọc file giọng của mọi segment mỗi lần gọi | Đã sửa ở T0 |
| F8 | `visual_prompt` có hai nơi chứa; Edit Plan chỉ ghi vào shots | Chờ T3/T8 |

**Edit Plan cũ (vẫn chạy cho dự án legacy):**
- Lưu ở `project_edit_plans` (`plan_json` khoá theo `segment_id`).
- Có 4 đường cùng ghi lớp dựng thẳng xuống timeline, không qua gate:
  1. áp Edit Plan;
  2. edit beats AI từng cảnh;
  3. PATCH `/timeline/{id}/plan`, PUT `/edit-beats`;
  4. `run_step("edit_plan")`.
- Render đọc các cột edit trên timeline.

---

## 6. Bước 5.3 — thiết kế EditDocument (đã duyệt) và thứ tự task

- **Lưu** trong `project_edit_plans.plan_json` với `"kind": "edit_document"`, `"engine_version": "edit-phase1"`. Không cần migration.
  - **Đã thay bằng quyết định của người dùng (08/10, T2):** lưu ở `project_director_artifacts`, `kind="edit_document"`, mỗi phiên bản một dòng. **Không dùng `project_edit_plans`**, không migration. Xem mục 9b.
- **Nối cảnh cũ–mới chỉ qua `lineage()`.**
- **Một đường ghi duy nhất:** `apply_scenes()` (T3). Sửa tay, AI từng cảnh, AI toàn bộ đều ghi vào EditDocument trước.
- **Gate (T7):**
  - lập kế hoạch dựng / Apply cần Storyboard Gate `current` và giọng đúng cấu hình;
  - render cần không còn lớp dựng stale, không lệch `layer_hash`, `voice_outdated == 0`. Cảnh trơn được phép.

**6 quyết định người dùng đã chốt:**
1. Lời đổi → giữ hình cũ, `visual_review`.
2. AI được viết overlay nhưng phải qua `text_errors`.
3. Sửa tay → ghi vào EditDocument → áp ngay cảnh đó.
4. `run_step("edit_plan")` chỉ áp khi `confirmed_apply=true`.
5. Giọng đổi mà lời không đổi → retime tất định; validation lỗi thì `stale_timing`.
6. Cho phép render cảnh không có lớp dựng.

**Thứ tự task:**

```text
T0 ✅ → T0.5 ✅ → T1 ✅ (chờ duyệt) → T2 Lưu trữ ✅ → T3 Apply ✅ → T4 Nối reconcile (F1)
→ T5 Planner theo storyboard → T6 Adapter sửa tay / AI từng cảnh → T7 Gate → T8 F5/F6/F8 → T9 Nghiệm thu
```

---

## 7. T0 — xong (đã duyệt)

- F2, F3, F4, F7 như bảng mục 5.
- **Ghi nhận về DB thật:** có migration 5.1 xảy ra ngoài lượt làm việc (xem mục 12). Người dùng đã chốt: không điều tra thêm, không rollback.

---

## 8. T0.5 — Identity Hardening (xong, đã duyệt; checkpoint READY_FOR_T1)

**Chia cảnh neo** (`storyboard_engine.anchors`, `build(..., previous=)`):
- Giữ các cảnh của lần chia trước còn nguyên vẹn (cùng dòng, cùng chữ, liền nhau, cùng section/role/người nói). Chỉ vùng thay đổi được chia lại.
- Mẩu vụn ngắn hơn **`MIN_FRAGMENT_FACTOR = 0.35`** × độ dài cảnh thì nhả một cảnh neo kề bên. Ngưỡng 0.35 người dùng đã chốt.
- Không neo khi:
  - không có storyboard trước;
  - engine khác;
  - `plan_fingerprint` đổi;
  - tốc độ đọc hoặc độ dài cảnh đổi;
  - cách gom do agent gửi.

**Benchmark 3.000 lần sửa một dòng (ngưỡng 0.35):**

| | Trước | Sau |
|---|---|---|
| Lần sửa làm chia lại cảnh không liên quan | 11,93% | **0,97%** |
| Cảnh không liên quan bị mất | 1,62% | **0,12%** |
| Số cảnh bị ảnh hưởng trung bình mỗi lần sửa | 0,131 | **0,010** |

Sửa 3 dòng cùng lúc: 30,8% → 4,5%. Xoá dòng / chèn dòng: → 0%. Mọi cảnh còn bị mất đều do quy tắc nhả mẩu vụn.

**Lineage** (`storyboard_reconcile.lineage(old_board, new_board)`) — hàm thuần, là cách **duy nhất** để tìm lại cảnh cũ:
- **Bộ khớp:**
  - căn **mọi dòng** của hai bản chia trước bằng LCS (lấy được nhiều cặp nhất); số thứ tự dòng chỉ dùng để phân xử khi hai cách ngang nhau;
  - sau đó các bậc khớp cảnh lần lượt là `lines` → `section` → `words` → `moved` → `position`;
  - `position` chỉ ghép trong cùng section/role: trước hết ưu tiên cảnh còn giữ dòng của cảnh cũ; sau đó chỉ ghép "viết lại tại chỗ" khi cảnh cũ thật sự mất dòng và cảnh mới thật sự có dòng mới.
- **Kết quả đo theo dòng gốc** (6.300 lần sửa):

  | Ca | Trước | Sau |
  |---|---|---|
  | Dời dòng: nối sang cảnh khác nội dung | 28 | **0** |
  | Dòng trùng + chèn: tráo giữa hai cảnh y hệt | 249 | **0** |
  | Xoá 1 trong nhiều bản y hệt | 168 | 66 |

  66 ca còn lại không quyết định được: xoá bản nào thì tài liệu thu được cũng giống hệt nhau.
- **`with_segments()`:** lối dự phòng qua id segment. Chỉ áp cho cảnh cũ mà lineage chưa ghép được, không giao một cảnh cũ cho hai cảnh mới. Luôn `match="segment"`, `changes=["unverified"]`, và **không được kế thừa gì**.

**Chính sách kế thừa — `inheritance(match, changes, keep_voice)`, chính sách chuẩn duy nhất:**
- `visual`: hình và "look" (transition, effect, trim) đi theo mọi cặp khớp đã xác minh; lời đổi thì vẫn giữ nhưng có `review`.
- `layers` (overlays, graphic direction, sound cues, edit beats): chỉ còn hợp lệ khi lời, người nói và chữ trên màn hình không đổi.
- `timing`: còn hợp lệ khi giọng mà lớp dựng được căn theo vẫn còn (`keep_voice`). Lineage không có thông tin giọng nên trả `None` khi lời giữ nguyên (không đoán), và `False` khi lời đổi.
- Khớp không xác minh (`segment`) hoặc cảnh mới thêm: không nhận gì.

**Reconcile ghi gì:**
- Bản ghi `storyboard_reconcile` lưu cho từng cảnh: `status`, `changes`, `keep_voice`, `inherit`, `retimed`, `shot_id`/`segment_id` cũ, `new_shot_id`/`new_segment_id`, và `lineage` (cùng các trường đó).
- Đã kiểm trên bản ghi trong DB cho thêm / xoá / dời / tách / gộp, cả tại chỗ lẫn mang sang. Rollback khi lỗi giữa chừng: không còn bản ghi, các dòng không đổi.
- Khi một dòng mất giọng, độ dài về mức ước lượng, và overlay / sound cue / edit beat được **retime theo tỉ lệ**. Trước bản sửa này, overlay vượt thời lượng mới làm renderer dừng hẳn với lỗi "Overlay nằm ngoài thời lượng cảnh".

**Checkpoint kiến trúc (READY_FOR_T1):**
- Đã sửa một mâu thuẫn: hai verdict `timing` trái nhau trong cùng một bản ghi (plan nói `False`, lineage nói `True`). Đã bỏ hằng chết `VOICE_CHANGES`.
- **Nguồn sự thật cho từng quyết định:**

| Quyết định | Hiện tại | Đích |
|---|---|---|
| Giữ giọng | `keeps_voice()` → `plan()` → cột voice | không đổi (giọng gắn với dòng timeline, không thuộc EditDocument) |
| Hình / layers / beats / retime / stale | `apply_storyboard_reconcile` chép theo cơ chế + `Database._retime` (lớp tạm T0.5) | EditDocument (T1) → `apply_scenes` (T3); reconcile thôi chép cột edit (T4) |

- **Ràng buộc T3/T4:** không được có giai đoạn mà cả reconcile (chép cột edit + `_retime`) **và** `apply_scenes` cùng ghi cột edit. T4 phải gỡ hai thứ đó trong cùng thay đổi nối `apply_scenes` vào sau reconcile.

---

## 9. T1 — EditDocument Engine thuần (xong, CHỜ DUYỆT)

**File:**
- `youtube_monitor/edit_document.py` (mới).
- `tests/test_edit_document.py` (25 test).
- `storyboard_reconcile.py`: thêm `scene_changes(before, after)`, và lineage cũng gọi hàm này; logic không đổi.

**Cấu trúc:**

```text
{kind: "edit_document", engine_version: "edit-phase1", provenance, based_on (hash document trước),
 scenes: [{scene_key, index, segment_id,
           lineage{previous_scene_key, previous_index, previous_segment_id, match},
           basis{scene_key, storyboard_hash, scene{lời, người nói, section, role, dòng, chữ trên màn hình,
                 trích dẫn}, voice{audio_signature, voice_fingerprint, duration_seconds}, edit_hash} | null,
           edit{visual{}, layers{overlays[], sound_cues[], direction{}}, beats[]},
           voice (giọng hiện tại: audio_signature, voice_fingerprint, duration_seconds, fits),
           changes, inherit, timing{state kept|retimed|stale, basis_seconds, current_seconds, ratio, errors},
           statuses[], status, ready, review[]}],
 orphans: [{scene_key, storyboard_hash, segment_id, reason removed|unverified|legacy, candidate,
            edit, basis, status "orphan", ready false}],
 counts, document_hash}
```

**Provenance:**
- `storyboard_id`, `storyboard_hash`, `storyboard_engine`;
- `script_id`, `script_version`, `script_fingerprint`;
- `plan_id`, `plan_version`, `plan_fingerprint`;
- `voice_fingerprint`, `audio_signature`.

**API:**
- `build(storyboard, voices=, previous=, previous_storyboard=, segments=, links=, legacy=, storyboard_id=, voice_fingerprint=)`.
- `plan_scene(document, storyboard, scene_key, edit=None)`: lập lại edit cho cảnh và đặt basis mới. `edit=None` = chấp nhận edit đang chạy (đã retime). Từ chối edit có thời gian vượt cảnh, và từ chối chấp nhận khi timing đang stale.
- `judge()`, `effective_edit()` (edit đã retime theo giọng hiện tại), `retimed()`, `timing_errors()`.
- `voice_entry(row, scene, audio_signature=, duration_seconds=, voice_fingerprint=)`: adapter thuần, gọi `keeps_voice()` để tạo `fits`.
- `validate(document, storyboard=None)`: có storyboard thì đánh giá lại từng cảnh và so với trạng thái đang lưu.

**Mô hình trạng thái:**
- `statuses` giữ **mọi** trạng thái đúng, theo thứ tự `needs_plan → stale_content → stale_overlays → stale_timing → visual_review`.
- `status` là trạng thái đầu tiên, hoặc `ready` nếu rỗng.
- `orphan` chỉ có trong `orphans`, luôn `ready=false`.
- Ví dụ lời đổi: `[stale_content, visual_review]` + `timing.state=retimed`; nếu retime không được thì có thêm `stale_timing`.

**Basis là trung tâm:**
- Trạng thái luôn tính lại từ `basis` so với storyboard và giọng hiện tại; không đọc timeline, không đọc bản ghi reconcile.
- Basis chỉ đổi qua `plan_scene`.
- Đã test: sửa X (stale) rồi lần sau chỉ sửa Y — X **vẫn stale** dù `lineage()` của lần sau nói X `unchanged`.
- Edit lưu nguyên như lúc lập; retime luôn tính từ basis nên không cộng dồn sai số.

**Cách dùng ba chính sách:**
- `lineage()` nối cảnh.
- `inheritance(match, scene_changes(basis.scene, cảnh hiện tại), voice_kept)` là verdict duy nhất.
- `keeps_voice()` không được engine gọi, chỉ đi vào qua `fits`.
- `voice_kept` = cùng audio (hoặc cùng chưa có giọng, cùng độ dài) **và** `fits`. Không bao giờ suy từ việc lời giống nhau.
- Có test: khi build, `plan()`, `keeps_voice` và `open` bị đặt báo lỗi nếu bị gọi — build vẫn chạy; `inheritance` được gọi đúng một lần cho mỗi cảnh có edit.

**Test ma trận A–L:**
- A. Không đổi: giữ tất cả.
- B. Lời đổi: `stale_content` + `visual_review`, retime 5 s → 3 s.
- C. Người nói đổi: như B, review `speaker`.
- D. Đổi section/role, lời giữ nguyên: chỉ `visual_review`.
- E. Chữ trên màn hình đổi: `stale_overlays`, giữ hình.
- F. Đổi cấu hình giọng: timing `retimed`, không bao giờ `kept`.
- G. Giọng không đổi: không bao giờ `stale_timing`.
- H. Retime thất bại: `stale_timing`.
- I. Tách cảnh: mảnh mới `needs_plan`, không nhận edit cũ.
- J. Gộp cảnh: phần sau thành orphan.
- K. Orphan: luôn `ready=false`.
- L. Legacy / segment: không kế thừa, giữ lại thành orphan có `candidate`.

Thêm: `[X, Y, X]` với chèn / xoá / dời không tráo edit; validator bắt 8 kiểu sai; cùng đầu vào cho ra cùng document, giống đến từng byte.

**Điều cần biết cho các bước sau (không phải lỗi):**
- Phép retime đang có ở hai nơi: `edit_document.retimed` (bản chuẩn) và `Database._retime` (lớp tạm T0.5, gỡ ở T4).
- Orphan được giữ lại qua mọi lần build; cách dọn bớt là việc của T2/T6.
- Cảnh trùng y hệt không quyết định được: lineage chọn theo quy tắc cố định, không đánh dấu "ambiguous" (edit vẫn khớp từng chữ).
- `origin` (ai/manual) và `applied.layer_hash` trong thiết kế chưa có trong T1. Đúng phạm vi: T3/T6 mới cần.

---

## 9b. T2 — Lưu trữ EditDocument (HOÀN THÀNH 08/10, chờ duyệt)

### Quyết định người dùng đã chốt

1. **Storage A:** `project_director_artifacts`, `kind="edit_document"`.
   - Không migration; bảng đã có sẵn.
   - **Không dùng `project_edit_plans`.** Edit Plan cũ và EditDocument hoàn toàn tách biệt, không đọc hay ghi lẫn nhau.
   - Version/history là các dòng artifact, chỉ thêm, không sửa dòng cũ.
   - `save_edit_document()` kiểm `expected_parent` **trong cùng transaction** với lệnh ghi (`BEGIN IMMEDIATE`), để chống ghi đè cạnh tranh.
   - Cùng `document_hash` với bản mới nhất thì dùng lại dòng đó, không tạo dòng mới.
2. **Bootstrap (b):** lớp dựng và visual đang có trên timeline được giữ thành **orphan `legacy`**.
   - Không dựng basis giả. Không cảnh nào thành `ready` chỉ vì đã có visual cũ.
   - EditDocument **không sở hữu** visual cũ.
   - T2 chỉ ghi nhận orphan, `candidate` và lineage. Không dọn file, không ghi ngược xuống timeline.

### Thay đổi

Code T2 ban đầu nằm trong `30ca9e1`. Commit T2 bổ sung:

| File | Thay đổi |
|---|---|
| `youtube_monitor/database.py` | `save_director_artifact` / `get_director_artifact` **từ chối** `kind="edit_document"`. EditDocument chỉ được ghi qua `save_edit_document`, chỉ được đọc qua `list_edit_documents` / `edit_store`. (Có sẵn từ `30ca9e1`: `EDIT_DOCUMENT_KIND`, `StoredEditDocumentError`, `EditDocumentConflict`, `list_edit_documents`, `get_latest_edit_document`, `save_edit_document`, `get_project_storyboard_by_hash`.) |
| `youtube_monitor/edit_document.py` | `plan_scene()` đặt `based_on` = hash của bản vừa dựa trên, giống `build()`. Trước đó nó chép nguyên `based_on` cũ. Nếu sửa cảnh A → B → A, bản thứ ba trùng byte với bản A trong lịch sử, `save` từ chối, và người dùng không quay lại được edit cũ. Nay quay lại là một phiên bản mới. |
| `youtube_monitor/edit_store.py` | `sync()` chỉ coi là "không đổi" khi provenance và, cho từng cảnh, `scene_key`, `segment_id`, giọng (kể cả `fits`), `statuses`, `timing` đều giống nhau (hàm `_held`). Trước đó chỉ so `segment_id`, nên bỏ sót trường hợp `fits` đổi mà file audio không đổi. `lineage` không được so, vì sync lại trên cùng storyboard nối mỗi cảnh với chính nó, và `inheritance()` không phân biệt loại match đã xác minh. |
| `tests/test_edit_store.py` (mới) | 20 test trên DB tạm, chi tiết bên dưới |

`edit_store.py` gồm:
- `load` / `history` / `current` (`current` · `outdated` · `missing`), đọc chặt và qua `validate()`;
- `save`;
- `snapshot` (đọc shots, timeline, giọng, edit beats);
- `sync` (`bootstrap` · `follow` · `carried_over` · `unchanged`);
- `plan_scene`.

Chưa có caller, route hay MCP nào gọi `edit_store`. Đây là đúng phạm vi T2.

### Test (`tests/test_edit_store.py`, 20 test)

| Nhóm | Kiểm |
|---|---|
| Lưu trữ (3) | Lưu ở `project_director_artifacts`, 0 dòng `project_edit_plans`. Một Edit Plan cũ có `kind: edit_document` không bị đọc thành EditDocument, và sync không đụng tới nó. Hàm director artifact chung không với tới được EditDocument |
| Phiên bản (5) | Cùng hash thì dùng lại dòng cũ. `expected_parent` sai thì 409, không ghi gì. Khoá ghi được giữ **trước** khi đọc bản mới nhất: một writer khác chen vào nhận "database is locked". Quay lại edit cũ là phiên bản mới. Bản đã có sâu trong lịch sử thì không lưu lại |
| Đọc (5) | Dòng JSON hỏng bị từ chối, không bỏ qua. Nội dung bị sửa không khớp hash bị từ chối. Sửa rồi băm lại hash mà không qua `validate()` cũng bị từ chối. Storyboard đổi hash bị từ chối. `current` / `outdated` / `missing` |
| Bootstrap (5) | Mọi cảnh `needs_plan`, `basis=None`, không cảnh nào `ready`. Mỗi hàng có hình thành một orphan `legacy` giữ nguyên `visual_path`, kèm `segment_id` và `candidate`. Sync không ghi gì xuống timeline và không xoá file nào. Hàng chưa ai sửa thì không sinh orphan. Cột JSON hỏng được giữ lại (`unparsed_*`). Shots lệch storyboard thì không đọc |
| Follow (2) | Orphan và cảnh đã lập vẫn còn ở phiên bản sau, `parent_hash` đúng. Kịch bản mới chạy `carried_over`, có `carried_from`, lịch sử của kịch bản cũ giữ nguyên |

### Kết quả (08/10, Linux, phiên Claude trên cloud, venv tạm, DB tạm của `conftest.py`)

- **Test T2:** **20/20 đạt.**
- **Mutation test:** cả **5/5 đột biến** đều bị test bắt:
  - bỏ `based_on` trong `plan_scene`;
  - bỏ `BEGIN IMMEDIATE`;
  - bỏ guard `kind`;
  - bỏ kiểm `expected_parent`;
  - bỏ đưa `legacy` vào bootstrap.
- **Nhóm Bước 5** (`test_edit_document`, `test_storyboard_lineage`, `test_storyboard_gate`, `test_storyboard_engine`): **134/134 đạt**.
- **Full suite (Linux):** **2246 đạt · 11 đỏ · 13 bỏ qua** (229 subtest đạt).
  - Cả 11 test đỏ đều có ở baseline chạy trên HEAD trước khi sửa. **Không có regression mới.**
  - Baseline: 2224 đạt, 13 đỏ. Hai test `test_premiere_plugin` đỏ ở baseline chỉ vì baseline chạy trên bản `git archive` bị thiếu file. Chênh lệch +22 = 20 test mới + 2 test đó.
  - 2 đỏ cũ đã biết: `test_burned_in_marks::…test_an_unmarked_reup_gets_its_source_measured`, `test_shorts::RendererFitTests::test_the_renderer_can_fill_a_frame_as_well_as_pad_it`.
  - 9 đỏ do môi trường Linux/cloud: `test_operations` ×4, `test_voxcpm_readiness` ×2, `test_motion_graphics` ×1, `test_channel_accounts` ×1, `test_publish_gate` ×1. Không điều tra thêm.
  - Số liệu Windows (máy người dùng) chưa đo lại cho T2. Lần đo gần nhất là sau T1: 2239 đạt, 2 đỏ cũ.
  - Venv tạm phải cài thêm `pillow`: test cần gói này nhưng `requirements.txt` không có.

### Chưa làm (cố ý)

- Chưa chạy app, chưa mở DB thật, chưa migration.
- **Chưa real-run T2** với app hay DB thật. DB thật không có trong môi trường cloud nên chưa đo lại hash.
- Không sửa reconcile, gate, apply, UI hay route Edit Plan cũ.

### Rủi ro còn lại, đã chuyển sang task sau

1. **T3 — hình legacy chưa được sở hữu.** Hàng timeline còn orphan `legacy` thì T3 **tuyệt đối không được xoá hay ghi đè `visual_path`** khi EditDocument chưa sở hữu hay kiểm soát visual đó.
   - T3 tra orphan theo `segment_id`, vì `segment_id` vẫn đúng khi storyboard đổi.
   - Không tra theo `candidate`: đó là `scene_key` của storyboard lúc bootstrap, không được nối lại khi storyboard đổi.
2. **T3/T7 — layer ghi sau bootstrap thì EditDocument không thấy.** Bốn đường ghi của Edit Plan cũ (mục 5) vẫn ghi thẳng xuống timeline. Từ bản thứ hai, `build()` không đọc lại timeline (T1 cố ý cấm `legacy` khi đã có `previous`). T3 phải so hàng timeline với thứ document đang sở hữu trước khi ghi. T7 phải chặn các đường ghi đó.
3. **T6 — orphan không có cơ chế dọn.** Bootstrap sinh nhiều orphan, vì hàng do storyboard sinh ra thường đã có `visual_prompt` (liên quan F8). Cờ `unverified` ở cấp cảnh chỉ có ở bản bootstrap; sau đó chỉ còn trong danh sách orphan.
4. **T3/T6 — `sync()` tự ghi khi được gọi** nhưng chưa có caller. Ai gọi và gọi lúc nào phải được định nghĩa ở T3/T6.
5. **Chống race chỉ trong SQLite.** `BEGIN IMMEDIATE` chặn được nhiều tiến trình cùng DB. Phần sửa `_held` (trường hợp `fits` đổi mà audio không đổi) chưa có test riêng.

---

## 9c. T3 — Apply EditDocument → timeline (HOÀN THÀNH 08/10: đã sửa B1–B4, qua final review, đã commit — chưa có caller)

### Quyết định người dùng đã chốt (audit T3, H1–H6)

| # | Quyết định |
|---|---|
| H1 | Trạng thái đã áp lưu ở `project_director_artifacts`, `kind="edit_apply"`. Mỗi lượt áp có ghi một dòng, không migration |
| H2 | Cảnh có basis và edit có `visual.visual_path` thì EditDocument **sở hữu** visual của hàng và ghi toàn bộ cột visual. Edit không có `visual_path` thì **giữ nguyên** visual hiện tại, kể cả visual legacy. Không xoá file nào |
| H3 | `needs_plan` → không ghi; `visual_review` → được ghi; `stale_content` / `stale_overlays` / `stale_timing` → không ghi |
| H4 | T3 **không** thêm caller hay route. Chỉ có hàm thư viện, storage và test. T4/T6 sẽ nối caller |
| H5 | Cột thuộc EditDocument: `edit_store._VISUAL_COLUMNS` + `asset_type`, `overlays`, `sound_cues`, `edit_direction`, cùng bảng edit beats. Không đụng audio, subtitle, duration, voice, status, `project_shots.visual_prompt` |
| H6 | Cảnh conflict thì bỏ qua và trả `conflict`; các cảnh hợp lệ vẫn được áp. Có transaction rõ ràng: conflict không phải exception; lỗi hệ thống thật thì rollback cả lượt |

### Sửa sau review cuối (B1–B4, người dùng đã duyệt hướng sửa)

Lần review trước commit đã chạy probe và chứng minh 3 lỗi thật, cộng 1 thiếu sót so với H1. Đã sửa cả bốn:

| # | Lỗi (probe chứng minh) | Sửa |
|---|---|---|
| B1 | Edit không nêu beats làm **xoá beats legacy** của hàng (P2: beats `[]` sau khi áp) | Edit không có beats → `beats=None` → **không đụng** beats của hàng (không DELETE). Edit có beats → thay, vẫn qua expected-state như mọi cột khác |
| B2 | Xoá beat làm `scene_generation_jobs.edit_beat_id` thành NULL (`ON DELETE SET NULL`). Job `cancelled` được retry khi xong ghi đè **hình của cả cảnh** (P4) | Trước khi thay beats: nếu **bất kỳ** job nào trỏ `edit_beat_id` vào beat của hàng (mọi trạng thái, vì `error`/`cancelled`/`completed`-review-fail đều retry được) → `skipped: beat_has_jobs`, giữ nguyên hình và beats. Không sửa route retry |
| B3 | `None` cho cột `NOT NULL` → `IntegrityError` → **rollback cả cảnh hợp lệ** (P5); `asset_id="abc"` → `ValueError` trong transaction | DB kiểm từng giá trị theo **schema thật** (`PRAGMA table_info`: kiểu khai báo + `NOT NULL`, số hữu hạn) **trước** khi ghi → `skipped: invalid_edit`, không dùng `IntegrityError` làm control flow. Engine có `InvalidEditError` riêng (JSON sai loại, overlay không phải object, beat sai schema), chỉ catch đúng loại này. Lỗi hệ thống / lập trình vẫn rollback cả lượt |
| B4 | Bản ghi thiếu "columns written" | Mỗi hàng có thêm `columns_written` (danh sách cột đã ghi) và `beats_written` (số beat, hoặc `null` nếu không đụng beats). Format cũ giữ nguyên, chỉ thêm khoá |

### Thay đổi (commit T3 trên `claude/dreamy-gates-4qehd3`)

| File | Nội dung |
|---|---|
| `youtube_monitor/database.py` (+232 dòng, chỉ thêm) | `EDIT_APPLY_KIND`, `EDIT_OWNED_COLUMNS`, `EDIT_BEAT_COLUMNS`, `StoredEditApplyError`, `_schema_problem` (kiểm theo schema thật). `save_director_artifact` / `get_director_artifact` từ chối `kind="edit_apply"`. Thêm `list_edit_applies` và `apply_edit_document_rows` (mô tả bên dưới) |
| `youtube_monitor/edit_apply.py` (mới) | `state_hash`, `row_writes` (H2/H5), `plan` (H3, legacy theo `segment_id`), `apply_scenes` (bắt buộc document `CURRENT` và theo kịp timeline/giọng hiện tại). Không module nào import nó (H4) |
| `tests/test_edit_apply.py` (mới) | 46 test: 10 nhóm ban đầu + B1 (6) + B2 (7) + B3 (6) + B4 (1) |

**Transaction** (`Database.apply_edit_document_rows`): `BEGIN IMMEDIATE`, sau đó với từng hàng:
1. Hàng không thuộc project/script → `skipped: missing_row`.
2. Giá trị không hợp với schema thật của bảng (kiểu, `NOT NULL`) → `skipped: invalid_edit`, không ghi hàng đó.
3. Đọc hàng và beats, tính `state_hash`.
4. **Expected-state** đọc trong transaction, theo thứ tự:
   1. `state_hash` mà lượt áp gần nhất để lại cho hàng đó;
   2. hash của orphan `legacy` có **cùng `segment_id`** (không bao giờ dùng `candidate`);
   3. edit rỗng (chưa từng ghi).
5. Hàng khác expected → `conflict` (`timeline_changed`, kèm `expected_from`), không ghi hàng đó.
6. Lượt áp trước đã ghi đúng edit này và hàng vẫn như nó để lại → `unchanged`, không ghi.
7. Edit có beats và có job (mọi trạng thái) trỏ vào beat hiện có của hàng → `skipped: beat_has_jobs`.
8. Còn scene job chưa xong trên hàng → `skipped: scene_job_running` (job xong sẽ ghi đè hình).
9. Beat trỏ tới asset không thuộc project → `skipped: unknown_asset`.
10. Còn lại: UPDATE các cột sở hữu; thay beats **chỉ khi edit nêu beats**; đọc lại để lấy `state_hash` mới.

Hàng đã ghi và bản ghi `edit_apply` (`rows`: `segment_id`, `scene_key`, `layer_hash`, `state_hash`, `visual_owned`, `columns_written`, `beats_written`) được **commit cùng nhau**. Conflict và `invalid_edit` chỉ bỏ qua hàng đó; lỗi hệ thống rollback cả lượt. Không có hàng nào ghi thì không tạo bản ghi. Mọi exception (lỗi hệ thống, cột ngoài `EDIT_OWNED_COLUMNS`) → rollback cả lượt.

**`apply_scenes()`** trả `{document_hash, artifact_id, applied, unchanged, skipped, conflicts}`. Nó từ chối (`EditStoreError`, không ghi gì) khi:
- document không `CURRENT`;
- shots / timeline lệch storyboard;
- `segment_id` hoặc giọng của cảnh khác với lúc document được dựng (phải `sync()` trước);
- `scene_keys` có cảnh không tồn tại (422).

Hàm ghi `effective_edit()` (đã retime theo giọng), `layer_hash = edit_hash(effective_edit)`.

### Test (`tests/test_edit_apply.py`, 46 test)

| Nhóm | Kiểm |
|---|---|
| 1. Áp cảnh ready (3) | Ghi đúng cột, beats, bản ghi `edit_apply`; ghi edit đã retime; cột không sở hữu giữ nguyên; tập cột khớp T2 |
| 2. Không có gì để áp (2) | Bootstrap: mọi cảnh `needs_plan`, timeline và file nguyên vẹn. Carried over: hình được reconcile chép sang → `conflict` (`expected_from: default`), không xoá hay ghi đè |
| 3. Sở hữu hình (3) | Edit không có hình → giữ hình legacy, chỉ ghi look và layer. Edit có hình → thay hình; file legacy và orphan vẫn còn. Orphan nối theo `segment_id`, tráo `candidate` không ảnh hưởng |
| 4. Conflict (3) | Hàng bị sửa tay sau lần áp → conflict, các cảnh khác vẫn áp. Job ảnh hoàn thành, hoặc layer cũ ghi đè hàng legacy → conflict. Hàng legacy chưa bị đụng → áp được |
| 5. Trạng thái (2) | `plan()` chỉ nhận `ready` / `visual_review`. Tích hợp: cảnh đổi lời (`stale_content` + `visual_review`) giữ nguyên |
| 6. Điều kiện (5) | Document lệch timeline/giọng → từ chối. Không `CURRENT` → từ chối. Cảnh lạ → 422. Hàng của script khác → `missing_row`. Cột ngoài danh sách → exception, không ghi |
| 7. Transaction (1) | Lỗi hệ thống sau khi đã ghi 2 hàng → rollback cả hai, không có bản ghi |
| 8. Idempotent (2) | Áp lại cùng document → `unchanged`, không ghi, không đổi `updated_at`, không tạo bản ghi. Edit mới → ghi |
| 9. Beats và job (3) | Beat được job gắn asset → conflict. Job đang chạy → skip. Asset của project khác → skip |
| 10. Tách biệt (2) | Không đụng `project_edit_plans`; hàm director artifact chung không với tới `edit_apply`. Bản ghi `edit_apply` hỏng → từ chối, không bỏ qua |
| B1. Beats legacy (6) | Edit không có beats → beats legacy còn nguyên (cùng id). Hình và beats legacy cùng còn. Edit có beats → thay đúng. Áp lại → `unchanged`, beats không bị thay lại. Beats bị ghi ngoài → conflict, không bị xoá. Edit không beats sau một lượt có beats → giữ beats |
| B2. Job giữ beat (7) | Job `running` / `queued` / `error` / `cancelled` / `completed` trỏ vào beat → `beat_has_jobs`, hình và beats giữ nguyên, `edit_beat_id` còn nguyên. Retry job sau T3 → job ghi vào beat của nó, **không** ghi đè hình cảnh. Beat không có job → thay được |
| B3. Edit không hợp lệ (6) | Cảnh hợp lệ + cảnh `edit_transition=None` → cảnh hợp lệ commit, cảnh kia `invalid_edit`. `asset_id="abc"` → `invalid_edit`. Cảnh cuối lỗi → các cảnh trước vẫn commit. DB nêu lỗi trước khi ghi, không qua `IntegrityError`. Engine nêu edit sai hình dạng. Lỗi phát hiện ở engine → `invalid_edit` qua `apply_scenes` |
| B4. Bản ghi (1) | Mỗi hàng có `columns_written`, `beats_written`, đúng với cái đã ghi |

### Kết quả (08/10, Linux, venv tạm, DB tạm) — sau khi sửa B1–B4

- **Test T3:** **46/46 đạt** (26 ban đầu + 20 cho B1–B4).
- **Mutation test: 23/23 đột biến bị bắt.**
  - 15 đột biến ban đầu:
    - bỏ kiểm expected-state;
    - bỏ expected legacy;
    - bỏ `needs_plan`;
    - bỏ kiểm stale;
    - luôn sở hữu hình;
    - bỏ `unchanged`;
    - bỏ kiểm job đang chạy;
    - bỏ kiểm "theo kịp";
    - bỏ guard `kind`;
    - commit từng hàng;
    - bỏ kiểm cột sở hữu;
    - bỏ kiểm asset;
    - bỏ bắt buộc `CURRENT`;
    - bỏ kiểm hàng lạ;
    - nối orphan theo `candidate`.
  - 8 đột biến mới:
    - edit không beats vẫn thay beats;
    - luôn DELETE beats;
    - bỏ `beat_has_jobs`;
    - `beat_has_jobs` chỉ tính job còn sống;
    - bỏ kiểm schema;
    - không catch `InvalidEditError`;
    - bỏ kiểm loại JSON;
    - bỏ `columns_written`.
  - 2 đột biến mới (không catch `InvalidEditError`, bỏ kiểm loại JSON) ban đầu **sống sót**. Đã thêm 1 test tích hợp và 1 ca chuỗi JSON sai loại; sau đó cả hai bị bắt.
- Đột biến "commit từng hàng" (lần code đầu) ban đầu không bị bắt vì test transaction lỗi (mock gọi đệ quy). Đã sửa test; hàng đầu được chứng minh là đã ghi rồi bị rollback.
- **Probe chạy lại sau khi sửa** (DB tạm):
  - **P2:** beat legacy + edit không beats → hình giữ, beats giữ nguyên (cùng id).
  - **P4:** job `cancelled` trỏ beat → `beat_has_jobs`, `edit_beat_id` còn nguyên. Retry → job ghi vào beat, hình cảnh vẫn là hình T3 đã áp.
  - **P5:** cảnh hợp lệ commit, cảnh `edit_transition=None` → `invalid_edit`, có bản ghi.
- **Nhóm Bước 5 + T2 + T3:** **200/200 đạt** (134 + 20 + 46).
- **Full suite (Linux):** **2292 đạt · 11 đỏ · 13 bỏ qua**.
  - Trước T3 là 2246 đạt; +46 = test T3.
  - 11 đỏ **giống hệt** danh sách trước T3: 2 đỏ cũ (`test_burned_in_marks`, `test_shorts`) + 9 do môi trường Linux/cloud. **Không có regression.**
- Chưa chạy app, chưa mở DB thật, chưa migration, không gọi API thật. **Chưa real-run T3.**

### Giới hạn đã biết, chuyển sang task sau

1. **T4:**
   - Hàng mang sang kịch bản mới (reconcile chép hình) luôn là `conflict` (`expected_from: default`), vì chưa có lượt áp nào và chưa có orphan nào cho `segment_id` mới. Cố ý an toàn.
   - Tương tự, reconcile tại chỗ `_retime` layer → hàng lệch `state_hash` → `conflict`.
   - T4 phải nối `apply_scenes` vào sau reconcile, đồng thời gỡ việc chép cột edit và `_retime`.
2. **T4/T6:** chưa có caller. `apply_scenes` chỉ được test gọi.
3. **H5:** T3 không gọi `resync_timeline_segment_states`, nên cột `status` có thể chưa phản ánh hình mới cho tới lần resync kế tiếp (reconcile, job…). Caller ở T4/T6 cần quyết định có gọi hay không.
4. **T6:**
   - Khi EditDocument sở hữu hình (H2), mọi cột visual không có trong edit (kể cả `visual_prompt`, `source_start_seconds`) trở về default.
   - Edit không nêu beats thì không bao giờ xoá được beats của hàng (cố ý, B1). Muốn bỏ beats cần một thao tác rõ ràng ở T6.
   - Khi thay beats, id beat đổi. Beat có job trỏ vào thì không bao giờ bị thay (B2), nên một hàng có beat từng được gửi job sẽ luôn `beat_has_jobs` cho tới khi T6 có cách xử lý (ví dụ cập nhật beat tại chỗ).
5. **T7:**
   - `state_hash` đọc theo `edit_store.timeline_edit`: `asset_type` chỉ được tính khi hàng có `visual_path`. Đổi riêng `asset_type` trên hàng không có hình thì không bị phát hiện.
   - Bốn đường Edit Plan cũ vẫn ghi được timeline. T3 chỉ **phát hiện** (conflict), không chặn.
   - Job cấp cảnh (không có `edit_beat_id`) ở trạng thái `error`/`cancelled` vẫn retry được và ghi đè `visual_path` của cảnh. Đây là hành vi cũ, không do T3 gây ra; T3 chỉ chặn job **chưa xong** (`scene_job_running`), và lần áp sau sẽ phát hiện thành conflict.
7. **T4 (caller) / T7 (gate):**
   - Kiểm `CURRENT` và "theo kịp" (`_fresh`) chạy **trước** transaction; cột giọng không nằm trong `state_hash`, nên một reconcile chen vào giữa không bị phát hiện.
   - `storyboard_row` do caller truyền không được kiểm là storyboard mới nhất (giống T2 `sync()`).
   - Chưa có caller nên chưa xảy ra được; caller ở T4 phải giữ hai điều kiện này.
6. **T6:** dọn orphan.

---

## 10. Yêu cầu bắt buộc cho T2 (đã nêu ở checkpoint)

- Trạng thái "stale" ở T0.5 **không bền**: nó chỉ nằm trong bản ghi reconcile của từng lần, và `get_director_artifact` chỉ đọc bản mới nhất.
- **Khi T2 dựng EditDocument lần đầu cho một timeline đã có lớp dựng** (bootstrap), không được nhận các lớp đó là `ready` một cách mù quáng. Hai cách:
  - gộp lại các bản ghi `storyboard_reconcile` theo `new_segment_id` để tái dựng basis;
  - hoặc đưa vào qua `build(..., legacy=...)`: lớp dựng được giữ thành orphan `legacy` cho người dùng xem lại.
- DB thật hiện có **0 storyboard**, nên chưa dự án thật nào ở trạng thái này.

---

## 11. Việc tiếp theo

1. Người dùng cùng GPT **duyệt T1** (mục 9).
2. ~~Chốt T2~~: **xong 08/10** (mục 9b). Nên chạy lại full suite trên Windows để xác nhận.
3. ~~T3 — Apply~~: **xong 08/10** (mục 9c), đã commit và push. Nên chạy lại full suite trên Windows.
4. **T4 — Nối reconcile:** gọi `edit_apply.apply_scenes` sau reconcile; trong **cùng thay đổi** gỡ việc reconcile chép cột edit và `Database._retime` / `_retime_beats`; xử lý hàng mang sang (mục 9c, giới hạn 1). **Bắt buộc theo checklist 11a.**
5. Sau đó lần lượt T5 … T9 (mục 6). Mỗi task một báo cáo, chờ duyệt.
6. Việc phụ chờ người dùng quyết: có gỡ các file `_tmp_*` (và `pymupdf_deps/`) khỏi git hay không (mục 2).

### 11a. T4 — Integration checklist bắt buộc (đã thống nhất 08/10)

Đây là **contract cho T4**, chưa triển khai. Nó không thay đổi contract T3 (H1–H6, B1–B4, mục 9c): T3 là thư viện apply độc lập và chưa có caller. Test T3 xanh **không** có nghĩa Bước 5 đã sẵn sàng cho sản xuất; T4 là nơi kiểm chứng caller thật.

1. **CURRENT / freshness**
   - Kiểm tra `CURRENT` (`edit_store.current`) và `_fresh` (document theo kịp `segment_id` + giọng hiện tại) **đúng thời điểm**, ngay trước khi apply.
   - Không để caller áp dụng EditDocument dựa trên snapshot đã stale.
   - Hiện tại hai kiểm tra này chạy **trước** transaction của `apply_edit_document_rows()`, và cột giọng không nằm trong `state_hash`. T4 phải tính tới khoảng hở này.
2. **Storyboard hiện hành**
   - Xác minh `storyboard_row` truyền vào thực sự là storyboard hiện hành của script (bản mới nhất, Storyboard Gate `current`) trước khi apply.
   - Không chỉ dựa vào việc row tồn tại hay `current()` trả `CURRENT` so với row do caller tự chọn.
3. **Segment identity / reconcile**
   - Khi reconcile hoặc revision kịch bản làm đổi `segment_id` (hàng mang sang có id mới; hàng bị xoá), phải xử lý theo expected-state / conflict của T3.
   - **Không dùng `candidate`** để nối lại visual hay edit; orphan chỉ được nhận diện theo `segment_id`.
   - T4 phải gỡ việc reconcile (`apply_storyboard_reconcile`) **chép các cột edit** sang hàng mới, vì đây là nguyên nhân hàng mang sang luôn thành conflict ở T3.
   - Việc gỡ này phải nằm **trong cùng thay đổi tích hợp T4**: không được nối caller mới vào trên một reconcile vẫn phá provenance của EditDocument (ràng buộc T3/T4 ở mục 8).
4. **`_retime` / timing**
   - Không để `_retime` / `_retime_beats` âm thầm sửa dữ liệu edit thuộc EditDocument.
   - T4 phải gỡ hoặc điều chỉnh đường `_retime` đang ghi đè edit, trong cùng thay đổi tích hợp.
   - Timing thực tế phải đi qua `effective_edit()` / giọng hiện tại theo contract T3.
   - Hàng bị `_retime` làm lệch phải trở thành **conflict**, không bị ghi đè im lặng.
5. **Partial success**
   - Caller phải hiểu đúng kết quả `apply_scenes()`:
     - `conflicts` và `skipped` (`needs_plan`, `stale`, `invalid_edit`, `beat_has_jobs`, `scene_job_running`, `unknown_asset`, `missing_row`, `no_row`) là bỏ qua **theo từng cảnh**;
     - lỗi hệ thống là exception, đã rollback **toàn bộ** lượt apply.
   - Không được biến kết quả một phần thành "thành công".
   - Nếu T4 chạm tới UI, status hay log, chúng phải hiện đúng số cảnh `applied` / `unchanged` / `skipped` / `conflicts`.
6. **Transaction boundary**
   - Hiện `apply_edit_document_rows()` **tự mở connection** và `BEGIN IMMEDIATE`.
   - `apply_storyboard_reconcile()` và `edit_store.sync()` (T2) cũng mỗi hàm một transaction riêng.
   - T4 phải quyết định rõ một trong hai:
     - **a.** Giữ các transaction riêng, chạy tuần tự `reconcile → sync() → apply_scenes()`, dựa vào expected-state để phát hiện thay đổi chen vào giữa; hoặc
     - **b.** Refactor chữ ký / API để cả chuỗi dùng chung một connection / transaction.
   - Không được tạo cảm giác atomic giữa reconcile / sync / apply nếu thực tế vẫn là nhiều transaction độc lập.

**Known limitations còn lại:**
- Job tạo ảnh/video chưa qua Storyboard Gate (để 5.4).
- Edit Plan cũ chưa qua gate (T7).
- UI Bước 5 chưa đổi; nút giọng ở Bước 4 vẫn tự gửi `force` khi nhận `stale` (để 5.4).
- Short ngoài phạm vi.

**Backlog chỉ ghi lại, chưa sửa:** giá Shopee lúc đọc được lúc không · audio tiếng Anh bị từ chối khi chủ đề viết bằng tiếng Việt · tab HÀNG ĐỢI / THƯ VIỆN · metadata xuất bản còn đọc writer cũ (để Phase 7).

---

## 12. DB thật

- Hash **`6ece65e24917facb3b46b3ab320796c4`**, không đổi từ 06/10 qua toàn bộ T0 → T1. Chưa đo lại sau khi có code T2. Code T2 chưa có caller nên không thể đã ghi DB, nhưng nên đo lại ở đầu phiên kế tiếp trên máy người dùng.
- Ngày 06/10 lúc 13:33:44 có một tiến trình ngoài lượt làm việc (khả năng cao là app được bật bằng `.bat`, hoặc một agent khác) chạy migration 5.1. Kết quả: thêm bảng `project_storyboards` (0 dòng) cùng index; không gì khác đổi.
- Người dùng đã chốt: **không điều tra thêm, không rollback, không sửa DB.**

---

## 13. Ghi chú kỹ thuật cho Claude ở chat mới

- **Chạy test** (từ `_HE_THONG/app`): `python -m pytest -q -rf -p no:cacheprovider`, khoảng 6–7 phút. Nhóm test liên quan: `tests/test_edit_document.py tests/test_storyboard_lineage.py tests/test_storyboard_gate.py tests/test_storyboard_engine.py` (~40 giây).
- **Không sửa file khi full suite đang chạy.** Test `test_a_freshly_imported_process_is_not_stale` kiểm thời điểm sửa file nguồn. Muốn sửa thì dừng suite trước, sửa xong chạy lại.
- **File trong repo dùng xuống dòng LF.** Sửa bằng script Python thì dùng `read_bytes`/`write_bytes` hoặc `newline="\n"`; `Path.write_text` trên Windows đổi cả file sang CRLF. Sửa xong thì kiểm `count(b"\r\n") == 0`.
- **Không mở DB thật bằng `Database()` hay `import main`** (`initialize()` sẽ migrate). Chỉ đọc bằng `sqlite3` với `mode=ro`, hoặc dùng bản sao.
- Test app dùng `_AppCase` trong `tests/test_storyboard_gate.py` (TestClient + DB tạm). Lưu ý: `resync_timeline_segment_states` đổi `status` của mọi segment, nên so dữ liệu theo trường, không so cả dòng.
- **Kiểm tra cuối mỗi task** (PowerShell): không còn tiến trình `uvicorn`/`pytest`/`youtube_monitor`; `Get-NetTCPConnection -LocalPort 8787 -State Listen` rỗng; `md5sum` DB thật vẫn là `6ece65e2…`.

---

## 14. Bản đồ tài liệu (đọc theo thứ tự này)

| # | File | Vai trò | Còn đúng tới |
|---|---|---|---|
| 1 | `HANDOFF_GPT_BUOC5.md` (file này) | **Trạng thái hiện tại**, Bước 5, quy tắc làm việc | 08/10 |
| 2 | `PROJECT_STATUS.md` | Trạng thái Bước 1–4, gate, an toàn dữ liệu, giới hạn đã biết | 04/10; mục đầu có tóm tắt Bước 5 trỏ về đây |
| 3 | `AI_CONNECTION_HANDOFF.md` | Kiến trúc AI (orchestrator vs worker), MCP, quota, Bước 1–4 chi tiết | 04/10 |
| 4 | `AGENTS.md` | Luật vận hành: không tự chạy app nền | luôn đúng |
| 5 | `AUDIT_HE_THONG.md` | Số liệu đo thật và các lỗi đã sửa (giai đoạn 25–29/09) | **lịch sử**, 29/09 |
| 6 | `KE_HOACH_HOP_NHAT_LUONG.md` | Lý do có "một luồng, `run_step`", nhật ký 25–29/09 | **lịch sử**; nguyên tắc vẫn đúng |
| 7 | `ASTRA_REFACTOR_IMPLEMENTATION_PLAN.md` | Kế hoạch refactor Astra/Orchestrator (tiếng Anh) | **lịch sử**, 20–22/09; đã được các file trên thay thế |
| 8 | `_HE_THONG/tai_lieu/STORYBOARD_EDITOR_CLEANUP_PLAN.md` | Ý tưởng storyboard/UI cũ | **lịch sử**, 12–19/09; thiết kế Bước 5 hiện hành nằm ở file này |
| 9 | `_HE_THONG/tai_lieu/KE_HOACH_DU_AN.md` | Kế hoạch gốc và nhật ký tháng 8 | **lịch sử** |
| — | `HUONG_DAN_SU_DUNG.md` | Hướng dẫn dùng app cho người dùng | — |
| — | `WORK BRIEF.docx` | Brief của người dùng (bản PDF/PNG ở `_tmp_work_brief_review/`) | — |

Khi tài liệu mâu thuẫn nhau: **code + test là nguồn sự thật**, sau đó tới file có ngày mới hơn.
