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

**Push, không poll.** Extension giữ một kết nối WebSocket tới app
(`ws://127.0.0.1:8787/ws/browser-scene-jobs`) và không làm gì cả cho đến khi
chính app báo "có job" qua kết nối đó — không có vòng lặp nào tự động kiểm
tra định kỳ, không mở tab hay gọi trang web nào khi hàng đợi trống. Việc
kiểm tra hàng đợi (rẻ, trong tiến trình app, mỗi 2 giây) nằm ở phía server,
không phải phía extension.

Khi có thông báo: extension gọi đúng endpoint claim-job hiện có
(`GET /api/browser-scene-jobs/next`, dùng chung với `web_video_sidecar.py`,
không cần sửa gì phía app) để lấy job một cách an toàn, mở 1 tab nền (không
làm phiền bạn), tự gõ prompt, gửi, đợi ảnh/video xuất hiện, tải về, gửi lên
app, gắn vào đúng cảnh trong storyboard, rồi đóng tab.

Nếu mất kết nối app (vd app khởi động lại), extension tự kết nối lại; có
một alarm nền mỗi 1 phút chỉ để đảm bảo việc kết nối lại đó thực sự xảy ra
ngay cả khi trình duyệt tạm ngưng service worker của extension — bản thân
alarm đó không kiểm tra job.

## Nếu job báo lỗi "không tìm thấy phần tử"

Không còn selector viết sẵn cho từng trang. Extension chỉ chụp lại các phần
tử đang có trên trang (kèm nhãn, chữ, toạ độ, kích thước, class/id và chữ ở
khối bên cạnh) rồi gửi cho AI điều phối; AI chọn thao tác tiếp theo. Cách
tiếp cận cũ — đoán trước selector rồi viết cứng vào `content_<trang>.js` —
đã bị bỏ vì mỗi lần đoán sai chỉ lộ ra sau trọn một vòng tạo-rồi-hỏng, và
nó sai liên tục: giao diện hiển thị tiếng Việt, nút gửi là icon không nhãn,
khe khung hình là `div` chứ không phải `button`.

Vì vậy khi có lỗi dạng này, thứ cần xem là **báo cáo của AI điều phối trong
thông báo lỗi của job** (nó liệt kê đã thử những gì và trang hiện ra những
gì), chứ không phải đi sửa selector.

Gõ chữ và bấm chuột đi qua `chrome.debugger`, nên trình duyệt sẽ hiện dải
băng "đang được gỡ lỗi" trong lúc chạy job. Đây là bắt buộc: các trình soạn
thảo như Lexical (Flow, Meta AI) bỏ qua mọi sự kiện giả, nút gửi sẽ không
bao giờ mở khoá nếu thiếu nó.

## Giới hạn đã biết

- Meta AI (`meta_ai_video`) không tạo được video — đã xác nhận cả bằng thao
  tác tay, không phải lỗi tự động hoá. Provider này bị khoá ở API.
- Tạo video Flow (Veo) đã qua được mọi bước thao tác nhưng chưa có lần chạy
  nào đi hết vì hết tín dụng Flow; cần một lần chạy có tín dụng để nghiệm thu.
- Điều khoản dịch vụ của Google/OpenAI/Meta nhìn chung không cho phép truy
  cập tự động các trang web tiêu dùng này, kể cả từ tài khoản hợp lệ. Rủi ro
  tài khoản bị giới hạn/gắn cờ là của bạn tự chịu trên tài khoản của mình.
