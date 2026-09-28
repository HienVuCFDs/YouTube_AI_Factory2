from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from .coccoc_session import CocCocSessionError, write_youtube_cookie_file
from .settings import VIDEO_DOWNLOAD_DIR


class VideoDownloadError(RuntimeError):
    pass


def _options(
    video_id: str,
    media_type: str,
    player_client: str = "",
    cookie_file: Path | None = None,
    format_selector: str = "",
    output_template: str = "",
    audio_codec: str = "mp3",
) -> dict:
    if media_type == "audio":
        options = {
            "format": "bestaudio/best",
            "outtmpl": output_template or str(VIDEO_DOWNLOAD_DIR / f"{video_id}.%(ext)s"),
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": audio_codec, "preferredquality": "192"}
            ],
        }
    else:
        options = {
            # Do not constrain height here. Some YouTube player clients expose
            # only one adaptive format without the height field; the old
            # selector then incorrectly failed with "Requested format is not
            # available" even though the video itself was downloadable.
            "format": format_selector or "bestvideo*+bestaudio/best",
            "outtmpl": output_template or str(VIDEO_DOWNLOAD_DIR / f"{video_id}.%(ext)s"),
            "merge_output_format": "mp4",
        }
    options.update({"quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True})
    # yt-dlp needs an external JS runtime plus yt-dlp-ejs for full YouTube
    # support. Deno is enabled by default; explicitly enable an installed
    # Node runtime too, since this Windows app already uses Node elsewhere.
    options["js_runtimes"] = {"deno": {}, **({"node": {}} if shutil.which("node") else {})}
    if player_client:
        options["extractor_args"] = {"youtube": {"player_client": [player_client]}}
    if cookie_file:
        options["cookiefile"] = str(cookie_file)
    return options


def _download_with_options(
    yt_dlp: object,
    video_url: str,
    video_id: str,
    media_type: str,
    cookie_file: Path | None,
    *,
    output_template: str = "",
    audio_codec: str = "mp3",
    selectors: tuple[str, ...] = (),
) -> None:
    failures: list[Exception] = []
    # Android VR and TV embedded clients currently expose public formats for
    # videos where YouTube blocks the default web client with a bot challenge.
    # No account session or browser cookie is used in these fallbacks.
    selectors = selectors or (
        ("bestvideo*+bestaudio/best", "best[ext=mp4]/best", "best")
        if media_type == "video" else ("bestaudio/best",)
    )
    for player_client in ("", "android_vr", "android", "tv_embedded", "web_safari"):
        for selector in selectors:
            try:
                with yt_dlp.YoutubeDL(_options(
                    video_id, media_type, player_client, cookie_file, selector,
                    output_template, audio_codec,
                )) as ydl:
                    ydl.download([video_url])
                return
            except Exception as exc:
                failures.append(exc)
    detail = re.sub(r"\x1b\[[0-9;]*m", "", str(failures[-1])) if failures else "Lỗi không xác định"
    hint = ""
    lower_detail = detail.lower()
    if "requested format is not available" in lower_detail:
        hint = " App đã thử các format thay thế nhưng YouTube không cấp stream phù hợp cho phiên này."
    elif any(token in lower_detail for token in ("429", "sign in", "bot", "not available")) and cookie_file is None:
        hint = " YouTube đang chặn phiên tải công khai; hãy dùng nút tải với phiên Cốc Cốc hoặc file cookies.txt của chính bạn."
    elif "403" in lower_detail:
        hint = " YouTube từ chối stream này; hãy cập nhật yt-dlp[default] và dùng bản nguồn đã tải hoặc file video của bạn nếu lỗi vẫn lặp lại."
    raise VideoDownloadError(f"Không tải được video: {detail}{hint}") from (failures[-1] if failures else None)


def download_audio_for_transcription(video_url: str, dest_dir: Path) -> Path:
    """Download temporary WAV using the same client fallbacks as source downloads."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise VideoDownloadError("Thiếu thư viện yt-dlp. Cài đặt bằng: pip install 'yt-dlp[default]'") from exc
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    _download_with_options(
        yt_dlp, video_url, "audio", "audio", None,
        output_template=str(dest_dir / "audio.%(ext)s"), audio_codec="wav",
    )
    audio = dest_dir / "audio.wav"
    if not audio.is_file():
        raise VideoDownloadError("Không tìm thấy file WAV sau khi trích xuất audio")
    return audio


def download_preview_video(video_url: str, dest_dir: Path, *, max_height: int = 480) -> Path:
    """Download the smallest watchable copy, for looking at rather than editing.

    Analysing a source means seeing it, and seeing it means having frames. The
    full download stays what it has always been - an explicit, confirmed act
    that keeps the file - because a publishable re-edit needs the real thing.
    This one is small, temporary, and exists only so a contact sheet can be
    made: a minute of 480p is a couple of megabytes.
    """
    try:
        import yt_dlp
    except ImportError as exc:
        raise VideoDownloadError("Thiếu thư viện yt-dlp. Cài đặt bằng: pip install 'yt-dlp[default]'") from exc
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Through the same player-client fallbacks the real download uses: a naive
    # selector gets "Requested format is not available" on videos where the
    # default web client is challenged, and those are the ones that most need
    # to work.
    _download_with_options(
        yt_dlp, video_url, "preview", "video", None,
        output_template=str(dest_dir / "preview.%(ext)s"),
        selectors=(
            f"best[height<={int(max_height)}]",
            f"worst[height>={min(240, int(max_height))}]",
            "worst",
            "best",
        ),
    )
    matches = sorted(
        path for path in dest_dir.glob("preview.*")
        if path.suffix.lower() not in {".part", ".ytdl"} and path.stat().st_size > 0
    )
    if not matches:
        raise VideoDownloadError("Không tìm thấy file xem trước sau khi tải")
    return max(matches, key=lambda path: path.stat().st_size)


def download_video(
    video_url: str,
    video_id: str,
    media_type: str = "video",
    browser_session: str = "",
    cookie_file: Path | None = None,
) -> Path:
    """Download one explicitly requested source file for local re-editing."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise VideoDownloadError("Thiếu thư viện yt-dlp. Cài đặt bằng: pip install 'yt-dlp[default]'") from exc
    if browser_session not in {"", "coccoc"}:
        raise VideoDownloadError(f"Browser session không được hỗ trợ: {browser_session}")
    if cookie_file is not None and not Path(cookie_file).is_file():
        raise VideoDownloadError("Không tìm thấy file cookies.txt đã chọn")

    VIDEO_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if cookie_file is not None:
        _download_with_options(yt_dlp, video_url, video_id, media_type, Path(cookie_file))
    elif browser_session == "coccoc":
        try:
            with tempfile.TemporaryDirectory(prefix="youtube-ai-coccoc-") as temporary_directory:
                cookie_file = write_youtube_cookie_file(Path(temporary_directory) / "youtube-session.txt")
                _download_with_options(yt_dlp, video_url, video_id, media_type, cookie_file)
        except CocCocSessionError as exc:
            raise VideoDownloadError(str(exc)) from exc
    else:
        _download_with_options(yt_dlp, video_url, video_id, media_type, None)

    matches = sorted(
        path for path in VIDEO_DOWNLOAD_DIR.glob(f"{video_id}.*")
        if path.suffix.lower() not in {".part", ".ytdl"}
    )
    if not matches:
        raise VideoDownloadError("Không tìm thấy file sau khi tải")
    return max(matches, key=lambda path: path.stat().st_mtime_ns)


def delete_downloaded_video(video_id: str) -> bool:
    deleted = False
    for path in VIDEO_DOWNLOAD_DIR.glob(f"{video_id}.*"):
        path.unlink()
        deleted = True
    return deleted
