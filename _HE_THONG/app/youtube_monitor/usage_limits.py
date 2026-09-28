"""Recognise "you are out of quota" among ordinary failures, and say when.

Every paid model in this app is reached through a subscription rather than a
metered key, so running out is a normal weekly event, not a bug. The app used
to treat it as one more provider error: the message went into a job row, the
orchestrator quietly fell back to another agent, and nothing on screen ever
said which model had stopped working or when it would come back. A whole
session was spent here believing Codex CLI was broken when it was simply out
of quota until a date its own error message stated.

Each provider phrases it differently, so the phrases live together in one
place rather than being re-guessed at each call site.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Phrases that mean the account is out, not that the call went wrong.
_LIMIT_PHRASES = (
    "hit your usage limit",
    "hit your weekly limit",
    "weekly usage limit",
    "usage limit reached",
    "usage limit exceeded",
    "rate limit",
    "quota reached",
    "quota exceeded",
    "exceeded your current quota",
    "individual quota reached",
    "insufficient credit",
    "out of credit",
    "resource_exhausted",
    "resource exhausted",
    "too many requests",
    "hết hạn mức",
    "hết quota",
    "hết tín dụng",
    "không đủ tín dụng",
    "vượt quá hạn mức",
)

# "try again at Aug 27th, 2026 9:43 PM" - the Codex CLI wording.
_RESET_AT = re.compile(
    r"try again (?:at|on)\s+"
    r"(?P<month>[A-Z][a-z]{2})[a-z]*\.?\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+"
    r"(?P<year>\d{4})"
    r"(?:\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<meridiem>[AaPp][Mm])?)?",
)
# "reset in 4 hours", "thử lại sau 30 phút"
_RESET_IN = re.compile(
    r"(?:resets?|try again|thử lại|quay lại)\s*(?:in|after|sau)\s+"
    r"(?P<amount>\d{1,3})\s*(?P<unit>hours?|hrs?|h|minutes?|mins?|m|giờ|phút|ngày|days?)",
    re.IGNORECASE,
)
_RESET_CLOCK = re.compile(
    r"(?:resets?\s+|try again at\s+)(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<meridiem>[AaPp][Mm])"
    r"(?:\s*\((?P<zone>[^)]+)\))?",
    re.IGNORECASE,
)

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_UNIT_SECONDS = {
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600, "giờ": 3600,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60, "phút": 60,
    "day": 86400, "days": 86400, "ngày": 86400,
}


def _normalize(text: str) -> str:
    """Fold case and Vietnamese tone marks.

    The same condition reaches this code both ways: some layers report
    "hết tín dụng" and others, written to survive a Windows console, report
    "het tin dung". Matching both is cheaper than keeping the two spellings
    of every phrase in step.
    """
    decomposed = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char)).replace("đ", "d")


_NORMALIZED_PHRASES = tuple(_normalize(phrase) for phrase in _LIMIT_PHRASES)


def is_usage_limit(message: str) -> bool:
    """Whether this failure means the account is out rather than broken."""
    normalized = _normalize(message)
    return any(phrase in normalized for phrase in _NORMALIZED_PHRASES)


def parse_reset_at(message: str, *, now: datetime | None = None) -> datetime | None:
    """When the provider says the quota returns, if it says so at all.

    Returned in UTC. Providers state a wall-clock time without a zone, so it
    is read as local time and converted - being an hour out is far better than
    having no idea when the model comes back.
    """
    text = message or ""
    moment = now or datetime.now(timezone.utc)

    absolute = _RESET_AT.search(text)
    if absolute:
        month = _MONTHS.get(absolute.group("month").lower())
        if month:
            hour = int(absolute.group("hour") or 0)
            meridiem = (absolute.group("meridiem") or "").lower()
            if meridiem == "pm" and hour < 12:
                hour += 12
            elif meridiem == "am" and hour == 12:
                hour = 0
            try:
                naive = datetime(
                    int(absolute.group("year")), month, int(absolute.group("day")),
                    hour, int(absolute.group("minute") or 0),
                )
            except ValueError:
                return None
            return naive.astimezone().astimezone(timezone.utc)

    relative = _RESET_IN.search(text)
    if relative:
        seconds = _UNIT_SECONDS.get(relative.group("unit").lower())
        if seconds:
            return moment + timedelta(seconds=int(relative.group("amount")) * seconds)
    clock = _RESET_CLOCK.search(text)
    if clock:
        hour = int(clock.group("hour"))
        meridiem = clock.group("meridiem").lower()
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        try:
            zone = ZoneInfo(clock.group("zone") or "Asia/Bangkok")
        except ZoneInfoNotFoundError:
            zone = moment.astimezone().tzinfo or timezone.utc
        local_now = moment.astimezone(zone)
        reset = local_now.replace(
            hour=hour,
            minute=int(clock.group("minute") or 0),
            second=0,
            microsecond=0,
        )
        if reset <= local_now:
            reset += timedelta(days=1)
        return reset.astimezone(timezone.utc)
    return None


# How long a recorded outage keeps a runtime out before it is tried again. The
# provider's own reset time is honoured when it comes sooner. When it is later,
# or was never stated, the runtime is still probed after this: stated reset
# times have been wrong (Antigravity ran again two days before "its" reset), and
# a runtime nobody is allowed to call can never prove it has recovered.
PROBE_COOLDOWN = timedelta(hours=6)


def _moment(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def limit_state(row: dict | None, *, now: datetime | None = None) -> dict:
    """What one stored outage means right now - the only place that decides it.

    Readiness, the task worker, the provider catalog and the warning banner
    each used to read the same row their own way, so one said a model was out
    while another was calling it. States:

    - "none": nothing recorded;
    - "recovered": a call succeeded since (history, not blocking);
    - "reset_passed": the stated reset time is behind us (history, not blocking);
    - "probe_due": still unconfirmed, but the cooldown is over - try it (not blocking);
    - "active": out now; `retry_at` says when it will be tried again (blocking).
    """
    if not row:
        return {"state": "none", "blocking": False, "retry_at": None}
    if row.get("cleared_at"):
        return {"state": "recovered", "blocking": False, "retry_at": None}
    moment = now or datetime.now(timezone.utc)
    resets = _moment(row.get("resets_at"))
    if resets and resets <= moment:
        return {"state": "reset_passed", "blocking": False, "retry_at": None}
    last = _moment(row.get("last_failure_at") or row.get("detected_at"))
    # With no time of failure there is no way to tell how old the outage is,
    # so it stays in force until a reset time or a success says otherwise.
    probe_at = (last + PROBE_COOLDOWN) if last else None
    candidates = [when for when in (resets, probe_at) if when is not None]
    if not candidates:
        return {"state": "active", "blocking": True, "retry_at": None}
    retry_at = min(candidates)
    if retry_at <= moment:
        return {"state": "probe_due", "blocking": False, "retry_at": None}
    return {"state": "active", "blocking": True, "retry_at": retry_at.isoformat()}


def describe(message: str) -> str:
    """The one line worth showing, pulled out of a multi-page error."""
    for line in (message or "").splitlines():
        cleaned = line.strip().lstrip("ERROR:").strip()
        if cleaned and is_usage_limit(cleaned):
            return cleaned[:300]
    return (message or "").strip()[:300]


# The bridges that see these failures sit below the database layer, so the
# recorder is injected from main.py rather than imported here - the same
# arrangement the scene worker uses for its prompt crafter.
_recorder: Callable[[str, str, str | None], None] | None = None
_clearer: Callable[[str], None] | None = None


def set_sink(
    record: Callable[[str, str, str | None], None] | None,
    clear: Callable[[str], None] | None = None,
) -> None:
    """Tell this module where to write what it notices."""
    global _recorder, _clearer
    _recorder = record
    _clearer = clear


def note_failure(provider: str, message: str) -> bool:
    """Record a failure if it means the account is out. Returns whether it did.

    Callers keep raising their own error afterwards: this only makes the
    reason visible, it does not change what happens to the call.
    """
    if not is_usage_limit(message):
        return False
    if _recorder is None:
        return True
    reset = parse_reset_at(message)
    try:
        _recorder(provider, describe(message), reset.isoformat() if reset else None)
    except Exception:
        # Never let bookkeeping turn a provider outage into a crash.
        return True
    return True


def note_success(provider: str) -> None:
    """A call went through, so any recorded outage for it is over."""
    if _clearer is None:
        return
    try:
        _clearer(provider)
    except Exception:
        pass
