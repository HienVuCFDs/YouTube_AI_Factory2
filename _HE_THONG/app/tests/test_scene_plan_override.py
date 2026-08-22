"""Correcting one scene's plan by hand, without re-running the planner."""

from __future__ import annotations

import pytest

from youtube_monitor.main import database, update_timeline_segment_plan, UpdateScenePlanRequest
from fastapi import HTTPException


@pytest.fixture()
def segment_id() -> int:
    """One project with one timeline segment, in the isolated test database."""
    database.upsert_channel({
        "youtube_channel_id": "UC0000000000000000000001",
        "channel_url": "https://www.youtube.com/channel/UC0000000000000000000001",
        "title": "Kenh test",
        "uploads_playlist_id": "UU0000000000000000000001",
    })
    database.upsert_video({
        "youtube_video_id": "video-plan-override",
        "youtube_channel_id": "UC0000000000000000000001",
        "video_url": "https://www.youtube.com/watch?v=video-plan-override",
        "title": "Nguon",
        "description": "",
        "metadata_hash": "hash-plan-override",
        "raw_payload": {},
    })
    project = database.create_production_project("video-plan-override", title="Ke hoach canh")
    script = database.create_project_script(
        int(project["id"]),
        script_title="Kich ban",
        hook="hook",
        intro="intro",
        main_content="noi dung",
        cta="cta",
    )
    timeline = database.create_project_timeline(
        int(project["id"]),
        int(script["id"]),
        [{
            "segment_index": 1,
            "start_seconds": 0,
            "duration_seconds": 5,
            "voice_text": "loi doc",
            "subtitle_text": "phu de",
            "visual_prompt": "mot bieu do",
            "asset_type": "image",
        }],
        force=True,
    )
    return int(timeline[0]["id"])


def test_changing_the_kind_records_that_a_person_chose_it(segment_id: int) -> None:
    """The reason column has to say so, or the next planner run looks wrong."""
    result = update_timeline_segment_plan(segment_id, UpdateScenePlanRequest(visual_kind="gif", visual_fps=10))

    segment = result["segment"]
    assert segment["visual_kind"] == "gif"
    assert segment["visual_fps"] == 10
    assert "tay" in segment["visual_kind_reason"]


def test_choosing_a_still_clears_the_frame_rate(segment_id: int) -> None:
    """A still has no frame rate; leaving a stale one behind misleads the render."""
    update_timeline_segment_plan(segment_id, UpdateScenePlanRequest(visual_kind="gif", visual_fps=12))

    result = update_timeline_segment_plan(segment_id, UpdateScenePlanRequest(visual_kind="image"))

    assert result["segment"]["visual_kind"] == "image"
    assert result["segment"]["visual_fps"] == 0


def test_editing_the_cut_leaves_the_visual_kind_alone(segment_id: int) -> None:
    """The two plans are set from separate tables in the UI and must not collide."""
    update_timeline_segment_plan(segment_id, UpdateScenePlanRequest(visual_kind="video", visual_fps=8))

    result = update_timeline_segment_plan(
        segment_id, UpdateScenePlanRequest(transition="cut", effect="static", note="giu yen de doc so")
    )

    segment = result["segment"]
    assert segment["visual_kind"] == "video"
    assert segment["edit_transition"] == "cut"
    assert segment["edit_effect"] == "static"
    assert segment["edit_note"] == "giu yen de doc so"


def test_changing_only_the_frame_rate_keeps_the_planner_s_reason(segment_id: int) -> None:
    database.set_segment_visual_kind(segment_id, "gif", fps=8, reason="AI: so dem tang dan")

    result = update_timeline_segment_plan(segment_id, UpdateScenePlanRequest(visual_fps=12))

    assert result["segment"]["visual_fps"] == 12
    assert result["segment"]["visual_kind_reason"] == "AI: so dem tang dan"


def test_an_unknown_segment_is_refused() -> None:
    with pytest.raises(HTTPException) as caught:
        update_timeline_segment_plan(999999, UpdateScenePlanRequest(visual_kind="image"))

    assert caught.value.status_code == 404
