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
    """The normal writing action must create both videos before production."""

    def setUp(self) -> None:
        super().setUp()
        self.database.save_video_analysis(
            "video-short-1",
            {
                "creative_direction": "Giải thích ngắn, rõ, có ví dụ cụ thể.",
                "new_script": LONG_SCRIPT,
            },
            analysis_type="writer",
            provider="test",
        )

    def test_draft_saves_a_short_with_its_own_storyboard_and_timeline(self) -> None:
        from youtube_monitor import main

        short_draft = {
            "script_title": "Bản short độc lập",
            "hook": "Điều bất ngờ nhất xảy ra ngay giữa rừng.",
            "intro": "",
            "main_content": "Anh biến một tấm bạt thành nơi trú qua mùa đông.",
            "cta": "Theo dõi để xem tiếp.",
        }
        with patch.object(main, "database", self.database), \
             patch.object(main, "_write_project_document"), \
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

        self.page = (
            Path(__file__).resolve().parent.parent
            / "youtube_monitor" / "templates" / "index.html"
        ).read_text(encoding="utf-8")

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
        self.assertIn('id="studioInitialShortSeconds"', self.page)
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

    def test_each_step_shows_both_lanes_side_by_side(self) -> None:
        """Beside each other, not one behind the other.

        Tabs made the two lanes take turns, so the short was only ever seen
        by leaving the long video. Split columns keep both in view, which is
        the point of writing them together.
        """
        for step in ("studioStep3", "studioStep4", "studioStep5", "studioStep6"):
            with self.subTest(step=step):
                self.assertIn(f'<div class="studio-lane-split" data-lane-step="{step}">', self.page)
                self.assertIn(f'data-lane-step="{step}" data-lane="long"', self.page)
                self.assertIn(f'data-lane-step="{step}" data-lane="short"', self.page)

    def test_nothing_is_left_of_the_tab_switching(self) -> None:
        self.assertNotIn("setStudioLane", self.page)
        self.assertNotIn("studio-lane-tab", self.page)

    def test_the_short_column_is_hidden_until_the_box_is_ticked(self) -> None:
        """Un-splitting is not enough; the column has to go.

        Left in the grid it would still take half the width away from the
        long video on a project that is not making a short.
        """
        self.assertIn('data-lane="short" hidden', self.page)
        self.assertIn("if (short) short.hidden = !wanted;", self.page)
        self.assertIn("split.classList.toggle('is-split', wanted)", self.page)

    def test_the_columns_are_labelled_only_when_there_are_two(self) -> None:
        self.assertIn('<div class="studio-lane-head">Video dài</div>', self.page)
        self.assertIn('<div class="studio-lane-head">Short</div>', self.page)
        self.assertIn(".studio-lane-head { display: none;", self.page)
        self.assertIn(".studio-lane-split.is-split .studio-lane-head { display: block; }", self.page)

    def test_the_split_stacks_rather_than_squeezing_on_a_narrow_screen(self) -> None:
        """Two columns of storyboard in 500px is unusable."""
        self.assertIn("@media (max-width: 1180px)", self.page)

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
        parser.feed(self.page)

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


class TheShortStoryboardIsTheSameStoryboardTests(unittest.TestCase):
    """The short lane used its own, poorer rendering.

    It listed each scene as a line of text: no picture, no player to hear the
    generated voice, no per-scene controls, and no way to cut scenes from the
    source. The long video's storyboard has all of it, and a short's scene is
    the same kind of thing - a shot joined to its segment - so it is now drawn
    by the same code rather than by a second, thinner copy.
    """

    def setUp(self) -> None:
        self.page = (
            Path(__file__).resolve().parent.parent
            / "youtube_monitor" / "templates" / "index.html"
        ).read_text(encoding="utf-8")

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
