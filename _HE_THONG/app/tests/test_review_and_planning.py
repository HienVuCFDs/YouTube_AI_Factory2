"""The four checks that shipped as endpoints with nothing covering them."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from youtube_monitor import main
from youtube_monitor.main import (
    database,
    plan_project_edit,
    plan_timeline_visuals,
    review_project_script,
    review_project_voice,
)

NARRATION = [
    "Cung tam muoi trieu, cung bon nam.",
    "Nguoi gui tiet kiem nhan ve mot tram le mot trieu.",
    "Nguoi di vay tra ve chin muoi chin trieu.",
]


def _project(slug: str, with_audio: bool = False, tmp_path: Path | None = None) -> dict[str, Any]:
    """A project with a script and three scenes, on its own source video."""
    video_id = f"video-review-{slug}"
    database.upsert_channel({
        "youtube_channel_id": "UC0000000000000000000007",
        "channel_url": "https://www.youtube.com/channel/UC0000000000000000000007",
        "title": "Kenh",
        "uploads_playlist_id": "UU0000000000000000000007",
    })
    database.upsert_video({
        "youtube_video_id": video_id,
        "youtube_channel_id": "UC0000000000000000000007",
        "video_url": f"https://www.youtube.com/watch?v={video_id}",
        "title": "Nguon",
        "description": "",
        "metadata_hash": f"hash-{slug}",
        "raw_payload": {},
    })
    project = database.create_production_project(video_id, title="Duyet")
    script = database.create_project_script(
        int(project["id"]),
        script_title="Lai suat",
        hook="Cung tam muoi trieu, hai so phan.",
        intro="Bon phut toi.",
        main_content="Noi dung chinh.",
        cta="Dang ky kenh.",
    )
    segments = []
    for index, text in enumerate(NARRATION):
        entry = {
            "segment_index": index + 1,
            "start_seconds": index * 6,
            "duration_seconds": 6,
            "voice_text": text,
            "subtitle_text": text,
            "visual_prompt": f"canh {index + 1}",
            "asset_type": "ai_scene",
        }
        if with_audio and tmp_path is not None:
            clip = tmp_path / f"segment-{index + 1}.wav"
            clip.write_bytes(b"RIFF----WAVEfmt ")
            entry["audio_path"] = str(clip)
        segments.append(entry)
    database.create_project_timeline(int(project["id"]), int(script["id"]), segments, force=True)
    return project


# --- B2: duyet kich ban -------------------------------------------------


def test_script_review_scores_and_moves_the_draft_into_review(monkeypatch: pytest.MonkeyPatch) -> None:
    """status had draft/review/approved and nothing ever set review."""
    project = _project("script-ok")
    monkeypatch.setattr(main, "_call_orchestrator_json", lambda *a, **k: {
        "score": 6,
        "hook_verdict": "Chua sac",
        "issues": ["Hook khong duoc tra bai"],
        "suggestions": ["Them ba cau ket"],
        "should_rewrite": False,
    })

    result = review_project_script(int(project["id"]))

    assert result["review"]["score"] == 6
    assert result["script"]["status"] == "review"
    assert result["script"]["review_score"] == 6
    assert "Hook khong duoc tra bai" in result["script"]["review_note"]


def test_script_review_needs_a_script() -> None:
    video_id = "video-review-noscript"
    database.upsert_channel({
        "youtube_channel_id": "UC0000000000000000000007",
        "channel_url": "https://www.youtube.com/channel/UC0000000000000000000007",
        "title": "Kenh",
        "uploads_playlist_id": "UU0000000000000000000007",
    })
    database.upsert_video({
        "youtube_video_id": video_id,
        "youtube_channel_id": "UC0000000000000000000007",
        "video_url": f"https://www.youtube.com/watch?v={video_id}",
        "title": "Nguon",
        "description": "",
        "metadata_hash": "hash-noscript",
        "raw_payload": {},
    })
    project = database.create_production_project(video_id, title="Chua co kich ban")

    with pytest.raises(HTTPException) as caught:
        review_project_script(int(project["id"]))

    assert caught.value.status_code == 404


# --- B3: duyet giong doc ------------------------------------------------


def test_voice_review_compares_what_was_heard_against_the_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = _project("voice-ok", with_audio=True, tmp_path=tmp_path)
    monkeypatch.setattr(main, "transcribe_local_file", lambda *a, **k: {"text": "nghe duoc gi do"})
    monkeypatch.setattr(main, "_call_orchestrator_json", lambda *a, **k: {
        "score": 9, "matches": True, "issues": ["chi sai chinh ta"],
    })

    result = review_project_voice(int(project["id"]), limit=2)

    assert result["checked"] == 2
    assert result["mismatched"] == 0
    timeline = database.list_project_timeline(int(project["id"]))
    assert timeline[0]["voice_review_score"] == 9


def test_voice_review_counts_a_scene_that_reads_differently(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A dropped sentence is the failure this check exists to catch."""
    project = _project("voice-bad", with_audio=True, tmp_path=tmp_path)
    monkeypatch.setattr(main, "transcribe_local_file", lambda *a, **k: {"text": "thieu mot cau"})
    monkeypatch.setattr(main, "_call_orchestrator_json", lambda *a, **k: {
        "score": 4, "matches": False, "issues": ["Bo sot nguyen cau"],
    })

    result = review_project_voice(int(project["id"]), limit=0)

    assert result["mismatched"] == result["checked"] == 3


def test_a_clip_that_cannot_be_transcribed_does_not_end_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = _project("voice-skip", with_audio=True, tmp_path=tmp_path)
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("file hong")
        return {"text": "nghe duoc"}

    monkeypatch.setattr(main, "transcribe_local_file", flaky)
    monkeypatch.setattr(main, "_call_orchestrator_json", lambda *a, **k: {"score": 8, "matches": True})

    result = review_project_voice(int(project["id"]), limit=0)

    statuses = [item["status"] for item in result["segments"]]
    assert statuses.count("skipped") == 1
    assert statuses.count("ok") == 2


def test_voice_review_needs_audio_on_disk() -> None:
    project = _project("voice-none")

    with pytest.raises(HTTPException) as caught:
        review_project_voice(int(project["id"]), limit=0)

    assert caught.value.status_code == 400


# --- B4: phan loai canh -------------------------------------------------


def test_visual_plan_stores_a_kind_and_reason_per_scene(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project("visual-plan")
    monkeypatch.setattr(main, "_call_orchestrator_json", lambda *a, **k: {"scenes": [
        {"segment_index": 1, "kind": "image", "fps": 0, "reason": "so lieu tinh"},
        {"segment_index": 2, "kind": "gif", "fps": 12, "reason": "so dem tang"},
        {"segment_index": 3, "kind": "video", "fps": 24, "reason": "mot shot lien mach"},
    ]})

    result = plan_timeline_visuals(int(project["id"]))

    assert result["by_kind"] == {"image": 1, "gif": 1, "video": 1}
    timeline = database.list_project_timeline(int(project["id"]))
    assert [item["visual_kind"] for item in timeline] == ["image", "gif", "video"]
    assert timeline[0]["visual_fps"] == 0, "anh tinh khong duoc mang fps"
    assert timeline[1]["visual_kind_reason"] == "so dem tang"


def test_gif_only_policy_never_leaves_a_scene_as_video(monkeypatch: pytest.MonkeyPatch) -> None:
    """This is the setting chosen precisely to avoid spending video credit."""
    project = _project("visual-gif")
    monkeypatch.setattr(main, "_call_orchestrator_json", lambda *a, **k: {"scenes": [
        {"segment_index": index + 1, "kind": "video", "fps": 24, "reason": "chuyen dong"}
        for index in range(3)
    ]})

    result = plan_timeline_visuals(int(project["id"]), motion_policy="gif_only")

    assert result["by_kind"] == {"gif": 3}


# --- B5: ke hoach dung --------------------------------------------------


def test_edit_plan_stores_a_transition_and_effect_per_scene(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project("edit-plan")
    monkeypatch.setattr(main, "_call_orchestrator_json", lambda *a, **k: {
        "pacing": "vua phai",
        "music_mood": "nhe",
        "scenes": [
            {"segment_index": 1, "transition": "cut", "effect": "static", "note": "giu yen de doc so"},
            {"segment_index": 2, "transition": "fade", "effect": "zoom_in", "note": ""},
            {"segment_index": 3, "transition": "cut", "effect": "zoom_out", "note": ""},
        ],
    })

    result = plan_project_edit(int(project["id"]))

    assert result["pacing"] == "vua phai"
    assert all(scene.get("segment_id") for scene in result["scenes"]), "giao dien can id de sua tay"
    timeline = database.list_project_timeline(int(project["id"]))
    assert [item["edit_transition"] for item in timeline] == ["cut", "fade", "cut"]
    assert timeline[0]["edit_effect"] == "static"


def test_edit_plan_ignores_a_scene_index_that_does_not_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hallucinated index must not write over a real scene."""
    project = _project("edit-ghost")
    monkeypatch.setattr(main, "_call_orchestrator_json", lambda *a, **k: {"scenes": [
        {"segment_index": 99, "transition": "cut", "effect": "static"},
        {"segment_index": 1, "transition": "fade", "effect": "zoom_in"},
    ]})

    result = plan_project_edit(int(project["id"]))

    assert len(result["scenes"]) == 1
    assert result["scenes"][0]["segment_index"] == 1
