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
# An explicit day.month[.year] date, e.g. "11.11.2026", "5.03" or "28/10/2026"
# (both '.' and '/' separators are in the wild). Checked before anything
# else, since it's the most unambiguous signal in the message and must win
# over any dot that could be misread as a time.
_DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")
# A message can carry two dates that mean different things -- the event
# itself and a separate "remind me on this day" instruction, e.g. "28/10 -
# Лікар о 10:30 - нагадати 27.10 о 21:00". A word like this right before a
# date marks that date as the one to actually schedule the reminder by.
_REMIND_KEYWORD_RE = re.compile(r"нагад|напомн|\bremind", re.IGNORECASE)
_IN_MINUTES_RE = re.compile(r"через\s+(\d+)\s*хв", re.IGNORECASE)
_IN_HOURS_RE = re.compile(r"через\s+(\d+)\s*(?:год|годин)", re.IGNORECASE)
_TODAY_RE = re.compile(r"сьогодні", re.IGNORECASE)
_TOMORROW_RE = re.compile(r"завтра", re.IGNORECASE)

# An explicit repeat cadence mentioned in the message itself, e.g.
# "нагадувати щодня" / "напоминать ежедневно" / "every day" -- checked
# separately from the deadline, since a message can carry both ("до
# 11.11.2026 - нагадувати щодня" means: repeat daily around that date).
_EVERY_N_DAYS_RE = re.compile(r"кожні?\s+(\d+)\s*дн", re.IGNORECASE)
_DAILY_RE = re.compile(
    r"щодня|щоденн|кожного дня|кожен день|ежедневно|каждый день|\bdaily\b|every day",
    re.IGNORECASE,
)
_WEEKLY_RE = re.compile(
    r"щотижня|щотижнев|кожного тижня|кожен тиждень|еженедельно|каждую неделю|\bweekly\b|every week",
    re.IGNORECASE,
)


def _extract_time(text: str) -> tuple[int, int] | None:
    match = _TIME_RE.search(text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _find_date_candidates(text: str, now: datetime) -> list[tuple[datetime, int]]:
    """Every explicit date in the message, each paired with the time that
    most plausibly belongs to it: the first explicit HH:MM found after that
    date and before the next one (so "28/10 о 10:30 - нагадати 27.10 о
    21:00" pairs each date with its own time, not the first time found
    anywhere in the text). Returns (datetime, date_match_start_index) pairs
    -- the index lets callers check what word immediately precedes a date."""

    date_matches = list(_DATE_RE.finditer(text))
    if not date_matches:
        return []

    time_matches = list(_TIME_RE.finditer(text))
    assigned_time: dict[int, tuple[int, int]] = {}
    for time_match in time_matches:
        owner = None
        for i, date_match in enumerate(date_matches):
            if date_match.start() < time_match.start():
                owner = i
            else:
                break
        if owner is not None and owner not in assigned_time:
            assigned_time[owner] = (int(time_match.group(1)), int(time_match.group(2)))

    candidates: list[tuple[datetime, int]] = []
    for i, match in enumerate(date_matches):
        day, month = int(match.group(1)), int(match.group(2))
        year_raw = match.group(3)
        if year_raw:
            year = int(year_raw)
            if year < 100:
                year += 2000
        else:
            year = now.year

        hour, minute = assigned_time.get(i, (9, 0))
        try:
            candidate = datetime(year, month, day, hour, minute)
        except ValueError:
            continue

        if not year_raw and candidate <= now:
            candidate = candidate.replace(year=year + 1)
        candidates.append((candidate, match.start()))

    return candidates


def _is_reminder_marked(text: str, date_start: int) -> bool:
    window = text[max(0, date_start - 25) : date_start]
    return bool(_REMIND_KEYWORD_RE.search(window))


def _extract_explicit_date(text: str, now: datetime) -> datetime | None:
    candidates = _find_date_candidates(text, now)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][0]

    marked = [dt for dt, start in candidates if _is_reminder_marked(text, start)]
    if len(marked) == 1:
        return marked[0]

    # Genuinely ambiguous (0 or 2+ dates explicitly marked as "remind me on
    # this one") -- best-effort fall back to the first date mentioned.
    # extract_ambiguous_candidates() is what callers should check first to
    # ask the user instead of silently guessing here.
    return candidates[0][0]


def extract_ambiguous_candidates(text: str, now: datetime) -> list[tuple[datetime, str]] | None:
    """When a message mentions multiple explicit dates and it isn't clear
    which one is the actual reminder time (no single date is marked with a
    "нагадати/напомни/remind"-type word), return the candidates so the
    caller can ask the user to pick instead of guessing wrong. Returns None
    when there's nothing to ask about -- 0 or 1 dates, or exactly one is
    already unambiguously marked."""

    candidates = _find_date_candidates(text, now)
    if len(candidates) < 2:
        return None

    marked = [dt for dt, start in candidates if _is_reminder_marked(text, start)]
    if len(marked) == 1:
        return None

    return [(dt, dt.strftime("%d.%m %H:%M")) for dt, _ in candidates]


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


def extract_recurrence_days(text: str) -> int | None:
    """Pull an explicit repeat cadence out of free text, as a day interval
    (1 = daily, 7 = weekly). Returns None for a one-off task with no
    repeating cadence mentioned."""

    every_n = _EVERY_N_DAYS_RE.search(text)
    if every_n:
        return int(every_n.group(1))

    if _DAILY_RE.search(text):
        return 1

    if _WEEKLY_RE.search(text):
        return 7

    return None
