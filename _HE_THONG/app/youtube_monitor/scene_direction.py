"""Executable scene direction shared by planning, storage, preview and export.

Only a finite vocabulary is accepted: a model cannot submit JSX, filter code,
asset URLs or arbitrary local paths. Old projects may have no direction at all.
"""
from __future__ import annotations

import copy
import json
import math
import re
import unicodedata
from typing import Any

PRESETS = ("kinetic_title", "speech_bubble", "icon_flow", "brush_label", "stat_card")
ICONS = ("person", "robot", "message", "brain", "check", "question", "spark", "heart", "chart", "clock")
PALETTES = ("blue", "pink", "lime", "amber")
SOUNDS = ("pop", "whoosh", "chime", "tick")

_TIME = {"type": "number", "minimum": 0}
_TEXT = {"type": "string"}
DIRECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "style_note": _TEXT,
        "graphic_layers": {"type": "array", "maxItems": 8, "items": {
            "type": "object", "properties": {
                "id": _TEXT, "preset": {"type": "string", "enum": list(PRESETS)},
                "text": _TEXT, "secondary": _TEXT, "anchor_text": _TEXT,
                "anchor_occurrence": {"type": "integer", "minimum": 1},
                "start_seconds": _TIME, "end_seconds": _TIME,
                "palette": {"type": "string", "enum": list(PALETTES)},
                "animation": {"type": "string", "enum": ["pop", "slide_up", "fade"]},
                "bounds": {"type": "object", "properties": {
                    key: {"type": "number", "minimum": 0, "maximum": 1}
                    for key in ("x", "y", "width", "height")
                }, "required": ["x", "y", "width", "height"]},
                "items": {"type": "array", "maxItems": 4, "items": {
                    "type": "object", "properties": {
                        "label": _TEXT, "icon": {"type": "string", "enum": list(ICONS)},
                        "at_seconds": _TIME,
                    }, "required": ["label", "icon", "at_seconds"]}},
                "reason": _TEXT,
            }, "required": ["id", "preset", "text", "start_seconds", "end_seconds", "bounds"]}},
        "audio_cues": {"type": "array", "maxItems": 12, "items": {
            "type": "object", "properties": {
                "preset": {"type": "string", "enum": list(SOUNDS)},
                "at_seconds": _TIME, "layer_id": _TEXT, "offset_seconds": _TIME,
                "gain_db": {"type": "number", "minimum": -36, "maximum": -10},
            }, "required": ["preset", "at_seconds", "gain_db"]}},
        "visual_beats": {"type": "array", "maxItems": 12, "items": {
            "type": "object", "properties": {
                "start_seconds": _TIME, "end_seconds": _TIME,
                "source_kind": {"type": "string", "enum": ["primary", "asset"]},
                "asset_id": {"type": "integer"},
                "effect": {"type": "string", "enum": ["static", "zoom_in", "zoom_out"]},
                "reason": _TEXT,
            }, "required": ["start_seconds", "end_seconds", "source_kind", "effect", "reason"]}},
    }, "required": ["style_note", "graphic_layers", "audio_cues", "visual_beats"],
}

DIRECTOR_INSTRUCTIONS = """
DUNG THEO NOI DUNG, VOI direction CHO TUNG CANH:
- direction.style_note: phong cach va ly do bo cuc. video nguon la tham chieu;
  giu mot video chinh, chi them asset neu can. Khong ep thay tat ca bang AI image.
- direction.graphic_layers: kinetic_title (hook), speech_bubble (hoi/dap),
  icon_flow (quy trinh/liet ke), brush_label (nhan manh), stat_card (con so da xac minh).
  0-3 lop cho mot canh thuong; giu do hoa nhat quan, co khoang nghi. Khong nhai lai
  toan bo caption. Canh khong can thi mang rong. Khong them logo/giao dien mang xa hoi.
- Moi layer co id duy nhat, text <= 64 ky tu, secondary <= 100, start_seconds/end_seconds
  TINH TU DAU CANH, bounds {x,y,width,height} theo ty le 0..1. Chon vung trong, tranh
  mat/nhan vat/chu goc va vung subtitle y>=0.86. palette blue/pink/lime/amber;
  animation pop/slide_up/fade. Khong de hai lop cung che mot vung cung luc.
- anchor_text la cum tu NGUYEN VAN trong WORD TIMING, anchor_occurrence mac dinh 1.
  Bo dung se can lai thoi diem theo audio that; khong tu bia timestamp chinh xac neu
  timing_basis=estimated. Neu khong co anchor phu hop dung start_seconds ro rang.
- icon_flow.items co 2-4 muc {label <=22 ky tu, icon, at_seconds}; at_seconds tinh
  TU DAU LAYER, tang dan theo loi noi. Icon: person,robot,message,brain,check,question,
  spark,heart,chart,clock. Chi ve cac y co trong loi binh, khong tao them su kien.
- direction.audio_cues: pop/whoosh/chime/tick. Dat layer_id de bam vao luc do hoa
  xuat hien, offset_seconds tu dau layer (0 neu khong can). gain_db -24 den -16.
  It va co chu dich; khong them tieng vao moi tu. Khong lap lai SFX neu nguon da co.
- direction.visual_beats: cac khoang start/end lien tuc phu het canh, effect
  static/zoom_in/zoom_out, source_kind primary hoac asset (asset_id trong danh sach
  da cung cap). Chi doi nhip khi y/noi dung doi, khong chia deu canh theo so giay.
  Mang rong nghia la giu visual hien tai. Khong dua duong dan file vao ke hoach.
- direction thay the overlays cu cho do hoa moi; de overlays=[] de tranh ve trung.
Ke hoach phai thuc thi duoc bang dung cac preset tren. Tra du canh duoc cung cap.
"""


def number(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} phải là số") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} không hữu hạn")
    return result


def _list(value: Any, name: str, limit: int) -> list[dict]:
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(x, dict) for x in value):
        raise ValueError(f"{name} phải là danh sách tối đa {limit} object")
    return value


def _text(value: Any, name: str, limit: int, required: bool = False) -> str:
    value = " ".join(str(value or "").split())
    if len(value) > limit or (required and not value):
        raise ValueError(f"{name} cần {'1' if required else '0'}–{limit} ký tự")
    return value


def _window(item: dict, duration: float) -> tuple[float, float]:
    start = number(item.get("start_seconds", 0), "start_seconds")
    end = number(item.get("end_seconds", duration), "end_seconds")
    if start < 0 or end - start < 0.15 or end > duration + 0.01:
        raise ValueError(f"Khoảng {start:g}–{end:g}s nằm ngoài cảnh {duration:g}s hoặc quá ngắn")
    return round(start, 3), round(min(end, duration), 3)


def normalize_direction(raw: Any, duration: float) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("direction phải là object")
    duration = number(duration, "duration")
    if duration <= 0:
        raise ValueError("Thời lượng cảnh phải dương")
    layers = []
    ids: set[str] = set()
    for item in _list(raw.get("graphic_layers", []), "graphic_layers", 8):
        identity = _text(item.get("id"), "layer.id", 64, True)
        if identity in ids:
            raise ValueError(f"Trùng layer id: {identity}")
        ids.add(identity)
        preset = item.get("preset")
        if preset not in PRESETS:
            raise ValueError(f"Preset chưa hỗ trợ: {preset}")
        start, end = _window(item, duration)
        bounds_raw = item.get("bounds") or {"x": .08, "y": .08, "width": .84, "height": .18}
        if not isinstance(bounds_raw, dict):
            raise ValueError("bounds phải là object")
        bounds = {k: number(bounds_raw.get(k), f"bounds.{k}") for k in ("x", "y", "width", "height")}
        if (bounds["x"] < .02 or bounds["y"] < .02 or bounds["width"] < .15 or bounds["height"] < .05
                or bounds["x"] + bounds["width"] > .98 + 1e-6
                or bounds["y"] + bounds["height"] > .86 + 1e-6):
            raise ValueError("Đồ họa vượt vùng an toàn (x 2–98%, y 2–86%)")
        palette, animation = item.get("palette", "blue"), item.get("animation", "pop")
        if palette not in PALETTES or animation not in {"pop", "slide_up", "fade"}:
            raise ValueError("Palette hoặc animation chưa hỗ trợ")
        children = []
        for child in _list(item.get("items", []), "items", 4):
            at = number(child.get("at_seconds", 0), "items.at_seconds")
            if child.get("icon") not in ICONS or at < 0 or at >= end - start:
                raise ValueError("Icon hoặc thời điểm xuất hiện không hợp lệ")
            if children and at < children[-1]["at_seconds"]:
                raise ValueError("Các bước icon_flow phải theo thứ tự thời gian")
            children.append({"label": _text(child.get("label"), "label", 22, True),
                             "icon": child["icon"], "at_seconds": round(at, 3)})
        if preset == "icon_flow" and len(children) < 2:
            raise ValueError("icon_flow cần 2–4 bước")
        layers.append({
            "id": identity, "preset": preset, "text": _text(item.get("text"), "text", 64, True),
            "secondary": _text(item.get("secondary"), "secondary", 100),
            "anchor_text": _text(item.get("anchor_text"), "anchor_text", 160),
            "anchor_occurrence": max(1, int(item.get("anchor_occurrence") or 1)),
            "start_seconds": start, "end_seconds": end, "bounds": bounds,
            "palette": palette, "animation": animation, "items": children,
            "reason": _text(item.get("reason"), "reason", 500),
        })
    cues = []
    for cue in _list(raw.get("audio_cues", []), "audio_cues", 12):
        at = number(cue.get("at_seconds", 0), "cue.at_seconds")
        gain = number(cue.get("gain_db", -22), "gain_db")
        linked = str(cue.get("layer_id") or "")
        offset = number(cue.get("offset_seconds", 0), "offset_seconds")
        if cue.get("preset") not in SOUNDS or not -36 <= gain <= -10:
            raise ValueError("SFX preset/gain không hợp lệ")
        if linked and linked not in ids:
            raise ValueError(f"SFX tham chiếu layer không tồn tại: {linked}")
        if linked:
            layer = next(x for x in layers if x["id"] == linked)
            at = layer["start_seconds"] + offset
            if offset < 0 or at >= layer["end_seconds"]:
                raise ValueError("SFX nằm ngoài layer được liên kết")
        if not 0 <= at < duration:
            raise ValueError("SFX nằm ngoài cảnh")
        cues.append({"preset": cue["preset"], "at_seconds": round(at, 3), "gain_db": gain,
                     "layer_id": linked, "offset_seconds": offset})
    beats, cursor = [], 0.0
    for beat in _list(raw.get("visual_beats", []), "visual_beats", 12):
        start, end = _window(beat, duration)
        if abs(start - cursor) > .015:
            raise ValueError("Visual beats phải liên tục từ đầu cảnh, không chồng hoặc bỏ trống")
        kind, effect = beat.get("source_kind", "primary"), beat.get("effect", "static")
        if kind not in {"primary", "asset"} or effect not in {"static", "zoom_in", "zoom_out"}:
            raise ValueError("Visual beat chưa được hỗ trợ")
        asset_id = int(beat.get("asset_id") or 0)
        if kind == "asset" and asset_id <= 0:
            raise ValueError("Beat dùng asset cần asset_id")
        beats.append({"start_seconds": start, "end_seconds": end, "source_kind": kind,
                      "effect": effect, "asset_id": asset_id,
                      "reason": _text(beat.get("reason"), "beat.reason", 500)})
        cursor = end
    if beats and abs(cursor - duration) > .015:
        raise ValueError("Visual beats phải phủ hết thời lượng cảnh")
    return {"version": 1, "duration_seconds": duration,
            "style_note": _text(raw.get("style_note"), "style_note", 1000),
            "graphic_layers": layers, "audio_cues": cues, "visual_beats": beats,
            "timing_basis": str(raw.get("timing_basis") or "estimated"),
            "audio_signature": str(raw.get("audio_signature") or ""),
            "warnings": [str(x)[:300] for x in (raw.get("warnings") or [])][:20]}


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFC", text).casefold())


def resolve_direction(raw: dict, rendered_duration: float, words: list[dict] | None = None) -> dict:
    """Scale all tracks together; then lock linked graphics/SFX to measured speech."""
    if not raw:
        return {}
    plan = normalize_direction(raw, float(raw["duration_seconds"]))
    result = copy.deepcopy(plan)
    ratio = rendered_duration / plan["duration_seconds"]
    flat_words = []
    for word in words or []:
        for token in _tokens(str(word.get("word") or word.get("text") or "")):
            flat_words.append((token, float(word["start"])))
    for layer in result["graphic_layers"]:
        start, end = layer["start_seconds"] * ratio, layer["end_seconds"] * ratio
        anchor = _tokens(layer["anchor_text"])
        if anchor and flat_words:
            matches = [i for i in range(len(flat_words) - len(anchor) + 1)
                       if [x[0] for x in flat_words[i:i+len(anchor)]] == anchor]
            occurrence = layer["anchor_occurrence"] - 1
            if len(matches) > occurrence:
                matched = flat_words[matches[occurrence]][1]
                end, start = min(rendered_duration, matched + end - start), matched
            else:
                result["warnings"].append(f"Không khớp lời thoại cho layer {layer['id']}; dùng mốc kế hoạch")
        layer["start_seconds"], layer["end_seconds"] = round(start, 3), round(end, 3)
        for item in layer["items"]:
            item["at_seconds"] = round(item["at_seconds"] * ratio, 3)
    for cue in result["audio_cues"]:
        cue["at_seconds"] *= ratio
        cue["offset_seconds"] *= ratio
    for beat in result["visual_beats"]:
        beat["start_seconds"] = round(beat["start_seconds"] * ratio, 3)
        beat["end_seconds"] = round(beat["end_seconds"] * ratio, 3)
    result["duration_seconds"] = rendered_duration
    result["timing_basis"] = "word_timestamps" if flat_words else result["timing_basis"]
    # Recompute linked cue times from the resolved layer, and validate again.
    return normalize_direction(result, rendered_duration)
