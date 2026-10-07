# YOUTUBE AI FACTORY — BÀN GIAO SANG CHAT MỚI (Bước 5, tới hết T1)

Cập nhật: 2026-10-07 · Người lập: Claude (Claude Code, làm việc trực tiếp trong repo)

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
- **T1 (EditDocument Engine thuần) đã xong, đang chờ duyệt.**
- Sau khi duyệt, việc kế tiếp là **T2 — lưu trữ EditDocument** (mục 11).

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
- DB thật: `_HE_THONG/data/youtube_monitor.db`. Hash hiện tại **`6ece65e24917facb3b46b3ab320796c4`**, không đổi từ 06/10.
- Git: nhánh `master`, commit gần nhất `98c51d2 feat: complete script engine and Gemini TTS` (Bước 3 + 4). Repo **không có remote**.

Pipeline:

```text
1 Phân tích ✅ → 2 Kế hoạch ✅ → 3 Kịch bản ✅ → 4 Giọng đọc ✅ (đã kiểm với API thật)
→ 5 Storyboard & Edit 🔧 (5.1 ✅ · 5.2 ✅ · 5.3: T0 ✅ T0.5 ✅ T1 ✅ chờ duyệt) → 6 Xưởng dựng → 7 Render & Xuất bản
```

Kiến trúc canonical (đích của Bước 5.3):

```text
ProjectPlan → ScriptDocument → StoryboardDocument ─(lineage)→ EditDocument ─(apply, T3)→ timeline (read model) → giọng / render
```

---

## 2. Thay đổi chưa commit (toàn bộ Bước 5.1 + 5.2 + 5.3 T0/T0.5/T1)

```text
 M _HE_THONG/app/tests/test_production_gate.py
 M _HE_THONG/app/tests/test_script_paths.py
 M _HE_THONG/app/youtube_monitor/database.py
 M _HE_THONG/app/youtube_monitor/main.py
 M _HE_THONG/app/youtube_monitor/production_worker.py
 M _HE_THONG/app/youtube_monitor/shot_planner.py        (chỉ docstring)
 M _HE_THONG/app/youtube_monitor/voice_library.py
?? _HE_THONG/app/youtube_monitor/storyboard_engine.py
?? _HE_THONG/app/youtube_monitor/storyboard_reconcile.py
?? _HE_THONG/app/youtube_monitor/edit_document.py      (T1)
?? _HE_THONG/app/tests/test_storyboard_engine.py       (34 test)
?? _HE_THONG/app/tests/test_storyboard_gate.py         (47 test)
?? _HE_THONG/app/tests/test_storyboard_lineage.py      (28 test)
?? _HE_THONG/app/tests/test_edit_document.py           (25 test)
?? HANDOFF_GPT_BUOC5.md                                 (file này)
```

- Các file `_tmp_*` ở thư mục gốc **không** thuộc commit nào; cố ý để ngoài.
- **Kết quả test mới nhất (sau T1):** 2239 đạt · 2 đỏ cũ · 9 bỏ qua · 230 subtest đạt.

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
T0 ✅ → T0.5 ✅ → T1 ✅ (chờ duyệt) → T2 Lưu trữ → T3 Apply → T4 Nối reconcile (F1)
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

## 10. Yêu cầu bắt buộc cho T2 (đã nêu ở checkpoint)

- Trạng thái "stale" ở T0.5 **không bền**: nó chỉ nằm trong bản ghi reconcile của từng lần, và `get_director_artifact` chỉ đọc bản mới nhất.
- **Khi T2 dựng EditDocument lần đầu cho một timeline đã có lớp dựng** (bootstrap), không được nhận các lớp đó là `ready` một cách mù quáng. Hai cách:
  - gộp lại các bản ghi `storyboard_reconcile` theo `new_segment_id` để tái dựng basis;
  - hoặc đưa vào qua `build(..., legacy=...)`: lớp dựng được giữ thành orphan `legacy` cho người dùng xem lại.
- DB thật hiện có **0 storyboard**, nên chưa dự án thật nào ở trạng thái này.

---

## 11. Việc tiếp theo

1. Người dùng cùng GPT **duyệt T1** (mục 9).
2. Soạn prompt **T2 — Lưu trữ EditDocument**. Gợi ý phạm vi:
   - ghi / đọc EditDocument trong `project_edit_plans.plan_json` (`kind: edit_document`), không migration;
   - quy tắc phiên bản (`based_on` / `document_hash`);
   - đọc lại phải qua `validate()`;
   - bootstrap theo mục 10;
   - chưa apply xuống timeline (T3), chưa đổi reconcile (T4), chưa gate (T7);
   - test chỉ trên DB tạm.
3. Sau đó lần lượt T3 … T9 (mục 6). Mỗi task một báo cáo, chờ duyệt.

**Known limitations còn lại:**
- Job tạo ảnh/video chưa qua Storyboard Gate (để 5.4).
- Edit Plan cũ chưa qua gate (T7).
- UI Bước 5 chưa đổi; nút giọng ở Bước 4 vẫn tự gửi `force` khi nhận `stale` (để 5.4).
- Short ngoài phạm vi.

**Backlog chỉ ghi lại, chưa sửa:** giá Shopee lúc đọc được lúc không · audio tiếng Anh bị từ chối khi chủ đề viết bằng tiếng Việt · tab HÀNG ĐỢI / THƯ VIỆN · metadata xuất bản còn đọc writer cũ (để Phase 7).

---

## 12. DB thật

- Hash **`6ece65e24917facb3b46b3ab320796c4`**, không đổi từ 06/10 qua toàn bộ T0 → T1.
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

## 14. Tài liệu khác trong repo

- `PROJECT_STATUS.md`: trạng thái dự án, cập nhật tới Bước 4. **Chưa ghi Bước 5**; nội dung Bước 5 nằm trong file này.
- `AI_CONNECTION_HANDOFF.md`: lịch sử kết nối AI và các bước trước.
- `AGENTS.md`: quy tắc vận hành (không tự chạy app nền).
