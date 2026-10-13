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
    """Used in the /tasks list -- a quick one-tap undo for an older
    mistake (no real "edit" yet: delete and resend the corrected text)."""

    buttons = [
        InlineKeyboardButton(text="🗑 Видалити", callback_data=reminder_callback_data(task_id, "delete")),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def confirmation_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """Shown right after a task is created: delete (undo a typo) plus a
    one-tap way to start the next task's /new wizard without having to
    scroll up in the chat to find and retype the command."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Видалити", callback_data=reminder_callback_data(task_id, "delete"))],
            [InlineKeyboardButton(text="➕ Нова задача (покроково)", callback_data="wiz:new")],
        ]
    )


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
