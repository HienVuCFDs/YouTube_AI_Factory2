"""Reading Antigravity's answer out of the envelope it actually returns."""

from __future__ import annotations

import json

import pytest

from youtube_monitor import reference_analyzer
from youtube_monitor.antigravity_bridge import AntigravityBridgeError, _parse_json_output
from youtube_monitor.reference_analyzer import ReferenceAnalysisError, _is_empty

# Captured from a live run. The answer is under structured_output and inside
# response - never under "result", which is what the old parser looked for.
LIVE_ENVELOPE = (
    '{"conversation_id":"192a7cdc","status":"SUCCESS",'
    '"response":"```json\\n{\\n  \\"answer\\": \\"ok\\"\\n}\\n```\\n",'
    '"duration_seconds":7.38,"num_turns":2,'
    '"structured_output":{"answer":"{\\"answer\\": \\"ok\\"}"},'
    '"usage":{"total_tokens":22717}}'
)


def _envelope(**overrides) -> str:
    base = {"conversation_id": "x", "status": "SUCCESS", "response": "", "structured_output": {}}
    base.update(overrides)
    return json.dumps(base, ensure_ascii=False)


def test_the_answer_is_found_in_the_live_envelope() -> None:
    """The old parser looked for "result", found nothing, and returned the
    envelope itself - so every schema field was missing."""
    assert _parse_json_output(LIVE_ENVELOPE) == {"answer": "ok"}


def test_the_envelope_is_never_returned_as_the_answer() -> None:
    parsed = _parse_json_output(LIVE_ENVELOPE)

    for envelope_key in ("conversation_id", "status", "usage", "structured_output"):
        assert envelope_key not in parsed


def test_a_double_encoded_field_is_unwrapped() -> None:
    """Live, it returned {"answer": "{\\"answer\\": \\"ok\\"}"} - the object
    encoded again as the value of its own key."""
    blob = _envelope(structured_output={"answer": '{"answer": "ok"}'})

    assert _parse_json_output(blob) == {"answer": "ok"}


def test_a_real_schema_comes_back_whole() -> None:
    answer = {
        "content_summary": "Cau chuyen",
        "characters": [{"name": "Tan", "role": "anh"}],
        "dialogue": [{"order": 1, "speaker": "Cha", "line": "Thuong nhau"}],
        "scene_map": [], "limitations": [],
    }
    blob = _envelope(response="```json\n" + json.dumps(answer, ensure_ascii=False) + "\n```")

    parsed = _parse_json_output(blob)

    assert parsed["content_summary"] == "Cau chuyen"
    assert parsed["dialogue"][0]["speaker"] == "Cha"


def test_structured_output_is_used_when_the_response_has_no_json() -> None:
    blob = _envelope(response="Da xong.", structured_output={"content_summary": "Cau chuyen"})

    assert _parse_json_output(blob)["content_summary"] == "Cau chuyen"


def test_a_reported_failure_is_raised_rather_than_parsed() -> None:
    with pytest.raises(AntigravityBridgeError, match="FAILED"):
        _parse_json_output(_envelope(status="FAILED", response="het phien"))


def test_an_envelope_with_no_answer_is_an_error() -> None:
    """Returning the envelope here is what stored an empty analysis as a success."""
    with pytest.raises(AntigravityBridgeError, match="khong tim thay ket qua"):
        _parse_json_output(_envelope())


def test_nothing_at_all_is_an_error() -> None:
    with pytest.raises(AntigravityBridgeError):
        _parse_json_output("")


def test_a_bare_answer_without_an_envelope_still_parses() -> None:
    assert _parse_json_output('{"answer": "ok"}') == {"answer": "ok"}


def test_braces_inside_strings_do_not_confuse_the_scan() -> None:
    answer = {"content_summary": "Anh ta noi { xong roi } va di ra"}
    blob = _envelope(response="```json\n" + json.dumps(answer, ensure_ascii=False) + "\n```")

    assert _parse_json_output(blob)["content_summary"] == "Anh ta noi { xong roi } va di ra"


# --- the guard that would have caught it anyway ---------------------------


def test_a_reading_with_nothing_in_it_is_recognised_as_empty() -> None:
    assert _is_empty({"content_summary": "", "characters": [], "dialogue": [], "scene_map": []})
    assert _is_empty({})


def test_a_reading_with_any_content_is_not_empty() -> None:
    assert not _is_empty({"dialogue": [{"order": 1, "speaker": "Cha", "line": "x"}]})
    assert not _is_empty({"content_summary": "co noi dung"})


def test_an_empty_analysis_is_refused_instead_of_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Five parts ran and every field came back missing, and it was shown as
    finished. A provider returning a well-formed empty object is not a success."""
    monkeypatch.setattr(
        reference_analyzer, "call_antigravity_json",
        lambda *a, **k: {"content_summary": "", "characters": [], "dialogue": [],
                         "scene_map": [], "limitations": []},
    )

    with pytest.raises(ReferenceAnalysisError, match="khong tra ve noi dung nao"):
        reference_analyzer.analyze_reference(
            {"title": "x", "description": ""}, "[0s] mot dong", "antigravity"
        )
