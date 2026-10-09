"""Demo data for Bước 5 in a TEST database - three planned projects, the model faked, no AI or API called.

Run by CHAY_THU_NGHIEM_DB_TAM.bat after it has pointed the app at the test
folder; it refuses any database or project folder whose path does not say
THU_NGHIEM, so it can never write to the real ones. A database that already
has projects is left as it is.

    A - storyboard, voices and pictures, edit planned in the EditDocument, NOT applied yet
    B - like A before planning, then its script edited in place: its storyboard is stale
    C - storyboard, voices and pictures, never planned

Pictures and voices are real small files (a coloured PNG, a silent WAV) so the
cards show them; nothing in them is meant to be watched.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import wave
import zlib
from pathlib import Path

MARK = "THU_NGHIEM"
APP_DIR = Path(__file__).resolve().parent.parent / "app"


def _refuse(why: str) -> None:
    print(f"[seed] DỪNG, không ghi gì: {why}")
    sys.exit(2)


for key in ("YOUTUBE_DB_PATH", "YOUTUBE_DATA_DIR", "PRODUCTION_ARTIFACT_DIR"):
    if MARK.lower() not in os.environ.get(key, "").lower():
        _refuse(f"{key} phải trỏ vào thư mục thử nghiệm ({MARK}); hiện là {os.environ.get(key)!r}")

# Only now may the app be imported: it opens YOUTUBE_DB_PATH, which is the test one.
sys.path.insert(0, str(APP_DIR))
os.chdir(APP_DIR)
from unittest import mock  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from tests.script_fixtures import Scripted, planned_project  # noqa: E402
from tests.test_edit_planner import Director  # noqa: E402
from youtube_monitor import main  # noqa: E402

if MARK.lower() not in str(main.database.path).lower():
    _refuse("app không mở DB thử nghiệm")


def _png(path: Path, rgb: tuple[int, int, int], width: int = 320, height: int = 180) -> None:
    row = b"\x00" + bytes(rgb) * width
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)  # noqa: E731
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


def _wav(path: Path, seconds: float, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * max(seconds, 0.5)))


def main_seed() -> int:
    if main.database.list_production_projects(limit=1):
        print("[seed] DB thử nghiệm đã có dự án: giữ nguyên, không seed lại.")
        return 0
    files = Path(os.environ["PRODUCTION_ARTIFACT_DIR"]) / "_demo_media"
    files.mkdir(parents=True, exist_ok=True)
    scripted, director = Scripted(), Director()
    route = lambda s, u, schema, **o: (director if schema is main._EDIT_DOCUMENT_PLAN_SCHEMA else scripted)(s, u, schema, **o)  # noqa: E731
    timing = lambda seg: {"duration_seconds": float(seg.get("duration_seconds") or 1), "words": [],  # noqa: E731
                          "timing_basis": "estimated", "audio_signature": ""}
    colours = [(38, 70, 120), (120, 52, 38), (40, 110, 70), (100, 60, 120)]
    with mock.patch.object(main, "_call_orchestrator_json", route), mock.patch.object(main, "scene_speech_timing", timing), \
            mock.patch.object(main.production_worker, "enqueue", mock.Mock(return_value={"id": 1, "status": "queued"})), \
            TestClient(main.app) as client:
        db = main.database
        made = {}
        for name in ("A", "B", "C"):
            project_id = planned_project(db)
            for step in ("script/generate", "shots/generate", "timeline/generate"):
                body = {"options": {}} if step == "script/generate" else {}
                response = client.post(f"/api/projects/{project_id}/{step}", json=body)
                if response.status_code != 200:
                    print(f"[seed] {name}: {step} lỗi {response.status_code}: {response.text[:300]}")
                    return 1
            script_id = int(db.get_latest_project_script(project_id)["id"])
            for index, segment in enumerate(db.list_project_timeline(project_id, script_id=script_id)):
                audio = files / f"voice-{segment['id']}.wav"
                picture = files / f"picture-{segment['id']}.png"
                _wav(audio, float(segment.get("duration_seconds") or 1))
                _png(picture, colours[index % len(colours)])
                db.update_project_timeline_segment(int(segment["id"]), audio_path=str(audio), visual_path=str(picture))
            made[name] = project_id
        planned = client.post(f"/api/projects/{made['A']}/steps/edit_plan", json={"options": {}}).json()["result"]
        script = client.get(f"/api/projects/{made['B']}/script").json()
        lines = script["main_content"].split("\n")
        at = len(script["document"]["sections"][0]["spoken_lines"])
        lines[at] = lines[at].replace(" ", " mỗi ", 1).rsplit(" ", 1)[0] + "."
        client.patch(f"/api/scripts/{script['id']}", json={"main_content": "\n".join(lines)})
    print("[seed] Đã tạo dữ liệu demo: " + json.dumps(
        {"A (đã lập, chưa áp)": made["A"], "B (storyboard cũ)": made["B"], "C (chưa lập)": made["C"],
         "A planner": planned.get("status"), "model gọi thật": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main_seed())
