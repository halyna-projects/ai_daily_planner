from __future__ import annotations

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.ai.claude_client import TaskParser
from app.bot.keyboards import (
    clarify_due_date_keyboard,
    confirmation_keyboard,
    delete_only_keyboard,
    parse_clarify_callback,
    parse_reminder_callback,
    reminder_keyboard,
)
from app.bot.task_replies import create_task_and_build_reply
from app.db import async_session_factory
from app.models import TaskStatus
from app.services.tasks import delete_task, get_task, list_pending, list_today, mark_done, snooze

logger = logging.getLogger(__name__)
router = Router(name="planner")

_parser: TaskParser | None = None

# A task waiting on the user to pick which of several dates/times found in
# their message is the actual reminder time (see extract_ambiguous_candidates
# in app/ai/fallback.py). Keyed by telegram_user_id; lost on restart, which
# just means re-sending the message -- acceptable for a single-process bot.
_pending_clarifications: dict[int, tuple[str, list[tuple[datetime, str]]]] = {}


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
    "/new — покроково, календар і години замість набору тексту\n"
    "/today — список задач на сьогодні\n"
    "/tasks — всі активні задачі (можна видалити помилкові)\n"
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
        # Full date+time, not just the time -- /today also lists tasks
        # merely *created* today whose due_at can be a different day
        # entirely (see list_today), so a bare time would misleadingly
        # read as "today at this time".
        if task.recurrence_days:
            done_today = (
                task.completed_at is not None and task.completed_at.date() == now.date()
            )
            mark = "✅" if done_today else "🔁"
            due = f" (повторюється, до {task.due_at.strftime('%d.%m %H:%M')})" if task.due_at else " (повторюється)"
        else:
            mark = "✅" if task.status == TaskStatus.DONE else "⏳"
            due = f" (до {task.due_at.strftime('%d.%m %H:%M')})" if task.due_at else ""
        lines.append(f"{mark} {task.title}{due}")
    await message.answer("\n".join(lines))


async def _send_tasks_list(telegram_user_id: int, answer) -> None:
    async with async_session_factory() as session:
        tasks = await list_pending(session, telegram_user_id)

    if not tasks:
        await answer("Активних задач немає.")
        return

    await answer(f"Активних задач: {len(tasks)}. Щоб видалити помилкову — тисни 🗑 під нею.")
    for task in tasks:
        due = f"\nдо {task.due_at.strftime('%d.%m %H:%M')}" if task.due_at else ""
        cadence = " 🔁" if task.recurrence_days else ""
        await answer(f"{task.title}{due}{cadence}", reply_markup=delete_only_keyboard(task.id))


@router.message(Command("tasks"))
async def handle_tasks(message: Message) -> None:
    await _send_tasks_list(message.from_user.id, message.answer)


@router.callback_query(F.data == "menu:tasks")
async def handle_tasks_button(callback: CallbackQuery) -> None:
    await callback.answer()
    await _send_tasks_list(callback.from_user.id, callback.message.answer)


@router.message(F.text)
async def handle_new_task(message: Message) -> None:
    now = datetime.now()

    if not get_parser().is_live:
        from app.ai.fallback import extract_ambiguous_candidates

        candidates = extract_ambiguous_candidates(message.text, now)
        if candidates:
            _pending_clarifications[message.from_user.id] = (message.text, candidates)
            labels = [label for _, label in candidates]
            await message.answer(
                "Бачу в повідомленні кілька дат/часів і не хочу вгадати неправильно — "
                "яка з них час нагадування?",
                reply_markup=clarify_due_date_keyboard(labels),
            )
            return

    parsed = get_parser().parse(message.text, now)
    task_id, reply = await create_task_and_build_reply(
        message.from_user.id, parsed.title, parsed.due_at, parsed.recurrence_days, now
    )
    await message.answer(reply, reply_markup=confirmation_keyboard(task_id))
    logger.info("Created task %s for user %s", task_id, message.from_user.id)


@router.callback_query(F.data.startswith("clarify:"))
async def handle_clarify(callback: CallbackQuery) -> None:
    from app.ai.fallback import extract_recurrence_days

    idx = parse_clarify_callback(callback.data)
    pending = _pending_clarifications.pop(callback.from_user.id, None)
    if pending is None:
        await callback.answer("Час очікування вийшов, напиши задачу ще раз.")
        return

    text, candidates = pending
    if idx >= len(candidates):
        await callback.answer("Помилка.")
        return

    now = datetime.now()
    due_at, _ = candidates[idx]
    task_id, reply = await create_task_and_build_reply(
        callback.from_user.id, text.strip(), due_at, extract_recurrence_days(text), now
    )
    await callback.answer("Записано!")
    try:
        await callback.message.edit_text(reply, reply_markup=confirmation_keyboard(task_id))
    except Exception:
        logger.debug("Could not update clarification message", exc_info=True)
    logger.info("Created task %s for user %s (clarified)", task_id, callback.from_user.id)


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
        elif action == "delete":
            await delete_task(session, task)
            await session.commit()
            await callback.answer("Видалено 🗑")
            try:
                await callback.message.edit_text(f"{callback.message.text}\n\n🗑 Видалено", reply_markup=None)
            except Exception:
                logger.debug("Could not update reminder message", exc_info=True)
