"""Web-app sidecar: hand queued YT Factory image/video jobs to a browser.

Generalizes flow_veo_sidecar.py to support more than one site. Each site you
already have paid/free access to (Google Flow for Veo 3, Meta AI's Vibes,
Gemini's/ChatGPT's own chat UI for images, whatever comes next) gets its own
entry in PROVIDERS below with its own URL and selectors, but they all share
the same pull-queue plumbing:

    GET  /api/browser-scene-jobs/next?provider=<name>
    POST /api/browser-scene-jobs/{job_id}/complete?asset_id=<id>
    POST /api/browser-scene-jobs/{job_id}/fail?error=<message>

To add a new site: add a PROVIDERS entry here, add its Literal value to
CreateSceneGenerationRequest/BatchSceneGenerationRequest in main.py, and add
it to database.BROWSER_SIDECAR_PROVIDERS. No other server-side change needed.

Current providers: flow_veo and meta_ai_video generate video (a dedicated
studio page with a Download button); gemini_web_image and chatgpt_web_image
generate a still image inline in a chat reply (no download button — the
image's own src is fetched directly, see output_kind on ProviderConfig).

*** SETUP (per provider, do this once) ***
1. pip install -r requirements.txt        (already includes playwright)
2. python -m playwright install chromium  (downloads the browser binary)
3. python web_video_sidecar.py --provider flow_veo --login
   (or --provider meta_ai_video / gemini_web_image / chatgpt_web_image)
   A real Chrome window opens at the site's URL. Log in by hand (Google
   account for Flow/Gemini, Facebook/Instagram for Meta AI, OpenAI account
   for ChatGPT), wait until the page has fully loaded, then press Enter in
   this terminal. The session is saved under a profile folder per provider
   and reused every future run.
4. python web_video_sidecar.py --provider flow_veo --recon
   Opens the site (already logged in) and calls page.pause(), which
   launches the Playwright Inspector. Use it to find the real selectors —
   for video providers: the prompt textbox, submit button, and the
   finished-clip download control; for image providers: the prompt textbox,
   submit button, and the generated <img> element in the reply — then
   update that provider's entry in PROVIDERS below. The selectors shipped
   here are a best-effort starting point (Playwright's own recommended
   role/text-based locators), NOT verified against the live UI of any of
   these sites — --recon is optional now (see below) but still the fastest
   way to get a provider working reliably from the start.
5. python web_video_sidecar.py --provider flow_veo
   Runs the poll loop for real (one provider per process; run one process
   per provider you want active at once).

*** AI VISION FALLBACK (self-healing selectors) ***
When none of a step's hardcoded selectors match — first run before --recon,
or the site changed its UI later — the sidecar takes a screenshot and asks
the app's configured orchestrator CLI (Cai dat > AI dieu phoi chinh: Codex
CLI or Claude Code CLI, both driven via the user's own logged-in
subscription, not a metered API key) where to click, via
POST /api/orchestrator/locate-element. This makes --recon optional rather
than mandatory, at the cost of a few extra seconds and one CLI invocation
per fallback. Requires the chosen CLI to be logged in (Cai dat page shows
status); if neither is logged in, the fallback simply fails with a clear
error and the job is reported failed rather than hanging.

*** IMPORTANT: this automates a consumer web app, not an official API ***
Google's, Meta's and OpenAI's consumer ToS generally don't permit automated
access to these apps, even from a legitimate free/paid account. Using this
script risks your account being rate-limited or flagged. That risk is yours
alone to accept; the pacing below (human-speed delays, one job at a time, no
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
    # "video" = existing studio flow: submit -> wait for a download button ->
    # click it -> capture via page.expect_download(). "image" = chat flow:
    # submit -> wait for an <img> to appear in the reply -> fetch its src
    # directly over HTTP (through the browser context, so session cookies
    # still apply). Chat UIs (Gemini, ChatGPT) generally have no explicit
    # "download" affordance on an inline image — the img src itself is the
    # only reliable target — so this needs a different capture strategy than
    # a dedicated video studio like Flow.
    output_kind: str = "video"
    # Best-effort starting selectors, ordered by how likely each is to still
    # match if the site tweaks copy/markup — see module docstring, step 4.
    prompt_selectors: list[str] = field(default_factory=list)
    submit_selectors: list[str] = field(default_factory=list)
    download_selectors: list[str] = field(default_factory=list)
    image_result_selectors: list[str] = field(default_factory=list)
    # Opens a file chooser for attaching a starting image (image-to-video).
    # Only used when the queued job carries a reference_asset_path.
    image_upload_selectors: list[str] = field(default_factory=list)
    # Plain-language description of each target, used only when every
    # selector above fails to match — see "AI VISION FALLBACK" above.
    prompt_instruction: str = "O nhap prompt/mo ta video can tao (thuong la 1 textarea lon giua man hinh)"
    submit_instruction: str = "Nut gui/tao video (Generate, Create, hoac icon mui ten gui), thuong canh o nhap prompt"
    download_instruction: str = "Nut tai video vua tao xong (Download), xuat hien sau khi video render xong"
    image_result_instruction: str = "Anh AI vua tao ra trong tin nhan tra loi moi nhat (anh lon nhat, moi nhat trong khung chat)"
    image_upload_instruction: str = "Nut them anh/tai anh len lam khung hinh dau cho video (Add image, Upload image, hoac icon ghep anh), thuong canh o nhap prompt"


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
        image_upload_selectors=[
            "input[type='file']",
            "button[aria-label*='Add image' i]",
            "button[aria-label*='Upload image' i]",
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
        image_upload_selectors=[
            "input[type='file']",
            "button[aria-label*='Add photo' i]",
            "button[aria-label*='Upload' i]",
        ],
    ),
    "gemini_web_image": ProviderConfig(
        url=os.getenv("GEMINI_WEB_URL", "https://gemini.google.com/app"),
        output_kind="image",
        prompt_selectors=[
            "div[contenteditable='true'][aria-label*='prompt' i]",
            "div.ql-editor[contenteditable='true']",
            "[contenteditable='true']",
            "textarea",
        ],
        submit_selectors=[
            "button[aria-label*='Send' i]",
            "button[aria-label*='Submit' i]",
            "button[type='submit']",
        ],
        image_result_selectors=[
            "img[alt*='Generated image' i]",
            "generated-image img",
            "single-image img",
            "message-content img",
        ],
    ),
    "chatgpt_web_image": ProviderConfig(
        url=os.getenv("CHATGPT_WEB_URL", "https://chatgpt.com/"),
        output_kind="image",
        prompt_selectors=[
            "#prompt-textarea",
            "div[contenteditable='true']",
            "textarea",
        ],
        submit_selectors=[
            "button[data-testid='send-button']",
            "button[aria-label*='Send' i]",
            "button[type='submit']",
        ],
        image_result_selectors=[
            "img[alt*='Generated image' i]",
            "div[data-testid*='image'] img",
            ".agent-turn img",
        ],
    ),
}

_ASPECT_RATIO_HINT = {"1280:720": "16:9 landscape", "720:1280": "9:16 portrait", "1024:1024": "1:1 square"}


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


def _api_post_json(path: str, payload: dict[str, Any], timeout: int = 180) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(f"{FACTORY}{path}", data=body, method="POST",
                                      headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


_IMAGE_MIME_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}


def _upload_asset(project_id: int, file_path: Path) -> int:
    """POST the downloaded clip/image as a multipart/form-data upload, return
    asset_id. asset_type is inferred from the file's own extension rather
    than assumed to always be video — image providers (Gemini/ChatGPT web
    chat) download a still image, and mislabeling that as video/mp4 would
    corrupt the asset record even though the bytes themselves are fine."""
    boundary = "----ytfactorywebvideo"
    file_bytes = file_path.read_bytes()
    extension = file_path.suffix.lower()
    if extension in _IMAGE_MIME_BY_EXT:
        asset_type, content_type = "image", _IMAGE_MIME_BY_EXT[extension]
    else:
        asset_type, content_type = "video", "video/mp4"
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="asset_type"\r\n\r\n{asset_type}\r\n'.encode(),
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
            f'Content-Type: {content_type}\r\n\r\n'
        ).encode() + file_bytes + b"\r\n",
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


def _locate_via_vision(page, instruction: str) -> tuple[int, int]:
    """AI vision fallback — see module docstring. Screenshots the current
    page, asks the app's configured orchestrator CLI for pixel coordinates,
    returns (x, y). Raises WebVideoError if the AI can't find it either or
    no orchestrator CLI is logged in."""
    viewport = page.viewport_size or {"width": 1280, "height": 800}
    screenshot_path = Path(os.environ.get("TEMP", str(BASE_DIR))) / f"web-video-locate-{int(time.time() * 1000)}.png"
    page.screenshot(path=str(screenshot_path))
    try:
        result = _api_post_json(
            "/api/orchestrator/locate-element",
            {
                "screenshot_path": str(screenshot_path),
                "instruction": instruction,
                "viewport_width": viewport["width"],
                "viewport_height": viewport["height"],
            },
        )
    finally:
        screenshot_path.unlink(missing_ok=True)
    if not result.get("found"):
        raise WebVideoError(f"AI (orchestrator) khong tim thay: {instruction}")
    return int(result["x"]), int(result["y"])


def _resolve_target(page, selectors: list[str], instruction: str, timeout_ms: int = 15_000):
    """Try the fast, free hardcoded selectors first; fall back to AI vision
    (slower, uses the orchestrator CLI) only if none of them match. Returns
    ("locator", Locator) or ("point", (x, y))."""
    try:
        return "locator", _find_first(page, selectors, timeout_ms=timeout_ms)
    except WebVideoError:
        return "point", _locate_via_vision(page, instruction)


def _click(page, kind: str, target) -> None:
    if kind == "locator":
        target.click()
    else:
        page.mouse.click(*target)


def _attach_reference_image(page, config: ProviderConfig, image_path: Path) -> None:
    """Best-effort image-to-video: attach an existing scene image as the
    starting frame before generating. Not yet verified against either site's
    live DOM (see module docstring, step 4) — falls back to AI vision like
    every other target here, and a failure here must not abort the whole
    job, since a from-scratch text-to-video clip is still a useful result."""
    if not config.image_upload_selectors:
        return
    try:
        file_input = page.locator("input[type='file']").first
        if file_input.count() > 0:
            file_input.set_input_files(str(image_path))
            return
        kind, target = _resolve_target(page, config.image_upload_selectors, config.image_upload_instruction, timeout_ms=8_000)
        with page.expect_file_chooser(timeout=8_000) as chooser_info:
            _click(page, kind, target)
        chooser_info.value.set_files(str(image_path))
    except Exception as exc:  # noqa: BLE001 - image-to-video is a nice-to-have, not a hard requirement
        print(f"Không đính kèm được ảnh tham chiếu ({image_path.name}), tiếp tục tạo video từ prompt: {exc}", flush=True)


_IMAGE_MIME_BY_EXT_REVERSE = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}


def _guess_image_extension(url: str, content_type: str) -> str:
    lowered_url = url.lower()
    for extension in (".png", ".jpeg", ".jpg", ".webp", ".gif"):
        if extension in lowered_url:
            return extension
    return _IMAGE_MIME_BY_EXT_REVERSE.get(content_type.split(";")[0].strip().lower(), ".png")


def _capture_chat_image(page, config: ProviderConfig, download_dir: Path) -> Path:
    """Chat UIs render the generated image inline with no download button —
    the only reliable handle is the <img> element's own src. Fetch it
    through the browser context's own request API so session cookies (the
    image URL is often auth-walled) are applied automatically."""
    deadline = time.monotonic() + GENERATION_TIMEOUT_SECONDS
    image_url: str | None = None
    while time.monotonic() < deadline:
        for selector in config.image_result_selectors:
            try:
                locator = page.locator(selector).last
                locator.wait_for(state="visible", timeout=3_000)
                src = locator.get_attribute("src")
                if src:
                    image_url = src
                    break
            except Exception:  # noqa: BLE001 - try the next selector / poll again
                continue
        if image_url:
            break
        time.sleep(3)
    if image_url is None:
        # Vision fallback here can only report a click point, not an image
        # src/URL, so it can't substitute for a working selector on this
        # path — this is a real limitation of chat-based image capture
        # versus the click-driven video/download flow above.
        raise WebVideoError(f"Không tìm thấy ảnh kết quả sau {GENERATION_TIMEOUT_SECONDS}s (selector chưa đúng với giao diện thật)")
    download_dir.mkdir(parents=True, exist_ok=True)
    response = page.context.request.get(image_url)
    if not response.ok:
        raise WebVideoError(f"Không tải được ảnh: HTTP {response.status}")
    body = response.body()
    extension = _guess_image_extension(image_url, response.headers.get("content-type", ""))
    target_path = download_dir / f"web-image-{int(time.time())}{extension}"
    target_path.write_bytes(body)
    return target_path


def _capture_video_download(page, config: ProviderConfig, download_dir: Path) -> Path:
    deadline = time.monotonic() + GENERATION_TIMEOUT_SECONDS
    resolved: tuple[str, Any] | None = None
    while time.monotonic() < deadline:
        try:
            resolved = ("locator", _find_first(page, config.download_selectors, timeout_ms=5_000))
            break
        except WebVideoError:
            time.sleep(5)
    if resolved is None:
        # One AI-vision attempt once the fixed timeout is close to expired,
        # rather than spamming a vision call on every 5s poll above.
        try:
            resolved = ("point", _locate_via_vision(page, config.download_instruction))
        except WebVideoError:
            pass
    if resolved is None:
        raise WebVideoError(f"Không tạo xong video sau {GENERATION_TIMEOUT_SECONDS}s")

    download_dir.mkdir(parents=True, exist_ok=True)
    with page.expect_download() as download_info:
        _click(page, resolved[0], resolved[1])
    download = download_info.value
    target_path = download_dir / f"web-video-{int(time.time())}.mp4"
    download.save_as(str(target_path))
    return target_path


def generate_video(
    page, config: ProviderConfig, prompt: str, download_dir: Path,
    ratio: str = "", reference_image_path: Path | None = None,
) -> Path:
    page.goto(config.url, wait_until="domcontentloaded")
    if reference_image_path is not None and reference_image_path.is_file():
        _attach_reference_image(page, config, reference_image_path)
    kind, target = _resolve_target(page, config.prompt_selectors, config.prompt_instruction)
    _click(page, kind, target)
    ratio_hint = _ASPECT_RATIO_HINT.get(ratio, "")
    page.keyboard.type(f"{prompt} ({ratio_hint})" if ratio_hint else prompt)
    kind, target = _resolve_target(page, config.submit_selectors, config.submit_instruction)
    _click(page, kind, target)

    if config.output_kind == "image":
        return _capture_chat_image(page, config, download_dir)
    return _capture_video_download(page, config, download_dir)


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
                ratio = str(job.get("ratio") or "")
                reference_asset_path = job.get("reference_asset_path")
                reference_image_path = Path(str(reference_asset_path)) if reference_asset_path else None
                print(f"[{provider}] job {job_id}: generating...", flush=True)
                try:
                    video_path = generate_video(
                        page, config, prompt, _download_dir(provider),
                        ratio=ratio, reference_image_path=reference_image_path,
                    )
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
