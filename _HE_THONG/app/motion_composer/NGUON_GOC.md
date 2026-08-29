# Nguồn gốc và giấy phép của thư mục này

Thư mục `motion_composer/` **không phải code gốc của YouTube AI Factory**. Nó được
sao chép từ dự án ngoài:

- **Dự án:** OpenMontage — <https://github.com/calesthio/OpenMontage>
- **Phần được lấy:** `remotion-composer/` (các composition Remotion viết bằng
  React/TypeScript: biểu đồ động, thẻ số liệu, tiêu đề chuyển động, cảnh terminal…)
- **Giấy phép:** **AGPL-3.0** — xem `LICENSE` trong chính thư mục này.
- **Ngày sao chép:** 2026-08-29

## Nghĩa vụ giấy phép — đọc trước khi phát hành app

AGPL-3.0 lan sang phần mềm kết hợp với nó. Cụ thể với dự án này:

- **Chạy cục bộ cho kênh của mình: không phát sinh nghĩa vụ gì.** AGPL chỉ kích hoạt
  khi bạn *phân phối* phần mềm, hoặc *cho người khác dùng qua mạng*.
- **Nếu sau này bán, chia sẻ, hoặc chạy YouTube AI Factory thành dịch vụ trực tuyến
  cho người khác dùng**, thì toàn bộ app phải được phát hành dưới AGPL-3.0 (kèm mã
  nguồn), hoặc phải gỡ thư mục này cùng provider `motion_graphics` ra trước.
- App hiện chạy ở `127.0.0.1:8787` cho một người dùng trên chính máy đó, nên đang
  nằm gọn trong trường hợp thứ nhất.

## Ranh giới với code của dự án

- Thư mục này giữ **nguyên trạng** phần React/TypeScript của OpenMontage. Sửa đổi
  nên hạn chế tối đa để còn đối chiếu được với upstream.
- Phần Python điều khiển nó (`youtube_monitor/motion_graphics.py`) **là code của dự
  án này**, không sao chép từ OpenMontage, và giao tiếp qua dòng lệnh `remotion
  render` cùng một tệp props JSON.
- Danh sách kiểu cảnh và trường bắt buộc: xem `SCENE_TYPES.md` (tài liệu gốc của
  OpenMontage, giữ nguyên).

## `node_modules`

Không sao chép từ upstream. Cài bằng `npm ci` trong chính thư mục này, dùng
`package-lock.json` đã kèm để khoá đúng phiên bản. Thư mục `node_modules/` đã nằm
trong `.gitignore` của repo.
