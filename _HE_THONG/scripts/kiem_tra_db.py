"""Read-only check, before starting the app: which database it would open and what starting it would do there.

    py -3.13 _HE_THONG\\scripts\\kiem_tra_db.py

Resolves the database exactly as the app does when started by
CHAY_YOUTUBE_AI_FACTORY.bat (working directory _HE_THONG\\app, variables of
this shell first, then _HE_THONG\\config\\.env, then the default), and
reports - without writing anything, not even SQLite's -wal/-shm files
(immutable read) - what app startup would do to it:

* database.initialize(): tables it would create (a schema migration);
* the workers: jobs left queued or running that they would pick up or requeue
  (agent tasks, analysis, production, scene generation, publishing);
* resync_timeline_segment_states(): timeline rows whose status it may rewrite.

It never imports the app (importing it creates folders) and never opens the
database for writing.
"""

from __future__ import annotations

import hashlib
import os
import re
import socket
import sqlite3
import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent          # _HE_THONG
APP_DIR = SYSTEM_ROOT / "app"                                  # the launcher's working directory
ENV_PATH = SYSTEM_ROOT / "config" / ".env"
DATABASE_PY = APP_DIR / "youtube_monitor" / "database.py"
ACTIVE = ("queued", "running", "pending", "scheduled", "retry", "retrying", "processing", "claimed", "in_progress")


def _dotenv() -> dict[str, str]:
    """What settings._load_dotenv would set: only keys the shell has not set already."""
    found: dict[str, str] = {}
    if not ENV_PATH.exists():
        return found
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        found.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return found


def resolve() -> tuple[Path, str]:
    """(database path, where it came from) - settings.DATA_DIR / DB_PATH, relative paths from the launcher's folder."""
    env = _dotenv()

    def value(key: str) -> tuple[str | None, str]:
        if os.environ.get(key) is not None:
            return os.environ[key], f"biến môi trường {key}"
        if key in env:
            return env[key], f"{ENV_PATH} ({key})"
        return None, "mặc định"

    def absolute(text: str) -> Path:
        path = Path(text)
        return path if path.is_absolute() else (APP_DIR / path)

    db, source = value("YOUTUBE_DB_PATH")
    if db is not None:
        return absolute(db).resolve(), source
    data, source = value("YOUTUBE_DATA_DIR")
    data_dir = absolute(data) if data is not None else SYSTEM_ROOT / "data"
    return (data_dir / "youtube_monitor.db").resolve(), (source if data is not None else "mặc định (_HE_THONG\\data)")


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _port_in_use(port: int = 8787) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    path, source = resolve()
    print(f"DB mà launcher chính thức sẽ mở: {path}")
    print(f"  lấy từ: {source}")
    print(f"  cổng 8787: {'ĐANG BỊ DÙNG (có app khác đang chạy?)' if _port_in_use() else 'trống'}")
    if not path.exists():
        print("  File chưa tồn tại: app sẽ TẠO MỚI một DB rỗng ở đây.")
        return 0
    wal = [Path(f"{path}{suffix}") for suffix in ("-wal", "-shm")]
    print(f"  kích thước: {path.stat().st_size:,} byte · md5 {_md5(path)}")
    if any(item.exists() and item.stat().st_size for item in wal):
        print("  CẢNH BÁO: có file -wal/-shm khác rỗng: app có thể đang chạy, số liệu dưới đây có thể chưa đầy đủ.")
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        wanted = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", DATABASE_PY.read_text(encoding="utf-8")))
        missing = sorted(wanted - tables)
        print(f"\nMigration khi khởi động (database.initialize): "
              + (f"sẽ TẠO {len(missing)} bảng: {', '.join(missing)}" if missing else "không thiếu bảng nào (có thể vẫn thêm cột)"))
        print("\nViệc đang chờ mà worker sẽ nhận hoặc xếp lại khi app khởi động:")
        busy = 0
        for table in sorted(tables):
            columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
            if "status" not in columns:
                continue
            rows = connection.execute(
                f'SELECT status, COUNT(*) FROM "{table}" WHERE status IN ({",".join("?" * len(ACTIVE))}) GROUP BY status',
                ACTIVE).fetchall()
            for status, count in rows:
                busy += count
                print(f"  - {table}: {count} '{status}'")
        if not busy:
            print("  (không có)")
        if "project_timeline_segments" in tables:
            count = connection.execute("SELECT COUNT(*) FROM project_timeline_segments").fetchone()[0]
            print(f"\nresync_timeline_segment_states: có thể ghi lại trạng thái của tối đa {count} cảnh timeline.")
        projects = connection.execute("SELECT COUNT(*) FROM production_projects").fetchone()[0] \
            if "production_projects" in tables else 0
        print(f"Số dự án trong DB: {projects}")
    finally:
        connection.close()
    print("\nKẾT LUẬN: chạy CHAY_YOUTUBE_AI_FACTORY.bat sẽ mở DB trên"
          + (", tạo bảng mới" if missing else "")
          + (f", và worker sẽ xử lý {busy} việc đang chờ (có thể gọi AI/API thật)" if busy else "")
          + ". Muốn thử an toàn hãy dùng CHAY_THU_NGHIEM_DB_TAM.bat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
