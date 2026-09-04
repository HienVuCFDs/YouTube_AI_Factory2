"""What of the source is still in the finished video, measured.

A reup is built from someone else's film, and the platform's reused-content
policy is not about whether the source was credited - it is about how much of
it is still there and how much was added. So the question has to be answered
with numbers before it is put to a model: how many seconds of picture came
straight from the source, whether its audio came with them, whether the
narration is the source's own words in another language, and whether its
logo and burned-in subtitles are still on screen.

A model asked without those facts can only guess, which is how this app
previously came to ask an edit planner about on-screen marks it had never
been shown. Here the model is given the measurements and asked to weigh
them; it does not do the measuring.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .ffmpeg_renderer import media_duration_seconds, resolve_ffprobe

# Where prepare_source_visuals writes the clips it cuts. A visual under this
# directory is the source's own picture, not something this project drew.
SOURCE_CLIP_MARKER = "source_clips"

# Above this share of the running time being the source's own footage, the
# video is a re-upload with commentary rather than a new work built from
# clips, whatever else was added.
HEAVY_REUSE_SHARE = 0.85

# Two narrations this close are the same script in different words - or the
# same words in another language, which the policy counts as reused all the
# same.
SAME_NARRATION_OVERLAP = 0.60


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", str(text or "").lower(), flags=re.UNICODE)


def narration_overlap(narration: str, transcript: str) -> float:
    """How much of the narration is the transcript's own vocabulary.

    A crude bag-of-words ratio on purpose: it is meant to catch a narration
    that is the source transcript lightly edited, not to judge writing.
    Different languages score near zero, which is correct - a translation is
    caught by the language check instead, not by this one.
    """
    spoken = set(_words(transcript))
    said = _words(narration)
    if not spoken or not said:
        return 0.0
    shared = sum(1 for word in said if word in spoken)
    return round(shared / len(said), 4)


def _has_audio_stream(path: Path, ffmpeg_binary: str) -> bool:
    import subprocess

    probe = resolve_ffprobe(ffmpeg_binary)
    if not probe or not path.is_file():
        return False
    try:
        result = subprocess.run(
            [probe, "-v", "error", "-select_streams", "a", "-show_entries",
             "stream=index", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return bool((result.stdout or "").strip())


def measure_reuse(
    timeline: list[dict[str, Any]],
    *,
    source_video: dict[str, Any] | None = None,
    transcript_text: str = "",
    publish_title: str = "",
    publish_language: str = "",
    ffmpeg_binary: str = "ffmpeg",
) -> dict[str, Any]:
    """The facts a reuse judgement rests on, taken from the project itself."""
    source_video = source_video or {}
    total = 0.0
    borrowed = 0.0
    borrowed_scenes = 0
    uncovered = 0
    carries_source_audio = False
    checked_audio = False

    for item in timeline:
        seconds = float(item.get("duration_seconds") or 0)
        total += seconds
        visual = str(item.get("visual_path") or "")
        if SOURCE_CLIP_MARKER not in visual.replace("/", "\\"):
            continue
        borrowed += seconds
        borrowed_scenes += 1
        cleanups = str(item.get("edit_cleanups") or "").strip()
        if cleanups in {"", "[]"} or '"kind": "none"' in cleanups:
            uncovered += 1
        # One clip is enough to know how they were all cut.
        if not checked_audio:
            checked_audio = True
            carries_source_audio = _has_audio_stream(Path(visual), ffmpeg_binary)

    narration = " ".join(str(item.get("voice_text") or "") for item in timeline)
    source_title = str(source_video.get("title") or "").strip()
    reused_title = bool(source_title) and source_title.lower() in str(publish_title or "").lower()

    return {
        "total_seconds": round(total, 2),
        "source_seconds": round(borrowed, 2),
        "source_share": round(borrowed / total, 4) if total else 0.0,
        "source_scenes": borrowed_scenes,
        "scene_count": len(timeline),
        "carries_source_audio": carries_source_audio,
        "scenes_with_marks_uncovered": uncovered,
        "narration_overlap": narration_overlap(narration, transcript_text),
        "narration_words": len(_words(narration)),
        "publish_language": str(publish_language or ""),
        "source_license": str(source_video.get("license") or "") or "unknown",
        "source_duration_seconds": float(source_video.get("duration_seconds") or 0),
        "reuses_source_title": reused_title,
        "source_title": source_title[:200],
    }


def rule_findings(facts: dict[str, Any]) -> list[dict[str, str]]:
    """What the numbers alone already say, before any model is asked.

    These are the ones that do not need judgement: they are either true of
    the files or not, and each names the fix rather than only the problem.
    """
    findings: list[dict[str, str]] = []

    if facts["source_share"] >= HEAVY_REUSE_SHARE and facts["source_scenes"]:
        # Every reup is close to 100% source footage - that is what a reup is,
        # and an alarm that is always on gets ignored. What separates an
        # accepted retelling from reused content is what was added on top, so
        # the severity follows the narration rather than the footage share.
        thin = (
            not facts["narration_words"]
            or facts["narration_overlap"] >= SAME_NARRATION_OVERLAP
        )
        findings.append({
            "severity": "high" if thin else "medium",
            "code": "reused_footage",
            "detail": (
                f"{facts['source_share'] * 100:.0f}% thời lượng là hình cắt thẳng từ video gốc "
                f"({facts['source_seconds']:.0f}/{facts['total_seconds']:.0f} giây). "
                + (
                    "Lời bình chưa đủ khác để coi là nội dung mới — YouTube sẽ xếp vào nội dung dùng lại."
                    if thin
                    else "Phần được coi là mới nằm ở lời bình riêng của bạn; hãy giữ nguyên yếu tố đó."
                )
            ),
            "fix": (
                "Viết lời bình của riêng bạn, hoặc thêm cảnh tự dựng." if thin
                else "Thêm cảnh tự dựng hoặc đồ hoạ nếu muốn giảm rủi ro thêm nữa."
            ),
        })

    if facts["carries_source_audio"]:
        findings.append({
            "severity": "high",
            "code": "source_audio",
            "detail": "Clip cắt ra vẫn còn tiếng của video gốc — gồm cả nhạc nền của họ.",
            "fix": "Cắt lại clip ở chế độ tắt tiếng và chỉ dùng giọng đọc của bạn.",
        })

    if facts["scenes_with_marks_uncovered"]:
        findings.append({
            "severity": "medium",
            "code": "source_marks",
            "detail": (
                f"{facts['scenes_with_marks_uncovered']}/{facts['source_scenes']} cảnh chưa che "
                "logo hoặc phụ đề cháy sẵn của kênh gốc."
            ),
            "fix": "Ở Storyboard, bấm “Dò tự động từ video gốc” rồi render lại.",
        })

    if facts["narration_overlap"] >= SAME_NARRATION_OVERLAP:
        findings.append({
            "severity": "high",
            "code": "same_narration",
            "detail": (
                f"Lời đọc trùng {facts['narration_overlap'] * 100:.0f}% từ vựng với transcript "
                "của video gốc — gần như đọc lại lời của họ."
            ),
            "fix": "Viết lại lời bình bằng cách kể của bạn, đừng chép lại lời gốc.",
        })

    if facts["reuses_source_title"]:
        findings.append({
            "severity": "medium",
            "code": "reused_title",
            "detail": "Tiêu đề đăng vẫn chứa tiêu đề của video gốc.",
            "fix": "Dùng một trong các tiêu đề AI đã viết cho video này.",
        })

    if not facts["narration_words"]:
        findings.append({
            "severity": "high",
            "code": "no_narration",
            "detail": "Chưa có lời bình nào — video mới chỉ là hình của người khác.",
            "fix": "Tạo giọng đọc từ kịch bản trước khi đăng.",
        })

    return findings


def rule_verdict(findings: list[dict[str, str]]) -> str:
    if any(item["severity"] == "high" for item in findings):
        return "high"
    if findings:
        return "medium"
    return "low"
