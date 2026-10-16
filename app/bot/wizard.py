"""Step-by-step task creation via /new, for when a free-text message would
be ambiguous (several dates/times, or just a case where you'd rather fill in
fields one at a time -- the same idea as Reminders on iPhone: what / is it
repeating / when's the deadline / when to actually remind).

Recurrence is asked right after the title, before the deadline -- it used
to come last, which meant someone answering "щодня" out of habit as soon as
dates came up (at the "when to remind" step) got rejected as an
unparseable date. Asking it early means it's never competing with a
date/time question."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.ai.fallback import extract_due_at
from app.bot.keyboards import confirmation_keyboard
from app.bot.task_replies import create_task_and_build_reply

logger = logging.getLogger(__name__)
router = Router(name="new_task_wizard")

# A bare "09:00" typed at the "when to remind" step, with no date in it.
_BARE_TIME_RE = re.compile(r"^\s*([01]?\d|2[0-3]):([0-5]\d)\s*$")


class NewTaskForm(StatesGroup):
    title = State()
    recurrence_custom = State()
    deadline_custom = State()
    remind_custom = State()


def _recurrence_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Одноразово", callback_data="wiz:rec:none")],
        [InlineKeyboardButton(text="Щодня", callback_data="wiz:rec:daily")],
        [InlineKeyboardButton(text="Щотижня", callback_data="wiz:rec:weekly")],
        [InlineKeyboardButton(text="✏️ Свій інтервал (днів)", callback_data="wiz:rec:custom")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _deadline_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t, callback_data=f"wiz:time:{t}") for t in ("09:00", "15:00", "18:00")],
        [InlineKeyboardButton(text="Завтра 09:00", callback_data="wiz:tomorrow")],
        [InlineKeyboardButton(text="✏️ Написати дату і час", callback_data="wiz:deadline:custom")],
        [InlineKeyboardButton(text="Без дедлайну", callback_data="wiz:deadline:none")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _remind_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Точно в цей час", callback_data="wiz:remind:same")],
        [InlineKeyboardButton(text="За годину до", callback_data="wiz:remind:1h")],
        [InlineKeyboardButton(text="За день до", callback_data="wiz:remind:1d")],
        [InlineKeyboardButton(text="✏️ Вказати свій час", callback_data="wiz:remind:custom")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cadence_label(recurrence_days: int | None) -> str:
    if recurrence_days is None:
        return "Одноразово"
    if recurrence_days == 1:
        return "Щодня"
    if recurrence_days == 7:
        return "Щотижня"
    return f"Кожні {recurrence_days} дні(в)"


@router.message(Command("new"))
async def start_wizard(message: Message, state: FSMContext) -> None:
    await state.set_state(NewTaskForm.title)
    await message.answer("Що потрібно зробити?")


@router.callback_query(F.data == "wiz:new")
async def restart_wizard(callback: CallbackQuery, state: FSMContext) -> None:
    # Offered right under every "task created" confirmation, so adding the
    # next task doesn't mean scrolling up to find and retype /new.
    await state.set_state(NewTaskForm.title)
    await callback.answer()
    await callback.message.answer("Що потрібно зробити?")


@router.message(NewTaskForm.title, F.text)
async def got_title(message: Message, state: FSMContext) -> None:
    if message.text.startswith("/"):
        await message.answer("Спочатку заверши створення задачі (або почни заново: /new).")
        return

    await state.update_data(title=message.text.strip())
    await state.set_state(None)
    await message.answer("Це повторюване завдання?", reply_markup=_recurrence_keyboard())


@router.callback_query(F.data.startswith("wiz:rec:"))
async def got_recurrence_choice(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if "title" not in data:
        await callback.answer("Почни з /new.")
        return

    choice = callback.data.removeprefix("wiz:rec:")

    if choice == "custom":
        await state.set_state(NewTaskForm.recurrence_custom)
        await callback.message.edit_text("Через скільки днів повторювати? Напиши число, наприклад: 3.")
        await callback.answer()
        return

    recurrence_days = {"none": None, "daily": 1, "weekly": 7}[choice]
    await state.update_data(recurrence_days=recurrence_days)
    await callback.message.edit_text(_cadence_label(recurrence_days))
    await callback.answer()
    await message_ask_deadline(callback.message, state)


@router.message(NewTaskForm.recurrence_custom, F.text)
async def got_recurrence_custom(message: Message, state: FSMContext) -> None:
    if message.text.startswith("/"):
        await message.answer("Спочатку заверши створення задачі (або почни заново: /new).")
        return

    if not message.text.strip().isdigit():
        await message.answer("Напиши просто число днів, наприклад: 3.")
        return

    recurrence_days = int(message.text.strip())
    await state.update_data(recurrence_days=recurrence_days)
    await state.set_state(None)
    await message.answer(_cadence_label(recurrence_days))
    await message_ask_deadline(message, state)


async def message_ask_deadline(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("recurrence_days"):
        # A recurring task doesn't have a separate "deadline" concept --
        # this time just is the one it repeats at each cycle, so there's no
        # extra "when to remind relative to the deadline" question after it.
        await message.answer(
            "З якого дня і о котрій годині нагадувати (повторюватиметься щоразу о цій же годині)?",
            reply_markup=_deadline_keyboard(),
        )
    else:
        await message.answer("Коли дедлайн?", reply_markup=_deadline_keyboard())


@router.callback_query(
    F.data.startswith("wiz:time:") | F.data.startswith("wiz:tomorrow") | F.data.startswith("wiz:deadline:")
)
async def got_deadline_choice(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if "title" not in data:
        await callback.answer("Почни з /new.")
        return

    now = datetime.now()

    if callback.data == "wiz:deadline:none":
        await state.update_data(due_at=None)
        await callback.message.edit_text("Без дедлайну.")
        await callback.answer()
        await _finish(callback.message, state, callback.from_user.id)
        return
    elif callback.data == "wiz:deadline:custom":
        await state.set_state(NewTaskForm.deadline_custom)
        await callback.message.edit_text(
            "Напиши дату і час дедлайну, наприклад: 27.10.2026 21:00 (або просто 'завтра 15:00')."
        )
    elif callback.data == "wiz:tomorrow":
        due_at = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        await state.update_data(due_at=due_at.isoformat())
        if data.get("recurrence_days"):
            await _finish_recurring_at(callback.message.edit_text, state, due_at)
            await callback.answer()
            await _finish(callback.message, state, callback.from_user.id)
            return
        await callback.message.edit_text(f"Дедлайн: {due_at.strftime('%d.%m %H:%M')}.")
        await _ask_remind_offset(callback.message, state)
    else:
        _, _, time_str = callback.data.partition("wiz:time:")
        hour, minute = (int(x) for x in time_str.split(":"))
        due_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due_at <= now:
            due_at += timedelta(days=1)
        await state.update_data(due_at=due_at.isoformat())
        if data.get("recurrence_days"):
            await _finish_recurring_at(callback.message.edit_text, state, due_at)
            await callback.answer()
            await _finish(callback.message, state, callback.from_user.id)
            return
        await callback.message.edit_text(f"Дедлайн: {due_at.strftime('%d.%m %H:%M')}.")
        await _ask_remind_offset(callback.message, state)

    await callback.answer()


@router.message(NewTaskForm.deadline_custom, F.text)
async def got_deadline_custom(message: Message, state: FSMContext) -> None:
    if message.text.startswith("/"):
        await message.answer("Спочатку заверши створення задачі (або почни заново: /new).")
        return

    now = datetime.now()
    due_at = extract_due_at(message.text, now)
    if due_at is None:
        await message.answer("Не зрозумів дату/час, спробуй ще раз, наприклад: 27.10.2026 21:00.")
        return

    await state.update_data(due_at=due_at.isoformat())
    await state.set_state(None)

    data = await state.get_data()
    if data.get("recurrence_days"):
        await _finish_recurring_at(message.answer, state, due_at)
        await _finish(message, state, message.from_user.id)
        return

    await message.answer(f"Дедлайн: {due_at.strftime('%d.%m %H:%M')}.")
    await _ask_remind_offset(message, state)


async def _finish_recurring_at(announce, state: FSMContext, due_at: datetime) -> None:
    """A recurring task's chosen date/time IS its reminder time, repeating
    every cycle -- no separate "when to remind" offset makes sense here."""

    await state.update_data(remind_at=due_at.isoformat())
    data = await state.get_data()
    cadence = _cadence_label(data.get("recurrence_days")).lower()
    await announce(
        f"Нагадуватиму {cadence} о {due_at.strftime('%H:%M')}, починаючи з {due_at.strftime('%d.%m')}."
    )


async def _ask_remind_offset(message: Message, state: FSMContext) -> None:
    await message.answer("Коли нагадати?", reply_markup=_remind_keyboard())


@router.callback_query(F.data.startswith("wiz:remind:"))
async def got_remind_choice(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if "due_at" not in data:
        await callback.answer("Почни з /new.")
        return
    due_at = datetime.fromisoformat(data["due_at"])
    choice = callback.data.removeprefix("wiz:remind:")

    if choice == "same":
        await callback.message.edit_text(f"Нагадаю рівно о {due_at.strftime('%d.%m %H:%M')}.")
        await state.update_data(remind_at=due_at.isoformat())
        await callback.answer()
        await _finish(callback.message, state, callback.from_user.id)
        return
    elif choice == "1h":
        remind_at = due_at - timedelta(hours=1)
        await state.update_data(remind_at=remind_at.isoformat())
        await callback.message.edit_text(f"Нагадаю о {remind_at.strftime('%d.%m %H:%M')} (за годину до).")
        await callback.answer()
        await _finish(callback.message, state, callback.from_user.id)
        return
    elif choice == "1d":
        remind_at = due_at - timedelta(days=1)
        await state.update_data(remind_at=remind_at.isoformat())
        await callback.message.edit_text(f"Нагадаю о {remind_at.strftime('%d.%m %H:%M')} (за день до).")
        await callback.answer()
        await _finish(callback.message, state, callback.from_user.id)
        return
    else:
        await state.set_state(NewTaskForm.remind_custom)
        await callback.message.edit_text(
            f"Напиши дату і час, наприклад: 27.10.2026 21:00 -- або просто час "
            f"(наприклад 21:00), тоді це буде {due_at.strftime('%d.%m')}, в день дедлайну."
        )

    await callback.answer()


@router.message(NewTaskForm.remind_custom, F.text)
async def got_remind_custom(message: Message, state: FSMContext) -> None:
    if message.text.startswith("/"):
        await message.answer("Спочатку заверши створення задачі (або почни заново: /new).")
        return

    bare_time = _BARE_TIME_RE.match(message.text)
    if bare_time:
        # Just a time, no date -- apply it to the deadline's own date
        # (not "today/tomorrow relative to now", which would silently
        # ignore the deadline date already chosen earlier in the flow).
        data = await state.get_data()
        due_at = datetime.fromisoformat(data["due_at"])
        hour, minute = int(bare_time.group(1)), int(bare_time.group(2))
        remind_at = due_at.replace(hour=hour, minute=minute, second=0, microsecond=0)
    else:
        remind_at = extract_due_at(message.text, datetime.now())

    if remind_at is None:
        await message.answer("Не зрозумів, спробуй ще раз, наприклад: 27.10.2026 21:00.")
        return

    await state.update_data(remind_at=remind_at.isoformat())
    await state.set_state(None)
    await message.answer(f"Нагадаю о {remind_at.strftime('%d.%m %H:%M')}.")
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
