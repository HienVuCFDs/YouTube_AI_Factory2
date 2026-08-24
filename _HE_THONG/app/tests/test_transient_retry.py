"""A briefly overloaded provider is not a broken one."""

from __future__ import annotations

import pytest

from youtube_monitor import llm_client
from youtube_monitor.claude_code_bridge import ClaudeCodeBridgeError
from youtube_monitor.llm_client import LlmError, _is_transient, _readable

# What Claude Code actually returns: a page of session accounting with the
# cause buried in "result".
OVERLOADED = (
    'Claude Code CLI that bai: {"is_error":true,"duration_api_ms":1948,"num_turns":1,'
    '"stop_reason":"stop_sequence","total_cost_usd":0.003605,'
    '"usage":{"output_tokens":0,"input_tokens":0},'
    '"result":"API Error: 529 Overloaded. This is a server-side issue, usually temporary '
    '— try again in a moment.","permission_denials":[]}'
)


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backoff is real in production and pointless in a test."""
    monkeypatch.setattr(llm_client.time, "sleep", lambda _seconds: None)


def test_the_real_cause_is_pulled_out_of_the_json_blob() -> None:
    """This is why the failure was invisible: the message was a wall of token
    counts with one useful sentence inside it."""
    assert _readable(OVERLOADED).startswith("API Error: 529 Overloaded")
    assert "total_cost_usd" not in _readable(OVERLOADED)


@pytest.mark.parametrize("message", [
    OVERLOADED,
    "API Error: 503 Service Unavailable",
    "502 Bad Gateway",
    "Connection reset by peer",
    "temporarily unavailable",
])
def test_a_temporary_failure_is_worth_asking_again(message: str) -> None:
    assert _is_transient(message)


@pytest.mark.parametrize("message", [
    "You've hit your usage limit. Try again at Aug 27th, 2026 9:43 PM.",
    "Individual quota reached",
    "khong parse duoc JSON",
    "Khong tim thay Claude CLI",
])
def test_a_permanent_failure_is_not_retried(message: str) -> None:
    """Retrying a quota just spends minutes being refused three more times."""
    assert not _is_transient(message)


def test_an_overloaded_call_is_retried_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """The analysis reads a long transcript in several sequential passes; one
    529 anywhere in that run used to throw away every pass before it."""
    attempts = {"n": 0}

    def flaky(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ClaudeCodeBridgeError(OVERLOADED)
        return {"ok": True}

    monkeypatch.setattr(llm_client, "_call_claude_code_json", flaky)

    assert llm_client.call_claude_code_cli_json("s", "u", {}) == {"ok": True}
    assert attempts["n"] == 3


def test_it_gives_up_rather_than_retrying_forever(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"n": 0}

    def always_overloaded(*args, **kwargs):
        attempts["n"] += 1
        raise ClaudeCodeBridgeError(OVERLOADED)

    monkeypatch.setattr(llm_client, "_call_claude_code_json", always_overloaded)

    with pytest.raises(LlmError, match="529 Overloaded"):
        llm_client.call_claude_code_cli_json("s", "u", {})

    assert attempts["n"] == 4, "mot lan dau + ba lan thu lai"


def test_a_usage_limit_fails_on_the_first_try(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"n": 0}

    def out_of_quota(*args, **kwargs):
        attempts["n"] += 1
        raise ClaudeCodeBridgeError("You've hit your usage limit.")

    monkeypatch.setattr(llm_client, "_call_claude_code_json", out_of_quota)

    with pytest.raises(LlmError):
        llm_client.call_claude_code_cli_json("s", "u", {})

    assert attempts["n"] == 1, "het han muc thi thu lai cung vo ich"


def test_a_working_call_is_not_delayed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client, "_call_claude_code_json", lambda *a, **k: {"ok": True})

    assert llm_client.call_claude_code_cli_json("s", "u", {}) == {"ok": True}


def test_an_overload_is_not_recorded_as_a_usage_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """A red banner saying the model is out of quota would be wrong, and would
    stay on screen long after the provider recovered."""
    from youtube_monitor import usage_limits

    assert not usage_limits.is_usage_limit(OVERLOADED)
