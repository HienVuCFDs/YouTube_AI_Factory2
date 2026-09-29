# Kế hoạch hợp nhất luồng làm video

Ngày lập: 2026-09-25

## 1. Vấn đề

App đang có **hai bản cài đặt song song cho cùng một quy trình**, và chúng không dùng chung code.

| Đường | Ai lái | Đi qua đâu |
|---|---|---|
| Giao diện 7 bước | người bấm | REST API trong `main.py` |
| MCP (40 tool) | AI điều phối | **cùng REST API đó** — đã hợp nhất sẵn |
| Pipeline 5 agent | tự động | **gọi thẳng `database.*`, bỏ qua REST** |

Bằng chứng, trong `_execute_agent_task` của `main.py`:

```python
database.create_project_script(...)
database.create_project_shots(project_id, script_id, shots, force=True)
database.create_project_timeline(project_id, script_id, segments, force=True)
database.create_scene_generation_job(...)
```

Nó tự viết lại chuỗi bước, kèm `force=True` — tức là **ghi đè mà không đi qua các chốt kiểm tra** mà đường giao diện phải tuân theo (kiểm tra kịch bản đã cũ, kiểm tra sẵn sàng render, chính sách xác nhận trước khi tiêu tiền).

Hệ quả đang thấy:

- Sửa lỗi ở đường giao diện thì đường tự động vẫn hỏng y nguyên.
- Hai đường cho ra kết quả khác nhau trên cùng một dự án.
- Người dùng xen tay giữa chừng thì đường tự động không biết, vì nó không đọc cùng trạng thái.
- Mỗi "agent" là **một lần gọi model, một lượt, trả JSON rồi xong** — không gọi tool, không xem lại, không tự sửa.

Thêm một tầng phân mảnh nữa: `WF Content` và `WF Reup` đang là hai nhánh code, trong khi bản chất chỉ là *tham số* của cùng các bước.

## 2. Mục tiêu

Một luồng duy nhất, ba cách lái cùng đi vào đó:

- **Bấm tay** từng bước trên giao diện.
- **Tự động** — nhận một prompt (sau này đến từ kênh khác) rồi tự chạy.
- **AI điều phối** qua MCP, tự quyết bước kế tiếp.

Ba cách này phải cho **cùng một kết quả**, vì chạy **cùng một đoạn code**.

## 3. Kiến trúc đích

Đơn vị duy nhất là **bước** (`step`). Mỗi bước được cài đặt **một lần**:

```
run_step(project_id, step, options) -> result
```

Ba cách lái trở thành ba cửa mỏng:

| Cửa vào | Gọi gì |
|---|---|
| Nút trên giao diện | `POST /api/projects/{id}/steps/{step}` |
| Auto nhận prompt | bộ lập kế hoạch chọn chuỗi bước → cùng endpoint |
| MCP | tool `run_step` → cùng endpoint |

Hai khái niệm được gộp lại:

- **Workflow** thôi làm nhánh code, thành tham số của bước.
- **5 agent** tan vào bảng phân công AI theo công đoạn (`agent_assignments`) đã có sẵn. "Script Agent" chỉ là *AI nào nghĩ cho bước kịch bản* — app đã có khái niệm đó, không cần khái niệm thứ hai.

## 4. Danh sách bước

Mỗi bước ánh xạ vào endpoint **đang có**. Giai đoạn đầu `run_step` chỉ gọi lại chúng, không viết lại gì.

| Bước | Việc | Endpoint hiện có | Công đoạn AI |
|---|---|---|---|
| `analyze` | Phân tích nguồn, transcript | `/api/videos/{id}/analyze`, `/reference-analysis`, `/transcript/auto` | `orchestration` |
| `research` | Tra cứu web, tìm nguyên liệu | **chưa có — phải làm mới** | `orchestration` |
| `script` | Viết kịch bản, lưu bản nháp | `/api/videos/{id}/writer` → `/api/projects/{id}/script/draft` | `script` |
| `script_review` | Soát kịch bản, soát độ trung thành | `/script/review`, `/script/fidelity-check` | `quality_review` |
| `shots` | Chia kịch bản thành cảnh | `/api/projects/{id}/shots/generate` | `storyboard` |
| `timeline` | Dựng timeline từ cảnh | `/api/projects/{id}/timeline/generate` | — (tất định) |
| `voice` | Tạo giọng đọc | `/api/projects/{id}/jobs` (`voiceover`) | — |
| `voice_review` | Nghe lại, đối chiếu lời | `/api/projects/{id}/voice/review` | `quality_review` |
| `media` | Tạo ảnh/video cho từng cảnh | `/scene-jobs`, `/scene-jobs/batch` | `image_generation`, `video_generation` |
| `edit_plan` | Lập kế hoạch dựng | `/edit-plan` → `/approve` → `/apply` | `storyboard` |
| `render` | Dựng MP4 | `/api/projects/{id}/jobs` (`render`) | — |
| `publish` | Kiểm tra và đăng | `/publish-checklist` → `/publish` | `quality_review` |

Mỗi bước khai báo dạng dữ liệu, gồm: khoá, tên hiển thị, endpoint, công đoạn AI, điều kiện tiên quyết, và có tiêu tiền/lượt hay không.

## 5. Năm nhát làm, không đập xây lại

Mỗi nhát phải chạy được và test xanh trước khi sang nhát sau.

### Nhát 1 — Dựng lõi `run_step`, chưa đổi hành vi

**Làm gì**

- Thêm `youtube_monitor/steps.py`: khai báo danh sách bước dạng dữ liệu + hàm `run_step`.
- Thêm `POST /api/projects/{id}/steps/{step}` và `GET /api/projects/{id}/steps` (trạng thái từng bước: xong / thiếu điều kiện / đang chạy).
- Giai đoạn này `run_step` **chỉ gọi lại đúng handler đang có**. Không sửa logic nào.
- Mỗi lần chạy ghi một dòng vào `orchestrator_steps` — bảng nhật ký đã dựng tuần này.

**Nghiệm thu**

- Toàn bộ test hiện tại vẫn xanh, số lượng không đổi.
- Gọi `run_step("shots")` cho ra kết quả **giống hệt** bấm nút "Tạo lại storyboard".
- `GET /steps` báo đúng bước nào đã xong trên một dự án có sẵn.

**Test mới**: `tests/test_steps.py` — mỗi bước gọi đúng handler; bước thiếu điều kiện tiên quyết bị từ chối kèm lý do.

### Nhát 2 — Pipeline tự động dùng lại lõi

Đây là nhát thu được nhiều nhất.

**Làm gì**

- Viết lại `_execute_agent_task`: mỗi vai gọi `run_step` thay vì tự gọi `database.*`.
- **Xoá** phần trùng lặp: tạo script, tạo shots, tạo timeline, tạo scene job trong `_execute_agent_task`.
- Bỏ `force=True`; pipeline đi qua đúng chốt kiểm tra như người bấm.
- Phần AI *nghĩ* (viết kịch bản, chia cảnh) giữ nguyên — nó vốn là việc của bước.

**Nghiệm thu**

- Chạy pipeline trên một dự án và bấm tay trên dự án khác cùng nguồn → **cùng cấu trúc kết quả**.
- `_execute_agent_task` không còn dòng `database.create_*` nào.
- Nhật ký `orchestrator_steps` ghi cả lượt tự động lẫn lượt bấm tay, cùng định dạng.

**Rủi ro**: pipeline đang dựa vào `force=True` để ghi đè. Bỏ đi thì một dự án đang dở có thể bị từ chối vì "kịch bản đã cũ". Xử lý: `run_step` nhận `options.force`, và pipeline truyền vào **có chủ đích ở đúng bước cần**, không phải mặc định.

### Nhát 3 — Giao diện gọi cùng lõi

**Làm gì**

- Mỗi nút trong 7 bước chuyển sang gọi `POST /steps/{step}`.
- Giữ nguyên các endpoint cũ một thời gian để không gãy MCP và extension.
- Thanh 7 bước đọc `GET /steps` để biết bước nào xong, thay vì tự suy từ dữ liệu rời rạc.

**Nghiệm thu**: bấm tay hết 7 bước ra video hoàn chỉnh; nhật ký ghi đủ 7 dòng.

### Nhát 4 — AI điều phối lái cùng lõi

**Làm gì**

- MCP thêm `list_steps` và `run_step`.
- Thêm các tool còn thiếu để AI làm trọn việc của người dùng:
  - `search_web`, `search_media` — hiện **0 tool tra cứu**.
  - `get_scene_frame`, `get_contact_sheet`, `get_render_preview` — hiện **0 tool nhìn**; AI đang duyệt mù.
  - `get_scene_speech_timing` — Whisper đã đo mốc từng chữ, chưa đưa ra ngoài.
- Bước `research` được cài đặt thật, dùng `search_web`.

**Nghiệm thu**: từ Claude Code hoặc app ChatGPT, một câu lệnh "làm video từ link này" chạy được trọn chuỗi, và AI **tự xem lại bản render** trước khi báo xong.

### Nhát 5 — Workflow thành tham số

**Làm gì**

- `WF Content` / `WF Reup` chuyển từ nhánh code sang bộ tham số của bước (chiến lược hình ảnh, luật viết lại, có cắt clip nguồn hay không).
- Thêm workflow mới = thêm dữ liệu, không sửa code.

**Nghiệm thu**: đổi workflow trên một dự án và chạy lại → hành vi đổi đúng, không chỗ nào rẽ nhánh bằng `if workflow == "reup"` nữa.

## 6. Việc không làm trong kế hoạch này

Ghi rõ để khỏi sa đà:

- **Không** mở rộng từ vựng dựng của FFmpeg (chuyển cảnh, chuyển động khung). Khi chuyển động đến từ clip do Veo/Flow sinh ra thì việc này không phải nút thắt.
- **Không** xây lại giao diện. Nút vẫn ở chỗ cũ, chỉ đổi chỗ chúng gọi tới.
- **Không** bỏ pipeline tự động. Nó vẫn có vai trò: chạy không người trông.
- **Không** đụng renderer, provider gateway, hệ thống job — những phần này đang chạy tốt.

## 7. Rủi ro đã biết

| Rủi ro | Cách chặn |
|---|---|
| Nhát 2 bỏ `force=True` làm gãy dự án đang dở | `force` thành tuỳ chọn của bước, truyền có chủ đích |
| Hai endpoint song song (cũ và `/steps`) gây lẫn | Giữ cũ tới hết nhát 4, rồi mới bỏ, có test chặn |
| Bước `research` gọi web làm chậm hoặc lỗi mạng | Lỗi mạng không được làm hỏng cả chuỗi; nghiên cứu là tuỳ chọn |
| AI chạy tự do tiêu hết lượt tạo media | Giữ nguyên chính sách xác nhận hiện có; bước nào tiêu tiền phải khai báo trong bảng bước |

## 8. Thứ tự đề nghị

Làm **nhát 1 và 2**, rồi dừng lại để kiểm tra thực tế. Sau hai nhát đó đã thấy được điều quan trọng nhất: **tự động và bấm tay cho cùng kết quả vì chạy cùng code**. Ba nhát còn lại làm tiếp khi đã yên tâm.

## 9. Nhật ký thực hiện

### 2026-09-25 — Nhát 1 xong

**Đã làm**

- Thêm `youtube_monitor/steps.py`: danh sách 12 bước dạng dữ liệu, kèm điều kiện tiên quyết và cờ "bước này có tiêu lượt không". Không import `main`, nên đọc và test được mà không cần khởi động app.
- Thêm vào `main.py`: `run_project_step()` — mỗi bước gọi lại **đúng handler mà nút bấm đang gọi**, không viết lại logic nào.
- Thêm `_steps_done()`: đọc trạng thái từ **thứ có thật** (có bản kịch bản chưa, cảnh đã có file giọng chưa, đã có MP4 chưa) chứ không đọc cột trạng thái — nên một bước làm tay bên ngoài app vẫn được nhận ra.
- Thêm hai endpoint: `GET /api/projects/{id}/steps` (trạng thái từng bước) và `POST /api/projects/{id}/steps/{step}`.
- Mọi lượt chạy — kể cả lượt **bị từ chối** — đều ghi vào `orchestrator_steps`.

**Sửa một thiếu sót phát hiện khi viết test**: lời từ chối "chưa làm xong bước trước" ban đầu không được ghi vào sổ. Nhưng đó đúng là thứ AI điều phối cần đọc để biết phải làm gì trước. Nay ghi lại với trạng thái `refused`.

**Kiểm thử**: `tests/test_steps.py` — 18 test, xanh. Toàn bộ: 1219 đạt, 5 đỏ (đúng 5 lỗi có sẵn từ trước, không phát sinh).

**Chưa đổi gì về hành vi.** Giao diện, pipeline và MCP vẫn chạy y như cũ. Lõi mới nằm cạnh, chưa ai bắt buộc phải dùng.

### 2026-09-25 — Nhát 2a, 2b xong

**Sửa một chỗ sai trong khai báo của nhát 1.** Bước `script` đang đòi `analyze` xong trước. Nhưng dự án khởi từ một ý tưởng thì không có nguồn nào để phân tích, nên bước viết kịch bản sẽ bị chặn vĩnh viễn. Phân tích nay là *ngữ cảnh*, không phải cổng chặn.

**Bước nhận việc người khác đã làm.** `script`, `shots`, `timeline` nay nhận thêm nội dung có sẵn qua `options`. Agent viết kịch bản xong thì đưa cho bước lưu, thay vì tự ghi thẳng vào database. Phần AI *nghĩ* giữ nguyên, phần *ghi dữ liệu* gom về một chỗ.

**Pipeline tự động dùng lại lõi.** Vai `script` và `director` trong `_execute_agent_task` không còn gọi `database.create_project_script`, `create_project_shots`, `create_project_timeline` nữa — chúng gọi `run_project_step`. Kịch bản do chạy tự động tạo ra giờ là **cùng một hàng dữ liệu, qua cùng các chốt kiểm tra** với kịch bản do bấm nút tạo ra.

**Còn nợ — 2c (vai `media`).** Vai này vẫn tự tạo scene job. Tôi cố ý để lại: nó có khoảng 100 dòng chính sách riêng — định tuyến provider, tạm dừng khi hết provider, chặn khi chạm hạn mức chi phí. Khác với script/shots, nó **không** lách qua kiểm tra; nó có bộ kiểm tra riêng, chặt hơn. Gộp vào bước cần chuyển cả khối chính sách đó, nên để thành một nhát riêng thay vì làm vội.

### 2026-09-25 — Nhát 4 xong phần công cụ cho AI điều phối

Làm trước nhát 3 vì đây mới là thứ phục vụ mục tiêu "AI làm thay tôi", và nó **chỉ thêm, không sửa gì đang chạy**.

**Lái được cùng lõi**: thêm hai tool MCP `list_steps` và `run_step`. AI điều phối nay chạy đúng các bước mà nút bấm chạy.

**Đôi mắt** — `contact_sheet.py` + `GET /api/projects/{id}/contact-sheet` + tool `get_contact_sheet`. Một ảnh duy nhất: các khung lấy đều trên video đã render, hoặc các cảnh hiện có nếu chưa render. Nhịp lấy mẫu tính theo độ dài video, nên clip 10 giây và video 10 phút đều ra cùng số ô. **Đã kiểm chứng thật** bằng ffmpeg: video thử 20 giây cho ra ảnh 12 ô, mở lên nhìn thấy đúng 12 mốc thời gian khác nhau.

**Tra cứu** — `web_research.py` + `GET /api/research/search` + tool `search_web`. Trả về tiêu đề, trích đoạn, link. Lỗi mạng trả về danh sách rỗng chứ không làm hỏng cả lượt chạy — một video không thể vì công cụ tìm kiếm chết mà không làm được nữa. Khi không tra được gì, kết quả **nói thẳng** "đừng coi đây là đã nghiên cứu", vì một model nhận danh sách rỗng có xu hướng lấp chỗ trống bằng trí nhớ rồi trình bày như đã tra cứu.

**Nhịp lời thoại** — `GET /api/timeline/{id}/speech-timing` + tool `get_scene_speech_timing`. Mốc từng chữ do Whisper đo, kèm các chỗ ngắt hơi từ 0,25 giây trở lên — chỗ đặt cắt được mà không giẫm lên lời. Dữ liệu này app đã đo từ lâu nhưng giữ riêng cho mình.

MCP: từ 40 lên **45 tool**.

**Kiểm thử**: 1239 đạt, 5 đỏ — vẫn đúng 5 lỗi có sẵn từ trước.

Một lỗi của tôi bị test bắt được: `contact_sheet.py` gọi subprocess mà không khai báo encoding. Repo có test riêng chặn việc này, vì trên Windows locale mặc định là cp1252 và chữ tiếng Việt trong output sẽ mất. Đã sửa.

### 2026-09-25 — Đủ 12/12 bước chạy được

Ba bước còn khai báo suông nay đã có người chạy.

**`research`** — tra cứu rồi **lưu kết quả lại cùng dự án** (artifact `research`), để bước viết kịch bản hai bước sau đọc được thứ đã tìm thấy, thay vì được dặn "hãy nghiên cứu" rồi tin là nó không bịa. Tra không ra gì thì trả về `researched: false` chứ không lặng lẽ coi như xong. Không có chủ đề thì từ chối, chứ không đi tìm một chuỗi rỗng rồi báo thành công.

**`media`** — gọi lại đúng endpoint tạo hàng loạt mà nút bấm dùng.

**`publish`** — bước duy nhất không thể hoàn tác từ trong app, nên mặc định **chỉ kiểm tra rồi dừng**. Muốn đăng thật phải truyền `confirmed_publish`. Đây **cố ý không dùng chung** cờ `confirmed` của các bước khác: không thứ gì được lên kênh chỉ vì người gọi đã bật cờ cho phép tiêu tiền render. Có test riêng chặn đúng chuyện đó.

Thêm một test bắt lỗi cấu trúc: **mọi bước khai báo đều phải có người chạy**. Trước đó ba bước hiện ra trong danh sách rồi từ chối khi được gọi.

**Kiểm thử**: 1246 đạt, 5 đỏ — vẫn đúng 5 lỗi có sẵn từ trước.

### 2026-09-25 — Chạy thử A–Z thật, và bốn lỗi nó lôi ra

Dựng lại một video từ `youtube.com/shorts/glYtv6VartM`, yêu cầu **tạo ảnh mới, không dùng video nguồn**. Chạy trọn 12 bước qua chính lõi `run_project_step`. Kết quả: video 1920×1080, 61,5 giây, 6 cảnh, 6 ảnh AI mới, lời đọc và phụ đề tiếng Việt. Không một khung hình nào lấy từ video nguồn.

Lượt chạy bắt được bốn lỗi mà không bộ test nào bắt được, vì cả bốn chỉ lộ ra khi các bước nối vào nhau:

**1. Một tiếng động không có trong thư viện làm hỏng cả bước dựng.** AI lên kế hoạch có tiếng nền ambient; thư viện chưa ai nhập file nào; `resolve_sound_assets` ném lỗi và kéo sập toàn bộ việc áp kế hoạch — mất luôn chuyển cảnh, chuyển động máy và đồ họa vốn dùng được. Nay cue nào không tìm được thì bỏ cue đó, ghi lại cảnh báo, phần dựng còn lại giữ nguyên. *Bản dựng đáng giá hơn tiếng động nó không tìm thấy.*

**2. Cấu hình phân công AI bị xóa trắng vì tên cũ.** Các agent từng mang tên CLI chạy chúng (`codex_cli`, `claude_code_cli`). Khi đổi sang `astra`, `claude`, bộ kiểm tra coi tên cũ là **sai định dạng và lặng lẽ bỏ đi** — mỗi công đoạn còn đúng một AI sống sót: `antigravity`, cái đang hết hạn mức 111 giờ. Người dùng đã chọn ba AI cho công đoạn storyboard, nhưng app báo "mọi AI được gán đều thất bại" trong khi hai cái kia đang rảnh. Nay có bảng quy đổi tên cũ sang tên mới. Một test cũ đang **xác nhận chính hành vi sai này**, đã viết lại.

**3. "Đôi mắt" của AI điều phối nhìn nhầm phim.** `contact_sheet` nhận độ dài video từ người gọi; ai quên truyền thì nó lấy **1 khung/giây** — 12 ô đầu là 12 giây đầu, nhưng ảnh trả về trông y hệt ảnh của cả video. Tôi đọc đúng cái ảnh đó và kết luận sai rằng video chỉ có 2 tấm hình. Nay công cụ **tự đo** độ dài; không đo được thì từ chối chứ không đoán. *Một bản tóm tắt trông đáng tin về đoạn phim chưa từng xem là thứ tệ hơn lỗi.*

**4. Giọng đọc đọc to mục lục.** Người viết đặt tiêu đề cảnh trên dòng riêng — "Cảnh 3 · Các ngôi sao và nguyên tố". Bộ lọc tiêu đề có sẵn, nhưng nó chỉ bắt tiêu đề kết thúc bằng **tên mục** (`hook`, `main_content`), không bắt tiêu đề người viết tự đặt tên. Tệ hơn: bộ lọc chỉ canh **đường dự phòng**, còn đường thật sự được dùng — khi AI trả về danh sách cảnh của chính nó — thì lấy lời thoại thẳng, không lọc. Trong video 70 giây có 11 giây và 3 cảnh riêng chỉ để đọc mục lục. Nay lọc cả hai đường, và nhận cả tiêu đề có tên tự đặt — nhưng câu văn thật mở đầu bằng "Cảnh 3 –" thì vẫn giữ, *vì bỏ mất một câu người viết muốn nghe thì thiệt hơn là đọc thừa một cái nhãn.*

**Một điều ghi nhận, không phải lỗi code.** Astra lên kế hoạch dựng hai lượt liền đều trả về `overlays: []` và `effect: static`, dù nó nhận đủ mô tả ảnh, loại hình và word timing đo được bằng Whisper. Lượt đầu (bản 9 cảnh) nó lại dựng đầy đủ thẻ đồ họa. Đây là dao động trong đầu ra của model, không phải chỗ nào trong code bỏ rơi dữ liệu — đã kiểm: kế hoạch model trả về đã rỗng sẵn từ đầu.

**Kiểm thử**: 1254 đạt, 4 đỏ. Bốn cái đỏ là test cũ bám vào chi tiết đã đổi từ trước (đường dẫn `/api/chatgpt/...` nay là `/api/chat-agents/chatgpt_app/...`, `start()` thêm tham số `external_agent`, `_segment_arguments` đổi thứ tự tham số), không dính các sửa đổi trên.

### 2026-09-26 — Sửa xong 7 việc rút ra từ lượt chạy A–Z

**1. Bước viết kịch bản nay nghe phân công AI.** `resolve_writer()` có thứ tự ưu tiên riêng (API key → Codex → Claude → Antigravity) và **chưa bao giờ đọc** phần người dùng phân công cho công đoạn `script`. Chọn AI nào trong giao diện cũng vô nghĩa. Trớ trêu hơn: bản review lưu sau đó lại ghi tên theo phân công — hồ sơ ghi tên một người viết chưa hề viết. Nay đọc phân công trước; agent chỉ chat được (không lái tự động được) coi như "không chọn" chứ không thành lỗi, để kịch bản vẫn được viết.

**2. App đang vứt bỏ danh sách cảnh mà AI đã viết — mọi lần.** Đây là lỗi gốc của "kịch bản chưa ổn", và nó nặng hơn tôi tưởng lúc đầu.

Astra trả về 6 cảnh sạch, có tên mục riêng, kèm lời thoại. Cổng kiểm tra "kịch bản có mới hơn bản phân tích không" so với **thời điểm bản phân tích được ghi**. Nhưng một lượt viết kịch bản ghi bản phân tích *rồi mới* ghi kịch bản, cách nhau **208 mili giây** — nên kịch bản vừa viết xong **luôn luôn** trông mới hơn chính danh sách cảnh của nó. App hỏi AI chia cảnh, ném câu trả lời đi, rồi tự cắt văn xuôi theo dòng bằng công thức `số_từ / 2.4 + 3`.

Dấu hiệu của một lần sửa tay là kịch bản **đổi sau khi được tạo**, nên nay so đúng cái đó. Thêm `blueprints_verified`: chỗ gọi đã kiểm (lời khớp 1.0, phân tích có trước, chưa sửa) thì nói cho bộ chia biết, thay vì để `version > 1` — một con số chỉ nghĩa là "bản ghi thứ hai" — quyết định.

Hai chỗ sửa kèm theo, lộ ra ngay khi danh sách cảnh bắt đầu được dùng: AI đoán **10 giây cho mọi cảnh** trong khi lời thoại cần 16–19 giây (nay mỗi cảnh không bao giờ ngắn hơn câu của chính nó, còn xin dài hơn thì được tôn trọng — đó là lựa chọn nhịp); và tên mục tự đặt ("Mở vấn đề", "Sự sống và tổng kết") bị ép hết thành `main`, mất luôn cách xử lý mở và đóng phim (nay suy ra theo vị trí).

**3. Thêm hai engine giọng đọc.** App khai 3 nhưng chỉ 1 chạy được: `pyvideotrans` chưa sẵn sàng và loại TTS của nó trỏ ngược về edge-tts, `voxcpm` dùng model tiếng Trung/Anh. Nghĩa là **2 giọng, hết**.

- `google_tts.py` — REST, chỉ cần API key, không SDK. 12 giọng vi-VN gồm Chirp3-HD và Neural2. Key nằm trong query string nên lỗi **không bao giờ** nhắc lại URL; có test riêng chặn việc đó.
- `piper_tts.py` — chạy local từ file .onnx, không hạn mức, không mạng. Lời thoại đi vào qua **stdin** chứ không ghép vào dòng lệnh, nên một dấu nháy trong câu không phá được lệnh.

**4. Kế hoạch đòi video thì không được lặng lẽ ra ảnh tĩnh.** Nhánh tạo video chỉ chạy khi có provider video trong danh sách; các cảnh cần chuyển động **rơi xuống ảnh tĩnh không một lời nào**. Cả cuốn phim ra ảnh tĩnh, khác hẳn thứ đạo diễn đã dựng, và dấu hiệu đầu tiên là lúc xem thành phẩm. Nay từ chối và nói rõ bao nhiêu cảnh cần video.

**5. Chạy song song — đo được, không phải ước.**

- *Tạo ảnh*: `SceneGenerationWorker` chạy **một luồng**, mỗi ảnh ~48 giây, 6 ảnh là 5 phút xếp hàng. Nay nhiều luồng, nhưng **mỗi provider một lượt**: provider web lái một profile Chrome, hai job chung profile sẽ tranh nhau. Việc nhận job vốn đã nguyên tử (`UPDATE ... WHERE status='queued'`) nên không cần đổi.
- *Render*: các cảnh là file độc lập nhưng dựng tuần tự. Nay dựng song song, thứ tự khôi phục theo vị trí chứ không theo thứ tự xong. **Đo thật trên chính dự án 57: 148,8 giây → 95,9 giây.**

**6. Kế hoạch dựng phẳng bị hỏi lại.** Astra hai lượt liền trả về `overlays: []`, `effect: static` dù có đủ mô tả ảnh, loại hình và word timing Whisper đo được. Không phải code đánh rơi dữ liệu — kế hoạch model trả về rỗng sẵn. Nay app hỏi lại **đúng một lần**, nói thẳng thiếu gì. Cảnh dưới 10 giây được phép đứng yên — đó là lựa chọn, không phải thiếu sót, và một lượt hỏi lại tốn vài phút.

**7. Ba chốt chặn lỗi sớm.**
- *Phân tích*: chủ đề không chia chữ nào với tiêu đề hay lời thoại của video thì **không phải nói về video đó**. Một lượt từng trả về chủ đề `"com"` — mảnh của URL nguồn — và phần nghiên cứu, kịch bản, 9 cảnh ảnh đều được làm về hư không.
- *Nghiên cứu*: nay **mở và đọc** 3 kết quả đầu, không chỉ liệt kê. Tiêu đề với trích đoạn là mục lục, không phải thông tin. Thêm nguồn dự phòng (endpoint lite, rồi Wikipedia qua API — cào trang bị 403). Đã thử Mojeek: trả về captcha, không dùng được.
- *Duyệt kịch bản*: điểm chấm nay **chặn được**. Kịch bản bị chính app chấm dưới ngưỡng thì không đi tiếp tới khâu tiêu tiền. Kịch bản **chưa ai duyệt** vẫn qua — duyệt không bắt buộc, chỉ trượt mới bị chặn. Test bắt được đúng một lỗ của tôi ở đây: bản chưa duyệt có điểm 0, đọc thành "trượt" thì sẽ chặn mọi luồng bình thường; dấu hiệu đúng là **có tên người chấm hay không**.

**Kiểm thử**: 1305 đạt, 4 đỏ — vẫn đúng 4 lỗi cũ có sẵn từ trước (test bám vào đường dẫn `/api/chatgpt/...` đã đổi tên, `start()` thêm tham số, `_segment_arguments` đổi thứ tự tham số).

Một lỗi của tôi bị bộ test bắt: đổi worker tạo ảnh sang nhiều luồng làm hỏng `routes_system.py`, chỗ vẫn với tay vào `_thread` đơn lẻ. Nay hỏi `status()` thay vì cầm thẳng handle luồng.

### 2026-09-26 — Bước 1 (Phân tích nguồn) làm lại

**Hiện trạng trước khi sửa.** App gọi AI **hai lần** cho cùng một video. Lần một (`llm_analyzer`) chỉ được đưa tiêu đề, mô tả và tags — **không có transcript**, dù Whisper vừa chạy xong — rồi hỏi về SEO: `hook`, `description_opening`, `recommendations`. Lần hai (`reference_analyzer`) mới thật sự đọc nội dung, nhưng **không nằm trong luồng 12 bước** và chưa từng chạy: dự án 57 không hề có bản phân tích `reference` nào. Hệ quả dây chuyền là phần "NỘI DUNG NGUỒN, đây là sự thật phải giữ" trong prompt của người viết luôn rỗng, và AI lên kế hoạch dựng nhận `visual_style` trống.

**1. Whisper: `base` → `large-v3`.** Đo trên chính video nguồn, cùng một file tiếng:

| `base` | `large-v3` |
|---|---|
| "vũ **chụt** được tạo thành" | "**Vũ trụ** được tạo thành" |
| "chúng ta có **hít rộ**, heli" | "chúng ta có **Hydro, Heli**" |
| "hệ mặt **chờ** xuất hiện" | "**Hệ mặt trời** xuất hiện" |
| "trong không **dàn**" | "trong không **gian**" |
| 6 giây | 10 giây |

Model đã có sẵn trong cache máy, không phải tải. Thêm chuỗi dự phòng `medium → small → base → tiny` cho trường hợp card không đủ bộ nhớ: bản phiên âm thô còn hơn không có bản nào.

**2. Tách trích xuất khỏi phân tích** — `source_brief.py`. Trích xuất là việc cơ bắp và **biết nguồn thuộc loại nào**: tải, phiên âm, đọc chữ, cắt khung hình — không hiểu gì cả. Phân tích là **một** lời gọi AI trên thứ trích xuất được, và kết quả cùng một hình dạng bất kể nguồn là gì. Bốn loại đã chạy được: `video`, `article`, `images`, `idea`.

Thêm workflow "ảnh → video" hay "bài viết → video" sau này là viết **một hàm trích xuất**, không phải sửa lại bước.

**3. Lần đầu tiên AI *nhìn* thấy nguồn.** App tải một bản 480p tạm (3,8 MB cho clip 62 giây), dựng contact sheet 12 ô, rồi xóa bản tạm. Việc tải bản thật để dựng lại vẫn giữ nguyên là hành động phải xác nhận.

Kết quả kiểm chứng thật đáng chú ý hơn tôi nghĩ — nó **dùng chữ trên màn hình để bắt lỗi phiên âm**:

> *"Chữ trong ảnh khác bản phiên âm ở ít nhất hai vị trí: ảnh ghi 'SỰ SỐNG ĐÂM CHỒI NẢY LỘC'"* — trong khi Whisper nghe ra "đâm trôi nảy lốc".

`_call_orchestrator_json` nay nhận `image_path`, và khi có ảnh thì **chỉ** các runtime nhìn được (Codex CLI, Claude Code CLI) được nhận việc. Antigravity bị loại khỏi danh sách chứ không phải để thử rồi hỏng: nó sẽ *không* báo lỗi, nó sẽ mô tả tự tin một tấm ảnh chưa từng thấy — tệ hơn là không có câu trả lời.

**4. Nguồn phải khai nó thiếu gì.** Ảnh có phong cách, không có cốt chuyện. Bài viết có cốt chuyện, không có phong cách. Ý tưởng không có gì. Người viết kịch bản **phải biết là cái nào**, vì bịa thêm chi tiết là đúng trong trường hợp này và là sai sự thật trong trường hợp kia — mà hiện quyết định đó lấy từ `workflow` người dùng chọn tay, không phải từ nguồn.

Nên `has_story` / `has_dialogue` / `has_visual_style` do **app quyết định, không hỏi model**: chúng mô tả cái đã được trao tay, và bên trao tay là bên không thể sai về việc đó. Model được đưa ảnh mà không có ảnh thật sẽ mô tả ảnh. Kèm theo: không có ảnh thì `visual_style` bị xóa trắng, không có tiếng nói thì `dialogue` bị xóa, và `limitations` được app ghi trước một dòng nói rõ nguồn thiếu gì.

**5. Mỗi bước nay nói to ra mình đang làm gì** — `step.started` / `step.finished` / `step.failed` / `step.refused` vào `/api/events`. App **cố ý không biết ai đang nghe**. Một kênh Telegram sau này chỉ cần poll event log; không cần app biết Telegram là gì.

**Hai lỗi của tôi bị bắt trong lúc làm:**

Bộ chọn format tải bản xem trước quá ngây thơ — `Requested format is not available` với YouTube. App đã có sẵn cơ chế thử nhiều player client; dùng lại nó thay vì tự viết.

Nặng hơn: `_announce_step` truyền chi tiết thành keyword rời, mà event bus chỉ nhận một bộ tham số cố định → `TypeError` → bị chính `except Exception: pass` của tôi nuốt. **App trông như đang phát sự kiện mà không phát gì cả.** Test của tôi cũng không bắt được vì nó mock thẳng `emit_domain_event` — chứng minh lời gọi có xảy ra, không chứng minh có ai nhận. Đã sửa: chi tiết đi trong `payload`, và thêm test đọc ngược từ event log thật.

**Đã kiểm chứng chạy thật:**

| Việc | Kết quả |
|---|---|
| Video nguồn (dự án 57) | 12 cảnh `scene_map`, **33 câu thoại kèm mốc giây** (trước: 1 câu gộp), `visual_style` mô tả đúng bố cục lưới 4×3 |
| Dự án chỉ có ý tưởng | 15 giây, `has_visual_style: false`, `visual_style` rỗng, limitations ghi rõ "chỉ diễn giải ý tưởng" |
| Sự kiện qua HTTP | `step.started` → `step.finished analyze 15.4s` |
| Chạy lại bước | Không tải lại video (contact sheet dùng lại) |

**Kiểm thử**: 1334 đạt, 4 đỏ — vẫn đúng 4 lỗi cũ có từ trước.

### 2026-09-26 (bổ sung) — Video không có lời

Kiểm lại bước 1 thì phát hiện một lỗ tôi vừa tự tạo ra: video **không có lời nói** làm hỏng cả bước. `extract_source` ném 422 khi Whisper không nghe ra chữ nào.

Nhưng video nhạc, timelapse, gameplay, b-roll đều có hình và không có tiếng — **đúng hệt trường hợp thư mục ảnh**, không phải lỗi. Từ chối ở đây là dừng cả lượt chạy trên một nguồn mà riêng khung hình đã đủ dùng.

Nay video câm đi tiếp bằng khung hình: `dialogue` rỗng, `has_story` false, và limitations ghi rõ mọi lời dẫn sau này là do AI sáng tác. Chỉ từ chối khi **vừa không có tiếng vừa không lấy được khung hình nào** — lúc đó thật sự không còn gì để phân tích.

Kèm theo: câu dặn gửi model cũng phải đổi. Nói "bạn nhận lời thoại đã phiên âm" khi không đính kèm gì là cách khiến model trích dẫn những câu chưa ai nói.

**Đã chạy thật cả bốn loại nguồn:**

| Nguồn | Thời gian | Kết quả |
|---|---|---|
| Video có lời (dự án 57) | 141s | 12 cảnh, **33 câu thoại kèm mốc giây** |
| Video câm (dự án 60) | 75s | 12 cảnh từ khung hình, 0 câu thoại, tả đúng phong cách |
| Bài viết (dự án 61) | 27s | Rút đúng nhân vật "GS Trần Minh Hạnh", `visual_style` rỗng |
| Thư mục ảnh (dự án 63) | 69s | 6 cảnh từ 6 ảnh, tả đúng "minh họa kỹ thuật số", 0 câu thoại |

**Kiểm thử**: 1338 đạt, 4 đỏ — vẫn đúng 4 lỗi cũ.

### 2026-09-26 (bổ sung 2) — Trích xuất rỗng thì đi tiếp, không chặn

Hai câu hỏi làm lộ ra chỗ tôi làm chưa tới.

**"Bắt buộc phải phân tích mới chạy được à?"** Không. Không bước nào đòi `analyze` chạy trước — `script` cũng vậy. Bỏ qua phân tích vẫn chạy được, chỉ là người viết kịch bản không có gì về nguồn để bám.

**"Sao không gọi AI phân tích video luôn?"** Vì không đưa video cho AI được. Hỏi thẳng CLI:

```
-i, --image <FILE>...    Optional image(s) to attach to the initial prompt
```

Chỉ nhận **ảnh**, không có cờ nào nhận video. Việc cắt khung hình không phải thủ tục thừa — nó là cách duy nhất để AI nhìn được. Phải có ai đó đổi mp4 thành ảnh, và đó là ffmpeg.

**Nhưng ý đằng sau câu hỏi thì đúng.** Tôi đang cho *từ chối* khi trích xuất không ra gì, trong khi vẫn còn tiêu đề và mô tả — đúng bằng những gì một dự án ý tưởng có, mà dự án ý tưởng thì chạy tốt. Từ chối ở đó là dừng cả lượt vì một lý do không phải lỗi của ai: video bị chặn theo vùng, bị xóa, trang báo không mở được, file ảnh hỏng.

Nay cả ba trường hợp **hạ xuống `kind: idea`** và chạy tiếp, mang theo lý do trong `notes`. Chỉ còn một chỗ từ chối thật: dự án khai là nguồn ảnh nhưng **chưa từng có ảnh nào** — khác hẳn với ảnh có mà không mở được.

Điều không được phép xảy ra là chiều ngược lại: đi tiếp mà trông như đã xem xét nguồn. Chạy thật với link chết:

```
NGUON: kind=idea, has_story=true, has_visual_style=false
notes: "Không lấy được tiếng của video nguồn: ... Failed to resolve ..."
limitations: "Không có nguồn nội dung thực tế được cung cấp... không xác
              nhận nội dung của một video có thật."
```

**Kiểm thử**: 1344 đạt, 4 đỏ — vẫn đúng 4 lỗi cũ.

### Bước 1 — Tổng hợp toàn bộ hạng mục (2026-09-26)

#### Đã xong

| # | Việc | Kiểm chứng |
|---|---|---|
| 1 | Whisper `base` → `large-v3`, kèm chuỗi lùi `medium/small/base/tiny` | "vũ chụt" → "Vũ trụ", "hệ mặt chờ" → "Hệ mặt trời"; +4 giây |
| 2 | Tách trích xuất khỏi phân tích (`source_brief.py`), 4 loại nguồn | Chạy thật cả 4: video / video câm / bài viết / ảnh |
| 3 | AI **nhìn** được nguồn qua contact sheet; việc cần nhìn chỉ giao cho runtime nhìn được | Astra bắt lỗi phiên âm bằng chữ trên màn hình |
| 4 | `has_story`/`has_dialogue`/`has_visual_style` do app quyết, không hỏi model | Không ảnh → `visual_style` bị xóa trắng |
| 5 | Mỗi bước phát `step.started/finished/failed/refused` | `step.finished analyze 15.4s` qua `/api/events` |
| 6 | Trích xuất rỗng thì hạ xuống `idea` và chạy tiếp, không dừng | Link chết vẫn ra brief, limitations ghi rõ chưa chạm được nội dung |
| 7 | Tải bản xem trước theo độ dài nguồn (480/360/240p) | Video 2 tiếng: 450MB → 110MB cho cùng 12 khung |

#### Sửa lại cách xếp mục (2026-09-27)

Người dùng chỉ ra một chỗ tôi xếp sai: **bước phân tích phải chung một luồng cho mọi workflow, không cần chọn WF trước.** Kiểm lại thì đúng — `extract_source` và `_step_analyze` **không đọc `workflow` ở bất kỳ đâu**, và `workflow` mặc định là `'content'` trên bản ghi dự án. Code đã đúng; chỉ có danh sách việc của tôi là sai.

Nguyên tắc, viết cho rõ:

> **Phân tích mô tả nguồn *là gì*. Workflow quyết định *làm gì* với nó.**

Điều này sửa luôn một chỗ trong chính đề xuất bên dưới: **trường `fidelity` không được nằm trong bản phân tích.** "Bài này phải kể trung thành" là quyết định về sản phẩm, không phải mô tả về nguồn — nhét vào đó là trộn kế hoạch vào mô tả. Bản phân tích chỉ nói nguồn có gì và chỗ nào chưa chắc; bước sau đọc rồi tự quyết.

Xếp lại:

| Việc | Thuộc bước |
|---|---|
| B — lưu `source_text` | **1. Phân tích** |
| F — extractor link sản phẩm | **1. Phân tích** |
| G — bài viết lấy thêm ảnh | **1. Phân tích** |
| A — đọc `workflow.script_mode` + `has_story` | 3. Viết kịch bản |
| C — `fidelity_guard` đọc `source_text` | 4. Duyệt kịch bản |
| D — gộp chốt vào `script_review` | 4. Duyệt kịch bản |
| E — mức ràng buộc sự thật | 3–4, **không phải** phân tích |

Bước 1 còn lại **ba việc**, cả ba thuần trích xuất, không việc nào cần biết workflow.

#### Còn lại — và vì sao theo thứ tự này

**Việc A — Người viết kịch bản phải biết nó đang kể lại hay đang sáng tác.**
`main.py::_step_script` truyền cứng `remake_mode="new_angle_same_topic"`, **bỏ qua `workflow.script_mode`** — nên chọn workflow reup (khai `faithful_retell`) chạy qua bước vẫn ra chế độ sáng tác. Và bản phân tích nay *biết* nguồn có cốt chuyện hay không, nhưng `has_story`/`has_dialogue` hiện **không chỗ nào đọc**.
*Sửa:* `_step_script` đọc `project["workflow"]` → `workflows.get(key).script_mode`; bản phân tích nói `factual` thì ép `faithful_retell`. `remake_mode` trong options chỉ còn là cái để ghi đè thủ công.
*Vì sao đầu tiên:* đây là chỗ duy nhất biến dữ liệu phân tích thành khác biệt trên sản phẩm. Không có nó, sáu việc còn lại vẫn là dữ liệu nằm im.

**Việc B — Lưu `source_text` vào bản phân tích.**
`extraction.text` hiện dùng xong là mất. Hệ quả: muốn kiểm lại phải trích xuất lại từ đầu (tải lại video, chạy lại Whisper), và việc C không làm được.
*Sửa:* `source_brief.finalise` gắn `source_text` vào brief.

**Việc C — `fidelity_guard` đọc được mọi loại nguồn.**
`check_script_fidelity` lấy nguồn đối chiếu từ `get_transcript(video_id)`, nên **nguồn bài báo và sản phẩm trả 400 rồi bỏ cuộc**.
*Sửa:* lấy `source_text` từ brief trước, transcript chỉ là đường lùi.

**Việc D — Bật cái chốt đã nằm sẵn trong code.**
`fidelity_guard.py` đối chiếu bằng máy: tên riêng và con số có trong bản mới mà không có trong nguồn thì trượt, bất kể AI chấm bao nhiêu. Nó đang là **một nút bấm trên giao diện** ([project-detail.js:1201](_HE_THONG/app/youtube_monitor/static/project-detail.js)), không ai gọi tự động.
*Sửa:* gộp vào bước `script_review` (đã có sẵn, đã có cổng chặn `_refuse_a_script_that_failed_review`) thay vì thêm bước thứ 13.

**Việc E — Trường `fidelity` trên bản phân tích.**

| Mức | Nguồn | Sai thì sao |
|---|---|---|
| `invent` | prompt, thư mục ảnh | Không có gì để sai |
| `retell` | video (theo workflow) | Đổi tên, đổi kết → video sai |
| `factual` | bài báo, **sản phẩm** | Sai giá, sai thông số → người xem mua nhầm |

Chỉ `factual` mới **chặn**; `retell` cảnh báo; `invent` bỏ qua vì không có gì đối chiếu.

**Việc F — Extractor link sản phẩm, ba tầng.** Đã đo thật trên link của người dùng:

| Sàn | Đường | Lấy được |
|---|---|---|
| Lazada | HTTP + JSON-LD | Tên, 6 ảnh, thương hiệu, SKU, mô tả, **giá** — đủ |
| TikTok Shop | Playwright 6s | Tên, danh mục, 4.7/1037 đánh giá |
| Shopee | Playwright 8s | **Chỉ tên + quảng cáo chung.** `WebSite`+`BreadcrumbList`, không có `Product`, 0 ảnh, đòi đăng nhập |

Shopee cần profile Chrome đã đăng nhập — app đã có `launch_persistent_context` cho gflow/Meta, cùng một cơ chế. Nghĩa là app sẽ lái một phiên Shopee thật của người dùng; cần nói rõ trước khi làm.
Thêm `captured_at` cho giá: giá lấy hôm nay tuần sau đã sai, brief phải nói nó chụp lúc nào.

**Việc G — Bài viết lấy thêm ảnh trong bài.** `og:image` và ảnh JSON-LD hiện bị bỏ phí, trong khi bài báo có ảnh thì AI mô tả được phong cách thay vì để trống.

#### Vì sao F đứng sau A–E, không phải trước

Nguồn sản phẩm là loại sai sự thật gây hậu quả nặng nhất. Xây extractor trước khi nối chốt kiểm tra nghĩa là app **dựng được video với cái giá do AI tự nghĩ ra và không gì chặn lại** — mà Shopee đúng là ca không lấy được giá, tức là ca AI dễ tự điền nhất.

### 2026-09-27 — Bước 1 hoàn thiện (B, F, G)

**B — `source_text` lưu lại cùng bản phân tích.** Trước đây dùng xong là mất, nên kiểm lại phải tải lại video và chạy lại Whisper. Đây là thứ mở khóa cho việc C/D ở bước 4.

**F — Đọc link sản phẩm.** Đo thật trên ba link người dùng đưa, và kết quả **phủ định giả định ban đầu của tôi**:

| Sàn | HTTP tĩnh | Render headless |
|---|---|---|
| Lazada | JSON-LD có tên/6 ảnh/hãng/SKU — **`offers` KHÔNG có trường giá nào** | thân trang không load |
| Shopee | "Please enable JavaScript" | "Cần đăng nhập", 0 ảnh sản phẩm |
| TikTok Shop | — | **Captcha kéo mảnh ghép** |

Tức là **không sàn nào cho lấy giá tự động**. Tôi từng đề xuất "extractor ba tầng" với hàm ý tầng sau sẽ lấy được thứ tầng trước không lấy; thực tế giá nằm ngoài tầm cả ba tầng.

Nên thiết kế theo đúng sự thật đó: `page_source.py` lấy những gì lấy được (tên, ảnh, hãng, danh mục, SKU, mô tả) và **nói thẳng khi không đọc được giá**:

> *"KHONG doc duoc gia tu trang nay. TUYET DOI khong tu dien gia vao kich ban."*

Câu đó đi vào cả prompt gửi model lẫn `limitations` của brief. `options.price` cho người dùng nhập tay — người nhìn được trang đọc được thứ máy không đọc được, và con số của họ đáng giá hơn một ô trống.

Thêm `source_facts`: những gì **đọc trực tiếp từ trang** (tên, hãng, SKU, giá, `captured_at`, đi qua đường nào), giữ tách khỏi những gì model suy ra. Một giá đọc hôm nay thì tháng sau đã sai, nên brief ghi luôn thời điểm đọc.

**Nhập link không phải video.** yt-dlp hỏng là hỏng luôn, nên trang bán hàng và bài báo **không đưa vào app được**, dù bước phân tích đã biết đọc chúng. Nay yt-dlp thất bại thì lùi về `_probe_page_link` — đọc tiêu đề, mô tả, ảnh đại diện, tạo bản ghi cùng hình dạng, `duration_seconds = 0`.

**G — Bài viết lấy thêm ảnh của chính nó.** `og:image` và ảnh JSON-LD trước đây bỏ phí, nên bài báo có ảnh vẫn bị phân tích như không có, `visual_style` trống.

**Đã chạy thật:**

| Việc | Kết quả |
|---|---|
| Dán link Lazada → import | yt-dlp `Unsupported URL` → lùi về đọc trang → tạo dự án với đúng tên sản phẩm |
| Phân tích link đó | `kind=product`, route `http_jsonld`, **6 ảnh sản phẩm**, tả đúng phong cách ảnh quảng cáo |
| `source_facts` | tên, hãng, danh mục, SKU, tình trạng, `captured_at` |
| Không có giá | cảnh báo vào `limitations`, model được dặn không được tự điền |
| `options.price=285000` | warning biến mất, `source_facts.price` = 285000 VND |
| Bài báo VnExpress | `kind=article`, lấy được ảnh, tả đúng "đồ họa phẳng tối giản, logo VnExpress" |

**Kiểm thử**: 1372 đạt, 4 đỏ — vẫn đúng 4 lỗi cũ.

**Chưa kiểm chứng:** tầng `browser_profile` (Chrome đã đăng nhập) cho Shopee — code có nhưng chưa thử, vì cần người dùng đăng nhập thật. Không nên coi là đã chạy được.

### 2026-09-27 — Lỗi người dùng gặp khi dán link sàn vào ô thêm nguồn

Tái hiện được cả hai, và đều là lỗi thật:

| Link | Trước khi sửa | Vấn đề |
|---|---|---|
| Shopee | HTTP 400 | Đường lùi đọc trang trả `None`; lỗi hiện ra là câu của yt-dlp *"Unsupported URL"* — vô nghĩa với link sàn |
| TikTok Shop | **HTTP 200** | **Tệ hơn**: nhập thành công với tiêu đề **"Security Check"**. Dự án được tạo, trông như đã chạy được, và thư viện có một nguồn rác |

Bốn lần sửa, mỗi lần một phép thử thật lại lộ ra một tầng sai sâu hơn:

1. **Nhận diện tường chặn** (`looks_like_bot_wall`) — không bao giờ nhập "Security Check" / "Verify to continue" / "Cần đăng nhập" làm nguồn. Và khi từ chối thì nói câu người dùng làm được gì, không phải câu của yt-dlp.
2. **Thân trang là tường thì vẫn nhập** nếu tiêu đề thật — trang Shopee chưa đăng nhập vẫn nêu đúng tên sản phẩm ở `og:title`; một dòng nguồn đúng tên hơn là không có gì.
3. **Chỉ tin tiêu đề trang tự khai** (`og:title` / JSON-LD) — với **riêng sàn**. Vỏ trang của sàn vẫn có thẻ `<title>`, và đó là khẩu hiệu của sàn: tin nó thì nguồn mang tên *"Shopee Việt Nam | Mua và Bán Trên Ứng Dụng Di Động"*. Web thường không bị luật này — áp cho tất cả làm hỏng trang VnExpress vốn nhập được.
4. **Phát hiện bị đá sang trang khác** (`landed_elsewhere`) — Shopee không từ chối, nó **chuyển hướng trình duyệt headless về trang chủ**. Trang tải hoàn hảo, `og:title` thật, nhưng là của trang chủ. So đường dẫn cuối với đường dẫn đã xin; khác nhau thì coi như không được phục vụ.

Kết quả sau khi sửa:

| Link | Kết quả |
|---|---|
| Lazada | **200** (2s) — "Nước hoa EDT X-Men for Boss Intense..." |
| Bài báo VnExpress | **200** (1s) |
| Shopee | **400** kèm lời giải thích dùng được — Shopee đang chủ động đá headless về trang chủ |
| TikTok Shop | **400** kèm lời giải thích — captcha |

Shopee **có chạy được một lần** ở lượt đo đầu tiên trong ngày; sau nhiều lượt truy cập từ cùng IP thì nó siết lại. Đây là hiện tượng chập chờn, và tầng `browser_profile` (Chrome đã đăng nhập) vẫn là đường duy nhất cho Shopee — **vẫn chưa kiểm chứng**.

**Kiểm thử**: 1384 đạt, 4 đỏ — vẫn đúng 4 lỗi cũ.

### 2026-09-27 — Đọc trang bán hàng: bỏ trình cào, dùng AI đọc

Người dùng chặn tôi lại đúng lúc: *"chỉ lấy và xem sản phẩm thì hoàn toàn không cần đăng nhập... các model AI đều có thể truy cập link này để đọc dữ liệu cơ mà?"*

Đúng. Tôi xây trình cào rồi đi vá bot-wall, rồi đi xây cả cơ chế đăng nhập — trong khi app đã có sẵn một bộ đọc web tốt hơn hẳn. Đo thật cả bốn bộ đọc:

| Bộ đọc | Lazada | Shopee | TikTok |
|---|---|---|---|
| Trình cào (httpx + JSON-LD) | tên/ảnh/hãng, **không giá** | ❌ | ❌ |
| Trình cào (Playwright ẩn) | thân trang không load | đá về trang chủ | captcha |
| Codex CLI (web search) | ❌ | ❌ | — |
| **Claude Code CLI + WebFetch** | ✅ **280.000₫, 4,9 sao, 1.073 đánh giá** | ❌ | ❌ |

Điểm mấu chốt: `offers` trong JSON-LD của Lazada **không có trường giá nào**, và bản render thì thân trang không tải. Nghĩa là giá, số sao, số đánh giá **không tồn tại ở bất kỳ đâu trong HTML mà app với tới được** — nhưng bộ đọc của CLI lấy được, trong 24 giây.

**Vì sao trước đó app không dùng được nó.** `call_claude_code_json` gọi CLI với `--tools ""` — tắt toàn bộ công cụ, kể cả WebFetch. Đúng cho hầu hết lời gọi (người viết kịch bản không có việc gì phải lướt web), nên không sửa chỗ đó; thêm cờ `allow_web` mở đúng một công cụ, dùng cho đúng một việc.

**Cách ghép hai nguồn.** Không cái nào thay cái nào:
- JSON-LD giữ **ảnh, SKU, hãng** — chính xác, không qua model nào
- Bộ đọc AI giữ **giá, số sao, số đánh giá** — thứ markup không hề có

Không bên nào ghi đè trường bên kia đã xác lập. Kèm theo `reader_note` — ghi chú của chính bộ đọc, ví dụ nó tự nói đã lấy hai lần cho khớp và không chắc 1.073 là số đánh giá hay số lượt chấm.

**Bỏ hướng đăng nhập.** `shop_login.py` vẫn còn và vẫn dùng được nếu có profile, nhưng **thông báo lỗi không còn quảng cáo nó**. Xem một món hàng chưa bao giờ cần tài khoản; bảo người dùng đăng nhập là chỉ sai chỗ. Với trang không ai đọc được, thông báo nay nói đúng thứ giúp được: mở trang rồi dán tên/giá/mô tả vào dự án ý tưởng, *"app sẽ dùng đúng những gì bạn dán và không tự nghĩ ra con số nào"*.

**Hai lỗi của tôi trong lượt này, cùng một kiểu.** `read_with_ai` import sai tên hàm (`call_claude_code_cli_json` thay vì `call_claude_code_json`) → `ImportError` → bị chính `except ImportError` của tôi nuốt → trả về rỗng im lặng, trông như "AI không đọc được". Trước đó `_announce_step` cũng vậy. **Except rộng che lỗi của chính người viết ra nó** — lần thứ hai trong hai ngày.

Và bộ test chạy mất 262 giây vì ba test gọi Claude CLI thật. Test không được gọi AI; đã mock lại, còn 0,1 giây.

**Kiểm thử**: 1400 đạt, 4 đỏ — vẫn 4 lỗi cũ.

### 2026-09-28 — Tổng hợp: đã làm được gì, còn nợ gì

Chi tiết số liệu đo nằm ở [AUDIT_HE_THONG.md](AUDIT_HE_THONG.md). Đây là bản tóm tắt theo bước.

#### Bước 1 — Phân tích nguồn: **xong**

| Việc | Trạng thái | Kiểm chứng |
|---|---|---|
| Tách trích xuất khỏi phân tích (`source_brief.py`) | ✅ | 5 loại nguồn chạy thật: video / video câm / bài viết / ảnh / ý tưởng |
| AI **nhìn** được nguồn (contact sheet 12 khung) | ✅ | Bắt được lỗi phiên âm bằng chữ trên màn hình |
| Whisper `base` → `large-v3` + chuỗi lùi | ✅ | Đo đối chiếu từng câu |
| `has_story` / `has_dialogue` / `has_visual_style` do app quyết | ✅ | Không ảnh → `visual_style` bị xóa trắng |
| Trích xuất rỗng thì hạ xuống `idea`, không dừng | ✅ | Link chết vẫn ra brief, ghi rõ chưa chạm được nội dung |
| Lưu `source_text` cùng brief | ✅ | Mở khóa cho việc kiểm tra ở bước 4 |
| Đọc link sản phẩm (`page_source.py`) | ✅ một phần | Lazada đủ; Shopee/TikTok xem mục "còn nợ" |
| Nhập link không phải video | ✅ | yt-dlp hỏng → lùi về đọc trang |
| Bài viết lấy thêm ảnh của chính nó | ✅ | |
| Tải bản xem trước theo độ dài nguồn | ✅ | Video 2 tiếng: 450MB → 110MB |
| Mỗi bước phát `step.started/finished/failed/refused` | ✅ | Thấy qua `/api/events` |

#### Kết nối AI điều phối: **xong phần app, chờ phía Claude**

| Việc | Trạng thái |
|---|---|
| Cầu MCP, 45 tool | ✅ chạy được cả khi app tắt |
| Nhịp tim báo lúc `initialize` | ✅ đo thật: `False → True` |
| Vòng xếp việc → AI kéo → báo xong | ✅ đo thật trên server đang chạy |
| GPT Work đã cấu hình | ✅ sẵn trong `~/.codex/config.toml` |
| **Claude Cowork** | ❌ `mcpServers: []`, phải thêm từ giao diện app kèm `YOUTUBE_CHAT_AGENT=claude_chat` |

#### Các bước khác đã đụng tới

| Việc | Trạng thái |
|---|---|
| Render song song | ✅ 148,8s → 95,9s |
| Tạo ảnh nhiều luồng, mỗi provider một lượt | ✅ có test; **chỉ nhanh khi trải nhiều provider** |
| Chặn kế hoạch dựng phẳng (hỏi lại một lần) | ✅ |
| Cue âm thanh thiếu file không làm sập bước dựng | ✅ |
| Thêm Google TTS + Piper | ⚠️ code xong, **chưa phát ra tiếng nào** — thiếu API key và model |
| Chốt: chủ đề không khớp nguồn | ✅ |
| Nghiên cứu đọc nội dung trang, thêm nguồn dự phòng | ✅ |
| Điểm duyệt kịch bản chặn được | ✅ |

---

### Còn nợ — xếp theo thứ tự nên làm

**A. Ba sàn chưa đọc được giá (trừ Lazada).**
Shopee và TikTok chặn mọi bộ đọc trong app. Đường đã chứng minh được: **GPT Work đọc được Shopee** (người dùng thử tay: 119.000đ, 4.7 sao, ALPHA STORE VN). App nay tự giao việc đọc cho app desktop qua hàng đợi — **chưa ai chạy thử việc đó**.
Hai việc đang chờ: `chatgpt_app` và `claude_chat`, mỗi cái chứa cả 3 link.

**B. Vai "kỹ sư" sửa lỗi — chưa bắt đầu.**
Người dùng phân biệt rõ: AI điều phối là GPT Work / Claude Cowork; Codex CLI và Claude CLI **chỉ làm kỹ sư sửa lỗi app**, khi được duyệt, báo qua Telegram. Hiện chưa có `self_fix`/`auto_fix` nào trong code. Hai mảnh đã có sẵn: `/api/automation/approvals` và sự kiện `step.failed`; thiếu phần giữa.
**Nợ kỹ thuật kèm theo:** hiện CLI vẫn đang kiêm vai điều phối (`astra → codex_cli`, `claude → claude_code_cli`) vì đường MCP tới hai app desktop chưa dùng được. Phải ghi rõ đây là **tạm**, không phải thiết kế đúng.

**C. Bước 3 — Viết kịch bản.** Chưa làm:
- `_step_script` truyền cứng `new_angle_same_topic`, **bỏ qua `workflow.script_mode`**
- `has_story` / `has_dialogue` chưa ai đọc
- Cấu trúc 4 phần cứng, ánh xạ cảnh→phần theo vị trí, danh sách cấm cứng ("châu báu, phép màu, làng cổ"), văn bản mẫu có thể bị đọc lên
- Tốc độ đọc 3,2 token/giây là đo cho VoxCPM — engine không dùng

**D. Bước 4 — Duyệt kịch bản.** `fidelity_guard.py` đối chiếu tên riêng và con số bằng máy, làm đúng việc cần — nhưng **là một nút bấm trên giao diện, không ai gọi tự động**, và chỉ đọc transcript nên nguồn bài báo/sản phẩm trả 400.

**E. Nghiên cứu nằm ở ba chỗ, không chỗ nào nối nhau.**
`steps.py` có bước `research` lưu kết quả **không ai đọc**; ô tích trong trình viết chỉ chạy với truyện cổ tích về con vật; pipeline 5 agent có một chặng cùng tên. Nên gộp vào bước viết kịch bản.

**F. Chưa kiểm chứng.** Google TTS, Piper, profile Chrome đã đăng nhập, Claude in Chrome — đều có code, chưa có bằng chứng.

**G. Ba test đỏ có sẵn** (không dính đợt này), chi tiết ở file audit.

---

**Kiểm thử hiện tại: 1416 đạt, 3 đỏ, 9 bỏ qua.**

### Còn lại

| Nhát | Trạng thái |
|---|---|
| 2c — vai `media` của pipeline dùng lõi | **chưa làm**. Bước `media` đã có, nhưng `_execute_agent_task` vẫn tự tạo scene job bằng khối chính sách riêng (ngân sách, hết provider) |
| 3 — nút giao diện gọi lõi | **chưa làm**, đường cũ vẫn chạy bình thường |
| 5 — workflow thành tham số | **chưa làm** |

Ba nhát này đều không chặn việc dùng: AI điều phối đã lái được trọn 12 bước ngay bây giờ.

### 2026-09-28 — AI điều phối chuyển sang GPT Work / Claude Cowork

**Cài đặt:** `AI_ORCHESTRATOR_PROVIDER=chatgpt_app` (GPT Work), `AI_ORCHESTRATOR_FALLBACK_PROVIDER=claude_chat` (Claude Cowork). Trước đó là `codex_cli`.

**Vì sao không chỉ đổi một dòng cấu hình.** Công đoạn `orchestration` đang gánh hai vai: *ai lái lượt chạy* và *ai bước phân tích gọi rồi chờ trả lời*. App chat không gọi-rồi-chờ được — nó tự kéo việc qua MCP. Chọn app chat làm điều phối mà ghi luôn vào công đoạn đó thì bước 1 sẽ báo "Không có AI được phép thực hiện công đoạn orchestration". Nên tách hai vai:

| Vai | Ai | Ở đâu |
|---|---|---|
| Điều phối — nhận lượt chạy, quyết bước kế | GPT Work, dự phòng Claude Cowork | `AI_ORCHESTRATOR_*`, hàng đợi chat task |
| Nghĩ *bên trong* một bước khi app tự chạy bước đó | vẫn là CLI (`astra` → `claude` → `antigravity`) | `AI_STAGE_ASSIGNMENTS_JSON` — **không đổi** |

- Lưu điều phối là app chat thì **không** ghi vào công đoạn `orchestration`; chọn CLI thì vẫn như cũ.
- Mặc định của các công đoạn không bao giờ là app chat.
- "Dự phòng" với app chat nghĩa là: lượt mới giao cho app **đang kết nối**, ưu tiên app chính; không app nào kết nối thì chờ app chính. CLI dự phòng **không** được nhận lượt của app chat — app chat im lặng một lúc thường là đang rảnh, không phải đã mất.
- Tìm thấy và sửa kèm: yêu cầu sửa sau QC giao bước đầu cho ChatGPT nhưng **không ghi `chat_agent` vào input**, nên từ bước thứ hai trở đi lượt làm lại rơi về CLI. Nay mang theo, và giao theo đúng app đang điều phối.
- Việc app chat kéo về nay kèm `how_to_direct`: xem bước bằng `list_steps`, chạy bằng `run_step` — cùng đường với nút bấm.

**Kết nối Claude Cowork:** thêm `mcpServers.youtube_ai_factory` (kèm `YOUTUBE_CHAT_AGENT=claude_chat`) vào `claude_desktop_config.json` của Claude Desktop. Bản gốc lưu ở `claude_desktop_config.json.bak-2026-09-28`. Thử cầu qua stdio ở chế độ `claude_chat`: `initialize` trả lời, 45 tool, có `list_steps`/`run_step`/`get_next_task`.

**Chưa kiểm chứng:** Claude Desktop cần khởi động lại mới nạp cầu; chưa thấy Cowork gọi được tool nào. GPT Work giữ nguyên cấu hình có sẵn trong `~/.codex/config.toml`.

**Còn nguyên nợ B:** khi app tự chạy một bước (bấm nút, hoặc `run_step` không kèm nội dung), phần nghĩ trong bước vẫn do CLI làm. App chat muốn tự nghĩ thì truyền nội dung qua `options` (`script` → `draft`, `shots` → `shots`, `timeline` → `segments`); các bước `analyze`, `edit_plan`, `script_review` chưa có đường đó.

**Kiểm thử**: 1428 đạt, 2 đỏ — hai lỗi cũ (`_segment_arguments` đổi thứ tự tham số, `unmarked_reup`). Test cũ `test_high_level_pipeline_…` đã sửa; nó và `test_orchestrator_defaults_…` từng đọc `.env` thật của máy, nay không còn.

### 2026-09-28/29 — Mốc Agent Orchestrator (app tự điều phối qua MCP)

Chi tiết và bằng chứng: `AI_CONNECTION_HANDOFF.md` (mục 2–9), `AUDIT_HE_THONG.md` (mục 3).

**Một pipeline, hai cách lái.** Agent không có pipeline riêng. Nó quyết bước nào, rồi gọi đúng `run_step` mà nút bấm gọi, qua MCP.

**Đã làm:**
- **Orchestrator Agent tách khỏi Structured Worker.**
  - `codex_agent_bridge.py` và `claude_agent_bridge.py` có tay chân duy nhất là MCP `youtube_ai_factory`.
  - `codex_bridge` và `claude_code_bridge` giữ nguyên, không có tool.
- **`agent_loop.py`: vòng đọc state → hành động → quan sát → đổi cách → kiểm chứng.**
  - `completed` chỉ khi `_verify_goal` xác nhận từ DB.
  - Não hỏng thì đổi runtime; 2 vòng không đổi state thì dừng `blocked`.
- **Kích hoạt:** `POST /orchestrate` với `mode="agent"`. Việc đi vào hàng đợi `agent_tasks` có sẵn, vai `orchestrator`. Chế độ `plan` cũ giữ cho giao diện.
- **Chốt trong cầu MCP**, không nằm trong prompt:
  - ngân sách tool mỗi vòng;
  - chỉ làm trên một dự án;
  - chặn gọi lại y hệt khi state chưa đổi;
  - tiêu lượt cần `allow_spend`, ghi đè `force` cần `allow_overwrite`;
  - luôn chặn đăng video;
  - log từng lệnh gọi, đã che bí mật.
- **Một bảng ánh xạ agent → runtime** (`settings.AGENT_RUNTIME`). Đã sửa 2 chỗ lựa chọn của người dùng bị bỏ qua lặng lẽ và 4 hàm chọn provider từ chối tên agent.
- **Một cách đọc quota** (`usage_limits.limit_state`): quota cũ được thử lại sau 6 giờ, không chặn mãi.
- **Retry của pipeline 5 vai** mang theo lý do bị chấm chéo trả về.

**Nghiệm thu thật:**
- Dự án 66: `openai_gpt` hỏng → agent tự chọn `codex_cli` → script → shots → timeline → DB xác nhận → `completed`.
- Pipeline 5 vai trên dự án 72: research, script, director đạt; `media` trượt 6/10 vì chất lượng, giữ nguyên.

**Nợ còn lại của kế hoạch:**
- Nhát 2c: vai `media` vẫn tự tạo scene job.
- Nhát 3: nút giao diện chưa gọi `/steps` hay chế độ agent.
- Nhát 5: workflow chưa thành tham số.
- Nợ B chuyển hướng: CLI giờ vừa là Structured Worker, vừa là Orchestrator Agent **của app** khi chạy không người trông. GPT Work / Cowork vẫn là AI điều phối khi người dùng chat.

**Kiểm thử**: 1476 đạt, 2 đỏ (hai lỗi cũ: `_segment_arguments`, `unmarked_reup`), 9 bỏ qua.

**Dữ liệu thử chưa xoá:** dự án 61, 66 và 72 (`[TEST pipeline 5 vai CLI - có thể xoá]`). App không có endpoint xoá dự án; xoá dữ liệu để người dùng tự quyết.

### 2026-09-29 — Xác minh Claude CLI làm AI điều phối

- **Thêm:** `/orchestrate` với `mode=agent` nhận `runtime` để chọn AI điều phối đi trước. Task được giao cho agent đó, nên log ghi đúng AI đã lái.
- **Chạy thật trên dự án 61, mục tiêu `timeline`, `runtime=claude_code_cli`:**
  - 3 tool call: list_steps → run_step(timeline) → list_steps.
  - Model `claude-opus-5` + `claude-haiku-4-5`, 22,7 giây.
  - DB xác nhận 6 đoạn timeline; task `completed`.
  - Lời dặn cố ý đòi `force`, nhưng lượt chạy cấm ghi đè. Agent tự chạy không kèm `force`, vì chưa có timeline nào để ghi đè, và nói rõ trong báo cáo.
- **Còn UNVERIFIED:** đổi runtime giữa lượt khi não hỏng thật. Chỉ có test.

**Kiểm thử**: 1477 đạt, 2 đỏ (hai lỗi cũ), 9 bỏ qua.
