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


def for_row(row: dict[str, Any], payload: dict[str, Any] | None = None) -> str:
    """The kind of a row whose writer did not state one; "" for an idea placeholder."""
    from .page_source import looks_like_shop

    payload = payload if isinstance(payload, dict) else {}
    video_id = str(row.get("youtube_video_id") or "")
    source = str(payload.get("source") or "")
    if video_id.startswith("idea-"):
        return IMAGE_COLLECTION if source == "image_collection" else ""
    if video_id.startswith("local-"):
        return AUDIO if str(payload.get("media_kind") or "") == "audio" else VIDEO
    if source in _PAYLOAD_MARKERS:
        return _PAYLOAD_MARKERS[source]
    if looks_like_shop(str(row.get("video_url") or "")):
        return PRODUCT
    if payload.get("kind") == "youtube#video":
        return VIDEO
    if int(row.get("duration_seconds") or 0) <= 0:
        # No running time: text to read, the rule the analysis step used.
        if str(row.get("description") or "").strip():
            return ARTICLE
        # A page imported with no description used to be taken for a video.
        extractor = str(payload.get("platform") or "").strip().lower()
        if source == "link_import" and extractor in _PAGE_EXTRACTORS:
            return WEB
    return VIDEO
