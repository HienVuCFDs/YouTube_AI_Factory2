# Kế hoạch dự án YouTube AI Factory

## 1. Mục tiêu

Xây dựng hệ thống AI hỗ trợ quy trình sản xuất video YouTube theo dạng module. Hệ thống có thể theo dõi nhiều kênh, lưu metadata, phân tích nội dung, tạo transcript, hỗ trợ viết kịch bản, dựng video, tạo thumbnail và chuẩn bị xuất bản.

Người dùng vẫn kiểm duyệt và quyết định cuối cùng trước khi nội dung được đăng tải.

## 2. Nguyên tắc triển khai

- Xây dựng từng module độc lập.
- Ưu tiên API chính thức của YouTube.
- Dùng `channel_id` và `video_id` làm định danh chính.
- Không tải video về máy mặc định / tự động. Từ mục 19: có một hành động tải **thủ công, từng video, do người dùng chủ động bấm** để phục vụ dựng lại nội dung (bình luận/góc nhìn riêng) — không có hàng đợi/pipeline tự động nào tải video.
- Không để OpenClaw truy cập trực tiếp database.
- OpenClaw chỉ điều phối thông qua API của hệ thống.
- Lưu lịch sử thay đổi metadata.
- Có thể thay SQLite bằng PostgreSQL về sau.
- Nội dung từ kênh khác chỉ được xử lý khi có quyền sử dụng phù hợp. Việc tải video thủ công (mục 19) nằm ngoài phạm vi bảo vệ này — trách nhiệm đánh giá "sử dụng hợp lý" (fair use/biến đổi đủ mức) cho từng video xuất bản thuộc về người dùng, hệ thống không và sẽ không có tính năng tự động đăng lại (reup) nguyên video.

## 3. Kiến trúc tổng thể

```text
Web UI
   │
   ▼
FastAPI Backend
   │
   ├── YouTube Monitor
   ├── Database
   ├── Webhook Handler
   └── Job Queue
          ▲
          │
       OpenClaw
          │
          ▼
     AI Workflows
```

## 4. Lộ trình triển khai

### Giai đoạn 0 - Nền tảng

- Tạo cấu trúc project.
- Thiết lập Python environment.
- Thiết lập biến môi trường.
- Tạo database.
- Thiết kế API nội bộ.
- Thiết lập logging và xử lý lỗi.

### Giai đoạn 1 - YouTube Monitor

- Quản lý nhiều kênh.
- Nhập kênh bằng URL, handle hoặc channel ID.
- Chuẩn hóa thành `channel_id`.
- Lấy uploads playlist.
- Lấy danh sách `video_id`.
- Lấy metadata đầy đủ.
- Lưu dữ liệu vào SQLite.
- Lưu lịch sử thay đổi tiêu đề và mô tả.
- Hiển thị danh sách kênh và video.
- Hỗ trợ đồng bộ thủ công.
- Hỗ trợ YouTube Push Webhook.

### Giai đoạn 2 - Transcript

- Kiểm tra caption/subtitle nếu có.
- Trích xuất audio tạm thời khi cần.
- Chạy Faster-Whisper.
- Xuất TXT, SRT và JSON.
- Xóa audio tạm sau khi xử lý.

### Giai đoạn 3 - AI Writer

- Tóm tắt video.
- Phân tích chủ đề và cấu trúc.
- Trích xuất ý tưởng.
- Tạo tiêu đề mới.
- Tạo mô tả và hashtag.
- Viết CTA.
- Viết kịch bản mới có giá trị riêng.

### Giai đoạn 4 - Voice và Video

- Dịch nội dung.
- Lồng tiếng.
- Tạo phụ đề.
- Ghép cảnh.
- Xóa khoảng lặng.
- Tạo phiên bản Shorts.
- Không lưu video nguồn lâu dài nếu không cần thiết.

### Giai đoạn 5 - Thumbnail và Quality Check

- Tạo thumbnail bằng ComfyUI.
- Tạo nhiều phiên bản thumbnail.
- Kiểm tra title, description, subtitle và nội dung.
- Kiểm duyệt thủ công.

### Giai đoạn 6 - Publisher và Analytics

- Chuẩn bị upload.
- Đặt lịch đăng.
- Gắn thumbnail, playlist và chapter.
- Theo dõi CTR, watch time và retention.
- Đề xuất cải thiện tiêu đề, thumbnail và thời điểm đăng.

## 5. Chi tiết Giai đoạn 1

### 5.1. Quy trình thêm kênh

```text
URL / @handle / channel_id
        ↓
channels.list
        ↓
uploads_playlist_id
        ↓
playlistItems.list
        ↓
video_id
        ↓
videos.list
        ↓
SQLite
```

### 5.2. Dữ liệu kênh

```text
youtube_channel_id
handle
channel_url
title
description
thumbnail_url
uploads_playlist_id
published_at
subscriber_count
video_count
group_name
tracking_enabled
sync_status
last_sync_at
last_push_at
last_error
```

### 5.3. Dữ liệu video

```text
youtube_video_id
youtube_channel_id
video_url
title
description
published_at
thumbnail_url
duration_seconds
category_id
default_language
caption_available
live_broadcast_status
privacy_status
license
tags
view_count
like_count
comment_count
analysis_status
media_status
raw_payload
```

### 5.4. Phát hiện video mới

Không sử dụng lịch quét 15 phút làm cơ chế chính.

Các cơ chế được sử dụng:

1. YouTube Push Notification qua webhook.
2. Đồng bộ thủ công từ giao diện.
3. Đối soát định kỳ thưa hơn khi cần khôi phục sự kiện bị bỏ sót.

Thông báo đăng ký kênh trong ứng dụng YouTube không tự động trở thành sự kiện cho chương trình local. Để chương trình nhận được sự kiện, cần dùng callback webhook công khai hoặc một lớp trung gian chuyển tiếp thông báo.

## 6. Chính sách lưu trữ media

### Mặc định

```text
media_status = not_downloaded
```

Hệ thống chỉ lưu metadata, không tải video nguồn về máy.

### Khi cần phân tích nội dung

Ưu tiên theo thứ tự:

1. Metadata và mô tả.
2. Caption/transcript có sẵn.
3. Audio tạm thời cho Whisper.
4. Keyframe được lấy mẫu khi cần phân tích hình ảnh.
5. Xóa file tạm sau khi hoàn tất.

AI không phải lúc nào cũng có thể đọc trực tiếp URL YouTube. Phân tích video vẫn cần truy cập audio hoặc frame thông qua streaming hoặc file tạm. Tuy nhiên không cần lưu trữ video lâu dài.

Transcript thường tiết kiệm hơn việc gửi toàn bộ video vào AI cloud. Nếu dùng AI local, chi phí token không phát sinh nhưng sẽ dùng CPU/GPU và băng thông.

## 7. Database

### Bảng chính

```text
channels
videos
video_statistics
metadata_versions
sync_runs
```

### Quy tắc dữ liệu

- `youtube_channel_id` là duy nhất.
- `youtube_video_id` là duy nhất.
- Không ghi đè lịch sử metadata.
- Không xóa video khi video nguồn bị xóa; đánh dấu trạng thái nếu cần.
- Lưu thống kê theo từng thời điểm để phân tích tăng trưởng.

## 8. API dự kiến

```text
GET  /api/health
GET  /api/summary
GET  /api/channels
POST /api/channels
PATCH /api/channels/{channel_id}/tracking
POST /api/channels/{channel_id}/sync
GET  /api/videos
GET  /api/sync-runs
GET  /webhooks/youtube
POST /webhooks/youtube
```

OpenClaw về sau có thể gọi các API này để:

- Thêm kênh.
- Yêu cầu đồng bộ.
- Lấy video mới.
- Đưa video vào workflow transcript.
- Theo dõi trạng thái xử lý.

## 9. Trạng thái hiện tại

Đã hoàn thành MVP Giai đoạn 1:

- Project độc lập tại `F:\YouTube_AI_Factory`.
- FastAPI backend.
- SQLite database.
- Giao diện web local.
- Quản lý đa kênh.
- Lưu channel ID và video ID.
- Lưu metadata video.
- Lưu lịch sử metadata.
- Không tải video.
- Có endpoint webhook YouTube.
- Có test database và parser.

Chưa thực hiện:

- Cấu hình YouTube API key thật.
- Đăng ký callback webhook công khai.
- Transcript.
- Faster-Whisper.
- LLM Writer.
- Dựng video.
- Upload tự động.

## 10. Tiêu chí hoàn thành Giai đoạn 1

- Thêm được nhiều kênh.
- Đồng bộ được video công khai.
- Không tạo video trùng.
- Phát hiện được metadata thay đổi.
- Hiển thị được trạng thái đồng bộ.
- Có log lỗi.
- Không tải video mặc định.
- API sẵn sàng cho OpenClaw.

## 11. Tài liệu kỹ thuật tham khảo

- [YouTube Data API](https://developers.google.com/youtube/v3/docs)
- [YouTube Push Notifications](https://developers.google.com/youtube/v3/guides/push_notifications)
- [YouTube Channels API](https://developers.google.com/youtube/v3/docs/channels)
- [YouTube Videos API](https://developers.google.com/youtube/v3/docs/videos)

## 12. Cập nhật triển khai: metadata-first và giao diện Vibe-Trading

Đã bổ sung trong MVP hiện tại:

- Bộ phân tích `local_metadata` chạy cục bộ, không cần tải video và không cần gọi LLM bên ngoài.
- Lưu lịch sử job phân tích vào `analysis_jobs` và kết quả vào `video_analyses`.
- API `POST /api/videos/{video_id}/analyze` để phân tích một video.
- API `GET /api/videos/{video_id}/analysis` và `GET /api/analysis-jobs` để xem kết quả, hàng đợi.
- Giao diện dashboard mới theo phong cách Vibe-Trading: sidebar, terminal status, màu cam chủ đạo, bảng dữ liệu compact và analysis drawer.
- Giữ nguyên nguyên tắc `DOWNLOAD OFF`: chỉ lưu metadata, chưa tải video/audio.

Bước tiếp theo:

- Phân tích hàng loạt theo kênh hoặc theo hàng đợi.
- Bổ sung transcript có quyền sử dụng.
- Kết nối OpenClaw/LLM như một provider tùy chọn sau khi metadata pipeline ổn định.

## 13. Cập nhật triển khai: hàng đợi phân tích hàng loạt

Đã bổ sung:

- Worker nền xử lý metadata theo hàng đợi, không chặn giao diện.
- Chọn phân tích tất cả kênh hoặc một kênh cụ thể.
- Giới hạn số video mỗi lần chạy: 25, 100 hoặc 500.
- Trạng thái job: `queued`, `running`, `completed`, `error`.
- API bắt đầu hàng đợi: `POST /api/analysis-queue`.
- API xem trạng thái: `GET /api/analysis-queue`.
- API tạm dừng/tiếp tục: `PATCH /api/analysis-queue`.
- Tự phục hồi các job đang chạy nếu app khởi động lại.
- Giao diện có nút phân tích video chờ, chọn kênh, chọn giới hạn và tạm dừng/tiếp tục.

## 14. Cập nhật triển khai: Transcript tự động bằng Faster-Whisper

Đã bổ sung (Giai đoạn 2 của roadmap gốc):

- Module `transcriber.py`: dùng `yt-dlp` trích xuất audio tạm thời (chỉ audio, không lưu video), chạy `faster-whisper` cục bộ (CPU, model mặc định `base`, cấu hình qua `WHISPER_MODEL_SIZE`/`WHISPER_COMPUTE_TYPE`), rồi xoá audio tạm ngay sau khi xử lý xong — đúng chính sách mục 6.
- API `POST /api/videos/{video_id}/transcript/auto`: chạy toàn bộ pipeline cho một video, lưu cả 3 định dạng TXT/SRT/JSON vào bảng `transcripts`, gắn `source_type = whisper_auto` để phân biệt với transcript nhập thủ công/được cấp phép.
- API `GET /api/videos/{video_id}/transcripts`: xem tất cả bản ghi transcript (mọi định dạng) của một video; `GET /api/videos/{video_id}/transcript` hỗ trợ thêm query `?format=txt|srt|json`.
- Giao diện: nút "Whisper" trên mỗi dòng video để tự động tạo transcript; cảnh báo trong drawer transcript đã cập nhật để mô tả đúng hành vi mới (audio tạm được lấy tự động cho mọi kênh đang theo dõi, không giới hạn theo quyền sử dụng — khác với luồng nhập thủ công vẫn yêu cầu tự sở hữu/được cấp phép).
- Sửa lỗi tiềm ẩn: `start_analysis_job` trước đây luôn ghi đè `videos.analysis_status`; nay chỉ áp dụng cho `analysis_type = metadata` để job transcript không làm sai lệch trạng thái pipeline phân tích metadata.
- Đã kiểm thử thực tế end-to-end trên một video thật (trích audio → transcribe → lưu 3 định dạng → xoá file tạm, xác nhận không còn file rác).

Lưu ý: tính năng này chủ động tải audio tạm thời từ mọi video đã đồng bộ, kể cả kênh không thuộc sở hữu người dùng — khác với nguyên tắc "không tải nội dung khi chưa có quyền sử dụng" ở mục 2. Đây là lựa chọn được xác nhận rõ ràng, cần cân nhắc rủi ro bản quyền/ToS khi dùng cho kênh của người khác.

## 26. Cập nhật triển khai: voiceover segments và timeline dựng video

Đã bổ sung lớp kế hoạch dựng video cục bộ sau shot list:

- Module `timeline_builder.py`: chuyển từng shot thành một segment có lời voiceover, phụ đề, prompt hình ảnh, loại asset, thời lượng và mốc bắt đầu/kết thúc liên tục.
- Bảng `project_timeline_segments`: lưu timeline theo project/script, đường dẫn audio/video sẽ gắn về sau và trạng thái `planned`, `voice_ready`, `asset_ready`, `ready`, `done`.
- Khi sửa thời lượng một segment, hệ thống tự tính lại toàn bộ mốc thời gian phía sau để tránh lệch timeline.
- API:
  - `GET /api/projects/{project_id}/timeline`: lấy timeline của script mới nhất.
  - `POST /api/projects/{project_id}/timeline/generate`: tạo timeline từ shot list, hỗ trợ `force` để tạo lại.
  - `PATCH /api/timeline/{segment_id}`: sửa voiceover, prompt, thời lượng, đường dẫn audio/video hoặc trạng thái.
  - `GET /api/projects/{project_id}/timeline/manifest`: xuất JSON manifest cho OpenClaw/FFmpeg/OpenCut.
  - `GET /api/projects/{project_id}/timeline/markdown`: xuất tài liệu timeline dạng Markdown.
- UI: thêm khối "Voiceover + timeline dựng video" trong chi tiết project; có thể tạo, tạo lại, chỉnh từng đoạn, gắn đường dẫn asset và xuất manifest.
- Handoff OpenClaw có thêm `latest_timeline`; readiness có thêm `has_timeline`.

Giới hạn có chủ ý: module timeline không tự gọi TTS, không tự tải media và không tự render video. Việc gọi pyVideoTrans/FFmpeg được tách sang production worker ở mục 27 để người dùng xác nhận và cấu hình riêng.

Đã kiểm thử: compile thành công và 25/25 unit test pass.

## 27. Cập nhật triển khai: production worker cho voiceover và render

Đã bổ sung worker nền persistent-backed để nối timeline với các công cụ production:

- Bảng `project_jobs`: lưu job `voiceover` hoặc `render`, provider, trạng thái, output path và lỗi.
- Module `production_worker.py`: tự phục hồi job đang chạy khi app restart, hỗ trợ pause/resume, chạy tuần tự và ghi trạng thái vào SQLite.
- Provider `dry_run`: tạo `voiceover-plan.json` hoặc `render-manifest.json`, không gọi subprocess, không tạo audio/video.
- Provider `pyvideotrans`: chạy command template do người dùng cấu hình qua `PYVIDEOTRANS_COMMAND`, với placeholder `{text_file}`, `{output_file}`, `{language}`, `{segment_index}`.
- Provider `ffmpeg`: chạy command template qua `FFMPEG_RENDER_COMMAND`, với placeholder `{manifest_file}`, `{output_file}`, `{project_id}`.
- API:
  - `POST /api/projects/{project_id}/jobs`: đưa voiceover/render job vào hàng đợi.
  - `GET /api/projects/{project_id}/jobs`: xem lịch sử job của project.
  - `GET /api/jobs/{job_id}`: xem chi tiết một job.
  - `GET/PATCH /api/production-queue`: xem trạng thái hoặc tạm dừng worker.
- UI: thêm các nút Voiceover dry-run, pyVideoTrans, Render dry-run và Render FFmpeg trong chi tiết project.
- Job thật bắt buộc `confirmed=true`; nếu chưa cấu hình command, API trả lỗi rõ ràng và không tạo job chạy dở.
- Handoff có thêm `production_jobs`; readiness có thêm `has_voiceover` và `has_render`.

Đã kiểm thử: compile thành công và 29/29 unit test pass; server live xác nhận worker đang chạy, dry-run không tạo media và các route mới đã đăng ký.

## 28. Cập nhật triển khai: Premiere Export Pack

Đã bổ sung cầu nối xuất gói dựng cho Adobe Premiere Pro:

- Module `premiere_export.py` tạo thư mục export và file ZIP gồm `premiere_manifest.json`, `premiere_sequence.xml`, `subtitles.srt`, `README.md` và các asset local đã gắn trong timeline.
- Chỉ copy các file tồn tại trên máy từ `audio_path`, `visual_path` và `local_media_path`; không tự tải video YouTube.
- Tự ghi nhận asset thiếu trong `missing_assets` để người dùng relink/bổ sung trước khi dựng.
- Tạo sequence XML theo timeline 30 FPS với các clip audio/video đã có đường dẫn local; Premiere có thể import XML rồi relink media nếu cần.
- API:
  - `POST /api/projects/{project_id}/premiere-export`: tạo gói export.
  - `GET /api/projects/{project_id}/premiere-export/download`: tải ZIP.
- UI: thêm nút “Xuất gói Premiere” ngay trong khối Timeline.

Đã kiểm thử: 29/29 unit test pass; server live xác nhận giao diện và hai route Premiere Export Pack đã đăng ký.

## 29. Cập nhật triển khai: thư viện nguyên liệu local

Đã bổ sung khả năng đưa nguyên liệu từ máy tính vào từng project:

- Bảng `project_assets`: lưu loại `video`, `audio`, `image`, tên gốc, đường dẫn local, MIME type, dung lượng, SHA-256 và trạng thái phân tích.
- Upload file qua giao diện, giới hạn mặc định 2 GiB/file, chỉ nhận các định dạng phổ biến và lưu trong thư mục riêng của project.
- Audio/video có nút `Whisper local`: chạy Faster-Whisper trực tiếp trên file local sau khi người dùng xác nhận, lưu transcript riêng cho asset.
- Asset video/audio/ảnh có thể gắn trực tiếp vào audio hoặc visual track của từng timeline segment.
- API:
  - `GET /api/projects/{project_id}/assets`: danh sách nguyên liệu.
  - `POST /api/projects/{project_id}/assets/upload`: upload file local.
  - `GET /api/assets/{asset_id}/download`: mở/tải file đã import.
  - `POST /api/assets/{asset_id}/analyze`: phân tích Whisper audio/video.
  - `POST /api/timeline/{segment_id}/attach-asset`: gắn asset vào timeline.
- Premiere Export Pack tự copy các asset đã gắn vào gói export; không tự tải nội dung YouTube.
- Đã thêm dependency `python-multipart` để nhận upload form-data.

Đã kiểm thử: 29/29 unit test pass; server live xác nhận UI upload, Whisper local và các route asset đã đăng ký.

Chưa thực hiện tiếp:

- Kiểm tra caption/subtitle chính chủ qua YouTube API trước khi rơi vào Whisper (đòi hỏi OAuth, chưa triển khai).

## 15. Cập nhật triển khai: chọn provider phân tích (local / Claude / GPT)

Đã bổ sung:

- Module `llm_analyzer.py`: `ClaudeAnalyzer` (Anthropic API, model mặc định `claude-opus-5`, cấu hình qua `ANTHROPIC_MODEL`) và `OpenAiAnalyzer` (OpenAI Chat Completions API, model mặc định `gpt-4o-mini`, cấu hình qua `OPENAI_MODEL`). Cả hai dùng chung schema JSON đầu ra để tương thích với giao diện phân tích hiện có (không cần đổi UI hiển thị kết quả).
- Hàm `resolve_analyzer(provider)` chọn giữa `local_metadata` (mặc định, miễn phí, không cần key), `anthropic_claude`, `openai_gpt`.
- API `GET /api/analysis-providers`: liệt kê provider khả dụng (dựa trên API key đã cấu hình trong `.env`).
- `POST /api/videos/{video_id}/analyze?provider=...` và `POST /api/analysis-queue` (thêm field `provider`) đều hỗ trợ chọn provider theo từng lần gọi.
- Sửa lỗi kiến trúc: trước đây `AnalysisQueue` luôn dùng một analyzer cố định bất kể `provider` lưu trong job — nay worker nền tự chọn đúng analyzer theo `job.provider` của từng job.
- Giao diện: thêm dropdown chọn provider trong panel "Hàng đợi phân tích", disable provider chưa cấu hình API key; áp dụng cho cả nút "Phân tích" từng video và hàng đợi hàng loạt.
- Đã kiểm thử: `/api/analysis-providers` trả đúng trạng thái khả dụng, phân tích local vẫn hoạt động bình thường (regression), gọi Claude/GPT khi thiếu key trả lỗi 400 rõ ràng thay vì tạo job treo, provider không hợp lệ bị chặn trước khi enqueue.

Lưu ý: Claude/GPT chỉ phân tích dựa trên metadata (tiêu đề/mô tả/tags), giống luồng local hiện tại — chưa đưa nội dung transcript vào prompt (có thể mở rộng sau nếu cần phân tích sâu hơn).

## 16. Cập nhật triển khai: hàng đợi transcript hàng loạt (Whisper)

Đã bổ sung:

- Module `transcript_queue.py`: worker nền riêng biệt (tách khỏi `AnalysisQueue` phân tích metadata), xử lý job `analysis_type = "transcript"` theo hàng đợi, hỗ trợ tạm dừng/tiếp tục và tự phục hồi job dở dang khi khởi động lại — cùng mô hình với hàng đợi phân tích metadata đã có.
- API: `POST /api/transcript-queue` (chọn kênh, giới hạn số video, force), `GET /api/transcript-queue` (trạng thái), `PATCH /api/transcript-queue` (tạm dừng/tiếp tục).
- Video được chọn để đưa vào hàng đợi là video **chưa có transcript nào** (trừ khi bật force).
- Gộp logic lưu kết quả Whisper (json/srt/txt) giữa endpoint đơn lẻ và worker hàng loạt vào một hàm dùng chung `save_transcript_result()` trong `transcriber.py`, tránh trùng lặp code.
- Giao diện: thêm panel "HÀNG ĐỢI TRANSCRIPT (WHISPER)" với chọn kênh, giới hạn số lượng, nút chạy hàng loạt và tạm dừng/tiếp tục.

Sửa lỗi kiến trúc quan trọng phát hiện khi thêm loại job thứ hai: các hàm dùng chung trong `database.py` (`queue_analysis_jobs`, `claim_analysis_job`, `requeue_interrupted_analysis_jobs`, `list_queued_analysis_job_ids`, `analysis_queue_status`) trước đây không lọc theo `analysis_type` — nghĩa là job transcript có thể vô tình reset `analysis_status` của pipeline metadata về `pending`/`running`, hoặc hai hàng đợi giành job của nhau. Đã thêm tham số `analysis_type` để tách biệt hoàn toàn hai pipeline, kèm test hồi quy `test_transcript_jobs_do_not_disturb_metadata_analysis_status`.

Đã kiểm thử thực tế: chạy hàng loạt 2 video thật qua hàng đợi, worker xử lý tuần tự, lưu đủ 3 định dạng transcript, không còn file audio tạm sót lại, `analysis_status` của pipeline metadata không bị ảnh hưởng (đối chiếu số liệu trước/sau), hàng đợi metadata và hàng đợi transcript báo cáo số liệu tách biệt đúng, tạm dừng/tiếp tục hoạt động đúng.

Chưa thực hiện tiếp:

- Kiểm tra caption/subtitle chính chủ qua YouTube API trước khi rơi vào Whisper (đòi hỏi OAuth).
- Đăng ký callback webhook công khai.

## 17. Cập nhật triển khai: Giai đoạn 3 — AI Writer

Đã bổ sung:

- Module `llm_client.py`: tách phần gọi Claude API / OpenAI API (JSON schema / JSON mode) dùng chung, dùng lại cho cả `llm_analyzer.py` (phân tích metadata) và `writer.py` (sáng tạo nội dung mới) — tránh trùng lặp code.
- Module `writer.py`: `ClaudeWriter` và `OpenAiWriter` sinh nội dung MỚI (không sao chép transcript nguồn) gồm: tóm tắt, ý tưởng chính, tiêu đề mới (nhiều lựa chọn), mô tả mới, hashtag, CTA, dàn ý kịch bản mới. Ưu tiên dùng transcript đã có (Whisper/nhập thủ công) nếu tồn tại, không có thì chỉ dựa vào metadata. Khác với phân tích metadata, AI Writer **không có lựa chọn local miễn phí** vì sáng tạo nội dung mới đòi hỏi LLM thật sự; nếu không truyền `provider`, hệ thống tự chọn provider nào đã có API key.
- API: `POST /api/videos/{video_id}/writer` (tham số `provider` tùy chọn), `GET /api/videos/{video_id}/writer`.
- Tái sử dụng hạ tầng `analysis_jobs`/`video_analyses` đã có sẵn (thêm `analysis_type = "writer"`) thay vì tạo bảng mới.
- Giao diện: nút "AI Writer" trên mỗi dòng video, drawer riêng hiển thị tiêu đề mới/ý tưởng/mô tả/hashtag/CTA/dàn ý kịch bản.

Sửa lỗi kiến trúc quan trọng phát hiện khi thêm loại phân tích thứ hai vào bảng `video_analyses` dùng chung: `save_video_analysis` trước đây luôn đánh dấu `analysis_status = completed` bất kể loại phân tích, `get_video_analysis` và các subquery trong `list_videos` không lọc theo `analysis_type` — nghĩa là lưu kết quả AI Writer có thể vô tình đánh dấu video "đã phân tích metadata xong" hoặc làm lệch dữ liệu hiển thị ở bảng video/drawer phân tích metadata. Đã thêm tham số `analysis_type` để tách biệt hoàn toàn, kèm test hồi quy `test_writer_analysis_does_not_disturb_metadata_pipeline`.

Đã kiểm thử: 14/14 unit test pass (thêm test cho `writer.py` và test hồi quy DB); kiểm thử API thực tế xác nhận luồng lỗi rõ ràng khi chưa cấu hình `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` (môi trường hiện tại chưa có key thật nên chưa gọi thành công một lần sinh nội dung thực sự qua mạng — cần điền key vào `.env` để dùng); endpoint phân tích metadata vẫn hoạt động đúng sau khi thêm bộ lọc `analysis_type` (regression); trang chủ render đầy đủ các phần tử giao diện mới.

Chưa thực hiện tiếp:

- Đăng ký callback webhook công khai (cần URL public).
- Giai đoạn 4 trở đi: dựng video, thumbnail, publisher/analytics.

## 36. Lộ trình hoàn thiện app - cập nhật 2026-08-11

### 36.1. Tình trạng hiện tại

Các phần nền tảng đã có:

- Theo dõi nhiều kênh, lưu metadata và quản lý video theo kênh/nhãn.
- Transcript có xác nhận trước khi chạy, hỗ trợ Whisper và lưu kết quả vào project.
- Project sản xuất, AI Writer, kịch bản có version, shot list và gói handoff cho OpenClaw.
- Giao diện tiếng Việt dạng wizard 7 bước: Nguồn → Phân tích → Kịch bản → Storyboard → Giọng & phụ đề → Dựng → Xuất bản.
- Có lựa chọn model/giọng/ngôn ngữ cho các bước sản xuất và có khu vực quản lý project.
- Có import media cục bộ, tải media thủ công từng video, hàng đợi phân tích/transcript và kiểm tra xác nhận trước tác vụ tốn tài nguyên.
- Có cơ chế tự dừng backend khi trình duyệt đóng: heartbeat theo tab, launcher `.bat` mở server và trình duyệt, tiến trình runtime được dừng idempotent.
- Kiểm tra hiện tại: Python compile pass, JavaScript inline syntax pass, bộ kiểm thử backend 53 test pass.

### 36.2. Các bước phải thực hiện tiếp theo

#### Bước 1 - Chạy một luồng sản xuất end-to-end làm chuẩn nghiệm thu

Chọn một video mẫu khoảng 90 giây và chạy đủ chuỗi:

`Nguồn → Phân tích → Kịch bản → chat chỉnh sửa → Storyboard → Giọng → Phụ đề → Dựng → QC → Xuất video`

Phải ghi lại lỗi ở từng bước, thời gian xử lý, file đầu ra và các thao tác người dùng cần làm. Không chuyển sang tính năng mới nếu luồng này chưa tạo được video hoàn chỉnh mở được và nghe/xem được.

#### Bước 2 - Hoàn thiện trình chỉnh sửa Storyboard

- Hiển thị từng cảnh cùng lời thoại, thời lượng, loại asset và prompt hình ảnh/video.
- Cho phép sửa lời thoại, prompt, thời lượng và thứ tự cảnh.
- Cho phép xoá, nhân bản, tạo lại một cảnh và đánh dấu cảnh đã đủ asset.
- Gắn asset local hoặc asset AI vào từng cảnh.
- Có preview nhanh từng cảnh và tổng thời lượng dự kiến.
- Lưu mọi thay đổi vào project, không chỉ lưu ở giao diện trình duyệt.

#### Bước 3 - Nâng chất lượng voiceover, phụ đề và timeline

- Ép toàn bộ video dùng một voice profile đã chọn, trừ khi người dùng chủ động chọn nhiều giọng.
- Chia voiceover theo từng cảnh để khớp storyboard, không tạo một audio dài rồi ghép ước lượng.
- Tự cắt khoảng lặng đầu/cuối và khoảng lặng bất thường giữa các đoạn.
- Đồng bộ subtitle theo timestamp voiceover, kiểm tra không thiếu câu và không tràn khung hình.
- Thêm ducking nhạc nền theo voiceover và giới hạn peak âm thanh.
- Ưu tiên GPU cho Faster-Whisper, VoxCPM và FFmpeg/NVENC khi phần cứng/driver hỗ trợ; hiển thị rõ đang dùng GPU hay CPU.
- Timeline phải có các lớp: hình/video chính, B-roll hoặc cảnh AI, voiceover, nhạc nền, hiệu ứng và subtitle.

#### Bước 4 - Bổ sung cảnh chuyển động và module Thumbnail

- Cho phép chọn nguồn hình ảnh/video: asset local, cắt cảnh từ video nguồn, ComfyUI/Flux/SDXL hoặc provider video AI.
- Tạo prompt cho từng cảnh từ storyboard và cho phép người dùng sửa prompt trước khi gọi model.
- Hỗ trợ ảnh chuyển động nhẹ (pan/zoom), cảnh video AI và cắt highlight từ video nguồn.
- Tạo nhiều thumbnail, cho phép chọn một bản cuối và gắn vào project.
- Lưu provider, model, prompt, seed và file đầu ra để có thể tái tạo kết quả.

#### Bước 5 - Xây dựng Quality Check trước khi xuất

QC phải kiểm tra tối thiểu:

- Có đủ asset cho mọi cảnh.
- Tổng thời lượng khớp mục tiêu và không có đoạn trống bất thường.
- Voiceover tồn tại, đúng voice profile và không có khoảng lặng vượt ngưỡng.
- Subtitle phủ đủ voiceover, đúng ngôn ngữ và không vượt giới hạn dòng.
- Video có độ phân giải, FPS, codec, container và âm thanh hợp lệ.
- Âm lượng không clipping; nhạc nền không lấn giọng.
- Có thumbnail, tiêu đề, mô tả và trạng thái duyệt của người dùng.

Kết quả QC phải hiển thị dạng đạt/cảnh báo/lỗi. Lỗi nghiêm trọng phải chặn nút xuất bản cho đến khi người dùng sửa hoặc xác nhận ngoại lệ.

#### Bước 6 - Hoàn thiện model catalog và kết nối AI

- Gom lựa chọn model vào một catalog thống nhất theo từng bước: LLM, STT, TTS/voice, image, video generation và render.
- Có nhóm `Local` và `Cloud`, hiển thị model đang dùng, VRAM yêu cầu và trạng thái sẵn sàng.
- Các API key/endpoint đặt trong Cài đặt, không rải ở từng màn hình.
- Có nút kiểm tra kết nối và thông báo lỗi dễ hiểu.
- Cho phép lưu preset theo workflow của từng kênh.
- OpenClaw chỉ điều phối qua API/handoff ổn định; chưa cần phụ thuộc OpenClaw để chạy luồng thủ công.

#### Bước 7 - Kết nối YouTube OAuth và xuất bản có kiểm soát

Chỉ thực hiện sau khi Bước 1 đến Bước 5 ổn định:

- Kết nối/ngắt kết nối OAuth cho tài khoản YouTube.
- Chọn kênh đích trong danh sách kênh người dùng quản lý.
- Chọn quyền riêng tư, playlist, thumbnail, tags, chapters và ngôn ngữ.
- Đặt lịch đăng và hiển thị múi giờ/thời điểm chính xác.
- Có hàng đợi upload, retry, cancel và lưu trạng thái lỗi.
- Luôn yêu cầu người dùng duyệt QC trước khi upload; không tự động đăng video chưa được duyệt.

#### Bước 8 - Workflow riêng cho từng kênh

- Tạo hồ sơ workflow cho mỗi kênh: ngôn ngữ, độ dài, tỉ lệ khung hình, model, voice, subtitle, thumbnail, lịch đăng và quy tắc CTA.
- Cho phép gắn một project vào workflow của kênh.
- Khi tạo video mới, tự nạp preset nhưng vẫn cho phép thay đổi từng bước.
- Có lịch đăng riêng theo kênh và tránh trùng job.

#### Bước 9 - Độ ổn định, tiến trình và dọn dẹp dữ liệu

- Chuẩn hoá job state: `queued`, `running`, `paused`, `completed`, `error`, `cancelled`.
- Thêm retry có giới hạn, resume sau khi app khởi động lại và nút huỷ job.
- Hiển thị log theo project/cảnh thay vì chỉ log chung ở terminal.
- Thiết lập retention cho file tạm, audio Whisper, cache model và media đã tải.
- Thêm backup database, migration rõ ràng và kiểm tra khi nâng cấp phiên bản.
- Kiểm tra launcher không tạo terminal nhấp nháy, trình duyệt đóng thì server dừng đúng thời gian cấu hình.

#### Bước 10 - Kiểm thử nghiệm thu và đóng gói sử dụng cá nhân

- Test một video nguồn, một video không có nguồn tham khảo và một video có nhiều cảnh.
- Test voice đơn, subtitle đa ngôn ngữ và model local/cloud.
- Test lỗi mất mạng, thiếu model, thiếu asset, GPU bận và người dùng đóng trình duyệt giữa chừng.
- Test nhiều project/kênh không làm lẫn dữ liệu.
- Chạy toàn bộ regression test và test thủ công launcher `.bat`.
- Cập nhật `HUONG_DAN_SU_DUNG.md` theo giao diện wizard hiện tại.
- Tạo bản sao lưu trước khi phát hành bản dùng ổn định cá nhân.

### 36.3. Thứ tự triển khai bắt buộc

`Bước 1 end-to-end → Bước 2 Storyboard → Bước 3 chất lượng dựng → Bước 4 asset/thumbnail → Bước 5 QC → Bước 6 model catalog → Bước 7 YouTube OAuth → Bước 8 workflow đa kênh → Bước 9 ổn định → Bước 10 nghiệm thu.`

Không triển khai upload tự động trước khi QC và cơ chế người dùng duyệt đã hoàn tất.

### 36.4. Tiêu chí app được xem là hoàn thiện phiên bản cá nhân

- Người dùng có thể bắt đầu từ một video hoặc media local và đi qua từng bước trên một giao diện đơn giản.
- Mỗi bước đều có model/giọng/ngôn ngữ được chọn rõ ràng và có kết quả hiển thị để chỉnh sửa.
- Storyboard chỉnh sửa được trước khi render.
- Video đầu ra có hình ảnh/cảnh chuyển động, voiceover nhất quán, subtitle khớp và không có khoảng lặng bất thường.
- QC báo cáo rõ lỗi trước khi cho phép xuất bản.
- Có thể quản lý nhiều kênh bằng workflow/preset riêng.
- Upload và đặt lịch chỉ chạy sau khi người dùng duyệt.
- Đóng trình duyệt sẽ dừng tiến trình backend theo cấu hình, không để terminal hoặc worker chạy ngầm ngoài ý muốn.

### 36.5. Tiến độ triển khai Storyboard - 2026-08-11

Đã hoàn thiện các thao tác còn thiếu trong trình chỉnh sửa Storyboard:

- Thêm cảnh trống trực tiếp từ giao diện để nhập lời dẫn, prompt, loại asset và thời lượng.
- Nhân bản một cảnh ngay sau cảnh gốc, giữ lại nội dung để người dùng chỉnh biến thể mới.
- Sắp xếp chỉ áp dụng cho đúng phiên bản kịch bản đang mở; các shot list của phiên bản cũ không bị thay đổi.
- Xoá cảnh tự đánh lại thứ tự liên tục; thêm/nhân bản/xoá/sắp xếp đều cập nhật thời điểm project và xuất lại `shot-list.md`.
- Timeline hiện tại được giữ nguyên có chủ đích khi storyboard thay đổi, tránh làm mất audio/asset đã chuẩn bị; người dùng cần rà soát hoặc tạo lại timeline trước khi render.
- Chuyển test OpenMontage sang `unittest` để bộ kiểm thử chạy được bằng dependency runtime hiện có, không cần cài thêm `pytest`.

Kiểm thử: Python compile pass, JavaScript giao diện parse pass, `python -m unittest discover -s tests -v` pass 54/54.

### 36.6. Nghiệm thu end-to-end và audio render - 2026-08-11

- Đã nghiệm thu Quality Check thực tế trên project 2 (99,387 giây) và project 3 (90,087 giây). Cả hai đều đạt visual, voiceover, SRT timestamp, đồng bộ thời lượng, cảnh chuyển động và mã hoá NVENC.
- Renderer FFmpeg nay chuẩn hoá voice theo EBU R128 (`-16 LUFS`, true peak `-1.5 dBTP`), lọc tần số thấp nhẹ và mã hoá AAC 192 kbps.
- Khi có nhạc nền, renderer dùng sidechain compression để tự hạ nhạc trong lúc có lời thoại, sau đó trộn ở mức an toàn để giảm nguy cơ clipping/lấn giọng.

Kiểm thử: xác nhận FFmpeg local có `highpass`, `loudnorm` và `sidechaincompress`; Python compile và 55/55 unit test pass.

### 36.7. Thumbnail local và Quality Check - 2026-08-11

- Bổ sung module thumbnail local: trích tối đa 6 frame 16:9 từ `final.mp4` bằng FFmpeg để người dùng có nhiều phương án nhanh, không phát sinh chi phí cloud.
- Mỗi phương án được lưu như asset project cùng provider (`ffmpeg_frame`), model, prompt, seed và file đầu ra; giao diện cho phép chọn một bản duy nhất làm thumbnail cuối.
- Quality Check nay yêu cầu thumbnail đã chọn và file còn tồn tại; project chưa chọn thumbnail sẽ có cảnh báo thay vì được xem là đủ điều kiện xuất.
- Đã chạy thực tế trên project 3: tạo 3 JPG, chọn một bản và QC đạt toàn bộ điều kiện.

Kiểm thử: Python compile, JavaScript giao diện parse, 57/57 unit test pass; QC project 3 pass (6 segment, 89,918 giây voice, 90,087 giây final).

### 36.8. Quality Gate kỹ thuật trước xuất bản - 2026-08-11

- QC nay kiểm tra stream video/audio thật qua FFprobe: MP4, codec H.264/HEVC/AV1, audio stream, độ phân giải tối thiểu HD và FPS 20–60.
- Giữ các kiểm tra trước đó: đủ visual/voice/SRT, đồng bộ thời lượng, cảnh chuyển động, NVENC và thumbnail đã chọn.
- Endpoint Publisher bắt buộc QC phải `pass`; nếu còn điều kiện lỗi, hệ thống trả danh sách check cần sửa và không tạo publication queue.
- Thumbnail đã chọn trong project được dùng mặc định cho bước xuất bản sau này; người dùng vẫn có thể chọn một asset ảnh khác khi cần.

Kiểm thử: 57/57 unit test pass. QC project 3 pass với 1920×1080, 30 FPS, H.264/AAC và MP4 container.

### 36.9. Cảnh ảnh động và kiểm tra khoảng lặng - 2026-08-11

- Ảnh local khi dùng làm visual nay tự có Ken-Burns pan/zoom nhẹ qua FFmpeg `zoompan`, thay vì đứng yên suốt segment.
- QC quét từng file voice bằng `silencedetect` không phá huỷ; khoảng lặng từ 1,5 giây được báo theo số đoạn để người dùng chỉnh lời thoại/TTS trước khi xuất.
- Đã xác nhận FFmpeg local hỗ trợ `zoompan`; QC project 3 vẫn đạt tất cả điều kiện sau khi quét 6 segment voice.

Kiểm thử: Python compile, 59/59 unit test pass.

### 36.10. Sao lưu database an toàn - 2026-08-11

- Thêm endpoint `POST /api/maintenance/database-backup` và nút **Sao lưu DB** trong Cài đặt.
- Backup dùng SQLite Online Backup API, đóng kết nối tường minh sau khi hoàn thành để bao gồm trạng thái WAL mà không để file bị khoá trên Windows.
- Đã kiểm thử snapshot có thể mở và đọc lại độc lập; tạo thành công backup thật tại `_HE_THONG/data/backups/`.

Kiểm thử: Python compile, JavaScript giao diện parse, 60/60 unit test pass.

### 36.11. Vận hành job và retention backup - 2026-08-11

- Production job đã có trạng thái `cancelled`: người dùng có thể hủy job còn ở hàng đợi, nên worker sẽ không claim hay tạo media cho job đó. Job đã chạy không bị kill cưỡng bức để tránh file media dang dở.
- Job lỗi hoặc đã hủy có nút **Chạy lại**; hệ thống tạo một job mới, giữ lại bản ghi cũ để truy vết lỗi và kết quả trước đó.
- Mỗi production job ghi nhật ký khi được xếp hàng, bắt đầu, hoàn tất, lỗi, bị hủy hoặc được khôi phục sau khi worker dừng. Nhật ký hiển thị ngay trong chi tiết project.
- Cài đặt có nút **Dọn backup cũ**. Chỉ các snapshot do app tạo (`youtube_monitor-*.db`) mới nằm trong phạm vi dọn dẹp; luôn giữ 14 bản mới nhất và yêu cầu xác nhận trước khi xóa.

Kiểm thử: có regression test cho hủy job không thể bị worker claim và retention backup không động tới file ngoài phạm vi app.

### 36.12. Preset sản xuất theo kênh - 2026-08-11

- Hồ sơ **Kênh của tôi** nay lưu preset thực thi gồm tỷ lệ đầu ra, ngôn ngữ, chuyển cảnh, voice provider/model và subtitle provider/model.
- Project mới được gắn kênh sẽ tự nhận preset khi chưa có render settings; project hiện có có nút **Áp dụng preset kênh vào render** để người dùng chủ động ghi đè các thiết lập này.
- Asset nhạc và voice-reference riêng của project không bị thay thế khi áp dụng preset, giúp thay đổi workflow kênh không làm mất file người dùng đã chọn.

### 36.13. QC loudness và clipping - 2026-08-11

- QC phân tích `final.mp4` bằng FFmpeg `volumedetect` và `loudnorm`, trả về integrated loudness, true peak và max volume.
- Final cần nằm trong vùng mục tiêu `-16 LUFS ±3` và không có clipping (true peak/max volume không vượt `-0,1 dB`). Không đo được audio cũng được báo rõ để tránh xuất bản thiếu kiểm soát.

### 36.14. Quản lý nhãn kênh nguồn và tải thư viện - 2026-08-11

- Kênh nguồn đã thêm có nút **Nhãn** để đổi/gỡ nhãn trực tiếp, không cần xoá và thêm lại hoặc đồng bộ lại video.
- Thư viện video tải tối đa 500 bản ghi thay vì 100, nên kênh mới đồng bộ không còn bị che bởi các video cũ khi dùng bộ lọc theo kênh/nhãn.

### 36.15. Launcher giữ server ổn định - 2026-08-11

- Launcher không còn tự dừng server theo heartbeat của trình duyệt. Server local chạy cho đến khi người dùng chủ động nhấn `Ctrl+C` hoặc đóng cửa sổ launcher.
- Cờ `YOUTUBE_AUTO_CLOSE_ON_BROWSER_EXIT` mặc định là tắt để tránh mất kết nối khi trình duyệt làm mới, chuyển tab hoặc bị chặn heartbeat.

### 36.16. Rút gọn lối vào tạo video - 2026-08-11

- Mỗi video trong thư viện có nút chính **Tạo video →**, mở thẳng wizard với video mẫu đã được chọn.
- Nút **Dự án chi tiết** được hạ thành tùy chọn nâng cao; người mới chỉ cần theo bốn thao tác chính trong wizard để tạo bản đầu tiên.

### 36.17. Đơn giản hóa wizard và khôi phục kết quả AI - 2026-08-12

- Thanh điều hướng chính chỉ còn **Tạo video**, **Video tham khảo** và **Công cụ & kết nối**. Kênh đích/Dự án chi tiết chỉ mở khi người dùng cần chỉnh sâu.
- Sau phản hồi sử dụng, **Kênh xuất bản** được giữ lại như một mục điều hướng riêng, vì đây là nơi người dùng tạo và quản lý preset theo kênh; chỉ **Dự án chi tiết** được đưa ra khỏi luồng chính.
- Wizard không còn hiển thị bảy tab thao tác đồng thời; chỉ hiển thị một giai đoạn hiện tại với nhãn rõ ràng.
- Khi chọn lại video mẫu, wizard tự khôi phục phân tích, kịch bản, storyboard và timeline đã lưu, đồng thời mở đúng giai đoạn gần nhất thay vì để kết quả nằm trong vùng ẩn.

## 36. Cập nhật triển khai: kết nối AI cloud và tạo cảnh video từ prompt

Đã bổ sung lớp tích hợp AI có thể cấu hình trực tiếp từ giao diện:

- Panel **KẾT NỐI AI CLOUD & APP LOCAL**: nhập/lưu OpenAI GPT API, Claude API và Runway API. API key được gửi tới server local, lưu trong `.env` của project và không được trả lại/trình bày trên giao diện.
- Provider GPT/Claude được đọc động sau khi lưu cấu hình; không cần sửa code hay khởi động lại chỉ để chuyển AI Writer từ Claude sang GPT hoặc ngược lại. Dropdown ở hàng đợi phân tích tiếp tục là nơi chọn provider cho bước phân tích/AI Writer.
- Codex và Claude Desktop được biểu diễn đúng là **handoff local**: app xuất JSON project để đưa vào agent/app desktop, không giả định rằng các app desktop có HTTP API để hệ thống điều khiển trực tiếp.
- Bổ sung adapter Runway đầu tiên cho bước dựng: mỗi segment timeline có prompt, thời lượng 5/10 giây, tỷ lệ khung hình và ảnh tham chiếu tùy chọn. Sau xác nhận chi phí, worker gửi task cloud, poll trạng thái, tải video kết quả về thư mục artifact và tự gắn `visual_path` vào segment để FFmpeg/Premiere dùng tiếp.
- Bảng `scene_generation_jobs` lưu task, provider, prompt, task ID, output, lỗi và trạng thái. Nhờ đó có thể thêm Kling/Veo/Sora hay provider khác bằng adapter mới mà không thay đổi schema timeline/Premiere.

Kiểm thử: Python compile pass, JavaScript giao diện parse pass, 34/34 unit test pass. Chưa gọi API Runway thật vì chưa có API secret/không có xác nhận chi phí từ người dùng; cần cấu hình key trong giao diện rồi tạo một cảnh thử 5 giây để xác nhận quyền API và quota thực tế.

## 31. Cập nhật triển khai: tab dashboard và lọc đa kênh

Đã bổ sung:

- Thanh tiêu đề của "Danh sách kênh" và "Danh mục video" có thể click trực tiếp để đóng/mở theo phong cách panel Vibe-Trading; trạng thái được nhớ bằng `localStorage`.
- Danh sách kênh được gom theo `group_name`; từng nhóm có tab click để mở/đóng riêng.
- Danh sách video có bộ lọc theo nhãn nhóm và kênh cụ thể trong nhóm, kèm số lượng video đang hiển thị và nút xoá lọc.
- Bộ lọc chỉ thay đổi phần hiển thị trên dashboard; không thay đổi dữ liệu metadata trong database và không ảnh hưởng API hàng đợi phân tích.

Đã kiểm thử: JavaScript nhúng trong template pass `node --check`; trang chủ trả về đầy đủ panel click trực tiếp, logic nhóm kênh và bộ lọc nhóm/kênh.

## 32. Cập nhật triển khai: FFmpeg renderer tích hợp

Đã bổ sung:

- Module `ffmpeg_renderer.py` tự tạo segment từ timeline bằng hình/video local hoặc nền màu mặc định, kèm audio local hoặc audio im lặng.
- Provider production mới `ffmpeg_builtin`, không cần viết `FFMPEG_RENDER_COMMAND` thủ công.
- Tự ghép các segment thành MP4 cuối cùng, đồng nhất độ phân giải 1920x1080, 30 FPS, H.264/AAC.
- Health và production queue báo thêm `ffmpeg_builtin_available`.
- UI project có nút `Render FFmpeg tự động` và hiển thị trạng thái FFmpeg local.

Đã kiểm thử: FFmpeg render thật tạo được MP4 smoke test; toàn bộ 32 unit test pass; Python compile, JavaScript giao diện và server live đều pass.

## 33. Cập nhật triển khai: pyVideoTrans adapter và trung tâm trạng thái tools

Đã bổ sung:

- Sửa adapter pyVideoTrans để tạo SRT theo từng segment, truyền các placeholder `srt_file`, `output_dir`, `voice_role`, `tts_type` và tự tìm audio đầu ra trong thư mục kết quả.
- Thêm cấu hình `PYVIDEOTRANS_WORKDIR`, `PYVIDEOTRANS_VOICE_ROLE`, `PYVIDEOTRANS_TTS_TYPE` và mẫu CLI TTS tương thích tài liệu chính thức.
- Thêm endpoint `GET /api/tool-status` kiểm tra YouTube API, Faster-Whisper, AI Writer, pyVideoTrans, FFmpeg, Premiere, OAuth, webhook và các module kế hoạch.
- Thêm panel `TRUNG TÂM TRẠNG THÁI TOOLS` trên dashboard để hiển thị tool nào sẵn sàng, cần cấu hình hoặc chưa dựng.

Đã kiểm thử: server live trả về trạng thái tool thực tế; Faster-Whisper, YouTube API, FFmpeg và Premiere plugin đang sẵn sàng; AI Writer, pyVideoTrans, OAuth và các module thumbnail/publisher/analytics còn chờ cấu hình hoặc triển khai.

## 34. Cập nhật triển khai: cài môi trường pyVideoTrans và kiểm tra TTS

Đã bổ sung:

- Clone repo pyVideoTrans chính thức tại `F:\pyVideoTrans`.
- Tạo môi trường riêng `.venv` bằng Python 3.10, không ảnh hưởng Python 3.13 của YouTube AI Factory.
- Cài dependency pyVideoTrans bằng `uv sync`; môi trường đã có `edge_tts` và Torch.
- App tự nhận diện repo/uv khi thấy `F:\pyVideoTrans`, không cần ghi đè `.env` hoặc lộ API key.
- Trung tâm trạng thái hiện báo pyVideoTrans runtime đã sẵn sàng và hiển thị voice role mặc định `vi-VN-HoaiMyNeural`.
- Smoke test TTS đã được thử với một câu ngắn; CLI không tạo output trong thời gian chờ do khả năng chờ kết nối/cache bên ngoài, nên tiến trình đã được dừng an toàn. Cần kiểm tra tiếp trong môi trường mạng ổn định hoặc chọn provider TTS khác trong pyVideoTrans.

## 35. Cập nhật triển khai: bật GPU cho Faster-Whisper

Đã bổ sung:

- Phát hiện máy có NVIDIA GeForce RTX 5070 Ti 16 GB, driver 610.47.
- Kiểm tra CTranslate2 nhận CUDA với 1 GPU.
- Faster-Whisper tự chọn `device=cuda`, `compute_type=float16` khi `WHISPER_DEVICE=auto`; tự fallback `cpu/int8` nếu máy không có CUDA.
- Health API hiển thị `whisper_device` và `whisper_compute_type`; dashboard báo rõ transcript đang chạy GPU hay CPU.
- Khởi tạo thành công model Faster-Whisper tiny trên CUDA.

Đã kiểm thử: 32/32 unit test pass, Python compile pass, JavaScript giao diện pass; server live đang báo `whisper_device=cuda`, `whisper_compute_type=float16`.

## 30. Cập nhật triển khai: AI Auto Draft cho Premiere và voiceover một nút

Đã bổ sung lớp tự động hóa Premiere Pro:

- Thư mục `premiere_plugin/` là plugin UXP development, manifest v5, tương thích Premiere từ 25.6.
- Panel tiếng Việt cho phép chọn thư mục `premiere_export`, đọc `premiere_manifest.json`, hiển thị số segment/audio/visual và chọn tạo sequence mới hoặc dùng sequence active.
- Plugin import media local, đặt visual lên V1, voiceover lên A2 theo `start_seconds`/`end_seconds`, cắt clip dài hơn segment, thêm marker theo từng đoạn và lưu project Premiere.
- Thêm job `premiere_draft`: chạy pyVideoTrans cho toàn bộ segment rồi tự tạo Premiere Export Pack trong một lần chạy.
- UI project có nút `AI voiceover + Premiere`; job thật vẫn yêu cầu `confirmed=true` và cấu hình `PYVIDEOTRANS_COMMAND` trong `.env`.
- UI project đã có bảng điều khiển `AI AUTO DRAFT` ở đầu drawer, hiển thị trạng thái adapter/worker, theo dõi job tự động và tự mở gói Premiere khi hoàn tất.
- Provider `dry_run` của `premiere_draft` chỉ tạo gói kiểm thử, không gọi TTS và không tạo media.

Kiểm thử: 31/31 unit test pass, Python compile pass, manifest JSON hợp lệ và JavaScript plugin pass `node --check`.

Chưa thể test thao tác timeline thật nếu máy chưa mở Premiere Pro/UXP Developer Tool; bước kiểm thử tiếp theo là load plugin vào Premiere, chạy trên một project mẫu và xử lý khác biệt theo phiên bản Premiere đang cài.

## 21. Cập nhật triển khai: khóa xác nhận cho thao tác kéo audio/video

Đã bổ sung một lớp an toàn cho các tính năng có dùng `yt-dlp`:

- `POST /api/videos/{id}/transcript/auto` bắt buộc payload có `confirmed: true`; nếu không, backend trả lỗi 400 và không trích xuất audio.
- `POST /api/transcript-queue` bắt buộc payload có `confirmed: true`; tránh việc gọi API nhầm làm chạy Whisper hàng loạt.
- `POST /api/videos/{id}/download` bắt buộc query `confirmed=true`; tránh tải mp4/mp3 về ổ đĩa khi chưa có xác nhận rõ.
- Giao diện tự hiển thị hộp xác nhận trước khi chạy Whisper đơn video, Whisper hàng loạt, tải video/audio hàng loạt và xoá file media đã tải.
- `GET /api/health` có thêm `whisper_requires_explicit_confirmation: true` để các client/OpenClaw sau này biết cần hỏi người dùng trước khi kích hoạt tác vụ này.

Chính sách hiện tại:

- Metadata sync và metadata analysis vẫn không tải media.
- Whisper chỉ tải audio tạm thời sau khi người dùng xác nhận, sau đó xoá audio tạm và chỉ lưu transcript.
- Tải mp4/mp3 để dựng lại là thao tác thủ công, có xác nhận, file được giữ đến khi người dùng xoá.

## 22. Cập nhật triển khai: xưởng dự án sản xuất

Đã bổ sung lớp quản lý project nội bộ để nối bước Monitor → Transcript → AI Writer → Workflow dựng video:

- Bảng `production_projects`: mỗi video có thể được đưa vào một dự án sản xuất, lưu `title`, `status`, `notes`, `created_at`, `updated_at`.
- Trạng thái project hiện tại: `draft`, `script`, `review`, `approved`, `archived`.
- API:
  - `GET /api/projects`: liệt kê các dự án sản xuất gần nhất.
  - `POST /api/videos/{video_id}/project`: tạo hoặc lấy lại project đã có của một video.
  - `PATCH /api/projects/{project_id}`: cập nhật tiêu đề, trạng thái hoặc ghi chú.
- UI:
  - Thêm panel "XƯỞNG DỰ ÁN SẢN XUẤT".
  - Thêm nút "Tạo dự án" trên từng dòng video.
  - Mỗi project hiển thị nguồn video, trạng thái, tình trạng transcript, tình trạng AI Writer, ghi chú, nút mở video và nút gọi AI Writer.
- `GET /api/summary` có thêm `production_projects` để dashboard/OpenClaw biết số project đang chờ xử lý.

Ý nghĩa cho OpenClaw sau này: thay vì phải quét toàn bộ bảng video, agent chỉ cần đọc `/api/projects` để biết video nào đã được người dùng chọn đưa vào pipeline sản xuất thật.

## 23. Cập nhật triển khai: chi tiết project và gói handoff cho OpenClaw

Đã bổ sung:

- `Database.get_production_project_bundle(project_id, transcript_text_limit)`: gom project, video nguồn, transcript mới nhất, phân tích metadata, kết quả AI Writer, readiness checklist và next actions vào một payload chuẩn.
- API `GET /api/projects/{project_id}`: trả bundle rút gọn cho giao diện, transcript preview giới hạn 2.000 ký tự.
- API `GET /api/projects/{project_id}/handoff`: trả bundle JSON có `handoff_version = "youtube_ai_factory.project.v1"` và `intended_consumer = "OpenClaw"`, transcript mặc định tối đa 50.000 ký tự; dùng `?transcript_chars=0` nếu cần lấy toàn bộ.
- UI: thêm nút "Chi tiết" cho từng project, mở drawer hiển thị trạng thái, checklist, video nguồn, từ khóa metadata, tiêu đề/dàn ý từ AI Writer, transcript preview và ghi chú project.
- UI: thêm nút "Xuất JSON OpenClaw" trong drawer chi tiết để mở trực tiếp endpoint handoff.

Ý nghĩa: đây là điểm nối rõ ràng giữa dashboard thủ công và agent workflow. Người dùng chọn video đưa vào project, kiểm tra transcript/AI Writer, sau đó OpenClaw có thể nhận một JSON duy nhất để chạy các bước tiếp theo như viết lại kịch bản sâu hơn, tạo shot list, dựng video, thumbnail và upload queue.

## 24. Cập nhật triển khai: kịch bản sản xuất theo project

Đã bổ sung module kịch bản sản xuất trước khi chuyển sang dựng video:

- Bảng `project_scripts`: lưu kịch bản theo `project_id`, có version, `script_title`, `hook`, `intro`, `main_content`, `cta`, `status`, `approved_at`.
- Trạng thái kịch bản: `draft`, `review`, `approved`.
- Mỗi lần bấm tạo bản nháp sẽ tạo một version mới; sửa nội dung sẽ cập nhật version hiện tại.
- Khi duyệt kịch bản, script chuyển `approved` và project cũng chuyển `approved`.
- Module `script_builder.py`: tạo bản nháp deterministic từ bundle project/AI Writer, không gọi LLM mới và không tốn token.
- API:
  - `GET /api/projects/{project_id}/script`: lấy kịch bản mới nhất.
  - `GET /api/projects/{project_id}/scripts`: xem lịch sử version.
  - `POST /api/projects/{project_id}/script/draft`: tạo bản nháp từ AI Writer/metadata hiện có.
  - `PATCH /api/scripts/{script_id}`: sửa tiêu đề, hook, intro, nội dung chính, CTA hoặc trạng thái.
  - `POST /api/scripts/{script_id}/approve`: duyệt kịch bản.
  - `GET /api/scripts/{script_id}/markdown`: xuất kịch bản dạng Markdown.
- UI: trong drawer "Chi tiết dự án" có thêm khối "Kịch bản sản xuất" để tạo draft, sửa trực tiếp, lưu, chuyển chờ duyệt, duyệt và xuất Markdown.
- Handoff OpenClaw (`/api/projects/{project_id}/handoff`) nay có thêm `latest_script` và readiness có thêm `has_script`, `script_approved`.

Ý nghĩa: project giờ có thể đi hết từ video nguồn → metadata/transcript → AI Writer → kịch bản đã duyệt. Đây là điều kiện tốt để bước kế tiếp tạo shot list, b-roll plan, voiceover segments và timeline dựng video.

## 25. Cập nhật triển khai: shot list / kế hoạch cảnh

Đã bổ sung cầu nối từ kịch bản đã duyệt sang workflow dựng video:

- Module `shot_planner.py`: tách kịch bản thành các cảnh gồm Hook, Intro, từng ý chính và CTA; tự ước tính thời lượng, loại asset và visual/B-roll prompt ban đầu.
- Bảng `project_shots`: lưu shot list theo `project_id` và `script_id`, gồm `shot_index`, `section`, `narration`, `visual_prompt`, `asset_type`, `duration_seconds`, `status`.
- Trạng thái cảnh: `planned`, `ready`, `done`.
- API:
  - `GET /api/projects/{project_id}/shots`: lấy shot list của kịch bản mới nhất.
  - `POST /api/projects/{project_id}/shots/generate`: tạo shot list từ kịch bản mới nhất, hỗ trợ `force` để tạo lại.
  - `PATCH /api/shots/{shot_id}`: sửa lời dẫn, prompt hình ảnh/B-roll, loại asset, thời lượng hoặc trạng thái.
  - `GET /api/projects/{project_id}/shots/markdown`: xuất shot list dạng Markdown.
- UI: trong drawer "Chi tiết dự án" có thêm khối "Shot list / kế hoạch cảnh", nút tạo shot list, tạo lại, xuất Markdown và chỉnh từng cảnh ngay trong giao diện.
- Handoff OpenClaw nay có thêm `latest_shots`; readiness có thêm `has_shot_plan`.

Ý nghĩa: project hiện có thể đi từ video nguồn → script approved → shot list có prompt hình ảnh/B-roll. Đây là đầu vào thực tế cho bước tiếp theo: voiceover segments, timeline dựng video và prompt thumbnail/ComfyUI.

## 18. Cập nhật triển khai: OAuth YouTube và caption chính chủ

Đã bổ sung:

- Module `oauth.py`: luồng OAuth 2.0 "installed app" chuẩn của Google (authorization code + refresh token), lưu token cục bộ tại `data/oauth_token.json` (đã thêm vào `.gitignore`, không commit), tự làm mới access token khi hết hạn.
- Module `youtube_captions.py`: `list_captions()` (liệt kê track caption có sẵn) và `download_caption()` (tải nội dung caption dạng SRT) qua OAuth Bearer token — tách riêng khỏi `youtube_client.py` vì dùng cơ chế xác thực khác (OAuth thay vì API key).
- API: `GET /api/oauth/youtube/status`, `GET /oauth/youtube/authorize` (redirect sang Google), `GET /oauth/youtube/callback` (nhận mã, đổi token), `POST /api/oauth/youtube/disconnect`, `GET /api/videos/{id}/captions`, `POST /api/videos/{id}/transcript/from-caption` (lưu với `source_type = "authorized_caption"` đã có sẵn trong schema).
- Giao diện: pill trạng thái OAuth + nút kết nối/ngắt kết nối trên topbar; danh sách caption chính chủ hiển thị trong drawer transcript khi mở, kèm nút "Nhập caption này" cho từng track.
- Cấu hình: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` trong `.env.example`. Không cần dependency mới (dùng `httpx` sẵn có, không dùng thư viện `google-auth`).

Giới hạn thực tế quan trọng cần lưu ý: `captions.download` của YouTube **chỉ thành công với video thuộc kênh mà tài khoản OAuth đã kết nối sở hữu/quản lý**. Với video của kênh khác (như kênh đang theo dõi để phân tích), API sẽ trả lỗi 403 dù đã có OAuth hợp lệ — đây là giới hạn từ phía Google, không phải hạn chế tự đặt ra. `captions.list` (xem danh sách track có sẵn) thì gọi được cho mọi video công khai. Tính năng này vì vậy hữu ích nhất cho kênh của chính người dùng; với kênh theo dõi của người khác, Whisper (mục 14) vẫn là nguồn transcript chính.

Đã kiểm thử: 18/18 unit test pass (thêm 4 test cho vòng đời token — đọc/ghi/xoá file, không cần mạng); kiểm thử API thực tế xác nhận đầy đủ các nhánh lỗi (chưa cấu hình OAuth, chưa kết nối, thiếu mã xác thực, Google từ chối cấp quyền) đều trả về thông báo rõ ràng thay vì lỗi 500; trang chủ render đầy đủ UI mới. Chưa test được luồng OAuth thành công thực sự (cần bạn tự tạo OAuth Client ID trên Google Cloud Console và điền vào `.env` trước).

## 19. Cập nhật triển khai: tải video thủ công để dựng lại (thay đổi chính sách)

**Đây là thay đổi chính sách, không chỉ tính năng mới.** Trước đó dự án tuân thủ tuyệt đối "không tải video" (metadata-first). Theo yêu cầu trực tiếp, đã bổ sung khả năng tải nguyên video về máy — nhưng có chủ đích giới hạn phạm vi để không biến thành công cụ tải hàng loạt/reup:

- Module `video_downloader.py`: tải video bằng `yt-dlp` (đã có sẵn), lưu vào thư mục `downloads/` riêng (đã thêm `.gitignore`), **không tự xoá** như audio Whisper vì mục đích là giữ lại để dựng.
- API: `POST /api/videos/{id}/download` (tải), `DELETE /api/videos/{id}/download` (xoá file + reset trạng thái).
- Thêm cột `local_media_path` vào bảng `videos`; `media_status` có thêm giá trị `downloaded_for_editing`.
- Giao diện: nút "Tải video để dựng lại" từng dòng video (có xác nhận trước khi tải), đổi thành "Xoá file đã tải" khi đã có file. Cập nhật lại các badge "KHÔNG TẢI VIDEO" trên topbar/sidebar/footer cho đúng thực tế mới (tách rõ "tải tự động: tắt" và "tải thủ công: từng video").
- `GET /api/health` đổi `download_enabled` (đã gây hiểu nhầm) thành `auto_download_enabled: false` + `manual_video_download_available: true`.

**Ràng buộc có chủ đích, không thương lượng khi triển khai:**

- Chỉ tải **từng video một, do người dùng chủ động bấm** — không có hàng đợi/pipeline tự động nào tải video hàng loạt theo kênh.
- Không có tính năng tự động đăng lại (reup) video nguyên vẹn lên YouTube hay bất kỳ đâu — xuất bản vẫn hoàn toàn thủ công, đúng nguyên tắc mục 1 ("người dùng vẫn kiểm duyệt và quyết định cuối cùng").
- Tính năng này được xây cho mục đích dựng lại có bổ sung bình luận/góc nhìn cá nhân (dạng reaction/commentary) — không phải để sao chép nguyên vẹn nội dung người khác. Trách nhiệm đánh giá mức độ biến đổi đủ để xuất bản hợp lệ (fair use) cho từng video cụ thể thuộc về người dùng.

Đã kiểm thử thực tế end-to-end: tải video thật (23 giây, ~4MB mp4) qua API → xác nhận file tồn tại trên đĩa và `media_status`/`local_media_path` cập nhật đúng trong DB → gọi xoá → xác nhận file bị xoá sạch và trạng thái reset về `not_downloaded`. 18/18 unit test vẫn pass sau khi thêm migration cột mới.

Cập nhật UI sau đó: đổi tên nút thành "Tải video" (rút gọn từ "Tải video để dựng lại"), bấm vào hiện dropdown 2 lựa chọn — "Tải video (mp4)" hoặc "Tải audio (mp3)". Backend `download_video()` nhận thêm tham số `media_type` ("video" | "audio"), dùng `FFmpegExtractAudio` postprocessor của yt-dlp cho lựa chọn audio. Đã test thật cả hai nhánh (mp4 và mp3) tải và xoá thành công.

## 20. Cập nhật triển khai: chọn nhiều video để thao tác hàng loạt

Đã bổ sung:

- Checkbox từng dòng video + checkbox "chọn tất cả" ở đầu bảng (chỉ áp dụng cho các video đang hiển thị trên trang, không phải toàn bộ lịch sử kênh).
- Thanh thao tác hàng loạt hiện ra khi có video được chọn, hiển thị số lượng đã chọn và các nút: Phân tích, Transcript (Whisper), AI Writer, Tải video, Tải audio, Bỏ chọn.
- Backend: `AnalysisQueue.enqueue_pending()` và `TranscriptQueue.enqueue_pending()` nhận thêm tham số `video_ids` (danh sách ID cụ thể) — khi có, dùng trực tiếp thay vì suy ra từ `channel_id`/`limit`. API `POST /api/analysis-queue` và `POST /api/transcript-queue` nhận thêm field `video_ids` trong request body (tối đa 200 ID/lần).
- AI Writer và Tải video/audio chưa có hàng đợi nền riêng (đang là API đơn video), nên thao tác hàng loạt cho hai việc này chạy tuần tự từng video một ở phía giao diện (JS), hiển thị tiến trình "đang xử lý N/tổng" và dừng ngay kèm thông báo lỗi rõ ràng nếu một video thất bại — không âm thầm bỏ qua lỗi.
- Riêng "Tải video"/"Tải audio" hàng loạt vẫn giữ hộp xác nhận hiển thị đúng số lượng video trước khi chạy, đúng tinh thần "chủ động xác nhận" đã thống nhất ở mục 19 — không có nút "chọn tất cả kênh rồi tải" nào bỏ qua bước xác nhận này.

Đã kiểm thử thực tế: gọi `POST /api/analysis-queue` và `POST /api/transcript-queue` với `video_ids` cụ thể (không qua `channel_id`) — xác nhận đúng chỉ các video được chỉ định vào hàng đợi, xử lý xong đúng số lượng. Một job transcript trong lúc test bị lỗi do YouTube tạm chặn yt-dlp ("Sign in to confirm you're not a bot", do gọi quá nhiều lần trong phiên test hôm nay) — đây là giới hạn tạm thời từ phía YouTube, không phải lỗi của tính năng; cơ chế ghi nhận lỗi hoạt động đúng (job chuyển trạng thái `error` kèm thông báo rõ ràng, không crash). 18/18 unit test vẫn pass.

Chưa thực hiện tiếp:

- Đăng ký callback webhook công khai (cần URL public).
- Giai đoạn 4 trở đi: dựng video, thumbnail, publisher/analytics.

## 37. Cập nhật triển khai: rà soát kỹ thuật toàn dự án và vá nền tảng (2026-08-17)

Sau khi đọc kỹ toàn bộ mã nguồn `_HE_THONG`, tài liệu kế hoạch này và các thử nghiệm GPU trong `_THU_NGHIEM`, đã triển khai loạt nâng cấp nền tảng (không phải tính năng sản phẩm), theo thứ tự:

- **Git**: repo trước đó không có version control nào (13.800+ dòng Python, sửa liên tục, không thể rollback). Đã `git init` tại gốc `F:\YouTube_AI_Factory`, thêm `.gitignore` loại trừ secrets (`config/.env`), database/backups, và toàn bộ nội dung sinh ra/tải về (`01_DU_AN`, `02_NGUYEN_LIEU`, `_THU_NGHIEM` — riêng `_THU_NGHIEM` nặng ~28GB do model cache của LTX-Video). Chỉ track mã nguồn, plugin Premiere, tài liệu và script khởi động (~8.5MB).
- **Test tầng HTTP**: 24 file test trước đó không có file nào gọi qua FastAPI thật (0/126 route được test tự động). Đã thêm `tests/conftest.py` (cô lập DB/thư mục project sang temp dir trước khi import bất kỳ module `youtube_monitor.*` nào, tránh đụng dữ liệu thật) và `tests/test_main.py` (11 test dùng `TestClient` thật, chạy cả `lifespan` — health, projects, model-catalog, tool-status, integrations, các nhánh lỗi validate/xác nhận).
- **2 bug đã sửa** trong `settings.py`: (1) hai thông báo lỗi tiếng Việt bị double-encode UTF-8 (mojibake) khi từ chối key không hợp lệ / giá trị chứa xuống dòng; (2) `save_integration_values()` ghi trùng comment `# Local integrations...` mỗi lần lưu một phần key mới (đã xác nhận lặp 5 lần trong `.env` thật, đã dọn lại file thật và sửa logic idempotent). Thêm `tests/test_settings.py` cover cả hai. Cũng sửa reference chết tới `PROJECT_PLAN.md` (không tồn tại) → trỏ đúng sang file này.
- **Lockfile**: `requirements.txt` chỉ ghim floor (vd. `yt-dlp>=2024.8.6` không trần) — cài lại trên máy khác có thể ra bản khác hẳn bản đang chạy thật. Đã tạo `requirements.lock.txt` ghim đúng phiên bản đang chạy thật trên máy này (đối chiếu trực tiếp với `pip freeze` của môi trường Python 3.13 hệ thống), đã kiểm tra cài sạch từ venv rỗng.
- **Điều tra pyVideoTrans/F5-TTS** (đã dừng dùng sau 2 lần lỗi thật ngày 2026-08-05, project 2): log lỗi thật cho thấy job đầu `[WinError 2] The system cannot find the file specified`, job sau `AttributeError: module 'torch' has no attribute 'cuda'` tại `F:\pyVideoTrans\videotrans\util\gpus.py:26` — môi trường `.venv` của pyVideoTrans khi đó bị hỏng cài đặt torch/CUDA. Đối chiếu với smoke test GPU thành công 2026-08-10 (`_THU_NGHIEM/pyvideotrans-f5-gpu-smoke`, sau khi môi trường đã được sửa) và kiểm tra trực tiếp `PYVIDEOTRANS_CUDA_READY`/`PYVIDEOTRANS_RUNTIME_READY` **ngay bây giờ đều `True`** — môi trường đã được khắc phục, không phải lỗi trong code app. Không có gì cần sửa trong `production_worker.py`/`settings.py`; job lỗi cũ trong DB có thể bấm "Chạy lại" bình thường. Lưu ý cấu hình mặc định (`tts_type=0`, voice Edge neural) thực chất chạy qua Edge-TTS (cloud) chứ không phải model F5-TTS local — nếu muốn tận dụng giọng local GPU đã tải (F5TTS_v1_Base, 1.3GB), cần đổi `PYVIDEOTRANS_TTS_TYPE` sang giá trị dùng model local và test lại bằng tiếng Việt (chưa từng test — smoke test 2026-08-10 dùng tiếng Trung).

Đã kiểm thử: `python -m pytest` toàn bộ `_HE_THONG/app/tests` — 103/103 pass (89 test cũ + 14 test mới).

## 38. Điều tra: vì sao OpenMontage chưa từng render project thật (2026-08-17)

Đề xuất trước đó ("thí điểm OpenMontage trên 1 project thật rồi cân nhắc đổi mặc định") dựa trên giả định OpenMontage chỉ đơn giản là "chưa ai bật thử". Đọc kỹ code cho thấy **lý do thật sự khác hẳn — đây là một chặn cứng có chủ đích, không phải khoảng trống cần lấp**:

- `main.py:2435-2439`: khi `settings.GPU_ONLY=True` (mặc định `YOUTUBE_GPU_ONLY=1`, launcher luôn set giá trị này — tức luôn bật trong thực tế), job `render` **chỉ chấp nhận provider `ffmpeg_builtin`**; mọi `openmontage*` bị từ chối thẳng với lỗi "GPU-only mode chỉ cho phép Render FFmpeg built-in với h264_nvenc".
- Lý do chặn là chính đáng: `_THU_NGHIEM/OpenMontage/tools/video/video_compose.py` (`_compose`, dòng 451; các nhánh khác dòng 2620/2648/2717) đọc `codec = inputs.get("codec", "libx264")` — **mặc định luôn là `libx264` (CPU, software encode)**, không có NVENC nào được truyền vào từ `openmontage_adapter.py::render_timeline()` (payload không có key `codec`). Nếu để lọt qua guard, render sẽ âm thầm chạy bằng CPU — vi phạm đúng chính sách "no silent CPU fallback" đã ghi trong `CHAY_YOUTUBE_AI_FACTORY.bat`.
- Vì vậy **không nên gỡ guard này**, và cũng không nên tự ý sửa `video_compose.py` (đây là clone vendor từ repo GitHub ngoài `calesthio/OpenMontage`, nằm trong `_THU_NGHIEM` — không track trong git của project, sửa trực tiếp sẽ lệch khỏi upstream).

Đường đi khả thi để thật sự "bật" OpenMontage cho GPU-only mode sau này (chưa làm, cần một phiên làm việc riêng để test render thật): sửa `openmontage_adapter.py::render_timeline()` để truyền `"codec": "h264_nvenc"` trong payload khi `nvenc_available()` — nhưng `_compose()` hiện dùng chung `-crf {crf} -preset {preset}` cho mọi codec (dòng 685), mà `h264_nvenc` không nhận `-crf` kiểu x264 (cần `-cq`/`-rc` và tên preset khác) — nghĩa là cần sửa thêm nhánh chọn tham số theo codec trong `video_compose.py`, rồi test render thật để xác nhận trước khi nới guard ở `main.py`. Vì đây là thay đổi có rủi ro (ảnh hưởng pipeline render thật, phụ thuộc code vendor bên ngoài), không tự thực hiện trong phiên này.

## 39. Cập nhật triển khai: tách router hệ thống/OAuth ra khỏi main.py (2026-08-17)

`main.py` là 1 file duy nhất chứa toàn bộ 126 route + mọi Pydantic model (3.266 dòng) — khó review/định vị khi cần sửa. Đã tách 2 nhóm route ít phụ thuộc chéo nhất ra `youtube_monitor/api/`:

- `api/routes_system.py`: `/`, `/api/health`, `/api/maintenance/*`, `/api/summary`, `/api/integrations` (GET/POST), `/api/integrations/codex/login`, `/api/openmontage/status`, `/api/model-catalog`, `/api/tool-status`, `/api/browser/heartbeat`.
- `api/routes_oauth.py`: toàn bộ `/api/oauth/youtube/*` và `/oauth/youtube/*`.

Nguyên tắc an toàn: **không đổi bất kỳ route nào còn lại trong `main.py`**. Các singleton (`database`, `production_worker`, `publisher_worker`, `scene_generation_worker`, `openmontage_adapter`, `browser_lease_monitor`, `template_path`) và helper `_api_error` vẫn định nghĩa nguyên trạng trong `main.py`; 2 router mới `import` ngược lại từ `..main` (import đặt sau khi `_api_error` đã định nghĩa xong, ngay trước `app.include_router(...)`, để tránh circular-import — đã gặp và sửa lỗi này trong lúc làm). `main.py`: 3.266 → 2.778 dòng.

Đã kiểm thử: `pytest` toàn bộ 103 test pass; **và khởi động app thật bằng `uvicorn` trên cổng phụ (8799, DB/project tách riêng khỏi dữ liệu thật)**, gọi thật `/`, `/api/health`, `/api/tool-status`, `/api/integrations`, `/api/oauth/youtube/status`, `/api/model-catalog`, `/api/summary` — toàn bộ trả 200 với dữ liệu đúng (bao gồm xác nhận lại `pyvideotrans_runtime_ready`/`voxcpm_runtime_ready` đều `true` qua route thật, khớp với điều tra mục 37).

**Chưa làm, để lại cho phiên sau:** phần lớn route còn lại (~2.200 dòng: projects/scripts/shots/timeline/assets/thumbnails/scene-jobs/publish — pipeline sản xuất chính) chưa tách, vì đây là phần ghép chặt nhất và rủi ro cao nhất nếu tách vội. Gợi ý ranh giới cho lần sau: `routes_channels_videos.py` (channels/managed-channels/videos), `routes_projects.py` (script/shots/timeline/render-settings), `routes_assets.py` (assets/thumbnails/voice-library/scene-jobs), `routes_jobs_publish.py` (production jobs/publications/premiere export).

## 40. Quyết định: không thêm Alembic cho migration DB (2026-08-17)

Đề xuất ban đầu là cân nhắc công cụ migration có version tracking (Alembic) thay cho cách hiện tại (`Database.initialize()`: `CREATE TABLE IF NOT EXISTS` + helper `_ensure_column()` tự ALTER thêm cột thiếu, không bảng version, không rollback). Sau khi đọc kỹ `database.py`, quyết định **không thêm Alembic**:

- `_ensure_column()` (dòng 546-549) chỉ làm đúng 1 việc, an toàn: đọc `PRAGMA table_info()`, chỉ `ADD COLUMN` khi cột chưa tồn tại — idempotent, đã dùng ổn định qua nhiều lần thêm cột thật trong lịch sử dự án (mục 14/16/19/25/26 ở trên), có test (`test_database.py`).
- Toàn bộ thay đổi schema từ trước đến nay chỉ là **thêm cột/bảng**, chưa từng cần đổi kiểu dữ liệu, xoá cột, hay rollback — đúng loại thay đổi mà cách làm hiện tại xử lý tốt.
- App chạy 1 máy, 1 người dùng, 1 file SQLite — không có nhiều môi trường (dev/staging/prod) cần đồng bộ version migration, vốn là lý do chính để dùng Alembic.
- Tài liệu kế hoạch đã tự ghi "có thể thay SQLite bằng PostgreSQL về sau" là **chưa lên lịch** — thêm Alembic bây giờ là chuẩn bị cho một thay đổi kiến trúc chưa được quyết định, thêm phụ thuộc/độ phức tạp không tương xứng với lợi ích hiện tại.

Rủi ro thật sự đã xác định (ALTER TABLE sai kiểu/xoá cột sẽ không rollback được) vẫn còn, nhưng mức độ thấp vì lịch sử thay đổi chỉ additive. Đã có sẵn `backup_to()` + nút "Sao lưu DB" trong Cài đặt làm lưới an toàn thủ công trước khi thử thay đổi schema rủi ro hơn — khuyến nghị: **bấm sao lưu DB thủ công trước khi merge bất kỳ thay đổi `database.py` nào không phải "thêm cột mới"**, thay vì đầu tư hạ tầng Alembic cho một nhu cầu chưa phát sinh.

## 41. Thêm provider `flow_veo`: tạo video Veo 3 qua gói thuê bao Flow (2026-08-17)

Người dùng đã trả phí **Google AI Pro/Ultra** (không phải trả theo API) và có quyền tạo video Veo 3 qua ứng dụng web **Flow** (`labs.google/flow`). Thay vì né phí, đây là dùng đúng quyền lợi gói đã mua — chỉ cần AI tự gửi prompt vào Flow thay vì copy tay từng cảnh.

Đã tận dụng gần như nguyên vẹn cơ chế pull-queue có sẵn cho `antigravity_image` (bảng `scene_generation_jobs`, claim atomic, hoàn thành 2 bước qua asset upload) — chỉ thêm phần lái trình duyệt bằng Playwright:

- `database.py`: tổng quát hoá `claim_next_antigravity_scene_job()` thành `claim_next_scene_job_for_provider()`, thêm `claim_next_flow_veo_scene_job()`, thêm hằng `EXTERNAL_SIDECAR_PROVIDERS = ("antigravity_image", "flow_veo")` dùng chung cho việc loại 2 provider này khỏi `SceneGenerationWorker`.
- `main.py`: thêm `"flow_veo"` vào 2 Literal request; thêm route `GET /api/flow-veo/next-scene-job` + `POST /api/flow-veo/scene-jobs/{id}/complete` (nhân bản đúng cặp route antigravity). **Thêm mới `POST .../fail` cho cả 2 provider** — trước đó sidecar không có cách nào báo job thất bại về app, job sẽ kẹt ở `running` đến khi app restart mới được requeue. **Tiện sửa luôn 1 bug thật phát hiện được**: endpoint batch tạo cảnh (`queue_scene_generation_batch`) có nhánh if/else lồng nhau khiến mọi provider không phải `runway`/`openai_image` (kể cả `antigravity_image` từ trước) bị bắt buộc phải có `GEMINI_API_KEY` dù không dùng — sửa thành `elif` tường minh khớp với endpoint tạo 1 cảnh.
- `flow_veo_sidecar.py` (mới): script độc lập mô phỏng `antigravity_scene_sidecar.py` nhưng dùng **Playwright** thay vì gọi CLI ngoài — vòng lặp poll job, mở Flow bằng browser context đã đăng nhập sẵn (lưu session cục bộ, chỉ cần đăng nhập tay 1 lần qua `--login`), điền prompt, chờ tạo xong, tải video, upload vào project, gọi complete/fail. **Selector DOM của Flow trong file là best-effort, chưa xác minh** (không ai trong phiên này có tài khoản Google đã đăng nhập để xem giao diện thật) — có sẵn chế độ `--recon` mở Playwright Inspector để tìm selector thật, cần làm bước này trước khi chạy vòng lặp thật.
- `templates/index.html`: thêm option "Flow (Veo 3)" vào cả 4 dropdown chọn provider tạo cảnh, xử lý giống Antigravity (không cần API key, hiện hint về gói thuê bao).
- `requirements.txt`/`requirements.lock.txt`: thêm `playwright`; đã cài + xác minh chromium chạy được trên môi trường Python thật của app.

**Lưu ý minh bạch đã nói với người dùng**: điều khoản dịch vụ tiêu dùng của Google thường không cho phép truy cập tự động ngoài API chính thức, kể cả tài khoản trả phí hợp lệ — rủi ro tài khoản bị gắn cờ/giới hạn là rủi ro người dùng tự chịu trên tài khoản của mình. Sidecar cố tình chờ giữa các job (20s) để giả lập tốc độ thao tác người thật, không giảm hoàn toàn rủi ro này.

Đã kiểm thử: `pytest` 108/108 pass (thêm 5 test: claim/complete/fail cho cả 2 provider, cô lập khỏi worker queue); khởi động app thật bằng uvicorn, gọi trực tiếp 3 route mới — đều đúng như kỳ vọng (`{"job": null}` khi hàng đợi rỗng, 404 cho job không tồn tại).

**Chưa làm, cần người dùng tự thực hiện tiếp**: chạy `python web_video_sidecar.py --provider flow_veo --login` để đăng nhập Google 1 lần, sau đó `--recon` để xác minh/sửa selector thật của Flow trước khi chạy vòng lặp thật lần đầu.

## 42. Tổng quát hoá thành nhiều web app: thêm Meta AI (Vibes) (2026-08-17)

Người dùng cần thêm web app khác ngoài Flow — Google hết quota thì cần chỗ dự phòng — và có nêu cụ thể "meta ai" và "gpt". Đã tra cứu trước khi làm:

- **Meta AI (Vibes)**: tạo video **miễn phí hoàn toàn**, không cần gói trả phí, chỉ cần đăng nhập Facebook/Instagram, qua `meta.ai` (tối đa 16s/1080p/16fps). Đã thêm làm provider `meta_ai_video`.
- **GPT/Sora**: đã loại — OpenAI đóng cửa app/web Sora tiêu dùng từ 26/4/2026, API cũng sunset 24/9/2026, ChatGPT Plus/Pro hiện không còn đường nào tạo video được nữa. Không có gì để tự động hoá.

Thay vì lặp lại nguyên bộ route + sidecar riêng cho từng web app mới (sẽ tái diễn đúng vấn đề monolith đã sửa ở mục 39), đã tổng quát hoá ngay lần thêm provider thứ 2 này:

- `database.py`: `BROWSER_SIDECAR_PROVIDERS = ("flow_veo", "meta_ai_video")` — nơi duy nhất cần khai báo provider mới; `EXTERNAL_SIDECAR_PROVIDERS` suy ra từ đây + `antigravity_image`. Bỏ hàm chuyên biệt `claim_next_flow_veo_scene_job()`, dùng thẳng `claim_next_scene_job_for_provider()` (đã tổng quát sẵn từ mục 41).
- `main.py`: thay 3 route `/api/flow-veo/*` bằng 3 route tổng quát `GET /api/browser-scene-jobs/next?provider=X`, `POST .../complete`, `POST .../fail` — validate theo `BROWSER_SIDECAR_PROVIDERS`. Thêm web app mới sau này chỉ cần thêm 1 giá trị Literal + 1 entry trong sidecar, không cần route mới. `/api/antigravity/*` giữ nguyên không đổi (Antigravity gọi tool built-in riêng, không phải browser, là tích hợp đã có tài liệu riêng).
- `flow_veo_sidecar.py` → đổi tên/tổng quát thành `web_video_sidecar.py`: 1 script, `--provider flow_veo|meta_ai_video`, mỗi provider có `PROVIDERS` config riêng (URL + selector best-effort) và thư mục profile đăng nhập riêng (chạy song song 2 process nếu muốn dùng cả 2 web app cùng lúc, không đụng session nhau).
- `templates/index.html`: thêm "Meta AI (Vibes)" vào cả 4 dropdown chọn provider; thay chuỗi `isAntigravity`/`isFlowVeo`/... đang phình dần bằng 1 bảng tra `SUBSCRIPTION_PROVIDER_HINTS`/`_SHORT` theo key provider — thêm provider thứ 4 sau này chỉ sửa 1 dòng thay vì mọi ternary chain.

Cùng lưu ý minh bạch như Flow: selector chưa xác minh (không có tài khoản Meta đã đăng nhập để kiểm tra DOM thật), và tự động hoá web app tiêu dùng có rủi ro ToS người dùng tự chịu trên tài khoản của mình.

Đã kiểm thử: `pytest` 109/109 pass; khởi động app thật, gọi `/api/browser-scene-jobs/next` cho cả 2 provider (đều `{"job": null}`), provider không hợp lệ trả 400, job không tồn tại trả 404.

**Chưa làm, cần người dùng tự thực hiện tiếp**: `python web_video_sidecar.py --provider meta_ai_video --login` rồi `--recon` để xác minh/sửa selector thật của Meta AI, tương tự bước đã cần làm cho Flow.
