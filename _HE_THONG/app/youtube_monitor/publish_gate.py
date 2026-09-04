"""Everything that has to be true before a video is allowed out.

Publishing is the one step this app cannot take back: a video on a real
channel has to be found and deleted, and a Short filed as an ordinary video
cannot be reshaped after the fact. Every one of these was already checkable
somewhere - the timeline knows which scenes are silent, the file knows its
own shape, the reuse check knows what is left of the source - but nothing
gathered them into a single answer to "is this ready", so each was found
separately, usually after the upload.

The gate is deliberately a list of facts with a fix attached to each, not a
score. A blocked item names what to press; a warning is a judgement the user
is allowed to overrule, and says so.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .shorts import frame_matches_profile, profile_label

# A check is one of these. "block" stops the publication; "warn" is shown and
# can be accepted; "pass" is there so the list reads as a checklist rather
# than a list of complaints.
BLOCK = "block"
WARN = "warn"
PASS = "pass"


def _check(key: str, level: str, label: str, detail: str = "", fix: str = "") -> dict[str, str]:
    return {"key": key, "level": level, "label": label, "detail": detail, "fix": fix}


def evaluate(
    *,
    timeline: list[dict[str, Any]],
    script: dict[str, Any] | None,
    video_path: Path | None,
    frame_size: tuple[int, int] | None,
    output_profile: str,
    title: str,
    description: str,
    tags: list[str] | None,
    thumbnail_path: str,
    platform: str,
    reuse_verdict: str = "",
    source_title: str = "",
    youtube_connected: bool = True,
    youtube_configured: bool = True,
) -> list[dict[str, str]]:
    """The full checklist for one video going to one destination."""
    checks: list[dict[str, str]] = []
    tags = tags or []

    # --- the video itself -------------------------------------------------
    if not video_path or not Path(video_path).is_file():
        checks.append(_check(
            "rendered", BLOCK, "Video đã dựng",
            "Chưa có file MP4 cho bản này.",
            "Quay lại Xưởng dựng và bấm dựng video.",
        ))
    else:
        checks.append(_check("rendered", PASS, "Video đã dựng"))

    # --- every scene has both halves --------------------------------------
    silent = [item for item in timeline if not str(item.get("audio_path") or "").strip()]
    blind = [item for item in timeline if not str(item.get("visual_path") or "").strip()]
    if not timeline:
        checks.append(_check(
            "scenes", BLOCK, "Đủ cảnh và giọng đọc",
            "Dự án chưa có cảnh nào.",
            "Tạo storyboard từ kịch bản.",
        ))
    elif silent or blind:
        parts = []
        if silent:
            parts.append(f"{len(silent)}/{len(timeline)} cảnh chưa có giọng")
        if blind:
            parts.append(f"{len(blind)}/{len(timeline)} cảnh chưa có hình")
        checks.append(_check(
            "scenes", BLOCK, "Đủ cảnh và giọng đọc", " · ".join(parts),
            "Tạo giọng đọc và cắt/gắn hình cho những cảnh còn thiếu.",
        ))
    else:
        checks.append(_check(
            "scenes", PASS, "Đủ cảnh và giọng đọc", f"{len(timeline)} cảnh đủ hình và tiếng",
        ))

    # --- the shape the destination expects --------------------------------
    if frame_size and frame_size[0] > 0:
        width, height = frame_size
        if frame_matches_profile(width, height, output_profile):
            checks.append(_check(
                "aspect", PASS, "Đúng tỷ lệ nền tảng", f"{width}x{height}",
            ))
        else:
            checks.append(_check(
                "aspect", BLOCK, "Đúng tỷ lệ nền tảng",
                f"Video đang là {width}x{height}, không đúng khổ {output_profile} "
                f"({profile_label(output_profile)}).",
                "Dựng lại đúng định dạng đầu ra cho nền tảng này.",
            ))
    else:
        checks.append(_check(
            "aspect", WARN, "Đúng tỷ lệ nền tảng",
            "Không đo được kích thước video.",
            "Kiểm tra file MP4 có mở được không.",
        ))

    # --- what people actually see before they click -----------------------
    if str(thumbnail_path or "").strip() and Path(str(thumbnail_path)).is_file():
        checks.append(_check("thumbnail", PASS, "Đã chọn thumbnail"))
    elif platform == "youtube":
        checks.append(_check(
            "thumbnail", WARN, "Đã chọn thumbnail",
            "Chưa chọn thumbnail; YouTube sẽ tự lấy một khung hình bất kỳ.",
            "Ở bước Xuất bản, bấm “Tạo thumbnail” rồi chọn một ảnh.",
        ))
    else:
        checks.append(_check(
            "thumbnail", WARN, "Đã chọn thumbnail",
            "Gói đăng thủ công sẽ không có ảnh bìa kèm theo.",
            "Tạo thumbnail để đóng gói cùng video.",
        ))

    # --- the words that go with it ----------------------------------------
    clean_title = str(title or "").strip()
    if not clean_title:
        checks.append(_check(
            "title", BLOCK, "Có tiêu đề", "Chưa nhập tiêu đề.",
            "Chọn một tiêu đề AI đã viết, hoặc tự nhập.",
        ))
    elif source_title and source_title.strip().lower() in clean_title.lower():
        checks.append(_check(
            "title", WARN, "Có tiêu đề",
            "Tiêu đề vẫn chứa tiêu đề của video gốc.",
            "Dùng một tiêu đề viết riêng cho video này.",
        ))
    else:
        checks.append(_check("title", PASS, "Có tiêu đề", clean_title[:80]))

    if not str(description or "").strip():
        checks.append(_check(
            "description", WARN, "Có mô tả", "Chưa có mô tả.",
            "Mô tả đã được AI viết sẵn ở bước kịch bản; dán vào là được.",
        ))
    else:
        checks.append(_check("description", PASS, "Có mô tả"))

    if not tags:
        checks.append(_check(
            "tags", WARN, "Có hashtag / tag", "Chưa có tag nào.",
            "Dùng hashtag AI đã viết cho video này.",
        ))
    else:
        checks.append(_check("tags", PASS, "Có hashtag / tag", f"{len(tags)} tag"))

    # --- the one that is about someone else's work ------------------------
    if not reuse_verdict:
        checks.append(_check(
            "reuse", WARN, "Đã kiểm tra bản quyền",
            "Chưa chạy kiểm tra nội dung dùng lại.",
            "Bấm “Kiểm tra bản quyền” ở bước Xuất bản.",
        ))
    elif reuse_verdict == "high":
        checks.append(_check(
            "reuse", BLOCK, "Đã kiểm tra bản quyền",
            "Kiểm tra bản quyền đang ở mức RỦI RO CAO.",
            "Xem các mục trong kết quả kiểm tra và sửa trước khi đăng.",
        ))
    else:
        checks.append(_check(
            "reuse", PASS, "Đã kiểm tra bản quyền",
            "Rủi ro thấp" if reuse_verdict == "low" else "Cần xem lại, nhưng đăng được",
        ))

    # --- there has to be somewhere for it to go ---------------------------
    # The gate said "ready to publish" while publishing was impossible: no
    # OAuth client means no way to authorise, no token, and an upload queue
    # that can never move. Only YouTube is uploaded to; the other platforms
    # produce a package the user posts themselves.
    if platform == "youtube":
        if not youtube_configured:
            checks.append(_check(
                "youtube_account", BLOCK, "Đã nối tài khoản YouTube",
                "Chưa cấu hình YouTube OAuth client (client id/secret).",
                "Vào Cài đặt · Kết nối, khai báo YOUTUBE_CLIENT_ID và YOUTUBE_CLIENT_SECRET.",
            ))
        elif not youtube_connected:
            checks.append(_check(
                "youtube_account", BLOCK, "Đã nối tài khoản YouTube",
                "Đã cấu hình nhưng chưa đăng nhập YouTube.",
                "Vào Cài đặt · Kết nối và bấm đăng nhập YouTube.",
            ))
        else:
            checks.append(_check("youtube_account", PASS, "Đã nối tài khoản YouTube"))

    # --- an approved script is the user's own sign-off --------------------
    if str((script or {}).get("status") or "") != "approved":
        checks.append(_check(
            "approved", BLOCK, "Kịch bản đã duyệt",
            "Kịch bản của bản này chưa được duyệt.",
            "Ở bước Kịch bản, bấm “Duyệt kịch bản”.",
        ))
    else:
        checks.append(_check("approved", PASS, "Kịch bản đã duyệt"))

    return checks


def blockers(checks: list[dict[str, str]]) -> list[dict[str, str]]:
    return [item for item in checks if item["level"] == BLOCK]


def warnings(checks: list[dict[str, str]]) -> list[dict[str, str]]:
    return [item for item in checks if item["level"] == WARN]


def is_ready(checks: list[dict[str, str]]) -> bool:
    return not blockers(checks)
