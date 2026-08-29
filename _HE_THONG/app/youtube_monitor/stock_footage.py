"""Real footage from open archives, as a scene provider that costs nothing.

Every other video provider in this app spends something: Flow credit, a
subscription quota, or a paid API call. That is why the pipeline has spent
weeks blocked on "wait for Flow credit". These archives hand out real,
finished footage for free, which is enough to run a scene end to end today.

Only sources whose whole catalogue is public domain are used here. A
per-file licence check is a different and much larger job than a per-source
one, so Wikimedia Commons — where the licence varies by file and often
requires attribution in a specific form — is deliberately left out until
that check exists.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

import httpx

from .database import Database
from .ffmpeg_renderer import _encoding_arguments, media_duration_seconds, nvenc_available, resolve_ffmpeg
from .project_layout import ensure_project_layout


class StockFootageError(RuntimeError):
    pass


ARCHIVE_ORG = "archive_org"
NASA = "nasa"
STOCK_SOURCES = (ARCHIVE_ORG, NASA)

# Downloading a two-hour archival master to cut five seconds out of it wastes
# minutes and disk for no gain. Anything larger is skipped in favour of the
# next candidate.
MAX_DOWNLOAD_BYTES = 160 * 1024 * 1024
_HTTP_TIMEOUT = httpx.Timeout(60.0, connect=20.0)
_USER_AGENT = "YouTubeAIFactory/1.0 (+local research tool)"

# Words that describe how a shot should look, not what is in it. Archive
# search engines match titles and catalogue descriptions, so leaving these in
# a query returns nothing at all.
_STYLE_WORDS = frozenset(
    """
    cinematic photorealistic realistic detailed intricate stunning beautiful
    gorgeous dramatic epic moody atmospheric vibrant muted soft harsh warm cool
    golden hour blue backlit rim lighting volumetric bokeh depth
    field shallow wide close macro low angle high shot
    frame framing composition rule thirds symmetrical centered portrait
    orientation ratio resolution 4k 8k hd uhd quality render
    rendering octane unreal engine style styled art artistic painterly
    illustration illustrated digital concept design 35mm 50mm lens camera
    photograph photography photo image picture scene shot clip footage video
    no text caption captions typography logo logos watermark watermarks
    """.split()
)
_STOPWORDS = frozenset(
    """
    a an the and or of in on at to for with without from by as is are was were
    be being been it its this that these those there here very more most much
    many some any all each every into over under above below near far during
    while when where which who whom whose what how why not non
    """.split()
)


@dataclass(frozen=True, slots=True)
class StockClip:
    """One candidate clip, normalised across sources."""

    source: str
    clip_id: str
    title: str
    page_url: str
    download_url: str
    duration_seconds: float
    size_bytes: int
    license: str
    attribution: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def search_keywords(prompt: str, *, maximum: int = 6) -> str:
    """Reduce a cinematic scene prompt to words an archive can match.

    A storyboard prompt is written for an image model: long, and mostly about
    lighting and lens. Archive search matches catalogue text, so the style
    half of the prompt actively hurts.
    """
    words = re.findall(r"[a-zA-Z]{3,}", prompt.lower())
    keywords: list[str] = []
    for word in words:
        if word in _STYLE_WORDS or word in _STOPWORDS or word in keywords:
            continue
        keywords.append(word)
        if len(keywords) >= maximum:
            break
    return " ".join(keywords)


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=_HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    )


def _search_archive_org(client: httpx.Client, query: str, limit: int) -> list[StockClip]:
    """Search the Prelinger archive, whose films are all public domain."""
    if not query:
        return []
    try:
        response = client.get(
            "https://archive.org/advancedsearch.php",
            params=[
                ("q", f"collection:(prelinger) AND mediatype:(movies) AND ({query})"),
                ("fl[]", "identifier"),
                ("fl[]", "title"),
                ("rows", str(max(1, limit))),
                ("output", "json"),
            ],
        )
        response.raise_for_status()
        documents = response.json()["response"]["docs"]
    except (httpx.HTTPError, ValueError, KeyError):
        return []
    clips: list[StockClip] = []
    for document in documents:
        identifier = str(document.get("identifier") or "")
        if not identifier:
            continue
        try:
            metadata = client.get(f"https://archive.org/metadata/{identifier}").json()
        except (httpx.HTTPError, ValueError):
            continue
        for item in metadata.get("files") or []:
            name = str(item.get("name") or "")
            if not name.lower().endswith(".mp4"):
                continue
            size = int(float(item.get("size") or 0))
            if size <= 0 or size > MAX_DOWNLOAD_BYTES:
                continue
            clips.append(
                StockClip(
                    source=ARCHIVE_ORG,
                    clip_id=f"{identifier}/{name}",
                    title=str(document.get("title") or identifier)[:200],
                    page_url=f"https://archive.org/details/{identifier}",
                    download_url=f"https://archive.org/download/{identifier}/{name}",
                    duration_seconds=float(item.get("length") or 0) if str(item.get("length") or "").replace(".", "", 1).isdigit() else 0.0,
                    size_bytes=size,
                    license="public-domain",
                    attribution=f"Prelinger Archives via Internet Archive — {document.get('title') or identifier}",
                )
            )
            break
    return clips


def _search_nasa(client: httpx.Client, query: str, limit: int) -> list[StockClip]:
    """Search NASA's media library, which is public domain by policy."""
    if not query:
        return []
    try:
        response = client.get(
            "https://images-api.nasa.gov/search",
            params={"q": query, "media_type": "video", "page_size": max(1, limit)},
        )
        response.raise_for_status()
        items = response.json()["collection"]["items"]
    except (httpx.HTTPError, ValueError, KeyError):
        return []
    clips: list[StockClip] = []
    for item in items[:limit]:
        data = (item.get("data") or [{}])[0]
        nasa_id = str(data.get("nasa_id") or "")
        collection_url = str(item.get("href") or "")
        if not nasa_id or not collection_url:
            continue
        try:
            files = client.get(collection_url).json()
        except (httpx.HTTPError, ValueError):
            continue
        # NASA publishes the same clip at several sizes. "medium" is the
        # largest that stays comfortably inside the download cap.
        candidates = [str(url) for url in files if str(url).lower().endswith(".mp4")]
        chosen = ""
        for marker in ("~medium.mp4", "~small.mp4", "~mobile.mp4", "~large.mp4"):
            chosen = next((url for url in candidates if url.endswith(marker)), "")
            if chosen:
                break
        if not chosen and candidates:
            chosen = candidates[0]
        if not chosen:
            continue
        clips.append(
            StockClip(
                source=NASA,
                clip_id=nasa_id,
                title=str(data.get("title") or nasa_id)[:200],
                page_url=f"https://images.nasa.gov/details/{nasa_id}",
                download_url=chosen,
                duration_seconds=0.0,
                size_bytes=0,
                license="public-domain",
                attribution=f"NASA — {data.get('title') or nasa_id}",
            )
        )
    return clips


def rank_clips(clips: list[StockClip], prompt: str) -> list[StockClip]:
    """Put the candidate whose title shares most with the scene first.

    Widening a query to get any result at all also lets in films that merely
    share a common word. Title overlap is a crude signal, but it reliably
    beats "whichever archive answered first", and the app's own vision review
    still judges the finished clip against the storyboard afterwards.
    """
    keywords = set(search_keywords(prompt, maximum=12).split())
    if not keywords:
        return clips

    def score(clip: StockClip) -> tuple[int, int]:
        title_words = set(re.findall(r"[a-zA-Z]{3,}", clip.title.lower()))
        return (len(keywords & title_words), clip.size_bytes)

    return sorted(clips, key=score, reverse=True)


def search_stock_clips(
    prompt: str,
    *,
    limit: int = 4,
    sources: Iterable[str] = STOCK_SOURCES,
    client: httpx.Client | None = None,
) -> list[StockClip]:
    """Find candidate clips for a scene prompt across the open archives."""
    wanted = [source for source in sources if source in STOCK_SOURCES]
    owned = client is None
    active = client or _client()
    try:
        # An archive matches catalogue text, not meaning, so a six-word query
        # describing one specific shot usually matches nothing. Widen the
        # query until something comes back rather than reporting no footage
        # exists for the scene.
        for width in (6, 4, 2):
            query = search_keywords(prompt, maximum=width)
            if not query:
                continue
            clips: list[StockClip] = []
            for source in wanted:
                if source == ARCHIVE_ORG:
                    clips.extend(_search_archive_org(active, query, limit))
                elif source == NASA:
                    clips.extend(_search_nasa(active, query, limit))
            if clips:
                return rank_clips(clips, prompt)
        return []
    finally:
        if owned:
            active.close()


def _download(client: httpx.Client, clip: StockClip, destination: Path) -> Path:
    """Stream a clip to disk, refusing anything past the size cap."""
    written = 0
    try:
        with client.stream("GET", clip.download_url) as response:
            response.raise_for_status()
            declared = int(response.headers.get("content-length") or 0)
            if declared > MAX_DOWNLOAD_BYTES:
                raise StockFootageError(
                    f"Clip {clip.clip_id} nang {declared / 1e6:.0f} MB, vuot gioi han tai ve"
                )
            with destination.open("wb") as handle:
                for chunk in response.iter_bytes(1024 * 256):
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        raise StockFootageError(f"Clip {clip.clip_id} vuot gioi han tai ve khi dang tai")
                    handle.write(chunk)
    except httpx.HTTPError as exc:
        destination.unlink(missing_ok=True)
        raise StockFootageError(f"Khong tai duoc clip tu {clip.source}: {exc}") from exc
    except StockFootageError:
        destination.unlink(missing_ok=True)
        raise
    if written == 0:
        destination.unlink(missing_ok=True)
        raise StockFootageError(f"Clip tai ve tu {clip.source} rong")
    return destination


def _target_size(ratio: str) -> tuple[int, int]:
    parts = str(ratio or "").replace("x", ":").split(":")
    try:
        width, height = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return 1280, 720
    if width <= 0 or height <= 0:
        return 1280, 720
    # FFmpeg's scale and most encoders reject odd dimensions.
    return width - width % 2, height - height % 2


def _cut_scene_clip(
    source_path: Path,
    output_path: Path,
    *,
    duration_seconds: float,
    ratio: str,
    ffmpeg_binary: str,
) -> None:
    """Cut one scene-length window and normalise it to the project format.

    The window is taken from a little way in: archival films open on titles,
    leaders and countdowns, which are exactly what a storyboard scene must
    not show.
    """
    executable = resolve_ffmpeg(ffmpeg_binary)
    if not executable:
        raise StockFootageError(f"Khong tim thay FFmpeg ({ffmpeg_binary}) tren may")
    width, height = _target_size(ratio)
    wanted = max(1.0, float(duration_seconds))
    available = media_duration_seconds(source_path, ffmpeg_binary) or 0.0
    if available and available < wanted:
        raise StockFootageError(
            f"Clip nguon chi dai {available:.1f}s, ngan hon canh can {wanted:.1f}s"
        )
    start = 0.0
    if available > wanted:
        start = min(max(2.0, (available - wanted) / 2), available - wanted)
    codec = "h264_nvenc" if nvenc_available(ffmpeg_binary) else "libx264"
    arguments = [
        executable, "-y",
        "-ss", f"{start:.3f}",
        "-t", f"{wanted:.3f}",
        "-i", str(source_path),
        "-vf",
        (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps=30"
        ),
        # A scene clip carries no sound: narration is mixed in by the
        # timeline, and archival audio would fight it.
        "-an",
        *_encoding_arguments(codec),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    completed = subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-1200:]
        raise StockFootageError(f"FFmpeg khong cat duoc clip nguon: {detail}")


def _record_attribution(project_root: Path, output_path: Path, clip: StockClip) -> Path:
    """Keep the credit line the published video will need.

    Public domain does not require attribution, but a viewer asking where a
    shot came from — or a copyright claim on archival footage — is answered
    only if the provenance was kept at the moment the clip was used.
    """
    manifest_path = project_root / "NGUON_FOOTAGE.json"
    entries: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                entries = loaded
        except (OSError, ValueError):
            entries = {}
    entries[output_path.name] = clip.as_dict()
    manifest_path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest_path


def generate_stock_footage_scene(
    database: Database,
    job: dict[str, Any],
    artifact_root: Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
    client: httpx.Client | None = None,
) -> str:
    """Fill one scene with real footage from an open archive."""
    del database  # The provider contract passes it; this source needs none.
    prompt = str(job.get("prompt") or "").strip()
    if not prompt:
        raise StockFootageError("Prompt tim footage dang trong")
    owned = client is None
    active = client or _client()
    try:
        candidates = search_stock_clips(prompt, client=active)
        if not candidates:
            raise StockFootageError(
                f"Khong tim thay footage mo cho canh nay (tu khoa: {search_keywords(prompt) or '(rong)'})"
            )
        layout = ensure_project_layout(artifact_root, job["project_id"])
        output_dir = layout["assets"] / "generated_scenes"
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = f"stock-segment-{int(job['timeline_segment_id'])}-job-{int(job['id'])}"
        output_path = output_dir / f"{stem}.mp4"
        source_path = output_dir / f"{stem}.source"
        duration = max(1, int(job.get("duration_seconds") or 5))
        failures: list[str] = []
        for clip in candidates:
            try:
                _download(active, clip, source_path)
                _cut_scene_clip(
                    source_path,
                    output_path,
                    duration_seconds=duration,
                    ratio=str(job.get("ratio") or ""),
                    ffmpeg_binary=ffmpeg_binary,
                )
            except StockFootageError as exc:
                # One unusable archival file must not fail the scene while
                # other candidates are still untried.
                failures.append(f"{clip.clip_id}: {exc}")
                output_path.unlink(missing_ok=True)
                continue
            finally:
                source_path.unlink(missing_ok=True)
            _record_attribution(layout["root"], output_path, clip)
            return str(output_path)
        raise StockFootageError("Moi ung vien footage deu khong dung duoc. " + " | ".join(failures)[:2000])
    finally:
        if owned:
            active.close()
