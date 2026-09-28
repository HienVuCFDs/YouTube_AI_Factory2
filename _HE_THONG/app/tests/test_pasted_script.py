import pytest
from fastapi import HTTPException
from youtube_monitor import main
from youtube_monitor.database import Database


@pytest.fixture
def script_db(tmp_path, monkeypatch):
    db = Database(tmp_path / "scripts.db")
    monkeypatch.setattr(main, "database", db)
    monkeypatch.setattr(main, "_write_project_document", lambda *args: None)
    return db


def test_paste_creates_project_and_exact_narration_without_ai(script_db):
    text = "Der Wald ist still.\n\nEin Licht erscheint."
    result = main.import_pasted_script(main.ImportScriptRequest(text=text, title="Im Wald", language="de"))
    assert result["project"]["workflow"] == "content"
    assert result["script"]["main_content"] == text
    assert result["script"]["hook"] == result["script"]["intro"] == result["script"]["cta"] == ""
    assert [item["voice_text"] for item in result["timeline"]] == ["Der Wald ist still.", "Ein Licht erscheint."]
    assert all(not item["audio_path"] and not item["visual_path"] for item in result["timeline"])


def test_paste_new_version_keeps_old_media_and_other_variant(script_db):
    first = main.import_pasted_script(main.ImportScriptRequest(text="Old narration."))
    project_id = first["project"]["id"]
    old_segment = first["timeline"][0]["id"]
    script_db.update_project_timeline_segment(old_segment, audio_path="old.mp3", visual_path="old.mp4")
    short = main.import_pasted_script(main.ImportScriptRequest(project_id=project_id, text="Hola mundo.", variant="short", language="es"))
    new = main.import_pasted_script(main.ImportScriptRequest(project_id=project_id, text="New narration."))
    assert script_db.get_latest_project_script(project_id)["id"] == new["script"]["id"]
    assert script_db.get_latest_project_script(project_id, variant="short")["id"] == short["script"]["id"]
    assert script_db.get_project_timeline_segment(old_segment)["audio_path"] == "old.mp3"
    assert new["timeline"][0]["voice_text"] == "New narration."
    assert not new["timeline"][0]["audio_path"]


def test_blank_paste_is_rejected_without_creating_project(script_db):
    with pytest.raises(HTTPException) as error:
        main.import_pasted_script(main.ImportScriptRequest(text=" \n\t "))
    assert error.value.status_code == 400
    assert script_db.list_production_projects() == []


def test_unknown_project_does_not_create_another_one(script_db):
    with pytest.raises(HTTPException) as error:
        main.import_pasted_script(main.ImportScriptRequest(project_id=999999, text="Narration"))
    assert error.value.status_code == 404
