"""Report what a source video contains — the story and every line spoken in it.

This used to return a production brief: abstract story beats, a style recipe,
pacing notes. All of it was about *how the source was made*, and none of it was
the thing the next step actually needs, which is what the source says. A writer
handed "rhythm map: escalation, reversal, payoff" cannot retell a folk tale; a
writer handed the events in order and the characters' own words can.

So it is simpler now, and it is complete. Nothing may be summarised away: the
whole story, every line of dialogue, and an honest list of what could not be
made out. A long transcript is read in pieces rather than truncated, because a
brief that quietly stops halfway is worse than one that admits it is partial.

It also rules on nothing. Whether the new video may keep or change any of this
is decided in the script step, which is where the rules live.
"""

from __future__ import annotations

import re
from typing import Any

from . import languages, operations
from .llm_client import (
    LlmError,
    call_antigravity_json,
    call_claude_code_cli_json,
    call_claude_json,
    call_codex_json,
    call_openai_json,
)


ReferenceAnalysisError = LlmError

# The answer is bigger than the question here: every utterance comes back
# attributed and translated, so a chunk is capped by how many lines it holds
# rather than by its own size. 511 lines in one call ran out of output budget
# and timed out; in pieces this size each call returns comfortably.
_CHUNK_CHARS = 4500
_CHUNK_LINES = 90

REFERENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "content_summary": {"type": "string"},
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                },
                "required": ["name", "role"],
                "additionalProperties": False,
            },
        },
        "dialogue": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "order": {"type": "integer"},
                    "speaker": {"type": "string"},
                    "line": {"type": "string"},
                    # Where this turn sits in the source. It is what lets the
                    # reup workflow cut each scene exactly where the line is
                    # spoken instead of guessing at scene boundaries.
                    "start_seconds": {"type": "number"},
                    "end_seconds": {"type": "number"},
                },
                "required": ["order", "speaker", "line"],
                "additionalProperties": False,
            },
        },
        "scene_map": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "order": {"type": "integer"},
                    "what_happens": {"type": "string"},
                },
                "required": ["order", "what_happens"],
                "additionalProperties": False,
            },
        },
        "visual_style": {"type": "string"},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["content_summary", "characters", "dialogue", "scene_map", "limitations"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = """You are writing down what a source video contains, for someone who cannot
watch it and who will retell it.

Two things matter above all:
1. THE STORY, complete. Every event, in the order it happens, through to the ending. Not a
   summary - if you leave something out, it is gone.
2. THE DIALOGUE. Every line a character speaks, attributed to whoever says it, in order and in
   their own words. Narration counts too: attribute it to "Người dẫn". Do not paraphrase a line
   into a description of it.

Keep everything else short. A sentence or two on how it looks is enough; nobody needs a style
recipe. You are not deciding what a new video may keep or change - that is settled later, when
the script is written.

Never invent. Automatic transcripts mishear words, drop endings and run speakers together. Where
you cannot tell who is speaking, say "Không rõ". Where a line is garbled, keep what you can and
mark the rest. Put every such gap in limitations, so nobody later mistakes a guess for a fact.
Return only the requested JSON."""


def _chunks(text: str, size: int = _CHUNK_CHARS, lines: int = _CHUNK_LINES) -> list[str]:
    """Break the transcript into readable pieces without cutting a line."""
    body = (text or "").strip()
    if not body:
        return []
    units = [line for line in body.splitlines() if line.strip()]
    if len(units) <= 1:
        # A wall of text with no line breaks: fall back to sentence boundaries.
        units = [part for part in re.split(r"(?<=[.!?…])\s+", body) if part.strip()]
    if len(units) <= lines and len(body) <= size:
        return [body]
    pieces: list[str] = []
    current: list[str] = []
    length = 0
    for unit in units:
        if len(current) >= lines or (current and length + len(unit) + 1 > size):
            pieces.append("\n".join(current))
            current, length = [], 0
        current.append(unit)
        length += len(unit) + 1
    if current:
        pieces.append("\n".join(current))
    return pieces


def _call(provider: str, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    name = str(provider or "codex_cli").strip().lower()
    callers = {
        "codex_cli": call_codex_json,
        "openai_gpt": call_openai_json,
        "anthropic_claude": call_claude_json,
        "claude_code_cli": call_claude_code_cli_json,
        "antigravity": call_antigravity_json,
    }
    caller = callers.get(name)
    if caller is None:
        raise ReferenceAnalysisError(f"Provider không được hỗ trợ cho phân tích tham chiếu: {provider}")
    return caller(system_prompt, user_prompt, REFERENCE_SCHEMA, max_tokens=16000)


def _prompt(
    video: dict[str, Any],
    transcript_text: str | None,
    output_language: str = languages.DEFAULT_LANGUAGE,
    part: int = 1,
    total_parts: int = 1,
    known_characters: list[dict[str, Any]] | None = None,
) -> str:
    parts = [
        f"Tiêu đề nguồn: {str(video.get('title') or '').strip()}",
        f"Mô tả nguồn: {str(video.get('description') or '').strip()[:1200]}",
    ]
    if total_parts > 1:
        parts.append(
            f"Đây là PHẦN {part}/{total_parts} của bản ghi. Chỉ ghi lại những gì có trong phần này; "
            "đừng tóm tắt lại các phần khác và đừng đoán phần chưa đọc tới. "
            "content_summary chỉ kể nội dung phần này, KHÔNG ghi thêm nhãn 'PHẦN x/y' vào đầu."
        )
    # Each part is read on its own, so without this the same person is renamed
    # every time - "nhan vat chinh", then "trang si", then his actual name -
    # and one character comes back as three.
    if known_characters:
        listing = "; ".join(
            f"{str(person.get('name') or '').strip()} ({str(person.get('role') or '').strip()[:60]})"
            for person in known_characters if str(person.get("name") or "").strip()
        )
        parts.append(
            "NHÂN VẬT ĐÃ ĐẶT TÊN Ở CÁC PHẦN TRƯỚC — nếu người nói ở phần này là một trong số họ, "
            "hãy dùng ĐÚNG cái tên đó, đừng đặt tên mới:\n" + listing
        )
    if transcript_text:
        parts.append(
            "BẢN GHI LỜI NÓI. Mỗi dòng là MỘT lượt nói, theo đúng thứ tự, kèm mốc giây. "
            "Bản ghi do máy nghe lại nên KHÔNG có tên người nói và thường KHÔNG có dấu câu — "
            "bạn phải tự suy ra ai đang nói dựa vào nội dung, cách xưng hô và mạch đối đáp. "
            "Chỗ nào không suy ra được thì ghi 'Không rõ', đừng gán bừa cho một nhân vật.\n"
            f"{transcript_text}"
        )
    else:
        parts.append(
            "Không có bản ghi lời nói và không có khung hình nào. Đừng giả vờ đã xem video: "
            "ghi rõ trong limitations rằng mọi nhận định chỉ dựa trên tiêu đề và mô tả."
        )
    parts.append(
        "Hãy ghi lại:\n"
        "- content_summary: TOÀN BỘ câu chuyện/nội dung, kể tuần tự từ đầu đến hết. Đủ chi tiết để "
        "người đọc kể lại được mà không cần xem video.\n"
        "- characters: những ai xuất hiện, mỗi người một dòng ngắn.\n"
        "- dialogue: TỪNG LƯỢT NÓI, theo đúng thứ tự, kèm người nói. Gộp các dòng liền nhau của "
        "cùng một người thành một lượt; đổi người nói thì sang lượt mới. Lời dẫn chuyện ghi người "
        "nói là 'Người dẫn'. Không được rút gọn, không được bỏ lượt nào, không được mô tả thay vì "
        "trích lời. Mỗi lượt phải kèm 'start_seconds' và 'end_seconds' lấy đúng từ mốc giây "
        "[Ns] của các dòng tạo nên lượt đó — đây là căn cứ để cắt hình sau này.\n"
        "- scene_map: các đoạn nội dung theo thứ tự, mỗi đoạn một câu chuyện gì đang xảy ra.\n"
        "- visual_style: một hai câu về hình ảnh, ngắn thôi.\n"
        "- limitations: chỗ nào nghe không rõ, không biết ai nói, hoặc không xác định được."
    )
    parts.append(languages.instruction(output_language))
    return "\n\n".join(parts)


def _is_empty(reading: dict[str, Any]) -> bool:
    """Whether a reading says nothing at all.

    A provider that returns a well-formed but empty object is not a success.
    That is exactly what happened when the Antigravity envelope was misread:
    five parts ran, every field came back missing, and an analysis with no
    story, no cast and no dialogue was stored and shown as finished.
    """
    return not any((
        str(reading.get("content_summary") or "").strip(),
        reading.get("characters") or [],
        reading.get("dialogue") or [],
        reading.get("scene_map") or [],
    ))


def _merge(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Join per-chunk readings into one, keeping order and dropping repeats.

    Chunks are read independently, so the same character is introduced more
    than once while dialogue simply continues. Characters are de-duplicated by
    name; dialogue and events are concatenated and renumbered, because their
    order across the whole video is the thing being preserved.
    """
    merged: dict[str, Any] = {
        "content_summary": "",
        "characters": [],
        "dialogue": [],
        "scene_map": [],
        "visual_style": "",
        "limitations": [],
    }
    seen_characters: set[str] = set()
    summaries: list[str] = []
    for result in results:
        summary = str(result.get("content_summary") or "").strip()
        if summary:
            summaries.append(summary)
        for person in result.get("characters") or []:
            name = str(person.get("name") or "").strip()
            if name and name.lower() not in seen_characters:
                seen_characters.add(name.lower())
                merged["characters"].append(person)
        for line in result.get("dialogue") or []:
            merged["dialogue"].append({
                "order": len(merged["dialogue"]) + 1,
                "speaker": str(line.get("speaker") or "Không rõ"),
                "line": str(line.get("line") or ""),
                "start_seconds": float(line.get("start_seconds") or 0),
                "end_seconds": float(line.get("end_seconds") or 0),
            })
        for beat in result.get("scene_map") or []:
            merged["scene_map"].append({
                "order": len(merged["scene_map"]) + 1,
                "what_happens": str(beat.get("what_happens") or ""),
            })
        if not merged["visual_style"]:
            merged["visual_style"] = str(result.get("visual_style") or "")
        for item in result.get("limitations") or []:
            text = str(item)
            if text not in merged["limitations"]:
                merged["limitations"].append(text)
    merged["content_summary"] = "\n\n".join(summaries)
    return merged


def analyze_reference(
    video: dict[str, Any],
    transcript_text: str | None,
    provider: str,
    output_language: str = languages.DEFAULT_LANGUAGE,
    mode: str = "remake",
) -> dict[str, Any]:
    """Read the source through, in as many passes as its transcript needs."""
    del mode  # One brief now: describe the source, rule on nothing.
    pieces = _chunks(transcript_text or "")
    if not pieces:
        result = _call(provider, _SYSTEM_PROMPT, _prompt(video, None, output_language))
        parts_read = 0
    else:
        readings: list[dict[str, Any]] = []
        cast: list[dict[str, Any]] = []
        for index, piece in enumerate(pieces):
            # A cancel lands here even if the call already in flight cannot be
            # stopped: the next pass simply never starts.
            operations.check()
            operations.set_step(f"Đọc phần {index + 1}/{len(pieces)} của bản ghi")
            reading = _call(
                provider,
                _SYSTEM_PROMPT,
                _prompt(video, piece, output_language, index + 1, len(pieces), cast),
            )
            readings.append(reading)
            cast = _merge(readings)["characters"]
        result = _merge(readings) if len(readings) > 1 else readings[0]
        parts_read = len(pieces)
    if _is_empty(result):
        raise ReferenceAnalysisError(
            f"{provider} chay xong nhung khong tra ve noi dung nao: khong co tom tat, "
            "khong nhan vat, khong loi thoai. Hay thu lai hoac doi sang AI khac."
        )
    return {
        "provider": str(provider or "codex_cli").strip().lower(),
        "source_type": "transcript" if transcript_text else "metadata",
        "visual_evidence": "transcript-guided" if transcript_text else "metadata-only",
        "transcript_parts_read": parts_read,
        **result,
    }
