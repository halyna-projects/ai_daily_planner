from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Task, TaskStatus

settings = get_settings()


async def create_task(
    session: AsyncSession,
    telegram_user_id: int,
    title: str,
    due_at: datetime | None,
    now: datetime,
    recurrence_days: int | None = None,
) -> Task:
    """Create a pending task. Nagging starts at the deadline if one was
    given, otherwise immediately (now + the default interval) -- so a task
    with no due date starts getting reminders right away, same as the
    "крутилка" behavior that was asked for."""

    next_reminder_at = due_at if due_at else now + timedelta(
        minutes=settings.default_reminder_interval_minutes
    )

    task = Task(
        telegram_user_id=telegram_user_id,
        title=title,
        status=TaskStatus.PENDING,
        created_at=now,
        due_at=due_at,
        recurrence_days=recurrence_days,
        reminder_interval_minutes=settings.default_reminder_interval_minutes,
        next_reminder_at=next_reminder_at,
        reminder_count=0,
    )
    session.add(task)
    await session.flush()
    return task


async def get_task(session: AsyncSession, task_id: int) -> Task | None:
    result = await session.execute(select(Task).where(Task.id == task_id))
    return result.scalar_one_or_none()


async def mark_done(session: AsyncSession, task: Task, now: datetime) -> None:
    """Close a one-off task. A recurring task is never closed -- it's
    rescheduled forward by its cadence instead, so it keeps nagging on the
    next occurrence."""

    task.completed_at = now

    if task.recurrence_days:
        base = task.due_at or now
        next_due = base + timedelta(days=task.recurrence_days)
        while next_due <= now:
            next_due += timedelta(days=task.recurrence_days)
        task.due_at = next_due
        task.next_reminder_at = next_due
        task.reminder_count = 0
    else:
        task.status = TaskStatus.DONE

    await session.flush()


async def snooze(session: AsyncSession, task: Task, now: datetime) -> None:
    task.next_reminder_at = now + timedelta(minutes=settings.snooze_minutes)
    await session.flush()


async def register_reminder_sent(session: AsyncSession, task: Task, now: datetime) -> bool:
    """Call right after a reminder message is actually sent: bumps the nag
    count and schedules the next one. Returns True if this reminder should
    use the escalated tone."""

    task.reminder_count += 1
    task.next_reminder_at = now + timedelta(minutes=task.reminder_interval_minutes)
    await session.flush()
    return task.reminder_count >= settings.escalation_threshold


async def list_due_reminders(session: AsyncSession, now: datetime) -> list[Task]:
    result = await session.execute(
        select(Task).where(Task.status == TaskStatus.PENDING, Task.next_reminder_at <= now)
    )
    return list(result.scalars().all())


async def list_today(session: AsyncSession, telegram_user_id: int, now: datetime) -> list[Task]:
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    result = await session.execute(
        select(Task)
        .where(Task.telegram_user_id == telegram_user_id)
        .where(
            (Task.created_at >= start_of_day)
            | ((Task.due_at >= start_of_day) & (Task.due_at < end_of_day))
        )
        .order_by(Task.status, Task.due_at.is_(None), Task.due_at, Task.created_at)
    )
    return list(result.scalars().all())
