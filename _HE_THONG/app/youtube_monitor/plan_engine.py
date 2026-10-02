"""Bước 2 · Kế hoạch - Phase 3, second half: from insights to a plan that can be made.

    InsightReport (+ project settings, available assets)  →  ProjectPlan  →  Feasibility

A second model call chooses an angle among the validated candidates and lays
out the video: who it is for, how it opens, its sections with a time budget,
which kinds of media carry it, how it is cut. Then the code decides what the
model may not:

* platform, aspect ratio, output profile and language come from the project's
  settings, never from the answer;
* every insight and evidence id the plan cites must exist;
* claims the evidence does not carry are written into the plan as guardrails
  and claims to avoid - a disputed fact, a price with no reading, a selling
  point nobody showed;
* what is missing is decided from what the project holds (`review_assets`,
  `missing_assets`), not from the answer: the model proposes assets, the code
  checks each against the source footage, the images, the transcript and the
  uploads, and an asset that is there is never listed as missing;
* whether it can be made at all is checked by rule (`feasibility`): the time
  budget against the target, the media against the length, the transcript,
  the missing assets. A gap is reported with options. The plan is never
  quietly changed to fit - only a small drift in the time budget is rescaled,
  and that is recorded as an adjustment.

The step is finished (`completed`) only when feasibility is ok or adjusted.
`needs_attention` leaves it waiting on a person (`needs_user_decision`).

A plan is a strategy: it names kinds of media and a cutting style, not scenes
and not a timeline.
"""

from __future__ import annotations

import re
from math import gcd
from pathlib import Path
from typing import Any

from . import freshness, research_evidence, workflows
from .shorts import MAX_SHORT_SECONDS, MIN_SHORT_SECONDS, OUTPUT_PROFILE_SIZES, VERTICAL_PROFILES

ENGINE_VERSION = "plan-phase3"

PROFILE_PLATFORM = {
    "youtube_landscape": "youtube", "youtube_shorts": "youtube", "tiktok": "tiktok",
    "instagram_reels": "instagram", "facebook_reels": "facebook", "facebook_feed": "facebook",
}
MEDIA_SOURCES = (
    "source_footage", "product_images", "source_images", "screenshots", "b_roll", "ai_media", "diagrams", "graphics",
)
# Media the app holds a fixed amount of; the rest can be made or found to length.
FINITE_MEDIA = frozenset({"source_footage", "product_images", "source_images"})
STILL_SECONDS = 5  # how long one still image reasonably holds the screen
# Above this a vertical short-form video is no longer what the profile is for.
VERTICAL_ATTENTION_SECONDS = 180
LANDSCAPE_RANGE = (30, 1800)
# How far the sections may drift from the target before it is a decision for a person.
BUDGET_TOLERANCE = 0.10
BUDGET_RESCALE = 0.20
MEDIA_COVERAGE = 0.8

OK, ADJUSTED, NEEDS_ATTENTION, BLOCKED = "ok", "adjusted", "needs_attention", "blocked"
_RANK = {OK: 0, ADJUSTED: 1, NEEDS_ATTENTION: 2, BLOCKED: 3}

# What a feasibility verdict means for the step. Only a plan nobody has to
# decide anything about is a finished Bước 2.
COMPLETED, NEEDS_USER_DECISION, STALE = "completed", "needs_user_decision", "stale"
STEP_STATUS = {OK: COMPLETED, ADJUSTED: COMPLETED, NEEDS_ATTENTION: NEEDS_USER_DECISION, BLOCKED: BLOCKED}
# Plans saved before the statuses were named this way.
LEGACY_STATUS = {"ready": COMPLETED, "needs_attention": NEEDS_USER_DECISION}

# What a proposed asset can be. The first seven can be checked against the
# project; a reference document or anything else cannot, so it stays a
# proposal; and what the app makes in a later step is never missing.
ASSET_CATEGORIES = (
    "source_footage", "source_images", "product_images", "transcript", "source_audio",
    "user_footage", "user_images", "reference", "generated", "other",
)
EXISTS, APP_GENERATES, MISSING, UNVERIFIED = "exists", "app_generates", "missing", "unverified"
_GENERATED = re.compile(
    r"kịch bản|lời dẫn|giọng đọc|thuyết minh|lồng tiếng|phụ đề|nhạc nền|hình ai\b|ảnh ai\b|sơ đồ|đồ ho[ạa]|infographic"
    r"|voice ?over|\bscript\b|subtitle",
    re.IGNORECASE,
)
# A proposal the model filed under "other" is put where its words say it belongs.
_FOOTAGE = re.compile(r"cảnh quay|quay thử|footage|video (thật|thực tế|quay)", re.IGNORECASE)
_PICTURES = re.compile(r"ảnh chụp|hình chụp|ảnh thật|ảnh thực tế", re.IGNORECASE)
ASSET_LABELS = {
    "source_footage": "Cảnh quay từ nguồn", "source_images": "Ảnh từ nguồn", "product_images": "Ảnh sản phẩm",
    "transcript": "Lời thoại / transcript của nguồn", "source_audio": "Âm thanh của nguồn",
    "user_footage": "Cảnh quay thật tải vào dự án", "user_images": "Ảnh thật tải vào dự án",
}


def step_status(feasibility_status: str) -> str:
    return STEP_STATUS.get(str(feasibility_status or ""), NEEDS_USER_DECISION)

SYSTEM_PROMPT = """Ban la dao dien noi dung. Ban nhan: ket qua phan tich nguon, cac INSIGHT da duoc kiem chung (moi insight co ma
[in-...]), cac GOC NOI DUNG ung vien (ma [ang-...]), cai dat cua du an va nhung tu lieu dang co. Viec cua ban: lap
KE HOACH cho mot video - chien luoc, khong phai kich ban va khong phai storyboard.

Luat bat buoc:
1. Chon primary_angle_id trong cac goc ung vien da cho. Khong tu nghi ra goc moi. alternative_angle_ids la cac goc con lai dang giu.
2. Nen tang, ti le khung hinh, ngon ngu da duoc du an quyet dinh - khong doi.
3. Neu du an da dat thoi luong muc tieu thi dung dung con so do. content_structure phai co estimated_seconds cho tung phan
   va TONG phai xap xi thoi luong muc tieu. Video 60 giay thi tong khong duoc thanh 95-120 giay.
4. Moi phan trong content_structure ghi insight_ids / evidence_ids ma no dua vao. Chi dung ma co trong du lieu.
5. Gia thuyet (danh dau GIA THUYET) khong phai su that: khong dua thanh khang dinh trong video.
6. media_strategy chi o muc chien luoc: loai tu lieu nao la chinh, loai nao ho tro. Khong liet ke tung canh.
   Chi chon source_footage khi nguon co hinh de cat. Nguon am thanh khong co hinh.
7. edit_direction la huong dung: nhip, do dai canh trung binh, kieu cat, chuyen canh, chu dong, phu de, callout, zoom, B-roll,
   do hoa. Khong tao timeline.
8. factual_guardrails: dieu video phai giu dung. claims_to_avoid: dieu video khong duoc noi. Gia chi dung tai thoi diem da doc.
9. proposed_assets: tu lieu ban DE XUAT bo sung cho ke hoach. Ban khong quyet dinh cai gi dang thieu - app tu doi chieu voi tu lieu
   that cua du an. Moi muc chon mot category: source_footage (canh quay cua chinh nguon), source_images (anh cua nguon / bo anh),
   product_images, transcript, source_audio, user_footage (canh quay that nguoi dung phai tu quay hoac tai len), user_images (anh that
   nguoi dung phai cung cap), reference (tai lieu, so lieu de kiem chung), generated (thu app tu tao o buoc sau: kich ban, giong doc,
   hinh AI, so do/do hoa, phu de, nhac nen), other. required=true chi khi khong co no thi khong lam duoc video theo ke hoach nay.
10. Khong tu y doi mot quyet dinh lon de cho vua (vi du rut video 8 phut con 3 phut). Neu thay khong kha thi, cu lap ke hoach
    theo yeu cau va ghi van de vao limitations - app se kiem tra tinh kha thi.
11. video_type la mot nhan ngan 2-5 tu (vi du: giai thich nhanh, review san pham, tin nhanh, ke chuyen). limitations chi noi ve
    du lieu va ke hoach, khong noi ve ban than AI hay cong cu.
12. Viet bang ngon ngu cua du an (tieng Viet thi co dau day du). Chi tra ve JSON dung schema."""

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "video_type": {"type": "string"},
        "target_duration_seconds": {"type": "integer"},
        "target_audience": {"type": "string"},
        "goal": {"type": "string"},
        "primary_angle_id": {"type": "string"},
        "alternative_angle_ids": {"type": "array", "items": {"type": "string"}},
        "hook_strategy": {"type": "string"},
        "content_structure": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "purpose": {"type": "string"},
                    "estimated_seconds": {"type": "integer"},
                    "key_points": {"type": "array", "items": {"type": "string"}},
                    "insight_ids": {"type": "array", "items": {"type": "string"}},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "purpose", "estimated_seconds", "key_points", "insight_ids", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "media_strategy": {
            "type": "object",
            "properties": {
                "primary_sources": {"type": "array", "items": {"type": "string", "enum": list(MEDIA_SOURCES)}},
                "supporting_sources": {"type": "array", "items": {"type": "string", "enum": list(MEDIA_SOURCES)}},
                "notes": {"type": "string"},
            },
            "required": ["primary_sources", "supporting_sources", "notes"],
            "additionalProperties": False,
        },
        "edit_direction": {
            "type": "object",
            "properties": {
                "pacing": {"type": "string"},
                "average_shot_length_seconds": {"type": "number"},
                "cut_style": {"type": "string"},
                "transitions": {"type": "string"},
                "text_animation": {"type": "string"},
                "subtitle_style": {"type": "string"},
                "callouts": {"type": "string"},
                "zoom_punch_in": {"type": "string"},
                "broll_usage": {"type": "string"},
                "graphics": {"type": "string"},
            },
            "required": ["pacing", "average_shot_length_seconds", "cut_style", "transitions", "text_animation",
                         "subtitle_style", "callouts", "zoom_punch_in", "broll_usage", "graphics"],
            "additionalProperties": False,
        },
        "subtitle_strategy": {"type": "string"},
        "music_strategy": {"type": "string"},
        "sfx_strategy": {"type": "string"},
        "cta": {"type": "string"},
        "factual_guardrails": {"type": "array", "items": {"type": "string"}},
        "claims_to_avoid": {"type": "array", "items": {"type": "string"}},
        "proposed_assets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "asset": {"type": "string"}, "why": {"type": "string"},
                    "category": {"type": "string", "enum": list(ASSET_CATEGORIES)}, "required": {"type": "boolean"},
                },
                "required": ["asset", "why", "category", "required"],
                "additionalProperties": False,
            },
        },
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "video_type", "target_duration_seconds", "target_audience", "goal", "primary_angle_id", "alternative_angle_ids",
        "hook_strategy", "content_structure", "media_strategy", "edit_direction", "subtitle_strategy", "music_strategy",
        "sfx_strategy", "cta", "factual_guardrails", "claims_to_avoid", "proposed_assets", "limitations",
    ],
    "additionalProperties": False,
}


def _clean(value: Any, limit: int = 600) -> str:
    return research_evidence.impersonal(" ".join(str(value or "").split()))[:limit]


def _texts(values: Any, limit: int, size: int = 300) -> list[str]:
    return list(dict.fromkeys(_clean(item, size) for item in values or [] if _clean(item)))[:limit]


def aspect_ratio(profile: str) -> str:
    width, height = OUTPUT_PROFILE_SIZES.get(profile, (1920, 1080))
    divisor = gcd(width, height) or 1
    return f"{width // divisor}:{height // divisor}"


def duration_range(profile: str) -> dict[str, int]:
    """What this output profile is for, in seconds: the floor, the usual ceiling, and where it stops fitting."""
    if profile in VERTICAL_PROFILES:
        return {"min": MIN_SHORT_SECONDS, "recommended_max": MAX_SHORT_SECONDS, "attention_above": VERTICAL_ATTENTION_SECONDS}
    return {"min": LANDSCAPE_RANGE[0], "recommended_max": LANDSCAPE_RANGE[1], "attention_above": LANDSCAPE_RANGE[1]}


def settings_for(
    project: dict[str, Any], render_settings: dict[str, Any], *, language: str, requested: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """What the project has decided, and what this run was asked to plan for.

    `requested` (a duration, a video type, another output profile) is what a
    person changes without the research changing; it is recorded on the plan.
    """
    requested = dict(requested or {})
    profile = str(requested.get("output_profile") or render_settings.get("output_profile") or "youtube_landscape")
    if profile not in OUTPUT_PROFILE_SIZES:
        profile = "youtube_landscape"
    workflow = workflows.get(project.get("workflow"))
    try:
        duration = int(requested["target_duration_seconds"]) if requested.get("target_duration_seconds") else None
    except (TypeError, ValueError):
        duration = None
    return {
        "output_profile": profile,
        "platform": PROFILE_PLATFORM.get(profile, "youtube"),
        "aspect_ratio": aspect_ratio(profile),
        "vertical": profile in VERTICAL_PROFILES,
        "language": str(render_settings.get("publish_language") or language or "vi"),
        "workflow": workflow.key,
        "script_mode": workflow.script_mode,
        "scene_asset_type": workflow.scene_asset_type,
        "target_duration_seconds": duration if duration and duration > 0 else None,
        "video_type": _clean(requested.get("video_type"), 80),
        # The angle a person picked among the candidates; the model plans for it and may not pick another.
        "primary_angle_id": str(requested.get("primary_angle_id") or "").strip()[:20],
        "duration_range": duration_range(profile),
        "requested": {key: requested[key] for key in (
            "output_profile", "target_duration_seconds", "video_type", "primary_angle_id") if requested.get(key)},
    }


def available_assets(
    database: Any, project: dict[str, Any], video: dict[str, Any], analysis: dict[str, Any], *, source_kind: str,
) -> dict[str, Any]:
    """What there is to build the video from, counted from the database."""
    result = dict(analysis.get("result") or {})
    video_id = str(video.get("youtube_video_id") or "")
    assets = database.list_project_assets(int(project["id"]))
    by_type: dict[str, int] = {}
    for asset in assets:
        if Path(str(asset.get("file_path") or "")).is_file():
            by_type[str(asset.get("asset_type"))] = by_type.get(str(asset.get("asset_type")), 0) + 1
    facts = result.get("source_facts") or {}
    footage = int(video.get("duration_seconds") or 0) if source_kind == "video" else 0
    sound = int(video.get("duration_seconds") or 0) if source_kind in {"video", "audio"} else 0
    source_images = 0
    if source_kind == "product":
        source_images = len(facts.get("images") or [])
    elif source_kind in {"article", "web"}:
        source_images = int(result.get("image_count") or 0)
    elif source_kind == "image_collection":
        source_images = by_type.get("image", 0)
    transcript = bool(database.get_transcript(video_id)) if video_id else False
    return {
        "source_kind": source_kind,
        "source_footage_seconds": footage,
        "source_audio_seconds": sound,
        "source_has_picture": source_kind == "video",
        "source_media_local": Path(str(video.get("local_media_path") or "")).is_file() if video.get("local_media_path") else False,
        "source_images": source_images,
        "has_transcript": transcript,
        "has_dialogue": bool(result.get("has_dialogue")),
        "project_assets": by_type,
        "price_known": bool(str(facts.get("price") or facts.get("price_text") or "").strip()) if source_kind == "product" else None,
        "price_captured_at": facts.get("captured_at") if source_kind == "product" else None,
    }


# ---------------------------------------------------------------------------
# What the model reads
# ---------------------------------------------------------------------------

def build_prompt(
    *, kind: str, video: dict[str, Any], analysis: dict[str, Any], insight: dict[str, Any],
    settings: dict[str, Any], assets: dict[str, Any], must_not_invent: list[str],
) -> str:
    result = dict(analysis.get("result") or {})
    limits = settings["duration_range"]
    lines = [
        f"LOAI NGUON: {kind}",
        f"Tieu de nguon: {_clean(video.get('title') or result.get('topic'), 200)}",
        f"Chu de: {_clean(result.get('topic'), 300)}",
        f"Tom tat nguon: {_clean(result.get('content_summary'), 1200)}",
        "",
        "CAI DAT CUA DU AN (khong doi):",
        f"- Nen tang: {settings['platform']} · output_profile: {settings['output_profile']} · ti le: {settings['aspect_ratio']}",
        f"- Ngon ngu: {settings['language']}",
        f"- Workflow: {settings['workflow']} (cach viet: {settings['script_mode']}; hinh cua canh: {settings['scene_asset_type']})",
    ]
    if settings["target_duration_seconds"]:
        lines.append(f"- Thoi luong muc tieu DA DAT: {settings['target_duration_seconds']} giay. Dung dung con so nay.")
    else:
        lines.append(
            f"- Chua dat thoi luong. Hay de xuat target_duration_seconds trong khoang {limits['min']}-{limits['recommended_max']} giay "
            "cho dinh dang nay."
        )
    if settings["video_type"]:
        lines.append(f"- Loai video DA CHON: {settings['video_type']}")
    lines += [
        "",
        "TU LIEU DANG CO:",
        f"- Canh quay tu nguon: {assets['source_footage_seconds']} giay" + ("" if assets["source_has_picture"] else " (nguon khong co hinh de cat)"),
        f"- Anh tu nguon: {assets['source_images']}",
        f"- Transcript: {'co' if assets['has_transcript'] else 'chua co'} · loi noi trong nguon: {'co' if assets['has_dialogue'] else 'khong'}",
        f"- Tu lieu da tai vao du an: {assets['project_assets'] or 'khong co'}",
        "- App tu tao o cac buoc sau (khong phai tu lieu thieu): kich ban, giong doc, hinh AI, so do/do hoa, phu de, nhac nen.",
    ]
    if kind == "product":
        lines.append(
            f"- Gia: da doc luc {assets['price_captured_at']}" if assets["price_known"]
            else "- Gia: CHUA DOC DUOC. Ke hoach khong duoc dua vao con so gia nao."
        )
    lines += ["", "INSIGHT DA KIEM CHUNG (co bang chung):"]
    for item in insight.get("insights") or []:
        status = f" · trang thai: {item['fact_status']}" if item.get("fact_status") else ""
        proof = " · CAN BANG CHUNG THEM" if item.get("proof") == "needs_proof" else ""
        lines.append(
            f"- [{item['id']}] ({item['type']} · tin cay {item['confidence']}{status}{proof}) {item['statement']}"
            f" — bang chung: {', '.join(item['evidence_ids'][:6])}"
        )
        for implication in item.get("implications") or []:
            lines.append(f"    → {implication}")
    if insight.get("hypotheses"):
        lines += ["", "GIA THUYET (khong co bang chung - KHONG dung nhu su that):"]
        lines += [f"- ({item['type']}) {item['statement']}" for item in insight["hypotheses"]]
    if settings.get("primary_angle_id"):
        lines += ["", f"GOC DA DUOC NGUOI DUNG CHON: [{settings['primary_angle_id']}]. primary_angle_id phai la ma nay; "
                      "lap ke hoach cho dung goc nay, cac goc con lai la alternative_angle_ids."]
    lines += ["", "GOC NOI DUNG UNG VIEN (chi duoc chon trong danh sach nay):"]
    for angle in insight.get("angle_candidates") or []:
        lines.append(
            f"- [{angle['id']}] {angle['statement']} · cho: {angle['target_audience']} · nhu cau: {angle['need_or_problem']}"
            f" · dua tren: {', '.join(angle['supporting_insight_ids'])} · khac biet: {angle['differentiation']}"
            f" · hop nen tang: {angle['platform_fit']}"
        )
    if must_not_invent:
        lines += ["", "DIEU BUOC PHAN TICH KHONG XAC DINH DUOC (khong duoc tu dien vao): " + " | ".join(must_not_invent[:8])]
    return "\n".join(lines)


def repair_prompt(prompt: str, errors: list[str]) -> str:
    return (
        "Ke hoach truoc KHONG dung. Loi:\n- " + "\n- ".join(errors[:12])
        + "\n\nHay lap lai ke hoach tu dau, dung schema va dung cac ma da cho.\n\n" + prompt
    )


# ---------------------------------------------------------------------------
# After the model
# ---------------------------------------------------------------------------

def shape_errors(parsed: Any, insight: dict[str, Any], chosen: str = "") -> list[str]:
    """What makes the answer unusable as a plan (worth the one repair call).

    `chosen` is the angle a person picked: a plan written for another one is not the plan asked for.
    """
    if not isinstance(parsed, dict):
        return ["Kết quả không phải một đối tượng JSON"]
    errors: list[str] = []
    angles = {item["id"] for item in insight.get("angle_candidates") or []}
    if str(parsed.get("primary_angle_id") or "") not in angles:
        errors.append(f"primary_angle_id phải là một trong: {', '.join(sorted(angles))}")
    elif chosen and str(parsed.get("primary_angle_id")) != chosen:
        errors.append(f"primary_angle_id phải là {chosen}: người dùng đã chọn góc này")
    sections = parsed.get("content_structure")
    if not isinstance(sections, list) or not sections:
        errors.append("content_structure trống")
    else:
        for index, section in enumerate(sections):
            try:
                seconds = int((section or {}).get("estimated_seconds") or 0)
            except (TypeError, ValueError, AttributeError):
                seconds = 0
            if seconds <= 0:
                errors.append(f"content_structure[{index}] thiếu estimated_seconds")
    try:
        if int(parsed.get("target_duration_seconds") or 0) <= 0:
            errors.append("Thiếu target_duration_seconds")
    except (TypeError, ValueError):
        errors.append("target_duration_seconds không phải số")
    if not isinstance(parsed.get("media_strategy"), dict) or not isinstance(parsed.get("edit_direction"), dict):
        errors.append("Thiếu media_strategy hoặc edit_direction")
    return errors


def guardrails(insight: dict[str, Any], assets: dict[str, Any], *, kind: str) -> dict[str, list[str]]:
    """What the evidence obliges the video to respect - written by rule, whatever the model said.

    What the analysis could not settle is not repeated here: it stays in the
    plan's constraints (must_not_invent), where the writer reads it.
    """
    factual: list[str] = []
    avoid: list[str] = []
    proof: list[str] = []
    for item in insight.get("insights") or []:
        status = item.get("fact_status")
        if status == "disputed":
            factual.append(f"Các nguồn nói khác nhau, không khẳng định một chiều: {item['statement']}")
        elif status == "reported":
            factual.append(f"Mới có một nguồn đưa, phải nêu rõ nguồn khi nói: {item['statement']}")
        elif status == "unknown":
            factual.append(f"Chưa được xác nhận, không suy đoán: {item['statement']}")
        if item.get("proof") == "needs_proof":
            proof.append(item["statement"])
        if item.get("price_captured_at"):
            factual.append(f"Giá chỉ đúng tại thời điểm đọc ({item['price_captured_at'][:16]}): nêu kèm thời điểm hoặc không nêu con số.")
    for item in insight.get("hypotheses") or []:
        avoid.append(f"Chưa có bằng chứng, không nói như sự thật: {item['statement']}")
    if kind == "product":
        for item in insight.get("rejected") or []:
            if item.get("type") in {"selling_point", "product_risk"} and item.get("statement"):
                avoid.append(f"Không có bằng chứng cho khẳng định về sản phẩm: {item['statement']}")
        if assets.get("price_known") is False:
            avoid.append("Không nêu bất kỳ con số giá nào: chưa đọc được giá từ trang bán.")
        elif assets.get("price_captured_at"):
            state = freshness.product_price(assets["price_captured_at"])["state"]
            factual.append(
                f"Giá đọc lúc {str(assets['price_captured_at'])[:16]}"
                + (" đã quá 24 giờ: đọc lại trước khi nêu." if state != freshness.FRESH else ": nêu kèm thời điểm đọc.")
            )
    return {"factual_guardrails": _texts(factual, 20, 400), "claims_to_avoid": _texts(avoid, 20, 400),
            "claims_needing_proof": _texts(proof, 12, 400)}


def finalise(
    parsed: dict[str, Any], *, kind: str, insight: dict[str, Any], settings: dict[str, Any], assets: dict[str, Any],
    must_not_invent: list[str], refs: dict[str, Any],
) -> dict[str, Any]:
    """The plan as stored: the model's strategy, with what the code owns put in place."""
    angles = {item["id"]: item for item in insight.get("angle_candidates") or []}
    insight_ids = {item["id"] for item in insight.get("insights") or []}
    evidence_ids = set(insight.get("evidence_index") or {}) | {
        eid for item in insight.get("insights") or [] for eid in item["evidence_ids"]}
    removed: list[str] = []
    sections = []
    for raw in parsed.get("content_structure") or []:
        cited_insights = [str(item) for item in raw.get("insight_ids") or []]
        cited_evidence = [str(item) for item in raw.get("evidence_ids") or []]
        removed += [item for item in cited_insights if item not in insight_ids]
        removed += [item for item in cited_evidence if item not in evidence_ids]
        sections.append({
            "name": _clean(raw.get("name"), 120), "purpose": _clean(raw.get("purpose"), 300),
            "estimated_seconds": max(1, int(raw.get("estimated_seconds") or 0)),
            "key_points": _texts(raw.get("key_points"), 8),
            "insight_ids": [item for item in dict.fromkeys(cited_insights) if item in insight_ids],
            "evidence_ids": [item for item in dict.fromkeys(cited_evidence) if item in evidence_ids],
        })
    chosen = settings.get("primary_angle_id") or ""
    primary = angles[chosen if chosen in angles else str(parsed["primary_angle_id"])]
    alternatives = [angles[item] for item in dict.fromkeys(str(value) for value in parsed.get("alternative_angle_ids") or [])
                    if item in angles and item != primary["id"]]
    alternatives += [angle for key, angle in angles.items() if key != primary["id"] and angle not in alternatives]
    rules = guardrails(insight, assets, kind=kind)
    media = parsed.get("media_strategy") or {}
    media_used = {
        "primary_sources": [item for item in dict.fromkeys(media.get("primary_sources") or []) if item in MEDIA_SOURCES],
        "supporting_sources": [item for item in dict.fromkeys(media.get("supporting_sources") or []) if item in MEDIA_SOURCES],
    }
    proposed = review_assets(parsed.get("proposed_assets") or [], assets)
    edit = parsed.get("edit_direction") or {}
    target = settings["target_duration_seconds"] or int(parsed.get("target_duration_seconds") or 0)
    limitations = _texts([*(parsed.get("limitations") or []), *(insight.get("limitations") or [])], 16, 400)
    if removed:
        limitations.append(f"Đã bỏ {len(set(removed))} mã insight/bằng chứng không tồn tại khỏi cấu trúc nội dung.")
    wished = [item for item in proposed if item["verdict"] == UNVERIFIED and item["required_by_ai"]]
    if wished:
        limitations.append(
            f"AI cho rằng cần thêm {len(wished)} tư liệu mà dự án không tự đối chiếu được (ví dụ tài liệu kiểm chứng): "
            "xem ai_proposed_assets; chúng không được tính là tư liệu thiếu."
        )
    if assets.get("price_known") is False:
        # A listing whose price could not be read is still planned for; the plan says what it lacks.
        limitations.append("Chưa đọc được giá sản phẩm: kế hoạch không dựa vào con số giá nào.")
    return {
        "source_kind": kind,
        "video_type": settings["video_type"] or _clean(parsed.get("video_type"), 60),
        "platform": settings["platform"],
        "aspect_ratio": settings["aspect_ratio"],
        "output_profile": settings["output_profile"],
        "language": settings["language"],
        "target_duration_seconds": target,
        "target_duration_from": "project" if settings["target_duration_seconds"] else "ai_proposed",
        "target_audience": _clean(parsed.get("target_audience"), 400),
        "goal": _clean(parsed.get("goal"), 400),
        "primary_angle": primary,
        "primary_angle_id": primary["id"],
        "primary_angle_from": "user" if chosen in angles else "ai",
        "alternative_angles": alternatives,
        "hook_strategy": _clean(parsed.get("hook_strategy"), 600),
        "content_structure": sections,
        "media_strategy": {**media_used, "notes": _clean(media.get("notes"), 600)},
        "edit_direction": {
            **{key: _clean(edit.get(key), 300) for key in (
                "pacing", "cut_style", "transitions", "text_animation", "subtitle_style", "callouts", "zoom_punch_in",
                "broll_usage", "graphics",
            )},
            "average_shot_length_seconds": _number(edit.get("average_shot_length_seconds")),
        },
        "subtitle_strategy": _clean(parsed.get("subtitle_strategy"), 400),
        "music_strategy": _clean(parsed.get("music_strategy"), 400),
        "sfx_strategy": _clean(parsed.get("sfx_strategy"), 400),
        "cta": _clean(parsed.get("cta"), 300),
        # The rule's guardrails first: they cannot be argued away by the answer.
        "factual_guardrails": _texts([*rules["factual_guardrails"], *(parsed.get("factual_guardrails") or [])], 24, 400),
        "claims_to_avoid": _texts([*rules["claims_to_avoid"], *(parsed.get("claims_to_avoid") or [])], 24, 400),
        "claims_needing_proof": rules["claims_needing_proof"],
        # How many of each list, from the top, were written by rule rather than by the model.
        "guardrails_from_rules": {"factual_guardrails": len(rules["factual_guardrails"]),
                                  "claims_to_avoid": len(rules["claims_to_avoid"])},
        # What the model asked for, each with what the project's own state says about it...
        "ai_proposed_assets": proposed,
        # ...and what is in fact missing: decided here, from that state.
        "missing_assets": missing_assets(media_used, proposed, assets, settings=settings, kind=kind),
        "limitations": limitations,
        "constraints": {
            "script_mode": settings["script_mode"], "scene_asset_type": settings["scene_asset_type"],
            "workflow": settings["workflow"], "must_not_invent": must_not_invent,
            **({"no_price_claims": True} if assets.get("price_known") is False else {}),
        },
        "requested": settings["requested"],
        "pending_fields": [],
        **refs,
    }


def asset_state(assets: dict[str, Any]) -> dict[str, tuple[bool, str]]:
    """What the project holds, by asset category: (is it there, what was counted)."""
    uploads = assets.get("project_assets") or {}
    images, pictures, clips = int(assets.get("source_images") or 0), int(uploads.get("image", 0)), int(uploads.get("video", 0))
    footage, sound = int(assets.get("source_footage_seconds") or 0), int(assets.get("source_audio_seconds") or 0)
    words = bool(assets.get("has_transcript") or assets.get("has_dialogue"))
    return {
        "source_footage": (footage > 0, f"nguồn có {footage} giây hình"),
        "source_images": (images > 0, f"nguồn có {images} ảnh"),
        "product_images": (images + pictures > 0, f"có {images} ảnh từ trang bán và {pictures} ảnh đã tải vào dự án"),
        "transcript": (words, "nguồn có lời nói / transcript" if words else "nguồn chưa có lời nói hay transcript"),
        "source_audio": (sound > 0, f"nguồn có {sound} giây âm thanh"),
        "user_footage": (clips > 0, f"dự án có {clips} video đã tải vào"),
        "user_images": (pictures > 0, f"dự án có {pictures} ảnh đã tải vào"),
    }


def review_assets(proposed: list[Any], assets: dict[str, Any]) -> list[dict[str, Any]]:
    """Each asset the model proposed, with what the project's state says about it.

    exists         the project already has it - the model was wrong to ask, and it is not missing
    app_generates  a later step makes it (script, voice, AI pictures, subtitles, music)
    missing        checked against the project, and it is not there
    unverified     nothing in the project can confirm it either way (a reference document); a suggestion only
    """
    state = asset_state(assets)
    reviewed: list[dict[str, Any]] = []
    for raw in proposed:
        if not isinstance(raw, dict) or not _clean(raw.get("asset")):
            continue
        name = _clean(raw.get("asset"), 200)
        category = str(raw.get("category") or "other")
        if category not in ASSET_CATEGORIES:
            category = "other"
        if category == "other":
            category = ("generated" if _GENERATED.search(name) else "user_footage" if _FOOTAGE.search(name)
                        else "user_images" if _PICTURES.search(name) else "other")
        if category == "generated":
            verdict, note = APP_GENERATES, "App tự tạo ở bước sau; không phải tư liệu thiếu."
        elif category in state:
            present, counted = state[category]
            verdict = EXISTS if present else MISSING
            note = (f"Dự án đã có: {counted}." if present else f"Đã đối chiếu dự án: {counted}.")
        else:
            verdict, note = UNVERIFIED, "Không đối chiếu được với tư liệu của dự án; chỉ là đề xuất của AI."
        reviewed.append({
            "asset": name, "why": _clean(raw.get("why"), 300), "category": category,
            "required_by_ai": bool(raw.get("required")), "verdict": verdict, "note": note,
        })
    return reviewed[:12]


def missing_assets(
    media: dict[str, Any], proposed: list[dict[str, Any]], assets: dict[str, Any], *, settings: dict[str, Any], kind: str,
) -> list[dict[str, Any]]:
    """What the plan needs and the project does not have - from the project's state, never from the answer alone.

    By rule: a kind of media the plan builds on that is not there, and the
    source's words when the workflow retells them. From the model: only a
    proposal the state confirms is absent; `required` is taken from it then,
    and from nowhere else.
    """
    state = asset_state(assets)
    primary = list(media.get("primary_sources") or [])
    used = [*primary, *(media.get("supporting_sources") or [])]
    found: dict[str, dict[str, Any]] = {}

    def add(category: str, asset: str, why: str, required: bool, source: str) -> None:
        entry = found.setdefault(category, {"asset": asset, "category": category, "why": why, "required": False, "source": source})
        entry["required"] = entry["required"] or required
        if source == "rule" and entry["source"] != "rule":
            entry.update(asset=asset, why=why, source="rule")

    for name in ("source_footage", "source_images", "product_images"):
        if name in used and not state[name][0]:
            add(name, ASSET_LABELS[name], f"Kế hoạch dùng {ASSET_LABELS[name].lower()} nhưng {state[name][1]}.", name in primary, "rule")
    if kind in {"video", "audio"} and settings.get("script_mode") == "faithful_retell" and not state["transcript"][0]:
        add("transcript", ASSET_LABELS["transcript"], "Workflow kể lại đúng nguồn cần lời của nguồn.", True, "rule")
    for item in proposed:
        if item["verdict"] == MISSING:
            add(item["category"], item["asset"], item["why"] or item["note"], item["required_by_ai"], "ai_confirmed")
    return list(found.values())


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 1) if number > 0 else None


# ---------------------------------------------------------------------------
# Feasibility: by rule, after the model
# ---------------------------------------------------------------------------

def feasibility(plan: dict[str, Any], *, settings: dict[str, Any], assets: dict[str, Any]) -> dict[str, Any]:
    """Whether the plan can be made with what there is. Mutates only the time budget, within tolerance.

    ok               nothing to decide
    adjusted         a small drift in the time budget was rescaled; recorded in `adjustments`
    needs_attention  something a person has to choose; `options` says between what
    blocked          there is nothing to make the video from
    """
    checks: list[dict[str, Any]] = []
    adjustments: list[dict[str, Any]] = []

    def check(key: str, status: str, detail: str, options: list[str] | None = None) -> None:
        checks.append({"key": key, "status": status, "detail": detail, **({"options": options} if options else {})})

    target = int(plan.get("target_duration_seconds") or 0)
    sections = plan.get("content_structure") or []
    total = sum(int(item.get("estimated_seconds") or 0) for item in sections)
    kind = str(plan.get("source_kind") or "")

    # 1. The time budget against the target.
    if target <= 0 or not sections:
        check("duration_budget", BLOCKED, "Kế hoạch chưa có thời lượng mục tiêu hoặc chưa có cấu trúc nội dung.")
    else:
        drift = abs(total - target) / target
        if drift <= BUDGET_TOLERANCE or abs(total - target) <= 3:
            check("duration_budget", OK, f"Các phần cộng lại {total} giây, mục tiêu {target} giây.")
        elif drift <= BUDGET_RESCALE:
            before = [int(item["estimated_seconds"]) for item in sections]
            scaled = [max(1, round(seconds * target / total)) for seconds in before]
            scaled[-1] = max(1, scaled[-1] + (target - sum(scaled)))
            for item, seconds in zip(sections, scaled):
                item["estimated_seconds"] = seconds
            adjustments.append({"field": "content_structure.estimated_seconds", "from_total": total, "to_total": sum(scaled),
                                "why": f"Các phần lệch {round(100 * drift)}% so với mục tiêu {target} giây; đã chia lại theo tỉ lệ."})
            check("duration_budget", ADJUSTED, f"Các phần cộng lại {total} giây; đã chia lại cho khớp mục tiêu {target} giây.")
            total = sum(scaled)
        else:
            check(
                "duration_budget", NEEDS_ATTENTION,
                f"Các phần cộng lại {total} giây trong khi mục tiêu là {target} giây (lệch {round(100 * drift)}%).",
                [f"Rút gọn cấu trúc còn khoảng {target} giây", f"Đổi thời lượng mục tiêu thành khoảng {total} giây"],
            )

    # 2. The target against what this output profile is for.
    limits = settings["duration_range"]
    if target and target < limits["min"]:
        check("platform_fit", NEEDS_ATTENTION, f"{target} giây ngắn hơn mức tối thiểu {limits['min']} giây của định dạng này.",
              [f"Tăng lên ít nhất {limits['min']} giây"])
    elif target and target > limits["attention_above"]:
        check("platform_fit", NEEDS_ATTENTION,
              f"{target} giây dài hơn mức định dạng {settings['output_profile']} ({settings['aspect_ratio']}) dùng cho ({limits['attention_above']} giây).",
              [f"Rút còn tối đa {limits['recommended_max']} giây", "Đổi sang định dạng ngang cho video dài"])
    elif target and target > limits["recommended_max"]:
        check("platform_fit", OK, f"{target} giây dài hơn mức thường dùng ({limits['recommended_max']} giây) của định dạng này nhưng vẫn làm được.")
    else:
        check("platform_fit", OK, f"{settings['platform']} · {settings['aspect_ratio']} · {target} giây.")

    # 3. The media the plan leans on against what there is.
    media = plan.get("media_strategy") or {}
    primary = list(media.get("primary_sources") or [])
    used = [*primary, *(media.get("supporting_sources") or [])]
    stills = assets["source_images"] + int((assets.get("project_assets") or {}).get("image", 0)) if kind != "image_collection" else assets["source_images"]
    if "source_footage" in used and not assets["source_footage_seconds"]:
        only = primary == ["source_footage"] and len(set(used)) == 1
        check("source_footage", BLOCKED if only else NEEDS_ATTENTION,
              "Kế hoạch dùng cảnh quay từ nguồn nhưng nguồn không có hình để cắt.",
              ["Chọn loại tư liệu khác làm chính (ảnh, B-roll, hình AI, đồ hoạ)"])
    elif "source_footage" in used:
        check("source_footage", OK, f"Nguồn có {assets['source_footage_seconds']} giây hình.")
    for name, label in (("product_images", "ảnh sản phẩm"), ("source_images", "ảnh từ nguồn")):
        if name in primary and stills == 0:
            check("image_quantity", NEEDS_ATTENTION, f"Kế hoạch lấy {label} làm tư liệu chính nhưng dự án chưa có ảnh nào.",
                  ["Tải ảnh vào dự án", "Chọn loại tư liệu khác làm chính"])
            break
    else:
        if {"product_images", "source_images"} & set(used):
            check("image_quantity", OK, f"Có {stills} ảnh dùng được.")
    finite_only = bool(used) and set(used) <= FINITE_MEDIA
    coverage = (assets["source_footage_seconds"] if "source_footage" in used else 0) + (
        stills * STILL_SECONDS if {"product_images", "source_images"} & set(used) else 0)
    if not used:
        check("available_media", NEEDS_ATTENTION, "Kế hoạch chưa nói video được dựng từ loại tư liệu nào.",
              ["Chọn tư liệu chính cho kế hoạch"])
    elif target and finite_only and coverage < MEDIA_COVERAGE * target:
        check(
            "available_media", NEEDS_ATTENTION,
            f"Mục tiêu {target} giây nhưng tư liệu hiện có chỉ đủ khoảng {coverage} giây.",
            [f"Rút thời lượng còn khoảng {max(coverage, limits['min'])} giây", "Thêm B-roll, hình AI hoặc đồ hoạ để đủ thời lượng",
             "Tải thêm tư liệu vào dự án"],
        )
    elif target and settings["scene_asset_type"] == "source_clip" and assets["source_footage_seconds"] and target > assets["source_footage_seconds"]:
        check(
            "available_media", NEEDS_ATTENTION,
            f"Workflow cắt cảnh từ nguồn: mục tiêu {target} giây dài hơn nguồn ({assets['source_footage_seconds']} giây).",
            [f"Rút thời lượng còn tối đa {assets['source_footage_seconds']} giây", "Đổi sang workflow tạo hình mới"],
        )
    else:
        check("available_media", OK, "Tư liệu chính làm được theo độ dài kế hoạch."
              if not finite_only else f"Tư liệu hiện có đủ khoảng {coverage} giây cho mục tiêu {target} giây.")

    # 4. Words: a plan that retells the source needs the source's words.
    if kind in {"video", "audio"} and settings["script_mode"] == "faithful_retell" and not (assets["has_transcript"] or assets["has_dialogue"]):
        check("transcript", NEEDS_ATTENTION, "Workflow kể lại đúng nguồn nhưng nguồn chưa có lời thoại/transcript.",
              ["Tạo transcript cho nguồn", "Đổi sang workflow viết mới"])
    elif kind in {"video", "audio"}:
        check("transcript", OK, "Có lời nói của nguồn." if assets["has_transcript"] or assets["has_dialogue"] else "Nguồn không có lời nói; kế hoạch viết lời mới.")

    # 5. Claims: where the source is facts, each section must say what it rests on.
    unsupported = [item["name"] for item in sections if item.get("key_points") and not (item.get("insight_ids") or item.get("evidence_ids"))]
    if unsupported and kind in {"article", "web", "product"}:
        check("claim_evidence", NEEDS_ATTENTION,
              f"{len(unsupported)} phần không dẫn insight hay bằng chứng nào: {', '.join(unsupported[:4])}.",
              ["Gắn bằng chứng cho các phần này", "Bỏ các ý không có bằng chứng"])
    else:
        check("claim_evidence", OK, f"{len(sections) - len(unsupported)}/{len(sections)} phần dẫn insight hoặc bằng chứng.")

    # 6. What the plan needs and the project does not have (missing_assets: checked against the project).
    missing = list(plan.get("missing_assets") or [])
    required = [item for item in missing if item.get("required")]
    if required:
        check("missing_assets", NEEDS_ATTENTION,
              "Thiếu tư liệu bắt buộc: " + "; ".join(item["asset"].rstrip(". ") for item in required[:5]) + ".",
              ["Bổ sung tư liệu còn thiếu", "Đổi chiến lược tư liệu"])
    elif missing:
        check("missing_assets", OK, f"Thiếu {len(missing)} tư liệu không bắt buộc; kế hoạch vẫn làm được.")
    else:
        check("missing_assets", OK, "Không thiếu tư liệu bắt buộc.")

    status = max((item["status"] for item in checks), key=lambda value: _RANK[value], default=OK)
    return {
        "status": status,
        "checks": checks,
        "adjustments": adjustments,
        "estimated": {"structure_seconds": total, "target_seconds": target,
                      "finite_media_seconds": coverage if finite_only else None},
        "reason": next((item["detail"] for item in checks if item["status"] == status), "") if status != OK else "",
    }
