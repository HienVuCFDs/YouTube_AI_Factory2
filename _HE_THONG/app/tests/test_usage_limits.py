"""Telling a quota outage apart from a broken provider, and saying so."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from youtube_monitor import llm_client, usage_limits
from youtube_monitor.codex_bridge import CodexBridgeError
from youtube_monitor.main import database, list_usage_limits

CODEX_LIMIT = (
    "Codex CLI that bai: OpenAI Codex v0.149.0\n"
    "--------\n"
    "ERROR: You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), "
    "visit https://chatgpt.com/codex/settings/usage to purchase more credits or "
    "try again at Aug 27th, 2026 9:43 PM."
)


# --- nhan dien ------------------------------------------------------------


@pytest.mark.parametrize("message", [
    CODEX_LIMIT,
    "Tai khoan Antigravity da het quota su dung (Individual quota reached).",
    "Gemini: {'code': 429, 'message': 'You exceeded your current quota'}",
    "RESOURCE_EXHAUSTED",
    "Khong du tin dung de tao video",
    "Không đủ tín dụng",
    "Hết hạn mức Flow",
    "You've hit your weekly limit · resets 6pm (Asia/Bangkok)",
])
def test_a_quota_message_is_recognised(message: str) -> None:
    assert usage_limits.is_usage_limit(message)


@pytest.mark.parametrize("message", [
    "Codex CLI that bai: khong parse duoc JSON",
    "Khong tim thay FFmpeg",
    "Timeout sau 600s",
    "",
])
def test_an_ordinary_failure_is_not_mistaken_for_a_quota(message: str) -> None:
    """Misreading a crash as an outage would hide a real bug behind a banner."""
    assert not usage_limits.is_usage_limit(message)


def test_the_reset_date_is_read_from_the_message() -> None:
    reset = usage_limits.parse_reset_at(CODEX_LIMIT)

    assert reset is not None
    assert (reset.astimezone().month, reset.astimezone().day) == (8, 27)
    assert reset.astimezone().hour == 21, "9:43 PM phai la 21 gio"


def test_a_relative_reset_is_read_too() -> None:
    now = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)

    reset = usage_limits.parse_reset_at("Individual quota reached. Reset in 4 hours", now=now)

    assert reset == now + timedelta(hours=4)


def test_the_plural_reset_wording_is_read_as_well() -> None:
    """Antigravity says "Resets in 8h47m2s", and the singular-only pattern
    read that as no reset time at all - so a model that was coming back in
    nine hours looked like one that might never come back."""
    now = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)

    reset = usage_limits.parse_reset_at(
        "error: Individual quota reached. Please upgrade your subscription "
        "to increase your limits. Resets in 8h47m2s.",
        now=now,
    )

    assert reset == now + timedelta(hours=8)


def test_a_clock_only_reset_uses_the_named_zone_and_next_occurrence() -> None:
    now = datetime(2026, 8, 28, 1, 0, tzinfo=timezone.utc)  # 08:00 in Bangkok

    reset = usage_limits.parse_reset_at(
        "You've hit your weekly limit · resets 6pm (Asia/Bangkok)",
        now=now,
    )

    assert reset == datetime(2026, 8, 28, 11, 0, tzinfo=timezone.utc)


def test_codex_clock_only_retry_uses_bangkok_and_next_day_when_needed() -> None:
    now = datetime(2026, 8, 28, 1, 0, tzinfo=timezone.utc)  # 08:00 in Bangkok

    reset = usage_limits.parse_reset_at(
        "You've hit your usage limit; try again at 6:30 AM",
        now=now,
    )

    assert reset == datetime(2026, 8, 28, 23, 30, tzinfo=timezone.utc)


def test_no_stated_time_gives_no_guess() -> None:
    """Inventing a time would be worse than admitting we do not know."""
    assert usage_limits.parse_reset_at("You exceeded your current quota") is None


def test_the_shown_line_is_the_one_that_matters() -> None:
    """A provider error runs to pages; a banner gets one line."""
    described = usage_limits.describe(CODEX_LIMIT)

    assert described.startswith("You've hit your usage limit")
    assert "workdir" not in described


# --- ghi nhan qua cau noi -------------------------------------------------


def test_a_limited_cli_call_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    database.clear_provider_usage_limit("codex_cli")
    monkeypatch.setattr(
        llm_client, "_call_codex_json",
        lambda *a, **k: (_ for _ in ()).throw(CodexBridgeError(CODEX_LIMIT)),
    )

    with pytest.raises(llm_client.LlmError):
        llm_client.call_codex_json("s", "u", {"type": "object"})

    recorded = database.get_provider_usage_limit("codex_cli")
    assert recorded is not None and recorded["cleared_at"] is None
    assert "usage limit" in recorded["message"].lower()
    assert recorded["resets_at"].startswith("2026-08-27")


def test_an_ordinary_cli_failure_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    database.clear_provider_usage_limit("antigravity")
    monkeypatch.setattr(
        llm_client, "_call_antigravity_json",
        lambda *a, **k: (_ for _ in ()).throw(llm_client.AntigravityBridgeError("khong parse duoc JSON")),
    )

    with pytest.raises(llm_client.LlmError):
        llm_client.call_antigravity_json("s", "u", {"type": "object"})

    active = [item["provider"] for item in database.list_active_usage_limits()]
    assert "antigravity" not in active


def test_a_successful_call_clears_the_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    database.record_provider_usage_limit("claude_code_cli", "Usage limit reached", None)
    monkeypatch.setattr(llm_client, "_call_claude_code_json", lambda *a, **k: {"ok": True})

    llm_client.call_claude_code_cli_json("s", "u", {"type": "object"})

    assert database.get_provider_usage_limit("claude_code_cli")["cleared_at"] is not None


def test_repeated_failures_keep_the_first_time_it_broke() -> None:
    """What matters is when the model stopped, not when it was last retried."""
    database.clear_provider_usage_limit("gflow_cli")
    first = database.record_provider_usage_limit("gflow_cli", "het tin dung", None)

    again = database.record_provider_usage_limit("gflow_cli", "het tin dung lan hai", None)

    assert again["detected_at"] == first["detected_at"]
    assert again["message"] == "het tin dung lan hai"
    assert again["last_failure_at"] is not None


def test_a_new_outage_after_recovery_gets_a_new_time() -> None:
    database.record_provider_usage_limit("runway", "quota exceeded", None)
    database.clear_provider_usage_limit("runway")

    revived = database.record_provider_usage_limit("runway", "quota exceeded", None)

    assert revived["cleared_at"] is None


# --- hien thi -------------------------------------------------------------


def test_the_listing_names_the_product_not_the_key() -> None:
    database.record_provider_usage_limit("codex_cli", "You've hit your usage limit", None)

    labels = [item["label"] for item in list_usage_limits()["limits"]]

    assert "Codex CLI (ChatGPT)" in labels


def test_a_limit_whose_reset_has_passed_is_not_still_warned_about() -> None:
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    database.record_provider_usage_limit("openai_image", "quota exceeded", stale)

    providers = [item["provider"] for item in list_usage_limits()["limits"]]

    assert "openai_image" not in providers


def test_a_limit_still_in_force_is_listed() -> None:
    ahead = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    database.record_provider_usage_limit("gemini_image", "quota exceeded", ahead)

    providers = [item["provider"] for item in list_usage_limits()["limits"]]

    assert "gemini_image" in providers
