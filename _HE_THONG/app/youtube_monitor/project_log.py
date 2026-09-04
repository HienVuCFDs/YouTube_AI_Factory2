"""One chronological account of what happened to a project.

Everything here is already recorded - a job knows when it started, when it
finished and how it failed; a publication knows where it went; the ledger
knows what was paid. What did not exist was a single place to read them in
order, so answering "why is this project stuck" meant opening four panels and
comparing timestamps by eye, and reopening the app lost the thread entirely.

Nothing new is stored. The log is assembled from the rows that were already
there, which is also why it survives a restart: there was never anything in
memory to lose.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# The order production actually happens in, used to group the log rather than
# to enforce anything - a project may legitimately revisit a stage.
STAGES: tuple[str, ...] = ("nguồn", "kịch bản", "giọng đọc", "cảnh", "dựng", "xuất bản")

_JOB_STAGE = {
    "voiceover": "giọng đọc",
    "voiceover_segment": "giọng đọc",
    "voice_preview": "giọng đọc",
    "source_visuals": "cảnh",
    "render": "dựng",
    "render_short": "dựng",
    "premiere_draft": "dựng",
    "director_production": "dựng",
}

_JOB_LABEL = {
    "voiceover": "Tạo giọng đọc",
    "voiceover_segment": "Tạo giọng một cảnh",
    "voice_preview": "Nghe thử giọng",
    "source_visuals": "Cắt cảnh từ video gốc",
    "render": "Dựng video",
    "render_short": "Dựng Short",
    "premiere_draft": "Xuất bản nháp Premiere",
    "director_production": "AI Đạo diễn dựng cả chuỗi",
}


def _moment(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _elapsed(start: Any, end: Any) -> float | None:
    """Seconds a step took, when both ends are known."""
    began, ended = _moment(start), _moment(end)
    if not began or not ended:
        return None
    return round(max(0.0, (ended - began).total_seconds()), 1)


def _entry(
    when: Any, stage: str, label: str, status: str, **extra: Any
) -> dict[str, Any]:
    return {"at": str(when or ""), "stage": stage, "label": label, "status": status, **extra}


def build(
    *,
    project: dict[str, Any],
    source_video: dict[str, Any] | None,
    scripts: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    publications: list[dict[str, Any]],
    cost_usd: float = 0.0,
) -> dict[str, Any]:
    """The project's whole history, newest last, with what each step cost."""
    entries: list[dict[str, Any]] = []
    source_video = source_video or {}

    if str(source_video.get("local_media_path") or "").strip():
        entries.append(_entry(
            source_video.get("last_metadata_sync_at") or project.get("created_at"),
            "nguồn", "Tải video nguồn về máy", "completed",
            detail=str(source_video.get("media_kind") or "") or "chưa rõ loại",
        ))

    for script in scripts:
        variant = "Short" if str(script.get("variant") or "long") == "short" else "Video dài"
        entries.append(_entry(
            script.get("created_at"), "kịch bản",
            f"Viết kịch bản · {variant} · v{script.get('version')}",
            str(script.get("status") or "draft"),
            detail=str(script.get("script_title") or "")[:120],
        ))

    # A job that was run again after failing is the thing a log is for, so
    # repeats are counted rather than collapsed.
    attempts: dict[str, int] = {}
    for job in sorted(jobs, key=lambda item: str(item.get("created_at") or "")):
        job_type = str(job.get("job_type") or "")
        attempts[job_type] = attempts.get(job_type, 0) + 1
        entries.append(_entry(
            job.get("created_at"),
            _JOB_STAGE.get(job_type, "dựng"),
            _JOB_LABEL.get(job_type, job_type),
            str(job.get("status") or ""),
            job_id=job.get("id"),
            provider=str(job.get("provider") or ""),
            attempt=attempts[job_type],
            seconds=_elapsed(job.get("started_at"), job.get("completed_at")),
            error=str(job.get("error") or "")[:400],
            output_path=str(job.get("output_path") or ""),
        ))

    for publication in publications:
        entries.append(_entry(
            publication.get("created_at"), "xuất bản",
            f"Đăng {publication.get('platform') or 'youtube'} · "
            f"{'Short' if publication.get('video_variant') == 'short' else 'Video dài'}",
            str(publication.get("status") or ""),
            error=str(publication.get("error") or "")[:400],
            detail=str(publication.get("title") or "")[:120],
        ))

    entries.sort(key=lambda item: str(item.get("at") or ""))

    failed = [item for item in entries if item["status"] == "error"]
    retried = sorted({
        item["label"] for item in entries if int(item.get("attempt") or 0) > 1
    })
    spent = sum(float(item.get("seconds") or 0) for item in entries)

    return {
        "entries": entries,
        "stages": list(STAGES),
        "summary": {
            "steps": len(entries),
            "failures": len(failed),
            "retried_steps": retried,
            "machine_seconds": round(spent, 1),
            "cost_usd": round(float(cost_usd or 0), 4),
            "last_error": (failed[-1]["error"] if failed else ""),
            "last_at": entries[-1]["at"] if entries else "",
        },
    }


def stage_status(log: dict[str, Any]) -> dict[str, str]:
    """Where each stage stands, for a strip that can be read at a glance."""
    result = {stage: "" for stage in STAGES}
    for entry in log.get("entries") or []:
        stage = entry.get("stage")
        if stage not in result:
            continue
        status = str(entry.get("status") or "")
        # A later success clears an earlier failure: the log keeps both, but
        # the strip is about where the project is now.
        if status in {"completed", "approved"}:
            result[stage] = "completed"
        elif status == "error" and result[stage] != "completed":
            result[stage] = "error"
        elif not result[stage]:
            result[stage] = status
    return result
