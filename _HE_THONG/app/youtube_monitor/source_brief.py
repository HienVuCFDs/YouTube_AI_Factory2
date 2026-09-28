"""Turning a source of any kind into the one brief every later step reads.

The analysis step assumed a video. It called one AI with the title and the
description - never the transcript the app had just paid Whisper to make - and
asked it for SEO advice; the deeper analysis that actually reads the spoken
content existed but was not part of the flow and had never run. Meanwhile an
article link could not be imported at all, and uploaded images had a vision
analysis nobody called.

So the step is split in two. Extraction is mechanical and knows what kind of
source this is: it fetches, transcribes, reads and cuts frames, and understands
nothing. Analysis is one AI call over whatever extraction produced, and its
result has the same shape no matter where it came from.

Adding "article to video" or "images to video" later is then writing one
extractor, not reworking the step.

What a source does *not* have matters as much as what it does. Images carry a
look and no story; an article carries a story and no look; an idea carries
neither. Whoever writes the script has to know which, because inventing a
detail is right in one case and a falsehood in another - and that decision is
currently taken from a workflow the user picks by hand rather than from the
source itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SOURCE_KINDS = ("video", "article", "images", "product", "idea")

# Enough frames to follow what happens without becoming a wall the model skims.
SHEET_TILES = 12
MAX_TEXT_CHARS = 24_000
# What is stored with the brief for later checking. Larger than what is sent
# to the model, because the mechanical name/number comparison reads all of it.
MAX_SOURCE_TEXT_CHARS = 60_000


def preview_height(duration_seconds: float) -> int:
    """How much picture is worth fetching to cut twelve frames out of.

    The sheet scales every tile to 320px wide whatever it was given, so the
    bits above that are thrown away - and the download grows with the length
    of the source while the sheet does not. A minute costs about 4 MB at 480p;
    two hours would cost 450 MB to produce exactly the same twelve tiles.

    Short sources stay at 480p because the extra sharpness survives the
    downscale and is what lets a model read burned-in text, which has already
    caught one mis-transcription. Long ones drop, because 450 MB to read a few
    captions is not a trade worth making.
    """
    seconds = max(0.0, float(duration_seconds or 0))
    if seconds <= 0 or seconds <= 10 * 60:
        return 480
    if seconds <= 60 * 60:
        return 360
    return 240


@dataclass
class Extraction:
    """Everything the app could gather, and an honest note of what it could not."""

    kind: str
    text: str = ""
    text_label: str = ""
    image_sheet: Path | None = None
    image_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    # Things the extractor established that the reader must not miss - a
    # marketplace that would not hand over its price, for instance. Carried
    # into limitations so they survive into the brief.
    warnings: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)

    @property
    def has_story(self) -> bool:
        """Whether anything narrative was supplied at all."""
        return bool(self.text.strip())

    @property
    def has_dialogue(self) -> bool:
        """Spoken words specifically - an article has prose, not dialogue."""
        return self.kind == "video" and bool(self.text.strip())

    @property
    def has_visual_style(self) -> bool:
        """Whether the analyst was given pictures to look at."""
        return self.image_sheet is not None and self.image_sheet.is_file()

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.kind,
            "has_story": self.has_story,
            "has_dialogue": self.has_dialogue,
            "has_visual_style": self.has_visual_style,
            "text_chars": len(self.text),
            "image_count": self.image_count,
            "notes": list(self.notes),
            "warnings": list(self.warnings),
        }


BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "language": {"type": "string"},
        "content_type": {"type": "string"},
        "topic": {"type": "string"},
        "content_summary": {"type": "string"},
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "role": {"type": "string"}},
                "required": ["name", "role"],
                "additionalProperties": False,
            },
        },
        "dialogue": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "order": {"type": "integer"},
                    "speaker": {"type": "string"},
                    "line": {"type": "string"},
                    "start_seconds": {"type": "number"},
                    "end_seconds": {"type": "number"},
                },
                "required": ["order", "speaker", "line"],
                "additionalProperties": False,
            },
        },
        "scene_map": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"order": {"type": "integer"}, "what_happens": {"type": "string"}},
                "required": ["order", "what_happens"],
                "additionalProperties": False,
            },
        },
        "visual_style": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "language", "content_type", "topic", "content_summary",
        "characters", "dialogue", "scene_map", "visual_style", "keywords", "limitations",
    ],
    "additionalProperties": False,
}


SYSTEM_PROMPT = """Ban ghi lai mot nguon co san, cho nguoi khong tiep xuc duoc voi no va se
dung lai thanh video moi.

Hai thu quan trong nhat:
1. NOI DUNG, day du. Moi su viec, dung thu tu, den het. Khong phai ban tom tat - bo sot cai gi
   la mat cai do.
2. LOI THOAI, neu nguon co tieng noi. Tung cau, ghi ro ai noi, dung tu cua ho. Loi dan cung tinh,
   ghi la "Nguoi dan". Khong dien giai mot cau thoai thanh mo ta ve no.

Neu ban duoc dua anh: mo ta phong cach hinh anh tu nhung gi BAN THUC SU NHIN THAY - chat lieu,
mau, anh sang, bo cuc, goc may. Khong duoc dua anh thi de trong visual_style, TUYET DOI khong doan.

Khong bia bat cu thu gi. Ban ghi am tu dong nghe nham chu, nuot am va nhap nhang nguoi noi. Cho
nao khong ro ai noi thi ghi "Khong ro". Cho nao cau bi vo thi giu phan nghe duoc. Moi cho nhu vay
phai ghi vao limitations, de nguoi sau khong nham mot phong doan thanh su that.

Ban khong quyet dinh video moi duoc giu gi hay doi gi - viec do de buoc viet kich ban. Chi tra ve
dung JSON theo schema."""


def _kind_instruction(extraction: Extraction) -> str:
    """Say plainly what this source is and what it cannot supply.

    Written as a statement of fact rather than a rule, because the model is
    good at honouring "there is no X here" and bad at honouring "do not invent
    X" when nothing tells it X is absent.
    """
    if extraction.kind == "video" and not extraction.has_dialogue:
        # A music video, a timelapse, gameplay or plain b-roll. Telling it the
        # transcript is attached when nothing was attached is how a model ends
        # up quoting lines that were never said.
        return (
            "NGUON LA MOT VIDEO KHONG CO LOI NOI. Ban chi nhan mot bang cac khung hinh lay deu "
            "tu video; khong co loi thoai nao. De dialogue rong, va ghi ro trong limitations rang "
            "moi loi dan sau nay la do nguoi viet sang tac."
        )
    lines = {
        "video": "NGUON LA MOT VIDEO. Ban nhan loi thoai da phien am va mot bang cac khung hinh lay deu tu video.",
        "article": "NGUON LA MOT BAI VIET. Ban nhan noi dung chu cua bai. Bai viet khong co loi thoai noi, de dialogue rong.",
        "images": "NGUON CHI LA ANH TINH. Khong co loi thoai va khong co cot chuyen; hay mo ta that ky phong cach hinh anh, va ghi ro trong limitations rang moi cot chuyen sau nay la do nguoi viet sang tac.",
        "product": (
            "NGUON LA MOT TRANG BAN HANG. Cac con so o day - gia, dung luong, kich thuoc, so sao, "
            "so danh gia - la loi khang dinh ve mot mon hang nguoi xem co the mua. Chi duoc ghi lai "
            "dung nhung gi co trong du lieu duoc cung cap. Truong nao khong co thi de trong va ghi "
            "vao limitations; TUYET DOI khong suy ra, khong lam tron, khong doan."
        ),
        "idea": "KHONG CO NGUON NAO, chi co y tuong cua nguoi dung. Moi thu ban ghi ra deu la dien giai y tuong do, hay ghi ro dieu nay trong limitations.",
    }
    text = lines.get(extraction.kind, lines["idea"])
    if not extraction.has_visual_style:
        text += "\nBan KHONG duoc dua bat ky hinh anh nao, nen de visual_style rong."
    return text


def build_prompt(extraction: Extraction) -> str:
    """The user half of the one analysis call."""
    metadata = extraction.metadata or {}
    parts = [_kind_instruction(extraction), ""]
    for label, key in (("Tieu de", "title"), ("Mo ta", "description"), ("Thoi luong (giay)", "duration_seconds")):
        value = str(metadata.get(key) or "").strip()
        if value:
            parts.append(f"{label}: {value[:2000]}")
    if metadata.get("url"):
        parts.append(f"Duong dan: {metadata['url']}")
    if extraction.notes:
        parts.append("Ghi chu cua nguoi dung: " + " | ".join(extraction.notes)[:2000])
    if extraction.text.strip():
        parts.append(
            f"\n{extraction.text_label or 'Noi dung nguon'}:\n{extraction.text[:MAX_TEXT_CHARS]}"
        )
    if extraction.has_visual_style:
        parts.append(
            f"\nAnh dinh kem: mot bang {extraction.image_count} khung hinh. Hay xem va mo ta phong cach."
        )
    return "\n".join(parts)


def _app_limitations(extraction: Extraction) -> list[str]:
    """What the app knows was missing, written before the model says anything.

    These are facts about the handover, not judgements, so they are stated by
    the side that did the handing over.
    """
    missing: list[str] = []
    if not extraction.has_story:
        missing.append(
            "Nguồn không cung cấp nội dung chữ nào. Mọi cốt chuyện và lời dẫn sau này là do AI sáng tác."
        )
    if not extraction.has_dialogue and extraction.kind != "idea":
        missing.append("Nguồn không có lời thoại nói.")
    if not extraction.has_visual_style:
        missing.append(
            "Không có hình ảnh nào của nguồn để xem, nên phong cách hình ảnh chưa được xác định."
        )
    return missing + [str(item) for item in extraction.warnings]


def finalise(parsed: dict[str, Any], extraction: Extraction, provider: str) -> dict[str, Any]:
    """Merge the model's answer with what the app knows for certain.

    The three `has_*` flags are decided here, not asked of the model: they
    describe what was handed over, and the side that did the handing over is
    the one that cannot be wrong about it. A model told to look at pictures it
    never received will otherwise describe them.
    """
    brief = dict(parsed or {})
    limitations = [str(item).strip() for item in (brief.get("limitations") or []) if str(item).strip()]
    brief["limitations"] = _app_limitations(extraction) + limitations
    if not extraction.has_visual_style:
        brief["visual_style"] = ""
    if not extraction.has_dialogue:
        brief["dialogue"] = []
    brief.update(extraction.as_dict())
    # Kept with the brief, not discarded after the call. Checking a script
    # against what the source actually said needs the source, and reaching for
    # the transcript is why that check only ever worked for videos - an
    # article or a product page had nothing to compare against. Re-extracting
    # instead would mean downloading the video and running Whisper again.
    brief["source_text"] = extraction.text[:MAX_SOURCE_TEXT_CHARS]
    if extraction.facts:
        # Read off the page, not inferred by a model. Kept separate so a later
        # step can compare what the script says against what the page said.
        brief["source_facts"] = extraction.facts
    brief["provider"] = provider
    brief["source_type"] = extraction.kind
    return brief


def metadata_row(brief: dict[str, Any], title: str) -> dict[str, Any]:
    """The older, smaller analysis shape, derived rather than asked for again.

    Several places still read the metadata analysis. Deriving it from the one
    brief keeps them working without a second call to a model for facts the
    first call already established.
    """
    keywords = [str(item).strip() for item in (brief.get("keywords") or []) if str(item).strip()]
    return {
        "provider": str(brief.get("provider") or ""),
        "source_type": "metadata",
        "title": title,
        "language": str(brief.get("language") or ""),
        "content_type": str(brief.get("content_type") or "general"),
        "topic": str(brief.get("topic") or ""),
        "keywords": [{"keyword": word, "count": 1} for word in keywords[:12]],
        "hook": "",
        "description_opening": "",
        "metrics": {"title_length": len(title)},
        "recommendations": [],
        "next_step": "script_writing",
    }


def detect_kind(
    project: dict[str, Any],
    video: dict[str, Any] | None,
    image_assets: list[dict[str, Any]] | None = None,
) -> str:
    """What kind of source this project actually has."""
    if video and str(video.get("youtube_video_id") or "").strip():
        # An idea project is stored against a placeholder video row, so the
        # presence of a row is not by itself a source.
        if not str(video.get("youtube_video_id") or "").startswith("idea-"):
            from .page_source import looks_like_shop

            if looks_like_shop(str(video.get("video_url") or "")):
                return "product"
            return "article" if _is_article(video) else "video"
    if image_assets:
        return "images"
    return "idea"


def _is_article(video: dict[str, Any]) -> bool:
    payload = video.get("raw_payload") or {}
    if isinstance(payload, dict) and str(payload.get("source") or "") == "article_import":
        return True
    return int(video.get("duration_seconds") or 0) <= 0 and bool(str(video.get("description") or "").strip())


def article_text(html_or_text: str, *, max_chars: int = MAX_TEXT_CHARS) -> str:
    """Readable body text, whether the caller already stripped the tags or not."""
    body = str(html_or_text or "")
    if "<" in body and ">" in body:
        body = re.sub(r"(?is)<(script|style|nav|footer|header|form)[^>]*>.*?</\1>", " ", body)
        body = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", body).strip()[:max_chars]
