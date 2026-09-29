# AI CONNECTION HANDOFF — YouTube AI Factory

Cập nhật: **2026-09-29**, mốc "Agent Orchestrator" + xác minh Claude CLI làm AI điều phối; bổ sung mục 9 "Bước 1 – Phân tích nguồn và kết nối nền tảng". Bản trước (28/09) đã lỗi thời ở các điểm: pipeline CLI "unavailable", "chưa có agent loop", "fallback chưa hoạt động".

Nhãn trạng thái:

| Nhãn | Nghĩa |
|---|---|
| **VERIFIED** | đã chạy thật hoặc đo thật |
| **PARTIAL** | chạy một phần |
| **UNVERIFIED** | có code và test, chưa chạy thật |

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

- **Kích hoạt:** `POST /api/projects/{id}/orchestrate` với `{"mode":"agent","intent":…,"target_steps":[…],"runtime":"auto","allow_spend":false,"allow_overwrite":false,"max_rounds":4,"tool_budget":40}`. `runtime` (`auto` / `codex_cli` / `claude_code_cli` / `astra` / `claude`) chọn AI điều phối đi trước; các AI còn lại vẫn đứng sau làm dự phòng. App tạo task vai `orchestrator` trong **hàng đợi có sẵn**. Chế độ `plan` cũ vẫn giữ cho giao diện.
- **Hoàn thành:** task chỉ `completed` khi `_verify_goal` xác nhận từ DB. Không có chấm chéo cho vai này, và không chạy lại y hệt khi hỏng.
- **Hai loại retry:**
  - `llm_client._with_retry` chỉ lo lỗi kỹ thuật tạm thời (đợi 5/20/45 giây), giữ nguyên.
  - Vòng agent lo **đổi chiến lược**: provider khác, bước tiên quyết, runtime khác.

## 4. MCP `youtube_ai_factory` (`ai_desktop_mcp.py`, stdio → HTTP 127.0.0.1:8787)

- **48 tool**: 45 tool cũ cộng 3 tool kết nối nền tảng của Bước 1 (`list_connections`, `get_connection_status`, `read_product`, xem mục 9). `initialize` trả `instructions`: "dùng tool youtube_factory_*, không bấm giao diện".
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

## 7. Trạng thái kết nối

| Mục | Trạng thái | Bằng chứng |
|---|---|---|
| Codex CLI làm Orchestrator Agent qua MCP | **VERIFIED** | Dự án 61 và 66 (28/09), xem mục 8 |
| Claude CLI làm Orchestrator Agent qua MCP | **VERIFIED** | Dự án 61 (29/09), task `agt_64ed…`, `runtime=claude_code_cli`: list_steps → run_step(timeline) → list_steps; model `claude-opus-5` + `claude-haiku-4-5`, 5 lượt, 22,7 giây; DB xác nhận 6 đoạn timeline. Agent tự **không** dùng `force` vì chưa có timeline để ghi đè |
| Đổi runtime khi não hỏng (Codex → Claude) | **UNVERIFIED** (có test) | Chưa xảy ra thật. Khi xảy ra, log ghi `round.runtime_failed` cùng quyết định chọn runtime kế tiếp |
| Pipeline 5 vai chạy bằng CLI | **PARTIAL** | Dự án 72: research, script, director đạt (`astra`, `claude` chấm chéo 8 điểm). `media` trượt 6/10 vì chất lượng, giữ nguyên. `qc` chưa tới |
| GPT Work nạp MCP, thấy 45 tool | **VERIFIED** | log `~/.codex/logs_2.sqlite` |
| GPT Work gọi tool `youtube_factory_*` | **UNVERIFIED** | 0 lần trong `~/.codex/sessions`; ngày 28/09 nó bấm giao diện. Chưa có bằng chứng GPT Work đọc `instructions` của MCP |
| Claude Cowork nạp MCP | **Chưa kết nối** | Claude Desktop ghi đè config lúc 17:18:46 28/09. Phải sửa khi Claude Desktop **đã tắt hẳn** |
| App đánh thức GPT Work / Cowork | **Không có đường** | Chúng chỉ làm khi người gõ hoặc Automation tới lịch (hiện 0 Automation) |
| Claude in Chrome (Cốc Cốc) đọc Shopee/TikTok trong phiên Claude Code tương tác | **VERIFIED** | Đủ giá, 28/09 |
| `claude -p --chrome` chạy nền | **Bị chặn** bởi chính sách an toàn của Claude Code | — |

## 8. Bằng chứng tự phục hồi (regression đã nghiệm thu)

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

## 10. Còn tồn tại

- **Vai `media` của pipeline 5 vai** vẫn tự tạo scene job, không đi qua `run_step("media")` (nhát 2c trong kế hoạch).
- **GPT Work** chỉ được hướng dẫn qua mô tả tool và `instructions`. Dòng "ưu tiên tool youtube_factory_*" nên được thêm vào `AGENTS.md`. Claude Code không được tự sửa file luật đó, nên việc này do người dùng làm.
- **`/orchestrate mode=agent`** chưa có nút trên giao diện; hiện chỉ gọi qua API.
