from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Must run before any `youtube_monitor.*` module is imported (settings.py reads
# these once, at import time, into module-level constants) so the test suite
# never touches the real production database, backups, or project artifacts.
_TEST_STATE_DIR = tempfile.TemporaryDirectory(prefix="ytaif_test_")
_test_root = Path(_TEST_STATE_DIR.name)

os.environ.setdefault("YOUTUBE_DATA_DIR", str(_test_root / "data"))
os.environ.setdefault("YOUTUBE_DB_PATH", str(_test_root / "data" / "test.db"))
os.environ.setdefault("PRODUCTION_ARTIFACT_DIR", str(_test_root / "projects"))
