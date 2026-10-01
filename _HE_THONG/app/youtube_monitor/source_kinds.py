"""What a source is, in one word, stored once on its row as videos.source_kind.

The kind used to be worked out wherever it was needed - the analysis step
from a payload marker, the running time and the description; Bước 1 from the
host and the key's prefix; the source list from the analysis. Each had its
own rules and they disagreed: an article with no description was analysed as
a video, because the one marker that said "article" was in a payload the
analysis step was never handed.

Now the importer that knows says it when the row is written, and everything
after reads the column. `for_row` holds the older rules, in this one place,
for rows written before the column existed and for writers that only ever
store one kind (the YouTube monitor).
"""

from __future__ import annotations

import re
from typing import Any

VIDEO = "video"
ARTICLE = "article"
PRODUCT = "product"
IMAGE_COLLECTION = "image_collection"
AUDIO = "audio"
WEB = "web"

SOURCE_KINDS = (VIDEO, ARTICLE, PRODUCT, IMAGE_COLLECTION, AUDIO, WEB)

# How the analysis step reads each kind (source_brief.Extraction.kind). A row
# with no kind is not a source: the placeholder behind an idea project.
ANALYSIS_KIND = {
    VIDEO: "video", AUDIO: "audio", ARTICLE: "article", WEB: "web",
    PRODUCT: "product", IMAGE_COLLECTION: "images",
}

# The filter each kind is counted under in "Nguồn tham khảo" › NGUỒN.
GROUPS = {VIDEO: "video", ARTICLE: "article", WEB: "article", PRODUCT: "product", AUDIO: "file", IMAGE_COLLECTION: "file"}

# Markers a first cut of "Thêm nguồn" wrote into the payload before this column.
_PAYLOAD_MARKERS = {"article_import": ARTICLE, "product_import": PRODUCT, "image_collection": IMAGE_COLLECTION}
# Extractors that read a page rather than a film (see main._probe_page_link).
_PAGE_EXTRACTORS = {"", "web", "shop", "generic", "html5mediaembed"}


def valid(kind: Any) -> str:
    """The kind if it is one of the six, else ""."""
    text = str(kind or "").strip().lower()
    return text if text in SOURCE_KINDS else ""


_AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac")
_YOUTUBE_VIDEO_ID = re.compile(r"[\w-]{11}")
_YOUTUBE_CHANNEL_ID = re.compile(r"UC[\w-]{22}")


def for_row(row: dict[str, Any], payload: dict[str, Any] | None = None) -> str:
    """The kind of a row whose writer did not state one; "" for an idea placeholder.

    Only what the row already holds is read - never the network - and a row
    with too little to go on is a web page: the one kind that claims nothing.
    """
    from .page_source import looks_like_shop

    payload = payload if isinstance(payload, dict) else {}
    video_id = str(row.get("youtube_video_id") or "")
    source = str(payload.get("source") or "")
    if video_id.startswith("idea-"):
        return IMAGE_COLLECTION if source == "image_collection" else ""
    if video_id.startswith("local-"):
        # What the probe of the bytes found, what the upload recorded, or the file's name.
        heard = (str(row.get("media_kind") or ""), str(payload.get("media_kind") or ""))
        path = str(row.get("local_media_path") or row.get("video_url") or "").lower()
        return AUDIO if "audio" in heard or path.endswith(_AUDIO_EXTENSIONS) else VIDEO
    if source in _PAYLOAD_MARKERS:
        return _PAYLOAD_MARKERS[source]
    if looks_like_shop(str(row.get("video_url") or "")):
        return PRODUCT
    youtube = payload.get("kind") == "youtube#video" or (
        _YOUTUBE_VIDEO_ID.fullmatch(video_id) and _YOUTUBE_CHANNEL_ID.fullmatch(str(row.get("youtube_channel_id") or ""))
    )
    if youtube or int(row.get("duration_seconds") or 0) > 0:
        return VIDEO  # something that plays
    # No running time: a page. With a description it was read as an article
    # before this column, and still is.
    if str(row.get("description") or "").strip():
        return ARTICLE
    extractor = str(payload.get("platform") or "").strip().lower()
    if source == "link_import" and extractor not in _PAGE_EXTRACTORS:
        return VIDEO  # yt-dlp read it as a film, running time or not
    return WEB
