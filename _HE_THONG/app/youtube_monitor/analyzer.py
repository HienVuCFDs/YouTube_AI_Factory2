from __future__ import annotations

import re
from collections import Counter
from typing import Any


STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "in", "is", "it", "of", "on", "or", "that", "the", "this", "to", "with",
    "you", "your", "và", "là", "của", "cho", "một", "những", "các", "được",
    "trong", "với", "này", "đó", "từ", "khi", "sẽ", "đã", "có", "không", "như",
}

CONTENT_TYPES = {
    "tutorial": ("how", "tutorial", "guide", "hướng dẫn", "cách", "tự làm", "setup"),
    "news": ("news", "breaking", "tin tức", "mới nhất", "update", "cập nhật"),
    "review": ("review", "đánh giá", "test", "trải nghiệm", "so sánh"),
    "finance": ("stock", "crypto", "bitcoin", "forex", "trading", "chứng khoán", "tài chính"),
    "technology": ("ai", "software", "tech", "python", "app", "công nghệ", "máy tính"),
    "entertainment": ("movie", "music", "game", "reaction", "phim", "nhạc", "giải trí"),
}


def _words(value: str) -> list[str]:
    return [word.lower() for word in re.findall(r"[\wÀ-ỹ]{3,}", value, flags=re.UNICODE)]


def _language(text: str) -> str:
    lowered = text.lower()
    vietnamese = sum(lowered.count(token) for token in (" và ", " là ", " của ", " không ", " những ", " được "))
    english = sum(lowered.count(token) for token in (" the ", " and ", " with ", " how ", " this "))
    if vietnamese > english:
        return "vi"
    if english > 0:
        return "en"
    return "unknown"


def _content_type(text: str) -> str:
    lowered = text.lower()
    scores = {
        category: sum(1 for token in tokens if token in lowered)
        for category, tokens in CONTENT_TYPES.items()
    }
    category, score = max(scores.items(), key=lambda item: item[1])
    return category if score else "general"


class MetadataAnalyzer:
    """Deterministic text-first analyzer used before connecting an external LLM."""

    provider = "local_metadata"

    def analyze(self, video: dict[str, Any]) -> dict[str, Any]:
        title = str(video.get("title") or "").strip()
        description = str(video.get("description") or "").strip()
        tags = [str(tag).strip() for tag in (video.get("tags") or []) if str(tag).strip()]
        combined = " ".join([title, description, " ".join(tags)])
        counts = Counter(word for word in _words(combined) if word not in STOP_WORDS)
        keywords = [
            {"keyword": word, "count": count}
            for word, count in counts.most_common(12)
        ]

        recommendations: list[str] = []
        if len(title) < 35:
            recommendations.append("Tiêu đề hơi ngắn; cân nhắc bổ sung lợi ích hoặc kết quả cụ thể.")
        if len(title) > 90:
            recommendations.append("Tiêu đề dài; nên rút gọn phần phụ để dễ đọc trên mobile.")
        if len(description) < 120:
            recommendations.append("Mô tả ngắn; nên thêm bối cảnh, từ khóa chính và CTA.")
        if not tags:
            recommendations.append("Chưa có tags; cần bổ sung keyword liên quan trước khi tối ưu SEO.")
        if not recommendations:
            recommendations.append("Metadata cơ bản đã đầy đủ; có thể chuyển sang phân tích transcript.")

        first_sentence = re.split(r"(?<=[.!?。！？])\s+", description)[0] if description else ""
        return {
            "provider": self.provider,
            "source_type": "metadata",
            "title": title,
            "language": _language(f" {combined} "),
            "content_type": _content_type(combined),
            "topic": keywords[0]["keyword"] if keywords else "general",
            "keywords": keywords,
            "hook": title,
            "description_opening": first_sentence[:240],
            "metrics": {
                "title_length": len(title),
                "description_length": len(description),
                "tag_count": len(tags),
                "has_thumbnail": bool(video.get("thumbnail_url")),
                "caption_available": bool(video.get("caption_available")),
            },
            "recommendations": recommendations,
            "next_step": "transcript" if video.get("caption_available") else "authorized_audio_or_manual_review",
        }

