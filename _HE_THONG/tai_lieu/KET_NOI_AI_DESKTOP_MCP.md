# Kết nối ChatGPT app với YouTube AI Factory

YouTube AI Factory dùng **ChatGPT Chat làm AI điều phối chính** qua MCP. Luồng này không gọi Codex CLI để suy luận và không gọi model qua OpenAI API. Do ChatGPT không kết nối trực tiếp tới `127.0.0.1`, lớp truyền tải chính thức vẫn cần Secure MCP Tunnel và khóa Platform để chạy `tunnel-client`.

Giao diện web tại `http://127.0.0.1:8787` vẫn hoạt động độc lập: bạn có thể click thủ công như trước, hoặc chat trong ChatGPT để giao việc cấp cao. ChatGPT gọi các tool MCP để đọc/ghi project, còn worker của YouTube AI Factory tiếp tục xử lý job media, voice và render dài hạn.

## Cấu hình kết nối ChatGPT

MCP bridge của project nằm tại:

`F:\YouTube_AI_Factory\_HE_THONG\app\youtube_monitor\ai_desktop_mcp.py`

Bridge chỉ kết nối tới YouTube AI Factory đang chạy ở `http://127.0.0.1:8787`. Nó không đọc cookie, browser profile hay token ChatGPT.

Điều kiện phía tài khoản:

1. Tài khoản/workspace ChatGPT có Developer Mode và quyền dùng MCP app phù hợp.
2. Có `tunnel_id` trong OpenAI Platform và khóa dành cho `tunnel-client`.
3. Trong ChatGPT, tạo app ở Developer Mode, chọn kết nối **Tunnel** và chọn đúng `tunnel_id`.

Cấu hình tunnel theo MCP stdio, với lệnh server:

```text
"C:\Program Files\Python313\python.exe" "F:\YouTube_AI_Factory\_HE_THONG\app\youtube_monitor\ai_desktop_mcp.py"
```

Sau khi tạo tunnel, lưu `CHATGPT_MCP_TUNNEL_ID=<tunnel_id>` trong phần cấu hình tích hợp của YouTube AI Factory để dashboard hiển thị đúng trạng thái.

YouTube AI Factory và `tunnel-client` phải đang chạy khi ChatGPT gọi tool. Không cấu hình `tunnel-client` thành dịch vụ nền nếu bạn chưa chủ động muốn vậy.

## Cách giao việc trong ChatGPT

Ví dụ:

> Dùng YouTube AI Factory tạo một video 5 phút về lịch sử AI cho người mới. Hãy tự nghiên cứu, viết kịch bản trong chat này, lưu kịch bản vào app, xây storyboard và dừng lại trước bước tạo media để tôi duyệt.

Luồng task tự động:

1. ChatGPT gọi `youtube_factory_create_project` để tạo project và task Research.
2. ChatGPT gọi `youtube_factory_get_next_task`, thực hiện công việc ngay trong cuộc chat.
3. Với task Script, ChatGPT gọi `youtube_factory_save_script`; app tự tạo storyboard/timeline cơ bản.
4. ChatGPT gọi `youtube_factory_complete_task`; app tự tạo task kế tiếp.
5. Các bước tạo media, voice hoặc render chỉ chạy khi có `confirmed=true`.

Các tool quan trọng:

- Task: `youtube_factory_get_next_task`, `youtube_factory_complete_task`, `youtube_factory_fail_task`.
- Project/kịch bản: `youtube_factory_create_project`, `youtube_factory_list_projects`, `youtube_factory_save_script`, `youtube_factory_get_storyboard`, `youtube_factory_update_shot`.
- Media: `youtube_factory_generate_image`, `youtube_factory_generate_gif`, `youtube_factory_generate_video`, `youtube_factory_get_job_status`, `youtube_factory_approve_scene`.
- Hoàn thiện: `youtube_factory_build_timeline`, `youtube_factory_generate_voice`, `youtube_factory_render_video`, `youtube_factory_get_render_status`.

## Giới hạn cần hiểu đúng

- ChatGPT chỉ suy luận khi cuộc trò chuyện đang thực hiện một lượt chạy. Các job đã xếp hàng trong app có thể tiếp tục chạy độc lập.
- Ứng dụng web không thể âm thầm gọi gói thuê bao ChatGPT như một API. Chiều gọi đúng là ChatGPT gọi app qua MCP.
- Full MCP có hành động ghi hiện phụ thuộc gói và quyền Developer Mode của ChatGPT. Nếu tài khoản không có quyền này, phần kết nối ChatGPT Chat chưa thể bật chỉ bằng sửa code local.
- Gửi một link video và yêu cầu dựng lại có thể chạy theo chuỗi, nhưng các bước tốn tài nguyên hoặc xuất bản vẫn cần xác nhận theo policy của app.

Asset do công cụ ngoài tạo chỉ được import từ:

`F:\YouTube_AI_Factory\01_DU_AN\<project_id>\03_TAI_NGUYEN\ai_desktop_import`

Giới hạn này ngăn MCP đọc/ghi file tuỳ ý trên máy.
