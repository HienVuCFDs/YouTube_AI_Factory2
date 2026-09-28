from __future__ import annotations

from pathlib import Path

from youtube_monitor.database import Database
from youtube_monitor.project_context import (
    PROJECT_CONTEXT_VERSION,
    SOURCE_PACKAGE_VERSION,
    build_project_context,
    build_source_package,
)
from youtube_monitor.timeline_builder import build_timeline


def test_source_package_for_idea_project_is_compact(tmp_path: Path) -> None:
    database = Database(tmp_path / "context.db")
    project = database.create_idea_project("Lam video giai thich AI Director", title="AI Director")

    package = build_source_package(database, int(project["id"]))

    assert package is not None
    assert package["source_package_version"] == SOURCE_PACKAGE_VERSION
    assert package["source"]["kind"] == "prompt_text"
    assert package["source"]["title"] == "AI Director"
    assert package["transcript"]["available"] is False
    assert "article_url" in package["not_first_class_yet"]


def test_project_context_summarizes_script_storyboard_timeline(tmp_path: Path) -> None:
    database = Database(tmp_path / "context.db")
    project = database.create_idea_project("Lam video ve workflow dung video bang Astra", title="Astra workflow")
    script = database.create_project_script(
        int(project["id"]),
        script_title="Astra workflow",
        hook="Astra can plan the edit.",
        intro="The app measures and executes.",
        main_content="Astra decides scenes. The renderer follows executable plans.",
        cta="Review before publishing.",
        status="approved",
    )
    assert script is not None
    shots = database.create_project_shots(
        int(project["id"]),
        int(script["id"]),
        [
            {
                "shot_index": 1,
                "section": "hook",
                "narration": "Astra can plan the edit.",
                "visual_prompt": "Talking head with bold title",
                "asset_type": "ai_scene",
                "duration_seconds": 6,
            },
            {
                "shot_index": 2,
                "section": "main",
                "narration": "The renderer follows executable plans.",
                "visual_prompt": "Timeline with graphics",
                "asset_type": "motion_graphics",
                "duration_seconds": 8,
            },
        ],
        force=True,
    )
    assert shots
    timeline = build_timeline(project, script, shots)
    database.create_project_timeline(int(project["id"]), int(script["id"]), timeline, force=True)

    context = build_project_context(database, int(project["id"]))

    assert context is not None
    assert context["context_version"] == PROJECT_CONTEXT_VERSION
    assert context["project"]["workflow"] == "content"
    assert context["script"]["title"] == "Astra workflow"
    assert context["storyboard"]["shots"] == 2
    assert context["timeline"]["segments"] == 2
    assert context["timeline"]["asset_type_counts"]["motion_graphics"] == 1
    assert context["current_step"]["index"] == 5



def test_project_context_summarizes_applied_edit_plan(tmp_path: Path) -> None:
    database = Database(tmp_path / "context.db")
    project = database.create_idea_project("Lam video co chu pop va am thanh whoosh", title="Edit plan")
    script = database.create_project_script(
        int(project["id"]),
        script_title="Edit plan",
        hook="Show a bold price.",
        status="approved",
    )
    assert script is not None
    shots = database.create_project_shots(
        int(project["id"]),
        int(script["id"]),
        [{
            "shot_index": 1,
            "section": "hook",
            "narration": "Show a bold price.",
            "visual_prompt": "Talking head with price callout",
            "asset_type": "ai_scene",
            "duration_seconds": 4,
        }],
        force=True,
    )
    timeline = database.create_project_timeline(
        int(project["id"]), int(script["id"]), build_timeline(project, script, shots), force=True
    )
    scene = {
        "segment_id": timeline[0]["id"],
        "segment_index": 1,
        "kind": "image",
        "visual_strategy": "ai_image",
        "transition": "cut",
        "effect": "zoom_in",
        "overlays": [{
            "kind": "callout", "text": "Giá 299k", "style": "card", "animation": "pop",
            "position": "top_center", "start_seconds": 0.2, "end_seconds": 2.0,
        }],
        "sound_cues": [{"type": "whoosh", "start_seconds": 0.2, "end_seconds": 0.7}],
        "required_assets": [{"kind": "sound_effect", "prompt": "soft whoosh"}],
    }
    database.save_project_edit_plan(
        int(project["id"]), int(script["id"]), "rev", {"scenes": [scene], "workflow": "content"}, status="ready"
    )
    database.apply_project_edit_plan_scenes(int(project["id"]), int(script["id"]), [scene])

    context = build_project_context(database, int(project["id"]))

    assert context is not None
    assert context["edit_plan"]["available"] is True
    assert context["edit_plan"]["sound_cue_count"] == 1
    assert context["edit_plan"]["overlay_count"] == 1
    assert context["timeline"]["graphic_overlays"] == 1
    assert context["timeline"]["sound_cues"] == 1
    assert context["timeline"]["edited_segments"] == 1
