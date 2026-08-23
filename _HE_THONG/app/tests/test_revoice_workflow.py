"""The re-narration workflow: translating narration, and cutting from the source."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import HTTPException

from youtube_monitor import main
from youtube_monitor.main import (
    UpdateProjectWorkflowRequest,
    database,
    plan_timeline_source_cues,
    translate_project_narration,
    update_project_workflow,
)
from youtube_monitor.source_visuals import _cue_for_segment

SOURCE_LINES = [
    {"start": 0.0, "end": 4.0, "text": "Six months ago I gave up the apartment."},
    {"start": 60.0, "end": 64.0, "text": "This is what fifteen thousand a month buys in Dubai."},
    {"start": 300.0, "end": 305.0, "text": "Here is the strategy we settled on."},
]


def _project(slug: str, with_transcript: bool = True) -> dict[str, Any]:
    """A project on its own source video, in the isolated test database.

    Each test gets a distinct video id: these all share one database file, and
    a transcript or a workflow left behind by one test would decide the result
    of the next.
    """
    video_id = f"video-revoice-{slug}"
    database.upsert_channel({
        "youtube_channel_id": "UC0000000000000000000009",
        "channel_url": "https://www.youtube.com/channel/UC0000000000000000000009",
        "title": "Kenh nguon",
        "uploads_playlist_id": "UU0000000000000000000009",
    })
    database.upsert_video({
        "youtube_video_id": video_id,
        "youtube_channel_id": "UC0000000000000000000009",
        "video_url": f"https://www.youtube.com/watch?v={video_id}",
        "title": "Source",
        "description": "Khong co chapter nao trong mo ta.",
        "metadata_hash": f"hash-{slug}",
        "raw_payload": {},
        "duration_seconds": 600,
    })
    if with_transcript:
        database.save_transcript(
            video_id, json.dumps(SOURCE_LINES), transcript_format="json", language="en"
        )
    project = database.create_production_project(video_id, title="Revoice")
    script = database.create_project_script(int(project["id"]), script_title="Loi binh")
    database.create_project_timeline(
        int(project["id"]),
        int(script["id"]),
        [{
            "segment_index": index + 1,
            "start_seconds": index * 8,
            "duration_seconds": 8,
            "voice_text": text,
            "subtitle_text": text,
            "visual_prompt": text,
            "asset_type": "source_clip",
        } for index, text in enumerate([
            "And I gave everything back in a click.",
            "that you will go and spend in Dubai,",
            "That's an important sort of a way for us.",
        ])],
        force=True,
    )
    return project


def test_workflow_choice_is_stored_on_the_project() -> None:
    """It belongs to the project, not the browser: reopening must restore it."""
    project = _project("wf-store")

    result = update_project_workflow(int(project["id"]), UpdateProjectWorkflowRequest(workflow="revoice"))

    assert result["project"]["workflow"] == "revoice"


def test_existing_projects_default_to_the_original_workflow() -> None:
    """Every project predating the idea was built the one way the app worked."""
    project = _project("wf-default")

    assert project["workflow"] == "content"


def test_translation_replaces_each_line_and_keeps_the_original(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scene count and boundaries are fixed; only the words may change."""
    project = _project("tr-once")

    def fake_call(system_prompt, body, schema, stage="orchestration", **kwargs):
        assert stage == "script"
        indices = [int(line.split("]")[0][1:]) for line in body.splitlines()]
        return {"lines": [{"segment_index": index, "text": f"cau {index} da dich"} for index in indices]}

    monkeypatch.setattr(main, "_call_orchestrator_json", fake_call)

    result = translate_project_narration(int(project["id"]), target_language="vi", batch_size=8)

    assert result["translated"] == 3
    assert result["missing_segments"] == []
    timeline = database.list_project_timeline(int(project["id"]))
    assert len(timeline) == 3, "dich khong duoc lam thay doi so canh"
    assert [item["voice_text"] for item in timeline] == [f"cau {i} da dich" for i in (1, 2, 3)]
    assert timeline[0]["source_voice_text"] == "And I gave everything back in a click."


def test_translating_twice_does_not_lose_the_original(monkeypatch: pytest.MonkeyPatch) -> None:
    """The second pass sees translated text; the stored original must survive."""
    project = _project("tr-twice")
    counter = {"round": 0}

    def fake_call(system_prompt, body, schema, stage="orchestration", **kwargs):
        counter["round"] += 1
        indices = [int(line.split("]")[0][1:]) for line in body.splitlines()]
        return {
            "lines": [
                {"segment_index": index, "text": f"vong {counter['round']} canh {index}"}
                for index in indices
            ]
        }

    monkeypatch.setattr(main, "_call_orchestrator_json", fake_call)
    translate_project_narration(int(project["id"]), target_language="vi", batch_size=8)
    translate_project_narration(int(project["id"]), target_language="en", batch_size=8)

    timeline = database.list_project_timeline(int(project["id"]))
    assert timeline[0]["source_voice_text"] == "And I gave everything back in a click."
    assert timeline[0]["voice_text"] == "vong 2 canh 1"


def test_a_failed_batch_reports_why_instead_of_going_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project("tr-fail")

    def fake_call(*args, **kwargs):
        raise main.LlmError("orchestrator khong tra loi")

    monkeypatch.setattr(main, "_call_orchestrator_json", fake_call)

    with pytest.raises(HTTPException) as caught:
        translate_project_narration(int(project["id"]), target_language="vi", batch_size=8)

    assert caught.value.status_code == 502
    assert "orchestrator khong tra loi" in str(caught.value.detail)


def test_source_cues_are_stored_per_scene(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project("cue-store")

    def fake_call(system_prompt, body, schema, stage="orchestration", **kwargs):
        assert "BAN GHI VIDEO GOC" in body
        return {"cues": [
            {"segment_index": 1, "source_start_seconds": 120, "reason": "canh dong goi do"},
            {"segment_index": 2, "source_start_seconds": 300, "reason": "canh Dubai"},
            {"segment_index": 3, "source_start_seconds": 540, "reason": "canh man hinh"},
        ]}

    monkeypatch.setattr(main, "_call_orchestrator_json", fake_call)

    result = plan_timeline_source_cues(int(project["id"]))

    assert result["distinct_cues"] == 3
    assert [scene["source_start_seconds"] for scene in result["scenes"]] == [120, 300, 540]


def test_a_cue_past_the_end_is_pulled_back_inside_the_video(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cue beyond the source would cut a black clip, silently."""
    project = _project("cue-clamp")

    monkeypatch.setattr(
        main,
        "_call_orchestrator_json",
        lambda *a, **k: {"cues": [{"segment_index": 1, "source_start_seconds": 99999}]},
    )

    result = plan_timeline_source_cues(int(project["id"]))

    assert result["scenes"][0]["source_start_seconds"] <= 600


def test_planning_needs_a_timestamped_transcript() -> None:
    """Without one there is nothing to match narration against; say so."""
    project = _project("cue-none", with_transcript=False)

    with pytest.raises(HTTPException) as caught:
        plan_timeline_source_cues(int(project["id"]))

    assert caught.value.status_code == 400
    assert "transcript" in str(caught.value.detail).lower()


def test_a_planned_cue_beats_the_keyword_table() -> None:
    """The whole point: a source with no chapters used to cut everything at 0s."""
    without_chapters: list[tuple[float, str]] = []

    assert _cue_for_segment({"voice_text": "bat ky"}, 1, without_chapters) == 0.0
    assert _cue_for_segment({"source_start_seconds": 121.0}, 1, without_chapters) == 121.0


def test_an_unplanned_scene_still_falls_back_to_the_old_behaviour() -> None:
    """-1 means nobody chose; 0 is a real choice, so they cannot share a value."""
    cues = [(0.0, "intro"), (90.0, "data")]

    assert _cue_for_segment({"source_start_seconds": -1}, 2, cues) == 90.0
    assert _cue_for_segment({"source_start_seconds": 0.0}, 2, cues) == 0.0
