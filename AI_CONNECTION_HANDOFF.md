# AI CONNECTION HANDOFF — YouTube AI Factory

Cập nhật: **2026-10-04**, mốc **Bước 3 · Kịch bản COMPLETE (gồm UI) + Bước 4 · Giọng đọc COMPLETE / REAL-VERIFIED (Gemini 3.8 TTS)**. Cả hai chưa commit tại thời điểm bắt đầu commit.

**File này tự đủ để một AI khác (ChatGPT) nắm dự án.** Claude Code dùng thêm `PROJECT_STATUS.md` (cùng nội dung, gọn hơn).

Lịch sử cập nhật:
- 29/09: Bước 1 (mục 1–9).
- 03/10: thêm mục 0 và mục 10–16 — Nguồn tham khảo, Bước 2 Kế hoạch, Bước 3 Kịch bản (Script Engine, production gate ở API và worker, provenance của Short), trạng thái git/test/DB, quy tắc làm việc, việc đang chờ.
- 04/10: UI Bước 3 xong (12.5); thêm mục 13b — Bước 4 Giọng đọc (Edge + Gemini 3.8 Flash / Flash-Lite TTS, `voice_style`, nghiệm thu bằng API thật); cập nhật mục 0, 14, 16.

Mục 1–9 giữ nguyên nội dung cũ, vẫn đúng tại ngày ghi trong từng mục.

Nhãn trạng thái:

| Nhãn | Nghĩa |
|---|---|
| **VERIFIED** | đã chạy thật hoặc đo thật |
| **PARTIAL** | chạy một phần |
| **UNVERIFIED** | có code và test, chưa chạy thật |

---

## 0. Đọc nhanh (cho người/AI mới vào)

**App:** máy sản xuất video, chạy local. Stack: FastAPI + SQLite + HTML/JS thuần. Code ở `_HE_THONG/app/youtube_monitor/`, chạy bằng `CHAY_YOUTUBE_AI_FACTORY.bat`, cổng 8787.

**Luồng sản xuất (Studio, 7 bước trên giao diện):**

```text
1 Phân tích → 2 Kế hoạch → 3 Kịch bản → 4 Giọng đọc → 5 Storyboard & Edit → 6 Xưởng dựng → 7 Render & Xuất bản
```

- Mọi bước chạy qua **một** đường `run_project_step(step)`. Nút bấm, `POST /api/projects/{id}/steps/{step}`, MCP `youtube_factory_run_step`, AI orchestrator và automation đều đi vào đó.
- Danh mục bước ở `steps.py`: `analyze → plan → script → shots → timeline → voice → media / edit_plan → render → publish`, cộng `script_review`, `voice_review` và `research` (bản cũ).

**Nguồn sự thật hiện nay:**

```text
AnalysisResult → ResearchReport → InsightReport → ProjectPlan (Bước 2)
              → Script Engine → ScriptDocument (Bước 3)
              → Production Gate → Voice / Storyboard / Timeline / Render / Publish
```

**Đang ở đâu:**

| Phần | Trạng thái |
|---|---|
| Bước 1 Phân tích, Nguồn tham khảo, Bước 2 Kế hoạch (backend + UI) | **COMPLETE**, đã commit (tới `08c5ed0`); repo **chưa có remote**, chưa push đi đâu |
| Bước 3: Phase 1 (Script Engine), Phase 2 (nối đường + chặn bypass), Phase 2.1 (production gate), Phase 2.2 (gate ở worker + provenance của Short), UI Bước 3 | **COMPLETE**, xong code + test, **CHƯA COMMIT** (12, 13) |
| Bước 4 Giọng đọc: Edge TTS + Google Gemini 3.8 Flash TTS / Flash-Lite TTS, danh mục giọng, `voice_style`, nghe thử, UI, ProductionWorker | **COMPLETE / REAL-VERIFIED**, **CHƯA COMMIT** (13b) |
| Test | **2105 đạt**, 2 đỏ cũ (`test_burned_in_marks`, `test_shorts`), 9 bỏ qua |

**Ba điều không được làm khi chưa được bảo:**
- commit hoặc push;
- tự khởi động app (AGENTS.md);
- ghi vào DB thật (xem mục 14).

---

## 1. Kiến trúc: một pipeline, hai cách lái

```text
Người bấm nút ──┐
                ├──► run_project_step(step) ──► cùng logic, cùng chốt kiểm tra, cùng DB
AI Orchestrator ┘         ▲
   (agent tự quyết,       │ MCP tool youtube_factory_run_step / list_steps
    gọi qua MCP) ─────────┘
```

Không có pipeline riêng cho chế độ tự động. Agent chỉ quyết định bước nào, rồi gọi **chính** `run_step` mà nút bấm gọi.

- **Stack:** FastAPI + uvicorn (`_HE_THONG/app/youtube_monitor/main.py`), SQLite, HTML/JS thuần.
- **Chạy app:** `CHAY_YOUTUBE_AI_FACTORY.bat`.

## 2. Hai loại AI, không trộn lẫn

| | Structured Worker | Orchestrator Agent |
|---|---|---|
| File | `codex_bridge.py`, `claude_code_bridge.py` (**giữ nguyên**) | `codex_agent_bridge.py`, `claude_agent_bridge.py` (mới) |
| Việc | một nhiệm vụ trong một bước → một JSON | điều phối cả mục tiêu |
| Quyền | Codex `--sandbox read-only --ignore-user-config`; Claude `--tools ""` | **chỉ** tool của app qua MCP. Codex: read-only, `-c mcp_servers…`. Claude: `--restricted --tools "" --strict-mcp-config --permission-mode dontAsk --allowedTools mcp__youtube_ai_factory` |
| Vòng lặp | không | có: agent tự lặp gọi tool → đọc kết quả → chọn tiếp |
| Ai gọi | các bước của app | `agent_loop.run_goal`, chạy trên worker hàng đợi có sẵn |

Các bước Bước 2 và Bước 3 gọi model qua `_call_orchestrator_json(stage=…)`. Runtime do chính sách của từng công đoạn quyết định, có fallback và ghi audit log. Bước 2 dùng `stage="orchestration"`, Bước 3 dùng `stage="script"`.

## 3. Vòng Agent (`agent_loop.py`)

```text
GOAL + target_steps
 └► vòng r ≤ max_rounds:
     đọc state thật (_steps_done) → đạt rồi thì dừng
     chọn runtime (ghi lý do bỏ qua từng runtime) ─ runtime hỏng hẳn → đổi runtime, không tính vòng
     agent tự lặp: list_steps → run_step → đọc lỗi → đổi cách (bước tiên quyết / provider khác)
     app KIỂM LẠI bằng DB (_verify_goal); agent báo "done" là chưa đủ
     chưa đạt → vòng sau nhận lịch sử lệnh gọi, lỗi, phần còn thiếu, báo cáo sai (false_claims)
     2 vòng liền không đổi state → dừng "blocked"
```

- **Kích hoạt:** `POST /api/projects/{id}/orchestrate` với `{"mode":"agent","intent":…,"target_steps":[…],"runtime":"auto","allow_spend":false,"allow_overwrite":false,"max_rounds":4,"tool_budget":40}`.
  - `runtime` (`auto` / `codex_cli` / `claude_code_cli` / `astra` / `claude`) chọn AI điều phối đi trước; các AI còn lại đứng sau làm dự phòng.
  - App tạo task vai `orchestrator` trong **hàng đợi có sẵn**. Chế độ `plan` cũ vẫn giữ cho giao diện.
- **Hoàn thành:** task chỉ `completed` khi `_verify_goal` xác nhận từ DB. Từ Bước 3, `_verify_goal` chỉ tính `script` là xong khi kịch bản **hiện hành** (khớp plan), xem mục 12.
- **Hai loại retry:**
  - `llm_client._with_retry` chỉ lo lỗi kỹ thuật tạm thời (đợi 5/20/45 giây), giữ nguyên.
  - Vòng agent lo **đổi chiến lược**: provider khác, bước tiên quyết, runtime khác.

## 4. MCP `youtube_ai_factory` (`ai_desktop_mcp.py`, stdio → HTTP 127.0.0.1:8787)

- **48 tool** (đếm lại 03/10). `initialize` trả `instructions`: "dùng tool youtube_factory_*, không bấm giao diện".
- Mô tả tool đã cập nhật ngày 03/10:
  - `youtube_factory_run_step`: bước `script` chỉ chạy khi Kế hoạch đã hoàn thành; `draft` vẫn bị kiểm theo Kế hoạch; có option `create_standalone_short`.
  - `youtube_factory_save_script`: với dự án có Kế hoạch, kịch bản được lưu qua Bước 3 như một bản nháp đã kiểm tra.
- **Chế độ agent-run** chỉ bật khi app tự khởi chạy agent, qua biến môi trường. Ở chế độ này:
  - không gửi nhịp tim giả làm app chat;
  - ẩn 6 tool hàng đợi của app chat;
  - chỉ làm việc trên dự án của lượt chạy;
  - giới hạn số lần gọi tool mỗi vòng;
  - **chặn gọi lại y hệt** một lệnh đã chạy và hỏng khi trạng thái dự án chưa đổi (so dấu vân tay `list_steps`);
  - chặn tiêu lượt (bước có `spends`, tool có `confirmed`) trừ khi `allow_spend`;
  - chặn `force` ghi đè trừ khi `allow_overwrite`;
  - **luôn chặn** `confirmed_publish`;
  - ghi mỗi lần gọi vào `01_DU_AN/<id>/_WORK/agent_runs/<task>.jsonl`, đã che bí mật.
- Không tool nào xoá dữ liệu. `run_step` có timeout riêng 1500 giây.

## 5. Chọn AI / runtime — **một** bảng duy nhất

- Bảng duy nhất là `settings.AGENT_RUNTIME` (`astra→codex_cli`, `claude→claude_code_cli`, `antigravity→antigravity`), đọc qua `settings.runtime_for` = `orchestrator_runtime.runtime_id`.
- Mọi nơi đi qua đó:
  - `main._agent_runtime_available`, `_call_specific_agent_json`, `_resolve_auto_text_provider`;
  - phân tích ảnh tham chiếu, chấm cảnh bằng thị giác;
  - `writer.resolve_writer`, `writer._assigned_writer`;
  - `llm_analyzer.resolve_analyzer`, `reference_analyzer._call`, `director._call`.
- Bảng riêng `_ASSIGNED_TO_WRITER` đã bỏ.
- App chat (`chatgpt_app`, `claude_chat`) **không bao giờ** là executor hay reviewer của worker trong app.

## 6. Quota — **một** cách đọc

`usage_limits.limit_state()` được dùng chung cho readiness, worker, danh mục provider cảnh và banner `/api/usage-limits`:

| Trạng thái | Nghĩa | Chặn? |
|---|---|---|
| `active` | vừa hết, còn trong thời gian chờ | ✅ tới `retry_at` |
| `probe_due` | quá 6 giờ từ lần hỏng cuối, dù mốc hồi phục ghi xa hơn | ❌ được thử lại |
| `reset_passed` | đã qua mốc hồi phục | ❌ lịch sử |
| `recovered` | đã có lần gọi thành công sau đó | ❌ lịch sử |

Có một lần gọi thành công thì bản ghi tự xoá (`note_success`). Banner tách `limits` (đang chặn) khỏi `history`.

## 7. Trạng thái kết nối (tính đến 29/09)

| Mục | Trạng thái | Bằng chứng |
|---|---|---|
| Codex CLI làm Orchestrator Agent qua MCP | **VERIFIED** | Dự án 61 và 66 (28/09), xem mục 8 |
| Claude CLI làm Orchestrator Agent qua MCP | **VERIFIED** | Dự án 61 (29/09), task `agt_64ed…`, `runtime=claude_code_cli`: list_steps → run_step(timeline) → list_steps; model `claude-opus-5` + `claude-haiku-4-5`, 5 lượt, 22,7 giây; DB xác nhận 6 đoạn timeline. Agent tự **không** dùng `force` vì chưa có timeline để ghi đè |
| Đổi runtime khi não hỏng (Codex → Claude) | **UNVERIFIED** (có test) | Chưa xảy ra thật. Khi xảy ra, log ghi `round.runtime_failed` cùng quyết định chọn runtime kế tiếp |
| Pipeline 5 vai chạy bằng CLI | **PARTIAL** | Dự án 72: research, script, director đạt (`astra`, `claude` chấm chéo 8 điểm). `media` trượt 6/10 vì chất lượng, giữ nguyên. `qc` chưa tới. Từ 03/10, vai `script` chạy bằng Script Engine (mục 12) |
| GPT Work nạp MCP, thấy 45 tool | **VERIFIED** | log `~/.codex/logs_2.sqlite` |
| GPT Work gọi tool `youtube_factory_*` | **UNVERIFIED** | 0 lần trong `~/.codex/sessions`; ngày 28/09 nó bấm giao diện. Chưa có bằng chứng GPT Work đọc `instructions` của MCP |
| Claude Cowork nạp MCP | **Chưa kết nối** | Claude Desktop ghi đè config lúc 17:18:46 28/09. Phải sửa khi Claude Desktop **đã tắt hẳn** |
| App đánh thức GPT Work / Cowork | **Không có đường** | Chúng chỉ làm khi người gõ hoặc Automation tới lịch (hiện 0 Automation) |
| Claude in Chrome (Cốc Cốc) đọc Shopee/TikTok trong phiên Claude Code tương tác | **VERIFIED** | Đủ giá, 28/09 |
| `claude -p --chrome` chạy nền | **Bị chặn** bởi chính sách an toàn của Claude Code | — |

## 8. Bằng chứng tự phục hồi (regression đã nghiệm thu, 28/09)

Task `agt_b32ad16…`, dự án 66, mục tiêu `timeline`:

```text
1 list_steps                                   → chỉ analyze done
2 run_step(script, provider=openai_gpt)        ✗ HTTP 400 Thiếu OPENAI_API_KEY
3 get_ai_runtimes                              → codex_cli sẵn sàng
4 run_step(script, provider=codex_cli)         ✓ script 96
5 run_step(shots)                              ✓ 6 cảnh
6 run_step(timeline)                           ✓ 6 đoạn, 139 giây
7 list_steps                                   → script/shots/timeline done
_verify_goal: missing=[] false_claims=[] ; task completed ; 1 vòng ; 7 tool call ; 144 giây
```

Lưu ý: lần chạy này diễn ra **trước** khi Bước 2 và Bước 3 tồn tại. Bây giờ `run_step(script)` đòi Kế hoạch đã hoàn thành.

## 9. Bước 1 – Phân tích nguồn và kết nối nền tảng (29/09)

**Một đường duy nhất.** Nút "AI tiếp tục" gọi `POST /api/projects/{id}/steps/analyze`, đúng bước mà AI điều phối gọi qua `run_step`. Endpoint cũ `POST /api/videos/{id}/reference-analysis` đã gỡ; nút này là nơi duy nhất còn gọi nó. `GET` cùng đường dẫn vẫn giữ để đọc bản phân tích đã lưu.

**Connection Manager** (`platform_connections.py`, panel "Kết nối nền tảng bán hàng" trong tab Công cụ & kết nối). Có hai kiểu kết nối, chọn theo điều mà từng sàn chấp nhận:

| Sàn | Kiểu | Vì sao |
|---|---|---|
| Shopee | **Trình duyệt thật của người dùng** qua Browser Bridge (extension YT Factory trong Cốc Cốc). Không có profile riêng của app | Shopee đẩy mọi trình duyệt tự động sang `/verify/captcha?anti_bot…`, dù đã đăng nhập (đo 29/09) |
| TikTok Shop | **Trình duyệt thật** qua Browser Bridge trước; profile riêng của app (cửa sổ hiện) làm đường thứ hai | Headless bị "Security Check"; trình duyệt thật và cửa sổ hiện đều được phục vụ trang (đo 29/09) |
| Lazada, Tiki, Sendo | Profile riêng của app ở `%LOCALAPPDATA%\YouTubeAIFactory\profiles\<sàn>` | Đọc được qua profile riêng; profile nằm trên ổ C: vì trên ổ F: Chrome bị lỗi quyền truy cập thư mục |

- Trạng thái: `CONNECTED` / `DISCONNECTED` / `NEED_LOGIN` / `EXPIRED` / `NEED_HUMAN_VERIFY` / `ERROR`. `NEED_HUMAN_VERIFY` nghĩa là sàn đòi người vượt một bước kiểm tra (captcha, Security Check); app không tự giải.
- Các nút:
  - **Kết nối** Shopee / TikTok Shop: **không** mở trình duyệt tự động. App liệt kê trình duyệt có extension; nút "Mở … trong Cốc Cốc" nhờ extension mở một tab thường. Người dùng đăng nhập hoặc tự xác minh, rồi bấm "Kiểm tra". Riêng TikTok có thêm lựa chọn "Dùng trình duyệt riêng của app (cửa sổ hiện)".
  - **Kiểm tra**:
    - Shopee: extension đọc trang chủ Shopee; thấy tên tài khoản ở đầu trang thì `CONNECTED`.
    - TikTok: đọc lại trang sản phẩm gần nhất đã được phục vụ (trang chủ TikTok hay bị Security Check hơn trang sản phẩm). TikTok không bắt đăng nhập để xem, nên được phục vụ trang là đủ để `CONNECTED`.
  - **Kết nối** Lazada/Tiki/Sendo: mở cửa sổ profile riêng; người dùng tự đăng nhập, app nhìn đầu trang để nhận ra.
  - **Ngắt kết nối**: xoá profile riêng của sàn đó. Với phiên trong trình duyệt thật, app chỉ thôi dùng, không đăng xuất người dùng.
- ProductReader:
  - Shopee: đọc thẳng dữ liệu trang → trình duyệt thật qua extension → profile riêng (dự phòng, **không tự thử lại** sau khi đã gặp captcha) → `NEED_HUMAN_VERIFY` / `NEED_LOGIN`.
  - TikTok Shop: đọc thẳng dữ liệu trang → **phiên đang kết nối** → extension bất kỳ → profile riêng (cửa sổ hiện; sau một lần bị Security Check thì 30 phút sau mới tự thử lại) → `NEED_HUMAN_VERIFY`.
  - Lazada/Tiki/Sendo: đọc thẳng dữ liệu trang → profile riêng → extension → `NEED_*`.
  - Gặp captcha thì trả `NEED_HUMAN_VERIFY` ngay, không lặp.
- **Dữ liệu lưu của một lần đọc** (vào `source_facts` của bản phân tích): tên, giá đang hiển thị, giá gốc gạch ngang, mức giảm như trang ghi, ảnh, người bán, số sao, số đánh giá, số đã bán (khi trang có ghi), mã sản phẩm, URL chuẩn, phiên đã dùng, `captured_at`.
  - Giá TikTok **khác theo phiên**: cùng sản phẩm, cùng giờ, trình duyệt đã đăng nhập hiện ₫9.999, profile riêng chưa đăng nhập hiện ₫11.546. Vì vậy mỗi giá luôn đi kèm phiên và thời điểm đọc.
- **Browser Bridge không heartbeat.** Extension tự nối khi khởi động. Cốc Cốc cho nó ngủ khi rảnh; có việc thì yêu cầu nằm chờ và được đẩy khi extension tự nối lại (tối đa khoảng 1 phút). Extension (bản 1.3.1) chỉ đọc hoặc mở tab 5 sàn trên, không có quyền cookie.
  - Tên trình duyệt lấy theo tiến trình thật đang giữ kết nối, vì Cốc Cốc tự khai là "Google Chrome".
  - Trang được đọc trong một cửa sổ riêng thật sự hiển thị, vì trong tab chạy nền Shopee không tải giá và tiêu đề.
- AI chỉ thấy dạng `shopee: CONNECTED via extension:coccoc`, qua `youtube_factory_list_connections`, `get_connection_status` và `read_product`. Không có cookie, mật khẩu hay đường dẫn profile.

| Mục | Trạng thái | Bằng chứng |
|---|---|---|
| Nút và AI cùng vào `run_step("analyze")` | **VERIFIED** | Endpoint cũ đã gỡ; test giao diện |
| Bài báo đọc thân bài thay vì phần mô tả | **VERIFIED** | Dự án 66: 9.083 ký tự (trước 151) |
| Ghi đúng provider, `options.provider` có tác dụng | **VERIFIED** | Dự án 65 chạy với `claude_code_cli`, brief ghi đúng |
| Lazada: giá hiển thị trên trang | **VERIFIED** | 267.000₫ qua `profile:lazada`; không lấy nhầm mức 299.000₫ trong câu khuyến mãi |
| Shopee `CONNECTED via extension:coccoc`, đọc A/B, mở lại app, đọc lại A | **VERIFIED** | Loa MoMo 229.000 (gốc 450.000, −49%); lót chuột Deli 29.000 (gốc 63.000, −54%); đọc lại A 5,7 giây sau khi mở lại |
| `run_step("analyze")` Shopee dự án 68 | **VERIFIED** | DB: `read_status=OK`, `session=extension:coccoc`, giá 119.000 VND |
| TikTok `CONNECTED via extension:coccoc` | **VERIFIED** | Kiểm tra qua Cốc Cốc trên trang sản phẩm đã đọc: 5,4 giây |
| TikTok đọc A/B, mở lại app, đọc lại A | **VERIFIED** | Bàn chải ₫9.999 (gốc 26.000₫, −62%); móc treo ₫11.899 (gốc 39.800₫, −70%); shop "Shop Gia Dụng Tú Anh"; đọc lại A 6,2 giây sau khi mở lại |
| `run_step("analyze")` TikTok dự án 74 và 75 | **VERIFIED** | DB dự án 75: giá, giá gốc, giảm giá, người bán, 4.3 sao, 23.7K đã bán, mã sản phẩm, `session=extension:coccoc`, `captured_at` |
| TikTok trang chủ bị Security Check | **VERIFIED** | Trả `NEED_HUMAN_VERIFY`, không tự giải, không lặp |
| AI tự chọn đường khác khi đường đầu hỏng | **VERIFIED** | Task `agt_d0832968…` (dự án 75): `extension:googlechrome` → 424 → `list_connections` → `extension:coccoc` → đạt; cũng `agt_abe78e…` (dự án 74) |
| AI báo `blocked` đúng khi không còn đường | **VERIFIED** | Task `agt_f46241…` (dự án 68, lúc Shopee chưa đăng nhập) |
| Bridge không heartbeat, tự thức nhận việc | **VERIFIED** | Yêu cầu gửi lúc đang ngủ, trả kết quả sau 19,8 giây |
| Profile riêng của app cho Shopee | **Bị Shopee chặn** | `/verify/captcha?anti_bot…` dù người dùng đăng nhập; không còn được đề nghị khi Kết nối |
| Nhận biết đăng nhập của Tiki / Sendo | **UNVERIFIED** | Chưa đo đầu trang thật của hai sàn này |

Sau đó Bước 1 được làm lại giao diện (`e80e679`): một nút "Phân tích" chạy `run_step("analyze")`, kết quả hiện theo từng loại nguồn. Trạng thái đang chạy do server giữ; chạy trùng trả 409; tải lại trang thì theo dõi tiếp.

---

## 10. Nguồn tham khảo — "Thêm nguồn" một ô, Channel Intelligence (30/09–01/10)

Commit `09b5525`, `6ccb716`, `886eb9d`.

- **`source_kind` là một cột duy nhất** trên `videos`: `video` / `article` / `product` / `image_collection` / `audio` / `web` (`source_kinds.py`). Importer nào biết thì ghi lúc tạo dòng; mọi nơi sau đó chỉ đọc cột này. `for_row` giữ luật cũ cho dòng có từ trước khi có cột.
- **Ô "Thêm nguồn"** chỉ nhận link hoặc file; người dùng không phải chọn loại trước. `source_detector.py` đoán loại từ rẻ đến đắt và **không hỏi model**:
  1. dạng URL hoặc MIME;
  2. bảng site của yt-dlp (offline);
  3. đọc metadata;
  4. Product Reader.
- **Định danh nguồn** (`source_identity.py`): đọc id gốc của nền tảng (kênh, video) để nghiên cứu được; không đưa khoá do app tự đặt ra làm id thật.
- **Channel Intelligence** (`channel_research.py`, `knowledge_store.py`, `freshness.py`):
  - kênh được nghiên cứu một lần rồi cập nhật dần;
  - mọi con số do code tính từ YouTube Data API, không hỏi model;
  - độ tươi tính lúc đọc, theo TTL riêng từng loại dữ liệu.
- **Quyền riêng tư:** không lưu tên, handle, channel id, avatar hay profile URL của người bình luận; `@mention` bị xoá trắng.

## 11. Bước 2 · Kế hoạch (Phase 3) — đã commit

Commit `54148db` (backend + hardening), `08c5ed0` (UI). Đây là **nguồn sự thật** cho mọi bước sau.

```text
AnalysisResult → ResearchReport → InsightReport → ProjectPlan → Feasibility
```

- **Research** (`research_collectors.py`, `research_evidence.py`, không dùng model):
  - Thu thập video tương tự, mẫu bình luận, phụ đề, trang web; tái dùng dữ liệu còn tươi.
  - Nguồn bị chặn (403, challenge, tường đăng nhập) ghi `collector_status=blocked` và không sinh evidence.
  - Video lạc đề bị đánh độ liên quan thấp, không được làm chỗ dựa cho insight.
- **Insight** (`insight_engine.py`, 1 lượt gọi model):
  - Sinh insight và 2–4 góc nội dung (angle).
  - Code tự tính lại sample size, số nguồn, độ tin cậy; từ chối evidence id bịa và câu kiểu "viral vì…".
  - Insight không có evidence chỉ được giữ dưới dạng **giả thuyết**.
- **Plan** (`plan_engine.py`, 1 lượt gọi model):
  - Chọn angle; đặt khán giả, hook, `content_structure` (section kèm số giây), CTA, chiến lược sản xuất.
  - Platform, tỉ lệ khung, output profile, ngôn ngữ và thời lượng lấy từ cài đặt dự án, không lấy từ model.
  - Code tự viết `factual_guardrails`, `claims_to_avoid`, `claims_needing_proof`.
  - Feasibility tính bằng code.
- **`project_planner.run`:**
  - Có các mode `auto` / `full` / `reason` / `replan`; dùng chung một lượt sửa (repair).
  - `primary_angle_id` cho phép chọn góc khác rồi lập lại kế hoạch, không nghiên cứu lại.
  - Kế hoạch thành `stale` khi analysis, research hoặc insight mới hơn.
- **Trạng thái plan:** `completed` / `needs_user_decision` / `blocked` / `stale` (+ `draft` khi mới có khung nghiên cứu). **Chỉ `completed` mới tính Bước 2 xong.**
  - Ánh xạ từ feasibility: `ok` / `adjusted` → completed; `needs_attention` → needs_user_decision; `blocked` → blocked.
- **API:** `POST /steps/plan`, `GET /api/projects/{id}/plan` (có trường `resources`: dự án có gì, app sẽ làm gì, còn thiếu gì).
- **UI Bước 2:**
  - Các angle hiện dưới dạng lựa chọn ngang hàng; phần nghiên cứu gập trong "Chi tiết nghiên cứu".
  - Trạng thái đang chạy do server giữ.
  - **Bước 3 chỉ mở khi plan `completed`**, đi đường nào cũng vậy; dự án cũ chưa có plan sẵn sàng thì mở ở Bước 2.
- **Đo thật:** mỗi lần lập kế hoạch mất 2–3,5 phút, gần như toàn bộ là hai lượt gọi Codex CLI. Dự án 78 có plan v5 `completed` trong DB thật (**VERIFIED**).

## 12. Bước 3 · Kịch bản — Script Engine (COMPLETE: Phase 1 + 2 + UI, CHƯA COMMIT)

### 12.1 Script Engine (`script_engine.py`, mới)

```text
ProjectPlan (completed) → 1 lượt gọi model (+ tối đa 1 lượt sửa) → ScriptDocument → kiểm tra bằng code
```

- **Không** nghiên cứu lại, không lập lại kế hoạch, không tự chọn angle, thời lượng hay platform. Không gọi web search, `folklore_research` hay writer cũ.
- **ScriptDocument (canonical)** gồm:
  - `title`, `language`;
  - `plan{plan_id, plan_version, primary_angle_id…}`, `target_duration_seconds`, `estimated_seconds`;
  - `hook{spoken_lines, on_screen_text}`;
  - `sections[{plan_section_id s1…sN, spoken_lines[{speaker,text}], on_screen_text, estimated_seconds, insight_ids, evidence_ids}]`;
  - `cta`, `checks`, `validation`, `missing_information`, `limitations`.
- **Không có** `visual_prompt`, camera, shot, transition hay B-roll: những thứ đó thuộc Storyboard (Bước 5).
- **Kiểm tra bằng code:**
  - đúng angle; đủ section, đúng thứ tự;
  - thời lượng tính từ số từ theo tốc độ đọc của ngôn ngữ (lệch tổng tối đa ±15%; mỗi section không vượt quá max(ngân sách × 1,5, ngân sách + 5 giây));
  - evidence và insight id phải tồn tại;
  - số liệu phải có trong nguồn (trừ số nhỏ ≤10);
  - giá sản phẩm phải khớp giá đã đọc, đọc trong vòng 24 giờ, và mỗi câu nói giá giữ `captured_at`;
  - không nói điều nằm trong `claims_to_avoid`; không nói giả thuyết như sự thật;
  - không có chỉ dẫn hình ảnh.
- **Lưu trữ:** bảng `project_scripts` thêm 7 cột: `plan_id`, `plan_version`, `insight_report_id`, `language`, `estimated_seconds`, `document_json`, `engine_version`. Các cột cũ `hook` / `intro` / `main_content` / `cta` **luôn được ghi lại từ document**: `intro` rỗng, `main_content` = mọi section mỗi câu một dòng, `cta` = chỉ phần CTA.
- **Trạng thái kịch bản** (`current_script`):

| Trạng thái | Khi nào |
|---|---|
| `completed` | khớp `plan_id` + `plan_version` của plan hiện hành, và plan đang `completed` |
| `stale` | viết trước khi có kế hoạch, hoặc cho một version cũ hơn của plan, hoặc plan hiện không sẵn sàng; nếu id/version không khớp kiểu khác thì là "mismatch" |
| `invalid` | bị sửa (PATCH, chat) khiến vi phạm kế hoạch; vẫn được lưu nhưng không được dùng tiếp |

- **Engine hợp lệ:** `script-phase1` (engine viết) và `agent-draft` (bản do agent hoặc người dán vào, đã kiểm text và thời lượng nhưng chưa map được theo section, nên `plan_alignment: not_checked`).

### 12.2 Một đường tạo kịch bản dài (Phase 2)

| Đường | Đi qua |
|---|---|
| `POST /steps/script`, `POST /script/generate`, MCP `youtube_factory_run_step` | `run_step("script")` |
| `POST /script/draft` (UI cũ) | adapter → `run_step("script")`; từ chối 422 nếu request cố đặt angle, thời lượng, cấu trúc, CTA, audience, guardrail, platform hoặc tỉ lệ khung; `model` và `use_web_research` bị bỏ qua và liệt kê trong `ignored_fields` |
| Automation, vai Script Agent | `run_step("script")`, không dùng prompt riêng |
| Chat agent, vai script | được hướng dẫn gọi `youtube_factory_run_step` với step `script` |
| `/scripts/import`, MCP `save_script` vào dự án có plan | `run_step` dạng `draft`, kiểm theo plan |
| `/script/chat` | `run_step` dạng `revision`: chỉ sửa kịch bản hiện hành, giữ nguyên plan |
| `PATCH /api/scripts/{id}` | `script_engine.revise`: diff theo dòng → ghi lại vào document → kiểm lại → ghi lại các cột legacy; không đổi được `plan_id` / `plan_version` |
| `/director-draft` (writer → storyboard) | trả 409 với dự án có plan |

- Gate của bước script: thiếu plan, plan `needs_user_decision` / `blocked` / `stale` → 409; `force` hoặc `draft` không mở được.
- Một bước script đang chạy thì lần chạy thứ hai trả 409 (`_SINGLE_RUN_STEPS`). Trạng thái chạy và các giai đoạn đọc được qua `GET /steps` và `GET /script` (`generation`).
- Short đi kèm (`create_standalone_short`) là option của `run_step("script")`: viết từ kịch bản chuẩn, hướng mặc định là angle của plan; là variant `short`, không phải kịch bản dài thứ hai.

### 12.3 "Luồng Kế hoạch" là gì

`_in_plan_workflow(project)` = dự án **có plan hoặc có analysis của nguồn**. Dự án ngoài luồng (chỉ có kịch bản dán tay, không có nguồn để lập kế hoạch) giữ hành vi cũ. Ranh giới này do Claude đề xuất và **chưa được người dùng xác nhận rõ**.

### 12.4 Writer cũ

`writer.py` và `/api/videos/{id}/writer` **không xoá**. Script Engine và Storyboard **không đọc** `scene_blueprints` hay `visual_prompt` của writer cũ.

### 12.5 UI Bước 3 — xong (03/10)

Trước đây nút "Viết kịch bản" gọi `/api/videos/{id}/writer` (tốn một lượt model, chạy cả nghiên cứu folklore) rồi mới gọi `/script/draft`. Lượt gọi đó đã được bỏ. Hiện nay:
- Nút "Viết kịch bản" gửi **một** `POST /api/projects/{id}/steps/script`, tức `run_step("script")`. Nút không còn gọi `/api/videos/{id}/writer` hay `/script/draft`.
- Trang hiển thị ScriptDocument: hook, các section, CTA, thời lượng ước tính so với mục tiêu, lỗi kiểm tra.
- Trạng thái do server trả qua `GET /api/projects/{id}/script` (`state`, `current`, `blocked_reason`, `write_blocked_reason`, `generation`); trang không tự suy luận lại. Thông điệp 409 được hiển thị nguyên văn câu của server.
- Sửa lời đi qua PATCH `/api/scripts/{id}`.
- Làn Short đọc `provenance` và `blocked_reason` từ `GET /short-script`; Short làm từ kịch bản cũ thì các nút phía sau bị khóa.
- Test: `tests/step3_script_ui.test.cjs` (22, chạy code trang thật với server giả), `tests/test_step3_ui.py` (17).
- Writer cũ vẫn được dùng ở trang Thư viện (AI Writer) và ở phần đề xuất metadata xuất bản; Bước 3 không đọc nó.

## 13. Production gate (Phase 2.1 + 2.2, CHƯA COMMIT)

### 13.1 Một gate dùng chung

- **Logic:** `script_engine.production_block(plan, script, running)`. Thứ tự kiểm tra: plan có → plan `completed` → không có lượt viết kịch bản đang chạy → có script → script không invalid → script không stale hay mismatch. **`force` không mở được.**
- **Mức artifact** (Phase 2.2): `script_engine.artifact_block(row, current)`.
  - Một dòng kịch bản dài phải **chính là** kịch bản hiện hành; job làm cho một phiên bản cũ hơn bị từ chối (`superseded`).
  - Một Short phải mang provenance khớp kịch bản và plan hiện hành.
- **Lớp bọc trong `main.py`:**
  - `_script_gate()`;
  - `_require_current_script()` (trả 409 ở mức dự án);
  - `_artifact_gate()` / `_require_current_artifact()` (mức artifact);
  - `_production_block()` (không ném lỗi, dùng cho hook).
- Dự án **ngoài luồng Kế hoạch** đi qua gate mà không bị chặn (giữ hành vi cũ).

### 13.2 Gate ở API (Phase 2.1, mở rộng ở 2.2)

Với dự án trong luồng Kế hoạch, các đường sau đã khóa; gate chạy **trước** mọi lượt gọi model, mọi job, file hay dòng DB:
- `/shots/generate`, `/timeline/generate` (bản dài; bản `short` kiểm provenance), `/timeline/from-dialogue`;
- `/jobs` (voice, render, cả variant short) và `/jobs/{id}/retry` (kiểm đúng dòng kịch bản của job cũ);
- `/script/translate`;
- `/publish` và `/publications/{id}/retry` (Short đang publish phải đúng provenance);
- `/short-script` và `/short/plan`;
- `/orchestrate` chế độ plan (chế độ agent không chặn ở cửa vào vì mục tiêu có thể là viết lại kịch bản; các tool nó gọi đều có gate);
- `run_step` cho **mọi** bước sau script, kể cả khi agent tự đưa danh sách cảnh hoặc segment vào;
- automation: vai Media Agent, và hook tự dựng sau QC;
- **nhóm A (Phase 2.2):** `/scene-jobs`, `/scene-jobs/batch`, `/scene-jobs/{id}/retry`, MCP `youtube_factory_generate_image/gif/video`, `edit-beats/{i}/generate`, `POST /edit-plan` (và `/timeline/plan-visuals`, vốn gọi vào nó), `/timeline/plan-source-cues`, `edit-beats/plan`, `/thumbnails/generate`, `/premiere-export`.

**Cố ý để mở** (đã đối chiếu code):

| Nhóm | Đường | Vì sao để mở |
|---|---|---|
| B — sửa thứ đã có | `edit-plan/approve`, PATCH cảnh trong edit-plan, `edit-plan/apply`, `edit-beats/apply`, `edit-plan/fallback` (gán ảnh nền một màu), `/timeline/cleanups`, sửa tay shots/timeline | chỉnh sửa, không sinh nội dung mới |
| C — chỉ đánh giá | `/script/review`, `/voice/review` | không sinh artifact |
| D — nguồn / nghe thử | `/voice-previews` (đọc câu mẫu cố định, không đọc kịch bản), `/videos/{id}/transcript/translate` (dịch transcript nguồn của Bước 1) | không phải sản xuất từ kịch bản |

### 13.3 Gate ở worker (Phase 2.2)

Một job xếp hàng lúc kịch bản còn mới có thể được nhận **sau khi** plan hoặc kịch bản đã đổi. Vì vậy mỗi worker hỏi lại gate ngay **sau khi claim, trước mọi tác vụ tốn kém**, qua hook `set_production_gate(callback)` được nối trong `main.py`:

| Worker | Vị trí | Khi bị chặn |
|---|---|---|
| `production_worker.py` `ProductionWorker._process` (voice, render, render Short, export) | sau `claim_project_job`, trước mọi `run_*_job` | job `error` + lý do; job nghe thử giọng (`voice_preview`) được miễn |
| `scene_generator.py` `SceneGenerationWorker._process` | sau `claim_scene_generation_job`, trước khi viết prompt (lượt gọi model) và trước provider | ghi khoản sử dụng là `failed` (không tính credit), job `error` |
| `publisher.py` `PublisherWorker._process_due` | sau `claim_project_publication`, trước `upload_video` | publication `error` + lý do |

Không có trạng thái mới: job bị chặn dùng `error` sẵn có, phân biệt bằng nội dung lý do. File và audio đã tạo trước đó không bị đụng tới.

### 13.4 Provenance của Short (Phase 2.2, không migration)

- **Short độc lập** (`project_scripts`, `variant="short"`):
  - `plan_id` / `plan_version` ghi vào hai cột đã có;
  - `source_script_id`, `source_script_version`, `plan_id`, `plan_version` lưu trong `document_json` = `{"kind": "short_provenance", …}`;
  - `script_engine.decode()` chỉ đọc document của kịch bản dài, nên Short không bị coi là kịch bản chuẩn.
- **Short cắt lại** (`project_shorts.plan_json`): key `provenance`. `ShortPlan.from_dict` bỏ qua key lạ, nên plan cũ vẫn đọc được.
- **Hợp lệ** khi provenance khớp id + version của kịch bản hiện hành và của plan hiện hành. Sai thì trả 409 với "Short này được tạo từ một phiên bản kịch bản cũ. Hãy tạo lại Short từ kịch bản hiện tại."
- `GET /api/projects/{id}/short-script` trả thêm `provenance`, `current`, `blocked_reason`.
- Short tạo trước Phase 2.2 trong dự án có plan không có provenance, nên bị chặn và phải tạo lại (có chủ ý).

### 13.5 Thông điệp lỗi chuẩn

Bộ thông điệp nằm trong `script_engine.CONTINUE_MESSAGES`; đường nào cũng trả cùng câu.

| Lý do | Thông điệp |
|---|---|
| Thiếu plan | Bạn cần hoàn thành Kế hoạch trước khi tiếp tục. |
| Plan chờ quyết định | Kế hoạch hiện cần bạn quyết định trước khi tiếp tục. |
| Plan bị chặn | Kế hoạch hiện chưa thể thực hiện, chưa thể tiếp tục. |
| Plan cũ | Kế hoạch đã cũ vì dữ liệu bên dưới đã thay đổi. Hãy lập lại kế hoạch trước khi tiếp tục. |
| Đang viết kịch bản | Kịch bản đang được tạo. Vui lòng chờ lượt hiện tại hoàn tất. |
| Chưa có kịch bản | Chưa có kịch bản viết từ Kế hoạch hiện tại. Hãy viết kịch bản trước khi tiếp tục. |
| Stale | Kịch bản này thuộc một kế hoạch cũ. Hãy viết lại kịch bản trước khi tiếp tục. |
| Invalid | Kịch bản hiện tại không còn hợp lệ với kế hoạch. Hãy viết lại kịch bản trước khi tiếp tục. |
| Mismatch | Kịch bản hiện tại không khớp với kế hoạch hiện tại. |
| Việc làm cho phiên bản cũ | Việc này được tạo cho một phiên bản kịch bản cũ. Hãy chạy lại từ kịch bản hiện tại. |
| Short cũ | Short này được tạo từ một phiên bản kịch bản cũ. Hãy tạo lại Short từ kịch bản hiện tại. |

Bước script tự nó dùng các câu "…trước khi viết kịch bản", ví dụ "Bạn cần hoàn thành Kế hoạch trước khi viết kịch bản."

### 13.6 Dự án mẫu (kiểm trên bản sao DB thật, model giả)

| Dự án | Hiện trạng trong DB thật | Kết quả |
|---|---|---|
| 57 (legacy) | Nguồn nhập bằng link (`web-cc2aba7cb65fe6e0`), writer cũ, kịch bản 93/94 (25/09), 6 cảnh, timeline, video cuối; plan v6 kiểu cũ `needs_attention` = đang chờ quyết định | Mọi đường đi tiếp trả 409; worker từ chối job render/voice của kịch bản 94; không gọi model; dữ liệu không đổi |
| 78 (chuẩn) | Bài báo; plan v5 `completed` (id 16), angle `ang-2`, 100 giây, 5 section [10, 24, 27, 20, 19]; **chưa có kịch bản trong DB thật** | Kịch bản v5 → voice chạy. Short v5 có provenance (kịch bản 98, phiên bản 1, plan 16, v5). Plan lên v6 → worker từ chối job render v5. Viết lại (kịch bản 100, v6) → render chạy. Short v5 bị chặn, Short v6 chạy |

**Chưa nghiệm thu với model thật:** Script Engine và các gate mới chạy bằng test và trên bản sao DB với model giả; chưa chạy trên app thật với Codex/Claude.

## 13b. Bước 4 · Giọng đọc — Edge + Gemini 3.8 TTS (COMPLETE / REAL-VERIFIED, CHƯA COMMIT)

Edge **không bị thay**. Bước 4 thêm hai model Gemini vào cùng pipeline: cùng render settings, cùng `/jobs`, cùng `ProductionWorker` / `run_voiceover_job`, cùng timeline audio. Short dùng cùng các provider.

| Provider key | Vendor / model | File |
|---|---|---|
| `edge_tts` | microsoft / `edge-tts` (mặc định, không đổi) | mp3 |
| `google_gemini_3_8_flash_tts` | google / `gemini-3.8-flash-tts` | wav |
| `google_gemini_3_8_flash_lite_tts` | google / `gemini-3.8-flash-lite-tts` | wav |
| `pyvideotrans`, `voxcpm` | không đổi | wav |

**File mới:** `youtube_monitor/gemini_tts.py` (adapter), `youtube_monitor/tts_catalog.py` (danh sách engine: vendor, model, đuôi file).

**Adapter Gemini:**
- Request:
  - `POST https://generativelanguage.googleapis.com/v1beta/interactions`, key chỉ nằm trong header `x-goog-api-key`. Key không vào URL, log, lỗi, ledger, file hay MCP.
  - `input[].content[]` = transcript nguyên văn của cảnh. Kiểu đọc nằm riêng trong `annotations[{type: "speech_metadata", style}]`.
  - `generation_config.speech_config = [{voice, language}]`; khi có 2 người nói thì dùng `{mode: "conversational", speakers: [...]}` (tối đa 2).
- Kết quả: `steps[model_output].content[audio].data` là WAV base64 (24 kHz, mono, 16-bit), ghi nguyên như nhận, chỉ đúng một header RIFF.
- Retry kỹ thuật 3 lần (chờ 2 s, 5 s). Rate limit chờ theo `retryDelay` (tối đa 30 s). Hết quota trong ngày thì ghi vào `usage_limits`. Lỗi auth và lỗi input dừng ngay; lỗi input không đánh dấu model là "Lỗi kết nối".

**Danh mục giọng** (`GET /v1beta/voices?type=prebuilt&language_code=vi-VN`):
- vi-VN có 40 giọng `vi-vn-*`, **không có Kore**.
- Google tra giọng theo cặp tên + ngôn ngữ, nên giọng catalog được gửi kèm `language` mà catalog ghi cho nó (`vi-VN`); gửi `vi` bị trả 400 "No matching speaker voice found…". Giọng dựng sẵn (Kore…) vẫn gửi `vi`.
- Cache 1 giờ. Đọc lỗi thì 5 phút sau mới hỏi lại. Làm mới bị lỗi thì vẫn trả danh sách cũ (`stale`). Danh mục rỗng không được cache.
- `voice_for`: giọng chưa xác nhận được vì danh mục không đọc được (app vừa khởi động lại và danh mục lỗi) thì **không bị thay bằng Kore**: báo lỗi tạm thời, không đọc cảnh nào. Giọng mà danh mục đọc được nhưng không liệt kê (ví dụ giọng của Edge) thì được thay bằng Kore và ghi `voice_fallback_from`.

**`voice_style`:**
- Migration duy nhất của Bước 4, người dùng đã duyệt: `project_render_settings.voice_style TEXT NOT NULL DEFAULT ''`. Áp lên DB thật khi mở app ngày 04/10.
- Giá trị đi vào `speech_metadata.style`, không bao giờ chen vào lời.
- `voice_prompt_text` giữ nghĩa cũ (lời của file giọng mẫu VoxCPM) và không dùng cho Gemini. `voice_model` không đổi nghĩa.

**Worker và ledger:**
- Mỗi cảnh, với mọi engine, ghi một dòng ledger `voice.tts`: vendor, model, voice, language, `voice_language` (ngôn ngữ thực gửi kèm giọng), speaker, segment, job, `audio_path`; với Gemini thêm style, usage token và số lần thử.
- Việc ghi ledger không bao giờ làm hỏng job.

**API:**
- `GET /api/tts/voices?provider=&language=`: không truyền `provider` thì là danh sách Edge như cũ.
- `GET /api/voice-previews/gemini/{provider}?voice&style&language`:
  - đọc câu mẫu cố định, không đọc kịch bản, không tạo job;
  - cache ở `01_DU_AN/_voice_previews/gemini-{model}-{voice}-{sha1(style|language)}.wav`;
  - ghi ledger `voice.preview`.
- `GET /api/production-queue` trả thêm `tts_providers` (Sẵn sàng / Chưa cấu hình / Hết quota / Lỗi kết nối). Thông tin đọc từ dữ liệu sẵn có, không gọi Google.
- `/jobs` từ chối (400) model chưa có key hoặc đã hết quota.

**UI Bước 4 (redesign 04–05/10, ít chữ):**
- Bố cục 2 cột (1 cột trên màn hẹp).
  - Trái: *Công nghệ* (4 card gọn: Edge, Gemini Flash, Gemini Flash-Lite, TTS cục bộ mở ra pyVideoTrans / VoxCPM2), *Giọng nói* (tìm, lọc Nam/Nữ/Khác, danh sách cuộn riêng), *Nâng cao* (gập: phụ đề, ngôn ngữ, công cụ VoxCPM, Chi tiết kỹ thuật).
  - Phải: *Đang chọn* (engine, giọng, kiểu đọc, Đã lưu/Chưa lưu), *Kiểu đọc* (Gemini, 7 preset chỉ điền `voice_style`) hoặc *Tốc độ* (Edge/cục bộ), *Nghe thử* (trình phát; bấm lại cùng giọng không gọi lại server).
- Các `<select>` cũ vẫn là nguồn sự thật: card và danh sách chỉ đặt giá trị select rồi phát `change`, nên mọi cơ chế lưu đã nghiệm thu chạy như cũ.
- Danh mục giọng chỉ được hỏi khi người dùng chọn một model Gemini (một lượt tải cho mỗi model và ngôn ngữ).
- Khi đổi nhà cung cấp, cài đặt chỉ được lưu **sau khi** danh sách giọng đã tải và đã chọn giọng. Trước đây có lỗi: app lưu giọng giữ chỗ Kore trong khi UI hiện giọng khác; lỗi này đã sửa.
- Giọng của từng nhóm engine được nhớ khi đi Gemini → Edge → Gemini (trước đây bị đổi sang giọng đầu danh sách).
- Giọng Gemini dự án đã lưu vẫn được giữ, kể cả khi danh mục không liệt kê giọng đó.
- Thông tin kỹ thuật chỉ nằm trong tooltip hoặc mục "Chi tiết".

**Nghiệm thu bằng API thật (04/10) — REAL-VERIFIED:**

| | Flash | Flash-Lite |
|---|---|---|
| Nghe thử Kore, Kore + style | HTTP 200, WAV 24 kHz mono, 1 header RIFF | HTTP 200 |
| Nghe thử giọng catalog `vi-vn-advisor-6` | HTTP 200, gửi `language: vi-VN` | HTTP 200, có style |
| Worker trên DB tạm (1 cảnh, câu tiếng Việt mẫu, có style) | `completed`, có `audio_path`, ledger `voice.tts` đúng | `completed`, có `audio_path`, ledger đúng |
| Request gửi đi | transcript không đổi, style trong `speech_metadata` | như Flash |

- Mỗi lượt gọi mất khoảng 5–8 giây.
- Token: Kore khoảng 400–490; giọng catalog khoảng 1600.
- Có 6 lần nghe thử thật, ghi ở ledger `voice.preview` #111–116 của DB thật. Không có job sản xuất nào trên DB thật.
- Lỗi thật tìm được và đã sửa trong lúc nghiệm thu:
  - giọng catalog gửi `vi` thay vì `vi-VN`;
  - ô chọn giọng bị trống khi danh mục không có Kore;
  - lưu nhầm giọng giữ chỗ khi đổi nhà cung cấp;
  - giọng catalog bị thay bằng Kore khi danh mục không đọc được sau khi khởi động lại app.
- UI đã kiểm trên app thật:
  - Khi chưa mở dự án: không có gì được ghi.
  - Khi có dự án (kiểm trên bản sao DB): lưu đúng; sau khi khởi động lại app, giọng và style vẫn giữ đúng.

**Test:**
- `tests/test_gemini_tts.py` (38), `tests/test_step4_tts.py` (28), `tests/step4_gemini_voices.test.cjs` (7, node), `tests/step4_voice_desk.test.cjs` (19, node).
- Mọi lời gọi Google trong test đi vào `httpx.MockTransport` với key giả.

**Giới hạn của Bước 4:**
- Chi phí chưa đo chính xác: `estimated_cost` là 0, mới chỉ ghi số token.
- Chất lượng style cần người nghe đánh giá: style được gửi đúng field, nhưng số token đầu vào không đổi dù có hay không có style.
- Mỗi cảnh đọc bằng một giọng; tên người nói chỉ được ghi lại.

## 14. Trạng thái git / test / DB (04/10)

- **Nhánh `master`, repo chưa có remote** (`git remote -v` trống). Commit gần nhất: `08c5ed0 feat: finalize step 2 planning workflow`.
- **Bước 3 + Bước 4 chưa commit tại thời điểm bắt đầu commit.** Đường dẫn dưới đây tính từ `_HE_THONG/app/`, trừ hai file tài liệu ở root repo.
- **Bước 3 (Phase 1 → 2.2 + UI):**
  - mới: `youtube_monitor/script_engine.py`; `tests/script_fixtures.py`; `tests/test_script_engine.py` (31); `tests/test_script_paths.py` (29); `tests/test_production_gate.py` (23); `tests/test_production_gate_worker.py` (18, chạy thẳng `_process` thật của từng worker); `tests/test_step3_ui.py` (17); `tests/step3_script_ui.test.cjs` (22, node); `tests/fixtures/project78_plan_v5.json` (snapshot chỉ đọc);
  - sửa: `steps.py`, `scene_generator.py`, `publisher.py`, `ai_desktop_mcp.py`, `tool_layer/registry.py`;
  - sửa test cũ cho khớp hợp đồng mới: `test_steps`, `test_short_script`, `test_shot_planner`, `test_dialogue_timeline`, `test_reup_clip_sync` (chỉ fixture); `test_writer_quality`, `studio_navigation.test.cjs` (UI Bước 3);
  - tài liệu: `AI_CONNECTION_HANDOFF.md` (file này), `PROJECT_STATUS.md` (mới; bản tóm tắt trạng thái cho Claude).
- **Bước 4 (Giọng đọc):**
  - mới: `youtube_monitor/gemini_tts.py`, `youtube_monitor/tts_catalog.py`; `tests/test_gemini_tts.py` (38); `tests/test_step4_tts.py` (28); `tests/step4_gemini_voices.test.cjs` (7, node); `tests/step4_voice_desk.test.cjs` (19, node);
  - sửa: `static/core.js`, `static/library.js`, `static/app.css`.
- **Dùng chung Bước 3 + 4** (trong file có hunk của cả hai bước): `main.py`, `database.py`, `production_worker.py`, `static/studio-lanes.js`, `static/publish.js`, `static/project-detail.js`, `templates/index.html`.
- **File `_tmp_*` ở root là của người dùng** (từ 21/09, không thuộc Bước 3 hay 4): không xoá, không commit.
- **Test:** chạy từ `_HE_THONG/app` bằng `python -B -m pytest -q -p no:cacheprovider tests` (khoảng 6 phút).
  - Toàn bộ (05/10): **2105 đạt, 2 đỏ, 9 bỏ qua** (230 subtest).
  - Hai test đỏ có từ trước, không sửa: `test_burned_in_marks` (0 lần gọi thay vì 1) và `test_shorts` (`'sound_cues' != 'fit'`).
- **DB thật** `_HE_THONG/data/youtube_monitor.db`:
  - Phase 1 (03/10) đã **vô tình thêm 7 cột** vào `project_scripts`: một script trích fixture mở DB thật qua `Database()`, và `initialize()` tự chạy migration. Chỉ thêm cột có giá trị mặc định; 51 kịch bản cũ nguyên vẹn.
  - Từ Phase 2 tới UI Bước 3 hash không đổi: `8cc459dbe9c051269297295e55951e49`.
  - 04/10, Bước 4: migration đã được duyệt `project_render_settings.voice_style TEXT NOT NULL DEFAULT ''`, sau đó hash là `acc04da25339327d30999813a7caab81`; chỉ thêm cột, mọi bảng khác giống hệt.
  - Hiện tại: `31ac5e63abc30bb423a000b902489963`. So với trước migration, chỉ khác ở cột `voice_style` (6 dòng settings giữ nguyên, giá trị rỗng) và 6 dòng ledger `voice.preview` #111–116 của 6 lần nghe thử thật. Không có job sản xuất, 0 dòng `voice.tts`, không ghi nhận hết quota Gemini.
- **Quy tắc DB:**
  - Không mở DB thật bằng `Database()`, và không `import youtube_monitor.main` ngoài pytest khi chưa trỏ `YOUTUBE_DATA_DIR` / `YOUTUBE_DB_PATH` / `PRODUCTION_ARTIFACT_DIR` sang thư mục tạm.
  - Đọc DB thật chỉ bằng `sqlite3` với `mode=ro`, hoặc qua bản sao (backup API); xoá bản sao sau khi dùng; ghi hash trước và sau.
  - Cần migration DB thật thì **dừng và hỏi**.
  - Kiểm UI có ghi settings của dự án: chạy app với `YOUTUBE_DB_PATH` trỏ tới bản sao DB; `/api/health` trả về `database` để xác nhận app đang dùng bản sao.
- **Secret:** lần quét gần nhất (04/10) sạch. `GEMINI_API_KEY` chỉ nằm ở `_HE_THONG/config/.env` (đã gitignore, git không theo dõi). Không gọi Gemini API thật khi người dùng chưa cho phép.
- **Test dùng DB tạm chung một phiên:**
  - `TestClient` khởi động worker thật: mock `production_worker.enqueue` / `scene_generation_worker.enqueue`; đừng để job `queued` sót lại.
  - Đừng kết thúc job cảnh bằng lỗi kiểu "hết hạn mức" trong fixture, vì sẽ mở circuit breaker của provider đó cho các test sau.

## 15. Cách làm việc với người dùng

- Người dùng gửi đặc tả theo **phase**, viết tiếng Việt, rất cụ thể. Họ luôn nói rõ phạm vi KHÔNG làm (thường là: không UI, không commit, không push, không khởi động app, không sửa Bước 1/2, không redesign Storyboard, không xoá `writer.py`, không sửa 2 test đỏ cũ).
- Sau mỗi phase: chạy test liên quan + toàn bộ suite, quét secret, xem git diff, kiểm hash DB, báo cáo đúng format người dùng yêu cầu, rồi **dừng chờ review**. Commit chỉ khi được bảo, với message người dùng đưa.
- Gặp đường bypass hay quyết định chưa chắc: **không tự mở rộng phạm vi**; ghi rõ endpoint, call path và lý do vào báo cáo.
- Ràng buộc an toàn cố định:
  - không đưa cookie, password, token cho AI hay vào log;
  - không tự giải captcha hay vượt anti-bot; trả `NEED_LOGIN` / `NEED_HUMAN_VERIFY`;
  - không lưu dữ liệu định danh người bình luận;
  - không in API key.
- AGENTS.md: không tự khởi động app; chỉ chạy khi người dùng bảo, cho chạy ở cửa sổ người dùng thấy được, và tắt hẳn khi xong. Cách chạy: `Start-Process CHAY_YOUTUBE_AI_FACTORY.bat`; cách tắt: dừng các tiến trình có `CHAY_YOUTUBE_AI_FACTORY|youtube_monitor|uvicorn` (trừ pytest), rồi kiểm tra cổng 8787 đã trống.

## 16. Còn tồn tại, quyết định đang chờ, việc tiếp theo

**Đang chờ người dùng:**
1. Review rồi commit Bước 3 + Bước 4. Người dùng sẽ ra lệnh commit riêng, với message của họ.
2. Quyết định migration cho phase "final.mp4 provenance + publish artifact gate". Audit A và B (chỉ đọc, 03/10) đã xong, kết quả **FAIL**:
   - **A — provenance của `final.mp4`:**
     - P0: `/publish` bản dài luôn lấy file cố định `01_DU_AN/<id>/04_XUAT_BAN/final.mp4` (`_publication_video_path`), không hỏi file đó dựng từ kịch bản nào; publication không lưu script, render hay hash, nên bản đăng đã xếp lịch hoặc retry có thể tải lên file cũ;
     - P1: PATCH sửa kịch bản tại chỗ; gói manual-package không có gate.
   - **B — worker sidecar bên ngoài** (antigravity, web; `database.EXTERNAL_SIDECAR_PROVIDERS`): P2, claim/complete của sidecar không có gate (gate ở API vẫn chặn lúc tạo job).
   - Phase sửa đã dừng ở bước 1: **MIGRATION_REQUIRED**. Đề xuất thêm `project_jobs.provenance_json` và `project_publications.artifact_json` (`TEXT DEFAULT ''`). Chưa sửa code.
   - **C — provenance xuyên suốt** Plan → Script → Storyboard → Timeline → Voice → Render → `final.mp4` → Publish, và **D — route/worker còn tạo artifact** mà chưa có provenance hoặc gate: chưa audit riêng.
3. Xác nhận ranh giới "luồng Kế hoạch" (mục 12.3) và cách đặt câu cho trường hợp plan bị chặn / plan cũ (mục 13.5).

**Giới hạn đã biết:**
- Provenance của `final.mp4` (mục 2.A ở trên).
- Worker sidecar bên ngoài (mục 2.B).
- Job bị gate chặn dùng trạng thái `error` (không có trạng thái riêng).
- Bản nháp (agent hoặc dán tay) chưa map theo section. PATCH không chuyển được một dòng sang section khác.
- Kiểm claim và số liệu vẫn là heuristic (trùng ≥80% từ nội dung; số >10 phải có trong nguồn).
- **Metadata khi xuất bản** (mô tả, hashtag, đề xuất AI) vẫn đọc từ writer cũ; để Phase 7 / Publish xử lý.
- **Bước 4:**
  - chi phí Gemini TTS chưa đo chính xác (`estimated_cost` là 0, mới chỉ ghi token);
  - chất lượng style cần người nghe đánh giá;
  - mỗi cảnh đọc bằng một giọng;
  - khi danh mục giọng không đọc được, job dùng giọng catalog dừng với lỗi tạm thời. Đây là hành vi có chủ ý: không thay giọng (mục 13b).
- Vai `media` của pipeline 5 vai vẫn tự tạo scene job (không qua `run_step("media")`); nay bị gate chặn ở cả API lẫn worker khi kịch bản không hiện hành.
- `/orchestrate mode=agent` chưa có nút trên giao diện.
- GPT Work chỉ được hướng dẫn qua mô tả tool và `instructions`; dòng "ưu tiên tool youtube_factory_*" nên do người dùng thêm vào `AGENTS.md`.

**Backlog người dùng bảo chỉ ghi lại, chưa sửa:**
- Giá Shopee lúc đọc được lúc không; tên sản phẩm Shopee đôi khi là tiêu đề chung "Shopee Việt Nam…".
- Audio tiếng Anh bị bước kiểm "phân tích có khớp nguồn không" (`analysis_is_about_the_source`) từ chối khi chủ đề viết bằng tiếng Việt.
- Chưa làm tab HÀNG ĐỢI, tab THƯ VIỆN.
- Độ liên quan mới chấm cho video tương tự, chưa chấm trang web.
- `limitations` của bước phân tích đôi khi chứa ghi chú vận hành và trôi vào `must_not_invent` của plan.

**Hướng tiếp theo dự kiến (chưa được giao):**
- provenance của `final.mp4` và publish artifact gate (chờ quyết định migration ở mục 2);
- Bước 5: Storyboard dựng từ section của ScriptDocument;
- chạy thật Script Engine trên dự án 78 bằng model thật;
- metadata xuất bản (Phase 7).
