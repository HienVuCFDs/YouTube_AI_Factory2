"""Bước 3 · Kịch bản: the words of the video, written from the plan.

    ProjectPlan (completed)  →  ScriptDocument  →  checks by rule

The plan is the source of truth. It has already chosen the angle, the
audience, the length, the platform and the sections with their time
budgets; this step only turns that strategy into what is said and what is
written on screen. It researches nothing, re-plans nothing and decides
none of what the plan decided.

One model call writes the document (and one repair if it is unusable).
Then the code takes over, because a model's text is not a check of itself:

* every section of the plan has exactly one section of script, in order;
* the length is counted from the words at the language's speaking rate -
  the model is not asked how long its text takes;
* every insight and evidence id cited must exist; a number the sources do
  not contain, a price nobody read, a claim the plan forbids, or a guess
  stated as a fact is refused;
* the script is words, not a storyboard: no picture, camera, shot or
  transition directions.

A ScriptDocument names the plan (id and version) it was written from, so it
is stale the moment the plan it served is no longer the current, completed
plan of the project.

The document is the script. The old columns (hook, intro, main_content, cta)
are written from it and only from it; an edit made through them is put back
into the document and checked again, so the two never say different things.
"""

from __future__ import annotations

import copy
import difflib
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

from . import freshness, languages, plan_engine, project_planner, research_text
from .fidelity_guard import numbers

ENGINE_VERSION = "script-phase1"
DRAFT_ENGINE_VERSION = "agent-draft"

STAGES = (
    ("read_plan", "Đọc kế hoạch"),
    ("write", "Viết lời"),
    ("check", "Kiểm tra kịch bản"),
    ("finalize", "Hoàn thiện kịch bản"),
)

# How far the whole may drift from the plan's target, and how far one section
# may run past the time the plan gave it, before it is a problem.
DURATION_TOLERANCE = 0.15
SECTION_OVERRUN = 1.5
SECTION_SLACK_SECONDS = 5
# Small counting numbers ("ba điều", "2 lý do") are wording, not facts.
FREE_NUMBERS = 10
PRICE_FRESH_HOURS = 24

COMPLETED, STALE, INVALID, MISSING = "completed", "stale", "invalid", "missing"

# The scripts Bước 3 makes: the engine's, and an agent's own draft held to the
# same plan (its engine_version is the compatibility marker). A plan-linked row
# made by anything else is not Bước 3's script.
CANONICAL_ENGINES = frozenset({ENGINE_VERSION, DRAFT_ENGINE_VERSION})

STALE_SCRIPT_MESSAGE = "Kịch bản này thuộc một kế hoạch cũ. Hãy viết lại kịch bản trước khi tiếp tục."

# What every way of continuing a planned project past Bước 3 answers when it
# may not - voice, storyboard, timeline, render, translate, publish, Short.
# One wording per reason, whichever door was used.
CONTINUE_MESSAGES = {
    "no_plan": "Bạn cần hoàn thành Kế hoạch trước khi tiếp tục.",
    plan_engine.NEEDS_USER_DECISION: "Kế hoạch hiện cần bạn quyết định trước khi tiếp tục.",
    plan_engine.BLOCKED: "Kế hoạch hiện chưa thể thực hiện, chưa thể tiếp tục.",
    "plan_stale": "Kế hoạch đã cũ vì dữ liệu bên dưới đã thay đổi. Hãy lập lại kế hoạch trước khi tiếp tục.",
    "running": "Kịch bản đang được tạo. Vui lòng chờ lượt hiện tại hoàn tất.",
    MISSING: "Chưa có kịch bản viết từ Kế hoạch hiện tại. Hãy viết kịch bản trước khi tiếp tục.",
    STALE: STALE_SCRIPT_MESSAGE,
    INVALID: "Kịch bản hiện tại không còn hợp lệ với kế hoạch. Hãy viết lại kịch bản trước khi tiếp tục.",
    "mismatch": "Kịch bản hiện tại không khớp với kế hoạch hiện tại.",
    # A job, an export or a re-cut made for an earlier version of the script.
    "superseded": "Việc này được tạo cho một phiên bản kịch bản cũ. Hãy chạy lại từ kịch bản hiện tại.",
    "short_stale": "Short này được tạo từ một phiên bản kịch bản cũ. Hãy tạo lại Short từ kịch bản hiện tại.",
}

# How a Short records the long script it was written from. Kept in the Short's
# own row (plan_id and plan_version columns, the rest in document_json), so
# no column is added for it.
SHORT_PROVENANCE = "short_provenance"

# Directions for the picture belong to the storyboard (Bước 5), not here.
_STAGE_DIRECTION = re.compile(
    r"\b(camera|máy quay|góc máy|lia máy|cận cảnh|toàn cảnh|trung cảnh|cảnh quay|chuyển cảnh|b-?roll|"
    r"visual prompt|shot|cut to|fade (?:in|out)|transition|zoom (?:in|out)|close-?up|wide shot)\b",
    re.IGNORECASE,
)
_BRACKETED_DIRECTION = re.compile(r"[\[(]\s*(?:hình|cảnh|camera|b-?roll|chèn|visual|nhạc|sfx|âm thanh)\b[^\])]*[\])]", re.IGNORECASE)
_PRICE = re.compile(r"₫|\bvnđ\b|\bvnd\b|\d[\d.,]*\s*(?:đ|k|nghìn|ngàn|triệu)\b|\bgiá\s+(?:chỉ\s+|là\s+|còn\s+)?\d", re.IGNORECASE)
# A sentence that hedges or denies is not the claim it mentions.
_HEDGE = re.compile(r"\b(không|chưa|chẳng|có thể|chưa chắc|theo|nếu|liệu|dường như|được cho là|cho rằng)\b|\?", re.IGNORECASE)
# The plan's rules prefix what they forbid with why; the claim is what follows.
_RULE_PREFIX = re.compile(r"^[^:]{0,80}:\s*")

SYSTEM_PROMPT = """Ban viet LOI cho mot video. Ban nhan KE HOACH da duoc nguoi dung duyet (goc noi dung, khan gia, muc tieu,
thoi luong, cac phan co ma [s1], [s2]... kem so giay), cac INSIGHT va BANG CHUNG ke hoach dua vao, va NOI DUNG NGUON.
Viec cua ban: chuyen ke hoach thanh LOI NOI va CHU TREN MAN HINH. Ke hoach la su that; ban khong doi no.

Luat bat buoc:
1. Theo dung ke hoach: dung goc noi dung da chon (angle_id), dung khan gia, dung muc tieu. Moi phan cua ke hoach co DUNG MOT
   section voi plan_section_id tuong ung, dung thu tu. Khong them phan, khong bo phan, khong gop phan.
2. hook: loi mo dau, thuoc phan dau tien. cta: loi ket, thuoc phan cuoi cung. Ca hai tinh vao thoi luong cua phan do.
3. Chi viet LOI NOI (spoken_lines) va CHU TREN MAN HINH (on_screen_text). KHONG mo ta hinh anh, canh quay, goc may, chuyen
   canh, B-roll, zoom hay am thanh - viec do la cua buoc Storyboard sau nay.
4. Do dai: viet du loi cho so giay cua tung phan theo toc do doc da cho. App tu dem so giay tu so chu; khong ghi so giay.
5. Su that: chi dung dieu co trong NOI DUNG NGUON va trong INSIGHT/BANG CHUNG duoc dua. Moi section ghi insight_ids va
   evidence_ids no dua vao - chi dung ma co trong du lieu. Khong them so lieu, ten rieng, gia hay su kien nao khac.
   GIA THUYET khong phai su that: khong noi nhu su that.
6. Tuyet doi khong noi cac dieu trong muc KHONG DUOC NOI. Giu dung cac dieu trong muc PHAI GIU DUNG; dieu gi moi mot nguon
   dua thi noi ro la theo nguon do.
7. Gia san pham: chi neu dung gia da doc, kem thoi diem doc. Chua doc duoc gia, hoac gia da cu, thi khong neu con so gia.
8. Khong tu nghien cuu them, khong doi goc noi dung, khong doi thoi luong, khong doi nen tang.
9. missing_information: dieu ke hoach can ma nguon khong co. limitations: gioi han cua ban kich ban nay.
10. Viet bang ngon ngu da cho (tieng Viet thi co dau day du). Speaker mac dinh la "narrator"; chi dung ten nhan vat khi
    nguon co nhan vat do noi. Chi tra ve JSON dung schema."""

_LINES = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"speaker": {"type": "string"}, "text": {"type": "string"}},
        "required": ["speaker", "text"],
        "additionalProperties": False,
    },
}
_TEXTS = {"type": "array", "items": {"type": "string"}}
_PART = {
    "type": "object",
    "properties": {"spoken_lines": _LINES, "on_screen_text": _TEXTS},
    "required": ["spoken_lines", "on_screen_text"],
    "additionalProperties": False,
}
SCRIPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "angle_id": {"type": "string"},
        "tone": {"type": "string"},
        "hook": _PART,
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "plan_section_id": {"type": "string"},
                    "spoken_lines": _LINES,
                    "on_screen_text": _TEXTS,
                    "insight_ids": _TEXTS,
                    "evidence_ids": _TEXTS,
                },
                "required": ["plan_section_id", "spoken_lines", "on_screen_text", "insight_ids", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "cta": _PART,
        "missing_information": _TEXTS,
        "limitations": _TEXTS,
    },
    "required": ["title", "angle_id", "tone", "hook", "sections", "cta", "missing_information", "limitations"],
    "additionalProperties": False,
}


class ScriptError(RuntimeError):
    """The step could not finish, said in words a person can act on."""

    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any, limit: int = 600) -> str:
    return " ".join(str(value or "").split())[:limit]


def _texts(values: Any, limit: int = 12, size: int = 400) -> list[str]:
    return list(dict.fromkeys(_clean(item, size) for item in values or [] if _clean(item)))[:limit]


# ---------------------------------------------------------------------------
# The plan the script is written from
# ---------------------------------------------------------------------------

_NO_PLAN = "Bạn cần hoàn thành Kế hoạch trước khi viết kịch bản."
_PLAN_REFUSALS = {
    None: _NO_PLAN,
    # Research only: the plan itself has not been made.
    "draft": _NO_PLAN,
    plan_engine.NEEDS_USER_DECISION: "Kế hoạch hiện cần bạn quyết định trước khi viết kịch bản.",
    plan_engine.BLOCKED: "Kế hoạch hiện chưa thể thực hiện, chưa thể viết kịch bản.",
    plan_engine.STALE: "Kế hoạch đã cũ vì dữ liệu bên dưới đã thay đổi. Hãy lập lại kế hoạch ở Bước 2 trước khi viết kịch bản.",
}


def ready_plan(plan_row: dict[str, Any] | None) -> dict[str, Any]:
    """The plan to write from, or ScriptError(409) saying why there is none.

    Only a plan Bước 2 calls completed - feasibility ok or adjusted, and
    nothing under it changed since - may carry a script.
    """
    outcome = project_planner.step_outcome(plan_row)
    if outcome and outcome["completed"]:
        return plan_row  # type: ignore[return-value]
    status = (outcome or {}).get("status")
    raise ScriptError(_PLAN_REFUSALS.get(status, _PLAN_REFUSALS[None]), 409)


def plan_sections(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """The plan's content structure with the ids a script section refers to (s1, s2, …)."""
    return [
        {"id": f"s{index}", "name": _clean(item.get("name"), 160), "purpose": _clean(item.get("purpose"), 400),
         "seconds": max(1, int(item.get("estimated_seconds") or 0)), "key_points": _texts(item.get("key_points"), 8),
         "insight_ids": list(item.get("insight_ids") or []), "evidence_ids": list(item.get("evidence_ids") or [])}
        for index, item in enumerate(plan.get("content_structure") or [], start=1)
    ]


def speaking_rate(language: str) -> dict[str, Any]:
    speech = languages.resolve(language)
    return {"tokens_per_second": float(speech["tokens_per_second"]), "unit": str(speech.get("unit") or "từ")}


def spoken_seconds(text: str, rate: float) -> float:
    return len(re.findall(r"\w+", str(text or ""), flags=re.UNICODE)) / max(0.5, rate)


# ---------------------------------------------------------------------------
# What the model reads
# ---------------------------------------------------------------------------

def _source_block(kind: str, video: dict[str, Any], analysis: dict[str, Any], transcript: str) -> list[str]:
    result = dict(analysis.get("result") or {})
    lines = ["NOI DUNG NGUON (chi dung dieu co o day)", f"Tieu de: {_clean(video.get('title') or result.get('topic'), 200)}",
             f"Chu de: {_clean(result.get('topic'), 300)}", f"Tom tat: {_clean(result.get('content_summary'), 2500)}"]
    steps = [_clean(item.get("what_happens"), 200) for item in result.get("scene_map") or [] if isinstance(item, dict)]
    if steps:
        lines.append("Y chinh / dien bien: " + " → ".join(steps[:14]))
    if kind == "product":
        facts = result.get("source_facts") or {}
        shown = [f"{label}: {facts[key]}" for key, label in (
            ("name", "ten"), ("brand", "thuong hieu"), ("seller", "shop"), ("price_text", "gia hien thi"), ("price", "gia"),
            ("original_price_text", "gia goc"), ("discount", "giam"), ("rating", "sao"), ("review_count", "so danh gia"),
            ("sold_count", "da ban"), ("availability", "tinh trang"), ("category", "nganh hang"),
        ) if str(facts.get(key) or "").strip()]
        lines.append("Du kien san pham: " + ("; ".join(shown) or "khong doc duoc"))
        price = price_reading(analysis)
        if price["known"]:
            lines.append(f"Gia duoc doc luc: {price['captured_at'] or 'khong ro'}"
                         + ("" if price["fresh"] else " - DA CU, khong duoc neu con so gia."))
        else:
            lines.append("CHUA DOC DUOC GIA: khong neu bat ky con so gia nao.")
    if kind in {"video", "audio"}:
        spoken = [f"{_clean(item.get('speaker'), 40) or 'Không rõ'}: {_clean(item.get('line'), 240)}"
                  for item in result.get("dialogue") or [] if isinstance(item, dict)]
        if spoken:
            lines.append("Loi thoai cua nguon:\n" + "\n".join(spoken[:60]))
        if transcript:
            lines.append(f"Transcript (co the bi cat): {transcript[:6000]}")
    if kind == "audio":
        lines.append("Nguon la am thanh, KHONG co hinh.")
    limits = _texts(result.get("limitations"), 8, 240)
    if limits:
        lines.append("Dieu buoc phan tich KHONG xac dinh duoc (khong tu dien vao): " + " | ".join(limits))
    return lines


def build_prompt(
    *, plan_row: dict[str, Any], insight: dict[str, Any], video: dict[str, Any], analysis: dict[str, Any], transcript: str = "",
) -> str:
    plan = plan_row.get("plan") or {}
    kind = str(plan.get("source_kind") or "")
    language = str(plan.get("language") or "vi")
    rate = speaking_rate(language)
    target = int(plan.get("target_duration_seconds") or 0)
    angle = plan.get("primary_angle") or {}
    lines = [
        f"KE HOACH DA DUYET (ban {plan_row.get('version')}). Loai nguon: {kind}. Ngon ngu: {language}.",
        f"Nen tang: {plan.get('platform')} · khung hinh {plan.get('aspect_ratio')} · loai video: {_clean(plan.get('video_type'), 80)}",
        f"THOI LUONG MUC TIEU: {target} giay. Toc do doc: khoang {rate['tokens_per_second']:.1f} {rate['unit']}/giay "
        f"(tong khoang {round(target * rate['tokens_per_second'])} {rate['unit']}).",
        f"GOC NOI DUNG DA CHON [{angle.get('id')}]: {_clean(angle.get('statement'), 400)}",
        f"  · Danh cho: {_clean(angle.get('target_audience'), 300)}",
        f"  · Nhu cau / van de: {_clean(angle.get('need_or_problem'), 300)}",
        f"  · Diem khac biet: {_clean(angle.get('differentiation'), 300)}",
        f"Khan gia: {_clean(plan.get('target_audience'), 300)}",
        f"Muc tieu: {_clean(plan.get('goal'), 400)}",
        f"Cach mo dau (hook): {_clean(plan.get('hook_strategy'), 500)}",
        f"Loi ket (CTA): {_clean(plan.get('cta'), 300)}",
        "",
        "CAC PHAN (moi phan dung mot section, dung thu tu; so giay la ngan sach thoi luong cua phan do):",
    ]
    for section in plan_sections(plan):
        lines.append(f"- [{section['id']}] {section['name']} — {section['seconds']} giay "
                     f"(khoang {round(section['seconds'] * rate['tokens_per_second'])} {rate['unit']}). Muc dich: {section['purpose']}")
        for point in section["key_points"]:
            lines.append(f"    · {point}")
        if section["insight_ids"] or section["evidence_ids"]:
            lines.append(f"    dua vao: {', '.join([*section['insight_ids'], *section['evidence_ids']])}")
    statements = {item["id"]: item for item in insight.get("insights") or []}
    cited = list(dict.fromkeys([
        *(angle.get("supporting_insight_ids") or []),
        *[iid for item in plan.get("content_structure") or [] for iid in item.get("insight_ids") or []],
    ]))
    if cited:
        lines += ["", "INSIGHT KE HOACH DUA VAO (co bang chung):"]
        for iid in cited:
            item = statements.get(iid)
            if item:
                status = f" · trang thai: {item['fact_status']}" if item.get("fact_status") else ""
                lines.append(f"- [{iid}] ({item['type']}{status}) {_clean(item['statement'], 400)} — bang chung: {', '.join(item['evidence_ids'][:6])}")
    if insight.get("hypotheses"):
        lines += ["", "GIA THUYET (KHONG phai su that, khong duoc noi nhu su that):"]
        lines += [f"- {_clean(item['statement'], 300)}" for item in insight["hypotheses"]]
    index = insight.get("evidence_index") or {}
    if index:
        lines += ["", "BANG CHUNG (ma duoc phep dan):"]
        lines += [f"- [{eid}] {item.get('source_kind')} · {_clean(item.get('title'), 140)}" for eid, item in list(index.items())[:40]]
    if plan.get("factual_guardrails"):
        lines += ["", "PHAI GIU DUNG:"] + [f"- {_clean(item, 400)}" for item in plan["factual_guardrails"]]
    avoid = [*(plan.get("claims_to_avoid") or []), *(plan.get("claims_needing_proof") or [])]
    if avoid:
        lines += ["", "KHONG DUOC NOI (hoac chi noi khi co bang chung ro rang):"] + [f"- {_clean(item, 400)}" for item in avoid]
    must_not = (plan.get("constraints") or {}).get("must_not_invent") or []
    if must_not:
        lines += ["", "KHONG TU DIEN VAO: " + " | ".join(_clean(item, 200) for item in must_not[:8])]
    if (plan.get("constraints") or {}).get("script_mode") == "faithful_retell":
        lines += ["", "WORKFLOW KE LAI: giu nguyen su viec, nhan vat, ten, con so, thu tu va loi thoai cua nguon; chi doi cach ke."]
    lines += ["", *_source_block(kind, video, analysis, transcript)]
    lines += ["", f"Tra ve angle_id = {angle.get('id')} va dung {len(plan_sections(plan))} section."]
    return "\n".join(lines)


def repair_prompt(prompt: str, errors: list[str]) -> str:
    return (
        "Ban kich ban truoc KHONG dung. Loi:\n- " + "\n- ".join(errors[:14])
        + "\n\nHay viet lai tu dau, dung schema, dung cac ma va so phan da cho.\n\n" + prompt
    )


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

def price_reading(analysis: dict[str, Any]) -> dict[str, Any]:
    """The listing's price as it was read, and whether that reading is still fresh."""
    facts = ((analysis or {}).get("result") or {}).get("source_facts") or {}
    text = _clean(facts.get("price_text") or facts.get("price"), 80)
    captured = str(facts.get("captured_at") or "") or None
    digits = {re.sub(r"\D", "", str(value)) for value in (facts.get("price"), facts.get("price_text"), facts.get("original_price"),
                                                          facts.get("original_price_text")) if re.sub(r"\D", "", str(value or ""))}
    state = freshness.product_price(captured)["state"] if captured else freshness.MISSING
    return {"known": bool(text), "text": text, "captured_at": captured, "digits": digits, "fresh": state == freshness.FRESH}


def _known_numbers(*texts: Any) -> set[str]:
    found: set[str] = set()
    for text in texts:
        for value in numbers(str(text or "")):
            found.add(re.sub(r"[.,]", "", value))
    return found


def _claim_body(claim: str) -> str:
    """The claim itself, without the rule in front of it ("Chưa có bằng chứng, không nói như sự thật: …")."""
    text = str(claim or "")
    main = _RULE_PREFIX.sub("", text, count=1) if ":" in text[:90] else text
    return re.split(r"[;—]", main)[0]


def _claim_tokens(claim: str) -> set[str]:
    return set(research_text.tokens(_claim_body(claim)))


def _restates(sentence: str, claim: str) -> bool:
    """A sentence that says, plainly, what a claim to avoid says.

    Said with a doubt or a negation it is not said as a fact - unless the
    claim itself carries one.
    """
    wanted = _claim_tokens(claim)
    if len(wanted) < 4:
        return False
    have = set(research_text.tokens(sentence))
    if len(wanted & have) / len(wanted) < 0.8:
        return False
    claim_hedged = bool(_HEDGE.search(_claim_body(claim)))
    return claim_hedged or not _HEDGE.search(sentence)


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?…])\s+|\n+", str(text or "")) if part.strip()]


def text_errors(
    lines: list[dict[str, Any]], *, plan: dict[str, Any], insight: dict[str, Any], analysis: dict[str, Any],
    allowed_numbers: set[str], label: str,
) -> list[str]:
    """What is wrong with words wherever they come from: the model's, or an agent's draft."""
    errors: list[str] = []
    kind = str(plan.get("source_kind") or "")
    price = price_reading(analysis)
    no_price = bool((plan.get("constraints") or {}).get("no_price_claims"))
    avoid = [*(plan.get("claims_to_avoid") or []), *(plan.get("claims_needing_proof") or [])]
    guesses = [item.get("statement") for item in insight.get("hypotheses") or []]
    for line in lines:
        text = str(line.get("text") or "")
        if _STAGE_DIRECTION.search(text) or _BRACKETED_DIRECTION.search(text):
            errors.append(f"{label}: có chỉ dẫn hình ảnh/cảnh quay ({_clean(text, 80)}) - kịch bản chỉ gồm lời nói và chữ trên màn hình")
        if _PRICE.search(text):
            if no_price or (kind == "product" and not price["known"]):
                errors.append(f"{label}: nêu giá trong khi chưa đọc được giá ({_clean(text, 80)})")
            elif kind == "product" and not price["fresh"]:
                errors.append(f"{label}: nêu giá đã đọc quá {PRICE_FRESH_HOURS} giờ ({_clean(text, 80)}); kế hoạch yêu cầu đọc lại trước khi nêu")
            elif kind == "product":
                stated = {re.sub(r"[.,]", "", value) for value in numbers(text)}
                if stated and not stated & price["digits"]:
                    errors.append(f"{label}: giá nêu ra không khớp giá đã đọc ({_clean(text, 80)})")
        unknown = [value for value in numbers(text) if re.sub(r"[.,]", "", value) not in allowed_numbers
                   and not (value.isdigit() and int(value) <= FREE_NUMBERS)]
        if unknown:
            errors.append(f"{label}: số liệu không có trong nguồn hay bằng chứng: {', '.join(unknown[:5])}")
        for sentence in _sentences(text):
            for claim in avoid:
                if _restates(sentence, claim):
                    errors.append(f"{label}: nói điều kế hoạch cấm: “{_clean(sentence, 120)}”")
                    break
            for guess in guesses:
                if _restates(sentence, guess):
                    errors.append(f"{label}: nói giả thuyết như sự thật: “{_clean(sentence, 120)}”")
                    break
    return errors


def _inputs(database: Any, plan_row: dict[str, Any], analysis: dict[str, Any], video_id: str = "") -> dict[str, Any]:
    """What the checks read besides the words: the plan's insights, its evidence and the numbers the sources hold."""
    plan = plan_row.get("plan") or {}
    insight_row = database.get_insight_report(int(plan_row["insight_report_id"])) if plan_row.get("insight_report_id") else None
    insight = (insight_row or {}).get("report") or {}
    report_row = database.get_research_report(int(plan_row["research_report_id"])) if plan_row.get("research_report_id") else None
    transcript_row = database.get_transcript(video_id, transcript_format="txt") if video_id else None
    transcript = str((transcript_row or {}).get("content_text") or "")
    allowed = allowed_numbers_for(plan, insight, analysis, (report_row or {}).get("report") or {}, transcript)
    return {"plan": plan, "insight_row": insight_row, "insight": insight, "transcript": transcript, "allowed": allowed}


def _lines(raw: Any) -> list[dict[str, str]]:
    found = []
    for item in raw or []:
        if isinstance(item, dict) and _clean(item.get("text")):
            found.append({"speaker": _clean(item.get("speaker"), 60) or "narrator", "text": _clean(item.get("text"), 1200)})
    return found


def validate(
    parsed: Any, *, plan_row: dict[str, Any], insight: dict[str, Any], analysis: dict[str, Any], allowed_numbers: set[str],
) -> tuple[list[str], dict[str, Any]]:
    """(errors, the checked pieces). An empty error list means the document can be assembled."""
    if not isinstance(parsed, dict):
        return ["Kết quả không phải một đối tượng JSON"], {}
    plan = plan_row.get("plan") or {}
    errors: list[str] = []
    wanted = plan_sections(plan)
    rate = speaking_rate(str(plan.get("language") or "vi"))["tokens_per_second"]

    # A. The plan.
    angle_id = str(plan.get("primary_angle_id") or (plan.get("primary_angle") or {}).get("id") or "")
    if str(parsed.get("angle_id") or "") != angle_id:
        errors.append(f"angle_id phải là {angle_id}: góc nội dung đã chọn ở Bước 2")
    raw_sections = [item for item in parsed.get("sections") or [] if isinstance(item, dict)]
    got = [str(item.get("plan_section_id") or "") for item in raw_sections]
    expected = [item["id"] for item in wanted]
    if got != expected:
        missing = [item for item in expected if item not in got]
        extra = [item for item in got if item not in expected]
        detail = "; ".join(part for part in (
            f"thiếu {', '.join(missing)}" if missing else "", f"không có trong kế hoạch: {', '.join(extra)}" if extra else "",
            "sai thứ tự hoặc lặp" if not missing and not extra else "",
        ) if part)
        errors.append(f"Các section phải đúng {', '.join(expected)} theo thứ tự ({detail})")
    hook = _lines((parsed.get("hook") or {}).get("spoken_lines") if isinstance(parsed.get("hook"), dict) else None)
    cta = _lines((parsed.get("cta") or {}).get("spoken_lines") if isinstance(parsed.get("cta"), dict) else None)
    if not hook:
        errors.append("Thiếu lời mở đầu (hook)")
    if _clean(plan.get("cta")) and not cta:
        errors.append("Thiếu lời kết (cta) trong khi kế hoạch có CTA")
    sections = []
    known_insights = {item["id"] for item in insight.get("insights") or []}
    known_evidence = set(insight.get("evidence_index") or {}) | {eid for item in wanted for eid in item["evidence_ids"]}
    for raw, plan_section in zip(raw_sections, wanted):
        lines = _lines(raw.get("spoken_lines"))
        if not lines:
            errors.append(f"[{plan_section['id']}] chưa có lời nói")
        bad_insights = [item for item in raw.get("insight_ids") or [] if str(item) not in known_insights]
        bad_evidence = [item for item in raw.get("evidence_ids") or [] if str(item) not in known_evidence]
        if bad_insights or bad_evidence:
            errors.append(f"[{plan_section['id']}] dẫn mã không tồn tại: {', '.join(map(str, [*bad_insights, *bad_evidence]))}")
        sections.append({"plan": plan_section, "lines": lines, "on_screen_text": _texts(raw.get("on_screen_text"), 8, 200),
                         "insight_ids": [str(item) for item in dict.fromkeys(raw.get("insight_ids") or [])],
                         "evidence_ids": [str(item) for item in dict.fromkeys(raw.get("evidence_ids") or [])]})

    # B. Length, counted here from the words.
    target = int(plan.get("target_duration_seconds") or 0)
    hook_seconds = sum(spoken_seconds(item["text"], rate) for item in hook)
    cta_seconds = sum(spoken_seconds(item["text"], rate) for item in cta)
    for index, section in enumerate(sections):
        own = sum(spoken_seconds(item["text"], rate) for item in section["lines"])
        section["seconds"] = own
        counted = own + (hook_seconds if index == 0 else 0) + (cta_seconds if index == len(sections) - 1 else 0)
        budget = section["plan"]["seconds"]
        if counted > max(budget * SECTION_OVERRUN, budget + SECTION_SLACK_SECONDS):
            errors.append(f"[{section['plan']['id']}] dài khoảng {round(counted)} giây trong khi kế hoạch dành {budget} giây")
    total = hook_seconds + cta_seconds + sum(section["seconds"] for section in sections)
    if target and abs(total - target) > DURATION_TOLERANCE * target:
        errors.append(f"Tổng lời đọc khoảng {round(total)} giây, kế hoạch đặt {target} giây (cho phép lệch {round(DURATION_TOLERANCE * 100)}%)")

    # C, D. Facts and the boundary with the storyboard.
    parts = [("hook", hook), *[(f"[{section['plan']['id']}]", section["lines"]) for section in sections], ("cta", cta)]
    screen = [("chữ trên màn hình", [{"text": text} for text in [
        *_texts((parsed.get("hook") or {}).get("on_screen_text") if isinstance(parsed.get("hook"), dict) else None, 8, 200),
        *[text for section in sections for text in section["on_screen_text"]],
        *_texts((parsed.get("cta") or {}).get("on_screen_text") if isinstance(parsed.get("cta"), dict) else None, 8, 200),
    ]])]
    for label, lines in [*parts, *screen]:
        errors += text_errors(lines, plan=plan, insight=insight, analysis=analysis, allowed_numbers=allowed_numbers, label=label)
    checked = {"hook": hook, "cta": cta, "sections": sections, "hook_seconds": hook_seconds, "cta_seconds": cta_seconds, "total": total,
               "hook_screen": _texts((parsed.get("hook") or {}).get("on_screen_text") if isinstance(parsed.get("hook"), dict) else None, 8, 200),
               "cta_screen": _texts((parsed.get("cta") or {}).get("on_screen_text") if isinstance(parsed.get("cta"), dict) else None, 8, 200)}
    return list(dict.fromkeys(errors)), checked


def allowed_numbers_for(
    plan: dict[str, Any], insight: dict[str, Any], analysis: dict[str, Any], report: dict[str, Any], transcript: str,
) -> set[str]:
    """Every number the sources, the evidence and the plan contain: the only numbers a script may say."""
    result = dict((analysis or {}).get("result") or {})
    evidence_text = [f"{item.get('title')} {item.get('excerpt')} {json.dumps(item.get('metrics') or {}, ensure_ascii=False)}"
                     for item in (report or {}).get("evidence") or []]
    return _known_numbers(
        json.dumps(result, ensure_ascii=False), transcript,
        json.dumps([item.get("statement") for item in insight.get("insights") or []], ensure_ascii=False),
        json.dumps(insight.get("evidence_index") or {}, ensure_ascii=False), *evidence_text,
        json.dumps({key: plan.get(key) for key in ("content_structure", "goal", "hook_strategy", "cta", "factual_guardrails",
                                                   "primary_angle")}, ensure_ascii=False),
    )


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------

def assemble(
    parsed: dict[str, Any], checked: dict[str, Any], *, plan_row: dict[str, Any], insight_row: dict[str, Any] | None,
    analysis: dict[str, Any], ai: dict[str, Any],
) -> dict[str, Any]:
    """The ScriptDocument as stored: the words, what each rests on, and the plan it was written from."""
    plan = plan_row.get("plan") or {}
    language = str(plan.get("language") or "vi")
    rate = speaking_rate(language)
    price = price_reading(analysis)

    def mark(lines: list[dict[str, str]]) -> list[dict[str, Any]]:
        return _mark(lines, price)

    sections = checked["sections"]
    document = {
        "engine_version": ENGINE_VERSION,
        "title": _clean(parsed.get("title"), 200) or _clean((plan.get("primary_angle") or {}).get("statement"), 200),
        "language": language,
        "tone": _clean(parsed.get("tone"), 200),
        "source_kind": plan.get("source_kind"),
        "plan": {
            "plan_id": plan_row.get("id"), "plan_version": plan_row.get("version"),
            "primary_angle_id": plan.get("primary_angle_id"), "primary_angle": _clean((plan.get("primary_angle") or {}).get("statement"), 400),
            "target_duration_seconds": plan.get("target_duration_seconds"), "platform": plan.get("platform"),
            "aspect_ratio": plan.get("aspect_ratio"), "output_profile": plan.get("output_profile"), "video_type": plan.get("video_type"),
        },
        "target_duration_seconds": int(plan.get("target_duration_seconds") or 0),
        "estimated_seconds": round(checked["total"]),
        "speaking_rate": rate,
        "hook": {"plan_section_id": sections[0]["plan"]["id"] if sections else None, "spoken_lines": mark(checked["hook"]),
                 "on_screen_text": checked["hook_screen"], "estimated_seconds": round(checked["hook_seconds"])},
        "sections": [
            {"id": f"sec-{index}", "plan_section_id": section["plan"]["id"], "name": section["plan"]["name"],
             "purpose": section["plan"]["purpose"], "budget_seconds": section["plan"]["seconds"],
             "spoken_lines": mark(section["lines"]), "on_screen_text": section["on_screen_text"],
             "estimated_seconds": round(section["seconds"]), "insight_ids": section["insight_ids"], "evidence_ids": section["evidence_ids"]}
            for index, section in enumerate(sections, start=1)
        ],
        "cta": {"plan_section_id": sections[-1]["plan"]["id"] if sections else None, "spoken_lines": mark(checked["cta"]),
                "on_screen_text": checked["cta_screen"], "estimated_seconds": round(checked["cta_seconds"])},
        "price_reading": {"text": price["text"], "captured_at": price["captured_at"]} if price["known"] else None,
        "factual_guardrails": list(plan.get("factual_guardrails") or []),
        "claims_to_avoid": list(plan.get("claims_to_avoid") or []),
        "checks": {"plan_alignment": "ok", "duration": "ok", "evidence": "ok", "claims": "ok", "boundary": "ok"},
        "validation": {"ok": True, "errors": [], "checked_at": _now(), "source": "engine"},
        "missing_information": _texts(parsed.get("missing_information"), 12),
        "limitations": _texts(parsed.get("limitations"), 12),
        "research_report_id": plan_row.get("research_report_id"),
        "insight_report_id": (insight_row or {}).get("id"),
        "analysis_ref": {"created_at": analysis.get("created_at"), "provider": analysis.get("provider")},
        "ai": ai,
        "captured_at": _now(),
    }
    stale_price = f"Giá đọc lúc {price['captured_at']} đã quá {PRICE_FRESH_HOURS} giờ nên kịch bản không nêu con số giá."
    if price["known"] and not price["fresh"] and stale_price not in document["limitations"]:
        document["limitations"].append(stale_price)
    return document


def _mark(lines: list[dict[str, Any]], price: dict[str, Any]) -> list[dict[str, Any]]:
    """A price said aloud carries the moment it was read."""
    return [{**line, "price_captured_at": price["captured_at"]} if price["known"] and _PRICE.search(line["text"]) else line
            for line in lines]


def legacy_fields(document: dict[str, Any]) -> dict[str, str]:
    """The old columns (hook, intro, main_content, cta), written from the document so older readers still work.

    One spoken line per line of text, and every section, in order, in
    main_content: the storyboard's plain-script path makes a scene of each
    line. The hook and the CTA keep their own columns. `intro` stays empty -
    the first section is content like the others, and the conclusion is not
    the call to action, so neither is folded into a column the storyboard
    treats as a single opening or closing card.
    """
    def said(lines: Any) -> str:
        return "\n".join(str(line.get("text") or "") for line in lines or [] if str(line.get("text") or "").strip())

    return {
        "script_title": _clean(document.get("title"), 300),
        "hook": said((document.get("hook") or {}).get("spoken_lines")),
        "intro": "",
        "main_content": "\n".join(part for part in (said(section.get("spoken_lines")) for section in document.get("sections") or []) if part),
        "cta": said((document.get("cta") or {}).get("spoken_lines")),
    }


def _field_lines(text: Any) -> list[str]:
    return [_clean(line, 1200) for line in str(text or "").replace("\r", "\n").split("\n") if _clean(line)]


# ---------------------------------------------------------------------------
# An agent's own draft: the same facts and the same length, no section map
# ---------------------------------------------------------------------------

def _draft_check(
    fields: dict[str, Any], *, plan: dict[str, Any], insight: dict[str, Any], analysis: dict[str, Any], allowed: set[str],
) -> tuple[list[str], dict[str, Any]]:
    rate = speaking_rate(str(plan.get("language") or "vi"))["tokens_per_second"]
    parts = {
        "hook": [{"speaker": "narrator", "text": text} for text in _field_lines(fields.get("hook"))],
        "body": [{"speaker": "narrator", "text": text} for text in [*_field_lines(fields.get("intro")), *_field_lines(fields.get("main_content"))]],
        "cta": [{"speaker": "narrator", "text": text} for text in _field_lines(fields.get("cta"))],
    }
    errors = text_errors([*parts["hook"], *parts["body"], *parts["cta"]], plan=plan, insight=insight, analysis=analysis,
                         allowed_numbers=allowed, label="bản nháp")
    seconds = {key: sum(spoken_seconds(line["text"], rate) for line in lines) for key, lines in parts.items()}
    total = sum(seconds.values())
    target = int(plan.get("target_duration_seconds") or 0)
    if not parts["body"]:
        errors.append("Bản nháp chưa có lời nói cho phần thân")
    if target and abs(total - target) > DURATION_TOLERANCE * target:
        errors.append(f"Bản nháp đọc khoảng {round(total)} giây, kế hoạch đặt {target} giây")
    return list(dict.fromkeys(errors)), {**parts, "seconds": seconds, "total": total}


def _draft_document(
    title: str, checked: dict[str, Any], *, plan_row: dict[str, Any], insight_row: dict[str, Any] | None, analysis: dict[str, Any],
) -> dict[str, Any]:
    plan = plan_row.get("plan") or {}
    target = int(plan.get("target_duration_seconds") or 0)
    price = price_reading(analysis)
    return {
        "engine_version": DRAFT_ENGINE_VERSION, "title": _clean(title, 200),
        "language": str(plan.get("language") or "vi"), "source_kind": plan.get("source_kind"),
        "plan": {"plan_id": plan_row.get("id"), "plan_version": plan_row.get("version"), "primary_angle_id": plan.get("primary_angle_id"),
                 "primary_angle": _clean((plan.get("primary_angle") or {}).get("statement"), 400), "target_duration_seconds": target},
        "target_duration_seconds": target, "estimated_seconds": round(checked["total"]),
        "speaking_rate": speaking_rate(str(plan.get("language") or "vi")),
        "hook": {"plan_section_id": None, "spoken_lines": _mark(checked["hook"], price), "on_screen_text": [],
                 "estimated_seconds": round(checked["seconds"]["hook"])},
        # One block: a draft cannot be mapped onto the plan's sections.
        "sections": [{"id": "sec-1", "plan_section_id": None, "name": "Toàn bài (bản tự viết)", "purpose": "", "budget_seconds": target,
                      "spoken_lines": _mark(checked["body"], price), "on_screen_text": [],
                      "estimated_seconds": round(checked["seconds"]["body"]), "insight_ids": [], "evidence_ids": []}],
        "cta": {"plan_section_id": None, "spoken_lines": _mark(checked["cta"], price), "on_screen_text": [],
                "estimated_seconds": round(checked["seconds"]["cta"])},
        "price_reading": {"text": price["text"], "captured_at": price["captured_at"]} if price["known"] else None,
        "factual_guardrails": list(plan.get("factual_guardrails") or []),
        "claims_to_avoid": list(plan.get("claims_to_avoid") or []),
        "checks": {"plan_alignment": "not_checked", "duration": "ok", "evidence": "not_checked", "claims": "ok", "boundary": "ok"},
        "missing_information": [],
        "limitations": ["Bản tự viết (agent hoặc người dùng): chưa đối chiếu được từng phần với cấu trúc của kế hoạch."],
        "research_report_id": plan_row.get("research_report_id"),
        "insight_report_id": (insight_row or {}).get("id"),
        "analysis_ref": {"created_at": analysis.get("created_at"), "provider": analysis.get("provider")},
        "captured_at": _now(),
    }


# ---------------------------------------------------------------------------
# Editing a written script
# ---------------------------------------------------------------------------

def _realign(old: list[tuple[int, dict[str, Any]]], new: list[str], default: int = 0) -> list[tuple[int, dict[str, Any]]]:
    """The edited lines, each in the place of the old line it stands for.

    An unchanged line keeps everything it had; a rewritten one takes the
    section and the speaker of the line it replaces; an added one joins the
    line before it (or the first one, at the very start).
    """
    matcher = difflib.SequenceMatcher(a=[str(line.get("text") or "") for _, line in old], b=new, autojunk=False)
    placed: list[tuple[int, dict[str, Any]]] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            placed += old[i1:i2]
            continue
        for k in range(j1, j2):
            if op == "replace":
                tag, line = old[i1 + (k - j1) * (i2 - i1) // (j2 - j1)]
            elif op == "insert":
                tag, line = old[i1 - 1] if i1 > 0 else (old[0] if old else (default, {}))
            else:
                continue
            placed.append((tag, {"speaker": str(line.get("speaker") or "narrator"), "text": new[k]}))
    return placed


def apply_edit(document: dict[str, Any], edits: dict[str, Any]) -> dict[str, Any]:
    """The document with an edit made through the old columns put back into it."""
    edited = copy.deepcopy(document)
    if edits.get("script_title") is not None:
        edited["title"] = _clean(edits["script_title"], 200)
    for part in ("hook", "cta"):
        if edits.get(part) is not None:
            block = edited.setdefault(part, {})
            old = [(0, line) for line in block.get("spoken_lines") or []]
            block["spoken_lines"] = [line for _, line in _realign(old, _field_lines(edits[part]))]
    if edits.get("intro") is not None or edits.get("main_content") is not None:
        current = legacy_fields(document)
        intro = current["intro"] if edits.get("intro") is None else edits["intro"]
        body = current["main_content"] if edits.get("main_content") is None else edits["main_content"]
        sections = edited.get("sections") or []
        if not sections:
            sections = [{"id": "sec-1", "plan_section_id": None, "name": "Toàn bài (bản tự viết)", "purpose": "",
                         "spoken_lines": [], "on_screen_text": [], "insight_ids": [], "evidence_ids": []}]
        old = [(index, line) for index, section in enumerate(sections) for line in section.get("spoken_lines") or []]
        placed = _realign(old, [*_field_lines(intro), *_field_lines(body)])
        for index, section in enumerate(sections):
            section["spoken_lines"] = [line for tag, line in placed if tag == index]
        edited["sections"] = sections
    return edited


def _as_answer(document: dict[str, Any]) -> dict[str, Any]:
    """A document in the shape the model answers in, so an edit is checked by the same rules as the model."""
    def part(block: Any) -> dict[str, Any]:
        block = block or {}
        return {"spoken_lines": block.get("spoken_lines") or [], "on_screen_text": block.get("on_screen_text") or []}

    return {
        "title": document.get("title"), "angle_id": (document.get("plan") or {}).get("primary_angle_id"), "tone": document.get("tone"),
        "hook": part(document.get("hook")),
        "sections": [{"plan_section_id": section.get("plan_section_id"), **part(section),
                      "insight_ids": section.get("insight_ids") or [], "evidence_ids": section.get("evidence_ids") or []}
                     for section in document.get("sections") or []],
        "cta": part(document.get("cta")),
        "missing_information": document.get("missing_information") or [], "limitations": document.get("limitations") or [],
    }


_CHECK_KINDS = (
    ("boundary", ("chỉ dẫn hình ảnh",)),
    ("claims", ("kế hoạch cấm", "giả thuyết", "nêu giá", "giá nêu ra")),
    ("evidence", ("dẫn mã", "số liệu")),
    ("duration", ("giây",)),
    ("plan_alignment", ("angle_id", "section", "hook", "cta", "lời nói")),
)


def _checks(errors: list[str], base: dict[str, Any]) -> dict[str, Any]:
    """Which of the document's checks an error list breaks."""
    result = {key: ("ok" if value == "failed" else value) for key, value in (base or {}).items()}
    for error in errors:
        text = error.lower()
        kind = next((name for name, needles in _CHECK_KINDS if any(needle in text for needle in needles)), "plan_alignment")
        result[kind] = "failed"
    return result


def revise(
    database: Any, script: dict[str, Any], edits: dict[str, Any], *, plan_row: dict[str, Any], analysis: dict[str, Any],
    video_id: str = "", source: str = "edit",
) -> dict[str, Any]:
    """An edit of a written script, checked again against the plan it was written from.

    Returns the new document - its `validation` saying whether it still holds
    - and the old columns written from it. Nothing is refused here: an edit
    that breaks the plan is kept, marked invalid, and nothing is built on it
    until it is fixed. The plan the script belongs to never changes here.
    """
    document = decode(script)
    if document is None:
        raise ScriptError("Kịch bản này không có ScriptDocument nên không sửa theo kế hoạch được.", 409)
    edited = apply_edit(document, edits)
    context = _inputs(database, plan_row, analysis, video_id)
    if document.get("engine_version") == DRAFT_ENGINE_VERSION:
        errors, checked = _draft_check(legacy_fields(edited), plan=context["plan"], insight=context["insight"], analysis=analysis,
                                       allowed=context["allowed"])
        revised = _draft_document(edited.get("title") or "", checked, plan_row=plan_row, insight_row=context["insight_row"], analysis=analysis)
    else:
        parsed = _as_answer(edited)
        errors, checked = validate(parsed, plan_row=plan_row, insight=context["insight"], analysis=analysis,
                                   allowed_numbers=context["allowed"])
        revised = assemble(parsed, checked, plan_row=plan_row, insight_row=context["insight_row"], analysis=analysis,
                           ai=document.get("ai") or {})
        revised["tone"] = document.get("tone") or revised.get("tone")
    revised["engine_version"] = document.get("engine_version")
    revised["captured_at"] = document.get("captured_at") or revised.get("captured_at")
    revised["checks"] = _checks(errors, revised.get("checks") or {})
    revised["validation"] = {"ok": not errors, "errors": errors, "checked_at": _now(), "source": source}
    revised["revisions"] = [*(document.get("revisions") or []),
                            {"source": source, "at": _now(), "from_script_id": script.get("id"), "ok": not errors}][-20:]
    return {"document": revised, "fields": legacy_fields(revised), "errors": errors}


# ---------------------------------------------------------------------------
# The step
# ---------------------------------------------------------------------------

def run(
    database: Any,
    project: dict[str, Any],
    video: dict[str, Any],
    analysis: dict[str, Any],
    plan_row: dict[str, Any],
    *,
    reasoner: Callable[..., tuple[Any, dict[str, Any]]],
    progress: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """Write, check and save the script of a completed plan. One model call, and one repair at most."""
    def stage(key: str) -> None:
        if progress:
            progress(key, dict(STAGES).get(key, key))

    stage("read_plan")
    plan_row = ready_plan(plan_row)
    plan = plan_row.get("plan") or {}
    if not plan_sections(plan):
        raise ScriptError("Kế hoạch chưa có cấu trúc nội dung để viết kịch bản. Hãy lập lại kế hoạch ở Bước 2.", 409)
    context = _inputs(database, plan_row, analysis, str(video.get("youtube_video_id") or ""))
    insight_row, insight, allowed = context["insight_row"], context["insight"], context["allowed"]
    prompt = build_prompt(plan_row=plan_row, insight=insight, video=video, analysis=analysis, transcript=context["transcript"])

    stage("write")
    ai = project_planner._Ai(reasoner)
    holder: dict[str, Any] = {}

    def check(parsed: Any) -> tuple[list[str], Any]:
        stage("check")
        errors, checked = validate(parsed, plan_row=plan_row, insight=insight, analysis=analysis, allowed_numbers=allowed)
        holder["checked"] = checked
        return errors, checked

    try:
        parsed, checked = ai.ask("Viết kịch bản", SYSTEM_PROMPT, prompt, SCRIPT_SCHEMA, check=check, repair=repair_prompt)
    except project_planner.PlanError as exc:
        raise ScriptError(str(exc).replace("ở bước Viết kịch bản", "khi viết kịch bản"), exc.status_code) from exc

    stage("finalize")
    document = assemble(parsed, checked, plan_row=plan_row, insight_row=insight_row, analysis=analysis, ai=ai.summary())
    saved = database.create_project_script(
        int(project["id"]), **legacy_fields(document), status="draft", variant="long",
        plan_id=plan_row.get("id"), plan_version=plan_row.get("version"), insight_report_id=(insight_row or {}).get("id"),
        language=document["language"], estimated_seconds=document["estimated_seconds"], document=document,
        engine_version=ENGINE_VERSION,
    )
    if not saved:
        raise ScriptError("Không lưu được kịch bản", 500)
    return {
        "status": COMPLETED, "script_id": saved["id"], "version": saved["version"], "plan_id": plan_row.get("id"),
        "plan_version": plan_row.get("version"), "primary_angle_id": plan.get("primary_angle_id"),
        "target_duration_seconds": document["target_duration_seconds"], "estimated_seconds": document["estimated_seconds"],
        "sections": [{"plan_section_id": item["plan_section_id"], "name": item["name"], "estimated_seconds": item["estimated_seconds"],
                      "budget_seconds": item["budget_seconds"]} for item in document["sections"]],
        "missing_information": document["missing_information"], "limitations": document["limitations"],
        "ai": document["ai"], "script": saved,
    }


def save_draft(
    database: Any, project: dict[str, Any], analysis: dict[str, Any], plan_row: dict[str, Any], draft: dict[str, Any],
) -> dict[str, Any]:
    """A script written outside the engine - by an agent, or pasted - held to the same plan, facts and length.

    It cannot be mapped section by section - a draft is four blocks of text -
    so that check is recorded as not done; everything that can be checked on
    words alone is, and a draft that fails is refused with the reasons.
    """
    plan_row = ready_plan(plan_row)
    context = _inputs(database, plan_row, analysis, str(project.get("youtube_video_id") or ""))
    fields = {key: str(draft.get(key) or "") for key in ("hook", "intro", "main_content", "cta")}
    errors, checked = _draft_check(fields, plan=context["plan"], insight=context["insight"], analysis=analysis, allowed=context["allowed"])
    if errors:
        raise ScriptError("Bản nháp chưa dùng được: " + "; ".join(errors[:6]), 422)
    title = _clean(draft.get("script_title") or draft.get("title"), 200) or _clean(project.get("title"), 200)
    document = _draft_document(title, checked, plan_row=plan_row, insight_row=context["insight_row"], analysis=analysis)
    document["validation"] = {"ok": True, "errors": [], "checked_at": _now(), "source": str(draft.get("source") or "draft")}
    saved = database.create_project_script(
        int(project["id"]), **legacy_fields(document), status=str(draft.get("status") or "review"), variant="long",
        plan_id=plan_row.get("id"), plan_version=plan_row.get("version"), insight_report_id=(context["insight_row"] or {}).get("id"),
        language=document["language"], estimated_seconds=document["estimated_seconds"], document=document,
        engine_version=DRAFT_ENGINE_VERSION,
    )
    if not saved:
        raise ScriptError("Không lưu được kịch bản", 404)
    return {"status": COMPLETED, "script_id": int(saved["id"]), "engine_version": DRAFT_ENGINE_VERSION, "script": saved}


def save_revision(
    database: Any, project: dict[str, Any], analysis: dict[str, Any], plan_row: dict[str, Any], base: dict[str, Any],
    edits: dict[str, Any], *, source: str,
) -> dict[str, Any]:
    """A new version of a written script (an AI rewrite, say), kept on the plan the script was written from.

    Only a current script can be revised: one from an older plan is written
    again, not touched up into looking current. The revision is checked like
    an edit and saved even when it fails, marked invalid.
    """
    plan_row = ready_plan(plan_row)
    if decode(base) is None or (base.get("plan_id"), base.get("plan_version")) != (plan_row.get("id"), plan_row.get("version")):
        raise ScriptError(STALE_SCRIPT_MESSAGE, 409)
    revised = revise(database, base, edits, plan_row=plan_row, analysis=analysis, video_id=str(project.get("youtube_video_id") or ""),
                     source=source)
    document = revised["document"]
    saved = database.create_project_script(
        int(project["id"]), **revised["fields"], status="draft", variant="long", plan_id=base.get("plan_id"),
        plan_version=base.get("plan_version"), insight_report_id=base.get("insight_report_id"), language=document.get("language") or "",
        estimated_seconds=document.get("estimated_seconds") or 0, document=document, engine_version=str(base.get("engine_version") or ""),
    )
    if not saved:
        raise ScriptError("Không lưu được kịch bản", 404)
    return {"status": INVALID if revised["errors"] else COMPLETED, "script_id": int(saved["id"]), "engine_version": saved.get("engine_version"),
            "validation": document["validation"], "script": saved}


# ---------------------------------------------------------------------------
# Where the step stands
# ---------------------------------------------------------------------------

def decode(script: dict[str, Any] | None) -> dict[str, Any] | None:
    """The ScriptDocument of a long script. A Short's row holds its provenance there instead, never a document."""
    if not script or str(script.get("variant") or "long") != "long":
        return None
    try:
        document = json.loads(script.get("document_json") or "null")
    except ValueError:
        document = None
    return document if isinstance(document, dict) else None


# ---------------------------------------------------------------------------
# Provenance: what a Short (or a re-cut) was made from
# ---------------------------------------------------------------------------

def provenance(script: dict[str, Any]) -> dict[str, Any]:
    """Which long script - and plan - something was made from, to be stored with it."""
    return {"kind": SHORT_PROVENANCE, "source_script_id": int(script["id"]), "source_script_version": int(script.get("version") or 0),
            "plan_id": script.get("plan_id"), "plan_version": script.get("plan_version"), "recorded_at": _now()}


def short_provenance(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """The provenance a Short's row carries, or None (a Short from before provenance, or outside the plan workflow)."""
    if not row or str(row.get("variant") or "") != "short":
        return None
    try:
        stored = json.loads(row.get("document_json") or "null")
    except ValueError:
        stored = None
    return stored if isinstance(stored, dict) and stored.get("kind") == SHORT_PROVENANCE else None


def _made_from_current(stored: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if not stored:
        return False
    made = (stored.get("source_script_id"), stored.get("source_script_version"), stored.get("plan_id"), stored.get("plan_version"))
    return made == (current.get("id"), current.get("version"), current.get("plan_id"), current.get("plan_version"))


def artifact_block(row: dict[str, Any] | None, current: dict[str, Any] | None, *, recut: dict[str, Any] | None = None) -> tuple[str, str]:
    """(code, message) when `row` - the script a job, an export or a Short was made for - is not the current one.

    Called after `production_block` has passed, with `current` the project's
    current script. A long row must be that script itself (a job queued for an
    earlier version must not run on the later one). A Short must carry the
    provenance of exactly that script and plan; so must a re-cut Short's plan
    (`recut`, the stored re-cut plan) when the job renders one.
    """
    if not current:
        return MISSING, CONTINUE_MESSAGES[MISSING]
    if not row:
        return MISSING, CONTINUE_MESSAGES[MISSING]
    if str(row.get("variant") or "long") == "short":
        if not _made_from_current(short_provenance(row), current):
            return "short_stale", CONTINUE_MESSAGES["short_stale"]
        return "", ""
    if int(row["id"]) != int(current["id"]):
        return "superseded", CONTINUE_MESSAGES["superseded"]
    if recut is not None and not _made_from_current((recut.get("plan") or {}).get("provenance"), current):
        return "short_stale", CONTINUE_MESSAGES["short_stale"]
    return "", ""


def current_script(database: Any, project_id: int, plan_row: dict[str, Any] | None) -> dict[str, Any] | None:
    """The latest long script and whether it is current.

    Current only when it was written from the project's current plan - the
    same plan id and version - and that plan is still completed. Anything
    else (a script from before plans existed, from an older plan, or under a
    plan that has since gone stale) is kept, untouched, and is stale.
    """
    script = database.get_latest_project_script(project_id)
    if not script:
        return None
    document = decode(script)
    reasons = []
    # Which way it is not current: written before any plan or for an older
    # version of it ("stale"), or linked to something that is not the current
    # plan at all ("mismatch").
    kind = ""
    if not script.get("plan_id"):
        kind = STALE
        reasons.append("Kịch bản này được viết trước khi có kế hoạch, không theo kế hoạch nào")
    elif str(script.get("engine_version") or "") not in CANONICAL_ENGINES or document is None:
        kind = "mismatch"
        reasons.append("Kịch bản này không được viết bằng Script Engine")
    elif not plan_row:
        kind = "mismatch"
        reasons.append("Dự án không còn kế hoạch nào")
    elif (int(script["plan_id"]), int(script.get("plan_version") or 0)) != (int(plan_row["id"]), int(plan_row.get("version") or 0)):
        older = script.get("plan_version") is not None and int(script["plan_version"]) < int(plan_row.get("version") or 0)
        kind = STALE if older else "mismatch"
        reasons.append("Kế hoạch đã thay đổi sau khi viết kịch bản" if older
                       else "Kịch bản không khớp kế hoạch hiện tại (plan_id hoặc plan_version)")
    outcome = project_planner.step_outcome(plan_row)
    if plan_row and not (outcome or {}).get("completed"):
        kind = kind or STALE
        reasons.append("Kế hoạch hiện chưa sẵn sàng")
    # An edit that broke the plan is kept, but it is not a script anything may
    # be built on until it is fixed.
    validation = (document or {}).get("validation") or {}
    invalid = not reasons and validation.get("ok") is False
    state = STALE if reasons else INVALID if invalid else COMPLETED
    return {**script, "document": document, "state": state, "stale": bool(reasons), "stale_reasons": reasons,
            "stale_kind": kind if reasons else "",
            "invalid": invalid, "validation_errors": list(validation.get("errors") or []) if invalid else []}


def step_outcome(script: dict[str, Any] | None) -> dict[str, Any] | None:
    """Where Bước 3 stands, from `current_script`. None before any script."""
    if not script:
        return None
    reasons = script["stale_reasons"] or script.get("validation_errors") or []
    return {"status": script["state"], "completed": script["state"] == COMPLETED, "reason": "; ".join(reasons[:5]),
            "script_id": script.get("id"), "script_version": script.get("version"), "plan_id": script.get("plan_id"),
            "plan_version": script.get("plan_version"), "engine_version": script.get("engine_version"), "approval": script.get("status")}


def production_block(plan_row: dict[str, Any] | None, script: dict[str, Any] | None, *, running: bool) -> tuple[str, str]:
    """(reason code, message) when a planned project may not go past Bước 3 yet; ("", "") when it may.

    Checked in this order: the plan exists and is completed; no script is
    being written; the script exists, was written from this plan (same id
    and version) by the engine or as a checked draft, and was not left
    invalid by an edit. `script` is what `current_script` returns.
    """
    outcome = project_planner.step_outcome(plan_row)
    status = (outcome or {}).get("status")
    if not outcome or status == "draft":
        return "no_plan", CONTINUE_MESSAGES["no_plan"]
    if not outcome["completed"]:
        code = "plan_stale" if status == plan_engine.STALE else status
        return code, CONTINUE_MESSAGES.get(code, CONTINUE_MESSAGES["no_plan"])
    if running:
        return "running", CONTINUE_MESSAGES["running"]
    if not script:
        return MISSING, CONTINUE_MESSAGES[MISSING]
    if script["state"] == INVALID:
        return INVALID, CONTINUE_MESSAGES[INVALID]
    if script["state"] == STALE:
        code = "mismatch" if script.get("stale_kind") == "mismatch" else STALE
        return code, CONTINUE_MESSAGES[code]
    return "", ""
