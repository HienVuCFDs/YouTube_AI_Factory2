"""Keeping dialogue as dialogue, and cutting the timeline where it is spoken."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from youtube_monitor.main import build_timeline_from_dialogue, database
from youtube_monitor.shot_planner import build_shot_plan
from youtube_monitor.timeline_builder import build_timeline
from youtube_monitor.writer import FAITHFUL_RETELL_MODE, _build_prompt, system_prompt_for

TURNS = [
    {"order": 1, "speaker": "Người dẫn", "line": "Ngày xưa có hai anh em.", "start_seconds": 0, "end_seconds": 5},
    {"order": 2, "speaker": "Cha", "line": "Các con phải thương nhau.", "start_seconds": 5, "end_seconds": 9},
    {"order": 3, "speaker": "Tân", "line": "Thưa cha, con xin ghi lòng.", "start_seconds": 9, "end_seconds": 12},
]


def _project(slug: str, turns: list[dict] | None = None) -> dict:
    video_id = f"video-dialogue-{slug}"
    database.upsert_channel({
        "youtube_channel_id": "UC0000000000000000000012",
        "channel_url": "https://www.youtube.com/channel/UC0000000000000000000012",
        "title": "Kenh", "uploads_playlist_id": "UU0000000000000000000012",
    })
    database.upsert_video({
        "youtube_video_id": video_id, "youtube_channel_id": "UC0000000000000000000012",
        "video_url": f"https://x/{video_id}", "title": "Nguon", "description": "",
        "metadata_hash": f"h-{slug}", "raw_payload": {}, "duration_seconds": 120,
    })
    if turns is not None:
        database.save_video_analysis(
            video_id, {"dialogue": turns}, analysis_type="reference", provider="antigravity"
        )
    project = database.create_production_project(video_id, title="Reup")
    database.create_project_script(int(project["id"]), script_title="x")
    return project


# --- the script keeps dialogue as dialogue --------------------------------


def test_the_brief_forbids_turning_dialogue_into_reported_speech() -> None:
    """Every character line was arriving as narration - "anh ta noi rang..." -
    because the brief cast the writer as a narrator and gave scenes no speaker."""
    brief = system_prompt_for(FAITHFUL_RETELL_MODE)

    assert "VẪN NÓI" in brief
    assert "lời kể gián tiếp" in brief


def test_a_scene_is_one_speaking_turn_with_its_speaker() -> None:
    prompt = _build_prompt(
        {"title": "x", "description": ""},
        "Cha noi: Cac con phai thuong nhau.",
        remake_mode=FAITHFUL_RETELL_MODE,
    )

    assert "'speaker': ai nói" in prompt
    assert "LỜI THOẠI TRỰC TIẾP" in prompt
    assert "đừng gộp hai người thành một cảnh" in prompt


def test_the_speaker_survives_from_script_to_timeline() -> None:
    """It had nowhere to live, so a line could not stay attached to who says it."""
    writer_content = {"scene_blueprints": [
        {"order": 1, "section": "main", "narration": "Các con phải thương nhau.",
         "speaker": "Cha", "visual_prompt": "x", "asset_type": "source_clip", "duration_seconds": 4},
    ]}

    shots = build_shot_plan({"title": "x"}, {}, writer_content=writer_content)
    timeline = build_timeline({"title": "x"}, {}, shots)

    assert shots[0]["speaker"] == "Cha"
    assert timeline[0]["speaker"] == "Cha"


def test_the_writers_asset_type_is_not_overwritten() -> None:
    """Forcing ai_scene sent the reup workflow, whose pictures come from its own
    source, into the image generators anyway."""
    writer_content = {"scene_blueprints": [
        {"order": 1, "section": "main", "narration": "x", "speaker": "Cha",
         "visual_prompt": "x", "asset_type": "source_clip", "duration_seconds": 4},
    ]}

    assert build_shot_plan({"title": "x"}, {}, writer_content=writer_content)[0]["asset_type"] == "source_clip"


# --- the timeline is cut where the line is spoken -------------------------


def test_one_segment_per_spoken_turn() -> None:
    project = _project("basic", TURNS)

    result = build_timeline_from_dialogue(int(project["id"]), min_seconds=1.2)

    assert result["segments"] == 3
    assert result["speakers"] == ["Cha", "Người dẫn", "Tân"]


def test_each_cut_lands_on_the_second_the_line_is_spoken() -> None:
    """This is the whole point: the pictures come from the source, so the cut
    belongs where the speech is, not on invented even blocks."""
    project = _project("cuts", TURNS)

    result = build_timeline_from_dialogue(int(project["id"]), min_seconds=1.2)

    assert [item["source_start_seconds"] for item in result["timeline"]] == [0.0, 5.0, 9.0]
    assert [item["duration_seconds"] for item in result["timeline"]] == [5, 4, 3]


def test_segments_are_marked_as_source_clips() -> None:
    project = _project("assets", TURNS)

    result = build_timeline_from_dialogue(int(project["id"]), min_seconds=1.2)

    assert {item["asset_type"] for item in result["timeline"]} == {"source_clip"}


def test_the_line_stays_with_whoever_says_it() -> None:
    project = _project("speakers", TURNS)

    result = build_timeline_from_dialogue(int(project["id"]), min_seconds=1.2)

    pairs = [(item["speaker"], item["voice_text"]) for item in result["timeline"]]
    assert ("Cha", "Các con phải thương nhau.") in pairs


def test_a_turn_with_no_timing_is_counted_rather_than_silently_zero() -> None:
    """An analysis from before turns carried times would otherwise produce
    zero-length scenes that render as nothing."""
    project = _project("untimed", [
        {"order": 1, "speaker": "Cha", "line": "khong co moc", "start_seconds": 0, "end_seconds": 0},
    ])

    result = build_timeline_from_dialogue(int(project["id"]), min_seconds=1.2)

    assert result["turns_without_timing"] == 1
    assert result["timeline"][0]["duration_seconds"] >= 1


def test_an_empty_line_is_skipped() -> None:
    project = _project("empty", [
        {"order": 1, "speaker": "Cha", "line": "co noi dung", "start_seconds": 0, "end_seconds": 4},
        {"order": 2, "speaker": "Tân", "line": "   ", "start_seconds": 4, "end_seconds": 6},
    ])

    assert build_timeline_from_dialogue(int(project["id"]), min_seconds=1.2)["segments"] == 1


def test_it_refuses_without_an_analysis() -> None:
    project = _project("noanalysis", None)

    with pytest.raises(HTTPException) as caught:
        build_timeline_from_dialogue(int(project["id"]), min_seconds=1.2)

    assert caught.value.status_code == 400
    assert "Phân tích" in str(caught.value.detail)


def test_cutting_by_dialogue_rewrites_the_storyboard_to_match() -> None:
    """The storyboard grid is drawn from project_shots and finds a card's
    picture through segment.shot_id. Cutting the timeline used to leave the
    earlier, AI-invented storyboard in place beside it, so the screen showed
    36 cards for 85 scenes and every card said it had no picture yet - even
    though each segment already carried its clip from the source video.
    """
    project = _project("shots-follow", TURNS)
    script = database.get_latest_project_script(int(project["id"]))
    database.create_project_shots(int(project["id"]), int(script["id"]), [
        {"shot_index": i, "narration": "canh AI cu", "visual_prompt": "anh minh hoa"}
        for i in range(1, 8)
    ], force=True)

    build_timeline_from_dialogue(int(project["id"]), min_seconds=1.2)

    shots = database.list_project_shots(int(project["id"]), script_id=int(script["id"]))
    timeline = database.list_project_timeline(int(project["id"]), script_id=int(script["id"]))

    assert len(shots) == len(timeline) == len(TURNS), "moi luot thoai mot canh"
    assert all(segment["shot_id"] for segment in timeline), "canh nao cung phai noi duoc voi doan"
    assert {int(s["shot_id"]) for s in timeline} == {int(s["id"]) for s in shots}


def test_each_storyboard_card_carries_the_line_and_the_speaker() -> None:
    """A card showing narration that nobody in the source says would send the
    reup workflow straight back to inventing content."""
    project = _project("shots-carry", TURNS)
    build_timeline_from_dialogue(int(project["id"]), min_seconds=1.2)

    script = database.get_latest_project_script(int(project["id"]))
    shots = database.list_project_shots(int(project["id"]), script_id=int(script["id"]))

    assert [shot["narration"] for shot in shots] == [turn["line"] for turn in TURNS]
    assert [shot["speaker"] for shot in shots] == [turn["speaker"] for turn in TURNS]
    assert all(shot["asset_type"] == "source_clip" for shot in shots), "WF reup khong tao anh AI"


def test_the_edit_planner_is_told_what_the_source_looks_like(monkeypatch) -> None:
    """Every scene in a reup is cut from one video, so a channel logo or a
    burned-in subtitle is on all of them or none. The planner used to be asked
    what a scene looks like while holding only its dialogue and the words
    "cut from the source at 9s", so it correctly reported no evidence of any
    mark - and eighty-five scenes of Chinese subtitles were never cleaned,
    even though the analysis had written down that they were there.
    """
    from youtube_monitor import main

    project = _project("plan-sees-source", TURNS)
    build_timeline_from_dialogue(int(project["id"]), min_seconds=1.2)
    database.save_video_analysis(
        "video-dialogue-plan-sees-source",
        {"dialogue": TURNS, "visual_style": "Hoạt họa 2D, có phụ đề tiếng Hán chạy dưới"},
        analysis_type="reference", provider="antigravity",
    )

    seen: dict[str, str] = {}

    def capture(system_prompt, user_prompt, _schema, **_kwargs):
        seen["system"] = system_prompt
        seen["user"] = user_prompt
        return {"scenes": [], "pacing": "", "music_mood": ""}

    monkeypatch.setattr(main, "_call_orchestrator_json", capture)
    main.plan_project_edit(int(project["id"]))

    assert "phụ đề tiếng Hán" in seen["user"], "mo ta hinh anh nguon phai di kem"
    assert "MOT video goc" in seen["user"], "phai noi ro moi canh cat tu cung mot nguon"
    assert "MOI canh" in seen["system"], "dau vet cua nguon thi dung cho moi canh"


def _plan_with(monkeypatch, project_id: int, scenes: list[dict]) -> None:
    from youtube_monitor import main

    monkeypatch.setattr(
        main, "_call_orchestrator_json",
        lambda *_a, **_k: {"scenes": scenes, "pacing": "", "music_mood": ""},
    )
    main.plan_project_edit(project_id)
    main.approve_project_edit_plan(project_id)
    main.apply_project_edit_plan(project_id)


def test_a_scene_short_of_pictures_goes_back_to_the_storyboard(monkeypatch) -> None:
    """What is on screen is decided in the storyboard, and its cards already
    carry the controls to draw or attach a visual. Reported only in the
    edit-plan table, the note was a dead end: nothing could act on it.
    """
    project = _project("needs-visual", TURNS)
    build_timeline_from_dialogue(int(project["id"]), min_seconds=1.2)
    _plan_with(monkeypatch, int(project["id"]), [{
        "segment_index": 2, "transition": "cut", "effect": "static",
        "needs_extra_visual": True,
        "extra_visual_note": "Can ban do vung dat duoc nhac toi",
    }])

    script = database.get_latest_project_script(int(project["id"]))
    shots = database.list_project_shots(int(project["id"]), script_id=int(script["id"]))

    assert shots[1]["status"] == "needs_visual"
    assert shots[1]["visual_prompt"] == "Can ban do vung dat duoc nhac toi"
    assert [shot["status"] for shot in shots].count("needs_visual") == 1, "chi canh duoc bao moi danh dau"


def test_the_note_becomes_the_prompt_the_card_generates_from(monkeypatch) -> None:
    """"Cắt từ video gốc tại 9s" is not something an image model can draw."""
    project = _project("needs-visual-prompt", TURNS)
    build_timeline_from_dialogue(int(project["id"]), min_seconds=1.2)
    script = database.get_latest_project_script(int(project["id"]))
    before = database.list_project_shots(int(project["id"]), script_id=int(script["id"]))[0]

    _plan_with(monkeypatch, int(project["id"]), [{
        "segment_index": 1, "transition": "cut", "effect": "static",
        "needs_extra_visual": True, "extra_visual_note": "The chu giai nghia chuc quan",
    }])

    after = database.list_project_shots(int(project["id"]), script_id=int(script["id"]))[0]
    assert before["visual_prompt"] != after["visual_prompt"]
    assert after["visual_prompt"] == "The chu giai nghia chuc quan"


def test_withdrawing_the_flag_releases_the_card(monkeypatch) -> None:
    project = _project("needs-visual-clear", TURNS)
    build_timeline_from_dialogue(int(project["id"]), min_seconds=1.2)
    scene = {"segment_index": 1, "transition": "cut", "effect": "static"}

    _plan_with(monkeypatch, int(project["id"]), [{**scene, "needs_extra_visual": True, "extra_visual_note": "x"}])
    _plan_with(monkeypatch, int(project["id"]), [{**scene, "needs_extra_visual": False}])

    script = database.get_latest_project_script(int(project["id"]))
    shots = database.list_project_shots(int(project["id"]), script_id=int(script["id"]))
    assert shots[0]["status"] == "planned"


def test_a_card_already_filled_in_keeps_its_own_status(monkeypatch) -> None:
    """Re-running the plan must not walk back work somebody has since done."""
    project = _project("needs-visual-keep", TURNS)
    build_timeline_from_dialogue(int(project["id"]), min_seconds=1.2)
    script = database.get_latest_project_script(int(project["id"]))
    shot = database.list_project_shots(int(project["id"]), script_id=int(script["id"]))[0]
    database.update_project_shot(int(shot["id"]), status="done")

    _plan_with(monkeypatch, int(project["id"]), [
        {"segment_index": 1, "transition": "cut", "effect": "static", "needs_extra_visual": False},
    ])

    kept = database.get_project_shot(int(shot["id"]))
    assert kept["status"] == "done"
