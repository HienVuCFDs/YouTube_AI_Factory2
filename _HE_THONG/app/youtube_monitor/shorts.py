"""Derive a vertical short from the long video a project already built.

Both workflows end with the same thing: a timeline of segments that each
have a visual and a voice track. WF Content generates those scenes, WF Reup
cuts them from a source video — but by the time either finishes, a short is
a selection problem, not a production one. That is why this works for every
workflow without knowing which one produced the timeline.

A short reuses the segments' existing audio rather than re-narrating them.
That keeps picture and voice in sync for free and costs nothing to produce;
the plan's own hook line rides as an on-screen caption. Re-narrating a short
in a different voice is a separate job and is deliberately not attempted
here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


class ShortsPlanError(RuntimeError):
    pass


# YouTube Shorts, Reels and TikTok are all 1080x1920; only the landscape
# profile differs. The renderer had no such table and never passed a size, so
# a project set to Shorts still rendered 1920x1080.
OUTPUT_PROFILE_SIZES: dict[str, tuple[int, int]] = {
    "youtube_landscape": (1920, 1080),
    "youtube_shorts": (1080, 1920),
    "instagram_reels": (1080, 1920),
    "tiktok": (1080, 1920),
}
VERTICAL_PROFILES = frozenset({"youtube_shorts", "instagram_reels", "tiktok"})
DEFAULT_SHORT_PROFILE = "youtube_shorts"

# YouTube treats anything over 60s as a normal video, so a plan that runs
# longer stops being a short at all.
MAX_SHORT_SECONDS = 60
MIN_SHORT_SECONDS = 8

PlanBuilder = Callable[[dict[str, Any]], dict[str, Any]]
_plan_builder: PlanBuilder | None = None


def set_plan_builder(callback: PlanBuilder | None) -> None:
    """Let the app write the short's script with its own model.

    Choosing which moments carry a story is a judgement call. The app owns
    the models, so it injects the writer the way it injects the scene prompt
    crafter; without one this module still produces a usable plan.
    """
    global _plan_builder
    _plan_builder = callback


def profile_size(profile: str) -> tuple[int, int]:
    return OUTPUT_PROFILE_SIZES.get(str(profile or "").strip().lower(), (1920, 1080))


def is_vertical(profile: str) -> bool:
    return str(profile or "").strip().lower() in VERTICAL_PROFILES


@dataclass(frozen=True, slots=True)
class ShortPlan:
    title: str
    hook: str
    segment_ids: tuple[int, ...]
    captions: dict[int, str] = field(default_factory=dict)
    profile: str = DEFAULT_SHORT_PROFILE
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "hook": self.hook,
            "segment_ids": list(self.segment_ids),
            "captions": {str(key): value for key, value in self.captions.items()},
            "profile": self.profile,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ShortPlan":
        captions = {}
        for key, value in dict(payload.get("captions") or {}).items():
            try:
                captions[int(key)] = str(value)
            except (TypeError, ValueError):
                continue
        return cls(
            title=str(payload.get("title") or ""),
            hook=str(payload.get("hook") or ""),
            segment_ids=tuple(int(item) for item in payload.get("segment_ids") or []),
            captions=captions,
            profile=str(payload.get("profile") or DEFAULT_SHORT_PROFILE),
            reason=str(payload.get("reason") or ""),
        )


def _usable_segments(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A segment can only carry a short if it has something to show and say."""
    return [
        segment
        for segment in timeline
        if str(segment.get("visual_path") or "").strip()
        and str(segment.get("audio_path") or "").strip()
    ]


def _segment_seconds(segment: dict[str, Any]) -> float:
    try:
        return max(0.0, float(segment.get("duration_seconds") or 0))
    except (TypeError, ValueError):
        return 0.0


def plan_duration_seconds(timeline: list[dict[str, Any]], segment_ids: tuple[int, ...]) -> float:
    by_id = {int(item["id"]): item for item in timeline if item.get("id") is not None}
    return round(sum(_segment_seconds(by_id[sid]) for sid in segment_ids if sid in by_id), 3)


def fit_to_short(timeline: list[dict[str, Any]], segment_ids: list[int]) -> tuple[int, ...]:
    """Trim a selection down to something that is still a short.

    Segments keep the order the long video gave them: a short cut out of
    sequence reads as a different video, not a condensed one.
    """
    by_id = {int(item["id"]): item for item in timeline if item.get("id") is not None}
    order = {int(item["id"]): index for index, item in enumerate(timeline) if item.get("id") is not None}
    wanted = [sid for sid in dict.fromkeys(int(s) for s in segment_ids) if sid in by_id]
    wanted.sort(key=lambda sid: order[sid])
    kept: list[int] = []
    total = 0.0
    for sid in wanted:
        seconds = _segment_seconds(by_id[sid])
        if kept and total + seconds > MAX_SHORT_SECONDS:
            continue
        kept.append(sid)
        total += seconds
    return tuple(kept)


def default_plan(timeline: list[dict[str, Any]], title: str = "") -> ShortPlan:
    """Build a usable short without asking a model anything.

    Takes the opening, which carries the premise, then keeps following
    segments until the clip is as long as a short may be. Crude, but it means
    the feature works when no model is reachable rather than failing.
    """
    usable = _usable_segments(timeline)
    if not usable:
        raise ShortsPlanError(
            "Chưa có cảnh nào đủ cả hình và giọng đọc để dựng short"
        )
    chosen = fit_to_short(usable, [int(item["id"]) for item in usable])
    if not chosen:
        raise ShortsPlanError("Không chọn được cảnh nào nằm trong giới hạn 60 giây")
    opening = usable[0]
    return ShortPlan(
        title=(title or str(opening.get("voice_text") or ""))[:120],
        hook=str(opening.get("subtitle_text") or opening.get("voice_text") or "")[:200],
        segment_ids=chosen,
        profile=DEFAULT_SHORT_PROFILE,
        reason="Chọn tự động: lấy từ cảnh mở đầu cho tới khi chạm giới hạn 60 giây",
    )


def build_plan(
    timeline: list[dict[str, Any]],
    *,
    title: str = "",
    goal: str = "",
    profile: str = DEFAULT_SHORT_PROFILE,
) -> ShortPlan:
    """Ask the app's model which moments make a short, falling back if it cannot."""
    usable = _usable_segments(timeline)
    if not usable:
        raise ShortsPlanError("Chưa có cảnh nào đủ cả hình và giọng đọc để dựng short")
    if _plan_builder is None:
        plan = default_plan(timeline, title=title)
        return ShortPlan(
            title=plan.title, hook=plan.hook, segment_ids=plan.segment_ids,
            captions=plan.captions, profile=profile, reason=plan.reason,
        )
    request = {
        "goal": goal,
        "title": title,
        "max_seconds": MAX_SHORT_SECONDS,
        "segments": [
            {
                "segment_id": int(item["id"]),
                "scene": int(item.get("segment_index") or 0),
                "seconds": _segment_seconds(item),
                "narration": str(item.get("voice_text") or "")[:600],
            }
            for item in usable
        ],
    }
    try:
        verdict = dict(_plan_builder(request) or {})
    except Exception as exc:
        raise ShortsPlanError(f"Không dựng được kịch bản short: {exc}") from exc
    chosen = fit_to_short(usable, [int(x) for x in verdict.get("segment_ids") or []])
    if not chosen:
        # A model that picked nothing usable must not lose the feature.
        return default_plan(timeline, title=title or str(verdict.get("title") or ""))
    captions = {}
    for entry in verdict.get("captions") or []:
        try:
            captions[int(entry["segment_id"])] = str(entry.get("text") or "")[:200]
        except (TypeError, ValueError, KeyError):
            continue
    return ShortPlan(
        title=str(verdict.get("title") or title or "")[:120],
        hook=str(verdict.get("hook") or "")[:200],
        segment_ids=chosen,
        captions=captions,
        profile=profile,
        reason=str(verdict.get("reason") or "")[:1000],
    )


def build_short_timeline(
    timeline: list[dict[str, Any]], plan: ShortPlan
) -> list[dict[str, Any]]:
    """Return the chosen segments, renumbered, with the plan's captions applied."""
    by_id = {int(item["id"]): item for item in timeline if item.get("id") is not None}
    selected: list[dict[str, Any]] = []
    for index, segment_id in enumerate(plan.segment_ids, start=1):
        source = by_id.get(segment_id)
        if source is None:
            continue
        segment = dict(source)
        segment["segment_index"] = index
        caption = plan.captions.get(segment_id)
        if index == 1 and plan.hook:
            # The hook has to land on the first frames or the short is scrolled past.
            caption = plan.hook
        if caption:
            segment["subtitle_text"] = caption
        selected.append(segment)
    if not selected:
        raise ShortsPlanError("Kế hoạch short không trỏ tới cảnh nào còn tồn tại")
    return selected
