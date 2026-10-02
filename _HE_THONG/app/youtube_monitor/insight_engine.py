"""Bước 2 · Kế hoạch - Phase 3, first half: what the evidence means for this video.

    ResearchReport (what was collected)  →  InsightReport (what it means)

One model call reads the analysis, the evidence and what the stores already
hold, and answers with insights and two to four angles. Then the validator
here takes over, because a model's sentence is not a measurement:

* an insight citing evidence that does not exist is refused;
* its sample size, source count and confidence are worked out from the
  evidence it does cite (research_evidence.measure) - the model is not asked
  for them and anything it writes is ignored;
* an insight with no evidence survives only as a marked hypothesis, which no
  later step may treat as a fact;
* a sentence saying *why* a video did well is refused. Something seen more
  often among the sampled high performers is a pattern, not a cause;
* what was collected but is not about the source (a video the search returned
  that is on another subject, the comments under it) and a page that answered
  with a block instead of its content are never offered to the model, and an
  insight citing one is refused.

What the model is asked depends on what the source is (videos.source_kind):
a listing is reasoned about as something for sale, a news article as claims
with a status, an audio file as words with no picture. No prose from the
model is written into the ResearchReport; this report stands beside it.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from . import research_collectors, research_evidence, source_kinds
from .knowledge_store import AudienceObservations, ChannelIntelligence, ContentPatterns, TopicIntelligence

ENGINE_VERSION = "insight-phase3"

INSIGHT_TYPES = (
    "audience_need", "audience_question", "pain_point", "objection", "positive_signal",
    "channel_pattern", "competitor_pattern", "performance_pattern",
    "content_gap", "opportunity",
    "selling_point", "product_risk",
    "fact", "disputed_fact", "uncertainty",
)
PATTERN_TYPES = frozenset({"channel_pattern", "competitor_pattern", "performance_pattern"})
FACT_TYPES = frozenset({"fact", "disputed_fact", "uncertainty"})
FACT_STATUSES = ("confirmed", "reported", "disputed", "unknown")
# Evidence that stands for many videos at once, so one of it can carry a pattern.
MULTI_VIDEO_KINDS = frozenset({"channel_stats"})
# A source that is not a video is held to the stricter relevance rule (research_collectors.mark_relevance).
STRICT_RELEVANCE_KINDS = frozenset({"article", "product", "audio", "web", "image_collection"})
LOW_RELEVANCE = "Bằng chứng ít liên quan tới nguồn (video hoặc comment lạc đề): không được dùng làm cơ sở."
BLOCKED_SOURCE = "Nguồn bị chặn, chưa đọc được nội dung: không được dùng làm cơ sở."
MAX_INSIGHTS = 24
MAX_ANGLES = 4
MIN_ANGLES = 2
PACK_CHARS = 22_000

# "Video này viral vì…": a cause read off a correlation. The pattern may be
# stated; the reason may not.
_CAUSAL = re.compile(
    r"viral\s+(vì|do|nhờ|bởi)|(vì|do|nhờ|bởi)\s+[^.]{0,80}\s+(nên|mà)\s+[^.]{0,60}(viral|triệu\s+(view|lượt)|bùng\s+nổ|lên\s+xu\s+hướng)"
    r"|(lý\s+do|nguyên\s+nhân)\s+[^.]{0,60}(viral|nhiều\s+(view|lượt\s+xem)|thành\s+công|hiệu\s+suất\s+cao)"
    r"|(giúp|khiến|làm\s+cho)\s+(video|clip|kênh)[^.]{0,60}(viral|bùng\s+nổ|đạt\s+[^.]{0,20}(view|lượt\s+xem)|hiệu\s+suất\s+cao)"
    r"|(viral|nhiều\s+view|thành\s+công)\s+(là\s+)?(vì|do|nhờ|bởi)\b"
    r"|went\s+viral\s+because|because\s+of\s+(its|the)\b[^.]{0,40}(viral|views)",
    re.IGNORECASE,
)
_PRICE = re.compile(r"₫|\bvnđ\b|\bvnd\b|\d[\d.,]*\s*(đ|k)\b|\bgiá\s+(chỉ\s+)?\d", re.IGNORECASE)

SYSTEM_PROMPT = """Ban la nguoi phan tich chien luoc noi dung. Ban nhan ket qua phan tich mot NGUON va cac BANG CHUNG da thu thap
quanh no, moi bang chung co mot ma [ev-...]. Viec cua ban: noi nhung du lieu do CO Y NGHIA GI cho video sap lam.

Luat bat buoc:
1. Moi insight phai tro toi bang chung bang dung ma [ev-...] co trong du lieu. Khong tu tao ma. Khong co bang chung
   ma van thay dang noi thi dat hypothesis=true va evidence_ids rong - do la gia thuyet, khong phai su that.
2. KHONG viet con so ve do lon mau, so nguon hay do tin cay - app tu tinh tu bang chung. Khong viet ti le phan tram
   cho "nguoi xem" noi chung; chi duoc noi ve mau da doc ("trong 40 comment mau...").
3. KHONG suy ra nguyen nhan. Khong viet "video nay viral vi...", "nho X nen dat trieu view". Chi duoc mo ta dieu
   quan sat duoc: "Trong nhom video hieu suat cao da lay mau, X xuat hien thuong xuyen hon." Loai do la
   performance_pattern, khong phai su that nhan qua.
4. Mot video don le khong phai la pattern. Pattern phai dua tren tu hai video tro len, hoac ho so kenh.
5. Trich doan tim kiem chua mo trang (search_result) chi la goi y, khong du de khang dinh mot su that.
6. implications: moi insight keo theo dieu gi cho video sap lam - cu the, ngan, khong lap lai statement.
7. angle_candidates: 2 den 4 goc noi dung khac nhau that su. Moi goc phai dua tren it nhat mot insight CO BANG CHUNG
   (supporting_insight_keys tro toi key cua insight ben tren). Goc khong co insight do thi khong dua vao.
8. limitations chi noi ve du lieu con thieu hoac chua doc duoc, khong noi ve ban than AI hay cong cu.
   Du lieu thu thap bi lac de, thieu hoac khong doc duoc thi ghi vao limitations - KHONG tao insight tu no. Loai uncertainty chi danh
   cho mot dieu ve chinh chu de / san pham / su kien ma chua duoc xac nhan.
   Khong neu ten nguoi binh luan hay nguoi danh gia, ke ca ten da che (vi du "T**n"): chi viet "mot nguoi mua", "mot binh luan".
9. Viet moi cau bang ngon ngu cua du an (tieng Viet thi viet co dau day du). Chi tra ve JSON dung schema."""

# What to read and what to look for, by what the source is. One brief for
# everything would ask a news article for selling points.
KIND_BRIEFS: dict[str, dict[str, str]] = {
    "video": {
        "label": "NGUON LA MOT VIDEO",
        "use": "phan tich nguon, ho so kenh nguon, cac video tuong tu, comment mau, mo dau transcript, hieu suat, "
               "dang tieu de, bang chung ve chu de tren web",
        "find": "nhu cau cua nguoi xem, cau hoi lap lai, pattern noi dung va cau truc, pattern hieu suat (khong nhan qua), "
                "khoang trong va cau hoi chua duoc tra loi, cac goc co the lam, rui ro",
        "types": "audience_need, audience_question, pain_point, positive_signal, channel_pattern, competitor_pattern, "
                 "performance_pattern, content_gap, opportunity, uncertainty",
    },
    "audio": {
        "label": "NGUON LA MOT FILE AM THANH (chi co loi noi, KHONG co hinh)",
        "use": "loi da phien am, chu de, cac khang dinh trong loi noi, nghien cuu lien quan neu co",
        "find": "nhu cau va cau hoi cua nguoi nghe quanh chu de, cac khang dinh can kiem chung, khoang trong, goc co the lam. "
                "Khong gia dinh bat cu dieu gi ve hinh anh cua nguon - nguon khong co hinh",
        "types": "audience_need, audience_question, competitor_pattern, performance_pattern, content_gap, opportunity, "
                 "fact, uncertainty",
    },
    "product": {
        "label": "NGUON LA MOT SAN PHAM DANG BAN",
        "use": "du kien san pham hien tai (ten, gia kem thoi diem doc, gia goc/giam gia, shop, thong so, sao, da ban), "
               "danh gia va comment, cau hoi thuong gap, san pham canh tranh, video review/ban hang, gia doi thu",
        "find": "nhu cau khach hang, e ngai va phan doi, noi dau, cau hoi thuong gap, diem manh, diem yeu, cach doi thu dinh vi, "
                "goc ban hang, khoang trong noi dung, khang dinh can bang chung, khang dinh nen tranh. "
                "Gia chi dung tai thoi diem da doc: khong viet gia nhu mot su that vinh vien. Khong co gia thi van phan tich, "
                "va ghi ro la chua co gia",
        "types": "audience_need, audience_question, pain_point, objection, positive_signal, selling_point, product_risk, "
                 "competitor_pattern, content_gap, opportunity, uncertainty",
    },
    "article": {
        "label": "NGUON LA MOT BAI VIET / TIN TUC",
        "use": "bai nguon, cac nguon moi hon, nguon goc/chinh thuc, trinh tu thoi gian, cho mau thuan, cho chua ro, boi canh tren web",
        "find": "tung khang dinh chinh va trang thai cua no: confirmed (nhieu nguon doc lap hoac nguon chinh thuc), "
                "reported (moi mot nguon dua), disputed (cac nguon noi khac nhau), unknown (chua ai xac nhan). "
                "Ngoai ra: dieu nguoi doc muon biet, khoang trong, goc co the lam",
        "types": "fact, disputed_fact, uncertainty, audience_need, audience_question, content_gap, opportunity",
    },
    "web": {
        "label": "NGUON LA MOT TRANG WEB (khong chac la bai viet)",
        "use": "noi dung trang, cac nguon lien quan tren web, cho mau thuan, cho chua ro",
        "find": "trang nay noi gi va muc do chac chan cua tung khang dinh (confirmed/reported/disputed/unknown), "
                "dieu nguoi doc muon biet, khoang trong, goc co the lam",
        "types": "fact, disputed_fact, uncertainty, audience_need, content_gap, opportunity",
    },
    "image_collection": {
        "label": "NGUON LA MOT BO ANH",
        "use": "phan tich hinh anh (chu the, phong cach), chu de nhan ra duoc, nghien cuu ngoai neu co",
        "find": "chu de va doi tuong trong anh, phong cach co the giu, goc co the lam tu chinh bo anh. "
                "Neu bo anh tu no da du ngu canh thi khong can dua vao nghien cuu ngoai",
        "types": "positive_signal, competitor_pattern, content_gap, opportunity, uncertainty",
    },
    "idea": {
        "label": "KHONG CO NGUON, chi co y tuong cua nguoi dung",
        "use": "y tuong, cac video tuong tu, comment mau, bang chung ve chu de tren web",
        "find": "nhu cau va cau hoi cua nguoi xem quanh chu de, pattern cua video tuong tu, khoang trong, goc co the lam",
        "types": "audience_need, audience_question, competitor_pattern, performance_pattern, content_gap, opportunity, uncertainty",
    },
}

INSIGHT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "insights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "type": {"type": "string", "enum": list(INSIGHT_TYPES)},
                    "statement": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "hypothesis": {"type": "boolean"},
                    "fact_status": {"type": "string", "enum": ["", *FACT_STATUSES]},
                    "implications": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["key", "type", "statement", "evidence_ids", "hypothesis", "fact_status", "implications"],
                "additionalProperties": False,
            },
        },
        "angle_candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "statement": {"type": "string"},
                    "target_audience": {"type": "string"},
                    "need_or_problem": {"type": "string"},
                    "supporting_insight_keys": {"type": "array", "items": {"type": "string"}},
                    "differentiation": {"type": "string"},
                    "platform_fit": {"type": "string"},
                    "risks": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["key", "statement", "target_audience", "need_or_problem", "supporting_insight_keys",
                             "differentiation", "platform_fit", "risks"],
                "additionalProperties": False,
            },
        },
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["insights", "angle_candidates", "limitations"],
    "additionalProperties": False,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any, limit: int = 600) -> str:
    return research_evidence.impersonal(" ".join(str(value or "").split()))[:limit]


def reasoning_kind(video: dict[str, Any], report: dict[str, Any]) -> str:
    """Which brief applies: the row's source_kind, or "idea" for a project with no source."""
    stored = source_kinds.valid((video or {}).get("source_kind"))
    if stored in KIND_BRIEFS:
        return stored
    researched = str(((report or {}).get("brief") or {}).get("source_kind") or "")
    return {"images": "image_collection"}.get(researched, researched) if researched in {"images", "product", "article", "video"} else "idea"


# ---------------------------------------------------------------------------
# What the model reads
# ---------------------------------------------------------------------------

def knowledge_evidence(database: Any, report: dict[str, Any]) -> list[dict[str, Any]]:
    """What the stores already hold, as evidence the model can cite.

    The source channel's profile stands for the window of uploads it was
    computed from; a stored topic fact stands for the page it was read on.
    Both come from the database only.
    """
    found: list[dict[str, Any]] = []
    channel = report.get("source_channel") or {}
    native = str(channel.get("native_channel_id") or "")
    platform = str(channel.get("platform") or "")
    if channel.get("channel_identity") == "native" and native:
        profile = ChannelIntelligence(database).get(platform, native) or {}
        stats, performance = profile.get("profile") or {}, profile.get("performance") or {}
        if stats or performance:
            captured = profile.get("performance_at") or profile.get("last_incremental_at") or profile.get("last_full_at")
            url = f"https://www.youtube.com/channel/{native}" if platform == "youtube" else f"{platform}:{native}"
            found.append(research_evidence.make_evidence(
                "channel_stats", source_url=url, collector="channel_research.profile",
                collector_version=str(profile.get("version") or "1"), native_source_id=native, platform=platform,
                title=str(profile.get("channel_name") or channel.get("channel_name") or ""),
                metrics={
                    "videos_sampled": (stats.get("sample") or {}).get("videos"),
                    "median_views": performance.get("median_views"),
                    "recent_vs_overall": performance.get("recent_vs_overall"),
                    "uploads_per_week": (stats.get("cadence") or {}).get("uploads_per_week"),
                    "median_duration_seconds": (stats.get("duration") or {}).get("median_seconds"),
                    "shorts": (stats.get("duration") or {}).get("shorts"),
                },
                sampling={"window": "recent uploads", "source": "channel profile"},
                captured_at=str(captured) if captured else None,
            ))
    topic = report.get("topic") or {}
    known = TopicIntelligence(database).get(str(topic.get("key") or ""), str((report.get("brief") or {}).get("language") or "vi"))
    for fact in ((known or {}).get("facts") or [])[:10]:
        urls = [str(url) for url in fact.get("source_urls") or [] if str(url).strip()]
        if not urls or not str(fact.get("fact") or "").strip():
            continue
        found.append(research_evidence.make_evidence(
            "article", source_url=urls[0], collector="topic_knowledge", platform="web",
            title=_clean(fact["fact"], 300), excerpt=_clean(fact["fact"], 300),
            metrics={"status": str(fact.get("status") or "reported"), "sources": len(urls)},
            sampling={"store": "topic_knowledge"}, captured_at=str(fact.get("captured_at") or "") or None,
        ))
    return found


def unusable_evidence(report: dict[str, Any], evidence: list[dict[str, Any]], kind: str) -> dict[str, str]:
    """Evidence that was collected but may carry nothing: {evidence id: why}.

    A page that answered with a block (kept by a report from before such
    pages were refused), a similar video that is on another subject, and the
    comments and captions read under it. The collector's own mark is used;
    a report from before the mark existed is judged by the same rule now.
    """
    excluded = {item["id"]: BLOCKED_SOURCE for item in evidence if research_collectors.is_blocked_evidence(item)}
    similar = report.get("similar_content") or []
    if any("relevance" not in item for item in similar):
        similar = research_collectors.mark_relevance(
            similar, research_collectors.topic_terms(report.get("brief") or {}), strict=kind in STRICT_RELEVANCE_KINDS)
    off_topic = {str(item.get("video_id")) for item in similar if item.get("relevance") == research_collectors.LOW}
    for item in evidence:
        if item["source_kind"] in {"video_meta", "comment_sample", "transcript"} and item.get("native_source_id") in off_topic:
            excluded[item["id"]] = LOW_RELEVANCE
    return excluded


def _evidence_line(database: Any, item: dict[str, Any]) -> list[str]:
    metrics = item.get("metrics") or {}
    kind = item["source_kind"]
    head = f"[{item['id']}] {kind}"
    title = _clean(item.get("title"), 140)
    if kind == "video_meta":
        facts = [f"{metrics[key]} {label}" for key, label in (
            ("view_count", "luot xem"), ("views_per_day", "luot xem/ngay"), ("comment_count", "comment"),
            ("duration_seconds", "giay"),
        ) if metrics.get(key) not in (None, "")]
        if metrics.get("published_at"):
            facts.append(f"dang {str(metrics['published_at'])[:10]}")
        return [f"{head} · “{title}” · " + ", ".join(facts)]
    if kind == "comment_sample":
        lines = [f"{head} · {item.get('sample_size')} comment mau duoi “{title}”"]
        scope = f"{item.get('platform') or 'youtube'}:{item.get('native_source_id')}"
        latest = next(iter(AudienceObservations(database).list("video", scope, limit=1)), None) if item.get("native_source_id") else None
        for pattern in (latest or {}).get("patterns") or []:
            name = pattern.get("kind")
            if name in {"questions", "negative"} and pattern.get("count"):
                label = "cau hoi" if name == "questions" else "comment co tu khoa tieu cuc"
                lines.append(f"    {pattern['count']}/{pattern.get('of')} {label}; vi du: " + " | ".join(
                    _clean(text, 140) for text in (pattern.get("examples") or [])[:3]))
            elif name == "terms" and pattern.get("items"):
                lines.append("    tu duoc nhac (so comment chua tu): " + ", ".join(
                    f"{term.get('term')} ({term.get('count')})" for term in pattern["items"][:8]))
            elif name == "most_liked" and pattern.get("examples"):
                lines.append("    duoc thich nhieu: " + " | ".join(
                    _clean(example.get("text"), 140) for example in pattern["examples"][:3]))
        return lines
    if kind == "transcript":
        return [f"{head} · mo dau cua “{title}” ({metrics.get('words')} tu): {_clean(item.get('excerpt'), 300)}"]
    if kind == "channel_stats":
        facts = [f"{label}: {metrics[key]}" for key, label in (
            ("videos_sampled", "so video trong cua so"), ("median_views", "luot xem trung vi"),
            ("recent_vs_overall", "gan day so voi toan bo"), ("uploads_per_week", "video/tuan"),
            ("median_duration_seconds", "thoi luong trung vi (giay)"), ("shorts", "so video <= 60 giay"),
        ) if metrics.get(key) not in (None, "")]
        return [f"{head} · ho so kenh “{title}” · " + "; ".join(facts)]
    if kind == "search_result":
        return [f"{head} · CHUA MO TRANG, chi la trich doan tim kiem · “{title}”: {_clean(item.get('excerpt'), 200)}"]
    if kind == "product_page":
        facts = [f"{key}: {metrics[key]}" for key in ("price", "original_price", "rating", "sold_count") if metrics.get(key) not in (None, "")]
        return [f"{head} · trang san pham “{title}” · doc luc {str(item.get('captured_at'))[:16]} · " + (", ".join(facts) or "khong co so lieu")]
    when = f" · {str(metrics.get('published_at'))[:10]}" if metrics.get("published_at") else ""
    status = f" · trang thai da luu: {metrics['status']}" if metrics.get("status") else ""
    return [f"{head} · “{title}”{when}{status}: {_clean(item.get('excerpt'), 300)}"]


def _source_block(kind: str, video: dict[str, Any], result: dict[str, Any], source_ids: list[str]) -> list[str]:
    cite = f" (ma bang chung cua nguon: {', '.join(source_ids)})" if source_ids else ""
    lines = [f"NGUON DA PHAN TICH{cite}",
             f"Tieu de: {_clean(video.get('title') or result.get('topic'), 200)}",
             f"Chu de: {_clean(result.get('topic'), 300)}",
             f"Tom tat: {_clean(result.get('content_summary'), 1800)}"]
    steps = [_clean(item.get("what_happens"), 160) for item in result.get("scene_map") or [] if isinstance(item, dict)]
    if steps:
        lines.append("Dien bien / y chinh: " + " → ".join(steps[:12]))
    words = [_clean(item.get("keyword") if isinstance(item, dict) else item, 40) for item in result.get("keywords") or []]
    if any(words):
        lines.append("Tu khoa: " + ", ".join(word for word in words[:15] if word))
    if kind in {"video", "image_collection"} and result.get("visual_style"):
        lines.append(f"Phong cach hinh: {_clean(result.get('visual_style'), 400)}")
    if kind in {"video", "audio"}:
        lines.append("Co loi noi: " + ("co" if result.get("has_dialogue") else "khong"))
    if kind == "audio":
        lines.append("Nguon KHONG co hinh anh.")
    if kind == "product":
        facts = result.get("source_facts") or {}
        shown = [f"{label}: {facts[key]}" for key, label in (
            ("name", "ten"), ("brand", "thuong hieu"), ("seller", "shop"), ("price_text", "gia hien thi"), ("price", "gia"),
            ("original_price_text", "gia goc"), ("discount", "giam"), ("rating", "sao"), ("review_count", "so danh gia"),
            ("sold_count", "da ban"), ("availability", "tinh trang"), ("category", "nganh hang"),
        ) if str(facts.get(key) or "").strip()]
        lines.append("Du kien san pham: " + ("; ".join(shown) or "khong doc duoc"))
        if str(facts.get("price") or facts.get("price_text") or "").strip():
            lines.append(f"Gia duoc doc luc: {facts.get('captured_at') or 'khong ro'} - chi dung tai thoi diem do.")
        else:
            lines.append("CHUA CO GIA: khong doc duoc gia tu trang ban. Khong neu bat ky con so gia nao.")
    limits = [_clean(item, 200) for item in result.get("limitations") or []]
    if limits:
        lines.append("Dieu buoc phan tich KHONG xac dinh duoc (khong duoc tu dien vao): " + " | ".join(limits[:8]))
    return lines


def build_pack(
    database: Any, video: dict[str, Any], analysis: dict[str, Any], report: dict[str, Any], kind: str,
) -> dict[str, Any]:
    """Everything the model is shown, and the evidence it may cite. Database reads only."""
    result = dict(analysis.get("result") or {})
    evidence = [*(report.get("evidence") or []), *knowledge_evidence(database, report)]
    by_id: dict[str, dict[str, Any]] = {}
    for item in evidence:
        by_id.setdefault(item["id"], item)
    excluded = unusable_evidence(report, list(by_id.values()), kind)
    evidence = [item for item in by_id.values() if item["id"] not in excluded]
    source_ids = [item["id"] for item in evidence if item.get("collector") == "planner.source"]
    brief = KIND_BRIEFS[kind]
    lines = [brief["label"], f"Du lieu duoc dung: {brief['use']}.", f"Can tim: {brief['find']}.",
             f"Loai insight phu hop: {brief['types']}.", ""]
    lines += _source_block(kind, video, result, source_ids)

    similar = [item for item in report.get("similar_content") or [] if item.get("evidence_id") not in excluded]
    if similar:
        lines += ["", "VIDEO TUONG TU DA LAY MAU (xep theo diem lien quan; khong phai toan bo thi truong):"]
        for item in similar[:10]:
            lines.append(
                f"- [{item.get('evidence_id')}] “{_clean(item.get('title'), 120)}” · {item.get('view_count')} luot xem · "
                f"{item.get('views_per_day')} luot xem/ngay · {item.get('duration_seconds')} giay · {str(item.get('published_at'))[:10]}"
            )
    counted = [(group, entry) for group in ("audience_insights", "competitor_patterns") for entry in report.get(group) or []
               if not set(entry.get("evidence_ids") or []) & set(excluded)]
    if counted:
        lines += ["", "SO DEM DA KIEM (app tu dem, co the dua vao bang chinh cac ma bang chung nay):"]
        lines += [f"- {entry['text']} [{', '.join(entry.get('evidence_ids') or [])}]" for _, entry in counted[:16]]
    patterns = []
    topic_key = str((report.get("topic") or {}).get("key") or "")
    if topic_key:
        patterns += ContentPatterns(database).list("topic", topic_key)
    if patterns:
        lines += ["", "DANG TIEU DE DA GHI NHAN CHO CHU DE NAY:"]
        lines += [f"- {_clean(item.get('description'), 160)}" for item in patterns[:6]]
    timeline = [entry for entry in report.get("timeline") or [] if entry.get("evidence_id") not in excluded]
    if timeline:
        lines += ["", "TRINH TU THOI GIAN (theo ngay dang cua cac trang da doc):"]
        lines += [f"- {str(entry.get('date'))[:10]} · “{_clean(entry.get('title'), 120)}” [{entry.get('evidence_id')}]" for entry in timeline[:12]]

    lines += ["", f"BANG CHUNG ({len(evidence)} muc):"]
    for item in evidence[:70]:
        lines += _evidence_line(database, item)
    dropped = {reason: sum(1 for value in excluded.values() if value == reason) for reason in (LOW_RELEVANCE, BLOCKED_SOURCE)}
    gaps = [*(report.get("limitations") or []), *[
        f"Khong lay duoc: {failed.get('source') or failed.get('collector')} ({failed.get('reason')})"
        for failed in (report.get("failed_sources") or [])[:8]
    ]]
    if dropped[LOW_RELEVANCE]:
        gaps.append(f"{dropped[LOW_RELEVANCE]} bang chung (video tuong tu, comment duoi no) bi loai vi khong lien quan toi nguon.")
    if dropped[BLOCKED_SOURCE]:
        gaps.append(f"{dropped[BLOCKED_SOURCE]} trang bi chan, chua doc duoc noi dung - khong co trong bang chung.")
    if gaps:
        lines += ["", "NHUNG GI CHUA THU THAP DUOC (khong duoc gia dinh la co):"]
        lines += [f"- {_clean(item, 220)}" for item in gaps[:12]]
    text = "\n".join(lines)
    return {
        "text": text[:PACK_CHARS],
        "truncated": len(text) > PACK_CHARS,
        "evidence": evidence,
        "excluded": excluded,
        "source_evidence_ids": source_ids,
        "stats": {
            "evidence_offered": len(evidence),
            "excluded_low_relevance": dropped[LOW_RELEVANCE],
            "excluded_blocked": dropped[BLOCKED_SOURCE],
            "from_report": len(report.get("evidence") or []),
            "from_knowledge": len({item["id"] for item in evidence} - {item["id"] for item in report.get("evidence") or []}),
            "similar_videos": len(similar),
            "count_statements": len(counted),
        },
    }


def build_prompt(pack: dict[str, Any], *, language: str, platform: str) -> str:
    return (
        f"Ngon ngu cua du an: {language}. Nen tang dich: {platform}.\n\n{pack['text']}\n\n"
        f"Hay tra ve toi da {MAX_INSIGHTS} insight va tu {MIN_ANGLES} den {MAX_ANGLES} goc noi dung."
    )


def repair_prompt(prompt: str, errors: list[str]) -> str:
    return (
        "Cau tra loi truoc KHONG dung. Loi:\n- " + "\n- ".join(errors[:12])
        + "\n\nHay lam lai tu dau, dung schema, chi dung cac ma bang chung co trong du lieu ben duoi.\n\n" + prompt
    )


# ---------------------------------------------------------------------------
# The validator
# ---------------------------------------------------------------------------

def shape_errors(parsed: Any) -> list[str]:
    """What makes an answer unusable as it stands (worth the one repair call)."""
    if not isinstance(parsed, dict):
        return ["Kết quả không phải một đối tượng JSON"]
    errors: list[str] = []
    insights = parsed.get("insights")
    angles = parsed.get("angle_candidates")
    if not isinstance(insights, list) or not insights:
        errors.append("Thiếu danh sách insights")
    if not isinstance(angles, list) or not angles:
        errors.append("Thiếu angle_candidates")
    for index, item in enumerate(insights if isinstance(insights, list) else []):
        if not isinstance(item, dict) or not _clean(item.get("statement")):
            errors.append(f"insights[{index}] thiếu statement")
        elif str(item.get("type") or "") not in INSIGHT_TYPES:
            errors.append(f"insights[{index}] có type không hợp lệ: {item.get('type')}")
    return errors


def is_causal_claim(text: str) -> bool:
    return bool(_CAUSAL.search(str(text or "")))


def _fact_status(insight_type: str, stated: str, cited: list[dict[str, Any]], measured: dict[str, Any]) -> str:
    """The status a claim has earned. A model saying "confirmed" does not make it so."""
    if insight_type == "disputed_fact":
        return "disputed"
    if insight_type == "uncertainty":
        return "unknown"
    read = [item for item in cited if item["source_kind"] not in research_evidence.WEAK_KINDS]
    sources = len({item["source_url"] for item in read})
    official = any(item["source_kind"] in research_evidence.AUTHORITATIVE_KINDS for item in read)
    if stated == "disputed":
        return "disputed"
    if not read:
        return "unknown"
    # Two independent pages read, or the owner of the fact itself.
    return "confirmed" if (sources >= 2 or official) and stated in ("confirmed", "") else "reported"


def validate(
    parsed: dict[str, Any], evidence: list[dict[str, Any]], *, kind: str, excluded: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Keep what rests on evidence, mark what is only supposed, refuse the rest - and say why.

    `excluded` is evidence that exists but may support nothing (off the
    subject, or a blocked page): {evidence id: why}.
    """
    by_id = {item["id"]: item for item in evidence}
    excluded = dict(excluded or {})
    insights: list[dict[str, Any]] = []
    hypotheses: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    key_to_id: dict[str, str] = {}
    seen: set[str] = set()

    def refuse(raw: dict[str, Any], reason: str, **more: Any) -> None:
        rejected.append({"statement": _clean((raw or {}).get("statement"), 400), "type": str((raw or {}).get("type") or ""),
                         "reason": reason, **more})

    for raw in (parsed.get("insights") or [])[: MAX_INSIGHTS * 2]:
        if not isinstance(raw, dict):
            continue
        statement = _clean(raw.get("statement"), 500)
        insight_type = str(raw.get("type") or "")
        implications = [_clean(item, 240) for item in raw.get("implications") or [] if _clean(item)][:4]
        if not statement:
            refuse(raw, "Insight trống")
            continue
        if insight_type not in INSIGHT_TYPES:
            refuse(raw, f"Loại insight không hợp lệ: {insight_type}")
            continue
        if statement.lower() in seen:
            continue
        seen.add(statement.lower())
        if is_causal_claim(statement) or any(is_causal_claim(item) for item in implications):
            refuse(raw, "Suy ra nguyên nhân từ tương quan. Chỉ được nêu pattern quan sát được trong mẫu.")
            continue
        if research_evidence.audience_share_without_sample(statement):
            refuse(raw, "Nêu tỉ lệ cho toàn bộ người xem trong khi chỉ có mẫu. Hãy nói tỉ lệ trên mẫu đã đọc.")
            continue
        cited_ids = list(dict.fromkeys(str(item) for item in raw.get("evidence_ids") or [] if str(item).strip()))
        barred = [item for item in cited_ids if item in excluded]
        if barred:
            refuse(raw, excluded[barred[0]], excluded_evidence_ids=barred)
            continue
        unknown = [item for item in cited_ids if item not in by_id]
        if unknown:
            refuse(raw, "Viện dẫn bằng chứng không tồn tại", unknown_evidence_ids=unknown)
            continue
        key = str(raw.get("key") or "")
        if not cited_ids:
            if bool(raw.get("hypothesis")):
                hypothesis_id = f"hy-{len(hypotheses) + 1}"
                hypotheses.append({
                    "id": hypothesis_id, "type": insight_type, "statement": statement, "basis": "hypothesis",
                    "evidence_ids": [], "source_count": 0, "sample_size": None, "confidence": "none",
                    "scope_note": "Giả thuyết: chưa có bằng chứng nào. Không được dùng như một dữ kiện.",
                    "implications": implications,
                })
            else:
                refuse(raw, "Không có bằng chứng và không được đánh dấu là giả thuyết")
            continue
        cited = [by_id[item] for item in cited_ids]
        if insight_type in PATTERN_TYPES and len(cited) < 2 and not any(item["source_kind"] in MULTI_VIDEO_KINDS for item in cited):
            refuse(raw, "Một video đơn lẻ không phải là pattern: cần từ hai video trở lên hoặc hồ sơ kênh.")
            continue
        measured = research_evidence.measure(cited)
        only_snippets = all(item["source_kind"] in research_evidence.WEAK_KINDS for item in cited)
        confidence = "low" if only_snippets or bool(raw.get("hypothesis")) else measured["confidence"]
        insight: dict[str, Any] = {
            "id": f"in-{len(insights) + 1}", "type": insight_type, "statement": statement, "basis": "evidence",
            "evidence_ids": cited_ids, "source_count": measured["source_count"], "sample_size": measured["sample_size"],
            "confidence": confidence, "scope_note": measured["scope_note"], "captured_at": measured["captured_at"],
            "implications": implications,
        }
        if only_snippets:
            insight["scope_note"] += " Chỉ dựa trên trích đoạn tìm kiếm chưa mở trang."
        if insight_type in FACT_TYPES:
            insight["fact_status"] = _fact_status(insight_type, str(raw.get("fact_status") or ""), cited, measured)
        if insight_type in PATTERN_TYPES:
            insight["scope_note"] += " Đây là pattern quan sát được trong mẫu, không phải nguyên nhân."
        if kind == "product" and insight_type == "selling_point":
            read_on_page = any(item["source_kind"] in research_evidence.AUTHORITATIVE_KINDS for item in cited)
            insight["proof"] = "supported" if read_on_page or confidence != "low" else "needs_proof"
        if _PRICE.search(statement):
            # A price is a reading: it holds only with the listing it was read on, and the time.
            pages = [item for item in cited if item["source_kind"] == "product_page"
                     and (item.get("metrics") or {}).get("price") not in (None, "")]
            if pages:
                insight["price_captured_at"] = max(str(item.get("captured_at") or "") for item in pages)
            else:
                insight["proof"] = "needs_proof"
        insights.append(insight)
        if key:
            key_to_id[key] = insight["id"]
        if len(insights) >= MAX_INSIGHTS:
            break

    angles: list[dict[str, Any]] = []
    rejected_angles: list[dict[str, Any]] = []
    known = {item["id"]: item for item in insights}
    rank = {"high": 3, "medium": 2, "low": 1}
    for raw in parsed.get("angle_candidates") or []:
        if not isinstance(raw, dict):
            continue
        statement = _clean(raw.get("statement"), 400)
        if not statement:
            continue
        if is_causal_claim(statement):
            rejected_angles.append({"statement": statement, "reason": "Góc dựa trên suy luận nhân quả từ tương quan"})
            continue
        keys = [str(item) for item in raw.get("supporting_insight_keys") or []]
        support = list(dict.fromkeys(key_to_id.get(item) or (item if item in known else "") for item in keys))
        support = [item for item in support if item]
        if not support:
            rejected_angles.append({
                "statement": statement,
                "reason": "Góc nội dung không dựa trên insight nào có bằng chứng",
                "cited": keys,
            })
            continue
        if len(angles) >= MAX_ANGLES:
            break
        confidences = [known[item]["confidence"] for item in support]
        angles.append({
            "id": f"ang-{len(angles) + 1}", "statement": statement,
            "target_audience": _clean(raw.get("target_audience"), 300),
            "need_or_problem": _clean(raw.get("need_or_problem"), 400),
            "supporting_insight_ids": support,
            "evidence_ids": list(dict.fromkeys(eid for item in support for eid in known[item]["evidence_ids"])),
            "support_confidence": max(confidences, key=lambda value: rank.get(value, 0)),
            "differentiation": _clean(raw.get("differentiation"), 400),
            "platform_fit": _clean(raw.get("platform_fit"), 300),
            "risks": [_clean(item, 240) for item in raw.get("risks") or [] if _clean(item)][:5],
        })
    return {
        "insights": insights, "hypotheses": hypotheses, "rejected": rejected,
        "angle_candidates": angles, "rejected_angles": rejected_angles,
        "limitations": [_clean(item, 300) for item in parsed.get("limitations") or [] if _clean(item)][:10],
    }


def validation_errors(
    parsed: Any, evidence: list[dict[str, Any]], *, kind: str, excluded: dict[str, str] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Shape problems, or a result that left nothing to plan from. Returns (errors, validated)."""
    errors = shape_errors(parsed)
    if errors:
        return errors, {}
    validated = validate(parsed, evidence, kind=kind, excluded=excluded)
    if not validated["insights"]:
        reasons = "; ".join(sorted({item["reason"] for item in validated["rejected"]}))[:400]
        errors.append("Không insight nào có bằng chứng hợp lệ" + (f" ({reasons})" if reasons else ""))
    elif not validated["angle_candidates"]:
        errors.append(
            "Không góc nội dung nào dựa trên insight có bằng chứng. supporting_insight_keys phải trỏ tới key của insight "
            "có evidence_ids hợp lệ."
        )
    return errors, validated


def assemble(
    validated: dict[str, Any], pack: dict[str, Any], *, kind: str, research_report_id: int | None,
    analysis: dict[str, Any], ai: dict[str, Any],
) -> dict[str, Any]:
    """The InsightReport as stored: what was kept, what was refused, and what it was read from."""
    by_id = {item["id"]: item for item in pack["evidence"]}
    cited = sorted({eid for item in validated["insights"] for eid in item["evidence_ids"]})
    by_type: dict[str, int] = {}
    for item in validated["insights"]:
        by_type[item["type"]] = by_type.get(item["type"], 0) + 1
    statuses: dict[str, int] = {}
    for item in validated["insights"]:
        if item.get("fact_status"):
            statuses[item["fact_status"]] = statuses.get(item["fact_status"], 0) + 1
    limitations = list(validated["limitations"])
    if len(validated["angle_candidates"]) < MIN_ANGLES:
        limitations.append(f"Chỉ có {len(validated['angle_candidates'])} góc nội dung dựa trên insight có bằng chứng.")
    if pack.get("truncated"):
        limitations.append("Dữ liệu nghiên cứu dài hơn phần đưa cho AI đọc; một số bằng chứng cuối danh sách chưa được đọc.")
    left_out = pack.get("excluded") or {}
    low = sorted(eid for eid, why in left_out.items() if why == LOW_RELEVANCE)
    blocked = sorted(eid for eid, why in left_out.items() if why == BLOCKED_SOURCE)
    if low:
        limitations.append(f"{len(low)} bằng chứng (video tương tự và comment dưới nó) ít liên quan tới nguồn nên không được dùng.")
    if blocked:
        limitations.append(f"{len(blocked)} trang bị chặn, chưa đọc được nội dung nên không được dùng.")
    return {
        "source_kind": kind,
        "insights": validated["insights"],
        "hypotheses": validated["hypotheses"],
        "rejected": validated["rejected"],
        "angle_candidates": validated["angle_candidates"],
        "rejected_angles": validated["rejected_angles"],
        "summary": {
            "by_type": by_type, "fact_status": statuses, "insights": len(validated["insights"]),
            "hypotheses": len(validated["hypotheses"]), "rejected": len(validated["rejected"]),
            "evidence_cited": len(cited), "evidence_offered": pack["stats"]["evidence_offered"],
        },
        # Enough of each cited piece to show it without the research report.
        "evidence_index": {
            eid: {key: by_id[eid].get(key) for key in ("source_kind", "title", "source_url", "sample_size", "captured_at", "collector")}
            for eid in cited if eid in by_id
        },
        "excluded_evidence": {"low_relevance": low, "blocked": blocked},
        "limitations": limitations,
        "input": pack["stats"],
        "research_report_id": research_report_id,
        "analysis_ref": {"created_at": analysis.get("created_at"), "provider": analysis.get("provider")},
        "ai": ai,
        "engine_version": ENGINE_VERSION,
        "captured_at": _now(),
    }


def topic_facts(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The checked claims worth keeping for the next plan on this subject: each with the pages it was read on."""
    index = report.get("evidence_index") or {}
    facts = []
    for item in report.get("insights") or []:
        if item["type"] not in {"fact", "disputed_fact"}:
            continue
        urls = [str((index.get(eid) or {}).get("source_url") or "") for eid in item["evidence_ids"]
                if (index.get(eid) or {}).get("source_kind") not in research_evidence.WEAK_KINDS]
        urls = [url for url in dict.fromkeys(urls) if url.startswith("http")]
        if urls:
            facts.append({"fact": item["statement"], "source_urls": urls, "status": item.get("fact_status") or "reported",
                          "captured_at": item.get("captured_at") or _now()})
    return facts
