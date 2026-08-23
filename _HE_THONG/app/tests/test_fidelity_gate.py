"""A retelling nobody checked must not reach a voice track or a render."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from youtube_monitor import main
from youtube_monitor.main import (
    CreateProductionJobRequest,
    UpdateScriptRequest,
    check_script_fidelity,
    database,
    queue_project_job,
    update_script,
)

SOURCE = (
    "Ngày xưa có hai anh em họ Cao, người anh tên Tân, người em tên Lang. "
    "Vua Hùng đi qua, từ đó người Việt có tục ăn trầu trong lễ cưới."
)


def _project(slug: str, workflow: str, narration: str) -> dict[str, Any]:
    video_id = f"video-gate-{slug}"
    database.upsert_channel({
        "youtube_channel_id": "UC0000000000000000000004",
        "channel_url": "https://www.youtube.com/channel/UC0000000000000000000004",
        "title": "Kenh",
        "uploads_playlist_id": "UU0000000000000000000004",
    })
    database.upsert_video({
        "youtube_video_id": video_id,
        "youtube_channel_id": "UC0000000000000000000004",
        "video_url": f"https://www.youtube.com/watch?v={video_id}",
        "title": "Su tich trau cau",
        "description": "",
        "metadata_hash": f"hash-gate-{slug}",
        "raw_payload": {},
    })
    database.save_transcript(video_id, SOURCE, transcript_format="txt", language="vi")
    project = database.create_production_project(video_id, title="Gate")
    script = database.create_project_script(int(project["id"]), script_title="Ke lai")
    database.create_project_timeline(
        int(project["id"]),
        int(script["id"]),
        [{
            "segment_index": 1,
            "start_seconds": 0,
            "duration_seconds": 8,
            "voice_text": narration,
            "subtitle_text": narration,
            "visual_prompt": "x",
            "asset_type": "source_clip",
        }],
        force=True,
    )
    database.set_project_workflow(int(project["id"]), workflow)
    return database.get_production_project(int(project["id"]))


def _queue(project_id: int, **overrides: Any) -> dict[str, Any]:
    payload = {"job_type": "voiceover", "provider": "edge_tts", "confirmed": True}
    payload.update(overrides)
    return queue_project_job(project_id, CreateProductionJobRequest(**payload))


@pytest.fixture(autouse=True)
def _no_real_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Queueing must not depend on a TTS runtime being installed here."""
    monkeypatch.setattr(main, "EDGE_TTS_RUNTIME_READY", True)


def test_an_unchecked_retelling_cannot_be_voiced() -> None:
    project = _project("unchecked", "revoice", "Vua Lê Lợi đi qua.")

    with pytest.raises(HTTPException) as caught:
        _queue(int(project["id"]))

    assert caught.value.status_code == 409
    assert "chưa soát" in str(caught.value.detail)


def test_a_retelling_that_failed_the_check_cannot_be_voiced(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project("failed", "revoice", "Vua Lê Lợi đi qua cùng con chó tên Vện.")
    monkeypatch.setattr(main, "_call_orchestrator_json", lambda *a, **k: {
        "faithful": True, "score": 9, "invented": [], "altered": [], "missing": [],
    })

    verdict = check_script_fidelity(int(project["id"]))

    # The reviewer said it was fine; the machine found two names that are not
    # in the source, and the machine decides.
    assert verdict["faithful"] is False
    assert sorted(verdict["unsourced_names"]) == ["Lợi", "Vện"]
    with pytest.raises(HTTPException) as caught:
        _queue(int(project["id"]))
    assert caught.value.status_code == 409
    assert "SAI LỆCH" in str(caught.value.detail)


def test_a_checked_retelling_goes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project("passed", "revoice", "Người anh là Tân, người em là Lang.")
    monkeypatch.setattr(main, "_call_orchestrator_json", lambda *a, **k: {
        "faithful": True, "score": 9, "invented": [], "altered": [], "missing": [],
    })

    assert check_script_fidelity(int(project["id"]))["faithful"] is True
    assert _queue(int(project["id"]))["job"]["job_type"] == "voiceover"


def test_the_other_workflow_is_not_gated() -> None:
    """It writes an original script; there is no source to be unfaithful to."""
    project = _project("content", "content", "Bat cu loi dan nao.")

    assert _queue(int(project["id"]))["job"]["job_type"] == "voiceover"


def test_a_person_can_override_deliberately() -> None:
    project = _project("override", "revoice", "Vua Lê Lợi đi qua.")

    result = _queue(int(project["id"]), force=True)

    assert result["job"]["job_type"] == "voiceover"
    script = database.get_latest_project_script(int(project["id"]))
    assert script["fidelity_status"] == "overridden", "phai ghi lai rang nguoi dung da bo qua"


def test_editing_the_script_clears_an_earlier_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Otherwise a checked script could be rewritten and still walk through."""
    project = _project("reedit", "revoice", "Người anh là Tân.")
    monkeypatch.setattr(main, "_call_orchestrator_json", lambda *a, **k: {"faithful": True, "score": 9})
    check_script_fidelity(int(project["id"]))
    script = database.get_latest_project_script(int(project["id"]))
    assert script["fidelity_status"] == "passed"

    update_script(int(script["id"]), UpdateScriptRequest(hook="Doi loi mo dau"))

    assert database.get_project_script(int(script["id"]))["fidelity_status"] == "unchecked"
    with pytest.raises(HTTPException):
        _queue(int(project["id"]))


def test_a_dry_run_is_never_gated() -> None:
    """Dry runs produce no media, and they are how people inspect the plan."""
    project = _project("dryrun", "revoice", "Vua Lê Lợi đi qua.")

    assert _queue(int(project["id"]), provider="dry_run", confirmed=False)["job"]["provider"] == "dry_run"
