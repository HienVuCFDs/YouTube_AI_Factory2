"""WF Content: write a new script, and have image models draw every scene."""

from __future__ import annotations

from .base import Workflow

WORKFLOW = Workflow(
    key="content",
    label="WF Content",
    state="Đang dang dở ở bước tạo hình",
    summary="Viết kịch bản mới, rồi để AI vẽ hình cho từng cảnh.",
    steps=(
        "Nguồn", "Phân tích", "Kịch bản", "Giọng đọc",
        "Storyboard", "Xưởng dựng", "Xuất bản",
    ),
    notes=(
        "Hình do AI tạo: ChatGPT/Gemini qua Extension, Google Flow qua CLI.",
        "Cảnh cần video sẽ tạo ảnh tĩnh trước rồi mới dựng video từ chính ảnh đó.",
        "CHƯA XONG: khâu tạo hình còn hỏng nhiều — Antigravity 9/81, ChatGPT web 11/32, "
        "Gemini API 0/30; tạo video qua Flow chưa từng chạy trọn một lần.",
    ),
    script_mode="new_angle_same_topic",
    scene_asset_type="ai_scene",
    uses_web_research=True,
)
