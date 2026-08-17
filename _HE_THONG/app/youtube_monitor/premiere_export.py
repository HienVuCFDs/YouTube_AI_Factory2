from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .project_layout import ensure_project_layout
from .timeline_builder import timeline_to_manifest


def _srt_timestamp(seconds: int | float) -> str:
    total_ms = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def timeline_to_srt(timeline: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for index, item in enumerate(timeline, start=1):
        text = str(item.get("subtitle_text") or item.get("voice_text") or "").strip()
        if not text:
            continue
        start = item.get("start_seconds") or 0
        end = item.get("end_seconds") or start + (item.get("duration_seconds") or 1)
        parts.extend(
            [
                str(index),
                f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}",
                text,
                "",
            ]
        )
    return "\n".join(parts).strip() + ("\n" if parts else "")


def _copy_asset(
    source: str,
    destination_dir: Path,
    filename: str,
) -> dict[str, Any]:
    source_text = str(source or "").strip()
    if not source_text:
        return {"source_path": "", "package_path": "", "exists": False}
    source_path = Path(source_text)
    if not source_path.is_file():
        return {"source_path": source_text, "package_path": "", "exists": False}
    destination_dir.mkdir(parents=True, exist_ok=True)
    suffix = source_path.suffix or ".bin"
    destination = destination_dir / f"{filename}{suffix}"
    shutil.copy2(source_path, destination)
    return {
        "source_path": source_text,
        "package_path": str(destination),
        "relative_path": str(destination.relative_to(destination_dir.parent.parent)).replace("\\", "/"),
        "exists": True,
    }


def _xml_text(parent: ET.Element, tag: str, value: Any) -> ET.Element:
    element = ET.SubElement(parent, tag)
    element.text = str(value)
    return element


def _file_element(
    parent: ET.Element,
    file_path: Path,
    file_id: str,
    media_type: str,
    duration_frames: int,
) -> None:
    file_element = ET.SubElement(parent, "file", id=file_id)
    _xml_text(file_element, "name", file_path.name)
    _xml_text(file_element, "pathurl", file_path.resolve().as_uri())
    media = ET.SubElement(file_element, "media")
    media_node = ET.SubElement(media, media_type)
    _xml_text(media_node, "duration", duration_frames)


def _clipitem(
    parent: ET.Element,
    item: dict[str, Any],
    media_type: str,
    file_path: Path,
    clip_index: int,
    fps: int = 30,
) -> None:
    start = int(round(float(item.get("start_seconds") or 0) * fps))
    end = int(round(float(item.get("end_seconds") or 0) * fps))
    duration = max(1, end - start)
    clip = ET.SubElement(parent, "clipitem", id=f"{media_type}-{clip_index}")
    _xml_text(clip, "name", f"{media_type.title()} {int(item.get('segment_index') or clip_index):03d}")
    _xml_text(clip, "duration", duration)
    _xml_text(clip, "rate", "")
    rate = clip.find("rate")
    _xml_text(rate, "timebase", fps)
    _xml_text(rate, "ntsc", "FALSE")
    _xml_text(clip, "start", start)
    _xml_text(clip, "end", end)
    _xml_text(clip, "in", 0)
    _xml_text(clip, "out", duration)
    _file_element(clip, file_path, f"file-{media_type}-{clip_index}", media_type, duration)
    source_track = ET.SubElement(clip, "sourcetrack")
    _xml_text(source_track, "mediatype", media_type)
    _xml_text(source_track, "trackindex", 1)


def timeline_to_premiere_xml(
    project: dict[str, Any],
    script: dict[str, Any],
    timeline: list[dict[str, Any]],
) -> str:
    fps = 30
    total_frames = int(round(sum(float(item.get("duration_seconds") or 0) for item in timeline) * fps))
    root = ET.Element("xmeml", version="5")
    sequence = ET.SubElement(root, "sequence", id="sequence-youtube-ai-factory")
    _xml_text(sequence, "name", project.get("title") or script.get("script_title") or "YouTube AI Factory")
    _xml_text(sequence, "duration", total_frames)
    rate = ET.SubElement(sequence, "rate")
    _xml_text(rate, "timebase", fps)
    _xml_text(rate, "ntsc", "FALSE")
    _xml_text(sequence, "timecode", "0")
    media = ET.SubElement(sequence, "media")
    video = ET.SubElement(media, "video")
    _xml_text(video, "format", "")
    video_format = video.find("format")
    video_rate = ET.SubElement(video_format, "rate")
    _xml_text(video_rate, "timebase", fps)
    _xml_text(video_rate, "ntsc", "FALSE")
    video_track = ET.SubElement(video, "track")
    audio = ET.SubElement(media, "audio")
    audio_track = ET.SubElement(audio, "track")

    video_index = 0
    audio_index = 0
    for item in timeline:
        visual_path = Path(str(item.get("visual_path") or ""))
        if visual_path.is_file():
            video_index += 1
            _clipitem(video_track, item, "video", visual_path, video_index, fps=fps)
        audio_path = Path(str(item.get("audio_path") or ""))
        if audio_path.is_file():
            audio_index += 1
            _clipitem(audio_track, item, "audio", audio_path, audio_index, fps=fps)

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return xml_bytes.decode("utf-8") + "\n"


def build_premiere_export_package(
    project: dict[str, Any],
    script: dict[str, Any],
    timeline: list[dict[str, Any]],
    source_video: dict[str, Any] | None,
    output_root: Path,
) -> dict[str, Any]:
    if not timeline:
        raise ValueError("Project chưa có timeline để xuất gói Premiere")

    layout = ensure_project_layout(output_root, project["id"])
    project_dir = layout["root"]
    export_dir = layout["premiere"]
    media_dir = export_dir / "media"
    audio_dir = media_dir / "audio"
    visual_dir = media_dir / "visual"
    source_dir = media_dir / "source"

    exported_segments: list[dict[str, Any]] = []
    missing_assets: list[dict[str, Any]] = []
    for item in timeline:
        segment = dict(item)
        index = int(item.get("segment_index") or len(exported_segments) + 1)
        audio = _copy_asset(str(item.get("audio_path") or ""), audio_dir, f"segment-{index:03d}")
        visual = _copy_asset(str(item.get("visual_path") or ""), visual_dir, f"segment-{index:03d}")
        segment["audio_file"] = audio.get("relative_path", "")
        segment["visual_file"] = visual.get("relative_path", "")
        exported_segments.append(segment)
        for asset_type, asset in (("audio", audio), ("visual", visual)):
            if asset.get("source_path") and not asset.get("exists"):
                missing_assets.append(
                    {
                        "segment_index": index,
                        "asset_type": asset_type,
                        "source_path": asset["source_path"],
                    }
                )

    source_asset = {"source_path": "", "package_path": "", "exists": False}
    if source_video:
        source_asset = _copy_asset(
            str(source_video.get("local_media_path") or ""),
            source_dir,
            "source-video",
        )
        if source_asset.get("source_path") and not source_asset.get("exists"):
            missing_assets.append(
                {
                    "segment_index": 0,
                    "asset_type": "source_video",
                    "source_path": source_asset["source_path"],
                }
            )

    manifest = {
        "manifest_version": "youtube_ai_factory.premiere.v1",
        "project_id": project.get("id"),
        "project_title": project.get("title") or script.get("script_title") or "",
        "script_id": script.get("id"),
        "script_title": script.get("script_title") or "",
        "sequence_name": project.get("title") or script.get("script_title") or "YouTube AI Factory",
        "fps": 30,
        "subtitle_file": "subtitles.srt",
        "sequence_xml_file": "premiere_sequence.xml",
        "source_video": source_asset,
        "segments": exported_segments,
        "missing_assets": missing_assets,
        "timeline": timeline_to_manifest(project, script, timeline),
    }
    manifest_path = export_dir / "premiere_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    srt_path = export_dir / "subtitles.srt"
    srt_path.write_text(timeline_to_srt(timeline), encoding="utf-8")
    xml_segments: list[dict[str, Any]] = []
    for segment in exported_segments:
        xml_segment = dict(segment)
        if segment.get("audio_file"):
            xml_segment["audio_path"] = str(export_dir / segment["audio_file"])
        if segment.get("visual_file"):
            xml_segment["visual_path"] = str(export_dir / segment["visual_file"])
        xml_segments.append(xml_segment)
    xml_path = export_dir / "premiere_sequence.xml"
    xml_path.write_text(timeline_to_premiere_xml(project, script, xml_segments), encoding="utf-8")
    readme_path = export_dir / "README.md"
    readme_path.write_text(
        "\n".join(
            [
                f"# Premiere Export Pack: {manifest['project_title']}",
                "",
                "1. Mở `premiere_sequence.xml` trong Adobe Premiere Pro bằng File → Import.",
                "2. Nếu Premiere hỏi relink media, chọn thư mục `media` trong gói này.",
                "3. Import `subtitles.srt` nếu cần chỉnh phụ đề trực tiếp trong Premiere.",
                "4. Kiểm tra các asset còn thiếu trong `premiere_manifest.json`.",
                "",
                "Gói này chỉ chứa các file local đã được gắn trong timeline; hệ thống không tự tải video YouTube.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    zip_path = layout["exports"] / "premiere-package.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in export_dir.rglob("*"):
            if path.is_file():
                archive.write(path, Path("premiere_export") / path.relative_to(export_dir))

    return {
        "project_id": project.get("id"),
        "export_dir": str(export_dir),
        "zip_path": str(zip_path),
        "manifest_path": str(manifest_path),
        "sequence_xml_path": str(xml_path),
        "subtitle_path": str(srt_path),
        "download_filename": zip_path.name,
        "segments": len(timeline),
        "missing_assets": missing_assets,
    }
