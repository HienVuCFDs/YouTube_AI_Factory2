"""A short written for its own sake, built beside the long video.

The short that already existed is a re-cut of the finished long video, so it
can only be made at the end and is a condensation of something the viewer may
have seen. This one is its own video, written from the same brief, with its
own hook and its own ending.

It lives as a second script for the project. That is what makes it cheap -
shots, timeline, voice, clips and render all key off script_id and need no
changes - and also what makes it dangerous: this project has already shipped
the bug where the wrong script reached the storyboard and the voiceover, so
the tests that matter most here are the ones proving the two never mix.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from youtube_monitor.database import Database
from youtube_monitor.short_script import (
    DEFAULT_SHORT_SCRIPT_SECONDS,
    ShortScriptError,
    build_short_script,
    condense,
    estimated_seconds,
    set_script_writer,
    word_budget,
)
from tests.ui_source import studio_markup, studio_ui


LONG_SCRIPT = {
    "script_title": "Ngôi nhà giữa rừng",
    "hook": "Anh bỏ phố về rừng. Không ai tin anh trụ nổi một mùa đông.",
    "intro": "Ngày đầu tiên chỉ có một cái rìu và một tấm bạt. " * 4,
    "main_content": "Anh hạ cây làm cột. " * 60,
    "cta": "Nếu bạn thích những câu chuyện như thế này, hãy đăng ký kênh để xem phần tiếp theo nhé.",
}


class WhatTheShortSaysTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_script_writer(None)

    def test_it_is_written_to_the_time_a_short_actually_has(self) -> None:
        """Overrunning is the one failure that cannot be fixed afterwards.

        A long script is measured against a target and can be trimmed later;
        a short that runs past the limit is cut by the platform, mid-sentence,
        after the voice has already been generated and paid for.
        """
        for seconds in (30, 45, 60):
            with self.subTest(seconds=seconds):
                short = condense(LONG_SCRIPT, seconds)

                self.assertLessEqual(estimated_seconds(short), seconds)

    def test_the_sign_off_counts_against_the_budget_too(self) -> None:
        """It is spoken, so it takes time.

        Counted outside the budget, a 45-second short came out at 58.
        """
        short = condense(LONG_SCRIPT, 45)
        spoken = sum(
            len(str(short.get(field) or "").split())
            for field in ("hook", "intro", "main_content", "cta")
        )

        self.assertLessEqual(spoken, word_budget(45))
        self.assertTrue(short["cta"].strip(), "a short still needs an ending")

    def test_it_works_with_no_model_reachable(self) -> None:
        short = build_short_script({}, LONG_SCRIPT, use_model=True)

        self.assertTrue(short["hook"].strip())
        self.assertTrue(short["main_content"].strip())

    def test_a_model_that_returns_nothing_usable_does_not_lose_the_feature(self) -> None:
        set_script_writer(lambda _request: {"script_title": "", "hook": "", "main_content": "", "cta": ""})

        short = build_short_script({}, LONG_SCRIPT)

        self.assertTrue(short["main_content"].strip())

    def test_a_model_that_overruns_is_trimmed_in_whole_sentences(self) -> None:
        set_script_writer(lambda _request: {
            "script_title": "Bản short",
            "hook": "Anh bỏ phố về rừng.",
            "main_content": "Câu này dài dòng và lặp lại mãi. " * 80,
            "cta": "Đăng ký kênh nhé.",
        })

        short = build_short_script({}, LONG_SCRIPT, seconds=30)

        self.assertLessEqual(estimated_seconds(short), 30)
        self.assertTrue(short["main_content"].rstrip().endswith("."))

    def test_an_overlong_hook_cannot_bypass_the_hard_time_limit(self) -> None:
        """The hook is spoken too, so it must be trimmed just like the body."""
        set_script_writer(lambda _request: {
            "script_title": "Standalone short",
            "hook": "This hook is much too long. " * 40,
            "main_content": "This is concise body content.",
            "cta": "Subscribe for more.",
        })

        short = build_short_script({}, LONG_SCRIPT, seconds=30)

        self.assertLessEqual(estimated_seconds(short), 30)
        self.assertTrue(short["main_content"].rstrip().endswith("."))

    def test_writer_failure_falls_back_to_a_local_condensation(self) -> None:
        set_script_writer(lambda _request: (_ for _ in ()).throw(ConnectionError("offline")))

        short = build_short_script({}, LONG_SCRIPT, seconds=30)

        self.assertTrue(short["hook"].strip())
        self.assertTrue(short["main_content"].strip())
        self.assertLessEqual(estimated_seconds(short), 30)

    def test_it_refuses_when_there_is_nothing_to_write_from(self) -> None:
        with self.assertRaises(ShortScriptError):
            build_short_script({}, {})

    def test_the_writer_is_told_the_budget_it_must_hit(self) -> None:
        seen: dict = {}
        set_script_writer(lambda request: seen.update(request) or {
            "script_title": "x", "hook": "x.", "main_content": "y.", "cta": "z.",
        })

        build_short_script({}, LONG_SCRIPT, seconds=30)

        self.assertEqual(seen["seconds"], 30)
        self.assertEqual(seen["word_budget"], word_budget(30))


class TheTwoScriptsNeverMixTests(unittest.TestCase):
    """The long video's words must never reach the short, or the reverse.

    Everything downstream asks the database for "the project's script". If a
    short can answer that question, it silently replaces the long video's
    storyboard and narration - which is exactly how this project once
    generated a whole video in the wrong language.
    """

    def setUp(self) -> None:
        # A file, not ":memory:": the schema is created on open, and each
        # connection to an in-memory database is a fresh empty one.
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.database = Database(Path(self._directory.name) / "shorts.db")
        self.database.upsert_channel({
            "youtube_channel_id": "UC0000000000000000000042",
            "channel_url": "https://www.youtube.com/channel/UC0000000000000000000042",
            "title": "Kênh thử",
            "uploads_playlist_id": "UU0000000000000000000042",
        })
        self.database.upsert_video({
            "youtube_video_id": "video-short-1",
            "youtube_channel_id": "UC0000000000000000000042",
            "video_url": "https://www.youtube.com/watch?v=video-short-1",
            "title": "Video nguồn",
            "metadata_hash": "hash-short-1",
            "raw_payload": {},
        })
        project = self.database.create_production_project("video-short-1")
        self.project_id = int(project["id"])

    def _write(self, variant: str, title: str) -> dict:
        return self.database.create_project_script(
            self.project_id, script_title=title, hook=f"hook {title}",
            main_content="nội dung", variant=variant,
        )

    def test_asking_without_naming_a_kind_gets_the_long_video(self) -> None:
        long_script = self._write("long", "Bản dài")
        self._write("short", "Bản short")

        self.assertEqual(
            self.database.get_latest_project_script(self.project_id)["id"],
            long_script["id"],
        )

    def test_the_short_is_reachable_when_asked_for_by_name(self) -> None:
        self._write("long", "Bản dài")
        short = self._write("short", "Bản short")

        found = self.database.get_latest_project_script(self.project_id, variant="short")

        self.assertEqual(found["id"], short["id"])
        self.assertEqual(found["variant"], "short")

    def test_rewriting_the_short_does_not_become_the_project_script(self) -> None:
        long_script = self._write("long", "Bản dài")
        for index in range(3):
            self._write("short", f"Bản short {index}")

        self.assertEqual(
            self.database.get_latest_project_script(self.project_id)["id"],
            long_script["id"],
        )

    def test_each_kind_lists_only_its_own_versions(self) -> None:
        self._write("long", "Bản dài")
        self._write("long", "Bản dài 2")
        self._write("short", "Bản short")

        self.assertEqual(len(self.database.list_project_scripts(self.project_id)), 2)
        self.assertEqual(
            len(self.database.list_project_scripts(self.project_id, variant="short")), 1
        )
        self.assertEqual(
            len(self.database.list_project_scripts(self.project_id, variant=None)), 3
        )

    def test_a_script_written_before_the_short_existed_is_a_long_one(self) -> None:
        """Existing rows must not become shorts when the column appears."""
        script = self._write("long", "Bản cũ")

        self.assertEqual(script["variant"], "long")


class WritingStepCreatesBothScriptsTests(TheTwoScriptsNeverMixTests):
    """The normal writing action must create both videos before production.

    The long script is written by Bước 3 from the completed plan (the old
    endpoint is an adapter on that step); the Short is written beside it.
    """

    def setUp(self) -> None:
        super().setUp()
        from tests.script_fixtures import plan_project

        self.database.save_video_analysis(
            "video-short-1",
            {
                "creative_direction": "Giải thích ngắn, rõ, có ví dụ cụ thể.",
                "new_script": LONG_SCRIPT,
            },
            analysis_type="writer",
            provider="test",
        )
        self.database.save_video_analysis(
            "video-short-1", {"topic": "Ngôi nhà giữa rừng", "content_summary": "Một người dựng nhà giữa rừng."},
            analysis_type="reference", provider="test",
        )
        plan_project(self.database, self.project_id)

    def test_draft_saves_a_short_with_its_own_storyboard_and_timeline(self) -> None:
        from youtube_monitor import main

        short_draft = {
            "script_title": "Bản short độc lập",
            "hook": "Điều bất ngờ nhất xảy ra ngay giữa rừng.",
            "intro": "",
            "main_content": "Anh biến một tấm bạt thành nơi trú qua mùa đông.",
            "cta": "Theo dõi để xem tiếp.",
        }
        from tests.script_fixtures import Scripted

        with patch.object(main, "database", self.database), \
             patch.object(main, "_write_project_document"), \
             patch.object(main, "_call_orchestrator_json", Scripted()), \
             patch.object(main, "build_short_script", return_value=short_draft) as writer:
            result = main.create_project_script_draft(
                self.project_id,
                main.ScriptDraftRequest(
                    create_standalone_short=True,
                    short_seconds=30,
                    short_direction="Mở thật bất ngờ.",
                ),
            )

        short = result["short"]
        self.assertTrue(short)
        self.assertEqual(result["script"]["variant"], "long")
        self.assertEqual(short["script"]["variant"], "short")
        self.assertTrue(short["shots"])
        self.assertTrue(short["timeline"])
        self.assertTrue(all(int(item["script_id"]) == int(short["script"]["id"]) for item in short["timeline"]))
        writer.assert_called_once()
        self.assertEqual(writer.call_args.kwargs["seconds"], 30)
        self.assertEqual(writer.call_args.kwargs["direction"], "Mở thật bất ngờ.")


class TheShortsPanelIsReachableTests(unittest.TestCase):
    def setUp(self) -> None:
        from pathlib import Path

        self.page = studio_ui()

    def test_the_studio_can_write_and_build_it(self) -> None:
        self.assertIn("writeShortScript()", self.page)
        self.assertIn("queueShortVariantJob('render_short')", self.page)

    def test_what_it_writes_is_shown_without_being_asked_for(self) -> None:
        """Written but never called is the defect this project keeps hitting."""
        self.assertIn("loadShortLane();", self.page)

    def test_every_short_job_says_which_video_it_is_for(self) -> None:
        self.assertIn("variant: 'short'", self.page)

    def test_the_writing_step_offers_a_standalone_short_option(self) -> None:
        self.assertIn('id="studioCreateStandaloneShort"', self.page)
        self.assertIn('id="studioShortWorkflowNote"', self.page)
        # The short's length has one control, in the Short tab: the first
        # script and every rewrite read the same box.
        self.assertNotIn('id="studioInitialShortSeconds"', self.page)
        self.assertIn("const shortSeconds = Number($('studioShortScriptSeconds')", self.page)
        self.assertIn("create_standalone_short: createStandaloneShort", self.page)
        self.assertIn("short_seconds: shortSeconds", self.page)




    def test_finishing_a_short_job_updates_the_lane_without_a_reload(self) -> None:
        """Steps left grey after the work is done are why people re-run it."""
        self.assertIn("await loadShortLane();", self.page)


    def test_the_lane_loads_even_when_there_is_no_long_script(self) -> None:
        """A project may hold only a short, and it must still show its lane."""
        script_branch = self.page.index("if (bundle.latest_script) {")
        branch_end = self.page.index("nextStep = 3;", script_branch)

        self.assertNotIn("loadShortLane", self.page[script_branch:branch_end])
        self.assertIn("loadShortLane();", self.page)

    def test_short_is_a_choice_made_once_not_a_button_on_every_step(self) -> None:
        """Ticked at the script step, the AI writes the short alongside.

        The lane went through two wrong shapes first: buried inside the build
        step, where it vanished at every other step, then pinned above all of
        them, which put a whole second workflow on top of the first. It is a
        checkbox: a project either is making a short or is not.
        """
        self.assertIn('id="studioCreateStandaloneShort"', self.page)
        self.assertIn('onchange="syncStudioLaneTabs()"', self.page)
        self.assertIn("createStandaloneShort", self.page)

    def test_every_step_with_both_videos_switches_between_them(self) -> None:
        """One video at a time, behind two tabs, on every step that has both.

        Side-by-side columns gave each video half the width - two scripts,
        two storyboards, two players squeezed next to each other - so each
        step now shows the long video or the Short, and a tab switches.
        """
        for step in ("studioStep3", "studioStep4", "studioStep5", "studioStep6", "studioStep7"):
            with self.subTest(step=step):
                self.assertIn(f'<div class="studio-lane-split" data-lane-step="{step}">', self.page)
                self.assertIn(f'<div class="studio-lane-tabs" role="tablist" data-lane-step="{step}" hidden>', self.page)
                self.assertIn(f'data-lane-step="{step}" data-lane="long"', self.page)
                self.assertIn(f'data-lane-step="{step}" data-lane="short" hidden', self.page)
        self.assertEqual(self.page.count('class="studio-lane-tabs"'), 5)
        self.assertIn("setStudioLaneTab('long')", self.page)
        self.assertIn("setStudioLaneTab('short')", self.page)

    def test_the_short_tab_is_there_only_when_there_is_a_short(self) -> None:
        """Without a Short there is nothing to switch to, so the bar goes too."""
        self.assertIn("if (tabs) tabs.hidden = !wanted;", self.page)
        self.assertIn("const active = wanted && state.studioLane === 'short' ? 'short' : 'long';", self.page)

    def test_the_choice_of_video_holds_across_steps(self) -> None:
        """Working on the Short, the next step opens on the Short too."""
        self.assertIn("state.studioLane = lane === 'short' ? 'short' : 'long';", self.page)
        self.assertNotIn("studioLaneTabs", self.page)

    def test_nothing_is_left_of_the_side_by_side_columns(self) -> None:
        self.assertNotIn("is-split", self.page)
        self.assertNotIn("studio-lane-head", self.page)

    def test_the_page_still_parses_with_the_panes_wrapped_around_each_step(self) -> None:
        """Wrapping a step's contents is where this breaks if it breaks."""
        from html.parser import HTMLParser

        void = {"br", "img", "input", "meta", "link", "hr", "source", "col",
                "area", "base", "embed", "track", "wbr"}

        class Balance(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.stack: list[str] = []
                self.errors: list[str] = []
                self.panes: dict[str, list[str]] = {}

            def handle_starttag(self, tag, attrs):
                found = dict(attrs)
                if tag == "div" and "studio-lane-pane" in (found.get("class") or ""):
                    self.panes.setdefault(found.get("data-lane-step"), []).append(found.get("data-lane"))
                if tag not in void:
                    self.stack.append(tag)

            def handle_endtag(self, tag):
                if tag in void:
                    return
                if not self.stack or self.stack.pop() != tag:
                    self.errors.append(tag)

        parser = Balance()
        # The markup alone: the script modules are code, not tags, and
        # feeding them to an HTML parser proves nothing about the document.
        parser.feed(studio_markup())

        self.assertEqual(parser.errors, [], "mismatched tags")
        self.assertEqual(parser.stack, [], "unclosed tags")
        for step in ("studioStep3", "studioStep4", "studioStep5", "studioStep6"):
            self.assertEqual(parser.panes.get(step), ["long", "short"], step)

    def test_the_lane_progress_endpoint_exists(self) -> None:
        from youtube_monitor.main import app

        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/projects/{project_id}/short-lane", paths)

    def test_the_endpoints_exist(self) -> None:
        from youtube_monitor.main import app

        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/projects/{project_id}/short-script", paths)
        self.assertIn("/api/projects/{project_id}/short-video", paths)


class TheShortRunsWithoutTheLongVideoTests(unittest.TestCase):
    """A parallel lane is only parallel if it can start on its own.

    The short is written from the brief, not from the long video, so making
    it wait for a long script turned two lanes back into one queue wearing
    the name of two. A project may also only ever want the short.
    """

    def test_a_brief_alone_is_enough_to_write_from(self) -> None:
        brief = {
            "script_title": "Hầm trú ẩn giữa rừng",
            "hook": "Anh vào rừng với hai bàn tay trắng.",
            "main_content": "Anh đào hầm. " * 40,
            "cta": "Đăng ký kênh nhé.",
        }

        short = build_short_script({}, brief, seconds=45, use_model=False)

        self.assertTrue(short["main_content"].strip())
        self.assertLessEqual(estimated_seconds(short), 45)

    def test_the_endpoint_no_longer_demands_a_long_script_first(self) -> None:
        """The 400 that made the short wait for the long video is gone."""
        from pathlib import Path

        source = (
            Path(__file__).resolve().parent.parent
            / "youtube_monitor" / "main.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("Hãy viết kịch bản video dài trước", source)
        self.assertIn(
            'database.get_latest_project_script(project_id) or build_script_draft(bundle)',
            source,
        )


class ShortRenderReadinessTests(unittest.TestCase):
    def test_stale_paths_do_not_make_the_short_look_renderable(self) -> None:
        from youtube_monitor import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "voice.wav"
            visual = root / "scene.png"
            audio.write_bytes(b"voice")
            visual.write_bytes(b"image")
            timeline = [
                {"id": 1, "segment_index": 1, "audio_path": str(audio), "visual_path": str(visual)},
                {"id": 2, "segment_index": 2, "audio_path": str(root / "lost.wav"), "visual_path": str(root / "lost.png")},
            ]
            with patch.object(main.database, "get_latest_project_script", return_value={"id": 9, "hook": "", "intro": "", "main_content": "x", "cta": ""}), \
                 patch.object(main.database, "list_project_shots", return_value=[]), \
                 patch.object(main.database, "list_project_timeline", return_value=timeline), \
                 patch.object(main.database, "list_project_jobs", return_value=[]):
                result = main._short_lane_progress(1)

        self.assertEqual(result["voiced"], 1)
        self.assertEqual(result["with_visuals"], 1)
        self.assertEqual(result["missing_audio"], 1)
        self.assertEqual(result["missing_visual"], 1)
        self.assertFalse(result["can_render"])
        self.assertEqual(result["steps"]["voice"], False)
        self.assertEqual(result["steps"]["visuals"], False)

    def test_api_refuses_to_queue_an_incomplete_short_render(self) -> None:
        from youtube_monitor import main

        payload = main.CreateProductionJobRequest(
            job_type="render_short", provider="ffmpeg_builtin",
            confirmed=True, variant="short",
        )
        # The production gate in front of /jobs has tests of its own (test_production_gate).
        with patch.object(main.database, "get_production_project", return_value={"id": 1}), \
             patch.object(main, "_in_plan_workflow", return_value=False), \
             patch.object(main.database, "get_latest_project_script", return_value={"id": 9}), \
             patch.object(main.database, "list_project_timeline", return_value=[{"id": 1}]), \
             patch.object(main, "_short_lane_progress", return_value={
                 "can_render": False, "issues": ["1 cảnh thiếu hình", "1 cảnh thiếu tiếng"],
             }):
            with self.assertRaises(main.HTTPException) as raised:
                main.queue_project_job(1, payload)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("Short chưa thể dựng", str(raised.exception.detail))
        self.assertIn("thiếu hình", str(raised.exception.detail))

    def test_api_refuses_to_queue_an_incomplete_long_render(self) -> None:
        from youtube_monitor import main

        payload = main.CreateProductionJobRequest(
            job_type="render", provider="ffmpeg_builtin", confirmed=True,
        )
        with patch.object(main.database, "get_production_project", return_value={"id": 1}), \
             patch.object(main, "_in_plan_workflow", return_value=False), \
             patch.object(main.database, "get_latest_project_script", return_value={"id": 8}), \
             patch.object(main.database, "list_project_timeline", return_value=[{"id": 1}]), \
             patch.object(main, "_render_readiness", return_value={
                 "can_render": False, "issues": ["1 cảnh thiếu tiếng"],
             }):
            with self.assertRaises(main.HTTPException) as raised:
                main.queue_project_job(1, payload)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("Video chưa thể dựng", str(raised.exception.detail))


class TheShortStoryboardIsTheSameStoryboardTests(unittest.TestCase):
    """The short lane used its own, poorer rendering.

    It listed each scene as a line of text: no picture, no player to hear the
    generated voice, no per-scene controls, and no way to cut scenes from the
    source. The long video's storyboard has all of it, and a short's scene is
    the same kind of thing - a shot joined to its segment - so it is now drawn
    by the same code rather than by a second, thinner copy.
    """

    def setUp(self) -> None:
        self.page = studio_ui()

    def test_the_short_draws_its_cards_with_the_long_videos_renderer(self) -> None:
        self.assertIn(
            "renderStudioStoryboard(shots, lane.timeline || [], 'studioShortStoryboardCards')",
            self.page,
        )

    def test_the_renderer_can_be_pointed_at_either_container(self) -> None:
        self.assertIn(
            "function renderStudioStoryboard(shots = [], timeline = [], containerId = 'studioStoryboardResult')",
            self.page,
        )

    def test_the_short_pane_can_cut_scenes_and_make_its_voice(self) -> None:
        self.assertIn("cutShortSourceScenes()", self.page)
        self.assertIn("Cắt cảnh từ video gốc", self.page)
        self.assertIn("Tạo giọng đọc Short", self.page)

    def test_a_short_scenes_controls_can_find_the_shot_they_act_on(self) -> None:
        """The cached shot list was only ever the long video's.

        Every per-scene button on a short card looked its shot up in that
        list, failed to find it, and silently did nothing.
        """
        self.assertIn("function findStudioShot(shotId)", self.page)
        self.assertIn("state.shortShots || []", self.page)
        self.assertNotIn(
            "const shot = state.shots?.find((item) => Number(item.id) === Number(shotId));",
            self.page,
        )

    def test_the_short_lane_carries_the_shots_the_cards_need(self) -> None:
        source = (
            Path(__file__).resolve().parent.parent / "youtube_monitor" / "main.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'shots = database.list_project_shots(project_id, script_id=int(script["id"]))',
            source,
        )
        self.assertIn('"shots": shots,', source)
