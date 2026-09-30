"""Whether something the app already knows can be used again, or must be redone.

Each kind of knowledge goes stale at its own pace: a channel's style holds for
a month, its view counts for a day or two, the news for hours. One TTL for
everything would either re-research a stable channel every time or plan from
yesterday's headlines. Where a cheaper signal than age exists - a channel has
uploaded five videos since it was profiled - it wins over the clock.

Freshness is never stored. It is worked out here, on read, from when the thing
was captured; a stored "fresh" would itself be stale a day later.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

FRESH = "fresh"
STALE = "stale"
MISSING = "missing"

# How a comment sample is brought up to date: new rows next to the old ones,
# never a rewrite, so every figure keeps the size and date it was taken at.
APPEND = "append"


@dataclass(frozen=True)
class Policy:
    kind: str
    max_age: timedelta
    note: str


POLICIES: dict[str, Policy] = {
    "channel_profile": Policy("channel_profile", timedelta(days=30), "Phong cách, chủ đề của kênh: 30 ngày hoặc khi có từ 5 video mới"),
    "channel_performance_active": Policy("channel_performance_active", timedelta(hours=24), "Số liệu gần đây của kênh đang đăng đều"),
    "channel_performance": Policy("channel_performance", timedelta(hours=48), "Số liệu gần đây của kênh"),
    "channel_performance_quiet": Policy("channel_performance_quiet", timedelta(hours=72), "Số liệu gần đây của kênh ít đăng"),
    "topic_news": Policy("topic_news", timedelta(hours=6), "Tin tức, sự kiện đang diễn ra"),
    "topic_hot": Policy("topic_hot", timedelta(hours=24), "Chủ đề đang nóng"),
    "topic_tech": Policy("topic_tech", timedelta(days=30), "Công nghệ, thông số, sản phẩm"),
    "topic_evergreen": Policy("topic_evergreen", timedelta(days=180), "Kiến thức ít thay đổi"),
    "comments_young_video": Policy("comments_young_video", timedelta(hours=24), "Comment của video dưới 7 ngày tuổi"),
    "comments": Policy("comments", timedelta(days=30), "Comment của video đã ổn định"),
    "similar_videos_hot": Policy("similar_videos_hot", timedelta(days=7), "Video tương tự của chủ đề nóng"),
    "similar_videos": Policy("similar_videos", timedelta(days=30), "Video tương tự của chủ đề ổn định"),
    "product_price": Policy("product_price", timedelta(hours=24), "Giá, ưu đãi của sản phẩm"),
}

VOLATILITIES = ("news", "hot", "tech", "evergreen")
NEW_UPLOADS_FOR_PROFILE_REFRESH = 5
YOUNG_VIDEO = timedelta(days=7)


def parse_time(value: Any) -> datetime | None:
    """An ISO time or date from the database, as an aware UTC datetime."""
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _result(policy: Policy, captured_at: Any, now: datetime, reasons: list[str], forced_stale: bool = False) -> dict[str, Any]:
    captured = parse_time(captured_at)
    if captured is None:
        return {
            "state": MISSING, "policy": policy.kind, "note": policy.note,
            "age_seconds": None, "max_age_seconds": int(policy.max_age.total_seconds()),
            "captured_at": None, "reasons": ["Chưa có dữ liệu"],
        }
    age = now - captured
    stale = forced_stale or age > policy.max_age
    if age > policy.max_age:
        reasons = [*reasons, f"Quá {_human(policy.max_age)} (đã {_human(age)})"]
    return {
        "state": STALE if stale else FRESH, "policy": policy.kind, "note": policy.note,
        "age_seconds": max(0, int(age.total_seconds())),
        "max_age_seconds": int(policy.max_age.total_seconds()),
        "captured_at": captured.isoformat(), "reasons": reasons,
    }


def _human(span: timedelta) -> str:
    hours = span.total_seconds() / 3600
    return f"{hours:.0f} giờ" if hours < 48 else f"{hours / 24:.0f} ngày"


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def channel_profile(captured_at: Any, *, new_uploads: int | None = None, now: datetime | None = None) -> dict[str, Any]:
    reasons: list[str] = []
    forced = new_uploads is not None and new_uploads >= NEW_UPLOADS_FOR_PROFILE_REFRESH
    if forced:
        reasons.append(f"Kênh có {new_uploads} video mới kể từ lần phân tích trước")
    return _result(POLICIES["channel_profile"], captured_at, _now(now), reasons, forced)


def channel_performance(captured_at: Any, *, active: bool | None = None, now: datetime | None = None) -> dict[str, Any]:
    key = {True: "channel_performance_active", False: "channel_performance_quiet"}.get(active, "channel_performance")  # type: ignore[arg-type]
    return _result(POLICIES[key], captured_at, _now(now), [])


def topic(captured_at: Any, *, volatility: str = "evergreen", now: datetime | None = None) -> dict[str, Any]:
    level = volatility if volatility in VOLATILITIES else "evergreen"
    return _result(POLICIES[f"topic_{level}"], captured_at, _now(now), [])


def comments(captured_at: Any, *, video_published_at: Any = None, now: datetime | None = None) -> dict[str, Any]:
    moment = _now(now)
    published = parse_time(video_published_at)
    young = published is not None and moment - published < YOUNG_VIDEO
    result = _result(POLICIES["comments_young_video" if young else "comments"], captured_at, moment, [])
    # Stale comments are topped up with a new sample, not replaced.
    return {**result, "update_mode": APPEND}


def similar_videos(captured_at: Any, *, volatility: str = "evergreen", now: datetime | None = None) -> dict[str, Any]:
    key = "similar_videos_hot" if volatility in {"news", "hot"} else "similar_videos"
    return _result(POLICIES[key], captured_at, _now(now), [])


def product_price(captured_at: Any, *, now: datetime | None = None) -> dict[str, Any]:
    return _result(POLICIES["product_price"], captured_at, _now(now), [])


_ASSESSORS = {
    "channel_profile": channel_profile,
    "channel_performance": channel_performance,
    "topic": topic,
    "comments": comments,
    "similar_videos": similar_videos,
    "product_price": product_price,
}


def assess(kind: str, captured_at: Any, **signals: Any) -> dict[str, Any]:
    """One entry point for every kind; the signals each kind accepts differ."""
    assessor = _ASSESSORS.get(kind)
    if assessor is None:
        raise ValueError(f"Không có chính sách độ mới cho: {kind}")
    return assessor(captured_at, **signals)
