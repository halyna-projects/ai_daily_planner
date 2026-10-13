"""Shared "create the task, build the confirmation text" step used by both
the free-text handler and the step-by-step /new wizard, so the two entry
points always confirm back to the user in the same way."""

from __future__ import annotations

from datetime import datetime

from app.db import async_session_factory
from app.services.tasks import create_task


async def create_task_and_build_reply(
    telegram_user_id: int,
    title: str,
    due_at: datetime | None,
    recurrence_days: int | None,
    now: datetime,
) -> tuple[int, str]:
    async with async_session_factory() as session:
        task = await create_task(
            session, telegram_user_id, title, due_at, now, recurrence_days=recurrence_days
        )
        await session.commit()
        task_id = task.id

    if due_at:
        reply = f"Записав! Нагадаю до {due_at.strftime('%d.%m %H:%M')}."
    else:
        reply = "Записав! Нагадуватиму регулярно, поки не відмітиш виконаним."

    if recurrence_days:
        cadence = "щодня" if recurrence_days == 1 else (
            "щотижня" if recurrence_days == 7 else f"кожні {recurrence_days} дні(в)"
        )
        reply += (
            f" Це повторюване завдання — нагадуватиму {cadence}: після «Виконано» "
            "воно не закриється, а повернеться на наступний раз."
        )

    return task_id, reply
