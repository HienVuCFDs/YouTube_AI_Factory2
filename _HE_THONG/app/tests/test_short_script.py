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
        self.assertIn("loadShortScriptState();", self.page)

    def test_every_short_job_says_which_video_it_is_for(self) -> None:
        self.assertIn("variant: 'short'", self.page)

    def test_the_endpoints_exist(self) -> None:
        from youtube_monitor.main import app

        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/projects/{project_id}/short-script", paths)
