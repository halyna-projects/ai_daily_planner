"""Step-by-step task creation via /new -- a fixed, standard field set
(deadline date+time, reminder date+time, repeat type), entered entirely by
tapping: a calendar grid for any date, an hour grid then a minute grid for
any time. No typed date/time format examples anywhere in this flow -- that
was the whole problem with the earlier free-text version of /new. Plain
free-text messages outside /new are unaffected."""

from __future__ import annotations

import calendar as calendar_module
import logging
from datetime import datetime
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.keyboards import confirmation_keyboard
from app.bot.task_replies import create_task_and_build_reply

logger = logging.getLogger(__name__)
router = Router(name="new_task_wizard")

_MONTH_NAMES = [
    "Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень",
    "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень",
]
_WEEKDAY_LABELS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд")


class NewTaskForm(StatesGroup):
    title = State()
    recurrence_custom = State()


def _recurrence_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Одноразово", callback_data="wiz:rec:none")],
        [InlineKeyboardButton(text="Щодня", callback_data="wiz:rec:daily")],
        [InlineKeyboardButton(text="Щотижня", callback_data="wiz:rec:weekly")],
        [InlineKeyboardButton(text="Щомісяця", callback_data="wiz:rec:monthly")],
        [
            InlineKeyboardButton(text="2 дні", callback_data="wiz:rec:2"),
            InlineKeyboardButton(text="3 дні", callback_data="wiz:rec:3"),
            InlineKeyboardButton(text="14 днів", callback_data="wiz:rec:14"),
        ],
        [InlineKeyboardButton(text="✏️ Інше число днів", callback_data="wiz:rec:custom")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cadence_label(recurrence_days: int | None) -> str:
    if recurrence_days is None:
        return "Одноразово"
    if recurrence_days == 1:
        return "Щодня"
    if recurrence_days == 7:
        return "Щотижня"
    if recurrence_days == 30:
        return "Щомісяця"
    return f"Кожні {recurrence_days} дні(в)"


def _calendar_keyboard(
    year: int, month: int, extra_button: Optional[tuple[str, str]] = None
) -> InlineKeyboardMarkup:
    cal = calendar_module.Calendar(firstweekday=0)
    weeks = cal.monthdayscalendar(year, month)

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)

    rows = []
    if extra_button:
        text, callback_data = extra_button
        rows.append([InlineKeyboardButton(text=text, callback_data=callback_data)])

    rows.append([
        InlineKeyboardButton(text="◀", callback_data=f"cal:nav:{prev_year:04d}-{prev_month:02d}"),
        InlineKeyboardButton(text=f"{_MONTH_NAMES[month - 1]} {year}", callback_data="cal:noop"),
        InlineKeyboardButton(text="▶", callback_data=f"cal:nav:{next_year:04d}-{next_month:02d}"),
    ])
    rows.append([InlineKeyboardButton(text=d, callback_data="cal:noop") for d in _WEEKDAY_LABELS])

    for week in weeks:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="cal:noop"))
            else:
                row.append(
                    InlineKeyboardButton(
                        text=str(day), callback_data=f"cal:pick:{year:04d}-{month:02d}-{day:02d}"
                    )
                )
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _hour_keyboard() -> InlineKeyboardMarkup:
    hours = list(range(24))
    rows = [
        [InlineKeyboardButton(text=f"{h:02d}", callback_data=f"hr:{h}") for h in hours[i : i + 6]]
        for i in range(0, 24, 6)
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _minute_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f":{m:02d}", callback_data=f"mi:{m}") for m in (0, 15, 30, 45)]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _extra_button_for_phase(state: FSMContext) -> Optional[tuple[str, str]]:
    data = await state.get_data()
    if data.get("phase") == "reminder":
        return ("📌 Так само, як дедлайн", "reminder:same_as_deadline")
    return ("Без дедлайну", "deadline:none")


_TITLE_PROMPT = "Введи завдання до виконання:"


@router.message(Command("new"))
async def start_wizard(message: Message, state: FSMContext) -> None:
    await state.set_state(NewTaskForm.title)
    await message.answer(_TITLE_PROMPT)


@router.callback_query(F.data == "wiz:new")
async def restart_wizard(callback: CallbackQuery, state: FSMContext) -> None:
    # Offered right under every "task created" confirmation, so adding the
    # next task doesn't mean scrolling up to find and retype /new.
    await state.set_state(NewTaskForm.title)
    await callback.answer()
    await callback.message.answer(_TITLE_PROMPT)


@router.message(NewTaskForm.title, F.text)
async def got_title(message: Message, state: FSMContext) -> None:
    if message.text.startswith("/"):
        await message.answer("Спочатку заверши створення задачі (або почни заново: /new).")
        return

    await state.update_data(title=message.text.strip(), phase="deadline")
    await state.set_state(None)
    now = datetime.now()
    await message.answer(
        "Дата дедлайну:",
        reply_markup=_calendar_keyboard(now.year, now.month, extra_button=("Без дедлайну", "deadline:none")),
    )


@router.callback_query(F.data == "deadline:none")
async def got_no_deadline(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if "title" not in data:
        await callback.answer("Почни з /new.")
        return

    await state.update_data(due_at=None, remind_at=None)
    await callback.message.edit_text("Без дедлайну і без конкретного часу нагадування.")
    await callback.answer()
    await callback.message.answer("Тип повторення:", reply_markup=_recurrence_keyboard())


@router.callback_query(F.data == "reminder:same_as_deadline")
async def got_reminder_same_as_deadline(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if "due_at" not in data or not data["due_at"]:
        await callback.answer("Почни з /new.")
        return

    due_at = datetime.fromisoformat(data["due_at"])
    await state.update_data(remind_at=due_at.isoformat())
    await callback.message.edit_text(f"Нагадаю: {due_at.strftime('%d.%m %H:%M')} (так само, як дедлайн).")
    await callback.answer()
    await callback.message.answer("Тип повторення:", reply_markup=_recurrence_keyboard())


@router.callback_query(F.data.startswith("cal:"))
async def got_calendar_action(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if "title" not in data:
        await callback.answer("Почни з /new.")
        return

    action = callback.data.removeprefix("cal:")

    if action == "noop":
        await callback.answer()
        return

    if action.startswith("nav:"):
        year, month = (int(x) for x in action.removeprefix("nav:").split("-"))
        extra = await _extra_button_for_phase(state)
        await callback.message.edit_reply_markup(reply_markup=_calendar_keyboard(year, month, extra))
        await callback.answer()
        return

    date_str = action.removeprefix("pick:")
    year, month, day = (int(x) for x in date_str.split("-"))
    friendly_date = f"{day:02d}.{month:02d}.{year:04d}"

    phase = data.get("phase", "deadline")
    if phase == "deadline":
        await state.update_data(deadline_date=date_str)
    else:
        await state.update_data(reminder_date=date_str)
    await callback.answer()
    await callback.message.edit_text(f"Дата: {friendly_date}. Обери годину:", reply_markup=_hour_keyboard())


@router.callback_query(F.data.startswith("hr:"))
async def got_hour_choice(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if "title" not in data:
        await callback.answer("Почни з /new.")
        return

    hour = int(callback.data.removeprefix("hr:"))
    await state.update_data(picked_hour=hour)
    await callback.answer()
    await callback.message.edit_text(f"Година: {hour:02d}. Обери хвилини:", reply_markup=_minute_keyboard())


@router.callback_query(F.data.startswith("mi:"))
async def got_minute_choice(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if "title" not in data or "picked_hour" not in data:
        await callback.answer("Почни з /new.")
        return

    minute = int(callback.data.removeprefix("mi:"))
    hour = data["picked_hour"]
    phase = data.get("phase", "deadline")
    await callback.answer()

    if phase == "deadline":
        year, month, day = (int(x) for x in data["deadline_date"].split("-"))
        due_at = datetime(year, month, day, hour, minute)
        await state.update_data(due_at=due_at.isoformat(), phase="reminder")
        await callback.message.edit_text(f"Дедлайн: {due_at.strftime('%d.%m %H:%M')}.")
        await callback.message.answer(
            "Дата нагадування:",
            reply_markup=_calendar_keyboard(
                due_at.year, due_at.month, extra_button=("📌 Так само, як дедлайн", "reminder:same_as_deadline")
            ),
        )
    else:
        year, month, day = (int(x) for x in data["reminder_date"].split("-"))
        remind_at = datetime(year, month, day, hour, minute)
        await state.update_data(remind_at=remind_at.isoformat())
        await callback.message.edit_text(f"Нагадаю: {remind_at.strftime('%d.%m %H:%M')}.")
        await callback.message.answer("Тип повторення:", reply_markup=_recurrence_keyboard())


@router.callback_query(F.data.startswith("wiz:rec:"))
async def got_recurrence_choice(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if "title" not in data:
        await callback.answer("Почни з /new.")
        return

    choice = callback.data.removeprefix("wiz:rec:")

    if choice == "custom":
        await state.set_state(NewTaskForm.recurrence_custom)
        await callback.message.edit_text("Через скільки днів повторювати? Напиши число.")
        await callback.answer()
        return

    preset = {"none": None, "daily": 1, "weekly": 7, "monthly": 30}
    recurrence_days = preset[choice] if choice in preset else int(choice)
    await state.update_data(recurrence_days=recurrence_days)
    await callback.message.edit_text(_cadence_label(recurrence_days))
    await callback.answer()
    await _finish(callback.message, state, callback.from_user.id)


@router.message(NewTaskForm.recurrence_custom, F.text)
async def got_recurrence_custom(message: Message, state: FSMContext) -> None:
    if message.text.startswith("/"):
        await message.answer("Спочатку заверши створення задачі (або почни заново: /new).")
        return

    if not message.text.strip().isdigit():
        await message.answer("Напиши просто число днів, наприклад: 5.")
        return

    recurrence_days = int(message.text.strip())
    await state.update_data(recurrence_days=recurrence_days)
    await state.set_state(None)
    await message.answer(_cadence_label(recurrence_days))
    await _finish(message, state, message.from_user.id)


async def _finish(message: Message, state: FSMContext, telegram_user_id: int) -> None:
    data = await state.get_data()
    title = data["title"]
    recurrence_days = data.get("recurrence_days")
    due_at_raw = data.get("due_at")
    remind_at_raw = data.get("remind_at")

    due_at = datetime.fromisoformat(remind_at_raw) if remind_at_raw else (
        datetime.fromisoformat(due_at_raw) if due_at_raw else None
    )

    await state.clear()
    now = datetime.now()
    task_id, reply = await create_task_and_build_reply(telegram_user_id, title, due_at, recurrence_days, now)
    await message.answer(reply, reply_markup=confirmation_keyboard(task_id))
    logger.info("Created task %s for user %s (wizard)", task_id, telegram_user_id)
