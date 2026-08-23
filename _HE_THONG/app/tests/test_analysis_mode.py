"""The analysis brief must never tell anyone to change the source's content."""

from __future__ import annotations

import pytest

from youtube_monitor import reference_analyzer
from youtube_monitor.reference_analyzer import _SYSTEM_PROMPT, _prompt

SOURCE = "Nam 938, Ngo Quyen danh tan quan Nam Han tren song Bach Dang."
VIDEO = {"title": "Tran Bach Dang nam 938", "description": ""}


def test_the_brief_asks_for_facts_to_keep_and_presentation_to_change() -> None:
    """One list mixing both is how "doi boi canh goc re" ended up reading as
    an instruction rather than a warning."""
    prompt = _prompt(VIDEO, SOURCE, "vi")

    assert "'GIU:'" in prompt and "'DOI:'" in prompt
    assert "must survive unchanged" in prompt


def test_content_is_explicitly_out_of_bounds_for_the_change_list() -> None:
    prompt = _prompt(VIDEO, SOURCE, "vi")

    assert "Never write a 'DOI:' line about a fact, a character, a setting, a motive or an outcome" in prompt


def test_the_brief_no_longer_asks_for_an_original_story() -> None:
    """These are the exact instructions that reached the screen and demanded a
    changed setting, a swapped motive and a different field of knowledge."""
    prompt = _prompt(VIDEO, SOURCE, "vi")

    for gone in ("an original story", "abstract beats", "non-identical style recipe"):
        assert gone not in prompt, f"loi cu con sot: {gone}"


def test_the_system_brief_forbids_changing_content() -> None:
    assert "CONTENT is not yours to change" in _SYSTEM_PROMPT
    assert "must survive into the new video" in _SYSTEM_PROMPT


def test_the_system_brief_names_history_and_folklore_directly() -> None:
    """The failure was worst exactly there, so the rule says so out loud."""
    assert "folklore, history and news are not" in _SYSTEM_PROMPT
    assert "not an original work, it is a wrong one" in _SYSTEM_PROMPT


def test_the_old_instruction_to_produce_an_original_video_is_gone() -> None:
    for gone in ("ORIGINAL new video", "never reproduce dialogue"):
        assert gone not in _SYSTEM_PROMPT, f"loi cu con sot: {gone}"


def test_there_is_one_brief_for_both_workflows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two briefs that both preserve content only invite picking the wrong one."""
    seen: list[str] = []

    def capture(system_prompt, user_prompt, schema, max_tokens=0):
        seen.append(system_prompt)
        return {
            "content_summary": "x", "narrative_formula": [], "scene_map": [],
            "visual_style": {}, "pacing": "x", "remake_guardrails": [], "limitations": [],
        }

    monkeypatch.setattr(reference_analyzer, "call_claude_code_cli_json", capture)

    reference_analyzer.analyze_reference(VIDEO, SOURCE, "claude_code_cli")
    reference_analyzer.analyze_reference(VIDEO, SOURCE, "claude_code_cli", mode="anything")

    assert seen[0] == seen[1] == _SYSTEM_PROMPT
