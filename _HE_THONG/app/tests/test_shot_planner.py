import unittest

from youtube_monitor.shot_planner import build_shot_plan, shots_to_markdown
from tests.ui_source import studio_ui


class ShotPlannerTests(unittest.TestCase):
    def test_build_shot_plan_splits_script_sections(self):
        project = {"id": 2, "title": "Project"}
        script = {
            "id": 5,
            "script_title": "Script",
            "hook": "Hook line",
            "intro": "Intro line",
            "main_content": "1. First point\n2. Second point",
            "cta": "CTA line",
        }
        shots = build_shot_plan(project, script)
        self.assertEqual([shot["section"] for shot in shots], ["hook", "intro", "main", "main", "cta"])
        self.assertEqual(shots[0]["asset_type"], "talking_head")
        self.assertEqual(shots[2]["asset_type"], "broll")
        self.assertIn("First point", shots[2]["narration"])
        self.assertGreaterEqual(shots[0]["duration_seconds"], 6)

    def test_shots_to_markdown_exports_prompts(self):
        markdown = shots_to_markdown(
            {"id": 2, "title": "Project"},
            {"id": 5},
            [
                {
                    "shot_index": 1,
                    "section": "hook",
                    "asset_type": "talking_head",
                    "duration_seconds": 8,
                    "status": "planned",
                    "narration": "Hook",
                    "visual_prompt": "Prompt",
                }
            ],
        )
        self.assertIn("# Shot list: Project", markdown)
        self.assertIn("## Shot 1", markdown)
        self.assertIn("### Visual prompt", markdown)

    def test_build_shot_plan_prefers_original_ai_scene_blueprints(self):
        shots = build_shot_plan(
            {"id": 2, "title": "Mèo"},
            {"hook": "H", "intro": "I", "main_content": "B", "cta": "C"},
            {"scene_blueprints": [{
                "order": 2, "section": "main", "narration": "Chú mèo bước vào khu vườn.",
                "visual_prompt": "original AI scene, orange cat in a sunlit garden, slow dolly", "asset_type": "ai_scene", "duration_seconds": 7,
            }]},
        )
        self.assertEqual(len(shots), 1)
        self.assertEqual(shots[0]["asset_type"], "ai_scene")
        self.assertIn("orange cat", shots[0]["visual_prompt"])


if __name__ == "__main__":
    unittest.main()

def test_a_freshly_written_script_keeps_the_scene_list_it_came_with() -> None:
    """Writing a script records the writer's analysis and then the script row,
    milliseconds apart. The freshness test compared the script against the
    moment the analysis was stored, so a brand new script always looked newer
    than its own blueprints: the app asked an AI to break the piece into
    scenes, threw the answer away every single time, and chopped the prose by
    line instead.
    """
    from unittest.mock import patch

    from youtube_monitor.main import GenerateShotsRequest, database, generate_project_shots

    project = database.create_idea_project("Nguon goc Trai Dat", title="Blueprint gate")
    project_id = int(project["id"])
    script = database.create_project_script(
        project_id,
        script_title="Trai Dat",
        hook="Cau mo dau cua kich ban.",
        intro="",
        main_content="Cau giua cua kich ban.",
        cta="Cau ket cua kich ban.",
    )
    blueprints = {"scene_blueprints": [
        {"order": 1, "narration": "Cau mo dau cua kich ban."},
        {"order": 2, "narration": "Cau giua cua kich ban."},
        {"order": 3, "narration": "Cau ket cua kich ban."},
    ]}
    analysis = {"created_at": str(script["created_at"]), "result": blueprints}

    # Only the writer's analysis: a project with no source analysis and no
    # plan is a manual one, outside the plan workflow, where this still holds.
    with patch.object(database, "get_video_analysis",
                      side_effect=lambda video_id, analysis_type="reference": analysis if analysis_type == "writer" else None):
        result = generate_project_shots(project_id, GenerateShotsRequest(force=True))

    assert [shot["section"] for shot in result["shots"]] == ["hook", "main", "cta"]


def test_a_script_edited_after_it_was_written_drops_the_scene_list() -> None:
    """The guard this replaces existed for a real reason: a rewrite must not
    be narrated in the first draft's sentences."""
    from unittest.mock import patch

    from youtube_monitor.main import GenerateShotsRequest, database, generate_project_shots

    project = database.create_idea_project("Nguon goc Trai Dat", title="Blueprint gate 2")
    project_id = int(project["id"])
    script = database.create_project_script(
        project_id, script_title="Ban viet lai", hook="", intro="",
        main_content="Cau hoan toan moi cua ban viet lai.", cta="",
    )
    stale = {"scene_blueprints": [{"order": 1, "narration": "Cau cu tu ban nhap dau tien."}]}
    # Recorded before the script, but the script has moved on since.
    edited = dict(script)
    edited["updated_at"] = "2099-01-01T00:00:00+00:00"

    with patch.object(database, "get_video_analysis",
                      side_effect=lambda video_id, analysis_type="reference": (
                          {"created_at": str(script["created_at"]), "result": stale} if analysis_type == "writer" else None)),             patch.object(database, "get_latest_project_script", return_value=edited):
        result = generate_project_shots(project_id, GenerateShotsRequest(force=True))

    assert "viet lai" in result["shots"][0]["narration"]


def test_a_scene_is_never_given_less_time_than_its_line_needs() -> None:
    """The writer estimates a duration before a word has been spoken, and it
    came back as a flat ten seconds for lines that take seventeen to read.
    Believing it would have cut the narration off mid-sentence."""
    from youtube_monitor.shot_planner import build_shot_plan

    line = (
        "Hơn 70% bề mặt Trái Đất là nước, nhưng chúng ta vẫn gọi nó là Trái Đất. "
        "Hành tinh đang quay giữa không gian này đã hình thành như thế nào?"
    )
    blueprints = {"scene_blueprints": [{"order": 1, "narration": line, "duration_seconds": 10}]}

    plan = build_shot_plan({"title": "p"}, {"version": 1}, blueprints)

    assert plan[0]["duration_seconds"] > 10


def test_a_longer_scene_the_writer_asked_for_is_honoured() -> None:
    """Asking for more room than the sentence needs is a pacing choice."""
    from youtube_monitor.shot_planner import build_shot_plan

    blueprints = {"scene_blueprints": [
        {"order": 1, "narration": "Một câu ngắn.", "duration_seconds": 12},
    ]}

    plan = build_shot_plan({"title": "p"}, {"version": 1}, blueprints)

    assert plan[0]["duration_seconds"] == 12


def test_the_writers_own_section_names_still_open_and_close_the_film() -> None:
    """A writer naming its sections - "Mở vấn đề", "Sự sống và tổng kết" - had
    every one flattened to "main", losing the opening and closing treatment
    those names exist to select."""
    from youtube_monitor.shot_planner import build_shot_plan

    blueprints = {"scene_blueprints": [
        {"order": 1, "section": "Mở vấn đề", "narration": "Câu mở đầu."},
        {"order": 2, "section": "Vũ trụ sơ khai", "narration": "Câu giữa."},
        {"order": 3, "section": "Sự sống và tổng kết", "narration": "Câu kết."},
    ]}

    plan = build_shot_plan({"title": "p"}, {"version": 1}, blueprints)

    assert [shot["section"] for shot in plan] == ["hook", "main", "cta"]


def test_a_verified_caller_keeps_the_scene_list_on_a_later_script_row() -> None:
    """The version number stands in for "this was rewritten". A second script
    row was enough to discard a scene list the AI had already written, and the
    prose got chopped by line instead."""
    from youtube_monitor.shot_planner import build_shot_plan

    blueprints = {"scene_blueprints": [
        {"order": 1, "narration": "Câu của blueprint."},
    ]}
    later = {"version": 2, "hook": "", "intro": "", "main_content": "Câu của kịch bản.", "cta": ""}

    assert build_shot_plan({"title": "p"}, later, blueprints)[0]["narration"] == "Câu của kịch bản."
    verified = build_shot_plan({"title": "p"}, later, blueprints, blueprints_verified=True)
    assert verified[0]["narration"] == "Câu của blueprint."


def test_a_rewritten_script_is_spoken_in_its_own_words() -> None:
    """A new script was being narrated with the first draft's sentences.

    The writer's scene blueprints are attached to the video, not to a script,
    and build_shot_plan returned them whenever they existed. So a rewrite
    produced the same shot list, the same timeline and the same voice — the
    user asked for a new script and heard the old one.
    """
    blueprints = {"scene_blueprints": [
        {"narration": "Cau tu ban nhap dau tien", "section": "main", "duration_seconds": 6},
    ]}
    rewritten = {
        "version": 2, "script_title": "Ban viet lai",
        "hook": "", "intro": "", "main_content": "Cau moi cua ban viet lai", "cta": "",
    }
    shots = build_shot_plan({"title": "p"}, rewritten, writer_content=blueprints)
    assert "viet lai" in shots[0]["narration"]


def test_the_first_draft_still_uses_the_blueprints_it_came_from() -> None:
    blueprints = {"scene_blueprints": [
        {"narration": "Cau tu blueprint", "section": "main", "duration_seconds": 6},
    ]}
    first = {
        "version": 1, "script_title": "Ban dau",
        "hook": "", "intro": "", "main_content": "Chu cua kich ban", "cta": "",
    }
    shots = build_shot_plan({"title": "p"}, first, writer_content=blueprints)
    assert shots[0]["narration"] == "Cau tu blueprint"


def test_a_rewrite_with_no_words_of_its_own_keeps_the_blueprints() -> None:
    """An empty rewrite must not leave the project with no narration at all."""
    blueprints = {"scene_blueprints": [
        {"narration": "Cau tu blueprint", "section": "main", "duration_seconds": 6},
    ]}
    empty = {"version": 3, "script_title": "Rong", "hook": "", "intro": "", "main_content": "", "cta": ""}
    shots = build_shot_plan({"title": "p"}, empty, writer_content=blueprints)
    assert shots[0]["narration"] == "Cau tu blueprint"


def test_the_timeline_endpoint_says_whether_it_rebuilt() -> None:
    """Without force an existing timeline came back untouched and silent, so
    pressing the button after a rewrite looked like it had worked."""
    from youtube_monitor import main
    import inspect

    source = inspect.getsource(main.generate_project_timeline)
    assert '"rebuilt"' in source
    assert '"stale"' in source
    assert '"shot_count"' in source


def test_the_page_refuses_to_voice_a_stale_timeline() -> None:
    from pathlib import Path

    page = studio_ui()
    assert "timelineResult?.stale" in page
    assert "force: true" in page


def test_voice_generation_refuses_an_outdated_storyboard_too() -> None:
    """Editing a script in place must not voice the old storyboard."""
    from youtube_monitor import main
    import inspect

    source = inspect.getsource(main.generate_project_shots)
    assert '"stale"' in source
    assert "storyboard_stale" in source


def test_a_section_heading_is_not_something_to_read_aloud() -> None:
    """The writer lays a script out with headings, and every line became a
    scene. Half of one script was headings, so twenty-six of its fifty-five
    scenes were the narrator saying "Cảnh 5 · main_content" out loud."""
    from youtube_monitor.shot_planner import is_section_heading

    for heading in (
        "Cảnh 3 · intro",
        "Cảnh 5 · main_content",
        "Scene 7: main",
        "Phần 2",
        "Cảnh 12 · cta",
    ):
        assert is_section_heading(heading), heading


def test_a_heading_the_writer_named_itself_is_not_read_aloud() -> None:
    """A writer given room to structure its own script names its scenes -
    "Cảnh 3 · Các ngôi sao và nguyên tố" - and a pattern that only knew the
    section keywords let those through. In a 70 second film the narrator spent
    eleven seconds reading the table of contents, over three scenes of its
    own."""
    from youtube_monitor.shot_planner import is_section_heading

    for heading in (
        "Cảnh 3 · Các ngôi sao và nguyên tố",
        "Cảnh 4 · Trái Đất nóng và Mặt Trăng",
        "Cảnh 5 · Nước, biển và đất",
        "Scene 2: The beginning",
        "Phần 1 — Mở đầu",
    ):
        assert is_section_heading(heading), heading


def test_a_heading_in_the_writers_own_scene_list_is_dropped_too() -> None:
    """The heading filter guarded only the path taken when the writer returns
    prose. A writer that returns a scene list - the path actually used - put
    three headings on screen as scenes and had them read out."""
    from youtube_monitor.shot_planner import build_shot_plan

    blueprints = {"scene_blueprints": [
        {"order": 1, "section": "hook", "narration": "Hơn 70% bề mặt Trái Đất là nước."},
        {"order": 2, "section": "main", "narration": "Cảnh 3 · Các ngôi sao và nguyên tố"},
        {"order": 3, "section": "main", "narration": "Tiếp đó, các ngôi sao xuất hiện."},
    ]}
    plan = build_shot_plan({"title": "Trái Đất"}, {"version": 1}, blueprints)

    spoken = [shot["narration"] for shot in plan]
    assert spoken == [
        "Hơn 70% bề mặt Trái Đất là nước.",
        "Tiếp đó, các ngôi sao xuất hiện.",
    ]


def test_a_sentence_that_opens_with_a_scene_number_is_still_spoken() -> None:
    """Dropping a line the writer meant to be heard costs more than reading
    one label, so anything sentence-shaped stays."""
    from youtube_monitor.shot_planner import is_section_heading

    for narration in (
        "Cảnh 3 là nơi mọi thứ bắt đầu, và rồi mọi thứ thay đổi.",
        "Cảnh 3 - Trái Đất nguội dần. Nước xuất hiện sau đó.",
        "Cảnh 6 · một đoạn dài kể lại toàn bộ hành trình của hành tinh xanh này qua nhiều tỉ năm",
    ):
        assert not is_section_heading(narration), narration


def test_a_line_that_only_starts_like_a_heading_is_kept() -> None:
    from youtube_monitor.shot_planner import is_section_heading

    for narration in (
        "Cảnh 5 · main_content: Yvan bắt đầu đào",
        "All right. You have all heard him say it",
        "Cảnh sát điều tra vụ án suốt đêm",
    ):
        assert not is_section_heading(narration), narration


def test_headings_never_reach_the_shot_list() -> None:
    script = {
        "version": 2, "script_title": "t", "hook": "", "intro": "",
        "main_content": chr(10).join([
            "Cảnh 1 · main_content",
            "Yvan bắt đầu đào",
            "Cảnh 2 · main_content",
            "Anh dựng khung",
        ]),
        "cta": "",
    }
    shots = build_shot_plan({"title": "p"}, script)
    narrations = [shot["narration"] for shot in shots]
    assert narrations == ["Yvan bắt đầu đào", "Anh dựng khung"], narrations


def test_the_voiceover_skips_a_scene_that_is_only_a_heading() -> None:
    """A timeline built before the planner learned to drop them still holds
    them, and reading one aloud wastes a scene and the picture it wants."""
    import inspect

    from youtube_monitor import production_worker

    source = inspect.getsource(production_worker.run_voiceover_job)
    assert "is_section_heading" in source
    assert "heading_scenes" in source


def test_a_timeline_of_nothing_but_headings_is_refused() -> None:
    import inspect

    from youtube_monitor import production_worker

    source = inspect.getsource(production_worker.run_voiceover_job)
    assert "chỉ là tiêu đề mục" in source


def test_the_storyboard_keeps_its_timeline_when_shots_are_regenerated() -> None:
    from pathlib import Path

    page = studio_ui()
    assert "renderStudioStoryboard(shots, state.timeline);" in page
    assert "renderStudioStoryboard(shots, []);" not in page
