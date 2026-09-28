"""Small, deterministic scene graphic vocabulary for AI edit plans.

The planner chooses timing and a preset. It never supplies FFmpeg expressions.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any


KINDS = {"title", "callout", "label", "text"}
STYLES = {"clean", "neon", "card"}
ANIMATIONS = {"fade", "pop", "slide_up"}
POSITIONS = {"top_left", "top_center", "top_right", "center"}


def normalize_graphic_overlay(raw: dict[str, Any], duration: float) -> dict[str, Any]:
    """Validate a planned overlay and supply stable defaults for older plans."""
    if not isinstance(raw, dict):
        raise ValueError("Overlay phải là object")
    kind = str(raw.get("kind") or "text").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"Overlay kind chưa hỗ trợ: {kind}")
    content = " ".join(str(raw.get("text") or "").split())
    if not content or len(content) > 100:
        raise ValueError("Overlay text phải có 1–100 ký tự")
    if "\n" in str(raw.get("text") or ""):
        raise ValueError("Overlay chỉ hỗ trợ một dòng chữ ngắn")
    style = str(raw.get("style") or ("card" if kind == "callout" else "clean")).strip().lower()
    animation = str(raw.get("animation") or "fade").strip().lower()
    position = str(raw.get("position") or "top_center").strip().lower()
    if style not in STYLES or animation not in ANIMATIONS or position not in POSITIONS:
        raise ValueError(f"Overlay preset không hợp lệ: {style}/{animation}/{position}")
    try:
        start = float(raw.get("start_seconds", 0))
        end = float(raw.get("end_seconds", min(duration, 3.0)))
    except (ValueError, TypeError) as exc:
        raise ValueError("Thời điểm overlay phải là số") from exc
    if not all(math.isfinite(value) for value in (start, end, duration)):
        raise ValueError("Thời điểm overlay không hợp lệ")
    if start < 0 or end <= start or end > duration + 0.05:
        raise ValueError(f"Overlay nằm ngoài thời lượng cảnh: {start:g}–{end:g}/{duration:g}s")
    return {
        "kind": kind, "text": content, "style": style,
        "animation": animation, "position": position,
        "start_seconds": round(start, 3), "end_seconds": round(min(end, duration), 3),
        "reason": str(raw.get("reason") or "").strip()[:300],
    }


def normalize_graphic_overlays(raw: Any, duration: float) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) > 6:
        raise ValueError("Overlay phải là danh sách tối đa 6 mục")
    return [normalize_graphic_overlay(item, duration) for item in raw]


def retime_graphic_overlays(raw: Any, planned_duration: float, rendered_duration: float) -> list[dict[str, Any]]:
    """Keep scene graphics aligned when measured voice length differs from script estimate."""
    planned = normalize_graphic_overlays(raw, planned_duration)
    if abs(planned_duration - rendered_duration) < 0.05:
        return planned
    ratio = rendered_duration / planned_duration
    return [
        {
            **item,
            "start_seconds": round(item["start_seconds"] * ratio, 3),
            "end_seconds": round(item["end_seconds"] * ratio, 3),
        }
        for item in planned
    ]


def _filter_path(path: Path) -> str:
    # FFmpeg parses a filter option and then the filtergraph. Escape both layers.
    return path.resolve().as_posix().replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")


def graphic_overlay_filters(
    overlays: list[dict[str, Any]], duration: float, width: int, height: int,
    directory: Path, stem: str, font: Path,
) -> list[str]:
    """Build timed drawtext filters and UTF-8 text files for a finished scene."""
    if not overlays:
        return []
    normalized = normalize_graphic_overlays(overlays, duration)
    directory.mkdir(parents=True, exist_ok=True)
    filters: list[str] = []
    for index, item in enumerate(normalized, 1):
        text_path = directory / f"{stem}-graphic-{index:02d}.txt"
        text_path.write_text(item["text"], encoding="utf-8")
        start, end = item["start_seconds"], item["end_seconds"]
        enter = min(0.25, (end - start) / 4)
        leave = min(0.25, (end - start) / 4)
        alpha = (
            f"if(lt(t,{start:.3f}),0,"
            f"if(lt(t,{start + enter:.3f}),(t-{start:.3f})/{enter:.3f},"
            f"if(lt(t,{end - leave:.3f}),1,"
            f"if(lt(t,{end:.3f}),({end:.3f}-t)/{leave:.3f},0))))"
        )
        font_size = max(18, min(80, round(width * (0.055 if item["kind"] == "title" else 0.04))))
        x = {
            "top_left": f"{round(width * 0.08)}",
            "top_center": "(w-text_w)/2",
            "top_right": f"w-text_w-{round(width * 0.08)}",
            "center": "(w-text_w)/2",
        }[item["position"]]
        target_y = round(height * (0.43 if item["position"] == "center" else 0.15))
        if item["animation"] == "slide_up":
            y = f"{target_y}+if(lt(t,{start:.3f}),36,if(lt(t,{start + enter:.3f}),36*(1-(t-{start:.3f})/{enter:.3f}),0))"
        elif item["animation"] == "pop":
            y = f"{target_y}-if(lt(t,{start:.3f}),0,if(lt(t,{start + enter:.3f}),12*sin(3.14159*(t-{start:.3f})/{enter:.3f}),0))"
        else:
            y = str(target_y)
        style = item["style"]
        color = "0xFFFFFF" if style != "neon" else "0xEEFFDD"
        border = "4" if style == "neon" else "2"
        border_color = "0x163200" if style == "neon" else "0x142035"
        box = "1" if style == "card" else "0"
        box_color = "0x14213D@0.82" if style == "card" else "black@0"
        filters.append(
            f"drawtext=fontfile='{_filter_path(font)}':textfile='{_filter_path(text_path)}':"
            f"expansion=none:fontcolor={color}:fontsize={font_size}:x='{x}':y='{y}':"
            f"alpha='{alpha}':borderw={border}:bordercolor={border_color}:"
            f"box={box}:boxcolor={box_color}:boxborderw={round(font_size * 0.25)}"
        )
    return filters
