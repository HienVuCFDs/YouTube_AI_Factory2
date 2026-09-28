# AI CONNECTION HANDOFF — YouTube AI Factory

Cập nhật: **2026-09-29**, mốc "Agent Orchestrator". Bản trước (28/09) đã lỗi thời ở các điểm: pipeline CLI "unavailable", "chưa có agent loop", "fallback chưa hoạt động".

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

- **Kích hoạt:** `POST /api/projects/{id}/orchestrate` với `{"mode":"agent","intent":…,"target_steps":[…],"allow_spend":false,"allow_overwrite":false,"max_rounds":4,"tool_budget":40}`. App tạo task vai `orchestrator` trong **hàng đợi có sẵn**. Chế độ `plan` cũ vẫn giữ cho giao diện.
- **Hoàn thành:** task chỉ `completed` khi `_verify_goal` xác nhận từ DB. Không có chấm chéo cho vai này, và không chạy lại y hệt khi hỏng.
- **Hai loại retry:**
  - `llm_client._with_retry` chỉ lo lỗi kỹ thuật tạm thời (đợi 5/20/45 giây), giữ nguyên.
  - Vòng agent lo **đổi chiến lược**: provider khác, bước tiên quyết, runtime khác.

## 4. MCP `youtube_ai_factory` (`ai_desktop_mcp.py`, stdio → HTTP 127.0.0.1:8787)

- **45 tool**, không đổi. `initialize` trả `instructions`: "dùng tool youtube_factory_*, không bấm giao diện".
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
| Claude CLI làm Orchestrator Agent qua MCP | **UNVERIFIED** | Lệnh và cờ có test; chưa lượt thật nào tới lượt Claude vì Codex luôn sẵn sàng |
| Đổi runtime khi não hỏng (Codex → Claude) | **UNVERIFIED** (có test) | Chưa xảy ra thật |
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

## 9. Còn tồn tại

- **Vai `media` của pipeline 5 vai** vẫn tự tạo scene job, không đi qua `run_step("media")` (nhát 2c trong kế hoạch).
- **GPT Work** chỉ được hướng dẫn qua mô tả tool và `instructions`. Dòng "ưu tiên tool youtube_factory_*" nên được thêm vào `AGENTS.md`. Claude Code không được tự sửa file luật đó, nên việc này do người dùng làm.
- **`/orchestrate mode=agent`** chưa có nút trên giao diện; hiện chỉ gọi qua API.
