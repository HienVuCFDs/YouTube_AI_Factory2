"""Retelling mode: same content, different telling — and the check that enforces it."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from youtube_monitor import main, writer
from youtube_monitor.main import check_script_fidelity, database
from youtube_monitor.writer import FAITHFUL_RETELL_MODE, WriterError, _build_prompt, system_prompt_for

FOLK_TALE = (
    "Ngay xua co hai anh em ho Cao, nguoi anh ten Tan, nguoi em ten Lang. "
    "Lang bo nha ra di, den bo suoi thi chet, hoa thanh tang da. "
    "Tan di tim em, cung chet, hoa thanh cay cau. "
    "Vua Hung di qua, tu do nguoi Viet co tuc an trau trong le cuoi."
)


def _project(slug: str, narration: list[str], with_source: bool = True) -> dict[str, Any]:
    video_id = f"video-faithful-{slug}"
    database.upsert_channel({
        "youtube_channel_id": "UC0000000000000000000006",
        "channel_url": "https://www.youtube.com/channel/UC0000000000000000000006",
        "title": "Kenh",
        "uploads_playlist_id": "UU0000000000000000000006",
    })
    database.upsert_video({
        "youtube_video_id": video_id,
        "youtube_channel_id": "UC0000000000000000000006",
        "video_url": f"https://www.youtube.com/watch?v={video_id}",
        "title": "Su tich trau cau",
        "description": "",
        "metadata_hash": f"hash-{slug}",
        "raw_payload": {},
    })
    if with_source:
        database.save_transcript(video_id, FOLK_TALE, transcript_format="txt", language="vi")
    project = database.create_production_project(video_id, title="Ke lai")
    script = database.create_project_script(int(project["id"]), script_title="Ke lai")
    database.create_project_timeline(
        int(project["id"]),
        int(script["id"]),
        [{
            "segment_index": index + 1,
            "start_seconds": index * 8,
            "duration_seconds": 8,
            "voice_text": text,
            "subtitle_text": text,
            "visual_prompt": text[:40],
            "asset_type": "source_clip",
        } for index, text in enumerate(narration)],
        force=True,
    )
    return project


# --- che do viet: khong duoc sang tac ------------------------------------


def test_retelling_mode_drops_every_instruction_to_invent() -> None:
    """The ordinary brief tells the writer not to reuse the source's plot."""
    video = {"title": "Su tich trau cau", "description": ""}

    prompt = _build_prompt(video, FOLK_TALE, remake_mode=FAITHFUL_RETELL_MODE, target_duration_seconds=120)

    for invention in ("ONE DIFFERENT animal", "Không sao chép", "đổi góc nhìn", "ai_scene"):
        assert invention not in prompt, f"loi sang tac con sot lai: {invention}"


def test_an_animal_folktale_is_not_forced_onto_a_different_animal() -> None:
    """The sharpest case: the normal path demands the animal be swapped out."""
    # Dấu tiếng Việt là bắt buộc: source_animal() dò trên tiêu đề có dấu.
    video = {"title": "SỰ TÍCH CON MÈO - Tại Sao Loài Mèo Hay Bắt Chuột", "description": ""}

    ordinary = _build_prompt(video, FOLK_TALE, remake_mode="new_angle_same_topic")
    retelling = _build_prompt(video, FOLK_TALE, remake_mode=FAITHFUL_RETELL_MODE)

    assert "ONE DIFFERENT animal" in ordinary
    assert "ONE DIFFERENT animal" not in retelling


def test_the_retelling_brief_pins_the_content_and_frees_the_telling() -> None:
    video = {"title": "Su tich trau cau", "description": ""}

    prompt = _build_prompt(video, FOLK_TALE, remake_mode=FAITHFUL_RETELL_MODE)
    brief = system_prompt_for(FAITHFUL_RETELL_MODE)

    assert "BẤT BIẾN" in brief and "CÁCH KỂ" in brief
    assert "Tan" in prompt, "nguon phai duoc dua vao prompt lam su that"
    assert "source_clip" in prompt, "hinh cua WF nay cat tu video goc"


def test_the_ordinary_brief_is_untouched() -> None:
    assert system_prompt_for("new_angle_same_topic") is writer._SYSTEM_PROMPT


def test_retelling_refuses_to_run_without_the_source() -> None:
    """With no source there is nothing to be faithful to; inventing is the risk."""
    with pytest.raises(WriterError, match="transcript"):
        _build_prompt({"title": "x", "description": ""}, None, remake_mode=FAITHFUL_RETELL_MODE)


def test_a_long_source_keeps_its_ending() -> None:
    """A folk tale is its ending; trimming only the tail would hide it."""
    body = "giua " * 30000
    long_source = "MO DAU DAC BIET. " + body + " KET CUC DAC BIET."

    prompt = _build_prompt({"title": "x", "description": ""}, long_source, remake_mode=FAITHFUL_RETELL_MODE)

    assert "MO DAU DAC BIET" in prompt
    assert "KET CUC DAC BIET" in prompt
    assert "PHẦN GIỮA BỊ LƯỢC BỚT" in prompt, "cho bi luoc phai duoc danh dau, khong lang le bo"


# --- soat do trung thanh -------------------------------------------------


def test_fidelity_check_reports_what_was_invented_and_altered(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project("wrong", ["Nguoi anh ten Lang", "Vua Le Loi di qua"])
    monkeypatch.setattr(main, "_call_orchestrator_json", lambda *a, **k: {
        "faithful": False,
        "score": 2,
        "invented": ["con cho ten Ven"],
        "altered": ["Vua Hung thanh Le Loi", "hoan ten Tan/Lang"],
        "missing": ["mau do nhu mau"],
        "ending_verdict": "Sai ket cuc",
    })

    result = check_script_fidelity(int(project["id"]))

    assert result["faithful"] is False
    assert result["score"] == 2
    assert result["altered"] == ["Vua Hung thanh Le Loi", "hoan ten Tan/Lang"]
    assert "Vua Hung thanh Le Loi" in result["script"]["review_note"]


def test_a_faithful_retelling_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Different wording alone must not cost a point."""
    project = _project("right", ["Thuo ay, hai anh em nha ho Cao giong nhau nhu duc."])
    monkeypatch.setattr(main, "_call_orchestrator_json", lambda *a, **k: {
        "faithful": True, "score": 9, "invented": [], "altered": [], "missing": [],
        "ending_verdict": "Dung ket cuc",
    })

    result = check_script_fidelity(int(project["id"]))

    assert result["faithful"] is True
    assert result["invented"] == []


def test_the_check_compares_against_the_source_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both halves must reach the reviewer, or it is grading in the dark."""
    project = _project("body", ["Ban ke lai cua toi"])
    seen: dict[str, str] = {}

    def capture(system_prompt, body, schema, stage="orchestration", **kwargs):
        seen["body"] = body
        seen["stage"] = stage
        return {"faithful": True, "score": 8}

    monkeypatch.setattr(main, "_call_orchestrator_json", capture)

    check_script_fidelity(int(project["id"]))

    assert "Vua Hung" in seen["body"], "thieu noi dung goc"
    assert "Ban ke lai cua toi" in seen["body"], "thieu ban ke lai"
    assert seen["stage"] == "quality_review", "nguoi soat phai khac nguoi viet"


def test_the_check_needs_a_source_to_compare_against() -> None:
    project = _project("nosource", ["Ban ke lai"], with_source=False)

    with pytest.raises(HTTPException) as caught:
        check_script_fidelity(int(project["id"]))

    assert caught.value.status_code == 400
    assert "transcript" in str(caught.value.detail).lower()
