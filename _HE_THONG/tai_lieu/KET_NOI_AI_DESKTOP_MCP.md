# Kết nối MiniMax Design, Claude và Antigravity với YT Factory

YT Factory đã có một MCP local tại:

`F:\YouTube_AI_Factory\_HE_THONG\app\youtube_monitor\ai_desktop_mcp.py`

MCP này không cần API key của Claude, Google hay MiniMax. Nó chỉ trao đổi với YT Factory đang chạy ở `http://127.0.0.1:8787` và chỉ import file từ thư mục an toàn của từng dự án.

## Thêm vào MiniMax Design

Trong phần **MCP / Tools / Add local server** của MiniMax Design, thêm server local với các giá trị:

- Name: `youtube_factory`
- Command: `C:\Program Files\Python313\python.exe`
- Arguments: `F:\YouTube_AI_Factory\_HE_THONG\app\youtube_monitor\ai_desktop_mcp.py`
- Environment: `YOUTUBE_FACTORY_URL=http://127.0.0.1:8787`

Nếu MiniMax hiển thị ô cấu hình JSON theo chuẩn OpenCode, dùng:

```json
{
  "mcp": {
    "youtube_factory": {
      "type": "local",
      "command": [
        "C:\\Program Files\\Python313\\python.exe",
        "F:\\YouTube_AI_Factory\\_HE_THONG\\app\\youtube_monitor\\ai_desktop_mcp.py"
      ],
      "environment": {
        "YOUTUBE_FACTORY_URL": "http://127.0.0.1:8787"
      },
      "enabled": true
    }
  }
}
```

Khởi động lại MiniMax Design sau khi lưu cấu hình.

## Claude Desktop

Trong **Settings → Developer → Edit Config**, thêm vào `mcpServers`:

```json
{
  "mcpServers": {
    "youtube_factory": {
      "command": "C:\\Program Files\\Python313\\python.exe",
      "args": [
        "F:\\YouTube_AI_Factory\\_HE_THONG\\app\\youtube_monitor\\ai_desktop_mcp.py"
      ],
      "env": {
        "YOUTUBE_FACTORY_URL": "http://127.0.0.1:8787"
      }
    }
  }
}
```

Nếu đã có `mcpServers`, chỉ thêm entry `youtube_factory`, không ghi đè các server khác.

## Google Antigravity

Trong **MCP Servers / Add local MCP server**, sử dụng cùng Command, Arguments và Environment của phần MiniMax. Antigravity cần khởi động lại sau khi thêm.

## Cách dùng trong app AI

Mở YT Factory trước, sau đó có thể giao một yêu cầu cấp cao thay vì điều khiển từng nút:

> Dùng `youtube_factory_create_project` để tạo video giải thích lịch sử AI cho người mới, dài khoảng 5 phút. Chưa tự render; hãy để Research, Script, Director, Media và QC Agent thực hiện và nghiệm thu chéo, rồi dùng `youtube_factory_get_pipeline_status` báo lại các lỗi còn thiếu.

MCP hiện cung cấp các nhóm tool cấp cao:

1. **Project và đa AI**: `youtube_factory_create_project`, `youtube_factory_start_pipeline`, `youtube_factory_get_pipeline_status`, `youtube_factory_create_agent_task`, `youtube_factory_list_agent_tasks`, `youtube_factory_list_events`.
2. **Provider Gateway**: `youtube_factory_list_providers`, `youtube_factory_route_provider`.
3. **Media bất đồng bộ**: `youtube_factory_generate_image`, `youtube_factory_generate_gif`, `youtube_factory_generate_video`, `youtube_factory_get_job_status`, `youtube_factory_approve_scene`.
4. **Timeline, voice và render**: `youtube_factory_build_timeline`, `youtube_factory_generate_voice`, `youtube_factory_render_video`, `youtube_factory_get_render_status`.
5. **Tương thích luồng import cũ**: `youtube_factory_list_projects`, `youtube_factory_get_storyboard`, `youtube_factory_import_asset`, `youtube_factory_import_assets_batch`, `youtube_factory_complete_antigravity_scene`.

Các tool tạo media, voice hoặc render yêu cầu `confirmed=true`. Tool tạo video còn bắt buộc `reference_asset_id` của ảnh scene đã có; MCP không được tự hạ xuống text-to-video khi thiếu ảnh nguồn.

Luồng đa AI không cho CLI truy cập trực tiếp SQLite. App lưu `AgentTask`, message A2A, review chéo, event và quyết định provider; MCP chỉ là hợp đồng để agent gọi công cụ cấp cao.

Nếu một reviewer hết hạn mức, pipeline trả trạng thái `review_required` và giữ nguyên output executor. App tự thử lại phần review sau thời điểm reset; nó không chạy lại executor. Khi provider không báo giờ reset nhưng tài khoản đã hồi phục, mở YT Factory và bấm **Cho thử lại** trong banner hạn mức để cho phép một lượt probe ngay.

Asset chỉ được import từ:

`F:\YouTube_AI_Factory\01_DU_AN\<project_id>\03_TAI_NGUYEN\ai_desktop_import`

Điều này giúp app AI không có quyền đọc/ghi tuỳ ý trên máy và không cần lấy cookie/token đăng nhập.
