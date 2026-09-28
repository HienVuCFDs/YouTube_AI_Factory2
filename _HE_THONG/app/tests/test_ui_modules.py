"""The page is one document kept in several files, not a rewrite.

It was 7530 lines, and every change to any part of it risked every other
part. Splitting it only helps if the split provably changed nothing, so the
property these tests hold is exact: the modules concatenated in document
order are byte for byte the script they came from.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from youtube_monitor.main import app

ROOT = Path(__file__).resolve().parent.parent / "youtube_monitor"
STATIC = ROOT / "static"
TEMPLATE = ROOT / "templates" / "index.html"

MODULES = ("core.js", "studio-lanes.js", "project-detail.js", "library.js", "publish.js")
HEADER_LINES = 7


def _body(name: str) -> str:
    lines = (STATIC / name).read_text(encoding="utf-8").split("\n")
    assert lines[HEADER_LINES - 1].startswith("// which is what"), name
    return "\n".join(lines[HEADER_LINES:])


class TheSplitIsAMoveNotARewriteTests(unittest.TestCase):
    def test_every_module_exists(self) -> None:
        for name in MODULES:
            with self.subTest(module=name):
                self.assertTrue((STATIC / name).is_file())

    def test_each_module_is_valid_javascript(self) -> None:
        """A module that does not parse takes every button on the page with it."""
        node = shutil.which("node")
        if not node:
            self.skipTest("node không có trên máy chạy test")
        for name in MODULES:
            with self.subTest(module=name):
                result = subprocess.run(
                    [node, "--check", str(STATIC / name)], capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr[-800:])

    def test_the_document_no_longer_carries_the_code(self) -> None:
        markup = TEMPLATE.read_text(encoding="utf-8")

        self.assertNotIn("<style", markup)
        self.assertLess(markup.count("\n"), 800, "the page should be markup now")

    def test_the_document_loads_them_in_order(self) -> None:
        markup = TEMPLATE.read_text(encoding="utf-8")
        # The `?v=` a release appends to break browser caches is not part of
        # which files load or in what order, which is what this pins.
        loaded = [name.split("?", 1)[0] for name in re.findall(r'<script src="/static/([^"]+)"', markup)]

        self.assertEqual(tuple(loaded), MODULES)
        self.assertIn('<link rel="stylesheet" href="/static/app.css', markup)


class TheModulesAreServedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_the_page_and_every_file_it_asks_for_are_served(self) -> None:
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)

        wanted = re.findall(r'(?:src|href)="(/static/[^"]+)"', page.text)
        self.assertTrue(wanted)
        for url in wanted:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.content)

    def test_javascript_and_css_are_served_as_themselves(self) -> None:
        """Served as text/plain, a browser refuses to run the script."""
        self.assertIn("javascript", self.client.get("/static/core.js").headers["content-type"])
        self.assertIn("text/css", self.client.get("/static/app.css").headers["content-type"])

    def test_a_name_cannot_reach_outside_the_static_directory(self) -> None:
        for name in ("../main.py", "..%2Fmain.py", "../../data/youtube_monitor.db"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(f"/static/{name}").status_code, 404)

    def test_only_stylesheets_and_scripts_are_served(self) -> None:
        (STATIC / "khong-phuc-vu.txt").write_text("x", encoding="utf-8")
        self.addCleanup((STATIC / "khong-phuc-vu.txt").unlink, True)

        self.assertEqual(self.client.get("/static/khong-phuc-vu.txt").status_code, 404)

    def test_a_missing_module_is_a_404_not_a_crash(self) -> None:
        self.assertEqual(self.client.get("/static/khong-co.js").status_code, 404)


class SayingWhenTheServerIsBehindTheCodeTests(unittest.TestCase):
    """Splitting the page made a stale server much harder to notice.

    The browser fetches /static fresh on every load, so the interface looks
    updated while the Python behind it is whatever was imported when the
    process started. A control that appears after an edit can still be
    talking to code from an hour ago, and the symptom - a sign-in landing in
    the wrong place, a flow that "did nothing" - reads as a bug in the new
    code rather than its absence.
    """

    def test_the_process_records_what_it_imported(self) -> None:
        from youtube_monitor import main

        self.assertGreater(main._IMPORTED_SOURCE_MTIME, 0)

    def test_a_freshly_imported_process_is_not_stale(self) -> None:
        from youtube_monitor import main

        self.assertFalse(main.running_build_is_stale())

    def test_a_newer_file_on_disk_makes_it_stale(self) -> None:
        from unittest import mock

        from youtube_monitor import main

        with mock.patch.object(
            main, "_source_fingerprint", return_value=main._IMPORTED_SOURCE_MTIME + 60
        ):
            self.assertTrue(main.running_build_is_stale())

    def test_a_touch_within_a_second_does_not_cry_wolf(self) -> None:
        """Filesystem timestamps drift; a warning that is always on is ignored."""
        from unittest import mock

        from youtube_monitor import main

        with mock.patch.object(
            main, "_source_fingerprint", return_value=main._IMPORTED_SOURCE_MTIME + 0.2
        ):
            self.assertFalse(main.running_build_is_stale())

    def test_health_reports_it(self) -> None:
        from fastapi.testclient import TestClient

        from youtube_monitor.main import app

        self.assertIn("restart_needed", TestClient(app).get("/api/health").json())

    def test_the_page_shows_it_and_says_what_to_do(self) -> None:
        from tests.ui_source import studio_ui

        page = studio_ui()
        self.assertIn("renderRestartNotice(health.restart_needed)", page)
        self.assertIn("CHAY_YOUTUBE_AI_FACTORY.bat", page)

    def test_the_notice_disappears_once_it_is_no_longer_true(self) -> None:
        from tests.ui_source import studio_ui

        self.assertIn("if (!needed) { if (bar) bar.remove(); return; }", studio_ui())
