from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(AsyncAttrs, DeclarativeBase):
    pass


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    DONE = "done"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(Integer, index=True)

    title: Mapped[str] = mapped_column(String(500))
    status: Mapped[TaskStatus] = mapped_column(String(20), default=TaskStatus.PENDING)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Nagging state.
    reminder_interval_minutes: Mapped[int] = mapped_column(Integer, default=15)
    next_reminder_at: Mapped[datetime] = mapped_column(DateTime)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)

    def is_escalated(self, threshold: int) -> bool:
        return self.reminder_count >= threshold
