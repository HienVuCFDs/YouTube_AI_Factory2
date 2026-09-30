"""Counting what the YouTube Data API costs, before it is spent.

The API gives a project 10,000 units a day, and the calls are not priced the
same: a search costs 100, reading a video or a page of comments costs 1. One
careless research run could spend the day's allowance on searches and leave
the channel monitor unable to sync. Every call is priced here first, refused
when it would go over the day's limit, and written to the usage ledger the
app already keeps for its other providers.

The day is Pacific time, because that is when Google resets the counter.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

PROVIDER = "youtube_data_api"
UNIT_COST = {
    "search": 100,
    "videos": 1,
    "channels": 1,
    "playlistItems": 1,
    "commentThreads": 1,
    "comments": 1,
    "captions": 50,
}
DEFAULT_DAILY_LIMIT = 10_000
_RESET_ZONE = ZoneInfo("America/Los_Angeles")


class QuotaExceeded(RuntimeError):
    pass


def cost_of(resource: str) -> int:
    return UNIT_COST.get(resource, 1)


def day_start_utc(now: datetime | None = None) -> str:
    """When today's allowance began, as a UTC ISO string comparable to ledger rows."""
    local = (now or datetime.now(timezone.utc)).astimezone(_RESET_ZONE)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc).isoformat()


class YouTubeQuota:
    def __init__(self, database: Any, daily_limit: int | None = None):
        self.database = database
        try:
            configured = int(os.getenv("YOUTUBE_API_DAILY_QUOTA", "") or 0)
        except ValueError:
            configured = 0
        self.daily_limit = int(daily_limit or configured or DEFAULT_DAILY_LIMIT)

    def used_today(self) -> int:
        return int(self.database.provider_units_since(PROVIDER, day_start_utc()))

    def remaining(self) -> int:
        return max(0, self.daily_limit - self.used_today())

    def check(self, resource: str) -> int:
        """Refuse a call that would take the day over its limit."""
        cost = cost_of(resource)
        used = self.used_today()
        if used + cost > self.daily_limit:
            raise QuotaExceeded(
                f"Hết hạn mức YouTube Data API hôm nay ({used}/{self.daily_limit} đơn vị); "
                f"lệnh {resource} cần {cost}. Hạn mức đặt lại lúc 0 giờ giờ Thái Bình Dương."
            )
        return cost

    def record(self, resource: str, *, ok: bool, status_code: int | None = None, note: str = "") -> None:
        """Every call is charged, failed ones included: Google charges them too."""
        try:
            self.database.record_provider_usage(
                provider=PROVIDER,
                capability=f"youtube.{resource}",
                status="used" if ok else "error",
                units=cost_of(resource),
                metadata={"status_code": status_code, "note": note[:200]} if (status_code or note) else {},
            )
        except Exception:
            # The ledger must never be the reason a call's result is lost.
            pass

    def status(self) -> dict[str, Any]:
        used = self.used_today()
        return {
            "provider": PROVIDER,
            "daily_limit": self.daily_limit,
            "used_today": used,
            "remaining": max(0, self.daily_limit - used),
            "day_started_at": day_start_utc(),
        }
