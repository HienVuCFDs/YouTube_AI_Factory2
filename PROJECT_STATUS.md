# PROJECT STATUS — YouTube AI Factory

Cập nhật: **2026-10-04**, sau khi hoàn tất Bước 3 · Kịch bản (Phase 1 → 2.2 và UI) và Bước 4 · Giọng đọc (đã nghiệm thu bằng API thật). Bản đầu viết ngày 03/10. Tác giả: Claude Code, theo yêu cầu người dùng.

File này là **trạng thái hiện tại**. Chi tiết kết nối AI và lịch sử các bước trước xem `AI_CONNECTION_HANDOFF.md`. Luật làm việc trong workspace: `AGENTS.md`.

> Code + test là nguồn sự thật. Mọi điều dưới đây đều đã được đối chiếu với code, test hoặc git khi viết; điều gì chưa xác minh được ghi rõ là chưa xác minh.

## Trạng thái các bước (04/10)

| Bước | Trạng thái | Gồm |
|---|---|---|
| Bước 1 — Phân tích | **COMPLETE** (đã commit) | `run_step("analyze")`, Nguồn tham khảo, Product Reader |
| Bước 2 — Kế hoạch | **COMPLETE** (đã commit) | Research → Insight → Plan → Feasibility, UI Bước 2 |
| Bước 3 — Kịch bản | **COMPLETE** (chưa commit) | Script Engine, production gate, worker gate, Short provenance, UI Bước 3 (mục 3) |
| Bước 4 — Giọng đọc | **COMPLETE / REAL-VERIFIED** (chưa commit) | Edge TTS, Google Gemini 3.8 Flash TTS, Google Gemini 3.8 Flash-Lite TTS, Gemini voice catalog, `voice_style`, preview, UI, ProductionWorker, real API verification (mục 3b) |

- **Test:** 2105 pass, 2 known old failures (`test_burned_in_marks`, `test_shorts`), 9 skipped (mục 4).
- **Git:** Bước 3 + Bước 4 chưa commit tại thời điểm bắt đầu commit. Commit gần nhất là `08c5ed0`.

---

## 0. Việc đầu tiên trong phiên mới

1. `git status` và `git diff --stat`. Nếu chưa có commit mới sau `08c5ed0` thì **Bước 3 + Bước 4 vẫn nằm trong working tree, CHƯA COMMIT** (mục 3, 3b).
2. Đọc file này, rồi `AI_CONNECTION_HANDOFF.md` (mục 0, 10–16, gồm 13b cho Bước 4).
3. Không reset, revert, clean, commit hay push khi người dùng chưa bảo.
4. Không tự khởi động app (AGENTS.md). Không mở DB thật bằng `Database()` (mục 7). Không gọi Google Gemini API thật khi người dùng chưa cho phép (lời gọi có phát sinh chi phí).
5. Chạy test: từ `_HE_THONG/app`, dùng `python -B -m pytest -q -p no:cacheprovider tests` (toàn bộ khoảng 6 phút).

## 1. App và pipeline

- **App:** máy sản xuất video, chạy local trên Windows. Stack: FastAPI + SQLite + HTML/JS thuần, code ở `_HE_THONG/app/youtube_monitor/`.
  - Chạy: `CHAY_YOUTUBE_AI_FACTORY.bat`, cổng 8787, chỉ khi người dùng bảo.
  - DB thật: `_HE_THONG/data/youtube_monitor.db`.
- **Một pipeline nghiệp vụ duy nhất:** nút bấm, AI orchestrator, MCP và automation đều đi qua `run_project_step(step)` / `POST /api/projects/{id}/steps/{step}`. Không có luồng Manual/Auto song song.

```text
Nguồn tham khảo → 1 Phân tích → 2 Kế hoạch → 3 Kịch bản → 4 Giọng đọc → 5 Storyboard & Edit → 6 Xưởng dựng → 7 Render & Xuất bản
```

- **Nguồn sự thật dữ liệu:**

```text
videos.source_kind
  → AnalysisResult → ResearchReport → InsightReport → ProjectPlan (Bước 2)
  → Script Engine → ScriptDocument (Bước 3)
  → production gate → giọng đọc (Bước 4) / storyboard / timeline / render / publish / Short
```

## 2. Các mốc đã commit (nhánh `master`, chưa có remote)

| Commit | Nội dung |
|---|---|
| `0615a34`, `a6ac010` | AI orchestrator chế độ agent (Codex/Claude CLI qua MCP), fallback runtime |
| `7a6022d` | Kết nối nền tảng bán hàng, Product Reader (Shopee/TikTok qua extension Cốc Cốc, Lazada/Tiki/Sendo qua profile riêng) |
| `e80e679` | Bước 1 Phân tích: một nút, `run_step("analyze")`, trạng thái chạy do server giữ |
| `09b5525`, `6ccb716`, `886eb9d` | Nguồn tham khảo: ô "Thêm nguồn" chung, cột `videos.source_kind`, Channel Intelligence |
| `54148db` | Bước 2 backend: Research → Insight → Plan → Feasibility, kèm hardening |
| `08c5ed0` | UI Bước 2; Bước 3 chỉ mở khi plan `completed` |

`git remote -v` trống: repo **chưa có remote**, nên "chưa push" nghĩa là chưa có nơi để push.

## 3. Bước 3 · Kịch bản — COMPLETE (Phase 1 → 2.2 + UI, CHƯA COMMIT)

### 3.1 Phase 1: Script Engine (`youtube_monitor/script_engine.py`, mới)

- Viết kịch bản **từ ProjectPlan đã `completed`**: 1 lượt gọi model qua `_call_orchestrator_json(stage="script")` cộng tối đa 1 lượt sửa. Không nghiên cứu lại, không lập lại kế hoạch, không đọc writer cũ.
- **ScriptDocument** (cột `project_scripts.document_json`) gồm:
  - `plan{plan_id, plan_version, primary_angle_id…}`, `target_duration_seconds`, `estimated_seconds`;
  - `hook`, `sections[{plan_section_id s1…sN, spoken_lines, on_screen_text, insight_ids, evidence_ids}]`, `cta`;
  - `checks`, `validation`, `missing_information`, `limitations`.
- Không chứa `visual_prompt`, camera hay shot: những thứ đó thuộc Storyboard.
- **Kiểm tra bằng code:**
  - đúng angle; đủ section, đúng thứ tự;
  - thời lượng tính từ số từ: lệch tổng tối đa ±15%; mỗi section không vượt quá max(ngân sách × 1,5, ngân sách + 5 giây);
  - evidence và insight id phải tồn tại; số liệu phải có trong nguồn (trừ số ≤10);
  - giá sản phẩm phải khớp giá đã đọc, đọc trong vòng 24 giờ, và giữ `captured_at`;
  - không nói `claims_to_avoid`; không nói giả thuyết như sự thật; không có chỉ dẫn hình ảnh.
- **7 cột mới ở `project_scripts`:** `plan_id`, `plan_version`, `insight_report_id`, `language`, `estimated_seconds`, `document_json`, `engine_version`. Các cột cũ luôn được ghi lại từ document: `intro` rỗng, `main_content` = mọi section mỗi câu một dòng, `cta` = chỉ phần CTA.
- **Trạng thái kịch bản** (`script_engine.current_script`):
  - `completed`: khớp `plan_id` + `plan_version` của plan hiện hành, và plan đang completed;
  - `stale`: viết cho plan cũ hoặc trước khi có plan; nếu id/version không khớp theo kiểu khác thì là `mismatch`;
  - `invalid`: bị sửa (PATCH, chat) khiến vi phạm plan.
- **Engine hợp lệ:** `script-phase1`, và `agent-draft` (bản do agent hoặc người dán vào; đã kiểm text và thời lượng, chưa map theo section).

### 3.2 Phase 2: một đường tạo kịch bản, chặn bypass

- Mọi đường tạo kịch bản dài của dự án trong luồng Kế hoạch đi qua `run_step("script")`:
  - `/script/generate`, `/steps/script`, MCP `youtube_factory_run_step`;
  - `/script/draft` (UI cũ) là adapter; từ chối 422 nếu request cố đặt angle, thời lượng, cấu trúc, CTA, platform…;
  - automation, vai Script Agent;
  - `/scripts/import`, MCP `save_script` → dạng draft;
  - `/script/chat` → dạng revision.
- PATCH `/api/scripts/{id}` → `script_engine.revise`: diff theo dòng, ghi lại vào document, kiểm lại; không đổi được `plan_id` / `plan_version`.
- `/director-draft` (writer cũ → storyboard) trả 409 với dự án trong luồng Kế hoạch.
- **"Luồng Kế hoạch"** (`main._in_plan_workflow`) = dự án có plan hoặc có analysis của nguồn. Dự án chỉ có kịch bản dán tay giữ hành vi cũ. *(Ranh giới này do Claude đề xuất, người dùng chưa xác nhận rõ.)*

### 3.3 Phase 2.1: production gate ở mức API

- **Logic chung:** `script_engine.production_block(plan, script, running)`. Thứ tự: plan có → plan completed → không có lượt viết kịch bản đang chạy → có script → không invalid → không stale/mismatch. **`force` không mở được.**
- **Thông điệp chuẩn:** `script_engine.CONTINUE_MESSAGES`, ví dụ "Kịch bản này thuộc một kế hoạch cũ. Hãy viết lại kịch bản trước khi tiếp tục."
- **Đã khóa:**
  - `/jobs`, `/jobs/{id}/retry`;
  - `/script/translate`;
  - `/publish`, `/publications/{id}/retry`;
  - `/short-script`, `/short/plan`;
  - `/shots/generate`, `/timeline/generate`, `/timeline/from-dialogue`;
  - `/orchestrate` chế độ plan (chế độ agent không chặn ở cửa vào; mọi tool nó gọi đều có gate);
  - `run_step` cho mọi bước sau script;
  - automation: Media Agent, hook tự dựng sau QC.

### 3.4 Phase 2.2: gate ở worker, provenance của Short, khóa đường bypass còn lại

**Gate ở worker** (`set_production_gate(callback)`): chạy **ngay sau khi claim, trước mọi tác vụ tốn kém**.

| Worker | Vị trí | Khi bị chặn |
|---|---|---|
| `production_worker.py` `ProductionWorker._process` | sau `claim_project_job`, trước mọi `run_*_job` (TTS, render, render Short, export) | `finish_project_job(..., "error", error=lý do)` |
| `scene_generator.py` `SceneGenerationWorker._process` | sau `claim_scene_generation_job`, trước khi viết prompt (lượt gọi model) và trước provider | ghi khoản sử dụng là `failed`, job `error` |
| `publisher.py` `PublisherWorker._process_due` | sau `claim_project_publication`, trước `upload_video` | publication `error` kèm lý do |

**Nối callback trong `main.py`:**
- Chuỗi gọi: `_script_gate` → `_artifact_gate` → `script_engine.artifact_block`; biến thể ném 409 là `_require_current_artifact`.
- Callback: `_job_gate_reason` (job nghe thử giọng `voice_preview` được miễn vì đọc câu mẫu cố định), `_scene_job_gate_reason`, `_publication_gate_reason`.
- API dùng lại đúng các hàm này.
- `artifact_block`: một dòng kịch bản dài phải **chính là** kịch bản hiện hành. Job làm cho một phiên bản cũ hơn bị từ chối với thông điệp `superseded`.

**Provenance của Short (không migration):**
- Short độc lập (`project_scripts`, `variant="short"`): `plan_id` / `plan_version` ghi vào hai cột đã có; `source_script_id`, `source_script_version`, `plan_id`, `plan_version` lưu trong `document_json` = `{"kind": "short_provenance", …}`. `script_engine.decode()` chỉ đọc document của kịch bản dài.
- Short cắt lại (`project_shorts.plan_json`): key `provenance`. `ShortPlan.from_dict` bỏ qua key lạ, nên plan cũ vẫn đọc được.
- Hợp lệ khi provenance khớp id + version của kịch bản hiện hành và của plan hiện hành. Sai thì trả 409 với "Short này được tạo từ một phiên bản kịch bản cũ. Hãy tạo lại Short từ kịch bản hiện tại."
- `GET /api/projects/{id}/short-script` trả thêm `provenance`, `current`, `blocked_reason`.

**Phân loại các route sau storyboard:**

| Nhóm | Route | Gate |
|---|---|---|
| A — sinh artifact mới, tốn model/credit | `/scene-jobs`, `/scene-jobs/batch`, `/scene-jobs/{id}/retry`, MCP `generate_image/gif/video`, `edit-beats/{i}/generate`, `POST /edit-plan`, `/timeline/plan-visuals`, `/timeline/plan-source-cues`, `edit-beats/plan`, `/thumbnails/generate`, `/premiere-export` | **khóa** |
| B — sửa artifact đã có | `edit-plan/approve`, PATCH cảnh trong edit-plan, `edit-plan/apply`, `edit-beats/apply`, `edit-plan/fallback` (ảnh nền một màu), `/timeline/cleanups`, PATCH shots/timeline | mở |
| C — chỉ đánh giá | `/script/review`, `/voice/review` | mở |
| D — xử lý nguồn / nghe thử | `/voice-previews` (câu mẫu cố định), `/videos/{id}/transcript/translate` | mở |

### 3.5 UI Bước 3 (xong 03/10)

- Nút "Viết kịch bản" gửi **một** `POST /api/projects/{id}/steps/script`. Nút này không còn gọi `/api/videos/{id}/writer` hay `/script/draft`.
- Trang hiển thị ScriptDocument: hook, các section, CTA, thời lượng ước tính so với mục tiêu, lỗi kiểm tra.
- Trạng thái do server trả qua `GET /api/projects/{id}/script`; trang không tự suy luận lại:
  - `state`, `current`;
  - `blocked_reason`: lời của production gate;
  - `write_blocked_reason`: vì sao chưa viết được kịch bản;
  - `generation`: lượt viết đang chạy hoặc lượt gần nhất.
- Thông điệp 409 được hiển thị nguyên văn câu của server. Sửa lời đi qua PATCH `/api/scripts/{id}` (`script_engine.revise`).
- Làn Short đọc `provenance` và `blocked_reason` từ `GET /short-script`. Short làm từ kịch bản cũ thì các nút phía sau bị khóa, kèm lý do của server.
- Writer cũ vẫn còn ở trang Thư viện (AI Writer từng video hoặc hàng loạt) và ở phần đề xuất metadata xuất bản (mục 6); Bước 3 không đọc nó.

## 3b. Bước 4 · Giọng đọc — COMPLETE / REAL-VERIFIED (CHƯA COMMIT)

**Engine** (`youtube_monitor/tts_catalog.py`, mới): mỗi provider key ứng với một vendor, một model và loại file.

| Provider key | Vendor / model | File |
|---|---|---|
| `edge_tts` | microsoft / `edge-tts` (giữ nguyên, vẫn là mặc định) | mp3 |
| `google_gemini_3_8_flash_tts` | google / `gemini-3.8-flash-tts` | wav |
| `google_gemini_3_8_flash_lite_tts` | google / `gemini-3.8-flash-lite-tts` | wav |
| `pyvideotrans`, `voxcpm` | không đổi | wav |

**Adapter Gemini** (`youtube_monitor/gemini_tts.py`, mới):
- `POST https://generativelanguage.googleapis.com/v1beta/interactions`, key chỉ nằm trong header `x-goog-api-key`. Key không vào URL, log, lỗi, ledger hay file.
- Lời đọc là transcript nguyên văn của cảnh. Kiểu đọc nằm riêng trong `annotations[].speech_metadata.style`, không chen vào lời.
- `speech_config: [{voice, language}]`; tối đa 2 người nói thì dùng `mode: "conversational"`.
- Kết quả là WAV có header RIFF (24 kHz, mono, 16-bit), ghi nguyên như nhận, không bao giờ thêm header hai lần.
- Retry kỹ thuật 3 lần (chờ 2 s, 5 s). Rate limit chờ theo `retryDelay`, tối đa 30 s. Hết quota trong ngày thì ghi vào `usage_limits`. Lỗi auth và lỗi input dừng ngay.

**Danh mục giọng** (`GET /v1beta/voices?type=prebuilt&language_code=vi-VN`):
- vi-VN có 40 giọng `vi-vn-*`, **không có Kore**.
- Google tra giọng theo cặp tên + ngôn ngữ, nên giọng catalog được gửi kèm `language` mà catalog ghi cho nó (`vi-VN`); gửi `vi` sẽ bị trả 400 "No matching speaker voice". Giọng dựng sẵn như Kore vẫn gửi `vi`.
- Cache 1 giờ. Đọc lỗi thì 5 phút sau mới hỏi lại. Làm mới bị lỗi thì vẫn trả danh sách cũ (đánh dấu `stale`). Danh mục rỗng không được cache.
- `voice_for`: giọng chưa xác nhận được vì danh mục không đọc được (app vừa khởi động lại, danh mục lỗi) thì **không bị thay bằng Kore**: báo lỗi tạm thời và không đọc cảnh nào. Giọng mà danh mục đọc được nhưng không liệt kê (ví dụ giọng của Edge) thì được thay bằng Kore, có ghi `voice_fallback_from`.

**`voice_style`:** cột `project_render_settings.voice_style TEXT NOT NULL DEFAULT ''`, là migration duy nhất của Bước 4, đã được người dùng duyệt (mục 7). Giá trị đi vào `speech_metadata.style`. `voice_prompt_text` giữ nghĩa cũ (lời của file giọng mẫu VoxCPM) và không dùng cho Gemini.

**Pipeline:**
- Vẫn là `/jobs` → `ProductionWorker` → `run_voiceover_job`, có thêm một nhánh Gemini. Edge không đổi. Short dùng cùng các provider.
- Mỗi cảnh, với mọi engine, ghi một dòng ledger `voice.tts`: vendor, model, voice, language, `voice_language`, speaker, segment, job, `audio_path`; với Gemini thêm style, usage token và số lần thử.
- Model chưa có key hoặc hết quota thì `/jobs` từ chối với lỗi 400.

**API và UI:**
- `GET /api/tts/voices?provider=&language=`: không truyền `provider` thì là danh sách Edge như cũ.
- `GET /api/voice-previews/gemini/{provider}?voice&style&language`:
  - đọc câu mẫu cố định, không đọc kịch bản, không tạo job;
  - cache ở `01_DU_AN/_voice_previews/`;
  - ghi ledger `voice.preview`.
- `GET /api/production-queue` trả thêm `tts_providers`, với các trạng thái Sẵn sàng / Chưa cấu hình / Hết quota / Lỗi kết nối. Thông tin này đọc từ dữ liệu sẵn có, không gọi Google.
- UI Bước 4 (redesign 04–05/10, ít chữ):
  - Bố cục 2 cột (1 cột trên màn hẹp).
    - Trái: *Công nghệ* (4 card gọn: Edge, Gemini Flash, Gemini Flash-Lite, TTS cục bộ mở ra pyVideoTrans / VoxCPM2), *Giọng nói* (tìm, lọc Nam/Nữ/Khác, danh sách cuộn riêng), *Nâng cao* (gập: phụ đề, ngôn ngữ, công cụ VoxCPM, Chi tiết kỹ thuật).
    - Phải: *Đang chọn* (engine, giọng, kiểu đọc, Đã lưu/Chưa lưu), *Kiểu đọc* (Gemini, 7 preset chỉ điền `voice_style`) hoặc *Tốc độ* (Edge/cục bộ), *Nghe thử* (trình phát; bấm lại cùng giọng không gọi lại server).
  - Các `<select>` cũ vẫn là nguồn sự thật: card và danh sách chỉ đặt giá trị select rồi phát `change`.
  - Danh mục giọng chỉ được hỏi khi người dùng chọn một model Gemini.
  - Khi đổi nhà cung cấp, cài đặt chỉ được lưu sau khi danh sách giọng đã tải và đã chọn giọng; giọng của từng nhóm engine được nhớ khi đi Gemini → Edge → Gemini.
  - Giọng Gemini dự án đã lưu vẫn được giữ, kể cả khi danh mục không liệt kê giọng đó.
  - Thông tin kỹ thuật chỉ nằm trong tooltip hoặc mục "Chi tiết".

**Nghiệm thu bằng API thật (04/10, REAL-VERIFIED):**

| | Flash | Flash-Lite |
|---|---|---|
| Nghe thử Kore / Kore + style | HTTP 200, WAV 24 kHz mono, 1 header RIFF | HTTP 200 |
| Nghe thử giọng catalog `vi-vn-advisor-6` | HTTP 200 (`voice_language: vi-VN`) | HTTP 200, có style |
| Worker trên DB tạm (1 cảnh, câu tiếng Việt mẫu, có style) | `completed`, có `audio_path`, ledger `voice.tts` đúng | `completed`, có `audio_path`, ledger đúng |
| Request gửi đi | transcript không đổi, style nằm trong `speech_metadata` | như Flash |

- Mỗi lượt gọi mất khoảng 5–8 giây.
- Token: Kore khoảng 400–490; giọng catalog khoảng 1600 (khoảng 1430 token đầu vào).
- Có 6 lần nghe thử thật, ghi ở ledger `voice.preview` #111–116 của DB thật. Phần worker chạy trên DB tạm, không tạo job trên DB thật.
- UI đã kiểm trên app thật:
  - Khi chưa mở dự án: không có gì được ghi.
  - Khi có dự án (kiểm trên bản sao DB): lưu đúng; sau khi khởi động lại app, giọng và style vẫn giữ đúng.

## 4. Kiểm thử (lần chạy cuối, 04/10)

- **Toàn bộ suite:** **2105 đạt, 2 đỏ, 9 bỏ qua** (230 subtest).
- **Hai test đỏ có từ trước**, không sửa, file của chúng không đổi:
  - `test_burned_in_marks.py::…test_an_unmarked_reup_gets_its_source_measured` (0 lần gọi thay vì 1);
  - `test_shorts.py::RendererFitTests::test_the_renderer_can_fill_a_frame_as_well_as_pad_it` (`'sound_cues' != 'fit'`).
- **Test của Bước 3:**

| File | Số test | Nội dung |
|---|---|---|
| `tests/test_script_engine.py` | 31 | Phase 1 |
| `tests/test_script_paths.py` | 29 | Phase 2 |
| `tests/test_production_gate.py` | 23 | Phase 2.1 |
| `tests/test_production_gate_worker.py` | 18 | Phase 2.2; chạy thẳng `_process` thật của từng worker, kiểm runner, model, uploader và provider không được gọi |
| `tests/test_step3_ui.py` | 17 | UI Bước 3: cấu trúc trang, lời của server; chạy `tests/step3_script_ui.test.cjs` bằng node |
| `tests/step3_script_ui.test.cjs` | 22 (node) | chạy code trang Bước 3 thật với server giả |
| `tests/script_fixtures.py` | — | helper dùng chung: dự án có plan theo trạng thái cần, model giả đọc ngược prompt |
| `tests/fixtures/project78_plan_v5.json` | — | snapshot chỉ đọc của plan v5 dự án 78 |

- **Test của Bước 4** (mọi lời gọi Google đều đi vào `httpx.MockTransport`; key trong test là key giả):

| File | Số test | Nội dung |
|---|---|---|
| `tests/test_gemini_tts.py` | 38 | adapter: request, WAV, retry, quota, phân loại lỗi, danh mục giọng, cache, catalog language, regression "không thay giọng bằng Kore khi danh mục không đọc được" |
| `tests/test_step4_tts.py` | 28 | migration `voice_style`, settings, `_process` thật của worker với cả hai model, ScriptDocument → transcript đúng từng chữ, Edge không đổi, API, nghe thử, Short, UI (bố cục, nối dây lưu, ngân sách chữ) |
| `tests/step4_gemini_voices.test.cjs` | 7 (node) | `loadGeminiVoices` thật: chọn giọng, giữ giọng đã lưu, dữ liệu danh mục trên option, một lượt tải cho mỗi model và ngôn ngữ |
| `tests/step4_voice_desk.test.cjs` | 19 (node) | bàn giọng thật: card và trạng thái, khóa đúng engine, danh sách và bộ lọc, Đang chọn, tốc độ, trình phát, nhớ giọng khi đổi engine |

- **Test cũ đã chỉnh cho khớp hợp đồng mới:** `test_steps`, `test_short_script`, `test_shot_planner`, `test_dialogue_timeline`, `test_reup_clip_sync` (chỉ fixture); `test_writer_quality` và `studio_navigation.test.cjs` (cho UI Bước 3).
- **Lưu ý khi viết test:**
  - DB test là một file tạm dùng chung cả phiên.
  - `TestClient` khởi động worker thật: mock `production_worker.enqueue` và `scene_generation_worker.enqueue`; đừng để job `queued` sót lại.
  - Đừng kết thúc job cảnh bằng lỗi kiểu "hết hạn mức" trong fixture, vì sẽ mở circuit breaker của provider đó cho các test sau.

## 5. Kiểm tra trên dữ liệu thật (bản sao DB, model giả)

| Dự án | Hiện trạng trong DB thật | Kết quả trên bản sao |
|---|---|---|
| **57** (legacy) | Kịch bản cũ 93/94, writer cũ, cảnh, timeline, video cuối; plan v6 kiểu cũ `needs_attention` (= chờ quyết định) | Mọi đường đi tiếp bị chặn ("Kế hoạch hiện cần bạn quyết định trước khi tiếp tục."); worker từ chối job render/voice của kịch bản 94; không gọi model; dữ liệu không đổi |
| **78** (chuẩn) | Bài báo, plan v5 `completed` (id 16), `ang-2`, 100 giây, 5 section [10, 24, 27, 20, 19]; **chưa có kịch bản trong DB thật** | Kịch bản v5 → voice chạy; Short v5 có provenance (kịch bản 98, phiên bản 1, plan 16, v5); plan lên v6 → worker từ chối job render v5; viết lại (kịch bản 100, v6) → render chạy; Short v5 bị chặn, Short v6 chạy |

Script Engine và các gate **chưa chạy với model viết kịch bản thật**. Mới chứng minh bằng test và bản sao DB với model giả. (Bước 4 thì đã chạy thật với Gemini TTS, xem mục 3b.)

## 6. Giới hạn đã biết (chưa sửa)

1. **Provenance của `final.mp4`** (audit chỉ đọc 03/10: **FAIL**, chưa sửa):
   - P0: `/publish` bản dài luôn lấy file cố định `01_DU_AN/<id>/04_XUAT_BAN/final.mp4` (`_publication_video_path`), không hỏi file đó dựng từ kịch bản nào. Publication không lưu script, render hay hash, nên bản đăng đã xếp lịch hoặc retry có thể tải lên file cũ.
   - P1: PATCH sửa kịch bản tại chỗ; gói manual-package không có gate.
   - Phase "final.mp4 provenance + publish artifact gate" đã dừng ở bước 1: **MIGRATION_REQUIRED**. Đề xuất thêm `project_jobs.provenance_json` và `project_publications.artifact_json` (`TEXT DEFAULT ''`); **đang chờ người dùng quyết**, chưa sửa code.
2. **Worker sidecar bên ngoài** (antigravity, web; `database.EXTERNAL_SIDECAR_PROVIDERS`) tự đọc job cảnh từ DB. Gate ở API chặn lúc tạo job, nhưng gate của worker trong app không chạy cho chúng. Audit 03/10 xếp P2: claim/complete của sidecar không có gate. Chưa sửa.
3. **Short tạo trước Phase 2.2** trong dự án có plan không có provenance, nên bị chặn và phải tạo lại. Đây là hành vi có chủ ý.
4. **Job bị gate chặn dùng trạng thái `error`** (schema không có trạng thái riêng), phân biệt bằng nội dung lý do.
5. **Metadata xuất bản** (mô tả, hashtag, đề xuất AI) vẫn đọc từ writer cũ; để Phase 7 / Publish xử lý.
6. Bản nháp (agent hoặc dán tay) chưa map theo section. PATCH không chuyển được dòng sang section khác. Kiểm claim và số liệu vẫn là heuristic.
7. **Bước 4 · chi phí Gemini TTS chưa đo chính xác:** `estimated_cost` trong ledger là 0; mới chỉ ghi số token.
8. **Bước 4 · chất lượng style cần người nghe đánh giá:** máy chỉ xác nhận style được gửi đúng field; số token đầu vào không đổi dù có hay không có style. Các file nghe thử nằm ở `01_DU_AN/_voice_previews/`.
9. **Bước 4 · mỗi cảnh đọc bằng một giọng:** adapter hỗ trợ 2 người nói, nhưng pipeline chỉ ghi lại tên người nói. Khi danh mục giọng không đọc được, job dùng giọng catalog sẽ dừng với lỗi tạm thời (có chủ ý, không thay giọng); chạy lại khi danh mục đọc được.

**Backlog người dùng bảo chỉ ghi lại, chưa sửa:**
- giá Shopee lúc đọc được lúc không;
- audio tiếng Anh bị `analysis_is_about_the_source` từ chối khi chủ đề viết tiếng Việt;
- tab HÀNG ĐỢI / THƯ VIỆN;
- độ liên quan chưa chấm cho trang web;
- `limitations` của phân tích đôi khi trôi vào `must_not_invent`.

## 7. An toàn dữ liệu

- **DB thật, các mốc hash:**
  - `8cc459dbe9c051269297295e55951e49`: không đổi từ Phase 2 tới Phase 2.2 và UI Bước 3.
  - `acc04da25339327d30999813a7caab81` (04/10): sau migration `voice_style`. Chỉ thêm cột; mọi bảng khác giống hệt.
  - `31ac5e63abc30bb423a000b902489963` (04/10, hiện tại): sau 6 lần nghe thử Gemini thật. So với bản sao lưu trước migration, chỉ có `project_render_settings` thêm cột (6 dòng giữ nguyên, `voice_style` rỗng) và `provider_usage_ledger` thêm 6 dòng `voice.preview` (#111–116).
- **7 cột của Phase 1 đã có sẵn trong DB thật:** một script trích fixture ngày 03/10 đã mở DB thật bằng `Database()`, và `initialize()` tự migrate. Chỉ thêm cột có giá trị mặc định; 51 kịch bản cũ nguyên vẹn.
- **Migration `voice_style` (Bước 4):** người dùng duyệt đúng một cột `project_render_settings.voice_style TEXT NOT NULL DEFAULT ''`. Cột được thêm khi mở app ngày 04/10 (`_ensure_column`). Không có migration nào khác.
- Không có job sản xuất nào phát sinh trên DB thật; 0 dòng `voice.tts`; không ghi nhận hết quota Gemini.
- **Quy tắc:**
  - Không mở DB thật bằng `Database()`, và không `import youtube_monitor.main` ngoài pytest khi chưa trỏ `YOUTUBE_DATA_DIR` / `YOUTUBE_DB_PATH` (cùng `PRODUCTION_ARTIFACT_DIR`) sang thư mục tạm.
  - Đọc DB thật chỉ bằng `sqlite3` với `mode=ro`, hoặc qua bản sao tạo bằng backup API; xoá bản sao sau khi dùng; ghi hash trước và sau.
  - Cần migration DB thật thì **dừng và hỏi** trước.
  - Kiểm UI có ghi settings của dự án: chạy app với `YOUTUBE_DB_PATH` trỏ tới bản sao DB; `/api/health` trả về `database` để xác nhận app đang dùng bản sao.
- **Bảo mật:** không đưa cookie, password, token hay API key vào code, log hay prompt; không vượt CAPTCHA hay anti-bot; không lưu định danh người bình luận.
  - Lần quét secret gần nhất (04/10): sạch. `GEMINI_API_KEY` chỉ nằm ở `_HE_THONG/config/.env` (đã gitignore, git không theo dõi).

## 8. Cách người dùng làm việc

- Giao việc theo **phase**, viết tiếng Việt, ghi rõ phạm vi KHÔNG làm (thường là: không UI, không commit, không push, không khởi động app, không sửa 2 test đỏ cũ, không redesign).
- Mỗi phase: chạy test liên quan + toàn bộ suite, quét secret, xem diff, kiểm hash DB, báo cáo **đúng format người dùng đưa**, rồi **dừng chờ review**.
- Đường bypass hay quyết định chưa chắc: không tự mở rộng phạm vi; ghi endpoint, call path và lý do vào báo cáo.
- File `_tmp_*` ở root là của người dùng: không xoá, không commit.

## 9. Việc tiếp theo (chờ người dùng quyết)

- [ ] Review và commit Bước 3 + Bước 4 (người dùng ra lệnh commit riêng, với message của họ).
- [x] Audit A (provenance của `final.mp4`) và B (worker sidecar) — xong 03/10, kết quả ở mục 6.
- [ ] Quyết định migration cho phase "final.mp4 provenance + publish artifact gate" (MIGRATION_REQUIRED, mục 6, ý 1).
- [ ] Xác nhận ranh giới "luồng Kế hoạch" (mục 3.2).
- [x] UI Bước 3 — xong (mục 3.5).
- [x] Bước 4 · Giọng đọc với Gemini TTS — xong, REAL-VERIFIED (mục 3b).
- [ ] Sau đó: Bước 5 Storyboard dựng từ section của ScriptDocument; chạy thật Script Engine trên dự án 78 với model thật.
