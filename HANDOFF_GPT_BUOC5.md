# YOUTUBE AI FACTORY — BÀN GIAO SANG CHAT MỚI (Bước 5 HOÀN THÀNH: T1 đã duyệt 14/10; T2–T9 xong; T6a `6a5bfb2` + T6b · T7 · T8 · T4-B · T9 `afda241`; full suite 2528 đạt · 2 đỏ nền — tiếp theo: Bước 6 Xưởng dựng)

Cập nhật: 2026-10-14 · Người lập: Claude (Claude Code, làm việc trực tiếp trong repo trên PC Windows)

> **Đây là file vào đầu tiên** cho GPT và cho Claude ở chat mới. Nó mô tả trạng thái **hiện tại** của dự án.
> Thứ tự đọc khuyên dùng và bản đồ tài liệu nằm ở mục 14.
> Bản 07/10 dừng ở T1. Bản 08/10 bổ sung: trạng thái git mới (mục 1–2), **T2 hoàn thành** (mục 9b), **T3 hoàn thành** (mục 9c), **T4 hoàn thành: EditDocument đã nối vào luồng sản xuất** (mục 9d), **T5 hoàn thành: Planner theo storyboard** (mục 9e), **UI Bước 5 nối vào T5/EditDocument** (mục 9f), việc tiếp theo (mục 11).
> **Bản 11/10 bổ sung:** trạng thái git trên PC (mục 1–2), **Storyboard UI bố cục A + form "Sửa cảnh" an toàn** (mục 9g), **P2-4 — sửa tay trước EditDocument: F1 so theo cột, F2 không nhận sửa tay làm legacy, F3 đọc theo timeline hiện tại** (mục 9h), **kết quả test lần đầu trên Windows** (mục 9i), DB thật đo lại (mục 12). Toàn bộ thay đổi 9g–9h **chưa commit, chưa push**.
> **Bản 14/10 (đọc mục 9l trước):** **Bước 5 xong.** Người dùng **chấp thuận T1** trên phiên bản hiện tại (theo bằng chứng: 25/25 test T1, các luồng dùng EditDocument đã kiểm; không phải một vòng review mã nguồn độc lập mới). T4 chốt **phương án B** (chỉ áp bản EditDocument người dùng đã xác nhận). Gate render, T8 và **T9 (kiểm trên trình duyệt bằng DB tạm)** xong, 6 lỗi T9 đã sửa. Toàn bộ suite: **2528 đạt · 2 đỏ (lỗi nền) · 9 bỏ qua**; Node **194/194**. Commit **`afda241`** (24 file) cùng `6a5bfb2` đã push (mục 1–2, 9l, 11).
> **Bản 13/10 (mục 9k):** **T6a** (sửa tay một cảnh qua EditDocument) đã commit `6a5bfb2`, chưa push. **T6b** (gỡ xung đột: giữ timeline / dùng kế hoạch / để sau) và **T7** (khoá mọi đường ghi cũ ở luồng Kế hoạch, đồng bộ job↔nhịp ở tầng DB, `PATCH /plan` nguyên tử, cleanup và loại cảnh của agent đi qua EditDocument) đã xong và test xanh, **chưa commit**. Toàn bộ suite: **2498 đạt · 2 đỏ (lỗi nền) · 9 bỏ qua**. Chưa thử trên trình duyệt.
> **Cập nhật cuối 11/10 (đọc mục 9j trước):** đã review 9g–9h hai vòng. Lỗi Medium F1×F2 (xung đột giả) **đã sửa và đã kiểm chứng** bằng test cùng mutation test. Toàn bộ suite: **2397 đạt · 2 đỏ (lỗi nền) · 9 bỏ qua** (mục 9i). **12/10: đã commit trong `44e110a`; đã push lên `origin/claude/dreamy-gates-4qehd3` cùng commit tài liệu `fbf2e52`** (mục 1–2, 11).

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
- **T1 (EditDocument Engine thuần): người dùng chấp thuận 14/10** trên phiên bản hiện tại (mục 9, 9l).
- **T2 (lưu trữ EditDocument) đã hoàn thành** (mục 9b). Người dùng đã chốt:
  - storage là `project_director_artifacts`, `kind="edit_document"`;
  - bootstrap theo cách (b): lớp dựng cũ thành orphan `legacy`.
- **T3 (Apply EditDocument → timeline) hoàn thành** (mục 9c). Người dùng đã chốt H1–H6, B1–B4.
- **T4 (tích hợp) hoàn thành** (mục 9d): `_sync_storyboard` → `_apply_edit_document` → `edit_store.sync()` → `edit_apply.apply_scenes()` là đường ghi EditDocument → timeline trong luồng sản xuất; reconcile không chép, không `_retime` phần EditDocument sở hữu. Chỉ chạy cho project **đã có** EditDocument.
- **T5 (Planner theo storyboard) hoàn thành** (mục 9e): `run_step("edit_plan")` của project luồng Kế hoạch lập edit cho các cảnh của storyboard hiện hành vào EditDocument (khớp theo `segment_id`), chỉ khi đầu vào current; áp ngay chỉ khi `confirmed_apply`.
- **UI Bước 5 nối vào T5** (mục 9f, 09/10): nút lập/áp kế hoạch dựng của project luồng Kế hoạch gọi `POST …/steps/edit_plan` (áp chỉ khi người dùng xác nhận → `confirmed_apply`), thẻ cảnh đọc `GET …/edit-document` (route mới, chỉ đọc), mọi trạng thái hiển thị đúng lời máy chủ; nút dựng lại storyboard gửi `force` trong body.
- **Storyboard UI bố cục A** (mục 9g, 09–10/10): đầu Bước 5 gọn (một nút primary "Lập kế hoạch dựng", "Áp dụng vào timeline…" luôn hỏi), bộ lọc/tìm cảnh, form "Sửa cảnh" chống lưu dở và chống ghi đè. Ở luồng Kế hoạch, lời đọc chỉ đọc.
- **P2-4 · F1/F2/F3** (mục 9h, 10–11/10): sửa tay (PATCH timeline, `/plan`, `/edit-beats`) không còn bị kế hoạch ghi đè im lặng, và không còn làm kẹt cảnh vô lý. F1 = apply chỉ so các cột nó ghi; F2 = hàng giữ sửa tay không bao giờ được nhận làm mốc legacy mới; F3 = `GET /edit-document` trả đúng điều lần sync kế tiếp sẽ lưu, không ghi gì.
- **Review + sửa sau review** (mục 9j, 11/10):
  - Review vòng 1 tìm ra 1 lỗi Medium (F2 đo cả hàng nên sinh xung đột giả, ngược mục tiêu F1) và 1 lỗi Low (UNVERIFIED).
  - Đã sửa lỗi Medium: hàng bị giữ được ghi nhận theo từng phần (`unknown_parts` → `held_from` → `held_edits` → `sync(kept=)`).
  - Review vòng 2 PASS cả A–D. Có 3 điểm Low: L1 (chú thích) đã sửa; L2, L3 người dùng chốt giữ làm giới hạn đã biết.
  - Đã chạy test: PASS, không regression.
- **T6a · T6b · T7** (mục 9k, 12–13/10): sửa tay một cảnh qua EditDocument (`PUT …/edit-document/scenes/{key}`, commit `6a5bfb2`); gỡ xung đột (`POST …/resolve`); mọi đường ghi cũ vào cảnh của dự án luồng Kế hoạch bị chặn (409) hoặc đi qua EditDocument; tạo job và thay nhịp đồng bộ ở tầng DB; `PATCH /plan` không ghi dở; trim/cleanup không còn bị reset.
- **T4-B · gate render · T8 · T9** (mục 9l, 13–14/10): chỉ áp bản EditDocument đã xác nhận; render bị chặn khi storyboard/kế hoạch/giọng không hợp lệ (nêu lý do); phụ đề, gắn giọng, `visual_prompt` khoá đúng; kiểm trên trình duyệt bằng DB tạm, 6 lỗi tìm được đã sửa. Commit `afda241`.
- **Việc kế tiếp:** Bước 6 — Xưởng dựng. Các giới hạn đã ghi ở cuối mục 9k và 9l là đầu vào để xét khi lập kế hoạch Bước 6.

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
- DB thật: `_HE_THONG/data/youtube_monitor.db` (gitignore, chỉ có trên máy người dùng). Hash **`6ece65e24917facb3b46b3ab320796c4`**, đo lại trên PC ngày **11/10**: không đổi từ 06/10.
- **Git trên PC (11/10):** `F:\YouTube_AI_Factory`, branch `claude/dreamy-gates-4qehd3`, HEAD **`99f4709`** (chore: read-only DB check + launcher DB tạm), trùng với branch trên GitHub. Lịch sử Bước 5 sau `30ca9e1`: `ec62257` (T2) → `1225aef` (T3) → `badba1e` (docs checklist T4) → `4555921` (T4) → `f4c07d6` (T5) → `c944c90` (UI nối T5) → `99f4709`. Thay đổi 9g–9h lúc đó nằm ở working tree, chưa commit.
- **Git trên PC (12/10, sau commit `44e110a`, trước push):** HEAD **`44e110a`** (feat: step 5 storyboard layout A and hand-edit safety before the EditDocument (P2-4 F1/F2/F3)), commit duy nhất chứa toàn bộ 9g–9j. **Chưa push:** `origin/claude/dreamy-gates-4qehd3` vẫn ở `99f4709`, local đi trước 1 commit. Working tree lúc ghi dòng này: `HANDOFF_CHAT_MOI_BUOC5.md` vẫn chưa track (cố ý không commit); ngoài ra bản cập nhật `HANDOFF_GPT_BUOC5.md` này cũng là thay đổi chưa commit lúc đó (được commit riêng ngay sau, commit tài liệu kế tiếp `44e110a`).
- **Git trên PC (14/10):** sau `fbf2e52`: `6a5bfb2` (T6a) → **`afda241`** (feat(step5): T6b, T7, T8, T4-B, T9 — 24 file, +4005 / −209) → commit tài liệu cập nhật file này. Cả ba push thường (không force) lên `origin/claude/dreamy-gates-4qehd3` ngay sau commit tài liệu. Chưa merge vào `main`. `HANDOFF_CHAT_MOI_BUOC5.md` vẫn chưa track (không bao giờ commit).
- **Git trên PC (12/10, sau push):** HEAD **`fbf2e52`** (docs: sync step 5 handoff after commit 44e110a), đi sau `44e110a`. Đã push thường (không force) lên `origin/claude/dreamy-gates-4qehd3`: `99f4709..fbf2e52`; HEAD remote **`fbf2e52`**, trùng local. Chưa merge vào `main`. `HANDOFF_CHAT_MOI_BUOC5.md` vẫn chưa track.
- Git (08/10):
  - Repo **đã có remote** GitHub `HienVuCFDs/YouTube_AI_Factory2`, nhánh chính `main`.
  - Lịch sử: `08c5ed0` (Bước 2) → `98c51d2 feat: complete script engine and Gemini TTS` (Bước 3 + 4) → **`30ca9e1 Initial commit`** (08/10 01:19).
  - `30ca9e1` gom **toàn bộ** thay đổi trước đó còn nằm ngoài git: Bước 5.1, 5.2, T0, T0.5, T1, code T2, file này. Nó gom luôn các file `_tmp_*` ở thư mục gốc, kể cả `_tmp_work_brief_review/pymupdf_deps/` (thư viện pymupdf vendored).
  - Nhánh làm việc của Claude trên cloud: `claude/dreamy-gates-4qehd3`.

Pipeline:

```text
1 Phân tích ✅ → 2 Kế hoạch ✅ → 3 Kịch bản ✅ → 4 Giọng đọc ✅ (đã kiểm với API thật)
→ 5 Storyboard & Edit ✅ (5.1 ✅ · 5.2 ✅ · 5.3: T0 ✅ T0.5 ✅ T1 ✅ duyệt 14/10 · T2 ✅ · T3 ✅ · T4 ✅ (B) · T5 ✅ · T6 ✅ · T7 ✅ · T8 ✅ · T9 ✅ · UI ✅ · Storyboard UI A ✅ · P2-4 ✅ — commit `afda241`, đã push) → 6 Xưởng dựng → 7 Render & Xuất bản
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
 mới  _HE_THONG/app/youtube_monitor/edit_store.py         (T2; caller từ T4: main._apply_edit_document)
 mới  _HE_THONG/app/tests/test_storyboard_engine.py       (34 test)
 mới  _HE_THONG/app/tests/test_storyboard_gate.py         (47 test)
 mới  _HE_THONG/app/tests/test_storyboard_lineage.py      (28 test)
 mới  _HE_THONG/app/tests/test_edit_document.py           (25 test)
 (T2, commit ec62257) _HE_THONG/app/tests/test_edit_store.py (20 test)
 (T3, commit 1225aef) _HE_THONG/app/youtube_monitor/edit_apply.py, _HE_THONG/app/tests/test_edit_apply.py (46 test), database.py (+232 dòng)
 (T4, commit 4555921) _HE_THONG/app/tests/test_edit_integration.py (18 test); sửa main.py, database.py, edit_store.py, edit_document.py; test_edit_apply.py / test_edit_store.py (cô lập test, mục 9d)
 (T5, commit f4c07d6) mới _HE_THONG/app/youtube_monitor/edit_planner.py, _HE_THONG/app/tests/test_edit_planner.py (30 test); sửa main.py, edit_store.py, edit_document.py (mục 9e)
 (UI T5, commit c944c90) sửa main.py (GET /edit-document), static/project-detail.js; mới tests/step5_edit_document_ui.test.cjs (27 test), tests/test_step5_edit_ui.py (12 test) (mục 9f)
 mới  HANDOFF_GPT_BUOC5.md                                (file này)
```

**Commit `44e110a` (12/10, đã push; remote `fbf2e52`) — 15 file** (trước đó, cuối 11/10, là thay đổi chưa commit ở working tree). Số dòng là ước lượng lúc kiểm kê; commit thực tế: 15 file, +3144 / −126:

```text
 sửa  _HE_THONG/app/youtube_monitor/main.py               (~+75) F2 + sửa F1×F2 ở _sync_storyboard/_held_parts/_apply_edit_document/_step_timeline; F3 ở GET /edit-document
 sửa  _HE_THONG/app/youtube_monitor/database.py           (~+79) F1 apply_edit_document_rows(rule=); F2 apply_storyboard_reconcile(held=) + held_from
 sửa  _HE_THONG/app/youtube_monitor/edit_apply.py         (~+238) F1 ScopedCheck, state_edit, known_writes; F2 unknown_rows/unknown_parts/held_edits, ROW_PARTS
 sửa  _HE_THONG/app/youtube_monitor/edit_store.py         (~+60) F3 _next() tách khỏi sync(), preview(); sync(kept=)
 sửa  _HE_THONG/app/youtube_monitor/static/project-detail.js (+742) bố cục A, bộ lọc, form Sửa cảnh, hiển thị F3 (mục 9g)
 sửa  _HE_THONG/app/youtube_monitor/static/app.css        (+121) CSS #studioStep5 / sb-
 sửa  _HE_THONG/app/youtube_monitor/templates/index.html  (+25)  đầu Bước 5, nhãn nút mới, ?v=20261010-storyboard3
 sửa  _HE_THONG/app/tests/step5_edit_document_ui.test.cjs (+26)  F3 (fresh false / null)
 sửa  _HE_THONG/app/tests/test_edit_apply.py              (+23)  F1 (asset check vs state_edit, bản ghi)
 sửa  _HE_THONG/app/tests/test_edit_integration.py        (+61)  F2 (lời đổi + lớp sửa tay → retime nhưng không nhận làm legacy)
 sửa  _HE_THONG/app/tests/test_step5_edit_ui.py           (+131) chạy 2 file .cjs, SceneSaveContractTests
 sửa  _HE_THONG/app/tests/test_workflow_ui.py             (+6)   ghim nhãn nút mới
 mới  _HE_THONG/app/tests/step5_storyboard_layout.test.cjs       42 test Node (bố cục, lọc, form Sửa cảnh)
 mới  _HE_THONG/app/tests/test_edit_manual_conflicts.py          19 test P2-4 (mục 9h; 7a/7b từ mục 9j)
 sửa  HANDOFF_GPT_BUOC5.md                                       file này
 ---  KHÔNG commit (chưa track, theo quyết định của người dùng):
      HANDOFF_CHAT_MOI_BUOC5.md                                  bàn giao gói đồng bộ cloud → PC (09/10), chỉ có trên PC
```

**Commit `6a5bfb2` (12/10, push 14/10) — T6a, 5 file:** `main.py` (route `PUT …/edit-document/scenes/{scene_key}` + sửa lost update), `static/project-detail.js`, `tests/test_edit_manual_document.py`, `tests/step5_edit_document_ui.test.cjs`, `tests/test_step5_edit_ui.py`.

**Commit `afda241` (14/10, đã push) — T6b · T7 · gate render · T8 · T4-B · T9, 24 file** (mục 9k, 9l; danh sách dưới là bản kiểm kê 13/10, bổ sung các file của 13–14/10 ở cuối):

```text
 sửa  _HE_THONG/app/youtube_monitor/main.py              T6b resolve; T7 guard, helper qua EditDocument, cleanup, batch, agent
 sửa  _HE_THONG/app/youtube_monitor/database.py          T6b cờ rewrite; T7 SceneJobConflict, BEGIN IMMEDIATE ở 3 hàm, save_segment_plan
 sửa  _HE_THONG/app/youtube_monitor/edit_apply.py        T6b 5A, accept, preview_conflicts, parts_hold
 sửa  _HE_THONG/app/youtube_monitor/production_worker.py T7 hook set_edit_document_owner (autocover)
 sửa  _HE_THONG/app/youtube_monitor/static/project-detail.js  T6b 3 nút xung đột
 sửa  _HE_THONG/app/youtube_monitor/static/core.js       T7 báo cảnh chưa che
 sửa  _HE_THONG/app/youtube_monitor/static/studio-lanes.js    T7 cleanupNotAppliedText
 sửa  _HE_THONG/app/tests/step5_edit_document_ui.test.cjs     T6b
 sửa  _HE_THONG/app/tests/test_edit_manual_conflicts.py       helper _outside()
 sửa  _HE_THONG/app/tests/test_edit_manual_document.py        theo T7a
 mới  _HE_THONG/app/tests/test_edit_conflict_resolution.py    29 test (T6b)
 mới  _HE_THONG/app/tests/test_legacy_timeline_writes.py      24 test (T7a/b/c, PATCH nguyên tử)
 mới  _HE_THONG/app/tests/test_beat_job_race.py               12 test (race hai luồng)
 mới  _HE_THONG/app/tests/test_plan_mode_writers.py           21 test (cleanup, batch, agent, autocover, cảnh legacy)
 mới  _HE_THONG/app/tests/step5_cleanups_ui.test.cjs          3 test Node
 --- thêm 13–14/10 (gate render, T8, T4-B, T9):
 sửa  _HE_THONG/app/youtube_monitor/static/app.css           nút dựng bị chặn: con trỏ not-allowed
 sửa  _HE_THONG/app/youtube_monitor/templates/index.html     ?v=20261014-buoc5-t9e
 sửa  _HE_THONG/app/tests/test_edit_integration.py           luồng B (lập → xem → xác nhận)
 sửa  _HE_THONG/app/tests/test_edit_planner.py               luồng B
 sửa  _HE_THONG/app/tests/test_step5_edit_ui.py              luồng B
 sửa  _HE_THONG/app/tests/test_step1_ui.py                   cắt mã từ selectStudioVideoNow (T9)
 mới  _HE_THONG/app/tests/test_render_gate.py                19 test (gate render, T8)
 mới  _HE_THONG/app/tests/test_edit_confirmation.py          T4-B, cảnh stale (T9)
 mới  _HE_THONG/app/tests/step5_t9_browser_fixes.test.cjs    10 test Node (lỗi T9)
 ---  KHÔNG commit: HANDOFF_GPT_BUOC5.md (commit tài liệu riêng), HANDOFF_CHAT_MOI_BUOC5.md (chưa track)
```

Ghi chú: trên PC `core.autocrlf=true`, nên một số file ở working tree là CRLF, số khác là LF (mỗi file đồng nhất, không lẫn). Git chuẩn hoá về LF khi commit, nên đây không phải lỗi.

- Các file `_tmp_*` ở thư mục gốc là của người dùng, nhưng **đã lọt vào `30ca9e1`**: `_tmp_inspect_project56.py`, `_tmp_schema.py`, `_tmp_project56_*.json`, `_tmp_review_project56/` (ảnh contact sheet), `_tmp_work_brief_review/` (PDF/PNG của WORK BRIEF + thư viện `pymupdf_deps/`). Có gỡ khỏi git hay không là quyết định của người dùng. Claude không tự xoá.
- **Kết quả test mới nhất (14/10, PC, trước commit `afda241`):** 2528 đạt · 2 đỏ nền · 9 bỏ qua · 257 subtest đạt; Node 194/194 (mục 9l). Lần đo sau T1 (07/10): 2239 đạt · 2 đỏ cũ · 9 bỏ qua · 230 subtest đạt. Kết quả T2 (Linux, 08/10) ở mục 9b.
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
T0 ✅ → T0.5 ✅ → T1 ✅ (chờ duyệt) → T2 Lưu trữ ✅ → T3 Apply ✅ → T4 Nối reconcile ✅ (F1)
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
  - **Đã thực hiện ở T4 (mục 9d), theo ownership chứ không gỡ toàn bộ:** reconcile thôi chép và thôi `_retime` các cột/beats mà EditDocument đã áp (`edit_apply`). Với hàng chưa từng được áp (legacy) reconcile vẫn chép và retime như cũ - đó là lớp legacy, không phải edit của EditDocument. Không có hàng nào mà cả hai cùng ghi cột edit đã sở hữu.

---

## 9. T1 — EditDocument Engine thuần (xong, NGƯỜI DÙNG CHẤP THUẬN 14/10)

> **14/10:** người dùng chấp thuận T1 **trên phiên bản hiện tại** của `edit_document.py` (đã đổi thêm ở T2 +4 dòng, T4 `refreshed=`, T5 `plan_scenes`; các thay đổi này được báo là không đổi luật cốt lõi). Căn cứ: 25/25 test T1 đạt, các luồng dùng EditDocument đã kiểm (tự động và trên trình duyệt ở T9), full suite 14/10 không có lỗi liên quan T1. Đây là **quyết định nghiệm thu theo bằng chứng**, không phải một vòng review mã nguồn độc lập mới.

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
- Phép retime đang có ở hai nơi: `edit_document.retimed` (bản chuẩn) và `Database._retime` (lớp tạm T0.5). Từ T4, `Database._retime` chỉ còn chạy trên nội dung legacy (hàng chưa được EditDocument áp); edit đã áp chỉ được retime qua `effective_edit`.
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

Lúc T2 chưa có caller nào gọi `edit_store` (đúng phạm vi T2). Từ T4, `main._apply_edit_document` gọi `sync()` (mục 9d).

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
4. **T3/T6 — `sync()` tự ghi khi được gọi.** Từ T4 caller là `_apply_edit_document`, sau mỗi `_sync_storyboard` của project đã có EditDocument (mục 9d); T6 sẽ thêm caller cho sửa tay / AI.
5. **Chống race chỉ trong SQLite.** `BEGIN IMMEDIATE` chặn được nhiều tiến trình cùng DB. Phần sửa `_held` (trường hợp `fits` đổi mà audio không đổi) chưa có test riêng.

---

## 9c. T3 — Apply EditDocument → timeline (HOÀN THÀNH 08/10: đã sửa B1–B4, qua final review, đã commit; caller nối ở T4, mục 9d)

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
| `youtube_monitor/edit_apply.py` (mới) | `state_hash`, `row_writes` (H2/H5), `plan` (H3, legacy theo `segment_id`), `apply_scenes` (bắt buộc document `CURRENT` và theo kịp timeline/giọng hiện tại). Lúc T3 không module nào import nó (H4); từ T4 `main._apply_edit_document` gọi `apply_scenes` |
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

1. **T4 (đã xử lý ở mục 9d):**
   - Hàng mang sang kịch bản mới (reconcile chép hình) luôn là `conflict` (`expected_from: default`), vì chưa có lượt áp nào và chưa có orphan nào cho `segment_id` mới. Cố ý an toàn.
   - Tương tự, reconcile tại chỗ `_retime` layer → hàng lệch `state_hash` → `conflict`.
   - T4 phải nối `apply_scenes` vào sau reconcile, đồng thời gỡ việc chép cột edit và `_retime`.
2. **T4/T6:** ~~chưa có caller~~ — T4 đã nối caller (mục 9d). T6 vẫn phải nối sửa tay / AI từng cảnh vào EditDocument.
3. **H5:** T3 không gọi `resync_timeline_segment_states`, nên cột `status` có thể chưa phản ánh hình mới cho tới lần resync kế tiếp (reconcile, job…). Caller ở T4/T6 cần quyết định có gọi hay không.
4. **T6:**
   - Khi EditDocument sở hữu hình (H2), mọi cột visual không có trong edit (kể cả `visual_prompt`, `source_start_seconds`) trở về default.
   - Edit không nêu beats thì không bao giờ xoá được beats của hàng (cố ý, B1). Muốn bỏ beats cần một thao tác rõ ràng ở T6.
   - Khi thay beats, id beat đổi. Beat có job trỏ vào thì không bao giờ bị thay (B2), nên một hàng có beat từng được gửi job sẽ luôn `beat_has_jobs` cho tới khi T6 có cách xử lý (ví dụ cập nhật beat tại chỗ).
5. **T7:**
   - `state_hash` đọc theo `edit_store.timeline_edit`: `asset_type` chỉ được tính khi hàng có `visual_path`. Đổi riêng `asset_type` trên hàng không có hình thì không bị phát hiện.
   - Bốn đường Edit Plan cũ vẫn ghi được timeline. T3 chỉ **phát hiện** (conflict), không chặn.
   - Job cấp cảnh (không có `edit_beat_id`) ở trạng thái `error`/`cancelled` vẫn retry được và ghi đè `visual_path` của cảnh. Đây là hành vi cũ, không do T3 gây ra; T3 chỉ chặn job **chưa xong** (`scene_job_running`), và lần áp sau sẽ phát hiện thành conflict.
7. **T4 (caller) / T7 (gate)** — T4 đã xử lý phần caller, xem mục 9d; khoảng hở còn lại ghi ở đó:
   - Kiểm `CURRENT` và "theo kịp" (`_fresh`) chạy **trước** transaction; cột giọng không nằm trong `state_hash`, nên một reconcile chen vào giữa không bị phát hiện.
   - `storyboard_row` do caller truyền không được kiểm là storyboard mới nhất (giống T2 `sync()`).
   - T4 đã thêm caller: điều kiện storyboard hiện hành được caller kiểm; khoảng hở thời điểm của `_fresh` còn lại, ghi ở mục 9d.
6. **T6:** dọn orphan.

---

## 9d. T4 — Tích hợp EditDocument vào luồng sản xuất (HOÀN THÀNH 08/10)

T3 không đổi (H1–H6, B1–B4 giữ nguyên). T4 làm đúng checklist 11a.

### Audit (code thực tế)

- **Mọi cửa vào** cảnh của dự án luồng Kế hoạch đều đi qua `main._sync_storyboard`: `/shots/generate`, `/timeline/generate` (`_storyboard_timeline`), `run_step("shots")`, `run_step("timeline")` (kể cả nhánh agent gửi `segments`), `/scripts/import`. MCP và UI gọi các route này. Không có worker nào gọi reconcile.
- Reconcile (`Database.apply_storyboard_reconcile`, một transaction riêng) **chép mọi cột không thuộc danh tính/giọng** sang hàng mới khi mang sang kịch bản mới, chép beats, và `_retime` / `_retime_beats` overlays, sound cues, beats khi một hàng mất giọng (tại chỗ hoặc mang sang).
- `edit_store.sync()` (T2) và `apply_edit_document_rows()` (T3) mỗi hàm một transaction riêng; trước T4 không có caller.
- Đường ghi edit khác trong **cùng luồng**: nhánh agent của `_step_timeline` ghi `visual_prompt` / `asset_type` ngay sau reconcile. Các đường Edit Plan cũ (mục 5) là luồng khác (T7).
- **Lệch với mục 8 / 11a:** mục 8 nói "gỡ" việc reconcile chép cột edit và `_retime`. Gỡ toàn bộ sẽ làm mất hình legacy khi mang sang kịch bản mới và làm render dừng vì overlay legacy vượt độ dài cảnh (lý do T0.5 thêm `_retime`). T4 gỡ **theo ownership** (dưới đây), đúng với yêu cầu T4: reconcile không chép hay `_retime` cột thuộc EditDocument, dữ liệu legacy giữ ở lớp legacy.

### Quyết định kiến trúc

1. **Transaction: A — các transaction riêng, chạy tuần tự** `reconcile → edit_store.sync() → apply_scenes()`. **Không atomic.**
   - Thay đổi chen giữa được phát hiện thế nào:
     - `apply_scenes` kiểm lại `CURRENT` và `_fresh` (segment + giọng) ngay khi bắt đầu, rồi trong transaction của nó kiểm expected-state từng hàng;
     - mọi thay đổi cột sở hữu hoặc beats của một hàng (bất kể ai ghi) → `conflict`, không ghi.
   - Khoảng hở còn lại:
     - (a) giọng đổi giữa lúc `_fresh` kiểm và lúc `BEGIN IMMEDIATE` (cột giọng không nằm trong `state_hash`) → edit được ghi theo độ dài giọng cũ;
     - (b) một hàng **mà reconcile vừa ghi nội dung legacy** bị đường khác ghi chen giữa reconcile và `sync()` → nội dung đó được ghi nhận là legacy.
   - Reconcile đã commit thì không rollback theo `sync()` / `apply`. Lỗi hệ thống trong apply rollback **riêng lượt apply** rồi ném lên (route trả 500).
   - Phương án B (dùng chung một connection) cần đổi chữ ký 3 hàm ở 3 task đã duyệt; không chọn.
2. **Ownership:** một hàng do EditDocument sở hữu ⇔ có bản ghi `edit_apply` cho hàng đó (lượt mới nhất).
   - Cột sở hữu = `columns_written`; beats sở hữu ⇔ `beats_written` khác `null`.
   - Bản ghi cũ không có các khoá này → coi là sở hữu toàn bộ.
   - Hàm: `Database._edit_owned` / `edit_owned_rows`.
3. **Một đường ghi:** EditDocument → `apply_scenes()` → timeline là đường duy nhất ghi edit **đã sở hữu**. Reconcile chỉ ghi phần legacy. Agent `segments` chỉ ghi hàng chưa sở hữu.

### Thay đổi

| File | Nội dung |
|---|---|
| `main.py` | `_apply_edit_document(project_id, script, *, refresh)` = caller sản xuất duy nhất. Gọi ở cuối `_sync_storyboard` (cả nhánh không reconcile lẫn nhánh có reconcile; không chạy khi reconcile trả `stale`). `_storyboard_timeline` trả thêm `edit_document`. Nhánh agent của `_step_timeline`: reconcile với `apply_edits=False`, bỏ qua hàng đã sở hữu (`edit_owned_rows_kept`), rồi mới apply |
| `database.py` | `_edit_owned` / `edit_owned_rows`. `apply_storyboard_reconcile`: tại chỗ, hàng sở hữu **không** `_retime` (cả layer lẫn beats); mang sang, **không chép** cột sở hữu và beats sở hữu, chỉ retime phần legacy. Bản ghi reconcile có thêm `touched_segments` (hàng reconcile vừa ghi nội dung legacy) và `edit_owned` từng cảnh |
| `edit_store.py` | `sync(..., refresh=)`: với hàng trong `refresh`, ghi nhận nội dung hiện có thành orphan `legacy` của chính hàng đó (để apply biết, không phải conflict). Có `refresh` thì luôn lưu phiên bản mới |
| `edit_document.py` | `build(..., refreshed=)`: thêm orphan `legacy` cho các hàng đó, **không** đụng edit, basis, lineage của cảnh; được phép khi đã có document trước (khác `legacy`). Không đổi luật nào của T1 |

**`_apply_edit_document`** — chỉ chạy khi project đã có EditDocument (`no_document` nếu chưa; project cũ giữ nguyên, không tạo document). Thứ tự:
1. Storyboard phải là bản `current` của Storyboard Gate, của đúng script này, và là storyboard mới nhất của script → nếu không: `not_current`, không ghi.
2. `edit_store.sync(refresh)`.
3. `apply_scenes()`.
4. Có hàng được áp → `resync_timeline_segment_states`.

Trạng thái trả về:
- `applied` / `unchanged` / `nothing_to_apply`: không có cảnh nào cần người xử lý.
- `partial` (có cảnh ghi được) / `blocked` (không cảnh nào ghi được): khi có conflict hoặc skip cần xử lý (`invalid_edit`, `beat_has_jobs`, `scene_job_running`, `unknown_asset`, `missing_row`). **Không bao giờ báo thành công.**
- `not_current` / `error` (`EditStoreError`, document hỏng) / `no_document`.
- Kèm `counts` và danh sách từng cảnh.

### Test

- **`tests/test_edit_integration.py` (mới, 18 test):**
  - caller của `timeline/generate`, `shots/generate`, `run_step`;
  - project không có document thì giữ nguyên;
  - idempotent (không phiên bản hay bản ghi mới);
  - storyboard không `current` / script cũ → `not_current`;
  - document hỏng → `error`;
  - cảnh sở hữu bị đổi lời → không retime, không ghi, skip `stale`;
  - cảnh legacy đổi lời → retime như cũ **và** được ghi nhận, sau đó lập và áp được;
  - mang sang kịch bản mới: hình sở hữu do apply ghi, hình legacy được chép, không conflict; cột và beats sở hữu không bị chép;
  - `partial` / `blocked`; `invalid_edit` → `partial`;
  - lỗi hệ thống → rollback lượt apply và ném lên;
  - agent không ghi hàng sở hữu;
  - một luồng ghi hàng sở hữu đúng một lần, không có writer legacy.
- **Đổi test cũ (cô lập, không nới guard):**
  - `test_edit_store.py::…carries_the_edit_over…` và `test_edit_apply.py::…carried_over_row_is_never_wiped…`: tắt caller T4 đúng tại bước revision, để tiếp tục kiểm thư viện T2/T3 khi đứng riêng (giả định "chưa có caller"). Hành vi tích hợp được test ở file mới.
  - `test_edit_apply.py::_ApplyCase`: chặn worker tạo cảnh nền (nó quét job `queued` mỗi 2 giây) nhặt job do test tạo. Đã tái hiện bằng probe 3 giây trễ: worker chạy job `dry_run` lỗi làm đổi beat, test nhận conflict thay vì `beat_has_jobs`. Đây là lỗi cô lập của test T3 bộc lộ khi máy tải nặng; guard T3 không đổi.
- **Mutation: 13/13 đột biến T4 bị bắt:**
  - reconcile chép cột sở hữu;
  - retime hàng sở hữu tại chỗ;
  - chép beats sở hữu;
  - không ghi nhận hàng mang sang;
  - không ghi nhận hàng retime;
  - `sync` bỏ `refresh`;
  - engine bỏ `refreshed`;
  - caller chạy cả khi không có document (54 test đỏ);
  - caller bỏ gate;
  - agent ghi hàng sở hữu;
  - `partial` báo thành công;
  - không đếm conflict;
  - không gọi caller sau reconcile.
- **Kết quả (08/10, Linux, DB tạm):**
  - T4: 18/18;
  - Bước 5 (T1–T4 + storyboard): **218/218**;
  - full suite **2310 đạt · 11 đỏ · 13 bỏ qua**, 11 đỏ giống hệt trước T3/T4 (2 cũ + 9 môi trường) → **không regression**.
  - Một lần chạy full suite song song với smoke test có thêm 1 đỏ (race worker nói trên); đã sửa và chạy lại sạch.
- **Smoke test app thật** (uvicorn cổng 8787, DB tạm `scratchpad/smoke/smoke.db` — `/api/health` xác nhận; seed bằng model giả, không gọi API):
  - `POST /api/projects/1/timeline/generate` lần 1 → `edit_document.status = applied` (1 áp, 9 `needs_plan`), hàng 1 nhận hình và overlay của EditDocument, 9 hàng khác giữ hình legacy;
  - lần 2 → `unchanged`, không bản ghi mới;
  - đã tắt app, không còn tiến trình uvicorn, cổng 8787 trống.
  - Không chạy trên DB thật (không có trong môi trường cloud).

### Rủi ro còn lại

1. **Không atomic** (chiến lược A): khoảng hở (a), (b) ở trên.
2. **Hàng sở hữu có cảnh stale sau khi đổi lời:**
   - không retime, nên overlay cũ có thể vượt độ dài mới và render dừng với lỗi rõ ràng, cho tới khi cảnh được lập lại (T6) hoặc gate chặn render (T7);
   - beats legacy trên hàng sở hữu cũng không được retime;
   - mang sang kịch bản mới: hình sở hữu của cảnh stale **không** được chép, apply cũng bỏ qua cảnh stale, nên hàng mới chưa có hình cho tới khi lập lại.
3. **Ghi nhận legacy (`refresh`)** chỉ áp cho hàng reconcile hay agent vừa ghi. Mọi đường khác ghi vào hàng đã biết (Edit Plan cũ, job, sửa tay) vẫn là conflict (T7 chặn).
4. **Caller chỉ chạy qua `_sync_storyboard`:** job giọng (`production_worker`) đổi giọng mà không gọi sync/apply, nên document chưa theo kịp cho tới lần sync kế tiếp; apply sẽ từ chối (`_fresh`) nếu bị gọi lúc đó.
5. **Bản ghi `edit_apply` hỏng** làm reconcile (đọc ownership) dừng với lỗi: chặt, không đọc thành "không sở hữu".
6. ~~Chưa có gì tạo edit trong sản xuất~~ — từ T5, `run_step("edit_plan")` lập edit vào EditDocument (mục 9e). Sửa tay / AI từng cảnh vẫn chờ T6.
7. Chưa chạy trên DB thật; số liệu Windows chưa đo lại.

---

## 9e. T5 — Planner theo Storyboard (HOÀN THÀNH 08/10)

T1–T4 không đổi luật: guard T3 (`apply_scenes`) và ownership T4 giữ nguyên; không dùng `candidate`; không ghi `project_edit_plans`; không xoá orphan; không render, ffmpeg, T6, T7.

### Luồng

```text
run_step("edit_plan")  (project luồng Kế hoạch; luồng khác giữ Edit Plan cũ)
  → _plan_edit_document
      1. gate = _storyboard_gate(with_voice=True): phải CURRENT, row = storyboard mới nhất của script hiện hành
         (script_engine.current_script)                         → nếu không: "not_current", không tạo document
      2. gate.voice_outdated > 0                                → "needs_rebuild", không tạo document
      3. edit_store.sync()  (bootstrap / follow / carried_over / unchanged — T2)
      4. edit_planner.select(): cảnh needs_plan hoặc stale (có hàng timeline); cảnh ready / visual_review giữ nguyên
         trừ khi replan + scene_keys; scene_key lạ → HTTP 422
      5. MỘT lần gọi model (_EDIT_DOCUMENT_PLAN_SCHEMA: khoá theo segment_id) — chỉ các cảnh cần lập
      6. chuẩn hoá như Edit Plan cũ (_normalise_visual_transform_fields, _scene_plan_to_edit_beats, sound cues, mark nguồn);
         overlay qua script_engine.text_errors ("chữ trên màn hình"); khớp câu trả lời theo segment_id
      7. edit_store.plan_scenes() → edit_document.plan_scenes(): MỘT phiên bản mới (expected_parent), based_on = bản trước
      8. confirmed_apply và status ≠ blocked → T4 _apply_edit_document (reconcile → sync → apply_scenes)
```

### Thay đổi

| File | Nội dung |
|---|---|
| `edit_planner.py` (mới) | Phần thuần: `select`, `overlays_through`, `scene_edit` (cột giống Edit Plan cũ, **không** `visual_path`), `outcome`, hằng trạng thái, `PlannerError` |
| `edit_document.py` | `plan_scenes(document, storyboard, edits)`: lập nhiều cảnh trong một bản; cảnh lỗi (không có, timing stale khi chấp nhận, không vừa cảnh) được nêu tên, cảnh khác vẫn lập; không cảnh nào lập được → trả nguyên document. `plan_scene` gọi lại `plan_scenes` (giữ nguyên hành vi, 25 test T1 xanh) |
| `edit_store.py` | `plan_scenes(...)`: đòi `current()` = CURRENT, lưu **một** phiên bản với `expected_parent`; không lập được gì → không lưu (`created` False) |
| `main.py` | `_step_edit_plan` định tuyến luồng Kế hoạch sang `_plan_edit_document`; `_EDIT_DOCUMENT_PLAN_SCHEMA`; `_edit_document_answers` (gọi model, dùng lại chuẩn hoá cũ); `_overlay_text_check`; `_measured_source_marks`; `_edit_document_planned` → `_steps_done` coi `edit_plan` xong khi EditDocument current không còn cảnh cần lập |

### Trạng thái trả về (không bao giờ báo thành công giả)

- `planned`: mọi cảnh được yêu cầu đều đã lập. `unchanged`: không cảnh nào cần lập (chạy lại cùng đầu vào → không gọi model, không phiên bản mới).
- `partial`: có cảnh lập được, có cảnh không (model bỏ sót, kế hoạch không chuẩn hoá được, không vừa cảnh) — `problems` nêu từng `scene_key`, cảnh đó giữ `needs_plan`.
- `blocked`: không cảnh nào lập được; không lưu phiên bản; không apply kể cả khi `confirmed_apply`.
- `error`: model lỗi (`LlmError` — **không** có template thay thế) hoặc `EditStoreError`; không ghi gì.
- `not_current` / `needs_rebuild` / `not_applicable` (project không thuộc luồng Kế hoạch, chỉ khi gọi trực tiếp).
- Kèm `wanted`, `left` (cảnh bỏ qua và lý do `holding` / `no_row`), `planned`, `warnings` (overlay bị loại, sound cue bị bỏ), `document_hash`, `applied` (khi `confirmed_apply`).

### Versioning

- Lần đầu: bootstrap (T2) + một bản đã lập. Chạy lại cùng đầu vào: `unchanged`, không phiên bản mới.
- Storyboard đổi: `sync` đi theo (cảnh giữ nguyên giữ edit theo lineage; cảnh đổi lời → `stale_content`; cảnh mới → `needs_plan`), planner chỉ lập các cảnh đó, một phiên bản mới.
- Thêm / bớt / đổi chỗ cảnh: theo `segment_id` + lineage T1; cảnh bị bỏ → orphan `removed`, không chuyển sang hàng khác; đổi chỗ → `unchanged`, edit giữ nguyên.
- Cùng `segment_id`, đổi độ dài: không lập lại; `effective_edit` retime (`timing.state = retimed`).
- Script đổi (revision mới chưa cắt storyboard) hoặc storyboard stale: `not_current`, document cũ không bị coi là current.

### Test (`tests/test_edit_planner.py`, 30 test, model giả)

Phủ 15 yêu cầu: storyboard current → document; idempotent; storyboard stale; script stale (revision mới); giọng stale → `needs_rebuild`; storyboard đổi phiên bản (một cảnh đổi lời); thêm cảnh; bớt cảnh; đổi chỗ; cùng `segment_id` đổi độ dài; cảnh đã sở hữu (không retime/chép bởi reconcile, lập lại rồi áp không conflict); document cũ có provenance không còn current (không lập, không áp; `plan_scenes` trên bản outdated bị từ chối); `partial` / `blocked` / `error` không báo thành công; project không có EditDocument → T4 `no_document`; document hợp lệ → T4 apply, giữ hình legacy. Thêm: khớp theo `segment_id` khi model trả ngược thứ tự; câu trả lời cho hàng lạ bị bỏ; overlay trượt `text_errors` bị loại; edit không vừa cảnh; gate trả row không phải storyboard mới nhất → `not_current`; scene_key lạ → 422; luồng ngoài Kế hoạch dùng Edit Plan cũ.

- **Mutation: 17/18 đột biến bị bắt** (bỏ gate CURRENT; bỏ kiểm row/script mới nhất; bỏ `voice_outdated`; khớp theo vị trí; `select` lập lại cảnh `ready`; bỏ lọc overlay; `partial` → `planned`; bỏ `blocked`; apply khi không xác nhận; apply khi `blocked`; bỏ `based_on`; `_steps_done` bỏ kiểm cảnh còn cần lập; edit có `visual_path`; `plan_scenes` bỏ kiểm CURRENT; cảnh thiếu câu trả lời được điền mặc định; `LlmError` thành kết quả rỗng; cảnh không vừa không báo lỗi). Đột biến sống: bỏ nhánh "không lưu khi không lập được gì" trong `edit_store.plan_scenes` — tương đương, vì `save` dùng lại bản cùng hash (`created` False).
- **Kết quả (08/10, Linux, DB tạm):** T5 **30/30**; Bước 5 **248/248**; full suite **2340 đạt · 11 đỏ · 13 bỏ qua**, 11 đỏ giống hệt danh sách trước T3/T4/T5 (2 cũ + 9 môi trường) → **không regression**.
- **Smoke test app thật** (uvicorn 8787, DB tạm `scratchpad/smoke_t5/data/smoke.db`; seed bằng model giả: project A lập 10 cảnh qua `POST /steps/edit_plan`, project B sửa kịch bản tại chỗ):
  - A `POST /api/projects/1/steps/edit_plan` → `unchanged`, không gọi model, vẫn 2 phiên bản, 0 `edit_apply`;
  - A với `confirmed_apply` → `unchanged` + T4 `applied` 10 cảnh, giữ hình legacy, `edit_transition`/overlay của EditDocument; lần nữa → T4 `unchanged`;
  - B → `not_current`, 0 document; `/steps`: A có `edit_plan`, B không;
  - log app không có traceback; đã tắt app (pid uvicorn), không còn tiến trình uvicorn, cổng 8787 trống. Không chạy trên DB thật.

### Rủi ro còn lại

1. **T4 tự áp edit đã lập ở lần `_sync_storyboard` kế tiếp**, kể cả khi `run_step("edit_plan")` không có `confirmed_apply`: theo thiết kế T4 đã duyệt, project đã có EditDocument thì mọi `shots/generate`, `timeline/generate`, `run_step("shots"|"timeline")` đều apply các cảnh `ready`. `confirmed_apply` chỉ quyết định có áp **ngay** hay không. Nếu cần "chỉ áp khi người dùng xác nhận" thật sự, phải đổi T4 (cần GPT/người dùng quyết; T5 không tự đổi).
2. **Edit Plan cũ vẫn chạy được trên project luồng Kế hoạch** qua route riêng `POST /api/projects/{id}/edit-plan` (và approve/apply cũ): nó ghi thẳng timeline, ngoài EditDocument → T4 thấy conflict ở hàng đã sở hữu. Chặn là việc của T7. `_steps_done` vẫn coi `edit_plan` xong nếu có Edit Plan cũ đã duyệt.
3. **Cảnh không có hàng timeline** (`no_row`) không được lập; cảnh `visual_review` (orphan legacy) không lập lại trừ khi `replan` — người dùng phải xem lại (T6).
4. Giọng đổi sau khi gate kiểm (`voice_outdated`) mà chưa sync: document lập theo độ dài giọng cũ; T4 `_fresh` sẽ từ chối apply. Không atomic (chiến lược A của T4).
5. Overlay bị loại vì `text_errors` chỉ được ghi trong `warnings`, cảnh vẫn `planned` (không có overlay đó).
6. Chưa chạy trên DB thật; chưa đo trên Windows; model thật chưa được gọi (mọi test và smoke dùng model giả).

---

## 9f. UI Bước 5 nối vào T5 / EditDocument (HOÀN THÀNH 09/10)

Audit UI (08/10) xác nhận 3 lỗi: (1) nút lập kế hoạch gọi Edit Plan cũ `POST /api/projects/{id}/edit-plan` (và `edit-beats/plan` từng cảnh) thay vì T5; (2) thẻ cảnh chỉ đọc `edit_beats` nên cảnh đã lập/đã áp vẫn hiện "Kế hoạch dựng: chưa lập"; (3) "Dựng lại storyboard từ kịch bản" gửi `?force=true` trên URL trong khi route đọc `force` trong body. Đã sửa cả 3. Không đổi guard T3, ownership/freshness T4, không thêm đường ghi timeline.

### Thay đổi

| File | Nội dung |
|---|---|
| `main.py` | Route mới **`GET /api/projects/{id}/edit-document`** — chỉ đọc (`_storyboard_gate`, `edit_store.current`, bản ghi `edit_apply`; không `sync`, không lưu, không apply). 404 nếu không có dự án. Trả `mode` (plan/reup/legacy), `gate`, `state` (`current`/`outdated`/`missing`/`not_applicable`/`error`), `counts`, và từng cảnh `{scene_key, segment_id, status, statuses, timing, applied}`; `applied` = `applied` (bản ghi apply mới nhất của hàng có đúng `layer_hash` của edit hiện tại) / `older` (hàng giữ edit cũ hơn) / `not_applied` / `null` (cảnh chưa lập hoặc cũ). Bản ghi apply hỏng → `state: error` kèm lý do, không đọc thành "chưa áp". Import thêm `edit_document`, `StoredEditApplyError` |
| `static/project-detail.js` | Khối mới `// ---- Bước 5 · EditDocument ----`: đọc `/edit-document` sau mỗi lần vẽ storyboard (lượt đọc mới nhất thắng, đúng project); `studioEditFlow()` = `plan`/`legacy`/không rõ. Project luồng Kế hoạch: "1. Lập kế hoạch dựng" và "Lập kế hoạch" → `POST …/steps/edit_plan {options:{}}`; "2. Áp dụng kế hoạch dựng" và "Duyệt và áp dụng" → hỏi xác nhận rồi `{options:{confirmed_apply:true}}`; nút từng cảnh → `{scene_keys:[key], replan:true}`. Không đọc được trạng thái → không lập gì (kể cả kiểu cũ). Project ngoài luồng Kế hoạch giữ nguyên Edit Plan cũ / edit-beats. Thẻ cảnh hiện trạng thái EditDocument (đã lập · đã áp / chưa áp / timeline còn bản cũ; chưa lập; cũ: lời/chữ/thời lượng; cần xem lại hình; document thuộc storyboard trước; chưa có EditDocument). Ô trạng thái: số cảnh đã lập/đã áp/chưa lập/cũ, cảnh báo gate không current, và câu nói rõ T4 sẽ tự áp ở lần dựng lại storyboard/timeline kế tiếp. `rebuildStoryboardFromScript` gửi `{force: true}` trong body |

### Hiển thị kết quả (không coi HTTP 200 là thành công)

- Lập: `planned` → thành công (+ "Chưa áp vào timeline…" + cảnh báo T4 tự áp); `unchanged` → trung tính; `partial` (nêu cảnh chưa lập và lý do), `blocked`, `not_current`, `needs_rebuild`, `error` (lời của model/máy chủ), `not_applicable`, trạng thái lạ hoặc rỗng → lỗi.
- Áp (`result.applied` của T4): `applied`/`unchanged`/`nothing_to_apply` → được; `partial`/`blocked` (số xung đột, số bỏ qua), `not_current`, `no_document`, `error`, thiếu kết quả áp khi đã yêu cầu áp, trạng thái lạ → lỗi.
- Request lỗi (409/422/500) → lỗi bằng chính thông điệp máy chủ. Bấm lần hai khi đang chạy → không gửi thêm.

### Hành vi áp (đo thật, không đổi)

- Lập không xác nhận: không áp (0 `edit_apply`, cột edit trên timeline không đổi).
- **T4 tự áp các cảnh đã lập ở lần đồng bộ storyboard kế tiếp.** Caller của `_apply_edit_document` (audit 09/10): `_sync_storyboard` (gọi từ `POST /shots/generate`, `POST /timeline/generate` qua `_storyboard_timeline`, `run_step("shots")`, `run_step("timeline")`, `POST /api/scripts/import`); nhánh agent của `_step_timeline`; T5 `_plan_edit_document` khi `confirmed_apply`. Trên UI các nút gây đồng bộ: "Tạo lại storyboard"/"Dựng lại storyboard từ kịch bản", "Chia cảnh & tạo giọng đọc" (Bước 4), tạo storyboard ở thư viện. UI nói rõ điều này; **semantics không đổi**.
- Lưu ý khi đổi: hàng đã sở hữu **chỉ được retime nhờ T4 áp lại** (reconcile không retime hàng sở hữu, mục 9d) — tắt hẳn tự áp sẽ làm overlay/beat của hàng sở hữu lệch độ dài giọng mới.
- **Phương án đề xuất (chưa làm, cần GPT/người dùng chọn):**
  - **A. Lần áp đầu cần xác nhận, áp lại tự động:** T4 khi đồng bộ chỉ áp cảnh mà hàng đã có bản ghi `edit_apply` (đã sở hữu); cảnh chưa từng áp chờ `confirmed_apply`. Đơn giản, giữ retime. Hở: cảnh đã sở hữu được *lập lại* (`older`) vẫn tự áp.
  - **B. Đồng ý theo phiên bản:** lưu một artifact `edit_apply_consent` (document_hash + layer_hash từng cảnh người dùng đã duyệt); T4 chỉ áp cảnh có layer đã duyệt, hoặc khác layer đã duyệt chỉ do retime (`effective_edit` từ cùng basis). Chặt nhất, cần thêm 1 kind artifact và test T4.
  - **C. Giữ như hiện tại** (đã nói rõ trên UI).
  - *(11/10: vẫn chưa chọn.)*

### Test

- `tests/step5_edit_document_ui.test.cjs` (mới, **27** test, chạy khối JS thật trong `vm` với máy chủ giả lập): một POST tới `steps/edit_plan`, không `confirmed_apply` khi lập; hai nút áp gửi `confirmed_apply` chỉ sau xác nhận; từ chối xác nhận → không gửi gì; nút từng cảnh `scene_keys`+`replan`; không bao giờ gọi `/edit-plan` hay `/edit-beats` với project luồng Kế hoạch; không đọc được trạng thái → không lập gì; project legacy giữ edit-beats; 9 trạng thái lập + 6 trạng thái áp hiển thị đúng; lỗi request; bấm hai lần; thẻ cảnh theo EditDocument (overlay không làm cảnh "đã lập", thiếu beats không làm cảnh "chưa lập"); document của project khác không vẽ lên project này; nút dựng lại gửi `{force:true}` trong body, không query.
- `tests/test_step5_edit_ui.py` (mới, **12** test + chạy file `.cjs`): `GET /edit-document` 404 / missing (không bootstrap) / planned→not_applied→applied / `older` sau lập lại / `needs_plan` → `applied: null` / cảnh đổi lời không còn "đã lập" / legacy `not_applicable` / bản ghi apply hỏng → `error`; đọc không ghi gì; lập không xác nhận không đổi timeline, `timeline/generate` kế tiếp T4 áp đúng từng hàng theo `segment_id`; `force` trong body tới `_sync_storyboard`/`_storyboard_timeline`, trong query thì không; hình dạng kết quả step mà UI đọc.
- **Mutation 18/18 bị bắt** (13 JS: luôn `confirmed_apply`, lập về Edit Plan cũ ×2, `partial`/trạng thái lạ thành công, `force` về query, thẻ cảnh về legacy, bỏ nhãn đã áp, không rõ flow → legacy, bỏ kiểm project, áp không hỏi, áp `partial` thành công, bỏ `replan`; 5 Python: luôn `applied`, đọc mà `sync`, nuốt bản ghi hỏng, legacy có document, cảnh chưa lập có `applied`).
- **Kết quả (09/10, Linux, DB tạm):** UI mới 27/27 + 12/12; test UI cũ (`test_workflow_ui`, `test_ui_modules`, `test_step1..3_ui`, …) 129/129 và mọi `.cjs` xanh; Bước 5 **260/260**; full suite **2352 đạt · 11 đỏ · 13 bỏ qua**, 11 đỏ giống hệt baseline (2 cũ + 9 môi trường) → không regression.
- **Smoke app thật + Chromium** (uvicorn 8787, DB tạm `scratchpad/smoke_ui2/data/smoke.db` — `/api/health` xác nhận; seed bằng model giả):
  - A (đã lập, chưa áp): 10 thẻ "đã lập · chưa áp vào timeline", ô trạng thái "10/10 đã lập · 0 đã áp" + cảnh báo T4; bấm "2. Áp dụng" → `POST …/steps/edit_plan {"options":{"confirmed_apply":true}}` → "Đã áp 10 cảnh vào timeline", thẻ đổi "đã áp vào timeline"; bấm "1. Lập kế hoạch dựng" và "Lập kế hoạch" → `{"options":{}}` → "Không có cảnh nào cần lập" (trung tính); "Dựng lại storyboard" → `shots/generate {"force":true}`, `timeline/generate {"force":true}`.
  - B (kịch bản sửa tại chỗ): "chưa có EditDocument" + cảnh báo gate `stale`; bấm lập → lỗi `not_current` đúng lời máy chủ.
  - C (chưa lập, **không có model**): lỗi `error` với lời máy chủ (không AI nào chạy được), thẻ vẫn "chưa lập".
  - Không request nào tới `/edit-plan` hay `/edit-beats`.
  - **Sự cố trong smoke (đã xử lý):** lần chạy C đầu tiên, app tự tìm thấy `claude` CLI có sẵn trong container cloud (`settings._detect_claude_code_cli` → `shutil.which("claude")`) và gọi nó làm model thật (`claude -p … --dangerously-skip-permissions`). Đã kill tiến trình đó sau ~20 giây và tắt app; chạy lại C với `PATH` không có CLI model. **Bài học: smoke trên máy có Claude Code/Codex CLI phải bỏ chúng khỏi `PATH` của app (hoặc đặt cấu hình provider) nếu không muốn gọi model thật.**
  - Đã tắt app, không còn uvicorn/chromium/`claude -p`, cổng 8787 trống. Không chạy trên PC Windows (phiên cloud không truy cập được máy người dùng), không dùng DB thật.

### Rủi ro còn lại

1. T4 tự áp ở lần đồng bộ kế tiếp (trên) — chờ chọn A/B/C.
2. Thẻ cảnh của project luồng Kế hoạch vẫn có trình sửa nhịp dựng cũ ("Lưu kế hoạch cảnh", "Áp dụng cảnh này" → `PUT/POST /api/timeline/{id}/edit-beats…`) và sửa chữ động/SFX (`PATCH /api/timeline/{id}/plan`): ghi thẳng timeline ngoài EditDocument → T4 báo xung đột ở hàng đã sở hữu (UI hiện `partial`/`blocked`). Nối các thao tác sửa tay vào EditDocument là **T6**; chặn đường ghi cũ là **T7**. Route `/edit-plan` cũ vẫn mở cho MCP/agent (không qua UI).
3. "2. Áp dụng kế hoạch dựng" với `confirmed_apply` cũng **lập luôn** các cảnh chưa lập/cũ rồi áp (đúng semantics T5); hộp xác nhận nói rõ.
4. Nút "Chia cảnh & tạo giọng đọc" (Bước 4) vẫn tự `force` khi máy chủ báo storyboard `stale` — hành vi có từ trước, có chủ đích, không đổi.
5. Chưa chạy trên Windows/DB thật; ảnh/sóng âm trong smoke lỗi vì file giả của seed (không phải lỗi app).
6. *(11/10)* Rủi ro 2 (sửa tay ghi thẳng timeline → conflict) được giảm phần lớn ở P2-4 (mục 9h): sửa tay ở cột kế hoạch không ghi thì không còn conflict; sửa tay ở cột kế hoạch ghi thì vẫn là conflict nhưng không bao giờ bị ghi đè. Nối sửa tay vào EditDocument vẫn là T6.

---

## 9g. Storyboard UI bố cục A + form "Sửa cảnh" (09–10/10, đã commit `44e110a` và đã push ngày 12/10)

Làm trên cloud (09/10), đồng bộ sang PC bằng gói `buoc5_sync` (chi tiết đồng bộ và hash từng file: `HANDOFF_CHAT_MOI_BUOC5.md`; file này không có trong git, chỉ có trên PC), rồi sửa tiếp trên PC. Chỉ đổi UI. Không đổi API, schema, guard T3/T4. Luồng legacy giữ nguyên.

### Bố cục (index.html, app.css, project-detail.js)

- **Đầu Bước 5** (`.sb-head`): tiêu đề, một nút primary **"Lập kế hoạch dựng"** (chưa ghi timeline), một nút thường **"Áp dụng vào timeline…"** (luôn hỏi xác nhận), và ô trạng thái `#studioEditPlanState`. Chi tiết kỹ thuật để trong tooltip.
- Công cụ ít dùng (tạo ảnh/video AI, cắt clip, che logo, chọn model ảnh phụ, Edit Plan đồ hoạ cũ) gom vào `<details class="sb-tools">`. Edit Plan đồ hoạ cũ đổi nhãn rõ: "Kế hoạch đồ hoạ tổng thể (Edit Plan cũ)".
- **Bảng cảnh** (`renderStudioSceneBoard`): mỗi cảnh một hàng gồm timecode, lời, hình, trạng thái giọng/hình và chip kế hoạch (`studioScenePlanChip`); thêm dải thời gian (`storyboardStripBlock`), chọn cảnh, và di chuyển bằng phím (`stepStudioScene`).
- **Lọc/tìm** (`setStudioStoryboardView`, `applyStudioStoryboardFilters`, `clearStudioStoryboardFilters`): thiếu hình / thiếu giọng / cả hai / nháp / fallback; theo trạng thái kế hoạch (so đúng trạng thái hàng giữ); tìm theo số cảnh hoặc chữ trong lời/hình. Mỗi trạng thái EditDocument giữ tên riêng: stale, review, older, applied, planned, not planned.
- Đã kiểm trên cloud bằng Chromium headless với route giả (không server, không DB): không tràn ngang ở 1440/1280/1024/768/390px. **Chưa thử trên Windows/Edge ở tỉ lệ 125–150%.**

### Form "Sửa cảnh" (`storyboardSceneEditForm`, `saveStudioSceneEdit`)

Dựa trên hợp đồng API có sẵn, không đổi gì: trường không gửi thì giữ nguyên; `audio_path: ''` là cách duy nhất để bỏ giọng; `duration_seconds` là số nguyên 1–3600. Hai request tuần tự: `PATCH /api/shots/{id}` rồi `PATCH /api/timeline/{segmentId}`.

- **Luồng Kế hoạch:** ô lời đọc **chỉ đọc**, ghi rõ chỗ sửa lời là Bước 3, không có cảnh báo giọng. Khi lưu, form không bao giờ gửi lời và không bao giờ bỏ giọng, dù trường đang chứa gì. Chỉ đổi lời thì coi như không đổi gì. Ngoài luồng Kế hoạch, và khi chưa rõ luồng, lời vẫn sửa được như cũ.
- **Giữ giọng:** chỉ đổi hình hoặc độ dài thì không hỏi, không gửi `audio_path`, không gửi lời. Gõ lại cùng lời, chỉ khác khoảng trắng, không tính là đổi lời. Đổi lời thì cảnh báo ngay, hỏi trước khi lưu, rồi bỏ giọng đúng theo hợp đồng (lời mới luôn đi kèm `audio_path: ''`).
- **Chống ghi đè:** trước mỗi lần lưu, form đọc lại cảnh từ máy chủ; không đọc được thì không gửi gì. Trường nào đã bị sửa ở nơi khác kể từ lúc mở form thì không ghi đè: dừng lưu và hiện các hàng mới hơn. Có giọng mới tạo trong lúc đang sửa thì đổi lời không làm mất giọng đó: dừng lưu. Trường đã đúng như muốn trên máy chủ thì không gửi lại.
- **Lưu dở:** shot đã lưu mà timeline bị từ chối → báo rõ phần nào đã lưu, hiện các hàng máy chủ trả về, giữ form, và lần thử lại chỉ gửi timeline. Mất phản hồi hoặc lỗi 5xx → trạng thái **"unknown"**: không gửi lại mù. Lần thử lại đọc máy chủ: thấy đã ghi thì không gửi gì, chưa ghi thì chỉ gửi phần đó. Shot bị mất phản hồi → dừng trước bước timeline, và không gọi là "chưa lưu". Đóng form sau lưu dở thì không bao giờ báo "cảnh không đổi".
- **Nháp:** điều đang gõ được giữ khi trang vẽ lại (job cảnh xong, đổi sắp xếp, xoá lọc), và khi lưu thì gửi đúng điều đã gõ. Chuyển cảnh khi còn thay đổi chưa lưu → hỏi trước. Huỷ → quay về cảnh như cũ, không gửi gì.
- Không còn trên storyboard dài → dùng hộp thoại cũ. Cảnh đã bị xoá trên máy chủ → không lưu.

### Rủi ro còn lại (9g)

1. Hai request không atomic: lưu dở vẫn xảy ra được, nhưng nay được báo đúng và thử lại an toàn.
2. Form "Sửa cảnh" và trình sửa nhịp dựng cũ vẫn ghi thẳng timeline, ngoài EditDocument (T6/T7). Từ P2-4 (9h), việc này không còn bị kế hoạch ghi đè.
3. Chưa chạy app thật trên PC, chưa thử Edge/DPI cao.

---

## 9h. P2-4 — Sửa tay trước EditDocument: F1 · F2 · F3 (10–11/10, đã commit `44e110a` và đã push ngày 12/10)

**Vấn đề (giai đoạn 1 = chốt hành vi bằng test, `tests/test_edit_manual_conflicts.py`):** sửa tay một cảnh (PATCH `/api/timeline/{id}`, `/plan`, `/edit-beats`) ghi thẳng timeline. Trước P2-4 có hai lỗi ngược chiều nhau:
- **(a) Kẹt vô lý:** apply so **cả hàng** với điều EditDocument biết lần cuối. Chỉ sửa `visual_prompt` (cột kế hoạch không bao giờ ghi) cũng làm cảnh thành `conflict` vĩnh viễn.
- **(b) Ghi đè im lặng:** khi reconcile (kịch bản mới, đổi lời) hoặc timeline của agent chạm vào hàng đang giữ sửa tay, `refresh` (T4) nhận nội dung đó làm mốc `legacy` mới. Lần apply sau "thấy đúng như mong đợi" nên ghi kế hoạch đè lên sửa tay, **không có conflict**.

### F1 — Apply chỉ so các cột nó ghi (`edit_apply.ScopedCheck`, `database.apply_edit_document_rows(rule=)`)

- `verdict()` (đọc trong transaction của apply): conflict ⇔ một cột **mà lần apply này ghi** (cột trong `updates`, cộng `beats` khi edit nêu beats) khác điều EditDocument biết lần cuối (`base`). Cột không ghi (`visual_prompt`, beats khi kế hoạch không nêu beats…) được phép giữ sửa tay, apply để nguyên.
- `base` lấy theo thứ tự: `state_edit` của bản ghi apply mới nhất → (bản ghi trước F1) dựng lại từng cột từ edit đã ghi (`known_writes`: `layer_hash` → trạng thái edit đó ghi), **chỉ khi** `state_hash` của bản ghi chứng minh được; nếu không thì so **cả hàng** như trước F1 (`columns: ["*"]`) → orphan `legacy` cùng `segment_id` → edit rỗng.
- Mỗi hàng trong bản ghi `edit_apply` có thêm **`state_edit`** = `base` với **chỉ các cột vừa ghi** được thay (`settle()`). Sửa tay ở cột không ghi **không bao giờ** được ghi vào `state_edit`: về sau, một edit có ghi cột đó vẫn thấy sửa tay và dừng.
- Conflict có thêm `columns` (các cột lệch). Format cũ giữ nguyên, chỉ thêm khoá. Gọi không có `rule` thì hành vi như cũ (so cả hàng).
- Sửa tên biến: biến tập asset trong apply đổi thành `found_assets`, để không trùng với `known` (điều document biết). Có test riêng (`test_a_beat_naming_an_asset_of_this_project_is_applied_and_recorded_as_known`).

### F2 — Hàng giữ sửa tay không bao giờ thành mốc legacy mới (`edit_apply.unknown_rows`)

- `unknown_rows(database, project_id, script_id, segments)`, chỉ đọc: trả các hàng đang giữ điều EditDocument **chưa từng biết**. So với cùng mốc mà apply dùng: `state_edit`/`state_hash` của apply mới nhất → orphan legacy cùng `segment_id` → edit rỗng.
  - Script chưa có EditDocument → không hàng nào (luồng legacy giữ nguyên).
  - Không đọc được điều document biết → **mọi hàng** đều bị coi là unknown (an toàn).
- `main._sync_storyboard`: tính `held` **trước** reconcile và truyền vào `apply_storyboard_reconcile(held=)`. Nội dung của các hàng này vẫn được mang sang và retime như cũ, nhưng hàng đích ghi vào **`held_segments`**, không vào `touched_segments` (nên không vào `refresh`).
- `main._step_timeline` (nhánh agent): agent vẫn ghi `visual_prompt`/`asset_type` vào hàng chưa sở hữu, nhưng hàng trong `held` không được thêm vào `refresh`.
- Kết quả: sửa tay trên hàng chưa áp luôn được giữ nguyên và báo conflict, dù đi qua đường nào: không reconcile, kịch bản mới (kể cả lần T4 tự áp khi tạo lại storyboard), đổi lời cảnh, hay timeline của agent.

### F3 — `GET /edit-document` đọc theo timeline hiện tại (`edit_store.preview`)

- Vấn đề: document đã lưu ghi lại timeline và giọng **lúc lưu**. Sau khi đổi độ dài hoặc giọng một cảnh, route vẫn trả `current` với timing/trạng thái/`applied` cũ, trong khi lần sync kế tiếp sẽ retime hoặc đánh dấu cảnh.
- `edit_store._next()` tách phần "dựng document kế tiếp" ra khỏi `sync()` (hành vi `sync()` không đổi). `preview()` dùng `_next()` để dựng, **không lưu**: `{fresh, document, document_hash}`.
- Route trả thêm: `fresh` (`true`: bản lưu vẫn đúng; `false`: các cảnh được trả **theo bản sync sẽ lưu**, `document_hash` là hash bản đó, `stored_document_hash` là bản đang lưu; `null` + `fresh_detail`: không tính được, trả bản đang lưu kèm lý do). Route vẫn chỉ đọc.
- UI (`editDocumentFreshNote`): `fresh: false` → nói rõ "máy chủ tính theo timeline hiện tại"; `fresh: null` → nêu lý do; `fresh: true` → không thêm gì.

### Test P2-4

- `tests/test_edit_manual_conflicts.py` (**mới, 17 test**, DB tạm, model giả `test_edit_planner.Director`):
  - 1, 2, 2b — `visual_prompt` sửa tay trước/sau khi áp: giữ nguyên, cảnh vẫn áp/lập lại được; bản ghi nhớ mô tả cũ, không nhận mô tả tay;
  - 3 — kế hoạch AI không nêu `visual_prompt`/`visual_path`, apply không ghi hai cột đó và không ghi `project_shots`;
  - 3b/3c — lớp kế hoạch ghi bị sửa tay → conflict, giữ nguyên; beats tay mà kế hoạch không ghi → không conflict;
  - 4a–4d — lớp sửa tay trên hàng chưa áp: conflict và giữ nguyên khi không reconcile / kịch bản mới / đổi lời / timeline agent;
  - 5, 5b, 5c — F3: sau khi đổi độ dài, đọc trả `retimed`, cảnh `older`, `fresh: false`, không ghi DB; độ dài không theo được → `stale_timing`; không tính được → bản lưu + lý do;
  - 6, 6a–6c — reflow (đổi độ dài làm đổi start/end mọi hàng) không gây conflict giả; bản ghi trước F1: đọc lại được từng cột thì gỡ kẹt, không đọc được thì so cả hàng.
- `test_edit_integration.py`: test cũ "cảnh legacy đổi lời được retime **và nhận làm legacy**" đổi thành hai ca: lớp document **chưa từng biết** → retime nhưng không nhận (`test_a_reworded_scene_with_layers_the_document_never_knew_…`, `test_layers_the_document_never_knew_are_a_conflict_after_a_reword_…`); lớp legacy **đã có từ khi document bắt đầu** (orphan bootstrap) → vẫn retime và nhận như cũ (`KnownLegacyReconcileTests`).
- `test_edit_apply.py`: thêm ca asset (F1) và kiểm `state_edit` trong bản ghi.
- `step5_edit_document_ui.test.cjs`: thêm 2 test F3 (`fresh: false`, `fresh: null`).
- **Mutation test:** đã làm cho phần sửa F1×F2 (2 đột biến đều bị bắt, mục 9j). Chưa có mutation test riêng cho `ScopedCheck` (F1) và `preview` (F3).

### Rủi ro còn lại (9h)

1. `unknown_rows` đọc **ngoài** transaction của reconcile (chiến lược A của T4: không atomic). Một sửa tay chen vào giữa lúc đọc `held` và lúc reconcile thì không được đánh dấu là held; lần apply sau vẫn dựa vào expected-state (F1) để phát hiện nếu cột đó bị ghi.
2. `known_writes` chỉ dựng lại được bản ghi trước F1 khi edit đã ghi còn trong lịch sử EditDocument của script. Không thì so cả hàng (an toàn nhưng có thể vẫn kẹt).
3. `preview()` dựng lại document ở mỗi lần `GET /edit-document`, nên tốn công hơn trước (đọc file giọng). Chưa đo trên project lớn.
4. Sửa tay ở cột kế hoạch ghi vẫn làm cảnh kẹt `conflict`. Cách gỡ (nhận sửa tay vào EditDocument, hoặc nút "ghi đè") là T6.

### Sửa sau review (11/10/2026, lỗi Medium F1 × F2) — ĐÃ KIỂM CHỨNG

**Lỗi:** F2 đo "chưa biết" theo cả hàng. Chỉ cần sửa tay một cột kế hoạch không ghi (ví dụ `visual_prompt`), cả hàng bị giữ lại; sau reconcile, lớp dựng legacy được chép/retime không được ghi nhận, nên lần áp sau báo xung đột giả.

**Sửa:** ghi nhận hàng bị giữ theo từng phần (`unknown_parts` → `held_from` → `held_edits` → `sync(kept=)`). Phần sửa tay giữ mốc cũ; phần còn lại là đã biết. Chi tiết thiết kế, sơ đồ dữ liệu và bất biến: mục 9j.

**Kết quả kiểm chứng (11/10/2026, Windows, DB tạm của `conftest.py`, `--basetemp` riêng):**

| Nhóm | Kết quả |
|---|---|
| `test_edit_manual_conflicts.py` | **19 passed** |
| `test_edit_integration.py` | **20 passed** |
| Nhóm Bước 5 mở rộng (14 file) | **363 passed**, 6 subtests |
| Node Bước 5 (`step5_*.test.cjs`) | **71/71** |
| Toàn bộ suite | **2397 passed · 2 failed · 9 skipped**, 236 subtests |

- **Hai test đỏ là lỗi nền.** Cả hai cũng đỏ trên bản sạch `99f4709`, cùng assertion:
  - `test_burned_in_marks.py::AutoCoverRespectsWhatIsAlreadyDecided::test_an_unmarked_reup_gets_its_source_measured`: `AssertionError: 0 != 1`
  - `test_shorts.py::RendererFitTests::test_the_renderer_can_fill_a_frame_as_well_as_pad_it`: `AssertionError: 'sound_cues' != 'fit'`
- **Mutation mô phỏng hành vi trước bản sửa** (`_held_parts` trả `{}`): 4b, 7a, 7b thất bại, tái hiện đúng xung đột giả.
- **Mutation phá F2** (phần sửa tay bị coi là đã biết): bị **5 test** bắt (4b, 4c, 7a và 2 test F2 trong `test_edit_integration.py`).
- **Review vòng hai: PASS A–D.** L1 (chú thích nhánh agent trong `main.py`) đã sửa. L2 (khoảng hở giữa hai lần đọc) và L3 (`kept` không được lưu khi sync dừng sớm) giữ nguyên theo quyết định đã duyệt (mục 9j).

---

## 9i. Kết quả test trên Windows (11/10, lần đầu chạy trên PC)

> **Bảng dưới là lần chạy 1, trên bản trước khi sửa F1×F2.** Lần chạy 2, sau khi sửa: **toàn bộ suite 2397 đạt · 2 đỏ (vẫn 2 lỗi nền, cùng assertion) · 9 bỏ qua** + 236 subtests, 9 phút 11 giây, có `--basetemp` nên in đủ tóm tắt. Chi tiết lần 2 ở mục 9j.

Môi trường: Windows 11, Python 3.13.3 hệ thống (không venv), pytest 9.1.1, FastAPI 0.123.5, Node 24.15. DB tạm của `conftest.py`. Biến `YOUTUBE_DB_PATH`/`YOUTUBE_DATA_DIR` không đặt trong shell. Không chạy app, không gọi AI thật.

| Nhóm | Kết quả |
|---|---|
| Node `step5_edit_document_ui.test.cjs` | **29/29** |
| Node `step5_storyboard_layout.test.cjs` | **42/42** |
| `test_edit_manual_conflicts.py` | **17 passed** |
| `test_step5_edit_ui.py` | **22 passed** + 6 subtests |
| `test_edit_apply.py` | **47 passed** |
| `test_edit_integration.py` | **20 passed** |
| `test_workflow_ui.py` | **33 passed** |
| Nhóm Bước 5 (9 file ở mục 13 + `test_edit_manual_conflicts`) | **290 passed**, 6 subtests, 0 đỏ — 147 giây (Linux khoảng 75 giây) |
| Toàn bộ `tests` (2406 test thu thập) | **2395 đạt · 2 đỏ · 9 bỏ qua** — 2 đỏ đều là lỗi nền → **không regression** |

**Hai test đỏ: lỗi nền, có bằng chứng.** Đây đúng là 2 "đỏ cũ" đã biết (mục 0). Chạy lại từng test trên working tree và trên bản sạch `99f4709` (giải nén bằng `git archive` vào thư mục tạm của phiên, không đụng working tree): cả hai bản đều đỏ, cùng assertion.
- `test_burned_in_marks.py::AutoCoverRespectsWhatIsAlreadyDecided::test_an_unmarked_reup_gets_its_source_measured`: `AssertionError: 0 != 1`.
- `test_shorts.py::RendererFitTests::test_the_renderer_can_fill_a_frame_as_well_as_pad_it`: `AssertionError: 'sound_cues' != 'fit'`.

**9 đỏ "môi trường Linux/cloud"** (`test_operations` ×4, `test_voxcpm_readiness` ×2, `test_motion_graphics`, `test_channel_accounts`, `test_publish_gate`) **đều đạt trên Windows** (đạt thật, không nằm trong số bị bỏ qua). Chúng chỉ đỏ trên Linux. 9 test bị bỏ qua là `test_reup_clip_sync` ×4 và `test_workflows::CuttingByDialogueAsksBeforeReplacingTheScriptTests` ×5, đều thuộc Reup "cắt theo lời thoại", không thuộc Bước 5.

**Sự cố của pytest trên Windows (không phải lỗi code):** khi chạy toàn bộ suite với thư mục tạm mặc định, pytest chạy xong mọi test rồi mới sập ở bước dọn dẹp cuối phiên. Lỗi là `PermissionError: [WinError 5] Access is denied: '...\AppData\Local\Temp\pytest-of-ADMIN\pytest-current'`, ở `_pytest/pathlib.cleanup_dead_symlinks`. Vì sập nên không in phần tóm tắt, và exit code là 1. Số liệu trên lấy bằng cách khớp chuỗi tiến độ với `--collect-only` (2395 + 9 + 2 = 2406, khớp đúng), rồi xác nhận lại 2 test đỏ bằng cách chạy riêng. **Từ nay, trên PC luôn thêm `--basetemp=<thư mục tạm riêng>`** (ví dụ thư mục scratchpad của phiên) để tránh lỗi này.

Kiểm cuối (11/10): md5 DB thật vẫn `6ece65e24917facb3b46b3ab320796c4`, không có `-wal`/`-shm`. Cổng 8787 trống. Không còn tiến trình uvicorn/pytest/youtube_monitor. Chưa commit, chưa push, chưa chạy app.

---

## 9j. Review 9g–9h và sửa lỗi F1 × F2 (11/10, đã test; đã commit `44e110a` và đã push ngày 12/10)

### Review vòng 1 (chỉ đọc)

- Storyboard UI A: PASS về logic; UNVERIFIED về hiển thị trên Windows/Edge ở tỉ lệ 125–150%. F1: PASS. F3: PASS.
- F2: PASS về mục tiêu bảo vệ, nhưng có **lỗi Medium**.
  - `unknown_rows` so hash của **cả hàng**. Vì vậy chỉ cần sửa tay một cột kế hoạch không ghi (ví dụ "Mô tả hình" qua form "Sửa cảnh"), cả hàng đã bị giữ lại.
  - Khi đó reconcile (kịch bản mới, hoặc đổi lời tại chỗ có retime) vẫn chép hoặc căn lại lớp dựng legacy, nhưng không ghi nhận phần đó vào EditDocument.
  - Lần áp sau so `overlays`/`sound_cues`/`edit_direction` (ba cột này lần áp nào cũng ghi) với mốc cũ, nên báo xung đột giả. Cảnh bị kẹt cho tới T6. Không mất dữ liệu.
- **Lỗi Low (UNVERIFIED), chưa sửa, để làm task riêng:**
  - Vị trí: nhánh agent `main._step_timeline` gọi `unknown_rows` với kịch bản **hiện tại**.
  - Điều kiện: kịch bản mới chưa có EditDocument riêng, vì lần sync đầu của nó trả `not_current`/`error`.
  - Hậu quả: tập hàng chưa biết rỗng, và hàng agent ghi vào được `refresh` nguyên trạng, kể cả hàng mang sửa tay.

### Sửa lỗi Medium: ghi nhận theo từng phần, không còn theo cả hàng

```text
_sync_storyboard
 ├─ edit_apply.unknown_parts(source)       [đọc lần 1, trước reconcile]
 │    {S: {"known": mốc document biết, "columns": các phần lệch}}
 │    None = chỉ nói được cả hàng (bản ghi trước F1, hoặc không đọc được)
 ├─ database.apply_storyboard_reconcile(held=set(parts))
 │    held_from = [{segment_id (đích), source_segment_id, not_carried}]
 │    not_carried = cột (+ "beats") EditDocument sở hữu trên hàng nguồn, không được chép sang
 ├─ main._held_parts → {đích: {known, columns − not_carried}}   (None → bỏ qua, như trước)
 └─ _apply_edit_document(refresh=touched, held)
      ├─ edit_apply.held_edits             [đọc lần 2, ngay trước sync]
      │    with_parts(hàng hiện tại, known, columns)
      │    = phần chép/retime lấy từ hiện tại, phần sửa tay giữ mốc cũ
      ├─ edit_store.sync(refresh = touched − kept, kept)   (kept thắng refresh)
      │    → thành orphan legacy CUỐI của hàng
      └─ apply_scenes: plan() lấy orphan cuối làm legacy_edit; ScopedCheck (F1, không đổi)
```

- `edit_apply.py`: thêm `ROW_PARTS`, `unknown_parts`, `held_edits`. `unknown_rows` giờ là `set(unknown_parts())`, cho đúng tập hàng như trước.
- `database.py`: thêm hàm nội bộ `landed()` và trường `held_from` trong bản ghi reconcile.
- `edit_store.py`: `sync(kept=)`, `_next(kept=)`.
- `main.py`: `_held_parts`; `_apply_edit_document(held=)`; nhánh agent nhận qua `edit_held`. Khóa này chỉ có khi `apply_edits=False`, nên không lộ ra response HTTP.
- Không đổi schema, API, `ScopedCheck` (F1), hay hành vi tự áp của T4.
- Bất biến (đã review vòng 2):
  - Hàng chỉ vào `touched` hoặc `held`, không bao giờ cả hai.
  - Hàng đã có bản ghi áp dùng `state_edit`, không dùng orphan.
  - Cột sở hữu không được chép sang hàng mới, nên sửa tay ở đó không thành mốc mới.
  - Project chưa có EditDocument, legacy đã bootstrap, bản ghi trước F1: hành vi như cũ.

### Review vòng 2: PASS cả A–D, có 3 điểm Low

- **L1** (chú thích `main.py` ở nhánh agent không còn đúng hết): **đã sửa**, chỉ chú thích.
- **L2** (khoảng hở giữa đọc lần 1 và đọc lần 2, nay áp cả cho hàng bị giữ): **người dùng chốt giữ làm giới hạn đã biết**. Cùng loại với khoảng hở (b) chiến lược A của T4. Không thêm cơ chế khóa.
  - Ví dụ: job tạo ảnh chạy nền xong đúng lúc giữa reconcile và sync → cột hình của hàng bị giữ được coi là đã biết.
- **L3** (`kept` không được lưu lại): **người dùng chốt giữ làm giới hạn đã biết**.
  - Nếu `_apply_edit_document` dừng trước sync (`not_current`/`error`), thông tin hàng bị giữ mất theo. Lần sync sau quay về hành vi trước khi sửa: xung đột giả, nhưng an toàn.
  - `refresh` của T4 cũng mất theo cùng cách.

### Test sau khi sửa (lần chạy 2, Windows, `--basetemp` riêng)

| Nhóm | Kết quả |
|---|---|
| `test_edit_manual_conflicts.py` | **19 passed** (17 + `HandPromptThenReconcileTests` 7a, 7b) |
| `test_edit_integration.py` | **20 passed** |
| Nhóm Bước 5 mở rộng (14 file: 9 file mục 13 + `test_edit_manual_conflicts`, `test_storyboard_voice_recovery`, `test_edit_plan_applied`, `test_edit_cleanups`, `test_workflow_ui`) | **363 passed** + 6 subtests |
| Node `step5_*` | **71/71** |
| **Toàn bộ suite** | **2397 passed · 2 failed · 9 skipped** + 236 subtests; 2 đỏ = `test_burned_in_marks`, `test_shorts`, lỗi nền đã chứng minh trên `99f4709`, cùng assertion |

- **7a** (kịch bản mới, chỉ sửa tay mô tả hình, có lớp legacy): lần tự áp ra `applied`, không xung đột. Mô tả tay giữ nguyên; `edit_transition: cut` và overlay của kế hoạch đã ghi.
- **7b** (đổi lời tại chỗ, có retime): lập lại cảnh rồi áp, không xung đột, mô tả tay giữ nguyên.
- **4b**: kỳ vọng mới `expected_from = "legacy"` đúng với dữ liệu mẫu. Xung đột nằm đúng ở các phần sửa tay: `edit_direction`, `edit_effect`, `edit_note`, `edit_transition`, `overlays`, `sound_cues`.
- **Mutation test** (plugin pytest đặt ngoài repo, không sửa code):
  - Đột biến "trước khi sửa" (`_held_parts` trả `{}`): 4b, 7a, 7b đỏ, tái hiện đúng xung đột giả.
  - Đột biến "phá F2" (coi phần sửa tay là đã biết): 5 test đỏ (4b, 4c, 7a và 2 test F2 trong `test_edit_integration`).
- Kiểm cuối (11/10, trước commit): md5 DB thật vẫn `6ece65e2…`; cổng 8787 trống; không còn tiến trình app/pytest. Lúc đó chưa commit, chưa push, chưa chạy app. Commit `44e110a` tạo ngày 12/10; đã push cùng `fbf2e52` cùng ngày.

---

## 9k. T6a · T6b · T7 — sửa tay qua EditDocument, gỡ xung đột, khoá mọi đường ghi cũ (12–13/10)

Trạng thái (14/10): **T6a commit `6a5bfb2`; T6b, T7 và phần "Cập nhật 13/10 (sau)" ở commit `afda241`; cả hai đã push.** Mọi số liệu dưới đây đo trên PC Windows, DB tạm (`conftest.py`, `--basetemp` riêng). Kiểm trên trình duyệt: mục 9l.

### T6a — sửa tay một cảnh đi qua EditDocument (commit `6a5bfb2`)
- Route mới **`PUT /api/projects/{id}/edit-document/scenes/{scene_key}`** (`EditDocumentSceneRequest`: overlays, sound_cues, direction, transition, effect, note, beats).
- Bản sửa = edit của cảnh như đang chạy + phần được gửi → **một phiên bản EditDocument mới** (`edit_store.save(expected_parent=…)`, `BEGIN IMMEDIATE`) → chỉ áp đúng cảnh đó (`apply_scenes(scene_keys=[key])`). Kết quả theo `_edit_apply_outcome`: chỉ `applied`/`unchanged` là thành công; xung đột là `blocked`, hàng giữ nguyên.
- Từ chối trước khi lưu: dự án ngoài luồng Kế hoạch, storyboard/kịch bản không hiện hành, giọng làm bằng cấu hình cũ (409); cảnh không có (404); phần không chuẩn hoá được / nhịp không khớp thời lượng (422); cảnh có job chưa xong hoặc nhịp có job (409).
- Sau review: sửa HIGH (lost update — hai request cùng đọc một phiên bản, bản sau ghi đè bản trước; giờ cái thứ hai nhận 409) và MEDIUM (UI tải lại trạng thái sau khi lưu). UI luồng Kế hoạch: ẩn "Áp dụng cảnh này", các nút sửa lớp/nhịp gọi route T6a.

### T6b — gỡ cảnh kẹt xung đột (chưa commit)
- Luật **5A**: cột đang giữ đúng giá trị kế hoạch sẽ ghi thì không tính là xung đột.
- `GET …/edit-document`: mỗi cảnh có `conflict` (`columns`, `expected_from`, `state_hash`, `layer_hash`) từ `edit_apply.preview_conflicts` (chỉ đọc). `counts.conflicts` bị bỏ để giữ hợp đồng cũ.
- Route mới **`POST …/edit-document/scenes/{scene_key}/resolve`** (`choice`: `keep_timeline` | `use_plan`, `columns`, `state_hash`, `layer_hash`):
  - `keep_timeline`: EditDocument nhận phần đang có trên hàng (không ghi timeline).
  - `use_plan`: áp kế hoạch với quyết định `accept` gắn chặt vào `state_hash` + `layer_hash`; lệch → 409 `decision_outdated`. Thay đổi tối thiểu ở `database.apply_edit_document_rows`: cờ `rewrite` (mặc định False) để ghi lại một hàng mà lần áp trước đã ghi đúng kế hoạch này. Có hậu kiểm `parts_hold`.
  - Gửi lại → `unchanged` (idempotent).
- UI: cảnh xung đột có 3 nút "Giữ bản trên timeline" · "Dùng kế hoạch…" (hỏi trước, nêu phần bị ghi đè) · "Để sau" (không gọi API). Lỗi/409 thì tải lại trạng thái, không bao giờ tự gửi lại.
- Test: `tests/test_edit_conflict_resolution.py` (29) + Node trong `step5_edit_document_ui.test.cjs`. Trạng thái đã báo: **CLOSED — AUTOMATED TESTS PASS, BROWSER NOT VERIFIED**.

### T7 vòng 1 — các route timeline cũ (chưa commit)
- **T7b — không còn mất trim/cleanup:** `PATCH /api/timeline/{id}/plan` và `POST …/edit-beats/plan` từng gọi `save_segment_edit` với trim = 0 và cleanup = [] mặc định (đo được: 0.4/0.3 → 0/0, logo → []). Giờ hai route **không ghi trim/cleanup**. `/cut` và `timeline/cleanups` vẫn sửa chúng tường minh.
- **T7a — luồng Kế hoạch: route cũ trả 409, không ghi gì.** Định nghĩa duy nhất: `_edit_document_owns_timeline(project_id, script_id)` = `_storyboard_gate` ở `PLAN_MODE` **và** hàng thuộc kịch bản hiện hành. Legacy, Reup và hàng của kịch bản cũ giữ nguyên hành vi. Bị chặn: `PATCH /plan`, `PUT /edit-beats`, `POST /edit-beats/plan`, `/edit-beats/apply`, `/edit-beats/{i}/generate`, `/extract-frame`, `PATCH /edit-plan/scenes/{id}`, `POST /edit-plan/apply` (guard đứng **trước** `_current_project_edit_plan`, vì hàm này tự ghi `stale`). Vẫn mở: GET, `POST /edit-plan`, `approve` (chỉ ghi `project_edit_plans`), `attach-asset` (chỉ `visual_path`/`audio_path`; có test chứng minh không xung đột). MCP và tool agent (`plan_scene_edits`, `apply_scene_edits`) nhận cùng lời từ chối.
- **T7c — job giữ nhịp:** đường cũ còn mở (legacy) không thay/xoá nhịp khi có job trỏ vào nhịp (**mọi trạng thái** — job lỗi/huỷ có thể retry, job xong có thể bị chấm fail rồi retry) hoặc cảnh còn job chưa xong (queued, waiting, running). `edit_beat_id` không bao giờ bị NULL.

### T7 vòng 2 — đồng bộ job/beat ở tầng DB, PATCH nguyên tử (chưa commit)
- **Race job ↔ thay nhịp:** `replace_timeline_edit_beats`, `create_scene_generation_job`, `apply_project_edit_plan_scenes` đều `BEGIN IMMEDIATE` **trước lần đọc đầu tiên** rồi kiểm + ghi trong cùng giao dịch (SQLite WAL chỉ cho một bên giữ khoá ghi; bên sau chờ busy timeout rồi đọc trạng thái đã commit). `SceneJobConflict(reason)`: `scene_job_running`, `beat_has_jobs`, `beat_gone`, `beat_changed`. Tạo job cho nhịp nhận `edit_beat_seen` (nhịp đúng như route đã đọc). Kiểm ở route chỉ để trả lời sớm; quyết định nằm trong giao dịch. `edit-beats/plan` ghi nhịp + cut + layers trong một giao dịch. Worker hoàn tất/retry/huỷ không bị chặn.
- Test `tests/test_beat_job_race.py` (12): hai luồng thật, thứ tự ép bằng Event (không sleep). Luồng 1 dừng ngay trước lần ghi đầu tiên; kết nối thử `timeout=0` nhận "database is locked"; log chứng minh luồng 2 đứng ở khoá trước khi luồng 1 commit. Sau mỗi ca kiểm không có job mồ côi / `edit_beat_id` trỏ sai cảnh.
- **`PATCH /plan` không ghi dở:** trước đó `visual_kind` đã ghi rồi overlay mới bị 422 (5 ca tái hiện). Giờ chuẩn hoá mọi phần trước, ghi bằng **một câu UPDATE** (`Database.segment_plan_updates` + `save_segment_plan`, danh sách cột trắng không có trim/cleanup). 4xx → `_db_state` giống hệt, kể cả `updated_at`.
- `PATCH /cut`: phần trim bị chặn ở luồng Kế hoạch (planner ghi trim); điểm cắt `source_start_seconds` và cắt lại clip vẫn mở.

### T7 vòng 3 — ba đường ghi còn BLOCKED + hai phát hiện (chưa commit)
- **Helper chung `_change_scenes_through_edit_document(project_id, {segment_id: {cột visual: giá trị}})`**: mỗi cảnh nhận thay đổi trên edit đang chạy → một phiên bản mới (`_keep_scene_edits`, dùng `edit_document.plan_scenes`) → áp đúng các cảnh đó theo luật T3/F1/T6b. Cảnh có job chưa xong / nhịp có job, cảnh không nhận được edit: bị loại **trước khi** lưu, có tên trong `not_applied`. Xung đột: không ghi đè, có tên trong `not_applied`.
- **`POST /timeline/cleanups`** (nút Bước 5): luồng Kế hoạch → qua helper; trả `partial`/`blocked` + `not_applied` + `edit_document`; UI báo lỗi và nêu cảnh chưa che (`cleanupNotAppliedText` trong `studio-lanes.js`, dùng ở `core.js`). Ngoài luồng Kế hoạch: ghi thẳng như cũ.
- **`scene-jobs/batch`**: chỉ nhánh `motion_as_gif=true` + `respect_plan=false` đổi `visual_kind`. UI không gửi `motion_as_gif`, MCP không gọi batch, orchestrator dùng `respect_plan=true` → **giữ 409** cho đúng tổ hợp đó ở luồng Kế hoạch. **Chức năng bị hạn chế:** "ép mọi cảnh thành GIF bất chấp kế hoạch" không dùng được cho dự án luồng Kế hoạch.
- **Agent Director/Media**: loại cảnh agent chọn đi qua helper (`_agent_kind`, `_agent_kinds_written`); cảnh không nhận được → `kinds_not_applied`, Media **không tạo job** cho loại hàng không có. Phần dựng lại timeline của Director vốn đã qua storyboard + reconcile.
- **Phát hiện 1 — lỗi có sẵn ở T6a:** sửa một phần trên cảnh `needs_plan` (chỉ có lớp legacy) xoá mất overlay/sound legacy mà vẫn `applied`, không xung đột. Sửa: `_scene_edit_base` dựng trên orphan legacy của hàng, bỏ `visual_path`/`visual_prompt`/`asset_type` (để EditDocument không thành chủ hình).
- **Phát hiện 2 — đường ghi thứ tư:** autocover lúc render (`production_worker._autocover_source_marks`) chạy cho Reup **và** dự án có cảnh dùng clip nguồn, ghi thẳng `edit_cleanups`. Giờ ở luồng Kế hoạch chỉ áp cho lần render đó (trong bộ nhớ), không ghi DB. Hook `production_worker.set_edit_document_owner`, nối từ `main` theo mẫu `set_production_gate`.

### Bảng đường ghi (sau T7)

| Đường | Ghi gì | Luồng Kế hoạch |
|---|---|---|
| `PATCH /api/timeline/{id}` | lời/phụ đề/thời lượng/âm thanh/status, `visual_prompt`, `visual_path`, `asset_type` | Mở (planner không ghi các cột này; lời đọc có khoá riêng) |
| `PATCH /cut` | trim / điểm cắt / file clip | Trim 409; còn lại mở |
| `PATCH /plan`, edit-beats (plan/put/apply/generate/extract), Edit Plan cũ (scenes/apply) | lớp dựng, nhịp | 409 |
| `POST /timeline/cleanups` | `edit_cleanups` | Qua EditDocument |
| autocover render | `edit_cleanups` | Chỉ trong bộ nhớ |
| `scene-jobs/batch` | job; `visual_kind` (nhánh GIF bỏ kế hoạch) | Nhánh đó 409, còn lại mở |
| Agent Director/Media | `visual_kind`, timeline | Qua EditDocument / reconcile |
| tạo/retry/huỷ/reroute job, worker hoàn tất | job, ảnh beat/hàng | Khoá DB; không chặn worker |
| `attach-asset`, `edit-plan/fallback`, voiceover, source-visuals | cột asset/giọng/điểm cắt | Mở |
| `plan-visuals`, `POST /edit-plan`, approve | `project_edit_plans` | Mở |
| `timeline/generate`, `scripts/import`, `director-draft`, `from-dialogue` | dựng timeline | Qua storyboard/reconcile hoặc bị từ chối; Short/Reup tách riêng |

### Test (13/10, Windows, DB tạm)
- File mới: `test_edit_conflict_resolution.py` (29), `test_legacy_timeline_writes.py` (24), `test_beat_job_race.py` (12), `test_plan_mode_writers.py` (21), `step5_cleanups_ui.test.cjs` (3). Sửa: `test_edit_manual_document.py` (T6a), `test_edit_manual_conflicts.py` (helper `_outside()` — mô phỏng sửa ngoài EditDocument phải vượt guard T7a một cách tường minh), `step5_edit_document_ui.test.cjs` (T6b).
- Nhóm liên quan (32 file: T7, T6a/T6b, race, MCP, workflow, reup, agent, render): 720 đạt, 9 bỏ qua. Node: 96/96.
- **Toàn bộ suite: 2498 đạt · 2 đỏ (lỗi nền) · 9 bỏ qua, 255 subtest.** Hai lỗi nền giữ nguyên thông điệp: `test_burned_in_marks…test_an_unmarked_reup_gets_its_source_measured` (`0 != 1`), `test_shorts…test_the_renderer_can_fill_a_frame_as_well_as_pad_it` (`'sound_cues' != 'fit'`).
- Mutation test trên bản sao trong scratchpad (không đụng repo): vòng 1 11/11, vòng 2 15/15 (bỏ khoá ở tạo job / thay nhịp, bỏ kiểm trong giao dịch, bỏ so nhịp, ghi trước khi kiểm, ghi từng cột, reset trim, bỏ guard `/cut`…), vòng 3 11/11 (E1–E11: nền legacy, cột hình, cleanup ghi thẳng, bỏ kiểm job, không nêu xung đột, status, guard batch, agent ghi thẳng, Media tạo job sai, autocover ghi DB, UI không báo). Riêng D2 (bỏ khoá thay nhịp) bị bắt qua timeout an toàn 30s, không qua kết quả.

### Giới hạn còn lại (đã ghi rõ, cần GPT xét)
1. Cảnh có job trỏ vào nhịp (chỉ còn trong dữ liệu trước T7a) không nhận cleanup/loại cảnh qua EditDocument; được báo trong `not_applied`.
2. Lập lại kế hoạch (T5) thay cleanup/loại cảnh người dùng chọn bằng quyết định của planner (vết đo được hoặc AI) — đúng nghĩa "lập lại", nhưng nên xét.
3. T6b `keep_timeline` khi chọn cả hàng (`*`, dữ liệu pre-F1) lấy cả `visual_path` → EditDocument có thể thành chủ hình của hàng; chưa sửa.
4. Autocover luồng Kế hoạch đo lại ở mỗi lần render (không lưu).
5. Chức năng GIF batch bỏ qua kế hoạch không dùng được ở luồng Kế hoạch (409).
6. Chưa thử trên trình duyệt; chưa chạy trên DB thật. T7d (MCP gọi thẳng EditDocument) chưa làm. Phương án T4 tự áp (A/B/C, mục 9f) vẫn chưa chốt.

### Cập nhật 13/10 (sau) — gate render T7 + T8 (commit `afda241`)
- **Gate render** (`main._render_blockers`, `edit_apply.render_blockers`): dự án luồng Kế hoạch, video dài. Hỏi ở route `POST /api/projects/{id}/jobs` (409 `{"code": "render_blocked", "message", "blockers": [{code, detail, next_step, segment_ids}]}`), ở worker khi nhận job và khi retry (`_job_gate_reason`), và ngay trong `run_render_job` trên chính các hàng render vừa đọc (hook `production_worker.set_render_gate`), trước autocover và mọi ghi. `render-readiness` có `render_gate`.
  - A: storyboard hiện hành + timeline khớp lời; EditDocument của storyboard hiện hành; không cảnh nào có lớp dựng `stale_*`; mỗi cảnh đã lập kế hoạch phải giữ đúng điều apply sẽ ghi (`edit_not_applied` / `conflict`). Cảnh `needs_plan` và dự án chưa có EditDocument được render.
  - B: record cạnh file giọng — `voice_outdated` (fingerprint khác cấu hình hiện tại), `voice_words_changed`, `voice_unverified` (không có record: chỉ qua khi người dùng gửi `accept_unverified_voices=true`, lưu theo chữ ký đúng file đó, artifact `render_voice_acceptance`). Đổi cấu hình về như cũ thì giọng cũ hợp lệ lại, không phải tạo lại.
- **T8:** F5 `PATCH /api/timeline/{id}` — phụ đề cảnh luồng Kế hoạch phải đúng lời đọc (khác dấu câu/khoảng trắng được), 409 `SUBTITLE_LOCKED`. F6 `attach-generated-voice` — chỉ nhận giọng có record cùng cấu hình hiện tại. F8 — `visual_prompt` một giá trị: hàng timeline là nơi đọc, shot giữ bản sao, ghi cùng giao dịch (PATCH timeline, PATCH shot, ghi chú ảnh phụ của Edit Plan cũ).
- Test `tests/test_render_gate.py` (19), mutation 17/17. Các file test liên quan (41 file): 876 đạt, 4 bỏ qua; renderer: chỉ 2 lỗi nền. Node 96/96.
- Còn lại: phụ đề Whisper (`subtitle_provider=faster_whisper_local`) vẫn là lời Whisper nghe được, có thể khác lời kịch bản (căn lời kịch bản theo thời gian Whisper là việc riêng); autocover legacy đọc lại timeline không kèm nhịp dựng (lỗi có sẵn, ngoài phạm vi). (Trình duyệt, T1, phương án T4: đã xử lý ở mục 9l.)

## 9l. T4-B · T9 · nghiệm thu Bước 5 (13–14/10, commit `afda241`)

**T4 — phương án B (người dùng chọn):** chỉ áp phiên bản EditDocument người dùng đã xác nhận.
- Artifact `edit_document_confirmation` `{script_id, document_hash, storyboard_hash}` (không đổi schema). `_apply_edit_document(confirmed=)` trả `needs_confirmation` khi bản hiện tại khác bản đã xác nhận; sync, reconcile, dựng lại storyboard, `timeline/generate`, `run_project_step("timeline")` đều **không** tự áp kế hoạch chưa xác nhận.
- "Áp dụng vào timeline…" gửi `confirmed_apply` + `document_hash` của đúng bản đang hiển thị; hash khác → không áp gì. Khi xác nhận, planner **không** lập lại.
- Sửa tay của người (T6a, resolve, cleanup) trên bản đã xác nhận → bản mới vẫn được coi là đã xác nhận (`person=True`). Agent dùng `person=False`: luôn chờ người xác nhận.
- Render gate có mã `edit_not_applied` khi kế hoạch chưa áp.

**T9 — kiểm trên trình duyệt** (DB tạm `%LOCALAPPDATA%\YouTubeAIFactory_THU_NGHIEM_T9_20261013`, model giả, không AI trả phí, không render thật; 0 job được tạo):
- Đã kiểm trên trình duyệt: T4-B (xác nhận đúng hash; đổi phiên bản → chưa xác nhận, không tự áp), T6a (chỉ cảnh được sửa đổi), T6b (3 lựa chọn + Huỷ), gate render (lý do hiện rõ, nút bị chặn có tooltip), F5 (gọi API từ trang: 409/200, lời đọc không đổi), F6 (file không có record bị từ chối, có record thì gắn được), F8 (form "Sửa cảnh" và PATCH chỉ shot đều giữ hàng = shot), cleanup (chờ khi chưa xác nhận → áp sau xác nhận → áp ngay trên bản đã xác nhận; cảnh stale bị bỏ qua).
- Chỉ có test tự động: agent Director/Media đề xuất loại cảnh (UI cần mô hình AI thật); F5 qua form (không có ô sửa phụ đề riêng ở luồng Kế hoạch).
- **Lỗi tìm được và đã sửa (đều có test, mutation xác nhận test bắt được):**
  1. Tạo lại storyboard khi `stale` báo thành công giả → hỏi rồi mới gửi `force`, tải lại EditDocument, báo cần xác nhận.
  2. Race khi đổi nhanh giữa hai dự án trộn dữ liệu → tải dự án tuần tự (`studioLoadChain`, `selectStudioVideoNow`).
  3. Nhãn trợ năng/tooltip của dải timeline giữ trạng thái cũ → cập nhật qua `data-strip-label`.
  4. Nút "2. Dựng video hoàn chỉnh" bị vô hiệu mà không nói lý do → tooltip nêu lý do, con trỏ `not-allowed`; `queueStudioRender` dừng ở gate trước khi lưu cấu hình hay gửi yêu cầu.
  5. Cleanup chờ xác nhận nhưng UI báo "Đang che… / đã che 0 cảnh" → "Chờ xác nhận"; câu chữ: "Bỏ che" nói "cảnh chưa bỏ che được"; thông báo chờ xác nhận nêu "Bỏ qua N cảnh có lớp dựng cũ (Cảnh …): lập lại kế hoạch … trước" (máy chủ thêm `code: "stale_layers"`, `scene_index` vào mục `not_applied`, logic không đổi).
  6. **(nghiêm trọng)** Thay đổi nhiều cảnh (cleanup, agent) làm cảnh `stale_*` thành "hiện hành" mà không ai lập lại kế hoạch → `_change_scenes_through_edit_document` bỏ qua cảnh stale, nêu lý do trong `not_applied`.

**Toàn bộ suite (14/10, PC, working tree ngay trước `afda241`, chạy một lần):** pytest **2528 đạt · 2 trượt · 9 bỏ qua · 257 subtest**, 13 phút 21 giây; Node (10 file) **194/194**. Hai test trượt là lỗi nền, chạy trên bản xuất `git archive` của HEAD `6a5bfb2` cũng trượt y hệt thông điệp: `test_burned_in_marks…test_an_unmarked_reup_gets_its_source_measured` (`0 != 1`), `test_shorts…RendererFitTests…test_the_renderer_can_fill_a_frame_as_well_as_pad_it` (`'sound_cues' != 'fit'`). Không có lỗi mới, không lỗi liên quan T1. 1 cảnh báo `SyntaxWarning` có sẵn ở `test_step1_ui.py:136`.

**Giới hạn còn lại (chưa sửa, ghi để xét ở bước sau):**
- T6a sửa một cảnh stale vẫn đặt basis mới cho chính cảnh đó (đúng nghĩa người sửa cảnh đó, nhưng nên xét).
- Phụ đề Whisper có thể khác lời kịch bản; autocover legacy đọc lại timeline không kèm nhịp (lỗi có sẵn).
- 6 giới hạn cuối mục 9k vẫn giữ nguyên (job trỏ nhịp từ dữ liệu cũ, lập lại kế hoạch thay quyết định người dùng, `keep_timeline` với `*`, autocover đo lại mỗi lần render, GIF batch bỏ kế hoạch bị 409, T7d MCP).
- Chưa chạy trên DB thật. Chưa merge vào `main`.

---

## 10. Yêu cầu bắt buộc cho T2 (đã nêu ở checkpoint)

- Trạng thái "stale" ở T0.5 **không bền**: nó chỉ nằm trong bản ghi reconcile của từng lần, và `get_director_artifact` chỉ đọc bản mới nhất.
- **Khi T2 dựng EditDocument lần đầu cho một timeline đã có lớp dựng** (bootstrap), không được nhận các lớp đó là `ready` một cách mù quáng. Hai cách:
  - gộp lại các bản ghi `storyboard_reconcile` theo `new_segment_id` để tái dựng basis;
  - hoặc đưa vào qua `build(..., legacy=...)`: lớp dựng được giữ thành orphan `legacy` cho người dùng xem lại.
- DB thật hiện có **0 storyboard**, nên chưa dự án thật nào ở trạng thái này.

---

## 11. Việc tiếp theo

1. ~~Duyệt T1~~: **người dùng chấp thuận 14/10** trên phiên bản hiện tại (mục 9).
2. ~~Chốt T2~~: **xong 08/10** (mục 9b). Nên chạy lại full suite trên Windows để xác nhận.
3. ~~T3 — Apply~~: **xong 08/10** (mục 9c), đã commit và push. Nên chạy lại full suite trên Windows.
4. ~~T4 — Nối reconcile~~: **xong 08/10** (mục 9d), theo checklist 11a.
5. ~~T5 — Planner theo storyboard~~: **xong 08/10** (mục 9e). Cần GPT review rủi ro 1 của 9e (T4 tự áp edit đã lập ở lần sync kế tiếp).
6. ~~UI Bước 5 nối T5~~: **xong 09/10** (mục 9f). Chờ quyết phương án "chỉ áp sau xác nhận" (9f).
7. **(11/10) Storyboard UI bố cục A (mục 9g) + P2-4 F1/F2/F3 (mục 9h) + sửa F1×F2 (mục 9j)**: ~~review~~ xong 2 vòng; ~~sửa Medium~~ xong; ~~test~~ xong (2397 đạt, 2 đỏ nền); ~~commit~~ xong: `44e110a` (12/10), đúng 15 file đã duyệt; ~~push~~ xong (remote `fbf2e52`, 12/10). **Còn lại, chờ người dùng quyết:**
   - a. ~~Lệnh commit~~: xong, `44e110a`. `HANDOFF_CHAT_MOI_BUOC5.md` không commit (đã quyết). ~~Push~~: xong ngày 12/10, `99f4709..fbf2e52`, không force. Chưa merge vào `main`.
   - b. Thử app thật trên PC bằng `CHAY_THU_NGHIEM_DB_TAM.bat` (DB tạm) và kiểm hiển thị Edge ở 125–150%: **chưa làm** (đã commit và push mà chưa thử). Theo review 12/10, việc này không bắt buộc trước khi push; nên làm trước khi merge vào `main` hoặc dùng với DB thật.
   - c. Task riêng cho lỗi Low nhánh agent (mục 9j). Chưa làm, vẫn UNVERIFIED.
   - d. (Tùy chọn) mutation test riêng cho F1 `ScopedCheck` và F3 `preview`.
   - e. L2, L3 (mục 9j) đã chốt là giới hạn đã biết, không làm thêm.
8. ~~T6~~ · ~~T7~~ · ~~T8~~ · ~~T4-B~~ · ~~T9~~: **xong 12–14/10**, mục 9k, 9l; commit `6a5bfb2` + `afda241`, đã push 14/10. **Còn lại (không chặn Bước 6):** T7d (MCP gọi thẳng EditDocument); các giới hạn cuối 9k và 9l; merge vào `main` khi người dùng quyết.
8b. **Tiếp theo: Bước 6 — Xưởng dựng.**
9. Việc phụ chờ người dùng quyết: có gỡ các file `_tmp_*` (và `pymupdf_deps/`) khỏi git hay không (mục 2).

### 11a. T4 — Integration checklist bắt buộc (đã thống nhất 08/10)

**Trạng thái: đã thực hiện ở T4, xem mục 9d** (cách giải quyết từng điểm và khoảng hở còn lại). Đây là **contract cho T4**. Nó không thay đổi contract T3 (H1–H6, B1–B4, mục 9c): T3 là thư viện apply độc lập và chưa có caller. Test T3 xanh **không** có nghĩa Bước 5 đã sẵn sàng cho sản xuất; T4 là nơi kiểm chứng caller thật.

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

- Hash **`6ece65e24917facb3b46b3ab320796c4`**, không đổi từ 06/10 (đo lại 13/10 và 14/10 sau full suite, chỉ đọc: vẫn vậy, 6.742.016 byte, không `-wal`/`-shm`). **Đo lại trên PC ngày 11/10 (`md5sum`, chỉ đọc): vẫn `6ece65e2…`**, file 6.742.016 byte, sửa lần cuối 06/10 13:33, không có `-wal`/`-shm`. Code T2–T5, UI và P2-4 chưa từng chạy trên DB thật (mọi smoke test dùng DB tạm).
- Ngày 06/10 lúc 13:33:44 có một tiến trình ngoài lượt làm việc (khả năng cao là app được bật bằng `.bat`, hoặc một agent khác) chạy migration 5.1. Kết quả: thêm bảng `project_storyboards` (0 dòng) cùng index; không gì khác đổi.
- Người dùng đã chốt: **không điều tra thêm, không rollback, không sửa DB.**

---

## 13. Ghi chú kỹ thuật cho Claude ở chat mới

- **Chạy test** (từ `_HE_THONG/app`): `python -m pytest -q -rf -p no:cacheprovider`, khoảng 6–7 phút trên Linux, khoảng 9–25 phút trên PC Windows (mục 9i, 9j). Nhóm test Bước 5 (~75 giây Linux, ~150 giây Windows): `tests/test_step5_edit_ui.py tests/test_edit_planner.py tests/test_edit_integration.py tests/test_edit_apply.py tests/test_edit_store.py tests/test_edit_document.py tests/test_storyboard_lineage.py tests/test_storyboard_gate.py tests/test_storyboard_engine.py tests/test_edit_manual_conflicts.py` (292 test sau khi sửa F1×F2), cộng từ 13/10: `tests/test_edit_manual_document.py tests/test_edit_conflict_resolution.py tests/test_legacy_timeline_writes.py tests/test_beat_job_race.py tests/test_plan_mode_writers.py`, từ 14/10: `tests/test_render_gate.py tests/test_edit_confirmation.py`. Test Node Bước 5: `node --test tests/step5_edit_document_ui.test.cjs tests/step5_storyboard_layout.test.cjs tests/step5_cleanups_ui.test.cjs tests/step5_t9_browser_fixes.test.cjs` (toàn bộ Node: `node --test tests/*.cjs`). Lệnh này chỉ chạy JS trong `vm`, không server, không DB.
- **Trên PC:** luôn thêm `--basetemp=<thư mục tạm riêng>` (mục 9i: không có thì pytest sập ở bước dọn `pytest-current` và mất phần tóm tắt). Dùng Python hệ thống (`C:\Program Files\Python313`), không có `.venv`. Nên đặt `PYTHONIOENCODING=utf-8`. Trước khi chạy test, kiểm shell **không** đặt `YOUTUBE_DB_PATH`/`YOUTUBE_DATA_DIR`, vì `conftest.py` dùng `setdefault`: biến có sẵn sẽ thắng DB tạm.
- `running_build_is_stale` chỉ xét file `.py` trong `youtube_monitor/`, nên sửa file `.md` ở gốc repo khi suite đang chạy vẫn an toàn.
- **Không sửa file khi full suite đang chạy.** Test `test_a_freshly_imported_process_is_not_stale` kiểm thời điểm sửa file nguồn. Muốn sửa thì dừng suite trước, sửa xong chạy lại.
- **File trong repo dùng xuống dòng LF.** Sửa bằng script Python thì dùng `read_bytes`/`write_bytes` hoặc `newline="\n"`; `Path.write_text` trên Windows đổi cả file sang CRLF. Sửa xong thì kiểm `count(b"\r\n") == 0`.
- **Không mở DB thật bằng `Database()` hay `import main`** (`initialize()` sẽ migrate). Chỉ đọc bằng `sqlite3` với `mode=ro`, hoặc dùng bản sao.
- Test app dùng `_AppCase` trong `tests/test_storyboard_gate.py` (TestClient + DB tạm). Lưu ý: `resync_timeline_segment_states` đổi `status` của mọi segment, nên so dữ liệu theo trường, không so cả dòng.
- **Chạy app an toàn trên PC (09/10):** `CHAY_YOUTUBE_AI_FACTORY.bat` mở DB thật (`.env` hoặc mặc định `_HE_THONG\data\youtube_monitor.db`), chạy `initialize()` + `resync_timeline_segment_states()` và bật worker nhận việc đang chờ. Trước khi chạy: `KIEM_TRA_DB_TRUOC_KHI_CHAY.bat` (chỉ đọc, `immutable=1`: DB nào, bảng sẽ tạo, việc đang chờ). Để thử: `CHAY_THU_NGHIEM_DB_TAM.bat` — mọi dữ liệu ở `%LOCALAPPDATA%\YouTubeAIFactory_THU_NGHIEM`, seed demo Bước 5 bằng model giả (`_HE_THONG/scripts/seed_demo_buoc5.py`, từ chối đường dẫn không chứa `THU_NGHIEM`). Lưu ý: nút gọi AI vẫn dùng key/CLI có trên máy (app tự tìm `claude` trên PATH). Lưu ý `.env.example` dùng đường dẫn tương đối `./data/...`, tính từ `_HE_THONG\app` (thư mục làm việc của launcher).
- **Kiểm tra cuối mỗi task** (PowerShell): không còn tiến trình `uvicorn`/`pytest`/`youtube_monitor`; `Get-NetTCPConnection -LocalPort 8787 -State Listen` rỗng; `md5sum` DB thật vẫn là `6ece65e2…`.

---

## 14. Bản đồ tài liệu (đọc theo thứ tự này)

| # | File | Vai trò | Còn đúng tới |
|---|---|---|---|
| 1 | `HANDOFF_GPT_BUOC5.md` (file này) | **Trạng thái hiện tại**, Bước 5, quy tắc làm việc | **14/10** |
| 1b | `HANDOFF_CHAT_MOI_BUOC5.md` (chưa track) | Gói đồng bộ Storyboard UI từ cloud sang PC (09/10): hash từng file, test trên cloud, rủi ro lưu cảnh | 09/10; nội dung đã gộp vào mục 9g |
| 2 | `PROJECT_STATUS.md` | Trạng thái Bước 1–4, gate, an toàn dữ liệu, giới hạn đã biết | 04/10; dòng Bước 5 đã cũ (08/10) — trạng thái Bước 5 xem file này |
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
