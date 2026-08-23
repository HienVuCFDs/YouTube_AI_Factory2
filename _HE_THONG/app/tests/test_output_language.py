"""Choosing the language the AI analyses and writes in."""

from __future__ import annotations

import pytest

from youtube_monitor import languages
from youtube_monitor.reference_analyzer import _prompt as reference_prompt
from youtube_monitor.writer import (
    FAITHFUL_RETELL_MODE,
    _build_prompt,
    validate_voiceover_plan,
)

SOURCE = "Ngay xua co hai anh em ho Cao, nguoi anh ten Tan, nguoi em ten Lang."
VIDEO = {"title": "Su tich trau cau", "description": ""}


def _script(words: int, seconds: int) -> dict:
    """A storyboard with a known word count and running time."""
    scenes = max(1, seconds // 20)
    return {"scene_blueprints": [{
        "order": index + 1,
        "section": "x",
        "narration": "word " * (words // scenes),
        "visual_prompt": "x",
        "asset_type": "ai_scene",
        "duration_seconds": seconds // scenes,
    } for index in range(scenes)]}


# --- danh muc ngon ngu ----------------------------------------------------


def test_an_unknown_code_falls_back_rather_than_failing() -> None:
    """A stale value in a saved session must not stop a script being written."""
    assert languages.resolve("klingon")["label"] == languages.LANGUAGES["vi"]["label"]
    assert languages.resolve(None)["label"] == languages.LANGUAGES["vi"]["label"]


def test_every_language_carries_a_speaking_rate() -> None:
    """The rate is what sizes a script; a language without one would silently
    reuse Vietnamese pacing."""
    for code, record in languages.LANGUAGES.items():
        assert record["tokens_per_second"] > 0, code
        assert 0 < record["min_tokens_per_second"] <= record["tokens_per_second"], code


# --- prompt viet kich ban -------------------------------------------------


@pytest.mark.parametrize("code,expected", [("vi", "Vietnamese"), ("en", "English"), ("ja", "Japanese")])
def test_the_writing_brief_names_the_output_language(code: str, expected: str) -> None:
    prompt = _build_prompt(VIDEO, SOURCE, remake_mode="new_angle_same_topic", output_language=code)

    assert "NGON NGU DAU RA" in prompt
    assert expected in prompt


def test_the_retelling_brief_names_it_too() -> None:
    """Retelling has its own prompt path, which is easy to leave behind."""
    prompt = _build_prompt(VIDEO, SOURCE, remake_mode=FAITHFUL_RETELL_MODE, output_language="en")

    assert "English" in prompt.split("NGON NGU DAU RA")[1][:120]


def test_the_word_target_scales_with_the_language() -> None:
    """An English script sized at the Vietnamese rate runs about a quarter long."""
    def target(code: str) -> int:
        prompt = _build_prompt(VIDEO, SOURCE, remake_mode="new_angle_same_topic",
                               target_duration_seconds=300, output_language=code)
        line = next(line for line in prompt.splitlines() if "Target final-video duration" in line)
        return int(line.split("about ")[1].split(" ")[0])

    assert target("vi") == 960
    assert target("en") == 750
    assert target("vi") > target("en"), "tieng Viet dem theo am tiet nen nhieu token hon"


# --- canh bao do dai ------------------------------------------------------


def test_the_same_script_is_short_in_vietnamese_and_fine_in_english() -> None:
    """The whole reason the rate travels with the language."""
    script = _script(words=750, seconds=300)

    vietnamese = [w for w in validate_voiceover_plan(script, 300, "vi") if "Lời dẫn có" in w]
    english = [w for w in validate_voiceover_plan(script, 300, "en") if "Lời dẫn có" in w]

    assert vietnamese, "750 tu la ngan cho 300 giay tieng Viet"
    assert not english, "750 tu la du cho 300 giay tieng Anh"


def test_the_default_stays_vietnamese() -> None:
    """Existing callers pass no language and must behave exactly as before."""
    script = _script(words=750, seconds=300)

    assert validate_voiceover_plan(script, 300) == validate_voiceover_plan(script, 300, "vi")


# --- prompt phan tich -----------------------------------------------------


@pytest.mark.parametrize("code,expected", [("vi", "Vietnamese"), ("en", "English")])
def test_the_analysis_brief_names_the_output_language(code: str, expected: str) -> None:
    prompt = reference_prompt(VIDEO, SOURCE, code)

    assert expected in prompt.split("NGON NGU DAU RA")[1][:120]


def test_the_analysis_no_longer_hard_codes_vietnamese() -> None:
    """It used to end with "Write all output in Vietnamese" regardless."""
    prompt = reference_prompt(VIDEO, SOURCE, "en")

    assert "Write all output in Vietnamese" not in prompt
