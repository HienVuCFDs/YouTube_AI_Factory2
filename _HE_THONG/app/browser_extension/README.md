# YT Factory · AI Web Bridge (browser extension)

Chạy tự động Gemini/ChatGPT/Meta AI web ngay trong trình duyệt bạn đang dùng
hàng ngày (Cốc Cốc, Chrome, Edge — bất kỳ trình duyệt nào dựa trên
Chromium). Không mở trình duyệt riêng, không cần đăng nhập lại — dùng thẳng
các tab bạn đã đăng nhập sẵn.

## Cài đặt (một lần)

1. Mở `chrome://extensions` (Cốc Cốc cũng hiểu địa chỉ này; nếu không, vào
   menu trình duyệt > Tiện ích mở rộng > Quản lý tiện ích mở rộng).
2. Bật **Chế độ nhà phát triển / Developer mode** (góc trên bên phải).
3. Bấm **Tải tiện ích đã giải nén / Load unpacked**.
4. Chọn đúng thư mục này:
   `F:\YouTube_AI_Factory\_HE_THONG\app\browser_extension`
5. Xong — icon extension xuất hiện trên thanh công cụ. Bấm vào để xem trạng
   thái và bật/tắt từng provider.

## Yêu cầu

- App YT Factory phải đang chạy tại `http://127.0.0.1:8787`.
- Cần có ít nhất 1 tab đã đăng nhập trang tương ứng (gemini.google.com,
  chatgpt.com, hoặc www.meta.ai) — extension sẽ tự mở tab nền mới bằng
  đúng phiên đăng nhập hiện có trong trình duyệt, không cần bạn giữ tab mở
  sẵn, chỉ cần đã đăng nhập ít nhất một lần trong trình duyệt này trước đó.

## Cách hoạt động

Extension poll (mỗi 30 giây) đúng hàng đợi job mà `web_video_sidecar.py`
cũng dùng (`GET /api/browser-scene-jobs/next`) — dùng chung backend, không
cần sửa gì phía app. Khi có job: mở 1 tab nền (không làm phiền bạn), tự gõ
prompt, gửi, đợi ảnh/video xuất hiện, tải về, gửi lên app, gắn vào đúng
cảnh trong storyboard, rồi đóng tab.

## Nếu job báo lỗi "không tìm thấy phần tử" / "selector chưa khớp"

Selector (vị trí ô nhập prompt, nút gửi, khu vực ảnh kết quả) trong các file
`content_gemini.js` / `content_chatgpt.js` / `content_meta.js` là suy đoán
hợp lý ban đầu, **chưa được xác minh với giao diện thật** của 3 trang này.

Cách sửa nhanh, không cần đăng nhập lại:
1. Mở trang đó (vd `gemini.google.com/app`), bấm F12 mở DevTools.
2. Bấm biểu tượng con trỏ (Inspect), click vào đúng ô nhập prompt thật —
   xem tag/class/aria-label thật của nó.
3. Sửa mảng selector tương ứng trong file `content_*.js`.
4. Vào lại `chrome://extensions`, bấm nút Reload (hình mũi tên tròn) trên
   thẻ extension này.
5. Thử lại — không cần khởi động lại trình duyệt hay đăng nhập lại gì cả.

## Giới hạn đã biết

- Chỉ tạo ảnh/video từ mô tả văn bản (text-to-image); chưa hỗ trợ đính kèm
  ảnh tham chiếu (image-to-video) như bản `web_video_sidecar.py`.
- Điều khoản dịch vụ của Google/OpenAI/Meta nhìn chung không cho phép truy
  cập tự động các trang web tiêu dùng này, kể cả từ tài khoản hợp lệ. Rủi ro
  tài khoản bị giới hạn/gắn cờ là của bạn tự chịu trên tài khoản của mình.
