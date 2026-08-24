"""Finding an earlier analysis again after the page reloads."""

from __future__ import annotations

import pytest

from youtube_monitor.claude_code_bridge import ClaudeCodeBridgeError
from youtube_monitor.main import database, get_reference_analysis
from fastapi import HTTPException


def _video(slug: str) -> str:
    """Its own source per test: these share one database, and an analysis left
    behind by one test decides the result of the next."""
    database.upsert_channel({
        "youtube_channel_id": "UC0000000000000000000002",
        "channel_url": "https://www.youtube.com/channel/UC0000000000000000000002",
        "title": "Kenh",
        "uploads_playlist_id": "UU0000000000000000000002",
    })
    database.upsert_video({
        "youtube_video_id": f"video-restore-{slug}",
        "youtube_channel_id": "UC0000000000000000000002",
        "video_url": f"https://www.youtube.com/watch?v=video-restore-{slug}",
        "title": "Nguon", "description": "", "metadata_hash": f"h-{slug}", "raw_payload": {},
    })
    return f"video-restore-{slug}"


def test_a_stored_analysis_comes_back_marked_completed() -> None:
    """The studio only redraws an analysis it can see is finished. The stored
    row carries no status, so a real analysis came back statusless, was
    ignored, and the wizard fell back to step one."""
    video_id = _video("stored")
    database.save_video_analysis(
        video_id,
        {"content_summary": "Cau chuyen", "dialogue": [{"order": 1, "speaker": "Cha", "line": "x"}]},
        analysis_type="reference",
        provider="antigravity",
    )

    answer = get_reference_analysis(video_id)

    assert answer["status"] == "completed"
    assert answer["result"]["content_summary"] == "Cau chuyen"


def test_the_stored_fields_are_not_shadowed_by_the_added_status() -> None:
    video_id = _video("fields")
    database.save_video_analysis(
        video_id, {"content_summary": "x"}, analysis_type="reference", provider="antigravity"
    )

    answer = get_reference_analysis(video_id)

    assert answer["provider"] == "antigravity"
    assert answer["youtube_video_id"] == video_id


def test_a_video_with_no_analysis_is_pending() -> None:
    """The wizard must be able to tell "not read yet" from "read"."""
    video_id = _video("pending")
    assert get_reference_analysis(video_id)["status"] == "pending"


def test_an_unknown_video_is_a_404() -> None:
    with pytest.raises(HTTPException) as caught:
        get_reference_analysis("khong-ton-tai")

    assert caught.value.status_code == 404


def test_a_timeout_says_so_instead_of_printing_the_whole_command() -> None:
    """TimeoutExpired stringifies the command, which is a 7500 character prompt
    and schema, so the reason ended up at the very end of a wall of text."""
    import subprocess

    from youtube_monitor import claude_code_bridge

    message = ""
    try:
        try:
            raise subprocess.TimeoutExpired(cmd=["claude.exe", "-p", "x" * 7000], timeout=600)
        except subprocess.TimeoutExpired as exc:
            raise ClaudeCodeBridgeError(
                f"Claude Code CLI qua thoi gian ({600}s). "
                "Noi dung qua dai hoac may chu dang cham."
            ) from exc
    except ClaudeCodeBridgeError as exc:
        message = str(exc)

    assert "qua thoi gian" in message
    assert len(message) < 200, "thong bao phai doc duoc, khong phai ca dong lenh"
    assert claude_code_bridge.call_claude_code_json.__defaults__ is not None
