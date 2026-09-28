"""The four checks that shipped as endpoints with nothing covering them."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from youtube_monitor import main
from youtube_monitor.main import (
    ApplyVisualFallbackRequest,
    ApplyEditBeatsRequest,
    PlanEditBeatsRequest,
    UpdateScenePlanRequest,
    _edit_preflight,
    apply_project_visual_fallbacks,
    apply_timeline_edit_beats,
    apply_project_edit_plan,
    approve_project_edit_plan,
    database,
    get_project_edit_plan,
    list_project_storyboard_required_jobs,
    plan_project_edit,
    plan_timeline_edit_beats,
    plan_timeline_visuals,
    review_project_script,
    review_project_voice,
    update_project_edit_plan_scene,
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
    assert [item["visual_kind"] for item in timeline] == ["", "", ""]
    approve_project_edit_plan(int(project["id"]))
    apply_project_edit_plan(int(project["id"]))
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


def test_edit_plan_stays_draft_until_it_is_approved_and_applied(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert result["status"] == "draft"
    assert all(scene.get("segment_id") for scene in result["scenes"]), "giao dien can id de sua tay"
    timeline = database.list_project_timeline(int(project["id"]))
    assert [item["edit_transition"] for item in timeline] == ["", "", ""]

    approved = approve_project_edit_plan(int(project["id"]))
    assert approved["status"] == "approved"
    applied = apply_project_edit_plan(int(project["id"]))
    assert applied["status"] == "ready"
    assert applied["applied_scenes"] == 3
    timeline = database.list_project_timeline(int(project["id"]))
    assert [item["edit_transition"] for item in timeline] == ["cut", "fade", "cut"]
    assert timeline[0]["edit_effect"] == "static"


def test_edit_plan_carries_visual_transform_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project("edit-transform")
    monkeypatch.setattr(main, "_call_orchestrator_json", lambda *a, **k: {
        "scenes": [
            {
                "segment_index": 1,
                "kind": "video",
                "transition": "cut",
                "effect": "static",
                "content_dna": {
                    "core_point": "Nhan vat mo hop",
                    "must_keep": ["hop go", "bat ngo"],
                    "characters": ["A"],
                    "facts": [],
                    "emotion": "ngac nhien",
                    "source_cue": "00:12",
                },
                "visual_strategy": "ai_video_from_image",
                "provider": "gflow_cli",
                "source_dependency": "low",
                "risk_level": "low",
                "transform_actions": [{"type": "ai_rebuild", "description": "Dung anh moi de tai dung khoanh khac"}],
                "required_assets": [{"kind": "image", "provider": "chatgpt_web_image", "prompt": "wooden box reveal"}],
                "overlays": [{"kind": "callout", "text": "Chi tiet quan trong", "position": "top_right",
                              "style": "card", "animation": "pop", "start_seconds": 0.5, "end_seconds": 2.0}],
            }
        ],
    })

    drafted = plan_project_edit(int(project["id"]))

    scene = drafted["scenes"][0]
    assert scene["content_dna"]["core_point"] == "Nhan vat mo hop"
    assert scene["visual_strategy"] == "ai_video_from_image"
    assert scene["provider"] == "gflow_cli"
    assert scene["source_dependency"] == "low"
    assert scene["risk_level"] == "low"
    assert scene["required_assets"][0]["prompt"] == "wooden box reveal"
    assert scene["overlays"][0]["animation"] == "pop"
    assert scene["overlays"][0]["start_seconds"] == 0.5

    approve_project_edit_plan(int(project["id"]))
    applied = apply_project_edit_plan(int(project["id"]))
    stored = database.list_project_timeline(int(project["id"]))[0]
    assert stored["visual_strategy"] == "ai_video_from_image"
    assert stored["visual_provider"] == "gflow_cli"
    assert stored["source_dependency"] == "low"
    assert stored["risk_level"] == "low"
    assert json.loads(stored["content_dna"])["emotion"] == "ngac nhien"
    assert json.loads(stored["transform_actions"])[0]["type"] == "ai_rebuild"
    assert json.loads(stored["overlays"])[0]["style"] == "card"
    assert applied["required_jobs_count"] == 3
    planned_asset_job = next(job for job in applied["required_jobs"] if job["prompt"] == "wooden box reveal")
    assert planned_asset_job["job_kind"] == "image"
    assert planned_asset_job["provider"] == "chatgpt_web_image"
    assert database.list_scene_generation_jobs(int(project["id"])) == []

    listed = list_project_storyboard_required_jobs(int(project["id"]))
    assert listed["total"] == 3
    assert any(job["prompt"] == "wooden box reveal" for job in listed["required_jobs"])


def test_reup_legacy_ai_plan_is_upgraded_to_visual_transform_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project("edit-reup-legacy")
    database.set_project_workflow(int(project["id"]), "reup")
    for segment in database.list_project_timeline(int(project["id"])):
        database.update_project_timeline_segment(int(segment["id"]), asset_type="source_clip")
    monkeypatch.setattr(main, "_call_orchestrator_json", lambda *a, **k: {
        "scenes": [
            {"segment_index": 1, "kind": "video", "transition": "cut", "effect": "static"},
            {"segment_index": 2, "kind": "video", "transition": "fade", "effect": "static"},
            {"segment_index": 3, "kind": "video", "transition": "cut", "effect": "static"},
        ],
    })

    result = plan_project_edit(int(project["id"]))

    strategies = [scene["visual_strategy"] for scene in result["scenes"]]
    assert strategies != ["source_clip_short", "source_clip_short", "source_clip_short"]
    assert "source_freeze_frame" in strategies
    assert "motion_graphics" in strategies
    assert result["scenes"][2]["provider"] == "motion_graphics"
    assert result["scenes"][2]["source_dependency"] == "none"


def test_edit_plan_falls_back_to_transform_plan_when_ai_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project("edit-reup-fallback")
    database.set_project_workflow(int(project["id"]), "reup")
    for segment in database.list_project_timeline(int(project["id"])):
        database.update_project_timeline_segment(int(segment["id"]), asset_type="source_clip")

    def fail(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise main.LlmError("orchestrator offline")

    monkeypatch.setattr(main, "_call_orchestrator_json", fail)

    result = plan_project_edit(int(project["id"]))

    assert result["planner_error"] == "orchestrator offline"
    assert len(result["scenes"]) == 3
    assert {scene["visual_strategy"] for scene in result["scenes"]} >= {"source_freeze_frame", "motion_graphics"}
    assert any(scene["required_assets"] for scene in result["scenes"])


def test_applying_a_plan_is_atomic_when_one_scene_is_invalid() -> None:
    project = _project("edit-plan-atomic")
    timeline = database.list_project_timeline(int(project["id"]))
    script_id = int(timeline[0]["script_id"])
    scenes = [
        {
            "segment_id": int(timeline[0]["id"]),
            "kind": "image",
            "transition": "cut",
            "effect": "static",
        },
        {
            "segment_id": 999999999,
            "kind": "video",
            "transition": "fade",
            "effect": "zoom_in",
        },
    ]

    with pytest.raises(ValueError):
        database.apply_project_edit_plan_scenes(
            int(project["id"]), script_id, scenes,
        )

    unchanged = database.get_project_timeline_segment(int(timeline[0]["id"]))
    assert unchanged["visual_kind"] == ""
    assert unchanged["edit_transition"] == ""


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


def test_edit_plan_becomes_stale_when_a_scene_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project("edit-stale")
    monkeypatch.setattr(main, "_call_orchestrator_json", lambda *a, **k: {"scenes": [
        {"segment_index": 1, "transition": "cut", "effect": "static"},
    ]})
    drafted = plan_project_edit(int(project["id"]))
    approve_project_edit_plan(int(project["id"]))

    first = database.list_project_timeline(int(project["id"]))[0]
    database.update_project_timeline_segment(int(first["id"]), voice_text="Loi thoai da doi")

    result = get_project_edit_plan(int(project["id"]))
    assert drafted["source_revision"] != result["plan"]["current_source_revision"]
    assert result["status"] == "stale"
    assert result["plan"]["stale"] is True
    with pytest.raises(HTTPException) as caught:
        apply_project_edit_plan(int(project["id"]))
    assert caught.value.status_code == 409


def test_a_draft_scene_can_be_edited_without_touching_the_timeline(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project("edit-draft-field")
    monkeypatch.setattr(main, "_call_orchestrator_json", lambda *a, **k: {"scenes": [
        {"segment_index": 1, "kind": "image", "transition": "cut", "effect": "static"},
    ]})
    drafted = plan_project_edit(int(project["id"]))
    segment_id = int(drafted["scenes"][0]["segment_id"])

    result = update_project_edit_plan_scene(
        int(project["id"]),
        segment_id,
        UpdateScenePlanRequest(visual_kind="gif", transition="fade"),
    )

    saved_scene = result["plan"]["plan"]["scenes"][0]
    assert saved_scene["kind"] == "gif"
    assert saved_scene["transition"] == "fade"
    segment = database.get_project_timeline_segment(segment_id)
    assert segment["visual_kind"] == ""
    assert segment["edit_transition"] == ""
    with pytest.raises(HTTPException) as invalid:
        update_project_edit_plan_scene(
            int(project["id"]), segment_id,
            UpdateScenePlanRequest(overlays=[{"kind": "title", "text": "Sai thời điểm", "end_seconds": 999}]),
        )
    assert invalid.value.status_code == 422


def test_scene_edit_beat_plan_saves_overlays_and_materializes_sfx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project("scene-edit-layers")
    segment = database.list_project_timeline(int(project["id"]))[0]
    monkeypatch.setattr(main, "_call_orchestrator_json", lambda *a, **k: {
        "beats": [
            {
                "source_kind": "primary",
                "duration_seconds": 6,
                "effect": "zoom_in",
                "transition": "cut",
                "prompt": "",
            },
        ],
        "overlays": [
            {
                "kind": "callout",
                "text": "Cùng 80 triệu",
                "position": "top_center",
                "style": "card",
                "animation": "pop",
                "start_seconds": 0.2,
                "end_seconds": 1.8,
            },
        ],
        "sound_cues": [
            {
                "type": "whoosh",
                "start_seconds": 0.2,
                "end_seconds": 0.7,
                "intensity": "low",
            },
        ],
        "reason": "Nhấn ý chính bằng chữ và SFX nhẹ.",
    })

    planned = plan_timeline_edit_beats(int(segment["id"]), PlanEditBeatsRequest(max_beats=4))

    assert planned["overlays"][0]["text"] == "Cùng 80 triệu"
    saved = database.get_project_timeline_segment(int(segment["id"]))
    assert json.loads(saved["overlays"])[0]["animation"] == "pop"
    assert json.loads(saved["sound_cues"])[0]["type"] == "whoosh"

    applied = apply_timeline_edit_beats(
        int(segment["id"]),
        ApplyEditBeatsRequest(image_provider="gemini_image", confirmed=True),
    )

    assert applied["sound_cues"][0]["asset_path"]
    assert Path(applied["sound_cues"][0]["asset_path"]).is_file()


def test_preflight_reports_missing_and_fallback_scenes(tmp_path: Path) -> None:
    project = _project("edit-preflight")
    timeline = database.list_project_timeline(int(project["id"]))
    visual = tmp_path / "visual.png"
    audio = tmp_path / "voice.wav"
    visual.write_bytes(b"png")
    audio.write_bytes(b"wav")
    database.update_project_timeline_segment(
        int(timeline[0]["id"]), visual_path=str(visual), audio_path=str(audio)
    )
    database.update_project_timeline_segment(
        int(timeline[1]["id"]), visual_path=str(visual), audio_path=str(audio), asset_type="fallback"
    )

    result = _edit_preflight(int(project["id"]))

    assert result["total"] == 3
    assert result["ready"] == 2
    assert result["missing_visual"] == 1
    assert result["missing_audio"] == 1
    assert result["fallback"] == 1
    assert result["can_render"] is False


def test_visual_fallback_requires_explicit_confirmation() -> None:
    project = _project("edit-fallback-confirm")
    with pytest.raises(HTTPException) as caught:
        apply_project_visual_fallbacks(
            int(project["id"]),
            ApplyVisualFallbackRequest(confirmed=False),
        )
    assert caught.value.status_code == 400
