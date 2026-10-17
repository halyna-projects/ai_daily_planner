"""Step-by-step task creation via /new -- a fixed, standard field set
(deadline date+time, reminder date+time, repeat type), entered entirely by
tapping: a calendar grid for any date, an hour grid then a minute grid for
any time. No typed date/time format examples anywhere in this flow -- that
was the whole problem with the earlier free-text version of /new. Plain
free-text messages outside /new are unaffected.

Every screen carries a "⬅️ Назад" button to the screen before it, so a
mis-tap doesn't mean restarting the whole wizard with /new."""

from __future__ import annotations

import calendar as calendar_module
import logging
from datetime import datetime, timedelta
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.keyboards import confirmation_keyboard
from app.bot.task_replies import create_task_and_build_reply, update_task_and_build_reply
from app.db import async_session_factory
from app.services.tasks import get_task

logger = logging.getLogger(__name__)
router = Router(name="new_task_wizard")

_MONTH_NAMES = [
    "Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень",
    "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень",
]
_WEEKDAY_LABELS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд")

# Which back-target an hour/minute screen points to, keyed by the current
# `phase` -- derived purely from phase, since the hour/minute grids
# themselves are generic and don't otherwise know how they were reached.
_HOUR_BACK_TARGET = {"deadline": "deadline_date", "reminder": "reminder_date", "remind_time_only": "remind_type"}
_MINUTE_BACK_TARGET = {"deadline": "deadline_hour", "reminder": "reminder_hour", "remind_time_only": "remind_time_hour"}


class NewTaskForm(StatesGroup):
    title = State()
    recurrence_custom = State()


def _back_button(target: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back:{target}")


def _remind_type_keyboard(with_date_option: bool, back_target: str) -> InlineKeyboardMarkup:
    """The "when to remind" step doubles as the repeat-type question: pick
    a cadence directly (reuses the deadline's own time, no separate date
    to enter), or -- only when there's a deadline to diverge from -- a
    one-off reminder on its own date/time."""

    rows = [
        [InlineKeyboardButton(text="Щодня", callback_data="remind:rec:daily")],
        [InlineKeyboardButton(text="Щотижня", callback_data="remind:rec:weekly")],
        [InlineKeyboardButton(text="Щомісяця", callback_data="remind:rec:monthly")],
        [
            InlineKeyboardButton(text="2 дні", callback_data="remind:rec:2"),
            InlineKeyboardButton(text="3 дні", callback_data="remind:rec:3"),
            InlineKeyboardButton(text="14 днів", callback_data="remind:rec:14"),
        ],
        [InlineKeyboardButton(text="✏️ Інше число днів", callback_data="remind:rec:custom")],
    ]
    if with_date_option:
        rows.append([InlineKeyboardButton(text="📌 У дату дедлайну", callback_data="remind:same")])
        rows.append([InlineKeyboardButton(text="📅 Інша дата і час (одноразово)", callback_data="remind:custom_datetime")])
    else:
        rows.append([InlineKeyboardButton(text="Одноразово", callback_data="remind:none")])
    rows.append([_back_button(back_target)])
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
    year: int,
    month: int,
    extra_button: Optional[tuple[str, str]] = None,
    back_target: Optional[str] = None,
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

    if back_target:
        rows.append([_back_button(back_target)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _hour_keyboard(back_target: str) -> InlineKeyboardMarkup:
    hours = list(range(24))
    rows = [
        [InlineKeyboardButton(text=f"{h:02d}", callback_data=f"hr:{h}") for h in hours[i : i + 6]]
        for i in range(0, 24, 6)
    ]
    rows.append([_back_button(back_target)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _minute_keyboard(back_target: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f":{m:02d}", callback_data=f"mi:{m}") for m in (0, 15, 30, 45)]]
    rows.append([_back_button(back_target)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _recurrence_custom_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_back_button("remind_type")]])


async def _extra_button_for_phase(state: FSMContext) -> Optional[tuple[str, str]]:
    data = await state.get_data()
    if data.get("phase") == "reminder":
        return None
    return ("Без дедлайну", "deadline:none")


def _calendar_start(data: dict) -> tuple[int, int]:
    """Default the calendar to the deadline's own month when there is one,
    since that's the most likely month someone picking a reminder date
    actually wants."""

    due_at_raw = data.get("due_at")
    if due_at_raw:
        due_at = datetime.fromisoformat(due_at_raw)
        return due_at.year, due_at.month
    now = datetime.now()
    return now.year, now.month


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


@router.callback_query(F.data.startswith("edit:"))
async def start_edit(callback: CallbackQuery, state: FSMContext) -> None:
    # Re-runs the task through the exact same deadline/cadence questions
    # as /new, ending in an update instead of a new task -- the title
    # itself is kept as-is (fixing a typo there is what the plain 🗑
    # delete-and-resend already covers).
    task_id = int(callback.data.removeprefix("edit:"))
    async with async_session_factory() as session:
        task = await get_task(session, task_id)
    if task is None:
        await callback.answer("Задачу не знайдено.")
        return

    await state.update_data(title=task.title, phase="deadline", editing_task_id=task_id)
    await state.set_state(None)
    await callback.answer()
    now = datetime.now()
    await callback.message.answer(
        f"Редагую «{task.title}». Дата дедлайну:",
        reply_markup=_calendar_keyboard(now.year, now.month, extra_button=("Без дедлайну", "deadline:none")),
    )


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
    await callback.message.edit_text("Без дедлайну.")
    await callback.answer()
    await callback.message.answer(
        "Коли нагадати?", reply_markup=_remind_type_keyboard(with_date_option=False, back_target="deadline_date")
    )


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
        phase = data.get("phase", "deadline")
        back_target = "remind_type" if phase == "reminder" else None
        await callback.message.edit_reply_markup(
            reply_markup=_calendar_keyboard(year, month, extra, back_target)
        )
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
    await callback.message.edit_text(
        f"Дата: {friendly_date}. Обери годину:", reply_markup=_hour_keyboard(_HOUR_BACK_TARGET[phase])
    )


@router.callback_query(F.data.startswith("hr:"))
async def got_hour_choice(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if "title" not in data:
        await callback.answer("Почни з /new.")
        return

    hour = int(callback.data.removeprefix("hr:"))
    await state.update_data(picked_hour=hour)
    await callback.answer()
    phase = data.get("phase", "deadline")
    await callback.message.edit_text(
        f"Година: {hour:02d}. Обери хвилини:", reply_markup=_minute_keyboard(_MINUTE_BACK_TARGET[phase])
    )


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
        await state.update_data(due_at=due_at.isoformat())
        await callback.message.edit_text(f"Дедлайн: {due_at.strftime('%d.%m %H:%M')}.")
        await callback.message.answer(
            "Коли нагадати?",
            reply_markup=_remind_type_keyboard(with_date_option=True, back_target="deadline_minute"),
        )
    elif phase == "remind_time_only":
        # Daily/weekly: just a time, no date -- starts at the nearest
        # upcoming occurrence of that time and repeats from there.
        now = datetime.now()
        remind_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if remind_at <= now:
            remind_at += timedelta(days=1)
        await state.update_data(remind_at=remind_at.isoformat())
        cadence = _cadence_label(data.get("recurrence_days"))
        await callback.message.edit_text(
            f"{cadence}, о {remind_at.strftime('%H:%M')} (починаючи з {remind_at.strftime('%d.%m')})."
        )
        await _finish(callback.message, state, callback.from_user.id)
    else:
        # "reminder" phase: a full date+time -- either a genuine one-off
        # reminder, or the starting date for a monthly/custom-days cadence
        # (those matter enough to ask, unlike daily/weekly).
        year, month, day = (int(x) for x in data["reminder_date"].split("-"))
        remind_at = datetime(year, month, day, hour, minute)
        await state.update_data(remind_at=remind_at.isoformat())
        recurrence_days = data.get("recurrence_days")
        if recurrence_days:
            cadence = _cadence_label(recurrence_days)
            await callback.message.edit_text(f"{cadence}, починаючи з {remind_at.strftime('%d.%m %H:%M')}.")
        else:
            await callback.message.edit_text(f"Нагадаю: {remind_at.strftime('%d.%m %H:%M')}.")
        await _finish(callback.message, state, callback.from_user.id)


@router.callback_query(F.data == "remind:none")
async def got_remind_none(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if "title" not in data:
        await callback.answer("Почни з /new.")
        return

    await callback.message.edit_text("Одноразово.")
    await callback.answer()
    await _finish(callback.message, state, callback.from_user.id)


@router.callback_query(F.data == "remind:same")
async def got_remind_same(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if "due_at" not in data or not data["due_at"]:
        await callback.answer("Почни з /new.")
        return

    due_at = datetime.fromisoformat(data["due_at"])
    await state.update_data(remind_at=due_at.isoformat())
    await callback.message.edit_text(f"Нагадаю: {due_at.strftime('%d.%m %H:%M')} (у дату дедлайну).")
    await callback.answer()
    await _finish(callback.message, state, callback.from_user.id)


@router.callback_query(F.data == "remind:custom_datetime")
async def got_remind_custom_datetime(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if "due_at" not in data or not data["due_at"]:
        await callback.answer("Почни з /new.")
        return

    await state.update_data(phase="reminder")
    await callback.answer()
    year, month = _calendar_start(data)
    await callback.message.edit_text(
        "Дата нагадування:", reply_markup=_calendar_keyboard(year, month, back_target="remind_type")
    )


@router.callback_query(F.data.startswith("remind:rec:"))
async def got_remind_recurrence(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if "title" not in data:
        await callback.answer("Почни з /new.")
        return

    choice = callback.data.removeprefix("remind:rec:")

    if choice == "custom":
        await state.set_state(NewTaskForm.recurrence_custom)
        await callback.message.edit_text(
            "Через скільки днів повторювати? Напиши число.", reply_markup=_recurrence_custom_keyboard()
        )
        await callback.answer()
        return

    preset = {"daily": 1, "weekly": 7, "monthly": 30}
    recurrence_days = preset[choice] if choice in preset else int(choice)
    await callback.answer()
    await _ask_cadence_time(callback.message, state, recurrence_days)


@router.message(NewTaskForm.recurrence_custom, F.text)
async def got_recurrence_custom(message: Message, state: FSMContext) -> None:
    if message.text.startswith("/"):
        await message.answer("Спочатку заверши створення задачі (або почни заново: /new).")
        return

    if not message.text.strip().isdigit():
        await message.answer("Напиши просто число днів, наприклад: 5.", reply_markup=_recurrence_custom_keyboard())
        return

    recurrence_days = int(message.text.strip())
    await state.set_state(None)
    await _ask_cadence_time(message, state, recurrence_days)


async def _ask_cadence_time(message: Message, state: FSMContext, recurrence_days: int) -> None:
    """Daily/weekly only need a time (it starts ASAP and repeats from
    there); longer cadences (monthly, a custom day count) ask for a full
    date too, since the specific starting day matters more at that scale."""

    cadence = _cadence_label(recurrence_days)
    await state.update_data(recurrence_days=recurrence_days)

    if recurrence_days in (1, 7):
        await state.update_data(phase="remind_time_only")
        await message.answer(f"{cadence}. Обери годину:", reply_markup=_hour_keyboard("remind_type"))
    else:
        await state.update_data(phase="reminder")
        data = await state.get_data()
        year, month = _calendar_start(data)
        await message.answer(
            f"{cadence}. Обери дату:", reply_markup=_calendar_keyboard(year, month, back_target="remind_type")
        )


@router.callback_query(F.data.startswith("back:"))
async def got_back(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if "title" not in data:
        await callback.answer("Почни з /new.")
        return

    target = callback.data.removeprefix("back:")
    await callback.answer()
    await state.set_state(None)

    if target == "deadline_date":
        await state.update_data(phase="deadline")
        now = datetime.now()
        year, month = now.year, now.month
        if data.get("deadline_date"):
            y, m, _d = (int(x) for x in data["deadline_date"].split("-"))
            year, month = y, m
        await callback.message.edit_text(
            "Дата дедлайну:",
            reply_markup=_calendar_keyboard(year, month, extra_button=("Без дедлайну", "deadline:none")),
        )
    elif target == "deadline_hour":
        await state.update_data(phase="deadline")
        await callback.message.edit_text("Обери годину:", reply_markup=_hour_keyboard("deadline_date"))
    elif target == "deadline_minute":
        await state.update_data(phase="deadline")
        hour = data.get("picked_hour", 0)
        await callback.message.edit_text(
            f"Година: {hour:02d}. Обери хвилини:", reply_markup=_minute_keyboard("deadline_hour")
        )
    elif target == "remind_type":
        with_date = bool(data.get("due_at"))
        back_target = "deadline_minute" if with_date else "deadline_date"
        await callback.message.edit_text(
            "Коли нагадати?", reply_markup=_remind_type_keyboard(with_date_option=with_date, back_target=back_target)
        )
    elif target == "reminder_date":
        await state.update_data(phase="reminder")
        year, month = _calendar_start(data)
        if data.get("reminder_date"):
            y, m, _d = (int(x) for x in data["reminder_date"].split("-"))
            year, month = y, m
        await callback.message.edit_text(
            "Дата нагадування:", reply_markup=_calendar_keyboard(year, month, back_target="remind_type")
        )
    elif target == "reminder_hour":
        await state.update_data(phase="reminder")
        await callback.message.edit_text("Обери годину:", reply_markup=_hour_keyboard("reminder_date"))
    elif target == "remind_time_hour":
        await state.update_data(phase="remind_time_only")
        await callback.message.edit_text("Обери годину:", reply_markup=_hour_keyboard("remind_type"))


async def _finish(message: Message, state: FSMContext, telegram_user_id: int) -> None:
    data = await state.get_data()
    title = data["title"]
    recurrence_days = data.get("recurrence_days")
    due_at_raw = data.get("due_at")
    remind_at_raw = data.get("remind_at")
    editing_task_id = data.get("editing_task_id")

    due_at = datetime.fromisoformat(remind_at_raw) if remind_at_raw else (
        datetime.fromisoformat(due_at_raw) if due_at_raw else None
    )

    await state.clear()
    now = datetime.now()

    if editing_task_id:
        result = await update_task_and_build_reply(editing_task_id, title, due_at, recurrence_days, now)
        if result is None:
            await message.answer("Цю задачу вже видалено — редагування скасовано.")
            return
        task_id, reply = result
    else:
        task_id, reply = await create_task_and_build_reply(telegram_user_id, title, due_at, recurrence_days, now)

    await message.answer(reply, reply_markup=confirmation_keyboard(task_id))
    action = "edited" if editing_task_id else "created"
    logger.info("%s task %s for user %s (wizard)", action, task_id, telegram_user_id)
