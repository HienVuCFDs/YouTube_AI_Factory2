"""Resolve planned sound cues to owned assets or original local presets."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .scene_compositor import write_sound_cues

PRESETS = {"pop": .16, "tick": .055, "chime": .48, "whoosh": .38}
TYPES = {*PRESETS, "hit", "ambient", "music_duck"}


def normalize_sound_cues(raw: Any, duration: float) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > 8:
        raise ValueError("Sound cues phải là danh sách tối đa 8 mục")
    result = []
    for cue in raw:
        if not isinstance(cue, dict):
            raise ValueError("Sound cue phải là object")
        kind = str(cue.get("type") or "pop")
        start = float(cue.get("start_seconds", 0))
        end = float(cue.get("end_seconds", min(duration, start + .5)))
        if kind not in TYPES or not all(math.isfinite(v) for v in (start, end, duration)):
            raise ValueError("Loại hoặc thời điểm sound cue không hợp lệ")
        if start < 0 or end <= start or end > duration + .05:
            raise ValueError("Sound cue nằm ngoài thời lượng cảnh")
        intensity = str(cue.get("intensity") or "medium")
        if intensity not in {"low", "medium", "high"}:
            raise ValueError("Cường độ SFX phải là low/medium/high")
        asset_id = int(cue.get("asset_id") or 0)
        result.append({"type": kind, "start_seconds": start, "end_seconds": min(end, duration),
                       "intensity": intensity, "asset_id": asset_id or None,
                       "asset_path": str(cue.get("asset_path") or cue.get("file_path") or ""),
                       "reason": str(cue.get("reason") or "")[:300]})
    return result


def preset_file(directory: Path, preset: str) -> Path:
    if preset not in PRESETS:
        raise ValueError("Preset SFX không hợp lệ")
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"{preset}-v1.wav"
    if not output.is_file():
        write_sound_cues([{"preset": preset, "at_seconds": 0, "gain_db": -10}], PRESETS[preset], output)
    return output


def resolve_sound_assets(database, project_id: int, raw: list, duration: float, directory: Path) -> list[dict]:
    cues = normalize_sound_cues(raw, duration)
    for cue in cues:
        if cue["type"] == "music_duck":
            # Executed as a gain envelope in the renderer, no audio asset needed.
            cue["asset_path"] = ""
            continue
        asset = database.get_project_asset(cue["asset_id"]) if cue["asset_id"] else None
        if cue["asset_id"] and (not asset or int(asset["project_id"]) != project_id):
            raise ValueError("SFX asset không thuộc dự án")
        if not asset and cue["asset_path"]:
            asset = database.find_project_asset_by_path(project_id, cue["asset_path"])
            if not asset:
                raise ValueError("Hãy import file SFX vào thư viện dự án trước")
        if asset:
            if asset["asset_type"] not in {"audio", "music", "sound_effect"}:
                raise ValueError("Asset SFX phải là âm thanh")
            path = Path(asset["file_path"])
            if not path.is_file():
                raise ValueError("Không tìm thấy file SFX")
            cue.update(asset_id=asset["id"], asset_path=str(path))
        else:
            preset = "pop" if cue["type"] == "hit" else cue["type"]
            if preset not in PRESETS:
                raise ValueError("Âm thanh ambient cần chọn file từ thư viện")
            path = preset_file(directory, preset)
            asset = database.find_project_asset_by_path(project_id, str(path)) or database.create_project_asset(
                project_id, "sound_effect", f"{preset} (local)", str(path), "audio/wav", path.stat().st_size)
            cue.update(asset_id=asset["id"], asset_path=str(path))
    return cues
