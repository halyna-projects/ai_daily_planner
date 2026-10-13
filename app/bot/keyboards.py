from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def reminder_callback_data(task_id: int, action: str) -> str:
    return f"task:{task_id}:{action}"


def parse_reminder_callback(data: str) -> tuple[int, str]:
    _, task_id, action = data.split(":")
    return int(task_id), action


def reminder_keyboard(task_id: int) -> InlineKeyboardMarkup:
    row1 = [
        InlineKeyboardButton(text="✅ Виконано", callback_data=reminder_callback_data(task_id, "done")),
        InlineKeyboardButton(text="⏳ Ще ні", callback_data=reminder_callback_data(task_id, "not_yet")),
        InlineKeyboardButton(text="🔁 Перенести", callback_data=reminder_callback_data(task_id, "snooze")),
    ]
    row2 = [
        InlineKeyboardButton(text="🗑 Видалити", callback_data=reminder_callback_data(task_id, "delete")),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2])


def delete_only_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """Used right after a task is created, and in the /tasks list -- a
    quick one-tap undo for typos or messages sent before you were done
    typing (no real "edit" yet: delete and resend the corrected text)."""

    buttons = [
        InlineKeyboardButton(text="🗑 Видалити", callback_data=reminder_callback_data(task_id, "delete")),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def clarify_due_date_keyboard(labels: list[str]) -> InlineKeyboardMarkup:
    """One button per date/time candidate found in an ambiguous message,
    asked instead of silently guessing which one is the actual reminder."""

    buttons = [
        [InlineKeyboardButton(text=label, callback_data=f"clarify:{i}")]
        for i, label in enumerate(labels)
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def parse_clarify_callback(data: str) -> int:
    return int(data.split(":")[1])
