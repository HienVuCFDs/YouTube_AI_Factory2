# YouTube AI Factory

## Khởi động

1. Chạy `CHAY_YOUTUBE_AI_FACTORY.bat`.
2. Ứng dụng mở tại `http://127.0.0.1:8787`. Nếu không tự mở, dán địa chỉ này vào trình duyệt.
3. Server tiếp tục chạy khi bạn đóng tab trình duyệt. Dừng app bằng `Ctrl+C` trong cửa sổ launcher khi đã dùng xong.

Không cần sửa code hay database để sử dụng bình thường. API key và cấu hình model chỉ nhập trong **Cài đặt** của app; key không được hiển thị lại trên giao diện.

## Auto Pipeline đa AI

1. Mở **Cài đặt → Auto Pipeline đa AI**.
2. Viết yêu cầu cấp cao cho video. Chỉ bật **tạo media** hoặc **tự render** khi tài khoản/provider tương ứng đã sẵn sàng; để tắt khi chỉ muốn thử Research → Script → Director → Media → QC mà không tốn credit.
3. Bấm khởi động. App tự tạo/giao task cho Codex CLI, Claude Code CLI hoặc Antigravity theo cấu hình fixed/auto/fallback. Output của một AI phải được AI khác nghiệm thu trước khi chuyển role.
4. Theo dõi executor, reviewer, message A2A, event và chi phí ước tính ngay trong panel. Đóng/reload trang không làm mất task vì trạng thái được lưu trong database.
5. Nếu thấy **CHỜ AI NGHIỆM THU**, output executor vẫn an toàn; reviewer đang hết hạn mức hoặc chưa sẵn sàng. App tự thử lại khi tới giờ reset. Nếu bạn biết tài khoản đã hồi phục, bấm **Cho thử lại** trong banner hạn mức; phần review tiếp tục mà không chạy lại executor.

Auto Pipeline không tự xuất bản. Dù QC đã đạt, người dùng vẫn phải duyệt bước cuối cùng trước khi đưa video ra ngoài.

## Quy tắc và hạn mức tự động

Mở **Cài đặt → Quy tắc & hạn mức tự động**. Đây là luật áp cho mọi lượt chạy tự động; app từ chối job vi phạm ngay khi tạo, không chạy rồi mới báo.

- **Quy tắc bắt buộc**: đoạn văn được gửi kèm mọi task cho AI.
- **Điểm tối thiểu để AI duyệt task** và **điểm tối thiểu để nhận một cảnh**: dưới ngưỡng thì task quay lại executor, hoặc cảnh bị đánh trượt và tạo lại. Note nghiệm thu ghi rõ điểm/ngưỡng để bạn phân biệt ảnh thật sự hỏng với ảnh chỉ thiếu điểm.
- **Trần chi phí mỗi dự án / mỗi ngày** (USD, `0` = không giới hạn): chỉ chặn provider thực sự tốn tiền. Flow, Antigravity, ChatGPT/Gemini web chạy bằng gói đã trả nên không bị trần này chặn. Batch dừng đúng tại cảnh sẽ vượt trần và nói rõ lý do, thay vì từ chối cả lượt.
- **Cho phép API trả phí**: tắt mặc định. Bật thì Runway, OpenAI Image và Gemini/Veo API mới được dùng.
- **Cho phép media qua gói thuê bao**: tắt nếu muốn app không đụng tới Flow/Antigravity/ChatGPT web.
- **Hết provider thì tạm dừng**: khi không còn provider nào khả dụng cho một loại media, app dừng và tạo một yêu cầu phê duyệt thay vì để từng cảnh lần lượt thất bại. Lỗi lặp lại chỉ hỏi một lần.

Ô xuất bản cần người duyệt cuối luôn bật và không tắt được.

## Luồng sản xuất chuẩn

1. Vào **Video** và chọn video nguồn, hoặc tạo project từ media local.
2. Tạo **Project**, chọn kênh đích nếu cần, rồi chạy phân tích/transcript khi bạn có quyền dùng nguồn đó.
3. Dùng **AI Writer** để tạo kịch bản. Đọc, sửa và duyệt bản kịch bản trước khi sang bước tiếp theo.
4. Trong **Storyboard**, thêm/nhân bản/sửa/sắp xếp cảnh. Kiểm tra lời dẫn, prompt, loại asset và thời lượng từng cảnh.
5. Tạo **Timeline**, gắn asset local hoặc cảnh video AI cho từng đoạn. Chọn voice, subtitle, transition và định dạng đầu ra trong phần render settings.
6. Chạy voiceover và render. Với job tốn CPU/GPU, app sẽ hỏi xác nhận trước khi đưa vào worker.
7. Tạo các thumbnail từ video render, chọn đúng một bản cuối.
8. Mở **Quality Check**. Chỉ tiếp tục khi QC đạt; kiểm tra lại nếu có cảnh báo về asset, voice, subtitle, khoảng lặng, loudness/clipping, codec hoặc thumbnail.
9. Tải `final.mp4` hoặc gói Premiere trong thư mục dự án. Kết nối/đăng YouTube là bước riêng, chỉ thực hiện sau khi QC đã đạt và người dùng duyệt.

## Thêm nguồn tham chiếu

Trong **Video tham khảo**, khối **Thêm nguồn tham chiếu** có hai lựa chọn:

- **Kênh**: dán URL kênh / `@handle` / channel ID. App đồng bộ danh sách video của kênh theo giới hạn đã cấu hình.
- **Một video**: dán URL video dạng `youtube.com/watch`, `youtu.be` hoặc `youtube.com/shorts`. App chỉ lấy metadata của đúng video đó; không quét các video khác trong kênh.

Ở bước đầu tiên của **Tạo video**, chọn **Kênh video tham chiếu** trước. Danh sách ở ô kế tiếp chỉ chứa video thuộc kênh đó, tránh lẫn video của nhiều kênh.

### Đường tắt dễ nhất

Trong **Video tham khảo**, tìm video mẫu rồi bấm **Tạo video →**. App mở thẳng wizard với video đó đã được chọn. Chỉ đi theo các nút chính: **1. Phân tích video** → **Viết kịch bản bằng AI** → **Tạo storyboard bằng AI** → **Tạo timeline** → **Dựng video**. Có thể bỏ qua phần dự án chi tiết cho video đầu tiên; wizard tự mở lại đúng bước và kết quả đang làm khi bạn quay lại.

### Remake sáng tạo: tạo video mới từ video tham chiếu

`Transcript` là phần lời nói của video được chuyển thành văn bản. App tự dùng transcript nếu đã có; đây không phải bước bắt buộc bạn phải làm thủ công trước khi tạo video. Có transcript, phân tích hiểu chính xác hơn diễn biến và nhịp kể; không có transcript, app vẫn phân tích metadata nhưng sẽ nêu rõ giới hạn dữ liệu.

Luồng tạo video mới trong **Tạo video**:

1. Chọn video tham chiếu, rồi nhập **Ý tưởng video mới**. Ví dụ: “Giữ cảm xúc ấm áp nhưng đổi nhân vật chính từ chó thành mèo, sống ở khu chung cư.”
2. Chọn cách biến tấu, bấm **Phân tích tham chiếu**. Kết quả gồm công thức kể chuyện, bản đồ cảnh, nhịp dựng, ngôn ngữ hình ảnh và các giới hạn của dữ liệu nguồn.
3. Bấm **Viết kịch bản bằng AI**. AI phải tạo câu chuyện mới độc lập, không review/tóm tắt/kể lại video gốc. Kết quả có kịch bản hoàn chỉnh và blueprint từng cảnh với prompt cho ảnh/video AI mới.
4. Bấm **Tạo storyboard bằng AI**. Khi blueprint có sẵn, shot list sẽ ưu tiên `ai_scene` và prompt gốc cho từng cảnh, không yêu cầu cắt lại video tham chiếu.

Lưu ý: phân tích phong cách từ transcript chỉ là suy luận có ghi rõ mức độ tin cậy; nó không thể khẳng định chi tiết khung hình khi chưa có dữ liệu hình ảnh. Với WF Content, ảnh có thể tạo bằng Flow trong Cốc Cốc, `gflow-cli`, ChatGPT/Gemini web hoặc API đã cấu hình. Video mặc định đi qua Google Flow/Veo bằng `gflow-cli` và luôn dùng ảnh storyboard làm khung đầu. App luôn yêu cầu xác nhận trước khi đưa tác vụ cloud vào hàng đợi.

## Google Flow và Cốc Cốc

- **Flow trong Cốc Cốc** dùng provider `flow_image` (ảnh) hoặc `flow_veo` (video legacy). Cần cài/bật Extension YT Factory trong Cốc Cốc và đăng nhập Google trực tiếp trên trình duyệt. App tự mở/tái sử dụng workspace Flow theo project.
- **Flow qua gflow-cli** dùng provider `gflow_image` (ảnh/GIF) hoặc `gflow_cli` (video). Tool này có profile đăng nhập riêng; một tab Flow đang mở trong Cốc Cốc không tự biến profile `gflow-cli` thành đã đăng nhập.
- Không nhập ID/mật khẩu Google vào app. Chỉ đăng nhập một lần trong cửa sổ Google do trình duyệt/tool mở; app không lưu hoặc hiển thị mật khẩu.
- WF Reup lấy hình từ video nguồn nên không gọi Flow/AI tạo ảnh. Nếu một cảnh Reup thiếu hình, sửa mốc cắt hoặc xuất lại clip nguồn thay vì thay bằng ảnh AI.

## Kho footage mở — tạo cảnh động không tốn credit

Trong **Tạo video → Studio**, ô chọn loại video có mục **Kho footage mở · Archive.org + NASA · miễn phí**. Nó lấy footage thật public-domain thay vì sinh cảnh bằng AI, nên không cần API key, không dùng credit Flow và không cần Extension.

- Dùng khi Flow hết credit hoặc chưa đăng nhập, hoặc khi cảnh cần hình ảnh có thật (vũ trụ, tư liệu lịch sử, đời sống Mỹ giữa thế kỷ 20) hơn là hình do AI vẽ.
- App tự rút từ khoá từ prompt storyboard, nới dần truy vấn nếu quá hẹp, xếp ứng viên theo mức khớp tiêu đề, rồi cắt đúng thời lượng cảnh và chuẩn hoá về tỉ lệ dự án. Clip lấy ở giữa phim để tránh tiêu đề và đếm ngược đầu phim.
- Clip không có tiếng; lời dẫn vẫn do timeline trộn vào như mọi cảnh khác.
- Nguồn từng clip được ghi vào **`NGUON_FOOTAGE.json`** trong thư mục dự án: nguồn, tiêu đề, URL trang, giấy phép và dòng ghi công. Public domain không bắt buộc ghi công, nhưng hãy giữ file này để trả lời được khi có người hỏi cảnh lấy ở đâu.
- Khi Flow còn dùng được, app vẫn tự ưu tiên Flow: Flow tạo footage đúng cho cảnh, còn kho lưu trữ chỉ đưa được thứ có thật gần nhất. Ảnh do AI chấm lại như mọi cảnh khác, cảnh lệch nội dung sẽ bị đánh trượt và làm lại.

## Quản lý job và dữ liệu

- Job đang chờ có thể **Hủy**. Job đang chạy không bị dừng cưỡng bức để tránh tạo file media hỏng.
- Job lỗi hoặc đã hủy có nút **Chạy lại**. Lịch sử và nhật ký của mỗi job nằm trong Chi tiết project.
- Trong **Cài đặt**, nút **Sao lưu DB** tạo snapshot SQLite nhất quán tại `_HE_THONG/data/backups`.
- Nút **Dọn backup cũ** chỉ xóa snapshot do app tạo sau khi hỏi xác nhận và luôn giữ lại 14 bản mới nhất. Không xóa media, project hay file ngoài thư mục backup.

## Kênh, model và cấu hình

- **Kênh xuất bản** lưu preset thực thi: định dạng đầu ra, ngôn ngữ, chuyển cảnh, voice và subtitle, cùng workflow tham khảo/lịch mặc định. Project mới nhận preset tự động; với project đang làm, dùng nút **Áp dụng preset kênh vào render** trong phần Tổng quan.
- **Model catalog** cho biết model/local runtime nào sẵn sàng. Những mục cloud cần API key hợp lệ; những mục GPU cần cài runtime và driver tương ứng.
- `DANG_NHAP_CODEX.bat` chỉ dùng khi muốn dùng Codex CLI làm AI Writer mà không nhập OpenAI API key.

## Cấu trúc thư mục

- `01_DU_AN`: từng project video. `04_XUAT_BAN/final.mp4` là video cuối; `05_PREMIERE` chứa gói Premiere.
- `01_DU_AN/_nguyen_lieu`: media nguồn đã nhập hoặc tải về để dựng.
- `_HE_THONG/tai_lieu`: kế hoạch và tài liệu dự án.
- `_HE_THONG`: mã nguồn, cấu hình, database, backup và plugin Premiere. Không nên sửa trực tiếp khi đang chạy app.

Trong mỗi project:

- `01_KICH_BAN`: kịch bản và storyboard.
- `02_AM_THANH`: voiceover.
- `03_TAI_NGUYEN`: ảnh, video, audio và thumbnail.
- `04_XUAT_BAN`: MP4 cuối.
- `05_PREMIERE`: XML, subtitle và media handoff.
- `_WORK`: file tạm/trung gian; không cần thao tác trong quá trình dùng app.
