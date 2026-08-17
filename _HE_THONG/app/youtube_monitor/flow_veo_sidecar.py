"""Flow (Veo 3) sidecar: hand queued YT Factory video jobs to Google Flow.

Uses YOUR OWN logged-in Google AI Pro/Ultra subscription (labs.google/flow)
instead of a metered API key — mirrors the existing antigravity_scene_sidecar.py
pull-queue pattern (GET next job -> do the work -> upload result -> POST
complete), but drives a real browser with Playwright instead of delegating to
an external agent CLI.

*** SETUP (do this once) ***
1. pip install -r requirements.txt        (already includes playwright)
2. python -m playwright install chromium  (downloads the browser binary)
3. python flow_veo_sidecar.py --login
   A real Chrome window opens at labs.google/flow. Log into your Google
   account by hand, wait until the Flow home page has fully loaded, then
   press Enter in this terminal. Your session is saved to
   FLOW_VEO_PROFILE_DIR and reused by every future run — you will not need
   to log in again unless Google signs you out.
4. python flow_veo_sidecar.py --recon
   Opens Flow (already logged in) and calls page.pause(), which launches
   the Playwright Inspector. Use it to find the real selectors for the
   prompt textbox, the submit button, and the finished-clip download
   control, then update PROMPT_INPUT_SELECTORS / SUBMIT_SELECTORS /
   DOWNLOAD_SELECTORS below. The selectors shipped here are a best-effort
   starting point (Playwright's own recommended role/text-based locators,
   which survive minor CSS/class changes better than XPath), NOT verified
   against the live Flow UI — nobody building this had a logged-in Google
   account to check against, so treat step 4 as mandatory before step 5.
5. python flow_veo_sidecar.py
   Runs the poll loop for real.

*** IMPORTANT: this automates a consumer web app, not an official API ***
Google's consumer ToS for Flow/Gemini apps generally do not permit automated
access, even from a legitimately paying account. Using this script risks your
account being rate-limited or flagged. That risk is yours alone to accept; the
pacing below (human-speed delays, no parallel tabs, one job at a time) is
meant to reduce — not eliminate — the chance of that happening.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

FACTORY = os.getenv("YOUTUBE_FACTORY_URL", "http://127.0.0.1:8787").rstrip("/")
FLOW_URL = os.getenv("FLOW_VEO_URL", "https://labs.google/flow")
PROFILE_DIR = Path(os.getenv("FLOW_VEO_PROFILE_DIR", str(Path(__file__).with_name("_flow_veo_profile"))))
DOWNLOAD_DIR = Path(os.getenv("FLOW_VEO_DOWNLOAD_DIR", str(Path(__file__).with_name("_flow_veo_downloads"))))
GENERATION_TIMEOUT_SECONDS = int(os.getenv("FLOW_VEO_GENERATION_TIMEOUT", "600"))
HEADLESS = os.getenv("FLOW_VEO_HEADLESS", "0").strip().lower() in {"1", "true", "yes"}

# Best-effort starting selectors — NOT verified against the live Flow UI (see
# module docstring, step 4). Ordered by how likely each is to still match if
# Google tweaks copy/markup; the sidecar tries each in turn.
PROMPT_INPUT_SELECTORS = [
    "textarea[placeholder*='Describe' i]",
    "textarea[placeholder*='prompt' i]",
    "[contenteditable='true']",
    "textarea",
]
SUBMIT_SELECTORS = [
    "button[aria-label*='Generate' i]",
    "button:has-text('Generate')",
    "button[type='submit']",
]
# A finished clip's download affordance. Flow generates asynchronously, so the
# sidecar polls for this to appear rather than assuming a fixed wait time.
DOWNLOAD_SELECTORS = [
    "button[aria-label*='Download' i]",
    "a[download]",
    "[aria-label*='Download video' i]",
]


class FlowVeoError(RuntimeError):
    pass


def _api_get(path: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{FACTORY}{path}", timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _api_post(path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(data or {}).encode("utf-8")
    request = urllib.request.Request(
        f"{FACTORY}{path}", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _upload_asset(project_id: int, video_path: Path) -> int:
    """POST the downloaded clip as a multipart/form-data upload, return asset_id."""
    boundary = "----ytfactoryflowveo"
    video_bytes = video_path.read_bytes()
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="asset_type"\r\n\r\nvideo\r\n'.encode(),
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{video_path.name}"\r\n'
            f'Content-Type: video/mp4\r\n\r\n'
        ).encode() + video_bytes + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    request = urllib.request.Request(
        f"{FACTORY}/api/projects/{project_id}/assets/upload",
        data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.loads(response.read().decode("utf-8"))
    return int(result["asset"]["id"])


def get_next_job() -> dict[str, Any] | None:
    return _api_get("/api/flow-veo/next-scene-job").get("job")


def complete_job(job_id: int, asset_id: int) -> None:
    _api_post(f"/api/flow-veo/scene-jobs/{job_id}/complete?asset_id={asset_id}")


def fail_job(job_id: int, error: str) -> None:
    try:
        _api_post(f"/api/flow-veo/scene-jobs/{job_id}/fail?error={urllib.parse.quote(error[:500])}")
    except Exception:
        pass  # best-effort; don't let a failed failure-report crash the loop


def _find_first(page, selectors: list[str], timeout_ms: int = 15_000):
    last_error: Exception | None = None
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.wait_for(state="visible", timeout=timeout_ms)
            return locator
        except Exception as exc:  # noqa: BLE001 - trying the next candidate on purpose
            last_error = exc
            continue
    raise FlowVeoError(f"Không tìm được phần tử khớp {selectors}: {last_error}")


def generate_video(page, prompt: str, download_dir: Path) -> Path:
    page.goto(FLOW_URL, wait_until="domcontentloaded")
    prompt_box = _find_first(page, PROMPT_INPUT_SELECTORS)
    prompt_box.click()
    prompt_box.fill(prompt)
    submit_button = _find_first(page, SUBMIT_SELECTORS)
    submit_button.click()

    deadline = time.monotonic() + GENERATION_TIMEOUT_SECONDS
    download_control = None
    while time.monotonic() < deadline:
        try:
            download_control = _find_first(page, DOWNLOAD_SELECTORS, timeout_ms=5_000)
            break
        except FlowVeoError:
            time.sleep(5)
    if download_control is None:
        raise FlowVeoError(f"Flow không tạo xong video sau {GENERATION_TIMEOUT_SECONDS}s")

    download_dir.mkdir(parents=True, exist_ok=True)
    with page.expect_download() as download_info:
        download_control.click()
    download = download_info.value
    target = download_dir / f"flow-veo-{int(time.time())}.mp4"
    download.save_as(str(target))
    return target


def run_login() -> None:
    from playwright.sync_api import sync_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False)
        page = context.new_page()
        page.goto(FLOW_URL, wait_until="domcontentloaded")
        input("Đăng nhập Google trong cửa sổ vừa mở, đợi Flow tải xong rồi bấm Enter ở đây...")
        context.close()
    print(f"Đã lưu session tại {PROFILE_DIR}. Có thể chạy lại mà không cần đăng nhập nữa.")


def run_recon() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False)
        page = context.new_page()
        page.goto(FLOW_URL, wait_until="domcontentloaded")
        print("Dùng Playwright Inspector để tìm selector thật cho: ô nhập prompt, nút Generate, nút Download.")
        page.pause()
        context.close()


def run_loop() -> None:
    from playwright.sync_api import sync_playwright

    if not (PROFILE_DIR / "Default").exists() and not any(PROFILE_DIR.glob("*")):
        raise SystemExit(f"Chưa có session đăng nhập tại {PROFILE_DIR}. Chạy `python flow_veo_sidecar.py --login` trước.")

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(str(PROFILE_DIR), headless=HEADLESS)
        page = context.new_page()
        while True:
            try:
                job = get_next_job()
                if not job:
                    time.sleep(10)
                    continue
                job_id = int(job["id"])
                project_id = int(job["project_id"])
                prompt = str(job.get("prompt") or "")
                print(f"[flow-veo] job {job_id}: generating...", flush=True)
                try:
                    video_path = generate_video(page, prompt, DOWNLOAD_DIR)
                    asset_id = _upload_asset(project_id, video_path)
                    complete_job(job_id, asset_id)
                    print(f"[flow-veo] job {job_id}: done -> asset {asset_id}", flush=True)
                except Exception as exc:  # noqa: BLE001 - report to the app, keep the loop alive
                    print(f"[flow-veo] job {job_id}: FAILED - {exc}", flush=True)
                    fail_job(job_id, str(exc))
                # Human-paced gap between jobs, not back-to-back automation.
                time.sleep(20)
            except (urllib.error.URLError, urllib.error.HTTPError) as exc:
                print(f"[flow-veo] cannot reach {FACTORY}: {exc}", flush=True)
                time.sleep(15)
            except KeyboardInterrupt:
                context.close()
                return


if __name__ == "__main__":
    if "--login" in sys.argv:
        run_login()
    elif "--recon" in sys.argv:
        run_recon()
    else:
        run_loop()
