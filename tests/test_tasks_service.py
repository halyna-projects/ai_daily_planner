from datetime import datetime, timedelta

import pytest

from app.config import get_settings
from app.models import TaskStatus
from app.services.tasks import (
    create_task,
    delete_all_tasks,
    delete_task,
    get_task,
    list_all_tasks,
    list_due_reminders,
    list_pending,
    list_today,
    mark_done,
    register_reminder_sent,
    snooze,
    update_task,
)

NOW = datetime(2026, 10, 14, 10, 0, 0)


@pytest.mark.asyncio
async def test_task_with_due_date_is_not_nagged_before_it(session):
    due = NOW + timedelta(hours=5)
    task = await create_task(session, telegram_user_id=1, title="Подати звіт", due_at=due, now=NOW)
    await session.commit()

    assert task.next_reminder_at == due
    due_now = await list_due_reminders(session, NOW)
    assert task not in due_now


@pytest.mark.asyncio
async def test_task_without_due_date_schedules_default_interval(session):
    task = await create_task(session, telegram_user_id=1, title="Подзвонити", due_at=None, now=NOW)
    await session.commit()

    settings = get_settings()
    expected = NOW + timedelta(minutes=settings.default_reminder_interval_minutes)
    assert task.next_reminder_at == expected


@pytest.mark.asyncio
async def test_due_reminder_is_picked_up_once_its_time_has_come(session):
    due = NOW - timedelta(minutes=1)
    task = await create_task(session, telegram_user_id=1, title="Подати звіт", due_at=due, now=NOW - timedelta(hours=1))
    await session.commit()

    due_now = await list_due_reminders(session, NOW)
    assert [t.id for t in due_now] == [task.id]


@pytest.mark.asyncio
async def test_mark_done_removes_task_from_due_list(session):
    due = NOW - timedelta(minutes=1)
    task = await create_task(session, telegram_user_id=1, title="Подати звіт", due_at=due, now=NOW - timedelta(hours=1))
    await mark_done(session, task, NOW)
    await session.commit()

    due_now = await list_due_reminders(session, NOW)
    assert task not in due_now
    assert task.status == TaskStatus.DONE
    assert task.completed_at == NOW


@pytest.mark.asyncio
async def test_mark_done_on_recurring_task_reschedules_instead_of_closing(session):
    due = NOW.replace(hour=9, minute=0)
    task = await create_task(
        session,
        telegram_user_id=1,
        title="Випити таблетки",
        due_at=due,
        now=NOW - timedelta(days=1),
        recurrence_days=1,
    )
    await register_reminder_sent(session, task, due)
    await mark_done(session, task, NOW)
    await session.commit()

    assert task.status == TaskStatus.PENDING
    assert task.completed_at == NOW
    assert task.due_at == due + timedelta(days=1)
    assert task.next_reminder_at == due + timedelta(days=1)
    assert task.reminder_count == 0


@pytest.mark.asyncio
async def test_mark_done_on_recurring_task_without_due_date_uses_now(session):
    task = await create_task(
        session,
        telegram_user_id=1,
        title="Пити воду",
        due_at=None,
        now=NOW,
        recurrence_days=1,
    )
    await mark_done(session, task, NOW)
    await session.commit()

    assert task.status == TaskStatus.PENDING
    assert task.due_at == NOW + timedelta(days=1)


@pytest.mark.asyncio
async def test_register_reminder_sent_reschedules_and_counts(session):
    task = await create_task(session, telegram_user_id=1, title="Подзвонити", due_at=None, now=NOW)
    await session.commit()

    escalated = await register_reminder_sent(session, task, NOW)
    await session.commit()

    assert task.reminder_count == 1
    assert escalated is False
    assert task.next_reminder_at == NOW + timedelta(minutes=task.reminder_interval_minutes)


@pytest.mark.asyncio
async def test_escalation_kicks_in_after_threshold(session):
    # Regression: a task ignored over and over should eventually get a
    # different tone, not the same gentle nudge forever.
    task = await create_task(session, telegram_user_id=1, title="Подзвонити", due_at=None, now=NOW)
    await session.commit()

    settings = get_settings()
    escalated = False
    for i in range(settings.escalation_threshold):
        escalated = await register_reminder_sent(session, task, NOW + timedelta(minutes=i))
    await session.commit()

    assert task.reminder_count == settings.escalation_threshold
    assert escalated is True


@pytest.mark.asyncio
async def test_snooze_pushes_next_reminder_without_marking_done(session):
    task = await create_task(session, telegram_user_id=1, title="Подзвонити", due_at=None, now=NOW)
    await session.commit()

    await snooze(session, task, NOW)
    await session.commit()

    settings = get_settings()
    assert task.status == TaskStatus.PENDING
    assert task.next_reminder_at == NOW + timedelta(minutes=settings.snooze_minutes)


@pytest.mark.asyncio
async def test_list_today_includes_tasks_created_today_and_due_today(session):
    created_today = await create_task(
        session, telegram_user_id=1, title="Купити хліб", due_at=None, now=NOW
    )
    due_today_only = await create_task(
        session,
        telegram_user_id=1,
        title="Здати документи",
        due_at=NOW.replace(hour=18, minute=0),
        now=NOW - timedelta(days=3),
    )
    unrelated_day = await create_task(
        session,
        telegram_user_id=1,
        title="Щось інше",
        due_at=NOW + timedelta(days=5),
        now=NOW - timedelta(days=10),
    )
    await session.commit()

    today = await list_today(session, telegram_user_id=1, now=NOW)
    ids = {t.id for t in today}

    assert created_today.id in ids
    assert due_today_only.id in ids
    assert unrelated_day.id not in ids


@pytest.mark.asyncio
async def test_list_today_only_returns_the_requesting_users_tasks(session):
    await create_task(session, telegram_user_id=1, title="Мій таск", due_at=None, now=NOW)
    await create_task(session, telegram_user_id=2, title="Чужий таск", due_at=None, now=NOW)
    await session.commit()

    today = await list_today(session, telegram_user_id=1, now=NOW)
    assert [t.title for t in today] == ["Мій таск"]


@pytest.mark.asyncio
async def test_delete_task_removes_it_entirely(session):
    task = await create_task(session, telegram_user_id=1, title="Поповнити П", due_at=None, now=NOW)
    await session.commit()
    task_id = task.id

    await delete_task(session, task)
    await session.commit()

    assert await get_task(session, task_id) is None


@pytest.mark.asyncio
async def test_list_pending_only_returns_open_tasks_for_that_user(session):
    open_task = await create_task(session, telegram_user_id=1, title="Відкрита", due_at=None, now=NOW)
    done_task = await create_task(session, telegram_user_id=1, title="Закрита", due_at=None, now=NOW)
    await mark_done(session, done_task, NOW)
    other_user_task = await create_task(session, telegram_user_id=2, title="Чужа", due_at=None, now=NOW)
    await session.commit()

    pending = await list_pending(session, telegram_user_id=1)

    assert [t.id for t in pending] == [open_task.id]


@pytest.mark.asyncio
async def test_delete_all_tasks_wipes_pending_and_done_for_that_user_only(session):
    open_task = await create_task(session, telegram_user_id=1, title="Відкрита", due_at=None, now=NOW)
    done_task = await create_task(session, telegram_user_id=1, title="Закрита", due_at=None, now=NOW)
    await mark_done(session, done_task, NOW)
    other_user_task = await create_task(session, telegram_user_id=2, title="Чужа", due_at=None, now=NOW)
    await session.commit()

    deleted_count = await delete_all_tasks(session, telegram_user_id=1)
    await session.commit()

    assert deleted_count == 2
    assert await get_task(session, open_task.id) is None
    assert await get_task(session, done_task.id) is None
    assert await get_task(session, other_user_task.id) is not None


@pytest.mark.asyncio
async def test_update_task_changes_fields_and_resets_nag_state(session):
    task = await create_task(session, telegram_user_id=1, title="Старе", due_at=None, now=NOW)
    await register_reminder_sent(session, task, NOW)
    await session.commit()
    assert task.reminder_count == 1

    new_due = NOW + timedelta(days=3)
    await update_task(session, task, "Нове", new_due, recurrence_days=7, now=NOW)
    await session.commit()

    assert task.title == "Нове"
    assert task.due_at == new_due
    assert task.recurrence_days == 7
    assert task.next_reminder_at == new_due
    assert task.reminder_count == 0


@pytest.mark.asyncio
async def test_update_task_reopens_a_done_task(session):
    task = await create_task(session, telegram_user_id=1, title="Закрита", due_at=None, now=NOW)
    await mark_done(session, task, NOW)
    await session.commit()
    assert task.status == TaskStatus.DONE

    await update_task(session, task, "Закрита", NOW + timedelta(days=1), recurrence_days=None, now=NOW)
    await session.commit()

    assert task.status == TaskStatus.PENDING
    assert task.completed_at is None


@pytest.mark.asyncio
async def test_list_all_tasks_returns_every_user_and_status(session):
    pending = await create_task(session, telegram_user_id=1, title="Моя відкрита", due_at=None, now=NOW)
    done = await create_task(session, telegram_user_id=1, title="Моя закрита", due_at=None, now=NOW)
    await mark_done(session, done, NOW)
    other_user = await create_task(session, telegram_user_id=2, title="Чужа", due_at=None, now=NOW)
    await session.commit()

    tasks = await list_all_tasks(session)

    assert {t.id for t in tasks} == {pending.id, done.id, other_user.id}
