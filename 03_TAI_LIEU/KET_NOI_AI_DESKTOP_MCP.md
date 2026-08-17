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

Mở YT Factory trước, sau đó trong MiniMax/Claude/Antigravity gửi yêu cầu sau:

> Dùng tool youtube_factory_list_projects và youtube_factory_get_storyboard cho dự án 27. Tạo một ảnh 16:9 theo prompt của cảnh 1. Lưu file PNG vào import_folder mà tool trả về, sau đó dùng youtube_factory_import_asset để gắn ảnh vào đúng segment_id cảnh 1.

MCP có 4 tool:

1. `youtube_factory_list_projects` — lấy danh sách dự án.
2. `youtube_factory_get_storyboard` — lấy lời đọc, prompt, ID cảnh và thư mục import.
3. `youtube_factory_import_asset` — upload + gắn một ảnh/video/audio vào cảnh.
4. `youtube_factory_import_assets_batch` — upload + gắn nhiều asset.

Asset chỉ được import từ:

`F:\YouTube_AI_Factory\01_DU_AN\<project_id>\03_TAI_NGUYEN\ai_desktop_import`

Điều này giúp app AI không có quyền đọc/ghi tuỳ ý trên máy và không cần lấy cookie/token đăng nhập.
