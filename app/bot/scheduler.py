from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram import Bot

from app.bot.keyboards import reminder_keyboard
from app.config import get_settings
from app.db import async_session_factory
from app.services.tasks import list_due_reminders, register_reminder_sent

logger = logging.getLogger(__name__)
settings = get_settings()

_ESCALATED_PREFIXES = [
    "Це вже нагадування №{n} — точно все гаразд?",
    "Знову не зроблено ({n}-й раз). Може, перенести чи скасувати?",
]


def _reminder_text(title: str, reminder_count: int, escalated: bool) -> str:
    if escalated:
        prefix = _ESCALATED_PREFIXES[reminder_count % len(_ESCALATED_PREFIXES)]
        return f"{prefix.format(n=reminder_count)}\n\n🔔 {title}"
    return f"🔔 Нагадування: {title}"


async def run_reminder_loop(bot: Bot) -> None:
    """Background task: every `scheduler_poll_seconds`, find pending tasks
    whose next_reminder_at has passed and nag the user again -- the
    "крутилка" that keeps returning to an unfinished item instead of firing
    once and forgetting."""

    while True:
        try:
            await _tick(bot)
        except Exception:
            logger.exception("Reminder loop tick failed")
        await asyncio.sleep(settings.scheduler_poll_seconds)


async def _tick(bot: Bot) -> None:
    now = datetime.now()
    async with async_session_factory() as session:
        due = await list_due_reminders(session, now)
        for task in due:
            escalated = await register_reminder_sent(session, task, now)
            try:
                await bot.send_message(
                    task.telegram_user_id,
                    _reminder_text(task.title, task.reminder_count, escalated),
                    reply_markup=reminder_keyboard(task.id),
                )
            except Exception:
                logger.exception("Failed to send reminder for task %s", task.id)
        await session.commit()
