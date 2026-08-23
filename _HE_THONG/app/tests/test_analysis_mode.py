"""The analysis step must not tell the writer to do the opposite of its job."""

from __future__ import annotations

import pytest

from youtube_monitor import reference_analyzer
from youtube_monitor.reference_analyzer import FAITHFUL_MODE, _prompt

SOURCE = "Ngay xua co hai anh em ho Cao, nguoi anh ten Tan, nguoi em ten Lang."
VIDEO = {"title": "Su tich trau cau", "description": ""}


def test_the_retelling_brief_asks_for_what_to_keep() -> None:
    """remake_guardrails carries the opposite meaning in each mode, so the
    instruction has to be explicit about which one is wanted."""
    prompt = _prompt(VIDEO, SOURCE, "vi", FAITHFUL_MODE)

    assert "MUST BE KEPT EXACTLY" in prompt
    assert "never as a change to make" in prompt


def test_the_retelling_brief_drops_every_instruction_to_change_the_source() -> None:
    """This is what reached the screen: rules to change the setting and the
    characters, shown on a workflow whose whole point is keeping them."""
    prompt = _prompt(VIDEO, SOURCE, "vi", FAITHFUL_MODE)

    for remake_rule in ("an original story", "non-identical style recipe", "abstract beats"):
        assert remake_rule not in prompt, f"loi remake con sot: {remake_rule}"


def test_the_remake_brief_is_unchanged() -> None:
    prompt = _prompt(VIDEO, SOURCE, "vi", "remake")

    assert "remake_guardrails that enforce an original story" in prompt
    assert "MUST BE KEPT EXACTLY" not in prompt


def test_the_default_mode_stays_remake() -> None:
    """WF Content callers pass no mode and must behave exactly as before."""
    assert _prompt(VIDEO, SOURCE, "vi") == _prompt(VIDEO, SOURCE, "vi", "remake")


def test_each_mode_gets_its_own_system_brief(monkeypatch: pytest.MonkeyPatch) -> None:
    """The system prompt tells the model never to copy; a retelling must not
    be given that instruction."""
    seen: dict[str, str] = {}

    def capture(system_prompt, user_prompt, schema, max_tokens=0):
        seen["system"] = system_prompt
        return {
            "content_summary": "x", "narrative_formula": [], "scene_map": [],
            "visual_style": {}, "pacing": "x", "remake_guardrails": [], "limitations": [],
        }

    monkeypatch.setattr(reference_analyzer, "call_claude_code_cli_json", capture)

    reference_analyzer.analyze_reference(VIDEO, SOURCE, "claude_code_cli", mode=FAITHFUL_MODE)
    faithful = seen["system"]
    reference_analyzer.analyze_reference(VIDEO, SOURCE, "claude_code_cli", mode="remake")
    remake = seen["system"]

    assert "RETOLD, not remade" in faithful
    assert "never reproduce dialogue" not in faithful
    assert "never reproduce dialogue" in remake


def test_the_mode_travels_back_so_the_screen_can_label_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same key means "keep" or "change" depending on mode; a heading that
    said the wrong one would be worse than none."""
    monkeypatch.setattr(
        reference_analyzer, "call_claude_code_cli_json",
        lambda *a, **k: {
            "content_summary": "x", "narrative_formula": [], "scene_map": [],
            "visual_style": {}, "pacing": "x", "remake_guardrails": [], "limitations": [],
        },
    )

    result = reference_analyzer.analyze_reference(VIDEO, SOURCE, "claude_code_cli", mode=FAITHFUL_MODE)

    assert result["mode"] == FAITHFUL_MODE
