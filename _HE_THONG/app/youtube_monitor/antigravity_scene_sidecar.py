"""Antigravity sidecar: hand queued YT Factory image jobs to an AG agent.

Run only under Antigravity Sidecars. ``agentapi`` is supplied by Antigravity
to the sidecar PATH, so the regular Windows shell never needs it installed.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

FACTORY = os.getenv("YOUTUBE_FACTORY_URL", "http://127.0.0.1:8787").rstrip("/")
WORKSPACE = Path(r"F:\YouTube_AI_Factory")
AGY = Path(os.getenv("ANTIGRAVITY_CLI", str(Path(os.getenv("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe")))


def get_next() -> dict | None:
    with urllib.request.urlopen(f"{FACTORY}/api/antigravity/next-scene-job", timeout=20) as response:
        return json.loads(response.read().decode("utf-8")).get("job")


def fail(job_id: int, error: str) -> None:
    """Report a claimed job as failed so it doesn't stay stuck at 'running'
    forever with no error message (that used to happen whenever dispatch()
    raised: the job had already been claimed by get_next(), but nothing told
    the app it wouldn't finish, so its status just froze mid-progress)."""
    try:
        request = urllib.request.Request(
            f"{FACTORY}/api/antigravity/scene-jobs/{job_id}/fail?error={urllib.parse.quote(error[:500])}",
            data=b"{}", method="POST", headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read()
    except Exception as exc:  # noqa: BLE001 - best-effort; don't let a failed failure-report crash the loop
        print(f"YT Factory sidecar: could not report job {job_id} as failed: {exc}", flush=True)


_ASPECT_RATIO_LABEL = {"1280:720": "16:9 ngang", "720:1280": "9:16 dọc", "1024:1024": "1:1 vuông"}


def dispatch(job: dict) -> None:
    project_id, segment_id, job_id = int(job["project_id"]), int(job["timeline_segment_id"]), int(job["id"])
    prompt = str(job.get("prompt") or "")
    ratio_label = _ASPECT_RATIO_LABEL.get(str(job.get("ratio") or ""), "16:9 ngang")
    text = f'''You are the YT Factory image worker. Complete exactly one job.
Project ID: {project_id}; storyboard segment ID: {segment_id}; Antigravity job ID: {job_id}.
Use youtube_factory_get_storyboard for this project. Create exactly ONE cinematic image using generate_image with this prompt (aspect ratio {ratio_label}; pass that aspect ratio to generate_image if it accepts one):
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
        except Exception as exc:  # noqa: BLE001 - can't reach the app; nothing was claimed yet, just retry
            print(f"YT Factory sidecar error: {exc}", flush=True)
            time.sleep(15)
            continue
        if not job:
            time.sleep(5)
            continue
        try:
            dispatch(job)
            time.sleep(20)
        except Exception as exc:  # noqa: BLE001 - job is already claimed ('running'); must report failure, not just log it
            print(f"YT Factory sidecar error on job {job.get('id')}: {exc}", flush=True)
            fail(int(job["id"]), str(exc))
            time.sleep(15)


if __name__ == "__main__":
    main()
