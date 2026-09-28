# Audit hệ thống — những gì đã đo, những gì mới là phỏng đoán

Ghi lại **kết quả đo thật**, tách khỏi những gì chỉ mới viết code chứ chưa chứng minh.
Mỗi mục ghi rõ: đo bằng cách nào, số liệu ra sao, và chỗ nào còn là giả thuyết.

Cập nhật: 2026-09-29

---

## 1. Lỗi đã tìm ra và sửa, kèm bằng chứng

### 1.1 App vứt bỏ danh sách cảnh mà AI đã viết — mọi lần

**Đo:** `script.created_at = 10:42:22.645`, `writer.created_at = 10:42:22.437` — cách nhau **208 mili giây**, do cùng một lệnh tạo ra.
Cổng kiểm tra là `script.updated_at <= writer.created_at`, nên với kịch bản vừa viết xong nó **luôn sai**.

**Hệ quả:** AI chia 6 cảnh sạch → app ném đi → tự cắt `main_content` theo dòng bằng công thức `số_từ / 2.4 + 3`. Đây là nguyên nhân gốc của "kịch bản chưa ổn".

**Sau khi sửa:** 6 cảnh của AI được dùng, mục hook/main/cta suy theo vị trí, thời lượng không bao giờ ngắn hơn câu nó phải đọc.

### 1.2 Giọng đọc đọc to mục lục

**Đo:** video 70 giây có **11 giây và 3 cảnh riêng** chỉ để đọc "Cảnh 3 · Các ngôi sao và nguyên tố".

**Nguyên nhân thật:** không phải AI viết ẩu — **app tự chèn** tiêu đề vào `main_content` ([script_builder.py:35](_HE_THONG/app/youtube_monitor/script_builder.py#L35)), rồi bước sau đọc ngược lại và tưởng là lời thoại.

### 1.3 Cấu hình phân công AI bị xóa trắng vì tên cũ

**Đo:** cấu hình lưu tên `codex_cli`, `claude_code_cli`; `AGENT_IDS` đã đổi sang `astra`, `claude`. Bộ kiểm tra coi tên cũ là sai định dạng và **lặng lẽ bỏ** — mỗi công đoạn còn đúng một AI: `antigravity`, đang hết hạn mức 111 giờ.

**Hệ quả:** app báo "mọi AI được gán đều thất bại" trong khi hai AI khác đang rảnh.

### 1.4 Whisper dùng model gần nhỏ nhất

**Đo trên chính video nguồn, cùng file tiếng:**

| `base` (đang dùng) | `large-v3` |
|---|---|
| "vũ **chụt** được tạo thành" | "**Vũ trụ** được tạo thành" |
| "chúng ta có **hít rộ**, heli" | "chúng ta có **Hydro, Heli**" |
| "hệ mặt **chờ** xuất hiện" | "**Hệ mặt trời** xuất hiện" |
| 6 giây | 10 giây |

Model `large-v3` đã có sẵn trong cache máy. Đổi mất thêm 4 giây cho clip 62 giây.

### 1.5 Phân tích nguồn gọi AI hai lần, không lần nào đủ

**Đo:** `llm_analyzer` chỉ nhận tiêu đề + mô tả + tags (**không có transcript**, dù Whisper vừa chạy), rồi hỏi về SEO. `reference_analyzer` mới thật sự đọc nội dung nhưng **không nằm trong luồng 12 bước** — dự án 57 không hề có bản phân tích `reference` nào.

**Sau khi sửa:** một lần gọi, có transcript **và** contact sheet 12 khung. Kết quả đáng chú ý nhất — AI **dùng chữ trên màn hình để bắt lỗi phiên âm**:

> *"Chữ trong ảnh khác bản phiên âm ở ít nhất hai vị trí: ảnh ghi 'SỰ SỐNG ĐÂM CHỒI NẢY LỘC'"* — Whisper nghe ra "đâm trôi nảy lốc".

### 1.6 Render tuần tự

**Đo trên dự án 57:** 148,8 giây → **95,9 giây** sau khi dựng các cảnh song song. Thành phẩm kiểm bằng contact sheet: đủ 6 ảnh, đúng thứ tự.

### 1.7 Một tiếng động không có trong thư viện làm sập cả bước dựng

`resolve_sound_assets` ném lỗi khi cue không tìm được file, kéo sập toàn bộ việc áp kế hoạch — mất luôn chuyển cảnh và đồ họa vốn dùng được.

---

## 2. Đo khả năng đọc trang bán hàng — 3 sàn, 4 bộ đọc

Đây là phần đo kỹ nhất, vì kết quả **phủ định giả định ban đầu của tôi**.

| Bộ đọc | Lazada | Shopee | TikTok Shop |
|---|---|---|---|
| httpx + JSON-LD | tên, hãng, SKU, **6 ảnh** — `offers` **không có trường giá** | "Please enable JavaScript" | — |
| Playwright headless | thân trang không load | **đá về trang chủ** | captcha kéo mảnh ghép |
| Codex CLI (web search) | ❌ | ❌ | — |
| Claude Code CLI + WebFetch | ✅ **280.000₫ · 4,9 sao · 1.073 đánh giá** | ❌ | ❌ |
| **GPT Work** (người dùng thử tay) | chưa thử | ✅ **119.000đ · gạch 238.000đ · ALPHA STORE VN · 4.7 sao · danh mục** | chưa thử |

**Kết luận đo được:**
- Giá **không tồn tại ở bất kỳ đâu trong HTML mà app với tới được** — kể cả JSON-LD của Lazada
- Shopee chặn mọi bộ đọc trong app; **GPT Work đọc được**
- TikTok chưa bộ đọc nào lấy đủ

**Hai đường tôi thử và loại:**
- ffmpeg seek thẳng vào stream YouTube → `403 Forbidden`
- yt-dlp tải từng đoạn (`download_ranges`) → cũng 403
- Mojeek làm nguồn tìm kiếm dự phòng → trả trang captcha
- Wikipedia làm nguồn dự phòng → 403 với mọi User-Agent thử trên máy này

---

## 3. Kết nối AI điều phối (cập nhật 2026-09-29)

Chi tiết đầy đủ ở `AI_CONNECTION_HANDOFF.md`. Tóm tắt:

| Điều | Trạng thái | Bằng chứng |
|---|---|---|
| Hàng đợi app → app chat (`get_next_task` → `complete_task`) | **VERIFIED khi gọi cầu trực tiếp** | Lượt đo 27/09 (`agt_ca235160…`). Không có bản ghi GPT Work tự làm việc này |
| GPT Work nạp MCP, thấy 45 tool | **VERIFIED** | log `~/.codex/logs_2.sqlite` 28/09 |
| GPT Work gọi tool của app | **UNVERIFIED** | 0 lần trong `~/.codex/sessions`; nó bấm giao diện trong trình duyệt tích hợp `iab` |
| Claude Cowork nạp MCP | **Chưa kết nối** | Claude Desktop ghi đè config lúc 17:18:46 28/09 ("Config file written"). Phải sửa khi Claude Desktop đã tắt hẳn |
| **App tự điều phối bằng agent CLI qua MCP** | **VERIFIED** (Codex) | Mục 3.1 |

### 3.1 Agent Orchestrator — đo thật (28/09)

**Tự phục hồi sau phương án hỏng** (dự án 66, mục tiêu `timeline`, không can thiệp tay):

```
list_steps → run_step(script, openai_gpt) ✗ "Thiếu OPENAI_API_KEY"
→ get_ai_runtimes → run_step(script, codex_cli) ✓ → run_step(shots) ✓ → run_step(timeline) ✓
→ list_steps (agent tự kiểm) → _verify_goal từ DB: script 96, 6 cảnh, 6 đoạn / 139 giây
→ task completed · 1 vòng · 7 tool call · 144 giây
```

**Lượt không được tính làm bằng chứng** (dự án 61): Antigravity viết được kịch bản vì quota đã hồi phục, còn bản ghi "hết hạn mức" trong app là dữ liệu cũ. Việc này dẫn tới sửa lỗi ở mục 3.3.

**Pipeline 5 vai bằng CLI** (dự án thử 72):
- research, script, director đạt; `astra` thực hiện, `claude` chấm chéo 8 điểm.
- `media` trượt 2 lần, chấm 6/10 (ngưỡng 8), vì lỗi chất lượng: gán loại "video" cho cảnh mà chính nó ghi là hình tĩnh. **Giữ nguyên thất bại này**; không hạ ngưỡng, không sửa prompt.

### 3.2 Pipeline 5 vai "astra: unavailable" dù CLI sẵn sàng

**Đo:**
- Database có nhiều task lỗi `astra: unavailable | claude: unavailable` (27/09) trong lúc `codex_cli` và `claude_code_cli` đều `ready`.
- Nguyên nhân: `_agent_runtime_available` và `_call_specific_agent_json` chỉ hiểu tên runtime, còn phân công truyền tên agent.

**Sửa:**
- Gom về một bảng duy nhất, `settings.AGENT_RUNTIME` / `runtime_id`.
- Tìm thêm 2 chỗ cùng loại lỗi, nơi lựa chọn của người dùng bị bỏ qua lặng lẽ: phân tích ảnh tham chiếu và chấm cảnh bằng thị giác.
- Tìm thêm 4 hàm chọn provider từng từ chối tên agent.

### 3.3 Quota cũ làm AI bị coi là hết lượt mãi

**Đo:**
- Antigravity bị báo chặn tới 30/09 dù đã chạy được ngày 28/09.
- Ba nơi đọc cùng một bản ghi theo ba cách: readiness chặn cả khi đã quá mốc hồi phục; worker chặn tới mốc mà không bao giờ thử lại; banner bỏ qua bản ghi quá hạn.

**Sửa:** một hàm `usage_limits.limit_state` dùng chung, trả `active` / `probe_due` (thử lại sau 6 giờ) / `reset_passed` / `recovered`.

### 3.4 Retry của pipeline 5 vai lặp lại y hệt

**Đo:** bước nhận việc xoá cột `error`, tức lý do bị chấm chéo trả về, trước khi chạy lại. Vì vậy lần thử 2 không biết mình sai ở đâu. Vai `media` trên dự án 72 hỏng 2 lần cùng một lỗi.

**Sửa:** lý do bị trả về được đưa vào lời gọi của lần thử sau, áp dụng chung cho mọi vai.

---

## 4. Lỗi của chính tôi trong quá trình làm

Ghi lại vì chúng lặp thành mẫu.

**Bốn lần `except` rộng che lỗi của chính người viết:**

| Chỗ | Lỗi thật | Biểu hiện ra ngoài |
|---|---|---|
| `_announce_step` | truyền keyword sai → `TypeError` | app "phát sự kiện" mà không phát gì |
| `read_with_ai` | import sai tên hàm → `ImportError` | "AI không đọc được trang" |
| `_source_contact_sheet` | (đúng thiết kế, có chủ đích) | — |
| `has_profile` | đếm file → mở trang đăng nhập đã sinh 314 file | "đã có phiên" khi chưa đăng nhập |

**Ba lần đi sai hướng, người dùng chặn lại:**
1. Xây trình cào rồi vá bot-wall → trong khi app đã có AI đọc web tốt hơn
2. Xây cả cơ chế đăng nhập Shopee → xem sản phẩm chưa bao giờ cần tài khoản
3. Đổi tên CLI thành tên sản phẩm → gộp nhầm hai vai trò khác nhau (điều phối vs kỹ sư)

**Một lần giao việc sai chỗ:** giao việc đọc trang cho `astra`, mà `astra` là runtime worker trong app tự chạy bằng CLI. Task chết với `"astra: unavailable | claude: unavailable | antigravity: unavailable"`.

**Một lần test gọi AI thật:** bộ test chạy 262 giây vì 3 test gọi Claude CLI. Đã mock, còn 0,1 giây.

**Lần thứ hai test gọi AI thật (28/09):**
- Một test tạo task `orchestrator` trong database test dùng chung.
- Worker nền do `TestClient` của `test_main` khởi động đã nhặt task đó và chạy **agent Codex thật**. Lúc ấy app không chạy nên mọi lệnh gọi tool đều hỏng, nhưng vẫn tốn quota.
- Đã sửa: test giả lập `create_agent_task`, không ghi task vào database dùng chung.

**Một lỗi cú pháp do sinh code bằng script:** ký tự xuống dòng bị ghi thành xuống dòng thật bên trong f-string. Import bắt được ngay.

---

## 5. Còn là phỏng đoán — chưa chứng minh

| Điều | Vì sao chưa chắc |
|---|---|
| Google TTS đọc tiếng Việt tốt hơn Edge | **Chưa có API key**, chưa phát ra tiếng nào |
| Piper chạy được | **Chưa tải model** `vi_VN-*.onnx` |
| Profile Chrome đã đăng nhập giúp đọc Shopee | Chưa ai đăng nhập; code có nhưng chưa thử |
| ~~Claude in Chrome đọc được Shopee~~ | **VERIFIED 28/09:** đọc đủ, kể cả giá, trên Cốc Cốc của người dùng, trong phiên tương tác |
| GPT Work / Claude Cowork làm được việc trong hàng đợi | Các việc vẫn `queued`; app không đánh thức được chúng |
| Claude CLI làm Orchestrator Agent | Có lệnh và test, chưa lượt thật nào tới lượt Claude |
| Đổi runtime giữa lượt khi não hỏng | Có test; chưa xảy ra thật |
| Song song tạo ảnh giúp nhanh hơn | Chỉ nhanh khi trải qua **nhiều provider**; một provider vẫn tuần tự |

---

## 6. Hai test đỏ có sẵn từ trước

Không dính các sửa đổi trong đợt này:

| Test | Nguyên nhân |
|---|---|
| `test_an_unmarked_reup_gets_its_source_measured` | 0 lần gọi thay vì 1 |
| `test_the_renderer_can_fill_a_frame_as_well_as_pad_it` | `_segment_arguments` đổi thứ tự tham số |

`test_high_level_pipeline_creates_project_and_durable_research_task` đã sửa (2026-09-28) khi chuyển AI điều phối, vì nằm đúng vùng đang sửa.

Lưu ý: `test_shot_planner` có hai test lúc đỏ lúc xanh khi chạy cả bộ, chạy riêng thì xanh — phụ thuộc thứ tự vì cả bộ dùng chung một database tạm.

**Tổng (29/09, sau mốc Agent Orchestrator): 1476 đạt, 2 đỏ, 9 bỏ qua.** 48 test mới trong `tests/test_agent_orchestration.py`.
