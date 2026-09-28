"""A generation that was paid for is not thrown away over a failed move.

gflow 0.79 downloads the finished video and then moves it to `-o`. When that
move raised, the run crashed after the credit had been spent: a real 1.9 MB
mp4 sat in the working directory while the job was marked failed - and the
retry that followed would spend another generation to make the same thing.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from youtube_monitor import gflow_bridge


def _log(path: Path, size: int) -> str:
    return "\n".join([
        json.dumps({"event": "browser.engine_selected", "engine": "playwright"}),
        json.dumps({"event": "migrated.download", "path": str(path), "bytes": size}),
        json.dumps({"event": "error_unhandled", "exception_class": "OSError"}),
    ])


class RescuingWhatTheRunAlreadyProducedTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def test_the_downloaded_file_is_found_in_the_log(self) -> None:
        produced = self.root / "87bd9d2c.mp4"
        produced.write_bytes(b"0" * 2048)

        found = gflow_bridge.downloaded_media_path(_log(produced, 2048))

        self.assertEqual(found, produced)

    def test_a_path_the_log_names_but_disk_does_not_have_is_ignored(self) -> None:
        missing = self.root / "gone.mp4"

        self.assertIsNone(gflow_bridge.downloaded_media_path(_log(missing, 2048)))

    def test_an_empty_file_is_not_treated_as_a_result(self) -> None:
        empty = self.root / "empty.mp4"
        empty.write_bytes(b"")

        self.assertIsNone(gflow_bridge.downloaded_media_path(_log(empty, 0)))

    def test_a_log_without_any_download_yields_nothing(self) -> None:
        self.assertIsNone(gflow_bridge.downloaded_media_path(
            json.dumps({"event": "error_raised", "error_class": "ProfileLockedError"})
        ))

    def test_the_rescued_file_is_moved_to_where_the_caller_asked(self) -> None:
        produced = self.root / "raw.mp4"
        produced.write_bytes(b"0" * 4096)
        wanted = self.root / "out" / "scene-01.mp4"
        error = gflow_bridge.GFlowCliError("crashed", kind="timeout")
        error.stdout = _log(produced, 4096)

        rescued = gflow_bridge._rescue_download(error, wanted)

        self.assertEqual(rescued, wanted)
        self.assertEqual(wanted.stat().st_size, 4096)
        self.assertFalse(produced.exists())

    def test_a_failure_with_nothing_to_rescue_still_raises(self) -> None:
        error = gflow_bridge.GFlowCliError("crashed", kind="timeout")
        error.stdout = json.dumps({"event": "error_raised"})

        self.assertIsNone(gflow_bridge._rescue_download(error, self.root / "out.mp4"))



class ReadingBackWhereFlowActuallyPutItTests(unittest.TestCase):
    """gflow renames the file to the format it got and reports the path one
    level down, so asking for `out.png` and reading `out.png` back found
    nothing while a real jpg sat beside it."""

    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def test_the_path_inside_results_is_found(self) -> None:
        produced = self.root / "picture.jpg"
        produced.write_bytes(b"0" * 1024)

        found = gflow_bridge.result_local_path({"results": [{"local_path": str(produced)}]})

        self.assertEqual(found, produced)

    def test_a_top_level_path_still_works(self) -> None:
        produced = self.root / "clip.mp4"
        produced.write_bytes(b"0" * 1024)

        self.assertEqual(gflow_bridge.result_local_path({"local_path": str(produced)}), produced)

    def test_a_path_that_is_not_on_disk_is_not_returned(self) -> None:
        self.assertIsNone(gflow_bridge.result_local_path(
            {"results": [{"local_path": str(self.root / "missing.jpg")}]}
        ))

    def test_nothing_reported_means_nothing_returned(self) -> None:
        self.assertIsNone(gflow_bridge.result_local_path({"status": "ok"}))

if __name__ == "__main__":
    unittest.main()
