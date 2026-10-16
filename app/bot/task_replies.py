"""Shared "write/update the task, build the confirmation text" step used
by the free-text handler and the step-by-step /new wizard (both the
create and the edit path), so every entry point confirms back to the
user in the same way."""

from __future__ import annotations

from datetime import datetime

from app.db import async_session_factory
from app.services.tasks import create_task, get_task, update_task


def _build_reply(due_at: datetime | None, recurrence_days: int | None, prefix: str) -> str:
    if due_at:
        reply = f"{prefix} Нагадаю до {due_at.strftime('%d.%m %H:%M')}."
    else:
        reply = f"{prefix} Нагадуватиму регулярно, поки не відмітиш виконаним."

    if recurrence_days:
        cadence = "щодня" if recurrence_days == 1 else (
            "щотижня" if recurrence_days == 7 else f"кожні {recurrence_days} дні(в)"
        )
        reply += (
            f" Це повторюване завдання — нагадуватиму {cadence}: після «Виконано» "
            "воно не закриється, а повернеться на наступний раз."
        )

    return reply


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

    return task_id, _build_reply(due_at, recurrence_days, "Записав!")


async def update_task_and_build_reply(
    task_id: int,
    title: str,
    due_at: datetime | None,
    recurrence_days: int | None,
    now: datetime,
) -> tuple[int, str] | None:
    """Returns None if the task no longer exists (deleted mid-edit)."""

    async with async_session_factory() as session:
        task = await get_task(session, task_id)
        if task is None:
            return None
        await update_task(session, task, title, due_at, recurrence_days, now)
        await session.commit()

    return task_id, _build_reply(due_at, recurrence_days, "Оновив!")
