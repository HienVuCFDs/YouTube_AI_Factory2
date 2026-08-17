"""Web-app video sidecar: hand queued YT Factory video jobs to a browser.

Generalizes flow_veo_sidecar.py to support more than one site. Each site you
already have paid/free access to (Google Flow for Veo 3, Meta AI's Vibes,
whatever comes next) gets its own entry in PROVIDERS below with its own URL
and selectors, but they all share the same pull-queue plumbing:

    GET  /api/browser-scene-jobs/next?provider=<name>
    POST /api/browser-scene-jobs/{job_id}/complete?asset_id=<id>
    POST /api/browser-scene-jobs/{job_id}/fail?error=<message>

To add a new site: add a PROVIDERS entry here, add its Literal value to
CreateSceneGenerationRequest/BatchSceneGenerationRequest in main.py, and add
it to database.BROWSER_SIDECAR_PROVIDERS. No other server-side change needed.

*** SETUP (per provider, do this once) ***
1. pip install -r requirements.txt        (already includes playwright)
2. python -m playwright install chromium  (downloads the browser binary)
3. python web_video_sidecar.py --provider flow_veo --login
   (or --provider meta_ai_video)
   A real Chrome window opens at the site's URL. Log in by hand (Google
   account for Flow, Facebook/Instagram for Meta AI), wait until the page
   has fully loaded, then press Enter in this terminal. The session is
   saved under a profile folder per provider and reused every future run.
4. python web_video_sidecar.py --provider flow_veo --recon
   Opens the site (already logged in) and calls page.pause(), which
   launches the Playwright Inspector. Use it to find the real selectors
   for the prompt textbox, the submit button, and the finished-clip
   download control, then update that provider's entry in PROVIDERS below.
   The selectors shipped here are a best-effort starting point (Playwright's
   own recommended role/text-based locators), NOT verified against the live
   UI of either site — treat step 4 as mandatory before step 5.
5. python web_video_sidecar.py --provider flow_veo
   Runs the poll loop for real (one provider per process; run two processes
   if you want both Flow and Meta AI working at once).

*** IMPORTANT: this automates a consumer web app, not an official API ***
Neither Google's nor Meta's consumer ToS generally permit automated access
to these apps, even from a legitimate free/paid account. Using this script
risks your account being rate-limited or flagged. That risk is yours alone
to accept; the pacing below (human-speed delays, one job at a time, no
parallel tabs per provider) is meant to reduce it, not eliminate it.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FACTORY = os.getenv("YOUTUBE_FACTORY_URL", "http://127.0.0.1:8787").rstrip("/")
BASE_DIR = Path(__file__).parent
GENERATION_TIMEOUT_SECONDS = int(os.getenv("WEB_VIDEO_GENERATION_TIMEOUT", "600"))
HEADLESS = os.getenv("WEB_VIDEO_HEADLESS", "0").strip().lower() in {"1", "true", "yes"}


@dataclass
class ProviderConfig:
    url: str
    # Best-effort starting selectors, ordered by how likely each is to still
    # match if the site tweaks copy/markup — see module docstring, step 4.
    prompt_selectors: list[str] = field(default_factory=list)
    submit_selectors: list[str] = field(default_factory=list)
    download_selectors: list[str] = field(default_factory=list)


PROVIDERS: dict[str, ProviderConfig] = {
    "flow_veo": ProviderConfig(
        url=os.getenv("FLOW_VEO_URL", "https://labs.google/flow"),
        prompt_selectors=[
            "textarea[placeholder*='Describe' i]",
            "textarea[placeholder*='prompt' i]",
            "[contenteditable='true']",
            "textarea",
        ],
        submit_selectors=[
            "button[aria-label*='Generate' i]",
            "button:has-text('Generate')",
            "button[type='submit']",
        ],
        download_selectors=[
            "button[aria-label*='Download' i]",
            "a[download]",
            "[aria-label*='Download video' i]",
        ],
    ),
    "meta_ai_video": ProviderConfig(
        url=os.getenv("META_AI_VIDEO_URL", "https://www.meta.ai/"),
        prompt_selectors=[
            "textarea[placeholder*='Imagine' i]",
            "textarea[placeholder*='prompt' i]",
            "[contenteditable='true']",
            "textarea",
        ],
        submit_selectors=[
            "button[aria-label*='Send' i]",
            "button[aria-label*='Generate' i]",
            "button[type='submit']",
        ],
        download_selectors=[
            "button[aria-label*='Download' i]",
            "a[download]",
            "[aria-label*='Save' i]",
        ],
    ),
}


class WebVideoError(RuntimeError):
    pass


def _profile_dir(provider: str) -> Path:
    return Path(os.getenv("WEB_VIDEO_PROFILE_DIR", str(BASE_DIR / f"_web_video_profile_{provider}")))


def _download_dir(provider: str) -> Path:
    return Path(os.getenv("WEB_VIDEO_DOWNLOAD_DIR", str(BASE_DIR / f"_web_video_downloads_{provider}")))


def _api_get(path: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{FACTORY}{path}", timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _api_post(path: str) -> dict[str, Any]:
    request = urllib.request.Request(f"{FACTORY}{path}", data=b"{}", method="POST",
                                      headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _upload_asset(project_id: int, video_path: Path) -> int:
    """POST the downloaded clip as a multipart/form-data upload, return asset_id."""
    boundary = "----ytfactorywebvideo"
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


def get_next_job(provider: str) -> dict[str, Any] | None:
    return _api_get(f"/api/browser-scene-jobs/next?provider={provider}").get("job")


def complete_job(job_id: int, asset_id: int) -> None:
    _api_post(f"/api/browser-scene-jobs/{job_id}/complete?asset_id={asset_id}")


def fail_job(job_id: int, error: str) -> None:
    try:
        _api_post(f"/api/browser-scene-jobs/{job_id}/fail?error={urllib.parse.quote(error[:500])}")
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
    raise WebVideoError(f"Không tìm được phần tử khớp {selectors}: {last_error}")


def generate_video(page, config: ProviderConfig, prompt: str, download_dir: Path) -> Path:
    page.goto(config.url, wait_until="domcontentloaded")
    prompt_box = _find_first(page, config.prompt_selectors)
    prompt_box.click()
    prompt_box.fill(prompt)
    submit_button = _find_first(page, config.submit_selectors)
    submit_button.click()

    deadline = time.monotonic() + GENERATION_TIMEOUT_SECONDS
    download_control = None
    while time.monotonic() < deadline:
        try:
            download_control = _find_first(page, config.download_selectors, timeout_ms=5_000)
            break
        except WebVideoError:
            time.sleep(5)
    if download_control is None:
        raise WebVideoError(f"Không tạo xong video sau {GENERATION_TIMEOUT_SECONDS}s")

    download_dir.mkdir(parents=True, exist_ok=True)
    with page.expect_download() as download_info:
        download_control.click()
    download = download_info.value
    target = download_dir / f"web-video-{int(time.time())}.mp4"
    download.save_as(str(target))
    return target


def run_login(provider: str, config: ProviderConfig) -> None:
    from playwright.sync_api import sync_playwright

    profile_dir = _profile_dir(provider)
    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(str(profile_dir), headless=False)
        page = context.new_page()
        page.goto(config.url, wait_until="domcontentloaded")
        input(f"Đăng nhập trong cửa sổ vừa mở ({provider}), đợi trang tải xong rồi bấm Enter ở đây...")
        context.close()
    print(f"Đã lưu session tại {profile_dir}. Có thể chạy lại mà không cần đăng nhập nữa.")


def run_recon(provider: str, config: ProviderConfig) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(str(_profile_dir(provider)), headless=False)
        page = context.new_page()
        page.goto(config.url, wait_until="domcontentloaded")
        print("Dùng Playwright Inspector để tìm selector thật cho: ô nhập prompt, nút gửi/generate, nút download.")
        page.pause()
        context.close()


def run_loop(provider: str, config: ProviderConfig) -> None:
    from playwright.sync_api import sync_playwright

    profile_dir = _profile_dir(provider)
    if not any(profile_dir.glob("*")):
        raise SystemExit(f"Chưa có session đăng nhập tại {profile_dir}. Chạy `--provider {provider} --login` trước.")

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(str(profile_dir), headless=HEADLESS)
        page = context.new_page()
        while True:
            try:
                job = get_next_job(provider)
                if not job:
                    time.sleep(10)
                    continue
                job_id = int(job["id"])
                project_id = int(job["project_id"])
                prompt = str(job.get("prompt") or "")
                print(f"[{provider}] job {job_id}: generating...", flush=True)
                try:
                    video_path = generate_video(page, config, prompt, _download_dir(provider))
                    asset_id = _upload_asset(project_id, video_path)
                    complete_job(job_id, asset_id)
                    print(f"[{provider}] job {job_id}: done -> asset {asset_id}", flush=True)
                except Exception as exc:  # noqa: BLE001 - report to the app, keep the loop alive
                    print(f"[{provider}] job {job_id}: FAILED - {exc}", flush=True)
                    fail_job(job_id, str(exc))
                # Human-paced gap between jobs, not back-to-back automation.
                time.sleep(20)
            except (urllib.error.URLError, urllib.error.HTTPError) as exc:
                print(f"[{provider}] cannot reach {FACTORY}: {exc}", flush=True)
                time.sleep(15)
            except KeyboardInterrupt:
                context.close()
                return


def main() -> None:
    if "--provider" not in sys.argv:
        raise SystemExit(f"Dùng: python web_video_sidecar.py --provider {{{','.join(PROVIDERS)}}} [--login|--recon]")
    provider = sys.argv[sys.argv.index("--provider") + 1]
    config = PROVIDERS.get(provider)
    if not config:
        raise SystemExit(f"Không biết provider '{provider}'. Có sẵn: {', '.join(PROVIDERS)}")

    if "--login" in sys.argv:
        run_login(provider, config)
    elif "--recon" in sys.argv:
        run_recon(provider, config)
    else:
        run_loop(provider, config)


if __name__ == "__main__":
    main()
