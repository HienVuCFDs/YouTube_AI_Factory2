# YouTube AI Factory · Premiere UXP plugin

Plugin thử nghiệm để tự động dựng bản nháp trong Adobe Premiere Pro từ `premiere_manifest.json` do dashboard xuất ra.

## Plugin làm được gì?

- Đọc gói `premiere_export` đã được người dùng chọn.
- Import các file audio/video/ảnh local vào project Premiere.
- Tạo sequence mới hoặc dùng sequence đang active.
- Đặt visual lên V1, voiceover lên A2 theo `start_seconds`/`end_seconds`.
- Cắt phần cuối clip nếu media dài hơn segment.
- Thêm marker cho từng segment để dễ rà soát.
- Lưu project Premiere sau khi hoàn tất.

Phần AI Writer, tạo shot list và tạo giọng nói vẫn chạy ở dashboard Python. Plugin này là lớp điều khiển Premiere để biến timeline đã duyệt thành bản dựng thật.

## Điều kiện

- Adobe Premiere Pro 25.6 trở lên.
- UXP Developer Tool 2.2 trở lên.
- Bật Developer Mode trong Premiere rồi khởi động lại Premiere.

## Cách chạy

1. Trong dashboard, tạo script → shot list → timeline.
2. Nếu đã cấu hình `PYVIDEOTRANS_COMMAND`, bấm **AI voiceover + Premiere** để worker tự lồng tiếng và tạo gói Premiere một lần. Nếu chưa, chạy voiceover rồi bấm **Xuất gói Premiere** như workflow thủ công.
3. Giải nén file ZIP. Trong UXP Developer Tool, chọn `premiere_plugin/manifest.json` rồi bấm **Load & Watch**.
4. Trong Premiere, mở `Window → UXP Plugins → YouTube AI Factory`.
5. Bấm **Chọn thư mục Premiere Export** và chọn đúng thư mục chứa `premiere_manifest.json`.
6. Chọn **Tạo sequence mới** hoặc **Dùng sequence đang active**, sau đó bấm **Tạo bản dựng tự động**.

## Lưu ý

- Đây là plugin development, chưa đóng gói để phân phối Marketplace.
- API UXP của Premiere còn thay đổi theo phiên bản; nếu plugin import được nhưng không đặt clip, mở Debug trong UXP Developer Tool để xem lỗi rồi điều chỉnh theo phiên bản Premiere đang cài.
- Gói Premiere chỉ chứa media local đã gắn vào timeline. Hệ thống không tự tải video YouTube.
