from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from youtube_monitor.maintenance import list_database_backups, prune_database_backups


class MaintenanceTests(unittest.TestCase):
    def test_prune_keeps_newest_app_backups_and_ignores_other_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(3):
                path = root / f"youtube_monitor-20260811T00000{index}Z.db"
                path.write_bytes(b"backup")
                path.touch()
            (root / "unrelated.db").write_bytes(b"keep")
            result = prune_database_backups(root, keep=2)
            self.assertEqual(result["kept"], 2)
            self.assertEqual(len(result["removed"]), 1)
            self.assertEqual(len(list_database_backups(root)), 2)
            self.assertTrue((root / "unrelated.db").is_file())

    def test_prune_rejects_unsafe_retention(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                prune_database_backups(Path(directory), keep=0)


if __name__ == "__main__":
    unittest.main()
