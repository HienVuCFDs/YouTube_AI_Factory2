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

# Phrases that mean the account is out, not that the call went wrong.
_LIMIT_PHRASES = (
    "hit your usage limit",
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
    r"(?:reset|try again|thử lại|quay lại)\s*(?:in|after|sau)\s+"
    r"(?P<amount>\d{1,3})\s*(?P<unit>hours?|hrs?|h|minutes?|mins?|m|giờ|phút|ngày|days?)",
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
    return None


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
