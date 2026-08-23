"""The analysis records the source: the whole story, and every line spoken."""

from __future__ import annotations

import pytest

from youtube_monitor import reference_analyzer
from youtube_monitor.reference_analyzer import _SYSTEM_PROMPT, _chunks, _merge, _prompt

SOURCE = "Nguoi dan: Ngay xua co hai anh em ho Cao. Cha noi: Cac con phai thuong nhau."
VIDEO = {"title": "Su tich trau cau", "description": ""}


def _reading(**overrides):
    base = {
        "content_summary": "x", "characters": [], "dialogue": [],
        "scene_map": [], "visual_style": "", "limitations": [],
    }
    base.update(overrides)
    return base


# --- what the brief asks for ---------------------------------------------


def test_the_brief_asks_for_every_line_of_dialogue() -> None:
    """Dialogue is what a retelling loses first, so it is asked for by name."""
    prompt = _prompt(VIDEO, SOURCE, "vi")

    assert "TỪNG CÂU THOẠI" in prompt
    assert "Không được rút gọn" in prompt or "không được rút gọn" in prompt.lower()


def test_narration_is_attributed_rather_than_dropped() -> None:
    assert "Người dẫn" in _prompt(VIDEO, SOURCE, "vi")


def test_the_brief_asks_for_the_whole_story_not_a_summary() -> None:
    prompt = _prompt(VIDEO, SOURCE, "vi")

    assert "TOÀN BỘ câu chuyện" in prompt


def test_the_brief_no_longer_asks_for_a_production_recipe() -> None:
    """It used to return abstract beats and a style recipe - true of how the
    source was made, useless for retelling what it says."""
    prompt = _prompt(VIDEO, SOURCE, "vi")

    for gone in ("narrative_formula", "style_recipe", "editing_pacing", "remake_guardrails"):
        assert gone not in prompt, f"loi cu con sot: {gone}"


def test_the_brief_rules_on_nothing() -> None:
    assert "không phải bạn quyết" in _SYSTEM_PROMPT or "settled later" in _SYSTEM_PROMPT
    assert "Never invent" in _SYSTEM_PROMPT


def test_a_part_of_a_long_transcript_says_so() -> None:
    """Otherwise a chunk is read as the whole video and summarised as such."""
    prompt = _prompt(VIDEO, SOURCE, "vi", part=2, total_parts=3)

    assert "PHẦN 2/3" in prompt
    assert "đừng đoán phần chưa đọc tới" in prompt


# --- reading a long transcript -------------------------------------------


def test_a_short_transcript_is_one_piece() -> None:
    assert _chunks("mot doan ngan") == ["mot doan ngan"]


def test_an_empty_transcript_gives_no_pieces() -> None:
    assert _chunks("") == []


def test_a_long_transcript_is_split_without_losing_anything() -> None:
    """Truncating instead would drop the ending, which is the part that matters."""
    paragraphs = [f"Doan so {index}." for index in range(400)]
    body = "\n\n".join(paragraphs)

    pieces = _chunks(body, size=2000)

    assert len(pieces) > 1
    assert "Doan so 0." in pieces[0]
    assert "Doan so 399." in pieces[-1]
    assert sum(len(piece) for piece in pieces) >= len(body) - 4 * len(pieces)


def test_a_wall_of_text_still_splits_on_sentences() -> None:
    body = " ".join(f"Cau so {index}." for index in range(500))

    pieces = _chunks(body, size=1500)

    assert len(pieces) > 1
    assert not any(piece.endswith("Cau so") for piece in pieces), "khong duoc cat giua cau"


# --- merging the pieces ---------------------------------------------------


def test_dialogue_from_every_piece_survives_in_order() -> None:
    merged = _merge([
        _reading(dialogue=[{"order": 1, "speaker": "Cha", "line": "mot"}]),
        _reading(dialogue=[{"order": 1, "speaker": "Tan", "line": "hai"}]),
    ])

    assert [line["line"] for line in merged["dialogue"]] == ["mot", "hai"]
    assert [line["order"] for line in merged["dialogue"]] == [1, 2], "phai danh so lai lien tuc"


def test_a_character_introduced_twice_is_listed_once() -> None:
    """Each piece is read on its own, so the cast is reintroduced every time."""
    merged = _merge([
        _reading(characters=[{"name": "Tan", "role": "nguoi anh"}]),
        _reading(characters=[{"name": "TAN", "role": "nguoi anh"}, {"name": "Lang", "role": "nguoi em"}]),
    ])

    assert [person["name"] for person in merged["characters"]] == ["Tan", "Lang"]


def test_summaries_are_joined_rather_than_the_last_one_winning() -> None:
    merged = _merge([_reading(content_summary="phan dau"), _reading(content_summary="phan cuoi")])

    assert "phan dau" in merged["content_summary"]
    assert "phan cuoi" in merged["content_summary"]


def test_the_same_limitation_is_not_repeated_per_piece() -> None:
    merged = _merge([
        _reading(limitations=["khong co khung hinh"]),
        _reading(limitations=["khong co khung hinh", "khong ro nguoi noi"]),
    ])

    assert merged["limitations"] == ["khong co khung hinh", "khong ro nguoi noi"]


def test_a_missing_speaker_becomes_an_explicit_unknown() -> None:
    """An empty attribution reads as narration; naming the gap does not."""
    merged = _merge([_reading(dialogue=[{"order": 1, "line": "ai do noi"}])])

    assert merged["dialogue"][0]["speaker"] == "Không rõ"


# --- the run --------------------------------------------------------------


def test_a_long_source_is_read_in_several_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake(system_prompt, user_prompt, schema, max_tokens=0):
        calls.append(user_prompt)
        return _reading(dialogue=[{"order": 1, "speaker": "Cha", "line": f"cau {len(calls)}"}])

    monkeypatch.setattr(reference_analyzer, "call_claude_code_cli_json", fake)
    body = "\n\n".join(f"Doan so {index}." for index in range(4000))

    result = reference_analyzer.analyze_reference(VIDEO, body, "claude_code_cli")

    assert len(calls) > 1
    assert result["transcript_parts_read"] == len(calls)
    assert len(result["dialogue"]) == len(calls), "moi phan phai gop het vao"


def test_a_source_without_a_transcript_is_still_read_once(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        reference_analyzer, "call_claude_code_cli_json",
        lambda system_prompt, user_prompt, schema, max_tokens=0: seen.append(user_prompt) or _reading(),
    )

    result = reference_analyzer.analyze_reference(VIDEO, None, "claude_code_cli")

    assert result["source_type"] == "metadata"
    assert result["transcript_parts_read"] == 0
    assert "Đừng giả vờ đã xem video" in seen[0]
