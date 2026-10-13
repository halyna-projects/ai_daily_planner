"""A minimal rule-based stand-in for the Claude due-date extractor.

Used when ANTHROPIC_API_KEY is not configured, so the bot stays testable
end-to-end without a live key. It intentionally keeps the task's title as
the full original message -- only the due date/time is parsed out of it --
so a bad regex match never mangles what the user actually asked to be
reminded about.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

# Stems rather than exact words, since Ukrainian declines the weekday name
# depending on the sentence ("до п'ятниці", "у п'ятницю", "п'ятниця").
_WEEKDAY_STEMS = [
    ("понеділ", 0),
    ("вівтор", 1),
    ("серед", 2),
    ("четвер", 3),
    ("п'ятниц", 4),
    ("субот", 5),
    ("неділ", 6),
]

# Colon only -- a dot here used to also match "11.11" inside a date like
# "11.11.2026" as if it were the time 11:11, silently discarding the actual
# date the user typed.
_TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
# An explicit day.month[.year] date, e.g. "11.11.2026" or "5.03". Checked
# before anything else, since it's the most unambiguous signal in the
# message and must win over any dot that could be misread as a time.
_DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b")
_IN_MINUTES_RE = re.compile(r"через\s+(\d+)\s*хв", re.IGNORECASE)
_IN_HOURS_RE = re.compile(r"через\s+(\d+)\s*(?:год|годин)", re.IGNORECASE)
_TODAY_RE = re.compile(r"сьогодні", re.IGNORECASE)
_TOMORROW_RE = re.compile(r"завтра", re.IGNORECASE)


def _extract_time(text: str) -> tuple[int, int] | None:
    match = _TIME_RE.search(text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _extract_explicit_date(text: str, now: datetime) -> datetime | None:
    match = _DATE_RE.search(text)
    if not match:
        return None

    day, month = int(match.group(1)), int(match.group(2))
    year_raw = match.group(3)
    if year_raw:
        year = int(year_raw)
        if year < 100:
            year += 2000
    else:
        year = now.year

    hour, minute = _extract_time(text) or (9, 0)
    try:
        candidate = datetime(year, month, day, hour, minute)
    except ValueError:
        return None

    # No year given and the date already passed this year -- assume next year.
    if not year_raw and candidate <= now:
        candidate = candidate.replace(year=year + 1)
    return candidate


def extract_due_at(text: str, now: datetime) -> datetime | None:
    """Pull a due date/time out of free text, relative to `now`. Returns
    None when no deadline is mentioned -- the task then just uses the
    default reminder interval starting immediately."""

    explicit_date = _extract_explicit_date(text, now)
    if explicit_date:
        return explicit_date

    minutes_match = _IN_MINUTES_RE.search(text)
    if minutes_match:
        return now + timedelta(minutes=int(minutes_match.group(1)))

    hours_match = _IN_HOURS_RE.search(text)
    if hours_match:
        return now + timedelta(hours=int(hours_match.group(1)))

    time_of_day = _extract_time(text)

    if _TOMORROW_RE.search(text):
        base = now + timedelta(days=1)
        hour, minute = time_of_day or (9, 0)
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if _TODAY_RE.search(text):
        if time_of_day is None:
            return None
        hour, minute = time_of_day
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    lowered = text.lower()
    for stem, weekday in _WEEKDAY_STEMS:
        if stem in lowered:
            days_ahead = (weekday - now.weekday()) % 7
            days_ahead = days_ahead or 7
            base = now + timedelta(days=days_ahead)
            hour, minute = time_of_day or (9, 0)
            return base.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if time_of_day is not None:
        hour, minute = time_of_day
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    return None
