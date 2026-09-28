"""WF Reup: retell a source faithfully, with its own footage as the pictures."""

from __future__ import annotations

from .base import Workflow

WORKFLOW = Workflow(
    key="reup",
    label="WF Reup",
    state="Đang làm",
    summary="Tải video gốc về, kể lại lời bình theo cách khác, dịch, rồi cắt hình từ chính video đó.",
    steps=(
        "Nguồn", "Phân tích", "Lời bình + Short", "Giọng đọc + Short",
        "Storyboard", "Xưởng dựng + Short", "Xuất bản",
    ),
    notes=(
        "Nội dung gốc giữ nguyên: nhân vật, tên riêng, số liệu, thứ tự sự việc, cái kết. "
        "Chỉ đổi cách dẫn chuyện.",
        "Nhân vật nào nói trong nguồn thì vẫn nói — lời thoại giữ là lời thoại, không "
        "chuyển thành lời kể gián tiếp.",
        "Cảnh cắt theo từng lượt thoại, đúng giây câu đó được nói. Không gọi AI tạo ảnh "
        "hay tạo video, nên không tốn tín dụng.",
        "Short đi cùng luồng: tạo từ cùng lời bình ở bước Kịch bản, tạo giọng ở bước Giọng đọc, rồi cắt cảnh và dựng riêng ở Xưởng dựng.",
        "CHƯA CHẠY THẬT: bước xuất clip và dựng MP4 chưa nghiệm thu trọn một lần.",
    ),
    # Content is fixed; only the telling changes. See writer.FAITHFUL_RETELL_MODE.
    script_mode="faithful_retell",
    scene_asset_type="source_clip",
    # Web hints exist to find motifs to invent from, which is the one thing a
    # retelling must not do.
    uses_web_research=False,
    extra={
        "short_flow": "Short giữ đúng nội dung nguồn của WF Reup, dùng cùng cấu hình giọng và cắt cảnh từ video nguồn thay vì tạo ảnh AI.",
    },
)
