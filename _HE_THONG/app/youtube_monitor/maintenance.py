from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKUP_PREFIX = "youtube_monitor-"


def list_database_backups(directory: Path) -> list[dict[str, Any]]:
    """Return only app-owned SQLite snapshots, newest first."""
    if not directory.is_dir():
        return []
    backups = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.name.startswith(BACKUP_PREFIX) and path.suffix.lower() == ".db"
    ]
    backups.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    return [
        {
            "name": path.name,
            "path": str(path),
            "bytes": path.stat().st_size,
            "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        }
        for path in backups
    ]


def prune_database_backups(directory: Path, keep: int = 14) -> dict[str, Any]:
    """Remove oldest app-owned snapshots while retaining a bounded recent set."""
    if not 1 <= keep <= 100:
        raise ValueError("Số bản sao lưu cần giữ phải nằm trong khoảng 1–100")
    backups = list_database_backups(directory)
    removed: list[dict[str, Any]] = []
    for backup in backups[keep:]:
        path = Path(backup["path"])
        path.unlink()
        removed.append(backup)
    return {"kept": min(len(backups), keep), "removed": removed}
