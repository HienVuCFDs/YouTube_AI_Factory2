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

    assert "TỪNG LƯỢT NÓI" in prompt
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

    pieces = _chunks(body)

    assert len(pieces) > 1
    assert "Doan so 0." in pieces[0]
    assert "Doan so 399." in pieces[-1]
    rejoined = "\n".join(pieces)
    assert all(f"Doan so {index}." in rejoined for index in range(400)), "khong duoc mat dong nao"


def test_a_wall_of_text_still_splits_on_sentences() -> None:
    body = " ".join(f"Cau so {index}." for index in range(500))

    pieces = _chunks(body)

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


def test_a_chunk_is_capped_by_how_many_lines_it_holds() -> None:
    """Every line comes back attributed and translated, so the answer is larger
    than the question. 511 lines in one call ran out of output budget."""
    body = "\n".join(f"[{index}s] a" for index in range(500))

    pieces = _chunks(body)

    assert all(len(piece.splitlines()) <= 90 for piece in pieces)
    assert len(pieces) >= 6


def test_a_line_is_never_cut_in_half() -> None:
    body = "\n".join(f"[{index}s] mot luot noi day du so {index}" for index in range(300))

    for piece in _chunks(body):
        for line in piece.splitlines():
            assert line.startswith("["), f"dong bi cat: {line!r}"


def test_the_brief_says_the_transcript_has_no_speaker_labels() -> None:
    """A real ASR transcript names nobody; without saying so the model either
    guesses confidently or calls everything narration."""
    prompt = _prompt(VIDEO, "[3s] anh noi gi", "vi")

    assert "KHÔNG có tên người nói" in prompt
    assert "Không rõ" in prompt


def test_dialogue_must_be_translated_not_left_in_the_source_language() -> None:
    """A model treats a quote as something to reproduce verbatim, which leaves
    Chinese lines sitting in a Vietnamese brief."""
    from youtube_monitor import languages

    assert "LOI THOAI cung phai DICH" in languages.instruction("vi")


def test_later_parts_are_told_who_has_already_been_named() -> None:
    """Read on its own, each part renames the same person - "nhan vat chinh",
    then "trang si", then his actual name - and one character becomes three."""
    prompt = _prompt(
        VIDEO, "[3s] a", "vi", part=2, total_parts=3,
        known_characters=[{"name": "Tào Tháo", "role": "chủ công"}],
    )

    assert "NHÂN VẬT ĐÃ ĐẶT TÊN Ở CÁC PHẦN TRƯỚC" in prompt
    assert "Tào Tháo (chủ công)" in prompt


def test_the_first_part_is_not_given_a_cast() -> None:
    prompt = _prompt(VIDEO, "[3s] a", "vi", part=1, total_parts=3, known_characters=[])

    assert "NHÂN VẬT ĐÃ ĐẶT TÊN" not in prompt


def test_a_part_summary_is_not_labelled_with_its_number() -> None:
    """The joined summary otherwise reads "PHAN 1/6." before the story starts."""
    prompt = _prompt(VIDEO, "[3s] a", "vi", part=1, total_parts=6)

    assert "KHÔNG ghi thêm nhãn 'PHẦN x/y'" in prompt


def test_the_cast_grows_across_parts_instead_of_restarting(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    casts = [
        [{"name": "Tào Tháo", "role": "chủ công"}],
        [{"name": "Tào Tháo", "role": "chủ công"}, {"name": "Điển Vi", "role": "mãnh tướng"}],
    ]

    def fake(system_prompt, user_prompt, schema, max_tokens=0):
        seen.append(user_prompt)
        return _reading(characters=casts[min(len(seen) - 1, len(casts) - 1)])

    monkeypatch.setattr(reference_analyzer, "call_claude_code_cli_json", fake)
    body = "\n".join(f"[{index}s] luot {index}" for index in range(200))

    result = reference_analyzer.analyze_reference(VIDEO, body, "claude_code_cli")

    assert "Tào Tháo" in seen[1], "phan sau phai biet ten da dat o phan truoc"
    assert [person["name"] for person in result["characters"]] == ["Tào Tháo", "Điển Vi"]
