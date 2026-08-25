"""Each workflow described once, in its own file."""

from __future__ import annotations

import pytest

from youtube_monitor import workflows
from youtube_monitor.main import database, list_workflows
from youtube_monitor.writer import FAITHFUL_RETELL_MODE


def test_every_workflow_is_reachable_by_its_key() -> None:
    for key in workflows.keys():
        assert workflows.get(key).key == key


def test_an_unknown_key_falls_back_to_the_default() -> None:
    """A stale value in a saved session or an old project row must not stop
    the studio opening."""
    assert workflows.get("khong-ton-tai").key == workflows.DEFAULT_KEY
    assert workflows.get(None).key == workflows.DEFAULT_KEY
    assert workflows.get("").key == workflows.DEFAULT_KEY


def test_the_retelling_workflow_carries_the_faithful_writing_mode() -> None:
    """It used to be decided by a string comparison in the browser, which is
    how the reup workflow got analysed under remake rules."""
    assert workflows.get("reup").script_mode == FAITHFUL_RETELL_MODE


def test_each_workflow_says_where_its_pictures_come_from() -> None:
    assert workflows.get("content").scene_asset_type == "ai_scene"
    assert workflows.get("reup").scene_asset_type == "source_clip"


def test_a_retelling_does_not_go_looking_for_motifs_to_invent_from() -> None:
    assert workflows.get("reup").uses_web_research is False
    assert workflows.get("content").uses_web_research is True


def test_every_workflow_names_all_its_steps() -> None:
    """The wizard labels its tabs from this; a missing entry leaves a step
    with whatever name the other workflow gave it."""
    for workflow in workflows.all_workflows():
        assert len(workflow.steps) == 7, workflow.key
        assert all(str(step).strip() for step in workflow.steps), workflow.key


def test_every_workflow_states_where_it_stands() -> None:
    """A picker that only listed capabilities would invite starting on the
    half that does not work."""
    for workflow in workflows.all_workflows():
        assert workflow.state.strip(), workflow.key
        assert workflow.notes, workflow.key


def test_the_browser_is_served_the_same_definitions() -> None:
    """One source of truth: a second copy in the page is how a workflow came
    to mean one thing on screen and another in the writer."""
    served = list_workflows()

    assert served["default"] == workflows.DEFAULT_KEY
    assert [item["key"] for item in served["workflows"]] == workflows.keys()
    for item in served["workflows"]:
        assert item["script_mode"] == workflows.get(item["key"]).script_mode
        assert item["steps"] == list(workflows.get(item["key"]).steps)


def test_a_project_stores_a_resolved_key(tmp_path) -> None:
    """An unknown key must not be written to a project, or nothing later
    knows how to run it."""
    database.upsert_channel({
        "youtube_channel_id": "UC0000000000000000000013",
        "channel_url": "https://x", "title": "K", "uploads_playlist_id": "U",
    })
    database.upsert_video({
        "youtube_video_id": "video-wf-key", "youtube_channel_id": "UC0000000000000000000013",
        "video_url": "https://x", "title": "N", "description": "",
        "metadata_hash": "h-wfkey", "raw_payload": {},
    })
    project = database.create_production_project("video-wf-key", title="WF")

    stored = database.set_project_workflow(int(project["id"]), "khong-ton-tai")

    assert stored["workflow"] == workflows.DEFAULT_KEY


def test_workflows_are_immutable() -> None:
    """Shared definitions that could be edited in place would drift apart."""
    with pytest.raises(Exception):
        workflows.get("reup").script_mode = "new_angle_same_topic"  # type: ignore[misc]
