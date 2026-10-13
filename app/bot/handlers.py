from __future__ import annotations

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.ai.claude_client import TaskParser
from app.bot.keyboards import parse_reminder_callback, reminder_keyboard
from app.db import async_session_factory
from app.models import TaskStatus
from app.services.tasks import create_task, get_task, list_today, mark_done, snooze

logger = logging.getLogger(__name__)
router = Router(name="planner")

_parser: TaskParser | None = None


def get_parser() -> TaskParser:
    global _parser
    if _parser is None:
        _parser = TaskParser()
    return _parser


WELCOME = (
    "Привіт! 👋 Я — твій AI-планувальник.\n\n"
    "Просто напиши задачу звичайними словами, наприклад:\n"
    "«Подати документи в банк до завтра 15:00» або просто «Подзвонити сантехніку».\n\n"
    "Я сам зрозумію, що робити і коли, і буду нагадувати, поки ти не відміт"
    "иш задачу виконаною.\n\n"
    "Команди:\n"
    "/today — список задач на сьогодні\n"
    "/help — ця підказка"
)


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    await message.answer(WELCOME)


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    await message.answer(WELCOME)


@router.message(Command("today"))
async def handle_today(message: Message) -> None:
    now = datetime.now()
    async with async_session_factory() as session:
        tasks = await list_today(session, message.from_user.id, now)

    if not tasks:
        await message.answer("На сьогодні задач немає.")
        return

    lines = ["Задачі на сьогодні:"]
    for task in tasks:
        if task.recurrence_days:
            done_today = (
                task.completed_at is not None and task.completed_at.date() == now.date()
            )
            mark = "✅" if done_today else "🔁"
            due = f" (повторюється, до {task.due_at.strftime('%H:%M')})" if task.due_at else " (повторюється)"
        else:
            mark = "✅" if task.status == TaskStatus.DONE else "⏳"
            due = f" (до {task.due_at.strftime('%H:%M')})" if task.due_at else ""
        lines.append(f"{mark} {task.title}{due}")
    await message.answer("\n".join(lines))


@router.message(F.text)
async def handle_new_task(message: Message) -> None:
    now = datetime.now()
    parsed = get_parser().parse(message.text, now)

    async with async_session_factory() as session:
        task = await create_task(
            session,
            message.from_user.id,
            parsed.title,
            parsed.due_at,
            now,
            recurrence_days=parsed.recurrence_days,
        )
        await session.commit()
        task_id = task.id

    if parsed.due_at:
        reply = f"Записав! Нагадаю до {parsed.due_at.strftime('%d.%m %H:%M')}."
    else:
        reply = "Записав! Нагадуватиму регулярно, поки не відмітиш виконаним."

    if parsed.recurrence_days:
        cadence = "щодня" if parsed.recurrence_days == 1 else (
            "щотижня" if parsed.recurrence_days == 7 else f"кожні {parsed.recurrence_days} дні(в)"
        )
        reply += (
            f" Це повторюване завдання — нагадуватиму {cadence}: після «Виконано» "
            "воно не закриється, а повернеться на наступний раз."
        )

    await message.answer(reply)
    logger.info("Created task %s for user %s", task_id, message.from_user.id)


@router.callback_query(F.data.startswith("task:"))
async def handle_reminder_button(callback: CallbackQuery) -> None:
    task_id, action = parse_reminder_callback(callback.data)
    now = datetime.now()

    async with async_session_factory() as session:
        task = await get_task(session, task_id)
        if task is None:
            await callback.answer("Задачу не знайдено.")
            return

        if action == "done":
            was_recurring = bool(task.recurrence_days)
            await mark_done(session, task, now)
            await session.commit()
            if was_recurring:
                next_due = task.due_at.strftime("%d.%m %H:%M") if task.due_at else ""
                await callback.answer(f"Виконано ✅ Нагадаю знову {next_due}".rstrip())
                closing_note = f"\n\n✅ Виконано (повторю {next_due})" if next_due else "\n\n✅ Виконано"
            else:
                await callback.answer("Відмічено виконаним ✅")
                closing_note = "\n\n✅ Виконано"
            try:
                await callback.message.edit_text(
                    f"{callback.message.text}{closing_note}", reply_markup=None
                )
            except Exception:
                logger.debug("Could not update reminder message", exc_info=True)
        elif action == "not_yet":
            await session.commit()
            await callback.answer("Гаразд, нагадаю ще раз пізніше.")
        elif action == "snooze":
            await snooze(session, task, now)
            await session.commit()
            await callback.answer("Перенесено.")
