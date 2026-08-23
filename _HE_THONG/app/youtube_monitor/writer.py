from __future__ import annotations

import math
import re
from typing import Any

from .llm_client import LlmError, call_antigravity_json, call_claude_code_cli_json, call_claude_json, call_codex_json, call_openai_json
from .antigravity_bridge import antigravity_cli_status
from .claude_code_bridge import claude_code_cli_status
from .codex_bridge import codex_cli_status
from .folklore_research import source_animal
from . import settings


WriterError = LlmError

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "key_ideas": {"type": "array", "items": {"type": "string"}},
        "new_titles": {"type": "array", "items": {"type": "string"}},
        "new_description": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "cta": {"type": "string"},
        "script_outline": {"type": "array", "items": {"type": "string"}},
        "creative_direction": {"type": "string"},
        "new_story_concept": {"type": "string"},
        "style_application": {"type": "array", "items": {"type": "string"}},
        "new_script": {
            "type": "object",
            "properties": {
                "script_title": {"type": "string"}, "hook": {"type": "string"},
                "intro": {"type": "string"}, "main_content": {"type": "string"}, "cta": {"type": "string"},
            },
            "required": ["script_title", "hook", "intro", "main_content", "cta"],
            "additionalProperties": False,
        },
        "scene_blueprints": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "order": {"type": "integer"}, "section": {"type": "string"},
                    "narration": {"type": "string"}, "visual_prompt": {"type": "string"},
                    "asset_type": {"type": "string"}, "duration_seconds": {"type": "integer"},
                },
                "required": ["order", "section", "narration", "visual_prompt", "asset_type", "duration_seconds"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "summary", "key_ideas", "new_titles", "new_description",
        "hashtags", "cta", "script_outline", "creative_direction", "new_story_concept", "style_application", "new_script", "scene_blueprints",
    ],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "Bạn là biên kịch YouTube chuyên chuyển thể sáng tạo. Trước khi viết, hãy xác định ĐÚNG "
    "loại nội dung của video nguồn (giải thích kiến thức, hướng dẫn, bình luận, truyện kể...). "
    "Mặc định phải giữ chính loại nội dung, chủ đề có ích, đối tượng, nhịp trình bày và giọng điệu của nguồn. "
    "Chỉ sửa đổi góc nhìn, ví dụ, tình huống và hình minh họa để tạo video độc lập; không biến "
    "video kiến thức thành truyện cổ tích hoặc đổi từ thể loại này sang thể loại khác, trừ khi người dùng nêu rõ. "
    "Không sao chép câu chữ, ví dụ đặc trưng, nhân vật, diễn biến hay bố cục hình ảnh của nguồn. "
    "Từng scene_blueprints phải là cảnh AI mới có prompt hình ảnh cụ thể để tạo video. Trả về đúng JSON."
)

_MAX_TRANSCRIPT_CHARS = 8000
# Vietnamese is written as syllable-separated tokens.  VoxCPM speaks roughly
# 3.0--3.3 of those tokens per second in the local production setup, noticeably
# faster than the former generic narration estimate.  Keep a small writing
# buffer so an exported video does not end minutes before its requested length.
VIETNAMESE_VOICE_TOKENS_PER_SECOND = 3.2
MIN_VIETNAMESE_VOICE_TOKENS_PER_SECOND = 3.0


def parse_duration_text(value: str) -> int | None:
    """Parse HH:MM:SS, MM:SS and Vietnamese hour/minute/second expressions."""
    text = (value or "").strip().lower()
    if not text:
        return None
    if re.fullmatch(r"\d+", text):
        return int(text)
    clock = re.fullmatch(r"(\d{1,2}):([0-5]\d)(?::([0-5]\d))?", text)
    if clock:
        first, second, third = (int(part) if part is not None else None for part in clock.groups())
        return first * 60 + second if third is None else first * 3600 + second * 60 + third
    hours = re.search(r"\b(\d{1,2})\s*(?:giờ|gio|hours?|hrs?|h)\b", text)
    minutes = re.search(r"\b(\d{1,3})\s*(?:phút|phut|minutes?|mins?|m)\b", text)
    seconds = re.search(r"\b(\d{1,4})\s*(?:giây|giay|seconds?|secs?|s)\b", text)
    if hours or minutes or seconds:
        return (int(hours.group(1)) * 3600 if hours else 0) + (int(minutes.group(1)) * 60 if minutes else 0) + (int(seconds.group(1)) if seconds else 0)
    return None


def resolve_target_duration_seconds(
    requested_seconds: int | None,
    instruction: str = "",
    duration_text: str = "",
    source_duration_seconds: int | None = None,
) -> int:
    """Use an explicit duration first, then duration text, otherwise inspect the prompt."""
    if requested_seconds is not None:
        return max(30, min(1800, int(requested_seconds)))
    parsed_text = parse_duration_text(duration_text)
    if duration_text.strip() and parsed_text is None:
        raise WriterError("Không hiểu thời lượng. Hãy nhập 00:12:00, 12:00, 12 phút hoặc 720 giây.")
    if parsed_text is not None:
        if not 30 <= parsed_text <= 1800:
            raise WriterError("Thời lượng phải nằm trong khoảng 00:00:30 đến 00:30:00.")
        return parsed_text
    text = (instruction or "").lower()
    minute_match = re.search(r"\b(\d{1,2})\s*(?:phút|phut|mins?|minutes?)\b", text)
    if minute_match:
        return max(30, min(1800, int(minute_match.group(1)) * 60))
    second_match = re.search(r"\b(\d{2,4})\s*(?:giây|giay|secs?|seconds?)\b", text)
    if second_match:
        return max(30, min(1800, int(second_match.group(1))))
    clock_match = re.search(r"\b(\d{1,2})\s*:\s*(\d{2})\b", text)
    if clock_match:
        return max(30, min(1800, int(clock_match.group(1)) * 60 + int(clock_match.group(2))))
    if source_duration_seconds is not None and int(source_duration_seconds) >= 30:
        return max(30, min(1800, int(source_duration_seconds)))
    return 90


def validate_voiceover_plan(content: dict[str, Any], target_duration_seconds: int) -> list[str]:
    """Return production-quality warnings without discarding a generated script."""
    scenes = content.get("scene_blueprints") if isinstance(content, dict) else None
    if not isinstance(scenes, list) or not scenes:
        raise WriterError("AI chưa tạo được storyboard có lời dẫn để sản xuất video")
    target = max(30, int(target_duration_seconds or 90))
    total_seconds = sum(max(0, int(item.get("duration_seconds") or 0)) for item in scenes if isinstance(item, dict))
    voice_text = " ".join(str(item.get("narration") or "") for item in scenes if isinstance(item, dict))
    spoken_words = len(re.findall(r"\w+", voice_text, flags=re.UNICODE))
    required_words = math.ceil(target * MIN_VIETNAMESE_VOICE_TOKENS_PER_SECOND)
    warnings: list[str] = []
    if not (target * 0.9 <= total_seconds <= target * 1.1):
        warnings.append(
            f"Storyboard dự kiến {total_seconds} giây, khác thời lượng mục tiêu {target} giây."
        )
    # Scene durations have an allowed ±10% range.  Apply the same tolerance to
    # narration density: a script that is only a few percent short is still a
    # valid natural read, and should be saved instead of forcing the user to
    # regenerate the entire story.
    minimum_spoken_words = math.ceil(required_words * 0.9)
    if spoken_words < minimum_spoken_words:
        warnings.append(
            f"Lời dẫn có {spoken_words} từ; mục tiêu khoảng {required_words} từ cho video {target} giây."
        )
    sparse_scenes = [
        str(index + 1)
        for index, item in enumerate(scenes)
        if isinstance(item, dict)
        and int(item.get("duration_seconds") or 0) >= 10
        and len(re.findall(r"\w+", str(item.get("narration") or ""), flags=re.UNICODE))
            < math.ceil(int(item.get("duration_seconds") or 0) * 2.7)
    ]
    if sparse_scenes:
        preview = ", ".join(sparse_scenes[:8])
        warnings.append(
            f"Lời dẫn ở cảnh {preview} có thể ngắn hơn thời lượng đã ghi."
        )
    return warnings


FAITHFUL_RETELL_MODE = "faithful_retell"

# A retelling is judged against the source, so the source has to arrive whole.
# The ordinary writing path can afford to see the first 8000 characters of a
# transcript because it is inventing anyway; here the ending is usually the
# part that matters most - a folk tale is its ending - and quietly dropping it
# is how a retelling starts making things up.
_MAX_FAITHFUL_TRANSCRIPT_CHARS = 40000

_FAITHFUL_SYSTEM_PROMPT = (
    "Bạn là người DẪN CHUYỆN kể lại đúng nội dung của một video có sẵn. "
    "Bạn KHÔNG phải biên kịch sáng tạo, và đây KHÔNG phải bản chuyển thể.\n"
    "Nội dung là BẤT BIẾN: mọi sự việc, nhân vật, tên riêng, địa danh, con số, mốc thời gian, "
    "thứ tự diễn biến và cái kết đều phải giữ đúng như nguồn.\n"
    "Bạn CHỈ được đổi CÁCH KỂ: cách đặt câu, nhịp kể, cách chọn từ, cách mở đầu và cách nối các đoạn.\n"
    "TUYỆT ĐỐI KHÔNG: thêm nhân vật, thêm tình tiết, thêm chi tiết trang trí, đổi tên, đổi số liệu, "
    "đổi kết cục, đảo thứ tự sự việc, hay rút ra bài học mà nguồn không nói.\n"
    "Nguồn nói mơ hồ chỗ nào thì kể mơ hồ chỗ đó; không được đoán rồi kể như thật.\n"
    "Đây là truyện dân gian, tin tức hoặc nội dung lịch sử: người xem tra được, sai một chi tiết là hỏng cả video.\n"
    "Trả về đúng JSON."
)


def _faithful_source_text(transcript_text: str) -> str:
    """Give the retelling the whole source, or both of its ends.

    Cutting only the tail would hide the ending, which is exactly the part a
    retelling must not get wrong. When the source really is too long, the gap
    is marked so the model knows it is missing a middle rather than believing
    the story stops there.
    """
    text = transcript_text.strip()
    if len(text) <= _MAX_FAITHFUL_TRANSCRIPT_CHARS:
        return text
    half = _MAX_FAITHFUL_TRANSCRIPT_CHARS // 2
    return (
        text[:half]
        + "\n\n[...PHẦN GIỮA BỊ LƯỢC BỚT VÌ QUÁ DÀI — "
        "đừng suy diễn nội dung đoạn này, chỉ kể phần bạn đọc được...]\n\n"
        + text[-half:]
    )


def _build_faithful_prompt(
    video: dict[str, Any],
    transcript_text: str | None,
    workflow_context: dict[str, Any] | None = None,
    creative_direction: str | None = None,
    target_duration_seconds: int = 90,
    source_duration_seconds: int | None = None,
) -> str:
    """Ask for the same content told a different way, and nothing more."""
    title = str(video.get("title") or "").strip()
    channel_name = str((workflow_context or {}).get("managed_channel_name") or "").strip()
    duration = max(30, int(target_duration_seconds or 90))
    scene_count = max(6, min(48, -(-duration // 20)))
    parts = [
        f"Tiêu đề video nguồn: {title}",
        f"Mô tả nguồn: {str(video.get('description') or '').strip()[:1500]}",
        f"Thời lượng video nguồn: {int(source_duration_seconds or 0)} giây.",
    ]
    if not transcript_text or not transcript_text.strip():
        # Without the source there is nothing to be faithful to, and inventing
        # is the one thing this mode exists to prevent.
        raise WriterError(
            "Chế độ kể lại trung thành bắt buộc phải có transcript của video nguồn. "
            "Hãy chạy Whisper cho video này trước."
        )
    parts.append(
        "NỘI DUNG NGUỒN (đây là sự thật duy nhất, kể lại đúng chừng này, không hơn):\n"
        + _faithful_source_text(transcript_text)
    )
    direction = (creative_direction or "").strip()
    parts.append(
        "YÊU CẦU VỀ CÁCH KỂ: "
        + (direction if direction else
           "Kể lại mạch lạc, tự nhiên, dễ nghe; giọng dẫn chuyện ấm và rõ ràng.")
        + " Yêu cầu này chỉ áp dụng cho GIỌNG KỂ và CÁCH DIỄN ĐẠT — không được dùng nó "
          "để thêm, bớt hay đổi bất cứ nội dung nào."
    )
    parts.append(
        "TỰ KIỂM TRA trước khi trả lời: mọi tên riêng, con số, địa danh và mốc thời gian trong bài "
        "viết của bạn phải tìm được trong nội dung nguồn ở trên. Chi tiết nào không có ở đó thì bỏ đi."
    )
    parts.append(
        f"Quy tắc CTA: {'Nhắc đúng tên kênh là ' + channel_name + ' khi kêu gọi đăng ký.' if channel_name else 'Không có tên kênh cụ thể — tuyệt đối không bịa tên kênh; chỉ dùng lời kêu gọi chung chung.'}"
    )
    parts.append(
        f"Video đích dài khoảng {duration} giây. Chia thành {scene_count} cảnh, mỗi cảnh khoảng 15-25 giây. "
        f"Tổng scene_blueprints.duration_seconds phải nằm trong khoảng 10% của {duration}."
    )
    parts.append(
        "Mỗi scene_blueprints.narration là lời đọc thật: 2-5 câu hoàn chỉnh, kể tiếp đúng mạch của nguồn. "
        f"Viết đủ dài để lấp thời lượng cảnh ở tốc độ khoảng {VIETNAMESE_VOICE_TOKENS_PER_SECOND:.1f} "
        "âm tiết tiếng Việt mỗi giây.\n"
        "Hình của video này được CẮT TỪ CHÍNH VIDEO NGUỒN, không phải ảnh AI. Vì vậy mỗi visual_prompt "
        "hãy mô tả ĐOẠN NÀO CỦA VIDEO NGUỒN nên xuất hiện ở cảnh đó (nhìn thấy gì trên màn hình lúc ấy), "
        "chứ không phải mô tả một bức tranh cần vẽ. asset_type để là 'source_clip'.\n"
        "new_titles: giữ đúng chủ đề và nội dung của nguồn, chỉ đổi cách đặt câu chữ. "
        "new_story_concept: nói rõ đây là bản kể lại, và cách kể khác nguồn ở chỗ nào."
    )
    return "\n\n".join(parts)


def system_prompt_for(remake_mode: str) -> str:
    """Which brief the writer works under: invent a new video, or retell this one."""
    return _FAITHFUL_SYSTEM_PROMPT if remake_mode == FAITHFUL_RETELL_MODE else _SYSTEM_PROMPT


def _build_prompt(
    video: dict[str, Any],
    transcript_text: str | None,
    workflow_context: dict[str, Any] | None = None,
    creative_direction: str | None = None,
    remake_mode: str = "new_angle_same_topic",
    target_duration_seconds: int = 90,
    source_duration_seconds: int | None = None,
    research_context: dict[str, Any] | None = None,
    reference_analysis: dict[str, Any] | None = None,
) -> str:
    if remake_mode == FAITHFUL_RETELL_MODE:
        # Everything below asks for a new story: different examples, a
        # different animal, no reuse of the source's characters or plot. A
        # retelling wants the opposite, so it takes its own path rather than
        # trying to switch off those rules one by one.
        return _build_faithful_prompt(
            video,
            transcript_text,
            workflow_context=workflow_context,
            creative_direction=creative_direction,
            target_duration_seconds=target_duration_seconds,
            source_duration_seconds=source_duration_seconds,
        )
    title = str(video.get("title") or "").strip()
    description = str(video.get("description") or "").strip()
    tags = ", ".join(str(tag) for tag in (video.get("tags") or []))
    parts = [
        f"Tiêu đề gốc: {title}",
        f"Mô tả gốc: {description[:1500]}",
        f"Tags gốc: {tags}",
    ]
    parts.append(f"Source video duration: {int(source_duration_seconds or 0)} seconds.")
    channel_name = str((workflow_context or {}).get("managed_channel_name") or "").strip()
    if workflow_context:
        parts.append(
            "Destination channel workflow (style reference only; do not copy source content): "
            f"channel={channel_name or '(chưa đặt tên — xem quy tắc CTA bên dưới)'}; "
            f"reference={workflow_context.get('workflow_reference_title', '')}; "
            f"format={workflow_context.get('output_profile', '')}; "
            f"notes={str(workflow_context.get('workflow_notes', ''))[:1200]}"
        )
    parts.append(
        f"Quy tắc CTA/kênh (bắt buộc): {'Nhắc đúng tên kênh là ' + channel_name + ' khi kêu gọi đăng ký.' if channel_name else 'KHÔNG có tên kênh cụ thể cho video này — tuyệt đối không tự bịa hay đặt tên kênh nào (kể cả tên nghe hợp lý). CTA chỉ dùng lời kêu gọi chung chung như “nhấn đăng ký để xem thêm”, không nêu bất kỳ tên kênh nào.'}"
    )
    if reference_analysis:
        scene_map = reference_analysis.get("scene_map") if isinstance(reference_analysis.get("scene_map"), list) else []
        reference_beats = "\n".join(
            f"- Rhythm {index + 1}: {item.get('story_beat', '')} | pacing: {item.get('editing_pacing', '')}"
            for index, item in enumerate(scene_map[:12]) if isinstance(item, dict)
        )
        parts.append(
            "Reference brief produced by the analysis stage. Use its ABSTRACT pacing and escalation only; never copy events, names or dialogue:\n"
            f"Narrative formula: {reference_analysis.get('narrative_formula', [])}\n"
            f"Reference rhythm map:\n{reference_beats or 'No scene map available.'}\n"
            f"Visual style: {reference_analysis.get('visual_style', {})}\n"
            f"Remake guardrails: {reference_analysis.get('remake_guardrails', [])}"
        )
    direction = (creative_direction or "").strip()
    if not direction:
        direction = "Giữ chủ đề, loại nội dung và cách trình bày của video gốc; đổi góc nhìn, ví dụ và tình huống để tạo video mới."
    parts.append(f"Creative remake mode: {remake_mode}. User's new-video direction: {direction}")
    parts.append(
        "FORMAT LOCK (bắt buộc): Hãy suy ra format với bằng chứng từ transcript, tiêu đề và phân tích tham chiếu. "
        "Video giải thích/giáo dục phải vẫn là video giải thích/giáo dục: mở vấn đề, định nghĩa, cơ chế, "
        "ví dụ hoặc tình huống mới, so sánh, cảnh báo và tổng kết. Video hướng dẫn phải vẫn là hướng dẫn theo bước. "
        "Video truyện kể mới được dùng nhân vật và kịch tính. Không tự thêm châu báu, phép màu, làng cổ, nhân vật hư cấu "
        "hoặc bài học sáo rỗng nếu nguồn không phải truyện."
    )
    animal = source_animal(title)
    if animal:
        suggested = list((research_context or {}).get("suggested_target_animals") or [])
        target_hint = ", ".join(suggested) or "mèo, chó, gà hoặc vịt"
        parts.append(
            f"NON-NEGOTIABLE TOPIC RULE: The source is an animal-origin folktale about '{animal}'. "
            f"Create an original animal-origin folktale about ONE DIFFERENT animal (choose {target_hint} unless the user names one). "
            f"The new title and central transformation must clearly be about that chosen animal; never replace the animal theme with an unrelated object, merchant or generic deception story. "
            f"Do not reuse '{animal}' as the transformed animal or central protagonist."
        )
    if research_context:
        results = research_context.get("results") or []
        research_lines = [f"- {item.get('title', '')}: {item.get('snippet', '')}" for item in results if isinstance(item, dict)]
        parts.append(
            "Web discovery hints, used only to find broad folklore motifs. Do not retell, quote, copy names, scenes or wording from them; invent a new plot:\n"
            + ("\n".join(research_lines) if research_lines else "- No result available: use the suggested target animal and invent an original folklore arc.")
        )
    duration = max(30, min(1800, int(target_duration_seconds or 90)))
    target_words = math.ceil(duration * VIETNAMESE_VOICE_TOKENS_PER_SECOND)
    parts.append(
        f"Target final-video duration: {duration} seconds (about {target_words} Vietnamese spoken words at a clear natural pace). "
        "The total of scene_blueprints.duration_seconds must be within 10% of this target."
    )
    if transcript_text:
        parts.append(f"Transcript gốc (có thể bị cắt bớt):\n{transcript_text[:_MAX_TRANSCRIPT_CHARS]}")
    else:
        parts.append(
            "Chưa có transcript cho video này — chỉ dựa vào tiêu đề/mô tả/tags ở trên, "
            "và nêu rõ trong script_outline rằng đây là gợi ý cấu trúc chung."
        )
    parts.append(
        "Write as a senior YouTube editor who follows FORMAT LOCK, never as a generic storyteller. Preserve the source's density of useful information and presentation rhythm, but use original examples, explanations and visual illustrations. For educational explainers, use precise plain language, cause-and-effect, definitions, mechanisms, comparisons and practical takeaways. Do not pad with fantasy, dramatic fiction, vague morals or decorative wording. For fictional stories, use characters and plot only when the source is genuinely fictional. New titles must retain the source title's topic and structural template, but use clearly different wording rather than replacing just one word. Do not make summary a recap: summary must explain the NEW production concept only. Return: new titles, description, hashtags, "
        f"creative_direction, new_story_concept, style_application, a complete new_script, and scene_blueprints ({max(6, min(48, -(-duration // 20)))} scenes, approximately 15-25 seconds each). "
        "Each scene_blueprints.narration is the actual voiceover: write 2-5 complete, concrete spoken sentences with a clear subject, action, "
        "cause/effect and transition to the next scene. Do not use vague summaries, bullet points, labels or placeholders. "
        f"Use enough narration to naturally fill that scene duration at about {VIETNAMESE_VOICE_TOKENS_PER_SECOND:.1f} Vietnamese written tokens per second. "
        "Each visual_prompt must describe only original AI-generated imagery: subject, action, setting, camera, light, art style and motion; "
        "never request source footage. asset_type should normally be ai_scene."
    )
    return "\n\n".join(parts)


def _finalize(video: dict[str, Any], provider: str, parsed: dict[str, Any], used_transcript: bool) -> dict[str, Any]:
    return {
        "provider": provider,
        "source_type": "transcript" if used_transcript else "metadata",
        "title": str(video.get("title") or "").strip(),
        "summary": parsed.get("summary", ""),
        "key_ideas": parsed.get("key_ideas", []),
        "new_titles": parsed.get("new_titles", []),
        "new_description": parsed.get("new_description", ""),
        "hashtags": parsed.get("hashtags", []),
        "cta": parsed.get("cta", ""),
        "script_outline": parsed.get("script_outline", []),
        "creative_direction": parsed.get("creative_direction", ""),
        "new_story_concept": parsed.get("new_story_concept", ""),
        "style_application": parsed.get("style_application", []),
        "new_script": parsed.get("new_script", {}),
        "scene_blueprints": parsed.get("scene_blueprints", []),
    }


class ClaudeWriter:
    """Sinh nội dung sáng tạo (tiêu đề/mô tả/CTA/kịch bản) bằng Claude API."""

    provider = "anthropic_claude"

    def generate(self, video: dict[str, Any], transcript_text: str | None = None, workflow_context: dict[str, Any] | None = None, creative_direction: str | None = None, remake_mode: str = "new_angle_same_topic", target_duration_seconds: int = 90, source_duration_seconds: int | None = None, research_context: dict[str, Any] | None = None, reference_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
        parsed = call_claude_json(
            system_prompt_for(remake_mode), _build_prompt(video, transcript_text, workflow_context, creative_direction, remake_mode, target_duration_seconds, source_duration_seconds, research_context, reference_analysis), RESULT_SCHEMA, max_tokens=min(16000, max(5000, target_duration_seconds * 10))
        )
        return _finalize(video, self.provider, parsed, bool(transcript_text))


class OpenAiWriter:
    """Sinh nội dung sáng tạo (tiêu đề/mô tả/CTA/kịch bản) bằng OpenAI API."""

    provider = "openai_gpt"

    def generate(self, video: dict[str, Any], transcript_text: str | None = None, workflow_context: dict[str, Any] | None = None, creative_direction: str | None = None, remake_mode: str = "new_angle_same_topic", target_duration_seconds: int = 90, source_duration_seconds: int | None = None, research_context: dict[str, Any] | None = None, reference_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
        parsed = call_openai_json(
            system_prompt_for(remake_mode), _build_prompt(video, transcript_text, workflow_context, creative_direction, remake_mode, target_duration_seconds, source_duration_seconds, research_context, reference_analysis), RESULT_SCHEMA, max_tokens=min(16000, max(5000, target_duration_seconds * 10))
        )
        return _finalize(video, self.provider, parsed, bool(transcript_text))


class CodexWriter:
    """Sinh noi dung bang Codex CLI da dang nhap tren may local."""

    provider = "codex_cli"

    def generate(self, video: dict[str, Any], transcript_text: str | None = None, workflow_context: dict[str, Any] | None = None, creative_direction: str | None = None, remake_mode: str = "new_angle_same_topic", target_duration_seconds: int = 90, source_duration_seconds: int | None = None, research_context: dict[str, Any] | None = None, reference_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
        parsed = call_codex_json(
            system_prompt_for(remake_mode), _build_prompt(video, transcript_text, workflow_context, creative_direction, remake_mode, target_duration_seconds, source_duration_seconds, research_context, reference_analysis), RESULT_SCHEMA, max_tokens=min(16000, max(5000, target_duration_seconds * 10))
        )
        return _finalize(video, self.provider, parsed, bool(transcript_text))


class ClaudeCodeCliWriter:
    """Sinh noi dung bang Claude Code CLI da dang nhap (goi claude.ai), khong can ANTHROPIC_API_KEY."""

    provider = "claude_code_cli"

    def generate(self, video: dict[str, Any], transcript_text: str | None = None, workflow_context: dict[str, Any] | None = None, creative_direction: str | None = None, remake_mode: str = "new_angle_same_topic", target_duration_seconds: int = 90, source_duration_seconds: int | None = None, research_context: dict[str, Any] | None = None, reference_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
        parsed = call_claude_code_cli_json(
            system_prompt_for(remake_mode), _build_prompt(video, transcript_text, workflow_context, creative_direction, remake_mode, target_duration_seconds, source_duration_seconds, research_context, reference_analysis), RESULT_SCHEMA, max_tokens=min(16000, max(5000, target_duration_seconds * 10))
        )
        return _finalize(video, self.provider, parsed, bool(transcript_text))


class AntigravityWriter:
    """Sinh noi dung bang Antigravity CLI da dang nhap (tai khoan Google), khong can API key."""

    provider = "antigravity"

    def generate(self, video: dict[str, Any], transcript_text: str | None = None, workflow_context: dict[str, Any] | None = None, creative_direction: str | None = None, remake_mode: str = "new_angle_same_topic", target_duration_seconds: int = 90, source_duration_seconds: int | None = None, research_context: dict[str, Any] | None = None, reference_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
        parsed = call_antigravity_json(
            system_prompt_for(remake_mode), _build_prompt(video, transcript_text, workflow_context, creative_direction, remake_mode, target_duration_seconds, source_duration_seconds, research_context, reference_analysis), RESULT_SCHEMA, max_tokens=min(16000, max(5000, target_duration_seconds * 10))
        )
        return _finalize(video, self.provider, parsed, bool(transcript_text))


_WRITERS: dict[str, Any] = {}

AVAILABLE_WRITER_PROVIDERS = [
    ClaudeWriter.provider, OpenAiWriter.provider, CodexWriter.provider,
    ClaudeCodeCliWriter.provider, AntigravityWriter.provider,
]

SCRIPT_REVISION_SCHEMA = {
    "type": "object",
    "properties": {
        "script_title": {"type": "string"},
        "hook": {"type": "string"},
        "intro": {"type": "string"},
        "main_content": {"type": "string"},
        "cta": {"type": "string"},
    },
    "required": ["script_title", "hook", "intro", "main_content", "cta"],
    "additionalProperties": False,
}

_SCRIPT_REVISION_SYSTEM = (
    "Bạn là biên tập viên kịch bản YouTube. Hãy chỉnh sửa bản kịch bản hiện tại theo yêu cầu của người dùng, "
    "giữ lại thông tin đúng, bổ sung giá trị riêng, không sao chép nguyên văn nguồn. "
    "Không tự bịa hay đổi tên kênh trong CTA trừ khi người dùng nêu rõ tên kênh trong yêu cầu chỉnh sửa; "
    "nếu không có tên kênh cụ thể, CTA chỉ dùng lời kêu gọi chung chung, không nêu tên kênh nào. "
    "Trả về đúng JSON theo schema, không thêm giải thích ngoài JSON."
)


def revise_script(
    provider: str | None,
    video: dict[str, Any],
    script: dict[str, Any],
    instruction: str,
    transcript_text: str | None = None,
    workflow_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask the selected writer model to revise the current production script."""
    active_writer = resolve_writer(provider)
    current = "\n\n".join(
        [
            f"Tiêu đề: {script.get('script_title', '')}",
            f"Hook: {script.get('hook', '')}",
            f"Intro: {script.get('intro', '')}",
            f"Nội dung chính:\n{script.get('main_content', '')}",
            f"CTA: {script.get('cta', '')}",
        ]
    )
    source_context = f"Video nguồn: {video.get('title', '')}\n"
    if transcript_text:
        source_context += f"Transcript tham khảo:\n{transcript_text[:8000]}\n"
    if workflow_context:
        source_context += (
            "Destination workflow (style reference only; do not copy): "
            f"reference={workflow_context.get('workflow_reference_title', '')}; "
            f"format={workflow_context.get('output_profile', '')}; "
            f"notes={str(workflow_context.get('workflow_notes', ''))[:1200]}\n"
        )
    user_prompt = (
        f"{source_context}\nKịch bản hiện tại:\n{current}\n\n"
        f"Yêu cầu chỉnh sửa của người dùng:\n{instruction.strip()}\n\n"
        "Hãy trả về một bản kịch bản hoàn chỉnh gồm script_title, hook, intro, main_content và cta."
    )
    if active_writer.provider == ClaudeWriter.provider:
        parsed = call_claude_json(_SCRIPT_REVISION_SYSTEM, user_prompt, SCRIPT_REVISION_SCHEMA, max_tokens=4000)
    elif active_writer.provider == OpenAiWriter.provider:
        parsed = call_openai_json(_SCRIPT_REVISION_SYSTEM, user_prompt, SCRIPT_REVISION_SCHEMA, max_tokens=4000)
    elif active_writer.provider == ClaudeCodeCliWriter.provider:
        parsed = call_claude_code_cli_json(_SCRIPT_REVISION_SYSTEM, user_prompt, SCRIPT_REVISION_SCHEMA, max_tokens=4000)
    elif active_writer.provider == AntigravityWriter.provider:
        parsed = call_antigravity_json(_SCRIPT_REVISION_SYSTEM, user_prompt, SCRIPT_REVISION_SCHEMA, max_tokens=4000)
    else:
        parsed = call_codex_json(_SCRIPT_REVISION_SYSTEM, user_prompt, SCRIPT_REVISION_SCHEMA, max_tokens=4000)
    return {
        "provider": active_writer.provider,
        "script_title": str(parsed.get("script_title") or script.get("script_title") or "").strip(),
        "hook": str(parsed.get("hook") or "").strip(),
        "intro": str(parsed.get("intro") or "").strip(),
        "main_content": str(parsed.get("main_content") or "").strip(),
        "cta": str(parsed.get("cta") or "").strip(),
    }


def resolve_writer(provider: str | None):
    """Return a writer instance. AI Writer needs an LLM — there is no free/local option.

    When provider is not specified, prefer whichever provider has an API key configured.
    """
    name = provider
    if not name:
        anthropic_key, _ = settings.anthropic_config()
        openai_key, _ = settings.openai_config()
        if anthropic_key:
            name = ClaudeWriter.provider
        elif openai_key:
            name = OpenAiWriter.provider
        elif codex_cli_status().get("logged_in"):
            name = CodexWriter.provider
        elif claude_code_cli_status().get("logged_in"):
            name = ClaudeCodeCliWriter.provider
        elif antigravity_cli_status().get("logged_in"):
            name = AntigravityWriter.provider
        else:
            raise WriterError(
                "AI Writer cần cấu hình ANTHROPIC_API_KEY/OPENAI_API_KEY, hoặc đăng nhập "
                "Codex CLI/Claude Code CLI/Antigravity CLI trên máy."
            )

    if name not in _WRITERS:
        if name == ClaudeWriter.provider:
            _WRITERS[name] = ClaudeWriter()
        elif name == OpenAiWriter.provider:
            _WRITERS[name] = OpenAiWriter()
        elif name == CodexWriter.provider:
            _WRITERS[name] = CodexWriter()
        elif name == ClaudeCodeCliWriter.provider:
            _WRITERS[name] = ClaudeCodeCliWriter()
        elif name == AntigravityWriter.provider:
            _WRITERS[name] = AntigravityWriter()
        else:
            raise WriterError(f"Provider không được hỗ trợ cho AI Writer: {name}")
    return _WRITERS[name]
