"""Antigravity sidecar: hand queued YT Factory image jobs to an AG agent.

Run only under Antigravity Sidecars. ``agentapi`` is supplied by Antigravity
to the sidecar PATH, so the regular Windows shell never needs it installed.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

FACTORY = os.getenv("YOUTUBE_FACTORY_URL", "http://127.0.0.1:8787").rstrip("/")
WORKSPACE = Path(r"F:\YouTube_AI_Factory")
AGY = Path(os.getenv("ANTIGRAVITY_CLI", str(Path(os.getenv("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe")))


def get_next() -> dict | None:
    with urllib.request.urlopen(f"{FACTORY}/api/antigravity/next-scene-job", timeout=20) as response:
        return json.loads(response.read().decode("utf-8")).get("job")


def dispatch(job: dict) -> None:
    project_id, segment_id, job_id = int(job["project_id"]), int(job["timeline_segment_id"]), int(job["id"])
    prompt = str(job.get("prompt") or "")
    text = f'''You are the YT Factory image worker. Complete exactly one job.
Project ID: {project_id}; storyboard segment ID: {segment_id}; Antigravity job ID: {job_id}.
Use youtube_factory_get_storyboard for this project. Create exactly ONE cinematic image using generate_image with this prompt:
{prompt}
No text, captions, logos or watermarks. Save the image in the returned import_folder. Then call youtube_factory_import_asset with project_id, segment_id and the saved file path. Finally call youtube_factory_complete_antigravity_scene with job_id {job_id} and the asset_id returned by import. Do not merely explain; execute these tools.'''
    if not AGY.is_file():
        raise RuntimeError(f"Không tìm thấy Antigravity CLI: {AGY}")
    subprocess.run(
        [str(AGY), "-p", text, "--output-format", "json", "--dangerously-skip-permissions", "--print-timeout", "10m"],
        cwd=str(WORKSPACE), check=True, timeout=660,
    )


def main() -> None:
    while True:
        try:
            job = get_next()
            if job:
                dispatch(job)
                time.sleep(20)
            else:
                time.sleep(5)
        except Exception as exc:
            print(f"YT Factory sidecar error: {exc}", flush=True)
            time.sleep(15)


if __name__ == "__main__":
    main()
