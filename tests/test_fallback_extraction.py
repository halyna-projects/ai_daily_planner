from datetime import datetime

from app.ai.fallback import extract_due_at, extract_recurrence_days

NOW = datetime(2026, 10, 14, 10, 0, 0)  # a Wednesday


def test_no_deadline_mentioned():
    assert extract_due_at("Подзвонити сантехніку", NOW) is None


def test_tomorrow_with_time():
    due = extract_due_at("Подати документи в банк до завтра 15:00", NOW)
    assert due == datetime(2026, 10, 15, 15, 0)


def test_tomorrow_without_time_defaults_to_nine():
    due = extract_due_at("Зробити це завтра", NOW)
    assert due == datetime(2026, 10, 15, 9, 0)


def test_today_with_time():
    due = extract_due_at("Зробити звіт сьогодні о 18:30", NOW)
    assert due == datetime(2026, 10, 14, 18, 30)


def test_today_without_time_has_no_deadline():
    # "today" alone isn't a real deadline -- falls back to the default
    # reminder interval instead of inventing a time.
    assert extract_due_at("Зробити це сьогодні", NOW) is None


def test_relative_minutes():
    due = extract_due_at("Написати через 20 хв", NOW)
    assert due == datetime(2026, 10, 14, 10, 20)


def test_relative_hours():
    due = extract_due_at("Зустріч через 2 години", NOW)
    assert due == datetime(2026, 10, 14, 12, 0)


def test_bare_time_today_if_still_ahead():
    due = extract_due_at("Купити хліб о 14:00", NOW)
    assert due == datetime(2026, 10, 14, 14, 0)


def test_bare_time_rolls_to_tomorrow_if_already_passed():
    due = extract_due_at("Купити хліб о 09:00", NOW)
    assert due == datetime(2026, 10, 15, 9, 0)


def test_weekday_name_resolves_to_next_occurrence():
    due = extract_due_at("Зробити до п'ятниці", NOW)
    assert due == datetime(2026, 10, 16, 9, 0)
    assert due.weekday() == 4


def test_explicit_date_with_year_is_not_misread_as_a_time():
    # Regression: "11.11.2026" used to be matched by the bare HH:MM regex
    # as if it meant 11:11 today, silently discarding the actual date the
    # user typed (day 11, month 11, year 2026).
    due = extract_due_at(
        "перейти на Lebara до 11.11.2026 (mitid, jobnet, mobilepay=...)", NOW
    )
    assert due == datetime(2026, 11, 11, 9, 0)


def test_explicit_date_without_year_assumes_current_year():
    due = extract_due_at("Здати звіт до 20.12", NOW)
    assert due == datetime(2026, 12, 20, 9, 0)


def test_explicit_date_without_year_rolls_to_next_year_if_passed():
    due = extract_due_at("Привітати з днем народження 1.01", NOW)
    assert due == datetime(2027, 1, 1, 9, 0)


def test_explicit_date_with_time():
    due = extract_due_at("Зустріч 11.11.2026 о 14:30", NOW)
    assert due == datetime(2026, 11, 11, 14, 30)


def test_no_recurrence_mentioned():
    assert extract_recurrence_days("Подзвонити сантехніку") is None


def test_recurrence_daily_ukrainian():
    assert extract_recurrence_days("Випити таблетки, нагадувати щодня") == 1


def test_recurrence_daily_russian():
    # Regression: "напоминать ежедневно" used to be silently ignored,
    # leaving the task a one-off even though a repeat was explicitly asked.
    assert extract_recurrence_days("перейти на Lebara до 11.11.2026 - напоминать ежедневно") == 1


def test_recurrence_daily_ukrainian_adverbial_form():
    # Regression: the user wrote "щоденно" (not "щодня") and it was
    # silently ignored since only the "щодня" word form was recognized.
    due_text = "перейти на Lebara до 11.11.2026 - нагадувати щоденно"
    assert extract_recurrence_days(due_text) == 1


def test_recurrence_weekly():
    assert extract_recurrence_days("Прибирання, нагадувати щотижня") == 7


def test_recurrence_every_n_days():
    assert extract_recurrence_days("Поливати квіти кожні 3 дні") == 3


def test_recurrence_combines_with_explicit_date():
    due = extract_due_at(
        "перейти на Lebara до 11.11.2026 - напоминать ежедневно", NOW
    )
    assert due == datetime(2026, 11, 11, 9, 0)
    assert (
        extract_recurrence_days("перейти на Lebara до 11.11.2026 - напоминать ежедневно")
        == 1
    )
