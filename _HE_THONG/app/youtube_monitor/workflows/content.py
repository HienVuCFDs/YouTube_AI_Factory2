"""WF Content: write a new script, and have image models draw every scene."""

from __future__ import annotations

from .base import Workflow

WORKFLOW = Workflow(
    key="content",
    label="WF Content",
    state="Sẵn sàng",
    summary="Viết kịch bản mới, tạo hình AI cho từng cảnh và dựng song song video dài/Short.",
    steps=(
        "Nguồn", "Phân tích", "Kịch bản + Short", "Giọng đọc + Short",
        "Storyboard", "Xưởng dựng + Short", "Xuất bản",
    ),
    notes=(
        "Hình do AI tạo: ChatGPT/Gemini qua Extension, Google Flow qua CLI.",
        "Cảnh cần video sẽ tạo ảnh tĩnh trước rồi mới dựng video từ chính ảnh đó.",
        "Short đi cùng luồng: tạo từ cùng brief ở bước Kịch bản, tạo giọng ở bước Giọng đọc, rồi tạo cảnh và dựng riêng ở Xưởng dựng.",
        "Mỗi cảnh được xếp hàng theo provider đã chọn; nếu provider web chưa kết nối, app hiển thị trạng thái sidecar thay vì báo đã tạo xong.",
    ),
    script_mode="new_angle_same_topic",
    scene_asset_type="ai_scene",
    uses_web_research=True,
    extra={
        "short_flow": "Short dùng cùng brief và cấu hình giọng với video dài; cảnh Short được tạo theo workflow AI của WF Content.",
    },
)
