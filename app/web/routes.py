from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_factory
from app.models import TaskStatus
from app.services.tasks import delete_task, get_task, list_all_tasks, mark_done, update_task
from app.web.auth import require_admin

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")

_FILTERS = ("all", "today", "overdue", "recurring", "done")


async def get_session() -> AsyncSession:
    async with async_session_factory() as session:
        yield session


def _cadence_label(recurrence_days: int | None) -> str:
    if recurrence_days is None:
        return ""
    if recurrence_days == 1:
        return "Щодня"
    if recurrence_days == 7:
        return "Щотижня"
    if recurrence_days == 30:
        return "Щомісяця"
    return f"Кожні {recurrence_days} дні(в)"


@router.get("/")
async def dashboard(
    request: Request,
    filter: str = "all",
    q: str = "",
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_admin),
):
    if filter not in _FILTERS:
        filter = "all"

    now = datetime.now()
    all_tasks = await list_all_tasks(session)

    def matches(t, f: str) -> bool:
        if f == "today":
            return t.due_at is not None and t.due_at.date() == now.date()
        if f == "overdue":
            return t.status == TaskStatus.PENDING and t.due_at is not None and t.due_at < now
        if f == "recurring":
            return t.recurrence_days is not None
        if f == "done":
            return t.status == TaskStatus.DONE
        return True

    counts = {f: sum(1 for t in all_tasks if matches(t, f)) for f in _FILTERS}

    tasks = [t for t in all_tasks if matches(t, filter)]
    if q:
        needle = q.strip().lower()
        tasks = [t for t in tasks if needle in t.title.lower()]

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "tasks": tasks,
            "filter": filter,
            "q": q,
            "counts": counts,
            "now": now,
            "cadence_label": _cadence_label,
        },
    )


@router.get("/tasks/{task_id}")
async def task_detail(
    task_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_admin),
):
    task = await get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задачу не знайдено")

    return templates.TemplateResponse(
        "task_detail.html",
        {"request": request, "task": task, "cadence_label": _cadence_label},
    )


@router.post("/tasks/{task_id}")
async def update_task_route(
    task_id: int,
    title: str = Form(...),
    due_at: str = Form(default=""),
    recurrence_days: str = Form(default=""),
    recurrence_days_custom: str = Form(default=""),
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_admin),
):
    task = await get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задачу не знайдено")

    due_at_parsed = datetime.fromisoformat(due_at) if due_at else None
    if recurrence_days_custom.strip():
        recurrence_parsed = int(recurrence_days_custom.strip())
    elif recurrence_days.strip():
        recurrence_parsed = int(recurrence_days)
    else:
        recurrence_parsed = None

    await update_task(session, task, title.strip(), due_at_parsed, recurrence_parsed, datetime.now())
    await session.commit()
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/done")
async def mark_done_route(
    task_id: int,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_admin),
):
    task = await get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задачу не знайдено")

    await mark_done(session, task, datetime.now())
    await session.commit()
    return RedirectResponse(url="/", status_code=303)


@router.post("/tasks/{task_id}/delete")
async def delete_task_route(
    task_id: int,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_admin),
):
    task = await get_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задачу не знайдено")

    await delete_task(session, task)
    await session.commit()
    return RedirectResponse(url="/", status_code=303)
